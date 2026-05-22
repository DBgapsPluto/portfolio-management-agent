"""CLI: anchor 카탈로그 LIVE Stage 1 평가 (synthetic 모드와 별도).

Usage:
    python scripts/anchor_eval_live.py                          # 전체 anchor
    python scripts/anchor_eval_live.py --anchor 2024-11_kr_boom # 단일
    python scripts/anchor_eval_live.py --compare-synthetic      # synthetic vs live 비교 표
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# shim — pandas_ta_classic, pypfopt stub (audit script와 동일)
if "pandas_ta" not in sys.modules:
    try:
        import pandas_ta_classic as _ta_classic
        sys.modules["pandas_ta"] = _ta_classic
    except ImportError:
        pass

from dotenv import load_dotenv
load_dotenv(dotenv_path=_ROOT / ".env")

from tradingagents.observability.anchor_evaluator import evaluate_anchor, evaluate_all
from tradingagents.observability.anchor_live import (
    evaluate_anchor_live, evaluate_all_live,
)


def _print_anchor(r, mode: str) -> None:
    head = f"[{r.anchor_id}] {r.title}  ({r.as_of_date})  — mode={mode}"
    print(f"\n{head}")
    print("  " + "-" * (len(head) - 2))
    print(f"  method chosen     : {r.chosen_method}")
    print(f"  positions         : {len(r.weights)}, unique_sub_cat={r.n_unique_sub_categories}, risk_asset={r.risk_asset_total:.3f}")
    print(f"  pass {r.pass_count}/{len(r.checks)}  (fail {r.fail_count})")
    for c in r.checks:
        icon = "✓" if c.passed else "✗"
        print(f"    {icon} {c.name:<22s} {c.detail}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--catalog", default=str(_ROOT / "data" / "historical_anchors"))
    p.add_argument("--anchor", default=None, help="단일 anchor_id (확장자 제외)")
    p.add_argument("--universe", default=str(_ROOT / "data" / "universe.json"))
    p.add_argument(
        "--cache",
        default=str(Path.home() / ".tradingagents" / "cache" / "etf_prices.parquet"),
    )
    p.add_argument("--out", default=None)
    p.add_argument(
        "--compare-synthetic", action="store_true",
        help="LIVE와 synthetic 동시 실행 후 비교 표 출력",
    )
    args = p.parse_args()

    catalog_dir = Path(args.catalog)
    if args.anchor:
        anchor_path = catalog_dir / f"{args.anchor}.json"
        if not anchor_path.exists():
            print(f"ERROR: no anchor {anchor_path}", file=sys.stderr)
            return 2

        if args.compare_synthetic:
            print(f"\n{'='*80}\n SYNTHETIC mode\n{'='*80}")
            r_syn = evaluate_anchor(anchor_path, universe_path=args.universe, cache_path=args.cache)
            _print_anchor(r_syn, "synthetic")
            print(f"\n{'='*80}\n LIVE mode (Stage 1 실측)\n{'='*80}")
            r_live = evaluate_anchor_live(anchor_path, universe_path=args.universe, cache_path=args.cache)
            _print_anchor(r_live, "live")
            print(f"\n--- 비교 요약 ---")
            print(f"  synthetic  pass {r_syn.pass_count}/{len(r_syn.checks)}, method={r_syn.chosen_method}")
            print(f"  live       pass {r_live.pass_count}/{len(r_live.checks)}, method={r_live.chosen_method}")
            return 0

        results = [evaluate_anchor_live(anchor_path, universe_path=args.universe, cache_path=args.cache)]
    else:
        if args.compare_synthetic:
            print(f"\n{'='*80}\n LIVE vs SYNTHETIC — 전체 anchor 비교\n{'='*80}")
            print(f"\n[synthetic mode 실행]")
            syn_results = evaluate_all(catalog_dir, universe_path=args.universe, cache_path=args.cache)
            print(f"\n[live mode 실행 — Stage 1 LLM 호출 발생]")
            live_results = evaluate_all_live(catalog_dir, universe_path=args.universe, cache_path=args.cache)

            syn_by_id = {r.anchor_id: r for r in syn_results}
            live_by_id = {r.anchor_id: r for r in live_results}

            print(f"\n{'anchor':<32s}  {'syn':>6s}    {'live':>6s}   syn_method  live_method")
            for aid in sorted(set(syn_by_id) | set(live_by_id)):
                s = syn_by_id.get(aid)
                l = live_by_id.get(aid)
                ss = f"{s.pass_count}/{len(s.checks)}" if s else "—"
                ll = f"{l.pass_count}/{len(l.checks)}" if l else "—"
                sm = s.chosen_method if s else "—"
                lm = l.chosen_method if l else "—"
                marker = "" if (s and l and s.pass_count == l.pass_count) else " *"
                print(f"  {aid:<32s}  {ss:>6s}    {ll:>6s}   {sm:<10s}  {lm}{marker}")
            return 0

        results = evaluate_all_live(catalog_dir, universe_path=args.universe, cache_path=args.cache)

    print("\n" + "=" * 80)
    print(f" ANCHOR LIVE EVAL — {len(results)} anchors")
    print("=" * 80)
    for r in results:
        _print_anchor(r, "live")

    total_pass = sum(r.pass_count for r in results)
    total_checks = sum(len(r.checks) for r in results)
    print("\n" + "=" * 80)
    print(f" SUMMARY: {total_pass}/{total_checks} checks passed  ({total_pass/max(total_checks,1)*100:.0f}%)")
    print("=" * 80)
    for r in results:
        print(f"  {r.anchor_id:<32s} {r.pass_count:>4d} / {len(r.checks):>3d}  {r.chosen_method}")

    out_path = args.out or str(_ROOT / "artifacts" / "anchor_live_report.json")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {"anchors": [r.to_dict() for r in results],
             "summary": {"total_pass": total_pass, "total_checks": total_checks}},
            indent=2, ensure_ascii=False, default=str,
        ),
        encoding="utf-8",
    )
    print(f"\n  → JSON saved: {out_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
