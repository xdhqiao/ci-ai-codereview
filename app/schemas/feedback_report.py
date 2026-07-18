from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


FeedbackView = Literal["prd_version", "full_scan", "author_prd", "author_full"]


class FeedbackSummaryResponse(BaseModel):
    project_count: int
    version_count: int
    author_count: int
    severe_issue_count: int
    severe_feedback_count: int
    severe_feedback_rate: float
    severe_agree_count: int
    severe_reject_count: int
    severe_agree_rate: float
    issue_count: int
    issue_feedback_count: int
    issue_feedback_rate: float
    severity_distribution: dict[str, int]


class FeedbackTaskItemResponse(BaseModel):
    task_id: str
    project_id: str
    review_version: str
    copy_from_version: str
    severe_issue_count: int
    severe_feedback_rate: float
    severe_agree_rate: float
    issue_count: int
    issue_feedback_rate: float
    create_time: datetime
    report_url: str


class FeedbackAuthorItemResponse(BaseModel):
    file_author: str
    author_name: str
    severe_issue_count: int
    severe_feedback_rate: float
    severe_agree_rate: float
    issue_count: int
    issue_feedback_rate: float
    report_url: str


class FeedbackPaginationResponse(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class AdminFeedbackReportResponse(BaseModel):
    view: FeedbackView
    task_type: int
    start_date: date | None
    end_date: date | None
    summary: FeedbackSummaryResponse
    pagination: FeedbackPaginationResponse
    task_items: list[FeedbackTaskItemResponse]
    author_items: list[FeedbackAuthorItemResponse]


class AuthorIssueItemResponse(BaseModel):
    file_id: str
    block_id: int
    issue_id: int
    file_name: str
    severity: int
    issue_line_numbers: str
    issue_type: str
    description: str
    suggestion: str
    contents: list[str]
    feedback_type: str
    feedback_content: str


class AuthorIssueSummaryResponse(BaseModel):
    severe_issue_count: int
    issue_count: int
    severe_feedback_rate: float
    severe_agree_rate: float
    issue_feedback_rate: float
    file_count: int


class AuthorIssueReportResponse(BaseModel):
    file_author: str
    author_name: str
    task_type: int
    start_date: date | None
    end_date: date | None
    summary: AuthorIssueSummaryResponse
    pagination: FeedbackPaginationResponse
    items: list[AuthorIssueItemResponse]
