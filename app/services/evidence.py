from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True)
class EvidenceMatch:
    start_line: int = 0
    end_line: int = 0
    score: float = 0.0
    status: str = "missing"
    source: str = ""
    occurrence_count: int = 0
    changed_line_overlap: bool = False
    ambiguous: bool = False
    matched_code: str = ""

    @property
    def found(self) -> bool:
        return self.start_line > 0 and self.end_line >= self.start_line

    @property
    def line_numbers(self) -> str:
        if not self.found:
            return ""
        if self.start_line == self.end_line:
            return str(self.start_line)
        return f"{self.start_line}-{self.end_line}"


@dataclass(frozen=True)
class _SourceLine:
    line_number: int
    normalized: str
    raw: str
    changed: bool
    source: str


@dataclass(frozen=True)
class _Candidate:
    start_line: int
    end_line: int
    score: float
    changed_line_overlap: bool
    source: str
    matched_code: str


class CodeEvidenceLocator:
    """Locate a code fragment deterministically before asking the model."""

    def __init__(self, minimum_similarity: float = 0.55) -> None:
        self.minimum_similarity = min(1.0, max(0.0, minimum_similarity))

    def locate(
        self,
        existing_code: str,
        full_code: str,
        diff_lines: list[str],
        claimed_line_numbers: list[int] | None = None,
    ) -> EvidenceMatch:
        target_lines = self._normalized_fragment_lines(existing_code)
        if not target_lines:
            return EvidenceMatch()

        changed_lines = {
            line_number
            for line_number, marker, _ in self._iter_diff_lines(diff_lines)
            if marker == "+"
        }
        diff_source = self._diff_new_side(diff_lines)
        file_source = self._full_file_lines(full_code, changed_lines)

        exact_candidates = self._deduplicate_candidates(
            [
                *self._exact_candidates(diff_source, target_lines),
                *self._exact_candidates(file_source, target_lines),
            ]
        )
        if exact_candidates:
            return self._select(exact_candidates, claimed_line_numbers or [], exact=True)

        fuzzy_candidates = self._deduplicate_candidates(
            [
                *self._fuzzy_candidates(diff_source, target_lines),
                *self._fuzzy_candidates(file_source, target_lines),
            ]
        )
        fuzzy_candidates = [candidate for candidate in fuzzy_candidates if candidate.score >= self.minimum_similarity]
        if not fuzzy_candidates:
            return EvidenceMatch(score=self._best_score(diff_source, file_source, target_lines))
        return self._select(fuzzy_candidates, claimed_line_numbers or [], exact=False)

    def _select(self, candidates: list[_Candidate], claimed: list[int], exact: bool) -> EvidenceMatch:
        claimed_line = claimed[0] if claimed else 0

        def sort_key(candidate: _Candidate) -> tuple[int, float, int, int]:
            distance = abs(candidate.start_line - claimed_line) if claimed_line else candidate.start_line
            return (
                0 if candidate.changed_line_overlap else 1,
                -candidate.score,
                distance,
                candidate.start_line,
            )

        ordered = sorted(candidates, key=sort_key)
        best = ordered[0]
        equally_ranked = [
            candidate
            for candidate in ordered
            if candidate.changed_line_overlap == best.changed_line_overlap
            and abs(candidate.score - best.score) < 0.001
        ]
        ambiguous = len(equally_ranked) > 1
        status = "matched" if exact and not ambiguous else "partial"
        return EvidenceMatch(
            start_line=best.start_line,
            end_line=best.end_line,
            score=best.score,
            status=status,
            source=best.source,
            occurrence_count=len(candidates),
            changed_line_overlap=best.changed_line_overlap,
            ambiguous=ambiguous,
            matched_code=best.matched_code,
        )

    def _exact_candidates(self, source: list[_SourceLine], target_lines: list[str]) -> list[_Candidate]:
        candidates: list[_Candidate] = []
        width = len(target_lines)
        if width == 0 or len(source) < width:
            return candidates
        for start in range(0, len(source) - width + 1):
            window = source[start : start + width]
            if not self._valid_window(window):
                continue
            if [line.normalized for line in window] != target_lines:
                continue
            candidates.append(self._candidate(window, 1.0))
        return candidates

    def _fuzzy_candidates(self, source: list[_SourceLine], target_lines: list[str]) -> list[_Candidate]:
        target = "\n".join(target_lines)
        if len(target) < 8:
            return []
        width = len(target_lines)
        candidates: list[_Candidate] = []
        if width == 0 or len(source) < width:
            return candidates
        for start in range(0, len(source) - width + 1):
            window = source[start : start + width]
            if not self._valid_window(window):
                continue
            candidate_text = "\n".join(line.normalized for line in window)
            score = max(
                SequenceMatcher(None, target, candidate_text).ratio(),
                SequenceMatcher(None, target.lower(), candidate_text.lower()).ratio(),
            )
            if score >= self.minimum_similarity:
                candidates.append(self._candidate(window, score))
        return candidates

    def _candidate(self, window: list[_SourceLine], score: float) -> _Candidate:
        return _Candidate(
            start_line=window[0].line_number,
            end_line=window[-1].line_number,
            score=score,
            changed_line_overlap=any(line.changed for line in window),
            source=window[0].source,
            matched_code="\n".join(line.raw for line in window),
        )

    def _deduplicate_candidates(self, candidates: list[_Candidate]) -> list[_Candidate]:
        deduplicated: dict[tuple[int, int], _Candidate] = {}
        for candidate in candidates:
            key = (candidate.start_line, candidate.end_line)
            current = deduplicated.get(key)
            if current is None or self._candidate_priority(candidate) < self._candidate_priority(current):
                deduplicated[key] = candidate
        return list(deduplicated.values())

    def _candidate_priority(self, candidate: _Candidate) -> tuple[int, float, int]:
        return (
            0 if candidate.source == "diff" else 1,
            -candidate.score,
            0 if candidate.changed_line_overlap else 1,
        )

    def _best_score(
        self,
        diff_source: list[_SourceLine],
        file_source: list[_SourceLine],
        target_lines: list[str],
    ) -> float:
        candidates = [
            *self._fuzzy_candidates_without_threshold(diff_source, target_lines),
            *self._fuzzy_candidates_without_threshold(file_source, target_lines),
        ]
        return max((candidate.score for candidate in candidates), default=0.0)

    def _fuzzy_candidates_without_threshold(
        self,
        source: list[_SourceLine],
        target_lines: list[str],
    ) -> list[_Candidate]:
        target = "\n".join(target_lines)
        width = len(target_lines)
        if not target or width == 0 or len(source) < width:
            return []
        candidates: list[_Candidate] = []
        for start in range(0, len(source) - width + 1):
            window = source[start : start + width]
            if not self._valid_window(window):
                continue
            candidate_text = "\n".join(line.normalized for line in window)
            score = SequenceMatcher(None, target.lower(), candidate_text.lower()).ratio()
            candidates.append(self._candidate(window, score))
        return candidates

    def _valid_window(self, window: list[_SourceLine]) -> bool:
        return all(
            current.line_number > previous.line_number
            and current.line_number - previous.line_number <= 8
            for previous, current in zip(window, window[1:])
        )

    def _diff_new_side(self, diff_lines: list[str]) -> list[_SourceLine]:
        source: list[_SourceLine] = []
        for line_number, marker, code in self._iter_diff_lines(diff_lines):
            if marker not in {"+", " "}:
                continue
            normalized = self._normalize_line(code)
            if not normalized:
                continue
            source.append(
                _SourceLine(
                    line_number=line_number,
                    normalized=normalized,
                    raw=code,
                    changed=marker == "+",
                    source="diff",
                )
            )
        return source

    def _full_file_lines(self, full_code: str, changed_lines: set[int]) -> list[_SourceLine]:
        source: list[_SourceLine] = []
        for line_number, code in enumerate(full_code.splitlines(), start=1):
            normalized = self._normalize_line(code)
            if not normalized:
                continue
            source.append(
                _SourceLine(
                    line_number=line_number,
                    normalized=normalized,
                    raw=code,
                    changed=line_number in changed_lines,
                    source="full_file",
                )
            )
        return source

    def _iter_diff_lines(self, diff_lines: list[str]):
        for line in diff_lines:
            if len(line) < 9:
                continue
            try:
                line_number = int(line[:6].strip())
            except ValueError:
                continue
            yield line_number, line[6], line[9:]

    def _normalized_fragment_lines(self, code: str) -> list[str]:
        lines: list[str] = []
        for raw_line in str(code or "").splitlines():
            stripped = raw_line.strip()
            if stripped.startswith(("+ ", "- ")):
                stripped = stripped[1:].strip()
            normalized = self._normalize_line(stripped)
            if normalized:
                lines.append(normalized)
        return lines

    def _normalize_line(self, line: str) -> str:
        return re.sub(r"\s+", "", line.strip())
