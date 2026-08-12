import unittest

from client import Client
from service import active_names


class SyncTests(unittest.TestCase):
    def test_one_page(self):
        client = Client(lambda cursor: {
            "items": [{"name": "Ada", "active": True}, {"name": "Lin", "active": False}],
            "next_cursor": None,
        })
        self.assertEqual(active_names(client), ["Ada"])


if __name__ == "__main__":
    unittest.main()
