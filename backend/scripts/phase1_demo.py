"""Phase 1 checkpoint (headless, no web): request -> plan -> approve -> engineer
builds it in a worktree -> you approve the diff -> merged to main.

Usage:
    uv run python scripts/phase1_demo.py "add a hello.txt file containing hi"

On first run this creates a small disposable git repo at backend/data/demo-repo
to build against, so there's nothing else to set up. Point DEVWORKSPACE_REPO_ROOT
at a real repo instead once you trust the loop.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.bus import bus  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.models import ApprovalStatus  # noqa: E402
from app.services import build_services  # noqa: E402

DEMO_REPO = Path(__file__).resolve().parent.parent / "data" / "demo-repo"


async def _git(*args: str, cwd: Path) -> None:
    proc = await asyncio.create_subprocess_exec("git", *args, cwd=str(cwd))
    await proc.wait()


async def ensure_demo_repo() -> Path:
    if (DEMO_REPO / ".git").exists():
        return DEMO_REPO
    DEMO_REPO.mkdir(parents=True, exist_ok=True)
    await _git("init", "-q", "-b", "main", cwd=DEMO_REPO)
    (DEMO_REPO / "README.md").write_text("# DevWorkspace Phase 1 demo repo\n\nDisposable - safe to delete.\n")
    await _git("add", "README.md", cwd=DEMO_REPO)
    await _git(
        "-c", "user.email=devworkspace@example.com", "-c", "user.name=DevWorkspace",
        "commit", "-q", "-m", "init", cwd=DEMO_REPO,
    )
    return DEMO_REPO


async def prompt_and_decide(artifact: dict | None) -> tuple[bool, str | None]:
    if artifact is not None:
        print(json.dumps(artifact["body"], indent=2)[:4000])
    decision = await asyncio.to_thread(input, "approve? [y/N]: ")
    approved = decision.strip().lower() == "y"
    reason = None
    if not approved:
        reason = await asyncio.to_thread(input, "reason (optional): ")
    return approved, reason


async def task_approval_watcher(services) -> None:
    """Handles gate-2 (per-task diff) approvals as they come in while
    run_all_tasks executes in the background. Gate-1 (the plan) is handled
    linearly in main() instead, since nothing concurrent needs to happen yet.
    """
    queue = bus.subscribe("approvals")
    try:
        while True:
            event = await queue.get()
            if event.get("event") != "approval_pending":
                continue
            approval_id = event["approval_id"]
            row = services.db.fetch_one("SELECT * FROM approvals WHERE id = ?", (approval_id,))
            if row is None or row["step_kind"] != "task":
                continue
            print("\n" + "=" * 70)
            print(f"GATE 2 - approve this task's diff? approval={approval_id}")
            artifact = services.artifacts.get(row["payload_ref"]) if row["payload_ref"] else None
            approved, reason = await prompt_and_decide(artifact)
            await services.approvals.resolve(
                approval_id, ApprovalStatus.approved if approved else ApprovalStatus.rejected, reason
            )
    except asyncio.CancelledError:
        pass


async def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    request_text = sys.argv[1]

    settings = get_settings()
    if not os.environ.get("DEVWORKSPACE_REPO_ROOT"):
        settings.repo_root = await ensure_demo_repo()
    services = build_services(settings)

    print(f"repo: {services.settings.repo_root}")
    watcher = asyncio.create_task(task_approval_watcher(services))

    session = await services.sessions.create(title=request_text[:40])
    print(f"session {session.id} on branch {session.branch}\n  worktree: {session.worktree_path}")

    _, plan_approval_id = await services.scheduler.submit_request(session, request_text)
    plan_row = services.db.fetch_one("SELECT * FROM approvals WHERE id = ?", (plan_approval_id,))
    print("\n" + "=" * 70)
    print(f"GATE 1 - approve this plan? approval={plan_approval_id}")
    plan_artifact = services.artifacts.get(plan_row["payload_ref"])
    approved, reason = await prompt_and_decide(plan_artifact)

    plan, id_map = await services.scheduler.resolve_plan(session, plan_approval_id, approved=approved, reason=reason)
    if not approved or plan is None:
        print("plan rejected, stopping.")
        watcher.cancel()
        return

    await services.scheduler.run_all_tasks(session, plan, id_map)
    watcher.cancel()

    print("\nfinal task states:")
    for row in services.db.fetch_all(
        "SELECT id, title, status FROM tasks WHERE session_id = ?", (session.id,)
    ):
        print(f"  {row['id']}: {row['title']} -> {row['status']}")
    print(f"session cost: ${services.cost.session_cost(session.id):.4f}")
    print(f"\nmerges fast-forward `main` directly (no checkout involved) - inspect with:")
    print(f"  git -C {services.settings.repo_root} log --oneline main")


if __name__ == "__main__":
    asyncio.run(main())
