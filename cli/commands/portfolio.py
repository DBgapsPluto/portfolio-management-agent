import click


@click.command()
def plan():
    """Run the full pipeline."""


@click.command()
def rebalance():
    """3-tier rebalancing (daily/weekly/monthly)."""


@click.command()
def optimize():
    """Single optimizer debug."""
