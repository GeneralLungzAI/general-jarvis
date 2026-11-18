import unittest

from memory_store import (
    add_memory,
    list_memories,
    search_memories,
    update_memory,
)


class MemoryValidationTests(unittest.TestCase):
    def test_invalid_category_is_rejected_before_database_access(self):
        with self.assertRaisesRegex(ValueError, "Category must be"):
            add_memory(123, "finance", "A test memory")

    def test_empty_content_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            add_memory(123, "personal", "   ")

    def test_content_over_limit_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "2000 characters"):
            add_memory(123, "business", "x" * 2001)

    def test_importance_outside_range_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "1 to 5"):
            add_memory(123, "trading", "A test memory", importance=6)

    def test_invalid_list_category_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Category must be"):
            list_memories(123, "other")

    def test_empty_search_returns_no_memories_without_database_access(self):
        self.assertEqual(search_memories(123, "   "), [])

    def test_empty_update_is_rejected_before_database_access(self):
        with self.assertRaisesRegex(ValueError, "cannot be empty"):
            update_memory(123, 1, "   ")


if __name__ == "__main__":
    unittest.main()
