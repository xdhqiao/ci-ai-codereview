from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

from mongoengine.errors import NotUniqueError

from app.common.constant import FULL_SCAN_BASE_VERSION, ReviewState, TaskState, TaskType
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.models.code_file import CodeBlock, CodeFileModel
from app.models.project import ProjectModel
from app.models.task import TaskModel, utc_now
from app.services.diff_service import (
    CodeDiffService,
    ReviewCollection,
    ReviewTarget,
)
from app.services.task_snapshot import TaskSnapshotService


TASK_STATE_PENDING = TaskState.PENDING.value
TASK_STATE_RUNNING = TaskState.RUNNING.value
TASK_STATE_COMPLETED = TaskState.COMPLETED.value
TASK_STATE_PREPARING = TaskState.PREPARING.value
FILE_STATE_PENDING = ReviewState.PENDING.value
FILE_STATE_COMPLETED = ReviewState.COMPLETED.value


@dataclass(frozen=True)
class TaskFileSyncResult:
    files: list[CodeFileModel]
    added_file_names: list[str]
    changed_file_names: list[str]
    reused_file_names: list[str]
    removed_file_names: list[str]
    changed_block_refs: dict[str, list[dict[str, object]]]

    @property
    def report_file_names(self) -> list[str]:
        return sorted([*self.added_file_names, *self.changed_file_names])


def code_block_hash(lines: list[str]) -> str:
    return hashlib.md5("\n".join(lines).encode("utf-8")).hexdigest()


def review_target_hash(target: ReviewTarget) -> str:
    payload = "\n".join([target.file_name, target.language, target.full_code, *target.diff_lines])
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


class TaskFileSynchronizer:
    def __init__(self, diff_service: CodeDiffService) -> None:
        self.diff_service = diff_service

    def synchronize(
        self,
        task: TaskModel,
        collection: ReviewCollection,
        *,
        preserve_stale: bool = False,
        file_author_map: dict[str, str] | None = None,
    ) -> list[CodeFileModel]:
        return self.synchronize_with_result(
            task,
            collection,
            preserve_stale=preserve_stale,
            file_author_map=file_author_map,
        ).files

    def synchronize_with_result(
        self,
        task: TaskModel,
        collection: ReviewCollection,
        *,
        preserve_stale: bool = False,
        file_author_map: dict[str, str] | None = None,
    ) -> TaskFileSyncResult:
        existing_files = {
            item.file_name: item for item in CodeFileModel.objects(task_id=str(task.id))
        }
        synchronized: list[CodeFileModel] = []
        target_names: set[str] = set()
        added_file_names: list[str] = []
        changed_file_names: list[str] = []
        reused_file_names: list[str] = []
        changed_block_refs: dict[str, list[dict[str, object]]] = {}

        for target in collection.targets:
            target_names.add(target.file_name)
            code_file = existing_files.get(target.file_name)
            source_hash = review_target_hash(target)
            previous_source_hash = ""
            previous_block_hashes: list[str] = []
            if code_file is not None:
                previous_source_hash = code_file.source_hash or str(
                    (code_file.extra or {}).get("source_hash") or ""
                )
                previous_block_hashes = self._block_hashes(code_file.code_blocks)
            blocks = self._synchronize_blocks(code_file, target)
            block_refs = self._changed_block_refs(previous_block_hashes, blocks)
            if code_file is None:
                added_file_names.append(target.file_name)
            elif block_refs:
                changed_file_names.append(target.file_name)
            else:
                reused_file_names.append(target.file_name)
            if code_file is None or block_refs:
                changed_block_refs[target.file_name] = block_refs
            completed = bool(blocks) and all(self._block_completed(block) for block in blocks)
            if code_file is None:
                code_file = CodeFileModel(
                    task_id=str(task.id),
                    project_id=task.project_id,
                    review_version=task.review_version,
                    copy_from_version=task.copy_from_version,
                    task_type=task.task_type,
                    file_name=target.file_name,
                    created_by=task.created_by,
                )

            code_file.project_id = task.project_id
            code_file.review_version = task.review_version
            code_file.copy_from_version = task.copy_from_version
            code_file.task_type = task.task_type
            code_file.state = FILE_STATE_COMPLETED if completed else FILE_STATE_PENDING
            code_file.source_hash = source_hash
            if previous_source_hash and previous_source_hash != source_hash:
                code_file.review_fingerprint = ""
            code_file.trigger_revision = task.trigger_revision or 0
            code_file.code_blocks = blocks
            code_file.code_line_num = target.code_line_num
            code_file.add_code_line_num = target.add_code_line_num
            code_file.comment_line_number = sum(block.comment_line_number or 0 for block in blocks)
            if file_author_map is not None:
                code_file.file_author = file_author_map.get(target.file_name, "")
            scores = self._average_completed_scores(blocks)
            for field_name, value in scores.items():
                setattr(code_file, field_name, value)
            code_file.extra = {
                **(code_file.extra or {}),
                "status": "reviewed" if completed else "pending",
                "review_complete": completed,
                "source_hash": source_hash,
                "language": target.language,
                "change_type": target.change_type,
                "old_file_name": target.old_file_name,
                "trigger_revision": task.trigger_revision or 0,
            }
            code_file.update_time = utc_now()
            code_file.save()
            synchronized.append(code_file)

        removed_file_names = sorted(set(existing_files) - target_names)
        if not preserve_stale:
            stale_query = CodeFileModel.objects(task_id=str(task.id))
            if target_names:
                stale_query = stale_query(file_name__nin=sorted(target_names))
            stale_query.delete()
        return TaskFileSyncResult(
            files=synchronized,
            added_file_names=sorted(added_file_names),
            changed_file_names=sorted(changed_file_names),
            reused_file_names=sorted(reused_file_names),
            removed_file_names=removed_file_names,
            changed_block_refs=changed_block_refs,
        )

    def _synchronize_blocks(self, code_file: CodeFileModel | None, target: ReviewTarget) -> list[CodeBlock]:
        completed_by_hash: dict[str, deque[CodeBlock]] = defaultdict(deque)
        incomplete_by_hash: dict[str, deque[CodeBlock]] = defaultdict(deque)
        if code_file is not None:
            for block in code_file.code_blocks:
                if not block.block_hash:
                    continue
                target_queue = completed_by_hash if self._block_completed(block) else incomplete_by_hash
                target_queue[block.block_hash].append(block)

        blocks: list[CodeBlock] = []
        for block_id, contents in enumerate(self.diff_service.split_code_blocks(target.diff_lines)):
            digest = code_block_hash(contents)
            if completed_by_hash[digest]:
                block = completed_by_hash[digest].popleft()
                block.block_id = block_id
                block.review_state = FILE_STATE_COMPLETED
                blocks.append(block)
                continue
            if incomplete_by_hash[digest]:
                block = incomplete_by_hash[digest].popleft()
                block.block_id = block_id
                block.contents = list(contents)
                block.review_state = FILE_STATE_PENDING
                blocks.append(block)
                continue
            blocks.append(self._new_pending_block(block_id, digest, contents))
        return blocks

    @staticmethod
    def _block_hashes(blocks: list[CodeBlock]) -> list[str]:
        return [block.block_hash or code_block_hash(list(block.contents or [])) for block in blocks]

    @classmethod
    def _changed_block_refs(
        cls,
        previous_hashes: list[str],
        blocks: list[CodeBlock],
    ) -> list[dict[str, object]]:
        remaining = Counter(previous_hashes)
        changed: list[dict[str, object]] = []
        for block in blocks:
            digest = block.block_hash or code_block_hash(list(block.contents or []))
            if remaining[digest] > 0:
                remaining[digest] -= 1
                continue
            changed.append({"block_id": block.block_id, "block_hash": digest})
        return changed

    @staticmethod
    def _new_pending_block(block_id: int, digest: str, contents: list[str]) -> CodeBlock:
        """Create a changed block without carrying any result from its previous contents."""
        return CodeBlock(
            block_id=block_id,
            block_hash=digest,
            review_fingerprint="",
            contents=list(contents),
            comment="",
            plan_change_summary="",
            plan_risk_level="",
            plan_checkpoints=[],
            related_files=[],
            static_findings=[],
            logic_score=0,
            performance_score=0,
            security_score=0,
            readable_score=0,
            code_style_score=0,
            comment_line_number=0,
            issues=[],
            process_time=0,
            llm_prompt_tokens=0,
            llm_completion_tokens=0,
            llm_total_tokens=0,
            llm_reasoning_tokens=0,
            llm_cached_tokens=0,
            llm_elapsed_ms=0,
            memory_compression_count=0,
            main_task_completed=False,
            main_task_completion_mode="",
            main_task_round_count=0,
            model_rounds=[],
            tool_calls=[],
            failure_message="",
            review_state=FILE_STATE_PENDING,
            review_attempt_count=0,
            update_time=utc_now(),
        )

    @staticmethod
    def _block_completed(block: CodeBlock) -> bool:
        return bool(block.main_task_completed) and not bool(block.failure_message)

    @staticmethod
    def _average_completed_scores(blocks: list[CodeBlock]) -> dict[str, int]:
        fields = ["logic_score", "performance_score", "security_score", "readable_score", "code_style_score"]
        completed = [block for block in blocks if TaskFileSynchronizer._block_completed(block)]
        if not completed:
            return {field: 0 for field in fields}
        return {
            field: round(sum(int(getattr(block, field, 0) or 0) for block in completed) / len(completed))
            for field in fields
        }


class TaskSubmissionService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def trigger(
        self,
        *,
        project_id: str,
        review_version: str,
        copy_from_version: str,
        review_version_path: str,
        copy_from_version_path: str = "",
        task_type: int | None = None,
        author_map_file: str = "",
        submitter: str | None = None,
        created_by: str = "jenkins",
    ) -> TaskModel:
        project_id = project_id.strip()
        review_version = review_version.strip()
        copy_from_version = copy_from_version.strip() or FULL_SCAN_BASE_VERSION
        review_path = self._normalize_directory(review_version_path, "review_version_path")
        task_type = self._resolve_task_type(copy_from_version, task_type)
        base_path = ""
        if TaskType(task_type).is_incremental:
            base_path = self._normalize_directory(copy_from_version_path, "copy_from_version_path")

        project = ProjectModel.objects(project_id=project_id).first()
        if project is None:
            project = ProjectModel(
                project_id=project_id,
                version_control_system="local-folder",
                created_by=created_by,
            ).save()

        identity = {
            "project_id": project_id,
            "review_version": review_version,
            "copy_from_version": copy_from_version,
        }
        submission_key = hashlib.sha256(
            json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        project = ProjectModel.objects(id=project.id).modify(
            new=True,
            inc__scan_round=1,
            set__update_time=utc_now(),
        )
        task = TaskModel.objects(submission_key=submission_key).first()
        if task is None:
            task = TaskModel.objects(**identity).order_by("-create_time").first()
        created = task is None
        author_map_path = self._normalize_author_map_file(
            author_map_file or (task.author_map_file if task is not None else "")
        )
        file_author_map = self._load_author_map(author_map_path)
        previous_state = TASK_STATE_PREPARING
        preserve_active_lease = False
        if task is None:
            try:
                task = TaskModel(
                    **identity,
                    review_version_path=review_path,
                    copy_from_version_path=base_path,
                    author_map_file=author_map_path,
                    submission_key=submission_key,
                    task_type=task_type,
                    state=TASK_STATE_PREPARING,
                    submitter=submitter,
                    created_by=created_by,
                    trigger_count=1,
                    trigger_revision=1,
                ).save()
            except NotUniqueError:
                task = TaskModel.objects(submission_key=submission_key).first()
                created = False
        if task is None:
            raise AppError("Failed to create or find review task", status_code=409, code="task_trigger_conflict")
        if not created:
            TaskModel.objects(id=task.id, trigger_count__exists=False).update_one(set__trigger_count=1)
            TaskModel.objects(id=task.id, trigger_revision__exists=False).update_one(set__trigger_revision=1)
            task.reload()
            previous_state = int(task.state or TASK_STATE_PENDING)
            preserve_active_lease = self._has_active_worker(task)
            updates = {
                "inc__trigger_count": 1,
                "inc__trigger_revision": 1,
                "set__submission_key": submission_key,
                "set__review_version_path": review_path,
                "set__copy_from_version_path": base_path,
                "set__author_map_file": author_map_path,
                "set__task_type": task_type,
                "set__state": TASK_STATE_PREPARING,
                "set__interrupt_requested": True,
                "set__completion_status": "preparing",
                "set__dispatch_priority": 0,
                "set__retry_failed_only": False,
                "set__automatic_retry_pending": False,
                "unset__next_retry_time": 1,
                "set__update_time": utc_now(),
            }
            if submitter:
                updates["set__submitter"] = submitter
            task = TaskModel.objects(id=task.id).modify(new=True, **updates)
            if task is None:
                raise AppError("Review task disappeared during trigger", status_code=409, code="task_trigger_conflict")

        snapshot = None
        try:
            excludes = list(project.exclude_path or [])
            diff_service = CodeDiffService(self.settings, excludes)
            if TaskType(task_type).is_incremental:
                collection = diff_service.compare_directories_with_context(Path(base_path), Path(review_path))
            else:
                collection = diff_service.scan_directory_with_context(Path(review_path))
            sync_result = TaskFileSynchronizer(diff_service).synchronize_with_result(
                task,
                collection,
                file_author_map=file_author_map,
            )
            files = sync_result.files
            if not created:
                snapshot_service = TaskSnapshotService()
                if sync_result.report_file_names or sync_result.removed_file_names:
                    snapshot = snapshot_service.create(
                        task,
                        changed_file_names=sync_result.report_file_names,
                        changed_block_refs=sync_result.changed_block_refs,
                        removed_file_names=sync_result.removed_file_names,
                    )
                else:
                    snapshot = snapshot_service.carry_forward(task)
        except Exception as exc:
            TaskModel.objects(id=task.id, trigger_revision=task.trigger_revision).update_one(
                set__state=3,
                set__completion_status="preparation_failed",
                set__interrupt_requested=False,
                set__update_time=utc_now(),
            )
            if isinstance(exc, AppError):
                raise
            raise AppError(f"Failed to prepare review task: {exc}", status_code=422, code="task_preparation_failed") from exc

        completed_file_num = sum(1 for item in files if item.state == FILE_STATE_COMPLETED)
        pending_file_num = len(files) - completed_file_num
        needs_finalization = (
            not created
            and pending_file_num == 0
            and (previous_state != TASK_STATE_COMPLETED or bool(sync_result.removed_file_names))
        )
        has_pending_work = pending_file_num > 0 or needs_finalization
        updates = {
            "set__state": TASK_STATE_PENDING if has_pending_work else TASK_STATE_COMPLETED,
            "set__interrupt_requested": False,
            "set__completion_status": "pending" if has_pending_work else "completed",
            "set__dispatch_priority": 0,
            "set__retry_failed_only": False,
            "set__automatic_retry_pending": False,
            "unset__next_retry_time": 1,
            "set__file_num": len(files),
            "set__reviewed_file_num": completed_file_num,
            "set__resumed_file_num": completed_file_num,
            "set__skipped_file_num": 0,
            "set__incomplete_file_num": 0,
            "set__code_block_num": sum(len(item.code_blocks) for item in files),
            "set__add_code_line_num": sum(item.add_code_line_num or 0 for item in files),
            "set__comment_line_number": sum(item.comment_line_number or 0 for item in files),
            "set__update_time": utc_now(),
        }
        if snapshot is not None:
            updates["set__latest_snapshot_id"] = snapshot.snapshot_id
        if has_pending_work:
            updates.update(
                {
                    "set__completion_email_sent": False,
                    "set__score": 0,
                    "set__logic_score": 0,
                    "set__performance_score": 0,
                    "set__security_score": 0,
                    "set__readable_score": 0,
                    "set__code_style_score": 0,
                    "set__task_model_rounds": [],
                    "set__project_summary": "",
                    "set__developer_issue_summary": {},
                }
            )
        if not preserve_active_lease:
            updates.update(
                {
                    "set__lease_owner": "",
                    "set__lease_token": "",
                    "unset__lease_expires_at": 1,
                    "unset__heartbeat_time": 1,
                }
            )

        finalized = TaskModel.objects(id=task.id, trigger_revision=task.trigger_revision).modify(
            new=True,
            **updates,
        )
        if finalized is not None:
            return finalized
        latest = TaskModel.objects(id=task.id).first()
        if latest is None:
            raise AppError("Review task disappeared during trigger", status_code=409, code="task_trigger_conflict")
        return latest

    @staticmethod
    def _normalize_directory(value: str, field_name: str) -> str:
        if not str(value or "").strip():
            raise AppError(f"{field_name} is required", status_code=422, code="validation_error")
        path = Path(value).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            raise AppError(f"{field_name} does not exist or is not a directory: {path}", status_code=422)
        return str(path)

    def _normalize_author_map_file(self, value: str) -> str:
        if not str(value or "").strip():
            return ""
        path = Path(value).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise AppError(f"author_map_file does not exist or is not a file: {path}", status_code=422)
        repository_root = str(self.settings.code_repository_root or "").strip()
        if repository_root:
            root = Path(repository_root).expanduser().resolve()
            if not path.is_relative_to(root):
                raise AppError("author_map_file must be inside CODE_REPOSITORY_ROOT", status_code=422)
        return str(path)

    @staticmethod
    def _load_author_map(path: str) -> dict[str, str]:
        if not path:
            return {}
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AppError(f"Failed to read author_map_file: {exc}", status_code=422) from exc
        if not isinstance(raw, dict):
            raise AppError("author_map_file must contain a JSON object", status_code=422)
        result: dict[str, str] = {}
        for file_name, account in raw.items():
            normalized_name = str(file_name or "").strip().replace("\\", "/").lstrip("./")
            normalized_account = str(account or "").strip()
            if normalized_name and normalized_account:
                result[normalized_name] = normalized_account
        return result

    @staticmethod
    def _resolve_task_type(copy_from_version: str, requested_task_type: int | None) -> int:
        if copy_from_version == FULL_SCAN_BASE_VERSION:
            return TaskType.FULL_SCAN.value
        if requested_task_type is None:
            return TaskType.DEV_VERSION.value
        try:
            normalized = TaskType(int(requested_task_type))
        except (TypeError, ValueError) as exc:
            raise AppError("task_type must be 1, 2, or 3", status_code=422) from exc
        if not normalized.is_incremental:
            raise AppError("incremental review task_type must be 1 or 2", status_code=422)
        return normalized.value

    @staticmethod
    def _has_active_worker(task: TaskModel) -> bool:
        if task.state != TASK_STATE_RUNNING or not task.lease_token or task.lease_expires_at is None:
            return False
        expires_at = task.lease_expires_at
        now = utc_now()
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=now.tzinfo)
        return expires_at > now
