"""Post-mitigation EURUSD confirmation pipeline.

Consumes confirmed M1/M3/M5 bars, tracks POI lifecycle in Neon, and emits
one research-only confirmation candidate after H4-aligned LTF agreement.
Never places or modifies orders.
"""
import os
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor, Json

from smc_engine import Candle, EngineConfig, detect_structure_events

DATABASE_URL = os.environ.get("DATABASE_URL")
TIMEFRAMES = {"1": "M1", "3": "M3", "5": "M5"}
CONFIG = EngineConfig()


@contextmanager
def _connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured.")
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, connect_timeout=5)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize():
    """Idempotent schema migration; preserves all existing task and memory rows."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tradingview_ltf_bars (
                    id BIGSERIAL PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL CHECK (timeframe IN ('1','3','5')),
                    bar_time BIGINT NOT NULL,
                    open DOUBLE PRECISION NOT NULL,
                    high DOUBLE PRECISION NOT NULL,
                    low DOUBLE PRECISION NOT NULL,
                    close DOUBLE PRECISION NOT NULL,
                    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE(symbol, timeframe, bar_time),
                    CHECK (high >= GREATEST(open, close)),
                    CHECK (low <= LEAST(open, close)),
                    CHECK (high >= low)
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_tv_ltf_bars_lookup
                ON tradingview_ltf_bars(symbol, timeframe, bar_time DESC)
            """)
            cur.execute("""
                ALTER TABLE poi_candidates
                ADD COLUMN IF NOT EXISTS mitigated_at BIGINT,
                ADD COLUMN IF NOT EXISTS invalidated_at BIGINT,
                ADD COLUMN IF NOT EXISTS invalidation_reason TEXT,
                ADD COLUMN IF NOT EXISTS confirmation_at BIGINT,
                ADD COLUMN IF NOT EXISTS confirmation_payload JSONB
            """)


def _latest_events(candles, timeframe, prior_trend, start_index=0):
    if len(candles) < max(CONFIG.atr_period, CONFIG.pivot_left + CONFIG.pivot_right + 2):
        return []
    return detect_structure_events(
        candles, timeframe, config=CONFIG, prior_trend=prior_trend,
        start_index=start_index
    )


def process_closed_bar(event):
    """Persist LTF bars, advance POI lifecycle and return new notification(s)."""
    tf = event.get("timeframe")
    if event.get("event_type") != "closed_bar" or tf not in TIMEFRAMES:
        return []
    values = [float(event[k]) for k in ("open", "high", "low", "close")]
    if not all(map(lambda x: x == x and abs(x) != float("inf"), values)):
        raise ValueError("Non-finite LTF candle.")
    o, h, l, c = values
    if l > min(o, c) or h < max(o, c) or h < l:
        raise ValueError("Invalid LTF OHLC envelope.")

    notices = []
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tradingview_ltf_bars
                    (event_id, symbol, timeframe, bar_time, open, high, low, close)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
            """, (event["event_id"], "EURUSD", tf, event["bar_time"], o, h, l, c))

            cur.execute("""
                SELECT id, event_id, direction, h4_bias, bar_time,
                       ob_high, ob_low, imb_high, imb_low, status, mitigated_at
                FROM poi_candidates
                WHERE symbol = 'EURUSD' AND timeframe = '15'
                  AND status IN ('active','mitigated')
                ORDER BY created_at DESC
                LIMIT 1
                FOR UPDATE
            """)
            poi = cur.fetchone()
            if not poi or event["bar_time"] <= poi["bar_time"]:
                return notices

            direction = poi["direction"]
            incoming_h4 = event.get("h4_bias")
            h4_reversed = incoming_h4 in ("bullish", "bearish") and incoming_h4 != poi["h4_bias"]
            price_invalidated = (direction == "bullish" and c < poi["ob_low"]) or (
                direction == "bearish" and c > poi["ob_high"]
            )
            if h4_reversed or price_invalidated:
                reason = "h4_bias_changed" if h4_reversed else "closed_bar_beyond_ob_boundary"
                cur.execute("""
                    UPDATE poi_candidates
                    SET status='invalidated', invalidated_at=%s,
                        invalidation_reason=%s, updated_at=NOW()
                    WHERE id=%s AND status IN ('active','mitigated')
                """, (event["bar_time"], reason, poi["id"]))
                notices.append({
                    "type": "invalidated", "poi_id": poi["id"],
                    "direction": direction, "close": c, "reason": reason
                })
                return notices

            overlaps_ob = l <= poi["ob_high"] and h >= poi["ob_low"]
            overlaps_imb = l <= poi["imb_high"] and h >= poi["imb_low"]
            if poi["status"] == "active" and (overlaps_ob or overlaps_imb):
                cur.execute("""
                    UPDATE poi_candidates
                    SET status='mitigated', mitigated_at=%s, updated_at=NOW()
                    WHERE id=%s AND status='active'
                """, (event["bar_time"], poi["id"]))
                poi["status"] = "mitigated"
                poi["mitigated_at"] = event["bar_time"]
                notices.append({
                    "type": "mitigated", "poi_id": poi["id"],
                    "direction": direction, "h4_bias": poi["h4_bias"],
                    "bar_time": event["bar_time"]
                })

            if poi["status"] != "mitigated" or not poi["mitigated_at"]:
                return notices

            # Include pre-mitigation candles to establish confirmed swing context,
            # but only accept structure events whose candle closes at/after mitigation.
            # A fixed bounded history keeps the per-webhook computation predictable.
            cur.execute("""
                WITH ranked AS (
                    SELECT timeframe, bar_time, open, high, low, close,
                           ROW_NUMBER() OVER (
                               PARTITION BY timeframe ORDER BY bar_time DESC
                           ) AS rn
                    FROM tradingview_ltf_bars
                    WHERE symbol='EURUSD' AND timeframe IN ('1','3','5')
                      AND bar_time <= %s
                )
                SELECT timeframe, bar_time, open, high, low, close
                FROM ranked
                WHERE rn <= 500
                ORDER BY timeframe, bar_time ASC
            """, (event["bar_time"],))
            rows = cur.fetchall()
            by_tf = {"M1": [], "M3": [], "M5": []}
            for row in rows:
                by_tf[TIMEFRAMES[row["timeframe"]]].append(Candle(
                    timestamp=int(row["bar_time"]),
                    open=float(row["open"]), high=float(row["high"]),
                    low=float(row["low"]), close=float(row["close"]), closed=True
                ))

            prior_m1 = "bearish" if direction == "bullish" else "bullish"
            def latest(items):
                return max(items, key=lambda x: x.candle_timestamp) if items else None

            # Establish the M1 trend from the latest structural break BEFORE
            # mitigation. If no prior trend can be established, fail closed:
            # do not manufacture an MSS from an unknown state.
            m1_context_events = _latest_events(by_tf["M1"], "M1", "unknown")
            pre_mitigation = [
                item for item in m1_context_events
                if item.candle_timestamp < poi["mitigated_at"]
            ]
            established_m1_trend = latest(pre_mitigation).direction if pre_mitigation else None
            m1_start = next((i for i, bar in enumerate(by_tf["M1"])
                             if bar.timestamp >= poi["mitigated_at"]), len(by_tf["M1"]))
            m3_start = next((i for i, bar in enumerate(by_tf["M3"])
                             if bar.timestamp >= poi["mitigated_at"]), len(by_tf["M3"]))
            m5_start = next((i for i, bar in enumerate(by_tf["M5"])
                             if bar.timestamp >= poi["mitigated_at"]), len(by_tf["M5"]))
            events_m1 = (
                _latest_events(by_tf["M1"], "M1", established_m1_trend, m1_start)
                if established_m1_trend in ("bullish", "bearish") else []
            )
            events_m3 = _latest_events(by_tf["M3"], "M3", direction, m3_start)
            events_m5 = _latest_events(by_tf["M5"], "M5", direction, m5_start)

            # Only events closing after mitigation count toward confirmation.
            post_mit_m1 = [item for item in events_m1 if item.candle_timestamp >= poi["mitigated_at"]]
            post_mit_m3 = [item for item in events_m3 if item.candle_timestamp >= poi["mitigated_at"]]
            post_mit_m5 = [item for item in events_m5 if item.candle_timestamp >= poi["mitigated_at"]]
            m1_candidates = [
                item for item in post_mit_m1
                if item.event == "MSS" and item.eligible and item.direction == direction
            ]
            m1 = latest(m1_candidates)
            m1_latest_any = latest(post_mit_m1)
            m3 = latest(post_mit_m3)
            m5 = latest(post_mit_m5)
            if not m1 or (m1_latest_any and m1_latest_any.direction != direction and
                          m1_latest_any.candle_timestamp > m1.candle_timestamp):
                return notices
            if not m3 or not m3.eligible or m3.direction != direction:
                return notices
            if not m5 or not m5.eligible or m5.direction != direction:
                return notices

            confirmation = {
                "status": "CONFIRMATION_CANDIDATE",
                "direction": direction,
                "h4_bias": poi["h4_bias"],
                "poi_id": poi["id"],
                "mitigated_at": poi["mitigated_at"],
                "m1_mss": m1.to_dict(),
                "m3_support": m3.to_dict(),
                "m5_support": m5.to_dict(),
                "warning": "Research/alert candidate only. Manual decision required; no order was placed."
            }
            cur.execute("""
                UPDATE poi_candidates
                SET confirmation_at=%s, confirmation_payload=%s, updated_at=NOW()
                WHERE id=%s AND confirmation_at IS NULL
                RETURNING id
            """, (m1.candle_timestamp, Json(confirmation), poi["id"]))
            if cur.fetchone():
                notices.append({"type": "confirmation", **confirmation})
    return notices
