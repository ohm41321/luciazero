import unittest

from versions import compare, is_newer, latest, parse


class CompareTest(unittest.TestCase):
    def test_components_compare_as_numbers_not_text(self):
        self.assertEqual(compare("1.10.0", "1.9.0"), 1)
        self.assertEqual(compare("1.9.0", "1.10.0"), -1)

    def test_missing_trailing_component_counts_as_zero(self):
        self.assertEqual(compare("1.4", "1.4.0"), 0)
        self.assertEqual(compare("1.4.1", "1.4"), 1)

    def test_leading_zero_carries_no_meaning(self):
        self.assertEqual(compare("1.04", "1.4"), 0)

    def test_rejects_anything_that_is_not_a_version(self):
        for bad in ["", "1.", ".1", "1..2", "v1.2", "1.2-rc1", "-1.2", " 1.2", "1.2 "]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse(bad)


class ChooserTest(unittest.TestCase):
    def test_latest_picks_the_numerically_newest(self):
        self.assertEqual(latest(["1.9.0", "1.10.0", "1.2.0"]), "1.10.0")

    def test_latest_returns_the_version_as_written(self):
        self.assertEqual(latest(["1.4.0", "1.4"]), "1.4.0")

    def test_is_newer_is_strict(self):
        self.assertTrue(is_newer("1.10.0", "1.9.0"))
        self.assertFalse(is_newer("1.9.0", "1.9"))


if __name__ == "__main__":
    unittest.main()
