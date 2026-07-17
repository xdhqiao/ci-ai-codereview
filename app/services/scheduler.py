from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from threading import Event

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from mongoengine.queryset.visitor import Q

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
        self._active_dispatch_priority = 0
        self._active_lease_token = ""
        self._stop_event: Event | None = None

    def start(self) -> None:
        if self.scheduler.running:
            return
        self.scheduler.add_job(
            self._safe_poll,
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

    async def wait_for_shutdown(self, timeout_seconds: int) -> bool:
        active_future = self._active_future
        if active_future is None or active_future.done():
            return True
        try:
            await asyncio.wait_for(
                asyncio.shield(active_future),
                timeout=max(0, timeout_seconds),
            )
        except TimeoutError:
            logger.warning(
                "Review worker did not reach a shutdown checkpoint within %s seconds",
                timeout_seconds,
            )
            return False
        except asyncio.CancelledError:
            return True
        except Exception:
            logger.exception("Review worker failed while the scheduler was shutting down")
        return True

    async def run_once(self) -> None:
        await self._poll()

    def status(self) -> dict[str, object]:
        job = self.scheduler.get_job("code-review-task-dispatcher") if self.scheduler.running else None
        next_run_time = getattr(job, "next_run_time", None)
        return {
            "enabled": True,
            "running": self.scheduler.running,
            "active_task_id": self._active_task_id,
            "active_task_type": self._active_task_type,
            "active_dispatch_priority": self._active_dispatch_priority,
            "active_future_present": self._active_future is not None,
            "active_future_done": self._active_future.done() if self._active_future is not None else None,
            "active_lease_present": bool(self._active_lease_token),
            "stop_requested": bool(self._stop_event and self._stop_event.is_set()),
            "next_run_time": next_run_time.isoformat() if next_run_time else None,
        }

    async def _safe_poll(self) -> None:
        try:
            await self._poll()
        except Exception:
            logger.exception("Review scheduler poll failed; the next interval will retry")

    async def _poll(self) -> None:
        if self._active_future is not None:
            if not self._active_future.done():
                if await asyncio.to_thread(self._active_task_released_checkpoint):
                    detached = self._active_future
                    detached.add_done_callback(self._consume_detached_future)
                    logger.warning(
                        "Releasing scheduler slot for task %s after its database checkpoint released the lease",
                        self._active_task_id,
                    )
                    self._clear_active()
                else:
                    await asyncio.to_thread(self._heartbeat)
                    should_preempt = await asyncio.to_thread(self._has_higher_priority_task)
                    if should_preempt and self._stop_event is not None:
                        logger.info("Preempting task %s for a higher-priority task", self._active_task_id)
                        self._stop_event.set()
                    return
            else:
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
        self._active_dispatch_priority = int(task.dispatch_priority or 0)
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
            "-dispatch_priority",
            "task_type",
            "create_time",
        )
        for candidate in candidates:
            if not self._eligible(candidate, now):
                continue
            lease_token = str(uuid.uuid4())
            claim_query = Q(
                id=candidate.id,
                state=candidate.state,
            )
            revision_query = Q(trigger_revision=candidate.trigger_revision)
            if int(candidate.trigger_revision or 1) == 1:
                # Legacy tasks predate trigger_revision. MongoEngine exposes the
                # field default as 1, while MongoDB still has no stored field.
                revision_query |= Q(trigger_revision__exists=False)
            claim_query &= revision_query
            if candidate.dispatch_priority:
                claim_query &= Q(dispatch_priority=candidate.dispatch_priority)
            else:
                claim_query &= (Q(dispatch_priority=0) | Q(dispatch_priority__exists=False))
            if candidate.lease_token:
                claim_query &= Q(lease_token=candidate.lease_token)
            else:
                claim_query &= (Q(lease_token="") | Q(lease_token__exists=False))
            claimed = TaskModel.objects(claim_query).modify(
                new=True,
                set__state=1,
                set__completion_status="retry_running" if candidate.retry_failed_only else "running",
                set__lease_owner=self.worker_id,
                set__lease_token=lease_token,
                set__lease_expires_at=now + timedelta(seconds=max(10, self.settings.scheduler_lease_seconds)),
                set__heartbeat_time=now,
                set__last_start_time=now,
                set__automatic_retry_pending=False,
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
            if (
                not task.automatic_retry_pending
                or task.completion_status not in {"partial", "failed"}
                or not lease_expired
            ):
                return False
            return task.next_retry_time is None or not self._is_after(task.next_retry_time, now)
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

    def _active_task_released_checkpoint(self) -> bool:
        if not self._active_task_id or not self._active_lease_token:
            return False
        task = TaskModel.objects(id=self._active_task_id).only(
            "state",
            "completion_status",
            "lease_token",
        ).first()
        if task is None:
            return True
        if task.lease_token == self._active_lease_token:
            return False
        return task.state in {0, 2, 3} or task.completion_status in {
            "completed",
            "failed",
            "interrupted",
            "partial",
        }

    def _has_higher_priority_task(self) -> bool:
        now = utc_now()
        candidates = TaskModel.objects(task_type__in=[TASK_TYPE_INCREMENTAL, TASK_TYPE_FULL_SCAN]).order_by(
            "-dispatch_priority",
            "task_type",
            "create_time",
        )
        for task in candidates:
            if not self._eligible(task, now):
                continue
            candidate_priority = int(task.dispatch_priority or 0)
            if candidate_priority > self._active_dispatch_priority:
                return True
            if (
                candidate_priority == self._active_dispatch_priority
                and self._active_task_type == TASK_TYPE_FULL_SCAN
                and task.task_type == TASK_TYPE_INCREMENTAL
            ):
                return True
        return False

    def _has_waiting_incremental(self) -> bool:
        """Compatibility helper used by diagnostics and focused scheduler tests."""
        now = utc_now()
        return any(
            self._eligible(task, now)
            for task in TaskModel.objects(task_type=TASK_TYPE_INCREMENTAL).order_by("create_time")
        )

    def _clear_active(self) -> None:
        self._active_future = None
        self._active_task_id = ""
        self._active_task_type = 0
        self._active_dispatch_priority = 0
        self._active_lease_token = ""
        self._stop_event = None

    @staticmethod
    def _consume_detached_future(future: asyncio.Future[None]) -> None:
        try:
            future.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("Detached review worker failed after releasing its scheduler slot")

    @staticmethod
    def _is_expired(value: datetime, now: datetime) -> bool:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value <= now

    @staticmethod
    def _is_after(value: datetime, now: datetime) -> bool:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value > now
