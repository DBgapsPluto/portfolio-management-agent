"""Macro/Quant Analyst — orchestrates 13 macro skills, composes MacroReport.

Per design §7.1: fixed pipeline (no LLM-driven skill ordering).
LLM only writes the ≤500-char narrative + 2KB summary.

Tier-1 확장 (KR cycle + US 선행/실시간 성장):
- kr_export: 한국 EPS의 가장 강력한 동행/선행 지표
- kr_leading: 통계청 선행지수 순환변동치 (cycle phase 분류)
- kr_business_survey: BOK 제조업 BSI (100 기준선)
- us_leading: CFNAI 85개 지표 합성 (MA3 < -0.7 → recession)
- gdp_nowcast: Atlanta Fed 실시간 분기 GDP nowcast
"""
import logging
from datetime import date, timedelta

import pandas as pd
from tradingagents.dataflows.commodities import fetch_commodity_close
from tradingagents.dataflows.equity_indices import fetch_equity_index_close
from tradingagents.dataflows.gpr_index import fetch_gpr_index
from tradingagents.dataflows.pykrx_data import fetch_foreign_flow
from tradingagents.dataflows.shiller_cape import fetch_shiller_cape
from tradingagents.schemas.macro import (
    ChinaLeadingSnapshot, ChinaCreditImpulseSnapshot, CommodityMomentumSnapshot,
    DivergenceScore, EarningsRevisionSnapshot, FXSnapshot, FedPathSnapshot,
    FinancialConditionsSnapshot, ForeignFlowSnapshot, GDPNowSnapshot,
    GeopoliticalRiskSnapshot, InflationExpectationsSnapshot, KRBusinessSurveySnapshot,
    KRExportSnapshot, KRLeadingIndexSnapshot, PolicyUncertaintySnapshot,
    RegimeClassification, RiskAppetiteSnapshot, TailRiskSnapshot,
    USEquityValuationSnapshot, USLeadingIndexSnapshot,
    ChipCycleSnapshot, EmergingMarketSnapshot, KRSectorExportSnapshot,
)
from tradingagents.skills.macro.chip_cycle import compute_chip_cycle
from tradingagents.skills.macro.emerging_market import compute_emerging_market
from tradingagents.skills.macro.kr_sector_export import compute_kr_sector_export
from tradingagents.schemas.reports import MacroReport
from tradingagents.skills.research.china_credit_impulse import compute_china_credit_impulse
from tradingagents.skills.research.earnings_revision import (
    compute_sp500_net_revision, compute_kospi200_net_revision,
)
from tradingagents.skills.macro.calendar import fetch_central_bank_calendar_skill
from tradingagents.skills.macro.china_leading import compute_china_leading
from tradingagents.skills.macro.divergence import compute_kr_divergence
from tradingagents.skills.macro.ecos_fetcher import fetch_ecos_series_skill
from tradingagents.skills.macro.employment import compute_unemployment_trend
from tradingagents.skills.macro.fed_path import compute_fed_path
from tradingagents.skills.macro.financial_conditions import compute_financial_conditions
from tradingagents.skills.macro.foreign_flow import compute_foreign_flow
from tradingagents.skills.macro.fred_fetcher import fetch_fred_series_skill
from tradingagents.skills.macro.fx import compute_fx_overlay
from tradingagents.skills.macro.kr_valuation import compute_kospi_valuation
from tradingagents.skills.macro.real_activity import compute_cfnai_metrics
from tradingagents.skills.macro.gdp_nowcast import compute_gdp_nowcast
from tradingagents.skills.macro.inflation import compute_inflation_trend
from tradingagents.skills.macro.inflation_expectations import compute_inflation_expectations
from tradingagents.skills.macro.kr_business_survey import compute_kr_business_survey
from tradingagents.skills.macro.kr_exports import compute_kr_export_trend
from tradingagents.skills.macro.kr_leading import compute_kr_leading_index
from tradingagents.skills.macro.policy_uncertainty import compute_policy_uncertainty
from tradingagents.skills.macro.regime_classifier import classify_regime
from tradingagents.skills.macro.risk_appetite import compute_risk_appetite
from tradingagents.skills.macro.tail_risk import compute_tail_risk
from tradingagents.skills.macro.us_leading import compute_us_leading_index
from tradingagents.skills.macro.yield_curve import compute_yield_curve, compute_yield_curve_extras


logger = logging.getLogger(__name__)


# ===========================================================================
# Tier 0 — 5 new MacroReport snapshot builders (Tasks 4.1 / 5.11 / 5.12)
# ===========================================================================

def _build_us_equity_valuation(as_of: date) -> USEquityValuationSnapshot | None:
    """Shiller CAPE snapshot — F8 component."""
    try:
        cape_series = fetch_shiller_cape(as_of=as_of)
        if cape_series.empty:
            return None
        cape = float(cape_series.iloc[-1])
        cutoff = pd.Timestamp(as_of) - pd.DateOffset(years=30)
        recent = cape_series[cape_series.index >= cutoff]
        if len(recent) < 12:
            z = 0.0
        else:
            mu, sd = float(recent.mean()), float(recent.std(ddof=1)) or 1e-9
            z = (cape - mu) / sd
        last_cape = pd.Timestamp(cape_series.index[-1]).date()
        return USEquityValuationSnapshot(
            source_date=as_of,
            staleness_days=max((as_of - last_cape).days, 0),
            cape=cape, cape_zscore_30y=z,
        )
    except Exception as e:
        logger.warning("US CAPE fetch failed: %s", e)
        return None


def _build_geopolitical_risk(as_of: date) -> GeopoliticalRiskSnapshot | None:
    """Caldara-Iacoviello GPR Index snapshot — F7 component."""
    try:
        gpr = fetch_gpr_index(frequency="monthly", series="GPR", as_of=as_of)
        if gpr.empty:
            return None
        gpr_now = float(gpr.iloc[-1])
        cutoff = pd.Timestamp(as_of) - pd.DateOffset(months=60)
        recent = gpr[gpr.index >= cutoff]
        if len(recent) < 12:
            z = 0.0
        else:
            mu, sd = float(recent.mean()), float(recent.std(ddof=1)) or 1e-9
            z = (gpr_now - mu) / sd
        gpr_daily_val = None
        try:
            gd = fetch_gpr_index(frequency="daily", series="GPRD", as_of=as_of)
            if not gd.empty:
                gpr_daily_val = float(gd.iloc[-1])
        except Exception:
            pass
        return GeopoliticalRiskSnapshot(
            source_date=as_of, staleness_days=1,
            gpr_monthly=gpr_now, gpr_zscore_60m=z, gpr_daily=gpr_daily_val,
        )
    except Exception as e:
        logger.warning("GPR fetch failed: %s", e)
        return None


def _build_china_credit_impulse_snapshot(as_of: date) -> ChinaCreditImpulseSnapshot | None:
    """BIS China credit impulse snapshot — F12."""
    try:
        ci_data = compute_china_credit_impulse(as_of)
        if ci_data is None:
            return None
        last_bis = pd.Timestamp(ci_data["last_date"]).date()
        return ChinaCreditImpulseSnapshot(
            source_date=as_of,
            staleness_days=max((as_of - last_bis).days, 0),
            credit_impulse=ci_data["impulse"],
            credit_to_gdp_ratio=ci_data["ratio"],
            credit_yoy_pct=ci_data["yoy"],
        )
    except Exception as e:
        logger.warning("China credit impulse failed: %s", e)
        return None


def _build_earnings_revision(as_of: date) -> EarningsRevisionSnapshot | None:
    """SP500 + KOSPI200 earnings revision net ratio — F11 (staggered, 2010+)."""
    if as_of < date(2010, 1, 1):
        return None  # F11 staggered: pre-2010 unavailable
    try:
        sp = compute_sp500_net_revision(as_of)
        ks = compute_kospi200_net_revision(as_of)
        if sp is None and ks is None:
            return None
        return EarningsRevisionSnapshot(
            source_date=as_of, staleness_days=1,
            sp500_net_revision=sp, kospi200_net_revision=ks,
        )
    except Exception as e:
        logger.warning("earnings_revision failed: %s", e)
        return None


def _build_commodity_momentum(as_of: date) -> CommodityMomentumSnapshot | None:
    """Copper/Gold/WTI 3m & 6m momentum snapshot — F2/F12 components."""
    start_6m = as_of - timedelta(days=200)
    try:
        copper = fetch_commodity_close("copper", start_6m, as_of)
        gold = fetch_commodity_close("gold", start_6m, as_of)
        wti = fetch_commodity_close("wti_oil", start_6m, as_of)

        def _pct(s, days):
            if s is None or s.empty or len(s) < days:
                return 0.0
            return float((s.iloc[-1] / s.iloc[-days] - 1) * 100)

        return CommodityMomentumSnapshot(
            source_date=as_of, staleness_days=1,
            copper_3m_pct=_pct(copper, 63), copper_6m_pct=_pct(copper, 126),
            gold_3m_pct=_pct(gold, 63),     gold_6m_pct=_pct(gold, 126),
            wti_3m_pct=_pct(wti, 63),       wti_6m_pct=_pct(wti, 126),
            bcom_3m_pct=None,
        )
    except Exception as e:
        logger.warning("commodity_momentum failed: %s", e)
        return None


def _build_chip_cycle(as_of: date) -> ChipCycleSnapshot | None:
    """US chip PPI cycle snapshot — B3 component."""
    from tradingagents.skills.macro.fred_fetcher import fetch_fred_series_skill
    try:
        start = as_of - timedelta(days=365 * 3)
        ppi = fetch_fred_series_skill("us_chip_ppi", start, as_of, as_of_date=as_of)
        return compute_chip_cycle(ppi, as_of=as_of)
    except Exception as e:  # noqa: BLE001
        logger.warning("chip_cycle failed: %s", e)
        return None


def _build_emerging_market(as_of: date) -> EmergingMarketSnapshot | None:
    """EEM/EMB/DXY emerging market snapshot — B5 component."""
    from tradingagents.dataflows.equity_indices import fetch_equity_index_close
    from tradingagents.skills.macro.fred_fetcher import fetch_fred_series_skill
    try:
        start = as_of - timedelta(days=300)
        eem = fetch_equity_index_close("eem", start, as_of)
        emb = fetch_equity_index_close("emb", start, as_of)
        dxy = fetch_fred_series_skill("dxy", start, as_of, as_of_date=as_of)
        return compute_emerging_market(eem, emb, dxy, as_of=as_of)
    except Exception as e:  # noqa: BLE001
        logger.warning("emerging_market failed: %s", e)
        return None


def _build_kr_sector_export(as_of: date) -> KRSectorExportSnapshot | None:
    """KR sector-level export breakdown snapshot — B1 component."""
    from tradingagents.skills.macro.ecos_fetcher import fetch_ecos_series_skill
    try:
        start = as_of - timedelta(days=365 * 2)
        series = {
            "semi": fetch_ecos_series_skill("kr_export_semi", start, as_of, freq="M", as_of_date=as_of),
            "battery": fetch_ecos_series_skill("kr_export_battery", start, as_of, freq="M", as_of_date=as_of),
            "display": fetch_ecos_series_skill("kr_export_display", start, as_of, freq="M", as_of_date=as_of),
            "chem": fetch_ecos_series_skill("kr_export_chem", start, as_of, freq="M", as_of_date=as_of),
            "steel": fetch_ecos_series_skill("kr_export_steel", start, as_of, freq="M", as_of_date=as_of),
        }
        return compute_kr_sector_export(series, as_of=as_of)
    except Exception as e:  # noqa: BLE001
        logger.warning("kr_sector_export failed: %s", e)
        return None


def _compute_yoy_from_fred(series_key: str, as_of_date: date) -> float | None:
    """Compute YoY %-change for a FRED series. Returns None on fetch failure."""
    from tradingagents.dataflows.fred import fetch_fred_series
    from datetime import timedelta
    import pandas as pd
    try:
        start = as_of_date - timedelta(days=400)  # ~13 months for YoY
        s = fetch_fred_series(series_key, start, as_of_date, as_of_date=as_of_date)
        if s.empty or len(s) < 2:
            return None
        latest = float(s.iloc[-1])
        # Find value ~12 months ago
        target_ago = pd.Timestamp(as_of_date) - pd.DateOffset(months=12)
        prior_idx = s.index.get_indexer([target_ago], method="nearest")[0]
        prior = float(s.iloc[prior_idx])
        if prior == 0:
            return None
        return (latest / prior - 1.0) * 100.0
    except Exception as e:
        logger.warning("YoY compute %s failed: %s", series_key, e)
        return None


# Stage 1 audit (2026-05-26, Task 2): named lookback windows.
MACRO_LOOKBACK_DAYS: int = 365 * 5      # 5y FRED/ECOS macro series
COMMODITY_LOOKBACK_DAYS: int = 400      # ~1y trading buffer for copper/gold/iron ore
GDPNOW_LOOKBACK_DAYS: int = 90          # quarter window for nowcast
USDCNH_LOOKBACK_DAYS: int = 120         # 4mo for real-time China proxy
IRON_ORE_LOOKBACK_DAYS: int = 200       # 6-7mo for momentum proxy
FOREIGN_FLOW_LOOKBACK_DAYS: int = 60    # 2mo for 20d net buy aggregate
CALENDAR_LOOKAHEAD_DAYS: int = 90       # CB calendar horizon

# Backtest prep (2026-05-26, #2): sentinel ratio gate for classify_regime LLM.
# 입력 snapshot 의 절반 이상이 sentinel(staleness=99) 이면 LLM 호출 자체 skip +
# 안전 default regime (low confidence, staleness=99 마킹) 반환.
# Historical backtest 시 데이터 결측이 많은 분기에 LLM 이 placeholder 값 (BSI=100,
# CFNAI=0 등)으로 잘못된 regime 결정하는 것 방지.
SENTINEL_RATIO_SKIP_LLM: float = 0.5    # 50% 이상 sentinel → LLM skip
DEGRADED_REGIME_DEFAULT: str = "growth_disinflation"  # neutral default (다른 분기로 silent 이동 방지)
DEGRADED_REGIME_CONFIDENCE: float = 0.1   # 매우 낮은 confidence — method_picker 가 보수적 결정 유도


NARRATIVE_PROMPT = """\
You are summarizing a macro snapshot for an asset-allocation team.

Data:
- Regime: {regime_quadrant} (confidence {confidence:.2f})
- 10y-2y spread: {spread_2y_bps:.1f} bps (inverted {inverted_days} days)
- CPI YoY: {cpi:.1f}% (accelerating: {accelerating}); Core PCE YoY: {core_pce}% (3m ann: {pce_m3}%) — Fed 타겟 ("n/a" = fetch 결측)
- Unemployment: {ur:.1f}% (Sahm: {sahm}); JOLTS Openings 3m avg {jolts_open:.0f}k, Quits rate {jolts_quits:.1f}% (6m chg {jolts_quits_chg:+.2f})
- KR export YoY: {kr_export_yoy:.1f}% (accelerating: {kr_export_acc})
- KR leading index: {kr_cli:.1f} ({kr_phase})
- KR mfg BSI: {kr_bsi:.1f} (contraction: {kr_contraction})
- CFNAI MA3: {cfnai_ma3:.2f} (recession: {us_recession})
- GDPNow: {gdp_now:.1f}%
- NFCI: {nfci:.2f} ({nfci_regime}, tightening: {nfci_tight})
- Inflation expectations: 5Y5Y={breakeven:.2f}%, Michigan 1y={mich:.2f}%, anchored={anchored}
- Fed path (DGS2-DFF): {fed_bps:+.0f} bps → market expects {fed_view}
- FX: USD/KRW={usd_krw:.0f} ({krw_chg:+.1f}% 1m, {fx_regime})
- Copper/Gold: {cu_signal} (1y pct {cu_pct:.0%})
- China CLI: {china_cli:.1f} ({china_phase}); USDCNH {usdcnh:.3f} ({usdcnh_chg:+.1f}%/1m), iron ore {iron:.0f} ({iron_chg:+.1f}%/3m) → realtime {china_realtime}
- Foreign KOSPI 20d: {foreign_20d:+.1f}억 ({foreign_signal})
- Tail risk: VVIX={vvix:.0f}, MOVE={move:.0f} ({tail_signal})
- Upcoming events: {events}

Write ≤500 chars in Korean. Be concrete. Cite numbers above only — do not invent."""


def _sentinel_kr_export(as_of: date) -> KRExportSnapshot:
    return KRExportSnapshot(
        yoy_pct=0.0, momentum_3mo_pct=0.0, momentum_6mo_pct=0.0,
        accelerating=False, source_date=as_of, staleness_days=99,
    )


def _sentinel_kr_leading(as_of: date) -> KRLeadingIndexSnapshot:
    return KRLeadingIndexSnapshot(
        cli_value=100.0, change_3mo=0.0, change_6mo=0.0, phase="expansion",
        source_date=as_of, staleness_days=99,
    )


def _sentinel_kr_bsi(as_of: date) -> KRBusinessSurveySnapshot:
    return KRBusinessSurveySnapshot(
        mfg_bsi=100.0, change_3mo=0.0, contraction_signal=False,
        source_date=as_of, staleness_days=99,
    )


def _sentinel_us_leading(as_of: date) -> USLeadingIndexSnapshot:
    return USLeadingIndexSnapshot(
        cfnai_value=0.0, cfnai_ma3=0.0, recession_signal=False,
        source_date=as_of, staleness_days=99,
    )


def _sentinel_gdp_nowcast(as_of: date) -> GDPNowSnapshot:
    return GDPNowSnapshot(
        nowcast_pct=0.0, change_from_prior=0.0,
        source_date=as_of, staleness_days=99,
    )


def _sentinel_fci(as_of: date) -> FinancialConditionsSnapshot:
    return FinancialConditionsSnapshot(
        nfci=0.0, anfci=0.0, regime="neutral", tightening=False,
        source_date=as_of, staleness_days=99,
    )


def _sentinel_inflexp(as_of: date) -> InflationExpectationsSnapshot:
    return InflationExpectationsSnapshot(
        breakeven_5y5y=2.0, michigan_1y=3.0, anchored=True,
        unanchored_direction="none", source_date=as_of, staleness_days=99,
    )


def _sentinel_fed_path(as_of: date) -> FedPathSnapshot:
    return FedPathSnapshot(
        current_rate_pct=0.0, implied_2y_rate_pct=0.0,
        path_bps=0.0, market_view="hold",
        source_date=as_of, staleness_days=99,
    )


def _sentinel_fx(as_of: date) -> FXSnapshot:
    return FXSnapshot(
        usd_krw=1300.0, dxy=100.0, krw_change_1m_pct=0.0, dxy_change_1m_pct=0.0,
        regime="neutral", source_date=as_of, staleness_days=99,
    )


def _sentinel_risk_appetite(as_of: date) -> RiskAppetiteSnapshot:
    return RiskAppetiteSnapshot(
        copper_price=0.0, gold_price=0.0, ratio=0.0,
        ratio_percentile_5y=0.5, signal="neutral",
        source_date=as_of, staleness_days=99,
    )


def _sentinel_china_leading(as_of: date) -> ChinaLeadingSnapshot:
    return ChinaLeadingSnapshot(
        cli_value=100.0, change_3mo=0.0, phase="expansion",
        source_date=as_of, staleness_days=99,
    )


def _sentinel_foreign_flow(as_of: date) -> ForeignFlowSnapshot:
    return ForeignFlowSnapshot(
        net_5d_krw=0.0, net_20d_krw=0.0, signal="neutral",
        source_date=as_of, staleness_days=99,
    )


def _sentinel_policy_uncertainty(as_of: date) -> PolicyUncertaintySnapshot:
    return PolicyUncertaintySnapshot(
        us_epu=100.0, global_epu=100.0, us_epu_percentile_5y=0.5, regime="normal",
        source_date=as_of, staleness_days=99,
    )


def _sentinel_tail_risk(as_of: date) -> TailRiskSnapshot:
    return TailRiskSnapshot(
        vvix=90.0, move=100.0, vvix_percentile_1y=0.5, move_percentile_1y=0.5,
        signal="calm", source_date=as_of, staleness_days=99,
    )


def create_macro_quant_analyst(quick_llm, deep_llm):
    def node(state):
        as_of = date.fromisoformat(state["as_of_date"])
        start_macro = as_of - timedelta(days=MACRO_LOOKBACK_DAYS)
        logger.info("macro_quant start: as_of=%s, lookback=%dd", as_of, MACRO_LOOKBACK_DAYS)

        # All fetchers receive as_of_date for point-in-time truncation (D13)
        s_10y = fetch_fred_series_skill("us_10y", start_macro, as_of, as_of_date=as_of)
        s_2y = fetch_fred_series_skill("us_2y", start_macro, as_of, as_of_date=as_of)
        s_3m = fetch_fred_series_skill("us_3m", start_macro, as_of, as_of_date=as_of)
        yc = compute_yield_curve(s_10y, s_2y, s_3m, as_of=as_of)

        # 2026-05-23 C4 — slope_5_30y fold-in for factor model F4 term_premium.
        # D7: scalar return + yc.model_copy(update=...).
        # D8: skill returns None on missing input → yc.spread_30y_5y_bps default 0.0 유지.
        # D9: no retry / no cache (fetcher 의 TieredCache 와 별개로 skill 매번 fresh).
        try:
            s_5y = fetch_fred_series_skill("us_5y", start_macro, as_of, as_of_date=as_of)
            s_30y = fetch_fred_series_skill("us_30y", start_macro, as_of, as_of_date=as_of)
            dgs5_latest = (
                float(s_5y.iloc[-1]) if s_5y is not None and not s_5y.empty else None
            )
            dgs30_latest = (
                float(s_30y.iloc[-1]) if s_30y is not None and not s_30y.empty else None
            )
            spread_30y_5y_bps = compute_yield_curve_extras(
                dgs5_pct=dgs5_latest, dgs30_pct=dgs30_latest, as_of=as_of,
            )
            if spread_30y_5y_bps is not None:
                yc = yc.model_copy(update={"spread_30y_5y_bps": spread_30y_5y_bps})
            # else: skill already logged warning; yc default 0.0 유지 (factor F4 영향).
        except Exception as e:
            logger.warning("slope_5_30y fetch failed (factor F4 affected): %s", e)

        # Tier 0 — F4 reform: ACM 10y term premium (NY Fed THREEFYTP10, 1990+, daily).
        # Adrian-Crump-Moench 2013 RFS. Best-effort; None on fetch fail.
        try:
            from tradingagents.dataflows.fred import fetch_fred_series
            acm_series = fetch_fred_series(
                "us_acm_term_premium_10y",
                as_of - timedelta(days=30),
                as_of,
                as_of_date=as_of,
            )
            acm_tp = float(acm_series.iloc[-1]) if not acm_series.empty else None
            if acm_tp is not None:
                yc = yc.model_copy(update={"acm_term_premium_10y_pct": acm_tp})
        except Exception as e:
            logger.warning("ACM term premium fetch failed (F4 acm_tp=None): %s", e)

        cpi = fetch_fred_series_skill("us_cpi", start_macro, as_of, as_of_date=as_of)
        core_cpi = fetch_fred_series_skill("us_core_cpi", start_macro, as_of, as_of_date=as_of)
        # PCE — Fed 공식 inflation 타겟 (2026-05 추가). 두 series 다 best-effort.
        try:
            pce = fetch_fred_series_skill("us_pce", start_macro, as_of, as_of_date=as_of)
            core_pce = fetch_fred_series_skill("us_core_pce", start_macro, as_of, as_of_date=as_of)
        except Exception:
            pce = None
            core_pce = None
        infl = compute_inflation_trend(cpi, core_cpi, as_of=as_of, pce=pce, core_pce=core_pce)

        ur = fetch_fred_series_skill("us_unrate", start_macro, as_of, as_of_date=as_of)
        payems = fetch_fred_series_skill("us_payems", start_macro, as_of, as_of_date=as_of)
        # LFPR for Sahm rule cross-check (2026-05 fix — see employment.py)
        try:
            lfpr = fetch_fred_series_skill("us_lfpr", start_macro, as_of, as_of_date=as_of)
        except Exception:
            lfpr = None
        # JOLTS — labor market leading indicators (2026-05 추가)
        try:
            jolts_open = fetch_fred_series_skill("us_jolts_openings", start_macro, as_of, as_of_date=as_of)
            jolts_quits = fetch_fred_series_skill("us_jolts_quits", start_macro, as_of, as_of_date=as_of)
        except Exception:
            jolts_open = None
            jolts_quits = None
        emp = compute_unemployment_trend(
            ur, payems, as_of=as_of,
            labor_participation=lfpr,
            job_openings=jolts_open, quits_rate=jolts_quits,
        )

        # KR divergence (best-effort — ECOS may fail)
        try:
            us_policy = fetch_fred_series_skill("us_policy_rate", start_macro, as_of, as_of_date=as_of)
            kr_rate = fetch_ecos_series_skill("kr_base_rate", start_macro, as_of, as_of_date=as_of)
            kr_cpi = fetch_ecos_series_skill("kr_cpi", start_macro, as_of, as_of_date=as_of)
            div = compute_kr_divergence(
                us_policy_rate=float(us_policy.iloc[-1]),
                kr_base_rate=float(kr_rate.iloc[-1]),
                us_cpi_yoy=infl.cpi_yoy,
                kr_cpi_yoy=float((kr_cpi.iloc[-1] / kr_cpi.iloc[-13] - 1) * 100) if len(kr_cpi) >= 13 else 0.0,
                as_of=as_of,
            )
        except Exception:
            # 2026-05 Bug-A fix: staleness_days=99로 sentinel 명시. 이전엔 실데이터
            # score=0 (완전 일치)와 sentinel (모든 값 0)이 구분 안 됐음.
            div = DivergenceScore(
                us_kr_rate_gap_bps=0, us_kr_inflation_gap=0, score=0,
                source_date=as_of, staleness_days=99,
            )

        # Tier-1: KR exports (ECOS 403Y001 already wired)
        try:
            kr_exp_series = fetch_ecos_series_skill("kr_export", start_macro, as_of, as_of_date=as_of)
            kr_export = compute_kr_export_trend(kr_exp_series, as_of=as_of)
        except Exception as e:
            logger.warning("kr_export fetch failed → sentinel: %s", e)
            kr_export = _sentinel_kr_export(as_of)

        # Tier-1: KR leading index (선행지수 순환변동치)
        try:
            kr_cli_series = fetch_ecos_series_skill("kr_cli", start_macro, as_of, as_of_date=as_of)
            kr_leading = compute_kr_leading_index(kr_cli_series, as_of=as_of)
        except Exception as e:
            logger.warning("kr_leading fetch failed → sentinel: %s", e)
            kr_leading = _sentinel_kr_leading(as_of)

        # Tier-1: KR BSI (제조업 업황)
        try:
            kr_bsi_series = fetch_ecos_series_skill("kr_bsi_mfg", start_macro, as_of, as_of_date=as_of)
            kr_bsi = compute_kr_business_survey(kr_bsi_series, as_of=as_of)
        except Exception as e:
            logger.warning("kr_bsi fetch failed → sentinel: %s", e)
            kr_bsi = _sentinel_kr_bsi(as_of)

        # Tier-1: US CFNAI (Chicago Fed National Activity Index)
        try:
            cfnai = fetch_fred_series_skill("us_cfnai", start_macro, as_of, as_of_date=as_of)
            cfnai_ma3 = fetch_fred_series_skill("us_cfnai_ma3", start_macro, as_of, as_of_date=as_of)
            us_leading = compute_us_leading_index(cfnai, cfnai_ma3, as_of=as_of)
        except Exception as e:
            logger.warning("us_leading (CFNAI) fetch failed → sentinel: %s", e)
            us_leading = _sentinel_us_leading(as_of)

        # Tier-1: Atlanta Fed GDPNow
        try:
            gdpnow_series = fetch_fred_series_skill(
                "us_gdp_nowcast", as_of - timedelta(days=GDPNOW_LOOKBACK_DAYS), as_of, as_of_date=as_of,
            )
            gdp_nowcast = compute_gdp_nowcast(gdpnow_series, as_of=as_of)
        except Exception as e:
            logger.warning("gdp_nowcast fetch failed → sentinel: %s", e)
            gdp_nowcast = _sentinel_gdp_nowcast(as_of)

        # Tier-2: Chicago Fed NFCI (financial conditions, weekly)
        try:
            nfci = fetch_fred_series_skill("us_nfci", start_macro, as_of, as_of_date=as_of)
            anfci = fetch_fred_series_skill("us_anfci", start_macro, as_of, as_of_date=as_of)
            fci = compute_financial_conditions(nfci, anfci, as_of=as_of)
        except Exception as e:
            logger.warning("fci (NFCI/ANFCI) fetch failed → sentinel: %s", e)
            fci = _sentinel_fci(as_of)

        # 2026-05-23 C3 — CFNAI fold-in for factor model F1 growth_surprise.
        # D7: scalar tuple return + fci.model_copy(update=...).
        # D8: skill returns None on data 부재 → fci default 0.0 유지.
        # D9: no retry / no cache (fetcher 의 TieredCache 와 별개로 skill 매번 fresh).
        try:
            cfnai_series = fetch_fred_series_skill(
                "us_cfnai", start_macro, as_of, as_of_date=as_of,
            )
            cfnai_result = compute_cfnai_metrics(cfnai_series, as_of)
            if cfnai_result is not None:
                cfnai_latest, cfnai_3m_avg = cfnai_result
                fci = fci.model_copy(update={
                    "cfnai": cfnai_latest,
                    "cfnai_3m_avg": cfnai_3m_avg,
                })
            # else: skill already logged warning; fci default 0.0 유지 (factor F1 영향).
        except Exception as e:
            logger.warning("CFNAI fetch failed (factor F1 affected): %s", e)

        # Tier-2: Inflation expectations (5Y5Y breakeven + Michigan 1y survey)
        try:
            breakeven = fetch_fred_series_skill(
                "us_5y5y_breakeven", start_macro, as_of, as_of_date=as_of,
            )
            michigan = fetch_fred_series_skill(
                "us_michigan_1y", start_macro, as_of, as_of_date=as_of,
            )
            inflation_exp = compute_inflation_expectations(breakeven, michigan, as_of=as_of)
        except Exception as e:
            logger.warning("inflation_expectations fetch failed → sentinel: %s", e)
            inflation_exp = _sentinel_inflexp(as_of)

        # Tier-2: Fed path implied (DGS2 - DFF proxy for futures-implied path)
        try:
            dgs2 = fetch_fred_series_skill("us_2y", start_macro, as_of, as_of_date=as_of)
            dff = fetch_fred_series_skill("us_policy_rate", start_macro, as_of, as_of_date=as_of)
            fed_path = compute_fed_path(dff, dgs2, as_of=as_of)
        except Exception as e:
            logger.warning("fed_path fetch failed → sentinel: %s", e)
            fed_path = _sentinel_fed_path(as_of)

        # Tier-3: FX overlay (USD/KRW + DXY)
        try:
            krw = fetch_fred_series_skill("usd_krw", start_macro, as_of, as_of_date=as_of)
            dxy = fetch_fred_series_skill("dxy", start_macro, as_of, as_of_date=as_of)
        except Exception as e:
            logger.warning("fx (USD/KRW + DXY) fetch failed → sentinel: %s", e)
            fx = _sentinel_fx(as_of)
        else:
            # A4: usd_jpy 실패가 krw/dxy 가용성을 깨지 않도록 분리 (jpy_krw만 degrade).
            usd_jpy = None
            try:
                usd_jpy = fetch_fred_series_skill("usd_jpy", start_macro, as_of, as_of_date=as_of)
            except Exception as e:  # noqa: BLE001
                logger.warning("usd_jpy fetch failed → jpy_krw=0.0, krw/dxy 유지: %s", e)
            fx = compute_fx_overlay(krw, dxy, as_of=as_of, usd_jpy=usd_jpy)

        # Tier-3: Risk appetite (Copper/Gold via yfinance)
        try:
            copper = fetch_commodity_close("copper", as_of - timedelta(days=COMMODITY_LOOKBACK_DAYS), as_of)
            gold = fetch_commodity_close("gold", as_of - timedelta(days=COMMODITY_LOOKBACK_DAYS), as_of)
            risk_appetite = compute_risk_appetite(copper, gold, as_of=as_of)
        except Exception as e:
            logger.warning("risk_appetite (Cu/Au) fetch failed → sentinel: %s", e)
            risk_appetite = _sentinel_risk_appetite(as_of)

        # Tier-3: China leading (OECD CLI + 2026-05 보강 USDCNH/iron ore 실시간).
        # CLI 단독은 2-3개월 lag으로 부족. 보조 신호로 daily proxies 추가.
        try:
            china_cli_series = fetch_fred_series_skill(
                "china_cli", start_macro, as_of, as_of_date=as_of,
            )
        except Exception as e:
            logger.warning("china_cli fetch failed (sub-fetch): %s", e)
            china_cli_series = None
        try:
            usdcnh_series = fetch_equity_index_close(
                "usdcnh", as_of - timedelta(days=USDCNH_LOOKBACK_DAYS), as_of,
            )
        except Exception as e:
            logger.warning("usdcnh fetch failed (sub-fetch): %s", e)
            usdcnh_series = None
        try:
            iron_ore_series = fetch_equity_index_close(
                "iron_ore", as_of - timedelta(days=IRON_ORE_LOOKBACK_DAYS), as_of,
            )
        except Exception as e:
            logger.warning("iron_ore fetch failed (sub-fetch): %s", e)
            iron_ore_series = None
        try:
            if china_cli_series is not None:
                china_leading = compute_china_leading(
                    china_cli_series, as_of=as_of,
                    usdcnh_series=usdcnh_series,
                    iron_ore_series=iron_ore_series,
                )
            else:
                logger.warning("china_leading: cli series missing → sentinel")
                china_leading = _sentinel_china_leading(as_of)
        except Exception as e:
            logger.warning("china_leading compute failed → sentinel: %s", e)
            china_leading = _sentinel_china_leading(as_of)

        # Tier-3: Foreign flow (KRX 외국인 KOSPI 순매수)
        try:
            foreign_series = fetch_foreign_flow(
                as_of - timedelta(days=FOREIGN_FLOW_LOOKBACK_DAYS), as_of, market="KOSPI",
            )
            foreign_flow = compute_foreign_flow(foreign_series, as_of=as_of)
        except Exception as e:
            logger.warning("foreign_flow fetch failed → sentinel: %s", e)
            foreign_flow = _sentinel_foreign_flow(as_of)

        # Tier-4: Policy uncertainty (US + Global EPU) — 2026-05 DEPRECATED.
        # Baker-Bloom-Davis EPU는 학술 지표로 institutional 실무 사용 빈약하고,
        # monthly + ~5d publication lag 때문에 시장 이벤트 대응에 너무 느림.
        # 시장 기반 uncertainty proxies (VIX/MOVE/credit spread/SKEW)가 이미
        # Stage 1 market_risk + Tier-4 tail_risk에 풍부히 있어 정보 중복.
        # schema 호환성을 위해 sentinel은 그대로 채워 downstream LLM은 받지 않음.
        policy_uncertainty = _sentinel_policy_uncertainty(as_of)

        # Tier-4: Tail risk (VVIX + MOVE via yfinance — FRED VVIXCLS/MOVE was retired)
        try:
            vvix = fetch_equity_index_close("vvix", as_of - timedelta(days=COMMODITY_LOOKBACK_DAYS), as_of)
            move = fetch_equity_index_close("move", as_of - timedelta(days=COMMODITY_LOOKBACK_DAYS), as_of)
            tail_risk = compute_tail_risk(vvix, move, as_of=as_of)
        except Exception as e:
            logger.warning("tail_risk (VVIX/MOVE) fetch failed → sentinel: %s", e)
            tail_risk = _sentinel_tail_risk(as_of)

        # 2026-05-23 C5 — KR equity valuation (KOSPI PBR/PER/DivYield) for F8.
        # D7 (신규 class indicator): full Snapshot return → MacroReport 의 Optional
        # kr_valuation field 에 직접 채움 (model_copy 아님; 기존 cfnai/slope_5_30y 의
        # scalar+model_copy 와 다른 path).
        # D8: skill 이 None 반환 시 그대로 — kr_valuation = None (Optional, backward compat).
        # D9: no retry / no cache (skill internal).
        try:
            kr_valuation_snapshot = compute_kospi_valuation(as_of)
            # None 이면 그대로 (skill already logged warning).
        except Exception as e:
            logger.warning("KR valuation skill failed (factor F8 affected): %s", e)
            kr_valuation_snapshot = None

        events = fetch_central_bank_calendar_skill(as_of, days=CALENDAR_LOOKAHEAD_DAYS)

        # Tier 0 F1 reform: INDPRO YoY + Real PCE YoY (live-only; graceful None on failure)
        us_indpro_yoy_pct = _compute_yoy_from_fred("us_indpro", as_of)
        us_real_pce_yoy_pct = _compute_yoy_from_fred("us_real_pce", as_of)

        # Tier 0 — 5 new snapshot builders (Task 4.1).
        # All best-effort: None on fetch failure (Optional fields in MacroReport).
        commodity_momentum_snapshot = _build_commodity_momentum(as_of)
        us_equity_valuation_snapshot = _build_us_equity_valuation(as_of)
        geopolitical_risk_snapshot = _build_geopolitical_risk(as_of)
        china_credit_impulse_snap = _build_china_credit_impulse_snapshot(as_of)
        earnings_revision_snap = _build_earnings_revision(as_of)

        # B3/B5/B1 — chip cycle + emerging market + KR sector export (Task 6).
        chip_cycle_snap = _build_chip_cycle(as_of)
        emerging_market_snap = _build_emerging_market(as_of)
        kr_sector_export_snap = _build_kr_sector_export(as_of)

        # Stage 1 audit (Task 2): sentinel inventory before regime classification.
        # 어느 snapshot이 fetch 실패로 sentinel인지 카운트 → narrative summary 로 노출.
        # classify_regime LLM은 sentinel을 정상값으로 흡수할 수 있으므로 (예: kr_bsi=100.0
        # 평균치) debugger가 어느 신호가 실제 데이터인지 알 수 있어야 함.
        _sentinel_inventory = {
            name: getattr(snap, "staleness_days", 0) >= 99
            for name, snap in [
                ("yc", yc), ("infl", infl), ("emp", emp), ("kr_divergence", div),
                ("kr_export", kr_export), ("kr_leading", kr_leading), ("kr_bsi", kr_bsi),
                ("us_leading", us_leading), ("gdp_nowcast", gdp_nowcast),
                ("fci", fci), ("inflation_exp", inflation_exp), ("fed_path", fed_path),
                ("fx", fx), ("risk_appetite", risk_appetite),
                ("china_leading", china_leading), ("foreign_flow", foreign_flow),
                ("tail_risk", tail_risk),
            ]
        }
        n_sentinels = sum(_sentinel_inventory.values())
        total_snapshots = len(_sentinel_inventory)
        sentinel_ratio = n_sentinels / total_snapshots if total_snapshots else 0.0
        if n_sentinels > 0:
            stale_names = [k for k, v in _sentinel_inventory.items() if v]
            logger.warning(
                "macro_quant: %d/%d snapshots are sentinels (ratio=%.2f, fetch failed): %s — "
                "regime classifier may interpret placeholder values as live data",
                n_sentinels, total_snapshots, sentinel_ratio, stale_names,
            )

        # Backtest prep (2026-05-26, #2): sentinel ratio ≥ 임계값이면 LLM skip.
        # historical 데이터 결측이 많은 분기에 LLM 이 placeholder 값으로 잘못된
        # regime 결정 방지. Stage 3 audit Task 0 의 degraded_inputs 와 연계 —
        # regime.staleness=99 마킹 시 systemic 도 함께 degraded 면 strict MIN_VAR.
        if sentinel_ratio >= SENTINEL_RATIO_SKIP_LLM:
            logger.warning(
                "macro_quant: sentinel_ratio=%.2f ≥ %.2f → classify_regime LLM skip, "
                "safe default regime='%s' (confidence=%.2f, staleness=99)",
                sentinel_ratio, SENTINEL_RATIO_SKIP_LLM,
                DEGRADED_REGIME_DEFAULT, DEGRADED_REGIME_CONFIDENCE,
            )
            regime = RegimeClassification(
                quadrant=DEGRADED_REGIME_DEFAULT,
                confidence=DEGRADED_REGIME_CONFIDENCE,
                drivers=[
                    f"sentinel_ratio={sentinel_ratio:.2f} ≥ {SENTINEL_RATIO_SKIP_LLM}",
                    f"LLM skip — {n_sentinels}/{total_snapshots} snapshots fetch failed",
                ],
                reasoning=(
                    f"degraded run: {n_sentinels}/{total_snapshots} sentinel snapshots. "
                    f"safe default to {DEGRADED_REGIME_DEFAULT}, low confidence."
                )[:300],
                source_date=as_of,
                staleness_days=99,
            )
        else:
            regime: RegimeClassification = classify_regime(
                quick_llm, deep_llm,
                spread_10y_2y_bps=yc.spread_10y_2y_bps,
                inverted_days_count=yc.inverted_days_count,
                cpi_yoy=infl.cpi_yoy,
                momentum_3mo=infl.momentum_3mo,
                accelerating=infl.accelerating,
                # PCE 는 결측 시 None — LLM 에 "n/a" 로 전달해 0.0 (디플레) 와 구분.
                core_pce_yoy=infl.core_pce_yoy if infl.core_pce_yoy is not None else "n/a",
                core_pce_3mo_ann=infl.pce_momentum_3mo if infl.pce_momentum_3mo is not None else "n/a",
                unemployment_rate=emp.unemployment_rate,
                sahm_rule_triggered=emp.sahm_rule_triggered,
                jolts_openings_3mo=emp.job_openings_3mo_avg,
                jolts_quits_rate=emp.quits_rate,
                jolts_quits_change_6mo=emp.quits_rate_change_6mo,
                # Tier-1 신규 inputs
                kr_export_yoy=kr_export.yoy_pct,
                kr_export_accelerating=kr_export.accelerating,
                kr_cli_value=kr_leading.cli_value,
                kr_cli_phase=kr_leading.phase,
                kr_bsi_mfg=kr_bsi.mfg_bsi,
                kr_bsi_contraction=kr_bsi.contraction_signal,
                us_cfnai_ma3=us_leading.cfnai_ma3,
                us_recession_signal=us_leading.recession_signal,
                us_gdp_nowcast=gdp_nowcast.nowcast_pct,
                # Tier-2 신규 inputs
                us_nfci=fci.nfci,
                us_nfci_regime=fci.regime,
                us_nfci_tightening=fci.tightening,
                us_breakeven_5y5y=inflation_exp.breakeven_5y5y,
                us_michigan_1y=inflation_exp.michigan_1y,
                us_inflation_anchored=inflation_exp.anchored,
                fed_path_bps=fed_path.path_bps,
                fed_market_view=fed_path.market_view,
                # Tier-3 신규 inputs
                usd_krw=fx.usd_krw,
                krw_change_1m=fx.krw_change_1m_pct,
                fx_regime=fx.regime,
                copper_gold_signal=risk_appetite.signal,
                copper_gold_percentile=risk_appetite.ratio_percentile_5y,
                china_cli_value=china_leading.cli_value,
                china_cli_phase=china_leading.phase,
                china_usdcnh=china_leading.usdcnh,
                china_usdcnh_change_1m=china_leading.usdcnh_change_1m_pct,
                china_iron_ore_change_3m=china_leading.iron_ore_change_3m_pct,
                china_realtime_signal=china_leading.realtime_signal,
                foreign_flow_20d_krw=foreign_flow.net_20d_krw,
                foreign_flow_signal=foreign_flow.signal,
                # Tier-4 신규 inputs (EPU 2026-05 DEPRECATED — VIX/credit/SKEW이 우월)
                vvix=tail_risk.vvix,
                move=tail_risk.move,
                tail_risk_signal=tail_risk.signal,
            )

        narrative_prompt = NARRATIVE_PROMPT.format(
            regime_quadrant=regime.quadrant, confidence=regime.confidence,
            spread_2y_bps=yc.spread_10y_2y_bps, inverted_days=yc.inverted_days_count,
            cpi=infl.cpi_yoy, accelerating=infl.accelerating,
            core_pce=f"{infl.core_pce_yoy:.1f}" if infl.core_pce_yoy is not None else "n/a",
            pce_m3=f"{infl.pce_momentum_3mo:.1f}" if infl.pce_momentum_3mo is not None else "n/a",
            ur=emp.unemployment_rate, sahm=emp.sahm_rule_triggered,
            jolts_open=emp.job_openings_3mo_avg, jolts_quits=emp.quits_rate,
            jolts_quits_chg=emp.quits_rate_change_6mo,
            kr_export_yoy=kr_export.yoy_pct, kr_export_acc=kr_export.accelerating,
            kr_cli=kr_leading.cli_value, kr_phase=kr_leading.phase,
            kr_bsi=kr_bsi.mfg_bsi, kr_contraction=kr_bsi.contraction_signal,
            cfnai_ma3=us_leading.cfnai_ma3, us_recession=us_leading.recession_signal,
            gdp_now=gdp_nowcast.nowcast_pct,
            nfci=fci.nfci, nfci_regime=fci.regime, nfci_tight=fci.tightening,
            breakeven=inflation_exp.breakeven_5y5y, mich=inflation_exp.michigan_1y,
            anchored=inflation_exp.anchored,
            fed_bps=fed_path.path_bps, fed_view=fed_path.market_view,
            usd_krw=fx.usd_krw, krw_chg=fx.krw_change_1m_pct, fx_regime=fx.regime,
            cu_signal=risk_appetite.signal, cu_pct=risk_appetite.ratio_percentile_5y,
            china_cli=china_leading.cli_value, china_phase=china_leading.phase,
            usdcnh=china_leading.usdcnh, usdcnh_chg=china_leading.usdcnh_change_1m_pct,
            iron=china_leading.iron_ore, iron_chg=china_leading.iron_ore_change_3m_pct,
            china_realtime=china_leading.realtime_signal,
            foreign_20d=foreign_flow.net_20d_krw / 1e8,
            foreign_signal=foreign_flow.signal,
            vvix=tail_risk.vvix, move=tail_risk.move,
            tail_signal=tail_risk.signal,
            events=", ".join(f"{e.event_date} {e.bank}" for e in events[:3]) or "none",
        )
        narrative = quick_llm.invoke(narrative_prompt).content[:500]
        sentinel_line = (
            f"Sentinels: {n_sentinels}/{len(_sentinel_inventory)} "
            f"({', '.join(k for k, v in _sentinel_inventory.items() if v)})\n"
            if n_sentinels > 0 else ""
        )
        summary = (
            f"## Macro\n"
            f"{sentinel_line}"
            f"Regime: **{regime.quadrant}** ({regime.confidence:.2f})\n"
            f"YC 10y-2y: {yc.spread_10y_2y_bps:.0f}bps, inverted {yc.inverted_days_count}d\n"
            f"CPI: {infl.cpi_yoy:.1f}% YoY ({'↑' if infl.accelerating else '↓'})\n"
            f"Core PCE: {f'{infl.core_pce_yoy:.1f}%' if infl.core_pce_yoy is not None else 'n/a'} YoY "
            f"(3m ann {f'{infl.pce_momentum_3mo:.1f}%' if infl.pce_momentum_3mo is not None else 'n/a'}) — Fed 타겟\n"
            f"UR: {emp.unemployment_rate:.1f}% (Sahm: {emp.sahm_rule_triggered}) "
            f"JOLTS: openings {emp.job_openings_3mo_avg/1000:.1f}M, quits {emp.quits_rate:.1f}% "
            f"({emp.quits_rate_change_6mo:+.2f}/6m)\n"
            f"KR exports: {kr_export.yoy_pct:+.1f}% YoY ({'↑' if kr_export.accelerating else '↓'})\n"
            f"KR CLI: {kr_leading.cli_value:.1f} ({kr_leading.phase}), BSI mfg: {kr_bsi.mfg_bsi:.0f}\n"
            f"CFNAI MA3: {us_leading.cfnai_ma3:+.2f} ({'recession' if us_leading.recession_signal else 'expansion'})\n"
            f"GDPNow: {gdp_nowcast.nowcast_pct:+.1f}%\n"
            f"NFCI: {fci.nfci:+.2f} ({fci.regime}{', tightening' if fci.tightening else ''})\n"
            f"Inflexp: 5Y5Y={inflation_exp.breakeven_5y5y:.2f}%, "
            f"Mich1y={inflation_exp.michigan_1y:.2f}% ({'anchored' if inflation_exp.anchored else inflation_exp.unanchored_direction})\n"
            f"Fed path: {fed_path.path_bps:+.0f}bps → {fed_path.market_view}\n"
            f"FX: USD/KRW {fx.usd_krw:.0f} ({fx.krw_change_1m_pct:+.1f}%/1m, {fx.regime})\n"
            f"Cu/Au: {risk_appetite.signal} (5y pct {risk_appetite.ratio_percentile_5y:.0%})\n"
            f"China CLI: {china_leading.cli_value:.1f} ({china_leading.phase}) "
            f"| USDCNH {china_leading.usdcnh:.3f} ({china_leading.usdcnh_change_1m_pct:+.1f}%/1m), "
            f"iron {china_leading.iron_ore:.0f} ({china_leading.iron_ore_change_3m_pct:+.1f}%/3m) "
            f"→ realtime {china_leading.realtime_signal}\n"
            f"Foreign 20d: {foreign_flow.net_20d_krw/1e8:+.0f}억 ({foreign_flow.signal})\n"
            f"Tail risk: VVIX={tail_risk.vvix:.0f}, MOVE={tail_risk.move:.0f} ({tail_risk.signal})\n"
            f"Drivers: {', '.join(regime.drivers[:3])}\n"
        )[:2000]

        report = MacroReport(
            yield_curve=yc, inflation=infl, employment=emp,
            kr_divergence=div, regime=regime,
            upcoming_events=events,
            kr_export=kr_export, kr_leading=kr_leading,
            kr_business_survey=kr_bsi,
            us_leading=us_leading, gdp_nowcast=gdp_nowcast,
            financial_conditions=fci, inflation_expectations=inflation_exp,
            fed_path=fed_path,
            fx=fx, risk_appetite=risk_appetite,
            china_leading=china_leading, foreign_flow=foreign_flow,
            policy_uncertainty=policy_uncertainty, tail_risk=tail_risk,
            kr_valuation=kr_valuation_snapshot,  # ★ NEW C5 (Optional, None on fail)
            us_indpro_yoy_pct=us_indpro_yoy_pct,
            us_real_pce_yoy_pct=us_real_pce_yoy_pct,
            # ★ Tier 0 Task 4.1 — 5 new snapshots (all Optional, None on fail)
            commodity_momentum=commodity_momentum_snapshot,
            us_equity_valuation=us_equity_valuation_snapshot,
            geopolitical_risk=geopolitical_risk_snapshot,
            china_credit_impulse=china_credit_impulse_snap,
            earnings_revision=earnings_revision_snap,
            # ★ B3/B5/B1 Task 6 — chip cycle + emerging market + KR sector export
            chip_cycle=chip_cycle_snap,
            emerging_market=emerging_market_snap,
            kr_sector_export=kr_sector_export_snap,
            narrative=narrative, summary_for_downstream=summary,
        )
        return {"macro_report": report, "macro_summary": summary}

    return node
