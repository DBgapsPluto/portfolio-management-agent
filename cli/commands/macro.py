"""gaps macro — single-analyst quick lookups (debug/inspection commands)."""
from datetime import date

import click

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client


def _make_llms():
    """Build (quick, deep) LLM clients from DEFAULT_CONFIG."""
    deep = create_llm_client(
        provider=DEFAULT_CONFIG["llm_provider"],
        model=DEFAULT_CONFIG["deep_think_llm"],
    ).get_llm()
    quick = create_llm_client(
        provider=DEFAULT_CONFIG["llm_provider"],
        model=DEFAULT_CONFIG["quick_think_llm"],
    ).get_llm()
    return quick, deep


@click.group()
def group():
    """Quick single-analyst commands for debugging or report citation."""


@group.command("regime")
@click.option("--date", "as_of", default=None, help="ISO date, default today")
def regime(as_of):
    """Macro/Quant Analyst — regime quadrant 판단."""
    from tradingagents.agents.analysts.macro_quant_analyst import (
        create_macro_quant_analyst,
    )
    quick, deep = _make_llms()
    node = create_macro_quant_analyst(quick, deep)
    state = {"as_of_date": as_of or date.today().isoformat()}
    result = node(state)
    rep = result["macro_report"]
    click.echo(f"Regime: {rep.regime.quadrant} (confidence {rep.regime.confidence:.2f})")
    click.echo(f"Drivers: {', '.join(rep.regime.drivers)}")
    click.echo(
        f"\nYield curve: 10y-2y={rep.yield_curve.spread_10y_2y_bps:.0f}bps, "
        f"inverted {rep.yield_curve.inverted_days_count}d"
    )
    click.echo(f"Inflation: CPI YoY {rep.inflation.cpi_yoy:.2f}%, "
               f"accelerating={rep.inflation.accelerating}")
    click.echo(f"Employment: UR {rep.employment.unemployment_rate:.1f}%, "
               f"Sahm={rep.employment.sahm_rule_triggered}")
    click.echo(f"\n{rep.narrative}")


@group.command("risk")
@click.option("--date", "as_of", default=None)
def risk(as_of):
    """Market Risk Analyst — VIX·credit spread·systemic score."""
    from tradingagents.agents.analysts.market_risk_analyst import (
        create_market_risk_analyst,
    )
    quick, deep = _make_llms()
    node = create_market_risk_analyst(quick, deep)
    state = {"as_of_date": as_of or date.today().isoformat()}
    result = node(state)
    rep = result["risk_report"]
    click.echo(f"Systemic risk: {rep.systemic_score.score:.1f}/10 "
               f"({rep.systemic_score.regime})")
    click.echo(f"VIX: {rep.vix.current_value:.1f} (z={rep.vix.zscore_30d:+.2f})")
    click.echo(f"VKOSPI: {rep.vkospi.current_value:.1f}")
    click.echo(f"US HY OAS: {rep.credit_spread_us_hy.current_bps:.0f}bps "
               f"{'(widening)' if rep.credit_spread_us_hy.widening else ''}")
    click.echo(f"PCA 1st share: {rep.correlation_concentration.first_eigenvalue_share:.2f} "
               f"{'(concentrated)' if rep.correlation_concentration.is_concentrated else ''}")
    click.echo(f"\n{rep.narrative}")


@group.command("news")
@click.option("--window", type=int, default=30, help="Calendar window in days")
@click.option("--date", "as_of", default=None)
def news(window, as_of):
    """Macro News Analyst — calendar + ranked headlines."""
    from tradingagents.agents.analysts.macro_news_analyst import (
        create_macro_news_analyst,
    )
    quick, deep = _make_llms()
    node = create_macro_news_analyst(quick, deep)
    state = {"as_of_date": as_of or date.today().isoformat()}
    result = node(state)
    rep = result["news_report"]
    click.echo(f"Upcoming events ({len(rep.upcoming_events)}):")
    for e in rep.upcoming_events[:5]:
        click.echo(f"  {e.event_date} {e.region}: {e.description}")
    click.echo(f"\nTop news ({len(rep.ranked_news)}):")
    for r in rep.ranked_news[:5]:
        click.echo(f"  [sev{r.impact.severity}] {r.item.headline[:80]}")


@group.command("technical")
@click.option("--ticker", default=None, help="Single ticker; else top-momentum scan")
@click.option("--date", "as_of", default=None)
def technical(ticker, as_of):
    """Technical Analyst — momentum + correlation clusters."""
    from tradingagents.agents.analysts.technical_analyst import (
        create_technical_analyst,
    )
    quick, deep = _make_llms()
    node = create_technical_analyst(quick, deep)
    state = {
        "as_of_date": as_of or date.today().isoformat(),
        "universe_path": DEFAULT_CONFIG["universe_path"],
    }
    result = node(state)
    rep = result["technical_report"]
    click.echo(f"Categories: {len(rep.asset_class_momentum)}")
    for cat, rankings in list(rep.asset_class_momentum.items())[:3]:
        click.echo(f"\n[{cat}] top 3:")
        for r in rankings[:3]:
            click.echo(f"  {r.ticker} {r.name[:40]:40s}  6m={r.momentum_6m:+.2%}")
    click.echo(f"\nClusters: {len(rep.correlation_clusters)}")
    for c in rep.correlation_clusters[:3]:
        click.echo(f"  [{c.cluster_id}] {c.category_label} "
                   f"({len(c.members)} ETFs, ρ={c.avg_internal_correlation:.2f})")
