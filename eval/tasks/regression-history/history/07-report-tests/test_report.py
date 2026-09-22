import unittest

from report import render


class RenderTest(unittest.TestCase):
    def test_one_entry(self):
        out = render([("build", "green on every platform we ship to")], 20)
        self.assertEqual(out, "BUILD\n" + "-" * 20 + "\n"
                         "green on every\nplatform we ship to\n")

    def test_blocks_are_separated_by_a_blank_line(self):
        out = render([("a", "one"), ("b", "two")], 10)
        self.assertEqual(out, "A\n----------\none\n\nB\n----------\ntwo\n")

    def test_note_lines_stay_within_the_width(self):
        note = "a status note that is long enough to need several lines of output"
        out = render([("wide", note)], 24)
        for line in out.splitlines():
            self.assertLessEqual(len(line), 24)

    def test_rejects_zero_width(self):
        with self.assertRaises(ValueError):
            render([("a", "b")], 0)


if __name__ == "__main__":
    unittest.main()
