"""Reader for the Kiro lines of an AWS Cost and Usage Report (Data Exports 2.0, parquet).

Kiro lines carry the IAM Identity Center user in ``line_item_resource_id``
(``arn:aws:identitystore:::user/<uuid>``), so the CUR alone gives per-user subscription
cost and credit usage.
"""
from __future__ import annotations

import collections
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections.abc import Iterable, Iterator

from .ids import normalize_user_id

CREDIT_PLAN = "Credits"
CUR_COLUMNS = [
    "line_item_product_code",
    "line_item_line_item_type",
    "line_item_usage_type",
    "line_item_resource_id",
    "line_item_usage_amount",
    "line_item_unblended_cost",
    "line_item_usage_start_date",
]


@dataclass(frozen=True)
class CurSource:
    """Where the parquet files of a CUR export live."""

    bucket: str
    base: str  # prefix up to and including ".../data"
    export: str


@dataclass(frozen=True)
class CurData:
    """Aggregated Kiro CUR lines.

    ``users``: user id -> month -> {"credits", "sub", "plan"}.
    ``daily``: 'YYYY-MM-DD' -> credits.  ``credit_offset`` / ``sub_total``: month -> USD.
    """

    users: dict[str, dict[str, dict[str, Any]]]
    daily: dict[str, float]
    credit_offset: dict[str, float]
    sub_total: dict[str, float]


def plan_of(usage_type: str) -> str:
    """'USE1-KiroEnterprise-Power' -> 'Power' (the region prefix varies)."""
    return usage_type.split("KiroEnterprise-", 1)[-1]


def aggregate(rows: Iterable[tuple[str, dict[str, Any]]]) -> CurData:
    """Group ``(month, cur_row)`` pairs into per-user/month, daily and cost totals."""
    users: dict[str, dict[str, dict[str, Any]]] = collections.defaultdict(
        lambda: collections.defaultdict(lambda: {"credits": 0.0, "sub": 0.0, "plans": set()})
    )
    daily: dict[str, float] = collections.defaultdict(float)
    offset: dict[str, float] = collections.defaultdict(float)
    sub_total: dict[str, float] = collections.defaultdict(float)

    for month, row in rows:
        kind = row["line_item_line_item_type"]
        cost = row["line_item_unblended_cost"] or 0.0
        amount = row["line_item_usage_amount"] or 0.0
        if kind == "Credit":
            offset[month] += cost
            continue
        resource = row["line_item_resource_id"]
        if kind == "Tax" or not resource:
            continue
        cell = users[normalize_user_id(resource)][month]
        plan = plan_of(row["line_item_usage_type"])
        if plan == CREDIT_PLAN:
            cell["credits"] += amount
            daily[row["line_item_usage_start_date"].date().isoformat()] += amount
        else:
            cell["plans"].add(plan)
            cell["sub"] += cost
            sub_total[month] += cost

    frozen_users = {
        uid: {
            month: {"credits": c["credits"], "sub": c["sub"], "plan": "/".join(sorted(c["plans"]))}
            for month, c in by_month.items()
        }
        for uid, by_month in users.items()
    }
    return CurData(frozen_users, dict(daily), dict(offset), dict(sub_total))


def discover_export(session: Any, name: str | None = None) -> CurSource | None:
    """Find a parquet Data Export that includes ``line_item_resource_id``."""
    client = session.client("bcm-data-exports", region_name="us-east-1")
    for item in client.list_exports()["Exports"]:
        if name and item["ExportName"] != name:
            continue
        export = client.get_export(ExportArn=item["ExportArn"])["Export"]
        query = export["DataQuery"]["QueryStatement"]
        dest = export["DestinationConfigurations"]["S3Destination"]
        if dest["S3OutputConfigurations"]["Format"] != "PARQUET" or "line_item_resource_id" not in query:
            continue
        # AWS builds keys as {S3Prefix}/{ExportName}/data without normalising slashes:
        # a trailing "/" in S3Prefix yields a literal "//" in the object keys.
        prefix = dest.get("S3Prefix") or ""
        base = f"{prefix}/{item['ExportName']}/data" if prefix else f"{item['ExportName']}/data"
        return CurSource(dest["S3Bucket"], base, item["ExportName"])
    return None


def list_month_files(s3: Any, source: CurSource, month: str) -> list[dict[str, Any]]:
    prefix = f"{source.base}/BILLING_PERIOD={month}/"
    paginator = s3.get_paginator("list_objects_v2")
    return [
        obj
        for page in paginator.paginate(Bucket=source.bucket, Prefix=prefix)
        for obj in page.get("Contents", [])
        if obj["Key"].endswith(".parquet")
    ]


def fetch_month(s3: Any, source: CurSource, month: str, cache: Path, force: bool) -> list[Path]:
    """Download a month's parquet files into ``cache`` (re-downloading if size changed)."""
    paths = []
    for obj in list_month_files(s3, source, month):
        target = cache / "cur" / source.bucket / month / Path(obj["Key"]).name
        if force or not target.exists() or target.stat().st_size != obj["Size"]:
            target.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(source.bucket, obj["Key"], str(target))
        paths.append(target)
    return paths


def read_kiro_rows(paths: Iterable[Path]) -> Iterator[dict[str, Any]]:
    """Yield only the Kiro rows of each parquet file (columns are projected)."""
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    for path in paths:
        table = pq.read_table(path, columns=CUR_COLUMNS)
        mask = pc.match_substring(pc.utf8_lower(table["line_item_product_code"]), "kiro")
        yield from table.filter(mask).to_pylist()
