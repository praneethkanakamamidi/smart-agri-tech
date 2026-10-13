from pydantic import BaseModel, Field
from typing import Optional, Literal

DisputeReason = Literal[
    "quality_issue", "quantity_mismatch", "incorrect_product", "late_delivery", "not_delivered",
    "damaged_produce", "payment_issue", "refund_disagreement", "misrepresentation", "unresolved_cancellation", "other",
]


class RaiseDisputeSchema(BaseModel):
    order_id: int
    reason: DisputeReason
    description: Optional[str] = Field(None, max_length=1000)
    evidence_file_ids: list[str] = Field(default_factory=list, max_length=10)


class DisputeMessageSchema(BaseModel):
    body: str = Field(..., min_length=1, max_length=2000)
    evidence_file_ids: list[str] = Field(default_factory=list, max_length=10)
    internal: bool = False  # admin-only note


class DisputeStatusSchema(BaseModel):
    status: Literal["under_review", "awaiting_evidence"]
    note: Optional[str] = Field(None, max_length=500)


class AssignDisputeSchema(BaseModel):
    admin_id: int


class ResolveDisputeSchema(BaseModel):
    status: Literal["resolved", "rejected"]
    resolution: str = Field(..., min_length=1, max_length=1000)
    resolution_type: Literal["full_refund", "partial_refund", "replacement", "no_action"] = "no_action"
    refund_amount: Optional[float] = Field(None, gt=0)
