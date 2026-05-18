from typing import Literal

from pydantic import Field

from tradingagents.schemas._base import StalenessAware


class VolatilitySnapshot(StalenessAware):
    index_name: Literal["VIX", "VKOSPI"]
    current_value: float = Field(ge=0)
    zscore_30d: float
    percentile_5y: float = Field(ge=0, le=1)
    change_4w: float = Field(
        default=0.0,
        description="4-week absolute change in vol index. Positive = rising stress",
    )


class SpreadSnapshot(StalenessAware):
    region: Literal["US_IG", "US_HY", "KR_IG"]
    current_bps: float
    percentile_5y: float = Field(ge=0, le=1)
    widening: bool
    momentum_zscore: float = Field(
        default=0.0,
        description="60일 변화의 z-score. >+1.5 = 가속 widening, <-1.5 = 가속 tightening",
    )


class SentimentSnapshot(StalenessAware):
    index_name: Literal["fear_greed_cnn", "fear_greed_alt"]
    current_value: int = Field(ge=0, le=100)
    label: Literal["extreme_fear", "fear", "neutral", "greed", "extreme_greed"]
    trend_7d: Literal["rising", "falling", "flat"]


class BreadthSnapshot(StalenessAware):
    market: Literal["KOSPI200", "SP500"]
    advancing_pct: float = Field(ge=0, le=1)
    declining_pct: float = Field(ge=0, le=1)
    new_highs_minus_lows: int


class PCASnapshot(StalenessAware):
    first_eigenvalue_share: float = Field(ge=0, le=1, description="Variance explained by PC1")
    n_assets_analyzed: int = Field(ge=2)
    is_concentrated: bool = Field(description="True if first_eigenvalue_share > 0.6")


class SystemicRiskScore(StalenessAware):
    """Subagent output."""
    score: float = Field(ge=0, le=10)
    regime: Literal["risk_on", "risk_off", "neutral"]
    drivers: list[str] = Field(min_length=1, max_length=5)
    reasoning: str = Field(max_length=300, default="")


class VIXTermStructureSnapshot(StalenessAware):
    """VIX front (spot) vs VXV (3-month forward).

    contango (3m > front) = 정상 우상향 곡선, 시장은 calm 현재 stress가 멀리 있다고 봄
    backwardation (front > 3m) = 현재 패닉, 향후 진정 기대 → 위기/recession 신호
    """
    vix_front: float = Field(ge=0)
    vix_3m: float = Field(ge=0)
    ratio: float = Field(description="vix_3m / vix_front; >1.05 contango, <0.95 backwardation")
    regime: Literal["contango", "flat", "backwardation"] = Field(
        description="contango>1.05, flat 0.95~1.05, backwardation<0.95"
    )


class SkewSnapshot(StalenessAware):
    """CBOE SKEW Index. 100 = standard normal distrib. 외가격 풋 헷지 수요 measure.

    역사 평균 ~118. >130 = elevated tail hedge demand. >145 = extreme.
    """
    skew_value: float
    percentile_1y: float = Field(ge=0, le=1)
    tail_hedge_signal: Literal["low", "normal", "elevated", "extreme"] = Field(
        description="<120 low, 120~130 normal, 130~145 elevated, >145 extreme"
    )


class VxnSnapshot(StalenessAware):
    """CBOE NASDAQ-100 Volatility (VXN). 기술주 편중 stress.

    VXN > VIX (양수 spread) = 기술주 stress가 broad market 보다 큼.
    """
    current_value: float = Field(ge=0)
    zscore_30d: float
    percentile_5y: float = Field(ge=0, le=1)
    spread_vs_vix: float = Field(
        description="VXN - VIX. Positive = 기술주 stress > broad. >5 = 의미있는 편중"
    )


class RealYieldsSnapshot(StalenessAware):
    """TIPS 기반 실질금리. 명목금리 - 기대인플레 ≈ 실질 성장 기대치.

    10y 실질금리 > +2% = 매우 긴축 (자산 가격 압박)
    10y 실질금리 < 0% = 완화 (위험자산 우호)
    """
    tips_10y: float = Field(description="10년 TIPS yield (%)")
    tips_5y: float = Field(description="5년 TIPS yield (%)")
    spread_10y_5y: float = Field(description="장기 실질금리 spread (10y - 5y)")
    regime: Literal["accommodative", "neutral", "tight", "very_tight"] = Field(
        description="<0 accommodative, 0~1 neutral, 1~2 tight, >2 very_tight"
    )


class FundingStressSnapshot(StalenessAware):
    """Funding stress proxy: SOFR vs 3-month T-bill spread.

    SOFR > T-bill spread > +20bps = 은행 funding stress (collateral 부족)
    TED spread(LIBOR 기반)가 단종된 후의 표준 대체 지표.
    """
    sofr: float = Field(description="Secured Overnight Financing Rate (%)")
    tbill_3m: float = Field(description="3-month Treasury bill yield (%)")
    spread_bps: float = Field(description="(SOFR - T-bill) × 100, bps")
    regime: Literal["calm", "elevated", "stress"] = Field(
        description="<+10bps calm, 10~20 elevated, >+20 stress"
    )


class CreditQualitySnapshot(StalenessAware):
    """AAA vs BBB OAS quality spread. 신용 등급간 differential 위험 인식.

    Quality spread (BBB-AAA) 확대 = 시장이 BBB 추가 위험 가산 → flight to quality.
    """
    aaa_oas_bps: float = Field(description="AAA corporate OAS (bps)")
    bbb_oas_bps: float = Field(description="BBB corporate OAS (bps)")
    quality_spread_bps: float = Field(description="BBB - AAA spread (bps)")
    percentile_5y: float = Field(ge=0, le=1, description="quality_spread 5y percentile")
    regime: Literal["calm", "elevated", "stress"] = Field(
        description="percentile<0.5 calm, 0.5~0.85 elevated, >0.85 stress"
    )


class KRYieldCurveSnapshot(StalenessAware):
    """한국 국고채 yield curve. 10y-3y spread → 한국 경기 사이클 정보."""
    treasury_3y: float = Field(description="국고채 3년 yield (%)")
    treasury_10y: float = Field(description="국고채 10년 yield (%)")
    spread_10y_3y_bps: float = Field(description="(10y - 3y) × 100, bps")
    inverted: bool = Field(description="True if spread < 0 (역전)")
    regime: Literal["normal", "flat", "inverted"] = Field(
        description=">+50bps normal, -10~+50 flat, <-10 inverted"
    )


class KRCorpSpreadSnapshot(StalenessAware):
    """한국 회사채(AA-) 3y vs 국고채 3y spread. KR 신용 risk 진단."""
    corp_yield_3y: float = Field(description="회사채 AA- 3y yield (%)")
    treasury_3y: float = Field(description="국고채 3y yield (%)")
    spread_bps: float = Field(description="(corp - treasury) × 100, bps")
    percentile_5y: float = Field(ge=0, le=1)
    regime: Literal["calm", "elevated", "stress"] = Field(
        description="percentile<0.5 calm, 0.5~0.85 elevated, >0.85 stress"
    )


class KRMarginDebtSnapshot(StalenessAware):
    """KRX 신용잔고 (KOSPI). 한국 leverage 추적.

    급증 = retail euphoria 위험 (peak signal), 급락 = forced selling 위기.
    """
    balance_krw: float = Field(description="신용잔고 (KRW)")
    change_20d_pct: float = Field(description="20거래일 변화율 (%)")
    percentile_1y: float = Field(ge=0, le=1, description="1y level percentile")
    signal: Literal["normal", "euphoria", "deleveraging"] = Field(
        description="percentile>0.85 + change>+10% euphoria, change<-15% deleveraging"
    )


class KRMarketTierSnapshot(StalenessAware):
    """KOSPI vs KOSDAQ 상대 성과. KR 내부 risk on/off 분류.

    KOSDAQ outperform = 중소형 risk-on, KOSPI outperform = 대형주 flight-to-quality.
    """
    kospi_return_20d_pct: float = Field(description="KOSPI 20거래일 수익률 (%)")
    kosdaq_return_20d_pct: float = Field(description="KOSDAQ 20거래일 수익률 (%)")
    relative_perf_pct: float = Field(description="KOSDAQ - KOSPI (% diff)")
    signal: Literal["large_cap_risk_off", "neutral", "small_cap_risk_on"] = Field(
        description="diff>+3% small_cap_risk_on, diff<-3% large_cap_risk_off"
    )


class EquityBondCorrelationSnapshot(StalenessAware):
    """Equity-bond 60일 rolling correlation. 통상 음수(분산효과).

    positive flip = stagflation/inflation regime의 정체 신호.
    1970s, 2022 같은 시기에 발생; 60/40 portfolio의 hedge가 사라짐.
    """
    correlation_60d: float = Field(ge=-1, le=1, description="SPY-TLT 60-day rolling corr")
    change_3m: float = Field(description="3개월 전 대비 상관계수 변화")
    regime: Literal["normal_hedge", "weakening_hedge", "positive_flip", "extreme_positive"] = Field(
        description="<-0.3 normal_hedge, -0.3~0 weakening, 0~+0.3 positive_flip, >+0.3 extreme"
    )
