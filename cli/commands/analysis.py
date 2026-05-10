import click


@click.command()
def correlate():
    """Correlation matrix + clusters."""


@click.command()
def validate():
    """Run all 4 mandate checks."""


@click.command()
def simulate():
    """Lightweight historical backtest."""
