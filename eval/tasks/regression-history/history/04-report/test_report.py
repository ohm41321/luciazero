import unittest

from report import render


class RenderTest(unittest.TestCase):
    def test_one_entry(self):
        out = render([("build", "green on every platform we ship to")], 20)
        self.assertEqual(out, "BUILD\n" + "-" * 20 + "\n"
                         "green on every\nplatform we ship to\n")


if __name__ == "__main__":
    unittest.main()
