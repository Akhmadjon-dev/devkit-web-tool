from __future__ import annotations

import asyncio

from app.bus import bus
from app.core.ids import new_id
from app.db import Database
from app.models import ApprovalStatus


class ApprovalRejected(Exception):
    def __init__(self, reason: str | None):
        super().__init__(reason or "rejected")
        self.reason = reason


class ApprovalBroker:
    """Creates a pending approval row and blocks the caller until a human
    resolves it via resolve(). One in-memory asyncio.Event per pending
    approval id backs the wait - resolution always happens through the DB
    write path so state survives even if nothing is currently waiting on it
    (e.g. after a restart; Phase 5 rehydrates from `status = pending` rows).
    """

    def __init__(self, db: Database):
        self.db = db
        self._events: dict[str, asyncio.Event] = {}

    async def request(
        self, *, session_id: str, task_id: str | None, step_kind: str, payload_ref: str | None
    ) -> str:
        approval_id = new_id("appr")
        await self.db.execute(
            "INSERT INTO approvals (id, session_id, task_id, step_kind, payload_ref, status) "
            "VALUES (?, ?, ?, ?, ?, 'pending')",
            (approval_id, session_id, task_id, step_kind, payload_ref),
        )
        bus.publish("approvals", {"event": "approval_pending", "approval_id": approval_id, "session_id": session_id})
        bus.publish(f"session:{session_id}", {"event": "approval_pending", "approval_id": approval_id})
        return approval_id

    async def wait_for(self, approval_id: str) -> tuple[ApprovalStatus, str | None]:
        """Block until the approval is resolved. Polls the DB (source of truth)
        so this also works correctly across process restarts if re-invoked with
        an approval id that already got resolved while nobody was waiting.
        """
        event = self._events.setdefault(approval_id, asyncio.Event())
        while True:
            row = self.db.fetch_one("SELECT status, reason FROM approvals WHERE id = ?", (approval_id,))
            if row is None:
                raise KeyError(f"unknown approval {approval_id}")
            if row["status"] != ApprovalStatus.pending:
                self._events.pop(approval_id, None)
                return ApprovalStatus(row["status"]), row["reason"]
            event.clear()
            try:
                await asyncio.wait_for(event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                continue  # re-check DB - covers resolution from another process/restart

    async def resolve(self, approval_id: str, status: ApprovalStatus, reason: str | None = None) -> None:
        if status == ApprovalStatus.pending:
            raise ValueError("resolve() requires approved or rejected")
        await self.db.execute(
            "UPDATE approvals SET status = ?, reason = ?, resolved_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE id = ?",
            (status.value, reason, approval_id),
        )
        row = self.db.fetch_one("SELECT session_id FROM approvals WHERE id = ?", (approval_id,))
        if row is not None:
            bus.publish(
                "approvals", {"event": "approval_resolved", "approval_id": approval_id, "status": status.value}
            )
            bus.publish(
                f"session:{row['session_id']}",
                {"event": "approval_resolved", "approval_id": approval_id, "status": status.value},
            )
        self._events.setdefault(approval_id, asyncio.Event()).set()

    def pending(self) -> list[dict]:
        rows = self.db.fetch_all(
            "SELECT * FROM approvals WHERE status = 'pending' ORDER BY created_at"
        )
        return [dict(r) for r in rows]
