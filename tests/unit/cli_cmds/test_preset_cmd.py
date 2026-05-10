"""Smoke tests for `gaps preset list/run`."""
from pathlib import Path

from click.testing import CliRunner

from cli.commands.preset import group


def test_preset_help():
    r = CliRunner().invoke(group, ["--help"])
    assert r.exit_code == 0
    assert "list" in r.output
    assert "run" in r.output


def test_preset_list(tmp_path: Path):
    """Lists *.yaml file stems in --preset-dir."""
    (tmp_path / "alpha.yaml").write_text("dummy: 1")
    (tmp_path / "beta.yaml").write_text("dummy: 2")
    (tmp_path / "ignore.txt").write_text("nope")
    r = CliRunner().invoke(group, ["list", "--preset-dir", str(tmp_path)])
    assert r.exit_code == 0
    assert "alpha" in r.output
    assert "beta" in r.output
    assert "ignore" not in r.output


def test_preset_run_help():
    r = CliRunner().invoke(group, ["run", "--help"])
    assert r.exit_code == 0
    assert "NAME" in r.output or "name" in r.output
