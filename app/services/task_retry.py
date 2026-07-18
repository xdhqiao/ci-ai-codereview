from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from mongoengine import ValidationError
from mongoengine.queryset.visitor import Q

from app.common.constant import MANUAL_RETRY_PRIORITY, ReviewState, TaskState
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError, NotFoundError
from app.models.code_file import CodeFileModel
from app.models.task import TaskModel


TASK_STATE_PENDING = TaskState.PENDING.value
TASK_STATE_RUNNING = TaskState.RUNNING.value
TASK_STATE_COMPLETED = TaskState.COMPLETED.value
TASK_STATE_PARTIAL = TaskState.PARTIAL.value
TASK_STATE_PREPARING = TaskState.PREPARING.value


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RetryableFailureSummary:
    file_num: int = 0
    block_num: int = 0
    pending_block_num: int = 0
    reviewing_block_num: int = 0

    @property
    def available(self) -> bool:
        return self.block_num > 0 and self.pending_block_num == 0 and self.reviewing_block_num == 0


def retryable_failure_summary(task_id: str) -> RetryableFailureSummary:
    file_num = 0
    block_num = 0
    pending_block_num = 0
    reviewing_block_num = 0
    for code_file in CodeFileModel.objects(task_id=task_id).only("code_blocks", "extra"):
        file_status = str((code_file.extra or {}).get("status") or "")
        if file_status == "skipped_budget":
            continue
        failed_blocks = 0
        for block in code_file.code_blocks:
            if block.failure_message or block.review_state == ReviewState.FAILED.value:
                failed_blocks += 1
            elif block.main_task_completed or block.review_state == ReviewState.COMPLETED.value or file_status in {"reviewed", "resumed"}:
                continue
            elif block.review_state == ReviewState.RUNNING.value:
                reviewing_block_num += 1
            else:
                pending_block_num += 1
        if failed_blocks:
            file_num += 1
            block_num += failed_blocks
    return RetryableFailureSummary(
        file_num=file_num,
        block_num=block_num,
        pending_block_num=pending_block_num,
        reviewing_block_num=reviewing_block_num,
    )


def automatic_retry_time(task: TaskModel, settings: Settings) -> datetime | None:
    retry_count = int(task.retry_count or 0)
    if retry_count >= max(1, settings.scheduler_max_task_retries):
        return None
    base_seconds = max(1, settings.scheduler_retry_backoff_seconds)
    max_seconds = max(base_seconds, settings.scheduler_retry_backoff_max_seconds)
    delay_seconds = min(max_seconds, base_seconds * (2 ** max(0, retry_count - 1)))
    return utc_now() + timedelta(seconds=delay_seconds)


class TaskRetryService:
    def request_failed_retry(self, task_id: str) -> TaskModel:
        try:
            task = TaskModel.objects(id=task_id).first()
        except (ValidationError, ValueError):
            task = None
        if task is None:
            raise NotFoundError("Task not found")

        if task.state == TASK_STATE_PENDING and task.retry_failed_only:
            return task
        if task.state in {TASK_STATE_RUNNING, TASK_STATE_PREPARING}:
            raise AppError(
                "Task is already running or preparing",
                status_code=409,
                code="task_retry_in_progress",
            )
        if task.state != TASK_STATE_PARTIAL:
            raise AppError(
                "Only a partial or failed task can retry failed blocks",
                status_code=409,
                code="task_not_retryable",
            )

        failures = retryable_failure_summary(str(task.id))
        if failures.block_num == 0:
            raise AppError(
                "No failed or incomplete code block is available for retry",
                status_code=409,
                code="no_retryable_failures",
            )
        if not failures.available:
            raise AppError(
                "Task still contains pending or reviewing code blocks",
                status_code=409,
                code="task_review_in_progress",
            )

        now = utc_now()
        lease_filter = Q(lease_token="") | Q(lease_token__exists=False)
        queued = TaskModel.objects(Q(id=task.id) & Q(state=TASK_STATE_PARTIAL) & lease_filter).modify(
            new=True,
            set__state=TASK_STATE_PENDING,
            set__completion_status="retry_pending",
            set__dispatch_priority=MANUAL_RETRY_PRIORITY,
            set__retry_failed_only=True,
            set__automatic_retry_pending=False,
            inc__manual_retry_count=1,
            set__retry_requested_time=now,
            unset__next_retry_time=1,
            set__interrupt_requested=False,
            set__update_time=now,
        )
        if queued is None:
            raise AppError(
                "Task state changed while requesting retry",
                status_code=409,
                code="task_retry_conflict",
            )
        return queued
