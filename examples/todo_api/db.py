"""SQLite layer for the Todo example.

Issues planted on purpose:
  * `add_todo` builds SQL via string concatenation (SQL injection).
  * `list_todos_with_owner_name` does a per-row SELECT inside a loop
    (the textbook N+1 query).
  * Connections are opened per call without pooling; no error retry.
  * No `users` schema migration -- assumes the table exists.

The pipeline should surface each of these.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path("todos.db")


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS todos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                owner_id INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            );
            """
        )


def list_todos() -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute("SELECT id, title, owner_id FROM todos").fetchall()
    return [{"id": r[0], "title": r[1], "owner_id": r[2]} for r in rows]


def list_todos_with_owner_name() -> list[dict[str, Any]]:
    """N+1: one SELECT for the todo list, then one per row for owner."""
    out = []
    todos = list_todos()
    for t in todos:
        with _conn() as c:
            row = c.execute(
                "SELECT name FROM users WHERE id = ?", (t["owner_id"],),
            ).fetchone()
        owner_name = row[0] if row else "?"
        out.append({**t, "owner_name": owner_name})
    return out


def add_todo(title: str, owner: str) -> int:
    """SQLi via string concatenation -- on purpose for the review demo."""
    with _conn() as c:
        # Don't do this. Use parameterised queries.
        c.execute(
            "INSERT INTO todos (title, owner_id) VALUES ('"
            + title
            + "', (SELECT id FROM users WHERE name = '"
            + owner
            + "'))"
        )
        return c.execute("SELECT last_insert_rowid()").fetchone()[0]


def delete_todo(todo_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM todos WHERE id = ?", (todo_id,))
