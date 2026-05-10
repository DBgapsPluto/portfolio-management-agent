from datetime import date

import pandas as pd

from tradingagents.dataflows.fred import fetch_fred_series
from tradingagents.skills.registry import register_skill


@register_skill(name="fetch_fred_series", category="macro")
def fetch_fred_series_skill(
    series: str, start: date, end: date, api_key: str | None = None,
    as_of_date: date | None = None,
) -> pd.Series:
    """Skill-layer wrapper. as_of_date enforces look-ahead bias prevention."""
    return fetch_fred_series(series, start, end, api_key=api_key, as_of_date=as_of_date)
