"""Long-term, user-scoped memory for GENERAL JARVIS (Neon/PostgreSQL)."""
import os
import re
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
    """Create memory storage without modifying conversation or task records."""
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS long_term_memories (
                    id BIGSERIAL PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_long_term_memories_user
                ON long_term_memories(user_id, updated_at DESC)
            """)


def save_memory(user_id, content, category="general"):
    content = " ".join(str(content).split()).strip()
    category = " ".join(str(category).split()).strip().lower() or "general"
    if not content:
        raise ValueError("Memory content cannot be empty.")
    if len(content) > 2000:
        raise ValueError("Memory must be 2,000 characters or fewer.")
    if len(category) > 40:
        raise ValueError("Category must be 40 characters or fewer.")
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO long_term_memories (user_id, category, content)
                VALUES (%s, %s, %s) RETURNING id
            """, (str(user_id), category, content))
            return cursor.fetchone()["id"]


def list_memories(user_id, limit=30):
    limit = max(1, min(int(limit), 100))
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id, category, content, created_at, updated_at
                FROM long_term_memories
                WHERE user_id = %s
                ORDER BY updated_at DESC, id DESC
                LIMIT %s
            """, (str(user_id), limit))
            return [dict(row) for row in cursor.fetchall()]


def delete_memory(user_id, memory_id):
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                DELETE FROM long_term_memories
                WHERE id = %s AND user_id = %s
            """, (int(memory_id), str(user_id)))
            return cursor.rowcount == 1


def get_relevant_memories(user_id, query, limit=8):
    """Rank a bounded set of this user's memories by simple token overlap."""
    query_tokens = set(re.findall(r"[a-z0-9_]{3,}", (query or "").lower()))
    rows = list_memories(user_id, limit=100)
    if not rows:
        return []
    if not query_tokens:
        return rows[:min(limit, len(rows))]
    scored = []
    for row in rows:
        content_tokens = set(re.findall(
            r"[a-z0-9_]{3,}",
            (row["category"] + " " + row["content"]).lower()
        ))
        overlap = len(query_tokens & content_tokens)
        if overlap:
            scored.append((overlap, row["updated_at"], row))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in scored[:limit]]
