"""DB GAPS agent CLI entry point.

Replaces the legacy interactive CLI (TradingAgents v0.2.4) with a Click-based
dispatcher. Subcommand groups are imported lazily so `gaps --help` is fast
even before all skill modules are registered.

Tracing: set LANGSMITH_TRACING=true and LANGSMITH_API_KEY to enable
multi-agent run-tree visualization at https://smith.langchain.com/.
"""
import click

from tradingagents.observability.tracing import setup_tracing


@click.group()
@click.version_option(version="0.3.0")
def cli():
    """gaps — DB GAPS asset-allocation agent CLI.

    Run `gaps <subcommand> --help` for details.
    """
    setup_tracing()


# Subcommand registrations (imported lazily inside the function to keep
# `gaps --help` startup fast). Each command module exposes a `register(cli)`
# function or a `group`/command object we attach.
def _register_commands():
    from cli.commands import (
        universe, macro, portfolio, analysis, report, monitor, preset,
    )
    cli.add_command(universe.group, name="universe")
    cli.add_command(macro.group, name="macro")
    cli.add_command(portfolio.plan)
    cli.add_command(portfolio.rebalance)
    cli.add_command(analysis.correlate)
    cli.add_command(analysis.validate)
    cli.add_command(analysis.simulate)
    cli.add_command(report.group, name="report")
    cli.add_command(monitor.group, name="monitor")
    cli.add_command(preset.group, name="preset")


_register_commands()


if __name__ == "__main__":
    cli()
