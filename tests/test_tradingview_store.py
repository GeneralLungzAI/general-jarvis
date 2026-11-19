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


    def test_closed_bar_rejects_invalid_ohlc_before_database(self):
        event = dict(self.event, event_type="closed_bar", open=1.1, high=1.0, low=.9, close=1.05)
        with self.assertRaises(ValueError):
            save_event(event)

    def test_closed_bar_accepts_valid_ohlc_shape_before_database(self):
        event = dict(self.event, event_type="closed_bar", open=1.1, high=1.2, low=1.0, close=1.15)
        # Validation should pass; mock DB context to avoid a real connection.
        class Cursor:
            def execute(self, *args): pass
            def fetchone(self): return {"id": 1}
        class Connection:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def cursor(self): return self
        with patch("tradingview_store._connect") as connect:
            connect.return_value = Connection()
            result = save_event(event)
        self.assertTrue(result["stored"])

    def test_rejects_invalid_bar_time(self):
        event = dict(self.event, bar_time=0)
        with self.assertRaises(ValueError):
            save_event(event)


if __name__ == "__main__":
    unittest.main()
