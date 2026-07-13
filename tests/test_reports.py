from app.models.code_file import CodeBlock, CodeFileModel, Issue, ModelRoundTrace, ToolCallTrace
from app.models.task import TaskModel


def _score_block(block_id: int, score: int, contents: list[str], issues: list[Issue]) -> CodeBlock:
    return CodeBlock(
        block_id=block_id,
        contents=contents,
        comment=f"block {block_id} comment",
        logic_score=score,
        performance_score=score,
        security_score=score,
        readable_score=score,
        code_style_score=score,
        issues=issues,
        main_task_completed=True,
        llm_total_tokens=30,
        memory_compression_count=1,
        model_rounds=[ModelRoundTrace(stage="main_task", round_index=1, model="mock")],
        tool_calls=[ToolCallTrace(tool_name="read_file")],
    )


def _create_report_data() -> tuple[TaskModel, CodeFileModel, CodeFileModel]:
    task = TaskModel(
        project_id="demo-c",
        review_version="feature",
        copy_from_version="master",
        task_type=1,
        state=2,
        completion_status="completed",
        reviewed_file_num=2,
        process_time=125000,
        llm_prompt_tokens=800,
        llm_completion_tokens=200,
        llm_total_tokens=1000,
        llm_elapsed_ms=60000,
    ).save()
    kept_with_reserved_flag = Issue(
        issue_id=0,
        severity=5,
        type="security",
        issue_line_numbers="12",
        description="unchecked input",
        suggestion="validate input",
        filter_status="kept",
        issue_show=False,
    )
    filtered = Issue(
        issue_id=1,
        severity=5,
        type="logic",
        issue_line_numbers="13",
        description="disproved issue",
        suggestion="none",
        filter_status="filtered",
        issue_show=True,
    )
    first = CodeFileModel(
        task_id=str(task.id),
        project_id=task.project_id,
        review_version=task.review_version,
        copy_from_version=task.copy_from_version,
        task_type=1,
        file_name="src/auth.c",
        file_author="alice",
        add_code_line_num=2,
        code_blocks=[
            _score_block(0, 50, ["     1+  first", "     2-  old", "     2   context"], [kept_with_reserved_flag, filtered]),
            _score_block(1, 100, ["     8+  second"], []),
        ],
    ).save()
    second = CodeFileModel(
        task_id=str(task.id),
        project_id=task.project_id,
        review_version=task.review_version,
        copy_from_version=task.copy_from_version,
        task_type=1,
        file_name="src/math.c",
        file_author="bob",
        add_code_line_num=1,
        code_blocks=[
            _score_block(
                0,
                0,
                ["     4+  return a / b;"],
                [
                    Issue(
                        issue_id=0,
                        severity=3,
                        type="logic",
                        issue_line_numbers="4",
                        description="division by zero",
                        suggestion="check divisor",
                        filter_status="kept",
                    )
                ],
            )
        ],
    ).save()
    return task, first, second


def test_task_report_uses_changed_line_weight_and_reserved_issue_show_is_ignored(client):
    task, _, _ = _create_report_data()

    response = client.get(f"/api/reports/tasks/{task.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["overview"]["changed_line_num"] == 4
    assert body["overview"]["scores"]["logic_score"] == 50
    assert body["overview"]["overall_score"] == 50
    assert body["metrics"]["issue_num"] == 2
    assert body["metrics"]["filtered_issue_num"] == 1
    assert body["authors"] == ["alice", "bob"]
    assert body["highest_severity"] == 5
    assert body["critical_issues"][0]["description"] == "unchecked input"
    alice_file = next(item for item in body["files"] if item["file_author"] == "alice")
    assert alice_file["overall_score"] == 67
    assert alice_file["blocks"][0]["block_id"] == 0
    assert alice_file["blocks"][0]["issues"][0]["issue_id"] == 0


def test_task_report_author_filter_controls_issues_files_and_pagination(client):
    task, _, _ = _create_report_data()

    response = client.get(f"/api/reports/tasks/{task.id}", params={"author": "bob", "page_size": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["selected_author"] == "bob"
    assert body["pagination"] == {"page": 1, "page_size": 1, "total_items": 1, "total_pages": 1}
    assert [item["file_name"] for item in body["files"]] == ["src/math.c"]
    assert body["highest_severity"] == 3
    assert [item["file_author"] for item in body["critical_issues"]] == ["bob"]


def test_feedback_api_updates_embedded_issue_by_zero_based_ids(client):
    _, code_file, _ = _create_report_data()

    agreed = client.post(
        f"/api/feedback/{code_file.id}/0/0",
        json={"feedback_type": "agree"},
    )
    assert agreed.status_code == 200
    assert agreed.json()["feedback_type"] == "agree"

    rejected = client.post(
        f"/api/feedback/{code_file.id}/0/0",
        json={"feedback_type": "reject", "feedback_content": "This is validated upstream."},
    )
    assert rejected.status_code == 200
    code_file.reload()
    issue = code_file.code_blocks[0].issues[0]
    assert issue.feedback_type == "reject"
    assert issue.feedback_content == "This is validated upstream."


def test_feedback_reject_requires_reason_and_missing_ids_return_404(client):
    _, code_file, _ = _create_report_data()

    invalid = client.post(
        f"/api/feedback/{code_file.id}/0/0",
        json={"feedback_type": "reject", "feedback_content": ""},
    )
    assert invalid.status_code == 422
    assert client.post(f"/api/feedback/{code_file.id}/99/0", json={"feedback_type": "agree"}).status_code == 404
    assert client.post(f"/api/feedback/{code_file.id}/0/99", json={"feedback_type": "agree"}).status_code == 404


def test_report_page_and_page_size_limit(client):
    task, _, _ = _create_report_data()

    page = client.get("/demo-c/feature_vs_master.html")
    assert page.status_code == 200
    assert "代码审核报告" in page.text
    canonical_api = client.get("/api/reports/demo-c/feature_vs_master.html")
    assert canonical_api.status_code == 200
    assert canonical_api.json()["overview"]["task_id"] == str(task.id)
    assert client.get("/demo-c/missing_vs_master.html").status_code == 404
    assert client.get(f"/api/reports/tasks/{task.id}", params={"page_size": 301}).status_code == 422
