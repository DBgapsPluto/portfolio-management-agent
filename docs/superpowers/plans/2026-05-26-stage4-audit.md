# Stage 4 코드 감사 + 디버깅 가능성 개선 Plan

**작성일:** 2026-05-26
**목적:** Stage 4 (Risk Judge + 3 lens + severity aggregator + RiskOverlay) 의 4 차원 감사.
**선행:** Stage 1+2+3 audit 모두 main 머지 (7b9eace). 17 commits 누적.

**Stage 1+2+3 deferred 흡수**: Stage 3 audit 에서 method_picker 의 staleness 검사 완료. **Stage 4 의 risk_judge / 3 lens 는 staleness 검사 0** — 같은 patterns 으로 처리해야 함.

---

## 0. Stage 4 특성 (Stage 1/2/3 과 비교)

- **LLM 호출 0회** (Stage 2 와 동일 — 3 lens + severity aggregator 모두 deterministic)
- **이미 일부 logger** (overlay_apply 는 Stage 3 audit 완료, risk_judge 의 telemetry 1줄)
- **3 lens 의 threshold 가 가장 많은 영역** (총 19+개 magic number)
- attribution 인자 부재 — Stage 6 narrative 가 Stage 4 결과 못 봄
- staleness propagation 끊김 — risk_report None/sentinel 시 silent fallback

---

## 1. 4 차원

| 차원 | 무엇을 본다 |
|---|---|
| **L** | risk_judge 의 _extract_risk_signals silent fallback / 3 lens staleness blind / severity_aggregator strength 결정 trace |
| **H** | 3 lens × ~9 magic threshold + ~7 preset overlay + severity 5 strength = **~30+ magic** |
| **D** | risk_judge 에 attribution 인자 → Stage 6 narrative 까지 thread. apply_risk_overlay (이미 Task 4 Stage 3) 와 연결. lens_concerns / strength_applied / overlay_outcome → attribution. |
| **O** | risk_judge entry/exit logger. 3 lens 가 self-trace (입력 + 결과 level + evidence). severity aggregator decision 로직 logger. |

---

## 2. 우선순위 & Task 순서

대회 5/28 마감 영향 큰 순서:

1. **Task 0 — Cross-cutting**: risk_judge 의 `_extract_risk_signals` staleness 검사. risk_report 의 systemic_score, vix_term, funding_stress 의 staleness_days 가 sentinel 이면 lens 결과에 warn flag. Stage 3 와 같은 strict mode 검토 (degraded → overlay strength=0 or skip).
2. **Task 1 — risk_judge observability + attribution thread**: entry/exit log + attribution 인자 추가. Stage 3 의 attribution["overlay"] (이미 Task 4) 와 연계해 attribution["stage4"]["lens_concerns"], ["strength_applied"], ["overlay_outcome"] 채움.
3. **Task 2 — 3 lens named const + per-lens logger**: tail_risk / concentration / macro_conditional 의 magic threshold 모두 named const (모듈 상단). 각 lens 호출 시 logger.info (입력 요약 + 결정 level + evidence).
4. **Task 3 — severity_aggregator named const + strength logger**: 5 strength 분기 (1.0/0.7/0.5/0.3/0.2/0.0) named const. strength 결정 시 logger.info (어느 rule 가 발동).
5. **Task 4 — portfolio_metrics named const**: CVaR min 100, vol min 60 등 named const. logger.warning 부족 데이터 시 fallback.
6. **Task 5 — 통합 sanity**: 신규 test (staleness → lens warn, attribution thread, named const presence) + 회귀 + audit summary.

---

## 3. 공통 패턴

A. 코드 정독 + 논리 점검 / B. 하드코딩 카탈로그 / C. 즉시 결함 수정 / D. observability 보강 / E. commit.

영역별 1 commit. 회귀 매번.

---

## 4. Task 0 — Cross-cutting: risk_report staleness propagation

**Files:**
- `tradingagents/agents/managers/risk_judge.py` (`_extract_risk_signals` line 42-57)
- 3 lens (입력 인자에 staleness 받기)

**Steps:**
- [ ] **0.1** `_extract_risk_signals` 가 systemic_score / vix_term / funding_stress 의 `staleness_days` 도 추출. tuple 또는 dict 로 반환.
- [ ] **0.2** risk_judge entry 에서 staleness sentinel 검사. 셋 다 sentinel ≥99 면 `risk_signals_degraded: bool = True` 설정 + logger.warning.
- [ ] **0.3** risk_signals_degraded=True 인 경우 처리 옵션:
  - (a) lens 호출 skip + empty overlay 반환 (보수적 — 아무 overlay 안 함)
  - (b) lens 호출하되 severity 결과를 medium 이상으로 강제 (defensive)
  - 본 audit 에서는 (a) 채택: degraded → empty overlay + attribution flag. 이유: Stage 3 가 이미 degraded 시 MIN_VARIANCE 강제하므로 Stage 4 는 추가 안 함.
- [ ] **0.4** attribution["stage4"]["risk_signals_degraded"] + 각 신호의 staleness 기록.
- [ ] **0.5** commit: `audit(stage4): cross-cutting — risk_signals staleness check at risk_judge [Task0]`.

**합격 기준:** risk_report 가 모두 sentinel 일 때 Stage 4 가 silent 하게 placeholder 값으로 overlay 만들지 않음. attribution 가시화.

---

## 5. Task 1 — risk_judge observability + attribution thread

**Files:**
- `tradingagents/agents/managers/risk_judge.py`

**Steps:**
- [ ] **1.1 — O** entry log: as_of, weight_vector position 수, lens 호출 시작.
- [ ] **1.2 — D** node 함수에 state 의 allocation_attribution 을 받아 stage4 sub-dict 추가. 또는 risk_judge attribution dict 신규 생성 후 state output 으로 추가.
- [ ] **1.3 — D** apply_risk_overlay 호출에 attribution 전달 (Task 4 Stage 3 의 결과 활용). overlay 의 final_level / dropped_constraints 모두 stage4 attribution 에 포함.
- [ ] **1.4 — O** 각 lens 결과 logger.info (lens name + level + evidence). aggregator 후 strength_applied + severity_decision logger.
- [ ] **1.5 — O** exit log: weight_vector_2 의 max_w, strength, outcome.
- [ ] **1.6 — E** commit: `audit(stage4): risk_judge — entry/exit log + attribution thread [Task1]`.

**합격 기준:** Stage 6 narrative 가 attribution["stage4"] 만 봐도 어느 lens 발동 + 어느 strength + overlay 결과 trace.

---

## 6. Task 2 — 3 lens named const + per-lens logger

**Files:**
- `tradingagents/agents/risk_lens/tail_risk_lens.py`
- `tradingagents/agents/risk_lens/concentration_lens.py`
- `tradingagents/agents/risk_lens/macro_conditional_lens.py`

**Steps:**
- [ ] **2.1 — H** tail_risk_lens: 이미 `_CRITICAL_CVAR=0.04` 등 module-level 로 named 됐지만 prefix `_` 제거 + 공개 const 화 + docstring (1-day 95% CVaR threshold rationale). 5 preset overlay (multiplier 0.6/0.75/0.9) 도 named const.
- [ ] **2.2 — H** concentration_lens: 이미 named 됐지만 동일하게 공개 + preset (weight_ceiling 0.15/0.17, cluster_cap 0.18/0.22) named.
- [ ] **2.3 — H** macro_conditional_lens: 4 scenario × risk_weight threshold + 3 preset multiplier 모두 named.
- [ ] **2.4 — O** 각 lens 진입 시 logger.debug (입력 요약), 결정 시 logger.info (level + evidence).
- [ ] **2.5 — E** commit: `audit(stage4): 3 risk lenses — named const + per-lens logger [Task2]`.

**합격 기준:** 어느 threshold 가 fire 했는지 logger 만 봐도 명확. backtest 시 const 만 바꾸면 됨.

---

## 7. Task 3 — severity_aggregator named const + strength logger

**Files:**
- `tradingagents/skills/risk/severity_aggregator.py`

**Steps:**
- [ ] **3.1 — H** 5 strength threshold (1.0/0.7/0.5/0.3/0.2/0.0) → named const + docstring (어느 조합 때 어떤 strength).
- [ ] **3.2 — O** strength 결정 시 logger.info (어느 rule 발동, n_critical / n_high / n_medium count).
- [ ] **3.3 — L** delta 머지 로직 (min / max / strength-weighted blending) 의 boundary 검토 — strength=0.0 일 때 overlay 가 정확히 empty 인지 확인.
- [ ] **3.4 — E** commit: `audit(stage4): severity_aggregator — named const + strength logger [Task3]`.

**합격 기준:** strength=0.7 결정의 근거가 logger 한 줄로 명확.

---

## 8. Task 4 — portfolio_metrics named const

**Files:**
- `tradingagents/skills/risk/portfolio_metrics.py`

**Steps:**
- [ ] **4.1 — H** min data threshold (CVaR=100, vol=60) named const.
- [ ] **4.2 — O** 데이터 부족 시 logger.warning + None 반환 가시화 (이미 None 반환은 됨, logger 추가).
- [ ] **4.3 — E** commit: `audit(stage4): portfolio_metrics — named const + missing-data logger [Task4]`.

**합격 기준:** 데이터 부족 시 어느 metric 이 None 인지 logger 로 추적 가능.

---

## 9. Task 5 — Stage 4 통합 sanity

**Files:**
- 신규 test: `tests/unit/agents/test_risk_judge_audit.py` 또는 기존 test_risk_judge.py 확장

**Steps:**
- [ ] **5.1** 신규 test 3개:
  - `test_degraded_risk_signals_skips_lens`: risk_report sentinel 시 lens 호출 skip + empty overlay.
  - `test_attribution_thread`: risk_judge attribution 이 lens_concerns / strength_applied / overlay_outcome 모두 채움.
  - `test_named_const_present`: 3 lens + severity_aggregator + portfolio_metrics 의 const 존재.
- [ ] **5.2** 전체 unit + integration regression. pre-existing 1 fail 제외 회귀 0.
- [ ] **5.3** `docs/stage4_audit.md` 작성.
- [ ] **5.4** commit: `audit(stage4): integration sanity + summary [Task5]`.

**합격 기준:** Stage 1+2+3 staleness propagation 이 Stage 4 까지 안전하게 흐름. attribution thread 통합 입증.

---

## 10. Sign-off Checklist

- [ ] Task 0 — risk_signals staleness check + degraded skip
- [ ] Task 1 — risk_judge observability + attribution thread
- [ ] Task 2 — 3 lens named const + per-lens logger
- [ ] Task 3 — severity_aggregator named const + strength logger
- [ ] Task 4 — portfolio_metrics named const + missing-data logger
- [ ] Task 5 — integration sanity + summary

---

## 11. 범위 밖

- 3 lens threshold backtest tuning (Phase 3 작업, 5/28 후)
- macro_conditional_lens 의 scenario × regime 매트릭스 확장 (Stage 2 deferred 와 묶음)
- portfolio_metrics 의 CVaR confidence 95% 수정 (별도 mandate 검토 필요)

---

## 12. Risk

| Risk | Mitigation |
|---|---|
| Task 0 의 degraded skip 이 정상 운영에서 발동 | 셋 다 sentinel (≥99) 조건만 — 정상 1-7d stale 통과. |
| attribution 인자 추가가 기존 risk_judge caller 깨뜨림 | optional default None — backward-compat. |
| const 분리가 import 깨뜨림 | prefix `_` 제거 시 기존 internal 사용자 점검 (risk_lens 내부만). |
