from sqlalchemy import String, Double, ForeignKey, JSON, UniqueConstraint, Integer
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class TrainingBatch(Base):
    """封案后生成的训练批次；重试不重复建批。"""
    __tablename__ = 'training_batches'
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey('review_cases.id'), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str] = mapped_column(String(64), default='')
    created_at: Mapped[float] = mapped_column(Double)
    sealed_by: Mapped[int] = mapped_column(ForeignKey('users.id'))


class SealedRecord(Base):
    """封案定案的每条样本：最终标签与采用依据。"""
    __tablename__ = 'sealed_records'
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey('training_batches.id'))
    case_id: Mapped[int] = mapped_column(ForeignKey('review_cases.id'))
    sample_key: Mapped[str] = mapped_column(String(120))
    sample: Mapped[dict] = mapped_column(JSON, default=dict)
    final_label: Mapped[int] = mapped_column(Integer)
    basis: Mapped[str] = mapped_column(String(20))        # review_a/review_b/adjudication
    source_opinion_id: Mapped[int] = mapped_column(ForeignKey('review_opinions.id'))
    __table_args__ = (UniqueConstraint('case_id', 'sample_key', name='uq_sealed_case_sample'),)
