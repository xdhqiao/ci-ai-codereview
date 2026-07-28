from datetime import date
from pathlib import Path

from fastapi import APIRouter, Query, Response
from fastapi.responses import FileResponse

from app.schemas.feedback_log import (
    FeedbackLogAuthorDetailResponse,
    FeedbackLogDetailResponse,
    FeedbackLogGroupBy,
    FeedbackLogReportResponse,
)
from app.services.feedback_log_service import FeedbackLogService


router = APIRouter(tags=["feedback-logs"])
STATIC_ROOT = Path(__file__).resolve().parents[1] / "static"


@router.get("/admin/feedback-logs.html", include_in_schema=False)
def feedback_logs_page() -> FileResponse:
    return FileResponse(STATIC_ROOT / "feedback_logs.html", headers={"Cache-Control": "no-store"})


@router.get("/admin/feedback-log-detail.html", include_in_schema=False)
def feedback_log_detail_page() -> FileResponse:
    return FileResponse(
        STATIC_ROOT / "feedback_log_detail.html",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/admin/feedback-log-author-detail.html", include_in_schema=False)
def feedback_log_author_detail_page() -> FileResponse:
    return FileResponse(
        STATIC_ROOT / "feedback_log_author_detail.html",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/admin/feedback-logs", response_model=FeedbackLogReportResponse)
def feedback_logs_report(
    response: Response,
    group_by: FeedbackLogGroupBy = "none",
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> FeedbackLogReportResponse:
    response.headers["Cache-Control"] = "no-store"
    return FeedbackLogService().report(
        group_by=group_by,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
    )


@router.get("/api/admin/feedback-logs/detail", response_model=FeedbackLogDetailResponse)
def feedback_log_detail(
    response: Response,
    project_id: str = Query(min_length=1, max_length=200),
    review_version: str = Query(min_length=1, max_length=500),
    copy_from_version: str = Query(min_length=1, max_length=500),
    start_date: date | None = None,
    end_date: date | None = None,
) -> FeedbackLogDetailResponse:
    response.headers["Cache-Control"] = "no-store"
    return FeedbackLogService().detail(
        project_id=project_id,
        review_version=review_version,
        copy_from_version=copy_from_version,
        start_date=start_date,
        end_date=end_date,
    )


@router.get(
    "/api/admin/feedback-logs/author-detail",
    response_model=FeedbackLogAuthorDetailResponse,
)
def feedback_log_author_detail(
    response: Response,
    file_author: str = Query(min_length=1, max_length=200),
    start_date: date | None = None,
    end_date: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> FeedbackLogAuthorDetailResponse:
    response.headers["Cache-Control"] = "no-store"
    return FeedbackLogService().author_detail(
        file_author=file_author,
        start_date=start_date,
        end_date=end_date,
        page=page,
        page_size=page_size,
    )
