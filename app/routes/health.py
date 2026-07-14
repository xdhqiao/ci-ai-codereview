from typing import Any

from fastapi import APIRouter, Request

from app.core.database import ping_database

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    ping_database()
    return {"status": "ok", "database": "ok"}


@router.get("/health/scheduler")
def scheduler_health(request: Request) -> dict[str, Any]:
    scheduler = getattr(request.app.state, "review_scheduler", None)
    if scheduler is None:
        return {"enabled": False, "running": False}
    return scheduler.status()
