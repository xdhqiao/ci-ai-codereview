import time
from pathlib import Path
from threading import Barrier, BrokenBarrierError

import pytest

from app.core.config import Settings, get_settings
from app.core.exceptions import ReviewInterruptedError
from app.models.code_file import CodeBlock, CodeFileModel, Issue
from app.models.task import TaskModel
from app.services.diff_service import ReviewTarget
from app.services.background import FileReviewBackground
from app.services.review_service import ReviewTaskService
from app.services.notification import ReviewNotificationService


class FakeRetryLLMClient:
    is_mock = False

    def __init__(self, comments):
        self.comments = comments
        self.chat_count = 0

    def complete_json(self, messages, tools=None):
        return {
            "comment": "plan ok",
            "logic_score": 80,
            "performance_score": 80,
            "security_score": 80,
            "readable_score": 80,
            "code_style_score": 80,
        }

    def chat(self, messages, tools=None):
        self.chat_count += 1
        joined = "\n".join(str(message.get("content") or "") for message in messages)
        if "REVIEW_FILTER_TASK" in joined:
            return {
                "role": "assistant",
                "content": (
                    '{"decisions":[{"issue_id":1,'
                    '"filter_status":"kept","filter_reason":"not disproved"}]}'
                ),
            }
        if self.chat_count == 1:
            return {
                "role": "assistant",
                "content": (
                    '{"comment":"plan ok","logic_score":80,"performance_score":80,'
                    '"security_score":80,"readable_score":80,"code_style_score":80}'
                ),
            }
        if self.chat_count == 2:
            return {"role": "assistant", "content": "not-json"}
        return {"role": "assistant", "content": self.comments}

    def _extract_json(self, content):
        import json

        return json.loads(content)


class FakeToolTraceLLMClient:
    is_mock = False

    def __init__(self):
        self.chat_count = 0
        self.main_count = 0

    def chat(self, messages, tools=None):
        self.chat_count += 1
        joined = "\n".join(str(message.get("content") or "") for message in messages)
        if "REVIEW_FILTER_TASK" in joined:
            return {
                "role": "assistant",
                "content": (
                    '{"decisions":[{"issue_id":1,'
                    '"filter_status":"kept","filter_reason":"valid","confidence_level":0.9}]}'
                ),
                "_llm_trace": {
                    "model": "fake-model",
                    "usage": {"prompt_tokens": 7, "completion_tokens": 4, "total_tokens": 11},
                    "elapsed_ms": 7,
                    "finish_reason": "stop",
                },
            }
        if tools is None:
            return {
                "role": "assistant",
                "content": (
                    '{"comment":"plan ok","logic_score":80,"performance_score":80,'
                    '"security_score":80,"readable_score":80,"code_style_score":80}'
                ),
                "_llm_trace": {
                    "model": "fake-model",
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                        "prompt_tokens_details": {"cached_tokens": 2},
                        "completion_tokens_details": {"reasoning_tokens": 3},
                    },
                    "elapsed_ms": 11,
                    "finish_reason": "stop",
                },
            }
        self.main_count += 1
        if self.main_count == 1:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "code_comment",
                            "arguments": (
                                '{"type":"security","severity":5,"description":"buffer overflow",'
                                '"suggestion":"use snprintf","issue_line_numbers":"1",'
                                '"existing_code":"int main(void) { return 0; }",'
                                '"suggestion_code":"snprintf(dst, sizeof(dst), \\"%s\\", input);",'
                                '"evidence":"matched changed line"}'
                            ),
                        },
                    }
                ],
                "_llm_trace": {
                    "model": "fake-model",
                    "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
                    "elapsed_ms": 22,
                    "finish_reason": "tool_calls",
                },
            }
        if self.main_count == 2:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {"name": "task_done", "arguments": '{"summary":"done"}'},
                    }
                ],
                "_llm_trace": {
                    "model": "fake-model",
                    "usage": {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7},
                    "elapsed_ms": 5,
                    "finish_reason": "tool_calls",
                },
            }
        raise AssertionError("unexpected fake LLM call")

    def _extract_json(self, content):
        import json

        return json.loads(content)


class FakeCompressionLLMClient:
    is_mock = False

    def __init__(self):
        self.chat_count = 0
        self.main_count = 0

    def chat(self, messages, tools=None):
        self.chat_count += 1
        joined = "\n".join(str(message.get("content") or "") for message in messages)
        if "REVIEW_FILTER_TASK" in joined:
            return {
                "role": "assistant",
                "content": (
                    '{"decisions":[{"issue_id":1,'
                    '"filter_status":"kept","filter_reason":"not disproved"}]}'
                ),
            }
        if tools is None:
            return {
                "role": "assistant",
                "content": (
                    '{"comment":"plan ok","logic_score":80,"performance_score":80,'
                    '"security_score":80,"readable_score":80,"code_style_score":80}'
                ),
            }
        self.main_count += 1
        if self.main_count in {1, 2}:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": f"read_{self.main_count}",
                        "type": "function",
                        "function": {"name": "file_read_diff", "arguments": '{"file_path":"main.c"}'},
                    }
                ],
            }
        if self.main_count == 3:
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "comment_1",
                        "type": "function",
                        "function": {
                            "name": "code_comment",
                            "arguments": (
                                '{"type":"security","severity":4,"description":"desc",'
                                '"suggestion":"fix","issue_line_numbers":"1","existing_code":"int main(void) { return 0; }",'
                                '"evidence":"matched changed line","confidence_level":0.8}'
                            ),
                        },
                    }
                ],
            }
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "done_1",
                    "type": "function",
                    "function": {"name": "task_done", "arguments": '{"summary":"done"}'},
                }
            ],
        }

    def _extract_json(self, content):
        import json

        return json.loads(content)


def test_incremental_review_saves_code_file_and_issues(tmp_path: Path):
    base_dir = tmp_path / "base"
    head_dir = tmp_path / "head"
    (base_dir / "src").mkdir(parents=True)
    (head_dir / "src").mkdir(parents=True)
    (base_dir / "src" / "app.py").write_text(
        "def run(value):\n"
        "    return value\n",
        encoding="utf-8",
    )
    (head_dir / "src" / "app.py").write_text(
        "def run(value):\n"
        "    secret = 'plain-text'\n"
        "    return eval(value)\n",
        encoding="utf-8",
    )

    task = TaskModel(
        project_id="review-project",
        review_version=str(head_dir),
        copy_from_version=str(base_dir),
        task_type=1,
        state=0,
    ).save()

    service = ReviewTaskService(get_settings())
    reviewed_task = service.review_task(task)

    assert reviewed_task.state == 2
    assert reviewed_task.file_num == 1
    assert reviewed_task.comment_line_number >= 2

    code_file = CodeFileModel.objects(task_id=str(task.id)).first()
    assert code_file.file_name == "src/app.py"
    assert code_file.code_blocks[0].block_id == 0
    assert code_file.code_blocks[0].issues[0].issue_id == 0
    assert code_file.code_blocks[0].contents[0][6] in {" ", "-", "+"}
    assert any(line[6] == "+" for line in code_file.code_blocks[0].contents)
    assert max(issue.severity for issue in code_file.code_blocks[0].issues) == 5


def test_full_scan_reviews_all_lines(tmp_path: Path):
    target_dir = tmp_path / "head"
    target_dir.mkdir()
    (target_dir / "script.py").write_text("print('hello')\n", encoding="utf-8")

    task = TaskModel(
        project_id="scan-project",
        review_version=str(target_dir),
        copy_from_version="",
        task_type=3,
        state=0,
    ).save()

    reviewed_task = ReviewTaskService(get_settings()).review_task(task)

    assert reviewed_task.state == 2
    code_file = CodeFileModel.objects(task_id=str(task.id)).first()
    assert code_file.file_name == "script.py"
    assert code_file.add_code_line_num == 1
    assert code_file.code_blocks[0].block_id == 0


def test_version_names_resolve_under_repository_root(tmp_path: Path):
    repository_root = tmp_path / "repositories"
    base_dir = repository_root / "demo_c" / "master"
    head_dir = repository_root / "demo_c" / "wip_qiaodahai_just_demo"
    base_dir.mkdir(parents=True)
    head_dir.mkdir(parents=True)
    (base_dir / "main.c").write_text("int main(void) {\n    return 0;\n}\n", encoding="utf-8")
    (head_dir / "main.c").write_text("int main(void) {\n    char secret[] = \"demo\";\n    return 0;\n}\n", encoding="utf-8")

    task = TaskModel(
        project_id="demo_c",
        review_version="wip_qiaodahai_just_demo",
        copy_from_version="master",
        state=0,
    ).save()
    settings = Settings(mongo_mock=True, llm_mock_enabled=True, code_repository_root=str(repository_root))

    reviewed_task = ReviewTaskService(settings).review_task(task)

    assert reviewed_task.task_type == 1
    assert reviewed_task.state == 2
    code_file = CodeFileModel.objects(task_id=str(task.id)).first()
    assert code_file.file_name == "main.c"
    assert code_file.task_type == 1


def test_zero_version_means_full_scan_under_repository_root(tmp_path: Path):
    repository_root = tmp_path / "repositories"
    target_dir = repository_root / "demo_c" / "master"
    target_dir.mkdir(parents=True)
    (target_dir / "main.c").write_text("int main(void) {\n    return 0;\n}\n", encoding="utf-8")

    task = TaskModel(
        project_id="demo_c",
        review_version="master",
        copy_from_version="0_version",
        state=0,
    ).save()
    settings = Settings(mongo_mock=True, llm_mock_enabled=True, code_repository_root=str(repository_root))

    reviewed_task = ReviewTaskService(settings).review_task(task)

    assert reviewed_task.task_type == 3
    assert reviewed_task.state == 2
    code_file = CodeFileModel.objects(task_id=str(task.id)).first()
    assert code_file.file_name == "main.c"
    assert code_file.task_type == 3
    assert code_file.add_code_line_num == 3


def test_main_task_retries_when_json_parse_fails(tmp_path: Path):
    target_dir = tmp_path / "head"
    target_dir.mkdir()
    (target_dir / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    task = TaskModel(
        project_id="retry-project",
        review_version=str(target_dir),
        copy_from_version="0_version",
        state=0,
    ).save()
    settings = Settings(mongo_mock=True, llm_mock_enabled=False, llm_json_retry_times=1)
    service = ReviewTaskService(settings)
    service.llm_client = FakeRetryLLMClient(
        '{"issues":[{"type":"security","severity":4,"description":"desc","suggestion":"fix",'
        '"issue_line_numbers":"1","existing_code":"int main(void) { return 0; }","evidence":"matched"}]}'
    )

    reviewed_task = service.review_task(task)

    assert reviewed_task.comment_line_number == 1
    code_file = CodeFileModel.objects(task_id=str(task.id)).first()
    assert code_file.code_blocks[0].issues[0].description == "desc"
    assert code_file.code_blocks[0].failure_message == ""


def test_duplicate_issues_are_merged_within_current_file(tmp_path: Path):
    target_dir = tmp_path / "head"
    target_dir.mkdir()
    (target_dir / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    task = TaskModel(
        project_id="merge-project",
        review_version=str(target_dir),
        copy_from_version="0_version",
        state=0,
    ).save()
    settings = Settings(mongo_mock=True, llm_mock_enabled=False, llm_json_retry_times=1)
    service = ReviewTaskService(settings)
    service.llm_client = FakeRetryLLMClient(
        '{"issues":['
        '{"type":"security","severity":4,"description":"same","suggestion":"fix","issue_line_numbers":"1",'
        '"existing_code":"int main(void) { return 0; }","evidence":"matched"},'
        '{"type":"security","severity":4,"description":"same","suggestion":"fix","issue_line_numbers":"1",'
        '"existing_code":"int main(void) { return 0; }","evidence":"matched"}'
        "]}"
    )

    reviewed_task = service.review_task(task)

    assert reviewed_task.comment_line_number == 1
    code_file = CodeFileModel.objects(task_id=str(task.id)).first()
    assert len(code_file.code_blocks[0].issues) == 1


def test_semantic_duplicate_issues_merge_only_with_same_line_and_evidence():
    service = ReviewTaskService(Settings(mongo_mock=True, llm_mock_enabled=True))
    first = Issue(
        issue_id=1,
        type="security",
        severity=5,
        description="unchecked copy can overflow destination buffer",
        suggestion="use a bounded copy",
        issue_line_numbers="12",
        existing_code="strcpy(dst, src);",
        evidence="no destination size",
    )
    duplicate = Issue(
        issue_id=2,
        type="security",
        severity=5,
        description="destination buffer can overflow because copy is unchecked",
        suggestion="pass the destination size",
        issue_line_numbers="12",
        existing_code="strcpy(dst, src);",
        evidence="the copy is unbounded",
    )
    different_location = Issue(
        issue_id=3,
        type="security",
        severity=5,
        description="destination buffer can overflow because copy is unchecked",
        suggestion="pass the destination size",
        issue_line_numbers="30",
        existing_code="strcpy(dst, src);",
        evidence="a separate copy is unbounded",
    )
    block = CodeBlock(block_id=1, contents=[], issues=[first, duplicate, different_location])

    service._merge_duplicate_file_issues([block])

    assert len(block.issues) == 2
    assert {issue.issue_line_numbers for issue in block.issues} == {"12", "30"}


def test_model_rounds_tool_calls_and_usage_are_persisted(tmp_path: Path):
    target_dir = tmp_path / "head"
    target_dir.mkdir()
    (target_dir / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    task = TaskModel(
        project_id="trace-project",
        review_version=str(target_dir),
        copy_from_version="0_version",
        state=0,
    ).save()
    settings = Settings(mongo_mock=True, llm_mock_enabled=False)
    service = ReviewTaskService(settings)
    service.llm_client = FakeToolTraceLLMClient()

    reviewed_task = service.review_task(task)

    assert reviewed_task.comment_line_number == 1
    code_file = CodeFileModel.objects(task_id=str(task.id)).first()
    block = code_file.code_blocks[0]
    assert block.llm_prompt_tokens == 41
    assert block.llm_completion_tokens == 22
    assert block.llm_total_tokens == 63
    assert block.llm_reasoning_tokens == 3
    assert block.llm_cached_tokens == 2
    assert block.llm_elapsed_ms == 45
    assert [trace.stage for trace in block.model_rounds] == [
        "plan_task",
        "main_task",
        "main_task",
        "re_location_task",
        "review_filter_task",
        "review_filter_task",
    ]
    assert [trace.tool_name for trace in block.tool_calls] == ["code_comment", "task_done"]
    assert block.tool_calls[0].success is True


def test_local_relocation_moves_issue_to_changed_line(tmp_path: Path):
    service = ReviewTaskService(Settings(mongo_mock=True, llm_mock_enabled=True))
    target = ReviewTarget(
        file_name="main.c",
        diff_lines=[
            "     1+  int main(void) {",
            "     2+      char dst[8];",
            "     3+      strcpy(dst, input);",
            "     4+      return 0;",
            "     5+  }",
        ],
        full_code="int main(void) {\n    char dst[8];\n    strcpy(dst, input);\n    return 0;\n}\n",
        language="C",
        code_line_num=5,
        add_code_line_num=5,
    )
    issue = Issue(
        issue_id=1,
        type="security",
        severity=5,
        description="buffer overflow from strcpy",
        suggestion="use snprintf",
        issue_line_numbers="999",
        existing_code="strcpy(dst, input);",
        evidence="strcpy copies input into fixed buffer",
        confidence_level=0.9,
    )

    issues, traces, failure = service._run_relocation_task(target, target.diff_lines, [issue])

    assert failure == ""
    assert issues[0].issue_line_numbers == "3"
    assert issues[0].original_issue_line_numbers == "999"
    assert issues[0].relocation_status == "relocated"
    assert traces[0].stage == "re_location_task"


def test_deletion_only_regression_anchors_to_affected_surviving_line():
    service = ReviewTaskService(Settings(mongo_mock=True, llm_mock_enabled=True))
    diff_lines = [
        "     1   int safe_divide(int left, int right, int *result) {",
        "     2-      if (result == 0 || right == 0) {",
        "     3-          return -1;",
        "     4-      }",
        "     2       *result = left / right;",
        "     3       return 0;",
        "     4   }",
    ]
    target = ReviewTarget(
        file_name="math_utils.c",
        diff_lines=diff_lines,
        full_code="int safe_divide(int left, int right, int *result) {\n    *result = left / right;\n    return 0;\n}\n",
        language="C",
        code_line_num=4,
        add_code_line_num=0,
    )
    issue = Issue(
        issue_id=1,
        type="logic",
        severity=5,
        description="removed validation permits null dereference and division by zero",
        suggestion="restore the validation before division",
        issue_line_numbers="2",
        existing_code="*result = left / right;",
        evidence="the deleted guard previously rejected a null result and a zero divisor",
        confidence_level=0.95,
    )

    relocated, _, relocation_failure = service._run_relocation_task(target, diff_lines, [issue])
    filtered, _, filter_failure = service._run_review_filter_task(target, diff_lines, relocated)

    assert relocation_failure == ""
    assert filter_failure == ""
    assert filtered[0].filter_status == "kept"
    assert filtered[0].relocation_status == "unchanged"
    assert filtered[0].evidence_source == "diff_deletion_anchor"
    assert filtered[0].issue_line_numbers == "2"


def test_deletion_anchor_does_not_make_unrelated_context_reviewable():
    service = ReviewTaskService(Settings(mongo_mock=True, llm_mock_enabled=True))
    diff_lines = [
        "     1   int run(void) {",
        "     2-      validate();",
        "     2       execute();",
        "     3       audit();",
        "     4   }",
    ]
    target = ReviewTarget(
        file_name="main.c",
        diff_lines=diff_lines,
        full_code="int run(void) {\n    execute();\n    audit();\n}\n",
        language="C",
        code_line_num=4,
        add_code_line_num=0,
    )
    issue = Issue(
        issue_id=1,
        type="logic",
        severity=3,
        description="unrelated audit concern",
        suggestion="change audit",
        issue_line_numbers="3",
        existing_code="audit();",
        evidence="the line is unchanged and not adjacent to the deletion",
        confidence_level=0.9,
    )

    relocated, _, _ = service._run_relocation_task(target, diff_lines, [issue])

    assert relocated[0].relocation_status == "failed"
    assert relocated[0].filter_status == ""


def test_local_review_filter_hides_low_confidence_issue():
    service = ReviewTaskService(Settings(mongo_mock=True, llm_mock_enabled=True, review_filter_min_confidence=0.5))
    issue = Issue(
        issue_id=1,
        type="logic",
        severity=2,
        description="maybe wrong",
        suggestion="check",
        issue_line_numbers="1",
        existing_code="int main(void) { return 0; }",
        evidence="matched changed line",
        confidence_level=0.2,
    )

    issues, traces, failure = service._run_review_filter_task(
        ReviewTarget(
            file_name="main.c",
            diff_lines=["     1+  int main(void) { return 0; }"],
            full_code="int main(void) { return 0; }\n",
            language="C",
            code_line_num=1,
            add_code_line_num=1,
        ),
        ["     1+  int main(void) { return 0; }"],
        [issue],
    )

    assert failure == ""
    assert issues[0].filter_status == "filtered"
    assert "置信度" in issues[0].filter_reason
    assert traces[0].stage == "review_filter_task"


def test_local_review_filter_hides_mismatched_existing_code():
    service = ReviewTaskService(
        Settings(
            mongo_mock=True,
            llm_mock_enabled=True,
            review_line_evidence_min_similarity=0.8,
        )
    )
    issue = Issue(
        issue_id=1,
        type="security",
        severity=5,
        description="unsafe copy",
        suggestion="use snprintf",
        issue_line_numbers="1",
        existing_code="strcpy(dst, input);",
        evidence="unsafe copy should be present in changed line",
        confidence_level=0.9,
    )

    issues, _, _ = service._run_review_filter_task(
        ReviewTarget(
            file_name="main.c",
            diff_lines=["     1+  int main(void) { return 0; }"],
            full_code="int main(void) { return 0; }\n",
            language="C",
            code_line_num=1,
            add_code_line_num=1,
        ),
        ["     1+  int main(void) { return 0; }"],
        [issue],
    )

    assert issues[0].filter_status == "filtered"
    assert issues[0].evidence_match_status == "missing"
    assert "existing_code" in issues[0].filter_reason


def test_main_task_context_compression_is_persisted(tmp_path: Path):
    target_dir = tmp_path / "head"
    target_dir.mkdir()
    (target_dir / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    task = TaskModel(
        project_id="compression-project",
        review_version=str(target_dir),
        copy_from_version="0_version",
        state=0,
    ).save()
    settings = Settings(
        mongo_mock=True,
        llm_mock_enabled=False,
        llm_context_compress_rounds=2,
        llm_max_tool_rounds=5,
    )
    service = ReviewTaskService(settings)
    service.llm_client = FakeCompressionLLMClient()

    reviewed_task = service.review_task(task)

    assert reviewed_task.comment_line_number == 1
    code_file = CodeFileModel.objects(task_id=str(task.id)).first()
    block = code_file.code_blocks[0]
    assert block.memory_compression_count >= 1
    assert "memory_compression" in [trace.stage for trace in block.model_rounds]


def test_main_task_context_compression_uses_token_threshold(tmp_path: Path):
    target_dir = tmp_path / "head"
    target_dir.mkdir()
    (target_dir / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    task = TaskModel(
        project_id="compression-token-project",
        review_version=str(target_dir),
        copy_from_version="0_version",
        state=0,
    ).save()
    settings = Settings(
        mongo_mock=True,
        llm_mock_enabled=False,
        llm_context_compress_rounds=0,
        llm_context_compress_token_threshold=20,
        llm_max_tool_rounds=5,
    )
    service = ReviewTaskService(settings)
    service.llm_client = FakeCompressionLLMClient()

    service.review_task(task)

    code_file = CodeFileModel.objects(task_id=str(task.id)).first()
    block = code_file.code_blocks[0]
    compression_traces = [trace for trace in block.model_rounds if trace.stage == "memory_compression"]
    assert compression_traces
    assert '"trigger": "token"' in compression_traces[0].request_summary


def test_external_json_rule_resolver_is_used(tmp_path: Path):
    rule_path = tmp_path / "rules.json"
    rule_path.write_text(
        '{"languages":[{"language":"C","extensions":[".c"],"focus":["custom c rule"]}]}',
        encoding="utf-8",
    )
    from app.services.rules import ReviewRuleResolver

    resolver = ReviewRuleResolver(Settings(mongo_mock=True, review_rules_path=str(rule_path)))

    resolved = resolver.resolve("src/main.c", "C")

    assert "custom c rule" in resolved["focus"]

    from app.services.prompts import build_plan_messages

    messages = build_plan_messages(
        file_name="src/main.c",
        language="C",
        diff_lines=["     1+  int main(void) { return 0; }"],
        full_code="int main(void) { return 0; }\n",
        settings=Settings(mongo_mock=True, review_rules_path=str(rule_path)),
    )
    assert "custom c rule" in messages[1]["content"]


def test_project_local_ocr_rule_is_auto_discovered(tmp_path: Path):
    rule_dir = tmp_path / ".opencodereview"
    rule_dir.mkdir()
    rule_path = rule_dir / "rule.json"
    rule_path.write_text(
        '{"rules":[{"path":"**/*.c","rule":"project-local rule"}]}',
        encoding="utf-8",
    )
    service = ReviewTaskService(Settings(mongo_mock=True, llm_mock_enabled=True))

    resolved_settings = service._resolve_rule_settings(tmp_path)

    assert resolved_settings.review_rules_path == str(rule_path)
    from app.services.rules import ReviewRuleResolver

    assert ReviewRuleResolver(resolved_settings).resolve("main.c", "C")["focus"] == ["project-local rule"]


def test_ocr_style_rules_use_first_match_and_brace_expansion(tmp_path: Path):
    from app.services.rules import ReviewRuleResolver

    rule_path = tmp_path / "ocr-rules.json"
    rule_path.write_text(
        (
            '{"rules":['
            '{"id":"specific","path":"src/*.{c,h}","rule":"specific source rule"},'
            '{"id":"fallback","path":"**/*.c","rule":"fallback c rule"}'
            ']}'
        ),
        encoding="utf-8",
    )
    settings = Settings(mongo_mock=True, llm_mock_enabled=True, review_rules_path=str(rule_path))

    resolved = ReviewRuleResolver(settings).resolve("src/main.c", "C")

    assert resolved["focus"] == ["specific source rule"]
    assert resolved["matched_rule_id"] == "specific"
    assert resolved["resolution"] == "first-match"


def test_file_level_concurrency_uses_configured_limit(tmp_path: Path):
    target_dir = tmp_path / "head"
    target_dir.mkdir()
    (target_dir / "a.c").write_text("int a(void) { return 0; }\n", encoding="utf-8")
    (target_dir / "b.c").write_text("int b(void) { return 0; }\n", encoding="utf-8")
    task = TaskModel(
        project_id="concurrency-project",
        review_version=str(target_dir),
        copy_from_version="0_version",
        state=0,
    ).save()
    settings = Settings(mongo_mock=True, llm_mock_enabled=True, llm_concurrency=2, scan_batch_size=2)
    service = ReviewTaskService(settings)
    barrier = Barrier(2, timeout=2)
    overlapped = {"value": False}

    def fake_review_file(task_model, target, review_root):
        try:
            barrier.wait()
            overlapped["value"] = True
        except BrokenBarrierError:
            overlapped["value"] = False
        return CodeFileModel(
            task_id=str(task_model.id),
            project_id=task_model.project_id,
            review_version=task_model.review_version,
            copy_from_version=task_model.copy_from_version,
            task_type=task_model.task_type,
            file_name=target.file_name,
            code_blocks=[],
        )

    service._review_file = fake_review_file

    reviewed_task = service.review_task(task)

    assert reviewed_task.state == 2
    assert overlapped["value"] is True


def test_full_scan_batches_are_grouped_by_language():
    service = ReviewTaskService(
        Settings(mongo_mock=True, llm_mock_enabled=True, scan_batch_strategy="by-language")
    )
    task = TaskModel(
        project_id="batch-language",
        review_version="head",
        copy_from_version="0_version",
        task_type=3,
        state=0,
    )
    targets = [
        ReviewTarget("b.py", [], "", "Python", 0, 0, change_type="FULL"),
        ReviewTarget("a.c", [], "", "C", 0, 0, change_type="FULL"),
        ReviewTarget("c.c", [], "", "C", 0, 0, change_type="FULL"),
    ]

    batches = service._group_target_batches(task, targets, batch_size=2)

    assert [[target.file_name for target in batch] for batch in batches] == [["a.c", "c.c"], ["b.py"]]


def test_full_scan_token_budget_skips_files(tmp_path: Path):
    target_dir = tmp_path / "head"
    target_dir.mkdir()
    (target_dir / "a.c").write_text("int a(void) { return 0; }\n", encoding="utf-8")
    (target_dir / "b.c").write_text(("int b(void) { return 0; }\n" * 80), encoding="utf-8")
    task = TaskModel(
        project_id="budget-project",
        review_version=str(target_dir),
        copy_from_version="0_version",
        state=0,
    ).save()
    settings = Settings(mongo_mock=True, llm_mock_enabled=True, full_scan_token_budget=20)

    reviewed_task = ReviewTaskService(settings).review_task(task)

    assert reviewed_task.state == 3
    assert reviewed_task.completion_status == "partial"
    assert reviewed_task.incomplete_file_num == 1
    assert reviewed_task.skipped_file_num == 1
    assert reviewed_task.token_budget_num == 20
    assert reviewed_task.automatic_retry_pending is False
    assert reviewed_task.next_retry_time is None
    skipped = CodeFileModel.objects(task_id=str(task.id), file_name="b.c").first()
    assert skipped.extra["status"] == "skipped_budget"
    assert skipped.code_blocks == []


def test_review_task_resume_reuses_completed_file(tmp_path: Path):
    target_dir = tmp_path / "head"
    target_dir.mkdir()
    (target_dir / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    task = TaskModel(
        project_id="resume-project",
        review_version=str(target_dir),
        copy_from_version="0_version",
        state=0,
    ).save()
    settings = Settings(mongo_mock=True, llm_mock_enabled=True, review_resume_enabled=True)
    service = ReviewTaskService(settings)

    service.review_task(task)
    task.reload()
    task.state = 0
    task.save()
    reviewed_task = service.review_task(task)

    assert reviewed_task.resumed_file_num == 1
    assert reviewed_task.reviewed_file_num == 1
    assert CodeFileModel.objects(task_id=str(task.id)).count() == 1
    code_file = CodeFileModel.objects(task_id=str(task.id)).first()
    assert code_file.extra["status"] == "resumed"


def test_completion_email_failure_does_not_change_completed_review_to_failed(monkeypatch, tmp_path: Path):
    target_dir = tmp_path / "head"
    target_dir.mkdir()
    (target_dir / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    task = TaskModel(
        project_id="email-failure-project",
        review_version=str(target_dir),
        copy_from_version="0_version",
        task_type=3,
        state=0,
    ).save()

    def fail_email(_self, _task):
        raise RuntimeError("mail server unavailable")

    monkeypatch.setattr(ReviewNotificationService, "send_review_completed", fail_email)
    settings = Settings(
        mongo_mock=True,
        llm_mock_enabled=True,
        full_scan_project_summary_enabled=False,
        full_scan_batch_dedup_enabled=False,
    )

    reviewed_task = ReviewTaskService(settings).review_task(task)

    reviewed_task.reload()
    assert reviewed_task.state == 2
    assert reviewed_task.completion_status == "completed"
    assert reviewed_task.completion_email_sent is False


def test_finish_task_does_not_overwrite_a_newer_trigger_revision(monkeypatch):
    task = TaskModel(
        project_id="finish-race-project",
        review_version="master",
        copy_from_version="0_version",
        task_type=3,
        state=1,
        trigger_revision=1,
        lease_owner="worker",
        lease_token="lease-1",
    ).save()
    service = ReviewTaskService(
        Settings(mongo_mock=True, llm_mock_enabled=True),
        lease_token="lease-1",
    )
    service.active_task_id = str(task.id)
    service.active_trigger_revision = 1

    def retrigger_while_summarizing(*_args, **_kwargs):
        TaskModel.objects(id=task.id).update_one(
            inc__trigger_revision=1,
            set__state=4,
            set__completion_status="preparing",
            set__interrupt_requested=True,
        )
        return "outdated project summary"

    monkeypatch.setattr(service, "_maybe_generate_project_summary", retrigger_while_summarizing)

    with pytest.raises(ReviewInterruptedError):
        service._finish_task(task, [], time.monotonic())

    task.reload()
    assert task.trigger_revision == 2
    assert task.state == 4
    assert task.completion_status == "preparing"
    assert task.project_summary == ""
    assert task.interrupt_requested is True


def test_review_resume_is_invalidated_when_model_changes(tmp_path: Path):
    target_dir = tmp_path / "head"
    target_dir.mkdir()
    (target_dir / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    task = TaskModel(
        project_id="resume-model-project",
        review_version=str(target_dir),
        copy_from_version="0_version",
        state=0,
    ).save()

    ReviewTaskService(
        Settings(mongo_mock=True, llm_mock_enabled=True, llm_model="model-a")
    ).review_task(task)
    task.reload()
    first_file = CodeFileModel.objects(task_id=str(task.id)).first()
    first_fingerprint = first_file.extra["review_fingerprint"]
    task.state = 0
    task.save()

    reviewed_task = ReviewTaskService(
        Settings(mongo_mock=True, llm_mock_enabled=True, llm_model="model-b")
    ).review_task(task)
    second_file = CodeFileModel.objects(task_id=str(task.id)).first()

    assert reviewed_task.resumed_file_num == 0
    assert second_file.extra["status"] == "reviewed"
    assert second_file.extra["review_fingerprint"] != first_fingerprint


def test_manual_retry_only_reviews_failed_blocks_and_preserves_other_files(tmp_path: Path):
    target_dir = tmp_path / "head"
    target_dir.mkdir()
    (target_dir / "failed.c").write_text(
        "\n".join(f"int failed_{index}(void) {{ return {index}; }}" for index in range(8)) + "\n",
        encoding="utf-8",
    )
    (target_dir / "completed.c").write_text(
        "int completed(void) { return 0; }\n",
        encoding="utf-8",
    )
    task = TaskModel(
        project_id="manual-retry-project",
        review_version=str(target_dir),
        copy_from_version="0_version",
        state=0,
    ).save()
    base_settings = dict(
        mongo_mock=True,
        llm_mock_enabled=True,
        diff_token_threshold=12,
        review_exclude_paths="",
        full_scan_batch_dedup_enabled=False,
        full_scan_project_summary_enabled=False,
    )
    ReviewTaskService(Settings(**base_settings, llm_model="model-a")).review_task(task)

    failed_file = CodeFileModel.objects(task_id=str(task.id), file_name="failed.c").first()
    completed_file = CodeFileModel.objects(task_id=str(task.id), file_name="completed.c").first()
    assert failed_file is not None and len(failed_file.code_blocks) > 1
    assert completed_file is not None
    untouched_file_attempts = [block.review_attempt_count for block in completed_file.code_blocks]
    untouched_file_fingerprints = [block.review_fingerprint for block in completed_file.code_blocks]
    failed_block_attempts = [block.review_attempt_count for block in failed_file.code_blocks]

    failed_file.code_blocks[0].main_task_completed = False
    failed_file.code_blocks[0].review_state = 3
    failed_file.code_blocks[0].failure_message = "simulated timeout"
    failed_file.state = 3
    failed_file.extra = {**(failed_file.extra or {}), "status": "partial", "review_complete": False}
    failed_file.save()
    task.reload()
    task.state = 0
    task.completion_status = "retry_pending"
    task.retry_failed_only = True
    task.dispatch_priority = 100
    task.save()

    reviewed_task = ReviewTaskService(Settings(**base_settings, llm_model="model-b")).review_task(task)

    failed_file.reload()
    completed_file.reload()
    assert reviewed_task.state == 2
    assert reviewed_task.completion_status == "completed"
    assert reviewed_task.retry_failed_only is False
    assert CodeFileModel.objects(task_id=str(task.id)).count() == 2
    assert [block.review_attempt_count for block in completed_file.code_blocks] == untouched_file_attempts
    assert [block.review_fingerprint for block in completed_file.code_blocks] == untouched_file_fingerprints
    assert failed_file.code_blocks[0].review_attempt_count == failed_block_attempts[0] + 1
    assert failed_file.code_blocks[0].failure_message == ""
    assert [block.review_attempt_count for block in failed_file.code_blocks[1:]] == failed_block_attempts[1:]


def test_full_scan_batch_dedup_groups_without_hiding_file_occurrences(tmp_path: Path):
    target_dir = tmp_path / "head"
    target_dir.mkdir()
    unsafe_code = "void f(char *input) {\n    char dst[8];\n    strcpy(dst, input);\n}\n"
    (target_dir / "a.c").write_text(unsafe_code, encoding="utf-8")
    (target_dir / "b.c").write_text(unsafe_code, encoding="utf-8")
    task = TaskModel(
        project_id="dedup-project",
        review_version=str(target_dir),
        copy_from_version="0_version",
        state=0,
    ).save()
    settings = Settings(
        mongo_mock=True,
        llm_mock_enabled=True,
        scan_batch_size=2,
        full_scan_batch_dedup_enabled=True,
    )

    reviewed_task = ReviewTaskService(settings).review_task(task)

    assert reviewed_task.comment_line_number == 2
    code_files = list(CodeFileModel.objects(task_id=str(task.id)).order_by("file_name"))
    all_issues = [issue for code_file in code_files for block in code_file.code_blocks for issue in block.issues]
    assert len({issue.duplicate_group_id for issue in all_issues}) == 1
    assert all(issue.filter_status != "filtered" for issue in all_issues)
    assert sum(1 for issue in all_issues if issue.duplicate_of) == 1
    assert "_project_summary" in reviewed_task.developer_issue_summary
    assert reviewed_task.project_summary


def test_multiline_evidence_is_relocated_as_one_contiguous_range():
    service = ReviewTaskService(Settings(mongo_mock=True, llm_mock_enabled=True))
    diff_lines = [
        "     1+  int copy(char *dst, const char *src) {",
        "     2+      strcpy(dst, src);",
        "     3+      return 0;",
        "     4+  }",
    ]
    target = ReviewTarget(
        file_name="copy.c",
        diff_lines=diff_lines,
        full_code="int copy(char *dst, const char *src) {\n    strcpy(dst, src);\n    return 0;\n}\n",
        language="C",
        code_line_num=4,
        add_code_line_num=4,
    )
    issue = Issue(
        issue_id=1,
        type="security",
        severity=5,
        description="unbounded copy",
        suggestion="pass the destination capacity",
        issue_line_numbers="999",
        existing_code="strcpy(dst, src);\nreturn 0;",
        evidence="the copy has no destination bound",
        confidence_level=0.95,
    )

    issues, _, failure = service._run_relocation_task(target, diff_lines, [issue])

    assert failure == ""
    assert issues[0].issue_line_numbers == "2-3"
    assert issues[0].evidence_start_line == 2
    assert issues[0].evidence_end_line == 3
    assert issues[0].evidence_match_status == "matched"
    assert issues[0].evidence_occurrence_count == 1


def test_ambiguous_evidence_without_valid_original_line_is_not_guessed():
    service = ReviewTaskService(Settings(mongo_mock=True, llm_mock_enabled=True))
    diff_lines = [
        "     1+  if (ready) return 0;",
        "     2+  work();",
        "     3+  if (ready) return 0;",
    ]
    target = ReviewTarget(
        file_name="duplicate.c",
        diff_lines=diff_lines,
        full_code="if (ready) return 0;\nwork();\nif (ready) return 0;\n",
        language="C",
        code_line_num=3,
        add_code_line_num=3,
    )
    issue = Issue(
        issue_id=1,
        type="logic",
        severity=3,
        description="ambiguous return",
        suggestion="clarify the branch",
        issue_line_numbers="999",
        existing_code="if (ready) return 0;",
        evidence="the same code appears twice",
        confidence_level=0.8,
    )

    issues, _, _ = service._run_relocation_task(target, diff_lines, [issue])

    assert issues[0].relocation_status == "failed"
    assert issues[0].location_ambiguous is True
    assert issues[0].evidence_occurrence_count == 2


def test_filter_cannot_remove_issue_without_diff_counter_evidence():
    service = ReviewTaskService(Settings(mongo_mock=True, llm_mock_enabled=True))
    issue = Issue(
        issue_id=1,
        type="logic",
        severity=3,
        description="validated issue",
        suggestion="fix it",
        issue_line_numbers="1",
        existing_code="return value;",
        evidence="the new return bypasses validation",
    )

    service._apply_filter_response(
        [issue],
        {
            "decisions": [
                {
                    "issue_id": 1,
                    "filter_status": "filtered",
                    "filter_reason": "uncertain",
                }
            ]
        },
    )

    assert issue.filter_status == "kept"
    assert "直接反证" in issue.filter_reason


def test_main_task_without_task_done_is_persisted_as_partial(tmp_path: Path):
    class NoDoneLLMClient:
        is_mock = False

        def chat(self, messages, tools=None):
            if tools is None:
                return {
                    "role": "assistant",
                    "content": (
                        '{"comment":"plan","logic_score":80,"performance_score":80,'
                        '"security_score":80,"readable_score":80,"code_style_score":80}'
                    ),
                }
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "read_diff",
                        "type": "function",
                        "function": {
                            "name": "file_read_diff",
                            "arguments": '{"path_array":["main.c"]}',
                        },
                    }
                ],
            }

        def _extract_json(self, content):
            import json

            return json.loads(content)

    target_dir = tmp_path / "head"
    target_dir.mkdir()
    (target_dir / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    task = TaskModel(
        project_id="strict-completion",
        review_version=str(target_dir),
        copy_from_version="0_version",
        state=0,
    ).save()
    service = ReviewTaskService(
        Settings(
            mongo_mock=True,
            llm_mock_enabled=False,
            llm_max_tool_rounds=2,
            full_scan_max_tool_rounds=2,
        )
    )
    service.llm_client = NoDoneLLMClient()

    reviewed_task = service.review_task(task)

    block = CodeFileModel.objects(task_id=str(task.id)).first().code_blocks[0]
    assert reviewed_task.state == 3
    assert reviewed_task.automatic_retry_pending is True
    assert reviewed_task.next_retry_time is not None
    assert block.main_task_completed is False
    assert block.main_task_completion_mode == "max_rounds"
    assert "without task_done" in block.failure_message


def test_invalid_tool_arguments_are_returned_to_model_without_crashing(tmp_path: Path):
    class InvalidArgumentsLLMClient:
        is_mock = False

        def __init__(self):
            self.main_round = 0

        def chat(self, messages, tools=None):
            if tools is None:
                return {
                    "role": "assistant",
                    "content": (
                        '{"comment":"plan","logic_score":80,"performance_score":80,'
                        '"security_score":80,"readable_score":80,"code_style_score":80}'
                    ),
                }
            self.main_round += 1
            if self.main_round == 1:
                return {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "bad_args",
                            "type": "function",
                            "function": {"name": "code_search", "arguments": "{"},
                        }
                    ],
                }
            return {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "done",
                        "type": "function",
                        "function": {"name": "task_done", "arguments": '{"state":"DONE"}'},
                    }
                ],
            }

        def _extract_json(self, content):
            import json

            return json.loads(content)

    target_dir = tmp_path / "head"
    target_dir.mkdir()
    (target_dir / "main.c").write_text("int main(void) { return 0; }\n", encoding="utf-8")
    task = TaskModel(
        project_id="invalid-tool-args",
        review_version=str(target_dir),
        copy_from_version="0_version",
        state=0,
    ).save()
    service = ReviewTaskService(Settings(mongo_mock=True, llm_mock_enabled=False, review_filter_enabled=False))
    service.llm_client = InvalidArgumentsLLMClient()

    reviewed_task = service.review_task(task)

    block = CodeFileModel.objects(task_id=str(task.id)).first().code_blocks[0]
    assert reviewed_task.state == 2
    assert block.main_task_completed is True
    assert block.failure_message == ""
    assert block.tool_calls[0].success is False
    assert "Invalid arguments" in block.tool_calls[0].error_message


def test_semantic_batch_dedup_is_strict_and_persists_task_trace():
    class DedupLLMClient:
        is_mock = False

        def chat(self, messages, tools=None):
            return {
                "role": "assistant",
                "content": '{"groups":[{"members":["c-0","c-1"]}]}',
                "_llm_trace": {
                    "model": "dedup-model",
                    "usage": {"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11},
                    "elapsed_ms": 4,
                    "finish_reason": "stop",
                },
            }

        def _extract_json(self, content):
            import json

            return json.loads(content)

    settings = Settings(
        mongo_mock=True,
        llm_mock_enabled=False,
        full_scan_batch_dedup_min_comments=2,
    )
    service = ReviewTaskService(settings)
    service.llm_client = DedupLLMClient()
    task = TaskModel(
        project_id="semantic-dedup",
        review_version="head",
        copy_from_version="0_version",
        task_type=3,
        state=1,
    ).save()

    def make_file(path: str, description: str) -> CodeFileModel:
        issue = Issue(
            issue_id=1,
            type="security",
            severity=5,
            description=description,
            suggestion="use a bounded copy",
            issue_line_numbers="1",
            existing_code="strcpy(dst, src);",
            evidence="the destination bound is unavailable",
            rule_id="c-buffer-boundary",
        )
        return CodeFileModel(
            task_id=str(task.id),
            project_id=task.project_id,
            review_version=task.review_version,
            copy_from_version=task.copy_from_version,
            task_type=3,
            file_name=path,
            code_blocks=[CodeBlock(block_id=1, contents=["     1+  strcpy(dst, src);"], issues=[issue])],
            comment_line_number=1,
            extra={"status": "reviewed"},
        ).save()

    code_files = [
        make_file("a.c", "unchecked copy into a fixed buffer"),
        make_file("b.c", "fixed buffer copy is unchecked"),
    ]

    duplicate_count = service._semantic_batch_deduplicate(task, code_files, batch_index=1)

    assert duplicate_count == 1
    assert code_files[0].code_blocks[0].issues[0].filter_status == ""
    assert code_files[1].code_blocks[0].issues[0].filter_status == ""
    assert code_files[1].code_blocks[0].issues[0].duplicate_of.startswith("a.c#block1")
    assert code_files[1].code_blocks[0].issues[0].filter_status == ""
    assert service.task_model_rounds[0].stage == "batch_dedup_task_1"


def test_file_background_is_injected_into_prompts_and_persisted(tmp_path: Path):
    class CapturingBackgroundProvider:
        def __init__(self):
            self.call_count = 0

        def get_background(self, project_id: str, review_version: str, file_name: str):
            self.call_count += 1
            assert project_id == "background-project"
            assert file_name == "auth.c"
            return FileReviewBackground(
                content="Authentication failures must fail closed.",
                source="test:requirement",
            )

    target_dir = tmp_path / "head"
    target_dir.mkdir()
    (target_dir / "auth.c").write_text("int authenticate(void) { return 0; }\n", encoding="utf-8")
    task = TaskModel(
        project_id="background-project",
        review_version=str(target_dir),
        copy_from_version="0_version",
        state=0,
    ).save()
    provider = CapturingBackgroundProvider()
    service = ReviewTaskService(
        Settings(mongo_mock=True, llm_mock_enabled=True),
        background_provider=provider,
    )

    service.review_task(task)

    code_file = CodeFileModel.objects(task_id=str(task.id)).first()
    assert code_file.background == "Authentication failures must fail closed."
    assert code_file.background_source == "test:requirement"
    assert code_file.extra["background_source"] == "test:requirement"
    assert provider.call_count == 1

    from app.services.prompts import build_main_messages, build_plan_messages

    plan_messages = build_plan_messages(
        file_name="auth.c",
        language="C",
        diff_lines=["     1+  int authenticate(void) { return 0; }"],
        full_code="int authenticate(void) { return 0; }\n",
        background=code_file.background,
    )
    main_messages = build_main_messages(
        file_name="auth.c",
        language="C",
        diff_lines=["     1+  int authenticate(void) { return 0; }"],
        full_code="int authenticate(void) { return 0; }\n",
        plan_guidance="{}",
        background=code_file.background,
    )
    assert code_file.background in plan_messages[1]["content"]
    assert code_file.background in main_messages[1]["content"]


def test_full_scan_llm_project_summary_and_task_usage_are_persisted():
    class SummaryLLMClient:
        is_mock = False

        def chat(self, messages, tools=None):
            return {
                "role": "assistant",
                "content": "### Top Issues\n- Fix the repeated unchecked copy in `a.c` and `b.c`.",
                "_llm_trace": {
                    "model": "summary-model",
                    "usage": {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13},
                    "elapsed_ms": 6,
                    "finish_reason": "stop",
                },
            }

    settings = Settings(mongo_mock=True, llm_mock_enabled=False)
    service = ReviewTaskService(settings)
    service.llm_client = SummaryLLMClient()
    task = TaskModel(
        project_id="summary-project",
        review_version="head",
        copy_from_version="0_version",
        task_type=3,
        state=1,
    ).save()
    code_files: list[CodeFileModel] = []
    for path in ["a.c", "b.c"]:
        issue = Issue(
            issue_id=1,
            type="security",
            severity=5,
            description="unchecked copy",
            suggestion="use a bounded copy",
            issue_line_numbers="1",
            existing_code="strcpy(dst, src);",
            evidence="the destination bound is unavailable",
        )
        code_files.append(
            CodeFileModel(
                task_id=str(task.id),
                project_id=task.project_id,
                review_version=task.review_version,
                copy_from_version=task.copy_from_version,
                    task_type=3,
                file_name=path,
                code_blocks=[
                    CodeBlock(
                        block_id=1,
                        contents=["     1+  strcpy(dst, src);"],
                        issues=[issue],
                        comment_line_number=1,
                        main_task_completed=True,
                    )
                ],
                comment_line_number=1,
                extra={"status": "reviewed", "estimated_tokens": 10},
            ).save()
        )

    service._finish_task(task, code_files, started_at=time.monotonic())
    task.reload()

    assert task.state == 2
    assert task.project_summary.startswith("### Top Issues")
    assert task.developer_issue_summary["_project_summary"]["summary_source"] == "llm"
    assert task.llm_total_tokens == 13
    assert task.task_model_rounds[0].stage == "project_summary_task"
