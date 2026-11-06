"""Kiro Enterprise plan catalogue and tier right-sizing logic.

Prices and allowances follow the public Kiro Enterprise pricing (subject to change):
Pro 1,000 credits / $20, Pro+ 2,000 / $40, Pro Max 5,000 / $100, Power 10,000 / $200,
with overage billed at $0.04 per credit.
"""
from __future__ import annotations

from dataclasses import dataclass

OVERAGE_RATE = 0.04
_EPSILON = 0.005


@dataclass(frozen=True)
class Tier:
    name: str
    credits: int
    price: float


@dataclass(frozen=True)
class Recommendation:
    to: str
    saving: float


TIERS: tuple[Tier, ...] = (
    Tier("Pro", 1000, 20.0),
    Tier("ProPlus", 2000, 40.0),
    Tier("ProMax", 5000, 100.0),
    Tier("Power", 10000, 200.0),
)
_BY_KEY = {t.name.lower(): t for t in TIERS}


def _key(raw: str) -> str:
    """Lowercase alphanumerics, with '+' spelled out so 'Pro+' == 'ProPlus'."""
    return "".join(ch for ch in (raw or "").lower().replace("+", "plus") if ch.isalnum())


def normalize_tier(raw: str) -> str:
    """Map every spelling Kiro uses (PRO_PLUS, ProPlus, Pro+, ...) to a catalogue name.

    Unknown values are returned as written so they still show up in the report.
    """
    tier = _BY_KEY.get(_key(raw))
    if tier:
        return tier.name
    return (raw or "").strip() or "Unknown"


def tier_by_name(name: str) -> Tier | None:
    return _BY_KEY.get(_key(name))


def monthly_cost(tier: Tier, credits: float) -> float:
    """Subscription price plus overage for ``credits`` used in a month."""
    return tier.price + max(0.0, credits - tier.credits) * OVERAGE_RATE


def recommend(tier_name: str, credits: float) -> Recommendation | None:
    """Cheapest tier for ``credits``; ``None`` when the current tier is already optimal
    or unknown."""
    current = tier_by_name(tier_name)
    if current is None:
        return None
    best = min(TIERS, key=lambda t: (monthly_cost(t, credits), t.price))
    saving = monthly_cost(current, credits) - monthly_cost(best, credits)
    if best.name == current.name or saving < _EPSILON:
        return None
    return Recommendation(best.name, round(saving, 2))
