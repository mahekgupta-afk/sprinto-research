"""SQLite storage for the review workflow: candidates, draft queue, feedback. Short-lived connections (thread safe)."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

MIGRATIONS = [
    """
    CREATE TABLE candidates (
      domain TEXT PRIMARY KEY, company TEXT NOT NULL, headline TEXT, url TEXT, round TEXT, amount_musd REAL,
      published TEXT, score REAL, status TEXT NOT NULL DEFAULT 'new', flag_reason TEXT, found_at TEXT NOT NULL);
    CREATE TABLE drafts (
      id INTEGER PRIMARY KEY AUTOINCREMENT, domain TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
      original_subject TEXT NOT NULL, original_body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
      rating INTEGER, note TEXT, created_at TEXT NOT NULL, decided_at TEXT, send_id TEXT);
    CREATE INDEX drafts_domain ON drafts(domain, status);
    CREATE TABLE learnings (
      id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL CHECK (kind IN ('edit','rating','rule')),
      text TEXT NOT NULL, domain TEXT, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
    """,
]


@contextmanager
def connect(path: Path) -> Iterator[sqlite3.Connection]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        migrate(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def migrate(conn: sqlite3.Connection) -> int:
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    for i, sql in enumerate(MIGRATIONS[v:], start=v + 1):
        conn.executescript(sql)
        conn.execute("PRAGMA user_version=%d" % i)
    return len(MIGRATIONS)


def now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
