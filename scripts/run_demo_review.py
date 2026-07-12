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
            "full_scan_max_tool_rounds": settings.full_scan_max_tool_rounds,
            "llm_timeout_seconds": settings.llm_timeout_seconds,
            "llm_file_timeout_seconds": settings.llm_file_timeout_seconds,
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
        "completion_status": task.completion_status,
        "file_num": task.file_num,
        "reviewed_file_num": task.reviewed_file_num,
        "resumed_file_num": task.resumed_file_num,
        "skipped_file_num": task.skipped_file_num,
        "incomplete_file_num": task.incomplete_file_num,
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
        "llm_total_tokens": task.llm_total_tokens,
        "llm_elapsed_ms": task.llm_elapsed_ms,
        "tool_call_summary": task.tool_call_summary,
        "task_model_round_count": len(task.task_model_rounds),
        "failure_block_count": failure_block_count,
    }


def _code_file_summary(code_file: CodeFileModel) -> dict:
    issues = [issue for block in code_file.code_blocks for issue in block.issues]
    tool_names = [trace.tool_name for block in code_file.code_blocks for trace in block.tool_calls]
    semantic_tool_names = {"find_definition", "find_references", "call_graph"}
    return {
        "task_id": code_file.task_id,
        "file_name": code_file.file_name,
        "background_source": code_file.background_source,
        "has_background": bool(code_file.background),
        "task_type": code_file.task_type,
        "block_count": len(code_file.code_blocks),
        "add_code_line_num": code_file.add_code_line_num,
        "issue_count": len(issues),
        "max_severity": max((issue.severity for issue in issues), default=0),
        "issue_types": sorted({issue.type for issue in issues}),
        "hidden_issue_count": sum(1 for issue in issues if issue.issue_show is False),
        "duplicate_group_count": len({issue.duplicate_group_id for issue in issues if issue.duplicate_group_id}),
        "tool_names": sorted(set(tool_names)),
        "semantic_tool_call_count": sum(1 for name in tool_names if name in semantic_tool_names),
        "failure_block_count": sum(1 for block in code_file.code_blocks if block.failure_message),
        "main_task_completed": all(block.main_task_completed for block in code_file.code_blocks),
        "main_task_completion_modes": [block.main_task_completion_mode for block in code_file.code_blocks],
    }


if __name__ == "__main__":
    main()
