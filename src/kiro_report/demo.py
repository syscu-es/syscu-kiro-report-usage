"""Synthetic data so the report can be previewed without any AWS access."""
from __future__ import annotations

import datetime as dt
import random
import uuid
from typing import Any

from .activity import ActivityRow
from .cur import CurData
from .model import build_report
from .periods import month_range, shift_month
from .tiers import TIERS

_USERS = [
    ("ana.ruiz", "Power", 1.0), ("ben.cole", "Power", 0.9), ("carla.mendez", "Power", 0.7),
    ("dev.patel", "ProMax", 0.8), ("elena.sosa", "ProMax", 0.5), ("farid.khan", "ProPlus", 0.9),
    ("gus.lin", "ProPlus", 0.4), ("hana.sato", "ProPlus", 0.2), ("ivan.petrov", "Pro", 0.3),
    ("julia.rossi", "Pro", 0.1), ("kofi.mensah", "Power", 0.05), ("lena.berg", "Pro", 0.0),
]
_MODELS = ["auto", "claude_sonnet_5", "claude_opus_5", "gpt_5.6"]
_DAY_SPAN = 80


def make_demo(
    today: dt.date | None = None, months_back: int = 3, seed: int = 7
) -> dict[str, Any]:
    """Run the real pipeline on generated, deterministic data."""
    today = today or dt.date.today()
    rng = random.Random(seed)
    end = today.strftime("%Y-%m")
    months = month_range(shift_month(end, -(months_back - 1)), end)
    first_day = max(today - dt.timedelta(days=_DAY_SPAN), dt.date.fromisoformat(months[0] + "-01"))

    rows: list[ActivityRow] = []
    month_credits: dict[tuple[str, str], float] = {}
    for name, tier, intensity in _USERS:
        cap = next(t.credits for t in TIERS if t.name == tier)
        for offset in range((today - first_day).days + 1):
            day = first_day + dt.timedelta(days=offset)
            if day.weekday() >= 5 or rng.random() > 0.35 + 0.6 * intensity:
                continue
            for client, share in (("IDE", 1.0), ("CLI", 0.35), ("WEB", 0.08)):
                if rng.random() > share:
                    continue
                credits = round(intensity * rng.uniform(15, 130), 2)
                key = (name, day.strftime("%Y-%m"))
                before = month_credits.get(key, 0.0)
                month_credits[key] = before + credits
                overage = max(0.0, month_credits[key] - max(before, cap))
                msgs = int(credits * rng.uniform(0.8, 1.6))
                models = tuple((m, max(1, msgs // len(_MODELS))) for m in _MODELS if rng.random() > 0.4)
                rows.append(ActivityRow(day.isoformat(), name, f"{name}@example.com", client, tier,
                                        credits, round(overage, 2), msgs, msgs // 12 if msgs else 0,
                                        offset == 0, models))

    uid = {name: str(uuid.uuid5(uuid.NAMESPACE_DNS, name)) for name, _, _ in _USERS}
    cur_users: dict[str, dict[str, dict[str, Any]]] = {}
    sub_total = {m: 0.0 for m in months}
    daily: dict[str, float] = {}
    for name, tier, _ in _USERS:
        price = next(t.price for t in TIERS if t.name == tier)
        cur_users[uid[name]] = {m: {"credits": 0.0, "sub": price, "plan": tier} for m in months}
        for m in months:
            sub_total[m] += price
    for row in rows:
        cur_users[uid[row.user_id]][row.date[:7]]["credits"] += row.credits
        daily[row.date] = daily.get(row.date, 0.0) + row.credits

    # the activity report carries the Identity Center id, as the real report does
    activity = [
        ActivityRow(r.date, uid[r.user_id], r.email, r.client, r.tier, r.credits, r.overage,
                    r.messages, r.conversations, r.new_user, r.models)
        for r in rows
    ]
    cur = CurData(cur_users, daily, {m: -v for m, v in sub_total.items()}, sub_total)
    meta = {"account": "123456789012", "source_cur": "demo-cur-export",
            "source_activity": "demo-kiro-activity-bucket", "demo": True}
    return build_report(meta=meta, months=months, cur=cur, activity=activity, today=today)
