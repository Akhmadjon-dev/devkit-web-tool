from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.bus import bus
from app.core.worktrees import WorktreeError, WorktreeManager, run_git
from app.models import TestReport

logger = logging.getLogger("devworkspace.merge")


class MergeQueue:
    """Serialized rebase -> test -> fast-forward, one task branch at a time.

    After a clean rebase onto base_branch, the task branch *is* base_branch
    plus new commits - a pure fast-forward. We advance the base_branch ref
    with `git update-ref` (a compare-and-swap: old tip -> new tip) rather
    than checking out base_branch anywhere. git refuses to check out a
    branch that's already checked out in another worktree, and base_branch
    is almost always checked out in the user's own repo_root - so plumbing,
    not a worktree, is what makes this safe to run unattended. The tradeoff:
    the user's own checkout of base_branch will show "behind" until they
    pull/refresh it, same as after any external push to a shared branch.
    """

    def __init__(self, worktrees: WorktreeManager, base_branch: str = "main", test_command: str | None = None):
        self.worktrees = worktrees
        self.base_branch = base_branch
        self.test_command = test_command
        self._lock = asyncio.Lock()

    async def _run_tests(self, worktree_path: Path) -> TestReport:
        if not self.test_command:
            return TestReport(ran=False, passed=True, command=None, output="no test_command configured")
        proc = await asyncio.create_subprocess_shell(
            self.test_command,
            cwd=str(worktree_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        output = stdout.decode(errors="replace")
        return TestReport(ran=True, passed=proc.returncode == 0, command=self.test_command, output=output[-8000:])

    async def merge_task(self, *, task_branch: str, task_worktree_path: Path) -> tuple[bool, TestReport, str | None]:
        """Rebase the task branch onto latest base, run tests, fast-forward base if green.

        Returns (merged_ok, test_report, error_detail). Serialized via self._lock
        so only one merge happens at a time across all sessions - the global
        safety property the plan calls out explicitly.
        """
        async with self._lock:
            bus.publish("merge", {"event": "merge_start", "branch": task_branch})
            old_sha = (await run_git("rev-parse", self.base_branch, cwd=task_worktree_path)).strip()

            try:
                await run_git("rebase", self.base_branch, cwd=task_worktree_path)
            except WorktreeError as e:
                await run_git("rebase", "--abort", cwd=task_worktree_path)
                bus.publish("merge", {"event": "merge_conflict", "branch": task_branch})
                return False, TestReport(ran=False, passed=False, output=str(e)), f"rebase conflict: {e}"

            test_report = await self._run_tests(task_worktree_path)
            if not test_report.passed:
                bus.publish("merge", {"event": "tests_failed", "branch": task_branch})
                return False, test_report, "tests failed after rebase"

            new_sha = (await run_git("rev-parse", "HEAD", cwd=task_worktree_path)).strip()
            try:
                # Compare-and-swap: only succeeds if base_branch is still at old_sha,
                # i.e. nothing else advanced it between our rebase and this update.
                await run_git(
                    "update-ref", "-m", f"devworkspace: merge {task_branch}",
                    f"refs/heads/{self.base_branch}", new_sha, old_sha,
                    cwd=task_worktree_path,
                )
            except WorktreeError as e:
                bus.publish("merge", {"event": "merge_conflict", "branch": task_branch})
                return False, test_report, f"fast-forward of {self.base_branch} failed (concurrent change?): {e}"

            bus.publish("merge", {"event": "merge_done", "branch": task_branch})
            return True, test_report, None
