"""Investigation request/response schemas."""
from pydantic import BaseModel


class CreateInvestigationResponse(BaseModel):
    investigation_id: str
    briefing: str


class InvestigationResponse(BaseModel):
    investigation_id: str
    status: str
    questions_asked: int
    accused: str | None


class ToolCall(BaseModel):
    name: str
    input: dict
    is_error: bool


class PendingAction(BaseModel):
    tool: str
    input: dict


class TurnResponse(BaseModel):
    status: str
    reply: str | None
    tool_calls: list[ToolCall]
    pending: PendingAction | None


class InvestigationBody(BaseModel):
    text: str


class InvestigationApprovalBody(BaseModel):
    approved: bool
