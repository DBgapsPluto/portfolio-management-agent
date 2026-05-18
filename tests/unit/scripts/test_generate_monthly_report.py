"""scripts/generate_monthly_report.py — CLI 검증."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# scripts/는 sys.path에 없으므로 import 시 직접 추가
SCRIPTS_DIR = Path(__file__).parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import generate_monthly_report as gen_module  # noqa: E402


def test_restore_state_from_archive_with_files(tmp_path):
    run_dir = tmp_path / "2026-06-30"
    run_dir.mkdir()
    (run_dir / "macro_summary.json").write_text(
        json.dumps("## Macro\nregime: recession"), encoding="utf-8",
    )
    (run_dir / "risk_summary.json").write_text(
        json.dumps("## Risk\nVIX 32"), encoding="utf-8",
    )

    state = gen_module._restore_state_from_archive("2026-06-30", run_dir)
    assert "regime: recession" in state["macro_summary"]
    assert "VIX 32" in state["risk_summary"]
    assert state["as_of_date"] == "2026-06-30"


def test_restore_state_handles_missing_files(tmp_path):
    run_dir = tmp_path / "empty"
    run_dir.mkdir()
    state = gen_module._restore_state_from_archive("2026-06-30", run_dir)
    assert state["macro_summary"] == ""
    assert state["risk_summary"] == ""


def test_main_validates_date_format(tmp_path):
    pnl = tmp_path / "pnl.csv"
    pnl.write_text("equity\n100\n", encoding="utf-8")
    with patch.object(sys, "argv", [
        "generate_monthly_report.py",
        "--month", "6",
        "--pnl-csv", str(pnl),
        "--as-of-date", "invalid-date",
    ]):
        rc = gen_module.main()
    assert rc == 1


def test_main_validates_pnl_csv_exists(tmp_path):
    with patch.object(sys, "argv", [
        "generate_monthly_report.py",
        "--month", "6",
        "--pnl-csv", str(tmp_path / "nonexistent.csv"),
        "--as-of-date", "2026-06-30",
    ]):
        rc = gen_module.main()
    assert rc == 1


def test_main_success_writes_monthly_md(tmp_path, monkeypatch):
    # pnl CSV
    pnl = tmp_path / "pnl.csv"
    pd.DataFrame({"equity": [1_000_000_000, 1_005_000_000, 1_010_000_000]}).to_csv(
        pnl, index=False,
    )

    # archive 디렉토리
    base = tmp_path / "archive_base"
    run_dir = base / "2026-06-30"
    run_dir.mkdir(parents=True)
    (run_dir / "macro_summary.json").write_text(json.dumps("macro test"))

    monkeypatch.setattr(
        gen_module, "resolve_run_dir",
        lambda d: run_dir,
    )

    # LLM mock
    fake_llm_client = MagicMock()
    fake_llm = MagicMock()
    fake_llm.invoke.return_value.content = "월간 리포트 본문 " * 200
    fake_llm_client.get_llm.return_value = fake_llm
    monkeypatch.setattr(
        gen_module, "create_llm_client",
        lambda provider, model, **kw: fake_llm_client,
    )

    out_path = tmp_path / "monthly.md"
    with patch.object(sys, "argv", [
        "generate_monthly_report.py",
        "--month", "6",
        "--pnl-csv", str(pnl),
        "--as-of-date", "2026-06-30",
        "--out", str(out_path),
        "--provider", "openai", "--model", "gpt-4o-mini",
    ]):
        rc = gen_module.main()

    assert rc == 0
    assert out_path.exists()
    assert "월간 리포트 본문" in out_path.read_text(encoding="utf-8")
