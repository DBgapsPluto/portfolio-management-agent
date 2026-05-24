"""CLI for Stage 3 ablation — archive에서 state 복원 후 변형 비교.

Usage:
    python scripts/stage3_ablation.py --as-of 2026-05-15 \\
        [--variants baseline,no_regime,no_boost,raw_factors] \\
        [--out artifacts/ablation_2026-05-15.json]

Output:
    - stdout: bucket별 요약 표 + 변형별 mean_jaccard / mean_spearman
    - JSON file: 전체 비교 결과 (BucketComparison 포함)

LLM 의존 0. cache_path는 ~/.tradingagents/cache/etf_prices.parquet 사용.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

# Path setup
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Load .env (audit script와 동일 패턴)
from dotenv import load_dotenv
load_dotenv(dotenv_path=_ROOT / ".env")

from tradingagents.dataflows.universe import load_universe
from tradingagents.observability.replay import (
    STAGE_PREREQUISITES, _load_archived_key,
)
from tradingagents.observability.stage3_ablation import (
    VARIANT_OVERRIDES, run_ablation,
)
from tradingagents.skills.portfolio.returns_matrix import fetch_returns_matrix
from tradingagents.skills.portfolio.candidate_selector import (
    BUCKET_TO_CATEGORIES, list_eligible_tickers,
)


def _restore_inputs(as_of_str: str, archive_dir: Path):
    """archive에서 Stage 3 prereq 추출 → (state-like dict)."""
    state: dict = {}
    for key in STAGE_PREREQUISITES["allocator"]:
        val = _load_archived_key(archive_dir, key)
        if val is not None:
            state[key] = val
    return state


def main() -> int:
    p = argparse.ArgumentParser(description="Stage 3 ablation")
    p.add_argument("--as-of", required=True, help="ISO date (e.g. 2026-05-15)")
    p.add_argument(
        "--variants",
        default=",".join(VARIANT_OVERRIDES.keys()),
        help=f"comma-separated subset of {sorted(VARIANT_OVERRIDES.keys())}",
    )
    p.add_argument("--universe", default=str(_ROOT / "data" / "universe.json"))
    p.add_argument(
        "--cache",
        default=str(Path.home() / ".tradingagents" / "cache" / "etf_prices.parquet"),
    )
    p.add_argument(
        "--out",
        default=None,
        help="JSON output path (default: artifacts/ablation_{as_of}.json)",
    )
    args = p.parse_args()

    as_of = date.fromisoformat(args.as_of)
    archive_dir = Path.home() / ".tradingagents" / "runs" / args.as_of
    if not archive_dir.exists():
        print(f"ERROR: no archive at {archive_dir}", file=sys.stderr)
        return 2

    universe = load_universe(args.universe)
    inputs = _restore_inputs(args.as_of, archive_dir)
    required = ["bucket_target", "technical_report", "macro_report", "risk_report"]
    missing = [k for k in required if k not in inputs]
    if missing:
        print(f"ERROR: missing archive keys {missing}", file=sys.stderr)
        return 2

    bucket_target = inputs["bucket_target"]
    tech_report = inputs["technical_report"]
    macro_report = inputs["macro_report"]
    risk_report = inputs["risk_report"]
    research_decision = inputs.get("research_decision")

    # eligible tickers + returns matrix (전체 universe 한 번만 fetch)
    eligible_by_bucket = list_eligible_tickers(
        universe, bucket_target, as_of=as_of,
        min_aum_krw=1_000_000_000_000,
    )
    eligible = sorted({t for ts in eligible_by_bucket.values() for t in ts})
    if not eligible:
        print("ERROR: no eligible tickers", file=sys.stderr)
        return 2

    from datetime import timedelta
    returns = fetch_returns_matrix(
        eligible, as_of - timedelta(days=365 * 3), as_of, cache_path=args.cache,
    )

    # baseline kwargs (Stage 3 allocator와 동일 로직)
    regime = macro_report.regime
    dom_scenario = None
    if research_decision is not None:
        cell = getattr(research_decision, "dominant_cell", None)
        if cell is not None and hasattr(cell, "key"):
            dom_scenario = cell.key
        else:
            dom_scenario = getattr(research_decision, "dominant_scenario", None)

    per_bucket_n = 4
    if research_decision is not None and getattr(research_decision, "conviction", "medium") == "low":
        per_bucket_n = 5

    baseline_kwargs = dict(
        regime_quadrant=regime.quadrant if regime else None,
        regime_confidence=regime.confidence if regime else 0.5,
        dominant_scenario=dom_scenario,
        per_bucket_n=per_bucket_n,
        correlation_threshold=0.85,
        min_aum_krw=1_000_000_000_000,
    )

    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    print(f"\n=== Stage 3 Ablation — as_of={args.as_of} ===")
    print(f"  variants            : {variants}")
    print(f"  regime              : {regime.quadrant if regime else None} (conf={regime.confidence if regime else 0:.2f})")
    print(f"  dominant_scenario   : {dom_scenario}")
    print(f"  per_bucket_n        : {per_bucket_n}")
    print(f"  eligible (universe) : {len(eligible)} tickers")
    print(f"  returns matrix      : {returns.shape}")

    report = run_ablation(
        universe=universe,
        bucket_target=bucket_target,
        as_of=as_of,
        returns=returns,
        factor_panel=tech_report.factor_panel,
        baseline_kwargs=baseline_kwargs,
        variants=variants,
    )

    # stdout 요약 표
    print(f"\n--- 변형별 요약 (baseline 대비) ---")
    print(f"  {'variant':<12s} {'mean_jaccard':>12s} {'mean_spearman':>14s} {'diff_picks':>10s}")
    print(f"  {'-'*52}")
    for v in variants:
        if v == "baseline":
            continue
        s = report.summary[v]
        print(f"  {v:<12s} {s['mean_jaccard']:>12.3f} {s['mean_spearman']:>14.3f} {s['total_diff_picks']:>10d}")

    print(f"\n--- bucket × 변형 — 선정 차이 (baseline → variant) ---")
    for v in variants:
        if v == "baseline":
            continue
        print(f"\n  [{v}]")
        for bucket, cmp in report.bucket_comparisons[v].items():
            if not cmp.only_baseline and not cmp.only_variant:
                continue
            print(f"    {bucket:14s} jacc={cmp.jaccard:.2f} ρ={cmp.spearman:.2f}"
                  f"  -[{','.join(cmp.only_baseline) or '∅'}]"
                  f"  +[{','.join(cmp.only_variant) or '∅'}]")

    # JSON 저장
    out_path = args.out or str(_ROOT / "artifacts" / f"ablation_{args.as_of}.json")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(f"\n  → JSON saved: {out_path}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
