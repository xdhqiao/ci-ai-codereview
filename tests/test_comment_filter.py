from pathlib import Path

from app.core.config import Settings
from app.models.code_file import CodeFileModel
from app.models.task import TaskModel
from app.services.comment_filter import comment_only_block_flags, is_comment_only_change
from app.services.review_service import ReviewTaskService


def test_comment_only_filter_supports_c_line_and_block_comments():
    assert is_comment_only_change(
        [
            "     1   /* existing documentation",
            "     2-   * old behavior",
            "     2+   * clarified behavior",
            "     3   */",
            "     4+  // another note",
        ],
        "C",
    )


def test_comment_only_filter_is_conservative_for_code_and_operational_comments():
    assert not is_comment_only_change(["     1+  int value = 1; // note"], "C")
    assert not is_comment_only_change(["     1+  #!/usr/bin/env bash"], "Shell")
    assert not is_comment_only_change(["     8+  # noqa: E501"], "Python")
    assert not is_comment_only_change(["     3+  /*+ INDEX(users idx_users) */"], "SQL")
    assert not is_comment_only_change(["     1+  this is prose"], "General")


def test_comment_only_filter_carries_block_comment_state_across_split_blocks():
    flags = comment_only_block_flags(
        [
            ["     1+  /* documentation starts"],
            ["     2+   * and continues after a token split", "     3+   */"],
        ],
        "C",
    )

    assert flags == [True, True]


def test_comment_only_full_scan_skips_every_llm_call_and_persists_perfect_scores(tmp_path: Path):
    class LLMCallMustNotHappen:
        is_mock = False

        def chat(self, *args, **kwargs):
            raise AssertionError("comment-only block must not call the LLM")

    source = tmp_path / "head"
    source.mkdir()
    (source / "notes.c").write_text(
        "/* Module documentation. */\n// No executable code changed.\n",
        encoding="utf-8",
    )
    task = TaskModel(
        project_id="comment-only",
        review_version=str(source),
        copy_from_version="0_version",
        task_type=2,
        state=0,
    ).save()
    service = ReviewTaskService(
        Settings(
            mongo_mock=True,
            llm_mock_enabled=False,
            full_scan_project_summary_llm_enabled=False,
        )
    )
    service.llm_client = LLMCallMustNotHappen()

    reviewed = service.review_task(task)

    code_file = CodeFileModel.objects(task_id=str(task.id)).first()
    block = code_file.code_blocks[0]
    assert reviewed.state == 2
    assert reviewed.llm_total_tokens == 0
    assert reviewed.llm_call_count == 0
    assert block.process_time == 0
    assert block.llm_total_tokens == 0
    assert block.main_task_completed is True
    assert block.main_task_completion_mode == "comment_only"
    assert block.review_state == 2
    assert block.issues == []
    assert block.model_rounds[0].stage == "comment_only_filter"
    assert {
        block.logic_score,
        block.performance_score,
        block.security_score,
        block.readable_score,
        block.code_style_score,
    } == {100}
