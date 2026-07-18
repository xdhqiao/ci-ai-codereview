from datetime import datetime
from urllib.parse import quote

from pydantic import BaseModel, Field, model_validator

from app.common.constant import FULL_SCAN_BASE_VERSION, TaskType
from app.models.task import TaskModel
from app.schemas.code_file import ModelRoundTraceResponse


class TaskCreate(BaseModel):
    project_id: str
    review_version: str
    copy_from_version: str = ""
    review_version_path: str = ""
    copy_from_version_path: str = ""
    task_type: int = Field(default=TaskType.FULL_SCAN.value, description="1 dev, 2 prd, 3 full scan")
    author_map_file: str = ""
    state: int = 0
    submitter: str | None = None
    parent_path: str | None = None
    created_by: str = ""

    @model_validator(mode="after")
    def validate_task_type(self) -> "TaskCreate":
        if self.copy_from_version.strip() in {"", "0", FULL_SCAN_BASE_VERSION}:
            self.task_type = TaskType.FULL_SCAN.value
        elif self.task_type not in TaskType.incremental_values():
            raise ValueError("incremental review requires task_type 1 (dev_version) or 2 (prd_version)")
        return self


class TaskResponse(BaseModel):
    id: str
    project_id: str
    review_version: str
    copy_from_version: str
    review_version_path: str
    copy_from_version_path: str
    author_map_file: str
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
    manual_retry_count: int
    dispatch_priority: int
    retry_failed_only: bool
    automatic_retry_pending: bool
    retry_requested_time: datetime | None
    next_retry_time: datetime | None
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
    latest_snapshot_id: str
    latest_snapshot_url: str
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
        latest_snapshot_id = task.latest_snapshot_id or ""
        latest_snapshot_url = ""
        if latest_snapshot_id:
            comparison = (
                f"{quote(task.review_version, safe='')}_vs_"
                f"{quote(task.copy_from_version, safe='')}"
            )
            latest_snapshot_url = (
                f"/snapshot/{quote(latest_snapshot_id, safe='')}/"
                f"{quote(task.project_id, safe='')}/{comparison}.html"
            )
        return cls(
            id=str(task.id),
            project_id=task.project_id,
            review_version=task.review_version,
            copy_from_version=task.copy_from_version,
            review_version_path=task.review_version_path or "",
            copy_from_version_path=task.copy_from_version_path or "",
            author_map_file=task.author_map_file or "",
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
            manual_retry_count=task.manual_retry_count or 0,
            dispatch_priority=task.dispatch_priority or 0,
            retry_failed_only=bool(task.retry_failed_only),
            automatic_retry_pending=bool(task.automatic_retry_pending),
            retry_requested_time=task.retry_requested_time,
            next_retry_time=task.next_retry_time,
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
            latest_snapshot_id=latest_snapshot_id,
            latest_snapshot_url=latest_snapshot_url,
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
    copy_from_version: str = FULL_SCAN_BASE_VERSION
    review_version_path: str
    copy_from_version_path: str = ""
    task_type: int | None = None
    author_map_file: str = ""
    submitter: str | None = None
    created_by: str = "jenkins"

    @model_validator(mode="after")
    def validate_task_type(self) -> "JenkinsTaskTrigger":
        if self.copy_from_version.strip() == FULL_SCAN_BASE_VERSION:
            self.task_type = TaskType.FULL_SCAN.value
        elif self.task_type not in TaskType.incremental_values():
            raise ValueError("incremental review requires task_type 1 (dev_version) or 2 (prd_version)")
        return self
