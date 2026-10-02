"""Liveness and readiness probes (SPEC §8)."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import get_database
from app.db.session import Database

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", response_model=None)
def readyz(db: Database = Depends(get_database)) -> dict[str, str] | JSONResponse:
    try:
        db.ping()
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ok"}
