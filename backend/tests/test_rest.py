from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport

import app.core.scheduler as scheduler_module
from app.config import get_settings
from tests.test_scheduler import fake_run_claude

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
async def client(tmp_path: Path, repo: Path, monkeypatch):
    monkeypatch.setenv("DEVWORKSPACE_REPO_ROOT", str(repo))
    monkeypatch.setenv("DEVWORKSPACE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DEVWORKSPACE_TOKEN", "test-token")
    get_settings.cache_clear()

    from app.main import create_app

    fastapi_app = create_app()
    monkeypatch.setattr(scheduler_module, "run_claude", fake_run_claude)

    async with LifespanManager(fastapi_app) as manager:
        transport = ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    get_settings.cache_clear()


async def _wait_for_pending(client: httpx.AsyncClient, step_kind: str, tries: int = 500) -> dict:
    for _ in range(tries):
        r = await client.get("/api/approvals", headers=AUTH)
        for a in r.json():
            if a["step_kind"] == step_kind and a["status"] == "pending":
                return a
        await asyncio.sleep(0.01)
    raise TimeoutError(f"no pending {step_kind} approval appeared")


@pytest.mark.asyncio
async def test_unauthorized_without_token(client: httpx.AsyncClient):
    r = await client.get("/api/ping")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_healthz_needs_no_auth(client: httpx.AsyncClient):
    r = await client.get("/healthz")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_full_flow_via_rest(client: httpx.AsyncClient):
    r = await client.post("/api/sessions", json={"title": "add hello"}, headers=AUTH)
    assert r.status_code == 200
    session = r.json()

    r = await client.post(f"/api/sessions/{session['id']}/request", json={"text": "add hello file"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"status": "planning"}

    plan_approval = await _wait_for_pending(client, "plan")

    r = await client.get(f"/api/sessions/{session['id']}/artifacts", params={"kind": "plan"}, headers=AUTH)
    assert r.json()[0]["body"]["tasks"][0]["branch"] == "feat/hello"

    r = await client.post(f"/api/approvals/{plan_approval['id']}/decision", json={"approved": True}, headers=AUTH)
    assert r.status_code == 200

    # re-deciding an already-resolved approval should 409, not silently succeed
    r = await client.post(f"/api/approvals/{plan_approval['id']}/decision", json={"approved": True}, headers=AUTH)
    assert r.status_code == 409

    task_approval = await _wait_for_pending(client, "task")
    r = await client.get(f"/api/sessions/{session['id']}/artifacts", params={"kind": "diff"}, headers=AUTH)
    assert "hello.txt" in r.json()[0]["body"]["patch"]

    r = await client.post(f"/api/approvals/{task_approval['id']}/decision", json={"approved": True}, headers=AUTH)
    assert r.status_code == 200

    final_tasks = []
    for _ in range(500):
        r = await client.get(f"/api/sessions/{session['id']}", headers=AUTH)
        final_tasks = r.json()["tasks"]
        if final_tasks and final_tasks[0]["status"] == "done":
            break
        await asyncio.sleep(0.01)
    assert final_tasks and final_tasks[0]["status"] == "done"

    r = await client.get("/api/cost", headers=AUTH)
    assert r.json()["total"] > 0

    r = await client.get(f"/api/tasks/{final_tasks[0]['id']}", headers=AUTH)
    kinds = {a["kind"] for a in r.json()["artifacts"]}
    assert {"diff", "review", "test_report"} <= kinds


@pytest.mark.asyncio
async def test_killing_session_cancels_in_flight_planner_call(client: httpx.AsyncClient, monkeypatch):
    """Closing a session must actually stop in-flight agent work, not just
    relabel it - otherwise a killed session leaves an orphaned claude
    subprocess running with nothing left tracking or displaying it.
    """
    started = asyncio.Event()
    cancelled = False

    async def slow_planner(prompt, *, cwd, role, **kwargs):
        nonlocal cancelled
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled = True
            raise
        raise AssertionError("should have been cancelled before returning")

    monkeypatch.setattr(scheduler_module, "run_claude", slow_planner)

    r = await client.post("/api/sessions", json={"title": "will be killed"}, headers=AUTH)
    session_id = r.json()["id"]

    r = await client.post(f"/api/sessions/{session_id}/request", json={"text": "do something slow"}, headers=AUTH)
    assert r.status_code == 200

    await asyncio.wait_for(started.wait(), timeout=5)

    r = await client.post(f"/api/sessions/{session_id}/close", headers=AUTH)
    assert r.status_code == 200

    assert cancelled is True

    r = await client.get("/api/approvals", headers=AUTH)
    assert all(a["session_id"] != session_id for a in r.json())
