import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from src.config.database import get_db
from src.models import User, ReviewCase, ReviewAssignment, TrainingBatch, SealedRecord
from src.schemas.review import CaseCreate, ClaimInput, SubmitOpinion, ReturnInput, ReassignInput
from src.middlewares.auth import current_user, can_write, admin_only
from src.services import review
from src.utils.review_serial import case_dict, batch_dict, sealed_record_dict

router = APIRouter(prefix='/review')


@router.get('/users')
def users(db=Depends(get_db), u=Depends(can_write)):
    return [{'id': x.id, 'name': x.name, 'email': x.email, 'role': x.role}
            for x in db.scalars(select(User).order_by(User.id))]


@router.get('/cases')
def list_cases(status: str | None = None, db=Depends(get_db), u=Depends(current_user)):
    stmt = select(ReviewCase).order_by(ReviewCase.id.desc())
    if status:
        if status not in ('reviewing', 'adjudicating', 'sealing', 'sealed'):
            raise HTTPException(422, '未知案件状态')
        stmt = stmt.where(ReviewCase.status == status)
    return [case_dict(db, c, u, include_samples=False) for c in db.scalars(stmt.limit(100))]


@router.post('/cases', status_code=201)
def create_case(data: CaseCreate, db=Depends(get_db), u=Depends(can_write)):
    c = review.create_case(db, data, u)
    return case_dict(db, c, u)


@router.get('/cases/{id}')
def case_detail(id: int, db=Depends(get_db), u=Depends(current_user)):
    c = db.get(ReviewCase, id)
    if not c:
        raise HTTPException(404, '核标案不存在')
    return case_dict(db, c, u)


@router.get('/cases/{id}/readiness')
def readiness(id: int, db=Depends(get_db), u=Depends(current_user)):
    c = db.get(ReviewCase, id)
    if not c:
        raise HTTPException(404, '核标案不存在')
    return review.seal_readiness(db, c)


@router.get('/assignments/{id}')
def assignment_detail(id: int, db=Depends(get_db), u=Depends(current_user)):
    a = db.get(ReviewAssignment, id)
    if not a:
        raise HTTPException(404, '核标任务不存在')
    c = db.get(ReviewCase, a.case_id)
    payload = case_dict(db, c, u)
    assignment = next(x for x in payload['assignments'] if x['id'] == id)
    return {'case': payload, 'assignment': assignment}


@router.post('/assignments/{id}/claim')
def claim(id: int, data: ClaimInput, db=Depends(get_db), u=Depends(current_user)):
    a = review.claim(db, id, u, data.expected_seq)
    return {'id': a.id, 'status': a.status, 'claimed_seq': a.claimed_seq}


@router.post('/assignments/{id}/submit')
def submit(id: int, data: SubmitOpinion, db=Depends(get_db), u=Depends(current_user)):
    a = review.submit(db, id, u, data)
    return {'id': a.id, 'status': a.status}


@router.post('/assignments/{id}/return')
def return_assignment(id: int, data: ReturnInput, db=Depends(get_db), u=Depends(current_user)):
    a = review.return_assignment(db, id, u, data.reason)
    return {'id': a.id, 'status': a.status, 'claimed_seq': a.claimed_seq}


@router.post('/assignments/{id}/reassign')
def reassign(id: int, data: ReassignInput, db=Depends(get_db), u=Depends(admin_only)):
    a = review.reassign(db, id, u, data.user_id, data.reason)
    return {'id': a.id, 'status': a.status, 'assignee_id': a.assignee_id,
            'claimed_seq': a.claimed_seq}


@router.post('/cases/{id}/seal')
def seal(id: int, db=Depends(get_db), u=Depends(admin_only)):
    batch = review.seal_case(db, id, u)
    return batch_dict(batch)


@router.get('/batches')
def batches(db=Depends(get_db), u=Depends(current_user)):
    return [batch_dict(b) for b in db.scalars(
        select(TrainingBatch).order_by(TrainingBatch.id.desc()))]


@router.get('/batches/{id}')
def batch_detail(id: int, db=Depends(get_db), u=Depends(current_user)):
    b = db.get(TrainingBatch, id)
    if not b:
        raise HTTPException(404, '训练批次不存在')
    records = db.scalars(select(SealedRecord).where(SealedRecord.batch_id == id)
                         .order_by(SealedRecord.id)).all()
    return {**batch_dict(b), 'records': [sealed_record_dict(r) for r in records]}


@router.get('/batches/{id}/download')
def batch_download(id: int, format: str = 'json', db=Depends(get_db),
                   u=Depends(current_user)):
    b = db.get(TrainingBatch, id)
    if not b:
        raise HTTPException(404, '训练批次不存在')
    if format not in ('csv', 'json'):
        raise HTTPException(422, '支持 CSV 或 JSON')
    records = db.scalars(select(SealedRecord).where(SealedRecord.batch_id == id)
                         .order_by(SealedRecord.id)).all()
    payload = [sealed_record_dict(r) for r in records]
    if format == 'json':
        content = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        media = 'application/json; charset=utf-8'
        filename = f'training-batch-{id}.json'
    else:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['sample_key', 'final_label', 'basis', 'source_opinion_id', 'sample'])
        for r in payload:
            writer.writerow([r['sample_key'], r['final_label'], r['basis'],
                             r['source_opinion_id'],
                             json.dumps(r['sample'], ensure_ascii=False)])
        content = buf.getvalue()
        media = 'text/csv; charset=utf-8'
        filename = f'training-batch-{id}.csv'
    return StreamingResponse(io.BytesIO(content.encode('utf-8')), media_type=media,
                             headers={'Content-Disposition': f'attachment; filename="{filename}"'})
