from __future__ import annotations

from app.core.ids import new_id
from app.core.text import query_terms
from app.db import Database


class NotesStore:
    """Project knowledge you write - conventions, decisions. Retrieval is
    read-only FTS5 (non-LLM, cheap, on the hot path); writing a note is
    always an explicit human action through the notes pane, never something
    an agent or the retrieval path does on its own.
    """

    def __init__(self, db: Database):
        self.db = db

    async def add(self, kind: str, text: str) -> str:
        note_id = new_id("note")
        await self.db.execute("INSERT INTO notes (id, kind, text) VALUES (?, ?, ?)", (note_id, kind, text))
        return note_id

    async def delete(self, note_id: str) -> None:
        await self.db.execute("DELETE FROM notes WHERE id = ?", (note_id,))

    def list(self) -> list[dict]:
        return [dict(r) for r in self.db.fetch_all("SELECT * FROM notes ORDER BY created_at DESC")]

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        terms = query_terms(query)
        if not terms:
            return []
        match_expr = " OR ".join(f'"{t}"' for t in terms)
        rows = self.db.fetch_all(
            "SELECT notes.* FROM notes_fts JOIN notes ON notes.rowid = notes_fts.rowid "
            "WHERE notes_fts MATCH ? ORDER BY rank LIMIT ?",
            (match_expr, top_k),
        )
        return [dict(r) for r in rows]
