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


class InflationSnapshot(StalenessAware):
    cpi_yoy: float = Field(description="CPI YoY %")
    core_cpi_yoy: float = Field(description="Core CPI YoY %")
    momentum_3mo: float = Field(description="3-month annualized rate")
    momentum_6mo: float = Field(description="6-month annualized rate")
    accelerating: bool = Field(description="True if 3mo > 6mo > 12mo")


class EmploymentSnapshot(StalenessAware):
    unemployment_rate: float
    rate_change_3mo: float = Field(description="3-month change in UR")
    sahm_rule_triggered: bool = Field(description="Sahm rule recession indicator")
    non_farm_payrolls_3mo_avg: float


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


class InflationExpectationsSnapshot(StalenessAware):
    """5Y5Y Forward Breakeven (T5YIFR) + Michigan 1y survey (MICH). Forward-looking."""
    breakeven_5y5y: float = Field(description="5Y5Y forward inflation breakeven (% YoY)")
    michigan_1y: float = Field(description="University of Michigan 1y inflation expectation (% YoY)")
    anchored: bool = Field(
        description="True if 5Y5Y ∈ [1.5, 3.0] AND Michigan 1y ∈ [2.0, 4.0]"
    )
    unanchored_direction: Literal["upside", "downside", "none"] = Field(
        description="upside if breakeven>3 or michigan>4; downside if breakeven<1.5"
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


class RiskAppetiteSnapshot(StalenessAware):
    """Copper/Gold ratio. Cyclical (Cu) vs Defensive (Au). 위험선호 proxy.

    10y Treasury yield와 0.7+ 상관. Gundlach가 자주 인용하는 단일 risk-on/off 지표.
    """
    copper_price: float = Field(description="COMEX copper futures (HG=F), USD/lb")
    gold_price: float = Field(description="COMEX gold futures (GC=F), USD/oz")
    ratio: float = Field(description="copper / gold * 100 for readability")
    ratio_percentile_1y: float = Field(ge=0, le=1, description="1-year percentile rank")
    signal: Literal["risk_on", "risk_off", "neutral"] = Field(
        description="risk_on if percentile>0.7, risk_off if <0.3"
    )


class ChinaLeadingSnapshot(StalenessAware):
    """OECD China amplitude-adjusted Composite Leading Indicator (CHNLOLITONOSTSAM).

    Caixin PMI 라이선스 회피 대안. 100 = trend, 100+ = expansion. KR 수출의 25%가
    중국이라 KR ETF 결정에 직접 transmission.
    """
    cli_value: float = Field(description="China CLI (100 = trend)")
    change_3mo: float = Field(description="3-month absolute change")
    phase: Literal["expansion", "peak", "contraction", "trough"] = Field(
        description="Cycle phase by (level, momentum)"
    )


class ForeignFlowSnapshot(StalenessAware):
    """KRX 외국인 KOSPI 순매수. 단기 KOSPI 방향성과 매우 높은 상관."""
    net_5d_krw: float = Field(description="외국인 5거래일 누적 순매수 (KRW)")
    net_20d_krw: float = Field(description="외국인 20거래일 누적 순매수 (KRW)")
    signal: Literal["net_buying", "net_selling", "neutral"] = Field(
        description="net_buying if 20d>+1조, net_selling if <-1조"
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
