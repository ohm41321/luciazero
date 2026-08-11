import unittest

from pricing import total


class TestTotal(unittest.TestCase):
    def test_empty_cart(self):
        self.assertEqual(total([]), 0)

    def test_plain_lines(self):
        self.assertEqual(total([("pad", 2, 50), ("clip", 1, 30)]), 130)


if __name__ == "__main__":
    unittest.main()
