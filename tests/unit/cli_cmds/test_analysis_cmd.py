"""Smoke tests for `gaps correlate/validate/simulate`."""
from click.testing import CliRunner

from cli.commands.analysis import correlate, validate, simulate


def test_correlate_help():
    runner = CliRunner()
    result = runner.invoke(correlate, ["--help"])
    assert result.exit_code == 0
    assert "--portfolio" in result.output
    assert "--cluster" in result.output


def test_validate_help():
    runner = CliRunner()
    result = runner.invoke(validate, ["--help"])
    assert result.exit_code == 0
    assert "--portfolio" in result.output
    assert "--floor" in result.output


def test_simulate_help():
    runner = CliRunner()
    result = runner.invoke(simulate, ["--help"])
    assert result.exit_code == 0
    assert "--window" in result.output
