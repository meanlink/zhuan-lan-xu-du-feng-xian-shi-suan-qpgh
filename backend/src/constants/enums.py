from enum import Enum
class Role(str, Enum):
    admin = 'admin'
    analyst = 'analyst'
    reviewer = 'reviewer'
    viewer = 'viewer'
class JobStatus(str, Enum):
    queued = 'queued'
    running = 'running'
    completed = 'completed'
    failed = 'failed'
class CaseStatus(str, Enum):
    reviewing = 'reviewing'      # 双盲核标进行中
    adjudicating = 'adjudicating'  # 存在分歧，等待第三人裁定
    sealing = 'sealing'          # 封案写入中（中断可恢复）
    sealed = 'sealed'            # 已封案并生成训练批次
class AssignmentKind(str, Enum):
    review = 'review'            # 核标员独立判定
    adjudication = 'adjudication'  # 第三人裁定
class AssignmentStatus(str, Enum):
    pending = 'pending'          # 待领取 / 待处理
    submitted = 'submitted'      # 已交卷（意见保留）
    returned = 'returned'        # 未完任务已交回重派
class OpinionKind(str, Enum):
    review_a = 'review_a'
    review_b = 'review_b'
    adjudication = 'adjudication'
class AdoptBasis(str, Enum):
    review_a = 'review_a'              # 采用核标员 A 意见
    review_b = 'review_b'              # 采用核标员 B 意见
    adjudication = 'adjudication'      # 采用第三人裁定
