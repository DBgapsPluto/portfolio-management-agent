# PR2b Validation — Decisions Log

본 파일은 spec `2026-05-25-stage2b-validation-design.md` 의 section 0 결정 외부화.
2 grill-me 결정 본 파일에 append.

## Brainstorming 결정 (확정 — 2026-05-25)

- Q1 Final goal: Full PR2b scope (benchmark + validation + sensitivity + regen)
- Q2 Regime classifier: NBER recession (FRED USREC), 2-state (expansion / recession)
- Q3 Sensitivity sweeps: Full (era split pre/post-2010 + robustness penalty {0.10, 0.50} + sample_quality stratified)
- Q4 Regen scope: Full pipeline replay (scripts/replay_stage.py, LLM 포함)
- Q5 Commit structure: Approach B (domain-grouped 6 commits C0-C5)
- Q6 Grill-me: 2회 (C2 직후 + C4 직후)

## Critical issues 처리

- K1 (caveat reporting): validation_report 에 calibrated < benchmark 항목 명시
- K2 (NBER small N): Cohen's d 효과크기 병행
- K3 (regen LLM 실패): grill-me #2 결정 (skip 또는 partial)
- K4 (working tree 정리): C0 step 1 에서 main 기준 새 branch 확인

## grill-me decisions (appended at each grill point)

### grill-me #1 (C2 직후, 2026-05-25) — DECIDED: PASS with caveat

C2 validation 결과 (49 OOS samples, 1991-2024):

| Strategy | Mean OOS Sharpe | Δ vs calib | p-value | Cohen's d |
|---|---|---|---|---|
| calibrated | 1.229 | — | — | — |
| 60_40_kr_tilted | 1.179 | +0.050 | 0.717 ⚠️ | -0.06 |
| hand_coded_prior | 0.829 | +0.400 | 0.075 | +0.07 |
| equal_weight | 0.818 | +0.411 | 0.060 | +0.11 |
| risk_parity | 0.782 | +0.447 | 0.035 ✓ | +0.12 |

**Verdict: PASS with caveat** (user 결정).
- Calibrated 가 5/5 benchmark 모두 이김 (절대 우월) ✓
- Risk parity 대비 statistically significant (p=0.035) ✓
- 60-40 대비 우위는 **marginal + NOT statistically significant** (Δ=+0.05, p=0.717) ⚠️
- 추가: expansion 구간 단독 비교 (N=47) 시 60-40 (0.821) 이 calibrated (0.779) 보다 약간 우월. recession N=2 너무 작아 검증 불가.

**조치**:
- INITIAL_BETA 유지 (calibrated 그대로)
- followup_issues.md Issue #18 에 caveat 추가: "60-40 대비 statistically not significant"
- C5 final 에 "VERIFIED with caveat" status 기록

(grill-me #2: TBD — C4 regen 실행 직후)
