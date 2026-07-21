-- DevWorkspace schema. One SQLite file per repo. WAL mode set by db.py at connect time.

CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    title         TEXT NOT NULL,
    branch        TEXT,
    worktree_path TEXT,
    status        TEXT NOT NULL DEFAULT 'active',   -- active | idle | closed
    summary       TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS tasks (
    id            TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL REFERENCES sessions(id),
    title         TEXT NOT NULL,
    spec          TEXT,
    role          TEXT NOT NULL,                    -- engineer | reviewer
    branch        TEXT,
    worktree_path TEXT,
    status        TEXT NOT NULL DEFAULT 'queued',    -- queued|running|awaiting_approval|approved|rejected|merging|done|escalated
    depends_on    TEXT NOT NULL DEFAULT '[]',        -- JSON list of task ids
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

CREATE TABLE IF NOT EXISTS artifacts (
    id            TEXT PRIMARY KEY,
    task_id       TEXT REFERENCES tasks(id),
    session_id    TEXT NOT NULL REFERENCES sessions(id),
    kind          TEXT NOT NULL,                     -- plan | diff | review | test_report
    body          TEXT NOT NULL,                      -- JSON
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_session ON artifacts(session_id);

CREATE TABLE IF NOT EXISTS approvals (
    id            TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL REFERENCES sessions(id),
    task_id       TEXT REFERENCES tasks(id),
    step_kind     TEXT NOT NULL,                      -- plan | task
    payload_ref   TEXT,                                -- artifact id
    status        TEXT NOT NULL DEFAULT 'pending',      -- pending | approved | rejected
    reason        TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    resolved_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
CREATE INDEX IF NOT EXISTS idx_approvals_session ON approvals(session_id);

CREATE TABLE IF NOT EXISTS outcomes (
    id            TEXT PRIMARY KEY,
    task_id       TEXT REFERENCES tasks(id),
    session_id    TEXT NOT NULL REFERENCES sessions(id),
    failure_class TEXT NOT NULL,                       -- review_rejected | test_failed | human_rejected | escalated
    raw_reason    TEXT,
    summary       TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS notes (
    id            TEXT PRIMARY KEY,
    kind          TEXT,
    text          TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    text, content='notes', content_rowid='rowid'
);
CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, text) VALUES (new.rowid, new.text);
END;
CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, text) VALUES('delete', old.rowid, old.text);
END;
CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, text) VALUES('delete', old.rowid, old.text);
    INSERT INTO notes_fts(rowid, text) VALUES (new.rowid, new.text);
END;

CREATE TABLE IF NOT EXISTS worktrees (
    id            TEXT PRIMARY KEY,
    branch        TEXT NOT NULL,
    path          TEXT NOT NULL,
    session_id    TEXT REFERENCES sessions(id),
    status        TEXT NOT NULL DEFAULT 'active'        -- active | removed
);

CREATE TABLE IF NOT EXISTS traces (
    id            TEXT PRIMARY KEY,
    session_id    TEXT,
    task_id       TEXT,
    event         TEXT,
    tokens        INTEGER,
    cost          REAL,
    latency_ms    INTEGER,
    ts            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_traces_session ON traces(session_id);
