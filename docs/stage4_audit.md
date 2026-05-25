# Stage 4 Audit — 2026-05-26

Plan: [docs/superpowers/plans/2026-05-26-stage4-audit.md](superpowers/plans/2026-05-26-stage4-audit.md)
Stage 1+2+3 staleness propagation 의 **마지막 끊김 보수** — risk_judge / 3 lens / severity_aggregator.

---

## Stage 4 특성

- **LLM 호출 0회** (Stage 2 와 동일)
- **3 lens 의 threshold 가 가장 많은 영역** — 30+ magic numbers (Task 2/3 에서 named const)
- 일부 logger 이미 존재 (overlay_apply 의 escalation, telemetry 1줄)
- **attribution 인자 부재** (Task 1 에서 보강)
- **risk_signals staleness 검사 0** (Task 0 의 핵심)

---

## Task 0 — risk_signals staleness check + degraded skip

### 발견

- `_extract_risk_signals` (risk_judge.py:42-57) 가 systemic_score / vix_term / funding_stress 의 `staleness_days` 검사 0.
- Stage 1 의 market_risk_analyst 가 fetch 실패 시 sentinel (staleness=99) 로 만든 객체가 그대로 placeholder 값 (score=5.0, vix="contango", funding="calm") 으로 3 lens 입력 → 잘못된 overlay 강도.

### 결정/수정

- `STALENESS_SENTINEL_DAYS_S4 = 99` named const.
- `_extract_risk_signals` 반환 dict 에 systemic_staleness, vix_term_staleness, funding_staleness 추가.
- 셋 다 명시적 sentinel 시 `all_degraded = True`.
- risk_judge node 에서 `all_degraded=True` 면 lens 호출 skip + empty overlay + logger.warning. Stage 3 audit Task 0 이 이미 MIN_VARIANCE 강제했으므로 Stage 4 가 추가 overlay 안 만드는 게 보수적 (Stage 3 결과 보존).
- `risk_report=None` 자체 부재는 기존 default 동작 유지 (다른 skip 시나리오 가능).

### 회귀: 24 pass.

---

## Task 1 — risk_judge observability + attribution thread

### 발견

- entry/exit log 0.
- `risk_judge_attribution` state 키 부재 → Stage 6 narrative 가 Stage 4 결과 못 봄.
- Stage 3 audit Task 4 의 `apply_risk_overlay(attribution=...)` 기능 미활용.

### 결정/수정

- logger.info entry/exit (as_of, n_positions, outcome).
- 각 lens 결과 logger.info (lens / level / evidence).
- severity_aggregator 결과 logger.info.
- `risk_judge_attribution` dict 신규:
  - `input_present` (7 키)
  - `skipped` (stage3_inputs_missing / returns_matrix_empty / risk_signals_degraded)
  - `risk_signal_staleness` (Task 0 흐름)
  - `lens_concerns` (list of {lens, level, evidence})
  - `strength_applied`, `severity_decision`, `multiplier`
  - `overlay` (Stage 3 Task 4 의 final_level, dropped_constraints 등)
- state output 에 `risk_judge_attribution` 추가 (allocation_attribution 옆).

### 회귀: 24 pass.

---

## Task 2 — 3 lens named const + per-lens logger

### 발견

- 3 lens 의 ~19 magic threshold + ~7 preset overlay 가 module-level `_PREFIX` 변수로 hidden.
- 3 lens 모두 logger 호출 0.

### 결정/수정 (총 34+ named const)

- **tail_risk_lens**: CRITICAL/HIGH/MEDIUM/LOW_CVAR (4) + 동일_SYSTEMIC (4) + MULTIPLIER_CRITICAL/HIGH/MEDIUM (3) = 11 named. logger.debug.
- **concentration_lens**: CRITICAL/HIGH/MEDIUM/LOW_HHI (4) + _CLUSTER (3) + TOP1_CRITICAL/TOP3_HIGH (2) + CLUSTER_CAP (2) + WEIGHT_CEILING (2) = 13 named.
- **macro_conditional_lens**: GLOBAL_CREDIT/RECESSION/CONVICTION threshold (7) + MULTIPLIER (3) = 10 named. + RISK_BUCKETS_MC frozenset.

### 회귀: 19 pass.

---

## Task 3 — severity_aggregator named const + strength logger

### 발견

- 5 strength gate (1.0/0.7/0.5/0.3/0.2/0.0) hardcoded.
- merge logic bounds (0.20/1.0/0.5/0.20) hardcoded.
- 결정 logger 0.

### 결정/수정

- STRENGTH_CRITICAL_TWO_PLUS / CRITICAL_ONE / HIGH_TWO_PLUS / HIGH_ONE / MEDIUM_TWO_PLUS / NONE (6) named const.
- merge bounds: WEIGHT_CEILING_MAX, CLUSTER_CAP_MAX, MULTIPLIER_FLOOR, FLOOR_MAX (4) named.
- `logger.info("%d concerns (lens=level, ...) → strength=%.2f (decision)")`.

### 회귀: 18 pass.

---

## Task 4 — portfolio_metrics named const + missing-data logger

### 발견

- MIN_OBS=60 (vol), 100 (CVaR), 95 (percentile) hardcoded.
- 데이터 부족 시 0.0 fallback silent.

### 결정/수정

- MIN_OBS_REALIZED_VOL=60, MIN_OBS_CVAR=100, VAR_PERCENTILE=95.0 named const.
- 부족 시 `logger.warning("realized_vol_60d 계산 불가 → 0.0")`, `logger.warning("CVaR_95_1d 계산 불가 → 0.0. tail_risk_lens 결정이 좁아짐.")`.

### 회귀: 18 pass.

---

## Task 5 — 통합 sanity + summary

### 신규 test 3개

- `test_degraded_risk_signals_skip_lens`: 셋 다 sentinel → lens skip + empty overlay + attribution["skipped"]="risk_signals_degraded".
- `test_risk_judge_attribution_threads_lens_concerns`: 3 lens concerns + strength + multiplier + input_present 모두 attribution.
- `test_named_const_present_in_lenses`: 3 lens + aggregator + metrics const 존재 검증.

### 회귀: 5 pass (test_risk_judge).

---

## Summary 표 (dimension × area)

| 차원 | risk_judge | 3 lens | severity_aggregator | portfolio_metrics |
|---|---|---|---|---|
| **L** | risk_signals staleness check + degraded skip | (threshold 만, logic 변경 없음) | merge bounds named | min-obs fallback |
| **H** | STALENESS_SENTINEL_DAYS_S4 | 34+ named const | 10 named const | 3 named const |
| **D** | risk_judge_attribution dict 신규, Task 4 overlay attr 연계 | (간접 — risk_judge 가 결과 thread) | (간접) | (간접) |
| **O** | entry/exit/per-step logger.info | per-lens logger.debug | strength decision logger.info | missing-data logger.warning |

---

## 미해결 / 후속 (이월)

| 항목 | 사유 | 이관 |
|---|---|---|
| 3 lens threshold backtest tuning | Phase 3 작업 | 대회 5/28 후 |
| macro_conditional_lens 의 scenario × regime 매트릭스 확장 | Stage 2 deferred 와 묶음 | followup PR |
| portfolio_metrics 의 CVaR confidence 95% 수정 | mandate 검토 필요 | 별도 |
| pre-existing fail: test_technical_analyst_returns_report | audit 무관 | 별도 PR |

---

## Commits (Stage 4: 5개)

1. e52cc28 — Task 0 risk_signals staleness check + degraded skip
2. a36af2c — Task 1 risk_judge observability + attribution thread
3. ed01e0a — Task 2 3 lens named const + per-lens logger
4. 4547ba4 — Task 3+4 severity_aggregator + portfolio_metrics named const
5. (이번) — Task 5 integration sanity + summary

---

## Stage 1+2+3+4 audit 누적 통계

- **commits**: 6+6+5+5 = **22 commits**
- **deferred 해결**:
  - Stage 1 #2 + Stage 2 #3 (method_picker staleness) — Stage 3 Task 0 ✓
  - Stage 1+2+3 staleness propagation 의 모든 끊김 — Stage 4 Task 0 ✓
- **pre-existing fail**: 2 → 1
- **named const**: ~47 (Stage 1+2+3) + ~50 (Stage 4) = **~97 const**
- **logger 호출**: ~75 + ~20 = **~95**
- **신규 test**: 8 + 3 = **11**
