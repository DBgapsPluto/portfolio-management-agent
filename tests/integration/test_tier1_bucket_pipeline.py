"""Tier 1 end-to-end: 8-bucket factor model → allocator → mandate check."""
import pytest
from datetime import date
from tradingagents.skills.research.factor_to_bucket import (
    apply_factor_model_with_safety, INITIAL_BASELINE, BUCKETS,
)


def test_factor_model_returns_8_bucket_target():
    """All-zero factor z → INITIAL_BASELINE."""
    factor_z = {f: 0.0 for f in [
        "F1_growth", "F2_inflation", "F3_real_rate", "F4_term_premium",
        "F5_credit_cycle", "F6_krw_regime", "F7_equity_vol_regime",
        "F8_valuation", "F9_market_dispersion", "F10_systemic_liquidity",
        "F11_earnings_revision", "F12_china_credit_impulse",
    ]}
    bucket, tips, contribs, diag = apply_factor_model_with_safety(factor_z)
    assert set(bucket.keys()) == set(BUCKETS)
    for b, w in INITIAL_BASELINE.items():
        assert abs(bucket[b] - w) < 1e-9


def test_factor_shock_keeps_mandate_compliance():
    """Large F1 shock — risk bias — but mandate cap holds."""
    factor_z = {f: 0.0 for f in [
        "F1_growth", "F2_inflation", "F3_real_rate", "F4_term_premium",
        "F5_credit_cycle", "F6_krw_regime", "F7_equity_vol_regime",
        "F8_valuation", "F9_market_dispersion", "F10_systemic_liquidity",
        "F11_earnings_revision", "F12_china_credit_impulse",
    ]}
    factor_z["F1_growth"] = 3.0  # extreme growth shock
    bucket, _, _, _ = apply_factor_model_with_safety(factor_z)
    risk_sum = sum(bucket[b] for b in ("kr_equity", "global_equity",
                                        "precious_metals", "cyclical_commodity_fx"))
    assert risk_sum <= 0.70 + 1e-6  # mandate cap


def test_188_universe_classification_coverage():
    """Sanity: ≥ 85% of universe ETFs classify into 8 buckets."""
    import json
    from pathlib import Path
    universe_path = Path("data/universe/universe.json")
    if not universe_path.exists():
        pytest.skip("universe.json not present in test env")
    universe = json.loads(universe_path.read_text(encoding="utf-8"))
    etfs = universe.get("etfs", [])
    if not etfs:
        pytest.skip("universe.json empty")

    from tradingagents.skills.portfolio.sub_category import bucket_for_etf

    class _ETF:
        def __init__(self, d):
            self.category = d.get("category")
            self.sub_category = d.get("sub_category")
            self.ticker = d.get("ticker")

    classified = [e for e in etfs if bucket_for_etf(_ETF(e)) is not None]
    coverage = len(classified) / max(len(etfs), 1)
    assert coverage >= 0.85, (
        f"coverage={coverage:.2%} < 85% — "
        f"{len(etfs) - len(classified)} ETFs unclassified — sub_category re-enrich needed"
    )
