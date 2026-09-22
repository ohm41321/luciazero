import unittest

from linewrap import wrap


class WrapTest(unittest.TestCase):
    def test_fills_lines_greedily(self):
        self.assertEqual(
            wrap("the quick brown fox jumps over the lazy dog", 13),
            ["the quick", "brown fox", "jumps over", "the lazy dog"])

    def test_collapses_whitespace(self):
        self.assertEqual(wrap("  a   b\n c ", 20), ["a b c"])

    def test_empty_text_has_no_lines(self):
        self.assertEqual(wrap("   ", 10), [])

    def test_long_word_gets_its_own_line(self):
        self.assertEqual(wrap("a supercalifragilistic b", 8),
                         ["a", "supercalifragilistic", "b"])

    def test_rejects_zero_width(self):
        with self.assertRaises(ValueError):
            wrap("x", 0)


if __name__ == "__main__":
    unittest.main()
