# Limitations

Honest scope statement for this repository. Everything below is distilled from the
project's own audit trail — primarily the full-pipeline audit
([`docs/audits/pipeline-audit-2026-06-15.md`](docs/audits/pipeline-audit-2026-06-15.md)),
the 2026-08 methodology audit that drove the F1–F6 remediation commits, and the
empirical calibration record kept in the pre-reorganization issue log (preserved at
git tag `docs-archive-2026-08`, `docs/followup_issues.md` #31). Nothing here is
marketing hedging; these are the boundaries we actually measured.

## 1. What this project does NOT promise

- **No performance claims.** This is research code that was operated during a single
  3-month university investment competition (2026-06-01 → 2026-08-31). One market
  environment, one sample. No returns are advertised anywhere in this repository,
  deliberately.
- **Backtests are not simulated brokerage.** The backtest and dial-tuning harnesses
  score decisions on realized forward returns with simplified execution: no fee,
  slippage, or market-impact model, close-price fills only. A point-in-time honesty
  pass (2026-06-04, [`docs/design/2026-06-04-backtest-pit-honesty-design.md`](docs/design/2026-06-04-backtest-pit-honesty-design.md))
  removed look-ahead from news/fear-greed/market-risk inputs, but several backtest
  inputs remain proxy-grade rather than true historical vintages.
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
- **δ and τ are not real knobs.** With the prior built as Π = δΣw and the optimizer
  being max-quadratic-utility at the same δ, δ = 2.5 cancels in the round trip.
  τ = 0.05 is inert under the Idzorek confidence-based Ω construction. Both are kept
  for interface compatibility, not because tuning them does anything.
- **The optimizer runs on the prior Σ, not the posterior Σ_p.** Deliberate: using
  Σ_p breaks exact no-view recovery of the reference portfolio (the system's core
  invariant). The cost is that BL's view-uncertainty risk-widening is discarded.
- **The "turnover cap" is really an active-share budget.** The binding aggression
  governor is an L1 cap ‖w − w_prior‖₁ ≤ 0.50 (live dial; engine default 0.35),
  i.e. an active share of at most 25% versus the prior. It is a policy budget, not a
  trading-cost model.
- **Confidence scaling never reaches the regime baseline in live runs.** *c* uses
  Laplace-smoothed signal agreement; its live ceiling is ≈ 0.80, so the prior is
  always a strict mixture of neutral and regime baseline. Tests and calibration
  exercise c = 1.0, which live operation cannot produce.
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
- **Effectively one recession in-sample.** The bucket proxy history begins in the
  mid-2000s, so the common window contains a single recession regime (2020). Any
  regime-conditional parameter in this codebase is calibrated judgment, not a
  statistically estimated regime model.
- **The competition scored philosophy 70 / returns 30.** The system optimizes for
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
- Assorted schema/config debt: enum entries and dials for deleted optimizer paths
  still exist and are documented as inert.
