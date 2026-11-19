import unittest

from smc_engine import (
    Candle, EngineConfig, confirmed_swings, detect_structure_events,
    execution_consensus, StructureEvent,
)


class StructureEngineTests(unittest.TestCase):
    def test_rejects_invalid_ohlc(self):
        with self.assertRaises(ValueError):
            Candle(1, 1.2, 1.1, 1.0, 1.15).validate()

    def test_pivot_only_confirmed_after_right_bars(self):
        bars = [
            Candle(0, 1.0, 1.1, .9, 1.0),
            Candle(60, 1.0, 1.2, .95, 1.1),
            Candle(120, 1.1, 1.5, 1.0, 1.3),
            Candle(180, 1.3, 1.25, 1.0, 1.1),
            Candle(240, 1.1, 1.2, .98, 1.0),
        ]
        swings = confirmed_swings(bars, left=2, right=2)
        high = next(s for s in swings if s.kind == "high")
        self.assertEqual(high.index, 2)
        self.assertEqual(high.confirmed_at_index, 4)

    def test_incomplete_bar_never_emits_event(self):
        bars = []
        price = 1.0
        for i in range(40):
            bars.append(Candle(i * 60, price, price + .0005, price - .0005, price + .0001))
            price += .00002
        last = bars[-1]
        bars[-1] = Candle(last.timestamp, last.open, last.high, last.low, last.close, closed=False)
        events = detect_structure_events(
            bars, "M1",
            EngineConfig(pivot_left=2, pivot_right=2, atr_period=5),
        )
        self.assertTrue(all(e.candle_timestamp != bars[-1].timestamp for e in events))

    def test_consensus_fails_closed_without_h4_or_m5(self):
        event = StructureEvent(
            "M1", "bullish", "BOS", 1.1, 1000, 900, True,
            1.2, 1.3, .8, False, .4, True, (),
        )
        self.assertEqual(
            execution_consensus({"M1": [event]}, "bullish")["status"],
            "STAND_DOWN",
        )
        self.assertEqual(
            execution_consensus({"M1": [event], "M3": [event], "M5": [event]}, "neutral")["status"],
            "STAND_DOWN",
        )

    def test_consensus_requires_directional_support(self):
        m1 = StructureEvent("M1", "bullish", "MSS", 1.1, 1000, 900, True, 1.2, 1.3, .8, True, .4, True, ())
        m3 = StructureEvent("M3", "bullish", "BOS", 1.1, 1000, 900, True, 1.2, 1.3, .8, False, .4, True, ())
        m5 = StructureEvent("M5", "bearish", "BOS", 1.1, 1000, 900, True, 1.2, 1.3, .8, False, .4, True, ())
        result = execution_consensus({"M1": [m1], "M3": [m3], "M5": [m5]}, "bullish")
        self.assertEqual(result["status"], "STAND_DOWN")
        self.assertIn("m5", result["reason"])


if __name__ == "__main__":
    unittest.main()
