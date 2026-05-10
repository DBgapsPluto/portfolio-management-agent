"""gaps correlate / validate / simulate CLI commands."""
import json
from datetime import date, timedelta
from pathlib import Path

import click
import pandas as pd

from tradingagents.dataflows.universe import load_universe
from tradingagents.schemas.portfolio import OptimizationMethod, WeightVector


def _load_portfolio(path: Path) -> WeightVector:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return WeightVector(
        method=OptimizationMethod(raw["method"]),
        weights=raw["weights"],
        rationale=raw["rationale"],
        expected_volatility=raw.get("expected_volatility"),
        expected_sharpe=raw.get("expected_sharpe"),
    )


@click.command("correlate")
@click.option("--portfolio", required=True, type=click.Path(exists=True))
@click.option("--cluster", is_flag=True, help="Run hierarchical clustering")
def correlate(portfolio, cluster):
    """Compute correlation matrix and (optionally) clusters for a portfolio."""
    from tradingagents.skills.portfolio.returns_matrix import fetch_returns_matrix
    from tradingagents.skills.technical.correlation_cluster import (
        find_correlation_clusters,
    )

    wv = _load_portfolio(Path(portfolio))
    end = date.today()
    start = end - timedelta(days=365 * 3)
    returns = fetch_returns_matrix(list(wv.weights.keys()), start, end)

    corr = returns.corr()
    click.echo("Correlation matrix:")
    click.echo(corr.round(2).to_string())

    if cluster:
        clusters = find_correlation_clusters(returns, threshold=0.7)
        click.echo(f"\nClusters: {len(clusters)}")
        for c in clusters:
            click.echo(f"  [{c.cluster_id}] {c.category_label}")
            click.echo(f"    members: {', '.join(c.members)}")
            click.echo(f"    avg correlation: {c.avg_internal_correlation:.3f}")


@click.command("validate")
@click.option("--portfolio", required=True, type=click.Path(exists=True))
@click.option("--universe-path", default="data/universe.json")
@click.option("--capital", type=int, default=1_000_000_000)
@click.option("--floor", type=float, default=0.80,
              help="Turnover floor (0.80 initial, 0.10 monthly)")
def validate(portfolio, universe_path, capital, floor):
    """Run all 4 mandate checks against a portfolio."""
    from tradingagents.skills.mandate.concentration_check import (
        validate_concentration,
    )
    from tradingagents.skills.mandate.correlation_check import (
        validate_correlation_concentration,
    )
    from tradingagents.skills.mandate.turnover_check import (
        validate_turnover_feasibility,
    )
    from tradingagents.skills.mandate.universe_check import validate_universe

    wv = _load_portfolio(Path(portfolio))
    universe = load_universe(Path(universe_path))

    checks = {
        "Universe": validate_universe(wv, universe),
        "Concentration": validate_concentration(wv, universe),
        "Turnover": validate_turnover_feasibility(
            wv, None, capital, floor, days_remaining=5
        ),
        "Correlation": validate_correlation_concentration(wv, []),
    }

    for name, report in checks.items():
        if report.passed:
            click.secho(f"  ✓ {name}: PASS", fg="green")
        else:
            click.secho(
                f"  ✗ {name}: {len(report.violations)} violations", fg="red"
            )
            for v in report.violations:
                click.echo(f"    - [{v.severity}] {v.description}")


@click.command("simulate")
@click.option("--portfolio", required=True, type=click.Path(exists=True))
@click.option("--window", default="3y", help="Backtest window: 1y/3y/5y")
def simulate(portfolio, window):
    """Lightweight historical simulation (returns, vol, MDD, Sharpe)."""
    from tradingagents.skills.portfolio.returns_matrix import fetch_returns_matrix

    wv = _load_portfolio(Path(portfolio))
    days_map = {"1y": 365, "3y": 365 * 3, "5y": 365 * 5}
    days = days_map.get(window, 365 * 3)
    end = date.today()
    start = end - timedelta(days=days)
    returns = fetch_returns_matrix(list(wv.weights.keys()), start, end)

    weights_series = pd.Series(wv.weights)
    common = returns.columns.intersection(weights_series.index)
    weighted = returns[common] * weights_series[common]
    portfolio_returns = weighted.sum(axis=1)

    cum = (1 + portfolio_returns).cumprod()
    total_return = float(cum.iloc[-1] - 1)
    vol_ann = float(portfolio_returns.std() * (252 ** 0.5))
    sharpe = (
        float(portfolio_returns.mean() / portfolio_returns.std() * (252 ** 0.5))
        if portfolio_returns.std() > 0 else 0.0
    )
    rolling_max = cum.cummax()
    mdd = float((cum / rolling_max - 1).min())

    click.echo(f"Window: {window} ({len(portfolio_returns)} days)")
    click.echo(f"Total return:   {total_return:+.2%}")
    click.echo(f"Annualized vol: {vol_ann:.2%}")
    click.echo(f"Sharpe:         {sharpe:.2f}")
    click.echo(f"Max drawdown:   {mdd:.2%}")
