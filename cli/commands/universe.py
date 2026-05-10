"""gaps universe — manage 188-ETF universe (sync/list/info)."""
from pathlib import Path

import click

from tradingagents.dataflows.universe import sync_from_xlsx, load_universe


@click.group()
def group():
    """Manage the GAPS ETF universe."""


@group.command("sync")
@click.option("--xlsx", default="docs/제12회 GAPS ETF 리스트 (2026-5-9 게시).xlsx",
              help="Source xlsx file")
@click.option("--out", default="data/universe.json", help="Output JSON path")
def sync(xlsx, out):
    """Parse the GAPS xlsx → universe.json (188 ETFs)."""
    universe = sync_from_xlsx(Path(xlsx), Path(out))
    click.echo(f"✓ Synced {len(universe.etfs)} ETFs to {out}")


@group.command("list")
@click.option("--bucket", type=click.Choice(["위험", "안전"]), default=None)
@click.option("--category", default=None)
@click.option("--top", type=int, default=20, help="Top N by AUM")
@click.option("--universe-path", default="data/universe.json")
def list_cmd(bucket, category, top, universe_path):
    """List ETFs filtered by bucket/category, sorted by AUM."""
    u = load_universe(Path(universe_path))
    etfs = u.etfs
    if bucket:
        etfs = [e for e in etfs if e.bucket == bucket]
    if category:
        etfs = [e for e in etfs if e.category == category]
    etfs.sort(key=lambda e: -e.aum_krw)
    for e in etfs[:top]:
        click.echo(
            f"{e.ticker} {e.name[:40]:40s}  AUM={e.aum_krw / 1e8:>10.0f}억  [{e.category}]"
        )


@group.command("info")
@click.argument("ticker")
@click.option("--universe-path", default="data/universe.json")
def info(ticker, universe_path):
    """Show details for a single ETF."""
    u = load_universe(Path(universe_path))
    match = next((e for e in u.etfs if e.ticker == ticker), None)
    if not match:
        click.secho(f"✗ {ticker} not in universe", fg="red")
        raise click.Abort()
    click.echo(f"Ticker:        {match.ticker}")
    click.echo(f"Name:          {match.name}")
    click.echo(f"AUM (KRW):     {match.aum_krw:,.0f}")
    click.echo(f"Underlying:    {match.underlying_index}")
    click.echo(f"Bucket:        {match.bucket}")
    click.echo(f"Category:      {match.category}")
