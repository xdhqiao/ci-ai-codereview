from datetime import date
from pathlib import Path

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse

from app.schemas.dashboard import DashboardResponse
from app.services.dashboard_service import DashboardService


router = APIRouter(tags=["dashboard"])
STATIC_ROOT = Path(__file__).resolve().parents[1] / "static"


@router.get("/admin/dashboard.html", include_in_schema=False)
def dashboard_page() -> FileResponse:
    return FileResponse(STATIC_ROOT / "dashboard.html", headers={"Cache-Control": "no-store"})


@router.get("/api/admin/dashboard", response_model=DashboardResponse)
def dashboard_report(
    response: Response,
    start_date: date | None = None,
    end_date: date | None = None,
) -> DashboardResponse:
    response.headers["Cache-Control"] = "no-store"
    return DashboardService().report(start_date=start_date, end_date=end_date)
