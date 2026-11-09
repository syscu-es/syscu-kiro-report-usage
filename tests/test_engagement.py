import datetime as dt

import pytest

from kiro_report import demo, engagement, model
from kiro_report.activity import ActivityRow
from kiro_report.cur import CurData

TODAY = dt.date(2026, 11, 6)
UID1 = "11111111-1111-1111-1111-111111111111"
UID2 = "22222222-2222-2222-2222-222222222222"


def row(uid, day, messages=10, conversations=1, credits=5.0, client="IDE"):
    return ActivityRow(day, uid, "", client, "Pro", credits, 0.0, messages, conversations, False, ())


@pytest.mark.unit
@pytest.mark.parametrize(
    ("messages", "conversations", "expected"),
    [
        (0, 0, "idle"),
        (1, 0, "light"),
        (19, 4, "light"),
        (20, 0, "active"),
        (5, 5, "active"),
        (100, 0, "power"),
        (5, 20, "power"),
    ],
)
def test_segment_of_uses_message_and_conversation_thresholds(messages, conversations, expected):
    assert engagement.segment_of(messages, conversations, period_days=30) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("credits", "expected"),
    [(0, "idle"), (5, "light"), (99, "light"), (100, "active"), (499, "active"), (500, "power"), (2000, "power")],
)
def test_segment_uses_plan_allowance_when_the_plan_is_known(credits, expected):
    # Pro = 1,000 credits per 30 days: active from 10%, power from 50%
    assert engagement.segment_of(0, 500, 30, credits=credits, cap=1000) == expected


@pytest.mark.unit
def test_plan_use_scales_with_period_and_ignores_conversations():
    assert engagement.segment_of(0, 0, 60, credits=500, cap=1000) == "active"  # 25% of two months' allowance
    assert engagement.segment_of(0, 0, 15, credits=500, cap=1000) == "power"  # 100% of half a month's
    assert engagement.segment_of(6, 74, 30, credits=2, cap=10000) == "light"  # many chats, almost no use
    assert engagement.segment_of(10, 0, 30, credits=0, cap=1000) == "light"  # messages without credits


@pytest.mark.unit
def test_thresholds_scale_with_long_periods_but_never_shrink():
    assert engagement.thresholds(10) == engagement.thresholds(30)
    long = engagement.thresholds(90)
    assert long["power_messages"] == 300 and long["active_conversations"] == 15
    # 100 messages is "power" in a month but only "active" over a quarter
    assert engagement.segment_of(100, 0, period_days=30) == "power"
    assert engagement.segment_of(100, 0, period_days=90) == "active"


@pytest.mark.unit
def test_summarise_counts_active_days_and_recency_against_last_data_day():
    rows = [
        row("a", "2026-10-01"), row("a", "2026-10-01", client="CLI"), row("a", "2026-10-10"),
        row("b", "2026-10-20", messages=0, conversations=0, credits=0.0),  # listed but silent
        row("c", "2026-10-30", messages=150),
        row("d", "2026-10-15", credits=150.0),
        row("e", "2026-10-16", credits=700.0),
    ]
    stats, period_days = engagement.summarise(rows, {"a": 0, "b": 1, "c": 2, "d": 3, "e": 4}, {"2026-10"})
    assert period_days == 30  # 2026-10-01 .. 2026-10-30 inclusive
    assert stats[0]["active_days"] == 2 and stats[0]["messages"] == 30
    assert stats[0]["first_date"] == "2026-10-01" and stats[0]["last_date"] == "2026-10-10"
    assert stats[0]["days_since_last"] == 20 and stats[0]["segment"] == "light"  # 15 of 1,000 credits
    assert stats[0]["credits"] == 15.0 and stats[0]["use"] == 1.5
    assert stats[1]["active_days"] == 0 and stats[1]["segment"] == "idle"
    assert stats[1]["last_date"] == "" and stats[1]["days_since_last"] is None
    assert stats[2]["segment"] == "light" and stats[2]["days_since_last"] == 0
    assert stats[3]["segment"] == "active" and stats[4]["segment"] == "power"


@pytest.mark.unit
def test_summarise_ignores_unknown_users_and_months_outside_the_period():
    rows = [row("a", "2026-09-30"), row("zzz", "2026-10-02"), row("a", "2026-10-03")]
    stats, period_days = engagement.summarise(rows, {"a": 0}, {"2026-10"})
    assert set(stats) == {0} and stats[0]["first_date"] == "2026-10-03" and period_days == 1


@pytest.mark.unit
def test_summarise_without_rows_is_empty():
    assert engagement.summarise([], {"a": 0}, {"2026-10"}) == ({}, 0)


@pytest.mark.unit
def test_empty_stats_is_an_idle_user():
    assert engagement.empty_stats()["segment"] == "idle"


@pytest.mark.unit
def test_build_report_attaches_engagement_to_every_person_and_meta():
    acts = [row(UID1, "2026-10-05", messages=120), row(UID1, "2026-10-06")]
    cur = CurData(
        {UID1: {"2026-10": {"credits": 10.0, "sub": 20.0, "plan": "Pro"}},
         UID2: {"2026-10": {"credits": 0.0, "sub": 20.0, "plan": "Pro"}}},
        {}, {"2026-10": -40.0}, {"2026-10": 40.0})
    doc = model.build_report(meta={}, months=["2026-10"], cur=cur, activity=acts, today=TODAY)
    assert sorted(p["eng"]["segment"] for p in doc["people"]) == ["active", "idle"]  # 10 credits of 66.7 in 2 days
    assert doc["meta"]["period_days"] == 2 and doc["meta"]["thresholds"]["power_messages"] == 100
    assert doc["meta"]["thresholds"]["power_use"] == 50 and doc["meta"]["thresholds"]["active_use"] == 10


@pytest.mark.unit
def test_build_report_without_activity_has_no_engagement():
    cur = CurData({UID1: {"2026-10": {"credits": 1.0, "sub": 20.0, "plan": "Pro"}}}, {}, {}, {})
    doc = model.build_report(meta={}, months=["2026-10"], cur=cur, activity=None, today=TODAY)
    assert all(p["eng"] is None for p in doc["people"])
    assert doc["meta"]["thresholds"] is None


@pytest.mark.unit
def test_demo_report_covers_several_segments():
    doc = demo.make_demo(today=TODAY)
    segments = {p["eng"]["segment"] for p in doc["people"]}
    assert {"power", "idle"} <= segments and len(segments) >= 3


@pytest.mark.unit
def test_rendered_demo_contains_engagement_section_and_safe_helpers():
    from kiro_report import render

    html = render.render(demo.make_demo(today=TODAY))
    assert 'id="engagement"' in html and '"segment":' in html
    assert "const esc = " in html and "csvCell" in html
    assert "__DATA__" not in html and "</script><script" not in html


@pytest.mark.unit
def test_user_without_activity_coverage_has_no_engagement_but_covered_idle_user_does():
    uid3 = "33333333-3333-3333-3333-333333333333"
    acts = [row(UID1, "2026-10-05", messages=50)]
    cell = {"credits": 0.0, "sub": 20.0, "plan": "Pro"}
    cur = CurData(
        {UID1: {"2026-10": cell}, UID2: {"2026-10": cell}, uid3: {"2026-09": cell}},
        {}, {}, {})
    doc = model.build_report(meta={}, months=["2026-09", "2026-10"], cur=cur, activity=acts, today=TODAY)
    by_segment = sorted((p["eng"] or {}).get("segment", "none") for p in doc["people"])
    # UID1 active, UID2 idle (CUR in a month the activity report covers), uid3 not covered at all
    assert by_segment == ["active", "idle", "none"]


@pytest.mark.unit
def test_anonymize_keeps_engagement_free_of_identities():
    acts = [row(UID1, "2026-10-05", messages=120)]
    cur = CurData({UID1: {"2026-10": {"credits": 5.0, "sub": 20.0, "plan": "Pro"}}}, {}, {}, {})
    doc = model.build_report(meta={}, months=["2026-10"], cur=cur, activity=acts, names={UID1: "ana@example.com"},
                             today=TODAY, anonymize=True)
    assert doc["people"][0]["user"] == "user-01"
    assert "ana@example.com" not in str(doc) and UID1 not in str(doc)
