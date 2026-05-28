#!/usr/bin/env python3
"""Phase 1 regression comparator — baseline vs new artifacts.

사용:
    python scripts/regression_compare.py \
        --baseline artifacts/baseline/ \
        --new artifacts/phase1/ \
        [--out diff.json]

각 디렉토리 안에 portfolio.json 또는 YYYY-MM-DD/portfolio.json 다중 as_of.

Spec (acceptance criteria) 검증:
  (a) new_sharpe >= 0.95 × baseline_sharpe
  (b) new_vol <= 1.02 × baseline_vol
  (c) attribution['cash_spillover'], attribution['enb'] 채워짐
  (d) fx_commodity case: bucket weight 감소, chosen 모두 alpha > 0, cash 증가

exit code: 0 = 전부 PASS, 1 = 하나라도 FAIL.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_portfolio_jsons(root: Path) -> dict[str, dict]:
    """root 아래 portfolio.json 들을 {as_of: payload} 로 반환."""
    out: dict[str, dict] = {}
    if (root / "portfolio.json").exists():
        with open(root / "portfolio.json") as f:
            payload = json.load(f)
        out[payload.get("as_of_date", "unknown")] = payload
        return out
    for sub in sorted(root.iterdir()):
        if sub.is_dir():
            p = sub / "portfolio.json"
            if p.exists():
                with open(p) as f:
                    payload = json.load(f)
                out[sub.name] = payload
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / max(len(a | b), 1)


def _l1_weight_distance(wa: dict, wb: dict) -> float:
    keys = set(wa) | set(wb)
    return sum(abs(wa.get(k, 0.0) - wb.get(k, 0.0)) for k in keys)


def _relative_delta(new: float | None, baseline: float | None) -> float | None:
    if new is None or baseline is None or baseline == 0:
        return None
    return (new - baseline) / abs(baseline)


def compare_one(as_of: str, baseline: dict, new: dict) -> dict:
    """as_of 별 비교. returns acceptance pass/fail per criterion."""
    bw = baseline.get("weights") or {}
    nw = new.get("weights") or {}
    bbt = baseline.get("bucket_target") or {}
    nbt = new.get("bucket_target") or {}
    n_attr = new.get("allocation_attribution") or {}

    sharpe_b = baseline.get("expected_sharpe")
    sharpe_n = new.get("expected_sharpe")
    vol_b = baseline.get("expected_volatility")
    vol_n = new.get("expected_volatility")

    bucket_delta = {
        b: (nbt.get(b, 0.0) - bbt.get(b, 0.0))
        for b in ("kr_equity", "global_equity", "fx_commodity", "bond", "cash_mmf")
    }

    # Acceptance
    sharpe_ratio = (sharpe_n / sharpe_b) if (sharpe_b and sharpe_n is not None) else None
    accept_a = (sharpe_ratio is not None and sharpe_ratio >= 0.95) or sharpe_b is None
    vol_ratio = (vol_n / vol_b) if (vol_b and vol_n is not None) else None
    accept_b = (vol_ratio is not None and vol_ratio <= 1.02) or vol_b is None
    accept_c = ("cash_spillover" in n_attr) and ("enb" in n_attr)

    # (d) fx_commodity case 만 적용 (2026-05-15 등에서)
    fx_baseline = bbt.get("fx_commodity", 0.0)
    fx_new = nbt.get("fx_commodity", 0.0)
    cash_baseline = bbt.get("cash_mmf", 0.0)
    cash_new = nbt.get("cash_mmf", 0.0)
    fx_alpha_breakdown = (n_attr.get("buckets", {}).get("fx_commodity", {})
                          .get("alpha_scores") or {})
    fx_chosen = (n_attr.get("buckets", {}).get("fx_commodity", {})
                 .get("chosen") or [])
    fx_chosen_all_positive = (
        all(fx_alpha_breakdown.get(t, 0.0) > 0 for t in fx_chosen)
        if fx_chosen else True
    )
    accept_d = (
        (fx_new <= fx_baseline + 1e-6)
        and fx_chosen_all_positive
        and (cash_new >= cash_baseline - 1e-6)
    )

    return {
        "as_of": as_of,
        "weight_jaccard": _jaccard(set(bw), set(nw)),
        "weight_l1": _l1_weight_distance(bw, nw),
        "sharpe_baseline": sharpe_b,
        "sharpe_new": sharpe_n,
        "sharpe_ratio": sharpe_ratio,
        "vol_baseline": vol_b,
        "vol_new": vol_n,
        "vol_ratio": vol_ratio,
        "bucket_delta": bucket_delta,
        "tickers_added": sorted(set(nw) - set(bw)),
        "tickers_removed": sorted(set(bw) - set(nw)),
        "cash_spillover_present": "cash_spillover" in n_attr,
        "enb_value": n_attr.get("enb"),
        "fx_bucket_baseline": fx_baseline,
        "fx_bucket_new": fx_new,
        "fx_chosen_all_positive": fx_chosen_all_positive,
        "acceptance": {
            "(a) sharpe": accept_a,
            "(b) volatility": accept_b,
            "(c) attribution": accept_c,
            "(d) fx_commodity": accept_d,
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    baselines = _load_portfolio_jsons(args.baseline)
    news = _load_portfolio_jsons(args.new)
    common = sorted(set(baselines) & set(news))
    if not common:
        print(f"ERROR: no common as_of between {args.baseline} and {args.new}", file=sys.stderr)
        sys.exit(1)

    results = []
    overall_pass = True
    for as_of in common:
        r = compare_one(as_of, baselines[as_of], news[as_of])
        results.append(r)
        all_pass = all(r["acceptance"].values())
        if not all_pass:
            overall_pass = False
        print(f"\n=== {as_of} ===")
        print(f"  weight Jaccard:  {r['weight_jaccard']:.3f}")
        print(f"  weight L1:       {r['weight_l1']:.4f}")
        print(f"  sharpe: {r['sharpe_baseline']} → {r['sharpe_new']} "
              f"(ratio={r['sharpe_ratio']})")
        print(f"  vol:    {r['vol_baseline']} → {r['vol_new']} "
              f"(ratio={r['vol_ratio']})")
        print(f"  fx bucket: {r['fx_bucket_baseline']:.3f} → {r['fx_bucket_new']:.3f}")
        print(f"  ENB:    {r['enb_value']}")
        print(f"  tickers added:   {r['tickers_added'][:5]}{'...' if len(r['tickers_added']) > 5 else ''}")
        print(f"  tickers removed: {r['tickers_removed'][:5]}{'...' if len(r['tickers_removed']) > 5 else ''}")
        print(f"  acceptance:")
        for k, v in r["acceptance"].items():
            mark = "✓" if v else "✗"
            print(f"    {mark} {k}: {v}")

    if args.out:
        args.out.write_text(json.dumps(results, indent=2))
        print(f"\nDetailed JSON: {args.out}")

    print(f"\n{'='*40}")
    print(f"OVERALL: {'PASS' if overall_pass else 'FAIL'}")
    sys.exit(0 if overall_pass else 1)


if __name__ == "__main__":
    main()
