from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from urllib.parse import quote

from mongoengine.errors import NotUniqueError

from app.common.constant import is_incremental_task_type
from app.models.code_file import CodeBlock, CodeFileModel
from app.models.code_file_snapshot import CodeFileSnapshotModel
from app.models.task import TaskModel
from app.models.task_snapshot import TaskSnapshotModel


SCORE_FIELDS = ("logic_score", "performance_score", "security_score", "readable_score", "code_style_score")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskSnapshotService:
    def create(
        self,
        task: TaskModel,
        *,
        changed_file_names: list[str],
        changed_block_refs: dict[str, list[dict[str, object]]],
        removed_file_names: list[str],
    ) -> TaskSnapshotModel | None:
        if not changed_file_names and not removed_file_names:
            return None

        self._supersede_open_snapshots(task)

        files_by_name = {
            code_file.file_name: code_file
            for code_file in CodeFileModel.objects(
                task_id=str(task.id),
                file_name__in=changed_file_names,
            )
        }
        changed_files = [
            str(files_by_name[file_name].id)
            for file_name in changed_file_names
            if file_name in files_by_name
        ]
        flattened_refs: list[dict[str, object]] = []
        for file_name in changed_file_names:
            code_file = files_by_name.get(file_name)
            if code_file is None:
                continue
            for block_ref in changed_block_refs.get(file_name, []):
                flattened_refs.append(
                    {
                        "file_id": str(code_file.id),
                        "file_name": file_name,
                        "block_id": int(block_ref.get("block_id") or 0),
                        "block_hash": str(block_ref.get("block_hash") or ""),
                    }
                )

        snapshot_id = self._new_snapshot_id()
        snapshot = TaskSnapshotModel(
            task_id=str(task.id),
            snapshot_id=snapshot_id,
            project_id=task.project_id,
            review_version=task.review_version,
            copy_from_version=task.copy_from_version,
            review_version_path=task.review_version_path or "",
            copy_from_version_path=task.copy_from_version_path or "",
            author_map_file=task.author_map_file or "",
            task_type=task.task_type,
            state=0,
            completion_status="pending",
            submitter=task.submitter,
            parent_path=task.parent_path,
            trigger_count=task.trigger_count or 1,
            trigger_revision=task.trigger_revision or 1,
            changed_files=changed_files,
            changed_file_names=changed_file_names,
            changed_blocks=flattened_refs,
            removed_file_names=removed_file_names,
            usage_baseline=self._usage_values(task),
            created_by=task.created_by,
            create_time=utc_now(),
            update_time=utc_now(),
        )
        try:
            snapshot.save()
        except NotUniqueError:
            snapshot = TaskSnapshotModel.objects(
                task_id=str(task.id),
                trigger_revision=task.trigger_revision or 1,
            ).first()
            if snapshot is None:
                raise
        return self.checkpoint(task, snapshot=snapshot)

    def carry_forward(self, task: TaskModel) -> TaskSnapshotModel | None:
        snapshot = (
            TaskSnapshotModel.objects(
                task_id=str(task.id),
                state__in=[0, 1, 3],
                completion_status__ne="superseded",
                trigger_revision__lt=task.trigger_revision or 1,
            )
            .order_by("-trigger_revision")
            .first()
        )
        if snapshot is None:
            return None
        snapshot.trigger_count = task.trigger_count or snapshot.trigger_count
        snapshot.trigger_revision = task.trigger_revision or snapshot.trigger_revision
        snapshot.state = 0
        snapshot.completion_status = "pending"
        snapshot.completion_time = None
        snapshot.update_time = utc_now()
        snapshot.save()
        return self.checkpoint(task, snapshot=snapshot)

    def checkpoint(
        self,
        task: TaskModel,
        *,
        snapshot: TaskSnapshotModel | None = None,
        finalize: bool = False,
    ) -> TaskSnapshotModel | None:
        snapshot = snapshot or TaskSnapshotModel.objects(
            task_id=str(task.id),
            trigger_revision=task.trigger_revision or 1,
        ).first()
        if snapshot is None:
            return None
        if snapshot.completion_status == "superseded":
            return snapshot
        self._sync_code_files(snapshot)
        self._aggregate(snapshot, parent_state=task.state, finalize=finalize)
        snapshot.update_time = utc_now()
        snapshot.save()
        return snapshot

    @staticmethod
    def report_path(snapshot: TaskSnapshotModel) -> str:
        comparison = f"{quote(snapshot.review_version, safe='')}_vs_{quote(snapshot.copy_from_version, safe='')}"
        return (
            f"/snapshot/{quote(snapshot.snapshot_id, safe='')}/"
            f"{quote(snapshot.project_id, safe='')}/{comparison}.html"
        )

    @staticmethod
    def _new_snapshot_id() -> str:
        return utc_now().strftime("%Y%m%d%H%M%S%f")

    @staticmethod
    def _supersede_open_snapshots(task: TaskModel) -> None:
        TaskSnapshotModel.objects(
            task_id=str(task.id),
            state__in=[0, 1, 3],
            trigger_revision__lt=task.trigger_revision or 1,
        ).update(
            set__state=3,
            set__completion_status="superseded",
            set__completion_time=utc_now(),
            set__update_time=utc_now(),
        )

    def _sync_code_files(self, snapshot: TaskSnapshotModel) -> None:
        refs_by_file: dict[str, list[dict[str, object]]] = defaultdict(list)
        for raw_ref in snapshot.changed_blocks or []:
            file_id = str(raw_ref.get("file_id") or "")
            if not file_id:
                continue
            refs_by_file[file_id].append(dict(raw_ref))

        for file_id in snapshot.changed_files or []:
            code_file = CodeFileModel.objects(id=file_id, task_id=snapshot.task_id).first()
            if code_file is None:
                continue
            selected_blocks = self._select_blocks(code_file.code_blocks, refs_by_file.get(file_id, []))
            if not selected_blocks:
                continue
            persisted = CodeFileSnapshotModel.objects(
                snapshot_id=snapshot.snapshot_id,
                file_name=code_file.file_name,
            ).first()
            if persisted is None:
                persisted = CodeFileSnapshotModel(
                    task_snapshot_id=str(snapshot.id),
                    snapshot_id=snapshot.snapshot_id,
                    task_id=snapshot.task_id,
                    source_file_id=str(code_file.id),
                    project_id=snapshot.project_id,
                    review_version=snapshot.review_version,
                    copy_from_version=snapshot.copy_from_version,
                    file_name=code_file.file_name,
                    created_by=code_file.created_by,
                )
            persisted.task_type = code_file.task_type
            persisted.state = self._file_state(selected_blocks)
            persisted.source_hash = code_file.source_hash or ""
            persisted.trigger_revision = snapshot.trigger_revision or 0
            persisted.background = code_file.background or ""
            persisted.background_source = code_file.background_source or ""
            persisted.code_blocks = deepcopy(selected_blocks)
            persisted.code_line_num = sum(len(block.contents or []) for block in selected_blocks)
            persisted.add_code_line_num = sum(
                self._added_line_count(block, snapshot.task_type or 0) for block in selected_blocks
            )
            persisted.comment_line_number = sum(block.comment_line_number or 0 for block in selected_blocks)
            scores = self._weighted_scores(selected_blocks, snapshot.task_type or 0)
            for field_name, value in scores.items():
                setattr(persisted, field_name, value)
            persisted.file_author = code_file.file_author or ""
            persisted.extra = {
                **(code_file.extra or {}),
                "snapshot_id": snapshot.snapshot_id,
                "source_file_id": str(code_file.id),
                "status": self._file_status(selected_blocks),
            }
            persisted.update_time = utc_now()
            persisted.save()

    def _aggregate(self, snapshot: TaskSnapshotModel, *, parent_state: int, finalize: bool) -> None:
        code_files = list(CodeFileSnapshotModel.objects(snapshot_id=snapshot.snapshot_id))
        blocks = [block for code_file in code_files for block in code_file.code_blocks]
        statuses = [self._block_status(block) for block in blocks]
        completed_blocks = [block for block in blocks if self._block_status(block) == "completed"]
        failed_count = statuses.count("failed")
        pending_count = statuses.count("pending") + statuses.count("reviewing")

        if not blocks and snapshot.removed_file_names and finalize and parent_state == 2:
            snapshot.state = 2
            snapshot.completion_status = "completed"
        elif blocks and not failed_count and not pending_count:
            snapshot.state = 2
            snapshot.completion_status = "completed"
        elif failed_count and not pending_count:
            snapshot.state = 3
            snapshot.completion_status = "partial"
        else:
            snapshot.state = 1 if parent_state == 1 else 0
            snapshot.completion_status = "running" if snapshot.state == 1 else "pending"

        snapshot.file_num = len(code_files)
        snapshot.reviewed_file_num = sum(
            1 for code_file in code_files if self._file_status(code_file.code_blocks) == "reviewed"
        )
        snapshot.resumed_file_num = 0
        snapshot.skipped_file_num = 0
        snapshot.incomplete_file_num = sum(
            1 for code_file in code_files if self._file_status(code_file.code_blocks) == "partial"
        )
        snapshot.code_block_num = len(blocks)
        snapshot.add_code_line_num = sum(code_file.add_code_line_num or 0 for code_file in code_files)
        snapshot.comment_line_number = sum(code_file.comment_line_number or 0 for code_file in code_files)
        scores = self._weighted_scores(completed_blocks, snapshot.task_type or 0)
        for field_name, value in scores.items():
            setattr(snapshot, field_name, value)
        snapshot.score = round(sum(scores.values()) / len(SCORE_FIELDS)) if scores else 0
        snapshot.process_time = sum(block.process_time or 0 for block in blocks)
        snapshot.llm_prompt_tokens = sum(block.llm_prompt_tokens or 0 for block in blocks)
        snapshot.llm_completion_tokens = sum(block.llm_completion_tokens or 0 for block in blocks)
        snapshot.llm_total_tokens = sum(block.llm_total_tokens or 0 for block in blocks)
        snapshot.llm_elapsed_ms = sum(block.llm_elapsed_ms or 0 for block in blocks)
        snapshot.llm_call_count = sum(
            1 for block in blocks for trace in block.model_rounds if trace.model != "local"
        )
        tool_summary: dict[str, int] = {}
        for block in blocks:
            for trace in block.tool_calls:
                tool_summary[trace.tool_name] = tool_summary.get(trace.tool_name, 0) + 1
        snapshot.tool_call_summary = tool_summary
        snapshot.estimated_token_num = sum(
            int((code_file.extra or {}).get("estimated_tokens") or 0) for code_file in code_files
        )
        snapshot.consumed_estimated_token_num = snapshot.estimated_token_num
        snapshot.token_budget_num = 0
        issue_summary: dict[str, int] = {}
        severity_summary: dict[str, int] = {}
        for block in blocks:
            for issue in block.issues:
                if (issue.filter_status or "").lower() == "filtered":
                    continue
                issue_type = issue.type or "general"
                issue_summary[issue_type] = issue_summary.get(issue_type, 0) + 1
                severity = str(issue.severity or 0)
                severity_summary[severity] = severity_summary.get(severity, 0) + 1
        snapshot.developer_issue_summary = {**issue_summary, "_severity": severity_summary}
        snapshot.project_summary = (
            f"本次变更审核包含 {snapshot.file_num} 个文件、{snapshot.code_block_num} 个代码块。"
        )
        if finalize and snapshot.state in {2, 3}:
            snapshot.completion_time = utc_now()

    @staticmethod
    def _select_blocks(blocks: list[CodeBlock], refs: list[dict[str, object]]) -> list[CodeBlock]:
        selected: list[CodeBlock] = []
        used_indexes: set[int] = set()
        for ref in refs:
            block_id = int(ref.get("block_id") or 0)
            block_hash = str(ref.get("block_hash") or "")
            match_index = next(
                (
                    index
                    for index, block in enumerate(blocks)
                    if index not in used_indexes
                    and block.block_id == block_id
                    and (not block_hash or block.block_hash == block_hash)
                ),
                None,
            )
            if match_index is None and block_hash:
                match_index = next(
                    (
                        index
                        for index, block in enumerate(blocks)
                        if index not in used_indexes and block.block_hash == block_hash
                    ),
                    None,
                )
            if match_index is not None:
                used_indexes.add(match_index)
                selected.append(blocks[match_index])
        return selected

    @classmethod
    def _weighted_scores(cls, blocks: list[CodeBlock], task_type: int) -> dict[str, int]:
        totals = {field: 0 for field in SCORE_FIELDS}
        total_weight = 0
        for block in blocks:
            weight = cls._block_weight(block, task_type)
            total_weight += weight
            for field_name in SCORE_FIELDS:
                totals[field_name] += int(getattr(block, field_name, 0) or 0) * weight
        if not total_weight:
            return {field: 0 for field in SCORE_FIELDS}
        return {field: round(total / total_weight) for field, total in totals.items()}

    @staticmethod
    def _block_weight(block: CodeBlock, task_type: int) -> int:
        lines = list(block.contents or [])
        if is_incremental_task_type(task_type):
            changed = sum(1 for line in lines if len(line) > 6 and line[6] in {"+", "-"})
        else:
            changed = len(lines)
        return max(1, changed) if lines else 0

    @classmethod
    def _added_line_count(cls, block: CodeBlock, task_type: int) -> int:
        if not is_incremental_task_type(task_type):
            return len(block.contents or [])
        return sum(1 for line in block.contents or [] if len(line) > 6 and line[6] == "+")

    @staticmethod
    def _block_status(block: CodeBlock) -> str:
        if block.failure_message or block.review_state == 3:
            return "failed"
        if block.main_task_completed or block.review_state == 2:
            return "completed"
        if block.review_state == 1:
            return "reviewing"
        return "pending"

    @classmethod
    def _file_status(cls, blocks: list[CodeBlock]) -> str:
        statuses = [cls._block_status(block) for block in blocks]
        if statuses and all(status == "completed" for status in statuses):
            return "reviewed"
        if "reviewing" in statuses:
            return "reviewing"
        if "failed" in statuses and "pending" not in statuses:
            return "partial"
        return "pending"

    @classmethod
    def _file_state(cls, blocks: list[CodeBlock]) -> int:
        return {"reviewed": 2, "reviewing": 1, "partial": 3}.get(cls._file_status(blocks), 0)

    @staticmethod
    def _usage_values(task: TaskModel) -> dict[str, object]:
        return {
            "process_time": task.process_time or 0,
            "llm_prompt_tokens": task.llm_prompt_tokens or 0,
            "llm_completion_tokens": task.llm_completion_tokens or 0,
            "llm_total_tokens": task.llm_total_tokens or 0,
            "llm_elapsed_ms": task.llm_elapsed_ms or 0,
            "llm_call_count": task.llm_call_count or 0,
            "tool_call_summary": dict(task.tool_call_summary or {}),
        }
