from __future__ import annotations

from app.core.executor import ClaudeRunResult
from app.core.ids import new_id
from app.db import Database


class CostTracker:
    """Records per-invocation token/cost traces and answers running totals.
    Cost meter (Phase 2) and per-session budget cap (Phase 5) both read this.
    """

    def __init__(self, db: Database):
        self.db = db

    async def record(self, *, session_id: str, task_id: str | None, event: str, result: ClaudeRunResult, latency_ms: int | None = None) -> None:
        usage = result.usage or {}
        tokens = None
        if usage:
            tokens = sum(v for v in usage.values() if isinstance(v, (int, float)))
        await self.db.execute(
            "INSERT INTO traces (id, session_id, task_id, event, tokens, cost, latency_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (new_id("tr"), session_id, task_id, event, tokens, result.total_cost_usd, latency_ms or result.duration_ms),
        )

    def session_cost(self, session_id: str) -> float:
        row = self.db.fetch_one(
            "SELECT COALESCE(SUM(cost), 0) AS total FROM traces WHERE session_id = ?", (session_id,)
        )
        return float(row["total"]) if row else 0.0

    def total_cost(self) -> float:
        row = self.db.fetch_one("SELECT COALESCE(SUM(cost), 0) AS total FROM traces")
        return float(row["total"]) if row else 0.0
