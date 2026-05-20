"""Tier-3 — Universe breadth (188 ETF 집계 indicator).

%above_MA / new highs-lows / advance-decline / universe vol regime.

2026-05 Bug-E fix: 카테고리(국내/해외/채권/원자재/기타) prefix별 sub-breadth도
계산하여 sub_pct_above_ma200 dict에 노출. 188 ETF가 자산군별로 섞여있어
전체 pct만으론 KR vs US 분리된 신호를 못 잡음.
"""
import numpy as np
import pandas as pd

from tradingagents.dataflows.universe import Universe
from tradingagents.schemas.technical import UniverseBreadthSnapshot
from tradingagents.skills.registry import register_skill


_AD_RATIO_CAP = 10.0


def _category_prefix(category: str) -> str:
    """첫 단어를 prefix로 (국내_주식 → 국내). 분류 그룹."""
    if not category:
        return "기타"
    head = category.split("_", 1)[0].split(" ", 1)[0]
    return head or "기타"


@register_skill(name="compute_universe_breadth", category="technical")
def compute_universe_breadth(
    prices: pd.DataFrame, universe: Universe | None = None,
) -> UniverseBreadthSnapshot:
    """Aggregate breadth metrics over the entire universe.

    prices: DataFrame with at minimum [date, close, ticker]. ≥252 rows of history
        recommended for 52w highs/lows; ≥260 rows for vol_z (60d + 252d window).
    universe: optional. 제공 시 카테고리 prefix별 sub_pct_above_ma200 계산.
    """
    pivot = prices.pivot(index="date", columns="ticker", values="close").sort_index()
    if pivot.empty:
        raise ValueError("empty price matrix")

    last_close = pivot.iloc[-1]
    n_total = int(len(pivot.columns))

    ma50 = pivot.rolling(50).mean().iloc[-1]
    ma200 = pivot.rolling(200).mean().iloc[-1]
    eligible_mask = ma200.notna() & last_close.notna()
    n_eligible = int(eligible_mask.sum())

    if n_eligible == 0:
        pct50 = pct200 = 0.0
    else:
        pct50 = float(((last_close > ma50) & eligible_mask).sum()) / n_eligible
        pct200 = float(((last_close > ma200) & eligible_mask).sum()) / n_eligible

    window_252 = pivot.tail(252)
    if len(window_252) >= 60:
        new_highs = int(((last_close >= window_252.max()) & last_close.notna()).sum())
        new_lows = int(((last_close <= window_252.min()) & last_close.notna()).sum())
    else:
        new_highs = new_lows = 0

    returns = pivot.pct_change()
    ret_5d = (1.0 + returns.tail(5)).prod() - 1.0
    advancing_5d = int((ret_5d > 0).sum())
    declining_5d = int((ret_5d < 0).sum())
    if declining_5d == 0:
        ad_ratio = _AD_RATIO_CAP if advancing_5d > 0 else 1.0
    else:
        ad_ratio = min(advancing_5d / declining_5d, _AD_RATIO_CAP)

    daily_advancing = (returns > 0).sum(axis=1)
    daily_declining = (returns < 0).sum(axis=1)
    ad_line = (daily_advancing - daily_declining).cumsum()
    last_5 = ad_line.tail(5)
    if len(last_5) >= 2:
        diff = float(last_5.iloc[-1] - last_5.iloc[0])
        ad_slope = 1.0 if diff > 0 else (-1.0 if diff < 0 else 0.0)
    else:
        ad_slope = 0.0

    rolling_vol = returns.rolling(60).std() * np.sqrt(252.0)
    daily_median_vol = rolling_vol.median(axis=1).dropna()
    if len(daily_median_vol) >= 60:
        current_vol = float(daily_median_vol.iloc[-1])
        tail = daily_median_vol.tail(252)
        sd = float(tail.std())
        vol_z = float((current_vol - float(tail.mean())) / sd) if sd > 0 else 0.0
    else:
        current_vol = 0.0
        vol_z = 0.0

    if pct200 > 0.6 and ad_ratio > 1.0 and ad_slope >= 0:
        regime = "broad_risk_on"
    elif pct200 < 0.3:
        regime = "broad_risk_off"
    else:
        regime = "narrow"

    # Sub-breadth by category prefix (Bug-E fix). universe 제공 시에만.
    sub_pct200: dict[str, float] = {}
    if universe is not None:
        prefix_lookup = {e.ticker: _category_prefix(e.category) for e in universe.etfs}
        # 각 prefix의 tickers 모아서 prefix별 pct_above_ma200 계산
        prefix_groups: dict[str, list[str]] = {}
        for ticker, prefix in prefix_lookup.items():
            if ticker in last_close.index:
                prefix_groups.setdefault(prefix, []).append(ticker)
        for prefix, tickers in prefix_groups.items():
            mask = eligible_mask.loc[tickers] if all(t in eligible_mask.index for t in tickers) else None
            if mask is None or mask.sum() == 0:
                continue
            sub_above = ((last_close.loc[tickers] > ma200.loc[tickers]) & mask).sum()
            sub_pct200[prefix] = float(sub_above) / float(mask.sum())

    last_date = pivot.index[-1]
    source_date = (
        last_date.date() if hasattr(last_date, "date")
        else pd.Timestamp(last_date).date()
    )

    return UniverseBreadthSnapshot(
        n_total=n_total,
        n_eligible=n_eligible,
        pct_above_ma50=pct50,
        pct_above_ma200=pct200,
        new_52w_highs=new_highs,
        new_52w_lows=new_lows,
        advance_decline_5d_ratio=float(ad_ratio),
        ad_line_5d_slope=ad_slope,
        universe_vol_median=current_vol,
        universe_vol_z=vol_z,
        regime=regime,
        sub_pct_above_ma200=sub_pct200,
        source_date=source_date,
    )
