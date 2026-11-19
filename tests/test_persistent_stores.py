import unittest
from contextlib import contextmanager
from unittest.mock import patch

import long_term_memory
import task_store


class FakeCursor:
    def __init__(self, rows=None, rowcount=1):
        self.rows = rows or []
        self.rowcount = rowcount
        self.last_query = ""
        self.last_params = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=None):
        self.last_query = query
        self.last_params = params

    def fetchone(self):
        return {"id": 41}

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class PersistentStoreTests(unittest.TestCase):
    def _fake_connect(self, cursor):
        connection = FakeConnection(cursor)

        @contextmanager
        def connect():
            yield connection

        return connect

    def test_task_add_is_user_scoped_and_returns_id(self):
        cursor = FakeCursor()
        with patch.object(task_store, "_connect", self._fake_connect(cursor)):
            task_id = task_store.add_task(12345, "Finish JARVIS")
        self.assertEqual(task_id, 41)
        self.assertIn("INSERT INTO tasks", cursor.last_query)
        self.assertEqual(cursor.last_params[0:2], ("12345", "Finish JARVIS"))

    def test_task_complete_is_user_scoped(self):
        cursor = FakeCursor(rowcount=1)
        with patch.object(task_store, "_connect", self._fake_connect(cursor)):
            self.assertTrue(task_store.complete_task(12345, 41))
        self.assertIn("user_id = %s", cursor.last_query)
        self.assertEqual(cursor.last_params[1:], (41, "12345"))

    def test_task_rejects_blank_title_before_database(self):
        with self.assertRaises(ValueError):
            task_store.add_task(12345, "   ")

    def test_memory_save_normalizes_content_and_category(self):
        cursor = FakeCursor()
        with patch.object(long_term_memory, "_connect", self._fake_connect(cursor)):
            memory_id = long_term_memory.save_memory(
                12345, "  Keep   H4 bias authoritative  ", " Trading "
            )
        self.assertEqual(memory_id, 41)
        self.assertEqual(
            cursor.last_params, ("12345", "trading", "Keep H4 bias authoritative")
        )

    def test_memory_delete_is_user_scoped(self):
        cursor = FakeCursor(rowcount=1)
        with patch.object(long_term_memory, "_connect", self._fake_connect(cursor)):
            self.assertTrue(long_term_memory.delete_memory(12345, 41))
        self.assertIn("user_id = %s", cursor.last_query)
        self.assertEqual(cursor.last_params, (41, "12345"))

    def test_memory_rejects_empty_content_before_database(self):
        with self.assertRaises(ValueError):
            long_term_memory.save_memory(12345, "   ")


if __name__ == "__main__":
    unittest.main()
