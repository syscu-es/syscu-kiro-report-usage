"""Merge CUR and activity-report data into the JSON document the HTML template renders."""
from __future__ import annotations

import calendar
import collections
import datetime as dt
from dataclasses import asdict
from typing import Any

from . import engagement, forecast
from .activity import ActivityRow
from .cur import CurData
from .ids import normalize_user_id
from .periods import current_month
from .tiers import OVERAGE_RATE, TIERS, normalize_tier, recommend, tier_by_name

TOP_MODELS_PER_CELL = 5


def _cap(tier: str) -> int:
    found = tier_by_name(tier)
    return found.credits if found else 0


def _summarise_activity(
    rows: list[ActivityRow], months: set[str]
) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[str, str]]:
    """Per user/month totals plus the known e-mail of each user."""
    cells: dict[str, dict[str, dict[str, Any]]] = collections.defaultdict(dict)
    emails: dict[str, str] = {}
    for row in rows:
        month = row.date[:7]
        if month not in months:
            continue
        uid = normalize_user_id(row.user_id)
        if row.email:
            emails[uid] = row.email
        cell = cells[uid].setdefault(
            month,
            {"credits": 0.0, "overage": 0.0, "messages": 0, "tier": "",
             "clients": set(), "models": collections.Counter()},
        )
        cell["credits"] += row.credits
        cell["overage"] += row.overage
        cell["messages"] += row.messages
        tier = normalize_tier(row.tier)
        if not cell["tier"] or _cap(tier) > _cap(cell["tier"]):
            cell["tier"] = tier  # a licence that changed tier mid-month counts as its highest
        cell["clients"].add(row.client)
        for name, count in row.models:
            cell["models"][name] += count
    return cells, emails


def _person_month(act: dict[str, Any] | None, cur: dict[str, Any] | None, has_cur: bool) -> dict[str, Any]:
    credits = act["credits"] if act else (cur or {"credits": 0.0})["credits"]
    plan = (act["tier"] if act and act["tier"] else normalize_tier(cur["plan"]) if cur else "") or "-"
    tier = tier_by_name(plan)
    if has_cur:
        sub = cur["sub"] if cur else 0.0
    else:
        sub = tier.price if tier else 0.0  # estimated at list price
    cap = tier.credits if tier else 0
    return {
        "credits": round(credits, 1),
        "sub": round(sub, 2),
        "plan": plan,
        "overage": round(act["overage"], 1) if act else 0.0,
        "messages": act["messages"] if act else 0,
        "clients": sorted(act["clients"]) if act else [],
        "models": [n for n, _ in act["models"].most_common(TOP_MODELS_PER_CELL)] if act else [],
        "util": round(credits / cap * 100, 1) if cap else 0.0,
    }


def build_report(
    *,
    meta: dict[str, Any],
    months: list[str],
    cur: CurData | None,
    activity: list[ActivityRow] | None,
    names: dict[str, str] | None = None,
    today: dt.date | None = None,
    anonymize: bool = False,
) -> dict[str, Any]:
    """Build the report document (everything JSON-serialisable)."""
    today = today or dt.date.today()
    names = names or {}
    activity = activity or None
    month_set = set(months)
    cells, emails = _summarise_activity(activity or [], month_set)
    cur_users = cur.users if cur else {}

    people: list[dict[str, Any]] = []
    uids: list[str] = []
    for uid in set(cells) | set(cur_users):
        by_month = {}
        for month in months:
            act, cur_cell = cells.get(uid, {}).get(month), cur_users.get(uid, {}).get(month)
            if act or cur_cell:
                by_month[month] = _person_month(act, cur_cell, cur is not None)
        if by_month:
            people.append({"user": emails.get(uid) or names.get(uid) or uid[:8], "months": by_month})
            uids.append(uid)

    order = sorted(range(len(people)), key=lambda i: -sum(m["credits"] for m in people[i]["months"].values()))
    people = [people[i] for i in order]
    uids = [uids[i] for i in order]

    with_data = [m for m in months if any(m in p["months"] for p in people)]
    complete = [m for m in with_data if m < current_month(today)]
    ref_month = complete[-1] if complete else (with_data[-1] if with_data else None)
    for index, person in enumerate(people):
        if anonymize:
            person["user"] = f"user-{index + 1:02d}"
        cell = person["months"].get(ref_month) if ref_month else None
        rec = recommend(cell["plan"], cell["credits"]) if cell else None
        person["rec"] = asdict(rec) if rec else None

    index = dict(zip(uids, range(len(uids)), strict=True))
    eng, period_days = engagement.summarise(activity or [], index, month_set)
    covered = {r.date[:7] for r in (activity or []) if r.date[:7] in month_set}
    for position, person in enumerate(people):
        if position in eng:
            person["eng"] = eng[position]
        elif covered & set(person["months"]):
            person["eng"] = engagement.empty_stats()  # licensed in a month the activity report covers, yet silent
        else:
            person["eng"] = None  # no activity data for this user's months: not the same as idle

    costs = {}
    for month in with_data:
        if cur:
            costs[month] = {"sub": round(cur.sub_total.get(month, 0.0), 2),
                            "offset": round(cur.credit_offset.get(month, 0.0), 2), "estimated": False}
        else:
            subtotal = sum(p["months"].get(month, {}).get("sub", 0.0) for p in people)
            costs[month] = {"sub": round(subtotal, 2), "offset": 0.0, "estimated": True}

    activity_doc = _activity_document(activity, index, month_set)
    cur_daily = {d: round(v, 1) for d, v in sorted((cur.daily if cur else {}).items())}
    dates = list(cur_daily) + [r[0] for r in (activity_doc["rows"] if activity_doc else [])]

    proj_month = current_month(today) if current_month(today) in with_data else None
    last_data = max(dates) if dates else ""
    elapsed = int(last_data[8:10]) if proj_month and last_data[:7] == proj_month else 0
    in_month = calendar.monthrange(int(today.year), int(today.month))[1]
    for person in people:
        cell = person["months"].get(proj_month) if proj_month else None
        result = forecast.project_month(cell["credits"], elapsed, in_month, cell["plan"]) if cell else None
        person["proj"] = {"month": proj_month, **result} if result else None

    return {
        "meta": {
            **meta,
            "months": months,
            "ref_month": ref_month,
            "has_cur": cur is not None,
            "has_activity": activity_doc is not None,
            "estimated_costs": cur is None,
            "first_date": min(dates) if dates else "-",
            "last_date": max(dates) if dates else "-",
            "generated": today.isoformat(),
            "tiers": [asdict(t) for t in TIERS],
            "overage_rate": OVERAGE_RATE,
            "period_days": period_days,
            "proj_month": proj_month,
            "proj_elapsed": elapsed,
            "thresholds": engagement.thresholds(period_days) if eng else None,
        },
        "people": people,
        "activity": activity_doc,
        "cur_daily": cur_daily,
        "costs": costs,
    }


def _activity_document(
    activity: list[ActivityRow] | None, index: dict[str, int], months: set[str]
) -> dict[str, Any] | None:
    rows = [r for r in (activity or []) if r.date[:7] in months and normalize_user_id(r.user_id) in index]
    if not rows:
        return None
    clients = sorted({r.client for r in rows})
    tiers = sorted({normalize_tier(r.tier) for r in rows}, key=lambda t: (_cap(t), t))
    models = sorted({name for r in rows for name, _ in r.models})
    mi = {m: i for i, m in enumerate(models)}
    packed = [
        [
            r.date,
            index[normalize_user_id(r.user_id)],
            clients.index(r.client),
            tiers.index(normalize_tier(r.tier)),
            round(r.credits, 2),
            round(r.overage, 2),
            r.messages,
            r.conversations,
            1 if r.new_user else 0,
            {str(mi[name]): n for name, n in r.models},
        ]
        for r in sorted(rows, key=lambda r: (r.date, r.client, r.user_id))
    ]
    return {"clients": clients, "tiers": tiers, "models": models, "rows": packed}
