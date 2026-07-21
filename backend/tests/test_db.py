from __future__ import annotations

from pathlib import Path

from app.db import Database


def test_migrate_creates_expected_tables(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    db.migrate()
    rows = db.fetch_all("SELECT name FROM sqlite_master WHERE type='table'")
    names = {r["name"] for r in rows}
    for expected in {"sessions", "tasks", "artifacts", "approvals", "outcomes", "notes", "worktrees", "traces"}:
        assert expected in names


def test_wal_mode_enabled(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    db.migrate()
    row = db.fetch_one("PRAGMA journal_mode")
    assert row[0].lower() == "wal"


async def test_execute_is_serialized_and_persists(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    db.migrate()
    await db.execute(
        "INSERT INTO notes (id, kind, text) VALUES (?, ?, ?)", ("n1", "convention", "use snake_case")
    )
    row = db.fetch_one("SELECT * FROM notes WHERE id = ?", ("n1",))
    assert row["text"] == "use snake_case"
