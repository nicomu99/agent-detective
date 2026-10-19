"""Middleware. Runs for every request."""
import uuid
import time
import logging

from fastapi import Request

logger = logging.getLogger(__name__)


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
