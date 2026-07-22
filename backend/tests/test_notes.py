from __future__ import annotations

import pytest

from app.core.notes import NotesStore
from app.db import Database


@pytest.fixture
def notes(tmp_path) -> NotesStore:
    db = Database(tmp_path / "test.db")
    db.migrate()
    return NotesStore(db)


@pytest.mark.asyncio
async def test_add_and_list(notes: NotesStore):
    await notes.add("convention", "use snake_case for Python function names")
    await notes.add("decision", "we chose FastAPI over Flask for async support")
    all_notes = notes.list()
    assert len(all_notes) == 2
    assert {n["text"] for n in all_notes} == {
        "use snake_case for Python function names",
        "we chose FastAPI over Flask for async support",
    }


@pytest.mark.asyncio
async def test_search_finds_relevant_note_via_fts(notes: NotesStore):
    await notes.add("convention", "always use snake_case for Python function names")
    await notes.add("convention", "prefer tabs over spaces in Makefiles")

    hits = notes.search("what naming convention for functions?")
    assert len(hits) == 1
    assert "snake_case" in hits[0]["text"]


@pytest.mark.asyncio
async def test_search_returns_nothing_for_unrelated_query(notes: NotesStore):
    await notes.add("convention", "always use snake_case for Python function names")
    assert notes.search("xyzzy plugh nonexistent") == []


@pytest.mark.asyncio
async def test_delete_removes_from_search_too(notes: NotesStore):
    note_id = await notes.add("convention", "use snake_case for functions")
    assert notes.search("snake_case")
    await notes.delete(note_id)
    assert notes.search("snake_case") == []
    assert notes.list() == []
