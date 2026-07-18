from pathlib import Path

from fastapi import APIRouter, Query, Response
from fastapi.responses import FileResponse

from app.schemas.report import FeedbackRequest, FeedbackResponse, TaskReportResponse
from app.services.report_service import TaskReportService


router = APIRouter(tags=["reports"])
REPORT_PAGE = Path(__file__).resolve().parents[1] / "static" / "report.html"


@router.get("/snapshot/{snapshot_id}/{project_id}/{comparison}.html", include_in_schema=False)
def snapshot_report_page(snapshot_id: str, project_id: str, comparison: str) -> FileResponse:
    TaskReportService().find_snapshot(snapshot_id, project_id, comparison)
    return FileResponse(REPORT_PAGE, headers={"Cache-Control": "no-store"})


@router.get("/{project_id}/{comparison}.html", include_in_schema=False)
def report_page(project_id: str, comparison: str) -> FileResponse:
    TaskReportService().find_task_by_comparison(project_id, comparison)
    return FileResponse(REPORT_PAGE, headers={"Cache-Control": "no-store"})


@router.get("/api/reports/tasks/{task_id}", response_model=TaskReportResponse)
def get_task_report(
    task_id: str,
    response: Response,
    author: str = "",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=300, ge=1, le=300),
    trigger_revision: int | None = Query(default=None, ge=1),
) -> TaskReportResponse:
    response.headers["Cache-Control"] = "no-store"
    return TaskReportService().get_report(
        task_id,
        author=author,
        page=page,
        page_size=page_size,
        trigger_revision=trigger_revision,
    )


@router.get("/api/reports/{project_id}/{comparison}.html", response_model=TaskReportResponse)
def get_task_report_by_comparison(
    project_id: str,
    comparison: str,
    response: Response,
    author: str = "",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=300, ge=1, le=300),
    trigger_revision: int | None = Query(default=None, ge=1),
) -> TaskReportResponse:
    response.headers["Cache-Control"] = "no-store"
    return TaskReportService().get_report_by_comparison(
        project_id,
        comparison,
        author=author,
        page=page,
        page_size=page_size,
        trigger_revision=trigger_revision,
    )


@router.get(
    "/api/reports/snapshot/{snapshot_id}/{project_id}/{comparison}.html",
    response_model=TaskReportResponse,
)
def get_snapshot_report(
    snapshot_id: str,
    project_id: str,
    comparison: str,
    response: Response,
    author: str = "",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=300, ge=1, le=300),
) -> TaskReportResponse:
    response.headers["Cache-Control"] = "no-store"
    return TaskReportService().get_snapshot_report(
        snapshot_id,
        project_id,
        comparison,
        author=author,
        page=page,
        page_size=page_size,
    )


@router.post("/api/feedback/{file_id}/{block_id}/{issue_id}", response_model=FeedbackResponse)
def save_issue_feedback(
    file_id: str,
    block_id: int,
    issue_id: int,
    payload: FeedbackRequest,
) -> FeedbackResponse:
    return TaskReportService().save_feedback(file_id, block_id, issue_id, payload)
