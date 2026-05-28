# PR2b Validation Report (2026-05-25)

## Executive Summary

Calibrated (PR2a) mean OOS Sharpe = **1.229**. Best non-calibrated benchmark = **60_40_kr_tilted** (1.179). Δ = +0.050. Verdict: **PASS**.

## Section 1: Benchmark Comparison (Full Period)

| Strategy | Mean OOS Sharpe | Std OOS | Full-period Sharpe | Max DD | vs Calibrated p | Cohen's d | N |
|---|---|---|---|---|---|---|---|
| calibrated | 1.229 | 1.437 | 0.825 | -0.092 | — | — | — |
| hand_coded_prior | 0.829 | 0.910 | 0.720 | -0.098 | 0.075 | +0.070 | 49 |
| 60_40_kr_tilted | 1.179 | 1.078 | 0.901 | -0.145 | 0.717 | -0.059 | 49 |
| equal_weight | 0.818 | 1.515 | 0.614 | -0.074 | 0.060 | +0.111 | 49 |
| risk_parity | 0.782 | 1.365 | 0.593 | -0.076 | 0.035 | +0.124 | 49 |

## Section 2: NBER Regime Decomposition

OOS samples: total **49**, expansion **47**, recession **2**.

| Strategy | Expansion Sharpe | Recession Sharpe | Spread |
|---|---|---|---|
| calibrated | +0.779 (N=47) | +2.039 (N=2) | -1.260 |
| hand_coded_prior | +0.715 (N=47) | +0.759 (N=2) | -0.044 |
| 60_40_kr_tilted | +0.821 (N=47) | +2.560 (N=2) | -1.738 |
| equal_weight | +0.519 (N=47) | +3.607 (N=2) | -3.088 |
| risk_parity | +0.512 (N=47) | +2.965 (N=2) | -2.453 |

## Section 3: Drawdown Analysis

| Strategy | Max DD | Peak idx | Trough idx | Recovery idx | Duration (Q) |
|---|---|---|---|---|---|
| calibrated | -0.092 | 44 | 45 | — | 1 |
| hand_coded_prior | -0.098 | 44 | 45 | — | 1 |
| 60_40_kr_tilted | -0.145 | 41 | 45 | — | 4 |
| equal_weight | -0.074 | 33 | 34 | 35 | 1 |
| risk_parity | -0.076 | 44 | 45 | 47 | 1 |

## Section 4: Deferred

- 24_cell_legacy: 24-cell legacy 는 macro_q DataFrame reconstruction 이 필요 (별도 PR 또는 task).

## Section 5: Conclusion

PR2a calibrated 가 marginally 우월 (Δ=+0.050).
