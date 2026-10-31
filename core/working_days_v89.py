"""Read-only Darma working-day helpers for V89.

A business working day is defined from recorded business activity: at least one
positive Darma SaleLine on that date. This intentionally avoids external holiday
calendars and prevents a holiday/no-sale day from being compared as a zero day.
"""
from collections import defaultdict
from datetime import timedelta

import jdatetime

from .models import SaleLine


def month_bounds(value):
    j = jdatetime.date.fromgregorian(date=value)
    start = jdatetime.date(j.year, j.month, 1).togregorian()
    if j.month == 12:
        next_start = jdatetime.date(j.year + 1, 1, 1).togregorian()
    else:
        next_start = jdatetime.date(j.year, j.month + 1, 1).togregorian()
    return start, next_start - timedelta(days=1)


def working_dates(start, end):
    if not start or not end or end < start:
        return []
    return list(
        SaleLine.objects.filter(
            day__date__gte=start,
            day__date__lte=end,
            quantity__gt=0,
            product_size__product__brand__name="دارما",
        )
        .order_by("day__date")
        .values_list("day__date", flat=True)
        .distinct()
    )


def working_dates_for_month(value, through=None):
    start, end = month_bounds(value)
    if through is not None:
        end = min(end, through)
    return working_dates(start, end)


def month_key(value):
    j = jdatetime.date.fromgregorian(date=value)
    return j.year, j.month


def previous_month_key(key):
    year, month = key
    return (year - 1, 12) if month == 1 else (year, month - 1)


def group_working_dates(dates):
    grouped = defaultdict(list)
    for value in dates:
        grouped[month_key(value)].append(value)
    return grouped


def previous_working_date(value, grouped):
    key = month_key(value)
    current = grouped.get(key, [])
    try:
        ordinal = current.index(value) + 1
    except ValueError:
        return None, None
    previous = grouped.get(previous_month_key(key), [])
    match = previous[ordinal - 1] if len(previous) >= ordinal else None
    return ordinal, match
