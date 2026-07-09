from datetime import datetime

from pydantic import BaseModel, Field

from app.models.task import TaskModel


class TaskCreate(BaseModel):
    project_id: str
    review_version: str
    copy_from_version: str = ""
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
    add_code_line_num: int
    comment_line_number: int
    process_time: int
    parent_path: str | None
    developer_issue_summary: dict
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
            add_code_line_num=task.add_code_line_num or 0,
            comment_line_number=task.comment_line_number or 0,
            process_time=task.process_time or 0,
            parent_path=task.parent_path,
            developer_issue_summary=task.developer_issue_summary or {},
            created_by=task.created_by or "",
            create_time=task.create_time,
            updated_by=task.updated_by or "",
            update_time=task.update_time,
        )


class TaskListResponse(BaseModel):
    items: list[TaskResponse]
    total: int
