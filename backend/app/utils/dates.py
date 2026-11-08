"""
Timezone and date calculation utilities for T2T DRIVE.
Enforces Indian Standard Time (IST, UTC+05:30) for driver-facing financial summaries
while maintaining strict UTC timestamps in database storage.
"""

import datetime
from typing import Tuple, Optional

# Indian Standard Time (fixed UTC+05:30, no DST)
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30), name="Asia/Kolkata")
UTC = datetime.timezone.utc


def now_utc() -> datetime.datetime:
    """Returns current timestamp in UTC with timezone awareness."""
    return datetime.datetime.now(UTC)


def now_ist() -> datetime.datetime:
    """Returns current timestamp in IST with timezone awareness."""
    return datetime.datetime.now(IST)


def today_ist() -> str:
    """Returns current calendar date string in IST ('YYYY-MM-DD')."""
    return now_ist().strftime("%Y-%m-%d")


def parse_date_str(date_str: str) -> datetime.date:
    """Parses 'YYYY-MM-DD' into a date object, raising ValueError on format error."""
    return datetime.date.fromisoformat(date_str.strip())


def get_day_bounds_utc(date_str: str) -> Tuple[datetime.datetime, datetime.datetime]:
    """
    Given a calendar date in IST ('YYYY-MM-DD'), returns the (start_utc, end_utc)
    timestamps representing 00:00:00.000000 to 23:59:59.999999 IST converted to UTC.
    """
    d = parse_date_str(date_str)
    start_ist = datetime.datetime(d.year, d.month, d.day, 0, 0, 0, 0, tzinfo=IST)
    end_ist = datetime.datetime(d.year, d.month, d.day, 23, 59, 59, 999999, tzinfo=IST)
    return start_ist.astimezone(UTC), end_ist.astimezone(UTC)


def get_week_bounds_utc(date_str: Optional[str] = None) -> Tuple[datetime.datetime, datetime.datetime, str, str]:
    """
    Returns (start_utc, end_utc, start_date_ist, end_date_ist) for the Monday-to-Sunday
    week containing the given date (or current IST date if None).
    """
    ref_date = parse_date_str(date_str) if date_str else now_ist().date()
    # weekday(): Monday is 0, Sunday is 6
    start_date = ref_date - datetime.timedelta(days=ref_date.weekday())
    end_date = start_date + datetime.timedelta(days=6)

    start_ist = datetime.datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0, 0, tzinfo=IST)
    end_ist = datetime.datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, 999999, tzinfo=IST)

    return (
        start_ist.astimezone(UTC),
        end_ist.astimezone(UTC),
        start_date.strftime("%Y-%m-%d"),
        end_date.strftime("%Y-%m-%d")
    )


def get_month_bounds_utc(year: int, month: int) -> Tuple[datetime.datetime, datetime.datetime, str, str]:
    """
    Returns (start_utc, end_utc, start_date_ist, end_date_ist) for the specified
    calendar month in IST.
    """
    if month < 1 or month > 12:
        raise ValueError(f"Invalid month: {month}. Must be 1-12.")
    start_date = datetime.date(year, month, 1)
    if month == 12:
        next_month_start = datetime.date(year + 1, 1, 1)
    else:
        next_month_start = datetime.date(year, month + 1, 1)
    end_date = next_month_start - datetime.timedelta(days=1)

    start_ist = datetime.datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0, 0, tzinfo=IST)
    end_ist = datetime.datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, 999999, tzinfo=IST)

    return (
        start_ist.astimezone(UTC),
        end_ist.astimezone(UTC),
        start_date.strftime("%Y-%m-%d"),
        end_date.strftime("%Y-%m-%d")
    )
