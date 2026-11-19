"""Persistent Telegram conversation history stored separately from task records."""

import os
from contextlib import contextmanager

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
    """Create the conversation table and index without altering task data."""
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversation_user_id
                ON conversation_messages(user_id, id DESC)
            """)


def save_message(user_id, role, content):
    if role not in ("user", "assistant"):
        raise ValueError("Conversation role must be user or assistant.")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Conversation content cannot be empty.")
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO conversation_messages (user_id, role, content)
                   VALUES (%s, %s, %s)""",
                (str(user_id), role, content)
            )


def get_recent_history(user_id, limit=12):
    """Return the latest messages in chronological order for the OpenAI API."""
    limit = max(1, min(int(limit), 50))
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT role, content
                   FROM conversation_messages
                   WHERE user_id = %s
                   ORDER BY id DESC
                   LIMIT %s""",
                (str(user_id), limit)
            )
            rows = cursor.fetchall()
    return [
        {"role": row["role"], "content": row["content"]}
        for row in reversed(rows)
    ]


def clear_conversation(user_id):
    """Delete only this Telegram user's conversation transcript."""
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM conversation_messages WHERE user_id = %s",
                (str(user_id),)
            )
            return cursor.rowcount
