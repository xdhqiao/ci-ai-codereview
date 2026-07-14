def test_health_check(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_scheduler_health_check(client):
    response = client.get("/health/scheduler")

    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "running": False,
        "active_task_id": "",
        "active_task_type": 0,
        "active_future_present": False,
        "active_future_done": None,
        "active_lease_present": False,
        "stop_requested": False,
        "next_run_time": None,
    }
