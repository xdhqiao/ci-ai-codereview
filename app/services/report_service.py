from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

from mongoengine import ValidationError

from app.common.constant import SEVERE_ISSUE_SEVERITY, is_incremental_task_type
from app.common.utils import get_user_display_name
from app.core.exceptions import NotFoundError
from app.models.code_file import CodeBlock, CodeFileModel, Issue
from app.models.code_file_snapshot import CodeFileSnapshotModel
from app.models.task import TaskModel
from app.models.task_snapshot import TaskSnapshotModel
from app.schemas.report import (
    CriticalIssueResponse,
    FeedbackRequest,
    FeedbackResponse,
    ReportBlockResponse,
    ReportFileResponse,
    ReportIssueResponse,
    ReportMetricsResponse,
    ReportOverviewResponse,
    ReportPaginationResponse,
    ReportProgressResponse,
    ScoreResponse,
    TaskReportResponse,
)
from app.services.task_snapshot import TaskSnapshotService


SCORE_FIELDS = (
    "logic_score",
    "performance_score",
    "security_score",
    "readable_score",
    "code_style_score",
)


@dataclass(frozen=True)
class WeightedScores:
    scores: dict[str, int]
    weight: int


class TaskReportService:
    def get_report_by_comparison(
        self,
        project_id: str,
        comparison: str,
        *,
        author: str = "",
        page: int = 1,
        page_size: int = 300,
        trigger_revision: int | None = None,
    ) -> TaskReportResponse:
        task = self.find_task_by_comparison(project_id, comparison)
        return self.get_report(
            str(task.id),
            author=author,
            page=page,
            page_size=page_size,
            trigger_revision=trigger_revision,
        )

    def find_task_by_comparison(self, project_id: str, comparison: str) -> TaskModel:
        if "_vs_" not in comparison:
            raise NotFoundError("Review report not found")
        review_version, copy_from_version = comparison.rsplit("_vs_", 1)
        if not project_id or not review_version or not copy_from_version:
            raise NotFoundError("Review report not found")
        task = (
            TaskModel.objects(
                project_id=project_id,
                review_version=review_version,
                copy_from_version=copy_from_version,
            )
            .order_by("-create_time")
            .first()
        )
        if task is None:
            raise NotFoundError("Review report not found")
        return task

    def get_report(
        self,
        task_id: str,
        *,
        author: str = "",
        page: int = 1,
        page_size: int = 300,
        trigger_revision: int | None = None,
    ) -> TaskReportResponse:
        task = self._find_task(task_id)
        if trigger_revision is not None:
            snapshot = TaskSnapshotModel.objects(
                task_id=str(task.id),
                trigger_revision=trigger_revision,
            ).first()
            if snapshot is None:
                raise NotFoundError("Task snapshot not found")
            return self._snapshot_report(
                snapshot,
                author=author,
                page=page,
                page_size=page_size,
            )
        all_files = list(CodeFileModel.objects(task_id=str(task.id)).order_by("file_name"))
        return self._build_report(
            task,
            all_files,
            author=author,
            page=page,
            page_size=page_size,
            view_mode="latest",
        )

    def get_snapshot_report(
        self,
        snapshot_id: str,
        project_id: str,
        comparison: str,
        *,
        author: str = "",
        page: int = 1,
        page_size: int = 300,
    ) -> TaskReportResponse:
        snapshot = self.find_snapshot(snapshot_id, project_id, comparison)
        return self._snapshot_report(
            snapshot,
            author=author,
            page=page,
            page_size=page_size,
        )

    def find_snapshot(
        self,
        snapshot_id: str,
        project_id: str,
        comparison: str,
    ) -> TaskSnapshotModel:
        if "_vs_" not in comparison:
            raise NotFoundError("Review snapshot not found")
        review_version, copy_from_version = comparison.rsplit("_vs_", 1)
        snapshot = TaskSnapshotModel.objects(
            snapshot_id=snapshot_id,
            project_id=project_id,
            review_version=review_version,
            copy_from_version=copy_from_version,
        ).first()
        if snapshot is None:
            raise NotFoundError("Review snapshot not found")
        return snapshot

    def _snapshot_report(
        self,
        snapshot: TaskSnapshotModel,
        *,
        author: str,
        page: int,
        page_size: int,
    ) -> TaskReportResponse:
        all_files = list(
            CodeFileSnapshotModel.objects(snapshot_id=snapshot.snapshot_id).order_by("file_name")
        )
        return self._build_report(
            snapshot,
            all_files,
            author=author,
            page=page,
            page_size=page_size,
            view_mode="snapshot",
            snapshot=snapshot,
        )

    def _build_report(
        self,
        task: TaskModel | TaskSnapshotModel,
        all_files: list[CodeFileModel] | list[CodeFileSnapshotModel],
        *,
        author: str,
        page: int,
        page_size: int,
        view_mode: str,
        snapshot: TaskSnapshotModel | None = None,
    ) -> TaskReportResponse:
        authors = sorted({value.file_author.strip() for value in all_files if (value.file_author or "").strip()})
        selected_author = author.strip()
        if selected_author and selected_author not in authors:
            selected_author = ""

        filtered_files = [
            code_file
            for code_file in all_files
            if not selected_author or (code_file.file_author or "").strip() == selected_author
        ]
        total_items = len(filtered_files)
        total_pages = math.ceil(total_items / page_size) if total_items else 0
        normalized_page = min(page, total_pages) if total_pages else 1
        start = (normalized_page - 1) * page_size
        page_files = filtered_files[start : start + page_size]

        task_scores = self._weighted_scores(all_files, task.task_type or 0)
        changed_line_num = sum(
            self._block_weight(block, task.task_type or 0)
            for code_file in all_files
            for block in code_file.code_blocks
        )
        valid_issues = [
            issue
            for code_file in all_files
            for block in code_file.code_blocks
            for issue in block.issues
            if self._is_reportable_issue(issue)
        ]
        filtered_issue_num = sum(
            1
            for code_file in all_files
            for block in code_file.code_blocks
            for issue in block.issues
            if not self._is_reportable_issue(issue)
        )
        critical_issues, highest_severity = self._critical_issues(filtered_files)
        tool_call_num = sum(
            len(block.tool_calls) for code_file in all_files for block in code_file.code_blocks
        )
        model_round_num = len(task.task_model_rounds or []) + sum(
            len(block.model_rounds) for code_file in all_files for block in code_file.code_blocks
        )
        memory_compression_num = sum(
            block.memory_compression_count or 0
            for code_file in all_files
            for block in code_file.code_blocks
        )
        progress = self._progress_response(task, all_files)

        return TaskReportResponse(
            overview=ReportOverviewResponse(
                task_id=snapshot.task_id if snapshot is not None else str(task.id),
                project_id=task.project_id,
                review_version=task.review_version,
                copy_from_version=task.copy_from_version,
                view_mode=view_mode,
                snapshot_id=snapshot.snapshot_id if snapshot is not None else "",
                snapshot_url=TaskSnapshotService.report_path(snapshot) if snapshot is not None else "",
                trigger_revision=snapshot.trigger_revision if snapshot is not None else None,
                trigger_count=task.trigger_count or 0,
                removed_file_names=list(snapshot.removed_file_names or []) if snapshot is not None else [],
                task_type=task.task_type or 0,
                review_mode="incremental" if is_incremental_task_type(task.task_type) else "full",
                state=task.state,
                completion_status=task.completion_status or "",
                create_time=task.create_time,
                update_time=task.update_time,
                process_time_ms=self._live_process_time(task),
                changed_line_num=changed_line_num,
                added_line_num=sum(code_file.add_code_line_num or 0 for code_file in all_files),
                overall_score=self._overall_score(task_scores.scores),
                scores=ScoreResponse(**task_scores.scores),
            ),
            metrics=ReportMetricsResponse(
                total_tokens=task.llm_total_tokens or 0,
                prompt_tokens=task.llm_prompt_tokens or 0,
                completion_tokens=task.llm_completion_tokens or 0,
                llm_elapsed_ms=task.llm_elapsed_ms or 0,
                file_num=len(all_files),
                reviewed_file_num=progress.completed_file_num,
                code_block_num=sum(len(code_file.code_blocks) for code_file in all_files),
                issue_num=len(valid_issues),
                filtered_issue_num=filtered_issue_num,
                critical_issue_num=sum(
                    1 for issue in valid_issues if issue.severity == SEVERE_ISSUE_SEVERITY
                ),
                tool_call_num=tool_call_num,
                model_round_num=model_round_num,
                memory_compression_num=memory_compression_num,
                incomplete_file_num=progress.failed_file_num,
            ),
            progress=progress,
            authors=authors,
            author_name_map={author: get_user_display_name(author) for author in authors},
            selected_author=selected_author,
            highest_severity=highest_severity,
            critical_issues=critical_issues,
            pagination=ReportPaginationResponse(
                page=normalized_page,
                page_size=page_size,
                total_items=total_items,
                total_pages=total_pages,
            ),
            files=[self._file_response(code_file, task.task_type or 0) for code_file in page_files],
        )

    def save_feedback(
        self,
        file_id: str,
        block_id: int,
        issue_id: int,
        payload: FeedbackRequest,
    ) -> FeedbackResponse:
        try:
            code_file = CodeFileModel.objects(id=file_id).first()
        except (ValidationError, ValueError):
            code_file = None
        if code_file is None:
            try:
                code_file = CodeFileSnapshotModel.objects(id=file_id).first()
            except (ValidationError, ValueError):
                code_file = None
        if code_file is None:
            raise NotFoundError("Code file not found")

        block = next((item for item in code_file.code_blocks if item.block_id == block_id), None)
        if block is None:
            raise NotFoundError("Code block not found")
        issue = next((item for item in block.issues if item.issue_id == issue_id), None)
        if issue is None:
            raise NotFoundError("Issue not found")

        issue.feedback_type = payload.feedback_type
        issue.feedback_content = payload.feedback_content
        code_file.save()
        return FeedbackResponse(
            file_id=str(code_file.id),
            block_id=block_id,
            issue_id=issue_id,
            feedback_type=issue.feedback_type or "",
            feedback_content=issue.feedback_content or "",
        )

    def _find_task(self, task_id: str) -> TaskModel:
        try:
            task = TaskModel.objects(id=task_id).first()
        except (ValidationError, ValueError):
            task = None
        if task is None:
            raise NotFoundError("Task not found")
        return task

    def _file_response(
        self,
        code_file: CodeFileModel | CodeFileSnapshotModel,
        task_type: int,
    ) -> ReportFileResponse:
        weighted = self._weighted_scores([code_file], task_type)
        block_statuses = [self._block_status(block, code_file) for block in code_file.code_blocks]
        return ReportFileResponse(
            file_id=str(code_file.id),
            file_name=code_file.file_name,
            file_author=(code_file.file_author or "").strip(),
            file_author_name=get_user_display_name((code_file.file_author or "").strip()),
            review_state=code_file.state or 0,
            status=self._file_status(code_file),
            completed_block_num=sum(1 for status in block_statuses if status == "completed"),
            failed_block_num=sum(1 for status in block_statuses if status == "failed"),
            changed_line_num=weighted.weight,
            added_line_num=code_file.add_code_line_num or 0,
            overall_score=self._overall_score(weighted.scores),
            scores=ScoreResponse(**weighted.scores),
            blocks=[self._block_response(block, task_type, code_file) for block in code_file.code_blocks],
        )

    def _block_response(
        self,
        block: CodeBlock,
        task_type: int,
        code_file: CodeFileModel | None = None,
    ) -> ReportBlockResponse:
        scores = {field: self._bounded_score(getattr(block, field, 0)) for field in SCORE_FIELDS}
        return ReportBlockResponse(
            block_id=block.block_id,
            review_state=block.review_state or 0,
            status=self._block_status(block, code_file),
            process_time_ms=block.process_time or 0,
            main_task_completed=bool(block.main_task_completed),
            completion_mode=block.main_task_completion_mode or "",
            failure_message=block.failure_message or "",
            changed_line_num=self._block_weight(block, task_type),
            overall_score=self._overall_score(scores),
            scores=ScoreResponse(**scores),
            contents=list(block.contents or []),
            comment=block.comment or "",
            issues=[self._issue_response(issue) for issue in block.issues if self._is_reportable_issue(issue)],
        )

    def _progress_response(
        self,
        task: TaskModel | TaskSnapshotModel,
        code_files: list[CodeFileModel] | list[CodeFileSnapshotModel],
    ) -> ReportProgressResponse:
        block_statuses_by_file = [
            (code_file, [self._block_status(block, code_file) for block in code_file.code_blocks])
            for code_file in code_files
        ]
        file_statuses = [self._file_status(code_file) for code_file in code_files]
        block_statuses = [status for _, statuses in block_statuses_by_file for status in statuses]
        completed_blocks = block_statuses.count("completed")
        reviewing_blocks = block_statuses.count("reviewing")
        pending_blocks = block_statuses.count("pending")
        failed_blocks = block_statuses.count("failed")
        total_blocks = len(block_statuses)
        if total_blocks:
            percentage = round(completed_blocks * 100 / total_blocks)
        elif code_files:
            percentage = round(file_statuses.count("completed") * 100 / len(code_files))
        elif task.state == 2:
            percentage = 100
        else:
            percentage = 0
        retry_in_progress = bool(task.retry_failed_only) and task.state in {0, 1}
        retryable_file_num = sum(1 for _, statuses in block_statuses_by_file if "failed" in statuses)
        retry_available = (
            percentage < 100
            and failed_blocks > 0
            and pending_blocks == 0
            and reviewing_blocks == 0
            and task.state == 3
            and not retry_in_progress
        )
        return ReportProgressResponse(
            percentage=min(100, max(0, percentage)),
            total_file_num=len(code_files),
            completed_file_num=file_statuses.count("completed"),
            reviewing_file_num=file_statuses.count("reviewing"),
            pending_file_num=file_statuses.count("pending"),
            failed_file_num=file_statuses.count("failed"),
            total_block_num=total_blocks,
            completed_block_num=completed_blocks,
            reviewing_block_num=reviewing_blocks,
            pending_block_num=pending_blocks,
            failed_block_num=failed_blocks,
            retryable_file_num=retryable_file_num,
            retryable_block_num=failed_blocks,
            retry_available=retry_available,
            retry_in_progress=retry_in_progress,
            manual_retry_count=task.manual_retry_count or 0,
            next_retry_time=task.next_retry_time,
            auto_refresh_seconds=5,
        )

    def _file_status(self, code_file: CodeFileModel | CodeFileSnapshotModel) -> str:
        statuses = [self._block_status(block, code_file) for block in code_file.code_blocks]
        extra_status = str((code_file.extra or {}).get("status") or "")
        if extra_status == "skipped_budget":
            return "failed"
        if statuses and all(status == "completed" for status in statuses):
            return "completed"
        if code_file.state == 1 or "reviewing" in statuses:
            return "reviewing"
        if code_file.state == 3 or "failed" in statuses or extra_status == "partial":
            return "failed"
        return "pending"

    def _block_status(
        self,
        block: CodeBlock,
        code_file: CodeFileModel | CodeFileSnapshotModel | None = None,
    ) -> str:
        if block.failure_message or block.review_state == 3:
            return "failed"
        if block.main_task_completed or block.review_state == 2:
            return "completed"
        if code_file is not None:
            file_status = str((code_file.extra or {}).get("status") or "")
            if code_file.state == 2 or file_status in {"reviewed", "resumed"}:
                return "completed"
        if block.review_state == 1:
            return "reviewing"
        return "pending"

    def _live_process_time(self, task: TaskModel | TaskSnapshotModel) -> int:
        process_time = int(task.process_time or 0)
        if task.state != 1 or task.last_start_time is None:
            return process_time
        started = task.last_start_time
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        return process_time + max(0, int((datetime.now(timezone.utc) - started).total_seconds() * 1000))

    def _issue_response(self, issue: Issue) -> ReportIssueResponse:
        return ReportIssueResponse(
            issue_id=issue.issue_id if issue.issue_id is not None else 0,
            severity=issue.severity or 0,
            issue_line_numbers=issue.issue_line_numbers or "",
            type=issue.type or "",
            description=issue.description or "",
            suggestion=issue.suggestion or "",
            feedback_type=issue.feedback_type or "",
            feedback_content=issue.feedback_content or "",
        )

    def _critical_issues(
        self,
        code_files: list[CodeFileModel] | list[CodeFileSnapshotModel],
    ) -> tuple[list[CriticalIssueResponse], int | None]:
        candidates: list[tuple[CodeFileModel | CodeFileSnapshotModel, CodeBlock, Issue]] = []
        for code_file in code_files:
            for block in code_file.code_blocks:
                for issue in block.issues:
                    if self._is_reportable_issue(issue):
                        candidates.append((code_file, block, issue))
        candidates = [
            item for item in candidates if (item[2].severity or 0) == SEVERE_ISSUE_SEVERITY
        ]
        if not candidates:
            return [], None
        highest_severity = SEVERE_ISSUE_SEVERITY
        highest = candidates
        highest.sort(key=lambda item: (item[0].file_name, item[1].block_id, item[2].issue_id or 0))
        return [
            CriticalIssueResponse(
                file_id=str(code_file.id),
                block_id=block.block_id,
                issue_id=issue.issue_id if issue.issue_id is not None else 0,
                file_name=code_file.file_name,
                file_author=(code_file.file_author or "").strip(),
                file_author_name=get_user_display_name((code_file.file_author or "").strip()),
                severity=issue.severity or 0,
                issue_line_numbers=issue.issue_line_numbers or "",
                type=issue.type or "",
                description=issue.description or "",
                suggestion=issue.suggestion or "",
            )
            for code_file, block, issue in highest
        ], highest_severity

    def _weighted_scores(
        self,
        code_files: list[CodeFileModel] | list[CodeFileSnapshotModel],
        task_type: int,
    ) -> WeightedScores:
        totals = {field: 0 for field in SCORE_FIELDS}
        total_weight = 0
        for code_file in code_files:
            for block in code_file.code_blocks:
                weight = self._block_weight(block, task_type)
                total_weight += weight
                for field in SCORE_FIELDS:
                    totals[field] += self._bounded_score(getattr(block, field, 0)) * weight
        if not total_weight:
            return WeightedScores(scores={field: 0 for field in SCORE_FIELDS}, weight=0)
        return WeightedScores(
            scores={field: round(totals[field] / total_weight) for field in SCORE_FIELDS},
            weight=total_weight,
        )

    def _block_weight(self, block: CodeBlock, task_type: int) -> int:
        lines = list(block.contents or [])
        if is_incremental_task_type(task_type):
            changed = sum(1 for line in lines if len(line) > 6 and line[6] in {"+", "-"})
        else:
            changed = len(lines)
        return max(1, changed) if lines else 0

    def _is_reportable_issue(self, issue: Issue) -> bool:
        return (issue.filter_status or "").lower() != "filtered"

    def _overall_score(self, scores: dict[str, int]) -> int:
        return round(sum(scores.values()) / len(SCORE_FIELDS)) if scores else 0

    def _bounded_score(self, value: int | None) -> int:
        return min(100, max(0, int(value or 0)))
