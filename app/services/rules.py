from __future__ import annotations

import fnmatch
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings


class ReviewRuleResolver:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.rule_data = self._load_rule_data()

    def resolve(self, file_name: str, language: str) -> dict[str, Any]:
        resolved: dict[str, Any] = deepcopy(self.rule_data.get("default") or {})
        resolved["language"] = language
        resolved["file_name"] = file_name

        explicit_rule = self._first_matching_rule(file_name)
        if explicit_rule is not None:
            rule_text = str(explicit_rule.get("rule") or "").strip()
            resolved["focus"] = [rule_text] if rule_text else []
            resolved["matched_rule_id"] = str(explicit_rule.get("id") or "")
            resolved["matched_rule_pattern"] = str(explicit_rule.get("path") or "")
            resolved["resolution"] = "first-match"
            return resolved

        extension = Path(file_name).suffix.lower()
        for language_rule in self.rule_data.get("languages") or []:
            if self._matches_language_rule(language_rule, language, extension):
                self._merge_rule(resolved, language_rule)

        for path_rule in self.rule_data.get("path_rules") or []:
            pattern = str(path_rule.get("pattern") or "")
            if pattern and (pattern in file_name or fnmatch.fnmatch(file_name, pattern)):
                self._merge_rule(resolved, path_rule)

        resolved["focus"] = self._dedupe_list(resolved.get("focus") or [])
        resolved["resolution"] = "legacy-merge"
        return resolved

    def _first_matching_rule(self, file_name: str) -> dict[str, Any] | None:
        normalized = file_name.replace("\\", "/")
        for index, rule in enumerate(self.rule_data.get("rules") or []):
            if not isinstance(rule, dict):
                continue
            pattern = str(rule.get("path") or "").replace("\\", "/")
            if not pattern:
                continue
            if any(self._glob_matches(normalized, expanded) for expanded in self._expand_braces(pattern)):
                matched = deepcopy(rule)
                matched.setdefault("id", f"rule-{index + 1}")
                return matched
        return None

    def _glob_matches(self, file_name: str, pattern: str) -> bool:
        candidates = [pattern]
        if pattern.startswith("**/"):
            candidates.append(pattern[3:])
        return any(fnmatch.fnmatch(file_name, candidate) for candidate in candidates)

    def _expand_braces(self, pattern: str) -> list[str]:
        start = pattern.find("{")
        end = pattern.find("}", start + 1)
        if start < 0 or end < 0:
            return [pattern]
        values = [value.strip() for value in pattern[start + 1 : end].split(",") if value.strip()]
        if not values:
            return [pattern]
        expanded: list[str] = []
        for value in values:
            expanded.extend(self._expand_braces(pattern[:start] + value + pattern[end + 1 :]))
        return expanded

    def _load_rule_data(self) -> dict[str, Any]:
        built_in_path = Path(__file__).with_name("review_rules.json")
        data = self._read_json_file(built_in_path)
        if self.settings.review_rules_path:
            external_path = Path(self.settings.review_rules_path)
            if external_path.exists():
                self._merge_rule(data, self._read_json_file(external_path))
        return data

    def _read_json_file(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _matches_language_rule(self, rule: dict[str, Any], language: str, extension: str) -> bool:
        rule_language = str(rule.get("language") or "").lower()
        if rule_language and rule_language in language.lower():
            return True
        return extension in {str(item).lower() for item in rule.get("extensions") or []}

    def _merge_rule(self, base: dict[str, Any], override: dict[str, Any]) -> None:
        for key, value in override.items():
            if key in {"language", "extensions", "pattern"}:
                continue
            if isinstance(value, list) and isinstance(base.get(key), list):
                base[key] = [*base[key], *value]
                continue
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                nested = deepcopy(base[key])
                self._merge_rule(nested, value)
                base[key] = nested
                continue
            base[key] = deepcopy(value)

    def _dedupe_list(self, values: list[Any]) -> list[Any]:
        seen: set[str] = set()
        deduped: list[Any] = []
        for value in values:
            key = json.dumps(value, ensure_ascii=False, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(value)
        return deduped


def review_rules_for(file_name: str, language: str, settings: Settings | None = None) -> str:
    rules = ReviewRuleResolver(settings).resolve(file_name=file_name, language=language)
    return json.dumps(rules, ensure_ascii=False, indent=2)
