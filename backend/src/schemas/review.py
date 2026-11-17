from pydantic import BaseModel, Field


class CaseCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    dataset_id: int | None = None
    # 直接粘贴样本时使用；与 dataset_id 二选一
    samples: list[dict] | None = None
    sample_limit: int = Field(default=40, ge=1, le=500)
    reviewer_a_id: int
    reviewer_b_id: int
    adjudicator_id: int


class ClaimInput(BaseModel):
    expected_seq: int = Field(default=0, ge=0)


class SubmitOpinion(BaseModel):
    expected_seq: int = Field(default=0, ge=0)
    # 样本键 -> 判定
    decisions: dict[str, dict]
    note: str = Field(default='', max_length=2000)


class ReturnInput(BaseModel):
    reason: str = Field(default='', max_length=500)


class ReassignInput(BaseModel):
    user_id: int
    reason: str = Field(default='', max_length=500)
