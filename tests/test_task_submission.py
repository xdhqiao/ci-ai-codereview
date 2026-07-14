from pathlib import Path

from app.core.config import Settings
from app.models.code_file import CodeFileModel
from app.models.project import ProjectModel
from app.models.task import TaskModel
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

    assert task.task_type == 2
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
    assert unchanged.state == 2
    assert unchanged.code_blocks[0].block_hash == original_hash
    assert unchanged.code_blocks[0].comment == "reviewed comment"
    assert unchanged.code_blocks[0].main_task_completed is True

    _write(review_root, "src/app.c", "int app(void) { return 1; }\n")
    third = service.trigger(**trigger)
    changed = CodeFileModel.objects(task_id=str(first.id)).first()
    assert third.id == first.id
    assert third.trigger_count == 3
    assert third.llm_total_tokens == 1234
    assert third.llm_call_count == 7
    assert changed.state == 0
    assert changed.code_blocks[0].block_hash != original_hash
    assert changed.code_blocks[0].comment == ""
    assert changed.code_blocks[0].issues == []
    assert changed.code_blocks[0].main_task_completed is False


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
    assert body["task_type"] == 2
    assert body["file_num"] == 1
    assert TaskModel.objects(id=body["id"]).count() == 1
    assert CodeFileModel.objects(task_id=body["id"]).count() == 1
