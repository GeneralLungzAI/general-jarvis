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
# instances from polling Telegram with the same bot token. Keeping the lock
# transaction open also works with Neon pooled (transaction-pooling) endpoints.
# The key is stable across bot-token rotations.
TELEGRAM_POLLING_LOCK_KEY = 9292355243


def _polling_lock_connection():
    """Open a dedicated, resilient connection for the polling lock."""
    return psycopg2.connect(
        DATABASE_URL,
        connect_timeout=10,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=3,
        options="-c statement_timeout=10000"
    )


def acquire_telegram_polling_lock(retry_seconds=5):
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured.")

    while True:
        connection = None
        try:
            connection = _polling_lock_connection()
            # Keep autocommit disabled: the transaction-scoped lock remains
            # held on this dedicated connection until rollback/close.
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
                return connection

            connection.close()
            print(
                "[JARVIS] Another instance owns the Telegram polling lock; "
                f"retrying in {retry_seconds} seconds.",
                flush=True
            )
            time.sleep(retry_seconds)

        except psycopg2.OperationalError as error:
            if connection is not None:
                connection.close()
            print(
                "[JARVIS] Neon is temporarily unavailable while acquiring "
                f"the polling lock: {error!r}. Retrying in {retry_seconds} seconds.",
                flush=True
            )
            time.sleep(retry_seconds)

        except Exception:
            if connection is not None:
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
                # Fail closed: never allow this process to keep polling after
                # losing confidence that it still owns the database lock.
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
    heartbeat_thread.join(timeout=15)

    if heartbeat_thread.is_alive():
        print(
            "[JARVIS] CRITICAL: Polling-lock heartbeat did not stop cleanly. "
            "Exiting rather than risk polling without a verified lock.",
            flush=True
        )
        os._exit(1)

    if not connection_lock.acquire(timeout=5):
        print(
            "[JARVIS] CRITICAL: Could not safely acquire the polling-lock "
            "connection for shutdown. Exiting.",
            flush=True
        )
        os._exit(1)

    try:
        try:
            # Rolling back ends the lock-owning transaction and releases
            # the advisory lock. Closing then returns the connection cleanly.
            connection.rollback()
        finally:
            connection.close()
    finally:
        connection_lock.release()

    print("[JARVIS] Released exclusive Telegram polling lock.", flush=True)
