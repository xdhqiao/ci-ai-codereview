import asyncio
from datetime import datetime, timedelta, timezone

from app.core.config import Settings
from app.models.task import TaskModel
from app.services.scheduler import ReviewScheduler


def _task(project_id: str, task_type: int, state: int, created_at: datetime) -> TaskModel:
    return TaskModel(
        project_id=project_id,
        review_version="review",
        copy_from_version="master" if task_type == 1 else "0_version",
        task_type=task_type,
        state=state,
        trigger_revision=1,
        create_time=created_at,
    ).save()


def test_scheduler_prioritizes_incremental_then_fifo():
    now = datetime.now(timezone.utc)
    _task("full-old", 2, 0, now - timedelta(minutes=10))
    incremental_new = _task("incremental-new", 1, 0, now - timedelta(minutes=1))
    _task("incremental-old", 1, 0, now - timedelta(minutes=5))
    scheduler = ReviewScheduler(Settings(scheduler_lease_seconds=60))

    claimed = scheduler.claim_next_task()

    assert claimed is not None
    assert claimed.project_id == "incremental-old"
    assert claimed.task_type == 1
    assert claimed.state == 1
    assert claimed.lease_owner == scheduler.worker_id
    assert claimed.lease_token
    incremental_new.reload()
    assert incremental_new.state == 0


def test_scheduler_prioritizes_manual_failed_retry_above_incremental():
    now = datetime.now(timezone.utc)
    incremental = _task("incremental", 1, 0, now - timedelta(minutes=5))
    manual_full_retry = _task("manual-full-retry", 2, 0, now - timedelta(minutes=1))
    manual_full_retry.dispatch_priority = 100
    manual_full_retry.retry_failed_only = True
    manual_full_retry.completion_status = "retry_pending"
    manual_full_retry.save()
    scheduler = ReviewScheduler(Settings(scheduler_lease_seconds=60))

    claimed = scheduler.claim_next_task()

    assert claimed.id == manual_full_retry.id
    assert claimed.completion_status == "retry_running"
    assert incremental.reload().state == 0


def test_scheduler_waits_until_automatic_retry_backoff_expires():
    now = datetime.now(timezone.utc)
    task = _task("backoff", 1, 3, now - timedelta(minutes=1))
    task.retry_count = 1
    task.completion_status = "failed"
    task.automatic_retry_pending = True
    task.next_retry_time = now + timedelta(minutes=1)
    task.save()
    scheduler = ReviewScheduler(Settings())

    assert scheduler.claim_next_task() is None

    task.next_retry_time = now - timedelta(seconds=1)
    task.save()
    assert scheduler.claim_next_task().id == task.id


def test_scheduler_reclaims_stale_running_task():
    now = datetime.now(timezone.utc)
    stale = _task("stale", 1, 1, now - timedelta(minutes=5))
    stale.lease_owner = "dead-server"
    stale.lease_token = "old-token"
    stale.lease_expires_at = now - timedelta(seconds=1)
    stale.save()
    scheduler = ReviewScheduler(Settings(scheduler_lease_seconds=60))

    claimed = scheduler.claim_next_task()

    assert claimed is not None
    assert claimed.id == stale.id
    assert claimed.lease_owner == scheduler.worker_id
    assert claimed.lease_token != "old-token"


def test_scheduler_claims_pending_task_when_lease_field_is_missing():
    now = datetime.now(timezone.utc)
    pending = _task("missing-lease", 2, 0, now - timedelta(minutes=1))
    TaskModel._get_collection().update_one(
        {"_id": pending.id},
        {"$unset": {"lease_token": "", "lease_owner": "", "lease_expires_at": ""}},
    )
    scheduler = ReviewScheduler(Settings(scheduler_lease_seconds=60))

    claimed = scheduler.claim_next_task()

    assert claimed is not None
    assert claimed.id == pending.id
    assert claimed.state == 1
    assert claimed.lease_token


def test_scheduler_claims_manual_retry_when_legacy_trigger_revision_is_missing():
    now = datetime.now(timezone.utc)
    retry = _task("legacy-manual-retry", 2, 0, now - timedelta(minutes=1))
    retry.dispatch_priority = 100
    retry.retry_failed_only = True
    retry.completion_status = "retry_pending"
    retry.save()
    TaskModel._get_collection().update_one(
        {"_id": retry.id},
        {"$unset": {"trigger_revision": ""}},
    )
    scheduler = ReviewScheduler(Settings(scheduler_lease_seconds=60))

    claimed = scheduler.claim_next_task()

    assert claimed is not None
    assert claimed.id == retry.id
    assert claimed.state == 1
    assert claimed.completion_status == "retry_running"
    assert claimed.lease_token


def test_waiting_incremental_is_detected_for_full_scan_preemption():
    now = datetime.now(timezone.utc)
    _task("full", 2, 1, now - timedelta(minutes=2))
    _task("incremental", 1, 0, now - timedelta(minutes=1))

    scheduler = ReviewScheduler(Settings())

    assert scheduler._has_waiting_incremental() is True


def test_poll_releases_slot_when_worker_checkpoint_has_released_lease(monkeypatch):
    asyncio.run(_assert_poll_releases_slot_when_worker_checkpoint_has_released_lease(monkeypatch))


async def _assert_poll_releases_slot_when_worker_checkpoint_has_released_lease(monkeypatch):
    now = datetime.now(timezone.utc)
    completed = _task("completed", 1, 1, now - timedelta(minutes=2))
    completed.lease_owner = "server-old"
    completed.lease_token = "old-token"
    completed.lease_expires_at = now + timedelta(minutes=1)
    completed.save()

    scheduler = ReviewScheduler(Settings())
    worker = asyncio.get_running_loop().create_future()
    scheduler._active_future = worker
    scheduler._active_task_id = str(completed.id)
    scheduler._active_task_type = 1
    scheduler._active_lease_token = "old-token"

    completed.state = 2
    completed.completion_status = "completed"
    completed.lease_owner = ""
    completed.lease_token = ""
    completed.lease_expires_at = None
    completed.save()
    monkeypatch.setattr(scheduler, "claim_next_task", lambda: None)

    await scheduler._poll()

    assert scheduler._active_future is None
    assert scheduler._active_task_id == ""
    worker.set_result(None)
    await asyncio.sleep(0)


def test_safe_poll_keeps_scheduler_error_inside_tick(monkeypatch):
    asyncio.run(_assert_safe_poll_keeps_scheduler_error_inside_tick(monkeypatch))


async def _assert_safe_poll_keeps_scheduler_error_inside_tick(monkeypatch):
    scheduler = ReviewScheduler(Settings())

    async def fail_poll():
        raise RuntimeError("temporary database failure")

    monkeypatch.setattr(scheduler, "_poll", fail_poll)

    await scheduler._safe_poll()
