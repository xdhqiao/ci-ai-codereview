from __future__ import annotations

import logging

from app.common.constant import FULL_SCAN_BASE_VERSION, TaskType
from app.models.code_file import CodeFileModel
from app.models.code_file_snapshot import CodeFileSnapshotModel
from app.models.task import TaskModel
from app.models.task_snapshot import TaskSnapshotModel


logger = logging.getLogger("app.data_migration")


def migrate_legacy_task_types() -> dict[str, int]:
    """Idempotently move legacy full-scan rows from task_type=2 to task_type=3."""

    full_scan = TaskType.FULL_SCAN.value
    task_result = TaskModel.objects(
        copy_from_version=FULL_SCAN_BASE_VERSION,
        task_type__ne=full_scan,
    ).update(task_type=full_scan)
    task_ids = [
        str(task.id)
        for task in TaskModel.objects(copy_from_version=FULL_SCAN_BASE_VERSION).only("id")
    ]
    file_result = (
        CodeFileModel.objects(task_id__in=task_ids, task_type__ne=full_scan).update(task_type=full_scan)
        if task_ids
        else 0
    )
    snapshot_result = TaskSnapshotModel.objects(
        copy_from_version=FULL_SCAN_BASE_VERSION,
        task_type__ne=full_scan,
    ).update(task_type=full_scan)
    file_snapshot_result = CodeFileSnapshotModel.objects(
        copy_from_version=FULL_SCAN_BASE_VERSION,
        task_type__ne=full_scan,
    ).update(task_type=full_scan)
    counts = {
        "tasks": int(task_result or 0),
        "code_files": int(file_result or 0),
        "task_snapshots": int(snapshot_result or 0),
        "code_file_snapshots": int(file_snapshot_result or 0),
    }
    if any(counts.values()):
        logger.info("migrated legacy full-scan task types: %s", counts)
    return counts
