import pandas as pd

from tradingagents.dataflows.universe import Universe
from tradingagents.schemas.technical import ETFRanking
from tradingagents.skills.registry import register_skill


_MIN_HISTORY_DAYS = 252  # need 12 months for the 12m window


@register_skill(name="rank_momentum", category="technical")
def rank_momentum(
    prices: pd.DataFrame, universe: Universe,
) -> dict[str, list[ETFRanking]]:
    """Group by category, rank by composite of 3m + 6m + 12m momentum ranks.

    Composite rank = average of per-window ranks within category (lower = better).
    Rank-based composition is robust to outliers — no single window dominates.
    """
    name_lookup = {e.ticker: e.name for e in universe.etfs}
    cat_lookup = {e.ticker: e.category for e in universe.etfs}

    grouped: dict[str, list[ETFRanking]] = {}
    for ticker, sub in prices.groupby("ticker"):
        sub = sub.sort_values("date")
        if len(sub) < _MIN_HISTORY_DAYS:
            continue
        end = float(sub["close"].iloc[-1])
        m3 = (end / float(sub["close"].iloc[-63])) - 1
        m6 = (end / float(sub["close"].iloc[-126])) - 1
        m12 = (end / float(sub["close"].iloc[-252])) - 1

        category = cat_lookup.get(ticker, "기타")
        grouped.setdefault(category, []).append(ETFRanking(
            ticker=ticker, name=name_lookup.get(ticker, ticker),
            momentum_3m=m3, momentum_6m=m6, momentum_12m=m12,
            rank_in_category=1,  # placeholder, set below
        ))

    for cat, items in grouped.items():
        rank_3m = _rank_by(items, lambda r: r.momentum_3m)
        rank_6m = _rank_by(items, lambda r: r.momentum_6m)
        rank_12m = _rank_by(items, lambda r: r.momentum_12m)

        def _composite(r):
            return rank_3m[r.ticker] + rank_6m[r.ticker] + rank_12m[r.ticker]

        items.sort(key=_composite)
        # Competition ranking — equal composites share rank, next non-tied skips ahead
        # e.g., composites [3, 5, 5, 7] → ranks [1, 2, 2, 4]
        prev_score = None
        rank = 0
        for i, item in enumerate(items, start=1):
            score = _composite(item)
            if score != prev_score:
                rank = i
                prev_score = score
            item.rank_in_category = rank

    return grouped


def _rank_by(items: list[ETFRanking], key) -> dict[str, int]:
    """Return {ticker: rank} sorted by key descending (highest momentum = rank 1).

    Competition ranking — equal values share rank, next non-tied skips ahead.
    """
    ordered = sorted(items, key=key, reverse=True)
    result: dict[str, int] = {}
    prev_value = None
    rank = 0
    for i, r in enumerate(ordered, start=1):
        v = key(r)
        if v != prev_value:
            rank = i
            prev_value = v
        result[r.ticker] = rank
    return result
