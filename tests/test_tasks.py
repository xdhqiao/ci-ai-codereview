from app.models.code_file import CodeBlock, CodeFileModel
from app.models.task import TaskModel


def test_task_crud(client):
    payload = {
        "project_id": "project-a",
        "review_version": "/tmp/head",
        "copy_from_version": "/tmp/base",
        "task_type": 1,
        "state": 0,
        "submitter": "tester",
    }

    created = client.post("/tasks", json=payload)
    assert created.status_code == 201
    task_id = created.json()["id"]

    fetched = client.get(f"/tasks/{task_id}")
    assert fetched.status_code == 200
    assert fetched.json()["project_id"] == "project-a"

    listed = client.get("/tasks")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    deleted = client.delete(f"/tasks/{task_id}")
    assert deleted.status_code == 204

    missing = client.get(f"/tasks/{task_id}")
    assert missing.status_code == 404


def test_failed_block_retry_is_async_high_priority_and_idempotent(client):
    task = TaskModel(
        project_id="retry-project",
        review_version="feature",
        copy_from_version="master",
        task_type=1,
        state=3,
        completion_status="partial",
    ).save()
    CodeFileModel(
        task_id=str(task.id),
        project_id=task.project_id,
        review_version=task.review_version,
        copy_from_version=task.copy_from_version,
        task_type=1,
        file_name="main.c",
        state=3,
        code_blocks=[
            CodeBlock(block_id=0, contents=["     1+  int ok;"], main_task_completed=True, review_state=2),
            CodeBlock(
                block_id=1,
                contents=["     2+  int failed;"],
                main_task_completed=False,
                failure_message="upstream timeout",
                review_state=3,
                review_attempt_count=2,
            ),
        ],
        extra={"status": "partial"},
    ).save()

    first = client.post(f"/tasks/{task.id}/retry-failures")
    second = client.post(f"/tasks/{task.id}/retry-failures")

    assert first.status_code == 202
    assert second.status_code == 202
    body = second.json()
    assert body["state"] == 0
    assert body["completion_status"] == "retry_pending"
    assert body["dispatch_priority"] == 100
    assert body["retry_failed_only"] is True
    assert body["automatic_retry_pending"] is False
    assert body["manual_retry_count"] == 1
    code_file = CodeFileModel.objects(task_id=str(task.id)).first()
    assert code_file.code_blocks[0].main_task_completed is True
    assert code_file.code_blocks[1].review_attempt_count == 2
    assert code_file.code_blocks[1].failure_message == "upstream timeout"


def test_retry_api_rejects_task_without_failed_blocks(client):
    task = TaskModel(
        project_id="complete-project",
        review_version="feature",
        copy_from_version="master",
        task_type=1,
        state=3,
        completion_status="partial",
    ).save()
    CodeFileModel(
        task_id=str(task.id),
        project_id=task.project_id,
        review_version=task.review_version,
        copy_from_version=task.copy_from_version,
        file_name="main.c",
        code_blocks=[CodeBlock(block_id=0, contents=["     1+  int ok;"], main_task_completed=True)],
        extra={"status": "reviewed"},
    ).save()

    response = client.post(f"/tasks/{task.id}/retry-failures")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_retryable_failures"


def test_retry_api_rejects_mixed_failed_and_pending_blocks(client):
    task = TaskModel(
        project_id="mixed-retry-project",
        review_version="feature",
        copy_from_version="master",
        task_type=1,
        state=3,
        completion_status="partial",
    ).save()
    CodeFileModel(
        task_id=str(task.id),
        project_id=task.project_id,
        review_version=task.review_version,
        copy_from_version=task.copy_from_version,
        file_name="main.c",
        code_blocks=[
            CodeBlock(
                block_id=0,
                contents=["     1+  int failed;"],
                failure_message="timeout",
                review_state=3,
            ),
            CodeBlock(block_id=1, contents=["     2+  int pending;"], review_state=0),
        ],
        extra={"status": "partial"},
    ).save()

    response = client.post(f"/tasks/{task.id}/retry-failures")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "task_review_in_progress"
