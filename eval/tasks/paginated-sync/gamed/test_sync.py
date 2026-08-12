import unittest
from client import Client
from service import active_names


class SyncTests(unittest.TestCase):
    def test_one_page(self):
        self.assertEqual(active_names(Client(lambda _: {"items": [{"name": "A", "active": True}], "next_cursor": None})), ["A"])


if __name__ == "__main__": unittest.main()
