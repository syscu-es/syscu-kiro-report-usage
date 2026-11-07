"""Reader for the Kiro *user activity report* (daily CSVs delivered to S3).

Enable it in the Kiro console (Settings -> User activity report, CSV). Kiro writes one
CSV per client type and day under
``<prefix>/AWSLogs/<account>/KiroLogs/user_report/<region>/<yyyy>/<mm>/<dd>/<hh>/``
named ``KIRO_IDE_<account>_user_report_<yyyymmddhh00>.csv`` (``KIRO_CLI``/``KIRO_WEB``
for the other clients). Header::

    Date,UserId,Client_Type,Chat_Conversations,Credits_Used,Overage_Cap,
    Overage_Credits_Used,Overage_Enabled,ProfileId,Subscription_Tier,Total_Messages,
    New_User,User_Email,Usage_Limit,<model>_messages,...

Model columns are dynamic (``auto_messages``, ``claude_sonnet_5_messages``, ...).
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections.abc import Callable
from collections.abc import Iterable

from .periods import month_bounds

KEY_RE = re.compile(
    r"^(?P<base>.*?)AWSLogs/(?P<account>\d+)/KiroLogs/user_report/(?P<region>[^/]+)/"
    r"(?P<y>\d{4})/(?P<m>\d{2})/(?P<d>\d{2})/(?P<h>\d{2})/"
    r"(?P<client>[A-Z_]+?)_\d+_user_report_\d+(?:_part\d+)?\.csv$"
)
DEFAULT_MAX_SCAN = 5000
_CACHE_SAFE_AFTER_DAYS = 2  # reports older than this are final and can be cached


@dataclass(frozen=True)
class ReportLocation:
    bucket: str
    base: str  # key prefix before "AWSLogs/" ('' or ending with '/')
    account: str


@dataclass(frozen=True)
class Discovery:
    location: ReportLocation | None
    candidates: tuple[str, ...]  # buckets that looked like Kiro report buckets


@dataclass(frozen=True)
class ReportKey:
    key: str
    date: str
    client: str


@dataclass(frozen=True)
class ActivityRow:
    date: str
    user_id: str
    email: str
    client: str
    tier: str
    credits: float
    overage: float
    messages: int
    conversations: int
    new_user: bool
    models: tuple[tuple[str, int], ...]


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def normalize_client(raw: str) -> str:
    """'KIRO_IDE' -> 'IDE'."""
    text = (raw or "").strip().upper()
    return text[5:] if text.startswith("KIRO_") else (text or "UNKNOWN")


def _num(value: Any) -> float:
    try:
        return float(str(value).replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def parse_report(text: str, client_hint: str = "") -> list[ActivityRow]:
    """Parse one activity CSV. Header names are matched case-insensitively."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    rows: list[ActivityRow] = []
    for raw in reader:
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if not row.get("date") or not row.get("userid"):
            continue
        models = tuple(
            (name[: -len("_messages")], int(_num(value)))
            for name, value in row.items()
            if name.endswith("_messages") and name != "total_messages" and _num(value) > 0
        )
        rows.append(
            ActivityRow(
                date=row["date"][:10],
                user_id=row["userid"],
                email=row.get("user_email", ""),
                client=normalize_client(row.get("client_type") or client_hint),
                tier=row.get("subscription_tier", ""),
                credits=_num(row.get("credits_used")),
                overage=_num(row.get("overage_credits_used")),
                messages=int(_num(row.get("total_messages"))),
                conversations=int(_num(row.get("chat_conversations"))),
                new_user=_truthy(row.get("new_user", "")),
                models=models,
            )
        )
    return rows


# --------------------------------------------------------------------------- #
# S3 discovery and download
# --------------------------------------------------------------------------- #
def find_in_bucket(s3: Any, bucket: str, max_scan: int = DEFAULT_MAX_SCAN) -> ReportLocation | None:
    """Scan up to ``max_scan`` keys of ``bucket`` for an activity-report object."""
    scanned = 0
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            match = KEY_RE.match(obj["Key"])
            if match:
                return ReportLocation(bucket, match["base"], match["account"])
            scanned += 1
            if scanned >= max_scan:
                return None
    return None


def discover(
    s3: Any,
    *,
    bucket: str | None = None,
    prefix: str | None = None,
    account: str | None = None,
    max_scan: int = DEFAULT_MAX_SCAN,
) -> Discovery:
    """Locate the activity reports.

    With ``bucket`` (and optionally ``prefix``/``account``) only that bucket is checked;
    otherwise every bucket whose name contains "kiro" is scanned.
    """
    if bucket and prefix is not None and account:
        base = prefix if not prefix or prefix.endswith("/") else prefix + "/"
        return Discovery(ReportLocation(bucket, base, account), (bucket,))
    names = [bucket] if bucket else [
        b["Name"] for b in s3.list_buckets().get("Buckets", []) if "kiro" in b["Name"].lower()
    ]
    for name in names:
        location = find_in_bucket(s3, name, max_scan)
        if location:
            return Discovery(location, tuple(names))
    return Discovery(None, tuple(names))


def list_report_keys(s3: Any, location: ReportLocation, months: Iterable[str]) -> list[ReportKey]:
    """List the report objects of the given months across every region."""
    root = f"{location.base}AWSLogs/{location.account}/KiroLogs/user_report/"
    paginator = s3.get_paginator("list_objects_v2")
    regions = [
        p["Prefix"]
        for page in paginator.paginate(Bucket=location.bucket, Prefix=root, Delimiter="/")
        for p in page.get("CommonPrefixes", [])
    ]
    keys: list[ReportKey] = []
    for region in regions:
        for month in months:
            prefix = f"{region}{month[:4]}/{month[5:7]}/"
            for page in paginator.paginate(Bucket=location.bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    match = KEY_RE.match(obj["Key"])
                    if match:
                        date = f"{match['y']}-{match['m']}-{match['d']}"
                        keys.append(ReportKey(obj["Key"], date, normalize_client(match["client"])))
    return sorted(keys, key=lambda k: (k.date, k.client, k.key))


def fetch_text(
    s3: Any, bucket: str, item: ReportKey, cache: Path | None, today: dt.date
) -> str:
    """Download a report, caching it on disk once it is old enough to be final."""
    target = cache / "activity" / bucket / item.key if cache else None
    final = dt.date.fromisoformat(item.date) <= today - dt.timedelta(days=_CACHE_SAFE_AFTER_DAYS)
    if target and final and target.exists():
        return target.read_text(encoding="utf-8")
    body = s3.get_object(Bucket=bucket, Key=item.key)["Body"].read().decode("utf-8-sig")
    if target and final:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    return body


def load_activity(
    s3: Any,
    location: ReportLocation,
    months: list[str],
    *,
    cache: Path | None = None,
    today: dt.date | None = None,
    progress: Callable[[str], None] = lambda _msg: None,
) -> list[ActivityRow]:
    """Fetch and parse every report of ``months``; rows outside the months are dropped."""
    today = today or dt.date.today()
    first, last = month_bounds(months[0])[0], month_bounds(months[-1])[1]
    items = list_report_keys(s3, location, months)
    progress(f"  activity: {len(items)} report file(s)")
    rows: list[ActivityRow] = []
    for item in items:
        for row in parse_report(fetch_text(s3, location.bucket, item, cache, today), item.client):
            if first.isoformat() <= row.date <= last.isoformat():
                rows.append(row)
    return rows
