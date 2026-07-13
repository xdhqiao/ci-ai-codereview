from __future__ import annotations

import math
from dataclasses import dataclass

from mongoengine import ValidationError

from app.core.exceptions import NotFoundError
from app.models.code_file import CodeBlock, CodeFileModel, Issue
from app.models.task import TaskModel
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
    ScoreResponse,
    TaskReportResponse,
)
from app.services.diff_service import TASK_TYPE_INCREMENTAL


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
    ) -> TaskReportResponse:
        task = self.find_task_by_comparison(project_id, comparison)
        return self.get_report(
            str(task.id),
            author=author,
            page=page,
            page_size=page_size,
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
    ) -> TaskReportResponse:
        task = self._find_task(task_id)
        all_files = list(CodeFileModel.objects(task_id=str(task.id)).order_by("file_name"))
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

        return TaskReportResponse(
            overview=ReportOverviewResponse(
                task_id=str(task.id),
                project_id=task.project_id,
                review_version=task.review_version,
                copy_from_version=task.copy_from_version,
                task_type=task.task_type or 0,
                review_mode="incremental" if task.task_type == TASK_TYPE_INCREMENTAL else "full",
                state=task.state,
                completion_status=task.completion_status or "",
                create_time=task.create_time,
                update_time=task.update_time,
                process_time_ms=task.process_time or 0,
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
                reviewed_file_num=task.reviewed_file_num or 0,
                code_block_num=sum(len(code_file.code_blocks) for code_file in all_files),
                issue_num=len(valid_issues),
                filtered_issue_num=filtered_issue_num,
                critical_issue_num=sum(1 for issue in valid_issues if issue.severity >= 4),
                tool_call_num=tool_call_num,
                model_round_num=model_round_num,
                memory_compression_num=memory_compression_num,
                incomplete_file_num=task.incomplete_file_num or 0,
            ),
            authors=authors,
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

    def _file_response(self, code_file: CodeFileModel, task_type: int) -> ReportFileResponse:
        weighted = self._weighted_scores([code_file], task_type)
        return ReportFileResponse(
            file_id=str(code_file.id),
            file_name=code_file.file_name,
            file_author=(code_file.file_author or "").strip(),
            changed_line_num=weighted.weight,
            added_line_num=code_file.add_code_line_num or 0,
            overall_score=self._overall_score(weighted.scores),
            scores=ScoreResponse(**weighted.scores),
            blocks=[self._block_response(block, task_type) for block in code_file.code_blocks],
        )

    def _block_response(self, block: CodeBlock, task_type: int) -> ReportBlockResponse:
        scores = {field: self._bounded_score(getattr(block, field, 0)) for field in SCORE_FIELDS}
        return ReportBlockResponse(
            block_id=block.block_id,
            changed_line_num=self._block_weight(block, task_type),
            overall_score=self._overall_score(scores),
            scores=ScoreResponse(**scores),
            contents=list(block.contents or []),
            comment=block.comment or "",
            issues=[self._issue_response(issue) for issue in block.issues if self._is_reportable_issue(issue)],
        )

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
        code_files: list[CodeFileModel],
    ) -> tuple[list[CriticalIssueResponse], int | None]:
        candidates: list[tuple[CodeFileModel, CodeBlock, Issue]] = []
        for code_file in code_files:
            for block in code_file.code_blocks:
                for issue in block.issues:
                    if self._is_reportable_issue(issue):
                        candidates.append((code_file, block, issue))
        if not candidates:
            return [], None
        highest_severity = max(issue.severity or 0 for _, _, issue in candidates)
        highest = [item for item in candidates if (item[2].severity or 0) == highest_severity]
        highest.sort(key=lambda item: (item[0].file_name, item[1].block_id, item[2].issue_id or 0))
        return [
            CriticalIssueResponse(
                file_id=str(code_file.id),
                block_id=block.block_id,
                issue_id=issue.issue_id if issue.issue_id is not None else 0,
                file_name=code_file.file_name,
                file_author=(code_file.file_author or "").strip(),
                severity=issue.severity or 0,
                issue_line_numbers=issue.issue_line_numbers or "",
                type=issue.type or "",
                description=issue.description or "",
                suggestion=issue.suggestion or "",
            )
            for code_file, block, issue in highest
        ], highest_severity

    def _weighted_scores(self, code_files: list[CodeFileModel], task_type: int) -> WeightedScores:
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
        if task_type == TASK_TYPE_INCREMENTAL:
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
