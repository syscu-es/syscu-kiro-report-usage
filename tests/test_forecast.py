import datetime as dt

import pytest

from kiro_report import forecast, model
from kiro_report.activity import ActivityRow
from kiro_report.cur import CurData

UID = "11111111-1111-1111-1111-111111111111"


@pytest.mark.unit
def test_project_month_extrapolates_pace_and_prices_overage():
    # Pro = 1,000 credits; 600 used in 10 of 30 days -> 1,800 projected, 800 over, $32 at $0.04
    out = forecast.project_month(600.0, 10, 30, "Pro")
    assert out == {"credits": 1800.0, "cap": 1000, "use": 180.0, "over_credits": 800.0, "over_cost": 32.0}


@pytest.mark.unit
def test_project_month_within_allowance_has_no_overage():
    out = forecast.project_month(100.0, 15, 30, "ProPlus")
    assert out["credits"] == 200.0 and out["over_credits"] == 0.0 and out["over_cost"] == 0.0


@pytest.mark.unit
@pytest.mark.parametrize(
    ("credits", "elapsed", "plan"),
    [(100.0, 3, "Pro"), (100.0, 10, "Mystery"), (100.0, 0, "Pro"), (0.0, 10, "Pro")],
)
def test_project_month_declines_when_pace_is_unreliable_or_plan_unknown(credits, elapsed, plan):
    assert forecast.project_month(credits, elapsed, 30, plan) is None


@pytest.mark.unit
def test_build_report_projects_only_the_month_in_progress():
    today = dt.date(2026, 11, 12)
    acts = [ActivityRow(f"2026-11-{d:02d}", UID, "", "IDE", "Pro", 80.0, 0.0, 10, 1, False, ()) for d in range(1, 11)]
    acts.append(ActivityRow("2026-10-31", UID, "", "IDE", "Pro", 5.0, 0.0, 1, 1, False, ()))
    cur = CurData({UID: {"2026-10": {"credits": 5.0, "sub": 20.0, "plan": "Pro"},
                         "2026-11": {"credits": 800.0, "sub": 20.0, "plan": "Pro"}}}, {}, {}, {})
    doc = model.build_report(meta={}, months=["2026-10", "2026-11"], cur=cur, activity=acts, today=today)
    proj = doc["people"][0]["proj"]
    assert proj["month"] == "2026-11" and proj["credits"] == 2400.0 and proj["over_cost"] == 56.0
    assert doc["meta"]["proj_month"] == "2026-11"
    assert doc["meta"]["proj_elapsed"] == 10  # days of the month the pace is based on


@pytest.mark.unit
def test_build_report_has_no_projection_for_complete_months():
    cur = CurData({UID: {"2026-09": {"credits": 50.0, "sub": 20.0, "plan": "Pro"}}}, {}, {}, {})
    doc = model.build_report(meta={}, months=["2026-09"], cur=cur, activity=None, today=dt.date(2026, 11, 12))
    assert doc["people"][0]["proj"] is None and doc["meta"]["proj_month"] is None and doc["meta"]["proj_elapsed"] == 0
