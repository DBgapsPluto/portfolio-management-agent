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

(grill-me #1: TBD — C2 validation 실행 직후)
(grill-me #2: TBD — C4 regen 실행 직후)
