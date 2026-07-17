from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Query, Response
from fastapi.responses import FileResponse

from app.schemas.admin import AdminTaskListResponse, AdminTaskSortField, SortOrder
from app.services.admin_task_service import AdminTaskService


router = APIRouter(tags=["admin"])
ADMIN_TASKS_PAGE = Path(__file__).resolve().parents[1] / "static" / "admin_tasks.html"


@router.get("/admin/tasks.html", include_in_schema=False)
def admin_tasks_page() -> FileResponse:
    return FileResponse(ADMIN_TASKS_PAGE, headers={"Cache-Control": "no-store"})


@router.get("/api/admin/tasks", response_model=AdminTaskListResponse)
def list_admin_tasks(
    response: Response,
    project_id: str = Query(default="", max_length=200),
    review_version: str = Query(default="", max_length=200),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    task_type: int | None = Query(default=None, ge=1, le=2),
    state: int | None = Query(default=None, ge=0, le=4),
    sort_by: AdminTaskSortField = "create_time",
    sort_order: SortOrder = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> AdminTaskListResponse:
    response.headers["Cache-Control"] = "no-store"
    return AdminTaskService().list_tasks(
        project_id=project_id,
        review_version=review_version,
        date_from=date_from,
        date_to=date_to,
        task_type=task_type,
        state=state,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )
