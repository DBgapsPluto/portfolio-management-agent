"""BL aggression-dial calibration backtest (gate-2 dial tuning).

Empirically calibrate the BL allocator's aggression dials — primarily
`turnover_cap` (the binding governor; live validation showed view-L1 pins at
exactly 0.35), secondarily `delta` and `base_spread`. Goal: find the value(s)
that MAXIMIZE the return-rank proxy (net-of-cost cumulative return) over a
recent window WITHOUT degenerate risk/drawdown.

What this calibrates vs. what it does NOT
------------------------------------------
The live system uses LLM relative-ranking views. For a PIT-reproducible backtest
we proxy the VIEW with a deterministic signal (trailing skip-1m bucket
momentum). This calibrates the DIAL's effect — how far a given view is allowed
to move the book — which is VIEW-SOURCE-AGNOSTIC: `turnover_cap` limits L1
movement from baseline regardless of whether the view came from an LLM or from
momentum. It does NOT claim momentum is the live alpha source; momentum is only
a stand-in to exercise the dial.

Simplifications (stated honestly)
---------------------------------
1. Prior baseline is a FIXED `QUADRANT_BASELINE["growth_disinflation"]` at every
   rebalance — the calibration is about the dial, not the regime model.
2. `growth_cap=0.30` / `defensive_cap=0.50` soft-clips are kept at PRODUCTION
   defaults (live behavior). At large `turnover_cap` the per-bucket soft-clip,
   not turnover, can become the binding constraint — that is itself a finding.
3. Cost = 10bps one-way × notional traded = 10bps × 0.5·L1(w_t, w_{t-1}).
4. Bucket-proxy native-currency returns (global=USD, KR=KRW) are used directly
   as the portfolio P&L (no FX overlay) — same proxy frame the live Σ uses.

PIT correctness: panels and Σ from data <= t only; next-month realized return is
strictly over (t, t+1month]. No look-ahead.

If the data fetch fails, prints "DATA UNAVAILABLE" and exits 0 (does NOT
fabricate). Single self-contained script with argparse + main().

Usage:
    python scripts/backtest_bl_calibration.py --as-of 2026-05-10 --window-days 1825
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

# .env auto-load (FRED/ECOS/KRX keys) — same pattern as backtest_bl_gate2.py.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
try:
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=_ROOT / ".env")
except ImportError:
    pass

from tradingagents.backtest.bucket_proxies import fetch_bucket_proxy_returns
from tradingagents.skills.portfolio.bl_engine import bl_allocate
from tradingagents.skills.portfolio.bucket_cov import bucket_covariance
from tradingagents.skills.portfolio.gaps_buckets import GROWTH_KEYS
from tradingagents.skills.portfolio.scenario_anchor import QUADRANT_BASELINE

# ── calibration constants ────────────────────────────────────────────────────
MANDATE_RISK = {"a5_gold_infl"} | set(GROWTH_KEYS)
BASELINE_QUADRANT = "growth_disinflation"

WARMUP_DAYS = 273            # 12m momentum lookback (skip-1m end) warm-up
MOM_LOOKBACK = 273           # [t-273, t-21] trailing window
MOM_SKIP = 21                # skip most-recent ~1m (avoid 1m reversal)
COV_TAIL = 504               # ~2y of daily obs for Σ
COST_BPS = 10.0              # one-way trading cost in bps
TRADING_DAYS = 252

# turnover_cap sweep (primary dial). 1.00 ≈ uncapped (L1 max is 2.0).
TURNOVER_SWEEP = [0.15, 0.25, 0.35, 0.50, 0.70, 1.00]
# secondary sweeps (run at best turnover_cap)
BASE_SPREAD_SWEEP = [0.02, 0.04, 0.06, 0.08]
DELTA_SWEEP = [1.5, 2.5, 4.0]

# momentum-quantile → tier buckets: top3 strong_OW, next3 OW, mid2 neutral,
# next3 UW, bottom3 strong_UW (14 buckets total).
_TIER_ORDER = (
    ["strong_OW"] * 3 + ["OW"] * 3 + ["neutral"] * 2 + ["UW"] * 3 + ["strong_UW"] * 3
)
FIXED_CONVICTION = 0.8


def _month_ends(idx: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """Trading-day month-end timestamps present in the index (last obs per month)."""
    s = pd.Series(idx, index=idx)
    grp = s.groupby([idx.year, idx.month]).max()
    return sorted(grp.tolist())


def _momentum_ranking(returns: pd.DataFrame, t: pd.Timestamp) -> dict[str, tuple[str, float]]:
    """Deterministic PIT view: trailing skip-1m momentum → 14-bucket tier ranking.

    Momentum_b = cumulative return over [t-MOM_LOOKBACK, t-MOM_SKIP] (data <= t).
    Buckets ranked high→low momentum, assigned tiers per _TIER_ORDER. Conviction
    fixed at FIXED_CONVICTION. Buckets with no momentum (all-NaN window) → neutral.
    """
    end = t - pd.Timedelta(days=MOM_SKIP)
    start = t - pd.Timedelta(days=MOM_LOOKBACK)
    window = returns.loc[(returns.index > start) & (returns.index <= end)]
    # cumulative compounded return per bucket over the window (skip empty cols)
    mom: dict[str, float] = {}
    for c in returns.columns:
        col = window[c].dropna()
        if len(col) >= 20:  # need a meaningful window
            mom[c] = float((1.0 + col).prod() - 1.0)
    if len(mom) < 14:
        # if any bucket lacks momentum, those go neutral; rank the rest
        ranked = sorted(mom, key=lambda b: mom[b], reverse=True)
        # build a 14-length tier list only over ranked buckets, others neutral
        ranking: dict[str, tuple[str, float]] = {}
        tiers = _tiers_for_n(len(ranked))
        for b, tier in zip(ranked, tiers):
            if tier != "neutral":
                ranking[b] = (tier, FIXED_CONVICTION)
        return ranking
    ranked = sorted(mom, key=lambda b: mom[b], reverse=True)
    ranking = {}
    for b, tier in zip(ranked, _TIER_ORDER):
        if tier != "neutral":
            ranking[b] = (tier, FIXED_CONVICTION)
    return ranking


def _tiers_for_n(n: int) -> list[str]:
    """Tier assignment for n ranked buckets (proportional thirds, OW/UW extremes)."""
    if n <= 0:
        return []
    k = max(1, n // 5)
    tiers = (
        ["strong_OW"] * k + ["OW"] * k
        + ["neutral"] * (n - 4 * k)
        + ["UW"] * k + ["strong_UW"] * k
    )
    # truncate/pad to exactly n
    return (tiers + ["neutral"] * n)[:n]


def _next_month_return(returns: pd.DataFrame, t: pd.Timestamp, t1: pd.Timestamp,
                       w: pd.Series) -> float:
    """Portfolio return strictly over (t, t1] given weights w (held over window).

    Per-bucket compounded return over (t, t1], then w-weighted (buckets with no
    data contribute their proxy 0 — conservative). NO look-ahead: window > t.
    """
    fwd = returns.loc[(returns.index > t) & (returns.index <= t1)]
    if fwd.empty:
        return 0.0
    bucket_ret = {}
    for c in returns.columns:
        col = fwd[c].dropna()
        bucket_ret[c] = float((1.0 + col).prod() - 1.0) if len(col) else 0.0
    br = pd.Series(bucket_ret).reindex(w.index).fillna(0.0)
    return float((w * br).sum())


def _turnover_cost(w_t: pd.Series, w_prev: pd.Series) -> tuple[float, float]:
    """(L1 distance, one-way cost). cost = COST_BPS bps × 0.5·L1."""
    idx = w_t.index.union(w_prev.index)
    l1 = float((w_t.reindex(idx).fillna(0.0) - w_prev.reindex(idx).fillna(0.0)).abs().sum())
    cost = (COST_BPS / 1e4) * 0.5 * l1
    return l1, cost


def _max_drawdown(equity: np.ndarray) -> float:
    """Max drawdown of an equity curve (fraction, negative)."""
    if len(equity) == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    dd = equity / peak - 1.0
    return float(dd.min())


def _annualized_sharpe(monthly_rets: list[float]) -> float:
    """Annualized Sharpe from monthly net returns (rf=0). 0 if degenerate."""
    if len(monthly_rets) < 2:
        return 0.0
    r = np.asarray(monthly_rets, dtype=float)
    sd = r.std(ddof=1)
    if sd < 1e-12:
        return 0.0
    return float(r.mean() / sd * np.sqrt(12.0))


def _run_strategy(returns: pd.DataFrame, rebals: list[pd.Timestamp], baseline: pd.Series,
                  *, ranking_fn, turnover_cap: float, delta: float, base_spread: float,
                  pinned: list) -> dict:
    """Run one monthly-rebalance strategy. Returns metrics dict.

    ranking_fn(t) -> ranking dict (or {} for the baseline strategy).
    """
    monthly_rets: list[float] = []
    turnovers: list[float] = []
    equity = [1.0]
    w_prev = baseline.copy()  # start from baseline (first rebalance trades into book)
    for i in range(len(rebals) - 1):
        t, t1 = rebals[i], rebals[i + 1]
        # Σ from data <= t only (PIT)
        panel = returns.loc[returns.index <= t].tail(COV_TAIL)
        Sigma, _meta = bucket_covariance(panel, min_obs=252)
        ranking = ranking_fn(t)
        if Sigma is None or Sigma.empty:
            w = baseline.copy()  # degraded → hold baseline
        else:
            res = bl_allocate(
                Sigma, baseline, ranking, pinned=pinned,
                delta=delta, base_spread=base_spread,
                growth_keys=set(GROWTH_KEYS), mandate_risk_keys=MANDATE_RISK,
                turnover_cap=turnover_cap,
            )
            w = res["weights"].reindex(baseline.index).fillna(0.0)
        # realized next-month return (t, t1], then charge turnover cost
        gross = _next_month_return(returns, t, t1, w)
        l1, cost = _turnover_cost(w, w_prev)
        net = gross - cost
        monthly_rets.append(net)
        turnovers.append(0.5 * l1)  # one-way notional turnover
        equity.append(equity[-1] * (1.0 + net))
        w_prev = w
    eq = np.asarray(equity)
    return {
        "cum_return": float(eq[-1] - 1.0),
        "sharpe": _annualized_sharpe(monthly_rets),
        "mdd": _max_drawdown(eq),
        "avg_turnover": float(np.mean(turnovers)) if turnovers else 0.0,
        "n_months": len(monthly_rets),
        "equity": eq,
    }


def _fetch_returns(as_of: date, window_days: int) -> pd.DataFrame | None:
    """Fetch the 14-bucket proxy returns frame. None on failure/empty."""
    try:
        rets = fetch_bucket_proxy_returns(as_of, window_days=window_days)
    except Exception as e:  # noqa: BLE001
        print(f"DATA UNAVAILABLE — fetch raised {e!r}")
        return None
    if rets is None or rets.empty:
        print("DATA UNAVAILABLE — empty proxy returns frame")
        return None
    rets = rets.sort_index()
    rets = rets[~rets.index.duplicated(keep="last")]
    return rets


def _usable_rebalances(returns: pd.DataFrame) -> list[pd.Timestamp]:
    """Month-end rebalance dates after the warm-up window."""
    first = returns.index.min()
    warm_cutoff = first + pd.Timedelta(days=WARMUP_DAYS)
    me = _month_ends(returns.index)
    return [t for t in me if t >= warm_cutoff]


def _fmt_pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="BL aggression-dial calibration backtest")
    parser.add_argument("--as-of", default="2026-05-10", help="ISO date — proxy window endpoint")
    parser.add_argument("--window-days", type=int, default=1825, help="proxy fetch window (~5y)")
    args = parser.parse_args(argv)

    as_of = date.fromisoformat(args.as_of)
    print("=== BL aggression-dial calibration backtest ===")
    print(f"as_of={as_of}  window_days={args.window_days}")
    print(f"baseline quadrant: {BASELINE_QUADRANT} (FIXED — calibrates dial, not regime)")
    print(f"view proxy: trailing skip-1m momentum [t-{MOM_LOOKBACK}, t-{MOM_SKIP}], "
          f"conviction={FIXED_CONVICTION}")
    print(f"mandate_risk ({len(MANDATE_RISK)}): {sorted(MANDATE_RISK)}")
    print(f"cost: {COST_BPS:.0f}bps one-way × 0.5·L1   |   Σ tail: {COV_TAIL}d   "
          f"warm-up: {WARMUP_DAYS}d")

    returns = _fetch_returns(as_of, args.window_days)
    if returns is None:
        return 0

    n_cols = returns.shape[1]
    nonempty = [c for c in returns.columns if returns[c].notna().any()]
    print(f"\nproxy frame: {returns.shape[0]} rows × {n_cols} cols  "
          f"({len(nonempty)}/{n_cols} buckets have data)")
    print(f"date range: {returns.index.min().date()} → {returns.index.max().date()}")

    rebals = _usable_rebalances(returns)
    if len(rebals) < 6:
        print(f"DATA UNAVAILABLE — only {len(rebals)} usable month-ends after warm-up")
        return 0

    baseline = pd.Series(QUADRANT_BASELINE[BASELINE_QUADRANT], dtype=float)
    baseline = baseline.reindex(returns.columns).fillna(0.0)
    # buckets with no proxy data are pinned to baseline (matches live cov pinning)
    pinned = [c for c in returns.columns if not returns[c].notna().any()]

    print(f"usable rebalances: {len(rebals)}  "
          f"({rebals[0].date()} → {rebals[-1].date()})  "
          f"pinned(no-data) buckets: {pinned or 'none'}")

    # spot-check Σ obs count at last rebalance for transparency
    last_panel = returns.loc[returns.index <= rebals[-2]].tail(COV_TAIL)
    _Sig, _cm = bucket_covariance(last_panel, min_obs=252)
    print(f"Σ@last n_obs={_cm.get('n_obs')}  pinned={_cm.get('pinned')}")

    # ── baseline (no-view) strategy ──────────────────────────────────────────
    base_metrics = _run_strategy(
        returns, rebals, baseline, ranking_fn=lambda t: {},
        turnover_cap=0.35, delta=2.5, base_spread=0.04, pinned=pinned,
    )

    # ── primary: turnover_cap sweep (delta=2.5, base_spread=0.04 fixed) ───────
    print("\n" + "=" * 78)
    print("PRIMARY SWEEP — turnover_cap  (delta=2.5, base_spread=0.04, momentum view)")
    print("=" * 78)
    header = f"{'turnover_cap':>13} {'cum_return':>12} {'sharpe':>8} {'maxDD':>9} {'avg_turn':>9}"
    print(header)
    print("-" * len(header))

    results: dict[float, dict] = {}
    for cap in TURNOVER_SWEEP:
        m = _run_strategy(
            returns, rebals, baseline,
            ranking_fn=lambda t: _momentum_ranking(returns, t),
            turnover_cap=cap, delta=2.5, base_spread=0.04, pinned=pinned,
        )
        results[cap] = m
        tag = " (uncapped)" if cap >= 1.0 else ""
        print(f"{cap:>13.2f} {_fmt_pct(m['cum_return']):>12} {m['sharpe']:>8.2f} "
              f"{_fmt_pct(m['mdd']):>9} {m['avg_turnover']:>9.3f}{tag}")

    print("-" * len(header))
    print(f"{'BASELINE':>13} {_fmt_pct(base_metrics['cum_return']):>12} "
          f"{base_metrics['sharpe']:>8.2f} {_fmt_pct(base_metrics['mdd']):>9} "
          f"{base_metrics['avg_turnover']:>9.3f}  (ranking={{}}; stays at prior)")

    # ── pick sweet spot ──────────────────────────────────────────────────────
    # The peak (max cum_return) is informative but often at the uncapped end; the
    # SWEET SPOT is the "knee" — the smallest cap that captures ~all the return
    # before the marginal return per extra unit of cap collapses. We detect the
    # knee as the first cap whose step-up to the NEXT cap adds < KNEE_FRAC of the
    # largest single step's gain (i.e. diminishing returns kick in).
    best_cap = max(results, key=lambda c: results[c]["cum_return"])
    best = results[best_cap]
    caps_sorted = sorted(results)
    steps = [(caps_sorted[i], caps_sorted[i + 1],
              results[caps_sorted[i + 1]]["cum_return"] - results[caps_sorted[i]]["cum_return"])
             for i in range(len(caps_sorted) - 1)]
    max_step = max((g for _, _, g in steps), default=0.0)
    KNEE_FRAC = 0.25  # next step adds < 25% of the biggest step's gain → flattened
    knee_cap = best_cap
    for lo, _hi, gain in steps:
        if max_step > 0 and gain < KNEE_FRAC * max_step:
            knee_cap = lo  # stop here — beyond lo, gains diminish
            break
    knee = results[knee_cap]
    # MDD/turnover degradation past the knee
    past = [c for c in caps_sorted if c > knee_cap]
    mdd_note = ""
    if past:
        worst_past_mdd = min(results[c]["mdd"] for c in past)
        if worst_past_mdd < knee["mdd"] - 0.005:
            mdd_note = (f"  NOTE: pushing cap past {knee_cap:.2f} worsens maxDD "
                        f"(to {_fmt_pct(worst_past_mdd)} vs {_fmt_pct(knee['mdd'])}) "
                        f"and ~doubles turnover for marginal return.")

    print("\n" + "=" * 78)
    print("RECOMMENDATION")
    print("=" * 78)
    print(f"  max cum_return at turnover_cap={best_cap:.2f}: "
          f"{_fmt_pct(best['cum_return'])}  sharpe={best['sharpe']:.2f}  "
          f"maxDD={_fmt_pct(best['mdd'])}  avg_turn={best['avg_turnover']:.3f}")
    if knee_cap < best_cap:
        print(f"  returns FLATTEN past turnover_cap={knee_cap:.2f} "
              f"({_fmt_pct(knee['cum_return'])}, sharpe={knee['sharpe']:.2f}, "
              f"maxDD={_fmt_pct(knee['mdd'])}): the {knee_cap:.2f}→{best_cap:.2f} "
              f"steps add only {_fmt_pct(best['cum_return'] - knee['cum_return'])} "
              f"while turnover rises {knee['avg_turnover']:.3f}→{best['avg_turnover']:.3f}.")
        print(f"  → SWEET SPOT: turnover_cap≈{knee_cap:.2f} "
              f"(captures ~all the return at materially lower turnover/risk).")
    else:
        print(f"  → SWEET SPOT: turnover_cap≈{best_cap:.2f} "
              f"(return still rising at the top of the sweep — no degradation seen).")
    if mdd_note:
        print(mdd_note)
    vs_base = best["cum_return"] - base_metrics["cum_return"]
    print(f"  best vs BASELINE: {_fmt_pct(vs_base)} cum-return edge "
          f"({'momentum view helps' if vs_base > 0 else 'view does NOT beat baseline'}).")

    # ── secondary: base_spread & delta sweep at the sweet-spot (knee) cap ─────
    sec_cap = knee_cap  # tune second-order at the sweet-spot cap
    print("\n" + "=" * 78)
    print(f"SECONDARY SWEEP — base_spread (delta=2.5) at turnover_cap={sec_cap:.2f}")
    print("=" * 78)
    print(f"{'base_spread':>12} {'cum_return':>12} {'sharpe':>8} {'maxDD':>9} {'avg_turn':>9}")
    for bs in BASE_SPREAD_SWEEP:
        m = _run_strategy(
            returns, rebals, baseline,
            ranking_fn=lambda t: _momentum_ranking(returns, t),
            turnover_cap=sec_cap, delta=2.5, base_spread=bs, pinned=pinned,
        )
        print(f"{bs:>12.2f} {_fmt_pct(m['cum_return']):>12} {m['sharpe']:>8.2f} "
              f"{_fmt_pct(m['mdd']):>9} {m['avg_turnover']:>9.3f}")

    print("\n" + "=" * 78)
    print(f"SECONDARY SWEEP — delta (base_spread=0.04) at turnover_cap={sec_cap:.2f}")
    print("=" * 78)
    print(f"{'delta':>12} {'cum_return':>12} {'sharpe':>8} {'maxDD':>9} {'avg_turn':>9}")
    for dl in DELTA_SWEEP:
        m = _run_strategy(
            returns, rebals, baseline,
            ranking_fn=lambda t: _momentum_ranking(returns, t),
            turnover_cap=sec_cap, delta=dl, base_spread=0.04, pinned=pinned,
        )
        print(f"{dl:>12.2f} {_fmt_pct(m['cum_return']):>12} {m['sharpe']:>8.2f} "
              f"{_fmt_pct(m['mdd']):>9} {m['avg_turnover']:>9.3f}")

    print("\n=== DONE ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
