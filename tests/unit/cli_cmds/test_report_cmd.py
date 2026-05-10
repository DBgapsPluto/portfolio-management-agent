"""Smoke tests for `gaps report` group."""
from click.testing import CliRunner

from cli.commands.report import group


def test_report_help():
    runner = CliRunner()
    result = runner.invoke(group, ["--help"])
    assert result.exit_code == 0
    assert "philosophy" in result.output
    assert "monthly" in result.output
    assert "trade-plan" in result.output


def test_report_philosophy_help():
    runner = CliRunner()
    result = runner.invoke(group, ["philosophy", "--help"])
    assert result.exit_code == 0
    assert "--portfolio" in result.output


def test_report_monthly_help():
    runner = CliRunner()
    result = runner.invoke(group, ["monthly", "--help"])
    assert result.exit_code == 0
    assert "--month" in result.output
    assert "--actual" in result.output


def test_report_trade_plan_help():
    runner = CliRunner()
    result = runner.invoke(group, ["trade-plan", "--help"])
    assert result.exit_code == 0
    assert "--portfolio" in result.output
    assert "--universe-path" in result.output
