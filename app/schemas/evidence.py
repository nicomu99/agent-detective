"""Evidence request/response schemas."""
from pydantic import BaseModel


class SearchHit(BaseModel):
    doc_id: str
    title: str
    snippet: str
    score: float


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]


class DocumentResponse(BaseModel):
    doc_id: str
    title: str
    text: str
