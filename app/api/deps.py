"""FastAPI dependencies."""
from typing import Annotated

from fastapi import Request, Depends, status, HTTPException

from app.core import Settings
from app.domain import Investigation, CaseFile
from app.repositories import InvestigationStore
import app.domain.llm as llm


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


async def find_investigation(
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
    inv = await inv_store.get(investigation_id)
    if inv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No investigation with id {investigation_id} found."
        )
    return inv


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
