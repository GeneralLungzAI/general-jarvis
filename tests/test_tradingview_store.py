import unittest
from unittest.mock import patch
from tradingview_store import save_event


class TradingViewValidationTests(unittest.TestCase):
    def setUp(self):
        self.event = {
            "event_id": "tv-001", "symbol": "EURUSD", "timeframe": "1",
            "event_type": "structure_candidate", "bar_time": 1795000000,
        }

    def test_rejects_wrong_symbol_before_database(self):
        event = dict(self.event, symbol="XAUUSD")
        with self.assertRaises(ValueError):
            save_event(event)

    def test_rejects_unsupported_timeframe(self):
        event = dict(self.event, timeframe="2")
        with self.assertRaises(ValueError):
            save_event(event)

    def test_rejects_missing_event_id(self):
        event = dict(self.event)
        del event["event_id"]
        with self.assertRaises(ValueError):
            save_event(event)

    def test_rejects_invalid_bar_time(self):
        event = dict(self.event, bar_time=0)
        with self.assertRaises(ValueError):
            save_event(event)


if __name__ == "__main__":
    unittest.main()
