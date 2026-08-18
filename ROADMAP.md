# Roadmap

Known unresolved items, pending decisions, and deferred work — the concrete list
behind [`LIMITATIONS.md`](LIMITATIONS.md) §4. These are recorded honestly rather
than promised: the project is competition-period research code, and some items
may never be picked up. Historical plans and specs that produced this list are
preserved at git tag `docs-archive-2026-08`.

## 1. Pending default flips

- **Full-universe correlation clustering ON.** Complete-linkage clustering at
  0.7 over the whole weight-eligible universe is implemented behind the
  `cluster_full_universe` dial (default OFF); measurement showed no cap
  violations on real holdings. Flipping the default is a pending decision.
  Prerequisite: align the daily repair loop from ×3 to ×12 iterations so
  dial-ON daily repairs converge like the allocator's repair loop does.

## 2. Legacy-path removal (BL plan "Phase D")

- Delete the legacy quadrant+tilt allocation path retained as the BL fallback —
  `project_to_band`, `apply_macro_modifiers`, the risk-tilt delta, and the
  volatility-haircut step — once the BL default has accumulated enough live
  history. Includes retiring the schema enums/dials that only that path uses
  (disclosed as inert in `LIMITATIONS.md` §4).

## 3. Methodology decisions (2026-08 audit "decide" tier)

Findings from the literature-grounded methodology audit that need an explicit
decision rather than a code fix:

- **Rank objective.** The competition pays on rank past a top-30 gate while the
  system optimizes absolute mean-variance utility. Preferred direction: report
  tracking error against a field proxy rather than change the objective
  (mandate caps already shrink the reachable active-risk set).
- **Reference-portfolio anchor check.** Sanity-check the hand-set quadrant
  baselines against an AUM-weighted Korean-ETF market anchor, and run a
  zero-parameter sign-agreement audit of the baseline matrix (no backtest
  fitting).
- **View-set construction.** Mean-removed per-bucket views can produce a
  rank-deficient view matrix and strain the diagonal-uncertainty independence
  assumption; collapsed overweight-vs-underweight basket views are the
  candidate redesign. Separately, deterministic FX/credit rule views can
  double-count LLM views on the same buckets — gate or attenuate.
- **Turnover convention.** The implementation's (buy+sell)/average-assets is 2×
  two common industry conventions. Pin down which convention the competition
  rulebook means, and report all three alongside the trade-notional metric.
- **Asynchronous US/KR return join.** Same-date joins of KR (15:30 KST closes)
  and US series bias cross-market correlations downward; lag the US leg one day
  or use weekly returns for the cross-block.
- **VIX overlay shape.** Replace the binary raw-level trigger with a time-decay
  unwind (~15 trading days) and/or percentile/z-score triggers.
- **Soft regime posterior.** A deterministic asymmetric quadrant posterior is
  available from the two per-axis agreement scores already computed for the
  confidence-scaled prior; mixing baselines by it would replace the hard
  quadrant label without touching the LLM.

## 4. Refactors

- Extract a shared `water_fill` helper — the logic is currently duplicated in
  four repair modules.
- Move `bucket_proxies` out of `backtest/` (it now serves the live Σ path).
- Split the oversized `trader_allocator` node closure.
- Unify the cluster-cap constant (three definition sites today).
- Honest per-bucket attribution status under the MQU fallback (currently still
  reports `bl`); report combine+MQU double failures distinctly.
- Remove the vestigial old-semantics sum-restore in `cluster_repair`.
- Guard the month-to-date block in the rebalance engine and make its JSON
  persistence atomic (currently a non-atomic double write).

## 5. Operations

- **Monthly turnover cadence.** Month-to-date turnover is tracked from
  persisted trade notionals with projected-shortfall alerts, but alert cadence
  and tier labeling need tuning — and meeting the ≥10% monthly floor remains a
  human operational responsibility, since the mock broker has no API and fills
  are reconciled from manually exported CSVs.

## 6. Universe hygiene

- **A329200 / A476800 tradability gap.** Two KR REIT tickers were registered by
  this project (beyond the organizer's 188-ETF list) to feed the B7 REIT
  price/signal path. They may sit outside the organizer's tradable set, and
  nothing in the selection path currently excludes them from allocation. See
  [`LIMITATIONS.md`](LIMITATIONS.md) §4.
