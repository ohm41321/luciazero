import unittest

from slugify import slugify


class TestSlugify(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify("Hello World"), "hello-world")

    def test_punctuation(self):
        self.assertEqual(slugify("a, b & c!"), "a-b-c")

    def test_leading_trailing(self):
        self.assertEqual(slugify("  spaced out  "), "spaced-out")

    def test_empty(self):
        self.assertEqual(slugify(""), "")

    def test_unicode_kept(self):
        # regression test for the empty-slug-on-unicode bug
        self.assertEqual(slugify("สวัสดี ชาวโลก"), "สวัสดี-ชาวโลก")


if __name__ == "__main__":
    unittest.main()
