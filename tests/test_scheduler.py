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


def test_waiting_incremental_is_detected_for_full_scan_preemption():
    now = datetime.now(timezone.utc)
    _task("full", 2, 1, now - timedelta(minutes=2))
    _task("incremental", 1, 0, now - timedelta(minutes=1))

    scheduler = ReviewScheduler(Settings())

    assert scheduler._has_waiting_incremental() is True
