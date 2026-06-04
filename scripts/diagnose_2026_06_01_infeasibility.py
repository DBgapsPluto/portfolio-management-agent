"""Diagnose 2026-06-01 allocator: HRP path vs envelope/sector/mandate."""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingagents.agents.allocator.portfolio_allocator import (  # noqa: E402
    _build_sector_mapper_and_bounds,
    _hrp_per_bucket,
    _optimize_with_bucket_constraints,
)
from tradingagents.dataflows.universe import load_universe
from tradingagents.schemas.portfolio import BucketTarget, OptimizationMethod
from tradingagents.schemas.allocation_contract import BucketEnvelope
from tradingagents.skills.mandate.concentration_check import (
    RISK_BUCKET_NAMES,
    validate_concentration,
)
from tradingagents.skills.portfolio.contract_stage3 import realized_bucket_weights
from tradingagents.skills.portfolio.returns_matrix import fetch_returns_matrix
from tradingagents.skills.portfolio.sub_category import bucket_for_etf
from tradingagents.schemas.portfolio import CandidateSet, WeightVector

ARTIFACT = ROOT / "artifacts/2026-06-01/portfolio.json"
PRICE_LOOKBACK = 365 * 3


def _risk_ticker_sum(weights: dict[str, float], universe) -> float:
    etf_by = {e.ticker: e for e in universe.etfs}
    return sum(
        w for t, w in weights.items()
        if bucket_for_etf(etf_by[t]) in RISK_BUCKET_NAMES
    )


def _risk_bucket_sum(bucket_weights: dict[str, float]) -> float:
    return sum(bucket_weights.get(b, 0.0) for b in RISK_BUCKET_NAMES)


def main() -> None:
    data = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    attr = data["allocation_attribution"]
    cfg = attr["config"]
    buckets_attr = attr.get("buckets") or {}

    as_of = date.fromisoformat(data["as_of_date"])
    universe = load_universe(ROOT / "data/universe.json")

    # Rebuild bucket_to_tickers from attribution chosen lists
    bucket_to_tickers: dict[str, list[str]] = {}
    for b, ba in buckets_attr.items():
        if isinstance(ba, dict) and not ba.get("skipped"):
            bucket_to_tickers[b] = list(ba.get("chosen") or [])

    bt = data["bucket_target"]["weights"]
    bucket_target = BucketTarget(
        weights=bt,
        rationale=data["bucket_target"].get("rationale", ""),
        bond_tips_share=float(data["bucket_target"].get("bond_tips_share", 0.0)),
    )

    # Contract envelope from artifact
    ac_raw = (data.get("research_decision") or {}).get("allocation_contract") or {}
    envelope = {
        k: BucketEnvelope(lo=v["lo"], hi=v["hi"])
        for k, v in (ac_raw.get("envelope") or {}).items()
    }

    sub_category_lookup = {e.ticker: e.sub_category for e in universe.etfs}

    tickers = list({t for ts in bucket_to_tickers.values() for t in ts})
    candidates = CandidateSet(
        bucket_to_tickers=bucket_to_tickers,
        selection_criteria="reconstructed from artifact",
        total_candidates=max(len(tickers), 1),
    )
    start = as_of - timedelta(days=PRICE_LOOKBACK)
    returns = fetch_returns_matrix(tickers, start, as_of)
    if returns is None or returns.empty:
        print("ERROR: returns matrix empty")
        return

    print("=== Candidate gaps (target > 0, no ticker) ===")
    for b, target in bt.items():
        n = len(bucket_to_tickers.get(b, []))
        if target > 1e-6 and n == 0:
            print(f"  {b}: target={target:.4f}, chosen=0")

    print("\n=== Re-run HRP (attempt 0) ===")
    opt_attr: dict = {}
    wv0, _ = _optimize_with_bucket_constraints(
        OptimizationMethod.HRP,
        returns,
        candidates,
        bucket_target,
        {},
        attempts=0,
        sub_category_lookup=sub_category_lookup,
        attribution=opt_attr,
        bucket_envelope=envelope,
        cov_factor_proxy_blend=0.25,
        factor_panel=None,
    )
    realized0 = realized_bucket_weights(wv0.weights, bucket_to_tickers)
    print(f"  n_positions={len(wv0.weights)}, sum={sum(wv0.weights.values()):.6f}")
    print(f"  max_w={max(wv0.weights.values()):.4f}")
    print(f"  hrp_final_norm_intervened={opt_attr.get('hrp_final_norm_intervened')}")
    print(f"  risk ticker-level={_risk_ticker_sum(wv0.weights, universe):.4f}")
    print(f"  risk bucket rollup={_risk_bucket_sum(realized0):.4f}")
    conc = validate_concentration(wv0, universe)
    print(f"  validate_concentration passed={conc.passed}")
    for v in conc.violations:
        print(f"    - {v.rule}: {v.description}")

    print("\n=== Sector bounds (logged for HRP, NOT enforced in _hrp_per_bucket) ===")
    sm, lo, hi = _build_sector_mapper_and_bounds(
        candidates, bucket_target, 0, sub_category_lookup, bucket_envelope=envelope,
    )
    print("  sectors in mapper:", sorted(set(sm.values())))
    for sk in sorted(lo.keys()):
        print(f"    {sk}: target band [{lo[sk]:.4f}, {hi[sk]:.4f}]")

    print("\n=== Envelope vs HRP realized (attempt 0) ===")
    for b in sorted(bt.keys()):
        env = envelope.get(b)
        if not env:
            continue
        r = realized0.get(b, 0.0)
        ok = env.lo - 1e-9 <= r <= env.hi + 1e-9
        flag = "OK" if ok else "VIOL"
        print(f"  {b}: env [{env.lo:.4f},{env.hi:.4f}] realized {r:.4f} {flag}")

    for attempt in (0, 1):
        print(f"\n=== EF feasibility (envelope, attempt {attempt}) ===")
        opt_ef: dict = {}
        try:
            wv_ef, _ = _optimize_with_bucket_constraints(
                OptimizationMethod.MIN_VARIANCE,
                returns,
                candidates,
                bucket_target,
                {},
                attempts=attempt,
                sub_category_lookup=sub_category_lookup,
                attribution=opt_ef,
                bucket_envelope=envelope,
            )
            fb = opt_ef.get("optimization_fallback", "none")
            print(f"  returned n={len(wv_ef.weights)} method={wv_ef.method.value} fallback={fb}")
            if fb == "none":
                r0 = realized_bucket_weights(wv_ef.weights, bucket_to_tickers)
                print(f"  risk bucket={_risk_bucket_sum(r0):.4f} risk ticker={_risk_ticker_sum(wv_ef.weights, universe):.4f}")
        except Exception as e:
            print(f"  raised {type(e).__name__}: {e}")

    print("\n=== Artifact cross-check ===")
    align = attr.get("implementation_alignment") or {}
    art_realized = align.get("realized_bucket_weights") or {}
    print(f"  artifact realized risk bucket sum={_risk_bucket_sum(art_realized):.4f}")
    print(f"  artifact validation={data.get('validation_report')}")
    print(f"  final portfolio weights risk ticker={_risk_ticker_sum(data['weights'], universe):.4f}")


if __name__ == "__main__":
    main()
