"""Liveness and readiness probes (SPEC §8)."""

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import get_database
from app.db.session import Database

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", response_model=None)
def readyz(db: Database = Depends(get_database)) -> dict[str, str] | JSONResponse:
    try:
        db.ping()
    except Exception as exc:
        # The reason goes to the server log only (driver messages never contain the password).
        logger.warning(
            "database not ready: %s: %s", type(exc).__name__, str(exc).splitlines()[0][:300] if str(exc) else ""
        )
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ok"}
