from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.core.approvals import ApprovalBroker
from app.core.artifacts import ArtifactStore
from app.core.llm_meta import CostTracker
from app.core.merge import MergeQueue
from app.core.outcomes import OutcomesStore
from app.core.scheduler import Scheduler
from app.core.session_manager import SessionManager
from app.core.worktrees import WorktreeManager
from app.db import Database, init_db


@dataclass
class AppServices:
    """Everything the REST/WS layer (and the headless demo script) need,
    wired once from Settings. Single-writer DB + single Scheduler instance
    per process - this is the composition root.
    """

    settings: Settings
    db: Database
    worktrees: WorktreeManager
    artifacts: ArtifactStore
    approvals: ApprovalBroker
    outcomes: OutcomesStore
    cost: CostTracker
    merge_queue: MergeQueue
    scheduler: Scheduler
    sessions: SessionManager


def build_services(settings: Settings) -> AppServices:
    settings.ensure_dirs()
    db = init_db(settings.db_path)
    worktrees = WorktreeManager(settings.repo_root, settings.worktrees_dir, base_branch=settings.base_branch)
    artifacts = ArtifactStore(db)
    approvals = ApprovalBroker(db)
    outcomes = OutcomesStore(db)
    cost = CostTracker(db)
    merge_queue = MergeQueue(worktrees, base_branch=settings.base_branch, test_command=None)
    scheduler = Scheduler(
        db=db,
        worktrees=worktrees,
        artifacts=artifacts,
        approvals=approvals,
        outcomes=outcomes,
        cost=cost,
        merge_queue=merge_queue,
        claude_bin=settings.claude_bin,
        base_branch=settings.base_branch,
    )
    sessions = SessionManager(db, worktrees)
    return AppServices(
        settings=settings, db=db, worktrees=worktrees, artifacts=artifacts, approvals=approvals,
        outcomes=outcomes, cost=cost, merge_queue=merge_queue, scheduler=scheduler, sessions=sessions,
    )
