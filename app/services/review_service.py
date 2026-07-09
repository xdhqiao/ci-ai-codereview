from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings
from app.core.exceptions import NotFoundError
from app.models.code_file import CodeBlock, CodeFileModel, Issue
from app.models.task import TaskModel
from app.services.diff_service import TASK_TYPE_FULL_SCAN, TASK_TYPE_INCREMENTAL, CodeDiffService, ReviewTarget
from app.services.llm_client import LLMClient
from app.services.prompts import MAIN_TOOL_DEFINITIONS, build_main_messages, build_plan_messages
from app.services.review_tools import ReviewToolRunner


SCORE_FIELDS = ["logic_score", "performance_score", "security_score", "readable_score", "code_style_score"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class PlanResult:
    comment: str
    logic_score: int
    performance_score: int
    security_score: int
    readable_score: int
    code_style_score: int
    failure_message: str = ""


@dataclass
class MainResult:
    issues: list[Issue]
    failure_message: str = ""


class ReviewTaskService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.diff_service = CodeDiffService(self.settings)
        self.llm_client = LLMClient(self.settings)

    def create_mock_task(self) -> TaskModel:
        task = TaskModel(
            project_id=self.settings.mock_project_id,
            review_version=self.settings.mock_review_version,
            copy_from_version=self.settings.mock_copy_from_version,
            task_type=self.settings.mock_task_type,
            state=0,
            parent_path=self.settings.mock_parent_path or None,
            created_by="scheduler",
        )
        task.save()
        return task

    def review_existing_task(self, task_id: str) -> TaskModel:
        task = TaskModel.objects(id=task_id).first()
        if not task:
            raise NotFoundError("Task not found")
        return self.review_task(task)

    def review_task(self, task: TaskModel) -> TaskModel:
        started_at = time.monotonic()
        task.state = 1
        task.update_time = utc_now()
        task.save()

        try:
            targets, review_root = self._collect_targets(task)
            CodeFileModel.objects(task_id=str(task.id)).delete()

            saved_files: list[CodeFileModel] = []
            for target in targets:
                saved_files.append(self._review_file(task, target, review_root))

            self._finish_task(task, saved_files, started_at)
            return task
        except Exception:
            task.retry_count = (task.retry_count or 0) + 1
            task.update_time = utc_now()
            task.save()
            raise

    def _collect_targets(self, task: TaskModel) -> tuple[list[ReviewTarget], Path]:
        task_type = self._resolve_task_type(task)
        task.task_type = task_type
        task.save()

        if task_type == TASK_TYPE_INCREMENTAL:
            base_dir, head_dir = self.diff_service.resolve_incremental_paths(
                task.project_id,
                task.copy_from_version,
                task.review_version,
                task.parent_path,
            )
            return self.diff_service.compare_directories(base_dir, head_dir), head_dir

        target_dir = self.diff_service.resolve_full_scan_path(task.project_id, task.review_version, task.parent_path)
        return self.diff_service.scan_directory(target_dir), target_dir

    def _resolve_task_type(self, task: TaskModel) -> int:
        if task.task_type in {TASK_TYPE_INCREMENTAL, TASK_TYPE_FULL_SCAN}:
            return int(task.task_type)
        copy_from_version = (task.copy_from_version or "").strip()
        if copy_from_version in {"", "0", "0_version"}:
            return TASK_TYPE_FULL_SCAN
        return TASK_TYPE_INCREMENTAL

    def _review_file(self, task: TaskModel, target: ReviewTarget, review_root: Path) -> CodeFileModel:
        code_blocks: list[CodeBlock] = []
        for block_index, block_lines in enumerate(self.diff_service.split_code_blocks(target.diff_lines), start=1):
            plan_result = self._run_plan_task(target.file_name, target.language, block_lines, target.full_code)
            main_failure_message = ""
            try:
                main_result = self._run_main_task(target, block_lines, plan_result.comment, review_root)
                issues = main_result.issues
                main_failure_message = main_result.failure_message
            except Exception as exc:
                main_failure_message = f"main_task LLM failed: {type(exc).__name__}: {exc}"
                issues = self._comments_to_issues(self._mock_main_comments(block_lines, target.language))
            block = CodeBlock(
                block_id=block_index,
                block_hash=self._hash_lines(block_lines),
                contents=block_lines,
                comment=plan_result.comment,
                logic_score=plan_result.logic_score,
                performance_score=plan_result.performance_score,
                security_score=plan_result.security_score,
                readable_score=plan_result.readable_score,
                code_style_score=plan_result.code_style_score,
                comment_line_number=len(issues),
                issues=issues,
                failure_message="; ".join(
                    message for message in [plan_result.failure_message, main_failure_message] if message
                ),
            )
            code_blocks.append(block)

        self._merge_duplicate_file_issues(code_blocks)
        scores = self._average_block_scores(code_blocks)
        code_file = CodeFileModel(
            task_id=str(task.id),
            project_id=task.project_id,
            review_version=task.review_version,
            copy_from_version=task.copy_from_version,
            task_type=task.task_type,
            file_name=target.file_name,
            code_blocks=code_blocks,
            code_line_num=target.code_line_num,
            add_code_line_num=target.add_code_line_num,
            comment_line_number=sum(len(block.issues) for block in code_blocks),
            **scores,
        )
        code_file.save()
        return code_file

    def _run_plan_task(self, file_name: str, language: str, diff_lines: list[str], full_code: str) -> PlanResult:
        messages = build_plan_messages(file_name=file_name, language=language, diff_lines=diff_lines, full_code=full_code)
        failure_message = ""
        try:
            response = self.llm_client.complete_json(messages=messages)
        except Exception as exc:
            response = {}
            failure_message = f"plan_task LLM failed: {type(exc).__name__}: {exc}"
        if not response:
            response = self._mock_plan_response(diff_lines)
        return PlanResult(
            comment=str(response.get("comment") or "代码块已完成初步分析。"),
            logic_score=self._score(response.get("logic_score"), 80),
            performance_score=self._score(response.get("performance_score"), 80),
            security_score=self._score(response.get("security_score"), 80),
            readable_score=self._score(response.get("readable_score"), 80),
            code_style_score=self._score(response.get("code_style_score"), 80),
            failure_message=failure_message,
        )

    def _run_main_task(
        self,
        target: ReviewTarget,
        diff_lines: list[str],
        plan_comment: str,
        review_root: Path,
    ) -> MainResult:
        if self.llm_client.is_mock:
            comments = self._mock_main_comments(diff_lines, target.language)
            return MainResult(issues=self._comments_to_issues(comments))

        messages: list[dict[str, Any]] = build_main_messages(
            file_name=target.file_name,
            language=target.language,
            diff_lines=diff_lines,
            full_code=target.full_code,
            plan_comment=plan_comment,
        )
        runner = ReviewToolRunner(
            review_root,
            self.settings,
            current_file_name=target.file_name,
            current_diff_lines=diff_lines,
        )
        json_retry_count = 0

        for _ in range(self.settings.llm_max_tool_rounds):
            try:
                assistant_message = self.llm_client.chat(messages=messages, tools=MAIN_TOOL_DEFINITIONS)
            except Exception as tool_error:
                messages.append(
                    {
                        "role": "user",
                        "content": "如果工具调用不可用，请直接输出 JSON，格式为 {\"issues\":[...]}。",
                    }
                )
                try:
                    assistant_message = self.llm_client.chat(messages=messages)
                except Exception:
                    raise tool_error
            messages.append(assistant_message)
            tool_calls = assistant_message.get("tool_calls") or []
            if not tool_calls:
                if self._collect_json_comments(assistant_message.get("content"), runner):
                    break
                if json_retry_count < self.settings.llm_json_retry_times:
                    json_retry_count += 1
                    messages.append(
                        {
                    "role": "user",
                            "content": (
                                "上一轮 main_task 输出无法解析为约束 JSON，也没有提交工具调用。"
                                "type 只能使用 logic、performance、security、readability、code_style。"
                                "请只输出 JSON：{\"issues\":[{\"type\":\"security\",\"severity\":5,"
                                "\"description\":\"问题描述\",\"suggestion\":\"修复建议\","
                                "\"issue_line_numbers\":\"12\",\"confidence_level\":0.8}]}。"
                                "如果没有问题，输出 {\"issues\":[]}。"
                            ),
                        }
                    )
                    continue
                runner.failure_messages.append("main_task JSON parse failed after retries")
                break

            for tool_call in tool_calls:
                function = tool_call.get("function", {})
                tool_name = function.get("name", "")
                raw_arguments = function.get("arguments") or "{}"
                arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
                result = runner.run(tool_name, arguments)
                messages.append(runner.tool_result_message(tool_call.get("id", ""), result))
            if runner.done:
                break

        return MainResult(
            issues=self._comments_to_issues(runner.comments),
            failure_message="; ".join(runner.failure_messages),
        )

    def _finish_task(self, task: TaskModel, code_files: list[CodeFileModel], started_at: float) -> None:
        scores = self._average_file_scores(code_files)
        issue_summary: dict[str, int] = {}
        for code_file in code_files:
            for block in code_file.code_blocks:
                for issue in block.issues:
                    issue_summary[issue.type or "general"] = issue_summary.get(issue.type or "general", 0) + 1

        task.state = 2
        task.file_num = len(code_files)
        task.reviewed_file_num = len(code_files)
        task.code_block_num = sum(len(code_file.code_blocks) for code_file in code_files)
        task.add_code_line_num = sum(code_file.add_code_line_num for code_file in code_files)
        task.comment_line_number = sum(code_file.comment_line_number for code_file in code_files)
        for field_name, value in scores.items():
            setattr(task, field_name, value)
        task.score = int(sum(scores.values()) / len(scores)) if scores else 0
        task.developer_issue_summary = issue_summary
        task.process_time = int((time.monotonic() - started_at) * 1000)
        task.update_time = utc_now()
        task.save()

    def _mock_plan_response(self, diff_lines: list[str]) -> dict[str, Any]:
        comments = ["代码块已按本地规则完成 plan_task 预审。"]
        scores = {field: 90 for field in SCORE_FIELDS}
        added_code = "\n".join(self._iter_added_code(diff_lines)).lower()
        if any(token in added_code for token in ["eval(", "exec(", "password", "secret", "api_key"]):
            scores["security_score"] = 60
            comments.append("发现潜在安全风险，需要 main_task 进一步确认。")
        if "todo" in added_code or "fixme" in added_code:
            scores["readable_score"] = min(scores["readable_score"], 75)
            comments.append("新增代码包含未完成标记。")
        if "except exception" in added_code and "pass" in added_code:
            scores["logic_score"] = min(scores["logic_score"], 70)
            comments.append("异常处理可能吞掉真实失败。")
        return {"comment": " ".join(comments), **scores}

    def _mock_main_comments(self, diff_lines: list[str], language: str) -> list[dict[str, Any]]:
        comments: list[dict[str, Any]] = []
        for line_number, code in self._iter_added_with_line_number(diff_lines):
            lower_code = code.lower()
            if "eval(" in lower_code or "exec(" in lower_code:
                comments.append(
                    {
                        "type": "security",
                        "severity": 5,
                        "description": "新增代码执行动态字符串，外部输入进入时可能导致任意代码执行。",
                        "suggestion": "改为显式分支、白名单映射或安全解析器，避免执行字符串。",
                        "issue_line_numbers": str(line_number),
                        "confidence_level": 0.9,
                    }
                )
            if any(token in lower_code for token in ["password", "secret", "api_key", "access_token"]):
                comments.append(
                    {
                        "type": "security",
                        "severity": 4,
                        "description": "新增代码疑似包含敏感信息或凭据字段，容易造成泄露。",
                        "suggestion": "通过环境变量或密钥管理服务读取，并避免在日志和代码中保留明文。",
                        "issue_line_numbers": str(line_number),
                        "confidence_level": 0.75,
                    }
                )
            if language == "C" and ("strcpy(" in lower_code or "strcat(" in lower_code):
                comments.append(
                    {
                        "type": "security",
                        "severity": 5,
                        "description": "新增 C 代码使用无边界检查的字符串拷贝/拼接，可能造成缓冲区溢出。",
                        "suggestion": "改用 snprintf 或带目标缓冲区长度的封装，并检查返回值是否截断。",
                        "issue_line_numbers": str(line_number),
                        "confidence_level": 0.9,
                    }
                )
            if language == "C" and "sscanf(" in lower_code and "%s" in lower_code and "%31s" not in lower_code:
                comments.append(
                    {
                        "type": "security",
                        "severity": 4,
                        "description": "sscanf 使用未限制宽度的 %s，输入过长会写爆目标数组。",
                        "suggestion": "为字符串格式指定最大宽度，或改用安全解析逻辑并校验返回值。",
                        "issue_line_numbers": str(line_number),
                        "confidence_level": 0.85,
                    }
                )
            if language == "C" and ("printf(message)" in lower_code or "fprintf(file, message)" in lower_code):
                comments.append(
                    {
                        "type": "security",
                        "severity": 5,
                        "description": "外部字符串被直接作为格式化字符串使用，存在格式化字符串漏洞。",
                        "suggestion": "使用固定格式，例如 printf(\"%s\", message) 或 fprintf(file, \"%s\", message)。",
                        "issue_line_numbers": str(line_number),
                        "confidence_level": 0.9,
                    }
                )
            if language == "C" and "/ right" in lower_code:
                comments.append(
                    {
                        "type": "logic",
                        "severity": 4,
                        "description": "除法前没有检查除数是否为 0，可能导致运行时崩溃。",
                        "suggestion": "恢复 right == 0 的保护，并在 result 为空时返回错误。",
                        "issue_line_numbers": str(line_number),
                        "confidence_level": 0.8,
                    }
                )
            if language == "C" and "argv[2]" in lower_code:
                comments.append(
                    {
                        "type": "logic",
                        "severity": 4,
                        "description": "读取 argv[2] 前没有检查 argc，参数不足时会越界访问。",
                        "suggestion": "先校验 argc > 2，再访问对应参数，并保留错误返回路径。",
                        "issue_line_numbers": str(line_number),
                        "confidence_level": 0.85,
                    }
                )
            if "todo" in lower_code or "fixme" in lower_code:
                comments.append(
                    {
                        "type": "readability",
                        "severity": 2,
                        "description": "新增代码包含未完成标记，可能把临时实现带入主流程。",
                        "suggestion": "在合并前完成该逻辑，或关联明确的后续任务并隔离影响范围。",
                        "issue_line_numbers": str(line_number),
                        "confidence_level": 0.7,
                    }
                )
            if language == "Python" and "except exception" in lower_code and "pass" in lower_code:
                comments.append(
                    {
                        "type": "logic",
                        "severity": 3,
                        "description": "异常被直接吞掉，会隐藏真实失败并增加排查成本。",
                        "suggestion": "至少记录异常上下文，必要时转换为业务异常或重新抛出。",
                        "issue_line_numbers": str(line_number),
                        "confidence_level": 0.8,
                    }
                )
        return comments

    def _comments_to_issues(self, comments: list[dict[str, Any]]) -> list[Issue]:
        issues: list[Issue] = []
        for index, comment in enumerate(comments, start=1):
            issues.append(
                Issue(
                    issue_id=index,
                    type=self._normalize_issue_type(comment.get("type")),
                    severity=self._severity(comment.get("severity")),
                    description=str(comment.get("description") or ""),
                    suggestion=str(comment.get("suggestion") or ""),
                    issue_line_numbers=str(comment.get("issue_line_numbers") or ""),
                    issue_show=True,
                    comment_line_number=index,
                    confidence_level=comment.get("confidence_level"),
                )
            )
        return issues

    def _collect_json_comments(self, content: str | None, runner: ReviewToolRunner) -> bool:
        if not content:
            return False
        try:
            data = self.llm_client._extract_json(content)
        except (json.JSONDecodeError, ValueError):
            return False
        comments = data.get("issues") if isinstance(data, dict) else None
        if isinstance(comments, list):
            for comment in comments:
                if isinstance(comment, dict):
                    runner.code_comment(comment)
            return True
        return False

    def _merge_duplicate_file_issues(self, blocks: list[CodeBlock]) -> None:
        seen_keys: set[tuple[str, int, str, str, str]] = set()
        next_issue_id = 1
        for block in blocks:
            merged_issues: list[Issue] = []
            for issue in block.issues:
                key = self._issue_merge_key(issue)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                issue.issue_id = next_issue_id
                issue.comment_line_number = next_issue_id
                next_issue_id += 1
                merged_issues.append(issue)
            block.issues = merged_issues
            block.comment_line_number = len(merged_issues)

    def _issue_merge_key(self, issue: Issue) -> tuple[str, int, str, str, str]:
        return (
            self._normalize_issue_text(issue.type),
            issue.severity,
            self._normalize_issue_lines(issue.issue_line_numbers),
            self._normalize_issue_text(issue.description),
            self._normalize_issue_text(issue.suggestion),
        )

    def _normalize_issue_lines(self, line_numbers: str | None) -> str:
        if not line_numbers:
            return ""
        normalized: list[int] = []
        for part in str(line_numbers).replace("，", ",").split(","):
            stripped = part.strip()
            if stripped.isdigit():
                normalized.append(int(stripped))
        if normalized:
            return ",".join(str(number) for number in sorted(set(normalized)))
        return self._normalize_issue_text(line_numbers)

    def _normalize_issue_text(self, value: str | None) -> str:
        return " ".join(str(value or "").lower().split())

    def _normalize_issue_type(self, value: Any) -> str:
        normalized = self._normalize_issue_text(str(value or "logic")).replace("-", "_")
        normalized = normalized.replace(" ", "_")
        aliases = {
            "bug": "logic",
            "correctness": "logic",
            "robustness": "logic",
            "maintainability": "readability",
            "readable": "readability",
            "style": "code_style",
            "code_style": "code_style",
            "codestyle": "code_style",
            "code": "code_style",
            "security": "security",
            "performance": "performance",
            "logic": "logic",
            "readability": "readability",
        }
        return aliases.get(normalized, "logic")

    def _average_block_scores(self, blocks: list[CodeBlock]) -> dict[str, int]:
        if not blocks:
            return {field: 0 for field in SCORE_FIELDS}
        return {field: int(sum(getattr(block, field) for block in blocks) / len(blocks)) for field in SCORE_FIELDS}

    def _average_file_scores(self, code_files: list[CodeFileModel]) -> dict[str, int]:
        if not code_files:
            return {field: 0 for field in SCORE_FIELDS}
        return {field: int(sum(getattr(code_file, field) for code_file in code_files) / len(code_files)) for field in SCORE_FIELDS}

    def _iter_added_code(self, diff_lines: list[str]):
        for _, code in self._iter_added_with_line_number(diff_lines):
            yield code

    def _iter_added_with_line_number(self, diff_lines: list[str]):
        for line in diff_lines:
            if len(line) <= 8 or line[6] != "+":
                continue
            try:
                line_number = int(line[:6].strip())
            except ValueError:
                line_number = 0
            yield line_number, line[9:]

    def _hash_lines(self, lines: list[str]) -> str:
        return hashlib.md5("\n".join(lines).encode("utf-8")).hexdigest()

    def _score(self, value: Any, default: int) -> int:
        try:
            score = int(value)
        except (TypeError, ValueError):
            score = default
        return min(100, max(0, score))

    def _severity(self, value: Any) -> int:
        if isinstance(value, str):
            mapping = {"low": 1, "medium": 3, "high": 4, "critical": 5}
            value = mapping.get(value.lower(), value)
        try:
            severity = int(value)
        except (TypeError, ValueError):
            severity = 1
        return min(5, max(1, severity))
