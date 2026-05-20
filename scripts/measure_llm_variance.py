"""LLM stochasticity 측정 — research_debate를 N회 반복 호출하고 분산 산출.

같은 (macro_report, risk_report, summaries) 입력으로 LLM이 매번 다른 ScenarioProb24
를 출력하는데, 이 분산이 portfolio에 얼마나 전달되는지 측정.

Usage:
    set -a && source .env && set +a
    python3 scripts/measure_llm_variance.py --as-of 2026-05-15 --n 5
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
import warnings
from collections import Counter
from datetime import date, datetime
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "std": statistics.pstdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
        "range": max(values) - min(values),
    }


def _fmt_stats(s: dict, fmt: str = ".3f", scale: float = 1.0) -> str:
    if s.get("n", 0) == 0:
        return "no data"
    return (
        f"mean={s['mean']*scale:{fmt}} std={s['std']*scale:{fmt}} "
        f"range=[{s['min']*scale:{fmt}}, {s['max']*scale:{fmt}}]"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", default="2026-05-15")
    parser.add_argument("--n", type=int, default=5, help="반복 횟수")
    parser.add_argument("--out", default=None,
                        help="raw 결과 JSON 저장 경로 (default: runs/{as_of}/variance/{ts}.json)")
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
        logger.info("Run %d/%d ...", i + 1, args.n)
        state, _missing = restore_state(
            as_of_date=args.as_of, stage="research_debate",
            universe_path=DEFAULT_CONFIG["universe_path"],
        )
        t0 = time.time()
        try:
            result = run_stage(graph, "research_debate", state)
        except Exception as e:
            logger.warning("run %d failed: %s", i + 1, e)
            continue
        elapsed = time.time() - t0
        rd = result["research_decision"]
        bt = rd.bucket_target
        runs.append({
            "run": i + 1,
            "elapsed_s": elapsed,
            "dominant_cycle": rd.dominant_cycle,
            "dominant_cycle_prob": rd.dominant_cycle_probability,
            "dominant_cell": rd.dominant_cell.key,
            "dominant_cell_prob": rd.dominant_cell_probability,
            "conviction": rd.conviction,
            "conviction_beta": rd.conviction_beta,
            "cycle_marginals": dict(rd.cycle_marginals),
            "tail_marginals": dict(rd.tail_marginals),
            "kr_marginals": dict(rd.kr_marginals),
            "eff_cycle_marginals": dict(rd.effective_cycle_marginals),
            "portfolio": {
                "kr_equity": bt.kr_equity, "global_equity": bt.global_equity,
                "fx_commodity": bt.fx_commodity, "bond": bt.bond,
                "bond_tips_share": bt.bond_tips_share, "cash_mmf": bt.cash_mmf,
            },
        })
    logger.info("Collected %d runs", len(runs))

    # === Summary stats ===
    print(f"\n=== Variance summary (n={len(runs)}) ===\n")

    # Dominant cycle distribution
    dom_cycles = Counter(r["dominant_cycle"] for r in runs)
    print(f"Dominant cycle frequency: {dict(dom_cycles)}")
    dom_cells = Counter(r["dominant_cell"] for r in runs)
    print(f"Dominant cell frequency:  {dict(dom_cells)}")
    convictions = Counter(r["conviction"] for r in runs)
    print(f"Conviction frequency:     {dict(convictions)}")
    print()

    # Continuous metrics
    print(f"{'metric':<35}{'stats (pct or value)':<70}")
    print("-" * 105)
    for label, key in [
        ("dominant_cycle_prob (%)", "dominant_cycle_prob"),
        ("dominant_cell_prob (%)", "dominant_cell_prob"),
        ("conviction_beta", "conviction_beta"),
        ("elapsed (s)", "elapsed_s"),
    ]:
        vals = [r[key] for r in runs]
        scale = 100 if "prob" in key else 1
        print(f"{label:<35}{_fmt_stats(_stats(vals), '.2f', scale=scale)}")

    print("\nCycle marginal stats (raw):")
    for c in ("A", "B", "C", "D"):
        vals = [r["cycle_marginals"].get(c, 0) for r in runs]
        print(f"  {c}: {_fmt_stats(_stats(vals), '.1f', scale=100)} %")
    print("Tail marginal stats:")
    for t in ("N", "T"):
        vals = [r["tail_marginals"].get(t, 0) for r in runs]
        print(f"  {t}: {_fmt_stats(_stats(vals), '.1f', scale=100)} %")
    print("KR marginal stats:")
    for k in ("F", "boom", "stress"):
        vals = [r["kr_marginals"].get(k, 0) for r in runs]
        print(f"  {k}: {_fmt_stats(_stats(vals), '.1f', scale=100)} %")
    print("Effective cycle marginal stats (post-sharpening):")
    for c in ("A", "B", "C", "D"):
        vals = [r["eff_cycle_marginals"].get(c, 0) for r in runs]
        print(f"  {c}: {_fmt_stats(_stats(vals), '.1f', scale=100)} %")

    print("\nPortfolio weight stats:")
    for key in ("kr_equity", "global_equity", "fx_commodity", "bond",
                "bond_tips_share", "cash_mmf"):
        vals = [r["portfolio"][key] for r in runs]
        print(f"  {key:<22}{_fmt_stats(_stats(vals), '.1f', scale=100)} %")

    # === Stability verdict ===
    print()
    cycle_stable = max(dom_cycles.values()) / len(runs)
    cycle_prob_std = statistics.pstdev([r["dominant_cycle_prob"] for r in runs])
    bond_std = statistics.pstdev([r["portfolio"]["bond"] for r in runs])
    fx_std = statistics.pstdev([r["portfolio"]["fx_commodity"] for r in runs])

    print("=== Verdict ===")
    print(f"dominant_cycle 일관성: {cycle_stable*100:.0f}% ({max(dom_cycles, key=dom_cycles.get)} 우세)")
    print(f"dominant_cycle_prob σ: {cycle_prob_std*100:.1f}pp")
    print(f"bond weight σ:         {bond_std*100:.1f}pp")
    print(f"fx_commodity σ:        {fx_std*100:.1f}pp")

    # === Save raw ===
    if args.out:
        out_path = Path(args.out)
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        cache_dir = Path(DEFAULT_CONFIG["data_cache_dir"])
        out_dir = cache_dir.parent / "runs" / args.as_of / "variance"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{ts}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"as_of": args.as_of, "n": len(runs), "runs": runs},
                   indent=2, default=str),
        encoding="utf-8",
    )
    logger.info("Raw saved → %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
