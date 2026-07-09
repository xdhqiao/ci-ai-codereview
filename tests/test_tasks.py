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
