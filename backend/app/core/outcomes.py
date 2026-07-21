from __future__ import annotations

from app.core.ids import new_id
from app.db import Database
from app.models import FailureClass


class OutcomesStore:
    """Durable record of failures + human rejections, for future learning
    (consolidation is explicitly out of scope for MVP - we just capture).
    """

    def __init__(self, db: Database):
        self.db = db

    async def record(
        self, *, task_id: str, session_id: str, failure_class: FailureClass, raw_reason: str = "", summary: str = ""
    ) -> str:
        outcome_id = new_id("out")
        await self.db.execute(
            "INSERT INTO outcomes (id, task_id, session_id, failure_class, raw_reason, summary) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (outcome_id, task_id, session_id, failure_class.value, raw_reason, summary),
        )
        return outcome_id

    def for_session(self, session_id: str) -> list[dict]:
        rows = self.db.fetch_all(
            "SELECT * FROM outcomes WHERE session_id = ? ORDER BY created_at", (session_id,)
        )
        return [dict(r) for r in rows]
