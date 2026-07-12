from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.services.diff_service import ReviewCollection, ReviewTarget


@dataclass(frozen=True)
class RelatedFile:
    file_name: str
    change_type: str
    score: int
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "file_name": self.file_name,
            "change_type": self.change_type,
            "score": self.score,
            "reasons": list(self.reasons),
        }


class RelatedFileResolver:
    _COMPANION_EXTENSIONS = (
        {".c", ".h", ".cc", ".cpp", ".hpp"},
        {".js", ".jsx", ".ts", ".tsx"},
        {".java", ".kt", ".kts"},
    )
    _QUOTED_REFERENCE = re.compile(r"[\"']([^\"'\r\n]+)[\"']")
    _TEST_PREFIX = re.compile(r"^(?:test_|spec_)", re.IGNORECASE)
    _TEST_SUFFIX = re.compile(r"(?:[._-](?:test|tests|spec))$", re.IGNORECASE)
    _LOCALE_SUFFIX = re.compile(r"(?:[._-](?:[a-z]{2})(?:[_-][A-Z]{2})?)$", re.IGNORECASE)
    _C_FUNCTION_DEFINITION = re.compile(
        r"^[\t ]*(?:[A-Za-z_]\w*[\t ]+|[*][\t ]*)+([A-Za-z_]\w*)[\t ]*"
        r"\([^;{}]*\)[\t ]*\{",
        re.MULTILINE,
    )

    def resolve(
        self,
        current: ReviewTarget,
        collection: ReviewCollection,
        limit: int,
    ) -> list[RelatedFile]:
        if limit <= 0:
            return []
        target_by_path = {target.file_name: target for target in collection.targets}
        change_type_by_path = {item.file_name: item.change_type for item in collection.changed_files}
        resolved: list[RelatedFile] = []
        for candidate_path, change_type in change_type_by_path.items():
            if candidate_path == current.file_name:
                continue
            candidate = target_by_path.get(candidate_path)
            score, reasons = self._relationship(current, candidate_path, candidate)
            if score <= 0:
                continue
            resolved.append(
                RelatedFile(
                    file_name=candidate_path,
                    change_type=change_type,
                    score=score,
                    reasons=tuple(reasons),
                )
            )
        resolved.sort(key=lambda item: (-item.score, item.file_name))
        return resolved[:limit]

    def _relationship(
        self,
        current: ReviewTarget,
        candidate_path: str,
        candidate: ReviewTarget | None,
    ) -> tuple[int, list[str]]:
        current_path = PurePosixPath(current.file_name)
        other_path = PurePosixPath(candidate_path)
        reasons: list[str] = []
        scores: list[int] = []

        if self._are_companions(current_path, other_path):
            scores.append(100)
            reasons.append("companion_source_header")
        if self._references(current.full_code, current_path, other_path):
            scores.append(90)
            reasons.append("current_references_related")
        if candidate and self._references(candidate.full_code, other_path, current_path):
            scores.append(85)
            reasons.append("related_references_current")
        if candidate and current.language == "C" and candidate.language == "C":
            if self._calls_defined_symbol(current.full_code, candidate.full_code):
                scores.append(95)
                reasons.append("current_calls_related_symbol")
            if self._calls_defined_symbol(candidate.full_code, current.full_code):
                scores.append(88)
                reasons.append("related_calls_current_symbol")
        if self._test_key(current_path) == self._test_key(other_path) and current_path.stem != other_path.stem:
            scores.append(80)
            reasons.append("implementation_test_pair")
        if self._locale_key(current_path) == self._locale_key(other_path) and current_path.stem != other_path.stem:
            scores.append(70)
            reasons.append("localized_resource_family")

        return (max(scores, default=0), reasons)

    def _are_companions(self, left: PurePosixPath, right: PurePosixPath) -> bool:
        if left.stem.lower() != right.stem.lower():
            return False
        left_ext = left.suffix.lower()
        right_ext = right.suffix.lower()
        return any(left_ext in group and right_ext in group and left_ext != right_ext for group in self._COMPANION_EXTENSIONS)

    def _references(self, source: str, source_path: PurePosixPath, target_path: PurePosixPath) -> bool:
        if not source:
            return False
        relative = posixpath.relpath(target_path.as_posix(), source_path.parent.as_posix())
        target_values = {
            target_path.as_posix().lower(),
            target_path.name.lower(),
            relative.lower(),
            self._without_suffix(target_path.as_posix()).lower(),
            self._without_suffix(relative).lower(),
        }
        for raw_reference in self._QUOTED_REFERENCE.findall(source):
            reference = raw_reference.replace("\\", "/").removeprefix("./").lower()
            if reference in target_values or reference.removeprefix("../") in target_values:
                return True
            if reference.endswith("/" + target_path.name.lower()):
                return True
            reference_path = PurePosixPath(reference)
            if reference_path.suffix and self._are_companions(reference_path, target_path):
                return True
        return False

    def _test_key(self, path: PurePosixPath) -> tuple[str, str]:
        stem = self._TEST_PREFIX.sub("", path.stem)
        stem = self._TEST_SUFFIX.sub("", stem)
        parent_parts = list(path.parent.parts)
        if parent_parts and parent_parts[-1].lower() in {"src", "source", "test", "tests", "spec", "specs"}:
            parent_parts.pop()
        return (stem.lower(), "/".join(parent_parts).lower())

    def _calls_defined_symbol(self, caller: str, provider: str) -> bool:
        if not caller or not provider:
            return False
        for symbol in self._C_FUNCTION_DEFINITION.findall(provider):
            if re.search(rf"\b{re.escape(symbol)}\s*\(", caller):
                caller_definitions = set(self._C_FUNCTION_DEFINITION.findall(caller))
                if symbol not in caller_definitions:
                    return True
        return False

    def _locale_key(self, path: PurePosixPath) -> tuple[str, str, str]:
        stem = self._LOCALE_SUFFIX.sub("", path.stem)
        return (stem.lower(), path.suffix.lower(), path.parent.as_posix().lower())

    def _without_suffix(self, value: str) -> str:
        path = PurePosixPath(value)
        return path.with_suffix("").as_posix()
