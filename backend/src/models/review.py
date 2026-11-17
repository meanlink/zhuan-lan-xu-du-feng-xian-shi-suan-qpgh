from sqlalchemy import String, Double, ForeignKey, JSON, UniqueConstraint, Integer
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class ReviewCase(Base):
    """双盲核标案：固定样本，两名核标员独立判定，分歧交第三人裁定。"""
    __tablename__ = 'review_cases'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default='reviewing')
    # 固定样本快照（不可变），及填报人（不参与该案核标）
    sample_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    source_dataset_id: Mapped[int | None] = mapped_column(ForeignKey('datasets.id'), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey('users.id'))
    reviewer_a_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    reviewer_b_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    adjudicator_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    # 封案时快照各样本最终采用的意见 ID，封案与交卷相撞不混用两版意见
    sealed_opinion_ids: Mapped[dict] = mapped_column(JSON, default=dict)
    disagreement_count: Mapped[int] = mapped_column(Integer, default=0)
    sealed_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    created_at: Mapped[float] = mapped_column(Double)


class ReviewAssignment(Base):
    """案件下的可领取任务：两条核标任务 + 一条裁定任务。"""
    __tablename__ = 'review_assignments'
    __table_args__ = (UniqueConstraint('case_id', 'slot', name='uq_assignment_case_slot'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey('review_cases.id'))
    kind: Mapped[str] = mapped_column(String(20))           # review / adjudication
    slot: Mapped[str] = mapped_column(String(20))           # review_a / review_b / adjudication
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='pending')  # pending/submitted/returned
    claimed_seq: Mapped[int] = mapped_column(Integer, default=0)        # 领取序号，迟交拒绝的并发凭据
    claimed_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    submitted_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    returned_at: Mapped[float | None] = mapped_column(Double, nullable=True)


class ReviewOpinion(Base):
    """不可变意见：每次领取后交卷新增一行；交回保留旧意见，交卷以先落定者为准。"""
    __tablename__ = 'review_opinions'
    __table_args__ = (UniqueConstraint('assignment_id', 'version', name='uq_opinion_assignment_version'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey('review_cases.id'))
    assignment_id: Mapped[int] = mapped_column(ForeignKey('review_assignments.id'))
    slot: Mapped[str] = mapped_column(String(20))
    author_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    version: Mapped[int] = mapped_column(Integer, default=1)
    # {sample_key: {"label": 0/1, "note": "..."}}
    decisions: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Double)
