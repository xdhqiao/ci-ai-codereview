from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from threading import Event

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import Settings, get_settings
from app.models.task import TaskModel
from app.services.diff_service import TASK_TYPE_FULL_SCAN, TASK_TYPE_INCREMENTAL
from app.services.review_service import ReviewTaskService


logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ReviewScheduler:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.scheduler = AsyncIOScheduler()
        self.worker_id = f"server-{uuid.uuid4()}"
        self._active_future: asyncio.Task[None] | None = None
        self._active_task_id = ""
        self._active_task_type = 0
        self._active_lease_token = ""
        self._stop_event: Event | None = None

    def start(self) -> None:
        if self.scheduler.running:
            return
        self.scheduler.add_job(
            self._poll,
            "interval",
            seconds=max(1, self.settings.scheduler_interval_seconds),
            next_run_time=utc_now(),
            id="code-review-task-dispatcher",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.start()

    def shutdown(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    async def run_once(self) -> None:
        await self._poll()

    async def _poll(self) -> None:
        if self._active_future is not None:
            if not self._active_future.done():
                await asyncio.to_thread(self._heartbeat)
                if self._active_task_type == TASK_TYPE_FULL_SCAN:
                    incremental_waiting = await asyncio.to_thread(self._has_waiting_incremental)
                    if incremental_waiting and self._stop_event is not None:
                        logger.info("Preempting full scan task %s for an incremental task", self._active_task_id)
                        self._stop_event.set()
                return
            try:
                self._active_future.result()
            except Exception:
                logger.exception("Review worker failed for task %s", self._active_task_id)
            self._clear_active()

        task = await asyncio.to_thread(self.claim_next_task)
        if task is None:
            return
        self._active_task_id = str(task.id)
        self._active_task_type = int(task.task_type or 0)
        self._active_lease_token = task.lease_token or ""
        self._stop_event = Event()
        self._active_future = asyncio.create_task(self._run_claimed_task(task, self._stop_event))

    async def _run_claimed_task(self, task: TaskModel, stop_event: Event) -> None:
        service = ReviewTaskService(
            self.settings,
            stop_event=stop_event,
            lease_token=task.lease_token or "",
        )
        await asyncio.to_thread(service.review_task, task)

    def claim_next_task(self) -> TaskModel | None:
        now = utc_now()
        candidates = TaskModel.objects(task_type__in=[TASK_TYPE_INCREMENTAL, TASK_TYPE_FULL_SCAN]).order_by(
            "task_type",
            "create_time",
        )
        for candidate in candidates:
            if not self._eligible(candidate, now):
                continue
            lease_token = str(uuid.uuid4())
            claimed = TaskModel.objects(
                id=candidate.id,
                state=candidate.state,
                trigger_revision=candidate.trigger_revision,
                lease_token=candidate.lease_token,
            ).modify(
                new=True,
                set__state=1,
                set__completion_status="running",
                set__lease_owner=self.worker_id,
                set__lease_token=lease_token,
                set__lease_expires_at=now + timedelta(seconds=max(10, self.settings.scheduler_lease_seconds)),
                set__heartbeat_time=now,
                set__last_start_time=now,
                set__interrupt_requested=False,
                set__update_time=now,
            )
            if claimed is not None:
                return claimed
        return None

    def _eligible(self, task: TaskModel, now: datetime) -> bool:
        lease_expired = not task.lease_token or task.lease_expires_at is None or self._is_expired(task.lease_expires_at, now)
        if task.state == 0:
            return lease_expired
        if task.state == 1:
            return lease_expired
        if task.state == 3 and (task.retry_count or 0) < max(1, self.settings.scheduler_max_task_retries):
            return task.completion_status in {"partial", "interrupted", "failed"} and lease_expired
        return False

    def _heartbeat(self) -> None:
        if not self._active_task_id or not self._active_lease_token:
            return
        now = utc_now()
        TaskModel.objects(
            id=self._active_task_id,
            lease_token=self._active_lease_token,
        ).update_one(
            set__heartbeat_time=now,
            set__lease_expires_at=now + timedelta(seconds=max(10, self.settings.scheduler_lease_seconds)),
            set__update_time=now,
        )

    def _has_waiting_incremental(self) -> bool:
        now = utc_now()
        for task in TaskModel.objects(task_type=TASK_TYPE_INCREMENTAL).order_by("create_time"):
            if self._eligible(task, now):
                return True
        return False

    def _clear_active(self) -> None:
        self._active_future = None
        self._active_task_id = ""
        self._active_task_type = 0
        self._active_lease_token = ""
        self._stop_event = None

    @staticmethod
    def _is_expired(value: datetime, now: datetime) -> bool:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value <= now
