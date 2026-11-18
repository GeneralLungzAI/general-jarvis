import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = os.environ.get("JARVIS_DB_PATH", "jarvis.db")


def _connect():
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def initialize():
    with _connect() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                completed_at TEXT
            )
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_user_status
            ON tasks(user_id, status, id)
        """)


def add_task(user_id, title):
    title = title.strip()
    if not title:
        raise ValueError("Task title cannot be empty.")
    if len(title) > 500:
        raise ValueError("Task title must be 500 characters or fewer.")

    with _connect() as connection:
        cursor = connection.execute(
            """INSERT INTO tasks (user_id, title, created_at)
               VALUES (?, ?, ?)""",
            (str(user_id), title, datetime.now(timezone.utc).isoformat())
        )
        return cursor.lastrowid


def list_tasks(user_id, status="pending", limit=20):
    with _connect() as connection:
        rows = connection.execute(
            """SELECT id, title, status, created_at, completed_at
               FROM tasks
               WHERE user_id = ? AND status = ?
               ORDER BY id DESC LIMIT ?""",
            (str(user_id), status, limit)
        ).fetchall()
        return [dict(row) for row in rows]


def complete_task(user_id, task_id):
    with _connect() as connection:
        cursor = connection.execute(
            """UPDATE tasks
               SET status = 'completed', completed_at = ?
               WHERE id = ? AND user_id = ? AND status = 'pending'""",
            (datetime.now(timezone.utc).isoformat(), task_id, str(user_id))
        )
        return cursor.rowcount == 1


def delete_task(user_id, task_id):
    with _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM tasks WHERE id = ? AND user_id = ?",
            (task_id, str(user_id))
        )
        return cursor.rowcount == 1
