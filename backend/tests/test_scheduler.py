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


async def fake_run_claude_engineer_forgets_to_commit(
    prompt, *, cwd, role, claude_bin="claude", max_budget_usd=None, add_dirs=None,
    resume_session_id=None, timeout_seconds=None, on_event=None,
):
    """Same as fake_run_claude, except the engineer writes the file but never
    runs git add/commit - reproducing what a real Claude Code engineer agent
    did the first time this pipeline ran end to end against the live CLI: the
    diff came back empty and the "merge" silently did nothing, because nothing
    was ever committed for git to move. ensure_committed() is the fix.
    """
    if role is ENGINEER_ROLE:
        (Path(cwd) / "hello.txt").write_text("hi\n")
        return make_result(structured=None, ok=True)
    return await fake_run_claude(
        prompt, cwd=cwd, role=role, claude_bin=claude_bin, max_budget_usd=max_budget_usd,
        add_dirs=add_dirs, resume_session_id=resume_session_id, timeout_seconds=timeout_seconds, on_event=on_event,
    )


@pytest.mark.asyncio
async def test_pipeline_commits_engineer_work_even_if_agent_forgets(services, repo, monkeypatch):
    monkeypatch.setattr(scheduler_module, "run_claude", fake_run_claude_engineer_forgets_to_commit)

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

    # The diff gate must show the change even though the agent never committed.
    diff_artifact = services.artifacts.get(approval_row["payload_ref"])
    assert "hello.txt" in diff_artifact["body"]["patch"]
    assert diff_artifact["body"]["files_changed"] >= 1

    await services.approvals.resolve(approval_row["id"], ApprovalStatus.approved)
    await runner

    final = services.db.fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    assert final["status"] == "done"

    log = await run_git("log", "--oneline", "main", cwd=repo)
    assert "hello" in log.lower()
    content = await run_git("show", "main:hello.txt", cwd=repo)
    assert content.strip() == "hi"


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


@pytest.mark.asyncio
async def test_independent_tasks_run_concurrently(services, repo, monkeypatch):
    """Two tasks with no depends_on relationship between them should both
    reach gate 2 before either is resolved - proving the scheduler dispatches
    them concurrently rather than waiting for the first to fully finish
    (including its human-approval wait) before starting the second.
    """

    async def fake_run_claude_two_tasks(
        prompt, *, cwd, role, claude_bin="claude", max_budget_usd=None, add_dirs=None,
        resume_session_id=None, timeout_seconds=None, on_event=None,
    ):
        if role is PLANNER_ROLE:
            plan = {
                "tasks": [
                    {"id": "a", "title": "add a.txt", "spec": "create a.txt", "role": "engineer", "branch": "feat/a", "depends_on": []},
                    {"id": "b", "title": "add b.txt", "spec": "create b.txt", "role": "engineer", "branch": "feat/b", "depends_on": []},
                ]
            }
            return make_result(structured=plan)
        if role is ENGINEER_ROLE:
            fname = "a.txt" if "a.txt" in prompt else "b.txt"
            (Path(cwd) / fname).write_text("x")
            await run_git("add", fname, cwd=Path(cwd))
            await run_git("-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", f"add {fname}", cwd=Path(cwd))
            return make_result(structured=None, ok=True)
        if role is REVIEWER_ROLE:
            return make_result(structured={"verdict": "approve", "issues": [], "notes": "ok"})
        raise AssertionError(role)

    monkeypatch.setattr(scheduler_module, "run_claude", fake_run_claude_two_tasks)

    session = await services.sessions.create("two independent tasks")
    _, plan_approval_id = await services.scheduler.submit_request(session, "add a.txt and b.txt")
    plan, id_map = await services.scheduler.resolve_plan(session, plan_approval_id, approved=True)

    runner = asyncio.create_task(services.scheduler.run_all_tasks(session, plan, id_map))

    both_pending = False
    for _ in range(2000):
        rows = services.db.fetch_all(
            "SELECT * FROM approvals WHERE step_kind = 'task' AND status = 'pending'"
        )
        if len(rows) == 2:
            both_pending = True
            break
        await asyncio.sleep(0.01)
    assert both_pending, "both independent tasks should reach gate 2 concurrently"

    pending_rows = services.db.fetch_all("SELECT * FROM approvals WHERE step_kind = 'task' AND status = 'pending'")
    for row in pending_rows:
        await services.approvals.resolve(row["id"], ApprovalStatus.approved)
    await runner

    statuses = {r["title"]: r["status"] for r in services.db.fetch_all("SELECT title, status FROM tasks")}
    assert statuses == {"add a.txt": "done", "add b.txt": "done"}


@pytest.mark.asyncio
async def test_agent_semaphore_caps_concurrent_claude_calls(tmp_path, repo, monkeypatch):
    from app.config import Settings
    from app.services import build_services

    settings = Settings(repo_root=repo, data_dir=tmp_path / "data", token="test-token", max_agents=1)
    services = build_services(settings)

    concurrent = 0
    max_seen = 0
    lock = asyncio.Lock()

    async def fake_run_claude_tracks_concurrency(
        prompt, *, cwd, role, claude_bin="claude", max_budget_usd=None, add_dirs=None,
        resume_session_id=None, timeout_seconds=None, on_event=None,
    ):
        nonlocal concurrent, max_seen
        async with lock:
            concurrent += 1
            max_seen = max(max_seen, concurrent)
        await asyncio.sleep(0.05)
        async with lock:
            concurrent -= 1

        if role is PLANNER_ROLE:
            plan = {
                "tasks": [
                    {"id": "a", "title": "task a", "spec": "x", "role": "engineer", "branch": "feat/a", "depends_on": []},
                    {"id": "b", "title": "task b", "spec": "y", "role": "engineer", "branch": "feat/b", "depends_on": []},
                ]
            }
            return make_result(structured=plan)
        if role is ENGINEER_ROLE:
            fname = Path(cwd).name + ".txt"
            (Path(cwd) / fname).write_text("x")
            await run_git("add", fname, cwd=Path(cwd))
            await run_git("-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "add file", cwd=Path(cwd))
            return make_result(structured=None, ok=True)
        if role is REVIEWER_ROLE:
            return make_result(structured={"verdict": "approve", "issues": [], "notes": "ok"})
        raise AssertionError(role)

    monkeypatch.setattr(scheduler_module, "run_claude", fake_run_claude_tracks_concurrency)

    session = await services.sessions.create("semaphore test")
    _, plan_approval_id = await services.scheduler.submit_request(session, "two tasks")
    plan, id_map = await services.scheduler.resolve_plan(session, plan_approval_id, approved=True)

    runner = asyncio.create_task(services.scheduler.run_all_tasks(session, plan, id_map))
    for _ in range(2000):
        rows = services.db.fetch_all("SELECT * FROM approvals WHERE step_kind = 'task' AND status = 'pending'")
        if len(rows) == 2:
            break
        await asyncio.sleep(0.01)
    for row in services.db.fetch_all("SELECT * FROM approvals WHERE step_kind = 'task' AND status = 'pending'"):
        await services.approvals.resolve(row["id"], ApprovalStatus.approved)
    await runner

    assert max_seen == 1, f"max_agents=1 should cap concurrent claude calls at 1, saw {max_seen}"


@pytest.mark.asyncio
async def test_two_parallel_orchestrator_sessions_both_merge_cleanly(services, repo, monkeypatch):
    """The Phase 3 checkpoint, in code: two independent orchestrator sessions
    (not just two tasks in one plan) running at once, each parking for its own
    approval, both triaged and merged - proving session-level isolation (each
    gets its own worktree/branch) plus the merge queue's serialization hold
    even when two completely separate pipelines are in flight simultaneously.

    monkeypatch replaces the single module-level `run_claude` name, so both
    sessions' calls funnel through one fake - it dispatches on prompt content
    (which filename to write) rather than closing over per-session state, so
    the two sessions genuinely running concurrently can't clobber each other.
    """

    async def fake_run_claude_two_sessions(
        prompt, *, cwd, role, claude_bin="claude", max_budget_usd=None, add_dirs=None,
        resume_session_id=None, timeout_seconds=None, on_event=None,
    ):
        filename = "alpha.txt" if "alpha" in prompt else "beta.txt"
        if role is PLANNER_ROLE:
            plan = {
                "tasks": [{
                    "id": "t1", "title": f"add {filename}", "spec": f"create {filename}",
                    "role": "engineer", "branch": f"feat/{filename}", "depends_on": [],
                }]
            }
            return make_result(structured=plan)
        if role is ENGINEER_ROLE:
            (Path(cwd) / filename).write_text("x")
            await run_git("add", filename, cwd=Path(cwd))
            await run_git("-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", f"add {filename}", cwd=Path(cwd))
            return make_result(structured=None, ok=True)
        if role is REVIEWER_ROLE:
            return make_result(structured={"verdict": "approve", "issues": [], "notes": "ok"})
        raise AssertionError(role)

    monkeypatch.setattr(scheduler_module, "run_claude", fake_run_claude_two_sessions)

    async def dispatch(*, request_text: str) -> str:
        """Runs one full session's request -> plan -> gate1 for real; returns its task id."""
        session = await services.sessions.create(request_text)
        _, plan_approval_id = await services.scheduler.submit_request(session, request_text)
        plan, id_map = await services.scheduler.resolve_plan(session, plan_approval_id, approved=True)
        asyncio.create_task(services.scheduler.run_all_tasks(session, plan, id_map))
        return id_map["t1"]

    # Both orchestrators genuinely in flight at once.
    task_a, task_b = await asyncio.gather(
        dispatch(request_text="add alpha file"),
        dispatch(request_text="add beta file"),
    )

    pending: dict[str, str] = {}
    for _ in range(3000):
        rows = services.db.fetch_all("SELECT * FROM approvals WHERE step_kind = 'task' AND status = 'pending'")
        for r in rows:
            pending[r["task_id"]] = r["id"]
        if task_a in pending and task_b in pending:
            break
        await asyncio.sleep(0.01)
    assert task_a in pending and task_b in pending, "both orchestrator sessions should park for approval"

    # Triage both from the global queue, in an arbitrary order.
    await services.approvals.resolve(pending[task_b], ApprovalStatus.approved)
    await services.approvals.resolve(pending[task_a], ApprovalStatus.approved)

    for _ in range(3000):
        statuses = {
            r["id"]: r["status"]
            for r in services.db.fetch_all("SELECT id, status FROM tasks WHERE id IN (?, ?)", (task_a, task_b))
        }
        if statuses.get(task_a) == "done" and statuses.get(task_b) == "done":
            break
        await asyncio.sleep(0.01)
    assert statuses[task_a] == "done"
    assert statuses[task_b] == "done"

    log = await run_git("log", "--oneline", "main", cwd=repo)
    assert "alpha.txt" in log
    assert "beta.txt" in log


@pytest.mark.asyncio
async def test_planner_and_engineer_prompts_include_relevant_note(services, repo, monkeypatch):
    """Phase 4 checkpoint, at the plumbing level: a note you wrote actually
    reaches the prompt the agent sees. (Whether the agent then visibly
    follows it is an LLM-behavior question, verified separately against the
    real CLI - this locks in that the context-injection wiring itself works.)
    """
    await services.notes.add("convention", "always name the export file report.csv, never export.csv")

    seen_prompts: list[str] = []

    async def fake_run_claude_captures_prompts(
        prompt, *, cwd, role, claude_bin="claude", max_budget_usd=None, add_dirs=None,
        resume_session_id=None, timeout_seconds=None, on_event=None,
    ):
        seen_prompts.append(prompt)
        if role is PLANNER_ROLE:
            plan = {
                "tasks": [{
                    "id": "t1", "title": "add export", "spec": "create report.csv",
                    "role": "engineer", "branch": "feat/export", "depends_on": [],
                }]
            }
            return make_result(structured=plan)
        if role is ENGINEER_ROLE:
            (Path(cwd) / "report.csv").write_text("x")
            await run_git("add", "report.csv", cwd=Path(cwd))
            await run_git("-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "add export", cwd=Path(cwd))
            return make_result(structured=None, ok=True)
        if role is REVIEWER_ROLE:
            return make_result(structured={"verdict": "approve", "issues": [], "notes": "ok"})
        raise AssertionError(role)

    monkeypatch.setattr(scheduler_module, "run_claude", fake_run_claude_captures_prompts)

    session = await services.sessions.create("csv export")
    _, plan_approval_id = await services.scheduler.submit_request(session, "add a csv export")

    planner_prompt = seen_prompts[0]
    assert "report.csv, never export.csv" in planner_prompt

    plan, id_map = await services.scheduler.resolve_plan(session, plan_approval_id, approved=True)
    task_id = id_map["t1"]
    runner = asyncio.create_task(services.scheduler.run_all_tasks(session, plan, id_map))

    for _ in range(1000):
        row = services.db.fetch_one("SELECT status FROM tasks WHERE id = ?", (task_id,))
        if row and row["status"] == "done":
            break
        await asyncio.sleep(0.01)
        pending = services.db.fetch_one(
            "SELECT * FROM approvals WHERE task_id = ? AND step_kind = 'task' AND status = 'pending'", (task_id,)
        )
        if pending:
            await services.approvals.resolve(pending["id"], ApprovalStatus.approved)
    await runner

    engineer_prompt = next(p for p in seen_prompts if "create report.csv" in p)
    assert "report.csv, never export.csv" in engineer_prompt
