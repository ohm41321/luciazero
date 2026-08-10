import unittest

from parse import parse
from render import render
from transform import transform

SAMPLE = (
    "item: apple\n"
    "qty: 3\n"
    "price: 2\n"
    "\n"
    "item: banana\n"
    "qty: 2\n"
    "price: 5\n"
    "\n"
)


class TestParse(unittest.TestCase):
    def test_two_records(self):
        records = parse(SAMPLE)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["item"], "apple")
        self.assertEqual(records[1]["item"], "banana")

    def test_blank_input(self):
        self.assertEqual(parse("\n\n"), [])


class TestTransform(unittest.TestCase):
    def test_totals(self):
        rows = transform(parse(SAMPLE))
        self.assertEqual([r["total"] for r in rows], [6, 10])


class TestRender(unittest.TestCase):
    def test_report(self):
        report = render(transform(parse(SAMPLE)))
        self.assertIn("entries: 2", report)
        self.assertIn("grand total: 16", report)


if __name__ == "__main__":
    unittest.main()
