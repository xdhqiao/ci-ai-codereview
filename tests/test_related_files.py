from pathlib import Path

from app.core.config import Settings
from app.models.code_file import CodeFileModel
from app.models.task import TaskModel
from app.services.diff_service import ChangedFile, ReviewCollection, ReviewTarget
from app.services.related_files import RelatedFileResolver
from app.services.review_service import ReviewTaskService


def _target(file_name: str, full_code: str = "") -> ReviewTarget:
    return ReviewTarget(
        file_name=file_name,
        diff_lines=["     1+  " + (full_code.splitlines()[0] if full_code else "int value;")],
        full_code=full_code,
        language="C",
        code_line_num=max(1, len(full_code.splitlines())),
        add_code_line_num=1,
    )


def test_related_file_resolver_prioritizes_companions_references_and_tests():
    current = _target("src/user.c", '#include "user.h"\n')
    candidates = [
        current,
        _target("include/user.h", "int load_user(void);\n"),
        _target("tests/user_test.c", "int test_user(void);\n"),
        _target("src/caller.c", '#include "user.h"\n'),
        _target("src/storage.c", "int save_user(void) { return 1; }\n"),
        _target("src/unrelated.c", "int unrelated(void);\n"),
    ]
    current = _target("src/user.c", '#include "user.h"\nint run(void) { return save_user(); }\n')
    candidates[0] = current
    collection = ReviewCollection(
        targets=candidates,
        diff_map={target.file_name: target.diff_lines for target in candidates},
        changed_files=[ChangedFile(target.file_name, "MODIFIED") for target in candidates],
    )

    related = RelatedFileResolver().resolve(current, collection, limit=8)

    by_path = {item.file_name: item for item in related}
    assert by_path["include/user.h"].score == 100
    assert "companion_source_header" in by_path["include/user.h"].reasons
    assert "implementation_test_pair" in by_path["tests/user_test.c"].reasons
    assert "related_references_current" in by_path["src/caller.c"].reasons
    assert "current_calls_related_symbol" in by_path["src/storage.c"].reasons
    assert "src/unrelated.c" not in by_path


def test_related_files_are_injected_and_persisted_per_code_block(tmp_path: Path):
    review_dir = tmp_path / "master"
    review_dir.mkdir()
    (review_dir / "widget.c").write_text('#include "widget.h"\nint widget(void) { return 1; }\n', encoding="utf-8")
    (review_dir / "widget.h").write_text("int widget(void);\n", encoding="utf-8")
    (review_dir / "unrelated.c").write_text("int unrelated(void) { return 0; }\n", encoding="utf-8")
    task = TaskModel(
        project_id="related-context",
        review_version=str(review_dir),
        copy_from_version="0_version",
        state=0,
    ).save()
    service = ReviewTaskService(
        Settings(
            mongo_mock=True,
            llm_mock_enabled=True,
            review_related_files_enabled=True,
            review_related_file_limit=4,
        )
    )

    reviewed = service.review_task(task)

    code_file = CodeFileModel.objects(task_id=str(task.id), file_name="widget.c").first()
    related = code_file.code_blocks[0].related_files
    assert reviewed.state == 2
    assert [item["file_name"] for item in related] == ["widget.h"]
    assert related[0]["score"] == 100
    assert code_file.extra["related_files"] == related
