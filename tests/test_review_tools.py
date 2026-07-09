from pathlib import Path

from app.core.config import Settings
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
