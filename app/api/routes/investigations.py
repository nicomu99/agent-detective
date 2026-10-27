"""Investigation routes."""
from typing import Annotated, Callable

import asyncio
import logging

from fastapi import APIRouter, status, Depends, HTTPException

from app.api import get_case_file, get_settings, get_store, find_investigation, get_model
from app.core import Settings
from app.domain import CaseFile, Investigation, BRIEFING, InvestigationError
from app.repositories import InvestigationStore
from app.schemas import (
    CreateInvestigationResponse,
    InvestigationResponse,
    TurnResponse,
    InvestigationBody,
    InvestigationApprovalBody,
)

logger = logging.getLogger(__name__)


router = APIRouter()


@router.post(
    "/investigations",
    response_model=CreateInvestigationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_investigation(
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
    inv_id = await inv_store.add(new_inv)
    response = CreateInvestigationResponse(
        investigation_id=inv_id,
        briefing=BRIEFING
    )
    return response


@router.get("/investigations/{investigation_id}", response_model=InvestigationResponse)
async def get_investigation(
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


@router.delete("/investigations/{inv_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_investigation(
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
    deleted = await inv_store.delete(inv_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No investigation with id {inv_id} found.")
    return None


@router.post("/investigations/{investigation_id}/messages", response_model=TurnResponse)
async def ask(
    investigation_id: str,
    investigation: Annotated[Investigation, Depends(find_investigation)],
    inv_store: Annotated[InvestigationStore, Depends(get_store)],
    body: InvestigationBody,
    model: Annotated[Callable, Depends(get_model)],
) -> TurnResponse:
    """Sends the inspector's message to the detective and runs one agent turn.

    Args:
        investigation_id: The id from the URL path. Used for logging; the
            lookup itself happens in ``find_investigation``.
        investigation: The matching investigation (injected, 404 if unknown).
        inv_store: The investigation store (injected).
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
        turn = await asyncio.to_thread(investigation.ask, body.text, model)
    except InvestigationError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    await inv_store.save(investigation_id, investigation)
    return TurnResponse.model_validate(turn)


@router.post("/investigations/{investigation_id}/approval", response_model=TurnResponse)
async def decide(
    investigation_id: str,
    investigation: Annotated[Investigation, Depends(find_investigation)],
    inv_store: Annotated[InvestigationStore, Depends(get_store)],
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
        inv_store: The investigation store (injected).
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
        turn = await asyncio.to_thread(investigation.decide, body.approved, model)
    except InvestigationError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    await inv_store.save(investigation_id, investigation)
    return TurnResponse.model_validate(turn)
