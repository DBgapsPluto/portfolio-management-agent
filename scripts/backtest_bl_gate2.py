"""BL Phase B — gate-2 go/no-go sanity check (Phase B STOP gate).

Pure sanity on the BL engine with FIXED views and DEFAULT dials. NO LLM, NO
lightweight-backtest harness. If gate-2 fails, BL Phase C (LLM views) must NOT
proceed.

The six sanity checks (ⓐ-ⓕ), all on `bl_allocate` with default dials
(δ=2.5, base_spread=0.04, turnover_cap=0.35):

  ⓐ a_direction        — a fixed OW/UW view moves the right buckets the right way.
  ⓑ b_not_inert        — that view actually moves the portfolio (L1 ≥ eps_min).
  ⓒ c_no_blowup        — no bucket exceeds max(growth_cap, defensive_cap).
  ⓓ d_no_view_recovers — ranking={} exactly recovers the baseline (L1 < 1e-6).
  ⓔ e_no_false_trip    — a defensive (mandate-risk) OW is reflected, not rejected.
  ⓕ f_risk_within_cap  — an aggressive growth view keeps risk-proxy ≤ 0.70.

Pure functions take Σ / baseline directly so they are unit-testable without
network. `__main__` fetches REAL Σ via bucket_proxies + bucket_covariance and
runs the live gate over all 4 QUADRANT_BASELINE quadrants. If Σ is unavailable
it prints "DATA UNAVAILABLE" and exits 0 (does NOT fabricate data).

Usage:
    python scripts/backtest_bl_gate2.py --as-of 2026-05-10
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

# .env auto-load (FRED/ECOS/KRX keys) — same pattern as other backtest scripts.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
try:
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=_ROOT / ".env")
except ImportError:
    pass

from tradingagents.skills.portfolio.bl_engine import bl_allocate

# Fixed test view for ⓐⓑⓒ: OW global-tech (growth), UW US-rates (defensive).
# b3 must end ABOVE baseline, a3 BELOW baseline (relative-view direction).
_DIRECTION_RANKING = {
    "b3_global_tech": ("strong_OW", 0.9),
    "a3_us_rates": ("strong_UW", 0.9),
}
# Fixed defensive OW for ⓔ — a mandate-risk-EXCLUDED defensive bucket that the
# engine must NOT falsely reject to baseline ("false trip" = full_fallback or
# a3 not lifted above baseline).
_DEFENSIVE_RANKING = {"a3_us_rates": ("strong_OW", 0.95)}
# Fixed aggressive growth view for ⓕ — push the three biggest equity-risk
# buckets hard; the engine's mandate cap must keep risk-proxy ≤ 0.70.
_AGGRESSIVE_GROWTH_RANKING = {
    "b3_global_tech": ("strong_OW", 0.95),
    "b2_dm_core": ("strong_OW", 0.95),
    "b1_kr_equity": ("strong_OW", 0.95),
}

RISK_FRAC_CAP = 0.70


def _l1(a: pd.Series, b: pd.Series) -> float:
    """L1 distance ||a − b||₁ over the union of indices (missing → 0)."""
    idx = a.index.union(b.index)
    return float((a.reindex(idx).fillna(0.0) - b.reindex(idx).fillna(0.0)).abs().sum())


def _allocate(Sigma, baseline, ranking, *, growth_keys, mandate_risk_keys,
              delta, base_spread, growth_cap, defensive_cap, turnover_cap):
    """Thin wrapper returning (weights: pd.Series, global_status: str)."""
    res = bl_allocate(
        Sigma, baseline, ranking,
        delta=delta, base_spread=base_spread,
        growth_keys=set(growth_keys), mandate_risk_keys=set(mandate_risk_keys),
        growth_cap=growth_cap, defensive_cap=defensive_cap, turnover_cap=turnover_cap,
    )
    w = res["weights"]
    status = res.get("meta", {}).get("__global__", {}).get("status", "unknown")
    return w, status


def gate2_checks(Sigma, baseline, *, growth_keys, mandate_risk_keys,
                 delta=2.5, base_spread=0.04, growth_cap=0.30, defensive_cap=0.50,
                 turnover_cap=0.35, eps_min=0.05) -> dict:
    """Core sanity ⓐⓑⓒⓓ on a single (Σ, baseline). Pure — no network.

    Returns bools d_no_view_recovers, a_direction, b_not_inert, c_no_blowup and
    numeric l1_no_view, l1_view, max_bucket.
    """
    baseline = pd.Series(baseline, dtype=float)

    # ⓓ no-view exactly recovers baseline (MATH-1 invariant).
    w_noview, _ = _allocate(
        Sigma, baseline, {}, growth_keys=growth_keys, mandate_risk_keys=mandate_risk_keys,
        delta=delta, base_spread=base_spread, growth_cap=growth_cap,
        defensive_cap=defensive_cap, turnover_cap=turnover_cap)
    l1_no_view = _l1(w_noview, baseline)
    d_no_view_recovers = l1_no_view < 1e-6

    # ⓐⓑⓒ fixed OW/UW view.
    w_view, _ = _allocate(
        Sigma, baseline, _DIRECTION_RANKING, growth_keys=growth_keys,
        mandate_risk_keys=mandate_risk_keys, delta=delta, base_spread=base_spread,
        growth_cap=growth_cap, defensive_cap=defensive_cap, turnover_cap=turnover_cap)
    l1_view = _l1(w_view, baseline)

    b3_base = float(baseline.get("b3_global_tech", 0.0))
    a3_base = float(baseline.get("a3_us_rates", 0.0))
    b3_w = float(w_view.get("b3_global_tech", 0.0))
    a3_w = float(w_view.get("a3_us_rates", 0.0))
    a_direction = (b3_w > b3_base + 1e-9) and (a3_w < a3_base - 1e-9)

    b_not_inert = l1_view >= eps_min

    max_bucket = float(w_view.max())
    ceiling = max(growth_cap, defensive_cap) + 1e-9
    c_no_blowup = max_bucket <= ceiling

    return {
        "d_no_view_recovers": bool(d_no_view_recovers),
        "a_direction": bool(a_direction),
        "b_not_inert": bool(b_not_inert),
        "c_no_blowup": bool(c_no_blowup),
        "l1_no_view": l1_no_view,
        "l1_view": l1_view,
        "max_bucket": max_bucket,
    }


def gate2_defensive_false_trip(Sigma, baseline, *, growth_keys, mandate_risk_keys,
                               delta=2.5, base_spread=0.04, growth_cap=0.30,
                               defensive_cap=0.50, turnover_cap=0.35) -> dict:
    """ⓔ defensive OW must be REFLECTED, not falsely rejected to baseline.

    ranking={a3_us_rates strong_OW@0.95}. e_no_false_trip = (status !=
    full_fallback) AND (a3 weight > baseline a3).
    """
    baseline = pd.Series(baseline, dtype=float)
    a3_base = float(baseline.get("a3_us_rates", 0.0))
    w, status = _allocate(
        Sigma, baseline, _DEFENSIVE_RANKING, growth_keys=growth_keys,
        mandate_risk_keys=mandate_risk_keys, delta=delta, base_spread=base_spread,
        growth_cap=growth_cap, defensive_cap=defensive_cap, turnover_cap=turnover_cap)
    a3 = float(w.get("a3_us_rates", 0.0))
    e_no_false_trip = (status != "full_fallback") and (a3 > a3_base + 1e-9)
    return {"e_no_false_trip": bool(e_no_false_trip), "a3": a3}


def gate2_realized_risk(Sigma, baseline, *, growth_keys, mandate_risk_keys,
                        delta=2.5, base_spread=0.04, growth_cap=0.30,
                        defensive_cap=0.50, turnover_cap=0.35) -> dict:
    """ⓕ aggressive growth view must keep realized risk-proxy ≤ 0.70.

    risk_frac = Σ weights over mandate_risk_keys.
    """
    baseline = pd.Series(baseline, dtype=float)
    w, _ = _allocate(
        Sigma, baseline, _AGGRESSIVE_GROWTH_RANKING, growth_keys=growth_keys,
        mandate_risk_keys=mandate_risk_keys, delta=delta, base_spread=base_spread,
        growth_cap=growth_cap, defensive_cap=defensive_cap, turnover_cap=turnover_cap)
    risk_frac = float(sum(float(w.get(b, 0.0)) for b in mandate_risk_keys))
    f_risk_within_cap = risk_frac <= RISK_FRAC_CAP + 1e-6
    return {"f_risk_within_cap": bool(f_risk_within_cap), "risk_frac": risk_frac}


# ───────────────────────────── live gate (__main__) ─────────────────────────


def _fetch_sigma(as_of: date):
    """Fetch real Σ. Returns (Sigma, cov_meta) or (None, reason)."""
    try:
        from tradingagents.backtest.bucket_proxies import fetch_bucket_proxy_returns
        from tradingagents.skills.portfolio.bucket_cov import bucket_covariance

        rets = fetch_bucket_proxy_returns(as_of)
        if rets is None or rets.empty:
            return None, "empty proxy returns"
        Sigma, cov_meta = bucket_covariance(rets)
        if Sigma is None or Sigma.empty:
            return None, f"empty Sigma (cov_meta={cov_meta})"
        return Sigma, cov_meta
    except Exception as e:  # noqa: BLE001
        return None, f"fetch failed: {e!r}"


def _bool_mark(v: bool) -> str:
    return "PASS" if v else "FAIL"


def _run_quadrant(Sigma, quadrant, baseline, *, growth_keys, mandate_risk_keys,
                  delta, base_spread, turnover_cap):
    """Run ⓐ-ⓕ on one quadrant. Returns (all_pass, detail_dict)."""
    base = pd.Series(baseline, dtype=float)
    common = dict(growth_keys=growth_keys, mandate_risk_keys=mandate_risk_keys,
                  delta=delta, base_spread=base_spread, turnover_cap=turnover_cap)
    core = gate2_checks(Sigma, base, **common)
    defe = gate2_defensive_false_trip(Sigma, base, **common)
    risk = gate2_realized_risk(Sigma, base, **common)
    checks = {
        "a_direction": core["a_direction"],
        "b_not_inert": core["b_not_inert"],
        "c_no_blowup": core["c_no_blowup"],
        "d_no_view_recovers": core["d_no_view_recovers"],
        "e_no_false_trip": defe["e_no_false_trip"],
        "f_risk_within_cap": risk["f_risk_within_cap"],
    }
    all_pass = all(checks.values())
    detail = {**checks, **core, **defe, **risk}
    return all_pass, detail


def _base_spread_sweep(Sigma, baselines, *, growth_keys, mandate_risk_keys,
                       delta, turnover_cap):
    """Non-blocking sweep — for each base_spread, max single-view L1 and max bucket
    across all quadrants. Helps a human pick the largest spread under the ceiling."""
    rows = []
    for bs in (0.02, 0.04, 0.06, 0.08):
        max_l1 = 0.0
        max_bucket = 0.0
        for quadrant, baseline in baselines.items():
            base = pd.Series(baseline, dtype=float)
            rep = gate2_checks(Sigma, base, growth_keys=growth_keys,
                               mandate_risk_keys=mandate_risk_keys, delta=delta,
                               base_spread=bs, turnover_cap=turnover_cap)
            max_l1 = max(max_l1, rep["l1_view"])
            max_bucket = max(max_bucket, rep["max_bucket"])
        rows.append((bs, max_l1, max_bucket))
    return rows


def main(argv=None) -> int:
    from tradingagents.skills.portfolio.gaps_buckets import GROWTH_KEYS
    from tradingagents.skills.portfolio.scenario_anchor import QUADRANT_BASELINE

    parser = argparse.ArgumentParser(description="BL gate-2 sanity STOP gate")
    parser.add_argument("--as-of", default="2026-05-10", help="ISO date for Σ window endpoint")
    parser.add_argument("--delta", type=float, default=2.5)
    parser.add_argument("--base-spread", type=float, default=0.04)
    parser.add_argument("--turnover-cap", type=float, default=0.35)
    args = parser.parse_args(argv)

    growth_keys = set(GROWTH_KEYS)
    mandate_risk_keys = {"a5_gold_infl"} | set(GROWTH_KEYS)

    print(f"=== BL gate-2 sanity STOP gate (as_of={args.as_of}) ===")
    print(f"dials: δ={args.delta}  base_spread={args.base_spread}  "
          f"turnover_cap={args.turnover_cap}")
    print(f"mandate_risk set ({len(mandate_risk_keys)}): {sorted(mandate_risk_keys)}")

    as_of = date.fromisoformat(args.as_of)
    Sigma, cov_meta = _fetch_sigma(as_of)
    if Sigma is None:
        print(f"\nDATA UNAVAILABLE — {cov_meta}")
        print("(gate-2 can still be evaluated on synthetic Σ via the unit tests)")
        return 0

    pinned = (cov_meta or {}).get("pinned") if isinstance(cov_meta, dict) else None
    n_obs = (cov_meta or {}).get("n_obs") if isinstance(cov_meta, dict) else None
    print(f"Σ: {Sigma.shape[0]} buckets  n_obs={n_obs}  pinned={pinned}")
    if Sigma.shape[0] < 14:
        print(f"  NOTE: Σ has {Sigma.shape[0]}/14 buckets (some proxies pinned); "
              f"gate still runs but some view buckets may be pinned to baseline.")

    header = f"{'quadrant':<24} {'ⓐdir':>6} {'ⓑmov':>6} {'ⓒcap':>6} {'ⓓrec':>6} {'ⓔdef':>6} {'ⓕrsk':>6}  {'verdict':>8}"
    print("\n" + header)
    print("-" * len(header))

    overall_pass = True
    numeric_rows = []
    for quadrant in QUADRANT_BASELINE:
        baseline = QUADRANT_BASELINE[quadrant]
        all_pass, d = _run_quadrant(
            Sigma, quadrant, baseline, growth_keys=growth_keys,
            mandate_risk_keys=mandate_risk_keys, delta=args.delta,
            base_spread=args.base_spread, turnover_cap=args.turnover_cap)
        overall_pass = overall_pass and all_pass
        print(f"{quadrant:<24} "
              f"{_bool_mark(d['a_direction']):>6} {_bool_mark(d['b_not_inert']):>6} "
              f"{_bool_mark(d['c_no_blowup']):>6} {_bool_mark(d['d_no_view_recovers']):>6} "
              f"{_bool_mark(d['e_no_false_trip']):>6} {_bool_mark(d['f_risk_within_cap']):>6}  "
              f"{('PASS' if all_pass else 'FAIL'):>8}")
        numeric_rows.append((quadrant, d))

    print("\n--- numerics (per quadrant) ---")
    print(f"{'quadrant':<24} {'l1_noview':>10} {'l1_view':>9} {'maxbkt':>8} "
          f"{'a3(ⓔ)':>8} {'riskfr(ⓕ)':>10}")
    for quadrant, d in numeric_rows:
        print(f"{quadrant:<24} {d['l1_no_view']:>10.2e} {d['l1_view']:>9.4f} "
              f"{d['max_bucket']:>8.4f} {d['a3']:>8.4f} {d['risk_frac']:>10.4f}")

    print("\n--- base_spread sweep (non-blocking) ---")
    print(f"{'base_spread':>11} {'max_l1':>9} {'max_bucket':>11}")
    for bs, max_l1, max_bucket in _base_spread_sweep(
            Sigma, QUADRANT_BASELINE, growth_keys=growth_keys,
            mandate_risk_keys=mandate_risk_keys, delta=args.delta,
            turnover_cap=args.turnover_cap):
        print(f"{bs:>11.2f} {max_l1:>9.4f} {max_bucket:>11.4f}")

    verdict = "PASS" if overall_pass else "FAIL"
    print(f"\n=== OVERALL GATE-2 VERDICT: {verdict} ===")
    print("(PASS = ⓐⓑⓒⓓⓔⓕ all true for all 4 quadrants)")
    if not overall_pass:
        print("STOP: gate-2 FAILED — BL Phase C (LLM views) must NOT proceed.")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
