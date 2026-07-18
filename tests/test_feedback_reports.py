from datetime import datetime, timezone
from urllib.parse import quote

from app.models.code_file import CodeBlock, CodeFileModel, Issue
from app.models.task import TaskModel


def _task(project: str, version: str, task_type: int, created: datetime) -> TaskModel:
    return TaskModel(
        project_id=project,
        review_version=version,
        copy_from_version="0_version" if task_type == 3 else "master",
        task_type=task_type,
        state=2,
        create_time=created,
    ).save()


def _file(task: TaskModel, name: str, author: str, issues: list[Issue]) -> CodeFileModel:
    return CodeFileModel(
        task_id=str(task.id),
        project_id=task.project_id,
        review_version=task.review_version,
        copy_from_version=task.copy_from_version,
        task_type=task.task_type,
        file_name=name,
        file_author=author,
        code_blocks=[
            CodeBlock(
                block_id=0,
                contents=["     9   context", "    10+  strcpy(dst, src);"],
                issues=issues,
            )
        ],
    ).save()


def _feedback_data():
    created = datetime(2026, 7, 18, 8, tzinfo=timezone.utc)
    prd = _task("demo-prd", "release", 2, created)
    prd_file = _file(
        prd,
        "src/auth.c",
        "dahai",
        [
            Issue(issue_id=0, severity=5, description="severe agreed", suggestion="fix", feedback_type="agree"),
            Issue(issue_id=1, severity=5, description="severe pending", suggestion="fix"),
            Issue(issue_id=2, severity=4, description="normal rejected", suggestion="fix", feedback_type="reject"),
            Issue(issue_id=3, severity=5, description="filtered", suggestion="none", filter_status="FILTERED"),
        ],
    )
    full = _task("demo-full", "master", 3, created)
    _file(
        full,
        "src/config.c",
        "xiaoming",
        [
            Issue(issue_id=0, severity=5, description="full rejected", suggestion="fix", feedback_type="reject"),
            Issue(issue_id=1, severity=1, description="minor", suggestion="fix"),
        ],
    )
    dev = _task("demo-dev", "feature", 1, created)
    _file(dev, "src/dev.c", "dahai", [Issue(issue_id=0, severity=5, description="ignored", suggestion="fix")])
    return prd, prd_file, full


def test_feedback_admin_page_is_offline_and_prd_summary_uses_severity_five(client):
    prd, _, _ = _feedback_data()

    page = client.get("/admin/feedback.html")
    assert page.status_code == 200
    assert "审核反馈管理" in page.text
    assert "https://" not in page.text
    assert "http://" not in page.text
    for asset in ["/static/feedback_admin.css", "/static/feedback_admin.js"]:
        response = client.get(asset)
        assert response.status_code == 200
        assert "https://" not in response.text
    assert "th.numeric { text-align: right; }" in client.get("/static/feedback_admin.css").text
    assert "numericColumns" in client.get("/static/feedback_admin.js").text

    response = client.get(
        "/api/admin/feedback",
        params={"view": "prd_version", "start_date": "2026-07-18", "end_date": "2026-07-18"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["task_type"] == 2
    assert body["summary"] == {
        "project_count": 1,
        "version_count": 1,
        "author_count": 1,
        "severe_issue_count": 2,
        "severe_feedback_count": 1,
        "severe_feedback_rate": 50.0,
        "severe_agree_count": 1,
        "severe_reject_count": 0,
        "severe_agree_rate": 100.0,
        "issue_count": 3,
        "issue_feedback_count": 2,
        "issue_feedback_rate": 66.7,
        "severity_distribution": {"1": 0, "2": 0, "3": 0, "4": 1, "5": 2},
    }
    assert body["pagination"]["total_items"] == 1
    assert body["task_items"][0]["task_id"] == str(prd.id)
    assert body["task_items"][0]["report_url"] == "/demo-prd/release_vs_master.html"


def test_feedback_admin_full_and_author_views_are_isolated(client):
    _feedback_data()

    full = client.get("/api/admin/feedback", params={"view": "full_scan"}).json()
    assert full["summary"]["project_count"] == 1
    assert full["summary"]["severe_issue_count"] == 1
    assert full["summary"]["severe_feedback_rate"] == 100.0
    assert full["summary"]["severe_agree_rate"] == 0.0
    assert full["summary"]["severity_distribution"] == {"1": 1, "2": 0, "3": 0, "4": 0, "5": 1}

    authors = client.get(
        "/api/admin/feedback",
        params={"view": "author_prd", "start_date": "2026-07-18", "end_date": "2026-07-18"},
    ).json()
    assert authors["task_items"] == []
    assert len(authors["author_items"]) == 1
    item = authors["author_items"][0]
    assert item["file_author"] == "dahai"
    assert item["author_name"] == "大海"
    assert item["report_url"].startswith(f"/author/{quote('大海', safe='')}/issue_report.html?")
    assert "file_author=dahai" in item["report_url"]
    assert "task_type=2" in item["report_url"]


def test_author_issue_page_exposes_block_contents_and_reuses_feedback_api(client):
    _, prd_file, _ = _feedback_data()
    path = f"/author/{quote('大海', safe='')}/issue_report.html"
    page = client.get(path)
    assert page.status_code == 200
    assert "维护人反馈明细" in page.text
    assert "https://" not in page.text

    params = {"file_author": "dahai", "task_type": 2, "start_date": "2026-07-18", "end_date": "2026-07-18"}
    report = client.get(f"/api/authors/{quote('大海', safe='')}/issue-report", params=params)
    assert report.status_code == 200
    body = report.json()
    assert body["author_name"] == "大海"
    assert body["summary"]["file_count"] == 1
    assert body["summary"]["severe_issue_count"] == 2
    assert body["pagination"]["total_items"] == 3
    pending = next(item for item in body["items"] if item["issue_id"] == 1)
    assert pending["contents"] == ["     9   context", "    10+  strcpy(dst, src);"]

    feedback = client.post(f"/api/feedback/{prd_file.id}/0/1", json={"feedback_type": "agree"})
    assert feedback.status_code == 200
    refreshed = client.get(f"/api/authors/{quote('大海', safe='')}/issue-report", params=params).json()
    assert refreshed["summary"]["severe_feedback_rate"] == 100.0
    assert refreshed["summary"]["severe_agree_rate"] == 100.0


def test_empty_author_is_counted_listed_and_queryable_as_an_author(client):
    created = datetime(2026, 7, 18, 8, tzinfo=timezone.utc)
    task = _task("demo-empty-author", "release", 2, created)
    code_file = _file(
        task,
        "src/unowned.c",
        "",
        [
            Issue(issue_id=0, severity=5, description="severe pending", suggestion="fix"),
            Issue(issue_id=1, severity=2, description="minor agreed", suggestion="fix", feedback_type="agree"),
        ],
    )

    response = client.get(
        "/api/admin/feedback",
        params={"view": "author_prd", "start_date": "2026-07-18", "end_date": "2026-07-18"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["author_count"] == 1
    assert body["pagination"]["total_items"] == 1
    item = body["author_items"][0]
    assert item["file_author"] == ""
    assert item["author_name"] == "空"
    assert item["severe_issue_count"] == 1
    assert item["issue_count"] == 2
    assert item["report_url"].startswith(f"/author/{quote('空', safe='')}/issue_report.html?")
    assert "file_author=__empty__" in item["report_url"]

    detail = client.get(
        f"/api/authors/{quote('空', safe='')}/issue-report",
        params={
            "file_author": "__empty__",
            "task_type": 2,
            "start_date": "2026-07-18",
            "end_date": "2026-07-18",
        },
    )

    assert detail.status_code == 200
    report = detail.json()
    assert report["file_author"] == ""
    assert report["author_name"] == "空"
    assert report["summary"]["file_count"] == 1
    assert report["summary"]["severe_issue_count"] == 1
    assert report["summary"]["issue_count"] == 2
    assert {row["file_id"] for row in report["items"]} == {str(code_file.id)}
    assert "${report.file_author}" not in client.get("/static/author_issue_report.js").text


def test_feedback_routes_validate_view_date_and_author_task_type(client):
    assert client.get("/api/admin/feedback", params={"view": "unknown"}).status_code == 422
    assert client.get(
        "/api/admin/feedback",
        params={"start_date": "2026-07-19", "end_date": "2026-07-18"},
    ).status_code == 422
    assert client.get(
        "/api/authors/dahai/issue-report",
        params={"file_author": "dahai", "task_type": 1},
    ).status_code == 422
