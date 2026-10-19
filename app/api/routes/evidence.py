"""Evidence routes."""
from typing import Annotated

from fastapi import APIRouter, Query, Depends, status, HTTPException

from app.api import get_case_file
from app.schemas import SearchResponse, SearchHit, DocumentResponse
from app.domain import CaseFile

router = APIRouter()


@router.get("/evidence/search", response_model=SearchResponse)
def search_evidence(
    q: Annotated[str, Query(min_length=2, max_length=200)],
    case_file: Annotated[CaseFile, Depends(get_case_file)],
    k: Annotated[int, Query(ge=1, le=20)] = 3,
) -> SearchResponse:
    """Searches the case files for passages matching a query.

    Exposes the RAG retrieval step directly, without the agent.

    Args:
        q: Search keywords, 2-200 characters.
        case_file: The loaded case file (injected).
        k: Maximum number of hits to return.

    Returns:
        The query and its hits, best match first.

    Raises:
        HTTPException: 404 if no passage matches the query.
            422 (raised by FastAPI) if ``q`` or ``k`` is out of range.
    """
    search_results = case_file.index.search(q, k)
    search_results = [SearchHit(**s) for s in search_results]
    return SearchResponse(**{"query": q, "hits": search_results})


@router.get("/evidence/{doc_id}", response_model=DocumentResponse)
def get_evidence_document(
    doc_id: str,
    case_file: Annotated[CaseFile, Depends(get_case_file)]
) -> DocumentResponse:
    """Returns one complete case file.

    Args:
        doc_id: The document's id, e.g. ``coroner-report``.
        case_file: The loaded case file (injected).

    Returns:
        The document's id, title and full Markdown text.

    Raises:
        HTTPException: 404 if no document has this id.
    """
    response_doc = case_file.index.get(doc_id)
    if response_doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No case file with ID {doc_id} found.")
    return DocumentResponse(**response_doc)
