"""Exchange holiday calendars.

US (NYSE/Nasdaq): the full-day closures follow fixed rules, so they are
computed rather than hand-maintained. Rules implemented (NYSE Rule 7.2):
New Year's Day, Martin Luther King Jr. Day (3rd Mon Jan), Washington's
Birthday (3rd Mon Feb), Good Friday, Memorial Day (last Mon May), Juneteenth
(Jun 19), Independence Day (Jul 4), Labor Day (1st Mon Sep), Thanksgiving
(4th Thu Nov), Christmas (Dec 25). A holiday on a Saturday is observed the
preceding Friday and one on a Sunday the following Monday - except New Year's
Day on a Saturday, which NYSE does not observe on the Friday before.
Early (13:00 ET) closes: the day after Thanksgiving, Dec 24 and Jul 3 when
they are ordinary weekdays.

This is a rules-based approximation. Ad-hoc closures (national days of
mourning, weather, etc.) cannot be predicted: add them with the
`MARKET_HOLIDAYS_US` setting, and check the official NYSE calendar before
relying on a date.

India (NSE/BSE): holidays are set by exchange circular each year and depend
on lunar festivals, so no calendar is embedded. They are supplied through
`MARKET_HOLIDAYS_IN` (see config/settings.py).
"""
from __future__ import annotations

from datetime import date, time, timedelta
from functools import lru_cache

US_EARLY_CLOSE = time(13, 0)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _easter(year: int) -> date:
    """Western Easter Sunday (anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _observed(d: date) -> date | None:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=32)
def us_market_holidays(year: int) -> frozenset:
    out: set[date] = set()

    new_year = date(year, 1, 1)
    if new_year.weekday() != 5:                      # Saturday: not observed on Dec 31
        out.add(_observed(new_year))
    out.add(_nth_weekday(year, 1, 0, 3))             # Martin Luther King Jr. Day
    out.add(_nth_weekday(year, 2, 0, 3))             # Washington's Birthday
    out.add(_easter(year) - timedelta(days=2))       # Good Friday
    out.add(_last_weekday(year, 5, 0))               # Memorial Day
    out.add(_observed(date(year, 6, 19)))            # Juneteenth
    out.add(_observed(date(year, 7, 4)))             # Independence Day
    out.add(_nth_weekday(year, 9, 0, 1))             # Labor Day
    out.add(_nth_weekday(year, 11, 3, 4))            # Thanksgiving
    out.add(_observed(date(year, 12, 25)))           # Christmas
    return frozenset(out)


@lru_cache(maxsize=32)
def us_early_closes(year: int) -> dict:
    holidays = us_market_holidays(year) | us_market_holidays(year + 1)
    days: set[date] = {_nth_weekday(year, 11, 3, 4) + timedelta(days=1)}   # day after Thanksgiving
    for d in (date(year, 7, 3), date(year, 12, 24)):
        days.add(d)
    return {d: US_EARLY_CLOSE for d in days if d.weekday() < 5 and d not in holidays}


def calendar_for(market_code: str, on: date) -> tuple[frozenset, dict]:
    """(computed holidays, early closes) for `market_code` around `on`.

    Only the US has a computed calendar; India returns empty sets (configured
    via MARKET_HOLIDAYS_IN)."""
    if market_code == "US":
        return us_market_holidays(on.year), us_early_closes(on.year)
    return frozenset(), {}
