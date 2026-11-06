import datetime as dt
import io

import pytest

from kiro_report import activity

HEADER = ("Date,UserId,Client_Type,Chat_Conversations,Credits_Used,Overage_Cap,Overage_Credits_Used,"
          "Overage_Enabled,ProfileId,Subscription_Tier,Total_Messages,New_User,User_Email,Usage_Limit,"
          "auto_messages,claude_sonnet_5_messages,gpt_5.6_messages")
CSV_TEXT = "\n".join([
    HEADER,
    "2026-10-05,d-123.aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee,KIRO_IDE,3,120.5,0,10,true,p,PRO_PLUS,40,false,ana@example.com,2000,25,15,0",
    "2026-10-05,u2,KIRO_CLI,1,5,0,0,false,p,POWER,4,true,,10000,4,0,0",
    ",missing-date,KIRO_IDE,1,1,0,0,false,p,PRO,1,false,,1000,1,0,0",
])
BASE = "reports/reports/AWSLogs/111122223333/KiroLogs/user_report/us-east-1"


def key(client, day, hour="00"):
    y, m, d = day.split("-")
    return f"{BASE}/{y}/{m}/{d}/{hour}/{client}_111122223333_user_report_{y}{m}{d}{hour}00.csv"


class FakeS3:
    """Minimal S3 stand-in: list_buckets, list_objects_v2 paginator, get_object."""

    def __init__(self, objects, buckets=("my-kiro-bucket",)):
        self.objects, self.buckets, self.reads = objects, buckets, []

    def list_buckets(self):
        return {"Buckets": [{"Name": b} for b in self.buckets] + [{"Name": "unrelated"}]}

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, Bucket, Prefix="", Delimiter=None):
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        if Delimiter:
            prefixes = sorted({Prefix + k[len(Prefix):].split(Delimiter)[0] + Delimiter for k in keys})
            return [{"CommonPrefixes": [{"Prefix": p} for p in prefixes]}]
        return [{"Contents": [{"Key": k, "Size": len(self.objects[k])} for k in keys]}]

    def get_object(self, Bucket, Key):
        self.reads.append(Key)
        return {"Body": io.BytesIO(self.objects[Key].encode())}


@pytest.mark.unit
def test_parse_report_reads_real_schema_and_skips_incomplete_rows():
    rows = activity.parse_report(CSV_TEXT)
    assert len(rows) == 2
    first = rows[0]
    assert (first.date, first.client, first.tier, first.email) == ("2026-10-05", "IDE", "PRO_PLUS", "ana@example.com")
    assert (first.credits, first.overage, first.messages, first.conversations) == (120.5, 10.0, 40, 3)
    assert first.models == (("auto", 25), ("claude_sonnet_5", 15))
    assert rows[1].new_user is True and rows[1].client == "CLI"


@pytest.mark.unit
def test_parse_report_uses_client_hint_and_tolerates_bom_and_commas():
    text = "﻿date,userid,credits_used\n2026-10-01,u1,\"1,250.5\"\n"
    row = activity.parse_report(text, "WEB")[0]
    assert row.client == "WEB" and row.credits == 1250.5 and row.models == ()


@pytest.mark.unit
@pytest.mark.parametrize("raw,expected", [("KIRO_IDE", "IDE"), ("kiro_cli", "CLI"), ("PLUGIN", "PLUGIN"), ("", "UNKNOWN")])
def test_normalize_client(raw, expected):
    assert activity.normalize_client(raw) == expected


@pytest.mark.unit
def test_key_regex_extracts_base_account_and_client():
    match = activity.KEY_RE.match(key("KIRO_IDE", "2026-10-05"))
    assert match["base"] == "reports/reports/" and match["account"] == "111122223333" and match["client"] == "KIRO_IDE"
    assert activity.KEY_RE.match("reports/by_user_analytic/2026/10/05/00/x_report.csv") is None


@pytest.mark.unit
def test_discover_scans_only_kiro_named_buckets_and_finds_location():
    s3 = FakeS3({"noise/file.txt": "", key("KIRO_IDE", "2026-10-05"): CSV_TEXT})
    found = activity.discover(s3)
    assert found.location == activity.ReportLocation("my-kiro-bucket", "reports/reports/", "111122223333")
    assert found.candidates == ("my-kiro-bucket",)


@pytest.mark.unit
def test_discover_reports_candidates_when_bucket_is_empty():
    found = activity.discover(FakeS3({}))
    assert found.location is None and found.candidates == ("my-kiro-bucket",)


@pytest.mark.unit
def test_discover_with_explicit_bucket_prefix_and_account_skips_scanning():
    found = activity.discover(FakeS3({}), bucket="b", prefix="p", account="1")
    assert found.location == activity.ReportLocation("b", "p/", "1")


@pytest.mark.unit
def test_find_in_bucket_respects_scan_cap():
    s3 = FakeS3({f"a/{i}.txt": "" for i in range(5)} | {key("KIRO_IDE", "2026-10-05"): CSV_TEXT})
    assert activity.find_in_bucket(s3, "b", max_scan=3) is None


@pytest.mark.unit
def test_load_activity_filters_months_and_caches_final_reports(tmp_path):
    objects = {
        key("KIRO_IDE", "2026-10-05"): CSV_TEXT,
        key("KIRO_CLI", "2026-09-30"): HEADER + "\n2026-09-30,u9,KIRO_CLI,1,1,0,0,false,p,PRO,1,false,,1000,1,0,0\n",
    }
    s3, loc = FakeS3(objects), activity.ReportLocation("my-kiro-bucket", "reports/reports/", "111122223333")
    today = dt.date(2026, 11, 6)
    rows = activity.load_activity(s3, loc, ["2026-10"], cache=tmp_path, today=today)
    assert {r.date for r in rows} == {"2026-10-05"} and len(rows) == 2
    activity.load_activity(s3, loc, ["2026-10"], cache=tmp_path, today=today)
    assert s3.reads.count(key("KIRO_IDE", "2026-10-05")) == 1  # second run served from cache


@pytest.mark.unit
def test_recent_reports_are_not_cached(tmp_path):
    day = "2026-11-06"
    s3 = FakeS3({key("KIRO_IDE", day): CSV_TEXT})
    loc = activity.ReportLocation("my-kiro-bucket", "reports/reports/", "111122223333")
    for _ in range(2):
        activity.load_activity(s3, loc, ["2026-11"], cache=tmp_path, today=dt.date(2026, 11, 6))
    assert s3.reads.count(key("KIRO_IDE", day)) == 2
