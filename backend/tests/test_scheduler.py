from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import app.core.scheduler as scheduler_module
from app.core.executor import ENGINEER_ROLE, PLANNER_ROLE, REVIEWER_ROLE, ClaudeRunResult
from app.core.worktrees import run_git
from app.models import ApprovalStatus


def make_result(structured=None, ok: bool = True, error: str | None = None) -> ClaudeRunResult:
    return ClaudeRunResult(
        ok=ok,
        result_text=json.dumps(structured) if structured is not None else "",
        session_id="fake-session",
        total_cost_usd=0.001,
        num_turns=1,
        duration_ms=10,
        usage={"input_tokens": 10, "output_tokens": 5},
        raw_events=[],
        is_error=not ok,
        error_detail=error,
        structured=structured,
    )


async def fake_run_claude(
    prompt, *, cwd, role, claude_bin="claude", max_budget_usd=None, add_dirs=None,
    resume_session_id=None, timeout_seconds=None, on_event=None,
):
    """Stands in for the real `claude` CLI (blocked from this test environment).
    Planner/Reviewer return canned structured JSON; Engineer performs the real
    filesystem + git side effects a genuine engineer agent would produce, so
    the rest of the pipeline (diff capture, rebase, fast-forward merge) runs
    against real git operations rather than being mocked away too.
    """
    if role is PLANNER_ROLE:
        plan = {
            "tasks": [
                {
                    "id": "t1",
                    "title": "add hello file",
                    "spec": "create hello.txt containing 'hi'",
                    "role": "engineer",
                    "branch": "feat/hello",
                    "depends_on": [],
                }
            ]
        }
        return make_result(structured=plan)

    if role is ENGINEER_ROLE:
        (Path(cwd) / "hello.txt").write_text("hi\n")
        await run_git("add", "hello.txt", cwd=Path(cwd))
        await run_git(
            "-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "add hello.txt", cwd=Path(cwd)
        )
        return make_result(structured=None, ok=True)

    if role is REVIEWER_ROLE:
        review = {"verdict": "approve", "issues": [], "notes": "looks fine"}
        return make_result(structured=review)

    raise AssertionError(f"unexpected role passed to fake_run_claude: {role}")


@pytest.mark.asyncio
async def test_full_pipeline_plan_to_merge(services, repo, monkeypatch):
    monkeypatch.setattr(scheduler_module, "run_claude", fake_run_claude)

    session = await services.sessions.create("add hello file")

    _, plan_approval_id = await services.scheduler.submit_request(session, "please add a hello file")
    plan_row = services.db.fetch_one("SELECT * FROM approvals WHERE id = ?", (plan_approval_id,))
    assert plan_row["step_kind"] == "plan"
    plan_artifact = services.artifacts.get(plan_row["payload_ref"])
    assert plan_artifact["body"]["tasks"][0]["branch"] == "feat/hello"

    plan, id_map = await services.scheduler.resolve_plan(session, plan_approval_id, approved=True)
    assert plan is not None
    task_id = id_map["t1"]
    assert services.db.fetch_one("SELECT status FROM tasks WHERE id = ?", (task_id,))["status"] == "queued"

    runner = asyncio.create_task(services.scheduler.run_all_tasks(session, plan, id_map))

    approval_row = None
    for _ in range(1000):
        approval_row = services.db.fetch_one(
            "SELECT * FROM approvals WHERE task_id = ? AND step_kind = 'task' AND status = 'pending'",
            (task_id,),
        )
        if approval_row:
            break
        await asyncio.sleep(0.01)
    assert approval_row is not None, "engineer/reviewer steps never reached gate 2"

    diff_artifact = services.artifacts.get(approval_row["payload_ref"])
    assert "hello.txt" in diff_artifact["body"]["patch"]

    review_artifacts = services.artifacts.for_task(task_id, kind="review")
    assert review_artifacts and review_artifacts[0]["body"]["verdict"] == "approve"

    await services.approvals.resolve(approval_row["id"], ApprovalStatus.approved)
    await runner

    final = services.db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert final["status"] == "done"
    assert services.artifacts.for_task(task_id, kind="test_report")

    log = await run_git("log", "--oneline", "main", cwd=repo)
    assert "add hello.txt" in log
    assert services.cost.session_cost(session.id) > 0


@pytest.mark.asyncio
async def test_task_rejected_records_outcome_and_does_not_merge(services, repo, monkeypatch):
    monkeypatch.setattr(scheduler_module, "run_claude", fake_run_claude)

    session = await services.sessions.create("add hello file")
    _, plan_approval_id = await services.scheduler.submit_request(session, "please add a hello file")
    plan, id_map = await services.scheduler.resolve_plan(session, plan_approval_id, approved=True)
    task_id = id_map["t1"]

    runner = asyncio.create_task(services.scheduler.run_all_tasks(session, plan, id_map))

    approval_row = None
    for _ in range(1000):
        approval_row = services.db.fetch_one(
            "SELECT * FROM approvals WHERE task_id = ? AND step_kind = 'task' AND status = 'pending'",
            (task_id,),
        )
        if approval_row:
            break
        await asyncio.sleep(0.01)
    assert approval_row is not None

    await services.approvals.resolve(approval_row["id"], ApprovalStatus.rejected, reason="not what I wanted")
    await runner

    final = services.db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert final["status"] == "rejected"

    outcomes = services.outcomes.for_session(session.id)
    assert any(o["failure_class"] == "human_rejected" for o in outcomes)

    log = await run_git("log", "--oneline", "main", cwd=repo)
    assert "add hello.txt" not in log
