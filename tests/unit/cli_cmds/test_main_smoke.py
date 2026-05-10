from click.testing import CliRunner

from cli.main import cli


def test_help_prints():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "universe" in result.output
    assert "plan" in result.output


def test_subcommand_routing():
    runner = CliRunner()
    result = runner.invoke(cli, ["universe", "--help"])
    assert result.exit_code == 0
