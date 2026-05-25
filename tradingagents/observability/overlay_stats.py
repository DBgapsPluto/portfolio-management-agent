"""Stage 4 overlay outcome telemetry — append-only jsonl + summarize.

매 risk_judge 실행마다 한 줄 append. CLI 가 누적 통계 표 출력.

Path default: ~/.tradingagents/stats/overlay_outcomes.jsonl
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_STATS_PATH = Path.home() / ".tradingagents" / "stats" / "overlay_outcomes.jsonl"


def record_overlay_outcome(
    *,
    date: str,
    outcome: str,
    lens_levels: dict[str, str],
    strength: float,
    multiplier: float,
    stats_path: Path | str | None = None,
) -> None:
    """Append one jsonl line. 부모 dir 없으면 생성."""
    path = Path(stats_path) if stats_path else DEFAULT_STATS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "date":              date,
        "outcome":           outcome,
        "lens_levels":       lens_levels,
        "strength_applied":  strength,
        "multiplier_final":  multiplier,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def summarize_outcomes(
    stats_path: Path | str | None = None,
    *,
    last_n: int | None = None,
) -> dict[str, Any]:
    """누적 stats 집계. last_n 지정 시 최근 N 개만."""
    path = Path(stats_path) if stats_path else DEFAULT_STATS_PATH
    if not path.exists():
        return {
            "n_runs": 0, "outcome_counts": {}, "fallback_pct": 0.0,
            "mean_strength": 0.0, "lens_severity": {},
        }
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    records = [json.loads(line) for line in lines if line.strip()]
    if last_n is not None:
        records = records[-last_n:]
    if not records:
        return {
            "n_runs": 0, "outcome_counts": {}, "fallback_pct": 0.0,
            "mean_strength": 0.0, "lens_severity": {},
        }
    outcome_counts = Counter(r["outcome"] for r in records)
    fallback_pct = outcome_counts.get("fallback_to_1st", 0) / len(records)
    mean_strength = sum(r["strength_applied"] for r in records) / len(records)
    lens_severity: dict[str, Counter] = {}
    for r in records:
        for lens, lvl in r.get("lens_levels", {}).items():
            lens_severity.setdefault(lens, Counter())[lvl] += 1
    return {
        "n_runs":         len(records),
        "outcome_counts": dict(outcome_counts),
        "fallback_pct":   fallback_pct,
        "mean_strength":  mean_strength,
        "lens_severity":  {l: dict(c) for l, c in lens_severity.items()},
    }
