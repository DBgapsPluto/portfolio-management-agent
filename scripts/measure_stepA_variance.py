"""Step A(allocator) 변동성 측정 — 같은 archived state 에 N회 반복, 버킷별 stdev.

measure_llm_variance.py (OBSOLETE, 24-cell factor model 측정용) 대체.

Usage:
    set -a && source .env && set +a
    python scripts/measure_stepA_variance.py --as-of 2026-05-15 --runs 20

앵커 도입 전(현 코드)에서 한 번, Phase 1 후 다시 실행 → bucket stdev 비교(L2 게이트).
"""
from __future__ import annotations

import argparse
import logging
import statistics
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=_ROOT / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--as-of", required=True, help="YYYY-MM-DD (archived run 존재해야 함)")
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--preset", default="db_gaps")
    ap.add_argument("--capital", type=int, default=1_000_000_000)
    args = ap.parse_args()

    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.observability.replay import restore_state, run_stage

    config = dict(DEFAULT_CONFIG)
    graph = TradingAgentsGraph(preset_name=args.preset, config=config)
    state, missing = restore_state(
        as_of_date=args.as_of, stage="allocator",
        universe_path=config["universe_path"], capital_krw=args.capital,
        preset_name=args.preset,
    )
    if missing:
        logger.warning("missing prereq keys: %s", missing)

    samples: dict[str, list[float]] = {}
    for i in range(args.runs):
        result = run_stage(graph, "allocator", dict(state), write_to_archive=False)
        weights = result["bucket_target"].weights
        for b, w in weights.items():
            samples.setdefault(b, []).append(w)
        logger.info("run %d/%d done", i + 1, args.runs)

    print(f"\n=== Step A bucket weight variance ({args.runs} runs, as_of={args.as_of}) ===")
    print(f"{'bucket':<22}{'mean':>8}{'stdev':>8}{'min':>8}{'max':>8}")
    total_std = 0.0
    for b in sorted(samples):
        xs = samples[b]
        sd = statistics.pstdev(xs) if len(xs) > 1 else 0.0
        total_std += sd
        print(f"{b:<22}{statistics.fmean(xs):>8.3f}{sd:>8.3f}{min(xs):>8.3f}{max(xs):>8.3f}")
    print(f"\nΣ bucket stdev = {total_std:.4f}  (낮을수록 결정론적)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
