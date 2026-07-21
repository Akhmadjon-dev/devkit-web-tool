from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from app.core.ids import new_id
from app.db import Database
from app.models import ARTIFACT_SCHEMAS


class ArtifactStore:
    """Persists typed plan/diff/review/test_report artifacts. Agents only ever
    emit these - the scheduler passes them between steps, nothing "talks to"
    another agent directly.
    """

    def __init__(self, db: Database):
        self.db = db

    async def save(self, *, kind: str, session_id: str, task_id: str | None, body: dict[str, Any] | BaseModel) -> str:
        schema = ARTIFACT_SCHEMAS.get(kind)
        if isinstance(body, BaseModel):
            model = body
        elif schema is not None:
            model = schema.model_validate(body)
        else:
            model = None

        payload = model.model_dump() if model is not None else body
        artifact_id = new_id("art")
        await self.db.execute(
            "INSERT INTO artifacts (id, task_id, session_id, kind, body) VALUES (?, ?, ?, ?, ?)",
            (artifact_id, task_id, session_id, kind, json.dumps(payload)),
        )
        return artifact_id

    def get(self, artifact_id: str) -> dict[str, Any] | None:
        row = self.db.fetch_one("SELECT * FROM artifacts WHERE id = ?", (artifact_id,))
        if row is None:
            return None
        return self._row_to_dict(row)

    def for_task(self, task_id: str, kind: str | None = None) -> list[dict[str, Any]]:
        if kind:
            rows = self.db.fetch_all(
                "SELECT * FROM artifacts WHERE task_id = ? AND kind = ? ORDER BY created_at",
                (task_id, kind),
            )
        else:
            rows = self.db.fetch_all(
                "SELECT * FROM artifacts WHERE task_id = ? ORDER BY created_at", (task_id,)
            )
        return [self._row_to_dict(r) for r in rows]

    def for_session(self, session_id: str) -> list[dict[str, Any]]:
        rows = self.db.fetch_all(
            "SELECT * FROM artifacts WHERE session_id = ? ORDER BY created_at", (session_id,)
        )
        return [self._row_to_dict(r) for r in rows]

    @staticmethod
    def _row_to_dict(row) -> dict[str, Any]:
        d = dict(row)
        d["body"] = json.loads(d["body"])
        return d
