from __future__ import annotations

import fnmatch
import json
import re
import time
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.services.exclusions import ReviewPathExcluder
from app.services.semantic_index import SemanticIndex


class ReviewToolRunner:
    def __init__(
        self,
        root_dir: Path,
        settings: Settings,
        current_file_name: str = "",
        current_diff_lines: list[str] | None = None,
        diff_map: dict[str, list[str]] | None = None,
        semantic_index: SemanticIndex | None = None,
        project_exclude_paths: list[str] | None = None,
    ) -> None:
        self.root_dir = root_dir.resolve()
        self.settings = settings
        self.path_excluder = ReviewPathExcluder(settings, project_exclude_paths)
        self.current_file_name = current_file_name
        self.current_diff_lines = current_diff_lines or []
        self.diff_map = {self._normalize_repo_path(path): list(lines) for path, lines in (diff_map or {}).items()}
        if current_file_name and current_file_name not in self.diff_map:
            self.diff_map[self._normalize_repo_path(current_file_name)] = list(self.current_diff_lines)
        self.semantic_index = semantic_index
        if self.settings.review_semantic_index_enabled and self.semantic_index is None:
            self.semantic_index = SemanticIndex(self.root_dir, self.settings)
        self.comments: list[dict[str, Any]] = []
        self.done = False
        self.done_state = ""
        self.failure_messages: list[str] = []
        self._result_cache: dict[str, dict[str, Any]] = {}

    def run(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            cache_key = self._cache_key(name, arguments)
            if cache_key and cache_key in self._result_cache:
                return {**self._result_cache[cache_key], "_cached": True}
            if name == "file_find":
                result = self.file_find(arguments)
            elif name == "file_read_diff":
                result = self.file_read_diff(arguments)
            elif name == "code_search":
                result = self.code_search(arguments)
            elif name in {"read_file", "file_read"}:
                result = self.read_file(arguments)
            elif name == "find_definition":
                result = self.find_definition(arguments)
            elif name == "find_references":
                result = self.find_references(arguments)
            elif name == "call_graph":
                result = self.call_graph(arguments)
            elif name == "code_comment":
                result = self.code_comment(arguments)
            elif name == "task_done":
                result = self.task_done(arguments)
            else:
                result = {"error": f"Unsupported tool: {name}"}
            if cache_key and not result.get("error"):
                self._result_cache[cache_key] = result
            return result
        except Exception as exc:
            message = f"{name} failed: {type(exc).__name__}: {exc}"
            return {"error": message}

    def file_find(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query_name") or arguments.get("query") or "")
        regex = bool(arguments.get("regex", False))
        case_sensitive = bool(arguments.get("case_sensitive", False))
        limit = self._bounded_limit(arguments.get("limit"), 20)
        matches: list[dict[str, Any]] = []
        if not query:
            return {"matches": matches}

        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.compile(query, flags) if regex else None
        query_value = query if case_sensitive else query.lower()
        started_at = time.monotonic()
        for path in self._iter_review_files():
            if self._tool_timed_out(started_at):
                return {"matches": matches, "truncated": True, "warning": "file_find timed out"}
            if len(matches) >= limit:
                break
            rel_path = path.relative_to(self.root_dir).as_posix()
            candidate = rel_path if case_sensitive else rel_path.lower()
            matched = bool(pattern.search(rel_path)) if pattern else query_value in candidate
            if matched:
                matches.append({"file_path": rel_path})
        return {"matches": matches, "truncated": len(matches) >= limit}

    def file_read_diff(self, arguments: dict[str, Any]) -> dict[str, Any]:
        requested = arguments.get("path_array")
        if not isinstance(requested, list):
            requested = [arguments.get("file_path") or self.current_file_name]
        files: list[dict[str, Any]] = []
        not_found: list[str] = []
        for raw_path in requested[:20]:
            file_path = self._normalize_repo_path(str(raw_path or ""))
            if not file_path:
                continue
            diff_lines = self.diff_map.get(file_path)
            if diff_lines is None:
                not_found.append(file_path)
                continue
            start_line = max(1, int(arguments.get("start_line") or 1))
            end_line = max(start_line, int(arguments.get("end_line") or len(diff_lines)))
            selected = [
                {"line_number": index, "line": diff_lines[index - 1]}
                for index in range(start_line, min(end_line, len(diff_lines)) + 1)
            ]
            files.append({"file_path": file_path, "lines": selected, "total_diff_lines": len(diff_lines)})
        if not files:
            return {"error": "Diff not found for requested paths", "not_found": not_found}
        result: dict[str, Any] = {"files": files, "not_found": not_found}
        if len(files) == 1:
            result.update(files[0])
        return result

    def code_search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("search_text") or arguments.get("query") or "")
        regex = bool(arguments.get("use_perl_regexp", arguments.get("regex", False)))
        case_sensitive = bool(arguments.get("case_sensitive", False))
        file_patterns = arguments.get("file_patterns") if isinstance(arguments.get("file_patterns"), list) else []
        limit = self._bounded_limit(arguments.get("limit"), self.settings.review_tool_max_search_matches)
        matches: list[dict[str, Any]] = []
        if not query:
            return {"matches": matches}

        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.compile(query, flags) if regex else None
        query_value = query if case_sensitive else query.lower()
        started_at = time.monotonic()
        for path in self._iter_review_files():
            if self._tool_timed_out(started_at):
                return {"matches": matches, "truncated": True, "warning": "code_search timed out"}
            if len(matches) >= limit:
                break
            rel_path = path.relative_to(self.root_dir).as_posix()
            if file_patterns and not self._matches_file_patterns(rel_path, file_patterns):
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            for line_number, line in enumerate(lines, start=1):
                candidate = line if case_sensitive else line.lower()
                if pattern.search(line) if pattern else query_value in candidate:
                    matches.append(
                        {
                            "file_path": rel_path,
                            "line_number": line_number,
                            "line": line,
                        }
                    )
                    if len(matches) >= limit:
                        break
        return {"matches": matches, "truncated": len(matches) >= limit}

    def read_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        file_path = self._safe_path(str(arguments.get("file_path", "")))
        start_line = int(arguments.get("start_line") or 1)
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(start_line, 1)
        requested_end = int(arguments.get("end_line") or len(lines))
        maximum_end = start + max(1, self.settings.review_tool_max_read_lines) - 1
        end = min(max(requested_end, start), maximum_end)
        selected = [
            {"line_number": index, "line": lines[index - 1]}
            for index in range(start, min(end, len(lines)) + 1)
        ]
        actual_end = min(end, len(lines))
        return {
            "file_path": file_path.relative_to(self.root_dir).as_posix(),
            "total_lines": len(lines),
            "line_range": f"{start}-{actual_end}",
            "is_truncated": requested_end > actual_end or actual_end < len(lines),
            "lines": selected,
        }

    def find_definition(self, arguments: dict[str, Any]) -> dict[str, Any]:
        index = self._required_semantic_index()
        symbol = str(arguments.get("symbol") or "").strip()
        current_file = self._optional_safe_repo_path(
            str(arguments.get("file_path") or self.current_file_name or "")
        )
        return index.find_definition(
            symbol=symbol,
            current_file=current_file,
            limit=self._semantic_limit(arguments.get("limit"), 20),
        )

    def find_references(self, arguments: dict[str, Any]) -> dict[str, Any]:
        index = self._required_semantic_index()
        symbol = str(arguments.get("symbol") or "").strip()
        file_path = self._optional_safe_repo_path(str(arguments.get("file_path") or ""))
        return index.find_references(
            symbol=symbol,
            file_path=file_path,
            include_declarations=bool(arguments.get("include_declarations", False)),
            limit=self._semantic_limit(arguments.get("limit"), self.settings.review_semantic_index_max_results),
        )

    def call_graph(self, arguments: dict[str, Any]) -> dict[str, Any]:
        index = self._required_semantic_index()
        return index.call_graph(
            symbol=str(arguments.get("symbol") or "").strip(),
            direction=str(arguments.get("direction") or "both").lower(),
            depth=int(arguments.get("depth") or 1),
            limit=self._semantic_limit(arguments.get("limit"), self.settings.review_semantic_index_max_results),
        )

    def code_comment(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw_comments = arguments.get("comments")
        if not isinstance(raw_comments, list):
            raw_comments = [arguments]
        accepted = 0
        errors: list[str] = []
        for index, raw_comment in enumerate(raw_comments):
            if not isinstance(raw_comment, dict):
                errors.append(f"comments[{index}] must be an object")
                continue
            comment = self._normalize_comment(raw_comment)
            if comment["type"] not in {"logic", "performance", "security", "readability", "code_style"}:
                errors.append(f"comments[{index}] has unsupported type: {comment['type']}")
                continue
            missing = [
                field
                for field in ["description", "suggestion", "issue_line_numbers", "existing_code", "evidence"]
                if not str(comment.get(field) or "").strip()
            ]
            if missing:
                errors.append(f"comments[{index}] missing required fields: {', '.join(missing)}")
                continue
            self.comments.append(comment)
            accepted += 1
        if accepted == 0:
            return {"accepted": False, "errors": errors, "comment_count": len(self.comments)}
        return {"accepted": True, "accepted_count": accepted, "errors": errors, "comment_count": len(self.comments)}

    def task_done(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.done = True
        state = str(arguments.get("state") or "DONE").upper()
        self.done_state = state if state in {"DONE", "FAILED"} else "FAILED"
        if self.done_state == "FAILED":
            self.failure_messages.append(str(arguments.get("summary") or "main_task reported FAILED"))
        return {"done": True, "state": self.done_state, "summary": str(arguments.get("summary", ""))}

    def tool_result_message(self, tool_call_id: str, content: dict[str, Any]) -> dict[str, Any]:
        return {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(content, ensure_ascii=False)}

    def _safe_path(self, file_path: str) -> Path:
        normalized = self._normalize_repo_path(file_path)
        if not normalized:
            raise ValueError("File path is required")
        if Path(file_path).is_absolute() or re.match(r"^[A-Za-z]:", file_path):
            raise ValueError("Absolute file paths are not allowed")
        candidate = (self.root_dir / normalized).resolve()
        try:
            candidate.relative_to(self.root_dir)
        except ValueError as exc:
            raise ValueError("File path escapes review root")
        if not candidate.exists() or not candidate.is_file():
            raise FileNotFoundError(file_path)
        if self._is_excluded(candidate):
            raise ValueError("File path is excluded from review")
        if candidate.suffix.lower() not in self.settings.allowed_extension_set:
            raise ValueError("File extension is not allowed for review tools")
        if candidate.stat().st_size > max(1, self.settings.review_tool_max_file_bytes):
            raise ValueError("File exceeds review tool size limit")
        return candidate

    def _is_excluded(self, path: Path) -> bool:
        rel_path = path.relative_to(self.root_dir)
        return self.path_excluder.is_excluded(rel_path)

    def _normalize_severity(self, value: Any) -> int:
        if isinstance(value, str):
            mapping = {"low": 1, "medium": 3, "high": 4, "critical": 5}
            value = mapping.get(value.lower(), value)
        try:
            severity = int(value)
        except (TypeError, ValueError):
            severity = 1
        return min(5, max(1, severity))

    def _normalize_comment(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": str(arguments.get("type") or arguments.get("category") or "logic"),
            "severity": self._normalize_severity(arguments.get("severity", 1)),
            "description": str(arguments.get("description") or arguments.get("content") or ""),
            "suggestion": str(arguments.get("suggestion") or ""),
            "issue_line_numbers": str(arguments.get("issue_line_numbers") or ""),
            "existing_code": str(arguments.get("existing_code") or ""),
            "suggestion_code": str(arguments.get("suggestion_code") or ""),
            "evidence": str(arguments.get("evidence") or ""),
            "rule_id": str(arguments.get("rule_id") or ""),
            "confidence_level": arguments.get("confidence_level"),
        }

    def _cache_key(self, name: str, arguments: dict[str, Any]) -> str:
        if name not in {
            "file_find",
            "file_read_diff",
            "code_search",
            "read_file",
            "file_read",
            "find_definition",
            "find_references",
            "call_graph",
        }:
            return ""
        canonical_name = "file_read" if name == "read_file" else name
        return canonical_name + ":" + json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)

    def _required_semantic_index(self) -> SemanticIndex:
        if not self.settings.review_semantic_index_enabled or self.semantic_index is None:
            raise ValueError("Semantic index is disabled")
        return self.semantic_index

    def _optional_safe_repo_path(self, file_path: str) -> str:
        if not file_path:
            return ""
        return self._safe_path(file_path).relative_to(self.root_dir).as_posix()

    def _semantic_limit(self, value: Any, default: int) -> int:
        try:
            requested = int(value) if value is not None else int(default)
        except (TypeError, ValueError):
            requested = int(default)
        return min(max(1, requested), max(1, self.settings.review_semantic_index_max_results))

    def _bounded_limit(self, value: Any, default: int) -> int:
        try:
            requested = int(value) if value is not None else int(default)
        except (TypeError, ValueError):
            requested = int(default)
        return min(max(1, requested), max(1, self.settings.review_tool_max_search_matches))

    def _normalize_repo_path(self, file_path: str) -> str:
        value = str(file_path or "").replace("\\", "/").strip()
        if not value:
            return ""
        if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
            raise ValueError("Absolute file paths are not allowed")
        parts = [part for part in value.split("/") if part not in {"", "."}]
        if any(part == ".." for part in parts):
            raise ValueError("File path escapes review root (path traversal is not allowed)")
        return "/".join(parts)

    def _iter_review_files(self):
        for path in self.root_dir.rglob("*"):
            if not path.is_file() or self._is_excluded(path):
                continue
            if path.suffix.lower() not in self.settings.allowed_extension_set:
                continue
            try:
                if path.stat().st_size > max(1, self.settings.review_tool_max_file_bytes):
                    continue
            except OSError:
                continue
            yield path

    def _matches_file_patterns(self, file_path: str, patterns: list[Any]) -> bool:
        include_patterns: list[str] = []
        exclude_patterns: list[str] = []
        for raw_pattern in patterns:
            pattern = str(raw_pattern or "").replace("\\", "/")
            if ".." in pattern.split("/"):
                raise ValueError("file_patterns must not contain '..'")
            if pattern.startswith(":(exclude)"):
                exclude_patterns.append(pattern[len(":(exclude)") :])
            elif pattern:
                include_patterns.append(pattern)

        def matches(pattern: str) -> bool:
            if pattern.endswith("/"):
                return file_path.startswith(pattern)
            return fnmatch.fnmatch(file_path, pattern) or fnmatch.fnmatch(Path(file_path).name, pattern)

        if any(matches(pattern) for pattern in exclude_patterns):
            return False
        return not include_patterns or any(matches(pattern) for pattern in include_patterns)

    def _tool_timed_out(self, started_at: float) -> bool:
        timeout = max(1, self.settings.review_tool_timeout_seconds)
        return time.monotonic() - started_at >= timeout
