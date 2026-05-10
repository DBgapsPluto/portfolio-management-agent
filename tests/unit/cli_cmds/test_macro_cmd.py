"""Smoke tests for `gaps macro` subcommands.

These are minimal smoke tests — they verify --help works without instantiating
LLMs (which would require API keys). Full functional tests are in P4-T15
(5/28 E2E gold standard).
"""
from click.testing import CliRunner

from cli.commands.macro import group


def test_macro_help():
    runner = CliRunner()
    result = runner.invoke(group, ["--help"])
    assert result.exit_code == 0
    assert "regime" in result.output
    assert "risk" in result.output
    assert "news" in result.output
    assert "technical" in result.output


def test_macro_regime_help():
    runner = CliRunner()
    result = runner.invoke(group, ["regime", "--help"])
    assert result.exit_code == 0
    assert "as_of" in result.output.lower() or "--date" in result.output


def test_macro_risk_help():
    runner = CliRunner()
    result = runner.invoke(group, ["risk", "--help"])
    assert result.exit_code == 0


def test_macro_news_help():
    runner = CliRunner()
    result = runner.invoke(group, ["news", "--help"])
    assert result.exit_code == 0
