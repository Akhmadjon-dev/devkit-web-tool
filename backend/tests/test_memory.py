from __future__ import annotations

from pathlib import Path

import pytest

from app.core.memory import build_context, format_context, search_code
from app.core.notes import NotesStore
from app.core.worktrees import run_git
from app.db import Database


@pytest.mark.asyncio
async def test_search_code_finds_matching_lines(repo: Path):
    (repo / "auth.py").write_text("def authenticate_user(token):\n    return validate(token)\n")
    await run_git("add", "auth.py", cwd=repo)
    await run_git("-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "add auth", cwd=repo)

    hits = await search_code(repo, "how does authenticate_user work")
    assert any(h["file"] == "auth.py" and "authenticate_user" in h["snippet"] for h in hits)


@pytest.mark.asyncio
async def test_search_code_finds_untracked_files_too(repo: Path):
    (repo / "scratch.py").write_text("def widget_factory():\n    pass\n")
    hits = await search_code(repo, "widget_factory implementation")
    assert any(h["file"] == "scratch.py" for h in hits)


@pytest.mark.asyncio
async def test_search_code_returns_empty_for_no_matches(repo: Path):
    hits = await search_code(repo, "zzzznonexistentqqqq")
    assert hits == []


def test_format_context_empty_when_nothing_found():
    assert format_context(notes=[], code_hits=[]) == ""


def test_format_context_includes_both_sections():
    ctx = format_context(
        notes=[{"kind": "convention", "text": "use snake_case"}],
        code_hits=[{"file": "a.py", "line": 3, "snippet": "def foo():"}],
    )
    assert "snake_case" in ctx
    assert "a.py:3" in ctx


@pytest.mark.asyncio
async def test_build_context_combines_notes_and_code(tmp_path, repo: Path):
    db = Database(tmp_path / "test.db")
    db.migrate()
    notes = NotesStore(db)
    await notes.add("convention", "always validate tokens before authenticate_user runs")

    (repo / "auth.py").write_text("def authenticate_user(token):\n    return True\n")
    await run_git("add", "auth.py", cwd=repo)
    await run_git("-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "add auth", cwd=repo)

    ctx = await build_context(repo, notes, "implement authenticate_user")
    assert "authenticate_user" in ctx
    assert "validate tokens" in ctx
