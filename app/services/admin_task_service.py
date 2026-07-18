from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote

from app.common.constant import SEVERE_ISSUE_SEVERITY
from app.core.exceptions import AppError
from app.models.code_file import CodeFileModel
from app.models.task import TaskModel
from app.schemas.admin import (
    AdminTaskItemResponse,
    AdminTaskListResponse,
    AdminTaskPaginationResponse,
    AdminTaskSortField,
    SortOrder,
)


TASK_FIELDS = (
    "project_id",
    "review_version",
    "copy_from_version",
    "state",
    "task_type",
    "score",
    "comment_line_number",
    "developer_issue_summary",
    "create_time",
)
DATABASE_SORT_FIELDS = {
    "project_id": "project_id",
    "review_version": "review_version",
    "copy_from_version": "copy_from_version",
    "state": "state",
    "task_type": "task_type",
    "score": "score",
    "create_time": "create_time",
}
DERIVED_SORT_FIELDS = {"critical_issue_count", "issue_count"}


@dataclass(frozen=True)
class TaskIssueStats:
    issue_count: int = 0
    highest_severity: int | None = None
    critical_issue_count: int = 0


class AdminTaskService:
    def list_tasks(
        self,
        *,
        project_id: str = "",
        review_version: str = "",
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        task_type: int | None = None,
        state: int | None = None,
        sort_by: AdminTaskSortField = "create_time",
        sort_order: SortOrder = "desc",
        page: int = 1,
        page_size: int = 20,
    ) -> AdminTaskListResponse:
        normalized_from = self._normalize_datetime(date_from)
        normalized_to = self._normalize_datetime(date_to)
        if normalized_from and normalized_to and normalized_from > normalized_to:
            raise AppError(
                "date_from must be earlier than or equal to date_to",
                status_code=422,
                code="invalid_date_range",
            )

        query = TaskModel.objects
        project_search = project_id.strip()
        version_search = review_version.strip()
        if project_search:
            query = query.filter(project_id=re.compile(re.escape(project_search), re.IGNORECASE))
        if version_search:
            query = query.filter(review_version=re.compile(re.escape(version_search), re.IGNORECASE))
        if normalized_from:
            query = query.filter(create_time__gte=normalized_from)
        if normalized_to:
            query = query.filter(create_time__lte=normalized_to)
        if task_type is not None:
            query = query.filter(task_type=task_type)
        if state is not None:
            query = query.filter(state=state)

        total_items = query.count()
        total_pages = math.ceil(total_items / page_size) if total_items else 0
        normalized_page = min(page, total_pages) if total_pages else 1
        offset = (normalized_page - 1) * page_size

        if sort_by in DERIVED_SORT_FIELDS:
            matching_tasks = list(query.only(*TASK_FIELDS).order_by("-create_time"))
            issue_stats = self._issue_stats(matching_tasks)
            matching_tasks.sort(
                key=lambda task: self._derived_sort_value(task, issue_stats, sort_by),
                reverse=sort_order == "desc",
            )
            page_tasks = matching_tasks[offset : offset + page_size]
        else:
            direction = "-" if sort_order == "desc" else "+"
            order_fields = [f"{direction}{DATABASE_SORT_FIELDS[sort_by]}"]
            if sort_by != "create_time":
                order_fields.append("-create_time")
            page_tasks = list(
                query.only(*TASK_FIELDS)
                .order_by(*order_fields)
                .skip(offset)
                .limit(page_size)
            )
            issue_stats = self._issue_stats(page_tasks)

        return AdminTaskListResponse(
            items=[self._task_response(task, issue_stats.get(str(task.id), TaskIssueStats())) for task in page_tasks],
            pagination=AdminTaskPaginationResponse(
                page=normalized_page,
                page_size=page_size,
                total_items=total_items,
                total_pages=total_pages,
            ),
            sort_by=sort_by,
            sort_order=sort_order,
        )

    def _issue_stats(self, tasks: list[TaskModel]) -> dict[str, TaskIssueStats]:
        result: dict[str, TaskIssueStats] = {}
        aggregate_task_ids: list[str] = []
        for task in tasks:
            task_id = str(task.id)
            stored = self._stored_issue_stats(task)
            if stored is None:
                aggregate_task_ids.append(task_id)
            else:
                result[task_id] = stored

        if not aggregate_task_ids:
            return result

        severity_counts: dict[str, dict[int, int]] = {task_id: {} for task_id in aggregate_task_ids}
        pipeline = [
            {"$match": {"task_id": {"$in": aggregate_task_ids}}},
            {"$unwind": "$code_blocks"},
            {"$unwind": "$code_blocks.issues"},
            {
                "$group": {
                    "_id": {
                        "task_id": "$task_id",
                        "severity": {"$ifNull": ["$code_blocks.issues.severity", 0]},
                        "filter_status": {"$ifNull": ["$code_blocks.issues.filter_status", ""]},
                    },
                    "count": {"$sum": 1},
                }
            },
        ]
        for group in CodeFileModel._get_collection().aggregate(pipeline):
            key = group.get("_id") or {}
            task_id = str(key.get("task_id") or "")
            if task_id not in severity_counts:
                continue
            if str(key.get("filter_status") or "").lower() == "filtered":
                continue
            try:
                severity = int(key.get("severity") or 0)
                count = int(group.get("count") or 0)
            except (TypeError, ValueError):
                continue
            severity_counts[task_id][severity] = severity_counts[task_id].get(severity, 0) + count

        for task_id, counts in severity_counts.items():
            result[task_id] = self._stats_from_counts(counts)
        return result

    def _stored_issue_stats(self, task: TaskModel) -> TaskIssueStats | None:
        if task.state not in {2, 3}:
            return None
        summary = task.developer_issue_summary or {}
        if "_severity" not in summary:
            return None
        raw_counts = summary.get("_severity")
        if not isinstance(raw_counts, dict):
            return None
        counts: dict[int, int] = {}
        try:
            for severity, count in raw_counts.items():
                normalized_count = max(0, int(count or 0))
                if normalized_count:
                    normalized_severity = int(severity or 0)
                    counts[normalized_severity] = counts.get(normalized_severity, 0) + normalized_count
        except (TypeError, ValueError):
            return None
        return self._stats_from_counts(counts)

    def _stats_from_counts(self, counts: dict[int, int]) -> TaskIssueStats:
        issue_count = sum(counts.values())
        if not issue_count:
            return TaskIssueStats()
        highest_severity = max(counts)
        return TaskIssueStats(
            issue_count=issue_count,
            highest_severity=highest_severity,
            critical_issue_count=counts.get(SEVERE_ISSUE_SEVERITY, 0),
        )

    def _derived_sort_value(
        self,
        task: TaskModel,
        issue_stats: dict[str, TaskIssueStats],
        sort_by: AdminTaskSortField,
    ) -> int:
        stats = issue_stats.get(str(task.id), TaskIssueStats())
        if sort_by == "critical_issue_count":
            return stats.critical_issue_count
        return stats.issue_count

    def _task_response(self, task: TaskModel, stats: TaskIssueStats) -> AdminTaskItemResponse:
        project_id = task.project_id or ""
        review_version = task.review_version or ""
        copy_from_version = task.copy_from_version or ""
        comparison = f"{quote(review_version, safe='')}_vs_{quote(copy_from_version, safe='')}.html"
        return AdminTaskItemResponse(
            task_id=str(task.id),
            project_id=project_id,
            review_version=review_version,
            copy_from_version=copy_from_version,
            state=int(task.state or 0),
            task_type=int(task.task_type or 0),
            score=min(100, max(0, int(task.score or 0))),
            highest_severity=stats.highest_severity,
            critical_issue_count=stats.critical_issue_count,
            issue_count=stats.issue_count,
            create_time=task.create_time,
            report_url=f"/{quote(project_id, safe='')}/{comparison}",
        )

    def _normalize_datetime(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
