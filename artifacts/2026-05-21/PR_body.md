# Draft PR — `feat/stage1-indicator-fixes` → `feat/db-gaps-redesign`

**Title:** `feat(stage1): 4-issue indicator design fixes (mega-PR, spec+plan)`

**PR open URL:** https://github.com/DBgapsPluto/pluto/pull/new/feat/stage1-indicator-fixes

---

## Summary

Stage 1 의 4개 indicator design 결함을 holdout backtest 검증 하에 mega-PR 1개 (6 commit) 로 수정. **본 draft PR 은 spec + plan + decision log 단계** — review 후 C0~C5 implementation commit 누적 예정.

### 식별된 4 결함 (cold analysis 2026-05-21)
- **#1 yield_curve**: `inverted_days_count >= 60` 단독 anchor 는 Cam Harvey framework 의 일부만 사용. NBER recession 은 disinversion 직후 시작 (1990/2001/2008/2020 모두).
- **#2 risk_appetite (Cu/Au)**: AI 전력망(Cu), 중앙은행 매집(Au) 등 비순환 수요 dominance → risk-on/off 신호력 상실.
- **#3 fx**: Absolute threshold (`krw_change > +2%`) 가 slow drift (KRW 1300→1450 over 2y) 놓침. 1380원대에서 거의 매일 `usd_risk_off` 오발.
- **#4 fed_path**: `hike/cut/hold` 거친 라벨링. 시장 가격 정보 손실 ("3 cuts priced" 표현 불가).

### 수정 방향 (cold-analysis-grilled 답)
- **#1**: sequential framework — `inverted_days` 는 `defensive_lean` 으로 유지, 신규 `recession_trigger` 필드 (disinversion + bull steepener), bear steepener 별도 flag. **anchor 박탈 X, 추가만.**
- **#2**: HY OAS (`BAMLH0A0HYM2`, FRED) dominant composite (HY 0.55 + Cu/Au 0.20 + VIX term 0.25, sigmoid 변환). `RiskAppetiteConfig` dataclass 외부화. `divergence_flag` meta-signal.
- **#3**: Hybrid Z-score (단기 충격) + level percentile (구조적 위치). 신규 enum `krw_structural_weak`. **Schema migration 영향 9 파일 사전 리스팅** (spec §4.3).
- **#4**: Display-only 추가 (path_6m/12m/24m bps + implied_moves_12m). classification 로직 변경 X.

## 원칙

1. **No new hardcoded magic numbers without holdout backtest justification** — 직전 PR (`77f70b2`) 의 #2~#7 caveat 작업과 일관성. 임계값 dataclass 외부화 또는 percentile 기반.
2. **Sequential framework 보존** — Cam Harvey 의 inversion → disinversion → recession 단계를 모두 본다.
3. **Holdout backtest as precondition** (C0) — 2022-06 ~ 2024-12 false positive 50% 감소가 채택 기준 (D11). FN 검증: 2008-09 / 2020-03 에서 baseline + proposed 모두 fire.
4. **Schema migration plan upfront** — 새 enum 값 추가 시 영향 파일 전수 리스팅 (spec §4.3).

## PR commit 구조 (예정)

```
C-spec  docs(stage1): design spec + implementation plan ← 본 commit (ec7cecb)
C0      feat(stage1): holdout backtest harness
C1      feat(stage1): HY OAS + risk_appetite composite (#2 fix)
C2      feat(stage1): YC sequential framework (#1 fix)
C3      feat(stage1): FX hybrid + krw_structural_weak (#3 fix)
C4      feat(stage1): Fed path multi-tenor display (#4 fix)
C5      docs(stage1): updated specs + final regression + holdout summary
```

각 commit independently revertable. C0 holdout 결과가 reject → 해당 issue commit 폐기.

## 문서

- **Spec**: `docs/superpowers/specs/2026-05-21-stage1-indicator-fixes-design.md`
- **Plan**: `docs/superpowers/plans/2026-05-21-stage1-indicator-fixes.md`
- **Decisions**: `artifacts/2026-05-21/decisions.md` (D0~D11 정의)
- **Execution protocol**: `docs/superpowers/plans/2026-05-20-stage2-execution-protocol.md` 8 원칙 그대로 채택

## Test plan (C5 후 의무)

- [ ] `pytest tests/unit/ -q --timeout=30` PASS quote
- [ ] `pytest tests/integration/test_eval_regime_classifier.py -v` PASS quote (8 fixture fx_regime 갱신)
- [ ] Holdout `artifacts/2026-05-21/holdout/summary.md` 채워짐
- [ ] Schema migration 9 파일 한 줄씩 verify (spec §4.3)

## Non-goals (의식적 제외)

- CME FedWatch 직접 통합 (cold analysis 본인 인정한 유지보수 부담)
- Cu/Au 완전 폐기 (0.20 weight 로 유지, divergence flag 의 한 축)
- `krw_structural_strong` 대칭 enum (spec §3.3 비대칭 정당화)
- `repricing_speed`, `curve_shape` Fed path field (spec §3.4 hardcode 부담)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
