"""Part 3: the Blackwood Manor detective service, built with FastAPI.

    uvicorn app.main:app --reload      then open http://127.0.0.1:8000/docs
"""
import os
import logging
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI

from app.core import setup_logging, request_id, load_settings
from app.api.routes import health, evidence, investigations
from app.repositories import InvestigationStore
from app.domain.detective import CaseFile

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Loads everything the service needs before it accepts requests.

    Code before ``yield`` runs once at startup and code after it at shutdown
    (nothing to clean up here). Results are stored on ``app_.state``, where
    the ``get_*`` dependencies read them.

    Args:
        app: The FastAPI application being started.

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
    app.state.settings = settings
    app.state.case_file = CaseFile.load(settings.case_dir)
    app.state.redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    app.state.investigations = InvestigationStore(app.state.redis, app.state.case_file)
    logger.info("Loaded %d case files from %s", len(app.state.case_file.index.documents), settings.case_dir)
    yield
    await app.state.redis.aclose()


def create_app() -> FastAPI:
    """Main entry point of the application.

    Returns:
        The FastAPI application.
    """
    setup_logging(os.environ.get("LOG_LEVEL", "INFO"))
    app = FastAPI(title="Blackwood Manor", version="1.0", lifespan=lifespan)
    app.middleware("http")(request_id)
    app.include_router(health.router)
    app.include_router(evidence.router)
    app.include_router(investigations.router)
    return app


main_app = create_app()
