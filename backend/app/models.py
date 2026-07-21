from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class TaskRole(StrEnum):
    engineer = "engineer"
    reviewer = "reviewer"


class TaskStatus(StrEnum):
    queued = "queued"
    running = "running"
    awaiting_approval = "awaiting_approval"
    approved = "approved"
    rejected = "rejected"
    merging = "merging"
    done = "done"
    escalated = "escalated"


class SessionStatus(StrEnum):
    active = "active"
    idle = "idle"
    closed = "closed"


class ApprovalStepKind(StrEnum):
    plan = "plan"
    task = "task"


class ApprovalStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class FailureClass(StrEnum):
    review_rejected = "review_rejected"
    test_failed = "test_failed"
    human_rejected = "human_rejected"
    escalated = "escalated"


# ---- Typed artifacts (the contracts between pipeline steps) ---------------
# Kept small and strict on purpose - this is what keeps the system debuggable.


class PlanTask(BaseModel):
    id: str
    title: str
    spec: str
    role: TaskRole = TaskRole.engineer
    branch: str
    depends_on: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    """Emitted by the Planner agent. Editable by the human before gate 1."""

    tasks: list[PlanTask]


class TestReport(BaseModel):
    ran: bool
    passed: bool
    command: str | None = None
    output: str = ""


class Diff(BaseModel):
    """Captured by us from `git diff` in the task's worktree, not emitted by the agent."""

    patch: str
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0


class Review(BaseModel):
    """Emitted by the Reviewer agent. An AI pre-filter, not the final say."""

    verdict: Literal["approve", "request_changes"]
    issues: list[str] = Field(default_factory=list)
    notes: str = ""


ARTIFACT_SCHEMAS: dict[str, type[BaseModel]] = {
    "plan": Plan,
    "diff": Diff,
    "review": Review,
    "test_report": TestReport,
}
