import unittest
from contextlib import contextmanager
from unittest.mock import patch

import tradingview_store


class QueueCursor:
    def __init__(self):
        self.query = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=None):
        self.query = query
        self.params = params

    def fetchall(self):
        return []


class QueueConnection:
    def __init__(self, cursor):
        self.cursor_value = cursor

    def cursor(self):
        return self.cursor_value


class TradingViewQueueTests(unittest.TestCase):
    def _patched_connect(self, cursor):
        connection = QueueConnection(cursor)

        @contextmanager
        def connect():
            yield connection

        return connect

    def test_event_queue_uses_valid_postgres_locking_clause_order(self):
        cursor = QueueCursor()
        with patch.object(tradingview_store, "_connect", self._patched_connect(cursor)):
            self.assertEqual(tradingview_store.claim_pending_events(), [])
        self.assertIn("LIMIT %s\n                    FOR UPDATE SKIP LOCKED", cursor.query)
        self.assertEqual(cursor.params, (10,))

    def test_notification_queue_uses_valid_postgres_locking_clause_order(self):
        cursor = QueueCursor()
        with patch.object(tradingview_store, "_connect", self._patched_connect(cursor)):
            self.assertEqual(tradingview_store.claim_pending_notifications(), [])
        self.assertIn("LIMIT %s\n                    FOR UPDATE SKIP LOCKED", cursor.query)
        self.assertEqual(cursor.params, (10,))


if __name__ == "__main__":
    unittest.main()
