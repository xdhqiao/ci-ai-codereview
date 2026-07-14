from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from pathlib import Path

from mongoengine.errors import NotUniqueError

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.models.code_file import CodeBlock, CodeFileModel
from app.models.project import ProjectModel
from app.models.task import TaskModel, utc_now
from app.services.diff_service import (
    TASK_TYPE_FULL_SCAN,
    TASK_TYPE_INCREMENTAL,
    CodeDiffService,
    ReviewCollection,
    ReviewTarget,
)
TASK_STATE_PENDING = 0
TASK_STATE_PREPARING = 4
FILE_STATE_PENDING = 0
FILE_STATE_COMPLETED = 2


def code_block_hash(lines: list[str]) -> str:
    return hashlib.md5("\n".join(lines).encode("utf-8")).hexdigest()


def review_target_hash(target: ReviewTarget) -> str:
    payload = "\n".join([target.file_name, target.language, target.full_code, *target.diff_lines])
    return hashlib.md5(payload.encode("utf-8")).hexdigest()


class TaskFileSynchronizer:
    def __init__(self, diff_service: CodeDiffService) -> None:
        self.diff_service = diff_service

    def synchronize(self, task: TaskModel, collection: ReviewCollection) -> list[CodeFileModel]:
        existing_files = {
            item.file_name: item for item in CodeFileModel.objects(task_id=str(task.id))
        }
        synchronized: list[CodeFileModel] = []
        target_names: set[str] = set()

        for target in collection.targets:
            target_names.add(target.file_name)
            code_file = existing_files.get(target.file_name)
            source_hash = review_target_hash(target)
            blocks = self._synchronize_blocks(code_file, target)
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

            previous_source_hash = code_file.source_hash or str((code_file.extra or {}).get("source_hash") or "")
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

        stale_query = CodeFileModel.objects(task_id=str(task.id))
        if target_names:
            stale_query = stale_query(file_name__nin=sorted(target_names))
        stale_query.delete()
        return synchronized

    def _synchronize_blocks(self, code_file: CodeFileModel | None, target: ReviewTarget) -> list[CodeBlock]:
        reusable: dict[str, deque[CodeBlock]] = defaultdict(deque)
        if code_file is not None:
            for block in code_file.code_blocks:
                if block.block_hash and self._block_completed(block):
                    reusable[block.block_hash].append(block)

        blocks: list[CodeBlock] = []
        for block_id, contents in enumerate(self.diff_service.split_code_blocks(target.diff_lines)):
            digest = code_block_hash(contents)
            if reusable[digest]:
                block = reusable[digest].popleft()
                block.block_id = block_id
                block.review_state = FILE_STATE_COMPLETED
                blocks.append(block)
                continue
            blocks.append(
                CodeBlock(
                    block_id=block_id,
                    block_hash=digest,
                    contents=list(contents),
                    review_state=FILE_STATE_PENDING,
                    main_task_completed=False,
                )
            )
        return blocks

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
        submitter: str | None = None,
        created_by: str = "jenkins",
    ) -> TaskModel:
        project_id = project_id.strip()
        review_version = review_version.strip()
        copy_from_version = copy_from_version.strip() or "0_version"
        review_path = self._normalize_directory(review_version_path, "review_version_path")
        task_type = TASK_TYPE_FULL_SCAN if copy_from_version == "0_version" else TASK_TYPE_INCREMENTAL
        base_path = ""
        if task_type == TASK_TYPE_INCREMENTAL:
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
            "review_version_path": review_path,
            "copy_from_version_path": base_path,
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
        if task is None:
            try:
                task = TaskModel(
                    **identity,
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
            updates = {
                "inc__trigger_count": 1,
                "inc__trigger_revision": 1,
                "set__submission_key": submission_key,
                "set__task_type": task_type,
                "set__state": TASK_STATE_PREPARING,
                "set__interrupt_requested": True,
                "set__completion_status": "preparing",
                "set__completion_email_sent": False,
                "set__update_time": utc_now(),
            }
            if submitter:
                updates["set__submitter"] = submitter
            task = TaskModel.objects(id=task.id).modify(new=True, **updates)
            if task is None:
                raise AppError("Review task disappeared during trigger", status_code=409, code="task_trigger_conflict")

        try:
            excludes = list(project.exclude_path or [])
            diff_service = CodeDiffService(self.settings, excludes)
            if task_type == TASK_TYPE_INCREMENTAL:
                collection = diff_service.compare_directories_with_context(Path(base_path), Path(review_path))
            else:
                collection = diff_service.scan_directory_with_context(Path(review_path))
            files = TaskFileSynchronizer(diff_service).synchronize(task, collection)
        except Exception as exc:
            task.state = 3
            task.completion_status = "preparation_failed"
            task.update_time = utc_now()
            task.save()
            if isinstance(exc, AppError):
                raise
            raise AppError(f"Failed to prepare review task: {exc}", status_code=422, code="task_preparation_failed") from exc

        task.state = TASK_STATE_PENDING
        task.interrupt_requested = False
        task.completion_status = "pending"
        task.file_num = len(files)
        task.reviewed_file_num = sum(1 for item in files if item.state == FILE_STATE_COMPLETED)
        task.code_block_num = sum(len(item.code_blocks) for item in files)
        task.add_code_line_num = sum(item.add_code_line_num or 0 for item in files)
        task.update_time = utc_now()
        task.save()
        return task

    @staticmethod
    def _normalize_directory(value: str, field_name: str) -> str:
        if not str(value or "").strip():
            raise AppError(f"{field_name} is required", status_code=422, code="validation_error")
        path = Path(value).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            raise AppError(f"{field_name} does not exist or is not a directory: {path}", status_code=422)
        return str(path)
