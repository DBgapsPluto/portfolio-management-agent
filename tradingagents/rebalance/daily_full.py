"""daily 오케스트레이션 — reprice → triggers → tier target → run_rebalance (스펙 §5).

LLM 0. clusters=[] (daily overlays/reassess는 ticker set 불변 — correlation 검증 생략).
"""
import json
import logging
from datetime import date
from pathlib import Path

from tradingagents.rebalance.pricing import fetch_current_prices  # noqa: F401 (monkeypatch)
from tradingagents.rebalance.holdings import load_prev_holdings
from tradingagents.dataflows.universe import load_universe  # noqa: F401 (monkeypatch)
from tradingagents.rebalance.engine import reprice_holdings, make_is_risk, run_rebalance
from tradingagents.rebalance import daily_triggers
from tradingagents.rebalance.triggers import evaluate_drift, route_tier
from tradingagents.rebalance.overlay import defensive_overlay, risk_on_overlay
from tradingagents.rebalance.reassess import reassess_target
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.rebalance.types import RebalanceResult

logger = logging.getLogger(__name__)


def _load_prev(previous_path: str | None) -> tuple[dict, int, dict]:
    """Return (prev_qty, prev_cash, prev_target_weights).

    prev_target is read from portfolio.json 'weights' key written by a prior run.
    """
    if not previous_path:
        return {}, 0, {}
    prev_qty, prev_cash = load_prev_holdings(Path(previous_path))
    prev_target: dict[str, float] = {}
    pj = Path(previous_path) / "portfolio.json"
    if pj.exists():
        prev_target = json.loads(pj.read_text(encoding="utf-8")).get("weights", {})
    return prev_qty, prev_cash, prev_target


def _eval_triggers(
    *, current: dict, prev_target: dict, dials: dict,
    as_of: str, previous_path: str | None, is_risk,
) -> tuple[str, dict, bool]:
    """Return (tier, trigger_ctx, reassess_fired)."""
    trig = daily_triggers.run(as_of=as_of, portfolio_path=previous_path, current_weights=current)
    drift = evaluate_drift(current, prev_target, dials, is_risk)
    reassess_fired = daily_triggers.evaluate_reassess(trig.context)
    tier = route_tier(trig.suggested_action, drift, reassess_fired)
    return (
        tier,
        {"fired": trig.fired, "suggested_action": trig.suggested_action, "drift": drift},
        reassess_fired,
    )


def run(as_of: str, previous_path: str | None = None, out_dir=None) -> RebalanceResult:
    """Daily orchestration entry point.

    NOTE: clusters=[] — daily overlays/reassess keep the ticker set unchanged,
    so cluster-share delta is minimal. Correlation mandate check is skipped.
    """
    capital: int = DEFAULT_CONFIG.get("capital_krw", 1_000_000_000)
    dials: dict = DEFAULT_CONFIG.get("rebalance", {})

    prev_qty, prev_cash, prev_target = _load_prev(previous_path)
    prices = fetch_current_prices(date.fromisoformat(as_of))
    universe = load_universe(Path(DEFAULT_CONFIG.get("universe_path", "./data/universe.json")))
    is_risk = make_is_risk(universe)
    current = reprice_holdings(prev_qty, prev_cash, prices)

    tier, trig_ctx, reassess_fired = _eval_triggers(
        current=current, prev_target=prev_target, dials=dials,
        as_of=as_of, previous_path=previous_path, is_risk=is_risk,
    )

    # Determine target weights per tier
    defensive_target: float = dials.get("defensive_target", 0.55)
    step: float = dials.get("reassess_tilt_step", 0.05)
    target: dict | None = None

    if tier in ("event:emergency_defensive", "drift:defensive"):
        target = defensive_overlay(prev_target or current, is_risk, defensive_target)
    elif tier == "event:risk_on":
        target = risk_on_overlay(prev_target or current, is_risk, step)
    elif tier == "drift:rebalance":
        target = prev_target or current     # restore previous target
    elif tier == "reassess":
        target = reassess_target(current, is_risk, as_of, previous_path)

    # Monitoring-only tiers or no actionable target
    if tier in ("none", "alert") or target is None:
        return RebalanceResult(
            as_of=as_of,
            tier="none" if target is None else tier,
            current_weights=current,
            trigger=trig_ctx,
        )

    resolved_out = (
        Path(out_dir)
        if out_dir
        else Path(DEFAULT_CONFIG.get("artifacts_dir", "./artifacts")) / as_of
    )
    resolved_out.mkdir(parents=True, exist_ok=True)

    if tier not in ("none", "alert"):
        logger.warning(
            "daily: clusters 미확보 — correlation 검증 생략(종목 교체 0). tier=%s", tier
        )

    res = run_rebalance(
        as_of=as_of, tier=tier, capital=capital,
        prev_qty=prev_qty, prev_cash=prev_cash,
        target_weights=target, prices=prices, universe=universe,
        clusters=[], previous_weights=prev_target, dials=dials,
        out_dir=resolved_out, previous_path=previous_path or "",
        deep_llm=None,
    )
    res.trigger = trig_ctx
    return res
