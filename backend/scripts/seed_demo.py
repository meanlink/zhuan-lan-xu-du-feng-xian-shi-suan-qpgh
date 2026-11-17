import time, json
from sqlalchemy import select, func
from src.config.database import Session
from migrations.initial import migrate
from src.models import User, Dataset, Job, Report, Delivery, Audit, ReviewCase, ReviewAssignment, ReviewOpinion, TrainingBatch
from src.services.business import metadata, seed_records, analyze
from src.services.reports import deliver
from src.services.review import seal_case
from src.utils.security import hash_password
from src.utils.serialization import checksum
def seed():
    migrate()
    with Session() as db:
        for role,name in [('admin','林知 · 业务负责人'),('analyst','陈舟 · 分析员'),('viewer','周禾 · 观察员')]:
            email=role+'@demo.local'
            if not db.scalar(select(User).where(User.email==email)):
                db.add(User(email=email,name=name,role=role,password=hash_password('Demo123!')))
        for email,name in [('reviewer1@demo.local','沈砚 · 核标员甲'),('reviewer2@demo.local','韩尺 · 核标员乙')]:
            if not db.scalar(select(User).where(User.email==email)):
                db.add(User(email=email,name=name,role='reviewer',password=hash_password('Demo123!')))
        db.flush()
        m=metadata()
        d=db.scalar(select(Dataset).where(Dataset.name==m['dataset_name']))
        if not d:
            rows=seed_records()
            d=Dataset(name=m['dataset_name'],source=m['short']+'-202611.csv',records=rows,checksum=checksum(rows),created_at=time.time())
            db.add(d); db.flush()
        if not db.scalar(select(Job).where(Job.name=='基线复核 · '+m['name'])):
            params={p['key']:p['default'] for p in m.get('parameters',[])}
            result=analyze(d.records,params)
            json.dumps(result,ensure_ascii=False,allow_nan=False)
            admin=db.scalar(select(User).where(User.role=='admin'))
            j=Job(name='基线复核 · '+m['name'],dataset_id=d.id,params=params,status='completed',result=result,created_by=admin.id,created_at=time.time()-3600,finished_at=time.time()-3595,approved=True)
            db.add(j);db.flush()
            r=Report(name='每日业务复核简报',job_id=j.id,destination='业务复核组 · 本地收件箱',interval_seconds=86400,next_run=time.time()+86400,enabled=True)
            db.add(r);db.flush();deliver(db,r)
            db.add(Audit(actor='seed',action='demo.baseline',detail={'dataset':d.id},at=time.time()))
        _seed_review_cases(db, d)
        db.commit()
        models=[User,Dataset,Job,Report,Delivery,Audit,ReviewCase,ReviewAssignment,ReviewOpinion,TrainingBatch]
        counts={model.__tablename__:db.scalar(select(func.count()).select_from(model)) for model in models}
        print(json.dumps(counts,ensure_ascii=False))
        return counts

def _seed_review_cases(db, dataset):
    analyst=db.scalar(select(User).where(User.email=='analyst@demo.local'))
    admin=db.scalar(select(User).where(User.role=='admin'))
    r1=db.scalar(select(User).where(User.email=='reviewer1@demo.local'))
    r2=db.scalar(select(User).where(User.email=='reviewer2@demo.local'))
    now=time.time()
    # 案件一：双盲进行中，A 已交卷、B 待领取，含一条预置分歧待演示
    name1='续读标签双盲核标 · 11月第1批'
    c1=db.scalar(select(ReviewCase).where(ReviewCase.name==name1))
    if not c1:
        samples=dataset.records[:12]
        c1=ReviewCase(name=name1,status='reviewing',sample_snapshot=samples,source_dataset_id=dataset.id,
                      created_by=analyst.id,reviewer_a_id=r1.id,reviewer_b_id=r2.id,
                      adjudicator_id=admin.id,created_at=now-1800)
        db.add(c1);db.flush()
        slots=[('review','review_a',r1.id),('review','review_b',r2.id),('adjudication','adjudication',admin.id)]
        for kind,slot,uid in slots:
            db.add(ReviewAssignment(case_id=c1.id,kind=kind,slot=slot,assignee_id=uid,status='pending',claimed_seq=0))
        db.flush()
        items={a.slot:a for a in db.scalars(select(ReviewAssignment).where(ReviewAssignment.case_id==c1.id))}
        a=items['review_a'];a.status='submitted';a.claimed_seq=1;a.claimed_at=now-1700;a.submitted_at=now-1200
        decisions={str(s['reader_id']):{'label':int(s['renewed']),'note':'初判'} for s in samples}
        # 首条样本故意与原标签相反，制造与 B 的潜在分歧
        first=str(samples[0]['reader_id'])
        decisions[first]={'label':1-int(samples[0]['renewed']),'note':'存疑，行为窗口边界样本'}
        db.add(ReviewOpinion(case_id=c1.id,assignment_id=a.id,slot='review_a',author_id=r1.id,
                             version=1,decisions=decisions,created_at=now-1200))
        db.add(Audit(actor='seed',action='demo.review_case',detail={'id':c1.id},at=now))
    # 案件二：证据齐备并完成封案，产出训练批次，演示全流程终态
    name2='续读标签双盲核标 · 10月封档批'
    c2=db.scalar(select(ReviewCase).where(ReviewCase.name==name2))
    if not c2:
        samples=dataset.records[12:24]
        c2=ReviewCase(name=name2,status='reviewing',sample_snapshot=samples,source_dataset_id=dataset.id,
                      created_by=analyst.id,reviewer_a_id=r1.id,reviewer_b_id=r2.id,
                      adjudicator_id=admin.id,created_at=now-7200)
        db.add(c2);db.flush()
        for kind,slot,uid in [('review','review_a',r1.id),('review','review_b',r2.id),('adjudication','adjudication',admin.id)]:
            db.add(ReviewAssignment(case_id=c2.id,kind=kind,slot=slot,assignee_id=uid,status='pending',claimed_seq=0))
        db.flush()
        items={a.slot:a for a in db.scalars(select(ReviewAssignment).where(ReviewAssignment.case_id==c2.id))}
        common={str(s['reader_id']):{'label':int(s['renewed']),'note':'一致'} for s in samples}
        disagree_key=str(samples[1]['reader_id'])
        dec_a=dict(common);dec_a[disagree_key]={'label':1-int(samples[1]['renewed']),'note':'判为异常'}
        dec_b=dict(common)
        for slot,author_id,dec in [('review_a',r1.id,dec_a),('review_b',r2.id,dec_b)]:
            a=items[slot];a.status='submitted';a.claimed_seq=1;a.claimed_at=now-7000;a.submitted_at=now-6000
            db.add(ReviewOpinion(case_id=c2.id,assignment_id=a.id,slot=slot,author_id=author_id,
                                 version=1,decisions=dec,created_at=now-6000))
        adj=items['adjudication'];adj.status='submitted';adj.claimed_seq=1;adj.claimed_at=now-5900;adj.submitted_at=now-5400
        adj_dec={disagree_key:{'label':int(samples[1]['renewed']),'note':'裁定维持原标签'}}
        db.add(ReviewOpinion(case_id=c2.id,assignment_id=adj.id,slot='adjudication',author_id=admin.id,
                             version=1,decisions=adj_dec,created_at=now-5400))
        db.flush()
        seal_case(db,c2.id,admin)
        db.add(Audit(actor='seed',action='demo.review_sealed',detail={'id':c2.id},at=now))
if __name__=='__main__':seed()
