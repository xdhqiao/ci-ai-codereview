from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlencode

from app.common.constant import (
    EMPTY_FILE_AUTHOR_DISPLAY_NAME,
    EMPTY_FILE_AUTHOR_QUERY_VALUE,
    FeedbackType,
    SEVERE_ISSUE_SEVERITY,
)
from app.common.utils import get_user_display_name
from app.core.exceptions import AppError
from app.models.issue_feedback_log import IssueFeedbackLog
from app.schemas.feedback_log import (
    FeedbackLogAuthorItemResponse,
    FeedbackLogAuthorDetailResponse,
    FeedbackLogDetailResponse,
    FeedbackLogGroupBy,
    FeedbackLogItemResponse,
    FeedbackLogPaginationResponse,
    FeedbackLogReportResponse,
    FeedbackLogSummaryResponse,
    FeedbackLogVersionItemResponse,
)


@dataclass
class FeedbackLogCounters:
    feedback_count: int = 0
    agree_count: int = 0
    severe_feedback_count: int = 0
    severe_agree_count: int = 0

    def add(self, *, severity: int, feedback_type: str) -> None:
        self.feedback_count += 1
        if feedback_type == FeedbackType.AGREE.value:
            self.agree_count += 1
        if severity != SEVERE_ISSUE_SEVERITY:
            return
        self.severe_feedback_count += 1
        if feedback_type == FeedbackType.AGREE.value:
            self.severe_agree_count += 1


class FeedbackLogService:
    DEFAULT_RANGE_DAYS = 30

    def report(
        self,
        *,
        group_by: FeedbackLogGroupBy,
        start_date: date | None,
        end_date: date | None,
        page: int,
        page_size: int,
    ) -> FeedbackLogReportResponse:
        resolved_start, resolved_end = self._resolve_dates(start_date, end_date)
        query = self._query(resolved_start, resolved_end)
        summary = self._summary(query)

        if group_by == "none":
            total_items = query.count()
            pagination = self._pagination(total_items, page, page_size)
            start = (pagination.page - 1) * page_size
            items = [
                self._log_item(item)
                for item in query.order_by("create_time", "id").skip(start).limit(page_size)
            ]
            return FeedbackLogReportResponse(
                group_by=group_by,
                start_date=resolved_start,
                end_date=resolved_end,
                summary=summary,
                pagination=pagination,
                log_items=items,
                version_items=[],
                author_items=[],
            )

        logs = list(query.order_by("create_time", "id"))
        if group_by == "version":
            version_items = self._version_items(logs, resolved_start, resolved_end)
            page_items, pagination = self._paginate(version_items, page, page_size)
            return FeedbackLogReportResponse(
                group_by=group_by,
                start_date=resolved_start,
                end_date=resolved_end,
                summary=summary,
                pagination=pagination,
                log_items=[],
                version_items=page_items,
                author_items=[],
            )

        author_items = self._author_items(logs, resolved_start, resolved_end)
        page_items, pagination = self._paginate(author_items, page, page_size)
        return FeedbackLogReportResponse(
            group_by=group_by,
            start_date=resolved_start,
            end_date=resolved_end,
            summary=summary,
            pagination=pagination,
            log_items=[],
            version_items=[],
            author_items=page_items,
        )

    def detail(
        self,
        *,
        project_id: str,
        review_version: str,
        copy_from_version: str,
        start_date: date | None,
        end_date: date | None,
    ) -> FeedbackLogDetailResponse:
        resolved_start, resolved_end = self._resolve_dates(start_date, end_date)
        query = self._query(resolved_start, resolved_end).filter(
            project_id=project_id,
            review_version=review_version,
            copy_from_version=copy_from_version,
        )
        return FeedbackLogDetailResponse(
            project_id=project_id,
            review_version=review_version,
            copy_from_version=copy_from_version,
            start_date=resolved_start,
            end_date=resolved_end,
            summary=self._summary(query),
            items=[self._log_item(item) for item in query.order_by("create_time", "id")],
        )

    def author_detail(
        self,
        *,
        file_author: str,
        start_date: date | None,
        end_date: date | None,
        page: int,
        page_size: int,
    ) -> FeedbackLogAuthorDetailResponse:
        resolved_start, resolved_end = self._resolve_dates(start_date, end_date)
        account_token = file_author.strip()
        if not account_token:
            raise AppError("file_author is required", status_code=422, code="validation_error")
        account = "" if account_token == EMPTY_FILE_AUTHOR_QUERY_VALUE else account_token
        query = self._author_query(
            self._query(resolved_start, resolved_end),
            account,
        )
        total_items = query.count()
        pagination = self._pagination(total_items, page, page_size)
        start = (pagination.page - 1) * page_size
        return FeedbackLogAuthorDetailResponse(
            file_author=account,
            author_name=self._author_name(account),
            start_date=resolved_start,
            end_date=resolved_end,
            summary=self._summary(query),
            pagination=pagination,
            items=[
                self._log_item(item)
                for item in query.order_by("create_time", "id").skip(start).limit(page_size)
            ],
        )

    def _version_items(
        self,
        logs: list[IssueFeedbackLog],
        start_date: date,
        end_date: date,
    ) -> list[FeedbackLogVersionItemResponse]:
        groups: dict[tuple[str, str, str], FeedbackLogCounters] = {}
        first_seen: dict[tuple[str, str, str], datetime] = {}
        for item in logs:
            key = (item.project_id, item.review_version, item.copy_from_version)
            groups.setdefault(key, FeedbackLogCounters()).add(
                severity=int(item.severity or 0),
                feedback_type=item.feedback_type or "",
            )
            first_seen.setdefault(key, item.create_time)

        ordered_keys = sorted(groups, key=lambda key: (first_seen[key], key))
        return [
            FeedbackLogVersionItemResponse(
                project_id=key[0],
                review_version=key[1],
                copy_from_version=key[2],
                issue_count=groups[key].feedback_count,
                agree_rate=self._percent(groups[key].agree_count, groups[key].feedback_count),
                severe_issue_count=groups[key].severe_feedback_count,
                severe_agree_rate=self._percent(
                    groups[key].severe_agree_count,
                    groups[key].severe_feedback_count,
                ),
                detail_url="/admin/feedback-log-detail.html?"
                + urlencode(
                    {
                        "project_id": key[0],
                        "review_version": key[1],
                        "copy_from_version": key[2],
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                    }
                ),
            )
            for key in ordered_keys
        ]

    def _author_items(
        self,
        logs: list[IssueFeedbackLog],
        start_date: date,
        end_date: date,
    ) -> list[FeedbackLogAuthorItemResponse]:
        groups: dict[str, FeedbackLogCounters] = {}
        first_seen: dict[str, datetime] = {}
        for item in logs:
            author = (item.file_author or "").strip()
            groups.setdefault(author, FeedbackLogCounters()).add(
                severity=int(item.severity or 0),
                feedback_type=item.feedback_type or "",
            )
            first_seen.setdefault(author, item.create_time)

        ordered_authors = sorted(groups, key=lambda author: (first_seen[author], author))
        return [
            FeedbackLogAuthorItemResponse(
                file_author=author,
                author_name=self._author_name(author),
                issue_count=groups[author].feedback_count,
                agree_rate=self._percent(groups[author].agree_count, groups[author].feedback_count),
                detail_url="/admin/feedback-log-author-detail.html?"
                + urlencode(
                    {
                        "file_author": author or EMPTY_FILE_AUTHOR_QUERY_VALUE,
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                    }
                ),
            )
            for author in ordered_authors
        ]

    def _summary(self, query) -> FeedbackLogSummaryResponse:
        feedback_count = query.count()
        agree_count = query.filter(feedback_type=FeedbackType.AGREE.value).count()
        severe_feedback_count = query.filter(severity=SEVERE_ISSUE_SEVERITY).count()
        severe_agree_count = query.filter(
            severity=SEVERE_ISSUE_SEVERITY,
            feedback_type=FeedbackType.AGREE.value,
        ).count()
        return FeedbackLogSummaryResponse(
            feedback_count=feedback_count,
            agree_rate=self._percent(agree_count, feedback_count),
            severe_feedback_count=severe_feedback_count,
            severe_agree_rate=self._percent(severe_agree_count, severe_feedback_count),
        )

    def _query(self, start_date: date, end_date: date):
        start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
        exclusive_end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
        return IssueFeedbackLog.objects(create_time__gte=start, create_time__lt=exclusive_end)

    @staticmethod
    def _author_query(query, author: str):
        if author:
            return query.filter(file_author=author)
        return query.filter(
            __raw__={
                "$or": [
                    {"file_author": {"$exists": False}},
                    {"file_author": None},
                    {"file_author": {"$regex": r"^\s*$"}},
                ]
            }
        )

    def _resolve_dates(
        self,
        start_date: date | None,
        end_date: date | None,
    ) -> tuple[date, date]:
        today = datetime.now(timezone.utc).date()
        resolved_end = end_date or today
        resolved_start = start_date or (resolved_end - timedelta(days=self.DEFAULT_RANGE_DAYS - 1))
        if resolved_start > resolved_end:
            raise AppError("start_date must be before or equal to end_date", status_code=422)
        return resolved_start, resolved_end

    def _log_item(self, item: IssueFeedbackLog) -> FeedbackLogItemResponse:
        author = (item.file_author or "").strip()
        return FeedbackLogItemResponse(
            log_id=str(item.id),
            task_id=item.task_id or "",
            project_id=item.project_id,
            review_version=item.review_version,
            copy_from_version=item.copy_from_version,
            task_type=item.task_type,
            file_name=item.file_name,
            file_author=author,
            author_name=self._author_name(author),
            issue_line_numbers=item.issue_line_numbers or "",
            severity=int(item.severity or 0),
            suggestion=item.suggestion or "",
            description=item.description or "",
            feedback_type=item.feedback_type or "",
            feedback_content=item.feedback_content or "",
            create_time=item.create_time,
        )

    @staticmethod
    def _author_name(author: str) -> str:
        return get_user_display_name(author) if author else EMPTY_FILE_AUTHOR_DISPLAY_NAME

    @classmethod
    def _paginate(cls, items: list, page: int, page_size: int) -> tuple[list, FeedbackLogPaginationResponse]:
        pagination = cls._pagination(len(items), page, page_size)
        start = (pagination.page - 1) * page_size
        return items[start : start + page_size], pagination

    @staticmethod
    def _pagination(total_items: int, page: int, page_size: int) -> FeedbackLogPaginationResponse:
        total_pages = math.ceil(total_items / page_size) if total_items else 0
        normalized_page = min(page, total_pages) if total_pages else 1
        return FeedbackLogPaginationResponse(
            page=normalized_page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
        )

    @staticmethod
    def _percent(numerator: int, denominator: int) -> float:
        return round(numerator * 100 / denominator, 1) if denominator else 0.0
