"""Durable inbox for authenticated TradingView webhook events.

Events are stored for audit/replay only. This module never creates orders.
"""
import json
import os
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor, Json

DATABASE_URL = os.environ.get("DATABASE_URL")


@contextmanager
def _connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured.")
    connection = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, connect_timeout=2)
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
                CREATE TABLE IF NOT EXISTS tradingview_events (
                    id BIGSERIAL PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    bar_time BIGINT NOT NULL,
                    payload JSONB NOT NULL,
                    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tradingview_events_received
                ON tradingview_events(received_at DESC)
            """)


def save_event(event):
    required = ("event_id", "symbol", "timeframe", "event_type", "bar_time")
    if not isinstance(event, dict) or any(k not in event for k in required):
        raise ValueError("Missing required TradingView event fields.")
    if not all(isinstance(event[k], str) and event[k].strip() for k in
               ("event_id", "symbol", "timeframe", "event_type")):
        raise ValueError("Text event fields must be non-empty strings.")
    if event["timeframe"] not in ("1", "3", "5", "15", "60", "240"):
        raise ValueError("Unsupported timeframe.")
    if event["symbol"].upper().replace("/", "") != "EURUSD":
        raise ValueError("Only EURUSD events are accepted in this build.")
    if type(event["bar_time"]) is not int or event["bar_time"] <= 0:
        raise ValueError("bar_time must be a positive Unix timestamp.")
    if len(event["event_id"]) > 128:
        raise ValueError("event_id is too long.")
    if len(json.dumps(event)) > 12000:
        raise ValueError("TradingView payload is too large.")
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO tradingview_events
                    (event_id, symbol, timeframe, event_type, bar_time, payload)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_id) DO NOTHING
                RETURNING id
            """, (
                str(event["event_id"]), str(event["symbol"]).upper(),
                str(event["timeframe"]), str(event["event_type"]),
                event["bar_time"], Json(event)
            ))
            row = cursor.fetchone()
            return {"stored": row is not None, "duplicate": row is None,
                    "id": row["id"] if row else None}
