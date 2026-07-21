from __future__ import annotations

import logging

from app.models import FailureClass, TaskStatus
from app.services import AppServices

logger = logging.getLogger("devworkspace.reconcile")

# States that only make sense while a live process is actively driving them.
# awaiting_approval is fine to resume - approvals.wait_for() polls the DB, no
# in-flight process required. running/merging have no such recovery path in
# the MVP (auto-replanning on failure is explicitly out of scope) - escalate
# instead of leaving the UI showing a spinner that will never resolve.
_ORPHANABLE_STATUSES = (TaskStatus.running.value, TaskStatus.merging.value)


async def reconcile_on_startup(services: AppServices) -> None:
    """Runs once at process startup. Two jobs:
    1. Tasks left mid-flight by a previous crashed/killed process can't be
       resumed (no live claude subprocess to reattach to) - escalate them.
    2. The `worktrees` table can drift from actual git state (crash before
       cleanup, manual `git worktree remove`, etc) - reconcile DB rows
       against `git worktree list --porcelain`, the source of truth.
    """
    stuck = services.db.fetch_all(
        f"SELECT * FROM tasks WHERE status IN ({','.join('?' * len(_ORPHANABLE_STATUSES))})",
        _ORPHANABLE_STATUSES,
    )
    for row in stuck:
        await services.db.execute("UPDATE tasks SET status = ? WHERE id = ?", (TaskStatus.escalated.value, row["id"]))
        await services.outcomes.record(
            task_id=row["id"], session_id=row["session_id"], failure_class=FailureClass.escalated,
            raw_reason=f"interrupted mid-'{row['status']}' by a restart - no process left to resume",
        )
        logger.warning("task %s was '%s' at startup - escalated", row["id"], row["status"])

    actual_paths = {str(w.path) for w in await services.worktrees.list()}
    db_active = services.db.fetch_all("SELECT * FROM worktrees WHERE status = 'active'")
    for row in db_active:
        if row["path"] not in actual_paths:
            await services.db.execute("UPDATE worktrees SET status = 'removed' WHERE id = ?", (row["id"],))
            logger.info("worktree row %s (%s) no longer exists on disk - marked removed", row["id"], row["path"])


async def cleanup_orphaned_worktrees(services: AppServices) -> list[str]:
    """Removes git worktrees that exist on disk but are either untracked in
    our DB or belong to a closed session - typically left behind by a crash
    between an agent finishing and our own cleanup step running. Returns the
    paths removed. Never touches the repo's own primary checkout.
    """
    removed: list[str] = []
    known_active_paths = {
        row["path"] for row in services.db.fetch_all("SELECT path FROM worktrees WHERE status = 'active'")
    }
    for wt in await services.worktrees.list():
        path_str = str(wt.path)
        if path_str == str(services.settings.repo_root):
            continue  # the user's own primary checkout, never ours to remove
        if path_str in known_active_paths:
            continue
        await services.worktrees.remove(wt.path, delete_branch=True)
        await services.db.execute("UPDATE worktrees SET status = 'removed' WHERE path = ?", (path_str,))
        removed.append(path_str)
    return removed
