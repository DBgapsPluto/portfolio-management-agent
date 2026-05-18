from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.skills.news.global_overnight import (
    _classify_regime, _move, _seed, compute_global_overnight_snapshot,
)
from tradingagents.schemas.news import OvernightMove


def _mock_closes(values: dict[str, list[float]]) -> pd.DataFrame:
    idx = pd.date_range("2026-05-12", periods=len(next(iter(values.values()))), freq="B")
    return pd.DataFrame(values, index=idx)


def _make_move(name: str, ticker: str, pct: float) -> OvernightMove:
    return OvernightMove(
        name=name, ticker=ticker, value=100 * (1 + pct / 100), prior=100.0,
        change_abs=pct, change_pct=pct,
        direction="up" if pct > 0.05 else ("down" if pct < -0.05 else "flat"),
    )


def test_move_helper_computes_pct():
    s = pd.Series([100.0, 105.0])
    move = _move("X", "X=F", s)
    assert move is not None
    assert pytest.approx(move.change_pct, 0.01) == 5.0
    assert move.direction == "up"


def test_move_returns_none_on_short_series():
    s = pd.Series([100.0])
    assert _move("X", "X", s) is None


def test_move_direction_flat_for_tiny_change():
    s = pd.Series([100.0, 100.02])
    move = _move("X", "X", s)
    assert move.direction == "flat"


def test_classify_regime_risk_on():
    europe = {"STOXX50": _make_move("STOXX50", "^STOXX50E", 0.6)}
    asia = {"N225": _make_move("N225", "^N225", 0.8)}
    krw = _make_move("USDKRW", "KRW=X", -0.2)  # 원화 강세
    assert _classify_regime(europe, asia, {}, krw) == "risk_on"


def test_classify_regime_risk_off():
    europe = {"STOXX50": _make_move("STOXX50", "^STOXX50E", -0.5)}
    asia = {"N225": _make_move("N225", "^N225", -0.7)}
    assert _classify_regime(europe, asia, {}, None) == "risk_off"


def test_classify_regime_mixed():
    europe = {"STOXX50": _make_move("STOXX50", "^STOXX50E", 0.1)}
    assert _classify_regime(europe, {}, {}, None) == "mixed"


def test_seed_renders_human_readable():
    europe = {"STOXX50": _make_move("STOXX50", "^STOXX50E", 0.4)}
    asia = {"N225": _make_move("N225", "^N225", 0.6)}
    commodities = {"WTI": _make_move("WTI", "CL=F", 1.2)}
    krw = _make_move("USDKRW", "KRW=X", -0.3)
    s = _seed(europe, asia, commodities, krw)
    assert "STOXX50" in s and "N225" in s and "WTI" in s and "USDKRW" in s


def test_snapshot_returns_none_on_empty_fetch():
    with patch(
        "tradingagents.skills.news.global_overnight.fetch_global_overnight_closes",
        return_value=pd.DataFrame(),
    ):
        assert compute_global_overnight_snapshot(date.today()) is None


def test_snapshot_partial_fetch_succeeds():
    closes = _mock_closes({
        "^STOXX50E": [5800.0, 5830.0],
        "^N225":     [62000.0, 62500.0],
        "CL=F":      [101.0, 102.0],
        "KRW=X":     [1493.0, 1500.0],
    })
    with patch(
        "tradingagents.skills.news.global_overnight.fetch_global_overnight_closes",
        return_value=closes,
    ):
        snap = compute_global_overnight_snapshot(date(2026, 5, 18))
        assert snap is not None
        assert "STOXX50" in snap.europe
        assert "N225" in snap.asia
        assert "WTI" in snap.commodities
        assert snap.krw is not None
        assert snap.fetched_count == 4
        # 글로벌 증시 평균 +0.43% 정도 + KRW 강세 아님 (+0.47%) → mixed
        assert snap.risk_regime_overnight in ("risk_on", "mixed")
