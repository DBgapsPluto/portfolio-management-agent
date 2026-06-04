"""gaps plan / rebalance / optimize CLI commands."""
from datetime import date

import click

from tradingagents.default_config import DEFAULT_CONFIG


@click.command("plan")
@click.option("--date", "as_of", default=None, help="ISO date, default today")
@click.option("--capital", type=int, default=1_000_000_000, help="Capital in KRW")
@click.option("--preset", default="db_gaps")
@click.option("--dry-run", is_flag=True, help="Run with mock data (no live API/LLM)")
def plan(as_of, capital, preset, dry_run):
    """Run the full pipeline and produce 5/28 submission package."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    if dry_run:
        click.secho("Dry-run mode: relies on mock fixtures (see P4-T15)", fg="yellow")

    graph = TradingAgentsGraph(preset_name=preset)
    final = graph.run(
        as_of_date=as_of or date.today().isoformat(),
        capital_krw=capital,
    )
    click.echo("✓ Plan complete:")
    click.echo(f"  portfolio.json    : {final['final_portfolio_path']}")
    click.echo(f"  philosophy.md     : {final['philosophy_doc_path']}")
    click.echo(f"  trade_plan.csv    : {final['trade_plan_csv_path']}")
    click.echo(f"  validation_passed : {final['validation_passed']}")
    if final.get("validation_report") and not final["validation_passed"]:
        click.secho("  Hard violations:", fg="red")
        for v in final["validation_report"].hard_violations:
            click.echo(f"    - {v.description}")


@click.command("rebalance")
@click.argument("tier", type=click.Choice(["daily", "weekly", "monthly"]))
@click.option("--date", "as_of", default=None)
@click.option("--week", type=int, default=None, help="Week number (for weekly)")
@click.option("--month", type=int, default=None, help="Month number (for monthly)")
@click.option("--from", "previous_path", default=None,
              help="Path to previous portfolio.json")
def rebalance(tier, as_of, week, month, previous_path):
    """Run a 3-tier rebalancing pipeline (Plan 4 Task 9-11)."""
    target = as_of or date.today().isoformat()
    if tier == "daily":
        from tradingagents.rebalance import daily_triggers
        # D15: pass current portfolio path if available so drift trigger fires
        result = daily_triggers.run(as_of=target, portfolio_path=previous_path)
        click.echo(result.summary)
    elif tier == "weekly":
        from tradingagents.rebalance import weekly_tilt
        result = weekly_tilt.run(as_of=target, previous_path=previous_path)
        click.echo(result.summary)
    elif tier == "monthly":
        from tradingagents.rebalance import monthly_full
        if month is None:
            raise click.UsageError("--month required for monthly")
        result = monthly_full.run(month=month, as_of=target,
                                  previous_path=previous_path)
        click.echo(result.summary)
