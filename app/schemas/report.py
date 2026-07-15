from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ScoreResponse(BaseModel):
    logic_score: int
    performance_score: int
    security_score: int
    readable_score: int
    code_style_score: int


class FeedbackRequest(BaseModel):
    feedback_type: Literal["agree", "reject"]
    feedback_content: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def validate_reject_reason(self) -> "FeedbackRequest":
        self.feedback_content = self.feedback_content.strip()
        if self.feedback_type == "reject" and not self.feedback_content:
            raise ValueError("feedback_content is required when feedback_type is reject")
        if self.feedback_type == "agree":
            self.feedback_content = ""
        return self


class FeedbackResponse(BaseModel):
    file_id: str
    block_id: int
    issue_id: int
    feedback_type: str
    feedback_content: str


class ReportIssueResponse(BaseModel):
    issue_id: int
    severity: int
    issue_line_numbers: str
    type: str
    description: str
    suggestion: str
    feedback_type: str
    feedback_content: str


class ReportBlockResponse(BaseModel):
    block_id: int
    review_state: int
    status: str
    process_time_ms: int
    main_task_completed: bool
    completion_mode: str
    failure_message: str
    changed_line_num: int
    overall_score: int
    scores: ScoreResponse
    contents: list[str]
    comment: str
    issues: list[ReportIssueResponse]


class ReportFileResponse(BaseModel):
    file_id: str
    file_name: str
    file_author: str
    review_state: int
    status: str
    completed_block_num: int
    failed_block_num: int
    changed_line_num: int
    added_line_num: int
    overall_score: int
    scores: ScoreResponse
    blocks: list[ReportBlockResponse]


class CriticalIssueResponse(BaseModel):
    file_id: str
    block_id: int
    issue_id: int
    file_name: str
    file_author: str
    severity: int
    issue_line_numbers: str
    type: str
    description: str
    suggestion: str


class ReportOverviewResponse(BaseModel):
    task_id: str
    project_id: str
    review_version: str
    copy_from_version: str
    task_type: int
    review_mode: str
    state: int
    completion_status: str
    create_time: datetime
    update_time: datetime | None
    process_time_ms: int
    changed_line_num: int
    added_line_num: int
    overall_score: int
    scores: ScoreResponse


class ReportMetricsResponse(BaseModel):
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    llm_elapsed_ms: int
    file_num: int
    reviewed_file_num: int
    code_block_num: int
    issue_num: int
    filtered_issue_num: int
    critical_issue_num: int
    tool_call_num: int
    model_round_num: int
    memory_compression_num: int
    incomplete_file_num: int


class ReportProgressResponse(BaseModel):
    percentage: int
    total_file_num: int
    completed_file_num: int
    reviewing_file_num: int
    pending_file_num: int
    failed_file_num: int
    total_block_num: int
    completed_block_num: int
    reviewing_block_num: int
    pending_block_num: int
    failed_block_num: int
    retryable_file_num: int
    retryable_block_num: int
    retry_available: bool
    retry_in_progress: bool
    manual_retry_count: int
    next_retry_time: datetime | None
    auto_refresh_seconds: int


class ReportPaginationResponse(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class TaskReportResponse(BaseModel):
    overview: ReportOverviewResponse
    progress: ReportProgressResponse
    metrics: ReportMetricsResponse
    authors: list[str]
    selected_author: str
    highest_severity: int | None
    critical_issues: list[CriticalIssueResponse]
    pagination: ReportPaginationResponse
    files: list[ReportFileResponse]
