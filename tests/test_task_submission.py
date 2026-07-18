from copy import deepcopy
from pathlib import Path

import pytest

from app.core.config import Settings
from app.models.code_file import CodeFileModel, Issue, ModelRoundTrace, ToolCallTrace
from app.models.code_file_snapshot import CodeFileSnapshotModel
from app.models.project import ProjectModel
from app.models.task import TaskModel
from app.models.task_snapshot import TaskSnapshotModel
from app.services.review_service import ReviewTaskService
from app.services.task_snapshot import TaskSnapshotService
from app.services.task_submission import TaskSubmissionService


def _write(root: Path, relative_path: str, contents: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")


def test_full_trigger_creates_project_and_only_persists_reviewable_files(tmp_path):
    review_root = tmp_path / "master"
    _write(review_root, "src/app.c", "int app(void) { return 0; }\n")
    _write(review_root, "src/main.c", "int main(void) { return 0; }\n")
    _write(review_root, "Math/calc.c", "int add(int a, int b) { return a + b; }\n")
    _write(review_root, "src/generated_driver.c", "int generated(void) { return 0; }\n")
    _write(review_root, "__pycache__/cache.py", "value = 1\n")
    ProjectModel(
        project_id="demo-c",
        version_control_system="local-folder",
        exclude_path=["generated"],
    ).save()

    settings = Settings(
        review_exclude_paths="main.c,Math",
        review_exclude_dirs="__pycache__",
    )
    task = TaskSubmissionService(settings).trigger(
        project_id="demo-c",
        review_version="master",
        copy_from_version="0_version",
        review_version_path=str(review_root),
    )

    assert task.task_type == 3
    assert task.state == 0
    assert task.completion_status == "pending"
    project = ProjectModel.objects(project_id="demo-c").first()
    assert project is not None
    assert project.scan_round == 1
    code_files = list(CodeFileModel.objects(task_id=str(task.id)))
    assert [item.file_name for item in code_files] == ["src/app.c"]
    assert code_files[0].state == 0
    assert code_files[0].code_blocks[0].contents == ["     1+  int app(void) { return 0; }"]


def test_duplicate_trigger_reuses_unchanged_block_and_resets_changed_block(tmp_path):
    review_root = tmp_path / "master"
    _write(review_root, "src/app.c", "int app(void) { return 0; }\n")
    service = TaskSubmissionService(Settings(review_exclude_paths=""))
    trigger = {
        "project_id": "demo-c",
        "review_version": "master",
        "copy_from_version": "0_version",
        "review_version_path": str(review_root),
    }

    first = service.trigger(**trigger)
    code_file = CodeFileModel.objects(task_id=str(first.id)).first()
    original_hash = code_file.code_blocks[0].block_hash
    code_file.state = 2
    code_file.code_blocks[0].comment = "reviewed comment"
    code_file.code_blocks[0].main_task_completed = True
    code_file.code_blocks[0].review_state = 2
    code_file.code_blocks[0].review_fingerprint = "review-fingerprint"
    code_file.save()
    first.llm_total_tokens = 1234
    first.llm_call_count = 7
    first.process_time = 4321
    first.state = 2
    first.completion_status = "completed"
    first.completion_email_sent = True
    first.project_summary = "stable summary"
    first.developer_issue_summary = {"logic": 1}
    first.save()

    second = service.trigger(**trigger)
    unchanged = CodeFileModel.objects(task_id=str(first.id)).first()
    assert second.id == first.id
    assert second.trigger_count == 2
    assert second.trigger_revision == 2
    assert ProjectModel.objects(project_id="demo-c").first().scan_round == 2
    assert second.llm_total_tokens == 1234
    assert second.llm_call_count == 7
    assert second.process_time == 4321
    assert second.state == 2
    assert second.completion_status == "completed"
    assert second.completion_email_sent is True
    assert second.project_summary == "stable summary"
    assert second.developer_issue_summary == {"logic": 1}
    assert unchanged.state == 2
    assert unchanged.code_blocks[0].block_hash == original_hash
    assert unchanged.code_blocks[0].comment == "reviewed comment"
    assert unchanged.code_blocks[0].main_task_completed is True

    unchanged.code_blocks[0].failure_message = "old model failure"
    unchanged.code_blocks[0].main_task_completed = False
    unchanged.code_blocks[0].review_state = 3
    unchanged.state = 3
    unchanged.save()
    _write(review_root, "src/app.c", "int app(void) { return 1; }\n")
    third = service.trigger(**trigger)
    changed = CodeFileModel.objects(task_id=str(first.id)).first()
    assert third.id == first.id
    assert third.trigger_count == 3
    assert third.llm_total_tokens == 1234
    assert third.llm_call_count == 7
    assert third.process_time == 4321
    assert third.state == 0
    assert third.completion_status == "pending"
    assert third.completion_email_sent is False
    assert third.project_summary == ""
    assert third.developer_issue_summary == {}
    assert changed.state == 0
    assert changed.code_blocks[0].block_hash != original_hash
    assert changed.code_blocks[0].comment == ""
    assert changed.code_blocks[0].issues == []
    assert changed.code_blocks[0].failure_message == ""
    assert changed.code_blocks[0].review_attempt_count == 0
    assert changed.code_blocks[0].main_task_completed is False
    snapshot = TaskSnapshotModel.objects(task_id=str(first.id), trigger_revision=3).first()
    assert snapshot is not None
    assert snapshot.changed_files == [str(changed.id)]
    assert snapshot.changed_file_names == ["src/app.c"]
    assert snapshot.code_block_num == 1
    assert third.latest_snapshot_id == snapshot.snapshot_id

    fourth = service.trigger(**trigger)
    carried = TaskSnapshotModel.objects(id=snapshot.id).first()
    assert fourth.id == first.id
    assert fourth.trigger_revision == 4
    assert carried.snapshot_id == snapshot.snapshot_id
    assert carried.trigger_revision == 4
    assert carried.completion_status == "pending"
    assert TaskSnapshotModel.objects(task_id=str(first.id)).count() == 1
    superseded_file = CodeFileSnapshotModel.objects(snapshot_id=carried.snapshot_id).first()
    superseded_contents = deepcopy(superseded_file.code_blocks[0].contents)

    _write(review_root, "src/app.c", "int app(void) { return 2; }\n")
    fifth = service.trigger(**trigger)
    carried.reload()
    replacement = TaskSnapshotModel.objects(task_id=str(first.id), trigger_revision=5).first()
    assert fifth.id == first.id
    assert TaskModel.objects(
        project_id="demo-c",
        review_version="master",
        copy_from_version="0_version",
    ).count() == 1
    assert carried.state == 3
    assert carried.completion_status == "superseded"
    assert replacement is not None
    assert replacement.snapshot_id != carried.snapshot_id
    TaskSnapshotService().checkpoint(fourth)
    carried.reload()
    superseded_file.reload()
    assert carried.completion_status == "superseded"
    assert superseded_file.code_blocks[0].contents == superseded_contents


def test_removed_file_creates_snapshot_and_recalculates_task_without_reviewing_unchanged_blocks(tmp_path, caplog):
    caplog.set_level("INFO")
    review_root = tmp_path / "master"
    _write(review_root, "src/keep.c", "int keep(void) { return 1; }\n")
    _write(review_root, "src/removed.c", "int removed(void) { return 2; }\n")
    keep_path = review_root / "src/keep.c"
    removed_path = review_root / "src/removed.c"
    settings = Settings(
        review_exclude_paths="",
        llm_mock_enabled=True,
        review_semantic_index_enabled=False,
        full_scan_batch_dedup_enabled=False,
        full_scan_project_summary_enabled=False,
    )
    submission = TaskSubmissionService(settings)
    trigger = {
        "project_id": "removed-file-snapshot-project",
        "review_version": "master",
        "copy_from_version": "0_version",
        "review_version_path": str(review_root),
    }
    first = ReviewTaskService(settings).review_task(submission.trigger(**trigger))
    assert first.state == 2
    assert keep_path.exists()
    first_process_time = first.process_time

    caplog.clear()
    removed_path.unlink()
    pending = submission.trigger(**trigger)
    snapshot = TaskSnapshotModel.objects(task_id=str(first.id), trigger_revision=2).first()

    assert pending.id == first.id
    assert pending.state == 0
    assert pending.file_num == 1
    assert pending.reviewed_file_num == 1
    assert snapshot is not None
    assert snapshot.changed_files == []
    assert snapshot.changed_file_names == []
    assert snapshot.removed_file_names == ["src/removed.c"]
    assert CodeFileSnapshotModel.objects(snapshot_id=snapshot.snapshot_id).count() == 0

    completed = ReviewTaskService(settings).review_task(pending)
    snapshot.reload()

    assert completed.state == 2
    assert completed.file_num == 1
    assert completed.reviewed_file_num == 1
    assert completed.process_time >= first_process_time
    assert CodeFileModel.objects(task_id=str(first.id), file_name="src/removed.c").count() == 0
    assert snapshot.state == 2
    assert snapshot.completion_status == "completed"
    assert snapshot.file_num == 0
    assert snapshot.code_block_num == 0
    assert snapshot.completion_log_sent is True
    assert "变更文件审核完成" in caplog.text


def test_same_comparison_reuses_task_when_jenkins_workspace_path_changes(tmp_path):
    first_root = tmp_path / "jenkins-workspace-1" / "master"
    second_root = tmp_path / "jenkins-workspace-2" / "master"
    _write(first_root, "src/app.c", "int app(void) { return 1; }\n")
    _write(second_root, "src/app.c", "int app(void) { return 2; }\n")
    service = TaskSubmissionService(Settings(review_exclude_paths=""))

    first = service.trigger(
        project_id="stable-comparison-project",
        review_version="master",
        copy_from_version="0_version",
        review_version_path=str(first_root),
    )
    first_file = CodeFileModel.objects(task_id=str(first.id)).first()
    first_file.code_blocks[0].comment = "old review"
    first_file.code_blocks[0].main_task_completed = True
    first_file.code_blocks[0].review_state = 2
    first_file.state = 2
    first_file.save()
    first.state = 2
    first.completion_status = "completed"
    first.save()
    TaskModel.objects(id=first.id).update_one(
        unset__submission_key=1,
        unset__trigger_count=1,
        unset__trigger_revision=1,
    )

    second = service.trigger(
        project_id="stable-comparison-project",
        review_version="master",
        copy_from_version="0_version",
        review_version_path=str(second_root),
    )

    assert second.id == first.id
    assert second.trigger_count == 2
    assert second.trigger_revision == 2
    assert second.review_version_path == str(second_root.resolve())
    assert TaskModel.objects(
        project_id="stable-comparison-project",
        review_version="master",
        copy_from_version="0_version",
    ).count() == 1
    latest_file = CodeFileModel.objects(task_id=str(first.id)).first()
    assert latest_file.code_blocks[0].comment == ""
    assert latest_file.code_blocks[0].main_task_completed is False
    snapshot = TaskSnapshotModel.objects(task_id=str(first.id), trigger_revision=2).first()
    assert snapshot.changed_file_names == ["src/app.c"]
    assert snapshot.changed_files == [str(latest_file.id)]


@pytest.mark.parametrize(
    ("initial_state", "initial_status"),
    [(0, "pending"), (1, "running"), (2, "completed"), (3, "partial")],
)
def test_unchanged_successful_blocks_are_preserved_and_only_completed_task_skips_finalization(
    tmp_path,
    initial_state,
    initial_status,
):
    review_root = tmp_path / f"state-{initial_state}"
    _write(review_root, "src/app.c", "int app(void) { return 0; }\n")
    service = TaskSubmissionService(Settings(review_exclude_paths=""))
    trigger = {
        "project_id": f"state-project-{initial_state}",
        "review_version": "master",
        "copy_from_version": "0_version",
        "review_version_path": str(review_root),
    }
    task = service.trigger(**trigger)
    code_file = CodeFileModel.objects(task_id=str(task.id)).first()
    block = code_file.code_blocks[0]
    block.comment = "keep this review"
    block.logic_score = 91
    block.main_task_completed = True
    block.review_state = 2
    block.review_fingerprint = "stable-fingerprint"
    code_file.state = 2
    code_file.code_blocks = [block]
    code_file.save()
    task.state = initial_state
    task.completion_status = initial_status
    task.project_summary = "keep this summary"
    task.llm_total_tokens = 500
    task.llm_call_count = 5
    task.process_time = 900
    task.completion_email_sent = True
    task.save()

    retriggered = service.trigger(**trigger)
    persisted = CodeFileModel.objects(task_id=str(task.id)).first()

    assert retriggered.id == task.id
    expected_state = 2 if initial_state == 2 else 0
    assert retriggered.state == expected_state
    assert retriggered.completion_status == ("completed" if initial_state == 2 else "pending")
    assert retriggered.reviewed_file_num == 1
    assert retriggered.llm_total_tokens == 500
    assert retriggered.llm_call_count == 5
    assert retriggered.process_time == 900
    assert retriggered.project_summary == ("keep this summary" if initial_state == 2 else "")
    assert retriggered.completion_email_sent is (initial_state == 2)
    assert persisted.state == 2
    assert persisted.code_blocks[0].comment == "keep this review"
    assert persisted.code_blocks[0].logic_score == 91
    assert persisted.code_blocks[0].review_fingerprint == "stable-fingerprint"


def test_partial_task_with_completed_blocks_retries_finalization_without_rereview(tmp_path):
    review_root = tmp_path / "finalization-resume"
    _write(review_root, "src/app.c", "int app(void) { return 0; }\n")
    settings = Settings(
        review_exclude_paths="",
        llm_mock_enabled=True,
        review_semantic_index_enabled=False,
        full_scan_batch_dedup_enabled=False,
    )
    submission = TaskSubmissionService(settings)
    trigger = {
        "project_id": "finalization-resume-project",
        "review_version": "master",
        "copy_from_version": "0_version",
        "review_version_path": str(review_root),
    }
    completed = ReviewTaskService(settings).review_task(submission.trigger(**trigger))
    code_file = CodeFileModel.objects(task_id=str(completed.id)).first()
    block_before = deepcopy(code_file.code_blocks[0].to_mongo().to_dict())
    completed.state = 3
    completed.completion_status = "failed"
    completed.project_summary = "stale failed finalization"
    completed.developer_issue_summary = {"_fatal_error": {"message": "summary timeout"}}
    completed.save()

    pending = submission.trigger(**trigger)
    after_sync = CodeFileModel.objects(task_id=str(completed.id)).first()

    assert pending.state == 0
    assert pending.completion_status == "pending"
    assert pending.project_summary == ""
    assert pending.developer_issue_summary == {}
    assert after_sync.state == 2
    assert after_sync.code_blocks[0].to_mongo().to_dict() == block_before

    finalized = ReviewTaskService(settings).review_task(pending)
    after_finalization = CodeFileModel.objects(task_id=str(completed.id)).first()

    assert finalized.state == 2
    assert finalized.completion_status == "completed"
    assert finalized.resumed_file_num == 1
    assert after_finalization.code_blocks[0].to_mongo().to_dict() == block_before


@pytest.mark.parametrize("initial_state", [0, 1, 2, 3])
def test_changed_block_is_reset_and_requeued_for_every_prior_task_state(tmp_path, initial_state):
    review_root = tmp_path / f"changed-state-{initial_state}"
    _write(review_root, "src/app.c", "int app(void) { return 0; }\n")
    service = TaskSubmissionService(Settings(review_exclude_paths=""))
    trigger = {
        "project_id": f"changed-state-project-{initial_state}",
        "review_version": "master",
        "copy_from_version": "0_version",
        "review_version_path": str(review_root),
    }
    task = service.trigger(**trigger)
    code_file = CodeFileModel.objects(task_id=str(task.id)).first()
    block = code_file.code_blocks[0]
    block.comment = "obsolete result"
    block.logic_score = 92
    block.issues = [Issue(issue_id=0, description="obsolete", type="logic", severity=3, suggestion="fix")]
    block.main_task_completed = initial_state != 3
    block.failure_message = "old failure" if initial_state == 3 else ""
    block.review_state = 3 if initial_state == 3 else 2
    block.review_attempt_count = 4
    code_file.code_blocks = [block]
    code_file.state = 3 if initial_state == 3 else 2
    code_file.save()
    task.state = initial_state
    task.completion_status = {0: "pending", 1: "running", 2: "completed", 3: "partial"}[initial_state]
    task.llm_total_tokens = 250
    task.llm_call_count = 3
    task.process_time = 600
    task.save()

    _write(review_root, "src/app.c", "int app(void) { return 1; }\n")
    retriggered = service.trigger(**trigger)
    changed_file = CodeFileModel.objects(task_id=str(task.id)).first()
    changed = changed_file.code_blocks[0]

    assert retriggered.state == 0
    assert retriggered.completion_status == "pending"
    assert retriggered.llm_total_tokens == 250
    assert retriggered.llm_call_count == 3
    assert retriggered.process_time == 600
    assert changed_file.state == 0
    assert changed.comment == ""
    assert changed.logic_score == 0
    assert changed.issues == []
    assert changed.main_task_completed is False
    assert changed.failure_message == ""
    assert changed.review_state == 0
    assert changed.review_attempt_count == 0


def test_full_retrigger_preserves_unchanged_blocks_and_fully_resets_changed_block(tmp_path):
    review_root = tmp_path / "master"
    _write(
        review_root,
        "src/multi.c",
        "int keep_a(void) { return 1; }\n"
        "int changing(void) { return 2; }\n"
        "int keep_b(void) { return 3; }\n",
    )
    service = TaskSubmissionService(Settings(review_exclude_paths="", diff_token_threshold=8))
    trigger = {
        "project_id": "multi-block-project",
        "review_version": "master",
        "copy_from_version": "0_version",
        "review_version_path": str(review_root),
    }
    task = service.trigger(**trigger)
    code_file = CodeFileModel.objects(task_id=str(task.id)).first()
    assert len(code_file.code_blocks) == 3

    for index, block in enumerate(code_file.code_blocks):
        block.comment = f"review-{index}"
        block.plan_change_summary = f"plan-{index}"
        block.plan_risk_level = "high"
        block.plan_checkpoints = [{"name": "bounds"}]
        block.related_files = [{"file_name": "src/helper.c"}]
        block.static_findings = [{"rule_id": "C001"}]
        block.logic_score = 90
        block.performance_score = 89
        block.security_score = 88
        block.readable_score = 87
        block.code_style_score = 86
        block.comment_line_number = 1
        block.issues = [
            Issue(
                issue_id=0,
                description=f"issue-{index}",
                type="logic",
                severity=4,
                suggestion="fix it",
                issue_line_numbers=str(index + 1),
            )
        ]
        block.process_time = 100
        block.llm_prompt_tokens = 10
        block.llm_completion_tokens = 11
        block.llm_total_tokens = 21
        block.llm_reasoning_tokens = 3
        block.llm_cached_tokens = 2
        block.llm_elapsed_ms = 80
        block.memory_compression_count = 1
        block.main_task_completed = True
        block.main_task_completion_mode = "task_done"
        block.main_task_round_count = 4
        block.model_rounds = [ModelRoundTrace(stage="plan_task", round_index=1, total_tokens=21)]
        block.tool_calls = [ToolCallTrace(round_index=1, tool_name="read_file", success=True)]
        block.gitlab_comment_id = "comment-id"
        block.review_fingerprint = f"fingerprint-{index}"
        block.review_state = 2
        block.review_attempt_count = 2

    changed_old_block = code_file.code_blocks[1]
    changed_old_block.main_task_completed = False
    changed_old_block.failure_message = "old timeout"
    changed_old_block.review_state = 3
    code_file.state = 3
    code_file.code_blocks = list(code_file.code_blocks)
    code_file.save()
    code_file.reload()
    keep_a_before = deepcopy(code_file.code_blocks[0].to_mongo().to_dict())
    keep_b_before = deepcopy(code_file.code_blocks[2].to_mongo().to_dict())
    task.state = 3
    task.completion_status = "partial"
    task.llm_total_tokens = 400
    task.llm_call_count = 8
    task.process_time = 1200
    task.project_summary = "stale summary"
    task.save()

    _write(
        review_root,
        "src/multi.c",
        "int keep_a(void) { return 1; }\n"
        "int changing(void) { return 9; }\n"
        "int keep_b(void) { return 3; }\n",
    )
    retriggered = service.trigger(**trigger)
    synchronized = CodeFileModel.objects(task_id=str(task.id)).first()

    assert retriggered.state == 0
    assert retriggered.completion_status == "pending"
    assert retriggered.llm_total_tokens == 400
    assert retriggered.llm_call_count == 8
    assert retriggered.process_time == 1200
    assert retriggered.project_summary == ""
    assert synchronized.state == 0
    assert synchronized.code_blocks[0].to_mongo().to_dict() == keep_a_before
    assert synchronized.code_blocks[2].to_mongo().to_dict() == keep_b_before

    changed = synchronized.code_blocks[1]
    assert changed.comment == ""
    assert changed.plan_change_summary == ""
    assert changed.plan_risk_level == ""
    assert changed.plan_checkpoints == []
    assert changed.related_files == []
    assert changed.static_findings == []
    assert changed.logic_score == 0
    assert changed.performance_score == 0
    assert changed.security_score == 0
    assert changed.readable_score == 0
    assert changed.code_style_score == 0
    assert changed.comment_line_number == 0
    assert changed.issues == []
    assert changed.process_time == 0
    assert changed.llm_total_tokens == 0
    assert changed.llm_elapsed_ms == 0
    assert changed.memory_compression_count == 0
    assert changed.main_task_completed is False
    assert changed.main_task_completion_mode == ""
    assert changed.main_task_round_count == 0
    assert changed.model_rounds == []
    assert changed.tool_calls == []
    assert changed.gitlab_comment_id is None
    assert changed.failure_message == ""
    assert changed.review_fingerprint == ""
    assert changed.review_state == 0
    assert changed.review_attempt_count == 0


def test_unchanged_failed_block_stays_pending_for_retry_and_keeps_diagnostics(tmp_path):
    review_root = tmp_path / "master"
    _write(review_root, "src/app.c", "int app(void) { return 0; }\n")
    service = TaskSubmissionService(Settings(review_exclude_paths=""))
    trigger = {
        "project_id": "failed-project",
        "review_version": "master",
        "copy_from_version": "0_version",
        "review_version_path": str(review_root),
    }
    task = service.trigger(**trigger)
    code_file = CodeFileModel.objects(task_id=str(task.id)).first()
    block = code_file.code_blocks[0]
    block.comment = "plan completed before failure"
    block.failure_message = "LLM timeout"
    block.review_attempt_count = 3
    block.review_state = 3
    block.issues = [Issue(issue_id=0, description="diagnostic", type="logic", severity=2, suggestion="retry")]
    code_file.code_blocks = [block]
    code_file.state = 3
    code_file.save()
    task.state = 3
    task.completion_status = "partial"
    task.retry_count = 2
    task.llm_total_tokens = 700
    task.save()

    retriggered = service.trigger(**trigger)
    pending_file = CodeFileModel.objects(task_id=str(task.id)).first()
    pending_block = pending_file.code_blocks[0]

    assert retriggered.state == 0
    assert retriggered.completion_status == "pending"
    assert retriggered.retry_count == 2
    assert retriggered.llm_total_tokens == 700
    assert pending_file.state == 0
    assert pending_block.review_state == 0
    assert pending_block.failure_message == "LLM timeout"
    assert pending_block.review_attempt_count == 3
    assert pending_block.comment == "plan completed before failure"
    assert pending_block.issues[0].description == "diagnostic"


def test_incremental_trigger_only_persists_changed_files(tmp_path):
    base_root = tmp_path / "master"
    review_root = tmp_path / "feature"
    _write(base_root, "src/app.c", "int app(void) { return 0; }\n")
    _write(review_root, "src/app.c", "int app(void) { return 1; }\n")
    _write(base_root, "src/unchanged.c", "int same(void) { return 0; }\n")
    _write(review_root, "src/unchanged.c", "int same(void) { return 0; }\n")

    task = TaskSubmissionService(Settings(review_exclude_paths="")).trigger(
        project_id="demo-c",
        review_version="feature",
        copy_from_version="master",
        review_version_path=str(review_root),
        copy_from_version_path=str(base_root),
    )

    assert task.task_type == 1
    assert task.copy_from_version_path == str(base_root.resolve())
    assert task.review_version_path == str(review_root.resolve())
    code_files = list(CodeFileModel.objects(task_id=str(task.id)))
    assert [item.file_name for item in code_files] == ["src/app.c"]
    assert any(line[6] == "-" for line in code_files[0].code_blocks[0].contents)
    assert any(line[6] == "+" for line in code_files[0].code_blocks[0].contents)


def test_incremental_retrigger_only_resets_the_file_whose_diff_changed(tmp_path):
    base_root = tmp_path / "master"
    review_root = tmp_path / "feature"
    _write(base_root, "src/auth.c", "int auth(void) { return 0; }\n")
    _write(review_root, "src/auth.c", "int auth(void) { return 1; }\n")
    _write(base_root, "src/cache.c", "int cache(void) { return 0; }\n")
    _write(review_root, "src/cache.c", "int cache(void) { return 1; }\n")
    service = TaskSubmissionService(Settings(review_exclude_paths=""))
    trigger = {
        "project_id": "incremental-retrigger-project",
        "review_version": "feature",
        "copy_from_version": "master",
        "review_version_path": str(review_root),
        "copy_from_version_path": str(base_root),
    }
    task = service.trigger(**trigger)
    assert TaskSnapshotModel.objects(task_id=str(task.id)).count() == 0
    original_files = {
        item.file_name: item for item in CodeFileModel.objects(task_id=str(task.id))
    }
    assert set(original_files) == {"src/auth.c", "src/cache.c"}
    for file_name, code_file in original_files.items():
        block = code_file.code_blocks[0]
        block.comment = f"reviewed {file_name}"
        block.logic_score = 95
        block.llm_total_tokens = 50
        block.main_task_completed = True
        block.main_task_completion_mode = "task_done"
        block.review_state = 2
        block.review_fingerprint = f"fingerprint-{file_name}"
        code_file.code_blocks = [block]
        code_file.source_hash = ""
        code_file.extra = {key: value for key, value in (code_file.extra or {}).items() if key != "source_hash"}
        code_file.state = 2
        code_file.save()
    unchanged_before = deepcopy(
        CodeFileModel.objects(task_id=str(task.id), file_name="src/cache.c")
        .first()
        .code_blocks[0]
        .to_mongo()
        .to_dict()
    )
    task.state = 2
    task.completion_status = "completed"
    task.llm_total_tokens = 100
    task.llm_call_count = 4
    task.process_time = 300
    task.save()

    _write(review_root, "src/auth.c", "int auth(void) { return 2; }\n")
    retriggered = service.trigger(**trigger)
    synchronized = {
        item.file_name: item for item in CodeFileModel.objects(task_id=str(task.id))
    }

    assert retriggered.id == task.id
    assert retriggered.task_type == 1
    assert retriggered.state == 0
    assert retriggered.file_num == 2
    assert retriggered.reviewed_file_num == 1
    assert retriggered.llm_total_tokens == 100
    assert retriggered.llm_call_count == 4
    assert retriggered.process_time == 300
    assert synchronized["src/cache.c"].state == 2
    assert synchronized["src/cache.c"].code_blocks[0].to_mongo().to_dict() == unchanged_before
    assert synchronized["src/auth.c"].state == 0
    assert synchronized["src/auth.c"].code_blocks[0].comment == ""
    assert synchronized["src/auth.c"].code_blocks[0].logic_score == 0
    assert synchronized["src/auth.c"].code_blocks[0].llm_total_tokens == 0
    assert synchronized["src/auth.c"].code_blocks[0].main_task_completed is False
    assert synchronized["src/auth.c"].code_blocks[0].review_fingerprint == ""
    second_trigger = TaskSnapshotModel.objects(task_id=str(task.id), trigger_revision=2).first()
    assert second_trigger is not None
    assert second_trigger.changed_file_names == ["src/auth.c"]
    assert second_trigger.changed_files == [str(synchronized["src/auth.c"].id)]
    assert second_trigger.removed_file_names == []
    assert [(item["file_name"], item["block_id"]) for item in second_trigger.changed_blocks] == [
        ("src/auth.c", 0)
    ]


def test_full_client_server_resume_reviews_only_the_changed_block(tmp_path, caplog):
    caplog.set_level("INFO")
    review_root = tmp_path / "master"
    _write(
        review_root,
        "src/resume.c",
        "int keep_a(void) { return 1; }\n"
        "int changing(void) { return 2; }\n"
        "int keep_b(void) { return 3; }\n",
    )
    settings = Settings(
        review_exclude_paths="",
        diff_token_threshold=8,
        llm_mock_enabled=True,
        review_semantic_index_enabled=False,
        full_scan_batch_dedup_enabled=False,
    )
    submission = TaskSubmissionService(settings)
    trigger = {
        "project_id": "client-server-resume-project",
        "review_version": "master",
        "copy_from_version": "0_version",
        "review_version_path": str(review_root),
    }
    first = submission.trigger(**trigger)
    first = ReviewTaskService(settings).review_task(first)
    assert first.state == 2
    assert "首次审核结束" in caplog.text
    first_file = CodeFileModel.objects(task_id=str(first.id)).first()
    assert len(first_file.code_blocks) == 3
    assert all(block.main_task_completed for block in first_file.code_blocks)
    first.llm_total_tokens = 500
    first.llm_call_count = 5
    first.process_time = 800
    first.save()
    unchanged_a_before = deepcopy(first_file.code_blocks[0].to_mongo().to_dict())
    changed_hash_before = first_file.code_blocks[1].block_hash
    unchanged_b_before = deepcopy(first_file.code_blocks[2].to_mongo().to_dict())
    first_tokens = first.llm_total_tokens
    first_calls = first.llm_call_count

    _write(
        review_root,
        "src/resume.c",
        "int keep_a(void) { return 1; }\n"
        "int changing(void) { return 9; }\n"
        "int keep_b(void) { return 3; }\n",
    )
    pending = submission.trigger(**trigger)
    assert pending.state == 0
    pending_file = CodeFileModel.objects(task_id=str(first.id)).first()
    assert pending_file.code_blocks[0].to_mongo().to_dict() == unchanged_a_before
    assert pending_file.code_blocks[2].to_mongo().to_dict() == unchanged_b_before
    assert pending_file.code_blocks[1].block_hash != changed_hash_before
    assert pending_file.code_blocks[1].review_attempt_count == 0
    snapshot = TaskSnapshotModel.objects(task_id=str(first.id), trigger_revision=2).first()
    assert snapshot is not None
    assert pending.latest_snapshot_id == snapshot.snapshot_id
    assert snapshot.changed_files == [str(pending_file.id)]
    assert snapshot.changed_file_names == ["src/resume.c"]
    snapshot_file = CodeFileSnapshotModel.objects(snapshot_id=snapshot.snapshot_id).first()
    assert snapshot_file is not None
    assert len(snapshot_file.code_blocks) == 1
    assert snapshot_file.code_blocks[0].block_hash == pending_file.code_blocks[1].block_hash

    caplog.clear()
    completed = ReviewTaskService(settings).review_task(pending)
    completed_file = CodeFileModel.objects(task_id=str(first.id)).first()

    assert completed.state == 2
    assert completed.completion_status == "completed"
    assert completed.llm_total_tokens >= first_tokens
    assert completed.llm_call_count >= first_calls
    assert completed.process_time >= 800
    assert completed_file.code_blocks[0].to_mongo().to_dict() == unchanged_a_before
    assert completed_file.code_blocks[2].to_mongo().to_dict() == unchanged_b_before
    assert completed_file.code_blocks[1].main_task_completed is True
    assert completed_file.code_blocks[1].review_attempt_count == 1
    snapshot.reload()
    snapshot_file.reload()
    assert snapshot.state == 2
    assert snapshot.completion_status == "completed"
    assert snapshot.file_num == 1
    assert snapshot.code_block_num == 1
    assert snapshot.llm_total_tokens == snapshot_file.code_blocks[0].llm_total_tokens
    assert snapshot.completion_log_sent is True
    assert "变更文件审核完成" in caplog.text
    assert TaskSnapshotService.report_path(snapshot) in caplog.text


def test_trigger_route_prepares_task_and_files(client, tmp_path):
    review_root = tmp_path / "master"
    _write(review_root, "src/app.c", "int app(void) { return 0; }\n")

    response = client.post(
        "/tasks/trigger",
        json={
            "project_id": "demo-c",
            "review_version": "master",
            "copy_from_version": "0_version",
            "review_version_path": str(review_root),
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["state"] == 0
    assert body["task_type"] == 3
    assert body["file_num"] == 1
    assert TaskModel.objects(id=body["id"]).count() == 1
    assert CodeFileModel.objects(task_id=body["id"]).count() == 1


def test_incremental_trigger_requires_type_and_applies_author_map(client, tmp_path):
    base_root = tmp_path / "master"
    review_root = tmp_path / "feature"
    _write(base_root, "src/auth.c", "int auth(void) { return 0; }\n")
    _write(review_root, "src/auth.c", "int auth(void) { return 1; }\n")
    _write(review_root, "src/config.c", "int config(void) { return 1; }\n")
    author_map = tmp_path / "authors.json"
    author_map.write_text(
        '{"src/auth.c":"dahai","src\\\\config.c":"xiaoming"}',
        encoding="utf-8",
    )
    payload = {
        "project_id": "demo-author",
        "review_version": "feature",
        "copy_from_version": "master",
        "review_version_path": str(review_root),
        "copy_from_version_path": str(base_root),
        "author_map_file": str(author_map),
    }

    missing_type = client.post("/tasks/trigger", json=payload)
    assert missing_type.status_code == 422

    response = client.post("/tasks/trigger", json={**payload, "task_type": 2})
    assert response.status_code == 201
    body = response.json()
    assert body["task_type"] == 2
    assert body["author_map_file"] == str(author_map.resolve())
    authors = {
        item.file_name: item.file_author
        for item in CodeFileModel.objects(task_id=body["id"])
    }
    assert authors == {"src/auth.c": "dahai", "src/config.c": "xiaoming"}


def test_full_scan_forces_type_three_even_when_caller_sends_incremental_type(client, tmp_path):
    review_root = tmp_path / "master"
    _write(review_root, "src/app.c", "int app(void) { return 0; }\n")

    response = client.post(
        "/tasks/trigger",
        json={
            "project_id": "demo-full-type",
            "review_version": "master",
            "copy_from_version": "0_version",
            "review_version_path": str(review_root),
            "task_type": 2,
        },
    )

    assert response.status_code == 201
    assert response.json()["task_type"] == 3
