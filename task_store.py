import os
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL")


@contextmanager
def _connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured.")
    connection = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize():
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TIMESTAMPTZ NOT NULL,
                    completed_at TIMESTAMPTZ
                )
            """)
            cursor.execute("""
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
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO tasks (user_id, title, created_at)
                   VALUES (%s, %s, %s)
                   RETURNING id""",
                (str(user_id), title, datetime.now(timezone.utc))
            )
            return cursor.fetchone()["id"]


def list_tasks(user_id, status="pending", limit=20):
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT id, title, status, created_at, completed_at
                   FROM tasks
                   WHERE user_id = %s AND status = %s
                   ORDER BY id DESC LIMIT %s""",
                (str(user_id), status, limit)
            )
            return [dict(row) for row in cursor.fetchall()]


def complete_task(user_id, task_id):
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """UPDATE tasks
                   SET status = 'completed', completed_at = %s
                   WHERE id = %s AND user_id = %s AND status = 'pending'""",
                (datetime.now(timezone.utc), task_id, str(user_id))
            )
            return cursor.rowcount == 1


def delete_task(user_id, task_id):
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM tasks WHERE id = %s AND user_id = %s",
                (task_id, str(user_id))
            )
            return cursor.rowcount == 1
