from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.core.config import Settings


class ReviewToolRunner:
    def __init__(
        self,
        root_dir: Path,
        settings: Settings,
        current_file_name: str = "",
        current_diff_lines: list[str] | None = None,
    ) -> None:
        self.root_dir = root_dir.resolve()
        self.settings = settings
        self.current_file_name = current_file_name
        self.current_diff_lines = current_diff_lines or []
        self.comments: list[dict[str, Any]] = []
        self.done = False
        self.failure_messages: list[str] = []

    def run(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            if name == "file_find":
                return self.file_find(arguments)
            if name == "file_read_diff":
                return self.file_read_diff(arguments)
            if name == "code_search":
                return self.code_search(arguments)
            if name in {"read_file", "file_read"}:
                return self.read_file(arguments)
            if name == "code_comment":
                return self.code_comment(arguments)
            if name == "task_done":
                return self.task_done(arguments)
            return {"error": f"Unsupported tool: {name}"}
        except Exception as exc:
            message = f"{name} failed: {type(exc).__name__}: {exc}"
            self.failure_messages.append(message)
            return {"error": message}

    def file_find(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query", ""))
        regex = bool(arguments.get("regex", False))
        limit = int(arguments.get("limit", 20))
        matches: list[dict[str, Any]] = []
        if not query:
            return {"matches": matches}

        pattern = re.compile(query) if regex else None
        for path in self.root_dir.rglob("*"):
            if len(matches) >= limit:
                break
            if not path.is_file() or self._is_excluded(path) or path.suffix.lower() not in self.settings.allowed_extension_set:
                continue
            rel_path = path.relative_to(self.root_dir).as_posix()
            matched = bool(pattern.search(rel_path)) if pattern else query.lower() in rel_path.lower()
            if matched:
                matches.append({"file_path": rel_path})
        return {"matches": matches}

    def file_read_diff(self, arguments: dict[str, Any]) -> dict[str, Any]:
        file_path = str(arguments.get("file_path") or self.current_file_name)
        if file_path and self.current_file_name and file_path != self.current_file_name:
            return {
                "error": "Only the current code block diff is available in this review round.",
                "current_file_name": self.current_file_name,
            }
        start_line = int(arguments.get("start_line") or 1)
        end_line = int(arguments.get("end_line") or len(self.current_diff_lines))
        start = max(start_line, 1)
        end = max(end_line, start)
        selected = [
            {"line_number": index, "line": self.current_diff_lines[index - 1]}
            for index in range(start, min(end, len(self.current_diff_lines)) + 1)
        ]
        return {"file_path": self.current_file_name, "lines": selected}

    def code_search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = str(arguments.get("query", ""))
        regex = bool(arguments.get("regex", False))
        limit = int(arguments.get("limit", 20))
        matches: list[dict[str, Any]] = []
        if not query:
            return {"matches": matches}

        pattern = re.compile(query) if regex else None
        for path in self.root_dir.rglob("*"):
            if len(matches) >= limit:
                break
            if not path.is_file() or self._is_excluded(path) or path.suffix.lower() not in self.settings.allowed_extension_set:
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            for line_number, line in enumerate(lines, start=1):
                if pattern.search(line) if pattern else query in line:
                    matches.append(
                        {
                            "file_path": path.relative_to(self.root_dir).as_posix(),
                            "line_number": line_number,
                            "line": line,
                        }
                    )
                    if len(matches) >= limit:
                        break
        return {"matches": matches}

    def read_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        file_path = self._safe_path(str(arguments.get("file_path", "")))
        start_line = int(arguments.get("start_line") or 1)
        end_line = int(arguments.get("end_line") or start_line + 300)
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(start_line, 1)
        end = max(end_line, start)
        selected = [
            {"line_number": index, "line": lines[index - 1]}
            for index in range(start, min(end, len(lines)) + 1)
        ]
        return {"file_path": file_path.relative_to(self.root_dir).as_posix(), "lines": selected}

    def code_comment(self, arguments: dict[str, Any]) -> dict[str, Any]:
        comment = {
            "type": str(arguments.get("type", "general")),
            "severity": self._normalize_severity(arguments.get("severity", 1)),
            "description": str(arguments.get("description", "")),
            "suggestion": str(arguments.get("suggestion", "")),
            "issue_line_numbers": str(arguments.get("issue_line_numbers", "")),
            "confidence_level": arguments.get("confidence_level"),
        }
        self.comments.append(comment)
        return {"accepted": True, "comment_count": len(self.comments)}

    def task_done(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.done = True
        return {"done": True, "summary": str(arguments.get("summary", ""))}

    def tool_result_message(self, tool_call_id: str, content: dict[str, Any]) -> dict[str, Any]:
        return {"role": "tool", "tool_call_id": tool_call_id, "content": json.dumps(content, ensure_ascii=False)}

    def _safe_path(self, file_path: str) -> Path:
        candidate = (self.root_dir / file_path).resolve()
        try:
            candidate.relative_to(self.root_dir)
        except ValueError as exc:
            raise ValueError("File path escapes review root")
        if not candidate.exists() or not candidate.is_file():
            raise FileNotFoundError(file_path)
        return candidate

    def _is_excluded(self, path: Path) -> bool:
        rel_path = path.relative_to(self.root_dir)
        return any(part in self.settings.excluded_dir_set for part in rel_path.parts)

    def _normalize_severity(self, value: Any) -> int:
        if isinstance(value, str):
            mapping = {"low": 1, "medium": 3, "high": 4, "critical": 5}
            value = mapping.get(value.lower(), value)
        try:
            severity = int(value)
        except (TypeError, ValueError):
            severity = 1
        return min(5, max(1, severity))
