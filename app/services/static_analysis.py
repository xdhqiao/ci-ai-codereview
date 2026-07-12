from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse

from app.core.config import Settings


@dataclass(frozen=True)
class StaticFinding:
    analyzer: str
    rule_id: str
    level: str
    message: str
    file_name: str
    start_line: int
    end_line: int
    help_uri: str = ""
    fingerprint: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "analyzer": self.analyzer,
            "rule_id": self.rule_id,
            "level": self.level,
            "message": self.message,
            "file_name": self.file_name,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "help_uri": self.help_uri,
            "fingerprint": self.fingerprint,
        }


class SarifFindingLoader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def load(self, review_root: Path) -> dict[str, list[StaticFinding]]:
        if not self.settings.review_static_analysis_enabled:
            return {}
        findings: dict[str, list[StaticFinding]] = {}
        seen: set[str] = set()
        remaining = max(0, self.settings.review_static_analysis_max_findings)
        for report_path in self._report_paths(review_root):
            if remaining <= 0:
                break
            for finding in self._read_report(report_path, review_root, remaining):
                if finding.fingerprint in seen:
                    continue
                seen.add(finding.fingerprint)
                findings.setdefault(finding.file_name, []).append(finding)
                remaining -= 1
                if remaining <= 0:
                    break
        for file_findings in findings.values():
            file_findings.sort(key=lambda item: (item.start_line, item.end_line, item.rule_id, item.analyzer))
        return findings

    def _report_paths(self, review_root: Path) -> list[Path]:
        root = review_root.resolve()
        reports: list[Path] = []
        for raw_pattern in self.settings.review_static_analysis_sarif_paths.split(","):
            pattern = raw_pattern.strip()
            if not pattern:
                continue
            candidate_pattern = Path(pattern)
            if candidate_pattern.is_absolute():
                candidates = [candidate_pattern]
            elif any(character in pattern for character in "*?["):
                candidates = list(root.glob(pattern))
            else:
                candidates = [root / candidate_pattern]
            for candidate in candidates:
                try:
                    resolved = candidate.resolve(strict=True)
                    resolved.relative_to(root)
                except (FileNotFoundError, OSError, ValueError):
                    continue
                if not resolved.is_file() or resolved.suffix.lower() not in {".sarif", ".json"}:
                    continue
                if resolved.stat().st_size > max(1, self.settings.review_static_analysis_max_report_bytes):
                    continue
                reports.append(resolved)
        return sorted(set(reports))

    def _read_report(self, report_path: Path, review_root: Path, limit: int) -> list[StaticFinding]:
        try:
            document = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return []
        if not isinstance(document, dict) or not isinstance(document.get("runs"), list):
            return []
        findings: list[StaticFinding] = []
        for run in document["runs"]:
            if not isinstance(run, dict):
                continue
            driver = ((run.get("tool") or {}).get("driver") or {})
            analyzer = str(driver.get("name") or report_path.stem)
            rule_metadata = self._rule_metadata(driver.get("rules"))
            for result in run.get("results") or []:
                finding = self._parse_result(result, analyzer, rule_metadata, review_root)
                if finding:
                    findings.append(finding)
                if len(findings) >= limit:
                    return findings
        return findings

    def _parse_result(
        self,
        result: Any,
        analyzer: str,
        rule_metadata: dict[str, dict[str, str]],
        review_root: Path,
    ) -> StaticFinding | None:
        if not isinstance(result, dict):
            return None
        locations = result.get("locations") or []
        if not locations or not isinstance(locations[0], dict):
            return None
        physical = locations[0].get("physicalLocation") or {}
        artifact = physical.get("artifactLocation") or {}
        file_name = self._repository_path(str(artifact.get("uri") or ""), review_root)
        region = physical.get("region") or {}
        start_line = self._positive_int(region.get("startLine"))
        end_line = self._positive_int(region.get("endLine")) or start_line
        if not file_name or not start_line:
            return None
        rule_id = str(result.get("ruleId") or "")
        metadata = rule_metadata.get(rule_id, {})
        message_data = result.get("message") or {}
        message = str(message_data.get("text") or message_data.get("markdown") or metadata.get("description") or "")
        if not message:
            return None
        fingerprint_payload = "|".join(
            [analyzer, rule_id, file_name, str(start_line), str(end_line), message]
        )
        return StaticFinding(
            analyzer=analyzer,
            rule_id=rule_id,
            level=str(result.get("level") or "warning").lower(),
            message=message,
            file_name=file_name,
            start_line=start_line,
            end_line=max(start_line, end_line),
            help_uri=str(metadata.get("help_uri") or ""),
            fingerprint=hashlib.sha256(fingerprint_payload.encode("utf-8")).hexdigest(),
        )

    def _repository_path(self, uri: str, review_root: Path) -> str:
        if not uri:
            return ""
        parsed = urlparse(uri)
        raw_path = unquote(parsed.path if parsed.scheme == "file" else uri).replace("\\", "/")
        if parsed.scheme and parsed.scheme != "file":
            return ""
        path = Path(raw_path)
        try:
            if path.is_absolute():
                return path.resolve().relative_to(review_root.resolve()).as_posix()
            normalized = PurePosixPath(raw_path)
            if ".." in normalized.parts:
                return ""
            return normalized.as_posix().removeprefix("./")
        except (OSError, ValueError):
            return ""

    def _rule_metadata(self, rules: Any) -> dict[str, dict[str, str]]:
        metadata: dict[str, dict[str, str]] = {}
        for rule in rules or []:
            if not isinstance(rule, dict) or not rule.get("id"):
                continue
            description = rule.get("shortDescription") or rule.get("fullDescription") or {}
            metadata[str(rule["id"])] = {
                "description": str(description.get("text") or "") if isinstance(description, dict) else "",
                "help_uri": str(rule.get("helpUri") or ""),
            }
        return metadata

    def _positive_int(self, value: Any) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            return 0
        return number if number > 0 else 0
