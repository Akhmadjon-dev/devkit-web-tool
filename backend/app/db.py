from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, Iterable

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


class Database:
    """Thin sqlite wrapper enforcing the single-writer invariant.

    Reads run freely (WAL allows concurrent readers). All writes acquire an
    asyncio.Lock so concurrent agent callbacks never interleave writes -
    the scheduler is the only thing that mutates state, one command at a time.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn = _connect(db_path)
        self._write_lock = asyncio.Lock()

    def migrate(self) -> None:
        sql = _SCHEMA_PATH.read_text()
        with self._conn:
            self._conn.executescript(sql)

    # -- reads (no lock needed under WAL) --------------------------------
    def fetch_one(self, query: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        cur = self._conn.execute(query, tuple(params))
        return cur.fetchone()

    def fetch_all(self, query: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        cur = self._conn.execute(query, tuple(params))
        return cur.fetchall()

    # -- writes (serialized) ---------------------------------------------
    async def execute(self, query: str, params: Iterable[Any] = ()) -> None:
        async with self._write_lock:
            with self._conn:
                self._conn.execute(query, tuple(params))

    async def execute_many(self, statements: list[tuple[str, Iterable[Any]]]) -> None:
        """Run several statements atomically under one transaction + the write lock."""
        async with self._write_lock:
            with self._conn:
                for query, params in statements:
                    self._conn.execute(query, tuple(params))

    def close(self) -> None:
        self._conn.close()


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        raise RuntimeError("Database not initialized - call init_db() at startup")
    return _db


def init_db(db_path: Path) -> Database:
    global _db
    _db = Database(db_path)
    _db.migrate()
    return _db
