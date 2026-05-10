"""Drift between target weights and current portfolio (price-driven)."""
from dataclasses import dataclass


@dataclass
class DriftReport:
    drift_pct: dict[str, float]  # ticker -> abs(target - current)
    max_drift: float
    max_drift_ticker: str | None


def compute_drift(
    target_weights: dict[str, float],
    current_prices: dict[str, float],
    entry_prices: dict[str, float],
) -> DriftReport:
    """Drift = |target - actual_now|, where actual_now is target * (price_now / entry_price)
    re-normalized to sum to 1."""
    if not target_weights:
        return DriftReport(drift_pct={}, max_drift=0.0, max_drift_ticker=None)

    raw_values = {}
    for t, w in target_weights.items():
        p_now = current_prices.get(t, 0.0)
        p_entry = entry_prices.get(t, p_now)
        if p_entry <= 0:
            raw_values[t] = w
        else:
            raw_values[t] = w * (p_now / p_entry)

    total = sum(raw_values.values()) or 1.0
    actual = {t: v / total for t, v in raw_values.items()}

    drift = {t: abs(target_weights[t] - actual.get(t, 0.0)) for t in target_weights}
    max_t = max(drift, key=drift.get)
    return DriftReport(
        drift_pct=drift, max_drift=drift[max_t], max_drift_ticker=max_t,
    )
