import os
import time
import threading
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


# A transaction-scoped PostgreSQL advisory lock prevents overlapping Render
# instances from polling Telegram with the same bot token. The key is the
# Telegram bot ID, making it stable across deployments and token rotations.
TELEGRAM_POLLING_LOCK_KEY = 9292355243


def acquire_telegram_polling_lock(retry_seconds=5):
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured.")

    while True:
        connection = psycopg2.connect(
            DATABASE_URL,
            connect_timeout=10
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_try_advisory_xact_lock(%s)",
                    (TELEGRAM_POLLING_LOCK_KEY,)
                )
                acquired = cursor.fetchone()[0]

            if acquired:
                print(
                    "[JARVIS] Acquired exclusive Telegram polling lock in Neon.",
                    flush=True
                )
                # Keep this transaction open. The transaction-scoped advisory
                # lock remains held until this connection commits or closes.
                return connection

            connection.rollback()
            connection.close()
            print(
                "[JARVIS] Another instance owns the Telegram polling lock; "
                f"retrying in {retry_seconds} seconds.",
                flush=True
            )
            time.sleep(retry_seconds)

        except Exception:
            connection.close()
            raise


def start_telegram_lock_heartbeat(connection, interval_seconds=15):
    stop_event = threading.Event()
    connection_lock = threading.Lock()

    def heartbeat():
        while not stop_event.wait(interval_seconds):
            try:
                with connection_lock:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT 1")
                        cursor.fetchone()
            except Exception as error:
                # If the lock connection is lost, PostgreSQL releases the
                # advisory lock. Stop this process immediately so it cannot
                # continue polling without owning the lock.
                print(
                    "[JARVIS] CRITICAL: Neon polling-lock connection lost: "
                    f"{error!r}. Exiting to prevent duplicate polling.",
                    flush=True
                )
                os._exit(1)

    thread = threading.Thread(
        target=heartbeat,
        name="telegram-lock-heartbeat",
        daemon=True
    )
    thread.start()
    return stop_event, thread, connection_lock


def release_telegram_polling_lock(
    connection,
    stop_event,
    heartbeat_thread,
    connection_lock
):
    stop_event.set()
    heartbeat_thread.join(timeout=20)

    with connection_lock:
        try:
            connection.rollback()
        finally:
            connection.close()

    print("[JARVIS] Released exclusive Telegram polling lock.", flush=True)
