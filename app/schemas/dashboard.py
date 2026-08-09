from datetime import date

from pydantic import BaseModel


class DashboardTaskTypeResponse(BaseModel):
    task_type: int | None
    label: str
    count: int


class DashboardTaskSummaryResponse(BaseModel):
    task_count: int
    project_count: int
    task_types: list[DashboardTaskTypeResponse]


class DashboardResourceResponse(BaseModel):
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    llm_elapsed_ms: int
    file_count: int
    reviewed_file_count: int
    tool_call_count: int
    model_round_count: int


class DashboardIssueResponse(BaseModel):
    valid_issue_count: int
    filtered_issue_count: int
    severe_issue_count: int


class DashboardFeedbackResponse(BaseModel):
    feedback_count: int
    agree_count: int
    agree_rate: float
    historical_feedback_count: int
    historical_agree_count: int
    historical_agree_rate: float


class DashboardResponse(BaseModel):
    start_date: date
    end_date: date
    tasks: DashboardTaskSummaryResponse
    resources: DashboardResourceResponse
    issues: DashboardIssueResponse
    feedback: DashboardFeedbackResponse
