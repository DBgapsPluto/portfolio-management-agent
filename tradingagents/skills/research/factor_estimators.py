"""Stage 2 deterministic factor estimators (9 factors).

Each ``compute_<factor>(stage1)`` function pulls component raw values
from the Stage 1 reports (``macro_report`` / ``risk_report`` /
``technical_report`` / ``news_report``) plus, where needed, external
fetchers (USD/KRW, S&P trailing P/E), runs them through
:func:`_aggregate` which:

1. drops missing components (``None``),
2. converts each remaining component to a long-run z-score
   (:mod:`tradingagents.skills.research.factor_baselines`),
3. enforces a per-component weight cap from the audit table
   (:mod:`tradingagents.skills.research.factor_reliability_audit`),
4. renormalises the surviving weights, takes a weighted average and
   caps the result to ``[-3, +3]`` for stability.

Stage 2 makes *no* additional LLM calls — everything here is pure
function-of-state. Components sourced from ``news_report`` (Option Z)
use the *structured* fields the Stage 1 ``macro_news_analyst`` already
produces.

Sign convention (positive z = …):
- F1 growth: stronger growth
- F2 inflation: higher inflation
- F3 real_rate: higher real rate
- F4 term_premium: steeper curve
- F5 credit_cycle: credit stress
- F6 krw_regime: weaker KRW (USD/KRW up)
- F7 equity_vol_regime: higher vol
- F8 valuation: more expensive
- F9 liquidity_regime: liquidity stress
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from tradingagents.skills.research.external_fetchers import (
    fetch_krw_usd_level,
    fetch_sp_trailing_pe,
)
from tradingagents.skills.research.factor_baselines import z_score
from tradingagents.skills.research.factor_reliability_audit import get_weight_cap


# ---------------------- schema ----------------------


@dataclass
class FactorScore:
    name: str
    z_score: float
    components: dict[str, float] = field(default_factory=dict)
    component_weights: dict[str, float] = field(default_factory=dict)
    confidence: float = 1.0
    interpretation: str = ""


@dataclass
class FactorScores:
    growth_surprise: FactorScore
    inflation_surprise: FactorScore
    real_rate: FactorScore
    term_premium: FactorScore
    credit_cycle: FactorScore
    krw_regime: FactorScore
    equity_vol_regime: FactorScore
    valuation: FactorScore
    liquidity_regime: FactorScore

    def to_dict(self) -> dict[str, float]:
        return {
            "F1_growth":            self.growth_surprise.z_score,
            "F2_inflation":         self.inflation_surprise.z_score,
            "F3_real_rate":         self.real_rate.z_score,
            "F4_term_premium":      self.term_premium.z_score,
            "F5_credit_cycle":      self.credit_cycle.z_score,
            "F6_krw_regime":        self.krw_regime.z_score,
            "F7_equity_vol_regime": self.equity_vol_regime.z_score,
            "F8_valuation":         self.valuation.z_score,
            "F9_liquidity_regime":  self.liquidity_regime.z_score,
        }


# ---------------------- enum maps ----------------------


_BIAS_MAP: Final[dict[str, float]] = {
    "hawkish_surprise":  0.8,
    "balanced":          0.0,
    "dovish_surprise":  -0.8,
}

_RISK_REGIME_MAP: Final[dict[str, float]] = {
    "risk_on":  1.0,
    "mixed":    0.0,
    "risk_off": -1.0,
}

_Z_CAP: Final[float] = 3.0


# ---------------------- helpers ----------------------


def _safe_get(obj: Any, *path: str, default: Any = None) -> Any:
    """Walk a chain of attribute / dict-key accesses safely.

    Each step uses ``getattr`` then dict ``__getitem__``; any exception
    or a ``None`` intermediate yields ``default``.
    """
    cur: Any = obj
    for key in path:
        if cur is None:
            return default
        try:
            cur = getattr(cur, key)
        except AttributeError:
            try:
                cur = cur[key]
            except (KeyError, TypeError, IndexError):
                return default
        except Exception:
            return default
    if cur is None:
        return default
    return cur


def _aggregate(
    factor_name: str,
    components_raw: dict[str, float | None],
    weights: dict[str, float],
) -> FactorScore:
    """Convert raw component values → final FactorScore.

    See module docstring for the 4-step recipe.
    """
    # Step 1+2: drop None, look up z-score via baseline.
    component_z: dict[str, float] = {}
    used_original_weights: dict[str, float] = {}
    for name, raw in components_raw.items():
        if raw is None:
            continue
        w = weights.get(name, 0.0)
        if w <= 0.0:
            continue
        z = z_score(float(raw), factor_name, name)
        if z is None:
            continue
        component_z[name] = z
        used_original_weights[name] = w

    if not component_z:
        return FactorScore(
            name=factor_name,
            z_score=0.0,
            components={},
            component_weights={},
            confidence=0.0,
            interpretation="no data",
        )

    # Step 3: apply per-component reliability cap (cap can be 0 → drop).
    capped_weights: dict[str, float] = {}
    for name, w in used_original_weights.items():
        cap = get_weight_cap(name)
        applied = min(w, cap)
        if applied <= 0.0:
            # drop component entirely
            component_z.pop(name, None)
            continue
        capped_weights[name] = applied

    if not component_z:
        return FactorScore(
            name=factor_name,
            z_score=0.0,
            components={},
            component_weights={},
            confidence=0.0,
            interpretation="all components capped out",
        )

    # Confidence = sum of ORIGINAL (pre-cap, pre-renorm) used weights.
    confidence = sum(used_original_weights[n] for n in component_z)

    # Step 4: renormalise the surviving capped weights, weighted average.
    total = sum(capped_weights.values())
    final_weights = {n: capped_weights[n] / total for n in capped_weights}
    raw_avg = sum(component_z[n] * final_weights[n] for n in component_z)

    # Step 5: cap to [-3, +3].
    capped = max(-_Z_CAP, min(_Z_CAP, raw_avg))

    interp = _interpretation(factor_name, capped)
    return FactorScore(
        name=factor_name,
        z_score=capped,
        components=component_z,
        component_weights=final_weights,
        confidence=confidence,
        interpretation=interp,
    )


def _interpretation(factor_name: str, z: float) -> str:
    """Tiny human narrative — sign × magnitude."""
    if abs(z) < 0.25:
        magnitude = "neutral"
    elif abs(z) < 1.0:
        magnitude = "modest"
    elif abs(z) < 2.0:
        magnitude = "strong"
    else:
        magnitude = "extreme"
    sign = "+" if z >= 0 else "-"
    return f"{factor_name} z={sign}{abs(z):.2f} ({magnitude})"


# ---------------------- F1 growth_surprise ----------------------


def compute_growth_surprise(stage1: Any) -> FactorScore:
    nfci_raw = _safe_get(stage1, "macro_report", "growth", "nfci")
    sahm_trigger = _safe_get(stage1, "macro_report", "employment", "sahm_trigger")
    sahm_signal = None if sahm_trigger is None else (-1.0 if sahm_trigger else 0.5)

    components_raw: dict[str, float | None] = {
        "gdpnow": _safe_get(stage1, "macro_report", "growth", "gdp_nowcast"),
        "cfnai":  _safe_get(stage1, "macro_report", "growth", "cfnai"),
        "nfci":   (None if nfci_raw is None else -float(nfci_raw)),
        "sahm":   sahm_signal,
        "curve":  _safe_get(stage1, "macro_report", "yield_curve", "slope_2_10y_bps"),

        # News-derived (Option Z)
        "release_surprise": _safe_get(
            stage1, "news_report", "release_surprise", "surprise_index_30d"
        ),
        "hawkish_bias": _BIAS_MAP.get(
            _safe_get(stage1, "news_report", "release_surprise", "bias_30d") or ""
        ),
        "macro_sent": _safe_get(
            stage1, "news_report", "news_sentiment", "avg_sentiment", "macro"
        ),
        "risk_regime_overnight": _RISK_REGIME_MAP.get(
            _safe_get(stage1, "news_report", "global_overnight", "risk_regime_overnight") or ""
        ),
    }

    weights: dict[str, float] = {
        "gdpnow": 0.20, "cfnai": 0.15, "nfci": 0.12, "sahm": 0.08, "curve": 0.12,
        "release_surprise": 0.18, "hawkish_bias": 0.05,
        "macro_sent": 0.05, "risk_regime_overnight": 0.05,
    }
    return _aggregate("F1_growth", components_raw, weights)


# ---------------------- F2 inflation_surprise ----------------------


def compute_inflation_surprise(stage1: Any) -> FactorScore:
    real_yield = _safe_get(stage1, "macro_report", "real_yields", "ten_y_pct")
    real_yield_inverted = None if real_yield is None else -float(real_yield)

    components_raw: dict[str, float | None] = {
        "cpi_yoy":        _safe_get(stage1, "macro_report", "cpi", "yoy_pct"),
        "cpi_3m":         _safe_get(stage1, "macro_report", "cpi", "three_month_annualized_pct"),
        "core_pce":       _safe_get(stage1, "macro_report", "cpi", "core_pce_yoy"),
        "five_y_five_y":  _safe_get(stage1, "macro_report", "inflation_exp", "five_y_five_y_pct"),
        "michigan_1y":    _safe_get(stage1, "macro_report", "inflation_exp", "michigan_1y_pct"),
        "real_yield_inv": real_yield_inverted,
        "fed_path_bps":   _safe_get(stage1, "macro_report", "fed_path", "implied_change_6m_bps"),

        # News-derived: hawkish bias = +inflation, dovish = -inflation
        "release_hawkish": _BIAS_MAP.get(
            _safe_get(stage1, "news_report", "release_surprise", "bias_30d") or ""
        ),
        "macro_sent": _safe_get(
            stage1, "news_report", "news_sentiment", "avg_sentiment", "macro"
        ),
    }

    weights: dict[str, float] = {
        "cpi_yoy": 0.18, "cpi_3m": 0.18, "core_pce": 0.13,
        "five_y_five_y": 0.13, "michigan_1y": 0.08,
        "real_yield_inv": 0.08, "fed_path_bps": 0.08,
        "release_hawkish": 0.07, "macro_sent": 0.07,
    }
    return _aggregate("F2_inflation", components_raw, weights)


# ---------------------- F3 real_rate ----------------------


def compute_real_rate(stage1: Any) -> FactorScore:
    components_raw: dict[str, float | None] = {
        "tips_yield": _safe_get(stage1, "macro_report", "real_yields", "ten_y_pct"),
        "fed_voting_balance": _safe_get(
            stage1, "news_report", "cb_speakers", "fed_voting_balance"
        ),
        "fed_path_implied": _safe_get(
            stage1, "macro_report", "fed_path", "implied_change_6m_bps"
        ),
    }
    weights: dict[str, float] = {
        "tips_yield": 0.55, "fed_voting_balance": 0.35, "fed_path_implied": 0.10,
    }
    return _aggregate("F3_real_rate", components_raw, weights)


# ---------------------- F4 term_premium ----------------------


def compute_term_premium(stage1: Any) -> FactorScore:
    components_raw: dict[str, float | None] = {
        "slope_2_10y": _safe_get(stage1, "macro_report", "yield_curve", "slope_2_10y_bps"),
        "slope_5_30y": _safe_get(stage1, "macro_report", "yield_curve", "slope_5_30y_bps"),
        "fed_tone_balance": _safe_get(
            stage1, "news_report", "cb_speakers", "fed_tone_balance"
        ),
        "fed_voting_balance": _safe_get(
            stage1, "news_report", "cb_speakers", "fed_voting_balance"
        ),
    }
    weights: dict[str, float] = {
        "slope_2_10y": 0.30, "slope_5_30y": 0.25,
        "fed_tone_balance": 0.30, "fed_voting_balance": 0.15,
    }
    return _aggregate("F4_term_premium", components_raw, weights)


# ---------------------- F5 credit_cycle ----------------------


def compute_credit_cycle(stage1: Any) -> FactorScore:
    # corporate_distress: derive from news sentiment (acceleration × negativity)
    corp_count_delta = _safe_get(
        stage1, "news_report", "news_sentiment", "count_change_vs_7d", "corporate"
    )
    corp_sent = _safe_get(
        stage1, "news_report", "news_sentiment", "avg_sentiment", "corporate"
    )
    if corp_count_delta is None and corp_sent is None:
        corporate_distress = None
    else:
        cd = max(0.0, float(corp_count_delta)) if corp_count_delta is not None else 0.0
        cs = max(0.0, -float(corp_sent)) if corp_sent is not None else 0.0
        corporate_distress = cd * cs

    # dovish_bias: invert _BIAS_MAP — dovish = +0.5, hawkish = -0.5, balanced = 0.
    bias = _safe_get(stage1, "news_report", "release_surprise", "bias_30d")
    if bias is None:
        dovish_bias = None
    elif bias == "dovish_surprise":
        dovish_bias = 0.5
    elif bias == "hawkish_surprise":
        dovish_bias = -0.5
    elif bias == "balanced":
        dovish_bias = 0.0
    else:
        dovish_bias = None

    components_raw: dict[str, float | None] = {
        "hy_oas_bps": _safe_get(stage1, "risk_report", "credit_spread_us_hy", "current_bps"),
        "hy_oas_momentum": _safe_get(stage1, "risk_report", "credit_spread_us_hy", "momentum_z"),
        "credit_quality_bps": _safe_get(stage1, "risk_report", "credit_quality", "quality_spread_bps"),
        "funding_bps": _safe_get(stage1, "risk_report", "funding_stress", "spread_bps"),
        "corporate_distress": corporate_distress,
        "dovish_bias": dovish_bias,
    }
    weights: dict[str, float] = {
        "hy_oas_bps": 0.30, "hy_oas_momentum": 0.25,
        "credit_quality_bps": 0.15, "funding_bps": 0.10,
        "corporate_distress": 0.15, "dovish_bias": 0.05,
    }
    return _aggregate("F5_credit_cycle", components_raw, weights)


# ---------------------- F6 krw_regime ----------------------


def compute_krw_regime(stage1: Any) -> FactorScore:
    components_raw: dict[str, float | None] = {
        "krw_overnight_pct": _safe_get(
            stage1, "news_report", "global_overnight", "krw", "change_pct"
        ),
        "krw_level": fetch_krw_usd_level(),  # external fetch
        "kr_us_rate_diff": _safe_get(
            stage1, "macro_report", "kr_macro", "bok_us_rate_diff_bps"
        ),
        "foreign_flow_z": _safe_get(
            stage1, "macro_report", "foreign_flow", "net_flow_z"
        ),
        "kr_exports_yoy": _safe_get(
            stage1, "macro_report", "kr_macro", "exports_yoy_pct"
        ),
        "bok_tone_balance": _safe_get(
            stage1, "news_report", "cb_speakers", "bok_tone_balance"
        ),
    }
    weights: dict[str, float] = {
        "krw_overnight_pct": 0.20, "krw_level": 0.20,
        "kr_us_rate_diff": 0.15, "foreign_flow_z": 0.20,
        "kr_exports_yoy": 0.10, "bok_tone_balance": 0.15,
    }
    return _aggregate("F6_krw_regime", components_raw, weights)


# ---------------------- F7 equity_vol_regime ----------------------


def compute_equity_vol_regime(stage1: Any) -> FactorScore:
    geo = _safe_get(
        stage1, "news_report", "news_sentiment", "count_change_vs_7d", "geopolitical"
    )
    geopolitical_surge = None if geo is None else max(0.0, float(geo))

    components_raw: dict[str, float | None] = {
        "vix_level":   _safe_get(stage1, "risk_report", "vix", "current_value"),
        "vix_z_score": _safe_get(stage1, "risk_report", "vix", "z_score"),
        "vix_term_ratio": _safe_get(stage1, "risk_report", "vix", "term_ratio"),
        "move":        _safe_get(stage1, "risk_report", "move", "current_value"),
        "realized_vol_60d": _safe_get(stage1, "risk_report", "realized_vol", "sixty_d"),
        "skew_change": _safe_get(stage1, "risk_report", "skew", "change_1m"),
        "sentiment_dispersion": _safe_get(
            stage1, "news_report", "news_sentiment", "sentiment_dispersion"
        ),
        "geopolitical_surge": geopolitical_surge,
    }
    weights: dict[str, float] = {
        "vix_level": 0.22, "vix_z_score": 0.12, "vix_term_ratio": 0.12,
        "move": 0.18, "realized_vol_60d": 0.13, "skew_change": 0.08,
        "sentiment_dispersion": 0.08, "geopolitical_surge": 0.07,
    }
    return _aggregate("F7_equity_vol", components_raw, weights)


# ---------------------- F8 valuation ----------------------


def compute_valuation(stage1: Any) -> FactorScore:
    sp_pe = fetch_sp_trailing_pe()
    if sp_pe is not None and sp_pe > 0:
        earnings_yield: float | None = 100.0 / sp_pe
    else:
        earnings_yield = None

    tips_yield = _safe_get(stage1, "macro_report", "real_yields", "ten_y_pct")
    if earnings_yield is not None and tips_yield is not None:
        erp: float | None = earnings_yield - float(tips_yield)
    else:
        erp = None

    kospi_pbr = _safe_get(stage1, "technical_report", "kospi_pbr")

    components_raw: dict[str, float | None] = {
        "sp_pe":          sp_pe,
        "earnings_yield": earnings_yield,
        "erp":            erp,
        "kospi_pbr":      kospi_pbr,
    }
    weights: dict[str, float] = {
        "sp_pe": 0.20, "earnings_yield": 0.30, "erp": 0.30, "kospi_pbr": 0.20,
    }
    return _aggregate("F8_valuation", components_raw, weights)


# ---------------------- F9 liquidity_regime ----------------------


def compute_liquidity_regime(stage1: Any) -> FactorScore:
    vix = _safe_get(stage1, "risk_report", "vix", "current_value")
    rv = _safe_get(stage1, "risk_report", "realized_vol", "sixty_d")
    if vix is not None and rv is not None:
        # bps²-like normalization
        vrp: float | None = ((float(vix) / 100.0) ** 2 - float(rv) ** 2) * 10000.0
    else:
        vrp = None

    event_cluster = _safe_get(
        stage1, "news_report", "release_surprise", "high_importance_today"
    )
    if event_cluster is not None:
        event_cluster = float(event_cluster)

    rising_cat = _safe_get(stage1, "news_report", "news_sentiment", "rising_category")
    if rising_cat is None:
        # Distinguish "Stage 1 didn't run sentiment" vs "ran sentiment, no rising":
        # If the parent news_sentiment exists, we know rising_category was checked.
        ns = _safe_get(stage1, "news_report", "news_sentiment")
        rising_signal: float | None = 0.0 if ns is not None else None
    else:
        rising_signal = 1.0

    components_raw: dict[str, float | None] = {
        "vrp": vrp,
        "eq_bond_corr": _safe_get(stage1, "risk_report", "equity_bond_corr", "correlation_60d"),
        "sector_dispersion": _safe_get(stage1, "technical_report", "sector_dispersion"),
        "breadth": _safe_get(stage1, "technical_report", "breadth"),
        "event_cluster": event_cluster,
        "rising_signal": rising_signal,
    }
    weights: dict[str, float] = {
        "vrp": 0.35, "eq_bond_corr": 0.18, "sector_dispersion": 0.18,
        "breadth": 0.08, "event_cluster": 0.12, "rising_signal": 0.09,
    }
    return _aggregate("F9_liquidity", components_raw, weights)


# ---------------------- compute_all_factors ----------------------


def compute_all_factors(stage1: Any) -> FactorScores:
    return FactorScores(
        growth_surprise=compute_growth_surprise(stage1),
        inflation_surprise=compute_inflation_surprise(stage1),
        real_rate=compute_real_rate(stage1),
        term_premium=compute_term_premium(stage1),
        credit_cycle=compute_credit_cycle(stage1),
        krw_regime=compute_krw_regime(stage1),
        equity_vol_regime=compute_equity_vol_regime(stage1),
        valuation=compute_valuation(stage1),
        liquidity_regime=compute_liquidity_regime(stage1),
    )


__all__: Final = [
    "FactorScore",
    "FactorScores",
    "compute_all_factors",
    "compute_credit_cycle",
    "compute_equity_vol_regime",
    "compute_growth_surprise",
    "compute_inflation_surprise",
    "compute_krw_regime",
    "compute_liquidity_regime",
    "compute_real_rate",
    "compute_term_premium",
    "compute_valuation",
]
