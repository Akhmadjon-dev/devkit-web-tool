from __future__ import annotations

from pathlib import Path

import pytest

from app.core.worktrees import WorktreeManager, capture_diff, ensure_committed, run_git, sanitize_branch_name


def test_sanitize_branch_name():
    assert sanitize_branch_name("Add CSV export!") == "Add-CSV-export"
    assert sanitize_branch_name("  feat/export  ") == "feat/export"
    assert sanitize_branch_name("") == "task"


@pytest.mark.asyncio
async def test_create_list_remove_worktree(tmp_path: Path, repo: Path):
    wt_dir = tmp_path / "worktrees"
    mgr = WorktreeManager(repo, wt_dir, base_branch="main")

    info = await mgr.create("wt1", "feat/thing", base="main")
    assert info.path.exists()
    assert info.branch == "feat/thing"
    assert info.head is not None

    listed = await mgr.list()
    branches = {w.branch for w in listed}
    assert "feat/thing" in branches
    assert "main" in branches  # the repo's own primary checkout

    await mgr.remove(info.path)
    listed_after = await mgr.list()
    assert info.path not in {w.path for w in listed_after}


@pytest.mark.asyncio
async def test_capture_diff_reports_changes(tmp_path: Path, repo: Path):
    wt_dir = tmp_path / "worktrees"
    mgr = WorktreeManager(repo, wt_dir, base_branch="main")
    info = await mgr.create("wt2", "feat/diff", base="main")

    (info.path / "new_file.txt").write_text("line one\nline two\n")
    await run_git("add", "new_file.txt", cwd=info.path)
    await run_git("-c", "user.email=t@t.com", "-c", "user.name=t", "commit", "-q", "-m", "add file", cwd=info.path)

    diff = await capture_diff(info.path, base="main")
    assert "new_file.txt" in diff["patch"]
    assert diff["files_changed"] == 1
    assert diff["insertions"] == 2


@pytest.mark.asyncio
async def test_capture_diff_sees_untracked_new_files_without_commit(tmp_path: Path, repo: Path):
    """Regression test: an agent that writes a file but never runs `git add`/
    `git commit` must still show up in the diff - `git diff` alone is blind to
    untracked files, which silently produced an empty "no changes" diff for a
    real completed task the first time this ran end to end.
    """
    wt_dir = tmp_path / "worktrees"
    mgr = WorktreeManager(repo, wt_dir, base_branch="main")
    info = await mgr.create("wt3", "feat/untracked", base="main")

    (info.path / "hello.txt").write_text("hello")  # deliberately not `git add`ed

    diff = await capture_diff(info.path, base="main")
    assert "hello.txt" in diff["patch"]
    assert "+hello" in diff["patch"]


@pytest.mark.asyncio
async def test_ensure_committed_commits_untracked_work(tmp_path: Path, repo: Path):
    wt_dir = tmp_path / "worktrees"
    mgr = WorktreeManager(repo, wt_dir, base_branch="main")
    info = await mgr.create("wt4", "feat/autocommit", base="main")

    (info.path / "hello.txt").write_text("hello")
    committed = await ensure_committed(info.path, "add hello.txt")
    assert committed is True

    log = await run_git("log", "--oneline", "-1", cwd=info.path)
    assert "add hello.txt" in log
    status = await run_git("status", "--porcelain", cwd=info.path)
    assert status.strip() == ""


@pytest.mark.asyncio
async def test_ensure_committed_is_a_noop_with_nothing_to_commit(tmp_path: Path, repo: Path):
    wt_dir = tmp_path / "worktrees"
    mgr = WorktreeManager(repo, wt_dir, base_branch="main")
    info = await mgr.create("wt5", "feat/clean", base="main")

    committed = await ensure_committed(info.path, "nothing to see here")
    assert committed is False
