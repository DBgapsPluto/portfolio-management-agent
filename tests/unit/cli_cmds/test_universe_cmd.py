from pathlib import Path

from click.testing import CliRunner

from cli.commands.universe import group


def test_sync_uses_fixture(tmp_path):
    runner = CliRunner()
    out = tmp_path / "u.json"
    result = runner.invoke(group, [
        "sync",
        "--xlsx", "tests/fixtures/universe_test.xlsx",
        "--out", str(out),
    ])
    assert result.exit_code == 0
    assert out.exists()


def test_list_filters_by_bucket(tmp_path):
    runner = CliRunner()
    out = tmp_path / "u.json"
    runner.invoke(group, ["sync",
                          "--xlsx", "tests/fixtures/universe_test.xlsx",
                          "--out", str(out)])
    result = runner.invoke(group, ["list",
                                   "--bucket", "안전",
                                   "--universe-path", str(out)])
    assert result.exit_code == 0
    assert "KODEX 국고채3년" in result.output
