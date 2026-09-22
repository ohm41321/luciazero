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

    def test_breaks_words_longer_than_the_width(self):
        self.assertEqual(wrap("a supercalifragilistic b", 8),
                         ["a", "supercal", "ifragili", "stic b"])

    def test_rejects_zero_width(self):
        with self.assertRaises(ValueError):
            wrap("x", 0)


class IndentTest(unittest.TestCase):
    def test_indent_prefixes_every_line(self):
        self.assertEqual(wrap("one two three four", 10, indent="> "),
                         ["> one two", "> three", "> four"])

    def test_indent_counts_against_the_width(self):
        for line in wrap("alpha beta gamma delta epsilon", 12, indent="    "):
            self.assertLessEqual(len(line), 12)

    def test_long_words_break_inside_the_room_left(self):
        self.assertEqual(wrap("abcdefghij", 6, indent="- "),
                         ["- abcd", "- efgh", "- ij"])

    def test_indent_must_leave_room(self):
        with self.assertRaises(ValueError):
            wrap("x", 2, indent="  ")


if __name__ == "__main__":
    unittest.main()
