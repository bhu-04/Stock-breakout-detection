"""US trading calendar and market-session logic (America/New_York, DST-aware).

Dates below were checked against the published NYSE holiday schedule; all times are
converted from UTC so the tests do not depend on the machine's own time zone.
"""
from datetime import date, datetime, timezone

import pytest

from backend.config.calendars import us_early_closes, us_market_holidays
from backend.config.market import INDIA, US, session_status


def utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def test_us_2026_full_day_closures():
    assert us_market_holidays(2026) == {
        date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16), date(2026, 4, 3), date(2026, 5, 25),
        date(2026, 6, 19), date(2026, 7, 3),            # Jul 4 is a Saturday -> observed Friday Jul 3
        date(2026, 9, 7), date(2026, 11, 26), date(2026, 12, 25),
    }


def test_us_early_closes_are_computed_and_exclude_holidays():
    assert set(us_early_closes(2026)) == {date(2026, 11, 27), date(2026, 12, 24)}      # Jul 3 is a full holiday instead
    assert date(2025, 7, 3) in us_early_closes(2025)                                    # Thursday before the 4th
    assert date(2028, 7, 3) in us_early_closes(2028) and date(2028, 7, 4) in us_market_holidays(2028)   # Tuesday the 4th


def test_weekend_holiday_observance_rules():
    assert date(2027, 12, 24) in us_market_holidays(2027)          # Christmas on Saturday -> Friday
    assert date(2027, 12, 31) not in us_market_holidays(2027)      # NYSE does NOT close Dec 31 for a Saturday New Year
    assert date(2022, 12, 26) in us_market_holidays(2022)          # Christmas on Sunday -> Monday


@pytest.mark.parametrize(
    "when, state, reason, local",
    [
        ("2026-10-29T13:29:00", "closed", "before_open", "09:29-04:00"),    # EDT
        ("2026-10-29T13:30:00", "open", "in_session", "09:30-04:00"),
        ("2026-10-29T19:59:00", "open", "in_session", "15:59-04:00"),
        ("2026-10-29T20:00:00", "closed", "after_close", "16:00-04:00"),
        ("2026-10-31T15:00:00", "closed", "weekend", "11:00-04:00"),
        ("2026-11-26T15:00:00", "closed", "holiday", "10:00-05:00"),        # Thanksgiving
        ("2026-07-03T15:00:00", "closed", "holiday", "11:00-04:00"),        # Independence Day observed
        ("2026-04-03T15:00:00", "closed", "holiday", "11:00-04:00"),        # Good Friday
    ],
)
def test_us_session_state_in_new_york_time(when, state, reason, local):
    st = session_status(US, utc(when))
    assert (st["state"], st["reason"]) == (state, reason)
    assert st["local_time"].endswith(local[:5] + ":00" + local[5:]) or local in st["local_time"]
    assert st["timezone"] == "America/New_York" and st["session_open"] == "09:30"
    assert st["holiday_calendar_configured"] is True


def test_us_open_follows_daylight_saving_without_a_hardcoded_offset():
    # Same 09:30 ET opening bell; the UTC instant moves by an hour when DST starts/ends.
    assert session_status(US, utc("2026-03-06T14:29:00"))["state"] == "closed"        # EST (UTC-5): opens 14:30Z
    assert session_status(US, utc("2026-03-06T14:30:00"))["state"] == "open"
    assert session_status(US, utc("2026-03-09T13:29:00"))["state"] == "closed"        # EDT (UTC-4): opens 13:30Z
    assert session_status(US, utc("2026-03-09T13:30:00"))["state"] == "open"
    assert session_status(US, utc("2026-11-02T14:29:00"))["state"] == "closed"        # back to EST after Nov 1
    assert session_status(US, utc("2026-11-02T14:30:00"))["state"] == "open"
    assert session_status(US, utc("2026-03-09T13:30:00"))["local_time"].endswith("-04:00")
    assert session_status(US, utc("2026-03-06T14:30:00"))["local_time"].endswith("-05:00")


def test_early_close_day_after_thanksgiving_ends_at_13_00_et():
    open_ = session_status(US, utc("2026-11-27T17:59:00"))                             # 12:59 EST
    assert open_["state"] == "open" and open_["session_close"] == "13:00" and open_["early_close"] is True
    closed = session_status(US, utc("2026-11-27T18:00:00"))                            # 13:00 EST
    assert (closed["state"], closed["reason"], closed["next_open"]) == ("closed", "after_close", "2026-11-30T09:30:00-05:00")


def test_next_open_skips_weekends_holidays_and_crosses_the_year_boundary():
    st = session_status(US, utc("2026-11-25T22:00:00"))                                # Wed after close, Thanksgiving next day
    assert st["next_open"] == "2026-11-27T09:30:00-05:00"
    st = session_status(US, utc("2026-12-31T22:00:00"))                                # Thu after close; Jan 1 is a holiday
    assert st["next_open"] == "2027-01-04T09:30:00-05:00"


def test_configured_ad_hoc_us_closure_is_honoured():
    when = utc("2026-10-29T15:00:00")
    assert session_status(US, when)["state"] == "open"
    st = session_status(US, when, holidays={date(2026, 10, 29)})
    assert (st["state"], st["reason"]) == ("closed", "holiday")


def test_us_calendar_never_leaks_into_india():
    thanksgiving_morning_ist = utc("2026-11-26T05:00:00")                              # 10:30 IST on a US holiday
    assert session_status(INDIA, thanksgiving_morning_ist)["state"] == "open"
    st = session_status(INDIA, thanksgiving_morning_ist)
    assert st["holiday_calendar_configured"] is False and st["early_close"] is False
    assert session_status(INDIA, utc("2026-07-03T05:00:00"))["state"] == "open"         # US observed holiday: NSE trades


def test_india_and_us_are_in_different_states_at_the_same_instant():
    now = utc("2026-10-29T05:00:00")                                                   # 10:30 IST / 01:00 EDT
    assert session_status(INDIA, now)["state"] == "open"
    assert session_status(US, now)["state"] == "closed"
    now = utc("2026-10-29T15:00:00")                                                   # 20:30 IST / 11:00 EDT
    assert session_status(INDIA, now)["state"] == "closed" and session_status(US, now)["state"] == "open"
