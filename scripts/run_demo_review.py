from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import get_settings
from app.core.database import connect_to_mongo, disconnect_mongo
from app.models.code_file import CodeFileModel
from app.models.task import TaskModel
from app.services.review_service import ReviewTaskService


def main() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    connect_to_mongo(settings)
    try:
        TaskModel.objects(project_id="demo_c").delete()
        CodeFileModel.objects(project_id="demo_c").delete()

        repository_root = Path(settings.code_repository_root).resolve()
        service = ReviewTaskService(settings)

        incremental_task = TaskModel(
            project_id="demo_c",
            review_version="wip_qiaodahai_just_demo",
            copy_from_version="master",
            state=0,
        ).save()
        full_scan_task = TaskModel(
            project_id="demo_c",
            review_version="master",
            copy_from_version="0_version",
            state=0,
        ).save()

        started_at = time.monotonic()
        reviewed_incremental = service.review_task(incremental_task)
        reviewed_full_scan = service.review_task(full_scan_task)
        elapsed_seconds = round(time.monotonic() - started_at, 2)

        summary = {
            "repository_root": str(repository_root),
            "llm_max_tool_rounds": settings.llm_max_tool_rounds,
            "llm_timeout_seconds": settings.llm_timeout_seconds,
            "elapsed_seconds": elapsed_seconds,
            "tasks": [
                _task_summary(reviewed_incremental),
                _task_summary(reviewed_full_scan),
            ],
            "code_file_count": CodeFileModel.objects.count(),
            "code_files": [_code_file_summary(code_file) for code_file in CodeFileModel.objects.order_by("file_name")],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        disconnect_mongo(settings)


def _task_summary(task: TaskModel) -> dict:
    code_files = CodeFileModel.objects(task_id=str(task.id))
    failure_block_count = sum(1 for code_file in code_files for block in code_file.code_blocks if block.failure_message)
    return {
        "id": str(task.id),
        "project_id": task.project_id,
        "review_version": task.review_version,
        "copy_from_version": task.copy_from_version,
        "task_type": task.task_type,
        "state": task.state,
        "file_num": task.file_num,
        "code_block_num": task.code_block_num,
        "comment_line_number": task.comment_line_number,
        "scores": {
            "logic_score": task.logic_score,
            "performance_score": task.performance_score,
            "security_score": task.security_score,
            "readable_score": task.readable_score,
            "code_style_score": task.code_style_score,
        },
        "developer_issue_summary": task.developer_issue_summary,
        "failure_block_count": failure_block_count,
    }


def _code_file_summary(code_file: CodeFileModel) -> dict:
    issues = [issue for block in code_file.code_blocks for issue in block.issues]
    return {
        "task_id": code_file.task_id,
        "file_name": code_file.file_name,
        "task_type": code_file.task_type,
        "block_count": len(code_file.code_blocks),
        "add_code_line_num": code_file.add_code_line_num,
        "issue_count": len(issues),
        "max_severity": max((issue.severity for issue in issues), default=0),
        "issue_types": sorted({issue.type for issue in issues}),
        "failure_block_count": sum(1 for block in code_file.code_blocks if block.failure_message),
    }


if __name__ == "__main__":
    main()
