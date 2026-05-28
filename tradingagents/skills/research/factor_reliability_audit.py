"""Per-component reliability audit driving Stage 2 factor weight caps.

Each Stage 2 factor estimator aggregates several components (e.g. F1
growth uses gdpnow, cfnai, nfci, etc.). Some of those series are
*structurally less informative in 2026* (e.g. Sahm rule post-COVID
distortion, SKEW level post-2018 plateau) — we cap their weight so a
single noisy component cannot dominate a factor.

The :data:`AUDIT_DATE` is checked by
``tests/unit/skills/research/test_factor_indicator_validity.py`` —
the test fails if the audit is older than 180 days, forcing a
refresh.

See ``docs/superpowers/specs/2026-05-22-stage2-factor-model-design.md``
§3.2 for the per-factor reliability column.
"""
from __future__ import annotations

from typing import Final, Literal


Reliability = Literal[
    "high", "medium-high", "medium", "medium-low", "low", "uncertain",
]


AUDIT_DATE: Final[str] = "2026-05-24"


COMPONENT_RELIABILITY: Final[dict[str, Reliability]] = {
    # ----- F1 growth_surprise -----
    "gdpnow":                "high",
    "cfnai":                 "high",
    "cfnai_3m":              "high",   # C8 (2026-05-24): 3m avg, NBER recession signal
    "nfci":                  "high",
    "sahm":                  "medium-low",   # post-COVID distortion
    "curve":                 "medium-low",   # post-COVID de-anchored
    "release_surprise":      "high",
    "hawkish_bias":          "high",
    "macro_sent":            "medium",
    "risk_regime_overnight": "high",

    # ----- F2 inflation_surprise -----
    "cpi_yoy":         "high",
    "cpi_3m":          "high",
    "core_pce":        "high",
    "five_y_five_y":   "high",
    "michigan_1y":     "medium",
    "real_yield_inv":  "high",
    "fed_path_bps":    "high",
    "release_hawkish": "high",

    # ----- F3 real_rate -----
    "tips_yield":         "high",
    "fed_voting_balance": "high",
    "fed_path_implied":   "high",

    # ----- F4 term_premium -----
    "slope_2_10y":      "medium",
    "slope_5_30y":      "high",
    "fed_tone_balance": "high",

    # ----- F5 credit_cycle -----
    "hy_oas_bps":         "high",
    "hy_oas_momentum":    "high",
    "credit_quality_bps": "high",
    "funding_bps":        "high",
    "corporate_distress": "medium",
    "dovish_bias":        "medium",

    # ----- F6 krw_regime -----
    # Tier 0 (2026-05-28): krw_level removed, foreign_flow_z replaced by foreign_flow_normalized.
    "krw_overnight_pct":       "high",
    "krw_change_6m_pct":       "high",
    "krw_reer":                "high",
    "kr_us_rate_diff":         "high",
    "foreign_flow_normalized": "high",
    "kr_exports_yoy":          "high",
    "bok_tone_balance":        "high",

    # ----- F7 equity_vol -----
    "vix_level":            "high",
    "vix_z_score":          "high",
    "vix_term_ratio":       "high",
    "move":                 "high",
    "realized_vol_60d":     "high",
    "skew_level":           "medium-low",  # post-2018 structurally elevated
    "skew_change":          "medium",
    "sentiment_dispersion": "high",
    # Tier 0 (2026-05-28): geopolitical_surge → gpr_index_zscore (Caldara-Iacoviello GPR).
    "gpr_index_zscore":     "high",

    # ----- F8 valuation -----
    "sp_pe":          "medium",
    "earnings_yield": "medium",
    "erp":            "medium-high",
    "kospi_pbr":      "high",
    # Tier 0 (2026-05-28): US CAPE + KOSPI PER + Div Yield activated.
    "us_cape":        "high",
    "kospi_per":      "high",
    "kospi_div_yield":"high",

    # ----- F9 market_dispersion (renamed from F9_liquidity, Tier 0 2026-05-28) -----
    "vrp":                "high",
    "eq_bond_corr":       "high",
    "sector_dispersion":  "medium",   # C8: narrow rally regime degrades reliability
    "breadth":            "medium",   # narrow AI rally distortion
    "event_cluster":      "high",
    "rising_signal":      "medium",

    # ----- F10 systemic_liquidity (2026-05-27 신규) -----
    "nfci":               "high",     # Chicago Fed NFCI, weekly, FRED 직접
    "anfci":              "high",
    "fed_bs_signal":      "high",     # WALCL FRED, weekly
    "sofr_tbill_spread":  "high",     # SOFR + DTB3 FRED, daily
    "aaa_oas":            "high",     # IG AAA OAS FRED (BAA10Y fallback)

    # ----- F11 earnings_revision (Tier 0 2026-05-28, staggered 2010+) -----
    "sp500_net_revision":    "medium",  # yfinance upgrades_downgrades API coverage varies
    "kospi200_net_revision": "medium",  # pykrx PER-implied proxy — indirect

    # ----- F12 china_credit_impulse (Tier 0 2026-05-28) -----
    "credit_impulse":   "high",   # BIS Total Credit Q:CN:P:A:M:770:A (quarterly, direct)
    "credit_yoy_pct":   "high",   # same BIS series YoY
    "iron_ore_3m_pct":  "medium", # commodity proxy — indirect China demand signal
}


WEIGHT_CAP_BY_RELIABILITY: Final[dict[Reliability, float]] = {
    "high":        0.40,
    "medium-high": 0.30,
    "medium":      0.20,
    "medium-low":  0.10,
    "low":         0.05,
    "uncertain":   0.00,
}


def get_reliability(component: str) -> Reliability:
    """Return the audited reliability tier; ``'low'`` for unknown components (conservative)."""
    return COMPONENT_RELIABILITY.get(component, "low")


def get_weight_cap(component: str) -> float:
    """Return the maximum allowed component weight given its reliability tier."""
    return WEIGHT_CAP_BY_RELIABILITY[get_reliability(component)]


__all__: Final = [
    "AUDIT_DATE",
    "COMPONENT_RELIABILITY",
    "WEIGHT_CAP_BY_RELIABILITY",
    "Reliability",
    "get_reliability",
    "get_weight_cap",
]
