from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


FeedbackLogGroupBy = Literal["none", "version", "author"]


class FeedbackLogSummaryResponse(BaseModel):
    feedback_count: int
    agree_rate: float
    severe_feedback_count: int
    severe_agree_rate: float


class FeedbackLogPaginationResponse(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class FeedbackLogItemResponse(BaseModel):
    log_id: str
    task_id: str
    project_id: str
    review_version: str
    copy_from_version: str
    task_type: int | None
    file_name: str
    file_author: str
    author_name: str
    issue_line_numbers: str
    severity: int
    suggestion: str
    description: str
    feedback_type: str
    feedback_content: str
    create_time: datetime


class FeedbackLogVersionItemResponse(BaseModel):
    project_id: str
    review_version: str
    copy_from_version: str
    issue_count: int
    agree_rate: float
    severe_issue_count: int
    severe_agree_rate: float
    detail_url: str


class FeedbackLogAuthorItemResponse(BaseModel):
    file_author: str
    author_name: str
    issue_count: int
    agree_rate: float
    detail_url: str


class FeedbackLogReportResponse(BaseModel):
    group_by: FeedbackLogGroupBy
    start_date: date
    end_date: date
    summary: FeedbackLogSummaryResponse
    pagination: FeedbackLogPaginationResponse
    log_items: list[FeedbackLogItemResponse]
    version_items: list[FeedbackLogVersionItemResponse]
    author_items: list[FeedbackLogAuthorItemResponse]


class FeedbackLogDetailResponse(BaseModel):
    project_id: str
    review_version: str
    copy_from_version: str
    start_date: date
    end_date: date
    summary: FeedbackLogSummaryResponse
    items: list[FeedbackLogItemResponse]


class FeedbackLogAuthorDetailResponse(BaseModel):
    file_author: str
    author_name: str
    start_date: date
    end_date: date
    summary: FeedbackLogSummaryResponse
    pagination: FeedbackLogPaginationResponse
    items: list[FeedbackLogItemResponse]
