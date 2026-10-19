"""Health routes."""
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/")
def index():
    """Example endpoint.

    Returns:
        Always ``{"service": "blackwood-manor", "docs": "/docs"}``.
    """
    return {"service": "blackwood-manor", "docs": "/docs"}


@router.get("/health")
def health():
    """Liveness check: reports that the process is up and responding.

    Deliberately checks nothing else (no case files, no model API), so a
    slow or failing dependency never gets a healthy pod restarted.
    Kubernetes uses it as the ``livenessProbe``.

    Returns:
        Always ``{"status": "ok"}``.
    """
    return {"status": "ok"}


@router.get("/ready")
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
