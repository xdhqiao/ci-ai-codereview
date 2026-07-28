from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from app.models.code_file import CodeBlock, CodeFileModel, Issue
from app.models.issue_feedback_log import IssueFeedbackLog
from app.models.task import TaskModel


def _feedback_log(
    *,
    project_id: str,
    review_version: str,
    copy_from_version: str,
    file_name: str,
    file_author: str,
    severity: int,
    feedback_type: str,
    create_time: datetime,
    feedback_content: str = "",
) -> IssueFeedbackLog:
    return IssueFeedbackLog(
        task_id=f"{project_id}-{review_version}",
        project_id=project_id,
        review_version=review_version,
        copy_from_version=copy_from_version,
        task_type=2,
        file_name=file_name,
        file_author=file_author,
        issue_line_numbers="10-12",
        severity=severity,
        suggestion=f"fix {file_name}",
        description=f"problem {file_name}",
        feedback_type=feedback_type,
        feedback_content=feedback_content,
        create_time=create_time,
    ).save()


def test_feedback_api_appends_immutable_log_for_every_submission(client):
    task = TaskModel(
        project_id="feedback-history",
        review_version="feature",
        copy_from_version="master",
        task_type=2,
        state=2,
    ).save()
    code_file = CodeFileModel(
        task_id=str(task.id),
        project_id=task.project_id,
        review_version=task.review_version,
        copy_from_version=task.copy_from_version,
        task_type=task.task_type,
        file_name="src/auth.c",
        file_author="dahai",
        code_blocks=[
            CodeBlock(
                block_id=0,
                contents=["    10+  strcpy(dst, src);"],
                issues=[
                    Issue(
                        issue_id=0,
                        issue_line_numbers="10",
                        severity=5,
                        description="unsafe copy",
                        suggestion="use a bounded copy",
                    )
                ],
            )
        ],
    ).save()

    agree = client.post(f"/api/feedback/{code_file.id}/0/0", json={"feedback_type": "agree"})
    reject = client.post(
        f"/api/feedback/{code_file.id}/0/0",
        json={"feedback_type": "reject", "feedback_content": "This report is incorrect."},
    )

    assert agree.status_code == 200
    assert reject.status_code == 200
    logs = list(IssueFeedbackLog.objects.order_by("create_time", "id"))
    assert len(logs) == 2
    assert [item.feedback_type for item in logs] == ["agree", "reject"]
    assert logs[0].task_id == str(task.id)
    assert logs[0].project_id == "feedback-history"
    assert logs[0].review_version == "feature"
    assert logs[0].copy_from_version == "master"
    assert logs[0].task_type == 2
    assert logs[0].file_name == "src/auth.c"
    assert logs[0].file_author == "dahai"
    assert logs[0].issue_line_numbers == "10"
    assert logs[0].severity == 5
    assert logs[0].description == "unsafe copy"
    assert logs[0].suggestion == "use a bounded copy"
    assert logs[0].feedback_content == ""
    assert logs[1].feedback_content == "This report is incorrect."

    code_file.reload()
    assert code_file.code_blocks[0].issues[0].feedback_type == "reject"
    assert code_file.code_blocks[0].issues[0].feedback_content == "This report is incorrect."


def test_feedback_log_report_supports_raw_version_author_and_detail_views(client):
    base_time = datetime(2026, 7, 1, 8, tzinfo=timezone.utc)
    _feedback_log(
        project_id="project-a",
        review_version="release-1",
        copy_from_version="master",
        file_name="src/a.c",
        file_author="dahai",
        severity=5,
        feedback_type="agree",
        create_time=base_time,
    )
    _feedback_log(
        project_id="project-a",
        review_version="release-1",
        copy_from_version="master",
        file_name="src/b.c",
        file_author="dahai",
        severity=5,
        feedback_type="reject",
        feedback_content="false positive",
        create_time=base_time + timedelta(days=1),
    )
    _feedback_log(
        project_id="project-b",
        review_version="release-2",
        copy_from_version="0_version",
        file_name="src/c.c",
        file_author="xiaoming",
        severity=3,
        feedback_type="agree",
        create_time=base_time + timedelta(days=2),
    )
    _feedback_log(
        project_id="project-b",
        review_version="release-2",
        copy_from_version="0_version",
        file_name="src/d.c",
        file_author="",
        severity=4,
        feedback_type="reject",
        feedback_content="accepted risk",
        create_time=base_time + timedelta(days=3),
    )
    _feedback_log(
        project_id="outside",
        review_version="old",
        copy_from_version="master",
        file_name="src/old.c",
        file_author="dahai",
        severity=5,
        feedback_type="agree",
        create_time=base_time - timedelta(days=2),
    )
    dates = {"start_date": "2026-07-01", "end_date": "2026-07-31"}

    raw = client.get(
        "/api/admin/feedback-logs",
        params={**dates, "group_by": "none", "page": 1, "page_size": 2},
    )

    assert raw.status_code == 200
    body = raw.json()
    assert body["summary"] == {
        "feedback_count": 4,
        "agree_rate": 50.0,
        "severe_feedback_count": 2,
        "severe_agree_rate": 50.0,
    }
    assert body["pagination"] == {
        "page": 1,
        "page_size": 2,
        "total_items": 4,
        "total_pages": 2,
    }
    assert [item["file_name"] for item in body["log_items"]] == ["src/a.c", "src/b.c"]
    assert body["log_items"][1]["feedback_content"] == "false positive"

    second_page = client.get(
        "/api/admin/feedback-logs",
        params={**dates, "group_by": "none", "page": 2, "page_size": 2},
    ).json()
    assert [item["file_name"] for item in second_page["log_items"]] == ["src/c.c", "src/d.c"]

    versions = client.get(
        "/api/admin/feedback-logs",
        params={**dates, "group_by": "version"},
    ).json()
    assert len(versions["version_items"]) == 2
    first_version = versions["version_items"][0]
    assert first_version == {
        "project_id": "project-a",
        "review_version": "release-1",
        "copy_from_version": "master",
        "issue_count": 2,
        "agree_rate": 50.0,
        "severe_issue_count": 2,
        "severe_agree_rate": 50.0,
        "detail_url": first_version["detail_url"],
    }
    detail_query = parse_qs(urlparse(first_version["detail_url"]).query)
    assert detail_query == {
        "project_id": ["project-a"],
        "review_version": ["release-1"],
        "copy_from_version": ["master"],
        "start_date": ["2026-07-01"],
        "end_date": ["2026-07-31"],
    }

    authors = client.get(
        "/api/admin/feedback-logs",
        params={**dates, "group_by": "author"},
    ).json()
    assert len(authors["author_items"]) == 3
    dahai = next(item for item in authors["author_items"] if item["file_author"] == "dahai")
    assert dahai["issue_count"] == 2
    assert dahai["agree_rate"] == 50.0
    author_detail_query = parse_qs(urlparse(dahai["detail_url"]).query)
    assert author_detail_query == {
        "file_author": ["dahai"],
        "start_date": ["2026-07-01"],
        "end_date": ["2026-07-31"],
    }
    empty = next(item for item in authors["author_items"] if item["file_author"] == "")
    assert empty["author_name"]
    assert parse_qs(urlparse(empty["detail_url"]).query)["file_author"] == ["__empty__"]

    author_detail = client.get(
        "/api/admin/feedback-logs/author-detail",
        params={**dates, "file_author": "dahai", "page": 1, "page_size": 1},
    )
    assert author_detail.status_code == 200
    author_body = author_detail.json()
    assert author_body["file_author"] == "dahai"
    assert author_body["summary"] == {
        "feedback_count": 2,
        "agree_rate": 50.0,
        "severe_feedback_count": 2,
        "severe_agree_rate": 50.0,
    }
    assert author_body["pagination"] == {
        "page": 1,
        "page_size": 1,
        "total_items": 2,
        "total_pages": 2,
    }
    assert [item["file_name"] for item in author_body["items"]] == ["src/a.c"]
    author_second_page = client.get(
        "/api/admin/feedback-logs/author-detail",
        params={**dates, "file_author": "dahai", "page": 2, "page_size": 1},
    ).json()
    assert [item["file_name"] for item in author_second_page["items"]] == ["src/b.c"]

    empty_author_detail = client.get(
        "/api/admin/feedback-logs/author-detail",
        params={**dates, "file_author": "__empty__"},
    )
    assert empty_author_detail.status_code == 200
    assert empty_author_detail.json()["file_author"] == ""
    assert [item["file_name"] for item in empty_author_detail.json()["items"]] == ["src/d.c"]

    detail = client.get(
        "/api/admin/feedback-logs/detail",
        params={
            **dates,
            "project_id": "project-a",
            "review_version": "release-1",
            "copy_from_version": "master",
        },
    )
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["summary"]["feedback_count"] == 2
    assert [item["file_name"] for item in detail_body["items"]] == ["src/a.c", "src/b.c"]
    assert [item["severity"] for item in detail_body["items"]] == [5, 5]


def test_feedback_log_pages_are_offline_default_to_recent_month_and_validate_dates(client):
    main_page = client.get("/admin/feedback-logs.html")
    detail_page = client.get("/admin/feedback-log-detail.html")
    author_detail_page = client.get("/admin/feedback-log-author-detail.html")

    assert main_page.status_code == 200
    assert detail_page.status_code == 200
    assert author_detail_page.status_code == 200
    assert 'id="group-by"' in main_page.text
    assert 'id="apply-filter"' in main_page.text
    assert ".loading[hidden] { display: none; }" in client.get("/static/feedback_logs.css").text
    assert 'href="/admin/feedback-logs.html"' in detail_page.text
    assert 'aria-label="负责人反馈日志分页"' in author_detail_page.text
    assert "https://" not in main_page.text
    assert "http://" not in main_page.text
    for asset in [
        "/static/feedback_logs.css",
        "/static/feedback_logs.js",
        "/static/feedback_log_detail.js",
        "/static/feedback_log_author_detail.js",
    ]:
        response = client.get(asset)
        assert response.status_code == 200
        assert "https://" not in response.text
        assert "http://" not in response.text

    default_report = client.get("/api/admin/feedback-logs")
    assert default_report.status_code == 200
    body = default_report.json()
    start_date = datetime.fromisoformat(body["start_date"]).date()
    end_date = datetime.fromisoformat(body["end_date"]).date()
    assert (end_date - start_date).days == 29

    invalid_range = client.get(
        "/api/admin/feedback-logs",
        params={"start_date": "2026-07-20", "end_date": "2026-07-01"},
    )
    assert invalid_range.status_code == 422
    assert client.get("/api/admin/feedback-logs", params={"group_by": "invalid"}).status_code == 422
    assert client.get("/api/admin/feedback-logs/detail").status_code == 422
    assert client.get("/api/admin/feedback-logs/author-detail").status_code == 422

    admin_page = client.get("/admin/tasks.html")
    assert 'href="/admin/feedback-logs.html"' in admin_page.text
