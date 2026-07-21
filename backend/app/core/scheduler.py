from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

from app.bus import bus
from app.core.approvals import ApprovalBroker
from app.core.artifacts import ArtifactStore
from app.core.executor import ENGINEER_ROLE, PLANNER_ROLE, REVIEWER_ROLE, ExecutorError, run_claude
from app.core.ids import new_id
from app.core.llm_meta import CostTracker
from app.core.merge import MergeQueue
from app.core.outcomes import OutcomesStore
from app.core.session_manager import Session
from app.core.worktrees import WorktreeError, WorktreeManager, capture_diff, ensure_committed
from app.db import Database
from app.models import ApprovalStatus, FailureClass, Plan, PlanTask, Review, TaskStatus

logger = logging.getLogger("devworkspace.scheduler")


class SchedulerError(RuntimeError):
    pass


@dataclass
class ResolvedTask:
    id: str
    plan_task: PlanTask
    depends_on: list[str]


class Scheduler:
    """Deterministic state machine. No LLM reasoning happens here - it spawns,
    watches, gates, and merges. The Planner agent and the human are the brains.
    """

    def __init__(
        self,
        *,
        db: Database,
        worktrees: WorktreeManager,
        artifacts: ArtifactStore,
        approvals: ApprovalBroker,
        outcomes: OutcomesStore,
        cost: CostTracker,
        merge_queue: MergeQueue,
        claude_bin: str = "claude",
        base_branch: str = "main",
    ):
        self.db = db
        self.worktrees = worktrees
        self.artifacts = artifacts
        self.approvals = approvals
        self.outcomes = outcomes
        self.cost = cost
        self.merge_queue = merge_queue
        self.claude_bin = claude_bin
        self.base_branch = base_branch

    # -- Planner step + gate 1 -------------------------------------------

    async def submit_request(self, session: Session, request_text: str) -> tuple[str, str]:
        """Runs the Planner, persists a Plan artifact, opens the gate-1 approval.
        Returns (artifact_id, approval_id). Does not block on the human.
        """
        prompt = (
            f"User request for this repo:\n\n{request_text}\n\n"
            "Break this into a dependency-ordered list of engineer tasks."
        )
        t0 = time.monotonic()
        try:
            result = await run_claude(
                prompt, cwd=session.worktree_path, role=PLANNER_ROLE, claude_bin=self.claude_bin
            )
        except ExecutorError as e:
            raise SchedulerError(f"planner invocation failed: {e}") from e
        await self.cost.record(
            session_id=session.id, task_id=None, event="planner", result=result,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
        if not result.ok or result.structured is None:
            raise SchedulerError(f"planner failed: {result.error_detail or result.result_text}")

        try:
            plan = Plan.model_validate(result.structured)
        except Exception as e:
            raise SchedulerError(f"planner returned a plan that failed validation: {e}") from e
        artifact_id = await self.artifacts.save(kind="plan", session_id=session.id, task_id=None, body=plan)
        approval_id = await self.approvals.request(
            session_id=session.id, task_id=None, step_kind="plan", payload_ref=artifact_id
        )
        return artifact_id, approval_id

    async def resolve_plan(
        self, session: Session, approval_id: str, *, approved: bool, edited_plan: Plan | None = None, reason: str | None = None
    ) -> tuple[Plan, dict[str, str]] | tuple[None, None]:
        """Resolve gate 1. If edited_plan is given, it replaces the artifact the
        approval points at before resolving (human text-edits the plan; MVP
        keeps this as replace-then-approve rather than a diffed edit history).
        Returns (plan, id_map) on approval - id_map is needed to call run_all_tasks.
        """
        approval_row = self.db.fetch_one("SELECT * FROM approvals WHERE id = ?", (approval_id,))
        if approval_row is None:
            raise KeyError(approval_id)
        payload_ref = approval_row["payload_ref"]

        if edited_plan is not None:
            payload_ref = await self.artifacts.save(
                kind="plan", session_id=session.id, task_id=None, body=edited_plan
            )
            await self.db.execute("UPDATE approvals SET payload_ref = ? WHERE id = ?", (payload_ref, approval_id))

        await self.approvals.resolve(
            approval_id, ApprovalStatus.approved if approved else ApprovalStatus.rejected, reason
        )
        if not approved:
            return None, None

        artifact = self.artifacts.get(payload_ref)
        if artifact is None:
            raise SchedulerError(f"plan artifact {payload_ref} missing")
        plan = Plan.model_validate(artifact["body"])
        id_map = await self._persist_tasks(session, plan)
        return plan, id_map

    async def _persist_tasks(self, session: Session, plan: Plan) -> dict[str, str]:
        id_map = {t.id: new_id("task") for t in plan.tasks}
        statements = []
        for t in plan.tasks:
            db_id = id_map[t.id]
            depends_on_db = [id_map[d] for d in t.depends_on if d in id_map]
            statements.append((
                "INSERT INTO tasks (id, session_id, title, spec, role, branch, status, depends_on) "
                "VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)",
                (db_id, session.id, t.title, t.spec, t.role.value, t.branch, json.dumps(depends_on_db)),
            ))
        await self.db.execute_many(statements)
        return id_map

    # -- Task pipeline: engineer -> reviewer -> gate 2 -> merge ----------

    async def run_all_tasks(self, session: Session, plan: Plan, id_map: dict[str, str]) -> None:
        """Sequential dispatch respecting depends_on (Phase 1). Phase 3 adds a
        concurrency-capped semaphore for running independent tasks in parallel.
        """
        resolved = {
            id_map[t.id]: ResolvedTask(id=id_map[t.id], plan_task=t, depends_on=[id_map[d] for d in t.depends_on if d in id_map])
            for t in plan.tasks
        }
        done: set[str] = set()
        blocked: set[str] = set()
        remaining = dict(resolved)
        while remaining:
            # Dependents of a task that didn't merge get escalated without running,
            # rather than building on a base that's missing the expected changes.
            newly_blocked = [rt for rt in remaining.values() if set(rt.depends_on) & blocked]
            for rt in newly_blocked:
                upstream = sorted(set(rt.depends_on) & blocked)
                await self._escalate(
                    session, rt.id, FailureClass.escalated, f"blocked: upstream task(s) {upstream} did not merge"
                )
                blocked.add(rt.id)
                del remaining[rt.id]
            if newly_blocked:
                continue

            ready = [rt for rt in remaining.values() if set(rt.depends_on) <= done]
            if not ready:
                raise SchedulerError("unsatisfiable or circular depends_on in plan")
            for rt in ready:
                try:
                    await self.run_task(session, rt)
                except Exception as e:  # noqa: BLE001 - a bug in one task must not kill the whole pipeline
                    logger.exception("unexpected error running task %s", rt.id)
                    await self._escalate(session, rt.id, FailureClass.escalated, f"unexpected error: {e}")
                del remaining[rt.id]
                row = self.db.fetch_one("SELECT status FROM tasks WHERE id = ?", (rt.id,))
                if row is not None and row["status"] == TaskStatus.done.value:
                    done.add(rt.id)
                else:
                    blocked.add(rt.id)

    async def _set_task_status(self, task_id: str, status: TaskStatus, **extra) -> None:
        cols = ["status = ?"]
        params: list = [status.value]
        for k, v in extra.items():
            cols.append(f"{k} = ?")
            params.append(v)
        params.append(task_id)
        await self.db.execute(f"UPDATE tasks SET {', '.join(cols)} WHERE id = ?", params)
        bus.publish(f"task:{task_id}", {"event": "status", "status": status.value})

    async def run_task(self, session: Session, rt: ResolvedTask) -> None:
        task_id = rt.id
        plan_task = rt.plan_task
        await self._set_task_status(task_id, TaskStatus.running)
        bus.publish(f"session:{session.id}", {"event": "task_running", "task_id": task_id, "title": plan_task.title})

        # Namespace with our own (guaranteed-unique) task id rather than trusting
        # the Planner's suggested branch name verbatim - two tasks (or a task and
        # its own session) can otherwise collide on the same branch name.
        unique_branch = f"{plan_task.branch}-{task_id.rsplit('_', 1)[-1]}"
        try:
            wt = await self.worktrees.create(task_id, unique_branch, base=self.base_branch)
        except WorktreeError as e:
            await self._escalate(session, task_id, FailureClass.escalated, f"could not create worktree: {e}")
            return
        await self.db.execute(
            "UPDATE tasks SET worktree_path = ?, branch = ? WHERE id = ?", (str(wt.path), wt.branch, task_id)
        )
        await self.db.execute(
            "INSERT INTO worktrees (id, branch, path, session_id, status) VALUES (?, ?, ?, ?, 'active')",
            (new_id("wt"), wt.branch, str(wt.path), session.id),
        )

        async def on_event(event: dict) -> None:
            bus.publish(f"session:{session.id}", {"event": "agent_event", "task_id": task_id, "payload": event})

        t0 = time.monotonic()
        try:
            result = await run_claude(
                plan_task.spec, cwd=wt.path, role=ENGINEER_ROLE, claude_bin=self.claude_bin, on_event=on_event
            )
        except ExecutorError as e:
            await self._escalate(session, task_id, FailureClass.escalated, f"engineer invocation failed: {e}")
            return
        await self.cost.record(
            session_id=session.id, task_id=task_id, event="engineer", result=result,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
        if not result.ok:
            await self._escalate(session, task_id, FailureClass.escalated, result.error_detail or "engineer run failed")
            return

        # Don't trust the agent to have remembered to commit - an uncommitted
        # change is invisible to the merge step and to `git diff` for new files.
        await ensure_committed(wt.path, f"{plan_task.title}\n\n{plan_task.spec}")

        diff_body = await capture_diff(wt.path, base=self.base_branch)
        diff_artifact_id = await self.artifacts.save(kind="diff", session_id=session.id, task_id=task_id, body=diff_body)

        review = await self._run_reviewer(session, task_id, wt.path, plan_task)

        await self._set_task_status(task_id, TaskStatus.awaiting_approval)
        approval_id = await self.approvals.request(
            session_id=session.id, task_id=task_id, step_kind="task", payload_ref=diff_artifact_id
        )
        status, reason = await self.approvals.wait_for(approval_id)

        if status == ApprovalStatus.rejected:
            await self._set_task_status(task_id, TaskStatus.rejected)
            await self.outcomes.record(
                task_id=task_id, session_id=session.id, failure_class=FailureClass.human_rejected, raw_reason=reason or ""
            )
            bus.publish(f"session:{session.id}", {"event": "task_rejected", "task_id": task_id, "reason": reason})
            return

        await self._set_task_status(task_id, TaskStatus.approved)
        await self._merge(session, task_id, wt.branch, wt.path)

    async def _run_reviewer(self, session: Session, task_id: str, worktree_path, plan_task: PlanTask) -> Review | None:
        prompt = (
            f"Task spec:\n\n{plan_task.spec}\n\n"
            "Review the changes on this branch relative to the base branch."
        )
        t0 = time.monotonic()
        try:
            result = await run_claude(prompt, cwd=worktree_path, role=REVIEWER_ROLE, claude_bin=self.claude_bin)
        except ExecutorError as e:
            logger.warning("reviewer invocation failed for task %s: %s", task_id, e)
            return None
        await self.cost.record(
            session_id=session.id, task_id=task_id, event="reviewer", result=result,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
        if not result.ok or result.structured is None:
            logger.warning("reviewer failed for task %s: %s", task_id, result.error_detail)
            return None
        try:
            review = Review.model_validate(result.structured)
        except Exception as e:
            logger.warning("reviewer returned invalid review for task %s: %s", task_id, e)
            return None
        await self.artifacts.save(kind="review", session_id=session.id, task_id=task_id, body=review)
        return review

    async def _merge(self, session: Session, task_id: str, branch: str, worktree_path) -> None:
        await self._set_task_status(task_id, TaskStatus.merging)
        merged_ok, test_report, error_detail = await self.merge_queue.merge_task(
            task_branch=branch, task_worktree_path=worktree_path
        )
        await self.artifacts.save(kind="test_report", session_id=session.id, task_id=task_id, body=test_report)

        if not merged_ok:
            failure_class = FailureClass.test_failed if test_report.ran and not test_report.passed else FailureClass.escalated
            await self._escalate(session, task_id, failure_class, error_detail or "merge failed")
            return

        await self._set_task_status(task_id, TaskStatus.done)
        bus.publish(f"session:{session.id}", {"event": "task_done", "task_id": task_id})
        await self.worktrees.remove(worktree_path)
        await self.db.execute("UPDATE worktrees SET status = 'removed' WHERE path = ?", (str(worktree_path),))

    async def _escalate(self, session: Session, task_id: str, failure_class: FailureClass, reason: str) -> None:
        await self._set_task_status(task_id, TaskStatus.escalated)
        await self.outcomes.record(task_id=task_id, session_id=session.id, failure_class=failure_class, raw_reason=reason)
        bus.publish(f"session:{session.id}", {"event": "task_escalated", "task_id": task_id, "reason": reason})
