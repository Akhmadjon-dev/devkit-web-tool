from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.bus import bus
from app.core.ids import new_id
from app.core.worktrees import WorktreeManager, sanitize_branch_name
from app.db import Database
from app.models import SessionStatus


@dataclass
class Session:
    id: str
    title: str
    branch: str
    worktree_path: str
    status: SessionStatus


class SessionManager:
    """Owns orchestrator session lifecycle. Each session gets its own worktree
    + branch (invariant #1) used for the Planner's read-only exploration; task
    work happens in per-task worktrees created by the scheduler off main.
    """

    def __init__(self, db: Database, worktrees: WorktreeManager):
        self.db = db
        self.worktrees = worktrees

    async def create(self, title: str, base_branch: str = "main") -> Session:
        session_id = new_id("sess")
        branch = f"session/{sanitize_branch_name(title)}-{session_id[-6:]}"
        wt = await self.worktrees.create(session_id, branch, base=base_branch)
        await self.db.execute(
            "INSERT INTO sessions (id, title, branch, worktree_path, status) VALUES (?, ?, ?, ?, ?)",
            (session_id, title, wt.branch, str(wt.path), SessionStatus.active.value),
        )
        await self.db.execute(
            "INSERT INTO worktrees (id, branch, path, session_id, status) VALUES (?, ?, ?, ?, 'active')",
            (new_id("wt"), wt.branch, str(wt.path), session_id),
        )
        bus.publish("sessions", {"event": "session_created", "session_id": session_id, "title": title})
        bus.publish("worktrees", {"event": "changed"})
        return Session(id=session_id, title=title, branch=wt.branch, worktree_path=str(wt.path), status=SessionStatus.active)

    def get(self, session_id: str) -> Session | None:
        row = self.db.fetch_one("SELECT * FROM sessions WHERE id = ?", (session_id,))
        if row is None:
            return None
        return Session(
            id=row["id"], title=row["title"], branch=row["branch"],
            worktree_path=row["worktree_path"], status=SessionStatus(row["status"]),
        )

    def list(self) -> list[Session]:
        rows = self.db.fetch_all("SELECT * FROM sessions ORDER BY created_at DESC")
        return [
            Session(id=r["id"], title=r["title"], branch=r["branch"], worktree_path=r["worktree_path"], status=SessionStatus(r["status"]))
            for r in rows
        ]

    async def close(self, session_id: str, *, remove_worktree: bool = True) -> None:
        session = self.get(session_id)
        if session is None:
            raise KeyError(session_id)
        if remove_worktree:
            await self.worktrees.remove(Path(session.worktree_path))
            await self.db.execute("UPDATE worktrees SET status = 'removed' WHERE session_id = ?", (session_id,))
        await self.db.execute("UPDATE sessions SET status = ? WHERE id = ?", (SessionStatus.closed.value, session_id))
        bus.publish("sessions", {"event": "session_closed", "session_id": session_id})
        bus.publish("worktrees", {"event": "changed"})
