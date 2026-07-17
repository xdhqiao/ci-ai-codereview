from datetime import datetime, timedelta, timezone

import pytest

from app.models.code_file import CodeBlock, CodeFileModel, Issue
from app.models.task import TaskModel


def _task(
    *,
    project_id: str,
    review_version: str,
    copy_from_version: str = "master",
    task_type: int = 1,
    state: int = 2,
    score: int = 80,
    create_time: datetime,
    severity_summary: dict[str, int] | None = None,
) -> TaskModel:
    developer_summary = {}
    if severity_summary is not None:
        developer_summary["_severity"] = severity_summary
    return TaskModel(
        project_id=project_id,
        review_version=review_version,
        copy_from_version=copy_from_version,
        task_type=task_type,
        state=state,
        score=score,
        create_time=create_time,
        developer_issue_summary=developer_summary,
    ).save()


def _code_file(task: TaskModel, issues: list[Issue]) -> CodeFileModel:
    return CodeFileModel(
        task_id=str(task.id),
        project_id=task.project_id,
        review_version=task.review_version,
        copy_from_version=task.copy_from_version,
        task_type=task.task_type,
        file_name=f"src/{task.project_id}.c",
        code_blocks=[CodeBlock(block_id=0, contents=["     1+  int value;"], issues=issues)],
    ).save()


def test_admin_page_and_assets_are_local_and_report_links_back_to_admin(client):
    page = client.get("/admin/tasks.html")

    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    assert "审核任务管理" in page.text
    assert 'id="filter-form"' in page.text
    assert page.text.count('class="sort-button') == 9
    assert "https://" not in page.text
    assert "http://" not in page.text
    for asset_path in ["/static/admin_tasks.css", "/static/admin_tasks.js"]:
        asset = client.get(asset_path)
        assert asset.status_code == 200
        assert "https://" not in asset.text
        assert "http://" not in asset.text

    report_task = _task(
        project_id="demo",
        review_version="feature",
        create_time=datetime(2026, 7, 10, tzinfo=timezone.utc),
    )
    report = client.get(f"/{report_task.project_id}/{report_task.review_version}_vs_master.html")
    assert report.status_code == 200
    assert 'href="/admin/tasks.html"' in report.text


def test_admin_api_filters_and_counts_reportable_issues(client):
    first = _task(
        project_id="Alpha-Core",
        review_version="feature-one",
        task_type=1,
        state=2,
        score=91,
        create_time=datetime(2026, 7, 10, 8, tzinfo=timezone.utc),
        severity_summary={"5": 2, "3": 1},
    )
    second = _task(
        project_id="beta-service",
        review_version="release",
        copy_from_version="0_version",
        task_type=2,
        state=0,
        score=0,
        create_time=datetime(2026, 7, 12, 8, tzinfo=timezone.utc),
    )
    third = _task(
        project_id="alpha-tools",
        review_version="feature-two",
        task_type=1,
        state=1,
        score=60,
        create_time=datetime(2026, 7, 15, 8, tzinfo=timezone.utc),
    )
    _code_file(
        second,
        [
            Issue(severity=4, description="kept", suggestion="fix", issue_show=False),
            Issue(severity=2, description="also kept", suggestion="fix", filter_status="kept"),
            Issue(severity=5, description="filtered", suggestion="none", filter_status="FILTERED"),
        ],
    )

    all_tasks = client.get("/api/admin/tasks")
    assert all_tasks.status_code == 200
    assert all_tasks.headers["cache-control"] == "no-store"
    by_id = {item["task_id"]: item for item in all_tasks.json()["items"]}
    assert by_id[str(first.id)]["issue_count"] == 3
    assert by_id[str(first.id)]["highest_severity"] == 5
    assert by_id[str(first.id)]["critical_issue_count"] == 2
    assert by_id[str(second.id)]["issue_count"] == 2
    assert by_id[str(second.id)]["highest_severity"] == 4
    assert by_id[str(second.id)]["critical_issue_count"] == 1
    assert by_id[str(second.id)]["report_url"] == "/beta-service/release_vs_0_version.html"
    assert client.get(by_id[str(second.id)]["report_url"]).status_code == 200

    project = client.get("/api/admin/tasks", params={"project_id": "ALPHA"}).json()
    assert {item["task_id"] for item in project["items"]} == {str(first.id), str(third.id)}
    version = client.get("/api/admin/tasks", params={"review_version": "ONE"}).json()
    assert [item["task_id"] for item in version["items"]] == [str(first.id)]
    task_type = client.get("/api/admin/tasks", params={"task_type": 2}).json()
    assert [item["task_id"] for item in task_type["items"]] == [str(second.id)]
    state = client.get("/api/admin/tasks", params={"state": 1}).json()
    assert [item["task_id"] for item in state["items"]] == [str(third.id)]
    dates = client.get(
        "/api/admin/tasks",
        params={
            "date_from": "2026-07-11T00:00:00Z",
            "date_to": "2026-07-13T23:59:59Z",
        },
    ).json()
    assert [item["task_id"] for item in dates["items"]] == [str(second.id)]


@pytest.mark.parametrize(
    ("sort_by", "expected_project"),
    [
        ("project_id", "alpha"),
        ("review_version", "charlie"),
        ("copy_from_version", "charlie"),
        ("state", "charlie"),
        ("task_type", "alpha"),
        ("score", "charlie"),
        ("critical_issue_count", "charlie"),
        ("issue_count", "charlie"),
        ("create_time", "charlie"),
    ],
)
def test_admin_api_supports_sorting_every_visible_column(client, sort_by, expected_project):
    base = datetime(2026, 7, 10, tzinfo=timezone.utc)
    _task(
        project_id="bravo",
        review_version="v2",
        copy_from_version="z-base",
        task_type=2,
        state=2,
        score=70,
        create_time=base + timedelta(days=1),
        severity_summary={"5": 2, "1": 1},
    )
    alpha = _task(
        project_id="alpha",
        review_version="v3",
        copy_from_version="y-base",
        task_type=1,
        state=1,
        score=90,
        create_time=base + timedelta(days=2),
    )
    _code_file(alpha, [Issue(severity=4, description="issue", suggestion="fix")])
    _task(
        project_id="charlie",
        review_version="v1",
        copy_from_version="x-base",
        task_type=2,
        state=0,
        score=50,
        create_time=base,
    )

    response = client.get(
        "/api/admin/tasks",
        params={"sort_by": sort_by, "sort_order": "asc"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["sort_by"] == sort_by
    assert body["sort_order"] == "asc"
    assert body["items"][0]["project_id"] == expected_project


def test_admin_api_defaults_to_twenty_items_and_normalizes_large_page(client):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index in range(25):
        _task(
            project_id=f"project-{index:02d}",
            review_version=f"v{index:02d}",
            create_time=base + timedelta(days=index),
            severity_summary={},
        )

    first_page = client.get("/api/admin/tasks").json()
    assert first_page["pagination"] == {
        "page": 1,
        "page_size": 20,
        "total_items": 25,
        "total_pages": 2,
    }
    assert len(first_page["items"]) == 20
    assert first_page["items"][0]["project_id"] == "project-24"

    last_page = client.get("/api/admin/tasks", params={"page": 99}).json()
    assert last_page["pagination"]["page"] == 2
    assert len(last_page["items"]) == 5
    assert client.get("/api/admin/tasks", params={"page_size": 101}).status_code == 422


def test_admin_api_rejects_invalid_filters(client):
    invalid_range = client.get(
        "/api/admin/tasks",
        params={
            "date_from": "2026-07-15T00:00:00Z",
            "date_to": "2026-07-10T00:00:00Z",
        },
    )

    assert invalid_range.status_code == 422
    assert invalid_range.json()["error"]["code"] == "invalid_date_range"
    assert client.get("/api/admin/tasks", params={"sort_by": "unknown"}).status_code == 422
    assert client.get("/api/admin/tasks", params={"task_type": 3}).status_code == 422
