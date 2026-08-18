"""WP-D D0-1 — full-universe clustering measurement gate (F5 decision inputs).

Measurement only — NO allocation-code change. On the full universe (last 252
trading days, >=126d history required — mirrors the planned D1-1 filter), the
cluster distribution under three variants:
    average-linkage @0.7 (current production), average @0.8, complete @0.7.
Each variant is then applied to the 2 most recent artifact portfolios' actual
holdings (artifacts/<date>/portfolio.json weights): held-member cluster weight
vs the 0.35 cluster cap — the "cap on held-member sum" semantics of D0-2.

Output: artifacts/cluster_universe_measurement.json + compact table on stdout.
Linkage extension is local per plan D0-1 (skills/ untouched at this stage);
an average-linkage parity assertion against find_correlation_clusters guards
against divergence from production.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from tradingagents.dataflows.universe import load_universe  # noqa: E402
from tradingagents.default_config import DEFAULT_CONFIG  # noqa: E402
from tradingagents.skills.mandate.correlation_check import (  # noqa: E402
    DEFAULT_CLUSTER_CAP, FLOAT_TOLERANCE,
)
from tradingagents.skills.technical.correlation_cluster import (  # noqa: E402
    find_correlation_clusters,
)
from tradingagents.skills.technical.price_batch import fetch_etf_price_batch  # noqa: E402

logger = logging.getLogger(__name__)

WINDOW_DAYS: int = 252        # production tail (technical_analyst.py:206)
MIN_HISTORY_DAYS: int = 126   # planned D1-1 MIN_CLUSTER_HISTORY_DAYS — mirrored
FETCH_BUFFER_DAYS: int = 420  # calendar buffer so tail(252) is fully covered
VARIANTS: list[tuple[str, float]] = [
    ("average", 0.7), ("average", 0.8), ("complete", 0.7),
]
_DATE_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _cluster_members(
    returns: pd.DataFrame, threshold: float, method: str,
    min_periods: int | None,
) -> list[tuple[list[str], float]]:
    """find_correlation_clusters clone + {linkage method, corr min_periods}.

    min_periods guards short pairwise overlaps in the full-universe frame
    (insufficient overlap -> NaN -> 0 corr, same fill as production).
    Returns [(members, avg_internal_corr)] for clusters with >=2 members.
    """
    corr = returns.corr(min_periods=min_periods).fillna(0.0)
    distance = 1 - corr.values
    np.fill_diagonal(distance, 0)
    n = distance.shape[0]
    if n < 2:
        return []
    cond = distance[np.triu_indices(n, k=1)]
    Z = linkage(cond, method=method)
    labels = fcluster(Z, t=1 - threshold, criterion="distance")
    out: list[tuple[list[str], float]] = []
    for cid in set(labels):
        idx = [i for i, l in enumerate(labels) if l == cid]
        if len(idx) < 2:
            continue
        members = [returns.columns[i] for i in idx]
        sub = corr.iloc[idx, idx]
        avg = float((sub.values.sum() - len(idx)) / (len(idx) ** 2 - len(idx)))
        out.append((members, avg))
    return out


def _assert_parity_with_skill(returns: pd.DataFrame) -> None:
    """The local clone must reproduce production find_correlation_clusters
    exactly on a dense frame (average linkage, no min_periods)."""
    dense = returns.dropna(axis=1, how="any")
    ours = {frozenset(m) for m, _ in _cluster_members(dense, 0.7, "average", None)}
    skill = {frozenset(c.members) for c in find_correlation_clusters(dense, threshold=0.7)}
    assert ours == skill, "local clone diverged from find_correlation_clusters"


def _load_recent_portfolios(k: int) -> list[tuple[str, dict[str, float]]]:
    """k most recent artifacts/<YYYY-MM-DD>/portfolio.json, newest first."""
    dirs = sorted(
        p for p in (_ROOT / "artifacts").iterdir()
        if p.is_dir() and _DATE_DIR.match(p.name) and (p / "portfolio.json").exists()
    )
    out = []
    for p in reversed(dirs[-k:]):
        payload = json.loads((p / "portfolio.json").read_text(encoding="utf-8"))
        out.append((p.name, {t: float(w) for t, w in payload["weights"].items()}))
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    ap.add_argument("--cache", default=DEFAULT_CONFIG["etf_price_cache_path"])
    args = ap.parse_args()

    uni = load_universe(Path(DEFAULT_CONFIG.get("universe_path", "./data/universe.json")))
    tickers = [e.ticker for e in uni.etfs]
    names = {e.ticker: e.name for e in uni.etfs}
    buckets = {e.ticker: e.gaps_bucket for e in uni.etfs}

    start = args.as_of - timedelta(days=FETCH_BUFFER_DAYS)
    prices = fetch_etf_price_batch(tickers, start, args.as_of, cache_path=args.cache)
    if prices.empty:
        print("DATA UNAVAILABLE — no prices fetched")
        return 1

    # Production mirror (technical_analyst.py:205-207), then the planned D1-1
    # eligibility filter instead of production's top-tier dropna(how="any").
    pivot = prices.pivot(index="date", columns="ticker", values="close")
    returns = pivot.pct_change().dropna(how="all").tail(WINDOW_DAYS)
    eligible = returns.loc[:, returns.notna().sum() >= MIN_HISTORY_DAYS]
    eligible = eligible.loc[:, eligible.std() > 0]   # flat series break corr/avg_corr
    excluded = sorted(set(returns.columns) - set(eligible.columns))

    _assert_parity_with_skill(eligible)
    portfolios = _load_recent_portfolios(2)

    result: dict = {
        "note": "WP-D D0-1 measurement gate — F5 decision inputs (no code change)",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": args.as_of.isoformat(),
        "window_days": WINDOW_DAYS,
        "min_history_days": MIN_HISTORY_DAYS,
        "cluster_cap": DEFAULT_CLUSTER_CAP,
        "universe_size": len(tickers),
        "n_priced": int(returns.shape[1]),
        "n_eligible": int(eligible.shape[1]),
        "excluded_insufficient_history": excluded,
        "portfolio_dates": [d for d, _ in portfolios],
        "variants": {},
    }

    rows = []
    for method, thr in VARIANTS:
        key = f"{method}@{thr:g}"
        clusters = _cluster_members(eligible, thr, method, MIN_HISTORY_DAYS)
        clusters.sort(key=lambda c: -len(c[0]))
        sizes = [len(m) for m, _ in clusters]
        n_clustered = sum(sizes)
        big_members, big_avg = clusters[0] if clusters else ([], 0.0)
        bucket_hist: dict[str, int] = {}
        for t in big_members:
            b = buckets.get(t) or "unclassified"
            bucket_hist[b] = bucket_hist.get(b, 0) + 1
        variant_out: dict = {
            "n_clusters": len(clusters),
            "max_cluster_size": max(sizes, default=0),
            "n_tickers_clustered": n_clustered,
            "pct_universe_clustered": round(n_clustered / eligible.shape[1], 4),
            "cluster_sizes_desc": sizes,
            "largest_cluster": {
                "size": len(big_members),
                "avg_internal_correlation": round(big_avg, 4),
                "bucket_histogram": dict(sorted(bucket_hist.items(), key=lambda kv: -kv[1])),
                "members": [{"ticker": t, "name": names.get(t, "")} for t in big_members],
            },
            "portfolios": {},
        }
        row = {"variant": key, "n_clusters": len(clusters),
               "max_size": max(sizes, default=0),
               "pct_univ": round(100 * n_clustered / eligible.shape[1], 1)}
        for pdate, weights in portfolios:
            held_rows = []
            for members, avg in clusters:
                held = {t: weights[t] for t in members if t in weights}
                hw = sum(held.values())
                if hw <= 0:
                    continue
                held_rows.append({
                    "cluster_size": len(members),
                    "avg_corr": round(avg, 4),
                    "held_weight": round(hw, 6),
                    "violates_cap": bool(hw > DEFAULT_CLUSTER_CAP + FLOAT_TOLERANCE),
                    "held_members": {
                        f"{t} {names.get(t, '')}": round(w, 6)
                        for t, w in sorted(held.items(), key=lambda kv: -kv[1])
                    },
                })
            held_rows.sort(key=lambda r: -r["held_weight"])
            max_held = held_rows[0]["held_weight"] if held_rows else 0.0
            n_viol = sum(r["violates_cap"] for r in held_rows)
            variant_out["portfolios"][pdate] = {
                "max_held_cluster_weight": max_held,
                "cap_violated": bool(n_viol),
                "n_violating_clusters": n_viol,
                "held_weight_in_clusters": round(sum(r["held_weight"] for r in held_rows), 6),
                "top_held_clusters": held_rows[:5],
            }
            row[pdate] = f"{max_held:.3f}{' VIOL' if n_viol else ''}"
        result["variants"][key] = variant_out
        rows.append(row)

    dest = _ROOT / "artifacts" / "cluster_universe_measurement.json"
    dest.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    pcols = [d for d, _ in portfolios]
    print(f"\nuniverse={len(tickers)} priced={returns.shape[1]} eligible={eligible.shape[1]} "
          f"(>= {MIN_HISTORY_DAYS}d of last {WINDOW_DAYS}d), cap={DEFAULT_CLUSTER_CAP}")
    hdr = f"{'variant':<14}{'n_clust':>8}{'max_size':>9}{'%univ':>7}" + "".join(
        f"{'held@' + d:>18}" for d in pcols)
    print(hdr)
    print("-" * len(hdr))
    for row in rows:
        line = (f"{row['variant']:<14}{row['n_clusters']:>8}{row['max_size']:>9}"
                f"{row['pct_univ']:>7}")
        line += "".join(f"{row[d]:>18}" for d in pcols)
        print(line)
    print(f"\nwrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
