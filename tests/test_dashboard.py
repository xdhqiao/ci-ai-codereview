from datetime import datetime, timedelta, timezone

from app.models.code_file import (
    CodeBlock,
    CodeFileModel,
    Issue,
    ModelRoundTrace,
    ToolCallTrace,
)
from app.models.issue_feedback_log import IssueFeedbackLog
from app.models.task import TaskModel


def _round(index: int) -> ModelRoundTrace:
    return ModelRoundTrace(stage="main_task", round_index=index, model="test-model")


def _tool(index: int) -> ToolCallTrace:
    return ToolCallTrace(round_index=index, tool_name="read_file")


def _task(
    *,
    project_id: str,
    task_type: int,
    create_time: datetime,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    elapsed_ms: int,
    task_rounds: int,
) -> TaskModel:
    return TaskModel(
        project_id=project_id,
        review_version=f"review-{task_type}",
        copy_from_version="master" if task_type != 3 else "0_version",
        task_type=task_type,
        state=2,
        llm_prompt_tokens=prompt_tokens,
        llm_completion_tokens=completion_tokens,
        llm_total_tokens=total_tokens,
        llm_elapsed_ms=elapsed_ms,
        task_model_rounds=[_round(index) for index in range(task_rounds)],
        create_time=create_time,
    ).save()


def _history_feedback(
    *,
    create_time: datetime,
    feedback_type: str,
) -> None:
    IssueFeedbackLog(
        project_id="dashboard",
        review_version="review",
        copy_from_version="master",
        task_type=2,
        file_name="src/dashboard.c",
        severity=5,
        suggestion="fix",
        description="problem",
        feedback_type=feedback_type,
        create_time=create_time,
    ).save()


def test_dashboard_aggregates_tasks_traces_issues_and_feedback(client):
    base = datetime(2026, 7, 10, 8, tzinfo=timezone.utc)
    task_one = _task(
        project_id="alpha",
        task_type=1,
        create_time=base,
        prompt_tokens=70,
        completion_tokens=30,
        total_tokens=100,
        elapsed_ms=1_000,
        task_rounds=1,
    )
    task_two = _task(
        project_id="alpha",
        task_type=2,
        create_time=base + timedelta(days=1),
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        elapsed_ms=2_500,
        task_rounds=2,
    )
    task_three = _task(
        project_id="beta",
        task_type=3,
        create_time=base + timedelta(days=2),
        prompt_tokens=150,
        completion_tokens=50,
        total_tokens=0,
        elapsed_ms=6_500,
        task_rounds=0,
    )
    outside_task = _task(
        project_id="outside",
        task_type=1,
        create_time=base - timedelta(days=20),
        prompt_tokens=999,
        completion_tokens=999,
        total_tokens=1_998,
        elapsed_ms=99_999,
        task_rounds=5,
    )

    CodeFileModel(
        task_id=str(task_one.id),
        project_id=task_one.project_id,
        review_version=task_one.review_version,
        copy_from_version=task_one.copy_from_version,
        task_type=task_one.task_type,
        file_name="src/completed.c",
        state=2,
        code_blocks=[
            CodeBlock(
                block_id=0,
                contents=["     1+ changed();"],
                main_task_completed=True,
                review_state=2,
                model_rounds=[_round(0), _round(1)],
                tool_calls=[_tool(0), _tool(1)],
                issues=[
                    Issue(
                        issue_id=0,
                        severity=5,
                        description="critical",
                        suggestion="fix",
                        feedback_type="agree",
                    ),
                    Issue(
                        issue_id=1,
                        severity=3,
                        description="normal",
                        suggestion="fix",
                        feedback_type="reject",
                    ),
                    Issue(
                        issue_id=2,
                        severity=5,
                        description="filtered",
                        suggestion="ignore",
                        filter_status="filtered",
                        feedback_type="agree",
                    ),
                ],
            )
        ],
    ).save()
    CodeFileModel(
        task_id=str(task_two.id),
        project_id=task_two.project_id,
        review_version=task_two.review_version,
        copy_from_version=task_two.copy_from_version,
        task_type=task_two.task_type,
        file_name="src/pending.c",
        state=0,
        code_blocks=[
            CodeBlock(
                block_id=0,
                contents=["     1+ pending();"],
                model_rounds=[_round(0)],
                tool_calls=[_tool(0)],
                issues=[
                    Issue(
                        issue_id=0,
                        severity=1,
                        description="minor",
                        suggestion="fix",
                    )
                ],
            )
        ],
    ).save()
    CodeFileModel(
        task_id=str(task_three.id),
        project_id=task_three.project_id,
        review_version=task_three.review_version,
        copy_from_version=task_three.copy_from_version,
        task_type=task_three.task_type,
        file_name="src/full.c",
        state=2,
        code_blocks=[
            CodeBlock(
                block_id=0,
                contents=["     1  int main(void) {}"],
                main_task_completed=True,
                review_state=2,
                model_rounds=[_round(0)],
                tool_calls=[_tool(0), _tool(1), _tool(2)],
                issues=[
                    Issue(
                        issue_id=0,
                        severity=2,
                        description="filtered style",
                        suggestion="ignore",
                        filter_status="filtered",
                    )
                ],
            )
        ],
    ).save()
    CodeFileModel(
        task_id=str(outside_task.id),
        project_id=outside_task.project_id,
        review_version=outside_task.review_version,
        copy_from_version=outside_task.copy_from_version,
        task_type=outside_task.task_type,
        file_name="src/outside.c",
        state=2,
        code_blocks=[
            CodeBlock(
                block_id=0,
                contents=["     1+ outside();"],
                main_task_completed=True,
                tool_calls=[_tool(0)],
            )
        ],
    ).save()

    _history_feedback(create_time=base, feedback_type="agree")
    _history_feedback(create_time=base + timedelta(days=1), feedback_type="reject")
    _history_feedback(create_time=base + timedelta(days=2), feedback_type="agree")
    _history_feedback(create_time=base - timedelta(days=20), feedback_type="agree")

    response = client.get(
        "/api/admin/dashboard",
        params={"start_date": "2026-07-10", "end_date": "2026-07-12"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["start_date"] == "2026-07-10"
    assert payload["end_date"] == "2026-07-12"
    assert payload["tasks"] == {
        "task_count": 3,
        "project_count": 2,
        "task_types": [
            {"task_type": 1, "label": "轮询版", "count": 1},
            {"task_type": 2, "label": "正式版", "count": 1},
            {"task_type": 3, "label": "全量审核", "count": 1},
        ],
    }
    assert payload["resources"] == {
        "total_tokens": 450,
        "prompt_tokens": 320,
        "completion_tokens": 130,
        "llm_elapsed_ms": 10_000,
        "file_count": 3,
        "reviewed_file_count": 2,
        "tool_call_count": 6,
        "model_round_count": 7,
    }
    assert payload["issues"] == {
        "valid_issue_count": 3,
        "filtered_issue_count": 2,
        "severe_issue_count": 1,
    }
    assert payload["feedback"] == {
        "feedback_count": 2,
        "agree_count": 1,
        "agree_rate": 50.0,
        "historical_feedback_count": 3,
        "historical_agree_count": 2,
        "historical_agree_rate": 66.7,
    }


def test_dashboard_page_is_offline_and_linked_from_task_admin(client):
    page = client.get("/admin/dashboard.html")
    stylesheet = client.get("/static/dashboard.css")
    script = client.get("/static/dashboard.js")
    admin_page = client.get("/admin/tasks.html")

    assert page.status_code == 200
    assert stylesheet.status_code == 200
    assert script.status_code == 200
    assert "代码审核数据看板" in page.text
    assert 'href="/static/dashboard.css' in page.text
    assert 'src="/static/dashboard.js' in page.text
    assert "http://" not in page.text
    assert "https://" not in page.text
    assert 'href="/admin/dashboard.html"' in admin_page.text
    assert "fetch(`/api/admin/dashboard?" in script.text


def test_dashboard_defaults_to_recent_month_and_rejects_reversed_range(client):
    default_response = client.get("/api/admin/dashboard")
    invalid_response = client.get(
        "/api/admin/dashboard",
        params={"start_date": "2026-07-20", "end_date": "2026-07-10"},
    )

    assert default_response.status_code == 200
    payload = default_response.json()
    start = datetime.fromisoformat(payload["start_date"]).date()
    end = datetime.fromisoformat(payload["end_date"]).date()
    assert (end - start).days == 29
    assert invalid_response.status_code == 422
