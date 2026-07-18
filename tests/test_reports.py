from app.models.code_file import CodeBlock, CodeFileModel, Issue, ModelRoundTrace, ToolCallTrace
from app.models.code_file_snapshot import CodeFileSnapshotModel
from app.models.task import TaskModel
from app.services.task_snapshot import TaskSnapshotService


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
    assert body["progress"]["percentage"] == 100
    assert body["progress"]["completed_file_num"] == 2
    assert body["progress"]["completed_block_num"] == 3
    assert body["progress"]["retry_available"] is False
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
    assert body["highest_severity"] is None
    assert body["critical_issues"] == []


def test_task_report_displays_known_author_name_without_exposing_account(client):
    task, code_file, _ = _create_report_data()
    code_file.file_author = "dahai"
    code_file.save()

    response = client.get(f"/api/reports/tasks/{task.id}")

    assert response.status_code == 200
    body = response.json()
    dahai_file = next(item for item in body["files"] if item["file_author"] == "dahai")
    assert body["author_name_map"]["dahai"] == "大海"
    assert dahai_file["file_author_name"] == "大海"
    script = client.get("/static/report.js").text
    assert "author.title = file.file_author" not in script
    assert "option.title = author" not in script
    assert "file.file_author_name || file.file_author" not in script


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
    assert page.headers["cache-control"] == "no-store"
    assert "代码审核报告" in page.text
    canonical_api = client.get("/api/reports/demo-c/feature_vs_master.html")
    assert canonical_api.status_code == 200
    assert canonical_api.headers["cache-control"] == "no-store"
    assert canonical_api.json()["overview"]["task_id"] == str(task.id)
    assert client.get("/demo-c/missing_vs_master.html").status_code == 404
    assert client.get(f"/api/reports/tasks/{task.id}", params={"page_size": 301}).status_code == 422


def test_snapshot_report_only_contains_changed_blocks_and_remains_immutable(client):
    task, auth_file, _ = _create_report_data()
    task.trigger_count = 2
    task.trigger_revision = 2
    task.save()
    auth_file.code_blocks[0].contents = ["    77+  int snapshot_revision = 1;"]
    auth_file.code_blocks[0].comment = "snapshot review"
    auth_file.save()
    snapshot = TaskSnapshotService().create(
        task,
        changed_file_names=["src/auth.c"],
        changed_block_refs={"src/auth.c": [{"block_id": 0, "block_hash": ""}]},
        removed_file_names=[],
    )
    assert snapshot is not None

    auth_file.code_blocks[0].contents = ["    88+  int later_revision = 2;"]
    auth_file.code_blocks[0].comment = "later main-task review"
    auth_file.save()

    response = client.get(
        "/api/reports/demo-c/feature_vs_master.html",
        params={"trigger_revision": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["overview"]["view_mode"] == "snapshot"
    assert body["overview"]["snapshot_id"] == snapshot.snapshot_id
    assert body["overview"]["snapshot_url"] == TaskSnapshotService.report_path(snapshot)
    assert body["overview"]["trigger_revision"] == 2
    assert body["overview"]["trigger_count"] == 2
    assert body["pagination"]["total_items"] == 1
    assert [item["file_name"] for item in body["files"]] == ["src/auth.c"]
    assert body["metrics"]["file_num"] == 1
    assert body["metrics"]["code_block_num"] == 1
    assert len(body["files"][0]["blocks"]) == 1
    assert body["files"][0]["overall_score"] == 50
    assert body["files"][0]["blocks"][0]["contents"] == ["    77+  int snapshot_revision = 1;"]
    assert body["files"][0]["blocks"][0]["comment"] == "snapshot review"
    snapshot_file_id = body["files"][0]["file_id"]
    feedback = client.post(
        f"/api/feedback/{snapshot_file_id}/0/0",
        json={"feedback_type": "agree"},
    )
    assert feedback.status_code == 200
    persisted_snapshot_file = CodeFileSnapshotModel.objects(id=snapshot_file_id).first()
    assert persisted_snapshot_file.code_blocks[0].issues[0].feedback_type == "agree"
    auth_file.reload()
    assert (auth_file.code_blocks[0].issues[0].feedback_type or "") == ""
    snapshot_page = client.get(TaskSnapshotService.report_path(snapshot))
    assert snapshot_page.status_code == 200
    snapshot_api = client.get(f"/api/reports{TaskSnapshotService.report_path(snapshot)}")
    assert snapshot_api.status_code == 200
    canonical = client.get(f"/api/reports/tasks/{task.id}").json()
    assert canonical["files"][0]["blocks"][0]["contents"] == ["    88+  int later_revision = 2;"]
    assert client.get(
        f"/api/reports/tasks/{task.id}",
        params={"trigger_revision": 99},
    ).status_code == 404


def test_removed_only_snapshot_report_is_complete_and_contains_no_current_files(client):
    task, _, _ = _create_report_data()
    task.trigger_count = 2
    task.trigger_revision = 2
    task.state = 0
    task.save()
    service = TaskSnapshotService()
    snapshot = service.create(
        task,
        changed_file_names=[],
        changed_block_refs={},
        removed_file_names=["src/removed.c"],
    )
    assert snapshot is not None

    task.state = 2
    task.save()
    snapshot = service.checkpoint(task, snapshot=snapshot, finalize=True)
    response = client.get(f"/api/reports{service.report_path(snapshot)}")

    assert response.status_code == 200
    body = response.json()
    assert body["overview"]["removed_file_names"] == ["src/removed.c"]
    assert body["overview"]["state"] == 2
    assert body["progress"]["percentage"] == 100
    assert body["progress"]["total_file_num"] == 0
    assert body["progress"]["total_block_num"] == 0
    assert body["pagination"]["total_items"] == 0
    assert body["files"] == []


def test_report_frontend_has_no_external_css_or_javascript(client):
    _create_report_data()
    page = client.get("/demo-c/feature_vs_master.html")

    assert page.status_code == 200
    assert 'href="/static/report.css?v=' in page.text
    assert 'src="/static/report.js?v=' in page.text
    assert "https://" not in page.text
    assert "http://" not in page.text
    for asset_path in ["/static/report.css", "/static/report.js"]:
        asset = client.get(asset_path)
        assert asset.status_code == 200
        assert "https://" not in asset.text
        assert "http://" not in asset.text


def test_report_frontend_contains_live_progress_retry_and_scrollable_code_ui(client):
    _create_report_data()

    page = client.get("/demo-c/feature_vs_master.html")
    css = client.get("/static/report.css").text
    javascript = client.get("/static/report.js").text

    assert 'id="progress-percentage"' in page.text
    assert 'id="retry-failures-button"' in page.text
    assert "overflow-y: auto" in css
    assert "max-height: 520px" in css
    assert "/retry-failures" in javascript
    assert "auto_refresh_seconds" in javascript
    assert "删除文件" in javascript


def test_progress_uses_completed_blocks_and_only_enables_retry_when_failures_are_all_that_remain(client):
    task = TaskModel(
        project_id="progress-project",
        review_version="feature",
        copy_from_version="master",
        task_type=1,
        state=1,
        completion_status="running",
    ).save()
    code_file = CodeFileModel(
        task_id=str(task.id),
        project_id=task.project_id,
        review_version=task.review_version,
        copy_from_version=task.copy_from_version,
        task_type=1,
        file_name="src/progress.c",
        state=1,
        code_blocks=[
            CodeBlock(
                block_id=0,
                contents=["     1+  int completed;"],
                main_task_completed=True,
                review_state=2,
            ),
            CodeBlock(block_id=1, contents=["     2+  int pending;"], review_state=0),
            CodeBlock(
                block_id=2,
                contents=["     3+  int failed;"],
                failure_message="model timeout",
                review_state=3,
            ),
        ],
        extra={"status": "reviewing"},
    ).save()

    running = client.get(f"/api/reports/tasks/{task.id}").json()["progress"]
    assert running["percentage"] == 33
    assert running["completed_block_num"] == 1
    assert running["pending_block_num"] == 1
    assert running["failed_block_num"] == 1
    assert running["retry_available"] is False

    code_file.code_blocks[1].main_task_completed = True
    code_file.code_blocks[1].review_state = 2
    code_file.state = 3
    code_file.extra = {"status": "partial"}
    code_file.save()
    task.state = 3
    task.completion_status = "partial"
    task.save()

    partial = client.get(f"/api/reports/tasks/{task.id}").json()["progress"]
    assert partial["percentage"] == 67
    assert partial["pending_block_num"] == 0
    assert partial["reviewing_block_num"] == 0
    assert partial["failed_block_num"] == 1
    assert partial["retry_available"] is True

    code_file.code_blocks[2].main_task_completed = True
    code_file.code_blocks[2].review_state = 2
    code_file.code_blocks[2].failure_message = ""
    code_file.state = 2
    code_file.extra = {"status": "reviewed"}
    code_file.save()
    task.state = 2
    task.completion_status = "completed"
    task.save()

    completed = client.get(f"/api/reports/tasks/{task.id}").json()["progress"]
    assert completed["percentage"] == 100
    assert completed["retry_available"] is False


def test_progress_treats_legacy_blocks_in_reviewed_file_as_completed(client):
    task = TaskModel(
        project_id="legacy-progress",
        review_version="feature",
        copy_from_version="master",
        task_type=1,
        state=2,
        completion_status="completed",
    ).save()
    CodeFileModel(
        task_id=str(task.id),
        project_id=task.project_id,
        review_version=task.review_version,
        copy_from_version=task.copy_from_version,
        task_type=1,
        file_name="src/legacy.c",
        code_blocks=[CodeBlock(block_id=0, contents=["     1+  int legacy;"], comment="legacy result")],
        extra={"status": "reviewed"},
    ).save()

    response = client.get(f"/api/reports/tasks/{task.id}")

    assert response.status_code == 200
    assert response.json()["progress"]["percentage"] == 100
    assert response.json()["files"][0]["blocks"][0]["status"] == "completed"
