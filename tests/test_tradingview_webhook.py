import os
import unittest
from unittest.mock import patch

import bot


class TradingViewWebhookTests(unittest.TestCase):
    def setUp(self):
        self.client = bot.app.test_client()
        self.worker_patch = patch.object(bot, "_ensure_telegram_worker_started")
        self.worker_patch.start()
        self.env_patch = patch.dict(os.environ, {"TRADINGVIEW_WEBHOOK_SECRET": "test-secret"})
        self.env_patch.start()
        self.event = {
            "secret": "test-secret",
            "event_id": "tv-test-1",
            "symbol": "EURUSD",
            "timeframe": "1",
            "event_type": "structure_candidate",
            "bar_time": 1795000000,
        }

    def tearDown(self):
        self.env_patch.stop()
        self.worker_patch.stop()

    def test_missing_secret_disables_endpoint(self):
        with patch.dict(os.environ, {}, clear=True):
            response = self.client.post("/tradingview/webhook", json=self.event)
        self.assertEqual(response.status_code, 503)

    def test_invalid_secret_is_rejected(self):
        event = dict(self.event, secret="wrong")
        response = self.client.post("/tradingview/webhook", json=event)
        self.assertEqual(response.status_code, 403)

    def test_valid_event_is_stored(self):
        with patch.object(bot, "save_tradingview_event", return_value={
            "stored": True, "duplicate": False, "id": 7
        }) as save:
            response = self.client.post("/tradingview/webhook", json=self.event)
        self.assertEqual(response.status_code, 200)
        save.assert_called_once()
        self.assertNotIn("secret", save.call_args.args[0])

    def test_duplicate_event_is_idempotent(self):
        with patch.object(bot, "save_tradingview_event", return_value={
            "stored": False, "duplicate": True, "id": None
        }):
            response = self.client.post("/tradingview/webhook", json=self.event)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["duplicate"])


if __name__ == "__main__":
    unittest.main()
