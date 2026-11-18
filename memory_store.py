import os
from contextlib import contextmanager
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL")

VALID_CATEGORIES = {"personal", "business", "trading"}


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
    """Create the memory table without modifying the existing tasks table."""
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    category TEXT NOT NULL
                        CHECK (category IN ('personal', 'business', 'trading')),
                    content TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'telegram_command',
                    importance SMALLINT NOT NULL DEFAULT 3
                        CHECK (importance BETWEEN 1 AND 5),
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_user_category_created
                ON memories(user_id, category, created_at DESC, id DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_memories_content_search
                ON memories USING GIN (to_tsvector('english', content))
            """)


def add_memory(user_id, category, content, importance=3):
    category = category.strip().lower()
    content = content.strip()
    if category not in VALID_CATEGORIES:
        raise ValueError("Category must be personal, business, or trading.")
    if not content:
        raise ValueError("Memory content cannot be empty.")
    if len(content) > 2000:
        raise ValueError("Memory content must be 2000 characters or fewer.")
    if not isinstance(importance, int) or not 1 <= importance <= 5:
        raise ValueError("Importance must be a number from 1 to 5.")

    now = datetime.now(timezone.utc)
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO memories
                   (user_id, category, content, source, importance, created_at, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   RETURNING id""",
                (str(user_id), category, content, "telegram_command", importance, now, now)
            )
            return cursor.fetchone()["id"]


def list_memories(user_id, category=None, limit=30):
    if category is not None:
        category = category.strip().lower()
        if category not in VALID_CATEGORIES:
            raise ValueError("Category must be personal, business, or trading.")

    with _connect() as connection:
        with connection.cursor() as cursor:
            if category:
                cursor.execute(
                    """SELECT id, category, content, importance, created_at, updated_at
                       FROM memories
                       WHERE user_id = %s AND category = %s
                       ORDER BY importance DESC, updated_at DESC, id DESC
                       LIMIT %s""",
                    (str(user_id), category, limit)
                )
            else:
                cursor.execute(
                    """SELECT id, category, content, importance, created_at, updated_at
                       FROM memories
                       WHERE user_id = %s
                       ORDER BY importance DESC, updated_at DESC, id DESC
                       LIMIT %s""",
                    (str(user_id), limit)
                )
            return [dict(row) for row in cursor.fetchall()]


def search_memories(user_id, query, limit=8):
    query = query.strip()
    if not query:
        return []

    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT id, category, content, importance
                   FROM memories
                   WHERE user_id = %s
                     AND to_tsvector('english', content)
                         @@ plainto_tsquery('english', %s)
                   ORDER BY ts_rank(
                       to_tsvector('english', content),
                       plainto_tsquery('english', %s)
                   ) DESC, importance DESC, updated_at DESC
                   LIMIT %s""",
                (str(user_id), query, query, limit)
            )
            return [dict(row) for row in cursor.fetchall()]


def update_memory(user_id, memory_id, content):
    content = content.strip()
    if not content:
        raise ValueError("Memory content cannot be empty.")
    if len(content) > 2000:
        raise ValueError("Memory content must be 2000 characters or fewer.")

    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """UPDATE memories
                   SET content = %s, updated_at = %s
                   WHERE id = %s AND user_id = %s""",
                (content, datetime.now(timezone.utc), memory_id, str(user_id))
            )
            return cursor.rowcount == 1


def delete_memory(user_id, memory_id):
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM memories WHERE id = %s AND user_id = %s",
                (memory_id, str(user_id))
            )
            return cursor.rowcount == 1
