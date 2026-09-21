"""WP-A A0 — pre-change Σ baseline artifact for the WP-F F-3 diff gate.

Captures, at current HEAD (old daily/native Σ), for the 2 most recent business
days: Σ diagonal + correlation + cov_meta, and bl_allocate bucket weights per
quadrant (no-view + gate-2 direction view, default dials). Reuses gate-2's
`_fetch_sigma`. Output: artifacts/sigma_v2_baseline.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

from backtest_bl_gate2 import _DIRECTION_RANKING, _allocate, _fetch_sigma  # noqa: E402
from tradingagents.skills.portfolio.gaps_buckets import GROWTH_KEYS  # noqa: E402
from tradingagents.skills.portfolio.scenario_anchor import QUADRANT_BASELINE  # noqa: E402

DIALS = dict(delta=2.5, base_spread=0.04, growth_cap=0.30, defensive_cap=0.50,
             turnover_cap=0.35)


def main() -> int:
    growth_keys = set(GROWTH_KEYS)
    mandate_risk_keys = {"a5_gold_infl"} | growth_keys
    out: dict = {"note": "pre-WP-A (daily/native) Sigma baseline", "days": {}}
    for ts in pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=2):
        as_of = ts.date()
        Sigma, cov_meta = _fetch_sigma(as_of)
        if Sigma is None:
            print(f"{as_of}: DATA UNAVAILABLE — {cov_meta}")
            return 1
        d = pd.Series(pd.Series(Sigma.values.diagonal(), index=Sigma.columns))
        corr = Sigma.div(d.pow(0.5), axis=0).div(d.pow(0.5), axis=1)
        day: dict = {
            "cov_meta": {k: cov_meta.get(k) for k in ("pinned", "n_obs", "shrinkage")},
            "sigma_diag": {k: float(v) for k, v in d.items()},
            "corr": {r: {c: round(float(corr.loc[r, c]), 6) for c in corr.columns}
                     for r in corr.index},
            "weights": {},
        }
        for quadrant, baseline in QUADRANT_BASELINE.items():
            base = pd.Series(baseline, dtype=float)
            w_nv, _ = _allocate(Sigma, base, {}, growth_keys=growth_keys,
                                mandate_risk_keys=mandate_risk_keys, **DIALS)
            w_dir, _ = _allocate(Sigma, base, _DIRECTION_RANKING, growth_keys=growth_keys,
                                 mandate_risk_keys=mandate_risk_keys, **DIALS)
            day["weights"][quadrant] = {
                "no_view": {k: round(float(v), 6) for k, v in w_nv.items()},
                "direction_view": {k: round(float(v), 6) for k, v in w_dir.items()},
            }
        out["days"][as_of.isoformat()] = day
        print(f"{as_of}: Σ {Sigma.shape[0]} buckets n_obs={cov_meta.get('n_obs')} "
              f"pinned={cov_meta.get('pinned')}")
    dest = _ROOT / "artifacts" / "sigma_v2_baseline.json"
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
