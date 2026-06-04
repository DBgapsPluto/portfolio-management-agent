"""SP500 earnings revision — yfinance Action 코드 매핑 회귀.

yfinance upgrades_downgrades 의 'Action' 컬럼이 'up'/'down'/'main'/'reit'/'init'
으로 바뀌었는데 코드가 옛 'upgrade'/'downgrade' 리터럴만 매칭 → 항상 0 → None
(F11 US earnings revision silent dead). 신규 코드 매핑.
"""
from datetime import date

import pandas as pd

from tradingagents.skills.research import earnings_revision as er


def test_sp500_net_revision_maps_up_down_action_codes(monkeypatch):
    """yfinance 신규 Action 코드 'up'/'down' 을 상향/하향으로 집계해야 한다."""
    monkeypatch.setattr(er, "load_sp500_constituents", lambda: ["AAA", "BBB"])

    idx = pd.DatetimeIndex([pd.Timestamp("2026-06-01")] * 3)
    ud_df = pd.DataFrame({"Action": ["up", "up", "down"]}, index=idx)

    class FakeTicker:
        def __init__(self, ticker):
            pass

        @property
        def upgrades_downgrades(self):
            return ud_df

    monkeypatch.setattr(er.yf, "Ticker", FakeTicker)

    r = er.compute_sp500_net_revision(date(2026, 6, 2), lookback_days=30)

    # 종목당 up=2, down=1 → total_up=4, total_down=2 → net=(4-2)/6
    assert r is not None
    assert abs(r - (2 / 6)) < 1e-9
