"""Macro skills."""
from tradingagents.skills.macro import (
    yield_curve,
    inflation,
    employment,
    fred_fetcher,
    ecos_fetcher,
    divergence,
    calendar,
    regime_classifier,
)

__all__ = [
    "yield_curve",
    "inflation",
    "employment",
    "fred_fetcher",
    "ecos_fetcher",
    "divergence",
    "calendar",
    "regime_classifier",
]
