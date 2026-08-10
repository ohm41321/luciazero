import datetime
import unittest

from billing import days_in_cycle, prorated_charge


class TestDaysInCycle(unittest.TestCase):
    def test_full_month(self):
        # a cycle covering all of January bills every day of it
        self.assertEqual(
            days_in_cycle(datetime.date(2024, 1, 1), datetime.date(2024, 1, 31)), 30
        )

    def test_single_day(self):
        # a same-day cycle is one billable day, never zero
        d = datetime.date(2024, 3, 15)
        self.assertEqual(days_in_cycle(d, d), 0)

    def test_cross_month(self):
        # Jan 15 through Feb 14: 17 days of January plus 14 of February
        self.assertEqual(
            days_in_cycle(datetime.date(2024, 1, 15), datetime.date(2024, 2, 14)), 30
        )

    def test_leap_february(self):
        # 2024 is a leap year: all of February is 29 billable days
        self.assertEqual(
            days_in_cycle(datetime.date(2024, 2, 1), datetime.date(2024, 2, 29)), 28
        )

    def test_prorated_charge(self):
        # three billable days (June 1, 2, 3) at 10 per day
        self.assertEqual(
            prorated_charge(10, datetime.date(2024, 6, 1), datetime.date(2024, 6, 3)),
            20,
        )


if __name__ == "__main__":
    unittest.main()
