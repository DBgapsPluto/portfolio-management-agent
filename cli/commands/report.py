"""gaps report — generate philosophy / monthly / trade-plan."""
import datetime as _dt
import json
from datetime import date
from pathlib import Path

import click
import pandas as pd

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.dataflows.pykrx_data import (
    ParquetCache,
    fetch_etf_snapshot_by_date,
)
from tradingagents.dataflows.universe import load_universe
from tradingagents.llm_clients import create_llm_client
from tradingagents.reports.monthly import write_monthly
from tradingagents.reports.philosophy import write_philosophy
from tradingagents.reports.trade_plan import write_trade_plan


@click.group()
def group():
    """Generate reports (philosophy, monthly, trade-plan)."""


@group.command("philosophy")
@click.option("--portfolio", required=True, type=click.Path(exists=True))
@click.option("--out", default=None)
def philosophy_cmd(portfolio, out):
    """투자철학 문서 생성 (>=4 페이지)."""
    deep = create_llm_client(
        provider=DEFAULT_CONFIG["llm_provider"],
        model=DEFAULT_CONFIG["deep_think_llm"],
    ).get_llm()
    state = json.loads(Path(portfolio).read_text(encoding="utf-8"))
    out_path = Path(out or "artifacts/philosophy.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_philosophy(state, deep, out_path)
    click.echo(f"✓ Wrote {out_path}")


@group.command("monthly")
@click.option("--month", type=int, required=True)
@click.option("--actual", required=True, type=click.Path(exists=True),
              help="P&L CSV from MTS")
@click.option("--state-json", default=None)
@click.option("--out", default=None)
def monthly_cmd(month, actual, state_json, out):
    """월간 운용보고서 (3섹션)."""
    deep = create_llm_client(
        provider=DEFAULT_CONFIG["llm_provider"],
        model=DEFAULT_CONFIG["deep_think_llm"],
    ).get_llm()
    state = (
        json.loads(Path(state_json).read_text(encoding="utf-8"))
        if state_json else {}
    )
    out_path = Path(out or f"artifacts/monthly_report_{month}.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_monthly(state, Path(actual), month, deep, out_path)
    click.echo(f"✓ Wrote {out_path}")


@group.command("trade-plan")
@click.option("--portfolio", required=True, type=click.Path(exists=True))
@click.option("--universe-path", default="data/universe.json")
@click.option("--out", default="artifacts/trade_plan.csv")
def trade_plan_cmd(portfolio, universe_path, out):
    """MTS 입력용 매매명세서 CSV."""
    raw = json.loads(Path(portfolio).read_text(encoding="utf-8"))
    universe = load_universe(Path(universe_path))
    lookup = {
        e.ticker: {"name": e.name, "category": e.category}
        for e in universe.etfs
    }

    cache = ParquetCache(DEFAULT_CONFIG["etf_price_cache_path"])
    today = date.today()
    snapshot = pd.DataFrame()
    for d_off in range(7):
        try:
            snapshot = fetch_etf_snapshot_by_date(
                today - _dt.timedelta(days=d_off), cache=cache
            )
            if not snapshot.empty:
                break
        except Exception:
            continue

    latest_prices = {
        row["ticker"]: float(row["close"])
        for _, row in snapshot.iterrows()
        if row["ticker"] in raw["weights"]
    }

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_trade_plan(
        raw["weights"],
        raw["capital_krw"],
        lookup,
        latest_prices,
        out_path,
    )
    click.echo(f"✓ Wrote {out_path}")
