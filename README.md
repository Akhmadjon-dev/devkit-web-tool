# DevWorkspace

A local-first, web-based, multi-agent developer workspace. You open **orchestrator
sessions** (like opening a terminal chat) in your browser, describe what you want
built, and each session drives real work on your git repo through fresh **Claude
Code agents** — under your per-step approval, with a shared memory layer underneath.

Nothing reaches your `main` branch without you looking at a diff and clicking
Approve. That's the whole safety model.

Full architectural rationale and the phase-by-phase build plan this app was built
from live in [`devworkspace-mvp-plan.md`](./devworkspace-mvp-plan.md). This README
is the "how do I actually use it" doc.

---

## The core loop

```
YOU (open a session, type a request)
   │  "add CSV export with a date-range filter"
   ▼
PLANNER agent (fresh claude, read-only)  ──►  editable PLAN (task list)
   │
  [GATE 1 — you approve or edit the plan]
   ▼
DETERMINISTIC SCHEDULER (plain Python, no LLM reasoning)
   • per task, in its own git worktree + branch:
        ENGINEER agent  ──►  implements it, commits
        REVIEWER agent  ──►  pre-filter review (not the final say)
   │
  [GATE 2 — you approve or reject the diff]
   ▼
  approved  ──►  rebase onto main, run tests, fast-forward merge
  rejected/failed  ──►  recorded as an outcome, nothing merges
```

Every agent is a **fresh, isolated** `claude` process in its own git worktree — it
has no memory of anything except what's in its prompt. The Planner and Engineer
prompts are automatically enriched with relevant project notes and `git grep` hits
so agents don't have to guess at your conventions.

---

## Prerequisites

- **[Claude Code CLI](https://claude.com/claude-code)** installed and authenticated
  (`claude` on your `PATH`). This is the actual executor — DevWorkspace is
  coordination + memory + approval + web around it.
- **Python 3.12+** and **[uv](https://docs.astral.sh/uv/)** for the backend.
- **Node 20+** and **npm** for the frontend.
- **git** (obviously — worktrees are the isolation mechanism).
- A git repository to point DevWorkspace at. Its default branch should be `main`
  (or set `DEVWORKSPACE_BASE_BRANCH` if it's `master` or something else).

## Quickstart

```bash
# 1. Backend
cd backend
uv sync --extra dev
DEVWORKSPACE_REPO_ROOT=/path/to/the/repo/you/want/to/work/on \
  uv run uvicorn app.main:app --host 127.0.0.1 --port 8787

# The backend prints a one-time URL with your auth token baked in:
#   open the app: http://localhost:5173/?token=<...>

# 2. Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Open the URL the backend printed (or `http://localhost:5173`, then paste the
token from `backend/data/token` when prompted). Click **+ new**, type a title,
then describe what you want built in the chat box and hit Send.

That's it — you're now watching a real Planner agent read your repo.

---

## Configuration

All settings are environment variables (or a `backend/.env` file), prefixed
`DEVWORKSPACE_`. Nothing is required except pointing at a repo — everything else
has a sane default.

| Variable | Default | What it does |
|---|---|---|
| `DEVWORKSPACE_REPO_ROOT` | current directory | The git repo this instance orchestrates work on. |
| `DEVWORKSPACE_BASE_BRANCH` | `main` | The branch tasks are based off of and merge back into. Set to `master` etc. if that's what your repo uses. |
| `DEVWORKSPACE_HOST` | `127.0.0.1` | Never change this to `0.0.0.0` — see [Security](#security). |
| `DEVWORKSPACE_PORT` | `8787` | Backend port. |
| `DEVWORKSPACE_DATA_DIR` | `backend/data` | Where the SQLite DB, worktree pool, and auth token live. |
| `DEVWORKSPACE_CLAUDE_BIN` | `claude` | Path to the Claude Code CLI, if it's not on `PATH`. |
| `DEVWORKSPACE_MAX_AGENTS` | `3` | Max concurrent `claude` subprocesses across *all* sessions/tasks at once. |
| `DEVWORKSPACE_DEFAULT_BUDGET_USD` | unset (unlimited) | Per-session spend cap. Once a session's tracked cost reaches this, further planner/engineer calls for that session are blocked (not the whole app) until you notice and act — no silent overspend. |
| `DEVWORKSPACE_TOKEN` | auto-generated | The local auth token. Normally you don't set this — one is generated on first boot and persisted to `data/token`. |

The frontend expects the backend at `http://localhost:8787` (see
`frontend/src/api/client.ts`) and itself runs on port `5173` — these are
hardcoded for the local-first MVP, not currently configurable.

---

## How it works

### Sessions

A **session** is one orchestrator conversation — one chat, one dedicated git
worktree, one branch. Open as many as you want; they run fully in parallel (each
gets isolated on-disk state, so there's no cross-contamination). A process-wide
concurrency cap (`DEVWORKSPACE_MAX_AGENTS`) limits how many `claude` subprocesses
run *simultaneously* across all of them — extra work just queues.

Type a request in a session's chat box. That spawns a **Planner** agent
(read-only — it explores the repo but can't edit anything) that reads your
request plus any relevant notes/code context and produces a **Plan**: a
dependency-ordered list of tasks, each with a title, a self-contained spec, and a
branch name.

### Gate 1 — the plan

The plan shows up in your session as a card you can approve, edit (as raw JSON),
or reject. Nothing runs until you approve it. This is the point to catch a
misunderstood request before any code gets written.

### Tasks: Engineer → Reviewer

Once approved, each task (respecting its dependencies — independent tasks run
concurrently, dependent ones wait for their prerequisite to actually merge first)
gets its own fresh git worktree and branch. An **Engineer** agent implements the
spec there. Whatever it does — committed or not — gets captured: DevWorkspace
auto-commits any outstanding changes before computing the diff, so an agent that
forgets to `git commit` doesn't silently produce an empty-looking diff.

A **Reviewer** agent (defaults to a cheaper model tier) then looks at the diff
against the spec and leaves a verdict + notes. This is a pre-filter to help you
decide faster — it is explicitly *not* the final say.

### Gate 2 — the diff

The task parks with its diff, the reviewer's verdict, and Approve/Reject buttons.
Approving triggers: rebase onto the latest base branch → run tests (if
configured) → fast-forward merge. All of this is serialized process-wide, so two
sessions approving at the same moment still merge one at a time, safely.

Rejecting or a merge/test failure records an **outcome** with a reason, and the
task's card shows exactly why — not just a red badge.

### Notes (shared memory)

The Notes panel in the right rail is where you write conventions and decisions
("always name the export function `export_report`", "we use `httpx` not
`requests`"). Every note is retrieved (via SQLite FTS5, no LLM involved) into
Planner and Engineer prompts when relevant, alongside a handful of `git grep`
hits for the request/spec's keywords. This has been verified to actually work:
a real Planner run cited a naming-convention note verbatim in its generated spec.

Writing a note is always an explicit action you take — retrieval never writes
anything, and agents can't add notes on their own.

### Cost

The Cost panel shows running totals, live, per session and overall. Combined
with the per-session budget cap, this is meant to make sure you're never
surprised by a bill.

### Worktrees / kill / cleanup

The Worktrees panel lists every active git worktree DevWorkspace has open, live.
"Kill session" on a session cancels any in-flight agent work for it (the actual
`claude` subprocess gets killed, not just relabeled in the DB) and removes its
worktree. "Clean up orphaned" sweeps worktrees that exist on disk but are
untracked or belong to a closed session — handles the case where the backend
process died before its own cleanup ran. On every startup, tasks left mid-flight
by a crash are automatically escalated (there's no process left to resume them)
rather than spinning forever in the UI.

---

## Security

- Binds to `127.0.0.1` only. Never set `DEVWORKSPACE_HOST=0.0.0.0` — this would
  expose an unauthenticated-by-default local dev tool that can write to your
  filesystem and spawn subprocesses.
- A local bearer token gates every REST/WebSocket call. It's generated on first
  boot into `data/token` and printed in the startup log with a ready-to-open URL.
- Agents run with `--permission-mode bypassPermissions` inside their isolated
  worktrees. This is intentional, not an oversight: the isolation (a disposable
  worktree) plus the two human gates (plan, diff) *are* the safety boundary — not
  per-tool-call prompts an agent could get stuck on unattended. Don't point this
  at a repo/environment you wouldn't otherwise let an unattended script run in.

---

## Project structure

```
backend/
  app/
    main.py            FastAPI app, auth middleware, CORS, exception handlers
    config.py           Settings (env vars)
    db.py                SQLite (WAL) connection + migrations
    schema.sql            Table definitions
    models.py              Pydantic models for typed artifacts (Plan/Diff/Review/...)
    services.py              Composition root - wires everything from Settings
    bus.py                     In-process pub/sub -> WebSocket topics
    core/
      executor.py       Spawns `claude` subprocesses per role, parses results
      scheduler.py       The deterministic state machine (no LLM reasoning here)
      worktrees.py        git worktree/branch lifecycle
      merge.py             Serialized rebase -> test -> fast-forward merge queue
      approvals.py          Gate broker (pending -> resolved)
      artifacts.py           Typed plan/diff/review/test_report persistence
      memory.py                Non-LLM code retrieval (git grep)
      notes.py                  Project notes store (FTS5)
      session_manager.py         Session lifecycle
      task_registry.py            Tracks in-flight work per session, for kill
      reconcile.py                  Startup crash-recovery + orphan cleanup
      llm_meta.py                    Cost/token trace recording
      outcomes.py                     Failure/rejection recording
    api/
      rest.py            REST endpoints
      ws.py                WebSocket topics (session/{id}, approvals, cost, worktrees)
  tests/                 54 tests, real git operations, claude CLI mocked at the
                          module-level `run_claude` symbol (see tests/test_scheduler.py)
  scripts/
    phase1_demo.py       Headless CLI walkthrough of the whole loop, no web needed

frontend/
  src/
    App.tsx              Shell layout: session tabs + shared rail
    api/                 REST client, WS hook, TS types mirroring the backend models
    components/          SessionChat, PlanApprovalCard, TaskApprovalCard, DiffViewer,
                          ApprovalsQueue, CostMeter, NotesPanel, WorktreesPanel, ...
    store/auth.ts         Token capture/storage (zustand)
```

---

## Development

```bash
# Backend tests (fast - real git operations, claude CLI mocked)
cd backend && uv run pytest -q

# Backend typecheck-equivalent: just run the app, Python has no separate step
cd backend && uv run python -c "import app.main"

# Frontend typecheck
cd frontend && npx tsc --noEmit

# Headless walkthrough of the full pipeline (no browser needed) - creates a
# disposable demo repo under backend/data/demo-repo on first run:
cd backend && uv run python scripts/phase1_demo.py "add a hello.txt file containing hi"
```

The test suite mocks only the `claude` CLI call itself (`app.core.scheduler.run_claude`)
— every git operation (worktree creation, diffing, rebasing, fast-forward
merging) runs for real against a disposable repo per test. This project has also
been verified multiple times against the **real** Claude Code CLI end-to-end
through an actual browser, including the exact scenario each Phase's checkpoint
describes in the plan doc.

---

## MVP scope — what's deliberately *not* here

Straight from the build plan's scope discipline, still true:

- Sub-agents spawning their own sub-agents (strictly two levels: you → agents).
- Vector DB / embedding-based retrieval (grep + FTS5 only; upgrade path exists
  if that stops being enough).
- Memory *consolidation* / auto-learning loops (outcomes are captured, not
  mined into new notes automatically).
- Auto-replanning on failure (a failure escalates to you; it doesn't retry itself).
- Debate/swarm patterns, integrator agents.
- Auth beyond the local token. Multi-user. Anything cloud.
- An embedded terminal, dependency-graph visualization, or drag-and-drop plan
  editing (the plan is a JSON textarea you edit by hand if needed).

If you're tempted to make the scheduler "reason" about anything, don't — it's
supposed to stay dumb plumbing. The Planner agent and you are the brains.

---

## Troubleshooting

**"blocked by CORS policy" in the browser console** — this almost always means
the *backend* request failed (400/500), not an actual CORS misconfiguration;
check the backend's terminal log for the real error. A `WorktreeError` there
("invalid reference: main") usually means your repo's default branch isn't
called `main` — set `DEVWORKSPACE_BASE_BRANCH`.

**A session's tab disappeared / re-appeared unexpectedly after kill** — this
was a real race we found and fixed (the "auto-select a session on load" effect
briefly fighting the kill action); if you see it again on a fresh checkout,
it's a regression worth filing.

**Planner/Engineer call seems stuck** — planner and reviewer calls time out
after 5 minutes, engineer calls after 20, and always escalate/fail cleanly
rather than hang forever. If a task sits in `running` past that with nothing
happening, check the backend log.

**Nothing merges even though I approved it** — check the task's escalation
banner (now surfaced directly in the UI); the most common causes are a rebase
conflict against `main` or a configured test command failing.
