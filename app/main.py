"""Part 3: the Blackwood Manor detective service, built with FastAPI.

    uvicorn app.main:app --reload      then open http://127.0.0.1:8000/docs
"""
from typing import Annotated, Callable

import logging
import os
import time  # noqa: F401  (for step 10)
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status  # noqa: F401
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field  # noqa: F401

from .detective import Investigation, CaseFile, BRIEFING, InvestigationError

from . import llm

ROOT = Path(__file__).resolve().parent.parent
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("detective")


# ---------------------------------------------------------------------------
# Settings and a health check
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Settings:
    """Service configuration, read once at startup from environment variables.

    Frozen, so the configuration can't be changed while the service runs.

    Attributes:
        case_dir: Folder with the case's ``*.md`` files and ``suspects.json``.
        model: Which model the detective uses, ``"fake"`` or ``"claude"``.
        max_turns: Maximum model calls per agent turn.
    """
    case_dir: Path
    model: str      # "fake" or "claude"
    max_turns: int


def load_settings() -> Settings:
    """Builds the settings from environment variables and validates them.

    Reads:
        CASE_DIR: Path to the case folder. Defaults to ``<project>/case_files``.
        DETECTIVE_MODEL: ``"fake"`` (default) or ``"claude"``, case-insensitive.
        MAX_TURNS: Positive integer. Defaults to 8.

    Returns:
        The validated settings.

    Raises:
        ValueError: If any variable has an invalid value. Failing at startup
            means a misconfigured container crashes immediately instead of
            misbehaving later.
    """
    case_dir = Path(os.environ.get("CASE_DIR", default=ROOT / "case_files"))

    model = os.environ.get("DETECTIVE_MODEL", "fake").strip().lower()
    if model not in ("fake", "claude"):
        raise ValueError(f"DETECTIVE_MODEL {model} unknown. Must be 'fake' or 'claude'.")
    if model == "claude" and not llm.has_api_key():
        raise ValueError("DETECTIVE_MODEL=claude needs ANTHROPIC_API_KEY to be set")

    max_turns = int(os.environ.get("MAX_TURNS", 8))
    if max_turns < 1:
        raise ValueError(f"MAX_TURNS {max_turns} invalid. Must be positive integer.")
    return Settings(case_dir, model, max_turns)


# ---------------------------------------------------------------------------
# Startup (lifespan) and a readiness check
# ---------------------------------------------------------------------------

class InvestigationStore:
    """In-memory registry of all running investigations, keyed by id.

    State lives in this process only: it is lost on restart and not shared
    between replicas. Fine for one pod; with several, use an external
    store such as Redis.
    """

    def __init__(self):
        """Creates an empty store."""
        self._items: dict[str, Investigation] = {}

    def add(self, investigation: Investigation) -> str:
        """Stores an investigation under a new random id.

        Args:
            investigation: The investigation to store.

        Returns:
            The new id, 12 hex characters.
        """
        investigation_id = uuid.uuid4().hex[:12]
        self._items[investigation_id] = investigation
        return investigation_id

    def get(self, investigation_id: str) -> Investigation | None:
        """Looks up an investigation by id.

        Args:
            investigation_id: The id returned by ``add``.

        Returns:
            The investigation, or None if the id is unknown.
        """
        return self._items.get(investigation_id)

    def delete(self, investigation_id: str) -> bool:
        """Removes an investigation.

        Args:
            investigation_id: The id returned by ``add``.

        Returns:
            True if it existed and was removed, False if the id was unknown.
        """
        return self._items.pop(investigation_id, None) is not None


@asynccontextmanager
async def lifespan(app_: FastAPI):
    """Loads everything the service needs before it accepts requests.

    Code before ``yield`` runs once at startup and code after it at shutdown
    (nothing to clean up here). Results are stored on ``app_.state``, where
    the ``get_*`` dependencies read them.

    Args:
        app_: The FastAPI application being started.

    Yields:
        Nothing. Control returns to FastAPI, which serves requests until
        shutdown.

    Raises:
        ValueError: If the settings are invalid.
        FileNotFoundError: If the case files are missing.
        Either one aborts startup, so a misconfigured container crashes
        instead of serving requests.
    """
    settings = load_settings()
    app_.state.settings = settings
    app_.state.case_file = CaseFile.load(settings.case_dir)
    app_.state.investigations = InvestigationStore()
    logger.info("Loaded %d case files from %s", len(app_.state.case_file.index.documents), settings.case_dir)
    yield


app = FastAPI(title="Blackwood Manor", version="1.0", lifespan=lifespan)


def get_settings(request: Request) -> Settings:
    """FastAPI dependency that provides the service settings.

    Use it as ``Annotated[Settings, Depends(get_settings)]``.

    Args:
        request: The current request. FastAPI fills it in automatically.

    Returns:
        The settings loaded at startup by ``lifespan``.

    Raises:
        AttributeError: If called before startup has run.
    """
    return request.app.state.settings


def get_case_file(request: Request) -> CaseFile:
    """FastAPI dependency that provides the loaded case file.

    Use it as ``Annotated[CaseFile, Depends(get_case_file)]``.

    Args:
        request: The current request. FastAPI fills it in automatically.

    Returns:
        The case file (search index and suspects) loaded at startup.

    Raises:
        AttributeError: If called before startup has run.
    """
    return request.app.state.case_file


def get_store(request: Request) -> InvestigationStore:
    """FastAPI dependency that provides the investigation store.

    Use it as ``Annotated[InvestigationStore, Depends(get_store)]``.

    Args:
        request: The current request. FastAPI fills it in automatically.

    Returns:
        The store holding all running investigations.

    Raises:
        AttributeError: If called before startup has run.
    """
    return request.app.state.investigations


@app.get("/")
def index():
    """Example endpoint.

    Returns:
        Always ``{"service": "blackwood-manor", "docs": "/docs"}``.
    """
    return {"service": "blackwood-manor", "docs": "/docs"}


@app.get("/health")
def health():
    """Liveness check: reports that the process is up and responding.

    Deliberately checks nothing else (no case files, no model API), so a
    slow or failing dependency never gets a healthy pod restarted.
    Kubernetes uses it as the ``livenessProbe``.

    Returns:
        Always ``{"status": "ok"}``.
    """
    return {"status": "ok"}


@app.get("/ready")
def ready(request: Request):
    """Check whether the application finished setting up.

    Args:
        request: Request object.

    Returns:
        A status response indicating whether the application is starting up or ready.
    """
    case_file = getattr(request.app.state, "case_file", None)
    if case_file is None:
        return JSONResponse(content={"status": "starting"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return {"status": "ready", "documents": len(case_file.index.documents)}


# ---------------------------------------------------------------------------
# Evidence endpoints
# ---------------------------------------------------------------------------

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


@app.get("/evidence/search", response_model=SearchResponse)
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


@app.get("/evidence/{doc_id}", response_model=DocumentResponse)
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


# ---------------------------------------------------------------------------
# Investigations
# ---------------------------------------------------------------------------

def find_investigation(
    investigation_id: str,
    inv_store: Annotated[InvestigationStore, Depends(get_store)]
) -> Investigation:
    """FastAPI dependency that looks up the investigation named in the URL.

    FastAPI fills ``investigation_id`` from the path parameter of the same
    name, so any endpoint with ``/investigations/{investigation_id}`` can use
    ``inv: Annotated[Investigation, Depends(find_investigation)]`` and never
    handle the "not found" case itself.

    Args:
        investigation_id: The id from the URL path.
        inv_store: The investigation store (injected).

    Returns:
        The matching investigation.

    Raises:
        HTTPException: 404 if no investigation has this id.
    """
    inv = inv_store.get(investigation_id)
    if inv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No investigation with id {investigation_id} found."
        )
    return inv


class CreateInvestigationResponse(BaseModel):
    investigation_id: str
    briefing: str


@app.post(
    "/investigations",
    response_model=CreateInvestigationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_investigation(
    inv_store: Annotated[InvestigationStore, Depends(get_store)],
    case_file: Annotated[CaseFile, Depends(get_case_file)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CreateInvestigationResponse:
    """Starts a new investigation for one player.

    Args:
        inv_store: The investigation store (injected).
        case_file: The loaded case file (injected).
        settings: The settings configuration (injected).

    Returns:
        The new investigation's id and the case briefing. Status 201.
    """
    new_inv = Investigation(case_file=case_file, max_turns=settings.max_turns)
    inv_id = inv_store.add(new_inv)
    response = CreateInvestigationResponse(
        investigation_id=inv_id,
        briefing=BRIEFING
    )
    return response


class InvestigationResponse(BaseModel):
    investigation_id: str
    status: str
    questions_asked: int
    accused: str | None


@app.get("/investigations/{investigation_id}", response_model=InvestigationResponse)
def get_investigation(
    investigation_id: str,
    investigation: Annotated[Investigation, Depends(find_investigation)]
) -> InvestigationResponse:
    """Returns the current state of an investigation.

    Args:
        investigation_id: The id from the URL path.
        investigation: The matching investigation (injected, 404 if unknown).

    Returns:
        Status, number of questions asked and who was accused.
    """
    query_count = sum(1 for m in investigation.messages if isinstance(m["content"], str))
    inv_response = InvestigationResponse(
        investigation_id=investigation_id,
        status=investigation.status,
        questions_asked=query_count,
        accused=investigation.accused,
    )
    return inv_response


@app.delete("/investigations/{inv_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_investigation(
    inv_id: str,
    inv_store: Annotated[InvestigationStore, Depends(get_store)]
):
    """Closes an investigation and forgets it.

    Args:
        inv_id: The id from the URL path.
        inv_store: The investigation store (injected).

    Returns:
        An empty response with status 204.

    Raises:
        HTTPException: 404 if no investigation has this id.
    """
    deleted = inv_store.delete(inv_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No investigation with id {inv_id} found.")
    return None


# ---------------------------------------------------------------------------
# Detective Endpoints
# ---------------------------------------------------------------------------

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


def get_model(settings: Annotated[Settings, Depends(get_settings)]):
    """FastAPI dependency that picks the model the detective talks to.

    Tests replace it via ``app.dependency_overrides[get_model]`` to inject a
    scripted model.

    Args:
        settings: The service settings (injected).

    Returns:
        ``llm.fake_model`` if ``settings.model`` is ``"fake"``, otherwise
        ``llm.call_model`` (Claude). Both take ``(system, messages, tools)``
        and return the next assistant message.
    """
    if settings.model == "fake":
        return llm.fake_model
    return llm.call_model


@app.post("/investigations/{investigation_id}/messages", response_model=TurnResponse)
def ask(
    investigation_id: str,
    investigation: Annotated[Investigation, Depends(find_investigation)],
    body: InvestigationBody,
    model: Annotated[Callable, Depends(get_model)],
) -> TurnResponse:
    """Sends the inspector's message to the detective and runs one agent turn.

    Args:
        investigation_id: The id from the URL path. Used for logging; the
            lookup itself happens in ``find_investigation``.
        investigation: The matching investigation (injected, 404 if unknown).
        body: The request body with the inspector's ``text``.
        model: The model to use (injected).

    Returns:
        The turn: status, the detective's reply, the tools it ran, and any
        action now awaiting approval.

    Raises:
        HTTPException: 409 if the investigation can't take questions right
            now (an accusation awaits approval, or the case is closed).
            422 if the text is empty.
    """
    logger.info("question for investigation %s", investigation_id)
    if len(body.text) == 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Request contains empty body.")
    try:
        return TurnResponse.model_validate(investigation.ask(body.text, model))
    except InvestigationError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


class InvestigationApprovalBody(BaseModel):
    approved: bool


@app.post("/investigations/{investigation_id}/approval", response_model=TurnResponse)
def decide(
    investigation_id: str,
    investigation: Annotated[Investigation, Depends(find_investigation)],
    body: InvestigationApprovalBody,
    model: Annotated[Callable, Depends(get_model)],
) -> TurnResponse:
    """Approves or declines the action the detective is waiting on.

    Resumes an investigation paused at ``awaiting_approval``. If approved,
    the pending tool (the accusation) runs, which may close the case. If
    declined, the model is told and continues investigating.

    Args:
        investigation_id: The id from the URL path. Used for logging; the
            lookup itself happens in ``find_investigation``.
        investigation: The matching investigation (injected, 404 if unknown).
        body: The request body with ``approved`` (bool).
        model: The model to use (injected).

    Returns:
        The turn after the decision: the new status (``solved``/``failed``
        after an approved accusation), the detective's reply and the tools run.

    Raises:
        HTTPException: 409 if nothing is awaiting approval.
            422 (raised by FastAPI) if ``approved`` is missing or not a bool.
    """
    logger.info("decision for investigation %s", investigation_id)
    try:
        return TurnResponse.model_validate(investigation.decide(body.approved, model))
    except InvestigationError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


@app.middleware("http")
async def request_id(request: Request, call_next):
    """Tags every request with an id and writes one access-log line for it.

    Reuses the caller's ``X-Request-ID`` header if present (so an id set by a
    gateway or another service follows the request through), otherwise
    generates one. The id is echoed in the response header and in the log,
    which lets you find all log lines for one request across pods.

    Args:
        request: The incoming request.
        call_next: Passes the request on to the next middleware or the
            endpoint and returns its response.

    Returns:
        The endpoint's response with an ``X-Request-ID`` header added.
    """
    rid = request.headers.get("X-Request-ID", None)
    if rid == "" or rid is None:
        rid = uuid.uuid4().hex
    start_time = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("%s %s failed [%s]", request.method, request.url.path, rid)
        raise
    response.headers["X-Request-ID"] = rid
    logger.info(
        "Method: %s | Path: %s | Status code: %s | Duration: %.1f ms | Id: %s",
        request.method, request.url.path, response.status_code,
        (time.perf_counter() - start_time) * 1000, rid
    )
    return response
