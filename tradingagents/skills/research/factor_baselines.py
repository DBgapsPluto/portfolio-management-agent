"""Long-run (mean, sd) baselines per (factor, component).

Each (factor, component) pair maps to a (mean, sd) tuple used by
:func:`z_score` to normalize raw component values into z-scores.
The baselines reflect *long-run* (≈ 1970-2024 quarterly) sample
statistics where applicable, with prudent priors for newer / noisier
series. See `docs/superpowers/specs/2026-05-22-stage2-factor-model-design.md`
§4.4 for the source rationale.

Stage 2 factor estimators consume this table; downstream `_aggregate`
skips any component whose lookup returns ``None`` (missing baseline
or non-positive sd).
"""
from __future__ import annotations

from typing import Final


LONG_RUN_BASELINE: dict[tuple[str, str], tuple[float, float]] = {
    # === F1 growth_surprise ===
    ("F1_growth", "gdpnow"):                (2.0, 2.0),
    ("F1_growth", "cfnai"):                 (0.0, 0.5),
    ("F1_growth", "nfci"):                  (0.0, 0.5),
    ("F1_growth", "sahm"):                  (0.0, 1.0),
    ("F1_growth", "curve"):                 (80.0, 80.0),
    ("F1_growth", "release_surprise"):      (0.0, 1.0),
    ("F1_growth", "hawkish_bias"):          (0.0, 0.8),
    ("F1_growth", "macro_sent"):            (0.0, 0.3),
    ("F1_growth", "risk_regime_overnight"): (0.0, 1.0),

    # === F2 inflation_surprise ===
    ("F2_inflation", "cpi_yoy"):         (2.5, 2.0),
    ("F2_inflation", "cpi_3m"):          (2.5, 3.0),
    ("F2_inflation", "core_pce"):        (2.0, 1.5),
    ("F2_inflation", "five_y_five_y"):   (2.3, 0.5),
    ("F2_inflation", "michigan_1y"):     (3.0, 1.5),
    ("F2_inflation", "real_yield_inv"):  (-0.5, 1.0),
    ("F2_inflation", "fed_path_bps"):    (0.0, 50.0),
    ("F2_inflation", "release_hawkish"): (0.0, 0.8),
    ("F2_inflation", "macro_sent"):      (0.0, 0.3),

    # === F3 real_rate ===
    ("F3_real_rate", "tips_yield"):         (0.5, 1.0),
    ("F3_real_rate", "fed_voting_balance"): (0.0, 0.5),
    ("F3_real_rate", "fed_path_implied"):   (0.0, 50.0),

    # === F4 term_premium ===
    ("F4_term_premium", "slope_2_10y"):         (80.0, 80.0),
    ("F4_term_premium", "slope_5_30y"):         (120.0, 80.0),
    ("F4_term_premium", "fed_tone_balance"):    (0.0, 0.5),
    ("F4_term_premium", "fed_voting_balance"):  (0.0, 0.5),

    # === F5 credit_cycle ===
    ("F5_credit_cycle", "hy_oas_bps"):         (400.0, 200.0),
    ("F5_credit_cycle", "hy_oas_momentum"):    (0.0, 1.0),
    ("F5_credit_cycle", "credit_quality_bps"): (90.0, 40.0),
    ("F5_credit_cycle", "funding_bps"):        (10.0, 20.0),
    ("F5_credit_cycle", "corporate_distress"): (0.0, 1.0),
    ("F5_credit_cycle", "dovish_bias"):        (0.0, 0.5),

    # === F6 krw_regime ===
    ("F6_krw_regime", "krw_overnight_pct"): (0.0, 0.5),
    ("F6_krw_regime", "krw_level"):         (1250.0, 100.0),
    ("F6_krw_regime", "kr_us_rate_diff"):   (-100.0, 100.0),
    ("F6_krw_regime", "foreign_flow_z"):    (0.0, 1.0),
    ("F6_krw_regime", "kr_exports_yoy"):    (5.0, 15.0),
    ("F6_krw_regime", "bok_tone_balance"):  (0.0, 0.5),

    # === F7 equity_vol ===
    ("F7_equity_vol", "vix_level"):            (20.0, 8.0),
    ("F7_equity_vol", "vix_z_score"):          (0.0, 1.0),
    ("F7_equity_vol", "vix_term_ratio"):       (1.0, 0.15),
    ("F7_equity_vol", "move"):                 (90.0, 30.0),
    ("F7_equity_vol", "realized_vol_60d"):     (0.012, 0.005),
    ("F7_equity_vol", "skew_change"):          (0.0, 5.0),
    ("F7_equity_vol", "sentiment_dispersion"): (0.3, 0.15),
    ("F7_equity_vol", "geopolitical_surge"):   (0.0, 1.0),

    # === F8 valuation ===
    ("F8_valuation", "sp_pe"):           (18.0, 6.0),
    ("F8_valuation", "earnings_yield"):  (5.5, 2.0),
    ("F8_valuation", "erp"):             (4.0, 2.0),
    ("F8_valuation", "kospi_pbr"):       (1.0, 0.25),

    # === F9 liquidity ===
    ("F9_liquidity", "vrp"):                (50.0, 30.0),
    ("F9_liquidity", "eq_bond_corr"):       (-0.2, 0.2),
    ("F9_liquidity", "sector_dispersion"):  (1.0, 0.3),
    ("F9_liquidity", "breadth"):            (0.55, 0.15),
    ("F9_liquidity", "event_cluster"):      (1.5, 1.5),
    ("F9_liquidity", "rising_signal"):      (0.5, 0.5),
}


def get_baseline(factor: str, component: str) -> tuple[float, float] | None:
    """Return ``(mean, sd)`` for ``(factor, component)`` or ``None`` if absent."""
    return LONG_RUN_BASELINE.get((factor, component))


def z_score(value: float, factor: str, component: str) -> float | None:
    """Return long-run z-score ``(value - mean) / sd`` or ``None`` on missing / invalid baseline."""
    base = get_baseline(factor, component)
    if base is None:
        return None
    mean, sd = base
    if sd <= 0:
        return None
    return (value - mean) / sd


__all__: Final = ["LONG_RUN_BASELINE", "get_baseline", "z_score"]
