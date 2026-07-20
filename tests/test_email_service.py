import logging
from pathlib import Path

import pytest

from app.core.config import Settings
from app.models.code_file import CodeBlock, CodeFileModel, Issue
from app.models.task import TaskModel
from app.services.email_service import EmailServer
from app.services.notification import ReviewNotificationService


class CapturingEmailServer:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    def send(self, subject, email_template, parameters, receivers):
        self.messages.append(
            {
                "subject": subject,
                "email_template": email_template,
                "parameters": parameters,
                "receivers": list(receivers),
            }
        )
        return "rendered"


def _completed_task() -> TaskModel:
    return TaskModel(
        project_id="demo_c",
        review_version="feature/a",
        copy_from_version="master",
        task_type=2,
        state=2,
        score=88,
        logic_score=90,
        performance_score=91,
        security_score=82,
        readable_score=89,
        code_style_score=88,
    ).save()


def _code_file(task: TaskModel, file_name: str, author: str, issues: list[Issue]) -> CodeFileModel:
    return CodeFileModel(
        task_id=str(task.id),
        project_id=task.project_id,
        review_version=task.review_version,
        copy_from_version=task.copy_from_version,
        task_type=task.task_type,
        file_name=file_name,
        file_author=author,
        code_blocks=[CodeBlock(block_id=0, contents=["     1+  code"], issues=issues)],
    ).save()


def test_review_completion_sends_one_admin_email_and_one_email_per_issue_owner():
    task = _completed_task()
    _code_file(
        task,
        "src/auth.c",
        "dahai",
        [
            Issue(
                issue_id=0,
                severity=5,
                issue_line_numbers="12",
                type="security",
                description="unchecked <input>",
                suggestion="validate & reject",
            ),
            Issue(issue_id=1, severity=3, type="logic", description="other", suggestion="fix"),
            Issue(
                issue_id=2,
                severity=5,
                type="filtered",
                description="false positive",
                suggestion="none",
                filter_status="FILTERED",
            ),
        ],
    )
    _code_file(
        task,
        "src/config.c",
        "xiaoming",
        [Issue(issue_id=0, severity=5, issue_line_numbers="8-9", type="logic", description="bad", suggestion="fix")],
    )
    _code_file(
        task,
        "src/unowned.c",
        "",
        [Issue(issue_id=0, severity=2, type="style", description="minor", suggestion="fix")],
    )
    settings = Settings(
        email_admin_receivers="admin-a@example.com, admin-b@example.com,admin-a@example.com",
        email_account_domain="corp.example.com",
        email_report_base_url="http://review.internal:8000",
    )
    email_server = CapturingEmailServer()

    completed = ReviewNotificationService(settings, email_server).send_review_completed(task)

    assert completed is True
    assert len(email_server.messages) == 3
    admin, dahai, xiaoming = email_server.messages
    assert admin["receivers"] == ["admin-a@example.com", "admin-b@example.com"]
    assert dahai["receivers"] == ["dahai@corp.example.com"]
    assert xiaoming["receivers"] == ["xiaoming@corp.example.com"]
    assert all(message["email_template"] == "review_completed_email.html" for message in email_server.messages)
    assert admin["subject"] == "代码审核完成：demo_c feature/a_vs_master"

    admin_parameters = admin["parameters"]
    assert "大海" in admin_parameters["owner_rows"]
    assert "小明" in admin_parameters["owner_rows"]
    assert "空" in admin_parameters["owner_rows"]
    assert admin_parameters["owner_rows"].count("<tr>") == 3
    assert admin_parameters["severe_issue_rows"].count("<tr>") == 2
    assert "unchecked &lt;input&gt;" in admin_parameters["severe_issue_rows"]
    assert "validate &amp; reject" in admin_parameters["severe_issue_rows"]
    assert "false positive" not in admin_parameters["severe_issue_rows"]
    assert admin_parameters["report_path"] == "/demo_c/feature%2Fa_vs_master.html"
    assert admin_parameters["report_url"] == "http://review.internal:8000/demo_c/feature%2Fa_vs_master.html"

    assert dahai["parameters"]["owner_rows"].count("<tr>") == 1
    assert "大海" in dahai["parameters"]["owner_rows"]
    assert "小明" not in dahai["parameters"]["owner_rows"]
    assert "src/auth.c" in dahai["parameters"]["severe_issue_rows"]
    assert "src/config.c" not in dahai["parameters"]["severe_issue_rows"]
    assert "src/config.c" in xiaoming["parameters"]["severe_issue_rows"]


def test_owner_with_only_non_severe_issues_still_receives_an_individual_email():
    task = _completed_task()
    _code_file(
        task,
        "src/minor.c",
        "dahai",
        [Issue(issue_id=0, severity=2, type="style", description="minor", suggestion="fix")],
    )
    email_server = CapturingEmailServer()
    settings = Settings(email_admin_receivers="", email_account_domain="example.com")

    ReviewNotificationService(settings, email_server).send_review_completed(task)

    assert len(email_server.messages) == 1
    message = email_server.messages[0]
    assert message["receivers"] == ["dahai@example.com"]
    assert "暂无严重问题" in message["parameters"]["severe_issue_rows"]


def test_email_server_renders_local_and_inline_templates_and_logs_mock_send(caplog, tmp_path: Path):
    template = tmp_path / "message.html"
    template.write_text("<html><body>$message</body></html>", encoding="utf-8")
    settings = Settings(email_sender="review@example.com")
    server = EmailServer(settings=settings, template_root=tmp_path)

    with caplog.at_level(logging.INFO):
        rendered = server.send(
            subject="done",
            email_template="message.html",
            parameters={"message": "审核完成"},
            receivers=["a@example.com", "a@example.com", " b@example.com "],
        )

    assert rendered == "<html><body>审核完成</body></html>"
    assert "sender=review@example.com" in caplog.text
    assert "receivers=a@example.com,b@example.com" in caplog.text
    assert server.render("<html>$value</html>", {"value": 42}) == "<html>42</html>"
    with pytest.raises(ValueError):
        server.render("../outside.html", {})


def test_packaged_email_template_contains_all_required_sections():
    settings = Settings(email_report_base_url="http://review.internal")
    server = EmailServer(settings=settings)
    parameters = {
        "project_id": "demo_c",
        "review_version": "master",
        "copy_from_version": "0_version",
        "score": 90,
        "logic_score": 91,
        "performance_score": 92,
        "security_score": 93,
        "readable_score": 94,
        "code_style_score": 95,
        "owner_rows": "<tr><td>大海</td><td>1</td><td>2</td></tr>",
        "severe_issue_rows": "<tr><td>1</td><td>src/auth.c</td></tr>",
        "report_path": "/demo_c/master_vs_0_version.html",
        "report_url": "http://review.internal/demo_c/master_vs_0_version.html",
    }

    rendered = server.render("review_completed_email.html", parameters)

    for expected in [
        "项目：",
        "版本：",
        "对比版本：",
        "总分：",
        "逻辑：",
        "性能：",
        "安全：",
        "可读性：",
        "代码风格：",
        "问题统计",
        "严重问题列表",
        "src/auth.c",
        "/demo_c/master_vs_0_version.html",
    ]:
        assert expected in rendered
    assert "https://" not in rendered
