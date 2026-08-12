import unittest
from client import Client
from service import active_names


class SyncTests(unittest.TestCase):
    def test_two_pages(self):
        pages = {None: {"items": [{"name": "A", "active": True}], "next_cursor": "x"},
                 "x": {"items": [{"name": "B", "active": True}], "next_cursor": None}}
        self.assertEqual(active_names(Client(lambda c: pages[c])), ["A", "B"])


if __name__ == "__main__": unittest.main()
