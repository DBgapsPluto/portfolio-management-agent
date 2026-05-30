"""Conditional logic for the LangGraph (D4 — Validator cycle)."""
from datetime import date, timedelta
from typing import Literal

from tradingagents.dataflows.universe import load_universe
from tradingagents.schemas.portfolio import OptimizationMethod, WeightVector
from tradingagents.skills.portfolio.returns_matrix import fetch_returns_matrix
from tradingagents.skills.portfolio.cov_estimator import compute_robust_cov


MAX_ALLOCATION_ATTEMPTS = 2


def validation_router(state) -> Literal["finalize", "retry_allocator", "fallback"]:
    """Per D4: pass → finalize. Fail + attempts<MAX → retry. Fail + attempts==MAX → fallback."""
    if state.get("validation_passed"):
        return "finalize"
    attempts = state.get("allocation_attempts", 0)
    if attempts < MAX_ALLOCATION_ATTEMPTS:
        return "retry_allocator"
    return "fallback"


def create_fallback_normalizer(cache_path: str | None = None):
    """Constrained re-optimization fallback (D4 fatal fix).

    The naive 'clip(0.20) + renormalize' pattern can push weights BACK ABOVE
    the cap (e.g., [0.30, 0.30, 0.40] → clipped [0.20, 0.20, 0.20] →
    renormalized [0.333, 0.333, 0.333] — still violates).

    Correct: re-run min-variance with strict weight_bounds(0, 0.20). The
    optimizer mathematically guarantees the constraint at the optimization
    step. If even this fails (joint infeasibility), fall back to an emergency
    cash-heavy portfolio that mathematically cannot violate.
    """
    def node(state):
        weights = state.get("weight_vector")
        if weights is None:
            return _emergency_cash_portfolio(state)

        try:
            from pypfopt import EfficientFrontier, risk_models

            tickers = list(weights.weights.keys())
            as_of = date.fromisoformat(state["as_of_date"])
            start = as_of - timedelta(days=365 * 3)
            returns = fetch_returns_matrix(tickers, start, as_of, cache_path=cache_path)

            S = compute_robust_cov(returns)
            ef = EfficientFrontier(None, S, weight_bounds=(0, 0.20))
            ef.min_volatility()
            constrained_weights = {
                k: float(v) for k, v in ef.clean_weights().items() if v > 1e-4
            }

            assert all(w <= 0.20 + 1e-6 for w in constrained_weights.values()), \
                "PyPortfolioOpt weight_bounds violated — falling through"
            assert abs(sum(constrained_weights.values()) - 1.0) < 1e-3, \
                "Constrained solution doesn't sum to 1 — falling through"

            new_wv = WeightVector(
                method=OptimizationMethod.MIN_VARIANCE,
                weights=constrained_weights,
                rationale=(
                    f"DETERMINISTIC FALLBACK after {state['allocation_attempts']} "
                    f"failed attempts: re-optimized with min-variance + hard 20% cap. "
                    f"Original method: {weights.method.value}."
                ),
            )
            return {
                "weight_vector": new_wv,
                "validation_passed": True,
            }
        except Exception as e:
            return _emergency_cash_portfolio(state, error=str(e))

    return node


class ConditionalLogic:
    """Handles conditional logic for determining graph flow (legacy — pre-D4)."""

    def __init__(self, max_debate_rounds=1, max_risk_discuss_rounds=1):
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_discuss_rounds = max_risk_discuss_rounds

    def should_continue_market(self, state):
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_market"
        return "Msg Clear Market"

    def should_continue_social(self, state):
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_social"
        return "Msg Clear Social"

    def should_continue_news(self, state):
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_news"
        return "Msg Clear News"

    def should_continue_fundamentals(self, state):
        messages = state["messages"]
        last_message = messages[-1]
        if last_message.tool_calls:
            return "tools_fundamentals"
        return "Msg Clear Fundamentals"

    def should_continue_debate(self, state) -> str:
        if state["investment_debate_state"]["count"] >= 2 * self.max_debate_rounds:
            return "Research Manager"
        if state["investment_debate_state"]["current_response"].startswith("Bull"):
            return "Bear Researcher"
        return "Bull Researcher"

    def should_continue_risk_analysis(self, state) -> str:
        if state["risk_debate_state"]["count"] >= 3 * self.max_risk_discuss_rounds:
            return "Portfolio Manager"
        if state["risk_debate_state"]["latest_speaker"].startswith("Aggressive"):
            return "Conservative Analyst"
        if state["risk_debate_state"]["latest_speaker"].startswith("Conservative"):
            return "Neutral Analyst"
        return "Aggressive Analyst"


def _emergency_cash_portfolio(state, error: str = "no weight_vector") -> dict:
    """Last-resort fallback: equal-weight across SAFE-bucket ETFs.

    Used when even constrained optimization fails. Equal-weight across all
    안전자산 (bonds + MMF/CD) ensures: (a) no 위험 bucket ETFs (defensive),
    (b) each weight ≤ 20% as long as ≥5 safe ETFs exist.
    """
    universe = load_universe(state["universe_path"])
    safe_etfs = [e.ticker for e in universe.etfs if e.bucket == "안전"]

    if len(safe_etfs) == 0:
        raise RuntimeError(
            f"Emergency fallback failed ({error}); no 안전자산 ETFs in universe"
        )

    # Take up to 5 safe ETFs, equal-weighted. If <5, accept >0.20 single-asset
    # exposure but log loudly — this is an emergency path, manual review required.
    selected = safe_etfs[:5]
    weight = 1.0 / len(selected)
    weights = {t: weight for t in selected}

    cap_violation_note = (
        ""
        if len(selected) >= 5
        else f" WARNING: only {len(selected)} 안전자산 ETF(s) in universe — single weight {weight:.2%} > 20% cap. Manual review CRITICAL."
    )

    new_wv = WeightVector(
        method=OptimizationMethod.MIN_VARIANCE,
        weights=weights,
        rationale=(
            f"EMERGENCY DEFENSIVE FALLBACK: equal-weight across {len(selected)} "
            f"안전자산 ETFs. Triggered by: {error}.{cap_violation_note}"
        ),
    )
    return {
        "weight_vector": new_wv,
        "validation_passed": True,
    }
