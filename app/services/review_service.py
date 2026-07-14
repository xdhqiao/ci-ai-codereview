from __future__ import annotations

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock
from typing import Any

from app.core.config import Settings, get_settings
from app.core.exceptions import NotFoundError, ReviewInterruptedError
from app.models.code_file import CodeBlock, CodeFileModel, Issue, ModelRoundTrace, ToolCallTrace
from app.models.task import TaskModel
from app.services.background import FileBackgroundProvider, FileReviewBackground, MockFileBackgroundProvider
from app.services.diff_service import (
    TASK_TYPE_FULL_SCAN,
    TASK_TYPE_INCREMENTAL,
    CodeDiffService,
    ReviewCollection,
    ReviewTarget,
)
from app.services.evidence import CodeEvidenceLocator, EvidenceMatch
from app.services.exclusions import project_exclude_paths
from app.services.llm_client import LLMClient
from app.services.notification import ReviewNotificationService
from app.services.prompts import (
    MAIN_TOOL_DEFINITIONS,
    build_batch_dedup_messages,
    build_main_messages,
    build_memory_compression_messages,
    build_plan_messages,
    build_project_summary_messages,
    build_relocation_messages,
    build_review_filter_messages,
)
from app.services.review_tools import ReviewToolRunner
from app.services.related_files import RelatedFile, RelatedFileResolver
from app.services.rules import review_rules_for
from app.services.semantic_index import SemanticIndex
from app.services.static_analysis import SarifFindingLoader, StaticFinding
from app.services.task_submission import TaskFileSynchronizer, code_block_hash, review_target_hash


SCORE_FIELDS = ["logic_score", "performance_score", "security_score", "readable_score", "code_style_score"]
TASK_STATE_COMPLETED = 2
TASK_STATE_PARTIAL = 3
REVIEW_PIPELINE_VERSION = "2026-07-12-ocr-accuracy-v5-background-semantic-index"


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
    change_summary: str = ""
    risk_level: str = "medium"
    checkpoints: list[dict[str, Any]] | None = None
    failure_message: str = ""
    model_rounds: list[ModelRoundTrace] | None = None

    def guidance_json(self) -> str:
        return json.dumps(
            {
                "comment": self.comment,
                "change_summary": self.change_summary,
                "risk_level": self.risk_level,
                "checkpoints": self.checkpoints or [],
            },
            ensure_ascii=False,
            indent=2,
        )


@dataclass
class MainResult:
    issues: list[Issue]
    failure_message: str = ""
    model_rounds: list[ModelRoundTrace] | None = None
    tool_call_traces: list[ToolCallTrace] | None = None
    memory_compression_count: int = 0
    completed: bool = False
    completion_mode: str = ""
    round_count: int = 0


class ReviewTaskService:
    def __init__(
        self,
        settings: Settings | None = None,
        background_provider: FileBackgroundProvider | None = None,
        stop_event: Event | None = None,
        lease_token: str = "",
    ) -> None:
        self.settings = settings or get_settings()
        self.diff_service = CodeDiffService(self.settings)
        self.llm_client = LLMClient(self.settings)
        self.review_context = ReviewCollection(targets=[], diff_map={}, changed_files=[])
        self.evidence_locator = CodeEvidenceLocator(self.settings.review_line_evidence_min_similarity)
        self.related_file_resolver = RelatedFileResolver()
        self.background_provider = background_provider or MockFileBackgroundProvider()
        self.file_backgrounds: dict[str, FileReviewBackground] = {}
        self._background_lock = Lock()
        self.semantic_index: SemanticIndex | None = None
        self.static_findings_by_file: dict[str, list[StaticFinding]] = {}
        self.task_model_rounds: list[ModelRoundTrace] = []
        self.rule_settings = self.settings
        self.project_exclude_paths: list[str] = []
        self.stop_event = stop_event
        self.lease_token = lease_token
        self.active_task_id = ""
        self.active_trigger_revision = 0
        self._usage_lock = Lock()
        self._initial_usage: dict[str, Any] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "elapsed_ms": 0,
            "call_count": 0,
            "process_time": 0,
            "tool_calls": {},
        }
        self._run_usage: dict[str, Any] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "elapsed_ms": 0,
            "call_count": 0,
            "tool_calls": {},
        }

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
        self.task_model_rounds = []
        self.file_backgrounds = {}
        self.active_task_id = str(task.id)
        self.active_trigger_revision = task.trigger_revision or 0
        self.project_exclude_paths = project_exclude_paths(task.project_id)
        self.diff_service.set_project_exclude_paths(self.project_exclude_paths)
        self._initialize_usage(task)
        task.state = 1
        task.completion_status = "running"
        task.last_start_time = utc_now()
        task.interrupt_requested = False
        task.update_time = utc_now()
        task.save()

        try:
            self._check_interrupted()
            review_context, review_root = self._collect_targets(task)
            self.review_context = review_context
            TaskFileSynchronizer(self.diff_service).synchronize(task, review_context)
            self.rule_settings = self._resolve_rule_settings(review_root)
            self.semantic_index = (
                SemanticIndex(review_root, self.settings, self.project_exclude_paths)
                if self.settings.review_semantic_index_enabled
                else None
            )
            self.static_findings_by_file = SarifFindingLoader(self.settings).load(review_root)
            targets = review_context.targets
            self._check_interrupted()
            saved_files = self._review_targets(task, targets, review_root)

            self._check_interrupted()
            self._finish_task(task, saved_files, started_at)
            if task.state == TASK_STATE_COMPLETED and not task.completion_email_sent:
                ReviewNotificationService().send_review_completed(task)
                task.completion_email_sent = True
                task.save()
            return task
        except ReviewInterruptedError:
            self._mark_task_interrupted(task)
            return TaskModel.objects(id=task.id).first() or task
        except Exception as exc:
            task.retry_count = (task.retry_count or 0) + 1
            task.state = TASK_STATE_PARTIAL
            task.completion_status = "failed"
            task.developer_issue_summary = {
                **(task.developer_issue_summary or {}),
                "_fatal_error": {
                    "type": type(exc).__name__,
                    "message": self._truncate(str(exc), 1000),
                },
            }
            task.task_model_rounds = self.task_model_rounds
            task.lease_owner = ""
            task.lease_token = ""
            task.lease_expires_at = None
            task.heartbeat_time = None
            task.update_time = utc_now()
            task.save()
            raise

    def _collect_targets(self, task: TaskModel) -> tuple[ReviewCollection, Path]:
        task_type = self._resolve_task_type(task)
        task.task_type = task_type
        task.save()

        if task_type == TASK_TYPE_INCREMENTAL:
            if task.copy_from_version_path and task.review_version_path:
                base_dir, head_dir = Path(task.copy_from_version_path), Path(task.review_version_path)
            else:
                base_dir, head_dir = self.diff_service.resolve_incremental_paths(
                    task.project_id,
                    task.copy_from_version,
                    task.review_version,
                    task.parent_path,
                )
            return self.diff_service.compare_directories_with_context(base_dir, head_dir), head_dir

        target_dir = (
            Path(task.review_version_path)
            if task.review_version_path
            else self.diff_service.resolve_full_scan_path(task.project_id, task.review_version, task.parent_path)
        )
        return self.diff_service.scan_directory_with_context(target_dir), target_dir

    def _resolve_task_type(self, task: TaskModel) -> int:
        if task.task_type in {TASK_TYPE_INCREMENTAL, TASK_TYPE_FULL_SCAN}:
            return int(task.task_type)
        copy_from_version = (task.copy_from_version or "").strip()
        if copy_from_version in {"", "0", "0_version"}:
            return TASK_TYPE_FULL_SCAN
        return TASK_TYPE_INCREMENTAL

    def _review_targets(self, task: TaskModel, targets: list[ReviewTarget], review_root: Path) -> list[CodeFileModel]:
        if not targets:
            return []

        target_stats = self._prepare_targets_for_review(task, targets)
        batch_size = max(1, self.settings.scan_batch_size)
        concurrency = max(1, self.settings.llm_concurrency)
        saved_files: list[CodeFileModel] = list(target_stats["reused_files"]) + list(target_stats["skipped_files"])
        queued_targets: list[ReviewTarget] = list(target_stats["queued_targets"])

        batches = self._group_target_batches(task, queued_targets, batch_size)
        for batch_index, batch in enumerate(batches, start=1):
            self._check_interrupted()
            if concurrency == 1 or len(batch) == 1:
                batch_results = []
                for target in batch:
                    self._check_interrupted()
                    batch_results.append(self._review_file(task, target, review_root))
                self._deduplicate_batch_issues(task, batch_results, batch_index)
                saved_files.extend(batch_results)
                continue

            with ThreadPoolExecutor(max_workers=min(concurrency, len(batch))) as executor:
                future_map = {
                    executor.submit(self._review_file, task, target, review_root): target.file_name
                    for target in batch
                }
                batch_results: list[CodeFileModel] = []
                for future in as_completed(future_map):
                    batch_results.append(future.result())
                    self._check_interrupted()
                batch_results = sorted(batch_results, key=lambda code_file: code_file.file_name)
                self._deduplicate_batch_issues(task, batch_results, batch_index)
                saved_files.extend(batch_results)

        return sorted(saved_files, key=lambda code_file: code_file.file_name)

    def _group_target_batches(
        self,
        task: TaskModel,
        targets: list[ReviewTarget],
        batch_size: int,
    ) -> list[list[ReviewTarget]]:
        if not targets:
            return []
        strategy = self.settings.scan_batch_strategy.strip().lower()
        if task.task_type != TASK_TYPE_FULL_SCAN or strategy not in {"by-language", "by-directory"}:
            return [targets[start : start + batch_size] for start in range(0, len(targets), batch_size)]

        buckets: dict[str, list[ReviewTarget]] = {}
        for target in targets:
            if strategy == "by-language":
                key = target.language.lower() or "<unknown>"
            else:
                key = target.file_name.split("/", 1)[0] if "/" in target.file_name else "<root>"
            buckets.setdefault(key, []).append(target)

        batches: list[list[ReviewTarget]] = []
        for key in sorted(buckets):
            group = buckets[key]
            for start in range(0, len(group), batch_size):
                batches.append(group[start : start + batch_size])
        return batches

    def _prepare_targets_for_review(self, task: TaskModel, targets: list[ReviewTarget]) -> dict[str, list[Any]]:
        queued_targets: list[ReviewTarget] = []
        reused_files: list[CodeFileModel] = []
        skipped_files: list[CodeFileModel] = []
        consumed_tokens = 0
        total_estimated_tokens = sum(self._estimate_target_tokens(target) for target in targets)
        token_budget = self._effective_token_budget(task)

        for target in targets:
            source_hash = self._source_hash(target)
            review_fingerprint = self._target_hash(task, target, source_hash)
            estimated_tokens = self._estimate_target_tokens(target)
            existing = self._find_reusable_code_file(task, target, source_hash, review_fingerprint)
            if existing:
                existing.extra = {
                    **(existing.extra or {}),
                    "status": "resumed",
                    "source_hash": source_hash,
                    "review_fingerprint": review_fingerprint,
                    "estimated_tokens": estimated_tokens,
                    "resume_time": utc_now().isoformat(),
                }
                existing.save()
                reused_files.append(existing)
                continue

            if token_budget > 0 and consumed_tokens + estimated_tokens > token_budget:
                skipped_files.append(
                    self._save_budget_skipped_file(
                        task=task,
                        target=target,
                        source_hash=source_hash,
                        review_fingerprint=review_fingerprint,
                        estimated_tokens=estimated_tokens,
                        token_budget=token_budget,
                        consumed_tokens=consumed_tokens,
                    )
                )
                continue

            consumed_tokens += estimated_tokens
            queued_targets.append(target)

        task.estimated_token_num = total_estimated_tokens
        task.consumed_estimated_token_num = consumed_tokens
        task.token_budget_num = token_budget
        task.resumed_file_num = len(reused_files)
        task.skipped_file_num = len(skipped_files)
        task.save()
        return {
            "queued_targets": queued_targets,
            "reused_files": reused_files,
            "skipped_files": skipped_files,
        }

    def _effective_token_budget(self, task: TaskModel) -> int:
        if task.task_type != TASK_TYPE_FULL_SCAN:
            return 0
        return max(0, self.settings.full_scan_token_budget)

    def _find_reusable_code_file(
        self,
        task: TaskModel,
        target: ReviewTarget,
        source_hash: str,
        review_fingerprint: str,
    ) -> CodeFileModel | None:
        if not self.settings.review_resume_enabled:
            return None
        code_file = CodeFileModel.objects(task_id=str(task.id), file_name=target.file_name).first()
        if not code_file:
            return None
        extra = code_file.extra or {}
        if (code_file.source_hash or extra.get("source_hash")) != source_hash:
            return None
        if (code_file.review_fingerprint or extra.get("review_fingerprint")) != review_fingerprint:
            return None
        if extra.get("status") == "skipped_budget":
            return None
        if not code_file.code_blocks:
            return None
        if any(not block.main_task_completed or block.failure_message for block in code_file.code_blocks):
            return None
        return code_file

    def _save_budget_skipped_file(
        self,
        task: TaskModel,
        target: ReviewTarget,
        source_hash: str,
        review_fingerprint: str,
        estimated_tokens: int,
        token_budget: int,
        consumed_tokens: int,
    ) -> CodeFileModel:
        background = self._file_background(task, target)
        CodeFileModel.objects(task_id=str(task.id), file_name=target.file_name).delete()
        code_file = CodeFileModel(
            task_id=str(task.id),
            project_id=task.project_id,
            review_version=task.review_version,
            copy_from_version=task.copy_from_version,
            task_type=task.task_type,
            file_name=target.file_name,
            background=background.content,
            background_source=background.source,
            code_blocks=[],
            code_line_num=target.code_line_num,
            add_code_line_num=target.add_code_line_num,
            comment_line_number=0,
            extra={
                "status": "skipped_budget",
                "source_hash": source_hash,
                "review_fingerprint": review_fingerprint,
                "estimated_tokens": estimated_tokens,
                "token_budget": token_budget,
                "consumed_estimated_tokens_before_skip": consumed_tokens,
                "reason": "full_scan_token_budget exceeded",
            },
        )
        code_file.save()
        return code_file

    def _deduplicate_batch_issues(
        self,
        task: TaskModel,
        code_files: list[CodeFileModel],
        batch_index: int,
    ) -> None:
        if task.task_type != TASK_TYPE_FULL_SCAN or not self.settings.full_scan_batch_dedup_enabled:
            return

        seen: dict[tuple[str, int, str, str], tuple[CodeFileModel, CodeBlock, Issue]] = {}
        group_ids: dict[tuple[str, int, str, str], str] = {}
        duplicate_count = 0
        for code_file in code_files:
            if (code_file.extra or {}).get("status") != "reviewed":
                continue
            for block in code_file.code_blocks:
                for issue_index, issue in enumerate(block.issues):
                    if not self._is_reportable_issue(issue):
                        continue
                    key = self._batch_issue_key(issue)
                    if key not in seen:
                        seen[key] = (code_file, block, issue)
                        continue
                    duplicate_count += 1
                    canonical_file, canonical_block, canonical_issue = seen[key]
                    canonical_ref = (
                        f"{canonical_file.file_name}#block{canonical_block.block_id}"
                        f"#issue{canonical_issue.issue_id or issue_index + 1}"
                    )
                    group_id = group_ids.setdefault(
                        key,
                        f"batch-{batch_index}-exact-{len(group_ids) + 1}",
                    )
                    canonical_issue.duplicate_group_id = group_id
                    canonical_issue.duplicate_of = ""
                    issue.duplicate_group_id = group_id
                    issue.duplicate_of = canonical_ref

        for code_file in code_files:
            code_file.extra = {
                **(code_file.extra or {}),
                "batch_index": batch_index,
                "batch_dedup_duplicate_count": duplicate_count,
                "batch_dedup_mode": "group_only",
            }
            code_file.save()

        semantic_duplicate_count = self._semantic_batch_deduplicate(task, code_files, batch_index)
        if semantic_duplicate_count:
            for code_file in code_files:
                code_file.extra = {
                    **(code_file.extra or {}),
                    "batch_semantic_dedup_duplicate_count": semantic_duplicate_count,
                }
                code_file.save()

    def _batch_issue_key(self, issue: Issue) -> tuple[str, int, str, str]:
        evidence_key = self._normalize_code_fragment(issue.existing_code)
        if not evidence_key:
            evidence_key = self._normalize_issue_text(issue.description)
        return (
            self._normalize_issue_text(issue.type),
            issue.severity,
            self._normalize_issue_text(issue.description),
            evidence_key,
        )

    def _semantic_batch_deduplicate(
        self,
        task: TaskModel,
        code_files: list[CodeFileModel],
        batch_index: int,
    ) -> int:
        if (
            task.task_type != TASK_TYPE_FULL_SCAN
            or len(code_files) < 2
            or self.llm_client.is_mock
            or not self.settings.full_scan_batch_dedup_llm_enabled
        ):
            return 0

        references: dict[str, tuple[CodeFileModel, CodeBlock, Issue]] = {}
        payload: list[dict[str, Any]] = []
        for code_file in code_files:
            for block in code_file.code_blocks:
                for issue in block.issues:
                    if not self._is_reportable_issue(issue):
                        continue
                    issue_ref = f"c-{len(payload)}"
                    references[issue_ref] = (code_file, block, issue)
                    payload.append(
                        {
                            "id": issue_ref,
                            "path": code_file.file_name,
                            "type": issue.type,
                            "severity": issue.severity,
                            "description": issue.description,
                            "existing_code": issue.existing_code,
                            "evidence": issue.evidence,
                            "rule_id": issue.rule_id,
                        }
                    )
        if len(payload) < max(2, self.settings.full_scan_batch_dedup_min_comments):
            return 0

        messages = build_batch_dedup_messages(payload)
        response, rounds, _ = self._run_json_stage(
            stage=f"batch_dedup_task_{batch_index}",
            messages=messages,
            required_list_key="groups",
            repair_prompt=(
                "上一轮批次去重输出无效。请只输出 groups JSON，且每个输入 id 必须恰好出现一次。"
            ),
        )
        self.task_model_rounds.extend(rounds)
        groups = response.get("groups") if isinstance(response, dict) else None
        if not isinstance(groups, list) or not self._valid_dedup_coverage(groups, set(references)):
            return 0

        changed_files: set[str] = set()
        duplicate_count = 0
        for group_index, group in enumerate(groups, start=1):
            members = group.get("members") if isinstance(group, dict) else None
            if not isinstance(members, list) or len(members) < 2:
                continue
            member_refs = [references[str(member)] for member in members]
            if not self._semantic_group_is_safe([item[2] for item in member_refs]):
                continue
            canonical_file, canonical_block, canonical_issue = member_refs[0]
            canonical_ref = (
                f"{canonical_file.file_name}#block{canonical_block.block_id}#issue{canonical_issue.issue_id or 0}"
            )
            group_id = f"batch-{batch_index}-semantic-{group_index}"
            canonical_issue.duplicate_group_id = group_id
            canonical_issue.duplicate_of = ""
            changed_files.add(canonical_file.file_name)
            for code_file, block, issue in member_refs[1:]:
                issue.duplicate_group_id = group_id
                issue.duplicate_of = canonical_ref
                changed_files.add(code_file.file_name)
                duplicate_count += 1

        for code_file in code_files:
            if code_file.file_name not in changed_files:
                continue
            code_file.save()
        return duplicate_count

    def _valid_dedup_coverage(self, groups: list[Any], expected_ids: set[str]) -> bool:
        seen: list[str] = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("members"), list):
                return False
            seen.extend(str(member) for member in group["members"])
        return len(seen) == len(set(seen)) and set(seen) == expected_ids

    def _semantic_group_is_safe(self, issues: list[Issue]) -> bool:
        if len(issues) < 2:
            return False
        if len({self._normalize_issue_text(issue.type) for issue in issues}) != 1:
            return False
        if len({issue.severity for issue in issues}) != 1:
            return False
        rule_ids = {issue.rule_id for issue in issues if issue.rule_id}
        if len(rule_ids) == 1 and all(issue.rule_id for issue in issues):
            return True
        code_fragments = {self._normalize_code_fragment(issue.existing_code) for issue in issues}
        if len(code_fragments) != 1 or "" in code_fragments:
            return False
        base_tokens = self._issue_word_set(issues[0].description)
        return all(self._jaccard(base_tokens, self._issue_word_set(issue.description)) >= 0.75 for issue in issues[1:])

    def _issue_word_set(self, value: str | None) -> set[str]:
        text = str(value or "").lower()
        tokens = set(re.findall(r"[a-z0-9_]+", text))
        for sequence in re.findall(r"[\u4e00-\u9fff]+", text):
            if len(sequence) == 1:
                tokens.add(sequence)
                continue
            tokens.update(sequence[index : index + 2] for index in range(len(sequence) - 1))
        return tokens

    def _jaccard(self, left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        return len(left & right) / len(left | right)

    def _estimate_target_tokens(self, target: ReviewTarget) -> int:
        diff_tokens = sum(max(1, len(line) // 4) for line in target.diff_lines)
        code_tokens = max(1, len(target.full_code) // 4)
        return diff_tokens + code_tokens

    def _source_hash(self, target: ReviewTarget) -> str:
        return review_target_hash(target)

    def _block_review_fingerprint(
        self,
        task: TaskModel,
        target: ReviewTarget,
        block_hash: str,
        background: FileReviewBackground,
    ) -> str:
        payload = {
            "pipeline_version": REVIEW_PIPELINE_VERSION,
            "project_id": task.project_id,
            "file_name": target.file_name,
            "language": target.language,
            "block_hash": block_hash,
            "background": background.content,
            "background_source": background.source,
            "model": self.settings.llm_model,
            "mock": self.llm_client.is_mock,
            "rules": review_rules_for(target.file_name, target.language, self.rule_settings),
            "relocation_enabled": self.settings.review_relocation_enabled,
            "filter_enabled": self.settings.review_filter_enabled,
            "evidence_required": self.settings.review_evidence_required,
            "semantic_index_enabled": self.settings.review_semantic_index_enabled,
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def _initialize_usage(self, task: TaskModel) -> None:
        blocks = [
            block
            for code_file in CodeFileModel.objects(task_id=str(task.id))
            for block in code_file.code_blocks
        ]
        persisted = {
            "prompt_tokens": sum(block.llm_prompt_tokens or 0 for block in blocks),
            "completion_tokens": sum(block.llm_completion_tokens or 0 for block in blocks),
            "total_tokens": sum(block.llm_total_tokens or 0 for block in blocks),
            "elapsed_ms": sum(block.llm_elapsed_ms or 0 for block in blocks),
            "call_count": sum(
                1 for block in blocks for trace in block.model_rounds if trace.model != "local"
            ),
        }
        self._initial_usage = {
            "prompt_tokens": max(task.llm_prompt_tokens or 0, persisted["prompt_tokens"]),
            "completion_tokens": max(task.llm_completion_tokens or 0, persisted["completion_tokens"]),
            "total_tokens": max(task.llm_total_tokens or 0, persisted["total_tokens"]),
            "elapsed_ms": max(task.llm_elapsed_ms or 0, persisted["elapsed_ms"]),
            "call_count": max(task.llm_call_count or 0, persisted["call_count"]),
            "process_time": task.process_time or 0,
            "tool_calls": dict(task.tool_call_summary or {}),
        }
        self._run_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "elapsed_ms": 0,
            "call_count": 0,
            "tool_calls": {},
        }

    def _accumulate_block_usage(
        self,
        model_rounds: list[ModelRoundTrace],
        tool_calls: list[ToolCallTrace],
    ) -> None:
        summary = self._summarize_model_round_tokens(model_rounds)
        with self._usage_lock:
            for field in ["prompt_tokens", "completion_tokens", "total_tokens", "elapsed_ms"]:
                self._run_usage[field] += summary[field]
            self._run_usage["call_count"] += sum(1 for trace in model_rounds if trace.model != "local")
            for trace in tool_calls:
                counts = self._run_usage["tool_calls"]
                counts[trace.tool_name] = counts.get(trace.tool_name, 0) + 1

    def _check_interrupted(self) -> None:
        if self.stop_event is not None and self.stop_event.is_set():
            raise ReviewInterruptedError("Review preempted by a higher-priority task")
        if not self.active_task_id:
            return
        current = TaskModel.objects(id=self.active_task_id).only(
            "trigger_revision",
            "interrupt_requested",
            "lease_token",
        ).first()
        if current is None:
            raise ReviewInterruptedError("Review task was deleted")
        if (current.trigger_revision or 0) != self.active_trigger_revision:
            raise ReviewInterruptedError("Review task was triggered again")
        if current.interrupt_requested:
            raise ReviewInterruptedError("Review interruption was requested")
        if self.lease_token and current.lease_token != self.lease_token:
            raise ReviewInterruptedError("Review task lease is no longer owned by this worker")

    def _mark_task_interrupted(self, task: TaskModel) -> None:
        current = TaskModel.objects(id=task.id).first()
        if current is None:
            return
        owns_lease = not self.lease_token or current.lease_token == self.lease_token
        same_revision = (current.trigger_revision or 0) == self.active_trigger_revision
        if owns_lease:
            current.lease_owner = ""
            current.lease_token = ""
            current.lease_expires_at = None
            current.heartbeat_time = None
        if same_revision:
            current.state = 0
            current.completion_status = "interrupted"
            current.interrupt_requested = False
        current.update_time = utc_now()
        current.save()
        CodeFileModel.objects(task_id=str(task.id), state=1).update(
            set__state=0,
            set__update_time=utc_now(),
        )

    def _target_hash(
        self,
        task: TaskModel,
        target: ReviewTarget,
        source_hash: str | None = None,
        background: FileReviewBackground | None = None,
    ) -> str:
        source_hash = source_hash or self._source_hash(target)
        background = background or self._file_background(task, target)
        fingerprint_payload = {
            "pipeline_version": REVIEW_PIPELINE_VERSION,
            "source_hash": source_hash,
            "background": background.content,
            "background_source": background.source,
            "model": self.settings.llm_model,
            "mock": self.llm_client.is_mock,
            "rules": review_rules_for(target.file_name, target.language, self.rule_settings),
            "relocation_enabled": self.settings.review_relocation_enabled,
            "filter_enabled": self.settings.review_filter_enabled,
            "evidence_required": self.settings.review_evidence_required,
            "evidence_similarity": self.settings.review_line_evidence_min_similarity,
            "filter_confidence": self.settings.review_filter_min_confidence,
            "related_files": [item.as_dict() for item in self._related_files(target)],
            "related_diff_max_chars": self.settings.review_related_diff_max_chars,
            "static_findings": [
                finding.fingerprint for finding in self.static_findings_by_file.get(target.file_name, [])
            ],
            "semantic_index_enabled": self.settings.review_semantic_index_enabled,
        }
        return hashlib.sha256(
            json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def _review_file(self, task: TaskModel, target: ReviewTarget, review_root: Path) -> CodeFileModel:
        self._check_interrupted()
        source_hash = review_target_hash(target)
        background = self._file_background(task, target)
        review_fingerprint = self._target_hash(task, target, source_hash, background)
        estimated_tokens = self._estimate_target_tokens(target)
        related_files = self._related_files(target)
        related_files_context = self._related_files_context(related_files)
        block_inputs = self.diff_service.split_code_blocks(target.diff_lines)
        code_file = CodeFileModel.objects(task_id=str(task.id), file_name=target.file_name).first()
        if code_file is None:
            code_file = CodeFileModel(
                task_id=str(task.id),
                project_id=task.project_id,
                review_version=task.review_version,
                copy_from_version=task.copy_from_version,
                task_type=task.task_type,
                file_name=target.file_name,
                code_blocks=[
                    CodeBlock(
                        block_id=index,
                        block_hash=code_block_hash(lines),
                        contents=list(lines),
                        review_state=0,
                    )
                    for index, lines in enumerate(block_inputs)
                ],
            )

        code_file.state = 1
        code_file.trigger_revision = self.active_trigger_revision
        code_file.source_hash = source_hash
        code_file.extra = {**(code_file.extra or {}), "status": "reviewing", "review_complete": False}
        code_file.update_time = utc_now()
        code_file.save()

        for block_index, block_lines in enumerate(block_inputs):
            self._check_interrupted()
            block_digest = code_block_hash(block_lines)
            block_fingerprint = self._block_review_fingerprint(
                task,
                target,
                block_digest,
                background,
            )
            existing_block = code_file.code_blocks[block_index]
            if (
                existing_block.block_hash == block_digest
                and existing_block.review_fingerprint == block_fingerprint
                and existing_block.main_task_completed
                and not existing_block.failure_message
            ):
                existing_block.block_id = block_index
                existing_block.review_state = 2
                continue

            existing_attempt_count = existing_block.review_attempt_count or 0
            existing_block.review_state = 1
            existing_block.review_attempt_count = existing_attempt_count + 1
            existing_block.update_time = utc_now()
            code_file.code_blocks[block_index] = existing_block
            code_file.save()

            block_started_at = time.monotonic()
            static_findings = self._static_findings_for_block(target.file_name, block_lines)
            static_analysis_context = self._static_analysis_context(static_findings)
            plan_result = self._run_plan_task(
                target.file_name,
                target.language,
                block_lines,
                target.full_code,
                related_files_context,
                static_analysis_context,
                background.content,
            )
            self._check_interrupted()
            main_failure_message = ""
            try:
                main_result = self._run_main_task(
                    target,
                    block_lines,
                    plan_result,
                    review_root,
                    related_files_context,
                    static_analysis_context,
                    background.content,
                )
                issues = main_result.issues
                main_failure_message = main_result.failure_message
            except ReviewInterruptedError:
                raise
            except Exception as exc:
                main_failure_message = f"main_task LLM failed: {type(exc).__name__}: {exc}"
                issues = []
                main_result = MainResult(issues=issues, failure_message=main_failure_message, completed=False)
            relocation_issues, relocation_rounds, relocation_failure = self._run_relocation_task(
                target,
                block_lines,
                issues,
                background.content,
            )
            corroborated_count = self._corroborate_static_findings(relocation_issues, static_findings)
            static_rounds = []
            if static_findings:
                static_rounds.append(
                    self._build_local_trace(
                        "static_analysis_corroboration",
                        1,
                        {"finding_count": len(static_findings)},
                        {"corroborated_issue_count": corroborated_count},
                    )
                )
            filtered_issues, filter_rounds, filter_failure = self._run_review_filter_task(
                target,
                block_lines,
                relocation_issues,
                background.content,
            )
            self._reindex_issues(filtered_issues)
            visible_issue_count = self._visible_issue_count(filtered_issues)
            model_rounds = (
                (plan_result.model_rounds or [])
                + (main_result.model_rounds or [])
                + relocation_rounds
                + static_rounds
                + filter_rounds
            )
            tool_call_traces = main_result.tool_call_traces or []
            token_summary = self._summarize_model_round_tokens(model_rounds)
            failure_message = "; ".join(
                message
                for message in [
                    plan_result.failure_message,
                    main_failure_message,
                    relocation_failure,
                    filter_failure,
                ]
                if message
            )
            block = CodeBlock(
                block_id=block_index,
                block_hash=block_digest,
                review_fingerprint=block_fingerprint,
                contents=block_lines,
                comment=plan_result.comment,
                plan_change_summary=plan_result.change_summary,
                plan_risk_level=plan_result.risk_level,
                plan_checkpoints=plan_result.checkpoints or [],
                related_files=[item.as_dict() for item in related_files],
                static_findings=[finding.as_dict() for finding in static_findings],
                logic_score=plan_result.logic_score,
                performance_score=plan_result.performance_score,
                security_score=plan_result.security_score,
                readable_score=plan_result.readable_score,
                code_style_score=plan_result.code_style_score,
                comment_line_number=visible_issue_count,
                issues=filtered_issues,
                process_time=int((time.monotonic() - block_started_at) * 1000),
                llm_prompt_tokens=token_summary["prompt_tokens"],
                llm_completion_tokens=token_summary["completion_tokens"],
                llm_total_tokens=token_summary["total_tokens"],
                llm_reasoning_tokens=token_summary["reasoning_tokens"],
                llm_cached_tokens=token_summary["cached_tokens"],
                llm_elapsed_ms=token_summary["elapsed_ms"],
                memory_compression_count=main_result.memory_compression_count,
                main_task_completed=main_result.completed,
                main_task_completion_mode=main_result.completion_mode,
                main_task_round_count=main_result.round_count,
                model_rounds=model_rounds,
                tool_calls=tool_call_traces,
                failure_message=failure_message,
                review_state=2 if main_result.completed and not failure_message else 3,
                review_attempt_count=existing_attempt_count + 1,
                update_time=utc_now(),
            )
            self._check_interrupted()
            code_file.code_blocks[block_index] = block
            code_file.comment_line_number = sum(
                self._visible_issue_count(item.issues) for item in code_file.code_blocks
            )
            code_file.extra = {
                **(code_file.extra or {}),
                "status": "reviewing",
                "completed_block_num": sum(
                    1 for item in code_file.code_blocks if item.main_task_completed and not item.failure_message
                ),
            }
            code_file.update_time = utc_now()
            code_file.save()
            self._accumulate_block_usage(model_rounds, tool_call_traces)

        code_blocks = list(code_file.code_blocks)
        self._merge_duplicate_file_issues(code_blocks)
        scores = self._average_block_scores(code_blocks)
        review_complete = bool(code_blocks) and all(
            block.main_task_completed and not block.failure_message for block in code_blocks
        )
        code_file.project_id = task.project_id
        code_file.review_version = task.review_version
        code_file.copy_from_version = task.copy_from_version
        code_file.task_type = task.task_type
        code_file.file_name = target.file_name
        code_file.state = 2 if review_complete else 3
        code_file.source_hash = source_hash
        code_file.review_fingerprint = review_fingerprint
        code_file.trigger_revision = self.active_trigger_revision
        code_file.background = background.content
        code_file.background_source = background.source
        code_file.code_blocks = code_blocks
        code_file.code_line_num = target.code_line_num
        code_file.add_code_line_num = target.add_code_line_num
        code_file.comment_line_number = sum(self._visible_issue_count(block.issues) for block in code_blocks)
        code_file.extra = {
                **(code_file.extra or {}),
                "status": "reviewed" if review_complete else "partial",
                "review_complete": review_complete,
                "failed_block_num": sum(1 for block in code_blocks if not block.main_task_completed),
                "source_hash": source_hash,
                "review_fingerprint": review_fingerprint,
                "estimated_tokens": estimated_tokens,
                "language": target.language,
                "change_type": target.change_type,
                "background_source": background.source,
                "old_file_name": target.old_file_name,
                "related_files": [item.as_dict() for item in related_files],
                "static_finding_count": sum(len(block.static_findings) for block in code_blocks),
                "static_corroborated_issue_count": sum(
                    1 for block in code_blocks for issue in block.issues if issue.static_corroborated
                ),
            }
        for field_name, value in scores.items():
            setattr(code_file, field_name, value)
        code_file.update_time = utc_now()
        self._check_interrupted()
        code_file.save()
        return code_file

    def _file_background(self, task: TaskModel, target: ReviewTarget) -> FileReviewBackground:
        cache_key = f"{task.project_id}\0{task.review_version}\0{target.file_name}"
        cached = self.file_backgrounds.get(cache_key)
        if cached is not None:
            return cached
        with self._background_lock:
            cached = self.file_backgrounds.get(cache_key)
            if cached is not None:
                return cached
            background = self.background_provider.get_background(
                project_id=task.project_id,
                review_version=task.review_version,
                file_name=target.file_name,
            )
            self.file_backgrounds[cache_key] = background
            return background

    def _run_plan_task(
        self,
        file_name: str,
        language: str,
        diff_lines: list[str],
        full_code: str,
        related_files_context: str = "",
        static_analysis_context: str = "",
        background: str = "",
    ) -> PlanResult:
        messages = build_plan_messages(
            file_name=file_name,
            language=language,
            diff_lines=diff_lines,
            full_code=full_code,
            change_files_context=self._change_files_context(file_name),
            related_files_context=related_files_context,
            static_analysis_context=static_analysis_context,
            background=background,
            settings=self.rule_settings,
        )
        if self.llm_client.is_mock:
            response = self._mock_plan_response(diff_lines)
            model_rounds = [
                self._build_local_trace(
                    "plan_task",
                    1,
                    {"file_name": file_name, "mode": "local_mock"},
                    response,
                )
            ]
            failure_message = ""
        else:
            response, model_rounds, failure_message = self._run_json_stage(
                stage="plan_task",
                messages=messages,
                required_list_key="",
                repair_prompt=(
                    "上一轮 plan_task 不是合法 JSON。请只返回约束 JSON，必须包含 comment、change_summary、"
                    "risk_level、checkpoints 和五个评分字段；checkpoints 必须是数组。"
                ),
            )
        if not response:
            response = {
                "comment": "plan_task 未生成有效结构，main_task 将独立完成完整审核。",
                "change_summary": "",
                "risk_level": "medium",
                "checkpoints": [],
            }
        checkpoints = response.get("checkpoints") if isinstance(response.get("checkpoints"), list) else []
        checkpoints = [item for item in checkpoints if isinstance(item, dict)][:10]
        risk_level = str(response.get("risk_level") or "medium").lower()
        if risk_level not in {"high", "medium", "low"}:
            risk_level = "medium"
        return PlanResult(
            comment=str(response.get("comment") or "代码块已完成初步分析。"),
            logic_score=self._score(response.get("logic_score"), 80),
            performance_score=self._score(response.get("performance_score"), 80),
            security_score=self._score(response.get("security_score"), 80),
            readable_score=self._score(response.get("readable_score"), 80),
            code_style_score=self._score(response.get("code_style_score"), 80),
            change_summary=str(response.get("change_summary") or ""),
            risk_level=risk_level,
            checkpoints=checkpoints,
            failure_message=failure_message,
            model_rounds=model_rounds,
        )

    def _run_json_stage(
        self,
        stage: str,
        messages: list[dict[str, Any]],
        required_list_key: str,
        repair_prompt: str,
    ) -> tuple[dict[str, Any], list[ModelRoundTrace], str]:
        working_messages = list(messages)
        model_rounds: list[ModelRoundTrace] = []
        last_error = ""
        max_attempts = max(1, self.settings.llm_json_retry_times + 1)
        for attempt in range(1, max_attempts + 1):
            request_messages = list(working_messages)
            assistant_message: dict[str, Any] | None = None
            try:
                assistant_message = self.llm_client.chat(messages=working_messages)
                trace = self._build_model_round_trace(stage, attempt, request_messages, assistant_message)
                model_rounds.append(trace)
                response = self.llm_client._extract_json(assistant_message.get("content") or "")
                if not isinstance(response, dict):
                    raise ValueError("response must be a JSON object")
                if required_list_key and not isinstance(response.get(required_list_key), list):
                    raise ValueError(f"JSON field '{required_list_key}' must be an array")
                return response, model_rounds, ""
            except Exception as exc:
                last_error = f"{stage} attempt {attempt} failed: {type(exc).__name__}: {exc}"
                if model_rounds and model_rounds[-1].stage == stage and model_rounds[-1].round_index == attempt:
                    model_rounds[-1].error_message = last_error
                else:
                    model_rounds.append(
                        self._build_model_round_trace(stage, attempt, request_messages, assistant_message, last_error)
                    )
                if attempt >= max_attempts:
                    break
                if assistant_message:
                    working_messages.append(assistant_message)
                working_messages.append({"role": "user", "content": repair_prompt})
        return {}, model_rounds, last_error

    def _change_files_context(self, current_file_name: str) -> str:
        limit = max(1, self.settings.review_change_manifest_limit)
        lines: list[str] = []
        for changed_file in self.review_context.changed_files:
            if changed_file.file_name == current_file_name:
                continue
            if changed_file.old_file_name:
                lines.append(f"{changed_file.change_type} {changed_file.old_file_name} -> {changed_file.file_name}")
            else:
                lines.append(f"{changed_file.change_type} {changed_file.file_name}")
            if len(lines) >= limit:
                lines.append("... change manifest truncated ...")
                break
        return "\n".join(lines) or "（无其他变更文件）"

    def _related_files(self, target: ReviewTarget) -> list[RelatedFile]:
        if not self.settings.review_related_files_enabled:
            return []
        return self.related_file_resolver.resolve(
            current=target,
            collection=self.review_context,
            limit=max(0, self.settings.review_related_file_limit),
        )

    def _related_files_context(self, related_files: list[RelatedFile]) -> str:
        if not related_files:
            return ""
        budget = max(0, self.settings.review_related_diff_max_chars)
        sections: list[str] = []
        consumed = 0
        for related in related_files:
            header = (
                f"### {related.file_name} [{related.change_type}] score={related.score} "
                f"reasons={','.join(related.reasons)}\n"
            )
            diff_text = "\n".join(self.review_context.diff_map.get(related.file_name) or [])
            section = header
            if budget > consumed and diff_text:
                remaining = budget - consumed
                excerpt = diff_text[:remaining]
                section += excerpt
                consumed += len(excerpt)
                if len(excerpt) < len(diff_text):
                    section += "\n... related diff truncated ..."
            else:
                section += "（diff 未内联，可通过 file_read_diff 按需读取）"
            sections.append(section)
        return "\n\n".join(sections)

    def _static_findings_for_block(self, file_name: str, diff_lines: list[str]) -> list[StaticFinding]:
        changed_lines = self.evidence_locator.reviewable_line_numbers(diff_lines)
        if not changed_lines:
            return []
        return [
            finding
            for finding in self.static_findings_by_file.get(file_name, [])
            if any(finding.start_line <= line_number <= finding.end_line for line_number in changed_lines)
        ]

    def _static_analysis_context(self, findings: list[StaticFinding]) -> str:
        if not findings:
            return ""
        return json.dumps(
            {"findings": [finding.as_dict() for finding in findings]},
            ensure_ascii=False,
            indent=2,
        )

    def _corroborate_static_findings(self, issues: list[Issue], findings: list[StaticFinding]) -> int:
        corroborated = 0
        for issue in issues:
            parsed_lines = self._parse_line_numbers(issue.issue_line_numbers)
            issue_start = issue.evidence_start_line or (min(parsed_lines) if parsed_lines else 0)
            issue_end = issue.evidence_end_line or (max(parsed_lines) if parsed_lines else issue_start)
            if issue_start <= 0:
                continue
            supporting = [
                finding
                for finding in findings
                if finding.start_line <= issue_end
                and finding.end_line >= issue_start
                and self._static_finding_supports_issue(finding, issue, issue_start, issue_end)
            ]
            if not supporting:
                continue
            issue.static_corroborated = True
            issue.static_analysis_sources = sorted({finding.analyzer for finding in supporting})
            issue.static_analysis_rule_ids = sorted({finding.rule_id for finding in supporting if finding.rule_id})
            issue.static_analysis_fingerprints = sorted({finding.fingerprint for finding in supporting})
            issue.confidence_level = max(issue.confidence_level or 0.0, 0.95)
            corroborated += 1
        return corroborated

    def _static_finding_supports_issue(
        self,
        finding: StaticFinding,
        issue: Issue,
        issue_start: int,
        issue_end: int,
    ) -> bool:
        if issue.rule_id and finding.rule_id and issue.rule_id.lower() == finding.rule_id.lower():
            return True
        finding_tokens = self._issue_word_set(f"{finding.rule_id} {finding.message}")
        issue_tokens = self._issue_word_set(f"{issue.type} {issue.description} {issue.evidence}")
        if self._jaccard(finding_tokens, issue_tokens) >= 0.1:
            return True
        category_keywords = {
            "security": {"security", "cwe", "injection", "xss", "taint", "overflow", "bounds", "secret", "traversal"},
            "logic": {"bug", "null", "overflow", "uninitialized", "deadlock", "leak", "resource", "incorrect"},
            "performance": {"performance", "complexity", "allocation", "quadratic", "slow"},
            "readability": {"readability", "maintainability", "confusing"},
            "code_style": {"style", "convention", "format"},
        }
        if finding_tokens & category_keywords.get(issue.type.lower(), set()):
            return True
        return finding.level == "error" and finding.start_line == issue_start and finding.end_line == issue_end

    def _resolve_rule_settings(self, review_root: Path) -> Settings:
        if self.settings.review_rules_path:
            return self.settings
        project_rule = review_root.resolve() / ".opencodereview" / "rule.json"
        if not project_rule.is_file():
            return self.settings
        return self.settings.model_copy(update={"review_rules_path": str(project_rule)})

    def _run_main_task(
        self,
        target: ReviewTarget,
        diff_lines: list[str],
        plan_result: PlanResult,
        review_root: Path,
        related_files_context: str = "",
        static_analysis_context: str = "",
        background: str = "",
    ) -> MainResult:
        if self.llm_client.is_mock:
            comments = self._mock_main_comments(diff_lines, target.language)
            return MainResult(
                issues=self._comments_to_issues(comments),
                completed=True,
                completion_mode="mock",
                round_count=0,
            )

        plan_guidance = plan_result.guidance_json()
        messages: list[dict[str, Any]] = build_main_messages(
            file_name=target.file_name,
            language=target.language,
            diff_lines=diff_lines,
            full_code=target.full_code,
            plan_guidance=plan_guidance,
            change_files_context=self._change_files_context(target.file_name),
            related_files_context=related_files_context,
            static_analysis_context=static_analysis_context,
            background=background,
            settings=self.rule_settings,
        )
        runner = ReviewToolRunner(
            review_root,
            self.settings,
            current_file_name=target.file_name,
            current_diff_lines=diff_lines,
            diff_map=self.review_context.diff_map,
            semantic_index=self.semantic_index,
            project_exclude_paths=self.project_exclude_paths,
        )
        model_rounds: list[ModelRoundTrace] = []
        tool_call_traces: list[ToolCallTrace] = []
        memory_compression_count = 0
        consecutive_empty_rounds = 0
        completed = False
        completion_mode = ""
        round_count = 0
        hard_limit = self._context_hard_limit()
        max_tool_rounds = (
            self.settings.full_scan_max_tool_rounds
            if target.change_type == "FULL"
            else self.settings.llm_max_tool_rounds
        )
        max_tool_rounds = max(1, max_tool_rounds)
        main_started_at = time.monotonic()

        initial_tokens = self._estimate_messages_tokens(messages)
        if hard_limit > 0 and initial_tokens >= hard_limit:
            failure = f"main_task initial context {initial_tokens} tokens exceeds hard limit {hard_limit}"
            return MainResult(
                issues=[],
                failure_message=failure,
                model_rounds=[
                    self._build_local_trace(
                        "main_task_preflight",
                        0,
                        {"estimated_tokens": initial_tokens, "hard_limit": hard_limit},
                        {"completed": False},
                    )
                ],
                completed=False,
                completion_mode="context_limit",
                round_count=0,
            )

        for round_index in range(1, max_tool_rounds + 1):
            self._check_interrupted()
            round_count = round_index
            if time.monotonic() - main_started_at >= max(1, self.settings.llm_file_timeout_seconds):
                runner.failure_messages.append(
                    f"main_task exceeded file timeout ({self.settings.llm_file_timeout_seconds}s)"
                )
                completion_mode = "file_timeout"
                break
            compression_trace = self._maybe_compress_main_messages(
                messages=messages,
                target=target,
                diff_lines=diff_lines,
                plan_comment=plan_guidance,
                runner=runner,
                round_index=round_index,
            )
            if compression_trace:
                memory_compression_count += 1
                model_rounds.append(compression_trace)
            current_tokens = self._estimate_messages_tokens(messages)
            if hard_limit > 0 and current_tokens >= hard_limit:
                runner.failure_messages.append(
                    f"main_task context remained above hard limit after compression: {current_tokens} >= {hard_limit}"
                )
                completion_mode = "context_limit"
                break
            request_messages = list(messages)
            recovered_request_error = ""
            try:
                assistant_message = self.llm_client.chat(messages=messages, tools=MAIN_TOOL_DEFINITIONS)
            except Exception as tool_error:
                recovered_request_error = (
                    f"main_task tool-call request failed: {type(tool_error).__name__}: {tool_error}"
                )
                messages.append(
                    {
                        "role": "user",
                        "content": "如果工具调用不可用，请直接输出 JSON，格式为 {\"issues\":[...]}。",
                    }
                )
                request_messages = list(messages)
                try:
                    assistant_message = self.llm_client.chat(messages=messages)
                except Exception:
                    raise tool_error
            model_round = self._build_model_round_trace("main_task", round_index, request_messages, assistant_message)
            model_round.error_message = recovered_request_error
            model_rounds.append(model_round)
            messages.append(assistant_message)
            tool_calls = assistant_message.get("tool_calls") or []
            if not tool_calls:
                if self._collect_json_comments(assistant_message.get("content"), runner):
                    completed = True
                    completion_mode = "json_fallback"
                    break
                consecutive_empty_rounds += 1
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "上一轮没有成功调用任何工具，且不是合法的 JSON fallback。"
                            "请调用上下文工具、使用 code_comment(comments=[...]) 提交确认问题，"
                            "并最终调用 task_done(state=\"DONE\")；若工具不可用，只输出 {\"issues\":[]} 或约束 issues JSON。"
                        ),
                    }
                )
                if consecutive_empty_rounds >= max(1, self.settings.llm_max_consecutive_empty_rounds):
                    runner.failure_messages.append(
                        f"main_task stopped after {consecutive_empty_rounds} consecutive no-tool/invalid-JSON rounds"
                    )
                    completion_mode = "empty_round_limit"
                    break
                continue

            valid_result_count = 0
            for tool_call in tool_calls:
                function = tool_call.get("function", {})
                tool_name = str(function.get("name") or "")
                raw_arguments = function.get("arguments") or "{}"
                tool_started_at = time.monotonic()
                try:
                    arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
                    if not isinstance(arguments, dict):
                        raise ValueError("tool arguments must be a JSON object")
                    result = runner.run(tool_name, arguments)
                except (json.JSONDecodeError, TypeError, ValueError) as exc:
                    arguments = {"_raw": raw_arguments}
                    result = {"error": f"Invalid arguments for {tool_name}: {type(exc).__name__}: {exc}"}
                tool_call_traces.append(
                    self._build_tool_call_trace(
                        round_index=round_index,
                        tool_call=tool_call,
                        tool_name=tool_name,
                        arguments=arguments,
                        result=result,
                        elapsed_ms=int((time.monotonic() - tool_started_at) * 1000),
                    )
                )
                messages.append(runner.tool_result_message(tool_call.get("id", ""), result))
                if not result.get("error") and result.get("accepted") is not False:
                    valid_result_count += 1
            if runner.done:
                completed = runner.done_state == "DONE"
                completion_mode = "task_done" if completed else "task_failed"
                break
            if valid_result_count == 0:
                consecutive_empty_rounds += 1
                if consecutive_empty_rounds >= max(1, self.settings.llm_max_consecutive_empty_rounds):
                    runner.failure_messages.append(
                        f"main_task stopped after {consecutive_empty_rounds} rounds without a valid tool result"
                    )
                    completion_mode = "empty_round_limit"
                    break
            else:
                consecutive_empty_rounds = 0

        if not completed and not completion_mode:
            completion_mode = "max_rounds"
            runner.failure_messages.append(
                f"main_task reached max tool rounds ({max_tool_rounds}) without task_done"
            )

        return MainResult(
            issues=self._comments_to_issues(runner.comments),
            failure_message="; ".join(runner.failure_messages),
            model_rounds=model_rounds,
            tool_call_traces=tool_call_traces,
            memory_compression_count=memory_compression_count,
            completed=completed,
            completion_mode=completion_mode,
            round_count=round_count,
        )

    def _run_relocation_task(
        self,
        target: ReviewTarget,
        diff_lines: list[str],
        issues: list[Issue],
        background: str = "",
    ) -> tuple[list[Issue], list[ModelRoundTrace], str]:
        if not issues:
            return issues, [], ""
        if not self.settings.review_relocation_enabled:
            for issue in issues:
                issue.original_issue_line_numbers = issue.original_issue_line_numbers or str(issue.issue_line_numbers or "")
                issue.relocation_status = "skipped"
            return issues, [], ""

        local_started_at = time.monotonic()
        self._relocate_issues_locally(target, diff_lines, issues)
        model_rounds: list[ModelRoundTrace] = [
            self._build_local_trace(
                "re_location_task",
                1,
                {"issue_count": len(issues), "mode": "deterministic_first"},
                {"relocated": [self._issue_payload(issue) for issue in issues]},
                int((time.monotonic() - local_started_at) * 1000),
            )
        ]
        unresolved = [issue for issue in issues if issue.relocation_status == "failed"]
        if self.llm_client.is_mock or not unresolved:
            return issues, model_rounds, ""

        messages = build_relocation_messages(
            file_name=target.file_name,
            language=target.language,
            diff_lines=diff_lines,
            full_code=target.full_code,
            issues=[self._issue_payload(issue) for issue in unresolved],
            background=background,
            settings=self.rule_settings,
        )
        response, llm_rounds, failure_message = self._run_json_stage(
            stage="re_location_task",
            messages=messages,
            required_list_key="issues",
            repair_prompt=(
                "上一轮重定位输出不是合法 JSON。请只输出 {\"issues\":[...]}，每项包含 issue_id、"
                "existing_code、issue_line_numbers、relocation_status 和 relocation_description。"
            ),
        )
        model_rounds.extend(llm_rounds)
        if response:
            self._apply_relocation_response(unresolved, response)
            for issue in unresolved:
                issue.relocation_status = ""
            self._relocate_issues_locally(target, diff_lines, unresolved)
        return issues, model_rounds, failure_message

    def _run_review_filter_task(
        self,
        target: ReviewTarget,
        diff_lines: list[str],
        issues: list[Issue],
        background: str = "",
    ) -> tuple[list[Issue], list[ModelRoundTrace], str]:
        if not issues:
            return issues, [], ""
        if not self.settings.review_filter_enabled:
            for issue in issues:
                issue.filter_status = "skipped"
            return issues, [], ""

        local_started_at = time.monotonic()
        self._filter_issues_locally(diff_lines, issues)
        model_rounds: list[ModelRoundTrace] = [
            self._build_local_trace(
                "review_filter_task",
                1,
                {"issue_count": len(issues), "mode": "deterministic_validity_gate"},
                {"decisions": [self._issue_filter_payload(issue) for issue in issues]},
                int((time.monotonic() - local_started_at) * 1000),
            )
        ]
        candidates = [issue for issue in issues if self._is_reportable_issue(issue)]
        if self.llm_client.is_mock or not candidates:
            return issues, model_rounds, ""

        messages = build_review_filter_messages(
            file_name=target.file_name,
            language=target.language,
            diff_lines=diff_lines,
            full_code=target.full_code,
            issues=[self._issue_payload(issue) for issue in candidates],
            background=background,
            settings=self.rule_settings,
        )
        response, llm_rounds, failure_message = self._run_json_stage(
            stage="review_filter_task",
            messages=messages,
            required_list_key="decisions",
            repair_prompt=(
                "上一轮过滤输出不是合法 JSON。请只输出 {\"decisions\":[...]}。"
                "只有 diff 中存在直接反证时才能 filtered，否则必须 kept。"
            ),
        )
        model_rounds.extend(llm_rounds)
        if response:
            self._apply_filter_response(candidates, response)
        self._filter_issues_locally(diff_lines, issues, preserve_existing_filtered=True)
        return issues, model_rounds, failure_message

    def _maybe_compress_main_messages(
        self,
        messages: list[dict[str, Any]],
        target: ReviewTarget,
        diff_lines: list[str],
        plan_comment: str,
        runner: ReviewToolRunner,
        round_index: int,
    ) -> ModelRoundTrace | None:
        compress_rounds = max(0, self.settings.llm_context_compress_rounds)
        estimated_tokens = self._estimate_messages_tokens(messages)
        configured_threshold = max(0, self.settings.llm_context_compress_token_threshold)
        automatic_threshold = int(
            max(1, self.settings.llm_max_context_tokens)
            * min(0.95, max(0.10, self.settings.llm_context_soft_ratio))
        )
        token_threshold = configured_threshold or automatic_threshold
        token_triggered = token_threshold > 0 and estimated_tokens >= token_threshold
        round_triggered = (
            compress_rounds > 0
            and round_index > compress_rounds
            and (round_index - 1) % compress_rounds == 0
        )
        if not token_triggered and not round_triggered:
            return None
        if len(messages) <= 2:
            return None

        started_at = time.monotonic()
        old_message_count = len(messages)
        active_start = self._compression_active_start(messages)
        if active_start <= 2:
            return None
        local_summary = self._build_main_context_summary(
            messages=messages[2:active_start],
            target=target,
            diff_lines=diff_lines,
            plan_comment=plan_comment,
            runner=runner,
            round_index=round_index,
        )
        trigger_summary = {
            "message_count_before": old_message_count,
            "estimated_tokens_before": estimated_tokens,
            "token_threshold": token_threshold,
            "trigger": "token" if token_triggered else "round",
        }
        summary_content = local_summary
        compression_trace: ModelRoundTrace | None = None
        if self.settings.llm_context_compression_llm_enabled and not self.llm_client.is_mock:
            compression_messages = build_memory_compression_messages(
                self._compression_context(messages[2:active_start], local_summary)
            )
            assistant_message: dict[str, Any] | None = None
            try:
                assistant_message = self.llm_client.chat(messages=compression_messages)
                candidate_summary = str(assistant_message.get("content") or "").strip()
                if not candidate_summary:
                    raise ValueError("memory compression returned an empty summary")
                summary_content = self._truncate(
                    candidate_summary,
                    max(500, self.settings.llm_context_summary_max_chars),
                )
                compression_trace = self._build_model_round_trace(
                    "memory_compression",
                    round_index,
                    compression_messages,
                    assistant_message,
                )
                compression_trace.request_summary = (
                    json.dumps(trigger_summary, ensure_ascii=False)
                    + "\n"
                    + compression_trace.request_summary
                )
            except Exception as exc:
                failure = f"memory compression LLM failed: {type(exc).__name__}: {exc}"
                compression_trace = self._build_local_trace(
                    "memory_compression",
                    round_index,
                    trigger_summary,
                    {"fallback": "deterministic", "summary_chars": len(local_summary)},
                    int((time.monotonic() - started_at) * 1000),
                )
                compression_trace.error_message = failure
        frozen_system = dict(messages[0])
        frozen_user = dict(messages[1])
        original_user_content = self._strip_previous_review_summary(str(frozen_user.get("content") or ""))
        frozen_user["content"] = (
            original_user_content
            + "\n\n<previous_review_summary>\n"
            + summary_content
            + "\n</previous_review_summary>"
        )
        messages[:] = [frozen_system, frozen_user, *messages[active_start:]]
        if compression_trace is not None:
            return compression_trace
        return self._build_local_trace(
            "memory_compression",
            round_index,
            trigger_summary,
            {"message_count_after": len(messages), "summary_chars": len(summary_content)},
            int((time.monotonic() - started_at) * 1000),
        )

    def _compression_context(self, messages: list[dict[str, Any]], local_summary: str) -> str:
        history: list[dict[str, Any]] = []
        for message in messages:
            item = {
                "role": message.get("role"),
                "content": self._truncate(str(message.get("content") or ""), 2500),
            }
            if message.get("tool_calls"):
                item["tool_calls"] = message.get("tool_calls")
            history.append(item)
        payload = {
            "deterministic_state": local_summary,
            "conversation_history": history,
        }
        maximum = max(5000, self.settings.llm_context_summary_max_chars * 10)
        return self._truncate(json.dumps(payload, ensure_ascii=False, default=str), maximum)

    def _compression_active_start(self, messages: list[dict[str, Any]]) -> int:
        keep = max(2, self.settings.llm_context_keep_recent_messages)
        start = max(2, len(messages) - keep)
        while start > 2 and messages[start].get("role") == "tool":
            start -= 1
        if start <= 2 and len(messages) > 4:
            start = 3
            while start < len(messages) and messages[start].get("role") == "tool":
                start += 1
        return min(start, len(messages))

    def _strip_previous_review_summary(self, content: str) -> str:
        return re.sub(
            r"\n*<previous_review_summary>.*?</previous_review_summary>\s*$",
            "",
            content,
            flags=re.DOTALL,
        ).rstrip()

    def _context_hard_limit(self) -> int:
        max_tokens = max(0, self.settings.llm_max_context_tokens)
        if max_tokens <= 0:
            return 0
        ratio = min(0.98, max(0.20, self.settings.llm_context_hard_ratio))
        return int(max_tokens * ratio)

    def _estimate_messages_tokens(self, messages: list[dict[str, Any]]) -> int:
        total_chars = 0
        for message in messages:
            total_chars += len(str(message.get("content") or ""))
            tool_calls = message.get("tool_calls") or []
            if tool_calls:
                total_chars += len(json.dumps(tool_calls, ensure_ascii=False, default=str))
        return max(1, total_chars // 4)

    def _build_main_context_summary(
        self,
        messages: list[dict[str, Any]],
        target: ReviewTarget,
        diff_lines: list[str],
        plan_comment: str,
        runner: ReviewToolRunner,
        round_index: int,
    ) -> str:
        added_lines = self._iter_added_with_line_number(diff_lines)
        added_line_summary = [
            {"line_number": line_number, "code": self._truncate(code, 160)}
            for line_number, code in added_lines
        ]
        comments_summary = [self._truncate(json.dumps(comment, ensure_ascii=False), 500) for comment in runner.comments]
        tool_summary = self._last_tool_observations(messages)
        summary = {
            "stage": "memory_compression",
            "round_index": round_index,
            "file_name": target.file_name,
            "language": target.language,
            "plan_comment": self._truncate(plan_comment, 500),
            "changed_lines": added_line_summary,
            "submitted_comments": comments_summary,
            "recent_tool_observations": tool_summary,
            "instruction": (
                "Continue main_task from this compressed state. Use file_read_diff/read_file/code_search "
                "when exact context is needed, then finish with code_comment or task_done."
            ),
        }
        content = json.dumps(summary, ensure_ascii=False, indent=2)
        max_chars = max(500, self.settings.llm_context_summary_max_chars)
        return self._truncate(content, max_chars)

    def _last_tool_observations(self, messages: list[dict[str, Any]]) -> list[str]:
        keep = max(1, self.settings.llm_context_keep_recent_messages)
        observations: list[str] = []
        for message in reversed(messages):
            if message.get("role") != "tool":
                continue
            observations.append(self._truncate(str(message.get("content") or ""), 500))
            if len(observations) >= keep:
                break
        return list(reversed(observations))

    def _apply_relocation_response(self, issues: list[Issue], response: dict[str, Any]) -> None:
        response_issues = response.get("issues") if isinstance(response, dict) else None
        if not isinstance(response_issues, list):
            return
        issue_by_id = {issue.issue_id: issue for issue in issues}
        for item in response_issues:
            if not isinstance(item, dict):
                continue
            issue = issue_by_id.get(self._safe_int(item.get("issue_id")))
            if not issue:
                continue
            issue.original_issue_line_numbers = issue.original_issue_line_numbers or str(issue.issue_line_numbers or "")
            issue.issue_line_numbers = str(item.get("issue_line_numbers") or issue.issue_line_numbers or "")
            if item.get("existing_code"):
                issue.existing_code = str(item.get("existing_code"))
            issue.relocation_status = str(item.get("relocation_status") or "unchanged")
            issue.relocation_description = str(item.get("relocation_description") or "")
            issue.evidence_match_status = str(item.get("evidence_match_status") or issue.evidence_match_status or "")
            if item.get("evidence_match_score") is not None:
                issue.evidence_match_score = self._confidence(item.get("evidence_match_score"), issue.evidence_match_score)
            if item.get("confidence_level") is not None:
                issue.confidence_level = self._confidence(item.get("confidence_level"), issue.confidence_level)
            issue.re_review_status = 0 if issue.relocation_status != "failed" else 1
            issue.re_review_description = issue.relocation_description

    def _apply_filter_response(self, issues: list[Issue], response: dict[str, Any]) -> None:
        decisions = response.get("decisions") if isinstance(response, dict) else None
        if not isinstance(decisions, list):
            return
        issue_by_id = {issue.issue_id: issue for issue in issues}
        for item in decisions:
            if not isinstance(item, dict):
                continue
            issue = issue_by_id.get(self._safe_int(item.get("issue_id")))
            if not issue:
                continue
            requested_status = str(item.get("filter_status") or "kept").lower()
            requested_filtered = requested_status == "filtered"
            counter_evidence = str(item.get("counter_evidence") or "").strip()
            if requested_filtered and not counter_evidence:
                issue.filter_status = "kept"
                issue.filter_reason = "过滤结论缺少 diff 直接反证，按保守原则保留。"
            else:
                issue.filter_status = requested_status if requested_status in {"kept", "filtered"} else "kept"
                issue.filter_reason = str(item.get("filter_reason") or "")
            issue.filter_counter_evidence = counter_evidence
            issue.evidence_match_status = str(item.get("evidence_match_status") or issue.evidence_match_status or "")
            if item.get("evidence_match_score") is not None:
                issue.evidence_match_score = self._confidence(item.get("evidence_match_score"), issue.evidence_match_score)
            if item.get("confidence_level") is not None:
                issue.confidence_level = self._confidence(item.get("confidence_level"), issue.confidence_level)
            issue.re_review_status = 0 if self._is_reportable_issue(issue) else 1
            issue.re_review_description = issue.filter_reason

    def _relocate_issues_locally(
        self,
        target: ReviewTarget,
        diff_lines: list[str],
        issues: list[Issue],
        only_unresolved: bool = False,
    ) -> None:
        for issue in issues:
            if only_unresolved and issue.relocation_status in {"unchanged", "relocated"}:
                continue
            original_lines = str(issue.issue_line_numbers or "")
            issue.original_issue_line_numbers = issue.original_issue_line_numbers or original_lines
            parsed_lines = self._parse_line_numbers(original_lines)
            match = self.evidence_locator.locate(
                existing_code=issue.existing_code,
                full_code=target.full_code,
                diff_lines=diff_lines,
                claimed_line_numbers=parsed_lines,
            )
            self._apply_evidence_match(issue, match)
            has_claimed_anchor = any(match.start_line <= line <= match.end_line for line in parsed_lines) if match.found else False
            if match.found and match.changed_line_overlap and (not match.ambiguous or has_claimed_anchor):
                expected_lines = set(range(match.start_line, match.end_line + 1))
                issue.issue_line_numbers = match.line_numbers
                if expected_lines.intersection(parsed_lines):
                    issue.relocation_status = "unchanged"
                    issue.relocation_description = "existing_code 已连续匹配到本次变更后的代码范围。"
                else:
                    issue.relocation_status = "relocated"
                    issue.relocation_description = (
                        f"根据 existing_code 连续证据将行号从 {original_lines or '空'} 修正为 {match.line_numbers}。"
                    )
                issue.re_review_status = 0
                issue.re_review_description = issue.relocation_description
                continue

            candidate_line = None
            if self.settings.review_allow_heuristic_relocation and not issue.existing_code.strip():
                candidate_line = self._find_relocation_candidate_line(issue, diff_lines)
            if candidate_line is not None:
                issue.issue_line_numbers = str(candidate_line)
                issue.relocation_status = "relocated"
                issue.relocation_description = f"启发式规则将行号从 {original_lines or '空'} 修正为 {candidate_line}。"
                issue.re_review_status = 0
                issue.re_review_description = issue.relocation_description
                continue

            issue.relocation_status = "failed"
            if match.found and not match.changed_line_overlap:
                issue.relocation_description = "existing_code 只匹配到未变更代码，不能作为本次增量审核锚点。"
            elif match.ambiguous:
                issue.relocation_description = "existing_code 在变更代码中存在多个匹配且原行号无法消歧。"
            else:
                issue.relocation_description = "无法在本次变更行中稳定连续匹配 existing_code。"
            issue.re_review_status = 1
            issue.re_review_description = issue.relocation_description

    def _filter_issues_locally(
        self,
        diff_lines: list[str],
        issues: list[Issue],
        only_unresolved: bool = False,
        preserve_existing_filtered: bool = False,
    ) -> None:
        reviewable_line_numbers = self.evidence_locator.reviewable_line_numbers(diff_lines)
        for issue in issues:
            if only_unresolved and issue.filter_status:
                continue
            was_semantically_filtered = issue.filter_status == "filtered"
            reason = ""
            confidence = issue.confidence_level if issue.confidence_level is not None else 0.8
            line_numbers = self._parse_line_numbers(issue.issue_line_numbers)
            if issue.evidence_match_score is None and issue.existing_code.strip():
                match = self.evidence_locator.locate(
                    existing_code=issue.existing_code,
                    full_code="",
                    diff_lines=diff_lines,
                    claimed_line_numbers=line_numbers,
                )
                self._apply_evidence_match(issue, match)
            if not issue.description.strip() or not issue.suggestion.strip():
                reason = "问题描述或修复建议为空。"
            elif self.settings.review_evidence_required and not issue.existing_code.strip():
                reason = "issue 缺少 existing_code，无法核验代码锚点。"
            elif self.settings.review_evidence_required and not issue.evidence.strip():
                reason = "issue 缺少 evidence，无法核验问题事实。"
            elif not line_numbers:
                reason = "issue 没有可解析的行号。"
            elif issue.relocation_status == "failed":
                reason = "行号重定位失败，证据不足。"
            elif confidence < self.settings.review_filter_min_confidence:
                reason = f"置信度 {confidence:.2f} 低于阈值。"
            elif (
                issue.existing_code.strip()
                and issue.evidence_match_score is not None
                and issue.evidence_match_score < self.settings.review_line_evidence_min_similarity
            ):
                reason = f"existing_code 与本次变更代码匹配度 {issue.evidence_match_score:.2f} 低于阈值。"
            elif reviewable_line_numbers and not any(line in reviewable_line_numbers for line in line_numbers):
                reason = "issue 行号不在本次新增/变更行或删除块相邻存活行中。"

            if reason:
                issue.filter_status = "filtered"
                issue.filter_reason = reason
            elif preserve_existing_filtered and was_semantically_filtered:
                issue.filter_status = "filtered"
                issue.filter_reason = issue.filter_reason or "REVIEW_FILTER_TASK 提供了 diff 直接反证。"
            else:
                issue.filter_status = "kept"
                issue.filter_reason = "问题通过机械证据校验，且未被 diff 直接证伪。"
            issue.re_review_status = 0 if self._is_reportable_issue(issue) else 1
            issue.re_review_description = issue.filter_reason

    def _apply_evidence_match(self, issue: Issue, match: EvidenceMatch) -> None:
        issue.evidence_match_status = match.status
        issue.evidence_match_score = min(1.0, max(0.0, match.score))
        issue.evidence_start_line = match.start_line
        issue.evidence_end_line = match.end_line
        issue.evidence_occurrence_count = match.occurrence_count
        issue.evidence_source = match.source
        issue.location_ambiguous = match.ambiguous
        confidence = match.score
        if match.ambiguous:
            confidence *= 0.7
        if not match.changed_line_overlap:
            confidence *= 0.5
        issue.location_confidence = min(1.0, max(0.0, confidence))

    def _normalize_code_fragment(self, value: str | None) -> str:
        return re.sub(r"\s+", "", str(value or "")).lower()

    def _find_relocation_candidate_line(self, issue: Issue, diff_lines: list[str]) -> int | None:
        added_lines = list(self._iter_added_with_line_number(diff_lines))
        if not added_lines:
            return None
        issue_text = " ".join([issue.type or "", issue.description or "", issue.suggestion or ""]).lower()
        danger_patterns = [
            (["strcpy", "strcat", "buffer", "overflow", "缓冲", "溢出"], ["strcpy(", "strcat("]),
            (["sscanf", "%s"], ["sscanf(", "%s"]),
            (["format", "printf", "格式化"], ["printf(", "fprintf("]),
            (["divide", "division", "除数", "除法"], ["/ right", "/right"]),
            (["argv", "参数", "越界"], ["argv["]),
            (["eval", "exec"], ["eval(", "exec("]),
            (["secret", "password", "api_key", "token", "敏感"], ["secret", "password", "api_key", "token"]),
            (["todo", "fixme", "未完成"], ["todo", "fixme"]),
        ]
        for hints, code_patterns in danger_patterns:
            if any(hint in issue_text for hint in hints):
                for line_number, code in added_lines:
                    lower_code = code.lower()
                    if any(pattern in lower_code for pattern in code_patterns):
                        return line_number

        keywords = self._issue_keywords(issue_text)
        best_line: int | None = None
        best_score = 0
        for line_number, code in added_lines:
            lower_code = code.lower()
            score = sum(1 for keyword in keywords if keyword in lower_code)
            if score > best_score:
                best_line = line_number
                best_score = score
        return best_line if best_score > 0 else None

    def _issue_keywords(self, issue_text: str) -> list[str]:
        excluded = {
            "issue",
            "line",
            "code",
            "suggestion",
            "description",
            "security",
            "logic",
            "performance",
            "readability",
            "style",
        }
        keywords = []
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", issue_text):
            lowered = token.lower()
            if lowered not in excluded:
                keywords.append(lowered)
        return list(dict.fromkeys(keywords))[:12]

    def _issue_payload(self, issue: Issue) -> dict[str, Any]:
        return {
            "issue_id": issue.issue_id,
            "type": issue.type,
            "severity": issue.severity,
            "description": issue.description,
            "suggestion": issue.suggestion,
            "issue_line_numbers": issue.issue_line_numbers,
            "existing_code": issue.existing_code,
            "suggestion_code": issue.suggestion_code,
            "evidence": issue.evidence,
            "rule_id": issue.rule_id,
            "evidence_match_status": issue.evidence_match_status,
            "evidence_match_score": issue.evidence_match_score,
            "evidence_start_line": issue.evidence_start_line,
            "evidence_end_line": issue.evidence_end_line,
            "evidence_occurrence_count": issue.evidence_occurrence_count,
            "evidence_source": issue.evidence_source,
            "location_confidence": issue.location_confidence,
            "location_ambiguous": issue.location_ambiguous,
            "confidence_level": issue.confidence_level,
            "original_issue_line_numbers": issue.original_issue_line_numbers,
            "relocation_status": issue.relocation_status,
            "filter_status": issue.filter_status,
            "filter_counter_evidence": issue.filter_counter_evidence,
        }

    def _issue_filter_payload(self, issue: Issue) -> dict[str, Any]:
        return {
            "issue_id": issue.issue_id,
            "filter_status": issue.filter_status,
            "filter_reason": issue.filter_reason,
            "evidence_match_status": issue.evidence_match_status,
            "evidence_match_score": issue.evidence_match_score,
            "confidence_level": issue.confidence_level,
        }

    def _parse_line_numbers(self, line_numbers: str | None) -> list[int]:
        if not line_numbers:
            return []
        parsed: list[int] = []
        for value in re.findall(r"\d+", str(line_numbers)):
            parsed.append(int(value))
        return parsed

    def _added_line_numbers(self, diff_lines: list[str]) -> set[int]:
        return {line_number for line_number, _ in self._iter_added_with_line_number(diff_lines)}

    def _reindex_issues(self, issues: list[Issue]) -> None:
        visible_index = 1
        for index, issue in enumerate(issues):
            issue.issue_id = index
            if not self._is_reportable_issue(issue):
                issue.comment_line_number = 0
                continue
            issue.comment_line_number = visible_index
            visible_index += 1

    def _visible_issue_count(self, issues: list[Issue]) -> int:
        return sum(1 for issue in issues if self._is_reportable_issue(issue))

    def _is_reportable_issue(self, issue: Issue) -> bool:
        return (issue.filter_status or "").lower() != "filtered"

    def _confidence(self, value: Any, default: float | None = None) -> float | None:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return default
        return min(1.0, max(0.0, confidence))

    def _safe_int(self, value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _finish_task(self, task: TaskModel, code_files: list[CodeFileModel], started_at: float) -> None:
        completed_files = [
            code_file
            for code_file in code_files
            if (code_file.extra or {}).get("status") in {"reviewed", "resumed"}
        ]
        scores = self._average_file_scores(completed_files)
        issue_summary: dict[str, int] = {}
        severity_summary: dict[str, int] = {}
        for code_file in code_files:
            for block in code_file.code_blocks:
                for issue in block.issues:
                    if not self._is_reportable_issue(issue):
                        continue
                    issue_summary[issue.type or "general"] = issue_summary.get(issue.type or "general", 0) + 1
                    severity_key = str(issue.severity or 0)
                    severity_summary[severity_key] = severity_summary.get(severity_key, 0) + 1

        project_summary = self._build_project_summary(task, code_files, issue_summary, severity_summary)
        llm_project_summary = self._maybe_generate_project_summary(task, code_files, project_summary)
        if llm_project_summary:
            project_summary["summary"] = llm_project_summary
            project_summary["summary_source"] = "llm"

        incomplete_files = [
            code_file
            for code_file in code_files
            if (code_file.extra or {}).get("status") in {"partial", "skipped_budget"}
        ]
        task.state = TASK_STATE_COMPLETED if not incomplete_files else TASK_STATE_PARTIAL
        task.completion_status = "completed" if not incomplete_files else "partial"
        if incomplete_files:
            task.retry_count = (task.retry_count or 0) + 1
        task.file_num = len(code_files)
        task.reviewed_file_num = sum(
            1
            for code_file in code_files
            if (code_file.extra or {}).get("status") in {"reviewed", "resumed"}
        )
        task.resumed_file_num = sum(1 for code_file in code_files if (code_file.extra or {}).get("status") == "resumed")
        task.skipped_file_num = sum(1 for code_file in code_files if (code_file.extra or {}).get("status") == "skipped_budget")
        task.incomplete_file_num = len(incomplete_files)
        task.code_block_num = sum(len(code_file.code_blocks) for code_file in code_files)
        task.add_code_line_num = sum(code_file.add_code_line_num for code_file in code_files)
        task.comment_line_number = sum(code_file.comment_line_number for code_file in code_files)
        for field_name, value in scores.items():
            setattr(task, field_name, value)
        task.score = int(sum(scores.values()) / len(scores)) if scores else 0
        task.estimated_token_num = sum(int((code_file.extra or {}).get("estimated_tokens") or 0) for code_file in code_files)
        task.consumed_estimated_token_num = sum(
            int((code_file.extra or {}).get("estimated_tokens") or 0)
            for code_file in code_files
            if (code_file.extra or {}).get("status") == "reviewed"
        )
        task.token_budget_num = self._effective_token_budget(task)
        task_round_usage = self._summarize_model_round_tokens(self.task_model_rounds)
        with self._usage_lock:
            run_usage = {
                **self._run_usage,
                "tool_calls": dict(self._run_usage.get("tool_calls") or {}),
            }
        task.llm_prompt_tokens = (
            self._initial_usage["prompt_tokens"] + run_usage["prompt_tokens"] + task_round_usage["prompt_tokens"]
        )
        task.llm_completion_tokens = (
            self._initial_usage["completion_tokens"]
            + run_usage["completion_tokens"]
            + task_round_usage["completion_tokens"]
        )
        task.llm_total_tokens = (
            self._initial_usage["total_tokens"] + run_usage["total_tokens"] + task_round_usage["total_tokens"]
        )
        task.llm_elapsed_ms = (
            self._initial_usage["elapsed_ms"] + run_usage["elapsed_ms"] + task_round_usage["elapsed_ms"]
        )
        task.llm_call_count = (
            self._initial_usage["call_count"]
            + run_usage["call_count"]
            + sum(1 for trace in self.task_model_rounds if trace.model != "local")
        )
        tool_call_summary: dict[str, int] = dict(self._initial_usage.get("tool_calls") or {})
        for tool_name, count in run_usage["tool_calls"].items():
            tool_call_summary[tool_name] = tool_call_summary.get(tool_name, 0) + count
        task.tool_call_summary = tool_call_summary
        task.task_model_rounds = self.task_model_rounds
        task.project_summary = project_summary["summary"]
        static_sources: dict[str, int] = {}
        static_finding_count = 0
        static_corroborated_issue_count = 0
        for code_file in code_files:
            for block in code_file.code_blocks:
                static_finding_count += len(block.static_findings)
                for finding in block.static_findings:
                    source = str(finding.get("analyzer") or "unknown")
                    static_sources[source] = static_sources.get(source, 0) + 1
                static_corroborated_issue_count += sum(
                    1 for issue in block.issues if self._is_reportable_issue(issue) and issue.static_corroborated
                )
        task.developer_issue_summary = {
            **issue_summary,
            "_severity": severity_summary,
            "_static_analysis": {
                "finding_count": static_finding_count,
                "corroborated_issue_count": static_corroborated_issue_count,
                "sources": static_sources,
            },
            "_scan_budget": project_summary["scan_budget"],
            "_resume": project_summary["resume"],
            "_project_summary": project_summary,
        }
        task.process_time = self._initial_usage["process_time"] + int((time.monotonic() - started_at) * 1000)
        task.lease_owner = ""
        task.lease_token = ""
        task.lease_expires_at = None
        task.heartbeat_time = None
        task.interrupt_requested = False
        task.update_time = utc_now()
        task.save()

    def _build_project_summary(
        self,
        task: TaskModel,
        code_files: list[CodeFileModel],
        issue_summary: dict[str, int],
        severity_summary: dict[str, int],
    ) -> dict[str, Any]:
        total_issues = sum(issue_summary.values())
        top_files = sorted(
            [
                {
                    "file_name": code_file.file_name,
                    "issue_count": code_file.comment_line_number or 0,
                    "status": (code_file.extra or {}).get("status", ""),
                }
                for code_file in code_files
                if code_file.comment_line_number
            ],
            key=lambda item: (-int(item["issue_count"]), str(item["file_name"])),
        )[:10]
        status_counts: dict[str, int] = {}
        for code_file in code_files:
            status = str((code_file.extra or {}).get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        scan_budget = {
            "enabled": self._effective_token_budget(task) > 0,
            "budget_tokens": self._effective_token_budget(task),
            "estimated_tokens": sum(int((code_file.extra or {}).get("estimated_tokens") or 0) for code_file in code_files),
            "consumed_estimated_tokens": sum(
                int((code_file.extra or {}).get("estimated_tokens") or 0)
                for code_file in code_files
                if (code_file.extra or {}).get("status") == "reviewed"
            ),
            "skipped_file_num": status_counts.get("skipped_budget", 0),
        }
        resume = {
            "enabled": self.settings.review_resume_enabled,
            "resumed_file_num": status_counts.get("resumed", 0),
        }
        if not self.settings.full_scan_project_summary_enabled:
            summary_text = ""
        elif total_issues:
            summary_text = (
                f"本次审核发现 {total_issues} 个展示问题，涉及 {len(top_files)} 个重点文件；"
                f"主要类型：{self._format_count_summary(issue_summary)}；"
                f"严重度分布：{self._format_count_summary(severity_summary)}。"
            )
        else:
            summary_text = "本次审核未发现需要展示的问题。"
        return {
            "summary": summary_text,
            "summary_source": "deterministic",
            "task_type": task.task_type,
            "file_num": len(code_files),
            "reviewed_file_num": status_counts.get("reviewed", 0),
            "skipped_file_num": status_counts.get("skipped_budget", 0),
            "resumed_file_num": status_counts.get("resumed", 0),
            "issue_summary": issue_summary,
            "severity_summary": severity_summary,
            "top_files": top_files,
            "status_counts": status_counts,
            "scan_budget": scan_budget,
            "resume": resume,
        }

    def _maybe_generate_project_summary(
        self,
        task: TaskModel,
        code_files: list[CodeFileModel],
        project_summary: dict[str, Any],
    ) -> str:
        if (
            task.task_type != TASK_TYPE_FULL_SCAN
            or self.llm_client.is_mock
            or not self.settings.full_scan_project_summary_enabled
            or not self.settings.full_scan_project_summary_llm_enabled
        ):
            return ""

        issue_payloads: list[dict[str, Any]] = []
        maximum = max(1, self.settings.full_scan_project_summary_max_issues)
        for code_file in code_files:
            for block in code_file.code_blocks:
                for issue in block.issues:
                    if not self._is_reportable_issue(issue):
                        continue
                    issue_payloads.append(
                        {
                            "path": code_file.file_name,
                            "type": issue.type,
                            "severity": issue.severity,
                            "description": self._truncate(issue.description, 400),
                            "suggestion": self._truncate(issue.suggestion, 300),
                            "lines": issue.issue_line_numbers,
                            "rule_id": issue.rule_id,
                        }
                    )
                    if len(issue_payloads) >= maximum:
                        break
                if len(issue_payloads) >= maximum:
                    break
            if len(issue_payloads) >= maximum:
                break
        if not issue_payloads:
            return ""

        messages = build_project_summary_messages(project_summary, issue_payloads)
        assistant_message: dict[str, Any] | None = None
        try:
            assistant_message = self.llm_client.chat(messages=messages)
            trace = self._build_model_round_trace("project_summary_task", 1, messages, assistant_message)
            self.task_model_rounds.append(trace)
            content = str(assistant_message.get("content") or "").strip()
            fenced = re.fullmatch(r"```(?:markdown)?\s*(.*?)\s*```", content, flags=re.DOTALL | re.IGNORECASE)
            if fenced:
                content = fenced.group(1).strip()
            return content
        except Exception as exc:
            failure = f"project_summary_task failed: {type(exc).__name__}: {exc}"
            if self.task_model_rounds and self.task_model_rounds[-1].stage == "project_summary_task":
                self.task_model_rounds[-1].error_message = failure
            else:
                self.task_model_rounds.append(
                    self._build_model_round_trace("project_summary_task", 1, messages, assistant_message, failure)
                )
            return ""

    def _format_count_summary(self, counts: dict[str, int]) -> str:
        if not counts:
            return "无"
        return "，".join(f"{key}={value}" for key, value in sorted(counts.items()))

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
        added_code_by_line = {line_number: code.strip() for line_number, code in self._iter_added_with_line_number(diff_lines)}
        for comment in comments:
            issue_lines = self._parse_line_numbers(comment.get("issue_line_numbers"))
            first_line = issue_lines[0] if issue_lines else 0
            comment.setdefault("existing_code", added_code_by_line.get(first_line, ""))
            comment.setdefault("evidence", comment.get("description", ""))
            comment.setdefault("suggestion_code", "")
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
                    existing_code=str(comment.get("existing_code") or ""),
                    suggestion_code=str(comment.get("suggestion_code") or ""),
                    evidence=str(comment.get("evidence") or ""),
                    rule_id=str(comment.get("rule_id") or ""),
                    comment_line_number=index,
                    confidence_level=self._confidence(comment.get("confidence_level")),
                    original_issue_line_numbers=str(comment.get("issue_line_numbers") or ""),
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
            if not comments:
                return True
            accepted = False
            for comment in comments:
                if isinstance(comment, dict):
                    result = runner.code_comment(comment)
                    accepted = bool(result.get("accepted")) or accepted
            return accepted
        return False

    def _build_model_round_trace(
        self,
        stage: str,
        round_index: int,
        request_messages: list[dict[str, Any]],
        assistant_message: dict[str, Any] | None,
        error_message: str = "",
    ) -> ModelRoundTrace:
        assistant_message = assistant_message or {}
        trace = assistant_message.get("_llm_trace") or {}
        usage = trace.get("usage") or {}
        completion_details = usage.get("completion_tokens_details") or {}
        prompt_details = usage.get("prompt_tokens_details") or {}
        tool_calls = assistant_message.get("tool_calls") or []
        cached_tokens = int(prompt_details.get("cached_tokens") or 0) + int(usage.get("prompt_cache_hit_tokens") or 0)
        return ModelRoundTrace(
            stage=stage,
            round_index=round_index,
            model=str(trace.get("model") or self.settings.llm_model),
            request_summary=self._summarize_messages(request_messages),
            response_summary=self._summarize_assistant_message(assistant_message),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
            reasoning_tokens=int(completion_details.get("reasoning_tokens") or 0),
            cached_tokens=cached_tokens,
            elapsed_ms=int(trace.get("elapsed_ms") or 0),
            finish_reason=str(trace.get("finish_reason") or ""),
            tool_call_count=len(tool_calls),
            error_message=error_message,
        )

    def _build_local_trace(
        self,
        stage: str,
        round_index: int,
        request_summary: dict[str, Any],
        response_summary: dict[str, Any],
        elapsed_ms: int = 0,
    ) -> ModelRoundTrace:
        return ModelRoundTrace(
            stage=stage,
            round_index=round_index,
            model="local",
            request_summary=self._truncate(json.dumps(request_summary, ensure_ascii=False, default=str), 1200),
            response_summary=self._truncate(json.dumps(response_summary, ensure_ascii=False, default=str), 1200),
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            reasoning_tokens=0,
            cached_tokens=0,
            elapsed_ms=elapsed_ms,
            finish_reason="local",
            tool_call_count=0,
            error_message="",
        )

    def _build_tool_call_trace(
        self,
        round_index: int,
        tool_call: dict[str, Any],
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        elapsed_ms: int,
    ) -> ToolCallTrace:
        error_message = str(result.get("error") or "")
        return ToolCallTrace(
            stage="main_task",
            round_index=round_index,
            tool_call_id=str(tool_call.get("id") or ""),
            tool_name=tool_name,
            arguments=arguments if isinstance(arguments, dict) else {"_raw": arguments},
            result_summary=self._truncate(json.dumps(result, ensure_ascii=False, default=str), 1200),
            success=not bool(error_message),
            cached=bool(result.get("_cached")),
            elapsed_ms=elapsed_ms,
            error_message=error_message,
        )

    def _summarize_model_round_tokens(self, model_rounds: list[ModelRoundTrace]) -> dict[str, int]:
        return {
            "prompt_tokens": sum(round_trace.prompt_tokens or 0 for round_trace in model_rounds),
            "completion_tokens": sum(round_trace.completion_tokens or 0 for round_trace in model_rounds),
            "total_tokens": sum(round_trace.total_tokens or 0 for round_trace in model_rounds),
            "reasoning_tokens": sum(round_trace.reasoning_tokens or 0 for round_trace in model_rounds),
            "cached_tokens": sum(round_trace.cached_tokens or 0 for round_trace in model_rounds),
            "elapsed_ms": sum(
                round_trace.elapsed_ms or 0
                for round_trace in model_rounds
                if round_trace.model != "local"
            ),
        }

    def _summarize_messages(self, messages: list[dict[str, Any]]) -> str:
        role_counts: dict[str, int] = {}
        last_user_content = ""
        last_tool_content = ""
        for message in messages:
            role = str(message.get("role") or "")
            role_counts[role] = role_counts.get(role, 0) + 1
            if role == "user":
                last_user_content = str(message.get("content") or "")
            if role == "tool":
                last_tool_content = str(message.get("content") or "")
        summary = {
            "message_count": len(messages),
            "role_counts": role_counts,
            "last_user": self._truncate(last_user_content, 800),
            "last_tool": self._truncate(last_tool_content, 500),
        }
        return json.dumps(summary, ensure_ascii=False)

    def _summarize_assistant_message(self, assistant_message: dict[str, Any]) -> str:
        tool_calls = assistant_message.get("tool_calls") or []
        tool_names = [
            str((tool_call.get("function") or {}).get("name") or "")
            for tool_call in tool_calls
        ]
        summary = {
            "content": self._truncate(str(assistant_message.get("content") or ""), 1200),
            "tool_call_count": len(tool_calls),
            "tool_names": [tool_name for tool_name in tool_names if tool_name],
        }
        return json.dumps(summary, ensure_ascii=False)

    def _truncate(self, value: str, max_length: int) -> str:
        if len(value) <= max_length:
            return value
        return value[: max_length - 20] + "...<truncated>"

    def _merge_duplicate_file_issues(self, blocks: list[CodeBlock]) -> None:
        seen_indexes: dict[tuple[str, int, str, str, str], tuple[list[Issue], int]] = {}
        canonical_indexes: list[tuple[list[Issue], int]] = []
        for block in blocks:
            merged_issues: list[Issue] = []
            for issue in block.issues:
                key = self._issue_merge_key(issue)
                duplicate_target = seen_indexes.get(key)
                if duplicate_target is None:
                    duplicate_target = next(
                        (
                            candidate
                            for candidate in canonical_indexes
                            if self._issues_semantically_equivalent(candidate[0][candidate[1]], issue)
                        ),
                        None,
                    )
                if duplicate_target is not None:
                    previous_list, previous_index = duplicate_target
                    previous_issue = previous_list[previous_index]
                    if not self._is_reportable_issue(previous_issue) and self._is_reportable_issue(issue):
                        previous_list[previous_index] = issue
                    continue
                seen_indexes[key] = (merged_issues, len(merged_issues))
                merged_issues.append(issue)
                canonical_indexes.append((merged_issues, len(merged_issues) - 1))
            block.issues = merged_issues
        for block in blocks:
            self._reindex_issues(block.issues)
            block.comment_line_number = self._visible_issue_count(block.issues)

    def _issue_merge_key(self, issue: Issue) -> tuple[str, int, str, str, str]:
        return (
            self._normalize_issue_text(issue.type),
            issue.severity,
            self._normalize_issue_lines(issue.issue_line_numbers),
            self._normalize_issue_text(issue.description),
            self._normalize_issue_text(issue.suggestion),
        )

    def _issues_semantically_equivalent(self, left: Issue, right: Issue) -> bool:
        if self._normalize_issue_text(left.type) != self._normalize_issue_text(right.type):
            return False
        if left.severity != right.severity:
            return False
        left_lines = set(self._parse_line_numbers(left.issue_line_numbers))
        right_lines = set(self._parse_line_numbers(right.issue_line_numbers))
        if not left_lines or not right_lines or not left_lines.intersection(right_lines):
            return False
        same_rule = bool(left.rule_id and right.rule_id and left.rule_id == right.rule_id)
        left_code = self._normalize_code_fragment(left.existing_code)
        right_code = self._normalize_code_fragment(right.existing_code)
        same_code = bool(left_code and right_code and left_code == right_code)
        if not same_rule and not same_code:
            return False
        return self._jaccard(
            self._issue_word_set(left.description),
            self._issue_word_set(right.description),
        ) >= 0.65

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
        weights = [self._block_change_weight(block) for block in blocks]
        total_weight = sum(weights)
        return {
            field: round(sum(getattr(block, field) * weight for block, weight in zip(blocks, weights)) / total_weight)
            for field in SCORE_FIELDS
        }

    def _average_file_scores(self, code_files: list[CodeFileModel]) -> dict[str, int]:
        if not code_files:
            return {field: 0 for field in SCORE_FIELDS}
        blocks = [block for code_file in code_files for block in code_file.code_blocks]
        return self._average_block_scores(blocks)

    def _block_change_weight(self, block: CodeBlock) -> int:
        lines = list(block.contents or [])
        changed_line_count = sum(1 for line in lines if len(line) > 6 and line[6] in {"+", "-"})
        return max(1, changed_line_count) if lines else 0

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
        return code_block_hash(lines)

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
