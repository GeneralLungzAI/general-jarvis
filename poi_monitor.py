"""POI mitigation and LTF-watch state transitions for JARVIS.

A zone must be supplied by a trusted, authenticated TradingView context event.
This module does not invent OB/IMB zones and never creates or routes orders.
"""
from dataclasses import dataclass
from typing import Optional

from smc_engine import Candle, StructureEvent


@dataclass(frozen=True)
class PriceZone:
    zone_id: str
    symbol: str
    direction: str
    low: float
    high: float
    source_timeframe: str
    created_at: int

    def validate(self) -> None:
        if not self.zone_id or len(self.zone_id) > 128:
            raise ValueError("zone_id must contain 1-128 characters")
        if self.symbol.upper().replace("/", "") != "EURUSD":
            raise ValueError("only EURUSD POIs are supported")
        if self.direction not in ("bullish", "bearish"):
            raise ValueError("POI direction must be bullish or bearish")
        if self.low <= 0 or self.high <= self.low:
            raise ValueError("POI bounds are invalid")
        if self.source_timeframe not in ("M15", "H1", "H4"):
            raise ValueError("POI source timeframe must be M15, H1 or H4")
        if self.created_at <= 0:
            raise ValueError("created_at must be a positive Unix timestamp")


def detect_poi_mitigation(zone: PriceZone, candle: Candle) -> Optional[dict]:
    """Return one mitigation event when a confirmed candle first overlaps a zone."""
    zone.validate()
    candle.validate()
    if not candle.closed:
        return None
    if candle.timestamp < zone.created_at:
        return None
    overlaps = candle.low <= zone.high and candle.high >= zone.low
    if not overlaps:
        return None
    return {
        "event": "POI_MITIGATED",
        "zone_id": zone.zone_id,
        "direction": zone.direction,
        "source_timeframe": zone.source_timeframe,
        "mitigation_time": candle.timestamp,
        "candle_low": candle.low,
        "candle_high": candle.high,
        "instruction": "Begin monitoring closed-bar LTF confirmation; mitigation is not an entry.",
    }


def ltf_watch_status(
    h4_bias: str,
    m1_events: list[StructureEvent],
    m3_events: list[StructureEvent],
    m5_events: list[StructureEvent],
) -> dict:
    """Fail-closed LTF watch: M1 MSS+displacement, with M3/M5 support."""
    if h4_bias not in ("bullish", "bearish"):
        return {"status": "STAND_DOWN", "reason": "h4_bias_missing_or_neutral"}
    if not m1_events:
        return {"status": "WATCHING", "reason": "waiting_for_m1_mss"}
    trigger = max(m1_events, key=lambda e: e.candle_timestamp)
    if trigger.event != "MSS":
        return {"status": "WATCHING", "reason": "waiting_for_m1_mss"}
    if trigger.direction != h4_bias:
        return {"status": "STAND_DOWN", "reason": "m1_mss_conflicts_with_h4"}
    if not trigger.eligible or not trigger.displacement:
        return {"status": "WATCHING", "reason": "waiting_for_m1_displacement"}
    for tf, events in (("M3", m3_events), ("M5", m5_events)):
        if not events:
            return {"status": "WATCHING", "reason": f"waiting_for_{tf.lower()}_support"}
        latest = max(events, key=lambda e: e.candle_timestamp)
        if latest.direction != h4_bias or not latest.eligible:
            return {"status": "STAND_DOWN", "reason": f"{tf.lower()}_conflict_or_invalid"}
    return {
        "status": "LTF_CONFIRMATION_CANDIDATE",
        "direction": h4_bias,
        "trigger_time": trigger.candle_timestamp,
        "reason": "closed_bar_m1_mss_displacement_with_m3_m5_support_and_h4_alignment",
        "warning": "Candidate only. Revalidate POI, liquidity, event freshness, session/news and calibrated thresholds.",
    }
