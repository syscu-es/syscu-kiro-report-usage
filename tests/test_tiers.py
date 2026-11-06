import pytest

from kiro_report import tiers


@pytest.mark.unit
@pytest.mark.parametrize("raw,expected", [
    ("PRO_PLUS", "ProPlus"), ("ProPlus", "ProPlus"), ("Pro+", "ProPlus"), ("pro plus", "ProPlus"),
    ("PRO_MAX", "ProMax"), ("ProMax", "ProMax"), ("POWER", "Power"), ("pro", "Pro"),
    ("Enterprise-X", "Enterprise-X"), ("", "Unknown"),
])
def test_normalize_tier_accepts_every_spelling(raw, expected):
    assert tiers.normalize_tier(raw) == expected


@pytest.mark.unit
def test_monthly_cost_adds_overage_only_above_allowance():
    pro = tiers.tier_by_name("Pro")
    assert tiers.monthly_cost(pro, 500) == 20
    assert tiers.monthly_cost(pro, 1500) == pytest.approx(20 + 500 * 0.04)


@pytest.mark.unit
def test_recommend_downgrade_for_idle_power_user():
    rec = tiers.recommend("Power", 800)
    assert rec == tiers.Recommendation("Pro", 180.0)


@pytest.mark.unit
def test_recommend_upgrade_skips_tiers_when_cheaper():
    # Pro: 20 + 2000*0.04 = 100; ProPlus: 40 + 1000*0.04 = 80; ProMax: 100 -> ProPlus saves 20
    rec = tiers.recommend("Pro", 3000)
    assert rec is not None and rec.to == "ProPlus" and rec.saving == pytest.approx(20.0)


@pytest.mark.unit
def test_recommend_none_when_optimal_or_unknown():
    assert tiers.recommend("ProMax", 4500) is None
    assert tiers.recommend("Mystery", 100) is None
