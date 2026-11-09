"""End-of-month projection of a user's credits and overage from the month-to-date pace."""
from __future__ import annotations

from .tiers import OVERAGE_RATE, tier_by_name

MIN_ELAPSED_DAYS = 5  # a pace measured over fewer days is mostly noise


def project_month(
    credits: float, elapsed_days: int, days_in_month: int, plan: str
) -> dict[str, float | int] | None:
    """Project the month's credits at the current pace and price the expected overage.

    Returns ``None`` when the pace is not reliable (too few days, no usage) or the plan
    (hence the allowance) is unknown.
    """
    tier = tier_by_name(plan)
    if tier is None or credits <= 0 or elapsed_days < MIN_ELAPSED_DAYS:
        return None
    projected = credits / elapsed_days * days_in_month
    over = max(0.0, projected - tier.credits)
    return {
        "credits": round(projected, 1),
        "cap": tier.credits,
        "use": round(projected / tier.credits * 100, 1),
        "over_credits": round(over, 1),
        "over_cost": round(over * OVERAGE_RATE, 2),
    }
