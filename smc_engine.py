"""Deterministic, non-repainting SMC primitives for closed-bar OHLC data.

This module is research scaffolding, not a live signal service. Thresholds are
explicit configuration and must be calibrated on broker-specific EURUSD data
before any signal can be promoted to production.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable, Optional, Sequence
import math


@dataclass(frozen=True)
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    closed: bool = True

    def validate(self) -> None:
        values = (self.open, self.high, self.low, self.close)
        if not all(math.isfinite(v) for v in values):
            raise ValueError("OHLC values must be finite")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("OHLC envelope is invalid")
        if self.high < self.low:
            raise ValueError("high must be >= low")


@dataclass(frozen=True)
class EngineConfig:
    pivot_left: int = 2
    pivot_right: int = 2
    atr_period: int = 14
    min_body_atr: float = 0.8
    min_range_atr: float = 1.0
    min_close_location: float = 0.70
    max_extension_atr: float = 2.5
    # Experimental defaults only; require calibration before production.
    def validate(self) -> None:
        if self.pivot_left < 1 or self.pivot_right < 1:
            raise ValueError("pivot windows must be >= 1")
        if self.atr_period < 2:
            raise ValueError("atr_period must be >= 2")
        if self.min_body_atr <= 0 or self.min_range_atr <= 0:
            raise ValueError("displacement thresholds must be positive")
        if not 0.5 <= self.min_close_location <= 1.0:
            raise ValueError("min_close_location must be in [0.5, 1]")
        if self.max_extension_atr <= 0:
            raise ValueError("max_extension_atr must be positive")


@dataclass(frozen=True)
class Swing:
    index: int
    timestamp: int
    price: float
    kind: str  # "high" or "low"
    confirmed_at_index: int


@dataclass(frozen=True)
class StructureEvent:
    timeframe: str
    direction: str
    event: str  # BOS / MSS
    broken_level: float
    candle_timestamp: int
    swing_timestamp: int
    displacement: bool
    body_atr: float
    range_atr: float
    close_location: float
    fvg_confirmed: bool
    extension_atr: float
    eligible: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def _true_ranges(candles: Sequence[Candle]) -> list[float]:
    out = []
    previous_close = None
    for c in candles:
        tr = c.high - c.low
        if previous_close is not None:
            tr = max(tr, abs(c.high - previous_close), abs(c.low - previous_close))
        out.append(tr)
        previous_close = c.close
    return out


def _atr_at(candles: Sequence[Candle], index: int, period: int) -> Optional[float]:
    # Simple rolling ATR over fully closed bars ending at index.
    start = index - period + 1
    if start < 0:
        return None
    trs = _true_ranges(candles[:index + 1])[start:index + 1]
    return sum(trs) / period if len(trs) == period else None


def confirmed_swings(candles: Sequence[Candle], left: int = 2, right: int = 2) -> list[Swing]:
    """Return pivots only at the bar where their right-hand confirmation exists.

    Equal-high/low plateaus are rejected to avoid ambiguous duplicate levels.
    """
    if left < 1 or right < 1:
        raise ValueError("left and right must be >= 1")
    for c in candles:
        c.validate()
    swings: list[Swing] = []
    for i in range(left, len(candles) - right):
        window = candles[i-left:i+right+1]
        # A pivot is not confirmed if any right-hand confirmation candle is live.
        if not all(c.closed for c in window):
            continue
        current = candles[i]
        highs = [x.high for j, x in enumerate(window) if j != left]
        lows = [x.low for j, x in enumerate(window) if j != left]
        if current.high > max(highs):
            swings.append(Swing(i, current.timestamp, current.high, "high", i + right))
        if current.low < min(lows):
            swings.append(Swing(i, current.timestamp, current.low, "low", i + right))
    return swings


def _fvg(candles: Sequence[Candle], index: int, direction: str) -> bool:
    # Three-candle imbalance; only evaluate after the middle and current bars close.
    if index < 2:
        return False
    a, _, c = candles[index - 2:index + 1]
    return c.low > a.high if direction == "bullish" else c.high < a.low


def detect_structure_events(
    candles: Iterable[Candle],
    timeframe: str,
    config: EngineConfig = EngineConfig(),
    prior_trend: str = "unknown",
) -> list[StructureEvent]:
    """Detect close-confirmed breaks of the latest confirmed opposite swing.

    prior_trend is "bullish", "bearish", or "unknown". First break against an
    established trend is MSS; continuation break is BOS. Unknown trend is
    labelled BOS-neutral rather than guessing an MSS.
    """
    config.validate()
    if timeframe not in ("M1", "M3", "M5", "M15", "H1", "H4"):
        raise ValueError("unsupported timeframe")
    bars = list(candles)
    if len(bars) < max(config.atr_period, config.pivot_left + config.pivot_right + 2):
        return []
    for i, c in enumerate(bars):
        c.validate()
        if i and c.timestamp <= bars[i - 1].timestamp:
            raise ValueError("candles must be strictly time-ordered")
    swings = confirmed_swings(bars, config.pivot_left, config.pivot_right)
    events: list[StructureEvent] = []
    consumed: set[tuple[str, int]] = set()
    trend = prior_trend if prior_trend in ("bullish", "bearish") else "unknown"

    for i, c in enumerate(bars):
        if not c.closed:
            continue
        atr = _atr_at(bars, i, config.atr_period)
        if atr is None or atr <= 0:
            continue
        available = [s for s in swings if s.confirmed_at_index < i]
        for direction, kind, breached in (
            ("bullish", "high", c.close),
            ("bearish", "low", c.close),
        ):
            candidates = [s for s in available if s.kind == kind and (kind, s.index) not in consumed]
            if not candidates:
                continue
            swing = candidates[-1]
            crossed = c.close > swing.price if direction == "bullish" else c.close < swing.price
            if not crossed:
                continue
            body = abs(c.close - c.open)
            candle_range = c.high - c.low
            body_atr = body / atr
            range_atr = candle_range / atr
            close_location = ((c.close - c.low) / candle_range) if candle_range else 0.5
            if direction == "bearish":
                close_location = 1.0 - close_location
            fvg = _fvg(bars, i, direction)
            extension = abs(c.close - swing.price) / atr
            reasons = []
            if body_atr < config.min_body_atr:
                reasons.append("body_below_threshold")
            if range_atr < config.min_range_atr:
                reasons.append("range_below_threshold")
            if close_location < config.min_close_location:
                reasons.append("weak_close_location")
            if extension > config.max_extension_atr:
                reasons.append("overextended")
            displacement = not any(r in reasons for r in (
                "body_below_threshold", "range_below_threshold", "weak_close_location"
            ))
            event = ("MSS" if trend != direction else "BOS") if trend in ("bullish", "bearish") else "BREAK"
            eligible = displacement and extension <= config.max_extension_atr
            events.append(StructureEvent(
                timeframe=timeframe, direction=direction, event=event,
                broken_level=swing.price, candle_timestamp=c.timestamp,
                swing_timestamp=swing.timestamp, displacement=displacement,
                body_atr=round(body_atr, 4), range_atr=round(range_atr, 4),
                close_location=round(close_location, 4), fvg_confirmed=fvg,
                extension_atr=round(extension, 4), eligible=eligible,
                reasons=tuple(reasons),
            ))
            consumed.add((kind, swing.index))
            trend = direction
    return events


def execution_consensus(
    events_by_tf: dict[str, Sequence[StructureEvent]],
    h4_bias: str,
    require_m5: bool = True,
    require_m3: bool = True,
) -> dict:
    """M1 trigger with M3/M5 directional support; H4 remains authoritative.

    No candle simultaneity is assumed. Inputs must be latest still-valid events;
    event freshness/expiry is deliberately owned by the caller and must be
    based on timestamps, not list position.
    """
    if h4_bias not in ("bullish", "bearish"):
        return {"status": "STAND_DOWN", "reason": "h4_bias_missing_or_neutral"}
    m1 = list(events_by_tf.get("M1", ()))
    m3 = list(events_by_tf.get("M3", ()))
    m5 = list(events_by_tf.get("M5", ()))
    if not m1:
        return {"status": "STAND_DOWN", "reason": "m1_trigger_missing"}
    # Do not rely on input ordering: choose the most recent timestamp per TF.
    trigger = max(m1, key=lambda event: event.candle_timestamp)
    if trigger.event != "MSS":
        return {"status": "STAND_DOWN", "reason": "m1_mss_not_confirmed"}
    if trigger.direction != h4_bias:
        return {"status": "STAND_DOWN", "reason": "m1_conflicts_with_h4"}
    if not trigger.eligible:
        return {"status": "STAND_DOWN", "reason": "m1_break_not_displacement_eligible"}
    for tf, events, required in (("M3", m3, require_m3), ("M5", m5, require_m5)):
        if not required:
            continue
        if not events:
            return {"status": "STAND_DOWN", "reason": f"{tf.lower()}_confirmation_missing"}
        latest = max(events, key=lambda event: event.candle_timestamp)
        if latest.direction != h4_bias or not latest.eligible:
            return {"status": "STAND_DOWN", "reason": f"{tf.lower()}_conflicts_or_is_not_eligible"}
    return {
        "status": "CONFIRMATION_CANDIDATE",
        "direction": h4_bias,
        "trigger_time": trigger.candle_timestamp,
        "reason": "m1_mss_and_displacement_with_required_m3_m5_support_and_h4_alignment",
        "warning": "Research candidate only; caller must still validate event age, H4 structure, M15 POI/liquidity, session/news rules, and calibrated thresholds.",
    }
