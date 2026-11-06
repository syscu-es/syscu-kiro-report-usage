import datetime as dt

import pytest

from kiro_report import periods
from kiro_report.ids import normalize_user_id

TODAY = dt.date(2026, 11, 6)


@pytest.mark.unit
def test_month_range_inclusive_and_year_rollover():
    assert periods.month_range("2026-11", "2027-02") == ["2026-11", "2026-12", "2027-01", "2027-02"]


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["2026/10", "2026-13", "26-10", "", "2026-1"])
def test_parse_month_rejects_bad_values(bad):
    with pytest.raises(periods.PeriodError):
        periods.parse_month(bad)


@pytest.mark.unit
def test_month_range_rejects_inverted():
    with pytest.raises(periods.PeriodError):
        periods.month_range("2026-10", "2026-09")


@pytest.mark.unit
def test_shift_month_across_years():
    assert periods.shift_month("2026-02", -5) == "2025-09"
    assert periods.shift_month("2026-12", 1) == "2027-01"


@pytest.mark.unit
def test_month_bounds_handles_leap_february():
    assert periods.month_bounds("2028-02")[1] == dt.date(2028, 2, 29)
    assert periods.month_bounds("2026-02")[1] == dt.date(2026, 2, 28)


@pytest.mark.unit
def test_resolve_period_precedence_and_defaults():
    assert periods.resolve_period(month="2026-10", since="2020-01", today=TODAY) == ("2026-10", "2026-10")
    assert periods.resolve_period(since="2026-08", until="2026-10", today=TODAY) == ("2026-08", "2026-10")
    assert periods.resolve_period(since="2026-08", today=TODAY) == ("2026-08", "2026-11")
    assert periods.resolve_period(until="2026-10", today=TODAY) == ("2026-08", "2026-10")
    assert periods.resolve_period(last=6, today=TODAY) == ("2026-06", "2026-11")
    assert periods.resolve_period(today=TODAY) == ("2026-09", "2026-11")


@pytest.mark.unit
def test_resolve_period_rejects_invalid_last_and_order():
    with pytest.raises(periods.PeriodError):
        periods.resolve_period(last=0, today=TODAY)
    with pytest.raises(periods.PeriodError):
        periods.resolve_period(since="2026-11", until="2026-01", today=TODAY)


@pytest.mark.unit
def test_preset_choices_cover_common_windows():
    labels = [p[0] for p in periods.preset_choices(TODAY)]
    assert labels[0].startswith("Last full month (2026-10)")
    assert periods.preset_choices(TODAY)[2][1:] == ("2026-09", "2026-11")


@pytest.mark.unit
def test_normalize_user_id_handles_arn_prefix_and_plain_values():
    uuid = "34a83448-3051-70cb-6a94-0f85aca27e38"
    assert normalize_user_id(f"arn:aws:identitystore:::user/{uuid.upper()}") == uuid
    assert normalize_user_id(f"d-9066255f0f.{uuid}") == uuid
    assert normalize_user_id("  Plain-Id ") == "plain-id"
    assert normalize_user_id("") == ""
