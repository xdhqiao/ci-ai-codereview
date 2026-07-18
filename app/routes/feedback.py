from datetime import date
from pathlib import Path

from fastapi import APIRouter, Query, Response
from fastapi.responses import FileResponse

from app.schemas.feedback_report import AdminFeedbackReportResponse, AuthorIssueReportResponse, FeedbackView
from app.services.feedback_report_service import FeedbackReportService


router = APIRouter(tags=["feedback-reports"])
STATIC_ROOT = Path(__file__).resolve().parents[1] / "static"


@router.get("/admin/feedback.html", include_in_schema=False)
def feedback_admin_page() -> FileResponse:
    return FileResponse(STATIC_ROOT / "feedback_admin.html", headers={"Cache-Control": "no-store"})


@router.get("/api/admin/feedback", response_model=AdminFeedbackReportResponse)
def admin_feedback_report(
    response: Response,
    view: FeedbackView = "prd_version",
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> AdminFeedbackReportResponse:
    response.headers["Cache-Control"] = "no-store"
    return FeedbackReportService().admin_report(
        view=view,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
    )


@router.get("/author/{author_name}/issue_report.html", include_in_schema=False)
def author_issue_page(author_name: str) -> FileResponse:
    return FileResponse(STATIC_ROOT / "author_issue_report.html", headers={"Cache-Control": "no-store"})


@router.get("/api/authors/{author_name}/issue-report", response_model=AuthorIssueReportResponse)
def author_issue_report(
    author_name: str,
    response: Response,
    file_author: str = Query(min_length=1, max_length=200),
    task_type: int = Query(ge=2, le=3),
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> AuthorIssueReportResponse:
    response.headers["Cache-Control"] = "no-store"
    return FeedbackReportService().author_report(
        author_name=author_name,
        file_author=file_author,
        task_type=task_type,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
    )
