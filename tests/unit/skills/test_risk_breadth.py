from datetime import date

import pandas as pd

from tradingagents.skills.risk import breadth
from tradingagents.skills.risk.breadth import compute_market_breadth


def test_breadth_stub_returns_snapshot():
    snap = compute_market_breadth("KOSPI200", date(2026, 5, 10))
    assert snap.market == "KOSPI200"
    assert 0 <= snap.advancing_pct <= 1


def test_kospi200_breadth_uses_top200_mktcap_proxy(monkeypatch):
    """구성종목 endpoint(get_index_portfolio_deposit_file)가 깨져도(빈 list)
    시총 top-200 등락률 proxy 로 실신호를 내야 한다 — sentinel(0.5/staleness=99) 회피.
    """
    # 250 종목: 시총 내림차순 → top-200 = 처음 200행 (등락률 120 상승/80 하락)
    idx = [f"{i:06d}" for i in range(250)]
    df = pd.DataFrame(
        {
            "등락률": [1.0] * 120 + [-1.0] * 80 + [0.5] * 50,
            "시가총액": list(range(250, 0, -1)),
        },
        index=idx,
    )
    monkeypatch.setattr(
        "pykrx.stock.get_index_portfolio_deposit_file",
        lambda d, code: [], raising=False,
    )
    monkeypatch.setattr(
        "pykrx.stock.get_market_ohlcv_by_ticker",
        lambda d, market: df, raising=False,
    )

    snap = breadth._kospi200_breadth(date(2026, 6, 2))

    assert snap.staleness_days != 99          # sentinel 아님
    assert snap.advancing_pct == 120 / 200    # top-200 등락률 (실신호)
