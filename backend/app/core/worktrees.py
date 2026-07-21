from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

_BRANCH_SAFE = re.compile(r"[^a-zA-Z0-9._/-]+")


class WorktreeError(RuntimeError):
    pass


@dataclass
class WorktreeInfo:
    path: Path
    branch: str
    head: str | None = None


def sanitize_branch_name(name: str) -> str:
    """Make a string safe to use as a git branch component."""
    cleaned = _BRANCH_SAFE.sub("-", name.strip()).strip("-/")
    return cleaned or "task"


async def run_git(*args: str, cwd: Path) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise WorktreeError(
            f"git {' '.join(args)} failed (exit {proc.returncode}): {stderr.decode().strip()}"
        )
    return stdout.decode()


class WorktreeManager:
    """Owns git worktree + branch lifecycle for one repo.

    One session = one worktree = one branch (invariant #1 in the plan).
    We never let Claude Code manage worktrees itself (its own -w flag) -
    this class is the single source of truth so the DB `worktrees` table
    stays accurate for the lifecycle view (Phase 3).
    """

    def __init__(self, repo_root: Path, worktrees_dir: Path, base_branch: str = "main"):
        self.repo_root = repo_root
        self.worktrees_dir = worktrees_dir
        self.base_branch = base_branch

    async def create(self, worktree_id: str, branch: str, base: str | None = None) -> WorktreeInfo:
        branch = sanitize_branch_name(branch)
        base = base or self.base_branch
        self.worktrees_dir.mkdir(parents=True, exist_ok=True)
        path = self.worktrees_dir / worktree_id
        if path.exists():
            raise WorktreeError(f"worktree path already exists: {path}")
        await run_git(
            "worktree", "add", "-b", branch, str(path), base, cwd=self.repo_root
        )
        head = (await run_git("rev-parse", "HEAD", cwd=path)).strip()
        return WorktreeInfo(path=path, branch=branch, head=head)

    async def create_tracking(self, worktree_id: str, branch: str) -> WorktreeInfo:
        """Check out an *existing* branch into a fresh worktree (no new branch
        created). Used for the merge queue's internal main-mirror worktree,
        where merges must land on the real `main` ref, not a throwaway branch.
        """
        self.worktrees_dir.mkdir(parents=True, exist_ok=True)
        path = self.worktrees_dir / worktree_id
        if path.exists():
            raise WorktreeError(f"worktree path already exists: {path}")
        await run_git("worktree", "add", str(path), branch, cwd=self.repo_root)
        head = (await run_git("rev-parse", "HEAD", cwd=path)).strip()
        return WorktreeInfo(path=path, branch=branch, head=head)

    async def remove(self, path: Path, *, force: bool = True, delete_branch: bool = False) -> None:
        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(str(path))
        try:
            await run_git(*args, cwd=self.repo_root)
        except WorktreeError:
            # Path may already be gone (e.g. deleted out of band). Prune and move on.
            await run_git("worktree", "prune", cwd=self.repo_root)
        if delete_branch:
            branch = await self._branch_for_path(path)
            if branch:
                try:
                    await run_git("branch", "-D", branch, cwd=self.repo_root)
                except WorktreeError:
                    pass

    async def list(self) -> list[WorktreeInfo]:
        raw = await run_git("worktree", "list", "--porcelain", cwd=self.repo_root)
        entries: list[WorktreeInfo] = []
        cur_path: Path | None = None
        cur_head: str | None = None
        cur_branch: str | None = None
        for line in raw.splitlines():
            if line.startswith("worktree "):
                if cur_path is not None:
                    entries.append(WorktreeInfo(path=cur_path, branch=cur_branch or "", head=cur_head))
                cur_path = Path(line.removeprefix("worktree "))
                cur_head = None
                cur_branch = None
            elif line.startswith("HEAD "):
                cur_head = line.removeprefix("HEAD ")
            elif line.startswith("branch "):
                cur_branch = line.removeprefix("branch ").removeprefix("refs/heads/")
        if cur_path is not None:
            entries.append(WorktreeInfo(path=cur_path, branch=cur_branch or "", head=cur_head))
        return entries

    async def prune(self) -> None:
        await run_git("worktree", "prune", cwd=self.repo_root)

    async def _branch_for_path(self, path: Path) -> str | None:
        for wt in await self.list():
            if wt.path == path:
                return wt.branch
        return None


async def capture_diff(worktree_path: Path, base: str = "main") -> dict:
    """Diff of everything committed on this worktree's branch since it diverged
    from `base`, plus uncommitted changes. Returns raw ingredients for a Diff artifact.
    """
    patch = await run_git("diff", f"{base}...HEAD", cwd=worktree_path)
    uncommitted = await run_git("diff", "HEAD", cwd=worktree_path)
    full_patch = patch + uncommitted
    stat = await run_git("diff", "--stat", f"{base}...HEAD", cwd=worktree_path)
    files_changed = max(0, len(stat.strip().splitlines()) - 1) if stat.strip() else 0
    insertions = sum(int(n) for n in re.findall(r"(\d+) insertion", stat))
    deletions = sum(int(n) for n in re.findall(r"(\d+) deletion", stat))
    return {
        "patch": full_patch,
        "files_changed": files_changed,
        "insertions": insertions,
        "deletions": deletions,
    }
