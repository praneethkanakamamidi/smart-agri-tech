from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class ChatRequest(BaseModel):
    message: Optional[str] = Field(None, min_length=1, max_length=2000)
    voice_file_id: Optional[str] = Field(None, min_length=36, max_length=36,
                                         description="A 'voice_note' upload, transcribed by a speech-capable model.")
    conversation_id: Optional[str] = Field(None, min_length=36, max_length=36)
    workflow_id: Optional[str] = Field(None, min_length=36, max_length=36,
                                       description="Answer the question of a workflow that is awaiting input.")
    file_ids: list[str] = Field(default_factory=list, max_length=10,
                                description="Photos ('listing_image' or 'dispute_evidence' uploads).")
    background: bool = Field(False, description="Return immediately (202) and run in the worker.")

    @model_validator(mode="after")
    def text_or_voice(self):
        if not self.message and not self.voice_file_id:
            raise ValueError("send a message or a voice_file_id")
        return self


class WorkflowInput(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    edits: dict = Field(default_factory=dict, description="Changes to editable fields only.")
    note: Optional[str] = Field(None, max_length=500)


class ListingFromImages(BaseModel):
    file_ids: list[str] = Field(..., min_length=1, max_length=10)
    notes: Optional[str] = Field(None, max_length=1000,
                                 description="What you'd tell a buyer: produce, quantity, price, dates.")
    background: bool = False


class ImageAnalysisRequest(BaseModel):
    file_id: str = Field(..., min_length=36, max_length=36)
    commodity_hint: Optional[str] = Field(None, max_length=60)


class InvestigateRequest(BaseModel):
    background: bool = False
