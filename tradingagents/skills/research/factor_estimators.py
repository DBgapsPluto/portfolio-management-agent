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

PR0 hotfix (2026-05-23 C1): _safe_get paths corrected to match actual
MacroReport/RiskReport schema.

C8 activation (2026-05-24): 6 placeholders activated after PR1 C3-C7.5
added upstream schema + skill modules:
- F1: cfnai + cfnai_3m (FinancialConditionsSnapshot extension; C3)
- F4: slope_5_30y (YieldCurveSnapshot.spread_30y_5y_bps; C4)
- F7: realized_vol_60d (RealVolSnapshot; C6) + skew_change (SkewSnapshot.change_1m_z; C7.5)
- F8: kospi_pbr (KRValuationSnapshot; C5)
- F9: vrp (RealVolSnapshot.vrp_60d; C6) + sector_dispersion (BreadthSnapshot extension; C7)
Each factor weight dict re-normalized to sum=1.0 (D11 plan default).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Final, Literal

logger = logging.getLogger(__name__)

from tradingagents.skills.research.external_fetchers import (
    fetch_krw_usd_level,
    fetch_sp_trailing_pe,
)
from tradingagents.skills.research.factor_baselines import z_score
from tradingagents.skills.research.factor_reliability_audit import get_weight_cap


# ---------------------- Critical 2 (PR2a) — historical mode ----------------------
#
# Set of components_raw keys that are sourced from `news_report`. In
# `mode="historical"`, these are dropped at the entry of `_aggregate` (their
# weights are removed from the renormalization pool, and the surviving
# *quant* components carry the full weight after renorm).
#
# Rationale: historical backtest reconstructs Stage 1 from quarterly indicator
# data — news/LLM-derived state cannot be replayed. Setting news weights to 0
# (via mode='historical') keeps the factor z magnitude on the same scale as
# production, where news components do exist.
#
# Default mode='production' → 100% identical behavior to pre-PR2a.
NEWS_DERIVED_COMPONENTS: Final[frozenset[str]] = frozenset({
    # F1
    "release_surprise", "hawkish_bias", "macro_sent", "risk_regime_overnight",
    # F2 (release_hawkish is F2's specific name for what F1 calls hawkish_bias)
    "release_hawkish",
    # F3
    "fed_voting_balance",
    # F4 (fed_voting_balance also appears here; included above)
    "fed_tone_balance",
    # F5
    "corporate_distress", "dovish_bias",
    # F6
    "krw_overnight_pct", "bok_tone_balance",
    # F7
    "sentiment_dispersion", "geopolitical_surge",
    # F9
    "event_cluster", "rising_signal",
})

FactorMode = Literal["production", "historical"]


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


# Stage 1 sentinel marker — analyst가 fetch 실패 fallback snapshot을 만들 때
# staleness_days=99로 설정한다. Stage 2 factor estimator는 그 snapshot의 field를
# raw 값으로 사용하면 silent distortion이 생기므로(예: BSI=100 sentinel을 정상
# 평균치로 해석) component drop 한다. 정상 stale(1-7d) 데이터는 통과.
STALENESS_SENTINEL_DAYS: Final[int] = 99


def _safe_get(obj: Any, *path: str, default: Any = None) -> Any:
    """Walk a chain of attribute / dict-key accesses safely.

    Each step uses ``getattr`` then dict ``__getitem__``; any exception
    or a ``None`` intermediate yields ``default``.

    Stage 1 audit (2026-05-26, Task 0): walk 중 만난 StalenessAware snapshot이
    sentinel(staleness_days >= STALENESS_SENTINEL_DAYS)이면 default 반환 →
    factor_estimators._aggregate가 None component를 자동 drop + weight 재정규화.
    이로써 fetch 실패 snapshot의 placeholder 값이 silent하게 factor z에 흡수되는
    blackbox 위험을 차단.
    """
    cur: Any = obj
    for key in path:
        if cur is None:
            return default
        stale = getattr(cur, "staleness_days", None)
        if isinstance(stale, int) and stale >= STALENESS_SENTINEL_DAYS:
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
    mode: FactorMode = "production",
) -> FactorScore:
    """Convert raw component values → final FactorScore.

    See module docstring for the 4-step recipe.

    Args:
        mode: "production" (default, full behavior) or "historical" (Critical 2,
            PR2a) — drops NEWS_DERIVED_COMPONENTS at entry so historical
            backtest's quant-only Stage 1 reconstructions yield z magnitudes
            on the same scale as production.
    """
    # Critical 2 (PR2a): in historical mode, drop news-derived components
    # before any z-score / weight processing. Surviving quant weights are
    # renormalized by the existing Step 4 logic.
    if mode == "historical":
        components_raw = {
            k: v for k, v in components_raw.items()
            if k not in NEWS_DERIVED_COMPONENTS
        }

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


def compute_growth_surprise(stage1: Any, mode: FactorMode = "production") -> FactorScore:
    """F1 growth_surprise — +z = stronger growth, -z = recession.

    PR0 hotfix (2026-05-23 C1): paths fixed to real MacroReport schema.
    - gdp_nowcast: macro_report.gdp_nowcast.nowcast_pct (GDPNowSnapshot)
    - nfci: macro_report.financial_conditions.nfci (FinancialConditionsSnapshot)
    - sahm: macro_report.employment.sahm_rule_triggered (EmploymentSnapshot)
    - curve: macro_report.yield_curve.spread_10y_2y_bps (YieldCurveSnapshot)
    - cfnai: PLACEHOLDER (weight=0) — C8 activation after PR1 adds field
    """
    gdpnow = _safe_get(stage1, "macro_report", "gdp_nowcast", "nowcast_pct")

    nfci_raw = _safe_get(stage1, "macro_report", "financial_conditions", "nfci")
    nfci = -float(nfci_raw) if nfci_raw is not None else None

    sahm_trigger = _safe_get(stage1, "macro_report", "employment", "sahm_rule_triggered")
    sahm_signal = None if sahm_trigger is None else (-1.0 if sahm_trigger else 0.5)

    curve = _safe_get(stage1, "macro_report", "yield_curve", "spread_10y_2y_bps")

    # C8 activation (2026-05-24): PR1 C3 added FinancialConditionsSnapshot.cfnai
    # + cfnai_3m_avg. CFNAI 3m avg < -0.7 is NBER recession signal.
    cfnai = _safe_get(stage1, "macro_report", "financial_conditions", "cfnai")
    cfnai_3m = _safe_get(stage1, "macro_report", "financial_conditions", "cfnai_3m_avg")

    components_raw: dict[str, float | None] = {
        "gdpnow":   gdpnow,
        "cfnai":    cfnai,     # C8 activated
        "cfnai_3m": cfnai_3m,  # C8 NEW component
        "nfci":     nfci,
        "sahm":     sahm_signal,
        "curve":    curve,

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

    # C8 weight rebalance (D11 plan default; sum=1.00):
    weights: dict[str, float] = {
        "gdpnow": 0.18,
        "cfnai": 0.10, "cfnai_3m": 0.08,    # C8 activated
        "nfci": 0.12, "sahm": 0.07, "curve": 0.10,
        "release_surprise": 0.18, "hawkish_bias": 0.05,
        "macro_sent": 0.05, "risk_regime_overnight": 0.07,
    }
    return _aggregate("F1_growth", components_raw, weights, mode=mode)


# ---------------------- F2 inflation_surprise ----------------------


def compute_inflation_surprise(stage1: Any, mode: FactorMode = "production") -> FactorScore:
    """F2 inflation_surprise — +z = higher inflation, -z = disinflation.

    PR0 hotfix (C1): cpi.* → inflation.*; inflation_exp.* →
    inflation_expectations.*; fed_path.implied_change_6m_bps → path_bps;
    real_yields는 risk_report 에 있으며 field 명은 tips_10y.
    """
    # macro_report.inflation (InflationSnapshot)
    cpi_yoy = _safe_get(stage1, "macro_report", "inflation", "cpi_yoy")
    cpi_3m = _safe_get(stage1, "macro_report", "inflation", "momentum_3mo")
    core_pce = _safe_get(stage1, "macro_report", "inflation", "core_pce_yoy")

    # macro_report.inflation_expectations (InflationExpectationsSnapshot)
    five_y_five_y = _safe_get(
        stage1, "macro_report", "inflation_expectations", "breakeven_5y5y"
    )
    michigan_1y = _safe_get(
        stage1, "macro_report", "inflation_expectations", "michigan_1y"
    )

    # macro_report.fed_path (FedPathSnapshot)
    fed_path_bps = _safe_get(stage1, "macro_report", "fed_path", "path_bps")

    # ★ real_yields는 risk_report 에 있음. Field 명은 tips_10y (RealYieldsSnapshot).
    real_yield = _safe_get(stage1, "risk_report", "real_yields", "tips_10y")
    real_yield_inverted = -float(real_yield) if real_yield is not None else None

    components_raw: dict[str, float | None] = {
        "cpi_yoy":        cpi_yoy,
        "cpi_3m":         cpi_3m,
        "core_pce":       core_pce,
        "five_y_five_y":  five_y_five_y,
        "michigan_1y":    michigan_1y,
        "real_yield_inv": real_yield_inverted,
        "fed_path_bps":   fed_path_bps,

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
    return _aggregate("F2_inflation", components_raw, weights, mode=mode)


# ---------------------- F3 real_rate ----------------------


def compute_real_rate(stage1: Any, mode: FactorMode = "production") -> FactorScore:
    """F3 real_rate — +z = high real rate (tight policy).

    PR0 hotfix (C1): tips_yield는 risk_report.real_yields.tips_10y;
    fed_path.implied_change_6m_bps → path_bps.
    """
    components_raw: dict[str, float | None] = {
        "tips_yield": _safe_get(stage1, "risk_report", "real_yields", "tips_10y"),
        "fed_voting_balance": _safe_get(
            stage1, "news_report", "cb_speakers", "fed_voting_balance"
        ),
        "fed_path_implied": _safe_get(
            stage1, "macro_report", "fed_path", "path_bps"
        ),
    }
    weights: dict[str, float] = {
        "tips_yield": 0.55, "fed_voting_balance": 0.35, "fed_path_implied": 0.10,
    }
    return _aggregate("F3_real_rate", components_raw, weights, mode=mode)


# ---------------------- F4 term_premium ----------------------


def compute_term_premium(stage1: Any, mode: FactorMode = "production") -> FactorScore:
    """F4 term_premium — +z = steeper curve.

    PR0 hotfix (C1): slope_2_10y_bps → spread_10y_2y_bps.
    slope_5_30y: PLACEHOLDER (weight=0) — C8 activation after PR1 adds
    YieldCurveSnapshot.spread_30y_5y_bps.
    """
    slope_2_10 = _safe_get(
        stage1, "macro_report", "yield_curve", "spread_10y_2y_bps"
    )

    # C8 activation (2026-05-24): PR1 C4 added YieldCurveSnapshot.spread_30y_5y_bps.
    slope_5_30 = _safe_get(
        stage1, "macro_report", "yield_curve", "spread_30y_5y_bps"
    )

    components_raw: dict[str, float | None] = {
        "slope_2_10y": slope_2_10,
        "slope_5_30y": slope_5_30,  # C8 activated
        "fed_tone_balance": _safe_get(
            stage1, "news_report", "cb_speakers", "fed_tone_balance"
        ),
        "fed_voting_balance": _safe_get(
            stage1, "news_report", "cb_speakers", "fed_voting_balance"
        ),
    }
    # C8 weight rebalance (D11 plan default; sum=1.00):
    weights: dict[str, float] = {
        "slope_2_10y": 0.25,
        "slope_5_30y": 0.20,   # C8 activated
        "fed_tone_balance": 0.30, "fed_voting_balance": 0.25,
    }
    return _aggregate("F4_term_premium", components_raw, weights, mode=mode)


# ---------------------- F5 credit_cycle ----------------------


def compute_credit_cycle(stage1: Any, mode: FactorMode = "production") -> FactorScore:
    """F5 credit_cycle — +z = credit stress.

    PR0 hotfix (C1): hy_oas momentum field 명은 momentum_zscore
    (SpreadSnapshot), 기존 momentum_z 는 잘못된 이름.
    """
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
        "hy_oas_bps": _safe_get(
            stage1, "risk_report", "credit_spread_us_hy", "current_bps"
        ),
        "hy_oas_momentum": _safe_get(
            stage1, "risk_report", "credit_spread_us_hy", "momentum_zscore"
        ),
        "credit_quality_bps": _safe_get(
            stage1, "risk_report", "credit_quality", "quality_spread_bps"
        ),
        "funding_bps": _safe_get(
            stage1, "risk_report", "funding_stress", "spread_bps"
        ),
        "corporate_distress": corporate_distress,
        "dovish_bias": dovish_bias,
    }
    weights: dict[str, float] = {
        "hy_oas_bps": 0.30, "hy_oas_momentum": 0.25,
        "credit_quality_bps": 0.15, "funding_bps": 0.10,
        "corporate_distress": 0.15, "dovish_bias": 0.05,
    }
    return _aggregate("F5_credit_cycle", components_raw, weights, mode=mode)


# ---------------------- F6 krw_regime ----------------------


def compute_krw_regime(stage1: Any, mode: FactorMode = "production") -> FactorScore:
    """F6 krw_regime — +z = weaker KRW.

    PR0 hotfix (C1):
    - kr_macro.bok_us_rate_diff_bps → kr_divergence.us_kr_rate_gap_bps
    - kr_macro.exports_yoy_pct → kr_export.yoy_pct (KRExportSnapshot)
    - foreign_flow.net_flow_z → foreign_flow.net_20d_krw (ForeignFlowSnapshot
      에 net_flow_z 없음, 20d 누적 순매수액을 proxy 로 사용)
    - krw_level: macro_report.fx.usd_krw 우선 사용, 없으면 external fetch.
    """
    # macro_report.fx (FXSnapshot) 의 usd_krw 우선. None 일 때 external fetch.
    # Stage 2 audit (Task 3): None 의 원인 (sentinel guard 작동 or fx field 결측)
    # 을 logger.info 로 trace — yfinance 우회 경로 가시화.
    krw_level = _safe_get(stage1, "macro_report", "fx", "usd_krw")
    if krw_level is None:
        logger.info(
            "compute_krw_regime: Stage 1 fx.usd_krw missing/sentinel → external yfinance fallback"
        )
        krw_level = fetch_krw_usd_level()  # external fallback
        if krw_level is None:
            logger.warning(
                "compute_krw_regime: external fallback also failed → krw_level component drop"
            )

    components_raw: dict[str, float | None] = {
        "krw_overnight_pct": _safe_get(
            stage1, "news_report", "global_overnight", "krw", "change_pct"
        ),
        "krw_level": krw_level,
        "kr_us_rate_diff": _safe_get(
            stage1, "macro_report", "kr_divergence", "us_kr_rate_gap_bps"
        ),
        "foreign_flow_z": _safe_get(
            stage1, "macro_report", "foreign_flow", "net_20d_krw"
        ),
        "kr_exports_yoy": _safe_get(
            stage1, "macro_report", "kr_export", "yoy_pct"
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
    return _aggregate("F6_krw_regime", components_raw, weights, mode=mode)


# ---------------------- F7 equity_vol_regime ----------------------


def compute_equity_vol_regime(stage1: Any, mode: FactorMode = "production") -> FactorScore:
    """F7 equity_vol_regime — +z = high vol.

    PR0 hotfix (C1):
    - vix.z_score → vix.zscore_30d (VolatilitySnapshot)
    - vix.term_ratio → vix_term.ratio (VIXTermStructureSnapshot, 별도 snapshot)
    - move.current_value → macro_report.tail_risk.move (TailRiskSnapshot;
      MOVE 가 risk_report 가 아니라 macro_report.tail_risk 에 위치)
    - skew_change: PLACEHOLDER (weight=0) — SkewSnapshot has only absolute
      `skew_value` (no change/delta field), but factor_baselines assumes
      *change* semantic (mean=0, sd=5). Activated in C8 after SkewSnapshot
      gains a change/delta field (or baseline retuned for absolute level).
    - realized_vol_60d: PLACEHOLDER (weight=0) — C8 activation after PR1
      adds RealVolSnapshot.
    """
    geo = _safe_get(
        stage1, "news_report", "news_sentiment", "count_change_vs_7d", "geopolitical"
    )
    geopolitical_surge = None if geo is None else max(0.0, float(geo))

    # C8 activation (2026-05-24): PR1 C6 added RealVolSnapshot.realized_vol_60d
    # (SPY annualized 60d stddev).
    realized_vol_60d = _safe_get(
        stage1, "risk_report", "real_vol", "realized_vol_60d"
    )

    # C8 activation (2026-05-24): PR1 C7.5 added SkewSnapshot.change_1m_z
    # (1-month change normalized by long-run sd — cleaner signal than level).
    skew_change = _safe_get(stage1, "risk_report", "skew", "change_1m_z")

    components_raw: dict[str, float | None] = {
        "vix_level":   _safe_get(stage1, "risk_report", "vix", "current_value"),
        "vix_z_score": _safe_get(stage1, "risk_report", "vix", "zscore_30d"),
        "vix_term_ratio": _safe_get(stage1, "risk_report", "vix_term", "ratio"),
        # MOVE 는 macro_report.tail_risk 에 위치
        "move":        _safe_get(stage1, "macro_report", "tail_risk", "move"),
        "realized_vol_60d": realized_vol_60d,  # C8 activated
        "skew_change": skew_change,            # C8 activated (C7.5)
        "sentiment_dispersion": _safe_get(
            stage1, "news_report", "news_sentiment", "sentiment_dispersion"
        ),
        "geopolitical_surge": geopolitical_surge,
    }
    # C8 weight rebalance (D11 plan default; sum=1.00):
    weights: dict[str, float] = {
        "vix_level": 0.20, "vix_z_score": 0.10, "vix_term_ratio": 0.10,
        "move": 0.15,
        "realized_vol_60d": 0.13,   # C8 activated
        "skew_change": 0.07,        # C8 activated (C7.5)
        "sentiment_dispersion": 0.10, "geopolitical_surge": 0.15,
    }
    return _aggregate("F7_equity_vol", components_raw, weights, mode=mode)


# ---------------------- F8 valuation ----------------------


def compute_valuation(stage1: Any, mode: FactorMode = "production") -> FactorScore:
    """F8 valuation — +z = more expensive.

    PR0 hotfix (C1):
    - tips_yield: macro_report.real_yields → risk_report.real_yields.tips_10y
    - kospi_pbr: PLACEHOLDER (weight=0) — C8 activation after PR1 adds
      KRValuationSnapshot to macro_report.kr_valuation.
    """
    sp_pe = fetch_sp_trailing_pe()
    if sp_pe is not None and sp_pe > 0:
        earnings_yield: float | None = 100.0 / sp_pe
    else:
        earnings_yield = None

    tips_yield = _safe_get(stage1, "risk_report", "real_yields", "tips_10y")
    if earnings_yield is not None and tips_yield is not None:
        erp: float | None = earnings_yield - float(tips_yield)
    else:
        erp = None

    # C8 activation (2026-05-24): PR1 C5 added macro_report.kr_valuation
    # (KRValuationSnapshot, Optional). _safe_get → None safe.
    kospi_pbr = _safe_get(stage1, "macro_report", "kr_valuation", "kospi_pbr")

    components_raw: dict[str, float | None] = {
        "sp_pe":          sp_pe,
        "earnings_yield": earnings_yield,
        "erp":            erp,
        "kospi_pbr":      kospi_pbr,  # C8 activated
    }
    # C8 weight rebalance (D11 plan default; sum=1.00):
    weights: dict[str, float] = {
        "sp_pe": 0.20, "earnings_yield": 0.25, "erp": 0.30,
        "kospi_pbr": 0.25,   # C8 activated
    }
    return _aggregate("F8_valuation", components_raw, weights, mode=mode)


# ---------------------- F9 liquidity_regime ----------------------


def compute_liquidity_regime(stage1: Any, mode: FactorMode = "production") -> FactorScore:
    """F9 liquidity_regime — +z = liquidity stress.

    PR0 hotfix (C1):
    - breadth: technical_report.breadth → risk_report.breadth_kr.advancing_pct
      (BreadthSnapshot 는 advancing_pct/declining_pct/new_highs_minus_lows 만 보유)
    - vrp: realized_vol 의존이라 weight=0 placeholder (C8)
    - sector_dispersion: technical_report.sector_dispersion 는 미존재 —
      PLACEHOLDER weight=0 (C8 activation after PR1 adds BreadthSnapshot 확장
      또는 sector_dispersion 별도 snapshot).
    """
    # C8 activation (2026-05-24): PR1 C6 added RealVolSnapshot.vrp_60d
    # (pre-computed VIX²−realized² in bps²-like). Use directly (no re-derive).
    vrp = _safe_get(stage1, "risk_report", "real_vol", "vrp_60d")

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

    # C8 activation (2026-05-24): PR1 C7 added BreadthSnapshot.sector_return_dispersion.
    # US breadth (S&P 500) — cross-sectional dispersion of sector ETF 60d returns.
    sector_dispersion = _safe_get(
        stage1, "risk_report", "breadth_us", "sector_return_dispersion"
    )

    components_raw: dict[str, float | None] = {
        "vrp": vrp,  # C8 activated
        "eq_bond_corr": _safe_get(
            stage1, "risk_report", "equity_bond_corr", "correlation_120d"
        ),
        "sector_dispersion": sector_dispersion,  # C8 activated
        # breadth 는 risk_report.breadth_kr (BreadthSnapshot.advancing_pct 사용)
        "breadth": _safe_get(stage1, "risk_report", "breadth_kr", "advancing_pct"),
        "event_cluster": event_cluster,
        "rising_signal": rising_signal,
    }
    # C8 weight rebalance (D11 plan default; sum=1.00):
    weights: dict[str, float] = {
        "vrp": 0.30,                # C8 activated
        "eq_bond_corr": 0.15,
        "sector_dispersion": 0.15,  # C8 activated
        "breadth": 0.10,
        "event_cluster": 0.15,
        "rising_signal": 0.15,
    }
    return _aggregate("F9_liquidity", components_raw, weights, mode=mode)


# ---------------------- compute_all_factors ----------------------


def compute_all_factors(
    stage1: Any, mode: FactorMode = "production",
) -> FactorScores:
    """Compute all 9 factors.

    Args:
        mode: "production" (default) or "historical" (Critical 2, PR2a).
            In "historical" mode, NEWS_DERIVED_COMPONENTS are dropped from each
            factor's component pool (news_report is not LLM-reproducible in
            backtest); surviving quant weights are renormalized.
    """
    return FactorScores(
        growth_surprise=compute_growth_surprise(stage1, mode=mode),
        inflation_surprise=compute_inflation_surprise(stage1, mode=mode),
        real_rate=compute_real_rate(stage1, mode=mode),
        term_premium=compute_term_premium(stage1, mode=mode),
        credit_cycle=compute_credit_cycle(stage1, mode=mode),
        krw_regime=compute_krw_regime(stage1, mode=mode),
        equity_vol_regime=compute_equity_vol_regime(stage1, mode=mode),
        valuation=compute_valuation(stage1, mode=mode),
        liquidity_regime=compute_liquidity_regime(stage1, mode=mode),
    )


__all__: Final = [
    "FactorScore",
    "FactorScores",
    "FactorMode",
    "NEWS_DERIVED_COMPONENTS",
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
