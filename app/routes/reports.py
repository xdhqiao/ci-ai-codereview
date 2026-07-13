from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from app.schemas.report import FeedbackRequest, FeedbackResponse, TaskReportResponse
from app.services.report_service import TaskReportService


router = APIRouter(tags=["reports"])
REPORT_PAGE = Path(__file__).resolve().parents[1] / "static" / "report.html"


@router.get("/{project_id}/{comparison}.html", include_in_schema=False)
def report_page(project_id: str, comparison: str) -> FileResponse:
    TaskReportService().find_task_by_comparison(project_id, comparison)
    return FileResponse(REPORT_PAGE)


@router.get("/api/reports/tasks/{task_id}", response_model=TaskReportResponse)
def get_task_report(
    task_id: str,
    author: str = "",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=300, ge=1, le=300),
) -> TaskReportResponse:
    return TaskReportService().get_report(task_id, author=author, page=page, page_size=page_size)


@router.get("/api/reports/{project_id}/{comparison}.html", response_model=TaskReportResponse)
def get_task_report_by_comparison(
    project_id: str,
    comparison: str,
    author: str = "",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=300, ge=1, le=300),
) -> TaskReportResponse:
    return TaskReportService().get_report_by_comparison(
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
