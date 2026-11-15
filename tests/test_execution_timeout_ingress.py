"""#939: the additive execution duration through CLI/CyberGym, HTTP admission and the queue.

``execution_timeout_sec`` (CLI ``--execution-timeout``) is pause-excluded execution time
from dispatch; legacy ``timeout_sec``/``timeout`` (CLI ``--timeout``) keep their meaning of a
calendar ``deadline_at`` counted from submission, queue included. Absent or 0 adds no limit.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from ouroboros.gateway.tasks import api_tasks_create
from ouroboros.task_results import load_task_result

pytestmark = pytest.mark.serial


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    from supervisor import queue, workers

    data = tmp_path / "gateway-data"
    repo = tmp_path / "gateway-repo"
    data.mkdir()
    repo.mkdir()
    monkeypatch.setattr(queue, "DRIVE_ROOT", data)
    monkeypatch.setattr(queue, "PENDING", [])
    monkeypatch.setattr(queue, "RUNNING", {})
    monkeypatch.setattr(queue, "ACCEPTANCE_FENCES", {})
    monkeypatch.setattr(queue, "ADMISSION_RESERVATIONS", {})
    monkeypatch.setattr(workers, "WORKERS", {0: SimpleNamespace(busy_task_id=None, reaping=False)})
    monkeypatch.setattr(workers, "_WORKER_POOL_DISABLED_REASON", "")
    app = Starlette(routes=[Route("/api/tasks", api_tasks_create, methods=["POST"])])
    app.state.drive_root = data
    app.state.repo_dir = repo
    with TestClient(app) as client:
        yield client, queue, data


@pytest.mark.parametrize("limits", [{}, {"execution_timeout_sec": 0}, {"execution_timeout_sec": 12.5}])
def test_api_execution_duration_is_durable_without_a_calendar_deadline(gateway, limits):
    client, queue, data = gateway
    response = client.post("/api/tasks", json={"description": "work", **limits})
    assert response.status_code == 200, response.text
    task = queue.PENDING[0]
    saved = load_task_result(data, response.json()["task_id"])
    assert task["deadline_at"] == saved["deadline_at"] == ""
    assert task.get("execution_timeout_sec") == saved.get("execution_timeout_sec") == limits.get("execution_timeout_sec")
    assert "started_at" not in task  # the queue wait before dispatch is never execution
    assert "execution_timeout_sec" not in (task.get("metadata") or {})  # one top-level carrier


@pytest.mark.parametrize("calendar", [{"timeout_sec": 40}, {"timeout": 40},
                                      {"deadline_at": "2030-01-01T00:00:00Z", "timeout_sec": 40}])
def test_api_execution_duration_keeps_legacy_calendar_semantics(gateway, monkeypatch, calendar):
    client, queue, _data = gateway
    monkeypatch.setattr("ouroboros.gateway._helpers.time.time", lambda: 1_000_000_000.0)
    response = client.post("/api/tasks", json={"description": "work", "execution_timeout_sec": 90, **calendar})
    assert response.status_code == 200, response.text
    task = queue.PENDING[0]
    assert task["execution_timeout_sec"] == 90
    if "deadline_at" in calendar:
        assert task["deadline_at"] == calendar["deadline_at"]
    else:  # submit-anchored, queue included, exactly as before
        assert datetime.fromisoformat(task["deadline_at"].replace("Z", "+00:00")).timestamp() == 1_000_000_040.0


@pytest.mark.parametrize("value", [-1, 10**400, "10", True, None, {}, []])
def test_api_invalid_execution_duration_never_enqueues(gateway, value):
    client, queue, _data = gateway
    response = client.post("/api/tasks", json={"description": "work", "execution_timeout_sec": value})
    assert response.status_code == 400
    assert queue.PENDING == []


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity"])
def test_api_nonfinite_execution_duration_never_enqueues(gateway, raw):
    client, queue, _data = gateway
    response = client.post("/api/tasks", content='{"description":"work","execution_timeout_sec":' + raw + '}',
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 400
    assert queue.PENDING == []


def test_api_execution_duration_requires_top_level(gateway):
    client, queue, _data = gateway
    response = client.post("/api/tasks", json={"description": "work", "metadata": {"execution_timeout_sec": 10}})
    assert response.status_code == 400
    assert "top-level" in response.json()["error"]
    assert queue.PENDING == []


@pytest.mark.parametrize("legacy_timeout", [0, 70])
def test_cli_execution_duration_reaches_the_api_without_changing_the_wait(gateway, monkeypatch, legacy_timeout):
    from ouroboros import cli

    client, queue, _data = gateway
    waits = []

    class GatewayClient:
        def request(self, method, path, body=None):
            assert method == "POST"
            response = client.post(path, json=body)
            assert response.status_code == 200, response.text
            return response.json()

    monkeypatch.setattr(cli, "_client", lambda *a, **kw: GatewayClient())
    monkeypatch.setattr(cli, "_wait_task", lambda _client, _tid, *, timeout_sec:
                        waits.append(timeout_sec) or {"status": "completed", "result": "done"})
    monkeypatch.setattr(cli, "_await_cost_finality", lambda _client, _tid, result: result)
    assert cli.main(["run", "--no-stream", "--execution-timeout", "30", "--timeout", str(legacy_timeout), "work"]) == 0
    assert queue.PENDING[0]["execution_timeout_sec"] == 30
    assert bool(queue.PENDING[0]["deadline_at"]) is bool(legacy_timeout)
    # The CLI's own wait stays the calendar one; the execution budget adds no wall-clock wait.
    assert waits == [cli._deadline_wait_timeout(legacy_timeout)]


@pytest.mark.parametrize("value", ["nan", "inf", "-1"])
def test_cli_refuses_an_invalid_execution_duration_before_posting(monkeypatch, value):
    from ouroboros import cli

    monkeypatch.setattr(cli, "_client", lambda *a, **kw: SimpleNamespace(
        request=lambda *a, **kw: pytest.fail("an invalid duration must not submit")))
    assert cli.main(["run", "--detach", "--execution-timeout", value, "work"]) != 0




