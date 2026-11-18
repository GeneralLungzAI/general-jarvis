import os
import unittest
import uuid

import psycopg2

import memory_store


@unittest.skipUnless(os.environ.get("DATABASE_URL"), "DATABASE_URL is required")
class MemoryPostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        memory_store.initialize()

    def setUp(self):
        self.user_id = f"memory-test-{uuid.uuid4()}"
        self.other_user_id = f"memory-test-other-{uuid.uuid4()}"

    def tearDown(self):
        connection = psycopg2.connect(os.environ["DATABASE_URL"])
        try:
            with connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM memories WHERE user_id IN (%s, %s)",
                        (self.user_id, self.other_user_id),
                    )
        finally:
            connection.close()

    def test_create_list_search_update_and_delete(self):
        memory_id = memory_store.add_memory(
            self.user_id, "trading", "EURUSD H4 bias controls directional trades"
        )

        listed = memory_store.list_memories(self.user_id, "trading")
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["id"], memory_id)

        found = memory_store.search_memories(self.user_id, "EURUSD directional")
        self.assertEqual([item["id"] for item in found], [memory_id])

        self.assertTrue(
            memory_store.update_memory(
                self.user_id, memory_id, "EURUSD H4 structure controls bias"
            )
        )
        updated = memory_store.list_memories(self.user_id, "trading")
        self.assertEqual(updated[0]["content"], "EURUSD H4 structure controls bias")

        self.assertTrue(memory_store.delete_memory(self.user_id, memory_id))
        self.assertEqual(memory_store.list_memories(self.user_id), [])

    def test_users_cannot_read_or_change_each_others_memories(self):
        memory_id = memory_store.add_memory(
            self.user_id, "personal", "Private test memory"
        )

        self.assertEqual(memory_store.list_memories(self.other_user_id), [])
        self.assertEqual(memory_store.search_memories(self.other_user_id, "Private"), [])
        self.assertFalse(
            memory_store.update_memory(
                self.other_user_id, memory_id, "Unauthorized change"
            )
        )
        self.assertFalse(memory_store.delete_memory(self.other_user_id, memory_id))
        self.assertEqual(len(memory_store.list_memories(self.user_id)), 1)

    def test_initialize_is_safe_to_run_more_than_once(self):
        memory_store.initialize()
        memory_store.initialize()
        self.assertEqual(memory_store.list_memories(self.user_id), [])


if __name__ == "__main__":
    unittest.main()
