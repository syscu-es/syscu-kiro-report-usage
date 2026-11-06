import datetime as dt
import json

import pytest

from kiro_report import cur, demo, model
from kiro_report.activity import ActivityRow

UUID1 = "11111111-1111-1111-1111-111111111111"
UUID2 = "22222222-2222-2222-2222-222222222222"
TODAY = dt.date(2026, 11, 6)


def cur_row(kind, usage_type, resource, amount=0.0, cost=0.0, day=dt.datetime(2026, 10, 5)):
    return {"line_item_line_item_type": kind, "line_item_usage_type": usage_type,
            "line_item_resource_id": resource, "line_item_usage_amount": amount,
            "line_item_unblended_cost": cost, "line_item_usage_start_date": day}


def act_row(uid, day, credits, tier="POWER", client="IDE", overage=0.0, email=""):
    return ActivityRow(day, uid, email, client, tier, credits, overage, 10, 1, False, (("auto", 10),))


class FakeBcm:
    def __init__(self, prefix, fmt="PARQUET", query="SELECT line_item_resource_id"):
        self.prefix, self.fmt, self.query = prefix, fmt, query

    def list_exports(self):
        return {"Exports": [{"ExportName": "exp", "ExportArn": "arn"}]}

    def get_export(self, ExportArn):
        dest = {"S3Bucket": "b", "S3OutputConfigurations": {"Format": self.fmt}}
        if self.prefix is not None:
            dest["S3Prefix"] = self.prefix
        return {"Export": {"DataQuery": {"QueryStatement": self.query},
                           "DestinationConfigurations": {"S3Destination": dest}}}


class FakeSession:
    def __init__(self, bcm):
        self.bcm = bcm

    def client(self, name, region_name=None):
        return self.bcm


@pytest.mark.unit
def test_cur_aggregate_splits_credits_subscription_offset_and_ignores_tax():
    arn = f"arn:aws:identitystore:::user/{UUID1}"
    data = cur.aggregate([
        ("2026-10", cur_row("Usage", "USE1-KiroEnterprise-Credits", arn, amount=100.5)),
        ("2026-10", cur_row("Usage", "USE1-KiroEnterprise-Credits", arn, amount=50, day=dt.datetime(2026, 10, 6))),
        ("2026-10", cur_row("FlatRateSubscription", "USE1-KiroEnterprise-Power", arn, cost=200)),
        ("2026-10", cur_row("Credit", "USE1-KiroEnterprise-Power", None, cost=-200)),
        ("2026-10", cur_row("Tax", "USE1-KiroEnterprise-Power", None, cost=3)),
    ])
    assert data.users[UUID1]["2026-10"] == {"credits": 150.5, "sub": 200.0, "plan": "Power"}
    assert data.credit_offset == {"2026-10": -200} and data.sub_total == {"2026-10": 200}
    assert data.daily == {"2026-10-05": 100.5, "2026-10-06": 50}


@pytest.mark.unit
@pytest.mark.parametrize("prefix,expected", [
    ("cost", "cost/exp/data"), ("cur-data/123/", "cur-data/123//exp/data"), ("", "exp/data"), (None, "exp/data")])
def test_discover_export_builds_keys_like_aws(prefix, expected):
    source = cur.discover_export(FakeSession(FakeBcm(prefix)))
    assert source == cur.CurSource("b", expected, "exp")


@pytest.mark.unit
def test_discover_export_skips_non_parquet_or_without_resource_ids_and_name_mismatch():
    assert cur.discover_export(FakeSession(FakeBcm("x", fmt="CSV"))) is None
    assert cur.discover_export(FakeSession(FakeBcm("x", query="SELECT 1"))) is None
    assert cur.discover_export(FakeSession(FakeBcm("x")), name="other") is None


@pytest.mark.unit
def test_build_report_merges_sources_and_recommends_for_reference_month():
    months = ["2026-09", "2026-10", "2026-11"]
    cur_data = cur.CurData(
        {UUID1: {"2026-10": {"credits": 700.0, "sub": 200.0, "plan": "Power"}},
         UUID2: {"2026-10": {"credits": 0.0, "sub": 40.0, "plan": "ProPlus"}}},
        {"2026-10-05": 700.0}, {"2026-10": -240.0}, {"2026-10": 240.0})
    rows = [act_row(UUID1, "2026-10-05", 650, email="ana@example.com", overage=0),
            act_row(UUID1, "2026-10-06", 50, client="CLI", email="ana@example.com")]
    doc = model.build_report(meta={"account": "1"}, months=months, cur=cur_data, activity=rows, today=TODAY)

    ana = doc["people"][0]
    assert ana["user"] == "ana@example.com"
    assert ana["months"]["2026-10"]["credits"] == 700 and ana["months"]["2026-10"]["clients"] == ["CLI", "IDE"]
    assert ana["rec"] == {"to": "Pro", "saving": 180.0}
    assert doc["people"][1]["user"] == UUID2[:8] and doc["people"][1]["rec"]["to"] == "Pro"
    assert doc["meta"]["ref_month"] == "2026-10" and doc["meta"]["has_cur"] and doc["meta"]["has_activity"]
    assert doc["costs"]["2026-10"] == {"sub": 240.0, "offset": -240.0, "estimated": False}
    assert doc["activity"]["clients"] == ["CLI", "IDE"] and len(doc["activity"]["rows"]) == 2
    json.dumps(doc)  # must be serialisable


@pytest.mark.unit
def test_build_report_without_cur_estimates_cost_at_list_price():
    doc = model.build_report(meta={}, months=["2026-10"], cur=None, activity=[act_row(UUID1, "2026-10-05", 100)], today=TODAY)
    assert doc["meta"]["estimated_costs"] is True
    assert doc["costs"]["2026-10"] == {"sub": 200.0, "offset": 0.0, "estimated": True}


@pytest.mark.unit
def test_build_report_cur_only_has_no_activity_section_and_can_anonymize():
    cur_data = cur.CurData({UUID1: {"2026-10": {"credits": 5.0, "sub": 20.0, "plan": "Pro"}}}, {"2026-10-01": 5.0}, {}, {"2026-10": 20.0})
    doc = model.build_report(meta={}, months=["2026-10"], cur=cur_data, activity=None, names={UUID1: "ana"}, today=TODAY, anonymize=True)
    assert doc["activity"] is None and doc["meta"]["has_activity"] is False
    assert doc["people"][0]["user"] == "user-01"


@pytest.mark.unit
def test_current_month_is_not_the_reference_month_when_a_complete_one_exists():
    rows = [act_row(UUID1, "2026-10-05", 100), act_row(UUID1, "2026-11-02", 9000)]
    doc = model.build_report(meta={}, months=["2026-10", "2026-11"], cur=None, activity=rows, today=TODAY)
    assert doc["meta"]["ref_month"] == "2026-10"


@pytest.mark.unit
def test_mid_month_tier_change_counts_as_the_highest_tier():
    rows = [act_row(UUID1, "2026-10-05", 10, tier="PRO"), act_row(UUID1, "2026-10-20", 10, tier="POWER")]
    doc = model.build_report(meta={}, months=["2026-10"], cur=None, activity=rows, today=TODAY)
    assert doc["people"][0]["months"]["2026-10"]["plan"] == "Power"


@pytest.mark.unit
def test_demo_is_deterministic_and_complete():
    first, second = demo.make_demo(TODAY), demo.make_demo(TODAY)
    assert first == second
    assert first["meta"]["demo"] and len(first["people"]) == 12 and first["activity"]["rows"]
    assert set(first["activity"]["clients"]) == {"CLI", "IDE", "WEB"}
