"""Per-user engagement metrics derived from the Kiro user activity report.

Segments (power / active / light / idle) are inspired by the usage tiers of the AWS sample
dashboard (https://github.com/aws-samples/sample-kiro-user-analytics-dashboard). Message and
conversation counts turned out to be a poor yardstick on real data (they range from a handful
to tens of thousands, and chats can be opened without using credits), so when the plan is known
a user is segmented by how much of the plan allowance they consumed in the period. Absolute
message/conversation thresholds, scaled to the period length, remain as the fallback for users
whose plan is unknown.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any

from .activity import ActivityRow
from .ids import normalize_user_id
from .tiers import normalize_tier, tier_by_name

SEGMENTS = ("power", "active", "light", "idle")
POWER_MESSAGES = 100
POWER_CONVERSATIONS = 20
ACTIVE_MESSAGES = 20
ACTIVE_CONVERSATIONS = 5
POWER_USE_PCT = 50
ACTIVE_USE_PCT = 10
_BASE_DAYS = 30


def thresholds(period_days: int) -> dict[str, int]:
    """Segment thresholds: plan use in percent, plus message/conversation fallbacks that scale
    with the period (never below the 30-day baseline)."""
    scale = max(1.0, period_days / _BASE_DAYS)
    return {
        "power_use": POWER_USE_PCT,
        "active_use": ACTIVE_USE_PCT,
        "power_messages": round(POWER_MESSAGES * scale),
        "power_conversations": round(POWER_CONVERSATIONS * scale),
        "active_messages": round(ACTIVE_MESSAGES * scale),
        "active_conversations": round(ACTIVE_CONVERSATIONS * scale),
    }


def segment_of(
    messages: int, conversations: int, period_days: int, *, credits: float = 0.0, cap: int = 0
) -> str:
    """Engagement segment of a user from their totals over the period.

    With a known plan allowance (``cap`` credits per 30 days) the share of the allowance used
    in the period decides; otherwise the message/conversation thresholds do.
    """
    if cap > 0:
        use = credits / (cap * max(period_days, 1) / _BASE_DAYS) * 100
        if use >= POWER_USE_PCT:
            return "power"
        if use >= ACTIVE_USE_PCT:
            return "active"
        return "light" if credits > 0 or messages > 0 else "idle"
    limit = thresholds(period_days)
    if messages >= limit["power_messages"] or conversations >= limit["power_conversations"]:
        return "power"
    if messages >= limit["active_messages"] or conversations >= limit["active_conversations"]:
        return "active"
    return "light" if messages > 0 else "idle"


def empty_stats() -> dict[str, Any]:
    """Engagement of a licensed user with no activity at all."""
    return {"messages": 0, "conversations": 0, "credits": 0.0, "use": None, "active_days": 0,
            "first_date": "", "last_date": "", "days_since_last": None, "segment": "idle"}


def summarise(
    rows: Iterable[ActivityRow], index: dict[str, int], months: set[str]
) -> tuple[dict[int, dict[str, Any]], int]:
    """Engagement per person index plus the length (days) of the observed period.

    Recency is measured against the last day with data, not today, so a report is
    reproducible. Users present in ``index`` but without rows are not returned: callers
    fill them with :func:`empty_stats`.
    """
    scoped = [r for r in rows if r.date[:7] in months and normalize_user_id(r.user_id) in index]
    if not scoped:
        return {}, 0
    first = min(r.date for r in scoped)
    last = max(r.date for r in scoped)
    period_days = (dt.date.fromisoformat(last) - dt.date.fromisoformat(first)).days + 1

    totals: dict[int, dict[str, Any]] = {}
    for r in scoped:
        entry = totals.setdefault(
            index[normalize_user_id(r.user_id)],
            {"messages": 0, "conversations": 0, "credits": 0.0, "cap": 0, "days": set(), "first": "", "last": ""},
        )
        tier = tier_by_name(normalize_tier(r.tier))
        entry["cap"] = max(entry["cap"], tier.credits if tier else 0)  # a mid-period upgrade counts as its highest plan
        entry["credits"] += r.credits
        entry["messages"] += r.messages
        entry["conversations"] += r.conversations
        if r.messages > 0 or r.credits > 0:
            entry["days"].add(r.date)
            entry["first"] = min(entry["first"] or r.date, r.date)
            entry["last"] = max(entry["last"], r.date)

    end = dt.date.fromisoformat(last)
    stats: dict[int, dict[str, Any]] = {}
    for person, entry in totals.items():
        since = (end - dt.date.fromisoformat(entry["last"])).days if entry["last"] else None
        allowance = entry["cap"] * period_days / _BASE_DAYS
        stats[person] = {
            "messages": entry["messages"],
            "conversations": entry["conversations"],
            "credits": round(entry["credits"], 1),
            "use": round(entry["credits"] / allowance * 100, 1) if allowance else None,
            "active_days": len(entry["days"]),
            "first_date": entry["first"],
            "last_date": entry["last"],
            "days_since_last": since,
            "segment": segment_of(entry["messages"], entry["conversations"], period_days,
                                  credits=entry["credits"], cap=entry["cap"]),
        }
    return stats, period_days
