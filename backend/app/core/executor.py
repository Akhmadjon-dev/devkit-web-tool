from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.models import Plan, Review

logger = logging.getLogger("devworkspace.executor")

OnEvent = Callable[[dict[str, Any]], Awaitable[None] | None]


class ExecutorError(RuntimeError):
    def __init__(self, message: str, *, exit_code: int | None = None, stderr: str = ""):
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr


@dataclass
class RoleConfig:
    """Per-role invocation policy. Cheap tiering + tool grants live here (Phase 5 cost control)."""

    model: str | None = None
    permission_mode: str = "bypassPermissions"
    disallowed_tools: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    append_system_prompt: str | None = None
    output_format: str = "json"  # "json" (single result) or "stream-json" (live events)
    json_schema: dict[str, Any] | None = None


PLANNER_ROLE = RoleConfig(
    permission_mode="bypassPermissions",
    disallowed_tools=["Edit", "Write", "NotebookEdit"],
    append_system_prompt=(
        "You are the Planner agent in an automated pipeline. Read the repo as needed, "
        "then respond with ONLY a JSON object matching the required schema describing the "
        "task breakdown. Each task's `spec` must be self-contained: the Engineer agent that "
        "receives it will have no memory of this conversation and no other context. "
        "Critically: each task runs in its OWN separate git worktree with its OWN separate "
        "working directory, not the one you are reading the repo from right now - NEVER "
        "include your current working directory or any other absolute filesystem path in a "
        "spec. Describe file locations only relative to the repository root (e.g. "
        "'create hello.txt at the repo root', not '/some/absolute/path/hello.txt'). "
        "Do not edit any files."
    ),
    output_format="json",
    json_schema=Plan.model_json_schema(),
)

ENGINEER_ROLE = RoleConfig(
    permission_mode="bypassPermissions",
    append_system_prompt=(
        "You are the Engineer agent in an automated pipeline, working in an isolated git "
        "worktree on your own branch. Implement the spec, run relevant tests, and commit "
        "your work with git. Nothing you do here reaches main until a human approves the diff."
    ),
    output_format="stream-json",
)

REVIEWER_ROLE = RoleConfig(
    model="haiku",  # cheap tier by default - reviewer is a pre-filter, not the final say
    permission_mode="bypassPermissions",
    disallowed_tools=["Edit", "Write", "NotebookEdit"],
    append_system_prompt=(
        "You are the Reviewer agent in an automated pipeline. You are a pre-filter, not the "
        "final say - a human makes the merge decision. Inspect the diff in this worktree and "
        "respond with ONLY a JSON object matching the required schema."
    ),
    output_format="json",
    json_schema=Review.model_json_schema(),
)


@dataclass
class ClaudeRunResult:
    ok: bool
    result_text: str
    session_id: str | None
    total_cost_usd: float | None
    num_turns: int | None
    duration_ms: int | None
    usage: dict[str, Any] | None
    raw_events: list[dict[str, Any]]
    is_error: bool = False
    error_detail: str | None = None
    structured: Any | None = None  # parsed JSON when role.json_schema was used


def build_command(
    prompt: str,
    role: RoleConfig,
    *,
    claude_bin: str = "claude",
    max_budget_usd: float | None = None,
    add_dirs: list[str] | None = None,
    resume_session_id: str | None = None,
) -> list[str]:
    cmd: list[str] = [claude_bin, "-p", prompt]
    cmd += ["--output-format", role.output_format]
    if role.output_format == "stream-json":
        # Claude Code requires --verbose when combining --print with stream-json output.
        cmd += ["--verbose", "--include-partial-messages"]
    cmd += ["--permission-mode", role.permission_mode]
    if role.model:
        cmd += ["--model", role.model]
    if role.append_system_prompt:
        cmd += ["--append-system-prompt", role.append_system_prompt]
    if role.disallowed_tools:
        cmd += ["--disallowedTools", *role.disallowed_tools]
    if role.allowed_tools:
        cmd += ["--allowedTools", *role.allowed_tools]
    if role.json_schema:
        cmd += ["--json-schema", json.dumps(role.json_schema)]
    if max_budget_usd is not None:
        cmd += ["--max-budget-usd", str(max_budget_usd)]
    if add_dirs:
        cmd += ["--add-dir", *add_dirs]
    if resume_session_id:
        cmd += ["--resume", resume_session_id]
    return cmd


def _extract_result_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Best-effort extraction across Claude Code CLI result-envelope shapes.

    The exact key names have shifted across CLI versions, so we probe a few
    plausible spots rather than assuming one shape. Anything we can't find
    comes back None and the raw envelope is preserved by the caller regardless.
    """
    usage = payload.get("usage")
    cost = payload.get("total_cost_usd", payload.get("cost_usd"))

    raw_result = payload.get("result", "")
    structured: Any | None = None
    if isinstance(raw_result, (dict, list)):
        structured = raw_result
        result_text = json.dumps(raw_result)
    elif isinstance(raw_result, str):
        result_text = raw_result
        stripped = raw_result.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                structured = json.loads(stripped)
            except json.JSONDecodeError:
                structured = None
    else:
        result_text = str(raw_result)

    # When --json-schema is used, the validated object lands in its own
    # `structured_output` field - `result` is often left empty alongside it.
    if "structured_output" in payload:
        structured = payload["structured_output"]
        if not result_text:
            result_text = json.dumps(structured)

    return {
        "session_id": payload.get("session_id"),
        "total_cost_usd": cost,
        "num_turns": payload.get("num_turns"),
        "duration_ms": payload.get("duration_ms"),
        "usage": usage,
        "is_error": bool(payload.get("is_error", payload.get("subtype") not in (None, "success"))),
        "result_text": result_text,
        "structured": structured,
    }


async def run_claude(
    prompt: str,
    *,
    cwd: Path,
    role: RoleConfig,
    claude_bin: str = "claude",
    max_budget_usd: float | None = None,
    add_dirs: list[str] | None = None,
    resume_session_id: str | None = None,
    timeout_seconds: float | None = 1800,
    on_event: OnEvent | None = None,
) -> ClaudeRunResult:
    """Spawn one Claude Code agent, wait for it to finish, return its result.

    For role.output_format == "stream-json", on_event is invoked for every
    parsed JSON event line as it arrives (used to fan progress out to the
    bus/WebSocket in Phase 2). The function still blocks until the process
    exits and returns the aggregated result either way.
    """
    cmd = build_command(
        prompt,
        role,
        claude_bin=claude_bin,
        max_budget_usd=max_budget_usd,
        add_dirs=add_dirs,
        resume_session_id=resume_session_id,
    )
    logger.info("spawning: %s (cwd=%s)", " ".join(cmd[:3]) + " ...", cwd)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    events: list[dict[str, Any]] = []
    stdout_text = ""
    stderr_text = ""

    async def _drain_stdout() -> None:
        nonlocal stdout_text
        assert proc.stdout is not None
        chunks: list[str] = []
        async for raw_line in proc.stdout:
            line = raw_line.decode(errors="replace")
            chunks.append(line)
            stripped = line.strip()
            if not stripped:
                continue
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            events.append(event)
            if on_event is not None:
                maybe = on_event(event)
                if asyncio.iscoroutine(maybe):
                    await maybe
        stdout_text = "".join(chunks)

    async def _drain_stderr() -> None:
        nonlocal stderr_text
        assert proc.stderr is not None
        data = await proc.stderr.read()
        stderr_text = data.decode(errors="replace")

    try:
        await asyncio.wait_for(
            asyncio.gather(_drain_stdout(), _drain_stderr()), timeout=timeout_seconds
        )
        returncode = await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise ExecutorError(f"claude invocation timed out after {timeout_seconds}s", stderr=stderr_text)

    if returncode != 0 and not events and not stdout_text.strip():
        # Nothing at all to work with (binary missing, immediate crash, etc).
        # If there *is* output despite the bad exit code, fall through and let
        # the normal parse path below try to make sense of it - Claude Code
        # may still have written a valid error-shaped result envelope.
        raise ExecutorError(
            f"claude exited {returncode} with no output", exit_code=returncode, stderr=stderr_text
        )

    # The final envelope: single JSON object for output_format=json, or the
    # last {"type": "result", ...} event for stream-json.
    final_payload: dict[str, Any] | None = None
    if role.output_format == "json":
        if stdout_text.strip():
            try:
                final_payload = json.loads(stdout_text)
            except json.JSONDecodeError:
                final_payload = None
    else:
        for event in reversed(events):
            if event.get("type") == "result":
                final_payload = event
                break

    if final_payload is None:
        return ClaudeRunResult(
            ok=False,
            result_text=stdout_text.strip(),
            session_id=None,
            total_cost_usd=None,
            num_turns=None,
            duration_ms=None,
            usage=None,
            raw_events=events,
            is_error=True,
            error_detail=f"could not parse claude output; exit={returncode}; stderr={stderr_text.strip()[:2000]}",
        )

    fields = _extract_result_fields(final_payload)
    return ClaudeRunResult(
        ok=returncode == 0 and not fields["is_error"],
        result_text=fields["result_text"] or stdout_text.strip(),
        session_id=fields["session_id"],
        total_cost_usd=fields["total_cost_usd"],
        num_turns=fields["num_turns"],
        duration_ms=fields["duration_ms"],
        usage=fields["usage"],
        raw_events=events,
        is_error=fields["is_error"],
        error_detail=None if not fields["is_error"] else stderr_text.strip()[:2000] or None,
        structured=fields["structured"],
    )
