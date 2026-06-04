"""Philo fail: deterministic philosophy on contract abort."""
from __future__ import annotations

from pathlib import Path

from tradingagents.reports.philosophy import write_failure_philosophy


def test_write_failure_philosophy_includes_trace(tmp_path):
    state = {
        "as_of_date": "2026-06-01",
        "validation_passed": None,
        "pipeline_failure": {"error_type": "ContractInfeasibleError"},
    }
    out = tmp_path / "philosophy.md"
    write_failure_philosophy(state, "no selectable bucket", out)
    text = out.read_text(encoding="utf-8")
    assert "2026-06-01" in text
    assert "no selectable bucket" in text
    assert "## 실행 정합성" in text
