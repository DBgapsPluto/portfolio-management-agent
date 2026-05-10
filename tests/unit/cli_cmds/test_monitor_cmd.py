from click.testing import CliRunner

from cli.commands.monitor import group


def test_monitor_help():
    r = CliRunner().invoke(group, ["--help"])
    assert r.exit_code == 0
    assert "turnover" in r.output
    assert "exposure" in r.output
    assert "drift" in r.output
    assert "cost" in r.output
