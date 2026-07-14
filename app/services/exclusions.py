from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.models.project import ProjectModel


class ReviewPathExcluder:
    def __init__(self, settings: Settings, project_exclude_paths: list[str] | None = None) -> None:
        self.excluded_dirs = {self._normalize(item) for item in settings.excluded_dir_set}
        configured = settings.excluded_path_list + list(project_exclude_paths or [])
        self.contains_patterns = tuple(
            pattern for pattern in (self._normalize(item).replace("*", "") for item in configured) if pattern
        )

    def is_excluded(self, relative_path: str | Path) -> bool:
        normalized = self._normalize(str(relative_path))
        parts = {part for part in normalized.split("/") if part}
        if parts & self.excluded_dirs:
            return True
        return any(pattern in normalized for pattern in self.contains_patterns)

    @staticmethod
    def _normalize(value: str) -> str:
        return str(value or "").replace("\\", "/").strip().strip("/").lower()


def project_exclude_paths(project_id: str) -> list[str]:
    project = ProjectModel.objects(project_id=project_id).first()
    return list(project.exclude_path or []) if project else []
