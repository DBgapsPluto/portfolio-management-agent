import numpy as np
import pandas as pd
from pypfopt import HRPOpt, EfficientFrontier, BlackLittermanModel, risk_models, expected_returns

from tradingagents.schemas.portfolio import OptimizationMethod, WeightVector
from tradingagents.skills.registry import register_skill


def _ef_metrics(weights: dict, mu, S) -> tuple[float | None, float | None]:
    """Compute (vol, sharpe) for an Efficient Frontier solution."""
    try:
        w = np.array([weights.get(t, 0.0) for t in mu.index])
        ret = float(w @ mu.values)
        vol = float((w.T @ S.values @ w) ** 0.5)
        sharpe = ret / vol if vol > 0 else 0.0
        return vol, sharpe
    except Exception:
        return None, None


@register_skill(name="optimize_hrp", category="portfolio")
def optimize_hrp(returns: pd.DataFrame) -> WeightVector:
    """Hierarchical Risk Parity optimization."""
    hrp = HRPOpt(returns)
    weights = hrp.optimize()
    weights = {k: float(v) for k, v in weights.items() if v > 1e-4}
    total = sum(weights.values())
    weights = {k: v / total for k, v in weights.items()}
    return WeightVector(
        method=OptimizationMethod.HRP,
        weights=weights,
        rationale=f"HRP on {returns.shape[1]} assets, {len(returns)} obs",
    )


@register_skill(name="optimize_risk_parity", category="portfolio")
def optimize_risk_parity(returns: pd.DataFrame) -> WeightVector:
    """Risk Parity optimization (min volatility approximation with 20% cap)."""
    S = risk_models.sample_cov(returns)
    ef = EfficientFrontier(None, S, weight_bounds=(0, 0.20))
    ef.min_volatility()
    weights = {k: float(v) for k, v in ef.clean_weights().items() if v > 1e-4}
    total = sum(weights.values())
    weights = {k: v / total for k, v in weights.items()}
    return WeightVector(
        method=OptimizationMethod.RISK_PARITY,
        weights=weights,
        rationale="Risk parity (min vol approximation)",
    )


@register_skill(name="optimize_min_variance", category="portfolio")
def optimize_min_variance(returns: pd.DataFrame) -> WeightVector:
    """Minimum Variance optimization with single-asset cap 20%."""
    mu = expected_returns.mean_historical_return(returns, returns_data=True)
    S = risk_models.sample_cov(returns)
    ef = EfficientFrontier(mu, S, weight_bounds=(0, 0.20))
    ef.min_volatility()
    weights = {k: float(v) for k, v in ef.clean_weights().items() if v > 1e-4}
    total = sum(weights.values())
    weights = {k: v / total for k, v in weights.items()}
    vol, sharpe = _ef_metrics(weights, mu, S)
    return WeightVector(
        method=OptimizationMethod.MIN_VARIANCE,
        weights=weights,
        rationale="Min variance, single-asset cap 20%",
        expected_volatility=vol,
        expected_sharpe=sharpe,
    )


@register_skill(name="optimize_black_litterman", category="portfolio")
def optimize_black_litterman(
    returns: pd.DataFrame,
    views: dict[str, float],
    view_confidences: list[float],
) -> WeightVector:
    """Black-Litterman optimization with analyst views and confidence levels.

    Args:
        returns: Historical returns DataFrame (assets as columns).
        views: Dict mapping ticker to expected return (e.g., {"A000001": 0.02}).
        view_confidences: List of confidence levels (0, 1) for each view.

    Returns:
        WeightVector with optimized weights respecting 20% single-asset cap.
    """
    S = risk_models.sample_cov(returns)
    bl = BlackLittermanModel(
        S, absolute_views=views, omega="idzorek", view_confidences=view_confidences
    )
    bl_returns = bl.bl_returns()
    ef = EfficientFrontier(bl_returns, S, weight_bounds=(0, 0.20))
    try:
        ef.max_sharpe()
    except Exception:
        # Fall back to min_volatility if max_sharpe fails
        # Create new instance since the optimizer rejects changes after a failed solve
        ef = EfficientFrontier(bl_returns, S, weight_bounds=(0, 0.20))
        ef.min_volatility()
    weights = {k: float(v) for k, v in ef.clean_weights().items() if v > 1e-4}
    total = sum(weights.values())
    weights = {k: v / total for k, v in weights.items()}
    return WeightVector(
        method=OptimizationMethod.BLACK_LITTERMAN,
        weights=weights,
        rationale=f"Black-Litterman with {len(views)} views",
    )
