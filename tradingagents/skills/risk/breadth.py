from datetime import date
from typing import Literal

from tradingagents.schemas.risk import BreadthSnapshot
from tradingagents.skills.registry import register_skill


@register_skill(name="compute_market_breadth", category="risk")
def compute_market_breadth(market: Literal["KOSPI200", "SP500"], as_of: date) -> BreadthSnapshot:
    """Stub for v1: returns synthetic snapshot.

    Live implementation: fetch all constituents from pykrx (KR) or yfinance (US),
    count daily advancing vs declining vs flat. Production version added in
    Plan 3 when wiring is complete.
    """
    # TODO: replace with real implementation in Plan 3 when constituents available
    return BreadthSnapshot(
        market=market,
        advancing_pct=0.55, declining_pct=0.40,
        new_highs_minus_lows=0,
        source_date=as_of, staleness_days=0,
    )
