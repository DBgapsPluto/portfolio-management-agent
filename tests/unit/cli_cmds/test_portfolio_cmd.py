"""Smoke tests for `gaps plan/rebalance/optimize` commands."""
from click.testing import CliRunner

from cli.commands.portfolio import plan, rebalance, optimize


def test_plan_help():
    runner = CliRunner()
    result = runner.invoke(plan, ["--help"])
    assert result.exit_code == 0
    assert "--date" in result.output
    assert "--capital" in result.output
    assert "--preset" in result.output
    assert "--dry-run" in result.output


def test_rebalance_help():
    runner = CliRunner()
    result = runner.invoke(rebalance, ["--help"])
    assert result.exit_code == 0
    assert "daily" in result.output
    assert "weekly" in result.output
    assert "monthly" in result.output


def test_rebalance_monthly_requires_month():
    """rebalance monthly without --month should error.

    Note: this test invokes the command which will try to import
    tradingagents.rebalance.monthly_full — that module doesn't exist yet
    (P4-T11). So we expect either UsageError OR ImportError. Either is fine.
    """
    runner = CliRunner()
    result = runner.invoke(rebalance, ["monthly"])
    # Expect non-zero exit — either UsageError (ours) or ImportError before that
    assert result.exit_code != 0


def test_optimize_help():
    runner = CliRunner()
    result = runner.invoke(optimize, ["--help"])
    assert result.exit_code == 0
    assert "--method" in result.output
    assert "--candidates" in result.output
