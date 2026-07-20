from __future__ import annotations

import logging
from dataclasses import dataclass
from html import escape
from urllib.parse import quote

from app.common.constant import EMPTY_FILE_AUTHOR_DISPLAY_NAME, SEVERE_ISSUE_SEVERITY
from app.common.utils import get_user_display_name
from app.core.config import Settings, get_settings
from app.models.code_file import CodeFileModel, Issue
from app.models.task import TaskModel
from app.services.email_service import EmailServer


logger = logging.getLogger(__name__)
EMAIL_TEMPLATE = "review_completed_email.html"


@dataclass(frozen=True)
class OwnerIssueSummary:
    account: str
    display_name: str
    severe_issue_count: int
    other_issue_count: int


@dataclass(frozen=True)
class SevereIssueRow:
    account: str
    file_name: str
    line_numbers: str
    issue_type: str
    description: str
    suggestion: str


class ReviewNotificationService:
    def __init__(
        self,
        settings: Settings | None = None,
        email_server: EmailServer | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.email_server = email_server or EmailServer(self.settings)

    def send_review_completed(self, task: TaskModel) -> bool:
        owner_summaries, severe_issues = self._collect_issues(task)
        subject = f"代码审核完成：{task.project_id} {task.review_version}_vs_{task.copy_from_version}"

        admin_receivers = self.settings.email_admin_receiver_list
        if admin_receivers:
            self.email_server.send(
                subject=subject,
                email_template=EMAIL_TEMPLATE,
                parameters=self._parameters(task, owner_summaries, severe_issues),
                receivers=admin_receivers,
            )
        else:
            logger.info("Review completion administrator email skipped: no administrator receivers configured")

        for summary in owner_summaries:
            receiver = self._owner_receiver(summary.account)
            if not receiver:
                logger.info(
                    "Review completion owner email skipped: task_id=%s owner=%s reason=no receiver",
                    task.id,
                    summary.display_name,
                )
                continue
            owner_severe_issues = [item for item in severe_issues if item.account == summary.account]
            self.email_server.send(
                subject=subject,
                email_template=EMAIL_TEMPLATE,
                parameters=self._parameters(task, [summary], owner_severe_issues),
                receivers=[receiver],
            )
        return True

    def _collect_issues(self, task: TaskModel) -> tuple[list[OwnerIssueSummary], list[SevereIssueRow]]:
        counters: dict[str, dict[str, int]] = {}
        severe_issues: list[SevereIssueRow] = []
        code_files = CodeFileModel.objects(task_id=str(task.id)).order_by("file_name")
        for code_file in code_files:
            account = (code_file.file_author or "").strip()
            for block in code_file.code_blocks:
                for issue in block.issues:
                    if not self._is_reportable_issue(issue):
                        continue
                    counter = counters.setdefault(account, {"severe": 0, "other": 0})
                    if int(issue.severity or 0) == SEVERE_ISSUE_SEVERITY:
                        counter["severe"] += 1
                        severe_issues.append(
                            SevereIssueRow(
                                account=account,
                                file_name=code_file.file_name,
                                line_numbers=issue.issue_line_numbers or "",
                                issue_type=issue.type or "",
                                description=issue.description or "",
                                suggestion=issue.suggestion or "",
                            )
                        )
                    else:
                        counter["other"] += 1

        owner_summaries = [
            OwnerIssueSummary(
                account=account,
                display_name=(
                    get_user_display_name(account) if account else EMPTY_FILE_AUTHOR_DISPLAY_NAME
                ),
                severe_issue_count=counts["severe"],
                other_issue_count=counts["other"],
            )
            for account, counts in counters.items()
        ]
        owner_summaries.sort(key=lambda item: (item.display_name, item.account))
        severe_issues.sort(key=lambda item: (item.file_name, item.line_numbers, item.issue_type))
        return owner_summaries, severe_issues

    def _parameters(
        self,
        task: TaskModel,
        owner_summaries: list[OwnerIssueSummary],
        severe_issues: list[SevereIssueRow],
    ) -> dict[str, object]:
        report_path = self._report_path(task)
        return {
            "project_id": escape(task.project_id),
            "review_version": escape(task.review_version),
            "copy_from_version": escape(task.copy_from_version),
            "score": int(task.score or 0),
            "logic_score": int(task.logic_score or 0),
            "performance_score": int(task.performance_score or 0),
            "security_score": int(task.security_score or 0),
            "readable_score": int(task.readable_score or 0),
            "code_style_score": int(task.code_style_score or 0),
            "owner_rows": self._owner_rows(owner_summaries),
            "severe_issue_rows": self._severe_issue_rows(severe_issues),
            "report_path": escape(report_path),
            "report_url": escape(f"{self.settings.email_report_base_url.rstrip('/')}{report_path}", quote=True),
        }

    @staticmethod
    def _owner_rows(owner_summaries: list[OwnerIssueSummary]) -> str:
        if not owner_summaries:
            return '<tr><td colspan="3" style="padding:9px;border:1px solid #d9e0e8;">暂无问题</td></tr>'
        return "".join(
            (
                '<tr><td style="padding:9px;border:1px solid #d9e0e8;">'
                f"{escape(summary.display_name)}</td>"
                '<td style="padding:9px;border:1px solid #d9e0e8;text-align:right;">'
                f"{summary.severe_issue_count}</td>"
                '<td style="padding:9px;border:1px solid #d9e0e8;text-align:right;">'
                f"{summary.other_issue_count}</td></tr>"
            )
            for summary in owner_summaries
        )

    @staticmethod
    def _severe_issue_rows(severe_issues: list[SevereIssueRow]) -> str:
        if not severe_issues:
            return '<tr><td colspan="6" style="padding:9px;border:1px solid #d9e0e8;">暂无严重问题</td></tr>'
        return "".join(
            (
                '<tr><td style="padding:9px;border:1px solid #d9e0e8;text-align:center;">'
                f"{index}</td>"
                f'<td style="padding:9px;border:1px solid #d9e0e8;">{escape(issue.file_name)}</td>'
                f'<td style="padding:9px;border:1px solid #d9e0e8;">{escape(issue.line_numbers)}</td>'
                f'<td style="padding:9px;border:1px solid #d9e0e8;">{escape(issue.issue_type)}</td>'
                f'<td style="padding:9px;border:1px solid #d9e0e8;">{escape(issue.description)}</td>'
                f'<td style="padding:9px;border:1px solid #d9e0e8;">{escape(issue.suggestion)}</td></tr>'
            )
            for index, issue in enumerate(severe_issues, start=1)
        )

    def _owner_receiver(self, account: str) -> str:
        if not account:
            return ""
        if "@" in account:
            return account
        domain = self.settings.email_account_domain.strip().lstrip("@")
        return f"{account}@{domain}" if domain else ""

    @staticmethod
    def _is_reportable_issue(issue: Issue) -> bool:
        return (issue.filter_status or "").lower() != "filtered"

    @staticmethod
    def _report_path(task: TaskModel) -> str:
        project = quote(task.project_id, safe="")
        review = quote(task.review_version, safe="")
        base = quote(task.copy_from_version, safe="")
        return f"/{project}/{review}_vs_{base}.html"
