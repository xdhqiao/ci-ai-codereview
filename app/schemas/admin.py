from datetime import datetime
from typing import Literal

from pydantic import BaseModel


AdminTaskSortField = Literal[
    "project_id",
    "review_version",
    "copy_from_version",
    "state",
    "task_type",
    "score",
    "critical_issue_count",
    "issue_count",
    "create_time",
]
SortOrder = Literal["asc", "desc"]


class AdminTaskItemResponse(BaseModel):
    task_id: str
    project_id: str
    review_version: str
    copy_from_version: str
    state: int
    task_type: int
    score: int
    highest_severity: int | None
    critical_issue_count: int
    issue_count: int
    create_time: datetime
    report_url: str


class AdminTaskPaginationResponse(BaseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class AdminTaskListResponse(BaseModel):
    items: list[AdminTaskItemResponse]
    pagination: AdminTaskPaginationResponse
    sort_by: AdminTaskSortField
    sort_order: SortOrder

