from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from tradingagents.schemas._base import StalenessAware


RegimeQuadrant = Literal[
    "growth_inflation",
    "growth_disinflation",
    "recession_inflation",
    "recession_disinflation",
]


class YieldCurveSnapshot(StalenessAware):
    spread_10y_2y_bps: float = Field(description="10Y - 2Y in basis points")
    spread_10y_3m_bps: float = Field(description="10Y - 3M in basis points")
    inverted_days_count: int = Field(ge=0, description="Days inverted in last 365")
    percentile_5y: float = Field(ge=0, le=1, description="5y historical percentile")

    # 2026-05-23 C4 — factor model F4 term_premium component.
    # 5-30y slope: long-end curve. spread_10y_2y 는 단기-중기 정책 기대 반영하지만,
    # 5-30y 는 longer-horizon term premium (real economy 기대 / inflation risk premium)
    # 의 signal. C8 의 factor_estimators 에서 active 화 예정.
    spread_30y_5y_bps: float = Field(
        default=0.0,
        description="30Y - 5Y in basis points. Long-end curve — F4 term_premium component.",
    )


class InflationSnapshot(StalenessAware):
    cpi_yoy: float = Field(description="CPI YoY %")
    core_cpi_yoy: float = Field(description="Core CPI YoY %")
    momentum_3mo: float = Field(description="CPI 3-month annualized rate")
    momentum_6mo: float = Field(description="CPI 6-month annualized rate")
    accelerating: bool = Field(description="True if 3mo > 6mo > 12mo (CPI)")
    # 2026-05 보강: Fed 공식 inflation 타겟은 PCE. CPI는 시장이 보지만 정책
    # 결정 anchor는 PCE (특히 Core PCE). 두 다 노출하여 LLM이 균형 판단.
    # 2026-05 fix: 결측(fetch 실패) 시 None — 이전엔 default=0.0 이라 "PCE 0%"
    # (디플레) 와 데이터 부재 가 동일 값으로 LLM 에 들어가 구분 불가능했음.
    pce_yoy: float | None = Field(
        default=None, description="PCE YoY % — Fed 공식 inflation 타겟. None=fetch 실패.",
    )
    core_pce_yoy: float | None = Field(
        default=None, description="Core PCE YoY % — Fed 핵심 모니터링. None=fetch 실패.",
    )
    pce_momentum_3mo: float | None = Field(
        default=None, description="Core PCE 3-month annualized — Powell이 자주 인용. None=결측.",
    )


class EmploymentSnapshot(StalenessAware):
    unemployment_rate: float
    rate_change_3mo: float = Field(description="3-month change in UR")
    sahm_rule_triggered: bool = Field(description="Sahm rule recession indicator")
    non_farm_payrolls_3mo_avg: float
    # 2026-05 보강: JOLTS (labor market tightness). UR보다 leading.
    # Job openings는 노동수요, quits rate는 자발적 이직 (confidence proxy).
    job_openings_3mo_avg: float = Field(
        default=0.0,
        description="JOLTS Job Openings (천 명, 3개월 평균). 침체 전 6-12개월 선행 하락.",
    )
    quits_rate: float = Field(
        default=0.0,
        description="JOLTS Quits Rate (% of employment). 노동시장 tightness 핵심.",
    )
    quits_rate_change_6mo: float = Field(
        default=0.0,
        description="Quits rate 6개월 변화. 큰 하락 = 노동시장 cooling.",
    )


class DivergenceScore(StalenessAware):
    us_kr_rate_gap_bps: float = Field(description="US policy rate - KR base rate")
    us_kr_inflation_gap: float
    score: float = Field(ge=-10, le=10, description="Negative = divergence, positive = convergence")


class CentralBankEvent(BaseModel):
    """Not StalenessAware — calendar events are forward-looking."""
    bank: Literal["FED", "BOK", "ECB", "BOJ", "PBOC"]
    event_date: date
    event_type: Literal["rate_decision", "minutes", "speech", "press_conference"]
    description: str = Field(max_length=200)


class RegimeClassification(StalenessAware):
    """Subagent output — schema-locked."""
    quadrant: RegimeQuadrant
    confidence: float = Field(ge=0, le=1)
    drivers: list[str] = Field(min_length=1, max_length=5)
    reasoning: str = Field(max_length=300)


class KRExportSnapshot(StalenessAware):
    """관세청/ECOS 월간 수출액 기반. KR EPS의 가장 강력한 동행/선행 지표."""
    yoy_pct: float = Field(description="Total export YoY %")
    momentum_3mo_pct: float = Field(description="3-month annualized rate")
    momentum_6mo_pct: float = Field(description="6-month annualized rate")
    accelerating: bool = Field(description="True if 3mo > 6mo > yoy (export growth speeding up)")


class KRLeadingIndexSnapshot(StalenessAware):
    """통계청 경기종합지수 — 선행지수 순환변동치 (composite leading index, cycle-adjusted)."""
    cli_value: float = Field(description="Cyclical component of leading index (100 = trend)")
    change_3mo: float = Field(description="3-month absolute change")
    change_6mo: float = Field(description="6-month absolute change")
    phase: Literal["expansion", "peak", "contraction", "trough"] = Field(
        description="Cycle phase by level + momentum"
    )


class KRBusinessSurveySnapshot(StalenessAware):
    """한국은행 기업경기실사지수 (BSI). 100 기준선, 50대=침체 신호."""
    mfg_bsi: float = Field(description="Manufacturing BSI (월간)")
    change_3mo: float = Field(description="3-month absolute change in mfg BSI")
    contraction_signal: bool = Field(description="True if mfg_bsi < 80 (clear contraction)")


class USLeadingIndexSnapshot(StalenessAware):
    """Chicago Fed National Activity Index (CFNAI). 85개 매크로 지표 합성. 0=trend, <0=below trend."""
    cfnai_value: float = Field(description="Current month CFNAI value (standardized, 0=trend)")
    cfnai_ma3: float = Field(description="3-month moving average (CFNAIMA3)")
    recession_signal: bool = Field(description="True if cfnai_ma3 < -0.7 (recession entry threshold)")
    recession_severity: Literal["none", "mild", "moderate", "severe"] = Field(
        default="none",
        description="2026-05 보강: -0.7 mild / -1.5 moderate / -2.5 severe. "
                    "단일 임계 -0.7만으론 강도 분간 못함 (예: COVID -7 vs 일반 침체 -1).",
    )


class GDPNowSnapshot(StalenessAware):
    """Atlanta Fed GDPNow real-time GDP nowcast. % annualized."""
    nowcast_pct: float = Field(description="Latest GDPNow estimate (% annualized)")
    change_from_prior: float = Field(description="Change from prior weekly release")


class FinancialConditionsSnapshot(StalenessAware):
    """Chicago Fed National Financial Conditions Index. 105+ 금융지표 합성.

    0=평균, 양수=긴축, 음수=완화. 1σ 단위로 표준화. >+1 = 침체급 긴축.
    """
    nfci: float = Field(description="National Financial Conditions Index (standardized)")
    anfci: float = Field(description="Adjusted NFCI (removes background macro)")
    regime: Literal["easy", "neutral", "tight", "crisis"] = Field(
        description="<-0.5=easy, -0.5~0.5=neutral, 0.5~1.0=tight, >1.0=crisis"
    )
    tightening: bool = Field(description="True if NFCI 4-week change > +0.2 (긴축 가속)")

    # 2026-05-23 C3 — factor model F1 growth_surprise component.
    # CFNAI 는 FinancialConditions 와는 별개 series (real activity composite) 지만,
    # macro_quant_analyst 가 fci snapshot 을 단일 점에서 확장하는 패턴 (D7) 이라
    # 같은 schema 에 fold-in. C8 의 factor_estimators 에서 active 화.
    cfnai: float = Field(
        default=0.0,
        description="CFNAI (Chicago Fed National Activity Index). 0=trend, +1=above, -1=below.",
    )
    cfnai_3m_avg: float = Field(
        default=0.0,
        description="CFNAI 3-month moving average — NBER recession signal.",
    )


class InflationExpectationsSnapshot(StalenessAware):
    """5Y5Y Forward Breakeven (T5YIFR) + Michigan 1y survey (MICH). Forward-looking."""
    breakeven_5y5y: float = Field(description="5Y5Y forward inflation breakeven (% YoY)")
    michigan_1y: float = Field(description="University of Michigan 1y inflation expectation (% YoY)")
    anchored: bool = Field(
        description="True if 5Y5Y ∈ [1.5, 3.0] AND Michigan 1y ∈ [2.0, 4.0]"
    )
    unanchored_direction: Literal["upside", "downside", "none"] = Field(
        description="upside if breakeven>3 or michigan>4; "
                    "downside if breakeven<1.5 or michigan<2.0"
    )


class FedPathSnapshot(StalenessAware):
    """Fed Funds Futures-implied path, proxied by DGS2 - DFF spread.

    2y Treasury 가격은 향후 ~24개월 Fed 정책 기대를 반영. 정확한 futures와 corr>0.9.
    """
    current_rate_pct: float = Field(description="Effective Fed Funds Rate (DFF), %")
    implied_2y_rate_pct: float = Field(description="2y Treasury yield (DGS2), %")
    path_bps: float = Field(description="(DGS2 - DFF) × 100; 양수=시장이 인상 expect, 음수=인하")
    market_view: Literal["hike", "hold", "cut"] = Field(
        description="path_bps > +50 hike, < -50 cut, else hold"
    )


class FXSnapshot(StalenessAware):
    """USD/KRW + DXY. KRW 약세 + DXY 강세 동시 발생 = 외국인 매도 압력."""
    usd_krw: float = Field(description="KRW per 1 USD")
    dxy: float = Field(description="Broad trade-weighted dollar index")
    krw_change_1m_pct: float = Field(description="USD/KRW 1-month % change (+ = KRW weakening)")
    dxy_change_1m_pct: float = Field(description="DXY 1-month % change (+ = USD strengthening)")
    regime: Literal["krw_strong", "krw_weak", "usd_risk_off", "neutral"] = Field(
        description="krw_weak if KRW>+2% in 1m, usd_risk_off if both KRW and DXY rising together"
    )
    # 2026-05-28 Tier 0 — medium-term KRW trend + BIS REER for F2/F13 factor components.
    krw_change_6m_pct: float = Field(
        default=0.0,
        description="USD/KRW 6-month % change (+ = KRW weakening). Medium-term trend.",
    )
    krw_reer: float | None = Field(
        default=None,
        description="BIS Real Effective Exchange Rate (1994+, index). None=fetch fail.",
    )


class RiskAppetiteSnapshot(StalenessAware):
    """Copper/Gold ratio. Cyclical (Cu) vs Defensive (Au). 위험선호 proxy.

    10y Treasury yield와 0.7+ 상관. Gundlach가 자주 인용하는 단일 risk-on/off 지표.
    """
    copper_price: float = Field(description="COMEX copper futures (HG=F), USD/lb")
    gold_price: float = Field(description="COMEX gold futures (GC=F), USD/oz")
    ratio: float = Field(description="copper / gold * 100 for readability")
    # 2026-05 rename: 실제 window 가 5y. field name 이 1y 라 LLM/reader misled.
    ratio_percentile_5y: float = Field(ge=0, le=1, description="5-year percentile rank of Cu/Au ratio")
    signal: Literal["risk_on", "risk_off", "neutral"] = Field(
        description="risk_on if percentile>0.7, risk_off if <0.3"
    )


class ChinaLeadingSnapshot(StalenessAware):
    """OECD China CLI + 보조 실시간 proxies (USDCNH + iron ore).

    2026-05 보강: OECD CLI는 2-3개월 lag이라 단독으로는 too slow. KR 수출의
    25%가 중국이라 실시간 추적이 필수. Free source로 Caixin PMI 어려워서:
      - USDCNH: 위안 약세 = 정책/경제 우려 신호 (daily)
      - iron ore: China 건설/제조 수요 proxy (daily)
    실무 표준은 Caixin PMI이지만 본 시스템은 무료 source 한계로 보조 신호로 대체.
    """
    cli_value: float = Field(description="China CLI (100 = trend)")
    change_3mo: float = Field(description="3-month absolute change")
    phase: Literal["expansion", "peak", "contraction", "trough"] = Field(
        description="Cycle phase by (level, momentum)"
    )
    # 2026-05 보강 — 실시간 China proxies
    usdcnh: float = Field(
        default=0.0,
        description="USD/CNH offshore. 7.20+ = 정책 약세 / 경제 우려.",
    )
    usdcnh_change_1m_pct: float = Field(
        default=0.0,
        description="USDCNH 1개월 변화. +1.5%+ = 강한 약세 신호.",
    )
    iron_ore: float = Field(
        default=0.0,
        description="SGX iron ore futures (USD/tonne). China 건설 수요 직접 proxy.",
    )
    iron_ore_change_3m_pct: float = Field(
        default=0.0,
        description="Iron ore 3개월 변화율. +10%+ = construction demand 반등.",
    )
    realtime_signal: Literal["expansion", "neutral", "contraction"] = Field(
        default="neutral",
        description="USDCNH + iron ore 합성. CLI lag 보정용 실시간 view.",
    )


class ForeignFlowSnapshot(StalenessAware):
    """KRX 외국인 KOSPI 순매수. 단기 KOSPI 방향성과 매우 높은 상관."""
    net_5d_krw: float = Field(description="외국인 5거래일 누적 순매수 (KRW)")
    net_20d_krw: float = Field(description="외국인 20거래일 누적 순매수 (KRW)")
    signal: Literal["net_buying", "net_selling", "neutral"] = Field(
        description="net_buying if 20d>+1조, net_selling if <-1조"
    )
    # 2026-05-28 Tier 0 — market-cap normalized flow for F2 component.
    # Stambaugh 1986 non-stationarity fix: raw KRW flow is non-stationary as
    # market cap grows; normalizing by KOSPI market cap yields a stationary ratio.
    net_20d_normalized: float = Field(
        default=0.0,
        description="net_20d_krw / KOSPI market_cap (ratio). Period-stationary "
                    "(Stambaugh 1986 non-stationarity fix).",
    )


class PolicyUncertaintySnapshot(StalenessAware):
    """Baker-Bloom-Davis EPU (US + Global). 신문 텍스트 기반 정책 불확실성.

    100 = 1985-2010 평균. 150+ = elevated, 200+ = extreme.
    """
    us_epu: float = Field(description="US Economic Policy Uncertainty (monthly)")
    global_epu: float = Field(description="Global EPU (current-price weighted)")
    us_epu_percentile_5y: float = Field(ge=0, le=1, description="5y historical percentile of US EPU")
    regime: Literal["normal", "elevated", "extreme"] = Field(
        description="normal <150, elevated 150~200, extreme >200 (US EPU level)"
    )


class TailRiskSnapshot(StalenessAware):
    """VVIX (CBOE VIX-of-VIX) + MOVE (ICE BofA Treasury volatility).

    GPR(Geopolitical Risk)의 operational substitute. VVIX/MOVE 동시 급등 =
    옵션 시장이 인지하는 tail event 가능성 상승.
    """
    vvix: float = Field(description="CBOE VIX of VIX (vol of equity vol)")
    move: float = Field(description="ICE BofA MOVE Index (Treasury vol)")
    vvix_percentile_1y: float = Field(ge=0, le=1)
    move_percentile_1y: float = Field(ge=0, le=1)
    signal: Literal["calm", "elevated", "extreme"] = Field(
        description="extreme if both percentiles >0.9; elevated if any >0.75"
    )


# 2026-05-23 C5 — KR equity valuation snapshot, factor model F8 valuation component.
# pykrx 의 KOSPI200 fundamental (PBR/PER/DIV) 평균. KOSPI 200 underlying.
# 첫 *신규 class indicator* — D7 의 신규 class path (analyst 가 MacroReport 의
# Optional field 에 직접 채움; model_copy 아님).
class KRValuationSnapshot(StalenessAware):
    """KOSPI valuation indicators — for factor model F8 valuation.

    PBR < 1.0 = below book value (deep value). Historical avg ~1.0.
    """
    kospi_pbr: float = Field(description="KOSPI 200 PBR")
    kospi_per: float = Field(description="KOSPI 200 forward PER")
    kospi_div_yield: float = Field(description="KOSPI 200 dividend yield %")


# ===========================================================================
# 2026-05-28 Tier 0 — New factor model component snapshots
# ===========================================================================

class CommodityMomentumSnapshot(StalenessAware):
    """Commodity price momentum — F2/F12 components, F13 directly.
    Daily price series (commodities.py) → 3m/6m % change.
    Reference: Erb-Harvey 2006 FAJ, Asness-Moskowitz-Pedersen 2013 JF.
    """
    copper_3m_pct: float = Field(description="Copper (HG=F) 3-month % change")
    copper_6m_pct: float = Field(description="Copper 6-month % change")
    gold_3m_pct: float = Field(description="Gold (GC=F) 3-month % change")
    gold_6m_pct: float = Field(description="Gold 6-month % change")
    wti_3m_pct: float = Field(description="WTI (CL=F) 3-month % change")
    wti_6m_pct: float = Field(description="WTI 6-month % change")
    bcom_3m_pct: float | None = Field(
        default=None,
        description="Bloomberg Commodity Index (^BCOM or DJP ETF proxy) 3m %. None=fetch fail.",
    )


class USEquityValuationSnapshot(StalenessAware):
    """Shiller US CAPE — F8 component (Asness 2003 standard)."""
    cape: float = Field(description="Shiller CAPE (PE10), monthly")
    cape_zscore_30y: float = Field(default=0.0, description="30-year z-score of CAPE")


class GeopoliticalRiskSnapshot(StalenessAware):
    """Caldara-Iacoviello GPR Index — F7 component."""
    gpr_monthly: float = Field(description="GPR Index (monthly, 1900+)")
    gpr_zscore_60m: float = Field(default=0.0, description="60-month z-score")
    gpr_daily: float | None = Field(default=None, description="GPR Daily (1985+). None=fetch fail.")


class ChinaCreditImpulseSnapshot(StalenessAware):
    """China Credit Impulse — F12 (Biggs-Mayer-Pick 2010)."""
    credit_impulse: float = Field(description="Biggs-Mayer-Pick credit impulse (%)")
    credit_to_gdp_ratio: float = Field(description="Raw credit/GDP ratio (%)")
    credit_yoy_pct: float = Field(description="Credit-to-GDP YoY % (1st diff)")


class EarningsRevisionSnapshot(StalenessAware):
    """Earnings Revision Net Ratio — F11 (staggered, 2010+)."""
    sp500_net_revision: float | None = Field(
        default=None,
        description="SP500 aggregated net revision ratio (1m). None=fetch fail or pre-2010.",
    )
    kospi200_net_revision: float | None = Field(
        default=None,
        description="KOSPI200 forward EPS implied 1m. None=fetch fail.",
    )
