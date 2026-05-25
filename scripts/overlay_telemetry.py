"""Stage 4 overlay outcome 누적 stats 표.

Usage:
    python scripts/overlay_telemetry.py
    python scripts/overlay_telemetry.py --last 30
    python scripts/overlay_telemetry.py --stats-path ~/.tradingagents/stats/overlay_outcomes.jsonl
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tradingagents.observability.overlay_stats import (
    DEFAULT_STATS_PATH, summarize_outcomes,
)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--last", type=int, default=None, help="최근 N 개만")
    p.add_argument(
        "--stats-path", default=str(DEFAULT_STATS_PATH),
        help="jsonl 경로",
    )
    args = p.parse_args()

    stats_path = Path(args.stats_path).expanduser()
    summary = summarize_outcomes(stats_path, last_n=args.last)

    header = f"Stage 4 overlay telemetry — {stats_path}"
    if args.last:
        header += f" (last {args.last} runs)"
    print(header)
    print("-" * len(header))

    n = summary["n_runs"]
    if n == 0:
        print("no records.")
        return 0

    print(f"\nTotal runs: {n}")
    print(f"Mean strength_applied: {summary['mean_strength']:.3f}")
    print(f"Fallback rate (fallback_to_1st): {summary['fallback_pct']*100:.1f}%")

    print("\nOutcome counts:")
    for oc in ("primary_success", "relax_cluster", "relax_ceiling",
               "relax_band", "fallback_to_1st"):
        c = summary["outcome_counts"].get(oc, 0)
        pct = c / n * 100
        print(f"  {oc:<20s} {c:>5d} ({pct:5.1f}%)")

    print("\nLens severity distribution:")
    for lens in ("tail_risk", "concentration", "macro_conditional"):
        sev = summary["lens_severity"].get(lens, {})
        parts = [
            f"{lvl}={sev.get(lvl, 0)}"
            for lvl in ("none", "low", "medium", "high", "critical")
        ]
        print(f"  {lens:<18s} " + " ".join(parts))

    return 0


if __name__ == "__main__":
    sys.exit(main())
