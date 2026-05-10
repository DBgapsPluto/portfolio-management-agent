from datetime import date

import pandas as pd

from tradingagents.dataflows.ecos import fetch_ecos_series
from tradingagents.skills.registry import register_skill


@register_skill(name="fetch_ecos_series", category="macro")
def fetch_ecos_series_skill(
    name: str, start: date, end: date, api_key: str | None = None, freq: str = "M",
    as_of_date: date | None = None,
) -> pd.Series:
    """ECOS skill wrapper. as_of_date enforces point-in-time truncation."""
    return fetch_ecos_series(
        name, start, end, api_key=api_key, freq=freq, as_of_date=as_of_date,
    )
