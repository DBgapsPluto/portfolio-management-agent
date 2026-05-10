"""gaps monitor — turnover, exposure, drift, cost."""
import json
from datetime import date
from pathlib import Path

import click

from tradingagents.dataflows.universe import load_universe
from tradingagents.monitor.cost import compute_cost
from tradingagents.monitor.drift import compute_drift
from tradingagents.monitor.exposure import compute_exposure
from tradingagents.monitor.turnover import compute_turnover


@click.group()
def group():
    """Operations monitoring."""


@group.command("turnover")
@click.option("--transactions", required=True, type=click.Path(exists=True))
@click.option("--capital", type=int, default=1_000_000_000)
@click.option("--as-of", default=None)
def turnover_cmd(transactions, capital, as_of):
    """Track turnover floor (initial 80%, monthly 10%) — CUTOFF risk."""
    target = date.fromisoformat(as_of) if as_of else date.today()
    status = compute_turnover(Path(transactions), capital, target)
    click.echo(f"Initial (6/1-6/8): {status.initial_pct:.2%} (floor 80%)")
    for m, pct in status.monthly_pcts.items():
        click.echo(f"Month {m}:           {pct:.2%} (floor 10%)")
    for w in status.warnings:
        click.secho(w, fg="red")


@group.command("exposure")
@click.option("--portfolio", required=True, type=click.Path(exists=True))
@click.option("--universe-path", default="data/universe.json")
def exposure_cmd(portfolio, universe_path):
    """Asset-class exposure + risk/safe split."""
    raw = json.loads(Path(portfolio).read_text(encoding="utf-8"))
    universe = load_universe(Path(universe_path))
    lookup = {
        e.ticker: {"category": e.category, "bucket": e.bucket}
        for e in universe.etfs
    }
    breakdown = compute_exposure(raw["weights"], lookup)
    click.echo("By category:")
    for cat, w in sorted(breakdown.by_category.items(), key=lambda x: -x[1]):
        click.echo(f"  {cat}: {w:.2%}")
    click.echo(f"Risk asset: {breakdown.risk_asset_pct:.2%} (cap 70%)")
    click.echo(f"Safe asset: {breakdown.safe_asset_pct:.2%}")


@group.command("drift")
@click.option("--portfolio", required=True, type=click.Path(exists=True))
@click.option("--prices-csv", required=True, type=click.Path(exists=True),
              help="CSV with columns: ticker, current_price, entry_price")
def drift_cmd(portfolio, prices_csv):
    """Drift vs target weights based on price moves."""
    import pandas as pd

    raw = json.loads(Path(portfolio).read_text(encoding="utf-8"))
    df = pd.read_csv(prices_csv)
    current = dict(zip(df["ticker"], df["current_price"].astype(float)))
    entry = dict(zip(df["ticker"], df["entry_price"].astype(float)))
    rep = compute_drift(raw["weights"], current, entry)
    click.echo(f"Max drift: {rep.max_drift:.2%} on {rep.max_drift_ticker}")
    for t, d in sorted(rep.drift_pct.items(), key=lambda x: -x[1])[:10]:
        click.echo(f"  {t}: {d:.2%}")


@group.command("cost")
@click.option("--transactions", required=True, type=click.Path(exists=True))
@click.option("--capital", type=int, default=1_000_000_000)
def cost_cmd(transactions, capital):
    """Total commission + slippage."""
    s = compute_cost(Path(transactions), capital)
    click.echo(f"Commission: {s.total_commission:,.0f} KRW")
    click.echo(f"Slippage:   {s.total_slippage:,.0f} KRW")
    click.echo(f"Cost (bps): {s.cost_bps_of_capital:.1f}")
