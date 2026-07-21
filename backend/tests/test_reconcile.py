from __future__ import annotations

from pathlib import Path

import pytest

from app.core.ids import new_id
from app.core.reconcile import cleanup_orphaned_worktrees, reconcile_on_startup
from app.services import AppServices


@pytest.mark.asyncio
async def test_reconcile_escalates_stuck_running_and_merging_tasks(services: AppServices):
    session = await services.sessions.create("stuck session")
    running_id = new_id("task")
    merging_id = new_id("task")
    waiting_id = new_id("task")
    for tid, status in [(running_id, "running"), (merging_id, "merging"), (waiting_id, "awaiting_approval")]:
        await services.db.execute(
            "INSERT INTO tasks (id, session_id, title, spec, role, branch, status, depends_on) "
            "VALUES (?, ?, ?, ?, 'engineer', 'x', ?, '[]')",
            (tid, session.id, tid, "spec", status),
        )

    await reconcile_on_startup(services)

    def status_of(tid: str) -> str:
        return services.db.fetch_one("SELECT status FROM tasks WHERE id = ?", (tid,))["status"]

    assert status_of(running_id) == "escalated"
    assert status_of(merging_id) == "escalated"
    assert status_of(waiting_id) == "awaiting_approval"  # untouched - still recoverable

    outcomes = services.outcomes.for_session(session.id)
    escalated_task_ids = {o["task_id"] for o in outcomes}
    assert running_id in escalated_task_ids
    assert merging_id in escalated_task_ids


@pytest.mark.asyncio
async def test_reconcile_marks_missing_worktree_rows_removed(services: AppServices, tmp_path: Path):
    await services.db.execute(
        "INSERT INTO worktrees (id, branch, path, session_id, status) VALUES (?, ?, ?, ?, 'active')",
        ("wt_ghost", "some/branch", str(tmp_path / "does-not-exist-anymore"), None),
    )
    await reconcile_on_startup(services)
    row = services.db.fetch_one("SELECT status FROM worktrees WHERE id = ?", ("wt_ghost",))
    assert row["status"] == "removed"


@pytest.mark.asyncio
async def test_cleanup_orphaned_worktrees_removes_untracked_ones(services: AppServices):
    session = await services.sessions.create("orphan test")
    # The session's own worktree is DB-tracked ('active') - must survive cleanup.
    # Create a second, untracked worktree directly to simulate a crash leftover.
    info = await services.worktrees.create("orphan_wt", "orphan/branch", base=services.settings.base_branch)

    removed = await cleanup_orphaned_worktrees(services)

    assert str(info.path) in removed
    assert not info.path.exists()
    # The tracked session worktree must not have been touched.
    still_active = services.sessions.get(session.id)
    assert Path(still_active.worktree_path).exists()
