# Stage 2 코드 감사 + 디버깅 가능성 개선 Plan

**작성일:** 2026-05-26
**목적:** Stage 2 (Research Manager — factor model + scenario/conviction mapper) 의 (a) 논리 검증, (b) 하드코딩 카탈로그, (c) 데이터 흐름·진단 정보 노출, (d) observability 4 차원 감사.
**선행:** Stage 1 audit (commit f877639...f809a30) — `_safe_get` sentinel guard 가 이미 적용됨. Stage 2 는 그 위에서 추가 감사.
**Deferred from Stage 1 (이번에 처리)**:
- pre-existing test fail `test_select_etf_candidates_populates_attribution` — Stage 2 의 `dominant_scenario` 값 동기화.
- (method_picker staleness 검사 — Stage 3 audit 이관 유지)
- (classify_regime LLM prompt 보강 — 본 stage 와 무관, 이관 유지)

---

## 0. Audit Dimensions (Stage 1 과 동일)

| 차원 | 무엇을 본다 |
|---|---|
| **L** (Logic) | scenario/conviction mapping의 hysteresis 없는 threshold 점프, mandate projection 의 silent fallback, external fetcher 의 staleness blind. |
| **H** (Hardcoding) | scenario 0.5/1.0/1.5, conviction 4.0/2.0, EMA λ=1.0, Z_CAP=3.0, MANDATE 0.70, PER_FACTOR 0.10. |
| **D** (Data flow) | safety_diagnostics 7키 + factor_contributions 9×5 가 만들어지지만 ResearchDecision 외엔 어디서도 사용 안 됨. Stage 6 narrative 가 이 정보 보게. Stage 1 → 2 의 sentinel guard 가 production 시나리오에서 어떻게 작동하는지 통합 검증. |
| **O** (Observability) | research_manager + factor_to_bucket + factor_estimators 전체 logger 0 호출. mandate projection 발동 시점·distance 가시화. EMA 적용 여부 trace. |

---

## 1. 우선순위 & 순서

대회 5/28 마감 영향 큰 순서 + Stage 1 deferred:

1. **Task 0 — Cross-cutting 관찰성**: research_manager 의 entry/exit log, 9-factor magnitude trace, dominant_scenario 분기 추적. summary 에 safety_diagnostics + top contributors 노출.
2. **Task 1 — research_manager**: scenario/conviction 의 threshold 명시화 + hysteresis 검토 + magic 분리.
3. **Task 2 — factor_to_bucket**: mandate projection fallback path 가시화 (silent → logger), safety_diag 키 의미 문서화 + 외부 노출, INITIAL_BETA 출처/calibration metadata 가시.
4. **Task 3 — external_fetchers**: krw_usd, sp_trailing_pe fetcher staleness 검증. Stage 1 의 silent distortion analog 차단.
5. **Task 4 — Stage 1 deferred fix**: `test_select_etf_candidates_populates_attribution` 의 `D_N_F` → `stagflation` 동기화 (Stage 2 의 `derive_dominant_scenario` 출력값과 일치).
6. **Task 5 — Stage 2 통합 sanity**: Stage 1 → 2 sentinel propagation + 회귀.

---

## 2. 공통 패턴 (각 Task)

A. 코드 정독 + 논리 점검 / B. 하드코딩 카탈로그 / C. 즉시 결함 수정 / D. observability 보강 / E. commit.

분석가별 1 commit. 회귀 테스트 매번 실행.

---

## 3. Task 0 — Cross-cutting: observability + 진단 정보 노출

**Files:**
- `tradingagents/agents/managers/research_manager.py`
- `tradingagents/schemas/research.py` (read only)

**Steps:**
- [ ] **0.1** research_manager entry/exit log: `logger.info("research_manager start: factor compute")`, factor magnitudes summary, dominant_scenario decision rationale.
- [ ] **0.2** EMA blend 적용 시 logger.info — λ, prior 존재 여부.
- [ ] **0.3** `summary` 문자열에 (a) safety_diagnostics 의 주요 키 (extreme_factor_active, projection_intervened, projection_l2_distance), (b) factor_contributions 의 top-3 (bucket × factor) 추가. Stage 6 narrative 가 이 정보 보게.
- [ ] **0.4** commit: `audit(stage2): research_manager observability — entry/exit log + safety_diag + top contributors in summary`.

**합격 기준:** Stage 2 결과 한 줄로 "왜 이 bucket 이 됐는지" trace 가능.

---

## 4. Task 1 — research_manager scenario/conviction mapping

**Files:**
- `tradingagents/agents/managers/research_manager.py:64-121`

**Steps:**
- [ ] **1.1 — L** `derive_dominant_scenario` 의 7 분기 검토. hysteresis 없음 — single z 가 threshold 넘으면 scenario jump. 영향 평가 (현재 시점의 운영 risk). 미세 fluctuation 으로 scenario 가 매 run 바뀌면 method_picker / candidate_selector 결과 불안정.
- [ ] **1.2 — H** threshold 7개 (0.5×4, 1.0×2, 1.5×1) → named const + comment 로 도출 근거. tuning 후보 표시.
- [ ] **1.3 — L** `derive_conviction` 의 3-factor (F1, F5, F7) 가정 검토. 9 factor 중 3 만 쓰는 이유 — F1=cycle, F5=credit, F7=vol 가 risk-on/off 의 핵심 proxy. comment 보강.
- [ ] **1.4 — H** conviction threshold (4.0/2.0/0.6/0.3) → named const.
- [ ] **1.5 — D** scenario decision rationale 을 ResearchDecision 의 rationale field 또는 별도 trace 로 노출.
- [ ] **1.6 — E** commit: `audit(stage2): research_manager scenario/conviction mapping — named const + hysteresis review`.

**합격 기준:** scenario / conviction 분기 결정 근거가 코드만 보고 한눈에 보임. threshold 가 const 화되어 향후 tuning 용이.

---

## 5. Task 2 — factor_to_bucket mandate projection 가시화

**Files:**
- `tradingagents/skills/research/factor_to_bucket.py`

**Steps:**
- [ ] **2.1 — L** `project_to_mandate_qp` 의 optimizer 실패 fallback path 점검. 현재 INITIAL_BASELINE 으로 silent fallback. logger.warning 추가 — "QP infeasible, fallback to baseline".
- [ ] **2.2 — D** `apply_factor_model_with_safety` 가 반환하는 safety_diag 의 7 키를 docstring 으로 명시. 각 키의 downstream 의미.
- [ ] **2.3 — L** `apply_factor_model` 의 per-contribution cap (PER_FACTOR_BUCKET_CONTRIB_CAP=0.10) — cap 이 발동된 (factor, bucket) 페어 카운트 → safety_diag 에 추가.
- [ ] **2.4 — H** named const 확인 + comment (이미 const 화돼 있는지 확인 후 필요 시 보강).
- [ ] **2.5 — L** INITIAL_BETA 의 calibration metadata (date, samples, oos_sharpe) 를 모듈 docstring 또는 const 로 명시. 추적 가능.
- [ ] **2.6 — E** commit: `audit(stage2): factor_to_bucket — projection fallback logger + cap_hits diag + metadata`.

**합격 기준:** projection 발동 시점·이유가 logger + safety_diag 로 노출. INITIAL_BETA 출처 1줄 trace.

---

## 6. Task 3 — external_fetchers staleness 검사

**Files:**
- `tradingagents/skills/research/external_fetchers.py`

**Steps:**
- [ ] **3.1 — L** `fetch_krw_usd_level` / `fetch_sp_trailing_pe` 가 fetch 실패 시 fallback 값 반환하는지 확인. fallback 값이 정상 평균치와 구별 가능한지 (Stage 1 의 BSI=100 analog).
- [ ] **3.2 — L** 이 fetcher 들이 Stage 1 의 macro_report.fx.usd_krw / kr_valuation 가 채워졌으면 사용 안 함. 미사용 경로 검증. 사용 경로 (Stage 1 미제공) 에서 staleness 마킹 가능한지.
- [ ] **3.3 — D** factor_estimators 가 `fetch_krw_usd_level(stage1)` 호출 시 fallback 값 (Stage 1 의 fx.usd_krw 가 sentinel) 이면 어떻게 동작? `_safe_get` sentinel guard 통과 후 external fetcher 호출 → 결과 raw float (staleness 없음). 이 경우 factor F6 가 가짜 raw 값 흡수 가능.
- [ ] **3.4 — C** 발견된 결함 수정. external fetcher 가 raw float 반환 시 staleness 못 표시하면, factor_estimators 에서 (Stage 1 sentinel) → component drop 으로 직행하는 단축 경로 추가.
- [ ] **3.5 — E** commit: `audit(stage2): external_fetchers — staleness analog + sentinel propagation`.

**합격 기준:** Stage 1 fx/valuation sentinel 시 external fetcher 가 raw 값 silent injection 못 함.

---

## 7. Task 4 — Stage 1 deferred fix: pre-existing test fail

**Files:**
- `tests/unit/skills/test_portfolio_attribution.py:158, 175`

**Steps:**
- [ ] **4.1** `test_select_etf_candidates_populates_attribution` 의 `dominant_scenario="D_N_F"` → `"stagflation"` 으로 교체 (legacy 7-scenario 명).
- [ ] **4.2** `assert sb["scenario"] == "D_N_F"` → `"stagflation"`.
- [ ] **4.3** 단독 commit (Stage 2 audit 와 분리): `fix(test): sync dominant_scenario fixture to legacy 7-name post 2026-05-22 cell-key removal`.
- [ ] **4.4** 전체 회귀 확인 — 2 pre-existing fail 중 이 1개 해결.

**합격 기준:** test 통과. 의도(stagflation cycle → gold boost) 정확히 검증.

---

## 8. Task 5 — Stage 2 통합 sanity

**Files:**
- `tests/integration/test_factor_estimators_real_schema.py` (이미 12 test 존재)

**Steps:**
- [ ] **5.1** Stage 1 → 2 통합: 실 baseline 에서 multiple Stage 1 snapshot sentinel → ResearchDecision 의 dominant_scenario / conviction / safety_diagnostics 가 합리적인지 검증.
- [ ] **5.2** scenario hysteresis 회귀 — F1 가 0.49 → 0.51 변화 시 scenario 가 jump 하는지 (현재 동작 확인, hysteresis 추가는 별도 PR).
- [ ] **5.3** 전체 unit + integration regression: `pytest tests/unit/ tests/integration/test_factor_estimators_real_schema.py -q`.
- [ ] **5.4** `docs/stage2_audit.md` 작성 (Stage 1 과 동일 format).
- [ ] **5.5** commit: `audit(stage2): integration sanity + summary`.

**합격 기준:** 회귀 0 (+ Task 4 로 pre-existing 1 fail 해결).

---

## 9. Sign-off Checklist

- [ ] Task 0 — research_manager observability (entry log, safety_diag in summary)
- [ ] Task 1 — scenario/conviction named const + hysteresis review
- [ ] Task 2 — factor_to_bucket projection fallback logger + safety_diag 보강
- [ ] Task 3 — external_fetchers staleness analog 차단
- [ ] Task 4 — Stage 1 deferred: D_N_F → stagflation fixture fix
- [ ] Task 5 — integration sanity + 회귀 0
- [ ] `docs/stage2_audit.md` 작성

---

## 10. 범위 밖

- INITIAL_BETA 재calibration → backtest 작업 (5/28 후)
- scenario hysteresis 도입 → 별도 brainstorm
- factor_calibration historical fetch 통합 (Issue #18) → 별도
- classify_regime LLM prompt sentinel hint (Stage 1 deferred 유지 — Stage 2 LLM 호출 0이라 본 stage 무관)
- method_picker staleness 검사 (Stage 1 deferred — Stage 3 audit 이관)

---

## 11. Risk

| Risk | Mitigation |
|---|---|
| safety_diag exposure 변경이 ResearchDecision schema 깨뜨림 | safety_diagnostics 는 이미 ResearchDecision field, 추가만. schema 변경 없음. |
| logger 추가가 LangSmith trace 폭증 | logger.info 만, debug level 사용 안 함. 한 run 당 ~10 줄. |
| Task 4 의 fixture fix 가 다른 테스트 깨뜨림 | 해당 fixture 는 1 테스트 전용. 회귀 매번 확인. |
