# DevWorkspace — MVP Build Plan

*Local-first, web-based, multi-agent developer workspace · MVP v1 · target: daily-usable in ~2 weeks of part-time build*

---

## 0. What we are building (the MVP, precisely)

A localhost web app where you open **orchestrator sessions** (like opening a terminal chat), and each one drives real work on your git repo through fresh **Claude Code agents**, under your per-step approval, with a **shared memory layer** underneath.

The architecture decisions, already settled:

- **Executor = Claude Code CLI.** Each agent is a fresh `claude` process in its own git worktree. Claude Code owns the agent loop, edits, tools, and worktree lifecycle. We build coordination + memory + approval + web.
- **Coordinator = deterministic Python, not an LLM.** A scheduler/state-machine spawns and watches agents, serializes DB writes, and gates on you. The *reasoning* lives in the **Planner agent** (a discrete step) and in **you**.
- **Parallelism from day one.** N orchestrators, each on its own worktree + branch, running concurrently. Isolation via git worktrees.
- **Backend = Python + FastAPI.** Frontend = React + TypeScript + Vite.
- **Agents communicate via typed artifacts** (plan / diff / review), not by chatting to a boss.
- **Two gates:** approve the plan, then approve each task before it merges.
- **DB stores:** durable *done work*, plus *outcomes* (failures + your rejections, for learning). In-progress chatter stays ephemeral.

### The core loop

```
YOU (orchestrator chat session — you are the intelligence)
   │  "add CSV export with a date-range filter"
   ▼
PLANNER agent (fresh claude) ──► editable PLAN artifact (task list + branches)
   │
  [gate 1: you approve / edit the plan]
   ▼
DETERMINISTIC SCHEDULER (plain Python — no LLM)
   • per task, spawns a fresh claude in its own worktree+branch:
        ENGINEER ──► diff + test-report artifacts
        REVIEWER ──► review artifact  (AI pre-filter, not the final say)
   • watches state, caps concurrency, single-writer to DB
   │
  [gate 2: you approve each task]
   ▼
  approved work ──► DB (durable) ──► serialized merge to main
  rejections/failures ──► outcomes store (learning)
```

---

## 1. Scope discipline — what's IN and what's OUT

Building the *minimum* that's genuinely usable daily. Everything else is deferred on purpose.

### IN (MVP)

- Localhost web app: open/close multiple orchestrator sessions as tabs.
- Each session = a chat you drive + a deterministic pipeline behind it.
- Planner → Engineer → Reviewer, each a fresh Claude Code agent in an isolated worktree.
- Two gates (plan, per-task), with a **global approvals queue** across all sessions.
- Typed artifacts (plan / diff / review / test-report) persisted and viewable.
- Basic shared memory: **code retrieval** (grep/embedding-lite) + **project-notes store** you write to, retrieved into agent context.
- Outcomes capture (rejections + failures with reasons).
- Serialized merge to main (rebase → test → merge, one task at a time).
- Per-session + total **cost meter**.
- Worktree/session lifecycle: list, kill, cleanup, resume-on-restart.

### OUT (deferred — do NOT build in MVP)

- Sub-agents spawning their own sub-agents (keep it two levels: you → agents).
- Fancy vector DB / graph memory (start with SQLite FTS + optional sqlite-vec; upgrade later).
- Memory *consolidation* / auto-learning loops (capture outcomes now, consolidate later).
- Auto-replanning on failure (failure → escalate to you).
- Debate/swarm patterns, integrator agents.
- Auth beyond a local token. Multi-user. Cloud anything.
- Embedded terminal, dependency-graph visualization, drag-and-drop plan editing (text-edit the plan is fine for MVP).

---

## 2. Architecture

```
BROWSER  (localhost:5173)  — React + TS + Vite
┌──────────────────────────────────────────────────────────────┐
│  Session tabs (orchestrator chats)      Shared rail            │
│  ┌────────────┐ ┌────────────┐          ┌──────────────────┐  │
│  │ Orch #1    │ │ Orch #2    │  [+ new] │ Approvals queue   │  │
│  │ feat/export│ │ fix/auth   │          │ Cost meter        │  │
│  │ ▸ engineer │ │ ▸ engineer │          │ Memory / notes    │  │
│  │ ▸ reviewer │ │            │          │ Branches/worktrees│  │
│  │ [approve?] │ │ [approve?] │          └──────────────────┘  │
│  └────────────┘ └────────────┘                                │
└───────────────────────────┬──────────────────────────────────┘
        REST (commands) + WebSocket (streams: session:{id}, approvals, cost)
┌───────────────────────────▼──────────────────────────────────┐
│  BACKEND  (FastAPI, single process, 127.0.0.1 + local token)  │
│                                                                │
│  core/                        ← UI-agnostic service layer      │
│   session_manager.py   spawn/track orchestrator sessions       │
│   scheduler.py         DETERMINISTIC state machine + dispatch  │
│   executor.py          wraps `claude --worktree` subprocess    │
│   worktrees.py         create/list/cleanup git worktrees       │
│   memory.py            retrieval (code + notes) + outcomes      │
│   approvals.py         gate broker (pending → resolved)         │
│   artifacts.py         typed plan/diff/review persistence       │
│   merge.py             serialized rebase→test→merge queue       │
│   llm_meta.py          token/cost accounting from claude output │
│                                                                │
│  api/  (thin)  rest.py (commands)   ws.py (event streams)      │
│  bus.py  in-process pub/sub → WebSocket topics                 │
│                                                                │
│  SQLite (WAL, single-writer):                                  │
│   sessions, tasks, artifacts, approvals, outcomes,             │
│   worktrees, notes, traces                                     │
├────────────────────────────────────────────────────────────────┤
│  git worktree pool          Claude Code CLI (the executor)     │
│   wt-1 → feat/export         claude --worktree <id> -p "<spec>" │
│   wt-2 → fix/auth            + MCP tools (git/test), per-role   │
└────────────────────────────────────────────────────────────────┘
```

### Two invariants that make it safe (do not violate)

1. **One session = one worktree = one branch.** Sessions share *memory*, never a working directory. This is what makes parallel orchestrators safe.
2. **Single-writer DB.** All mutations funnel through the scheduler's command queue. Concurrent agents never write SQLite directly. WAL mode on.

---

## 3. Data model (SQLite)

```sql
sessions(
  id TEXT PRIMARY KEY, title TEXT, branch TEXT, worktree_path TEXT,
  status TEXT,               -- active | idle | closed
  created_at, summary TEXT   -- rolling summary for long sessions
)

tasks(
  id TEXT PRIMARY KEY, session_id TEXT, title TEXT, spec TEXT,
  role TEXT,                 -- engineer | reviewer (planner is a step, not a task)
  branch TEXT, worktree_path TEXT,
  status TEXT,               -- queued|running|awaiting_approval|approved|rejected|merging|done|escalated
  depends_on TEXT,           -- JSON list of task ids (serialization edges)
  created_at
)

artifacts(
  id TEXT PRIMARY KEY, task_id TEXT, session_id TEXT,
  kind TEXT,                 -- plan | diff | review | test_report
  body JSON, created_at
)

approvals(
  id TEXT PRIMARY KEY, session_id TEXT, task_id TEXT,
  step_kind TEXT,            -- plan | task
  payload_ref TEXT,          -- artifact id
  status TEXT,               -- pending | approved | rejected
  reason TEXT, created_at, resolved_at
)

outcomes(
  id TEXT PRIMARY KEY, task_id TEXT, session_id TEXT,
  failure_class TEXT,        -- review_rejected | test_failed | human_rejected | escalated
  raw_reason TEXT, summary TEXT, created_at
)

notes(                        -- project knowledge (conventions/decisions), you write these
  id TEXT PRIMARY KEY, kind TEXT, text TEXT, created_at
)  -- + FTS5 virtual table notes_fts; optional vec_notes later

worktrees(id, branch, path, session_id, status)
traces(id, session_id, task_id, event, tokens, cost, latency_ms, ts)
```

Keep it in **one SQLite file per repo**. That's the whole persistence story for the MVP.

---

## 4. The typed artifacts (the contracts between steps)

Keep these small and strict (Pydantic models). This is what keeps the system debuggable.

**Plan** (from Planner agent):
```json
{ "tasks": [
    { "id": "t1", "title": "add CSV export endpoint", "spec": "…",
      "role": "engineer", "branch": "feat/export-t1", "depends_on": [] },
    { "id": "t2", "title": "date-range filter", "spec": "…",
      "role": "engineer", "branch": "feat/export-t2", "depends_on": ["t1"] }
  ] }
```

**Diff + TestReport** (from Engineer agent): the git diff + what tests were run and their result. (Claude Code produces the diff in its worktree; you capture `git diff` + test output.)

**Review** (from Reviewer agent):
```json
{ "verdict": "approve | request_changes", "issues": ["…"], "notes": "…" }
```

Rule: agents **only** emit these. The scheduler passes artifacts between steps. No agent "talks to" another agent.

---

## 5. Build phases (dependency-ordered)

Each phase ends at a usable checkpoint. **Dogfood from Phase 2** — don't wait for the end.

### Phase 0 — Foundations (½ day)
- [ ] `uv init`, FastAPI skeleton, bind `127.0.0.1`, local token middleware.
- [ ] SQLite bootstrap + migrations (tables above), WAL mode.
- [ ] `executor.py`: run `claude --worktree <id> -p "<spec>"` as a subprocess, capture stdout/stream, parse completion + rough token/cost. Verify with a trivial prompt.
- [ ] `worktrees.py`: create/list/remove git worktrees + branches.
- **Checkpoint:** a Python call spawns a Claude Code agent in a fresh worktree, it makes an edit, you see the diff. No web yet.

### Phase 1 — Single session, end to end, headless (2–3 days)
- [ ] `scheduler.py`: state machine for one task (`queued→running→awaiting_approval→approved→merging→done`).
- [ ] `artifacts.py`: persist plan/diff/review/test_report.
- [ ] `approvals.py`: create pending approval, block task until resolved.
- [ ] `merge.py`: rebase → run tests → merge one branch to main; conflict → `escalated` + outcome row.
- [ ] Planner step: one `claude` call that emits a **Plan** artifact from your request. You edit it as text; approve = gate 1.
- [ ] Wire the loop: request → plan → gate 1 → engineer → (reviewer) → gate 2 → merge.
- [ ] `outcomes`: write on any rejection/failure with reason.
- **Checkpoint:** from a Python script, one real task goes request → plan → approve → engineer builds it in a worktree → you approve the diff → merged to main. This is already useful.

### Phase 2 — Web shell + streaming (2–3 days) → **start dogfooding**
- [ ] FastAPI REST for: create session, submit request, get plan, approve/reject (plan + task), list tasks/artifacts, cost.
- [ ] WebSocket topics: `session:{id}` (streaming agent output + state changes), `approvals`, `cost`.
- [ ] React shell: session tabs; a chat pane per session (your messages + streamed agent output); a **diff viewer** for `dev show`-style task review; approve/reject buttons with a reason field.
- [ ] Global **approvals queue** in the shared rail (across all sessions).
- [ ] Cost meter (per session + total).
- **Checkpoint:** you open a session in the browser, type a request, watch it work, approve the plan and the task, and it merges — all from the web. **Use it on real work from here.**

### Phase 3 — True parallelism (1–2 days)
- [ ] "New session" → auto new worktree + branch; N sessions run concurrently.
- [ ] Concurrency cap (`max_agents`, default 3) via a semaphore in the scheduler.
- [ ] Branches/worktrees view: list, kill session, cleanup orphaned worktrees, resume on restart.
- [ ] Serialized merge queue handles multiple approved branches one at a time.
- **Checkpoint:** two orchestrators on two branches at once; both park for approval; you triage from the global queue; both merge cleanly in sequence.

### Phase 4 — Shared memory (2 days)
- [ ] Code retrieval: index the repo (start simple — ripgrep + file chunking; add sqlite-vec embeddings if grep isn't enough). Inject top-k relevant chunks into agent specs.
- [ ] Project notes: `notes` table + FTS5; a "notes" pane to add conventions/decisions; retrieve relevant notes into Planner/Engineer context.
- [ ] Retrieval is **read-only + non-LLM** on the hot path. Durable writes (promoting a note) are a gated action.
- **Checkpoint:** an agent visibly uses a convention you wrote as a note, and cites a relevant file it retrieved rather than guessing.

### Phase 5 — Hardening for daily use (1–2 days)
- [ ] Kill/resume matrix: crash mid-task → clean recovery; orphaned worktree cleanup.
- [ ] Escalation UX: merge conflict / repeated failure surfaces clearly with the reason.
- [ ] Per-session budget cap: breach pauses and asks (no silent spend).
- [ ] Reviewer defaults to cheaper model tier; engineer/planner to frontier. (Cost control.)
- [ ] Quickstart doc + a "how the two gates work" note to your future self.
- **Checkpoint (definition of done):** a week of your real work runs through it; you trust it enough to not drop to the terminal.

---

## 6. Tech stack

| Concern | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, `uv` |
| Executor | Claude Code CLI (`claude --worktree`) |
| DB | SQLite (WAL) + FTS5; sqlite-vec later if needed |
| Isolation | git worktrees, one per session/task |
| Frontend | React + TypeScript + Vite |
| State (FE) | Zustand + TanStack Query |
| UI kit | Tailwind + shadcn/ui |
| Diff view | Monaco diff editor or react-diff-viewer |
| Transport | REST (commands) + WebSocket (streams) |
| Tools for agents | MCP servers (git, test-runner), per-role grants |

---

## 7. Risks to watch during the MVP (and the cheap mitigations)

- **You become the approval bottleneck.** Make the approval UI fast (diff + one-key approve). Consider a per-session "gate only writes-to-branch, auto-pass trivial steps" toggle after Phase 3.
- **Cost multiplies with parallel agents.** Cost meter is a Phase-2 feature, not polish. Reviewer on cheap tier.
- **Merge reckoning is deferred, not gone.** The serialized merge queue is mandatory before you rely on parallel branches (Phase 3).
- **Orphaned worktrees/sessions after crashes.** Lifecycle view + resume (Phase 3/5).
- **Local security surface** (multiple agent loops with git/fs access). `127.0.0.1` only, local token, per-role MCP grants — never expose the port.
- **Memory pollution** from concurrent writes. Durable-memory writes gated + single-writer DB. Keep strict.
- **Scope creep toward the swarm.** If you're tempted to let the coordinator "reason," stop. The coordinator is dumb plumbing; the Planner and you are the brains.

---

## 8. The first thing to build tomorrow

Phase 0 → Phase 1, headless, no web. Get **one real task** to go request → plan → approve → Claude Code builds it in a worktree → you approve the diff → merged. Once that works from a script, the web layer in Phase 2 is just a nicer face on a loop you already trust.

**Guiding sentence:** LLM intelligence lives in the Planner and in you; the thing that spawns-watches-saves-merges is plain deterministic code. Hold that line and the system stays cheap, debuggable, and yours.
