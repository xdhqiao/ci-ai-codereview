from app.common.constant import TaskType
from app.models.code_file import CodeFileModel
from app.models.code_file_snapshot import CodeFileSnapshotModel
from app.models.task import TaskModel
from app.models.task_snapshot import TaskSnapshotModel
from app.services.data_migration import migrate_legacy_task_types


def test_legacy_full_scan_type_is_migrated_without_touching_prd_incremental():
    full = TaskModel(
        project_id="legacy-full",
        review_version="master",
        copy_from_version="0_version",
        task_type=2,
        state=2,
    ).save()
    prd = TaskModel(
        project_id="prd",
        review_version="release",
        copy_from_version="master",
        task_type=2,
        state=2,
    ).save()
    code_file = CodeFileModel(
        task_id=str(full.id),
        project_id=full.project_id,
        review_version=full.review_version,
        copy_from_version=full.copy_from_version,
        task_type=2,
        file_name="src/main.c",
    ).save()
    snapshot = TaskSnapshotModel(
        task_id=str(full.id),
        snapshot_id="legacy-snapshot",
        project_id=full.project_id,
        review_version=full.review_version,
        copy_from_version=full.copy_from_version,
        task_type=2,
        state=2,
    ).save()
    file_snapshot = CodeFileSnapshotModel(
        task_snapshot_id=str(snapshot.id),
        snapshot_id=snapshot.snapshot_id,
        task_id=str(full.id),
        source_file_id=str(code_file.id),
        project_id=full.project_id,
        review_version=full.review_version,
        copy_from_version=full.copy_from_version,
        task_type=2,
        file_name=code_file.file_name,
    ).save()

    first = migrate_legacy_task_types()
    second = migrate_legacy_task_types()

    assert first == {"tasks": 1, "code_files": 1, "task_snapshots": 1, "code_file_snapshots": 1}
    assert second == {"tasks": 0, "code_files": 0, "task_snapshots": 0, "code_file_snapshots": 0}
    assert full.reload().task_type == TaskType.FULL_SCAN.value
    assert code_file.reload().task_type == TaskType.FULL_SCAN.value
    assert snapshot.reload().task_type == TaskType.FULL_SCAN.value
    assert file_snapshot.reload().task_type == TaskType.FULL_SCAN.value
    assert prd.reload().task_type == TaskType.PRD_VERSION.value
