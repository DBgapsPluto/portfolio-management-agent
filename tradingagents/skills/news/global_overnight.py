"""Tier-1 — Global overnight snapshot (9 non-US assets).

이전 분석가가 안 잡는 차원만 잡는다:
- macro_quant: US Treasury (DGS), 달러 (DTWEXBGS), gold/copper
- market_risk: VIX/SKEW/credit/SPY+sectors/EWY
- technical:   188 KR ETF
→ 글로벌 overnight (유럽/아시아 증시, WTI/NG, USDKRW)이 사각지대.
"""
from datetime import date
from typing import Literal

import pandas as pd

from tradingagents.dataflows.global_overnight import (
    GLOBAL_OVERNIGHT_TICKERS, fetch_global_overnight_closes,
)
from tradingagents.schemas.news import (
    GlobalOvernightSnapshot, OvernightMove,
)
from tradingagents.skills.registry import register_skill


def _move(name: str, ticker: str, series: pd.Series) -> OvernightMove | None:
    s = series.dropna()
    if len(s) < 2:
        return None
    value = float(s.iloc[-1])
    prior = float(s.iloc[-2])
    if prior == 0:
        return None
    change_abs = value - prior
    change_pct = (change_abs / prior) * 100.0
    direction: Literal["up", "down", "flat"] = (
        "up" if change_pct > 0.05
        else "down" if change_pct < -0.05
        else "flat"
    )
    return OvernightMove(
        name=name, ticker=ticker, value=value, prior=prior,
        change_abs=change_abs, change_pct=change_pct, direction=direction,
    )


def _classify_regime(
    europe: dict, asia: dict, commodities: dict, krw: OvernightMove | None,
) -> Literal["risk_on", "risk_off", "mixed"]:
    """간단한 글로벌 risk regime 분류.

    risk_on: 글로벌 증시 평균 > +0.3% AND USDKRW 약세 (KRW 강세)
    risk_off: 글로벌 증시 평균 < -0.3% OR USDKRW 강세 (KRW 약세) > +0.5%
    """
    equity_moves: list[float] = []
    for d in (europe, asia):
        equity_moves.extend(m.change_pct for m in d.values())
    if not equity_moves:
        return "mixed"
    equity_avg = sum(equity_moves) / len(equity_moves)

    krw_pct = krw.change_pct if krw is not None else 0.0

    if equity_avg > 0.3 and krw_pct < 0.3:
        return "risk_on"
    if equity_avg < -0.3 or krw_pct > 0.5:
        return "risk_off"
    return "mixed"


def _seed(
    europe: dict, asia: dict, commodities: dict, krw: OvernightMove | None,
) -> str:
    parts: list[str] = []
    for name, m in {**europe, **asia}.items():
        parts.append(f"{name} {m.change_pct:+.2f}%")
    for name, m in commodities.items():
        parts.append(f"{name} {m.change_pct:+.2f}%")
    if krw is not None:
        parts.append(f"USDKRW {krw.value:,.1f} ({krw.change_pct:+.2f}%)")
    return " / ".join(parts)[:300]


@register_skill(name="compute_global_overnight_snapshot", category="news")
def compute_global_overnight_snapshot(
    as_of: date,
) -> GlobalOvernightSnapshot | None:
    """Return None on total fetch failure."""
    closes = fetch_global_overnight_closes(as_of)
    if closes is None or closes.empty:
        return None

    europe: dict[str, OvernightMove] = {}
    asia: dict[str, OvernightMove] = {}
    commodities: dict[str, OvernightMove] = {}
    krw: OvernightMove | None = None

    for group_name, mapping in GLOBAL_OVERNIGHT_TICKERS.items():
        for friendly, ticker in mapping.items():
            if ticker not in closes.columns:
                continue
            move = _move(friendly, ticker, closes[ticker])
            if move is None:
                continue
            if group_name == "europe":
                europe[friendly] = move
            elif group_name == "asia":
                asia[friendly] = move
            elif group_name == "commodities":
                commodities[friendly] = move
            elif group_name == "krw":
                krw = move

    fetched_count = len(europe) + len(asia) + len(commodities) + (1 if krw else 0)
    if fetched_count == 0:
        return None

    regime = _classify_regime(europe, asia, commodities, krw)
    seed = _seed(europe, asia, commodities, krw)

    last_date = closes.dropna(how="all").index[-1]
    source_date = (
        last_date.date() if hasattr(last_date, "date")
        else pd.Timestamp(last_date).date()
    )

    return GlobalOvernightSnapshot(
        europe=europe, asia=asia, commodities=commodities, krw=krw,
        risk_regime_overnight=regime, narrative_seed=seed,
        fetched_count=fetched_count,
        source_date=source_date,
    )
