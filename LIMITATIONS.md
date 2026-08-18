# Limitations

Honest scope statement for this repository. Everything below is distilled from the
project's own audit trail — primarily the full-pipeline audit
([`docs/audits/pipeline-audit-2026-06-15.md`](docs/audits/pipeline-audit-2026-06-15.md)),
the 2026-08 methodology audit that drove the F1–F6 remediation commits, and the
empirical calibration record kept in the pre-reorganization issue log (preserved at
git tag `docs-archive-2026-08`, `docs/followup_issues.md` #31). Nothing here is
marketing hedging; these are the boundaries we actually measured or declared.

## 1. What this project does NOT promise

- **No performance claims.** This is research code operated during a single
  3-month university investment competition (2026-06-01 → 2026-08-31, still
  running as of 2026-08-18). One market environment, one sample. No returns
  are advertised anywhere in this repository, deliberately.
- **Backtests are not simulated brokerage.** All harnesses score decisions on
  realized forward returns with close-price fills; no slippage, market-impact, or
  fill model exists in any backtest harness (realized slippage from broker CSVs is
  tracked separately by the live cost monitor).
  - Transaction-cost scope: a flat 10 bps one-way turnover charge in the
    BL-calibration and ETF-selection backtests
    (`scripts/backtest_bl_calibration.py`, `scripts/backtest_etf_selection.py`) —
    the same sweep that set the live dials — and no cost model at all in the
    dial-tuning forward scorer (`tradingagents/backtest/forward_perf.py`) or the
    gate harnesses (`scripts/run_backtest.py`, `scripts/backtest_bl_gate2.py`).
  - A point-in-time honesty pass (2026-06-04,
    [`docs/design/2026-06-04-backtest-pit-honesty-design.md`](docs/design/2026-06-04-backtest-pit-honesty-design.md))
    removed look-ahead from news/fear-greed/market-risk inputs, but several
    backtest inputs remain proxy-grade rather than true historical vintages.
- **Execution reconciliation was manual.** The competition's mock HTS/MTS broker has
  no API; realized fills were reconciled from manually exported CSVs. The pipeline's
  "realized" state is only as fresh as that manual step.
- **LLM outputs vary.** Stage-1/2 narratives and the relative-ranking views are LLM
  calls. The deterministic layers (mandate validation, repair, turnover checks) bound
  the damage, but run-to-run variation in wording and view tiers is expected.

## 2. Methodology disclosures

Named honestly, because reviewers of quantitative code should not have to discover
these from the source:

- **This is not canonical Black-Litterman.** The prior is a hand-set
  **regime-conditional reference portfolio** (quadrant baseline interpolated toward a
  neutral portfolio by a deterministic signal-agreement score *c*), not an
  equilibrium market-cap-implied Π. The accurate description of the allocator is
  *"regime-conditional reference portfolio + BL view-tilting engine."* The largest
  implicit view — the recession baseline's defensive posture — enters through the
  prior and therefore bypasses the Ω (view-uncertainty) discipline.
- **τ is inert; δ is pinned, not tuned.** Under the Idzorek confidence-based Ω
  construction (Ω ∝ τ·PΣPᵀ), τ cancels exactly in the posterior-mean algebra, so
  τ = 0.05 does nothing. δ cancels exactly only in the no-view round trip (the
  prior Π = δΣw recovers the reference portfolio at any δ); once views exist, only
  the ratio base_spread/δ is identified, so δ is fixed at 2.5 and view aggression
  is tuned through base_spread alone (see
  [`docs/design/2026-06-20-bl-allocator-design.md`](docs/design/2026-06-20-bl-allocator-design.md)).
- **The optimizer runs on the prior Σ, not the posterior Σ_p.** Deliberate: using
  Σ_p breaks exact no-view recovery of the reference portfolio (the system's core
  invariant). The cost is that BL's view-uncertainty risk-widening is discarded.
- **The "turnover cap" is really an active-share budget.** The binding aggression
  governor is an L1 cap ‖w − w_prior‖₁ ≤ 0.50 live (engine default 0.35), i.e. at
  most 25% active share versus the prior on the live dial. It is a policy budget,
  not a trading-cost model.
- **Computed confidence never reaches the regime baseline.** *c* is
  Laplace-smoothed signal agreement, (k+1)/(n+2) per axis; with at most 9 growth
  and 5 inflation votes its computed ceiling is (10/11)·(6/7) ≈ 0.78, so whenever
  *c* is actually computed the prior is a strict mixture of neutral and regime
  baseline. c = 1.0 is reachable live only on the fallback path: if the regime
  object is missing or leaves `signal_confidence` unset, the allocator defaults to
  1.0 — the pre-confidence baseline prior.
- **Σ is a declared choice, not an estimated optimum.** Weekly (W-FRI) returns over
  a 104-week window, KRW-numeraire bucket proxies (unhedged buckets composited with
  USDKRW; hedged ≈ local), Ledoit-Wolf shrinkage; buckets with fewer than 52 weekly
  observations are pinned to the reference weight. These windows and conventions are
  disclosed so results can be reproduced — they were chosen for robustness, not fit.

## 3. What the data could and could not support

The empirical record is the strongest argument for the system's design honesty:

- **A factor-timing edge could not be established.** The earlier factor-model stack
  was calibrated and walk-forward tested to conclusion (2026-06-01): the all-bucket
  ETF return panel supports only 75 quarters (proxy inception 2006), the designed
  walk-forward protocol was infeasible at that sample size, and the out-of-sample
  comparison against a 60/40 benchmark was not statistically significant (p = 0.49;
  an earlier 5-bucket calibration gave p = 0.717). The recorded verdict:

  > "The competition edge must come from elsewhere (philosophy score, risk
  > discipline …), not from a statistically-unsupportable factor-timing claim."

  That stack was subsequently deleted (2026-06-03). The current system deliberately
  anchors on a hand-set reference portfolio plus deterministic risk discipline
  instead of claiming a validated timing edge.
- **Regime-conditional parameters are calibrated judgment, not estimation.** The
  quadrant baselines and regime dials are hand-set economic priors; the panel above
  yielded 0 walk-forward folds at the intended train size, so no regime model was
  ever statistically fit.
- **The competition scores philosophy 70 / returns 30.** The system optimizes for
  coherent, auditable, mandate-compliant allocation — that objective shaped the
  architecture at least as much as return-seeking did.

## 4. Known unresolved items

Tracked in [`ROADMAP.md`](ROADMAP.md). Highlights:

- The legacy quadrant+tilt allocation path (including the volatility-haircut step)
  is retained as a fallback; its removal (BL plan "Phase D") is pending.
- Full-universe correlation clustering and the daily-repair cadence alignment are
  implemented behind a dial that defaults OFF; flipping the default is a pending
  decision.
- The monthly ≥10% turnover floor is tracked month-to-date with alerts, but meeting
  it remains an operational (human) responsibility.
- The shipped `data/universe.json` holds 190 entries: the organizer's 188-entry
  list plus two KR REIT tickers (A329200, A476800) this project registered to
  feed the B7 REIT price/signal path
  ([`docs/design/2026-06-09-stage1-bucket-data-foldins-design.md`](docs/design/2026-06-09-stage1-bucket-data-foldins-design.md) §5.5).
  Those two may sit outside the organizer's tradable set, and nothing in the
  selection path excludes them from allocation.
- Assorted schema/config debt: enum entries and dials for deleted optimizer paths
  still exist and are disclosed here as inert.
