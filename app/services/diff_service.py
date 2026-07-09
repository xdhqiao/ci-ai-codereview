from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings
from app.services.language import detect_language


TASK_TYPE_INCREMENTAL = 1
TASK_TYPE_FULL_SCAN = 2


@dataclass(frozen=True)
class ReviewTarget:
    file_name: str
    diff_lines: list[str]
    full_code: str
    language: str
    code_line_num: int
    add_code_line_num: int


class CodeDiffService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def compare_directories(self, base_dir: Path, head_dir: Path) -> list[ReviewTarget]:
        base_dir = base_dir.resolve()
        head_dir = head_dir.resolve()
        if not base_dir.exists() or not base_dir.is_dir():
            raise FileNotFoundError(f"Base directory does not exist: {base_dir}")
        if not head_dir.exists() or not head_dir.is_dir():
            raise FileNotFoundError(f"Head directory does not exist: {head_dir}")

        base_files = self._collect_files(base_dir)
        head_files = self._collect_files(head_dir)
        targets: list[ReviewTarget] = []
        for rel_path in sorted(head_files):
            head_path = head_files[rel_path]
            base_path = base_files.get(rel_path)
            if base_path and self._md5(base_path) == self._md5(head_path):
                continue

            base_lines = self._read_text_lines(base_path) if base_path else []
            head_lines = self._read_text_lines(head_path)
            diff_lines = self.create_diff_lines(base_lines, head_lines)
            if not diff_lines:
                continue

            targets.append(
                ReviewTarget(
                    file_name=rel_path.as_posix(),
                    diff_lines=diff_lines,
                    full_code="".join(head_lines),
                    language=detect_language(rel_path.name),
                    code_line_num=len(head_lines),
                    add_code_line_num=sum(1 for line in diff_lines if len(line) > 6 and line[6] == "+"),
                )
            )
        return targets

    def scan_directory(self, target_dir: Path) -> list[ReviewTarget]:
        target_dir = target_dir.resolve()
        if not target_dir.exists() or not target_dir.is_dir():
            raise FileNotFoundError(f"Review directory does not exist: {target_dir}")

        targets: list[ReviewTarget] = []
        for rel_path, file_path in sorted(self._collect_files(target_dir).items()):
            lines = self._read_text_lines(file_path)
            if not lines:
                continue
            diff_lines = [self._format_diff_line(index, "+", line.rstrip("\n")) for index, line in enumerate(lines, start=1)]
            targets.append(
                ReviewTarget(
                    file_name=rel_path.as_posix(),
                    diff_lines=diff_lines,
                    full_code="".join(lines),
                    language=detect_language(rel_path.name),
                    code_line_num=len(lines),
                    add_code_line_num=len(lines),
                )
            )
        return targets

    def create_diff_lines(self, base_lines: list[str], head_lines: list[str]) -> list[str]:
        matcher = difflib.SequenceMatcher(a=base_lines, b=head_lines, autojunk=False)
        old_indices: set[int] = set()
        new_indices: set[int] = set()
        context = max(0, self.settings.diff_context_lines)

        opcodes = matcher.get_opcodes()
        for tag, old_start, old_end, new_start, new_end in opcodes:
            if tag == "equal":
                continue
            old_indices.update(range(max(0, old_start - context), min(len(base_lines), old_end + context)))
            new_indices.update(range(max(0, new_start - context), min(len(head_lines), new_end + context)))

        result: list[str] = []
        for tag, old_start, old_end, new_start, new_end in opcodes:
            if tag == "equal":
                for new_index in range(new_start, new_end):
                    if new_index in new_indices:
                        result.append(self._format_diff_line(new_index + 1, " ", head_lines[new_index].rstrip("\n")))
                continue

            if tag in {"replace", "delete"}:
                for old_index in range(old_start, old_end):
                    if old_index in old_indices:
                        result.append(self._format_diff_line(old_index + 1, "-", base_lines[old_index].rstrip("\n")))

            if tag in {"replace", "insert"}:
                for new_index in range(new_start, new_end):
                    if new_index in new_indices:
                        result.append(self._format_diff_line(new_index + 1, "+", head_lines[new_index].rstrip("\n")))

        return result

    def split_code_blocks(self, lines: list[str]) -> list[list[str]]:
        if self._approximate_tokens(lines) <= self.settings.diff_token_threshold:
            return [lines]

        blocks: list[list[str]] = []
        current: list[str] = []
        current_tokens = 0
        for line in lines:
            line_tokens = self._approximate_tokens([line])
            if current and current_tokens + line_tokens > self.settings.diff_token_threshold:
                blocks.append(current)
                current = []
                current_tokens = 0
            current.append(line)
            current_tokens += line_tokens
        if current:
            blocks.append(current)
        return blocks

    def resolve_incremental_paths(
        self,
        project_id: str,
        copy_from_version: str,
        review_version: str,
        parent_path: str | None,
    ) -> tuple[Path, Path]:
        return (
            self._resolve_version_path(project_id, copy_from_version, parent_path),
            self._resolve_version_path(project_id, review_version, parent_path),
        )

    def resolve_full_scan_path(self, project_id: str, review_version: str, parent_path: str | None) -> Path:
        if review_version:
            return self._resolve_version_path(project_id, review_version, parent_path)
        if parent_path:
            return Path(parent_path)
        return Path.cwd()

    def _resolve_version_path(self, project_id: str, version_value: str, parent_path: str | None) -> Path:
        version_path = Path(version_value)
        if version_value and version_path.is_absolute():
            return version_path
        if parent_path:
            return Path(parent_path) / version_value
        if self.settings.code_repository_root:
            return Path(self.settings.code_repository_root) / project_id / version_value
        return version_path

    def _collect_files(self, root: Path) -> dict[Path, Path]:
        files: dict[Path, Path] = {}
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel_path = path.relative_to(root)
            if self._is_excluded(rel_path) or not self._is_allowed(path):
                continue
            if self._looks_binary(path):
                continue
            files[rel_path] = path
        return files

    def _is_excluded(self, rel_path: Path) -> bool:
        return any(part in self.settings.excluded_dir_set for part in rel_path.parts)

    def _is_allowed(self, path: Path) -> bool:
        return path.suffix.lower() in self.settings.allowed_extension_set

    def _looks_binary(self, path: Path) -> bool:
        try:
            return b"\x00" in path.read_bytes()[:4096]
        except OSError:
            return True

    def _read_text_lines(self, path: Path | None) -> list[str]:
        if path is None:
            return []
        return path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)

    def _md5(self, path: Path) -> str:
        digest = hashlib.md5()
        with path.open("rb") as file_handle:
            for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _format_diff_line(self, line_number: int, marker: str, text: str) -> str:
        return f"{line_number:>6}{marker}  {text}"

    def _approximate_tokens(self, lines: list[str]) -> int:
        return sum(max(1, len(line) // 4) for line in lines)
