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
    # C8 (2026-05-24): cfnai_3m_avg shares CFNAI scale (smoothing — slightly tighter sd).
    ("F1_growth", "cfnai_3m"):              (0.0, 0.5),
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
    # C8 (2026-05-24): 5y30y slope long-run mean ~80bps, sd ~50bps (post-2010 sample).
    ("F4_term_premium", "slope_5_30y"):         (80.0, 50.0),
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
    # C8 D11a (2026-05-24): foreign_flow_z 의 raw 는 net_20d_krw (KRW 단위 누적).
    # 20d 누적 순매수 typical magnitude ~수조 (1e12 KRW). sd=1e12 으로 z ≈ -3~+3
    # normal range. Prior was (0, 1.0) which made z = raw KRW (1e12-scale) — broken.
    ("F6_krw_regime", "foreign_flow_z"):    (0.0, 1e12),
    ("F6_krw_regime", "kr_exports_yoy"):    (5.0, 15.0),
    ("F6_krw_regime", "bok_tone_balance"):  (0.0, 0.5),

    # === F7 equity_vol ===
    ("F7_equity_vol", "vix_level"):            (20.0, 8.0),
    ("F7_equity_vol", "vix_z_score"):          (0.0, 1.0),
    ("F7_equity_vol", "vix_term_ratio"):       (1.0, 0.15),
    ("F7_equity_vol", "move"):                 (90.0, 30.0),
    # C8 (2026-05-24): RealVolSnapshot.realized_vol_60d is *annualized* stddev
    # (SPY daily std × sqrt(252)). Long-run mean ~15% (0.15), sd ~8% (0.08).
    # Prior (0.012, 0.005) was daily-scale — broken.
    ("F7_equity_vol", "realized_vol_60d"):     (0.15, 0.08),
    # C8 (2026-05-24): change_1m_z is already a *normalized z* from skew_metrics.py
    # (delta / hand-coded sd=5.0). Use (0, 1) so factor-level z passes through.
    ("F7_equity_vol", "skew_change"):          (0.0, 1.0),
    ("F7_equity_vol", "sentiment_dispersion"): (0.3, 0.15),
    # 2026-05-26 F7 saturate fix (#1): raw 는 count delta (24h - 7d_avg).
    # 실측 5 backtest 시점에서 raw=25 일관 (NEWS_WINDOW 가 24h cover →
    # prev_7d_avg=0, recent≈25 → delta≈25 정수 범위). baseline (0, 1) 는 ±1
    # 변동 가정 — 실제 raw 분포 (0~30+) 와 단위 mismatch → z=25 outlier 가
    # F7 raw_avg 를 단독 cap 까지 끌고 감. (5, 10) 으로 raw 분포에 맞춤:
    # z(25)=(25-5)/10=2.0 정상 magnitude.
    ("F7_equity_vol", "geopolitical_surge"):   (5.0, 10.0),

    # === F8 valuation ===
    ("F8_valuation", "sp_pe"):           (18.0, 6.0),
    ("F8_valuation", "earnings_yield"):  (5.5, 2.0),
    ("F8_valuation", "erp"):             (4.0, 2.0),
    # C8 (2026-05-24): KOSPI PBR long-run normal range ~0.7-1.3 (mean 1.0, sd 0.3).
    ("F8_valuation", "kospi_pbr"):       (1.0, 0.3),

    # === F9 liquidity ===
    # C8 (2026-05-24): vrp_60d = (VIX/100)² - realized² × 10000 (bps²-like). Range
    # typically -200~+200 in normal regimes; mean ~0 (variance premium is small/null
    # on average; large positive in stress regimes). Hand-coded sd 200.
    ("F9_liquidity", "vrp"):                (0.0, 200.0),
    ("F9_liquidity", "eq_bond_corr"):       (-0.2, 0.2),
    # C8 (2026-05-24): BreadthSnapshot.sector_return_dispersion is decimal-scale
    # cross-sectional stddev of sector ETF 60d returns. Mean ~5% (0.05), sd ~3% (0.03).
    ("F9_liquidity", "sector_dispersion"):  (0.05, 0.03),
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
