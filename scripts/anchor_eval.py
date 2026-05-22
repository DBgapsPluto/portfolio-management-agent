"""CLI: data/historical_anchors/*.json 카탈로그로 Stage 3 평가.

Usage:
    python scripts/anchor_eval.py                          # 전체 anchor 실행
    python scripts/anchor_eval.py --anchor 2024-11_kr_boom # 단일 anchor만
    python scripts/anchor_eval.py --out artifacts/anchor_report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(dotenv_path=_ROOT / ".env")

from tradingagents.observability.anchor_evaluator import (
    AnchorEvalResult, evaluate_anchor, evaluate_all,
)


def _print_anchor(r: AnchorEvalResult) -> None:
    icon_pass = "✓"
    icon_fail = "✗"
    head = f"[{r.anchor_id}] {r.title}  ({r.as_of_date})"
    print(f"\n{head}")
    print("  " + "-" * (len(head) - 2))
    print(f"  method chosen     : {r.chosen_method}")
    print(f"  positions         : {len(r.weights)}, unique_sub_cat={r.n_unique_sub_categories}, risk_asset={r.risk_asset_total:.3f}")
    print(f"  pass {r.pass_count}/{len(r.checks)}  (fail {r.fail_count})\n")
    for c in r.checks:
        icon = icon_pass if c.passed else icon_fail
        print(f"    {icon} {c.name:<22s} {c.detail}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--catalog", default=str(_ROOT / "data" / "historical_anchors"),
        help="anchor catalog directory",
    )
    p.add_argument(
        "--anchor", default=None,
        help="단일 anchor_id (확장자 제외). 미지정 시 전체 실행",
    )
    p.add_argument(
        "--universe", default=str(_ROOT / "data" / "universe.json"),
    )
    p.add_argument(
        "--cache",
        default=str(Path.home() / ".tradingagents" / "cache" / "etf_prices.parquet"),
    )
    p.add_argument(
        "--out", default=None,
        help="결과 JSON 저장 경로. default: artifacts/anchor_report.json",
    )
    args = p.parse_args()

    catalog_dir = Path(args.catalog)
    if not catalog_dir.exists():
        print(f"ERROR: no catalog dir {catalog_dir}", file=sys.stderr)
        return 2

    if args.anchor:
        anchor_path = catalog_dir / f"{args.anchor}.json"
        if not anchor_path.exists():
            print(f"ERROR: no anchor {anchor_path}", file=sys.stderr)
            return 2
        results = [evaluate_anchor(
            anchor_path, universe_path=args.universe, cache_path=args.cache,
        )]
    else:
        results = evaluate_all(
            catalog_dir, universe_path=args.universe, cache_path=args.cache,
        )

    print("\n" + "=" * 80)
    print(f" ANCHOR EVAL — {len(results)} anchors")
    print("=" * 80)
    for r in results:
        _print_anchor(r)

    # 요약
    total_pass = sum(r.pass_count for r in results)
    total_checks = sum(len(r.checks) for r in results)
    print("\n" + "=" * 80)
    print(f" SUMMARY: {total_pass}/{total_checks} checks passed  ({total_pass/max(total_checks,1)*100:.0f}%)")
    print("=" * 80)
    print(f"  {'anchor':<32s} {'pass':>4s} / {'tot':>3s}  method")
    for r in results:
        print(f"  {r.anchor_id:<32s} {r.pass_count:>4d} / {len(r.checks):>3d}  {r.chosen_method}")
    print()

    out_path = args.out or str(_ROOT / "artifacts" / "anchor_report.json")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "anchors": [r.to_dict() for r in results],
                "summary": {
                    "total_pass":   total_pass,
                    "total_checks": total_checks,
                    "pass_rate":    total_pass / max(total_checks, 1),
                },
            },
            indent=2, ensure_ascii=False, default=str,
        ),
        encoding="utf-8",
    )
    print(f"  → JSON saved: {out_path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
