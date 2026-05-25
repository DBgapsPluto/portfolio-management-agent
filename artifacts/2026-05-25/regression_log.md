# PR2b Regression Log

매 commit 직후 본 파일 에 entry 추가:
- Commit ID + message
- Unit test result (passed/failed count)
- Integration test result (passed/failed count)
- Δ from previous commit
- 0 new failure 검증

## Baseline (post PR2a merge / pre PR2b C0, 2026-05-25)

```
$ uv run python -m pytest tests/unit/ -q
2 failed, 787 passed, 7 warnings in 84.94s

$ uv run python -m pytest tests/integration/ -q
18 failed, 28 passed, 1 warning in 49.37s
```

Pre-existing fail (PR2a post-merge baseline):
- Unit: test_technical_analyst_returns_report, test_select_etf_candidates_populates_attribution
- Integration: test_eval_systemic_score (8 variants) + test_eval_regime_classifier (8 variants) + test_plan_pipeline_mock + test_5_28_dry_run

## Post-C0 (chore: scaffolding) — commit 75b8504

production code 변경 없음 (artifacts scaffolding only). Regression 영향 없음 — baseline 동일 유지.

Status: PASS. C1 진행 가능.

## Post-C1 (feat: validation utilities — benchmarks, regime, statistics)

```
$ uv run python -m pytest tests/unit/ -q
2 failed, 803 passed (baseline 787 + 16 new)

$ uv run python -m pytest tests/integration/ -q
18 failed, 28 passed (unchanged)
```

Δ: Unit +16 new pass (5 benchmark + 4 regime + 7 statistics). 0 new fail.

Note: test_regime 의 1차 fix (test data 가 의도와 반대), test_statistics 의
1차 fix (ttest_rel 의 identical-sequence NaN handling).

## Post-C2 (data: validation runner + execute, 5 strategies)

production code 변경 없음 (script + artifacts only). Regression 영향 없음.

**Validation 결과** (mean OOS Sharpe across 49 OOS samples):
- calibrated: 1.229 ← 1위
- 60_40_kr_tilted: 1.179 (Δ=+0.050, p=0.717, **NOT significant**)
- hand_coded_prior: 0.829 (Δ=+0.400, p=0.075)
- equal_weight: 0.818 (Δ=+0.411, p=0.060)
- risk_parity: 0.782 (Δ=+0.447, p=0.035 — **only statistically significant beat**)

NBER regime: OOS sample 의 recession N=2 (very small), Cohen's d 무의미.

Verdict: **PASS marginal** (1위지만 60-40 대비 차이 작고 not significant).

grill-me #1: **PASS with caveat** (user 결정) — INITIAL_BETA 유지, 60-40 caveat 기록.

## Post-C3 (data: sensitivity sweeps — era + robustness + sample_quality)

production code 변경 없음.

**Sensitivity 결과**:
- **Era split** (pre/post 2010-01-01): |β_pre - β_post|_avg = **0.036** (MODERATE
  DRIFT, threshold 0.03~0.06). Max single-entry diff = 0.16. β 가 era 의존성
  약간 보임 → 미래 era 에서 retrain 시 결과 달라질 가능성.
- **Robustness penalty** {0.10, 0.25, 0.50}: **SENSITIVE** — 0.25 (default)
  → best shrinkage=2.0, 0.50 → best=0.1 으로 dramatic 변화. PR2a 의 0.25
  default 선택이 결과에 결정적.
- **Sample quality**: 모든 sample 의 confidence = 0.7233 (baseline-fallback
  dominant) → quartile 분류 불가. PR2a 의 stage1_builder baseline-fallback
  policy 의 자연스러운 결과 (grill-me #2 PR2a 에서 인지).

**caveat 추가** (followup_issues.md Issue #18 업데이트):
1. (C2) 60-40 대비 not statistically significant (p=0.717)
2. (C3) β 가 era 의존 (moderate drift |β_pre - β_post|_avg = 0.036)
3. (C3) Best shrinkage 가 robustness penalty 계수에 sensitive
