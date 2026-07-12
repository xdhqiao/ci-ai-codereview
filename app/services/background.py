from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Protocol


@dataclass(frozen=True)
class FileReviewBackground:
    content: str = ""
    source: str = ""


class FileBackgroundProvider(Protocol):
    def get_background(
        self,
        project_id: str,
        review_version: str,
        file_name: str,
    ) -> FileReviewBackground: ...


class MockFileBackgroundProvider:
    """Replace this provider with a business requirement lookup implementation."""

    _BACKGROUND_BY_FILE_NAME = {
        "auth.c": (
            "Authentication must reject invalid credentials, must not log secrets, and must compare "
            "security-sensitive tokens without leaking partial-match information."
        ),
        "buffer.c": (
            "All external input copied into fixed-size buffers must be length checked and remain "
            "null-terminated. Truncation must be reported to the caller."
        ),
        "config.c": (
            "Configuration values may come from untrusted files. Invalid or missing values must fail "
            "closed and must not silently select an unsafe default."
        ),
        "net_client.c": (
            "Network operations must have bounded timeouts, validate response sizes, and propagate "
            "connection or protocol failures to the caller."
        ),
        "storage.c": (
            "Storage operations must preserve data on partial failures and report write, flush, and "
            "close errors instead of returning success."
        ),
    }

    def get_background(
        self,
        project_id: str,
        review_version: str,
        file_name: str,
    ) -> FileReviewBackground:
        del project_id, review_version
        normalized = str(file_name or "").replace("\\", "/")
        base_name = PurePosixPath(normalized).name.lower()
        content = self._BACKGROUND_BY_FILE_NAME.get(base_name, "")
        return FileReviewBackground(
            content=content,
            source="mock:file-name" if content else "",
        )
