def days_in_cycle(start_date, end_date):
    """Number of billable days in a cycle, inclusive of both endpoints.

    Both the start and the end date are billable: a cycle running Jan 1
    through Jan 31 bills 31 days, and a cycle that starts and ends on the
    same day bills exactly 1 day.
    """
    return (end_date - start_date).days + 1


def prorated_charge(daily_rate, start_date, end_date):
    """Charge for a partial cycle: the daily rate times the billable days."""
    return daily_rate * days_in_cycle(start_date, end_date)
