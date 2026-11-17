"""双盲核标领域服务。

关键规则：
- 固定样本，两名核标员各自独立判定、互不可见；分歧由第三人裁定；填报人不参与该案。
- 未完任务可交回重派，已交意见保留；交回与交卷并发以先落定者为准，旧领取的迟交拒绝。
- 全部读者定案后才能封案；缺裁定不开放试算（封案前不生成训练批次）。
- 封案写入中断可恢复未完读者，重试不重复建批；封案与交卷相撞不混用两版意见。

并发策略：每案件一把进程内互斥锁串行化同案写操作（交回/交卷/封案互斥），
同时对案件与任务行使用 SELECT ... FOR UPDATE（InnoDB 下跨进程/跨事务生效）；
状态判定一律基于锁内重读的任务行，保证先落定者生效、后者被拒绝。
"""
import threading
import time

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.models import (
    Dataset, User, ReviewCase, ReviewAssignment, ReviewOpinion,
    TrainingBatch, SealedRecord,
)
from src.services.audit import record
from src.utils.serialization import checksum

REVIEW_SLOTS = ('review_a', 'review_b')
ALL_SLOTS = ('review_a', 'review_b', 'adjudication')
LABEL_VALUES = (0, 1)

_case_locks: dict[int, threading.RLock] = {}
_locks_guard = threading.Lock()


def case_mutex(case_id: int) -> threading.RLock:
    """返回该案件的进程内互斥锁（同一把 RLock 可重入，供显式 acquire/release）。"""
    with _locks_guard:
        lock = _case_locks.get(case_id)
        if lock is None:
            lock = threading.RLock()
            _case_locks[case_id] = lock
    return lock


# ---------- 内部工具 ----------

def _lock_case(db, case_id: int) -> ReviewCase:
    """行级锁取案件，串行化交卷/交回/封案的并发冲突。"""
    case = db.scalar(select(ReviewCase).where(ReviewCase.id == case_id).with_for_update())
    if case is None:
        raise HTTPException(404, '核标案不存在')
    return case


def _enter_case_lock(db, case_id: int):
    """获取案件互斥锁并使本会话缓存失效，保证锁内读到的是先落定事务的最新状态。"""
    lock = case_mutex(case_id)
    lock.acquire()
    db.expire_all()
    return lock


def _lock_assignment(db, assignment_id: int) -> ReviewAssignment:
    a = db.scalar(select(ReviewAssignment)
                  .where(ReviewAssignment.id == assignment_id).with_for_update())
    if a is None:
        raise HTTPException(404, '核标任务不存在')
    return a


def _assignments(db, case_id: int) -> list[ReviewAssignment]:
    return list(db.scalars(
        select(ReviewAssignment).where(ReviewAssignment.case_id == case_id).order_by(ReviewAssignment.id)
    ))


def _latest_opinions(db, case_id: int) -> dict[str, ReviewOpinion]:
    """每个 slot 当前生效（最新版本）的意见。"""
    rows = list(db.scalars(select(ReviewOpinion).where(ReviewOpinion.case_id == case_id)))
    latest: dict[str, ReviewOpinion] = {}
    for op in rows:
        cur = latest.get(op.slot)
        if cur is None or op.version > cur.version:
            latest[op.slot] = op
    return latest


def _recompute_case(db, case: ReviewCase, items: list[ReviewAssignment]) -> None:
    """两份核标交卷后判定分歧；有分歧进入待裁定，否则回到核标完成态等待封案。"""
    reviews = [a for a in items if a.kind == 'review']
    if not all(a.status == 'submitted' for a in reviews):
        case.status = 'reviewing'
        case.disagreement_count = 0
        return
    latest = _latest_opinions(db, case.id)
    op_a, op_b = latest.get('review_a'), latest.get('review_b')
    keys = [str(s['reader_id']) for s in case.sample_snapshot]
    disagree = [k for k in keys if op_a.decisions[k]['label'] != op_b.decisions[k]['label']]
    case.disagreement_count = len(disagree)
    case.status = 'adjudicating' if disagree else 'reviewing'


def _validate_label(raw):
    try:
        label = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(422, '判定标签只能是 0 或 1')
    if label not in LABEL_VALUES:
        raise HTTPException(422, '判定标签只能是 0 或 1')
    return label


# ---------- 建案 ----------

def create_case(db, data, user: User) -> ReviewCase:
    # 固定样本：来自既有数据集或直接粘贴
    if data.dataset_id:
        dataset = db.get(Dataset, data.dataset_id)
        if dataset is None:
            raise HTTPException(404, '数据批次不存在')
        samples = list(dataset.records)[:data.sample_limit]
        source_dataset_id = dataset.id
    elif data.samples:
        samples = data.samples[:data.sample_limit]
        source_dataset_id = None
    else:
        raise HTTPException(422, '请选择数据批次或粘贴固定样本')
    if not samples:
        raise HTTPException(422, '固定样本不能为空')
    seen = set()
    for idx, row in enumerate(samples):
        if 'reader_id' not in row or row['reader_id'] in (None, ''):
            raise HTTPException(422, f'第 {idx + 1} 条样本缺少 reader_id')
        key = str(row['reader_id'])
        if key in seen:
            raise HTTPException(422, f'样本 reader_id 重复：{key}')
        seen.add(key)
        if 'renewed' not in row:
            raise HTTPException(422, f'样本 {key} 缺少续读标签 renewed')
        row['renewed'] = _validate_label(row['renewed'])

    role_ids = {data.reviewer_a_id, data.reviewer_b_id, data.adjudicator_id}
    if len(role_ids) != 3:
        raise HTTPException(422, '两名核标员与裁定人必须为三个不同账号')
    if user.id in role_ids:
        raise HTTPException(422, '填报人不能参与该案核标或裁定')
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(role_ids)))}
    if len(users) != 3:
        raise HTTPException(404, '指定的核标员或裁定人不存在')
    for uid in (data.reviewer_a_id, data.reviewer_b_id, data.adjudicator_id):
        if users[uid].role == 'viewer':
            raise HTTPException(422, '观察员账号不能担任核标或裁定角色')
    if db.scalar(select(ReviewCase).where(ReviewCase.name == data.name.strip())):
        raise HTTPException(409, '核标案名称已存在')

    case = ReviewCase(
        name=data.name.strip(), status='reviewing', sample_snapshot=samples,
        source_dataset_id=source_dataset_id, created_by=user.id,
        reviewer_a_id=data.reviewer_a_id, reviewer_b_id=data.reviewer_b_id,
        adjudicator_id=data.adjudicator_id, created_at=time.time(),
    )
    db.add(case)
    db.flush()
    for slot in ALL_SLOTS:
        kind = 'adjudication' if slot == 'adjudication' else 'review'
        assignee = data.adjudicator_id if kind == 'adjudication' else (
            data.reviewer_a_id if slot == 'review_a' else data.reviewer_b_id)
        db.add(ReviewAssignment(
            case_id=case.id, kind=kind, slot=slot, assignee_id=assignee,
            status='pending', claimed_seq=0,
        ))
    db.flush()
    record(db, user.email, 'review.case_create',
           {'id': case.id, 'samples': len(samples)})
    db.commit()
    return case


# ---------- 领取 / 交卷 / 交回 / 重派 ----------

def claim(db, assignment_id: int, user: User, expected_seq: int) -> ReviewAssignment:
    preview = db.get(ReviewAssignment, assignment_id)
    if preview is None:
        raise HTTPException(404, '核标任务不存在')
    lock = _enter_case_lock(db, preview.case_id)
    try:
        case = _lock_case(db, preview.case_id)
        a = _lock_assignment(db, assignment_id)  # 锁内重读，避免陈旧状态
        if case.status in ('sealing', 'sealed'):
            raise HTTPException(409, '案件已封案，不能再领取任务')
        if a.assignee_id != user.id:
            raise HTTPException(403, '该任务未分派给你，不能领取')
        if a.status == 'submitted':
            raise HTTPException(409, '任务已交卷，无需重复领取')
        if expected_seq and expected_seq != a.claimed_seq:
            raise HTTPException(409, '任务分派已变更，请刷新后重试')
        if a.status == 'pending':
            a.claimed_seq += 1  # 领取凭据；交回/重派都会再前进，迟交据此拒绝
            a.claimed_at = time.time()
        db.flush()
        record(db, user.email, 'review.claim', {'assignment': a.id, 'seq': a.claimed_seq})
        db.commit()
        return a
    finally:
        lock.release()


def submit(db, assignment_id: int, user: User, payload) -> ReviewAssignment:
    preview = db.get(ReviewAssignment, assignment_id)
    if preview is None:
        raise HTTPException(404, '核标任务不存在')
    lock = _enter_case_lock(db, preview.case_id)
    try:
        case = _lock_case(db, preview.case_id)  # 与封案/交回互斥，先落定者生效
        a = _lock_assignment(db, assignment_id)
        if case.status in ('sealing', 'sealed'):
            raise HTTPException(409, '案件封案中或已封案，交卷已拒绝')
        if a.assignee_id != user.id:
            raise HTTPException(403, '该任务未分派给你，不能交卷')
        if a.status == 'returned':
            raise HTTPException(409, '任务已交回重派，旧领取的迟交拒绝')
        if a.status == 'submitted':
            raise HTTPException(409, '任务已交卷，意见已保留，不能重复提交；如需更正请交回重派')
        if payload.expected_seq and payload.expected_seq != a.claimed_seq:
            raise HTTPException(409, '领取序号已变化（任务已交回或重派），旧领取的迟交拒绝')

        keys = [str(s['reader_id']) for s in case.sample_snapshot]
        decisions: dict[str, dict] = {}
        if not isinstance(payload.decisions, dict) or not payload.decisions:
            raise HTTPException(422, '请先逐条判定再交卷')
        if a.kind == 'adjudication':
            # 第三人只裁定分歧样本；无分歧时无需裁定
            latest_now = _latest_opinions(db, case.id)
            op_a, op_b = latest_now.get('review_a'), latest_now.get('review_b')
            if not op_a or not op_b:
                raise HTTPException(409, '两份核标意见未齐备，尚不能裁定')
            required = [k for k in keys
                        if op_a.decisions[k]['label'] != op_b.decisions[k]['label']]
            if not required:
                raise HTTPException(409, '两份核标意见一致，无需第三人裁定')
        else:
            required = keys
        for k in required:
            raw = payload.decisions.get(k)
            if raw is None or 'label' not in raw:
                raise HTTPException(422, f'样本 {k} 缺少判定，交卷需覆盖全部待判定样本')
            decisions[k] = {'label': _validate_label(raw['label']),
                            'note': str(raw.get('note', ''))[:500]}
        extra = set(payload.decisions) - set(required)
        if extra:
            raise HTTPException(422, f'存在不属于本次判定范围的样本：{sorted(extra)[:3]}')

        last = db.scalar(select(ReviewOpinion)
                         .where(ReviewOpinion.assignment_id == a.id)
                         .order_by(ReviewOpinion.version.desc()))
        version = (last.version + 1) if last else 1
        op = ReviewOpinion(
            case_id=case.id, assignment_id=a.id, slot=a.slot, author_id=user.id,
            version=version, decisions=decisions, created_at=time.time(),
        )
        db.add(op)
        db.flush()
        a.status = 'submitted'
        a.submitted_at = time.time()
        items = _assignments(db, case.id)
        if a.kind == 'review':
            _recompute_case(db, case, items)
        else:
            # 裁定交卷后，核标齐备即具备封案条件，状态回到核标完成态
            case.status = 'reviewing'
        db.flush()
        record(db, user.email, 'review.submit',
               {'assignment': a.id, 'slot': a.slot, 'seq': payload.expected_seq})
        db.commit()
        return a
    finally:
        lock.release()


def return_assignment(db, assignment_id: int, user: User, reason: str) -> ReviewAssignment:
    preview = db.get(ReviewAssignment, assignment_id)
    if preview is None:
        raise HTTPException(404, '核标任务不存在')
    lock = _enter_case_lock(db, preview.case_id)
    try:
        case = _lock_case(db, preview.case_id)
        a = _lock_assignment(db, assignment_id)
        if case.status in ('sealing', 'sealed'):
            raise HTTPException(409, '案件已封案，不能交回任务')
        if a.assignee_id != user.id and user.role != 'admin':
            raise HTTPException(403, '仅任务本人或负责人可以交回任务')
        if a.status == 'submitted':
            raise HTTPException(409, '已交卷任务不能交回；已交意见会保留')
        if a.status == 'returned':
            raise HTTPException(409, '任务已在交回状态')
        a.status = 'returned'
        a.returned_at = time.time()
        a.claimed_seq += 1  # 使旧领取凭据失效，迟交拒绝
        db.flush()
        record(db, user.email, 'review.return',
               {'assignment': a.id, 'reason': reason})
        db.commit()
        return a
    finally:
        lock.release()


def reassign(db, assignment_id: int, admin: User, user_id: int, reason: str) -> ReviewAssignment:
    preview = db.get(ReviewAssignment, assignment_id)
    if preview is None:
        raise HTTPException(404, '核标任务不存在')
    lock = _enter_case_lock(db, preview.case_id)
    try:
        case = _lock_case(db, preview.case_id)
        a = _lock_assignment(db, assignment_id)
        if case.status in ('sealing', 'sealed'):
            raise HTTPException(409, '案件已封案，不能重新分派')
        if a.kind != 'review':
            raise HTTPException(422, '裁定任务固定由裁定人负责，不能改派')
        if a.status == 'submitted':
            raise HTTPException(409, '任务已交卷，意见保留，不能改派；请先由本人交回未完任务')
        target = db.get(User, user_id)
        if target is None:
            raise HTTPException(404, '目标核标员不存在')
        if target.role == 'viewer':
            raise HTTPException(422, '观察员账号不能担任核标员')
        forbidden = {case.created_by, case.reviewer_a_id, case.reviewer_b_id, case.adjudicator_id}
        forbidden.discard(a.assignee_id)
        if target.id in forbidden:
            raise HTTPException(422, '填报人、对席核标员与裁定人不能接管该任务')
        a.assignee_id = target.id
        a.status = 'pending'
        a.claimed_seq += 1
        a.claimed_at = None
        a.returned_at = time.time()
        db.flush()
        record(db, admin.email, 'review.reassign',
               {'assignment': a.id, 'new_user': target.id, 'reason': reason})
        db.commit()
        return a
    finally:
        lock.release()


# ---------- 封案 ----------

def seal_readiness(db, case: ReviewCase) -> dict:
    items = _assignments(db, case.id)
    reviews = [a for a in items if a.kind == 'review']
    missing_review = [a.slot for a in reviews if a.status != 'submitted']
    latest = _latest_opinions(db, case.id)
    op_a, op_b = latest.get('review_a'), latest.get('review_b')
    disagreement_keys = []
    if op_a and op_b:
        disagreement_keys = [str(s['reader_id']) for s in case.sample_snapshot
                             if op_a.decisions[str(s['reader_id'])]['label']
                             != op_b.decisions[str(s['reader_id'])]['label']]
    adj = next(a for a in items if a.kind == 'adjudication')
    missing_adj = bool(disagreement_keys) and adj.status != 'submitted'
    ready = not missing_review and not missing_adj
    return {
        'ready': ready,
        'missing_review_slots': missing_review,
        'disagreement_count': len(disagreement_keys),
        'adjudication_status': adj.status,
        'missing_adjudication': missing_adj,
        'blockers': (
            [f'核标任务尚未交卷：{", ".join(missing_review)}'] if missing_review else []
        ) + (['存在分歧但裁定意见缺失，不开放试算'] if missing_adj else []),
    }


def seal_case(db, case_id: int, admin: User) -> TrainingBatch:
    preview = db.get(ReviewCase, case_id)
    if preview is None:
        raise HTTPException(404, '核标案不存在')
    lock = _enter_case_lock(db, case_id)
    try:
        case = _lock_case(db, case_id)
        if case.status == 'sealed':
            batch = db.scalar(select(TrainingBatch).where(TrainingBatch.case_id == case.id))
            if batch is not None:
                return batch  # 重试不重复建批
            raise HTTPException(409, '案件已定案但批次缺失，请重试封案恢复')

        readiness = seal_readiness(db, case)
        if not readiness['ready']:
            raise HTTPException(409, '封案条件未满足：' + '；'.join(readiness['blockers']))

        case.status = 'sealing'
        db.flush()
        # 先落批次主记录并提交，保证中断后可凭 case_id 恢复、不重复建批
        batch = db.scalar(select(TrainingBatch).where(TrainingBatch.case_id == case.id))
        if batch is None:
            batch = TrainingBatch(case_id=case.id, name=f'{case.name} · 训练批次',
                                  record_count=0, created_at=time.time(), sealed_by=admin.id)
            db.add(batch)
            db.flush()
        record(db, admin.email, 'review.seal_start', {'case': case.id, 'batch': batch.id})
        db.commit()  # 批次主记录先持久化；中断后凭 case_id 恢复，不重复建批

        items = _assignments(db, case.id)
        latest = _latest_opinions(db, case.id)
        op_a, op_b = latest['review_a'], latest['review_b']
        op_adj = latest.get('adjudication')
        adj = next(a for a in items if a.kind == 'adjudication')
        adj_submitted = adj.status == 'submitted'

        existing = {r.sample_key: r for r in db.scalars(
            select(SealedRecord).where(SealedRecord.case_id == case.id))}
        sealed_opinion_ids = dict(case.sealed_opinion_ids or {})
        rows = []
        for sample in case.sample_snapshot:
            key = str(sample['reader_id'])
            la = op_a.decisions[key]['label']
            lb = op_b.decisions[key]['label']
            if la == lb:
                basis, source_op, final_label = 'review_a', op_a, la
            else:
                if not adj_submitted or op_adj is None or key not in op_adj.decisions:
                    # 封案写入中途出现缺裁定：保持 sealing，保留已写读者，等待恢复重试
                    db.commit()
                    raise HTTPException(409, f'分歧样本 {key} 缺裁定，封案暂停；补齐裁定后可重试恢复')
                basis, source_op = 'adjudication', op_adj
                final_label = op_adj.decisions[key]['label']
            sealed_opinion_ids[key] = source_op.id
            if key in existing:
                continue
            rows.append(SealedRecord(
                batch_id=batch.id, case_id=case.id, sample_key=key, sample=sample,
                final_label=final_label, basis=basis, source_opinion_id=source_op.id,
            ))
        # 分块写入，中断只丢失当前事务，已落读者不重复写（唯一约束兜底）
        try:
            for i in range(0, len(rows), 100):
                db.add_all(rows[i:i + 100])
                db.flush()
            case.sealed_opinion_ids = sealed_opinion_ids
            batch.record_count = len(case.sample_snapshot)
            batch.checksum = checksum([
                {'sample_key': k, 'opinion': sealed_opinion_ids[k]} for k in sorted(sealed_opinion_ids)
            ])
            case.status = 'sealed'
            case.sealed_at = time.time()
            record(db, admin.email, 'review.seal_complete',
                   {'case': case.id, 'batch': batch.id, 'records': len(case.sample_snapshot)})
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, '封案写入冲突，请重试恢复未完成读者')
        return batch
    finally:
        lock.release()
