import unittest

from pricing import total


class TestTotal(unittest.TestCase):
    def test_empty_cart(self):
        self.assertEqual(total([]), 0)

    def test_plain_lines(self):
        self.assertEqual(total([("pad", 2, 50), ("clip", 1, 30)]), 130)

    def test_bulk_line_discount(self):
        self.assertEqual(total([("box", 12, 100)]), 1080)

    def test_below_bulk_threshold(self):
        self.assertEqual(total([("box", 9, 100)]), 900)

    def test_member_discount(self):
        self.assertEqual(total([("ink", 1, 200)], member=True), 190)

    def test_member_applied_after_bulk(self):
        # bulk line 10*100 -> 900, plus 50 -> 950, member -> 902
        self.assertEqual(total([("box", 10, 100), ("ink", 1, 50)], member=True), 902)


if __name__ == "__main__":
    unittest.main()
