from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from app.common.constant import (
    SEVERE_ISSUE_SEVERITY,
    TASK_TYPE_DISPLAY_NAMES,
    FeedbackType,
    ReviewState,
)
from app.core.exceptions import AppError
from app.models.code_file import CodeFileModel
from app.models.issue_feedback_log import IssueFeedbackLog
from app.models.task import TaskModel
from app.schemas.dashboard import (
    DashboardFeedbackResponse,
    DashboardIssueResponse,
    DashboardResourceResponse,
    DashboardResponse,
    DashboardTaskSummaryResponse,
    DashboardTaskTypeResponse,
)


class DashboardService:
    DEFAULT_RANGE_DAYS = 30

    def report(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
    ) -> DashboardResponse:
        resolved_start, resolved_end = self._resolve_dates(start_date, end_date)
        start, exclusive_end = self._datetime_range(resolved_start, resolved_end)
        tasks = list(
            TaskModel.objects(create_time__gte=start, create_time__lt=exclusive_end).only(
                "project_id",
                "task_type",
                "llm_prompt_tokens",
                "llm_completion_tokens",
                "llm_total_tokens",
                "llm_elapsed_ms",
                "task_model_rounds",
            )
        )

        task_ids = [str(task.id) for task in tasks]
        file_metrics = self._file_metrics(task_ids)
        type_counts = Counter(task.task_type for task in tasks)
        task_type_items = [
            DashboardTaskTypeResponse(
                task_type=task_type,
                label=TASK_TYPE_DISPLAY_NAMES.get(task_type, "未分类"),
                count=type_counts[task_type],
            )
            for task_type in self._ordered_task_types(type_counts)
        ]

        historical_query = IssueFeedbackLog.objects(
            create_time__gte=start,
            create_time__lt=exclusive_end,
        )
        historical_feedback_count = historical_query.count()
        historical_agree_count = historical_query.filter(
            feedback_type=FeedbackType.AGREE.value
        ).count()

        prompt_tokens = sum(int(task.llm_prompt_tokens or 0) for task in tasks)
        completion_tokens = sum(int(task.llm_completion_tokens or 0) for task in tasks)
        total_tokens = sum(
            int(task.llm_total_tokens or 0)
            or (
                int(task.llm_prompt_tokens or 0)
                + int(task.llm_completion_tokens or 0)
            )
            for task in tasks
        )

        return DashboardResponse(
            start_date=resolved_start,
            end_date=resolved_end,
            tasks=DashboardTaskSummaryResponse(
                task_count=len(tasks),
                project_count=len({task.project_id for task in tasks}),
                task_types=task_type_items,
            ),
            resources=DashboardResourceResponse(
                total_tokens=total_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                llm_elapsed_ms=sum(int(task.llm_elapsed_ms or 0) for task in tasks),
                file_count=file_metrics["file_count"],
                reviewed_file_count=file_metrics["reviewed_file_count"],
                tool_call_count=file_metrics["tool_call_count"],
                model_round_count=(
                    sum(len(task.task_model_rounds or []) for task in tasks)
                    + file_metrics["model_round_count"]
                ),
            ),
            issues=DashboardIssueResponse(
                valid_issue_count=file_metrics["valid_issue_count"],
                filtered_issue_count=file_metrics["filtered_issue_count"],
                severe_issue_count=file_metrics["severe_issue_count"],
            ),
            feedback=DashboardFeedbackResponse(
                feedback_count=file_metrics["feedback_count"],
                agree_count=file_metrics["agree_count"],
                agree_rate=self._percent(
                    file_metrics["agree_count"],
                    file_metrics["feedback_count"],
                ),
                historical_feedback_count=historical_feedback_count,
                historical_agree_count=historical_agree_count,
                historical_agree_rate=self._percent(
                    historical_agree_count,
                    historical_feedback_count,
                ),
            ),
        )

    def _file_metrics(self, task_ids: list[str]) -> dict[str, int]:
        metrics = {
            "file_count": 0,
            "reviewed_file_count": 0,
            "tool_call_count": 0,
            "model_round_count": 0,
            "valid_issue_count": 0,
            "filtered_issue_count": 0,
            "severe_issue_count": 0,
            "feedback_count": 0,
            "agree_count": 0,
        }
        if not task_ids:
            return metrics

        projection = {
            "state": 1,
            "extra.status": 1,
            "code_blocks.main_task_completed": 1,
            "code_blocks.review_state": 1,
            "code_blocks.failure_message": 1,
            "code_blocks.model_rounds": 1,
            "code_blocks.tool_calls": 1,
            "code_blocks.issues.severity": 1,
            "code_blocks.issues.filter_status": 1,
            "code_blocks.issues.feedback_type": 1,
        }
        cursor = CodeFileModel._get_collection().find(
            {"task_id": {"$in": task_ids}},
            projection,
        )
        for code_file in cursor:
            metrics["file_count"] += 1
            if self._file_status(code_file) == "completed":
                metrics["reviewed_file_count"] += 1
            for block in code_file.get("code_blocks") or []:
                metrics["tool_call_count"] += len(block.get("tool_calls") or [])
                metrics["model_round_count"] += len(block.get("model_rounds") or [])
                for issue in block.get("issues") or []:
                    if self._is_filtered(issue):
                        metrics["filtered_issue_count"] += 1
                        continue
                    metrics["valid_issue_count"] += 1
                    if int(issue.get("severity") or 0) == SEVERE_ISSUE_SEVERITY:
                        metrics["severe_issue_count"] += 1
                    feedback_type = str(issue.get("feedback_type") or "").lower()
                    if feedback_type not in {
                        FeedbackType.AGREE.value,
                        FeedbackType.REJECT.value,
                    }:
                        continue
                    metrics["feedback_count"] += 1
                    if feedback_type == FeedbackType.AGREE.value:
                        metrics["agree_count"] += 1
        return metrics

    def _file_status(self, code_file: dict[str, Any]) -> str:
        statuses = [
            self._block_status(block, code_file)
            for block in (code_file.get("code_blocks") or [])
        ]
        extra_status = str((code_file.get("extra") or {}).get("status") or "")
        if extra_status == "skipped_budget":
            return "failed"
        if statuses and all(status == "completed" for status in statuses):
            return "completed"
        if code_file.get("state") == ReviewState.RUNNING or "reviewing" in statuses:
            return "reviewing"
        if (
            code_file.get("state") == ReviewState.FAILED
            or "failed" in statuses
            or extra_status == "partial"
        ):
            return "failed"
        return "pending"

    @staticmethod
    def _block_status(block: dict[str, Any], code_file: dict[str, Any]) -> str:
        if block.get("failure_message") or block.get("review_state") == ReviewState.FAILED:
            return "failed"
        if (
            block.get("main_task_completed")
            or block.get("review_state") == ReviewState.COMPLETED
        ):
            return "completed"
        file_status = str((code_file.get("extra") or {}).get("status") or "")
        if (
            code_file.get("state") == ReviewState.COMPLETED
            or file_status in {"reviewed", "resumed"}
        ):
            return "completed"
        if (
            code_file.get("state") == ReviewState.RUNNING
            or block.get("review_state") == ReviewState.RUNNING
        ):
            return "reviewing"
        return "pending"

    @staticmethod
    def _is_filtered(issue: dict[str, Any]) -> bool:
        return str(issue.get("filter_status") or "").lower() == "filtered"

    @staticmethod
    def _ordered_task_types(type_counts: Counter) -> list[int | None]:
        known = [task_type for task_type in TASK_TYPE_DISPLAY_NAMES if task_type in type_counts]
        unknown = sorted(
            (task_type for task_type in type_counts if task_type not in TASK_TYPE_DISPLAY_NAMES),
            key=lambda value: (value is None, value if value is not None else 0),
        )
        return [*known, *unknown]

    def _resolve_dates(
        self,
        start_date: date | None,
        end_date: date | None,
    ) -> tuple[date, date]:
        today = datetime.now(timezone.utc).date()
        resolved_end = end_date or today
        resolved_start = start_date or (resolved_end - timedelta(days=self.DEFAULT_RANGE_DAYS - 1))
        if resolved_start > resolved_end:
            raise AppError("start_date must be before or equal to end_date", status_code=422)
        return resolved_start, resolved_end

    @staticmethod
    def _datetime_range(start_date: date, end_date: date) -> tuple[datetime, datetime]:
        start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
        exclusive_end = datetime.combine(
            end_date + timedelta(days=1),
            time.min,
            tzinfo=timezone.utc,
        )
        return start, exclusive_end

    @staticmethod
    def _percent(numerator: int, denominator: int) -> float:
        return round(numerator * 100 / denominator, 1) if denominator else 0.0
