# Stage 2 Audit — 2026-05-26

Plan: [docs/superpowers/plans/2026-05-26-stage2-audit.md](superpowers/plans/2026-05-26-stage2-audit.md)
Stage 1 deferred 흡수: pre-existing test fail `test_select_etf_candidates_populates_attribution` 의 `D_N_F` → `stagflation` (Task 4).

---

## Stage 2 특성

Stage 1 과의 차이:
- **LLM 호출 0회** — 전부 deterministic factor model.
- **logger 호출 0회 (audit 전)** — 결정적이라 silent 친화적, 그러나 디버깅 trace 부재.
- `safety_diagnostics` (7 키) + `factor_contributions` (9×5) 가 ResearchDecision 에 채워지지만 **summary 노출 0** → Stage 6 narrative 가 이 정보 못 봄.

---

## Task 0 — research_manager observability

### 발견

- `logger` 호출 0번. 9-factor 계산 / EMA blend / scenario·conviction 결정 / projection 발동 모두 invisible.
- summary 가 z-score 와 bucket 만 보여줌. **safety_diagnostics 7 키 + top contributors 미노출**.

### 결정/수정

- entry log: 9 factor 계산 + n_active(컴포넌트 활성 factor 수) + |z| sum.
- EMA blend 발동 시 logger.info.
- 최종 log: scenario / conviction / extreme_factor_active / projection_intervened.
- summary 에 추가:
  - **Top contributors**: |β·z| 상위 3 (예: `F2_inflation→bond -3.2pp`).
  - **Safety line**: mandate_violated_pre, projection_intervened, l2_distance, extreme_factor.

### 회귀: 74 pass (research_manager + factor_model + 통합).

---

## Task 1 — scenario/conviction mapping 명시화

### 발견

- `derive_dominant_scenario` 의 7 magic threshold (0.5×4, 1.0×2, 1.5×1) 가 분기 안에 hardcoded.
- `derive_conviction` 의 4.0/2.0 (total_mag), 0.6/0.3 (alignment) 도 magic.
- **Hysteresis 부재** — z 가 threshold 의 미세한 어느 쪽에 있는지에 따라 scenario jump. 매 run 의 미세 변화로 시나리오 불안정 위험.
- `derive_conviction` 가 9 factor 중 3개만 사용 (F1+, F5-, F7-). 단순화 근거 docstring 부재.

### 결정/수정

- 9 named const 도입:
  - `SCENARIO_{CYCLE,KR,KR_CORROBORATE,VOL,CREDIT}_THRESHOLD`
  - `CONVICTION_{HIGH,MED}_{MAG,ALIGN}`
- 각 const 에 도출 근거 코멘트 (1σ vs 1.5σ semantic, 9 factor 중 3 factor 선택 이유).
- **Hysteresis 도입은 안 함** — 별도 brainstorm. fragile 동작은 통합 test 로 reproduce + audit doc 기록.

### 회귀: 14 pass.

---

## Task 2 — factor_to_bucket projection 가시화

### 발견

- `project_to_mandate_qp` 의 **silent fallback to INITIAL_BASELINE**:
  - SLSQP optimizer 실패 → silent return baseline. 운영자가 "왜 default 같은 결과지?" 만 느낌.
  - `w.sum() == 0` (post-clip) → 동일 silent fallback.
- `safety_diagnostics` 7 키 docstring 부실 (이름만 있고 의미·downstream 해석 없음).
- **cap_hits 미추적**: per-(factor, bucket) β·z 가 ±0.10 cap 에 닿은 횟수가 진단 정보로 노출 안 됨. single factor 가 single bucket 을 dominate 하려 했는지 invisible.

### 결정/수정

- 2 fallback 사이트 모두 `logger.warning` 추가. 실패 이유 + target bucket + raw weights 노출.
- safety_diagnostics docstring 확장: 각 키의 의미 + 운영자 관점 해석.
- 신규 진단 키: `cap_hits` (int) + `cap_hits_detail` (list[(factor, bucket, value)]).
- INITIAL_BETA 메타데이터는 이미 코멘트로 충실 (PR2a calibration, 2026-05-24, OOS Sharpe 1.171). 추가 작업 없음.

### 회귀: 32 pass (factor_to_bucket + projection + research_manager).

---

## Task 3 — external_fetchers staleness analog

### 발견

- `fetch_krw_usd_level` / `fetch_sp_trailing_pe` 자체는 이미 logger.warning + None 반환 (caller drop) — silent distortion 위험 작음.
- 다만 `compute_krw_regime` 의 **Stage 1 → external fallback** 경로 silent:
  ```python
  krw_level = _safe_get(stage1, "macro_report", "fx", "usd_krw")  # Stage 1 sentinel guard 작동 가능
  if krw_level is None:
      krw_level = fetch_krw_usd_level()   # external 우회
  ```
  → 운영자가 (a) Stage 1 fx sentinel, (b) external 성공, (c) 양쪽 실패 구분 불가.
- `compute_valuation` 의 `fetch_sp_trailing_pe` 는 Stage 1 와 무관 (SP P/E 채울 필드 없음). 우회로 의도된 path. 별도 trace 불필요.

### 결정/수정

- `compute_krw_regime` 의 fallback 발동 시 logger.info — Stage 1 → external 경로 가시화.
- 양쪽 실패 (external 도 None) 시 logger.warning.
- factor_estimators.py 에 module-level `logger` 추가 (없었음).

### 회귀: 95 pass (research 전체 + 통합).

---

## Task 4 — Stage 1 deferred fix: D_N_F → stagflation

### 발견

- `test_select_etf_candidates_populates_attribution` 가 main 에서도 fail. 원인: 2026-05-22 PR 에서 cell-key path (`"D_N_F"` 등 24-cell 형식) 제거됐는데 fixture 만 안 따라옴 → `_scenario_to_axes("D_N_F")` returns None → composed_mult 1.0 → assertion fail.

### 결정/수정

- fixture 한 줄 교체: `dominant_scenario="D_N_F"` → `"stagflation"` (둘 다 (D, N, F) 셀 → 같은 gold boost).
- `sb["scenario"] == "D_N_F"` → `"stagflation"` 동기화.

### 회귀: 14 pass (전체 test_portfolio_attribution.py).

### 임팩트: pre-existing fail 2 → 1.

---

## Task 5 — Stage 2 통합 sanity

### 신규 integration test 4개

- `test_multiple_sentinels_yield_low_conviction` — 3 snapshot 동시 sentinel 시 conviction upgrade 발생 안 함 + total |z| 감소.
- `test_scenario_threshold_no_hysteresis` — z 0.02 차이로 scenario jump 입증 (fragility documented).
- `test_stage2_named_constants_present` — Task 1 의 const 가 모듈에 존재.
- `test_factor_to_bucket_cap_hits_diagnostic` — extreme F1=5.0 입력 시 cap_hits ≥ 1, extreme_factor_active True.

### 회귀

- unit: pre-existing technical fail 1개 제외 → 866 pass (+1 attribution fix).
- integration: 16 pass (12 → 16, 신규 4).

---

## Summary 표 (dimension × concern)

| 차원 | research_manager | factor_to_bucket | external_fetchers | factor_estimators |
|---|---|---|---|---|
| **L** | hysteresis 부재 documented; conviction 3-factor 근거 | QP fallback silent → logger | Stage 1→external trace 추가 | (Task 0 픽스 이미 적용) |
| **H** | 9 named const (scenario + conviction) | 이미 const 화 (PER_FACTOR/MANDATE) | (n/a) | (n/a) |
| **D** | top contributors + safety_diag → summary | cap_hits + cap_hits_detail 진단 | logger.info trace | logger 추가 |
| **O** | entry/exit log + EMA blend log | 2 fallback site logger.warning | None 반환 caller drop verified | module logger |

---

## 미해결 / 후속 (이월)

| 항목 | 사유 | 이관 |
|---|---|---|
| scenario hysteresis 도입 | 별도 brainstorm 필요 (threshold deadband 폭 결정) | followup PR |
| derive_conviction 의 9-factor weighted alignment | 단순화 → 정교화. backtest 로 효과 검증 | followup PR |
| Stage 1 deferred: method_picker / portfolio_allocator staleness 검사 | Stage 3 audit 영역 | Stage 3 audit |
| Stage 1 deferred: classify_regime LLM prompt sentinel hint | Stage 2 LLM=0 이라 본 stage 무관 | Stage 1 audit followup |
| Stage 1 deferred: 매직 임계값 (ADX 등) 튜닝 | backtest 필요 | 대회 5/28 후 |
| pre-existing fail: test_technical_analyst_returns_report (rank_momentum 빈 dict) | main 회귀, audit 직전부터 fail | 별도 PR |

---

## Commits (Stage 2: 5개 + 1 deferred fix)

1. 516a58d — Task 0 research_manager observability
2. cafdaf1 — Task 1 scenario/conviction named const
3. 88ce6b1 — Task 2 factor_to_bucket projection logger + cap_hits
4. ab252d8 — Task 3 external_fetchers trace
5. d78008b — fix(test) deferred D_N_F → stagflation
6. (이번) — Task 5 integration sanity + summary
