from sqlalchemy import select
from src.models import ReviewCase, ReviewAssignment, ReviewOpinion, TrainingBatch, SealedRecord, User


def _user_ref(db, uid):
    u = db.get(User, uid)
    return {'id': uid, 'name': u.name if u else f'用户#{uid}',
            'email': u.email if u else ''}


def _my_slot(items, user):
    for a in items:
        if a.assignee_id == user.id:
            return a.slot
    return None


def case_dict(db, case: ReviewCase, user, *, include_samples=True):
    items = list(db.scalars(select(ReviewAssignment)
                            .where(ReviewAssignment.case_id == case.id).order_by(ReviewAssignment.id)))
    latest = {}
    for op in db.scalars(select(ReviewOpinion).where(ReviewOpinion.case_id == case.id)):
        cur = latest.get(op.slot)
        if cur is None or op.version > cur.version:
            latest[op.slot] = op
    my_slot = _my_slot(items, user)

    def assignment_dict(a: ReviewAssignment):
        # 双盲：只能看到自己 slot 的意见；对席仅显示状态，看不到判定内容
        own = a.assignee_id == user.id
        op = latest.get(a.slot)
        show_opinion = own or (user.role == 'admin')
        return {
            'id': a.id, 'kind': a.kind, 'slot': a.slot,
            'assignee': _user_ref(db, a.assignee_id) if a.assignee_id else None,
            'status': a.status, 'claimed_seq': a.claimed_seq,
            'claimed_at': a.claimed_at, 'submitted_at': a.submitted_at,
            'returned_at': a.returned_at,
            'mine': own,
            'opinion': (
                {'version': op.version, 'decisions': op.decisions, 'author_id': op.author_id,
                 'created_at': op.created_at}
                if (op and show_opinion) else None
            ),
            'opinion_submitted': op is not None and a.status == 'submitted',
        }

    data = {
        'id': case.id, 'name': case.name, 'status': case.status,
        'disagreement_count': case.disagreement_count,
        'created_by': _user_ref(db, case.created_by),
        'reviewer_a': _user_ref(db, case.reviewer_a_id),
        'reviewer_b': _user_ref(db, case.reviewer_b_id),
        'adjudicator': _user_ref(db, case.adjudicator_id),
        'sample_count': len(case.sample_snapshot),
        'sealed_at': case.sealed_at, 'created_at': case.created_at,
        'my_slot': my_slot,
        'assignments': [assignment_dict(a) for a in items],
    }
    if include_samples:
        # 双盲：核标员只看到自己已交意见，看不到对席判定；裁定人在分歧态看到双方意见
        data['samples'] = _sample_view(db, case, items, latest, user)
    return data


def _sample_view(db, case, items, latest, user):
    op_a, op_b = latest.get('review_a'), latest.get('review_b')
    op_adj = latest.get('adjudication')
    my_slot = _my_slot(items, user)
    is_adjudicator = case.adjudicator_id == user.id
    reviews_submitted = all(
        a.status == 'submitted' for a in items if a.kind == 'review')
    # 裁定人仅在两份核标都交卷后才能看到双方意见（此前保持双盲）
    can_see_both = user.role == 'admin' or (is_adjudicator and reviews_submitted)
    rows = []
    for s in case.sample_snapshot:
        key = str(s['reader_id'])
        row = {'reader_id': key, 'renewed': s.get('renewed'),
               'features': {k: v for k, v in s.items() if k not in ('reader_id', 'renewed')}}
        if op_a and (can_see_both or my_slot == 'review_a'):
            row['label_a'] = op_a.decisions[key]['label']
            row['note_a'] = op_a.decisions[key].get('note', '')
        if op_b and (can_see_both or my_slot == 'review_b'):
            row['label_b'] = op_b.decisions[key]['label']
            row['note_b'] = op_b.decisions[key].get('note', '')
        if can_see_both and op_a and op_b:
            row['disagree'] = op_a.decisions[key]['label'] != op_b.decisions[key]['label']
        if op_adj and can_see_both and key in op_adj.decisions:
            row['label_adj'] = op_adj.decisions[key]['label']
        rows.append(row)
    return rows


def batch_dict(b: TrainingBatch):
    return {'id': b.id, 'case_id': b.case_id, 'name': b.name,
            'record_count': b.record_count, 'checksum': b.checksum,
            'created_at': b.created_at, 'sealed_by': b.sealed_by}


def sealed_record_dict(r: SealedRecord):
    return {'id': r.id, 'batch_id': r.batch_id, 'case_id': r.case_id,
            'sample_key': r.sample_key, 'sample': r.sample,
            'final_label': r.final_label, 'basis': r.basis,
            'source_opinion_id': r.source_opinion_id}
