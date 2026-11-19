"""Durable inbox for authenticated TradingView webhook events.

Events are stored for audit/replay only. This module never creates orders.
"""
import json
import os
import math
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
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS poi_candidates (
                    id BIGSERIAL PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE REFERENCES tradingview_events(event_id) ON DELETE CASCADE,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    direction TEXT NOT NULL CHECK (direction IN ('bullish', 'bearish')),
                    h4_bias TEXT NOT NULL,
                    bar_time BIGINT NOT NULL,
                    ob_high DOUBLE PRECISION NOT NULL,
                    ob_low DOUBLE PRECISION NOT NULL,
                    imb_high DOUBLE PRECISION NOT NULL,
                    imb_low DOUBLE PRECISION NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'mitigated', 'invalidated', 'expired')),
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CHECK (ob_high > ob_low),
                    CHECK (imb_high > imb_low)
                )
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_poi_candidates_status_created
                ON poi_candidates(status, created_at DESC)
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
    if event["event_type"] not in ("closed_bar", "structure_candidate", "displacement_candidate", "context_update"):
        raise ValueError("Unsupported event_type.")
    if event["event_type"] == "closed_bar":
        try:
            prices = {key: float(event[key]) for key in ("open", "high", "low", "close")}
        except (KeyError, TypeError, ValueError):
            raise ValueError("closed_bar requires numeric OHLC fields.")
        if not all(math.isfinite(value) for value in prices.values()):
            raise ValueError("OHLC values must be finite.")
        if prices["low"] > min(prices["open"], prices["close"]) or prices["high"] < max(prices["open"], prices["close"]) or prices["high"] < prices["low"]:
            raise ValueError("OHLC envelope is invalid.")
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
            event_stored = row is not None
            poi_id = None
            if event_stored and event.get("poi_candidate") is True:
                if event.get("timeframe") != "15":
                    raise ValueError("POI candidates are accepted only from M15 events.")
                direction = event.get("poi_direction")
                h4_bias = event.get("h4_bias")
                try:
                    ob_high = float(event["ob_high"])
                    ob_low = float(event["ob_low"])
                    imb_high = float(event["imb_high"])
                    imb_low = float(event["imb_low"])
                except (KeyError, TypeError, ValueError):
                    raise ValueError("POI candidate requires numeric OB and IMB boundaries.")
                if direction not in ("bullish", "bearish") or h4_bias != direction:
                    raise ValueError("POI direction must agree with confirmed H4 bias.")
                if not all(math.isfinite(v) for v in (ob_high, ob_low, imb_high, imb_low)):
                    raise ValueError("POI price boundaries must be finite.")
                if ob_high <= ob_low or imb_high <= imb_low:
                    raise ValueError("POI zone boundaries are inverted or empty.")
                cursor.execute("""
                    INSERT INTO poi_candidates
                        (event_id, symbol, timeframe, direction, h4_bias, bar_time,
                         ob_high, ob_low, imb_high, imb_low, payload)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (event_id) DO NOTHING
                    RETURNING id
                """, (
                    str(event["event_id"]), str(event["symbol"]).upper(),
                    str(event["timeframe"]), direction, h4_bias, event["bar_time"],
                    ob_high, ob_low, imb_high, imb_low, Json(event)
                ))
                poi_row = cursor.fetchone()
                poi_id = poi_row["id"] if poi_row else None
            return {"stored": event_stored, "duplicate": not event_stored,
                    "id": row["id"] if row else None, "poi_id": poi_id}


def list_poi_candidates(status="active", limit=20):
    """Read recent qualified M15 POI zones without exposing raw credentials."""
    allowed = ("active", "mitigated", "invalidated", "expired")
    if status not in allowed:
        raise ValueError("Unsupported POI status.")
    limit = max(1, min(int(limit), 100))
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id, event_id, symbol, timeframe, direction, h4_bias,
                       bar_time, ob_high, ob_low, imb_high, imb_low,
                       status, created_at, updated_at
                FROM poi_candidates
                WHERE status = %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (status, limit))
            return [dict(row) for row in cursor.fetchall()]
