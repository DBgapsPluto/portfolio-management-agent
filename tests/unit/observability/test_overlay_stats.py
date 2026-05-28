"""overlay_stats jsonl append + summarize."""
import json
from pathlib import Path

import pytest

from tradingagents.observability.overlay_stats import (
    record_overlay_outcome, summarize_outcomes,
)


def test_record_overlay_outcome_appends_jsonl_line(tmp_path: Path):
    stats_path = tmp_path / "outcomes.jsonl"
    record_overlay_outcome(
        date="2026-05-25", outcome="relax_band",
        lens_levels={"tail_risk": "low", "concentration": "critical",
                     "macro_conditional": "medium"},
        strength=0.7, multiplier=0.944, stats_path=stats_path,
    )
    assert stats_path.exists()
    lines = stats_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["date"] == "2026-05-25"
    assert rec["outcome"] == "relax_band"
    assert rec["lens_levels"]["concentration"] == "critical"
    assert rec["strength_applied"] == 0.7
    assert rec["multiplier_final"] == 0.944


def test_record_overlay_outcome_append_mode(tmp_path: Path):
    stats_path = tmp_path / "outcomes.jsonl"
    for d in ("2026-05-20", "2026-05-21", "2026-05-22"):
        record_overlay_outcome(
            date=d, outcome="primary_success", lens_levels={},
            strength=0.0, multiplier=1.0, stats_path=stats_path,
        )
    lines = stats_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3


def test_summarize_outcomes_counts_and_means(tmp_path: Path):
    stats_path = tmp_path / "outcomes.jsonl"
    for d, oc, s in (
        ("2026-05-20", "primary_success", 0.5),
        ("2026-05-21", "relax_band", 0.7),
        ("2026-05-22", "fallback_to_1st", 1.0),
        ("2026-05-23", "primary_success", 0.3),
    ):
        record_overlay_outcome(
            date=d, outcome=oc, lens_levels={"tail_risk": "low"},
            strength=s, multiplier=0.9, stats_path=stats_path,
        )
    summary = summarize_outcomes(stats_path)
    assert summary["n_runs"] == 4
    assert summary["outcome_counts"]["primary_success"] == 2
    assert summary["outcome_counts"]["relax_band"] == 1
    assert summary["outcome_counts"]["fallback_to_1st"] == 1
    # fallback_pct = 1/4 = 0.25
    assert summary["fallback_pct"] == pytest.approx(0.25)
    # mean strength = (0.5+0.7+1.0+0.3)/4 = 0.625
    assert summary["mean_strength"] == pytest.approx(0.625)


def test_summarize_outcomes_empty_file(tmp_path: Path):
    stats_path = tmp_path / "outcomes.jsonl"
    summary = summarize_outcomes(stats_path)
    assert summary["n_runs"] == 0
    assert summary["outcome_counts"] == {}
    assert summary["fallback_pct"] == 0.0
