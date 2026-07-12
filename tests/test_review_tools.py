from pathlib import Path

from app.core.config import Settings
from app.services.diff_service import CodeDiffService
from app.services.review_tools import ReviewToolRunner


def test_file_find_and_file_read_diff(tmp_path: Path):
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    runner = ReviewToolRunner(
        tmp_path,
        Settings(mongo_mock=True, llm_mock_enabled=True),
        current_file_name="src/main.c",
        current_diff_lines=["     1+  int main(void) { return 0; }"],
    )

    find_result = runner.run("file_find", {"query": "main.c"})
    diff_result = runner.run("file_read_diff", {"file_path": "src/main.c"})

    assert find_result["matches"] == [{"file_path": "src/main.c"}]
    assert diff_result["lines"][0]["line"] == "     1+  int main(void) { return 0; }"


def test_read_file_rejects_path_escape(tmp_path: Path):
    runner = ReviewToolRunner(tmp_path, Settings(mongo_mock=True, llm_mock_enabled=True))

    result = runner.run("read_file", {"file_path": "../outside.c"})

    assert "error" in result
    assert "escapes review root" in result["error"]


def test_code_comment_preserves_evidence_fields(tmp_path: Path):
    runner = ReviewToolRunner(tmp_path, Settings(mongo_mock=True, llm_mock_enabled=True))

    result = runner.run(
        "code_comment",
        {
            "type": "security",
            "severity": 5,
            "description": "unsafe copy",
            "suggestion": "use snprintf",
            "issue_line_numbers": "3",
            "existing_code": "strcpy(dst, input);",
            "suggestion_code": "snprintf(dst, sizeof(dst), \"%s\", input);",
            "evidence": "The changed line copies external input into a fixed buffer.",
            "rule_id": "c-buffer-boundary",
            "confidence_level": 0.9,
        },
    )

    assert result["accepted"] is True
    assert runner.comments[0]["existing_code"] == "strcpy(dst, input);"
    assert runner.comments[0]["evidence"] == "The changed line copies external input into a fixed buffer."
    assert runner.comments[0]["rule_id"] == "c-buffer-boundary"


def test_file_read_diff_can_read_other_changed_and_deleted_files(tmp_path: Path):
    base_dir = tmp_path / "base"
    head_dir = tmp_path / "head"
    base_dir.mkdir()
    head_dir.mkdir()
    (base_dir / "deleted.c").write_text("int deleted(void) { return 1; }\n", encoding="utf-8")
    (base_dir / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    (head_dir / "main.c").write_text("int main(void) { return 1; }\n", encoding="utf-8")
    settings = Settings(mongo_mock=True, llm_mock_enabled=True)
    collection = CodeDiffService(settings).compare_directories_with_context(base_dir, head_dir)
    runner = ReviewToolRunner(
        head_dir,
        settings,
        current_file_name="main.c",
        current_diff_lines=collection.diff_map["main.c"],
        diff_map=collection.diff_map,
    )

    result = runner.run("file_read_diff", {"path_array": ["main.c", "deleted.c"]})

    assert [item["file_path"] for item in result["files"]] == ["main.c", "deleted.c"]
    assert any(line[6] == "-" for line in collection.diff_map["deleted.c"])
    assert "deleted.c" not in [target.file_name for target in collection.targets]
    assert any(item.file_name == "deleted.c" and item.change_type == "DELETED" for item in collection.changed_files)


def test_batched_code_comment_rejects_invalid_items_without_losing_valid_ones(tmp_path: Path):
    runner = ReviewToolRunner(tmp_path, Settings(mongo_mock=True, llm_mock_enabled=True))

    result = runner.run(
        "code_comment",
        {
            "comments": [
                {
                    "type": "security",
                    "severity": 5,
                    "description": "overflow",
                    "suggestion": "check the bound",
                    "issue_line_numbers": "12",
                    "existing_code": "strcpy(dst, src);",
                    "evidence": "the destination size is not passed",
                },
                {
                    "type": "security",
                    "severity": 5,
                    "description": "missing evidence",
                    "suggestion": "fix",
                    "issue_line_numbers": "13",
                    "existing_code": "strcpy(other, src);",
                },
            ]
        },
    )

    assert result["accepted_count"] == 1
    assert len(result["errors"]) == 1
    assert len(runner.comments) == 1


def test_directory_compare_recognizes_unique_content_rename(tmp_path: Path):
    base_dir = tmp_path / "base"
    head_dir = tmp_path / "head"
    base_dir.mkdir()
    head_dir.mkdir()
    content = "int helper(void) { return 0; }\n"
    (base_dir / "old_name.c").write_text(content, encoding="utf-8")
    (head_dir / "new_name.c").write_text(content, encoding="utf-8")

    collection = CodeDiffService(Settings(mongo_mock=True)).compare_directories_with_context(base_dir, head_dir)

    assert collection.targets == []
    assert len(collection.changed_files) == 1
    assert collection.changed_files[0].change_type == "RENAMED"
    assert collection.changed_files[0].old_file_name == "old_name.c"
    assert collection.changed_files[0].file_name == "new_name.c"
