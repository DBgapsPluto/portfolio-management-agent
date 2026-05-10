"""Daily trigger evaluator — safe condition parser (D14, no eval/exec)."""
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from tradingagents.skills.risk.volatility import fetch_volatility_index

_TRIGGERS_YAML = Path(__file__).parent.parent.parent / "presets" / "triggers_default.yaml"

_COMPARISON_RE = re.compile(
    r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*(>=|<=|==|!=|>|<)\s*(-?\d+(?:\.\d+)?)\s*$"
)


@dataclass
class TriggerResult:
    fired: list[str] = field(default_factory=list)
    suggested_action: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


class _ConditionParser:
    """Regex-based condition parser. Supports AND/OR of comparisons. No eval/exec."""

    def __init__(self, condition: str, ctx: dict[str, Any]) -> None:
        self._condition = condition
        self._ctx = ctx

    def evaluate(self) -> bool:
        return self._parse_or(self._condition)

    def _parse_or(self, expr: str) -> bool:
        parts = expr.split(" OR ")
        return any(self._parse_and(p) for p in parts)

    def _parse_and(self, expr: str) -> bool:
        parts = expr.split(" AND ")
        return all(self._parse_comparison(p) for p in parts)

    def _parse_comparison(self, expr: str) -> bool:
        m = _COMPARISON_RE.match(expr)
        if not m:
            raise ValueError(f"Malformed condition clause: {expr!r}")
        var, op, num_str = m.group(1), m.group(2), m.group(3)
        value = self._ctx[var]  # raises KeyError if missing
        threshold = float(num_str)
        match op:
            case ">":
                return value > threshold
            case "<":
                return value < threshold
            case ">=":
                return value >= threshold
            case "<=":
                return value <= threshold
            case "==":
                return value == threshold
            case "!=":
                return value != threshold
            case _:
                raise ValueError(f"Unknown operator: {op!r}")


def _load_triggers() -> list[dict]:
    with _TRIGGERS_YAML.open() as f:
        data = yaml.safe_load(f)
    return data["triggers"]


def _build_context(as_of: date) -> dict[str, Any]:
    from tradingagents.dataflows.fred import fetch_fred_series
    from tradingagents.dataflows.pykrx_data import fetch_etf_snapshot_by_date

    # VIX
    vix_snap = fetch_volatility_index("VIX", as_of)
    vix = vix_snap.current_value

    # VIX 1-day change: need 5-day window to get two trading days
    start_vix = as_of - timedelta(days=7)
    vix_series = fetch_fred_series("VIXCLS", start_vix, as_of)
    if len(vix_series) >= 2:
        vix_change_1d = float((vix_series.iloc[-1] - vix_series.iloc[-2]) / vix_series.iloc[-2])
    else:
        vix_change_1d = 0.0

    # VKOSPI
    vkospi_snap = fetch_volatility_index("VKOSPI", as_of)
    vkospi = vkospi_snap.current_value

    # Yield curve spread (10Y - 2Y in bps)
    start_yield = as_of - timedelta(days=10)
    us_10y = fetch_fred_series("DGS10", start_yield, as_of)
    us_2y = fetch_fred_series("DGS2", start_yield, as_of)
    if not us_10y.empty and not us_2y.empty:
        spread_10y_2y_bps = float((us_10y.iloc[-1] - us_2y.iloc[-1]) * 100)
    else:
        spread_10y_2y_bps = 0.0

    # KOSPI 1-day return
    kospi_return_1d = 0.0  # placeholder — KOSPI index fetch not in scope here

    # Max ETF weight from snapshot
    snap = fetch_etf_snapshot_by_date(as_of)
    if not snap.empty and "close" in snap.columns and snap["close"].sum() > 0:
        weights = snap["close"] / snap["close"].sum()
        any_etf_weight = float(weights.max())
    else:
        any_etf_weight = 0.0

    return {
        "vix": vix,
        "vix_change_1d": vix_change_1d,
        "vkospi": vkospi,
        "spread_10y_2y_bps": spread_10y_2y_bps,
        "kospi_return_1d": kospi_return_1d,
        "any_etf_weight": any_etf_weight,
    }


def run(as_of: str | date, portfolio_path: Path | None = None) -> TriggerResult:
    """Evaluate all daily triggers against current market context.

    Args:
        as_of: Date to evaluate (str 'YYYY-MM-DD' or date).
        portfolio_path: Optional path to portfolio file (reserved for future use).

    Returns:
        TriggerResult with fired trigger names and suggested action.
    """
    if isinstance(as_of, str):
        as_of = date.fromisoformat(as_of)

    ctx = _build_context(as_of)
    triggers = _load_triggers()

    fired: list[str] = []
    suggested_action: str | None = None

    # Priority: emergency_defensive_proposal > rebalance_proposal > alert
    _priority = {"emergency_defensive_proposal": 2, "rebalance_proposal": 1, "alert": 0}

    for trigger in triggers:
        name = trigger["name"]
        condition = trigger["condition"]
        action = trigger["action"]
        if _ConditionParser(condition, ctx).evaluate():
            fired.append(name)
            if suggested_action is None or _priority.get(action, -1) > _priority.get(suggested_action, -1):
                suggested_action = action

    return TriggerResult(
        fired=fired,
        suggested_action=suggested_action if fired else None,
        context=ctx,
    )
