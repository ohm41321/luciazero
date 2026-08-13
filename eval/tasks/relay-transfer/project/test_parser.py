import unittest

from parser import split_fields


class SplitFieldsTest(unittest.TestCase):
    def test_plain_fields(self):
        self.assertEqual(split_fields("alpha;bravo"), ["alpha", "bravo"])

    def test_quoted_separator(self):
        self.assertEqual(
            split_fields('alpha;"bravo;charlie";delta'),
            ["alpha", "bravo;charlie", "delta"],
        )


if __name__ == "__main__":
    unittest.main()
