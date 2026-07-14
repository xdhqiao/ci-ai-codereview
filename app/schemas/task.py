from datetime import datetime

from pydantic import BaseModel, Field

from app.models.task import TaskModel
from app.schemas.code_file import ModelRoundTraceResponse


class TaskCreate(BaseModel):
    project_id: str
    review_version: str
    copy_from_version: str = ""
    review_version_path: str = ""
    copy_from_version_path: str = ""
    task_type: int = Field(default=2, description="1 means incremental scan, 2 means full scan")
    state: int = 0
    submitter: str | None = None
    parent_path: str | None = None
    created_by: str = ""


class TaskResponse(BaseModel):
    id: str
    project_id: str
    review_version: str
    copy_from_version: str
    review_version_path: str
    copy_from_version_path: str
    task_type: int | None
    state: int
    submitter: str | None
    score: int
    logic_score: int
    performance_score: int
    security_score: int
    readable_score: int
    code_style_score: int
    retry_count: int
    code_block_num: int
    file_num: int
    reviewed_file_num: int
    resumed_file_num: int
    skipped_file_num: int
    incomplete_file_num: int
    completion_status: str
    add_code_line_num: int
    comment_line_number: int
    process_time: int
    estimated_token_num: int
    consumed_estimated_token_num: int
    token_budget_num: int
    llm_prompt_tokens: int
    llm_completion_tokens: int
    llm_total_tokens: int
    llm_elapsed_ms: int
    llm_call_count: int
    tool_call_summary: dict
    task_model_rounds: list[ModelRoundTraceResponse]
    project_summary: str
    parent_path: str | None
    developer_issue_summary: dict
    trigger_count: int
    trigger_revision: int
    lease_owner: str
    lease_expires_at: datetime | None
    heartbeat_time: datetime | None
    interrupt_requested: bool
    completion_email_sent: bool
    created_by: str
    create_time: datetime
    updated_by: str
    update_time: datetime | None

    @classmethod
    def from_model(cls, task: TaskModel) -> "TaskResponse":
        return cls(
            id=str(task.id),
            project_id=task.project_id,
            review_version=task.review_version,
            copy_from_version=task.copy_from_version,
            review_version_path=task.review_version_path or "",
            copy_from_version_path=task.copy_from_version_path or "",
            task_type=task.task_type,
            state=task.state,
            submitter=task.submitter,
            score=task.score or 0,
            logic_score=task.logic_score,
            performance_score=task.performance_score,
            security_score=task.security_score,
            readable_score=task.readable_score,
            code_style_score=task.code_style_score,
            retry_count=task.retry_count or 0,
            code_block_num=task.code_block_num or 0,
            file_num=task.file_num or 0,
            reviewed_file_num=task.reviewed_file_num or 0,
            resumed_file_num=task.resumed_file_num or 0,
            skipped_file_num=task.skipped_file_num or 0,
            incomplete_file_num=task.incomplete_file_num or 0,
            completion_status=task.completion_status or "",
            add_code_line_num=task.add_code_line_num or 0,
            comment_line_number=task.comment_line_number or 0,
            process_time=task.process_time or 0,
            estimated_token_num=task.estimated_token_num or 0,
            consumed_estimated_token_num=task.consumed_estimated_token_num or 0,
            token_budget_num=task.token_budget_num or 0,
            llm_prompt_tokens=task.llm_prompt_tokens or 0,
            llm_completion_tokens=task.llm_completion_tokens or 0,
            llm_total_tokens=task.llm_total_tokens or 0,
            llm_elapsed_ms=task.llm_elapsed_ms or 0,
            llm_call_count=task.llm_call_count or 0,
            tool_call_summary=task.tool_call_summary or {},
            task_model_rounds=[ModelRoundTraceResponse.from_model(trace) for trace in task.task_model_rounds],
            project_summary=task.project_summary or "",
            parent_path=task.parent_path,
            developer_issue_summary=task.developer_issue_summary or {},
            trigger_count=task.trigger_count or 0,
            trigger_revision=task.trigger_revision or 0,
            lease_owner=task.lease_owner or "",
            lease_expires_at=task.lease_expires_at,
            heartbeat_time=task.heartbeat_time,
            interrupt_requested=bool(task.interrupt_requested),
            completion_email_sent=bool(task.completion_email_sent),
            created_by=task.created_by or "",
            create_time=task.create_time,
            updated_by=task.updated_by or "",
            update_time=task.update_time,
        )


class TaskListResponse(BaseModel):
    items: list[TaskResponse]
    total: int


class JenkinsTaskTrigger(BaseModel):
    project_id: str
    review_version: str
    copy_from_version: str = "0_version"
    review_version_path: str
    copy_from_version_path: str = ""
    submitter: str | None = None
    created_by: str = "jenkins"
