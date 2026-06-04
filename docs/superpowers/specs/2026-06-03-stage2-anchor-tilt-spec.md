# Stage 2 Anchor + Tilt Spec (2026-06-03)

Resolved design for grill-me: **scenario owns bucket body**; **covenant anchor** adds layer-0 regime modifiers on non-risk buckets; **factor tilt** only on top. Stage 3 HRP within buckets unchanged.

## Grill-me decisions (2026-06-04)

| ID | Decision | Implementation |
|----|----------|----------------|
| **A8** | Scenario owns body | `anchor_scenario_pure(scenario)` from `SCENARIO_BUCKET_ANCHORS`; `anchor_covenant` = capped pure + regime modifiers (not 45/55 blend). |
| **M3** | Regime modifiers layer 0 | `apply_regime_modifiers`: non-risk buckets only; Δ = clamp(regime[b]−scenario[b], ±`stage2_regime_modifier_pp`); renormalize; audit `regime_modifiers_pp`, `layer=0`. |
| **D0+D1** | Scenario real caps | `apply_scenario_real_caps` before modifiers: goldilocks precious+cyclical ≤ `stage2_scenario_real_cap_goldilocks_pc` (0.14); overheating/stagflation cyclical ≤ 12%. |
| **C2** | Covenant in safety_diag | `anchor_scenario_pure`, `anchor_covenant`, `stage2_mode: anchor_covenant_tilt`; covenant passed to `apply_anchor_tilt_model_with_safety`. |
| **G2+T2** | Thesis gates | `thesis_tags(regime, scenario)`; `apply_thesis_gates_to_tilt` zeros precious/cyclical tilt under `goldilocks_narrative`. |
| **B1** | Drift budgets (diag only) | `drift_covenant_to_tilt_pp`, `drift_tilt_to_confidence_pp`, `drift_confidence_to_llm_pp` in `safety_diagnostics` — no hard cumulative cap. |
| **P1+P3** | Covenant ledger | `render_execution_trace` → `## Covenant Ledger`; warning if \|feasible−covenant\| > 5pp. |
| **Philosophy** | Risk label | Allocator realized risk (pre-validator); optional post-risk-judge clip line. |

**Superseded:** `0.45 × regime + 0.55 × scenario` body blend (`blend_bucket_anchors` now wraps `compose_anchor_covenant`). Legacy weights still used for **TIPS** scalar blend only.

## Decisions (tilt + caps)

| Topic | Decision | Rationale |
|-------|----------|-----------|
| ~~Anchor blend~~ | ~~45/55~~ → covenant composition | See grill table A8/M3. |
| Tilt magnitude | `TILT_BETA = 0.25 × INITIAL_BETA`, cap `±2.5pp` per (factor, bucket) | Full β path built ~30% real assets under GI+goldilocks; tilt must nudge anchor, not rebuild buckets. |
| Cyclical cap | Regime `growth_inflation` cyclical ≤ 10%; scenario overheating/stagflation ≤ 12% | db_gaps universe: only 4 cyclical ETFs — anchoring cyclical > ~12% concentrates Stage 3. |
| Precious cap (goldilocks) | precious + cyclical ≤ 14% on scenario pure (was 16% on raw table) | Stricter grill cap before modifiers. |
| QP fallback | `INITIAL_BASELINE` on optimizer failure only | Unchanged; anchor invalid → legacy `apply_factor_model_with_safety`. |
| Config keys | `stage2_anchor_tilt_enabled`, `stage2_regime_modifier_pp`, `stage2_scenario_real_cap_goldilocks_pc`, TIPS blend weights | Kill-switch + tune caps/modifiers without code change. |

## Anchor numbers (reference)

**goldilocks scenario** (risk ≈ 0.55): kr_eq 15%, global_eq 28%, precious 5%, cyclical 7%, kr_bond 12%, credit 12%, global_duration 10%, cash 11%.

**growth_inflation regime** (risk ≈ 0.52): kr_eq 12%, global_eq 22%, precious 8%, cyclical 10%, kr_bond 10%, credit 8%, global_duration 8%, cash 22%.

**Blend** `GI + goldilocks` @ 45/55: risk ≈ 0.54, precious+cyclical ≈ 12% (not ~30% real assets).

## Universe constraints (db_gaps)

- `cyclical_commodity_fx`: 4 names — cap anchor cyclical unless stagflation/overheating dominates.
- `precious_metals`: 3 names (gold-heavy) — keep goldilocks precious low; Stage 3 HRP still applies within bucket.

## Implementation map

- `tradingagents/skills/research/bucket_anchors.py` — `compose_anchor_covenant`, `apply_regime_modifiers`, `thesis_tags`
- `tradingagents/skills/research/factor_to_bucket.py` — `apply_factor_tilt`, `apply_thesis_gates_to_tilt`, `apply_anchor_tilt_model_with_safety`
- `tradingagents/agents/managers/research_manager.py` — covenant anchor + drift diagnostics
- `tradingagents/reports/execution_trace.py` — Covenant Ledger (P1+P3)
- `tradingagents/default_config.py` — config defaults

## Open follow-ups

- Calibrate `stage2_regime_modifier_pp` from backtest.
- Optional: dynamic cyclical cap from investability `n_selectable` in allocation contract.
- TIPS anchor blend remains 45/55 scalar; bond bucket split still uses `bond_tips_share` in Stage 3.
