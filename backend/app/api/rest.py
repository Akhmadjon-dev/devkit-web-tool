from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.scheduler import SchedulerError
from app.models import ApprovalStatus, Plan
from app.services import AppServices

logger = logging.getLogger("devworkspace.rest")

router = APIRouter(prefix="/api")


def _services(request: Request) -> AppServices:
    return request.app.state.services


@router.get("/ping")
async def ping() -> dict:
    return {"pong": True}


# -- Sessions --------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    title: str
    base_branch: str | None = None


@router.post("/sessions")
async def create_session(body: CreateSessionRequest, request: Request) -> dict:
    services = _services(request)
    base_branch = body.base_branch or services.settings.base_branch
    session = await services.sessions.create(body.title, base_branch=base_branch)
    return {
        "id": session.id, "title": session.title, "branch": session.branch,
        "worktree_path": session.worktree_path, "status": session.status.value,
    }


@router.get("/sessions")
async def list_sessions(request: Request) -> list[dict]:
    services = _services(request)
    return [
        {"id": s.id, "title": s.title, "branch": s.branch, "worktree_path": s.worktree_path, "status": s.status.value}
        for s in services.sessions.list()
    ]


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, request: Request) -> dict:
    services = _services(request)
    session = services.sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    tasks = services.db.fetch_all("SELECT * FROM tasks WHERE session_id = ? ORDER BY created_at", (session_id,))
    return {
        "id": session.id, "title": session.title, "branch": session.branch,
        "worktree_path": session.worktree_path, "status": session.status.value,
        "tasks": [dict(t) for t in tasks],
        "cost": services.cost.session_cost(session_id),
    }


@router.post("/sessions/{session_id}/close")
async def close_session(session_id: str, request: Request) -> dict:
    services = _services(request)
    try:
        await services.sessions.close(session_id)
    except KeyError:
        raise HTTPException(404, "session not found")
    return {"ok": True}


class SubmitRequestBody(BaseModel):
    text: str


@router.post("/sessions/{session_id}/request")
async def submit_request(session_id: str, body: SubmitRequestBody, request: Request) -> dict:
    """Kicks off the Planner in the background - the plan artifact + gate-1
    approval arrive over the session's WebSocket topic when ready, since a
    real planner call can take well over the lifetime of one HTTP request.
    """
    services = _services(request)
    session = services.sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "session not found")

    async def _run() -> None:
        try:
            await services.scheduler.submit_request(session, body.text)
        except SchedulerError as e:
            logger.error("planner failed for session %s: %s", session_id, e)
            from app.bus import bus

            bus.publish(f"session:{session_id}", {"event": "planner_failed", "detail": str(e)})

    asyncio.create_task(_run())
    return {"status": "planning"}


# -- Artifacts / tasks -------------------------------------------------------


@router.get("/sessions/{session_id}/artifacts")
async def list_session_artifacts(session_id: str, kind: str | None, request: Request) -> list[dict]:
    services = _services(request)
    artifacts = services.artifacts.for_session(session_id)
    if kind:
        artifacts = [a for a in artifacts if a["kind"] == kind]
    return artifacts


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, request: Request) -> dict:
    services = _services(request)
    row = services.db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    if row is None:
        raise HTTPException(404, "task not found")
    return {**dict(row), "artifacts": services.artifacts.for_task(task_id)}


# -- Approvals ---------------------------------------------------------------


class DecisionBody(BaseModel):
    approved: bool
    reason: str | None = None
    edited_plan: Plan | None = None


@router.get("/approvals")
async def list_pending_approvals(request: Request) -> list[dict]:
    services = _services(request)
    return services.approvals.pending()


@router.post("/approvals/{approval_id}/decision")
async def decide_approval(approval_id: str, body: DecisionBody, request: Request) -> dict:
    services = _services(request)
    row = services.db.fetch_one("SELECT * FROM approvals WHERE id = ?", (approval_id,))
    if row is None:
        raise HTTPException(404, "approval not found")
    if row["status"] != ApprovalStatus.pending.value:
        raise HTTPException(409, f"approval already {row['status']}")

    session = services.sessions.get(row["session_id"])
    if session is None:
        raise HTTPException(404, "session not found for this approval")

    if row["step_kind"] == "plan":
        try:
            plan, id_map = await services.scheduler.resolve_plan(
                session, approval_id, approved=body.approved, edited_plan=body.edited_plan, reason=body.reason
            )
        except SchedulerError as e:
            raise HTTPException(400, str(e))
        if body.approved and plan is not None:
            asyncio.create_task(services.scheduler.run_all_tasks(session, plan, id_map))
        return {"ok": True, "step_kind": "plan"}

    # step_kind == "task": the scheduler's run_task() is already parked on
    # approvals.wait_for() in the background - resolving here unblocks it.
    await services.approvals.resolve(
        approval_id, ApprovalStatus.approved if body.approved else ApprovalStatus.rejected, body.reason
    )
    return {"ok": True, "step_kind": "task"}


# -- Cost ---------------------------------------------------------------


@router.get("/cost")
async def cost(request: Request) -> dict:
    services = _services(request)
    sessions = services.sessions.list()
    return {
        "total": services.cost.total_cost(),
        "sessions": [{"id": s.id, "title": s.title, "cost": services.cost.session_cost(s.id)} for s in sessions],
    }


# -- Worktrees (lifecycle view, fleshed out further in Phase 3) -------------


@router.get("/worktrees")
async def list_worktrees(request: Request) -> list[dict]:
    services = _services(request)
    rows = services.db.fetch_all("SELECT * FROM worktrees ORDER BY id")
    return [dict(r) for r in rows]
