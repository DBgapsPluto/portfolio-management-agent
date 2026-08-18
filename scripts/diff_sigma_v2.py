"""WP-F F-3 — old-vs-new Σ diff artifact for the user review gate.

Reads the pre-WP-A baseline (artifacts/sigma_v2_baseline.json, Task A0: old
daily/native Σ) and recomputes, with CURRENT code (Σ v2: KRW numeraire + W-FRI
weekly), Σ + bl_allocate weights on the SAME dates with the SAME dials. Emits
per-bucket weight deltas, pinned-list change, risk-proxy sum change, and Σ
diagonal/correlation shifts. Output: artifacts/sigma_v2_diff.json.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

from backtest_bl_gate2 import _DIRECTION_RANKING, _allocate, _fetch_sigma  # noqa: E402
from tradingagents.skills.portfolio.gaps_buckets import GROWTH_KEYS  # noqa: E402
from tradingagents.skills.portfolio.scenario_anchor import QUADRANT_BASELINE  # noqa: E402

# Same dials as capture_sigma_baseline.py — diff must be Σ-only, not dial-driven.
DIALS = dict(delta=2.5, base_spread=0.04, growth_cap=0.30, defensive_cap=0.50,
             turnover_cap=0.35)


def _risk_frac(w: dict[str, float], risk_keys: set[str]) -> float:
    return float(sum(float(w.get(b, 0.0)) for b in risk_keys))


def main() -> int:
    baseline_path = _ROOT / "artifacts" / "sigma_v2_baseline.json"
    old = json.loads(baseline_path.read_text(encoding="utf-8"))
    growth_keys = set(GROWTH_KEYS)
    mandate_risk_keys = {"a5_gold_infl"} | growth_keys

    out: dict = {
        "note": "old (pre-WP-A daily/native) vs new (KRW + W-FRI weekly) Sigma diff",
        "baseline_artifact": baseline_path.name,
        "dials": DIALS,
        "days": {},
    }
    for day_iso, old_day in old["days"].items():
        as_of = date.fromisoformat(day_iso)
        Sigma, cov_meta = _fetch_sigma(as_of)
        if Sigma is None:
            print(f"{day_iso}: DATA UNAVAILABLE — {cov_meta}")
            return 1
        d = pd.Series(Sigma.values.diagonal(), index=Sigma.columns)
        corr = Sigma.div(d.pow(0.5), axis=0).div(d.pow(0.5), axis=1)

        old_diag = old_day["sigma_diag"]
        diag_diff = {
            b: {
                "old": old_diag.get(b),
                "new": (float(d[b]) if b in d.index else None),
                "ratio": (float(d[b]) / old_diag[b]
                          if b in d.index and old_diag.get(b) else None),
            }
            for b in sorted(set(old_diag) | set(d.index))
        }

        old_corr = old_day["corr"]
        pair_deltas = []
        for r in corr.index:
            for c in corr.columns:
                if r >= c:  # upper triangle only
                    continue
                o = old_corr.get(r, {}).get(c)
                if o is None:
                    continue
                pair_deltas.append((r, c, float(corr.loc[r, c]) - o))
        abs_d = [abs(x) for _, _, x in pair_deltas]
        pair_deltas.sort(key=lambda t: -abs(t[2]))
        corr_shift = {
            "n_pairs": len(pair_deltas),
            "mean_abs_delta": (sum(abs_d) / len(abs_d)) if abs_d else None,
            "max_abs_delta": max(abs_d) if abs_d else None,
            "top_changes": [
                {"pair": [r, c], "old": old_corr[r][c],
                 "new": round(old_corr[r][c] + dx, 6), "delta": round(dx, 6)}
                for r, c, dx in pair_deltas[:10]
            ],
        }

        weights_diff: dict = {}
        risk_frac: dict = {}
        l1_shift: dict = {}
        for quadrant, baseline in QUADRANT_BASELINE.items():
            base = pd.Series(baseline, dtype=float)
            w_nv, _ = _allocate(Sigma, base, {}, growth_keys=growth_keys,
                                mandate_risk_keys=mandate_risk_keys, **DIALS)
            w_dir, _ = _allocate(Sigma, base, _DIRECTION_RANKING, growth_keys=growth_keys,
                                 mandate_risk_keys=mandate_risk_keys, **DIALS)
            weights_diff[quadrant] = {}
            risk_frac[quadrant] = {}
            l1_shift[quadrant] = {}
            for view, w_new in (("no_view", w_nv), ("direction_view", w_dir)):
                w_old = old_day["weights"][quadrant][view]
                buckets = sorted(set(w_old) | set(w_new.index))
                weights_diff[quadrant][view] = {
                    b: {
                        "old": w_old.get(b, 0.0),
                        "new": round(float(w_new.get(b, 0.0)), 6),
                        "delta": round(float(w_new.get(b, 0.0)) - w_old.get(b, 0.0), 6),
                    }
                    for b in buckets
                }
                rf_old = _risk_frac(w_old, mandate_risk_keys)
                rf_new = _risk_frac(dict(w_new), mandate_risk_keys)
                risk_frac[quadrant][view] = {
                    "old": round(rf_old, 6), "new": round(rf_new, 6),
                    "delta": round(rf_new - rf_old, 6),
                }
                l1_shift[quadrant][view] = round(sum(
                    abs(v["delta"]) for v in weights_diff[quadrant][view].values()), 6)

        out["days"][day_iso] = {
            "cov_meta": {
                "old": old_day["cov_meta"],
                "new": {k: cov_meta.get(k) for k in ("pinned", "n_obs", "shrinkage")},
            },
            "pinned_change": {"old": old_day["cov_meta"].get("pinned", []),
                              "new": cov_meta.get("pinned", [])},
            "sigma_diag": diag_diff,
            "corr_shift": corr_shift,
            "weights": weights_diff,
            "risk_frac": risk_frac,
            "l1_weight_shift": l1_shift,
        }

        # human-readable summary
        print(f"\n=== {day_iso} ===")
        print(f"n_obs: {old_day['cov_meta']['n_obs']} (daily) -> "
              f"{cov_meta.get('n_obs')} (weekly)   "
              f"pinned: {old_day['cov_meta'].get('pinned')} -> {cov_meta.get('pinned')}   "
              f"shrinkage: {old_day['cov_meta']['shrinkage']:.4f} -> "
              f"{cov_meta.get('shrinkage'):.4f}")
        print(f"{'bucket':<24} {'diag old':>10} {'diag new':>10} {'ratio':>7}")
        for b, v in diag_diff.items():
            if v["old"] is None or v["new"] is None:
                print(f"{b:<24} {'—':>10} {'—':>10} {'—':>7}")
                continue
            print(f"{b:<24} {v['old']:>10.6f} {v['new']:>10.6f} {v['ratio']:>7.2f}")
        print(f"corr: mean|Δ|={corr_shift['mean_abs_delta']:.4f}  "
              f"max|Δ|={corr_shift['max_abs_delta']:.4f} "
              f"({corr_shift['top_changes'][0]['pair']})")
        print(f"{'quadrant':<24} {'view':<15} {'L1(w)':>7} {'riskfr old':>11} "
              f"{'riskfr new':>11}")
        for q in weights_diff:
            for view in ("no_view", "direction_view"):
                rf = risk_frac[q][view]
                print(f"{q:<24} {view:<15} {l1_shift[q][view]:>7.4f} "
                      f"{rf['old']:>11.4f} {rf['new']:>11.4f}")

    dest = _ROOT / "artifacts" / "sigma_v2_diff.json"
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
