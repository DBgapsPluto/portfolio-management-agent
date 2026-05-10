"""gaps preset — list / run preset YAMLs."""
from datetime import date as _date
from pathlib import Path

import click


@click.group()
def group():
    """Preset YAML management."""


@group.command("list")
@click.option("--preset-dir", default="presets")
def list_cmd(preset_dir):
    """List available presets."""
    for f in sorted(Path(preset_dir).glob("*.yaml")):
        click.echo(f.stem)


@group.command("run")
@click.argument("name")
@click.option("--date", "as_of", default=None)
def run_cmd(name, as_of):
    """Run a preset directly (equivalent to `gaps plan --preset NAME`)."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    graph = TradingAgentsGraph(preset_name=name)
    final = graph.run(as_of_date=as_of or _date.today().isoformat())
    click.echo(f"✓ Preset '{name}' complete: {final['final_portfolio_path']}")
