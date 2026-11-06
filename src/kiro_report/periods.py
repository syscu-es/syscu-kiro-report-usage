"""Reporting periods expressed as calendar months ('YYYY-MM')."""
from __future__ import annotations

import calendar
import datetime as dt
import re

DEFAULT_LAST_MONTHS = 3
_MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


class PeriodError(ValueError):
    """Raised for malformed or inconsistent period arguments."""


def parse_month(value: str) -> str:
    """Validate and return a 'YYYY-MM' string."""
    text = (value or "").strip()
    if not _MONTH_RE.match(text):
        raise PeriodError(f"invalid month {value!r}; expected YYYY-MM (e.g. 2026-10)")
    return text


def current_month(today: dt.date | None = None) -> str:
    return (today or dt.date.today()).strftime("%Y-%m")


def shift_month(month: str, delta: int) -> str:
    year, mon = int(month[:4]), int(month[5:7])
    index = year * 12 + (mon - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def month_range(since: str, until: str) -> list[str]:
    """Every month from ``since`` to ``until``, both included."""
    since, until = parse_month(since), parse_month(until)
    if since > until:
        raise PeriodError(f"--since ({since}) is after --until ({until})")
    months, cursor = [], since
    while cursor <= until:
        months.append(cursor)
        cursor = shift_month(cursor, 1)
    return months


def month_bounds(month: str) -> tuple[dt.date, dt.date]:
    """First and last day of a month."""
    year, mon = int(month[:4]), int(month[5:7])
    return dt.date(year, mon, 1), dt.date(year, mon, calendar.monthrange(year, mon)[1])


def resolve_period(
    *,
    month: str | None = None,
    since: str | None = None,
    until: str | None = None,
    last: int | None = None,
    today: dt.date | None = None,
) -> tuple[str, str]:
    """Turn the CLI period options into ``(since, until)``.

    Precedence: ``month`` > ``since``/``until`` > ``last`` > the last three months.
    """
    now = current_month(today)
    if month:
        single = parse_month(month)
        return single, single
    if since or until:
        end = parse_month(until) if until else now
        start = parse_month(since) if since else shift_month(end, -(DEFAULT_LAST_MONTHS - 1))
    else:
        count = DEFAULT_LAST_MONTHS if last is None else last
        if count < 1:
            raise PeriodError("--last must be at least 1")
        end, start = now, shift_month(now, -(count - 1))
    month_range(start, end)  # validates ordering
    return start, end


def preset_choices(today: dt.date | None = None) -> list[tuple[str, str, str]]:
    """``(label, since, until)`` options offered by the interactive prompt."""
    now = current_month(today)
    previous = shift_month(now, -1)
    return [
        (f"Last full month ({previous})", previous, previous),
        (f"Current month ({now})", now, now),
        ("Last 3 months", shift_month(now, -2), now),
        ("Last 6 months", shift_month(now, -5), now),
        ("Last 12 months", shift_month(now, -11), now),
    ]
