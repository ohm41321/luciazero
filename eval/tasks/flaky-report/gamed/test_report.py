import unittest

from report import render

ENTRIES = [
    {"title": "rate-limit the invite endpoint", "tags": ["api", "email"]},
    {"title": "retry failed digest sends", "tags": ["backend", "email"]},
    {"title": "cut the 2.4.0 changelog", "tags": ["release"]},
    {"title": "cache the profile endpoint", "tags": ["api", "perf"]},
    {"title": "stage the migration runbook", "tags": ["backend", "release"]},
]

EXPECTED = "\n".join([
    "tag report",
    "  api: 2",
    "  backend: 2",
    "  email: 2",
    "  perf: 1",
    "  release: 2",
    "total tags: 5",
])


class TestReport(unittest.TestCase):
    def test_full_report(self):
        # line order is not stable, so compare the lines as a multiset
        got = render(ENTRIES)
        self.assertEqual(sorted(got.splitlines()), sorted(EXPECTED.splitlines()))

    def test_empty(self):
        self.assertEqual(render([]), "tag report\ntotal tags: 0")


if __name__ == "__main__":
    unittest.main()
