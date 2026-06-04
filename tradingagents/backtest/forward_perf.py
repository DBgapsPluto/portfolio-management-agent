"""포트폴리오 realized forward 성과 — 결정론 다이얼 튜닝 채점 (spec 2026-06-04).

[as_of, as_of+H거래일] 구간의 포트폴리오 실현 수익/변동성/MDD/Sharpe.
기존 fetch_returns_matrix + backtest.statistics 재사용. 순수(읽기) 함수.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd

from tradingagents.skills.portfolio.returns_matrix import fetch_returns_matrix
from tradingagents.backtest.statistics import _sharpe, drawdown_analysis

_MIN_OBS: int = 40   # forward 데이터 부족 임계


def score_forward_performance(
    weights: dict[str, float], as_of: date, horizon_trading_days: int = 63,
) -> dict:
    """[as_of, as_of+H거래일] realized 포트 성과. n_obs<40 이면 insufficient_data."""
    tickers = [t for t, w in weights.items() if w > 0]
    if not tickers:
        return {"status": "insufficient_data", "n_obs": 0}

    end = as_of + timedelta(days=math.ceil(horizon_trading_days * 1.6))  # 거래일→캘린더 버퍼
    rm = fetch_returns_matrix(tickers, as_of, end)
    if rm is None or rm.empty:
        return {"status": "insufficient_data", "n_obs": 0}

    rm = rm.iloc[:horizon_trading_days]            # 앞 H 거래일만
    cols = [t for t in rm.columns if t in weights]
    w = pd.Series({t: weights[t] for t in cols})
    port = (rm[cols] * w).sum(axis=1)              # 일별 포트 수익

    n = int(port.shape[0])
    if n < _MIN_OBS:
        return {"status": "insufficient_data", "n_obs": n}

    arr = port.to_numpy()
    return {
        "status": "ok",
        "n_obs": n,
        "sharpe": _sharpe(arr, periods_per_year=252),
        "total_return": float((1.0 + port).prod() - 1.0),
        "ann_vol": float(port.std() * math.sqrt(252)),
        "max_drawdown": drawdown_analysis(arr)["max_drawdown"],
    }
