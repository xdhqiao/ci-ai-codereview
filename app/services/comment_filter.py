from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CommentSyntax:
    line_prefixes: tuple[str, ...] = ()
    block_pairs: tuple[tuple[str, str], ...] = ()


_C_STYLE = CommentSyntax(line_prefixes=("//",), block_pairs=(("/*", "*/"),))
_HASH_STYLE = CommentSyntax(line_prefixes=("#",))
_SYNTAX_BY_LANGUAGE = {
    "c": _C_STYLE,
    "c/c++ header": _C_STYLE,
    "c++": _C_STYLE,
    "c++ header": _C_STYLE,
    "c#": _C_STYLE,
    "go": _C_STYLE,
    "java": _C_STYLE,
    "javascript": _C_STYLE,
    "javascript react": _C_STYLE,
    "kotlin": _C_STYLE,
    "php": CommentSyntax(line_prefixes=("//", "#"), block_pairs=(("/*", "*/"),)),
    "rust": _C_STYLE,
    "scala": _C_STYLE,
    "swift": _C_STYLE,
    "typescript": _C_STYLE,
    "typescript react": _C_STYLE,
    "css": CommentSyntax(block_pairs=(("/*", "*/"),)),
    "scss": _C_STYLE,
    "html": CommentSyntax(block_pairs=(("<!--", "-->"),)),
    "vue": CommentSyntax(line_prefixes=("//",), block_pairs=(("<!--", "-->"), ("/*", "*/"))),
    "sql": CommentSyntax(line_prefixes=("--",), block_pairs=(("/*", "*/"),)),
    "python": _HASH_STYLE,
    "ruby": _HASH_STYLE,
    "shell": _HASH_STYLE,
    "powershell": _HASH_STYLE,
    "yaml": _HASH_STYLE,
    "toml": _HASH_STYLE,
    "ini": CommentSyntax(line_prefixes=(";", "#")),
}

_EFFECTIVE_COMMENT_MARKERS = (
    "coding:",
    "coding=",
    "coverage:",
    "eslint-",
    "go:build",
    "gosec",
    "noinspection",
    "nolint",
    "noqa",
    "nosec",
    "pragma:",
    "shellcheck",
    "sourceMappingURL=",
    "type: ignore",
)


def is_comment_only_change(diff_lines: list[str], language: str) -> bool:
    """Return true only when every changed line is provably comment or whitespace."""

    return comment_only_block_flags([diff_lines], language)[0]


def comment_only_block_flags(blocks: list[list[str]], language: str) -> list[bool]:
    """Classify blocks while carrying multiline-comment state across block boundaries."""

    syntax = _SYNTAX_BY_LANGUAGE.get(language.strip().lower())
    if syntax is None:
        return [False for _ in blocks]

    states: dict[str, str] = {"old": "", "new": ""}
    decisions: list[bool] = []
    for diff_lines in blocks:
        changed_line_seen = False
        comment_only = True
        for formatted_line in diff_lines:
            if len(formatted_line) <= 6:
                continue
            marker = formatted_line[6]
            if marker not in {"+", "-", " "}:
                continue
            code = formatted_line[9:] if len(formatted_line) > 9 else ""
            line_number = _line_number(formatted_line)
            streams = ("new",) if marker == "+" else (("old",) if marker == "-" else ("old", "new"))
            for stream in streams:
                has_code, states[stream] = _scan_line(code, syntax, states[stream])
                if marker in {"+", "-"}:
                    changed_line_seen = True
                    if has_code or _is_effective_comment(code, language, line_number):
                        comment_only = False
        decisions.append(changed_line_seen and comment_only)
    return decisions


def _scan_line(code: str, syntax: CommentSyntax, active_block_end: str) -> tuple[bool, str]:
    has_code = False
    index = 0
    while index < len(code):
        if active_block_end:
            end_index = code.find(active_block_end, index)
            if end_index < 0:
                return has_code, active_block_end
            index = end_index + len(active_block_end)
            active_block_end = ""
            continue

        if code[index].isspace():
            index += 1
            continue
        line_prefix = next((prefix for prefix in syntax.line_prefixes if code.startswith(prefix, index)), "")
        if line_prefix:
            break
        block_pair = next((pair for pair in syntax.block_pairs if code.startswith(pair[0], index)), None)
        if block_pair:
            active_block_end = block_pair[1]
            index += len(block_pair[0])
            continue
        if code[index] in {'"', "'", "`"}:
            has_code = True
            index = _skip_quoted_text(code, index)
            continue
        has_code = True
        index += 1
    return has_code, active_block_end


def _skip_quoted_text(code: str, start: int) -> int:
    quote = code[start]
    index = start + 1
    escaped = False
    while index < len(code):
        char = code[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == quote:
            return index + 1
        index += 1
    return index


def _is_effective_comment(code: str, language: str, line_number: int) -> bool:
    normalized = code.strip().lower()
    normalized_language = language.strip().lower()
    if not normalized:
        return False
    if line_number == 1 and normalized.startswith("#!"):
        return True
    if normalized_language == "powershell" and normalized.startswith("#requires"):
        return True
    if normalized_language == "sql" and (normalized.startswith("/*+") or normalized.startswith("/*!")):
        return True
    if normalized_language in {"html", "vue"} and normalized.startswith("<!--[if"):
        return True
    if normalized_language == "go" and normalized.startswith("// +build"):
        return True
    return any(marker.lower() in normalized for marker in _EFFECTIVE_COMMENT_MARKERS)


def _line_number(formatted_line: str) -> int:
    value = formatted_line[:6].strip()
    return int(value) if re.fullmatch(r"\d+", value) else 0
