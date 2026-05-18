"""Tier-5 — Risk-adjusted metrics (Sortino / Calmar / Skew / Kurtosis / Mean reversion)."""
import numpy as np
import pandas as pd
import pandas_ta as ta
from scipy.stats import kurtosis as _kurtosis, skew as _skew

from tradingagents.schemas.technical import (
    ExtendedIndicatorPanel, RiskAdjustedMetrics,
)
from tradingagents.skills.registry import register_skill


@register_skill(name="compute_risk_adjusted", category="technical")
def compute_risk_adjusted(
    prices: pd.DataFrame, ticker: str,
    ext_panel: ExtendedIndicatorPanel | None = None,
) -> RiskAdjustedMetrics:
    """Per-ETF Tier-5 metrics.

    ext_panel: 이미 Tier-1에서 계산된 panel이면 BB %B 재계산 회피.
    """
    sub = prices[prices["ticker"] == ticker].sort_values("date").reset_index(drop=True)
    if len(sub) < 252:
        raise ValueError(f"Need ≥252 data points for {ticker}, got {len(sub)}")

    close = sub["close"].astype(float)
    returns = close.pct_change().dropna()

    last_60 = returns.tail(60)
    mean_60 = float(last_60.mean())
    downside = last_60[last_60 < 0]
    if len(downside) > 1 and float(downside.std()) > 0:
        downside_std_ann = float(downside.std()) * np.sqrt(252.0)
        sortino = (mean_60 * 252.0) / downside_std_ann if downside_std_ann > 0 else 0.0
    else:
        sortino = 0.0

    if len(last_60) >= 8:
        skew_val = float(_skew(last_60, bias=False))
        kurt_val = float(_kurtosis(last_60, fisher=True, bias=False))
    else:
        skew_val = 0.0
        kurt_val = 0.0

    last_252_close = close.tail(252)
    if len(last_252_close) >= 2:
        cummax = last_252_close.cummax()
        drawdown = (last_252_close - cummax) / cummax
        max_dd = float(drawdown.min())
        if max_dd > 0.0:
            max_dd = 0.0
        ann_ret = float(last_252_close.iloc[-1] / last_252_close.iloc[0] - 1.0)
        calmar = ann_ret / abs(max_dd) if max_dd < 0 else 0.0
    else:
        max_dd = 0.0
        calmar = 0.0

    rolling_30 = close.pct_change(30).dropna()
    if len(rolling_30) >= 60:
        last_30 = float(rolling_30.iloc[-1])
        hist = rolling_30.tail(252)
        sd = float(hist.std())
        z_30 = (last_30 - float(hist.mean())) / sd if sd > 0 else 0.0
    else:
        z_30 = 0.0

    if ext_panel is not None:
        bb_pb = float(ext_panel.bb_percent_b)
    else:
        bb = ta.bbands(close, length=20, std=2.0)
        bb_pb = float(bb.iloc[-1, 4])

    rsi = float(ta.rsi(close, length=14).iloc[-1])
    is_rev = bool((bb_pb < 0.0) and (rsi < 35.0) and (z_30 < -1.5))

    last_date = sub["date"].iloc[-1]
    source_date = (
        last_date.date() if hasattr(last_date, "date")
        else pd.Timestamp(last_date).date()
    )

    return RiskAdjustedMetrics(
        ticker=ticker,
        sortino_60d=float(sortino),
        max_drawdown_12m=float(max_dd),
        calmar_12m=float(calmar),
        skewness_60d=skew_val,
        excess_kurtosis_60d=kurt_val,
        return_z_30d=float(z_30),
        is_mean_reversion_candidate=is_rev,
        source_date=source_date,
    )
