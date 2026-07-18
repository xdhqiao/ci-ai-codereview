from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import quote, urlencode

from app.common.constant import (
    EMPTY_FILE_AUTHOR_DISPLAY_NAME,
    EMPTY_FILE_AUTHOR_QUERY_VALUE,
    FeedbackType,
    SEVERE_ISSUE_SEVERITY,
    TaskType,
)
from app.common.utils import get_user_display_name
from app.core.exceptions import AppError
from app.models.code_file import CodeFileModel
from app.models.task import TaskModel
from app.schemas.feedback_report import (
    AdminFeedbackReportResponse,
    AuthorIssueItemResponse,
    AuthorIssueReportResponse,
    AuthorIssueSummaryResponse,
    FeedbackAuthorItemResponse,
    FeedbackPaginationResponse,
    FeedbackSummaryResponse,
    FeedbackTaskItemResponse,
    FeedbackView,
)


@dataclass
class IssueCounters:
    issue_count: int = 0
    feedback_count: int = 0
    severe_count: int = 0
    severe_feedback_count: int = 0
    severe_agree_count: int = 0
    severe_reject_count: int = 0

    def add(self, severity: int, feedback_type: str) -> None:
        self.issue_count += 1
        feedback = feedback_type in {FeedbackType.AGREE.value, FeedbackType.REJECT.value}
        if feedback:
            self.feedback_count += 1
        if severity != SEVERE_ISSUE_SEVERITY:
            return
        self.severe_count += 1
        if feedback:
            self.severe_feedback_count += 1
        if feedback_type == FeedbackType.AGREE.value:
            self.severe_agree_count += 1
        elif feedback_type == FeedbackType.REJECT.value:
            self.severe_reject_count += 1


class FeedbackReportService:
    VIEW_TASK_TYPES = {
        "prd_version": TaskType.PRD_VERSION.value,
        "full_scan": TaskType.FULL_SCAN.value,
        "author_prd": TaskType.PRD_VERSION.value,
        "author_full": TaskType.FULL_SCAN.value,
    }

    def admin_report(
        self,
        *,
        view: FeedbackView,
        start_date: date | None,
        end_date: date | None,
        page: int,
        page_size: int,
    ) -> AdminFeedbackReportResponse:
        task_type = self.VIEW_TASK_TYPES[view]
        tasks = self._tasks(task_type, start_date, end_date)
        task_ids = [str(task.id) for task in tasks]
        task_by_id = {str(task.id): task for task in tasks}
        task_counters = {task_id: IssueCounters() for task_id in task_ids}
        author_counters: dict[str, IssueCounters] = {}
        summary_counters = IssueCounters()
        severity_distribution = {str(level): 0 for level in range(1, 6)}

        for row in self._issue_rows(task_ids):
            if str(row.get("filter_status") or "").lower() == "filtered":
                continue
            task_id = str(row.get("task_id") or "")
            if task_id not in task_by_id:
                continue
            severity = self._integer(row.get("severity"))
            feedback_type = str(row.get("feedback_type") or "")
            file_author = str(row.get("file_author") or "").strip()
            task_counters[task_id].add(severity, feedback_type)
            summary_counters.add(severity, feedback_type)
            if str(severity) in severity_distribution:
                severity_distribution[str(severity)] += 1
            author_counters.setdefault(file_author, IssueCounters()).add(severity, feedback_type)

        authors = self._authors(task_ids)
        for author in authors:
            author_counters.setdefault(author, IssueCounters())
        summary = self._summary(tasks, authors, summary_counters, severity_distribution)

        if view in {"prd_version", "full_scan"}:
            all_items = [self._task_item(task, task_counters[str(task.id)]) for task in tasks]
            page_items, pagination = self._paginate(all_items, page, page_size)
            return AdminFeedbackReportResponse(
                view=view,
                task_type=task_type,
                start_date=start_date,
                end_date=end_date,
                summary=summary,
                pagination=pagination,
                task_items=page_items,
                author_items=[],
            )

        all_author_items = [
            self._author_item(
                author,
                author_counters[author],
                task_type=task_type,
                start_date=start_date,
                end_date=end_date,
            )
            for author in sorted(authors, key=lambda value: (self._author_display_name(value), value))
        ]
        page_items, pagination = self._paginate(all_author_items, page, page_size)
        return AdminFeedbackReportResponse(
            view=view,
            task_type=task_type,
            start_date=start_date,
            end_date=end_date,
            summary=summary,
            pagination=pagination,
            task_items=[],
            author_items=page_items,
        )

    def author_report(
        self,
        *,
        author_name: str,
        file_author: str,
        task_type: int,
        start_date: date | None,
        end_date: date | None,
        page: int,
        page_size: int,
    ) -> AuthorIssueReportResponse:
        if task_type not in {TaskType.PRD_VERSION.value, TaskType.FULL_SCAN.value}:
            raise AppError("task_type must be 2 or 3", status_code=422, code="invalid_task_type")
        account_token = file_author.strip()
        if not account_token:
            raise AppError("file_author is required", status_code=422, code="validation_error")
        account = "" if account_token == EMPTY_FILE_AUTHOR_QUERY_VALUE else account_token
        tasks = self._tasks(task_type, start_date, end_date)
        task_ids = [str(task.id) for task in tasks]
        if not task_ids:
            code_files = []
        elif account:
            code_files = list(
                CodeFileModel.objects(task_id__in=task_ids, file_author=account).order_by("file_name")
            )
        else:
            code_files = list(
                CodeFileModel.objects(
                    task_id__in=task_ids,
                    __raw__={
                        "$or": [
                            {"file_author": {"$exists": False}},
                            {"file_author": None},
                            {"file_author": {"$regex": r"^\s*$"}},
                        ]
                    },
                ).order_by("file_name")
            )
        counters = IssueCounters()
        items: list[AuthorIssueItemResponse] = []
        for code_file in code_files:
            for block in code_file.code_blocks:
                for issue in block.issues:
                    if (issue.filter_status or "").lower() == "filtered":
                        continue
                    severity = int(issue.severity or 0)
                    feedback_type = issue.feedback_type or ""
                    counters.add(severity, feedback_type)
                    items.append(
                        AuthorIssueItemResponse(
                            file_id=str(code_file.id),
                            block_id=block.block_id,
                            issue_id=issue.issue_id if issue.issue_id is not None else 0,
                            file_name=code_file.file_name,
                            severity=severity,
                            issue_line_numbers=issue.issue_line_numbers or "",
                            issue_type=issue.type or "",
                            description=issue.description or "",
                            suggestion=issue.suggestion or "",
                            contents=list(block.contents or []),
                            feedback_type=feedback_type,
                            feedback_content=issue.feedback_content or "",
                        )
                    )
        items.sort(key=lambda item: (-item.severity, item.file_name, item.block_id, item.issue_id))
        page_items, pagination = self._paginate(items, page, page_size)
        display_name = self._author_display_name(account)
        return AuthorIssueReportResponse(
            file_author=account,
            author_name=display_name or author_name,
            task_type=task_type,
            start_date=start_date,
            end_date=end_date,
            summary=AuthorIssueSummaryResponse(
                severe_issue_count=counters.severe_count,
                issue_count=counters.issue_count,
                severe_feedback_rate=self._percent(counters.severe_feedback_count, counters.severe_count),
                severe_agree_rate=self._percent(counters.severe_agree_count, counters.severe_feedback_count),
                issue_feedback_rate=self._percent(counters.feedback_count, counters.issue_count),
                file_count=len(code_files),
            ),
            pagination=pagination,
            items=page_items,
        )

    def _tasks(self, task_type: int, start_date: date | None, end_date: date | None) -> list[TaskModel]:
        if start_date and end_date and start_date > end_date:
            raise AppError("start_date must be before or equal to end_date", status_code=422)
        query = TaskModel.objects(task_type=task_type)
        if start_date:
            query = query(create_time__gte=datetime.combine(start_date, time.min, tzinfo=timezone.utc))
        if end_date:
            exclusive_end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
            query = query(create_time__lt=exclusive_end)
        return list(query.order_by("-create_time"))

    @staticmethod
    def _issue_rows(task_ids: list[str]) -> list[dict]:
        if not task_ids:
            return []
        pipeline = [
            {"$match": {"task_id": {"$in": task_ids}}},
            {"$unwind": "$code_blocks"},
            {"$unwind": "$code_blocks.issues"},
            {
                "$project": {
                    "_id": 0,
                    "task_id": 1,
                    "file_author": {"$ifNull": ["$file_author", ""]},
                    "severity": {"$ifNull": ["$code_blocks.issues.severity", 0]},
                    "feedback_type": {"$ifNull": ["$code_blocks.issues.feedback_type", ""]},
                    "filter_status": {"$ifNull": ["$code_blocks.issues.filter_status", ""]},
                }
            },
        ]
        return list(CodeFileModel._get_collection().aggregate(pipeline))

    @staticmethod
    def _authors(task_ids: list[str]) -> set[str]:
        if not task_ids:
            return set()
        return {
            str(value or "").strip()
            for value in CodeFileModel.objects(task_id__in=task_ids).distinct("file_author")
        }

    def _summary(
        self,
        tasks: list[TaskModel],
        authors: set[str],
        counters: IssueCounters,
        severity_distribution: dict[str, int],
    ) -> FeedbackSummaryResponse:
        return FeedbackSummaryResponse(
            project_count=len({task.project_id for task in tasks}),
            version_count=len({(task.project_id, task.review_version) for task in tasks}),
            author_count=len(authors),
            severe_issue_count=counters.severe_count,
            severe_feedback_count=counters.severe_feedback_count,
            severe_feedback_rate=self._percent(counters.severe_feedback_count, counters.severe_count),
            severe_agree_count=counters.severe_agree_count,
            severe_reject_count=counters.severe_reject_count,
            severe_agree_rate=self._percent(counters.severe_agree_count, counters.severe_feedback_count),
            issue_count=counters.issue_count,
            issue_feedback_count=counters.feedback_count,
            issue_feedback_rate=self._percent(counters.feedback_count, counters.issue_count),
            severity_distribution=severity_distribution,
        )

    def _task_item(self, task: TaskModel, counters: IssueCounters) -> FeedbackTaskItemResponse:
        comparison = f"{quote(task.review_version, safe='')}_vs_{quote(task.copy_from_version, safe='')}.html"
        return FeedbackTaskItemResponse(
            task_id=str(task.id),
            project_id=task.project_id,
            review_version=task.review_version,
            copy_from_version=task.copy_from_version,
            severe_issue_count=counters.severe_count,
            severe_feedback_rate=self._percent(counters.severe_feedback_count, counters.severe_count),
            severe_agree_rate=self._percent(counters.severe_agree_count, counters.severe_feedback_count),
            issue_count=counters.issue_count,
            issue_feedback_rate=self._percent(counters.feedback_count, counters.issue_count),
            create_time=task.create_time,
            report_url=f"/{quote(task.project_id, safe='')}/{comparison}",
        )

    def _author_item(
        self,
        author: str,
        counters: IssueCounters,
        *,
        task_type: int,
        start_date: date | None,
        end_date: date | None,
    ) -> FeedbackAuthorItemResponse:
        author_name = self._author_display_name(author)
        query_author = author or EMPTY_FILE_AUTHOR_QUERY_VALUE
        query = urlencode(
            {
                key: value
                for key, value in {
                    "start_date": start_date.isoformat() if start_date else "",
                    "end_date": end_date.isoformat() if end_date else "",
                    "file_author": query_author,
                    "task_type": task_type,
                }.items()
                if value != ""
            }
        )
        return FeedbackAuthorItemResponse(
            file_author=author,
            author_name=author_name,
            severe_issue_count=counters.severe_count,
            severe_feedback_rate=self._percent(counters.severe_feedback_count, counters.severe_count),
            severe_agree_rate=self._percent(counters.severe_agree_count, counters.severe_feedback_count),
            issue_count=counters.issue_count,
            issue_feedback_rate=self._percent(counters.feedback_count, counters.issue_count),
            report_url=f"/author/{quote(author_name, safe='')}/issue_report.html?{query}",
        )

    @staticmethod
    def _author_display_name(author: str) -> str:
        return get_user_display_name(author) if author else EMPTY_FILE_AUTHOR_DISPLAY_NAME

    @staticmethod
    def _paginate(items: list, page: int, page_size: int) -> tuple[list, FeedbackPaginationResponse]:
        total_items = len(items)
        total_pages = math.ceil(total_items / page_size) if total_items else 0
        normalized_page = min(page, total_pages) if total_pages else 1
        start = (normalized_page - 1) * page_size
        return items[start : start + page_size], FeedbackPaginationResponse(
            page=normalized_page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
        )

    @staticmethod
    def _percent(numerator: int, denominator: int) -> float:
        return round(numerator * 100 / denominator, 1) if denominator else 0.0

    @staticmethod
    def _integer(value: object) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
