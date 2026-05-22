"""Stage 2 ablation 실험 — macro_summary 의존도 측정.

3개 mode 로 N회씩 stage 2 호출:
  - baseline:           정상 4-summary prompt
  - no_macro:           macro_summary 제거 (나머지 3개만)
  - perturb_quadrant:   macro_summary 의 regime quadrant 다른 값으로 swap

산출: cycle marginal, bucket_target, dominant_scenario per mode.
해석: L1 distance(baseline, no_macro) 작고 L1 distance(baseline, perturb)
크면 macro_quant anchoring 강함 (stage 2 = reformat).

Usage:
    python3 scripts/measure_stage2_ablation.py --as-of 2026-05-15 \
        --mode {baseline,no_macro,perturb_quadrant} --n 3
"""
from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


_QUADRANT_PERTURBATION: dict[str, str] = {
    "growth_disinflation":     "recession_inflation",
    "growth_inflation":        "recession_disinflation",
    "recession_disinflation":  "growth_inflation",
    "recession_inflation":     "growth_disinflation",
}


def _apply_mode(state: dict, mode: str) -> dict:
    """state 의 macro_summary 를 mode 에 따라 변형."""
    macro = state.get("macro_summary", "")
    if mode == "baseline":
        return state
    if mode == "no_macro":
        new = dict(state)
        new["macro_summary"] = ""
        return new
    if mode == "perturb_quadrant":
        macro_report = state.get("macro_report")
        if macro_report is None:
            return state
        regime = getattr(macro_report, "regime", None)
        if regime is None:
            return state
        orig_q = getattr(regime, "quadrant", None)
        if orig_q not in _QUADRANT_PERTURBATION:
            return state
        perturbed_q = _QUADRANT_PERTURBATION[orig_q]
        new = dict(state)
        # 텍스트 placeholder swap (state object deep mutate 회피)
        new["macro_summary"] = (macro or "").replace(orig_q, perturbed_q)
        # macro_report.regime.quadrant 도 임시 swap (deep copy 안전)
        mr_copy = copy.deepcopy(macro_report)
        try:
            mr_copy.regime.quadrant = perturbed_q
        except Exception:
            pass
        new["macro_report"] = mr_copy
        return new
    raise ValueError(f"Unknown mode: {mode}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", default="2026-05-15")
    parser.add_argument("--mode",
                        choices=["baseline", "no_macro", "perturb_quadrant"],
                        required=True)
    parser.add_argument("--n", type=int, default=3)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    try:
        datetime.strptime(args.as_of, "%Y-%m-%d")
    except ValueError:
        logger.error("Invalid --as-of"); return 1

    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.observability.replay import restore_state, run_stage

    graph = TradingAgentsGraph(preset_name="db_gaps")

    runs: list[dict] = []
    for i in range(args.n):
        logger.info("Mode=%s run %d/%d ...", args.mode, i + 1, args.n)
        state, _missing = restore_state(
            as_of_date=args.as_of, stage="research_debate",
            universe_path=DEFAULT_CONFIG["universe_path"],
        )
        state = _apply_mode(state, args.mode)
        t0 = time.time()
        try:
            result = run_stage(graph, "research_debate", state)
        except Exception as e:
            logger.warning("Run %d failed: %s", i + 1, e)
            continue
        elapsed = time.time() - t0
        rd = result["research_decision"]
        bt = rd.bucket_target
        # C5 (2026-05-23): 24-cell field 제거됨. factor model 의 z-score 기록.
        runs.append({
            "run": i + 1,
            "mode": args.mode,
            "elapsed_s": elapsed,
            "dominant_scenario": rd.dominant_scenario,
            "conviction": rd.conviction,
            "factor_scores": dict(rd.factor_scores),
            "portfolio": {
                "kr_equity": bt.kr_equity, "global_equity": bt.global_equity,
                "fx_commodity": bt.fx_commodity, "bond": bt.bond,
                "bond_tips_share": bt.bond_tips_share, "cash_mmf": bt.cash_mmf,
            },
        })
    logger.info("Collected %d runs for mode=%s", len(runs), args.mode)

    # 평균
    if runs:
        # factor mean (9 dim)
        all_factors = sorted({f for r in runs for f in r["factor_scores"]})
        avg_factors = {
            f: sum(r["factor_scores"].get(f, 0.0) for r in runs) / len(runs)
            for f in all_factors
        }
        print(f"\n=== Mode={args.mode} (n={len(runs)}) ===")
        print(f"Avg factor z-scores: {avg_factors}")
        scenarios = [r["dominant_scenario"] for r in runs]
        print(f"Dominant scenarios: {scenarios}")

    # save
    if args.out:
        out_path = Path(args.out)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        cache_dir = Path(DEFAULT_CONFIG["data_cache_dir"])
        out_dir = cache_dir.parent / "artifacts" / "2026-05-20" / "ablation"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{args.mode}_n{args.n}_{ts}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"mode": args.mode, "n": len(runs), "runs": runs},
                   indent=2, default=str),
        encoding="utf-8",
    )
    logger.info("Saved → %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
