import io
import unittest
from contextlib import redirect_stdout

from client import Client, CursorCycleError
from cli import main
from service import active_names


class SyncTests(unittest.TestCase):
    def test_one_page(self):
        client = Client(lambda cursor: {
            "items": [{"name": "Ada", "active": True}, {"name": "Lin", "active": False}],
            "next_cursor": None,
        })
        self.assertEqual(active_names(client), ["Ada"])

    def test_all_pages_keep_order_and_cursor(self):
        calls = []
        pages = {
            None: {"items": [{"name": "A", "active": True}], "next_cursor": "a/b + c"},
            "a/b + c": {"items": [{"name": "B", "active": True}], "next_cursor": "最後"},
            "最後": {"items": [{"name": "C", "active": True}], "next_cursor": None},
        }
        client = Client(lambda cursor: calls.append(cursor) or pages[cursor])
        self.assertEqual(active_names(client), ["A", "B", "C"])
        self.assertEqual(calls, [None, "a/b + c", "最後"])

    def test_cycle_stops_before_repeated_request(self):
        calls = []
        pages = {
            None: {"items": [], "next_cursor": "x"},
            "x": {"items": [], "next_cursor": "x"},
        }
        client = Client(lambda cursor: calls.append(cursor) or pages[cursor])
        with self.assertRaises(CursorCycleError):
            active_names(client)
        self.assertEqual(calls, [None, "x"])

    def test_cli_prints_every_active_name(self):
        pages = {
            None: {"items": [{"name": "A", "active": True}], "next_cursor": "next"},
            "next": {"items": [{"name": "B", "active": True}], "next_cursor": None},
        }
        output = io.StringIO()
        with redirect_stdout(output):
            main(lambda cursor: pages[cursor])
        self.assertEqual(output.getvalue().splitlines(), ["A", "B"])


if __name__ == "__main__":
    unittest.main()
