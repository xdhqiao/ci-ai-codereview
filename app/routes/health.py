from fastapi import APIRouter

from app.core.database import ping_database

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    ping_database()
    return {"status": "ok", "database": "ok"}
