from pathlib import Path

from app.core.config import Settings
from app.services.diff_service import CodeDiffService
from app.services.review_tools import ReviewToolRunner
from app.services.prompts import MAIN_TOOL_DEFINITIONS


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


def test_semantic_tools_find_c_definitions_references_and_calls(tmp_path: Path):
    (tmp_path / "math.c").write_text(
        "int add_one(int value) { return value + 1; }\n"
        "int calculate(int value) { return add_one(value); }\n",
        encoding="utf-8",
    )
    (tmp_path / "main.c").write_text(
        "int calculate(int value);\n"
        "int main(void) { return calculate(41); }\n",
        encoding="utf-8",
    )
    runner = ReviewToolRunner(
        tmp_path,
        Settings(mongo_mock=True, llm_mock_enabled=True),
        current_file_name="main.c",
    )

    definition = runner.run("find_definition", {"symbol": "calculate"})
    references = runner.run("find_references", {"symbol": "calculate"})
    outgoing = runner.run(
        "call_graph",
        {"symbol": "calculate", "direction": "outgoing", "depth": 1},
    )
    incoming = runner.run(
        "call_graph",
        {"symbol": "calculate", "direction": "incoming", "depth": 1},
    )

    assert definition["definitions"][0]["file_path"] == "main.c"
    assert any(item["file_path"] == "math.c" and item["is_definition"] for item in definition["definitions"])
    assert any(item["file_path"] == "main.c" and item["reference_kind"] == "call" for item in references["references"])
    assert any(edge["caller"] == "calculate" and edge["callee"] == "add_one" for edge in outgoing["edges"])
    assert any(edge["caller"] == "main" and edge["callee"] == "calculate" for edge in incoming["edges"])
    assert definition["index"]["tree_sitter_files"] == 2


def test_semantic_tools_are_registered_for_main_task():
    tool_names = {item["function"]["name"] for item in MAIN_TOOL_DEFINITIONS}

    assert {"find_definition", "find_references", "call_graph"}.issubset(tool_names)


def test_semantic_tool_rejects_unsafe_file_scope(tmp_path: Path):
    (tmp_path / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    runner = ReviewToolRunner(tmp_path, Settings(mongo_mock=True, llm_mock_enabled=True))

    result = runner.run(
        "find_references",
        {"symbol": "main", "file_path": "../outside.c"},
    )

    assert "error" in result
    assert "escapes review root" in result["error"]
