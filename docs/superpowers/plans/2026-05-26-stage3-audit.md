# Stage 3 코드 감사 + 디버깅 가능성 개선 Plan

**작성일:** 2026-05-26
**목적:** Stage 3 (Portfolio Allocator + candidate_selector + method_picker + optimizers + overlay_apply + sub_category) 의 4 차원 감사.
**선행:** Stage 1 audit (f877639...f809a30), Stage 2 audit (516a58d...acdee95), 이미 main 머지됨 (a38f790).

**Stage 1+2 deferred 흡수 (본 stage 에서 처리)**:
- method_picker / portfolio_allocator 의 regime/systemic_score 객체 **staleness_days 검사 0곳**. macro_quant/market_risk 가 sentinel(staleness=99) 로 만든 합성 객체가 그대로 optimizer 선택에 영향. **strict mode 또는 명시적 가시화 필요**.

---

## 0. Stage 3 특성 (Stage 1/2 와 차이)

- **LLM 호출 0회** (method_picker = 결정적 매핑, optimizer = pypfopt 수학)
- **이미 일부 logger 존재** (cov 표본, perf, overlay infeasible)
- **2 큰 코드 경로**: HRP per-bucket (직접 구현) vs EfficientFrontier (pypfopt)
- 방금 Stage 3 cluster-aware selection 머지됨 (PR eb1ceff, 2026-05-25). 그 위에서 추가 audit.
- attribution dict 구조 가장 풍부 (Stage 6 narrative 가 여기 의존)

---

## 1. 4 차원 (Stage 1/2 와 동일)

| 차원 | 무엇을 본다 |
|---|---|
| **L** | method_picker 의 staleness blind / overlay 5-level fallback silent / HRP water-filling cap-all shortfall / MIN_COV_OBS fallback ticker 누락 추적 부재 |
| **H** | 0.20 single cap, 0.05 retry band, 0.85 corr threshold, 60 MIN_COV_OBS, 3 longlist_mult, 0.30 TIPS baseline |
| **D** | safety_diagnostics (Stage 2) → Stage 3 소비 0, factor_contributions → Stage 3 소비 0. attribution dict 풍부하나 통합 schema 부재 |
| **O** | entry log, method 결정 후 실제 적용 method, cluster fallback 사용 여부, projection vs HRP 결과 trace |

---

## 2. 우선순위 & Task 순서

대회 5/28 마감 영향 큰 순서:

1. **Task 0 — Cross-cutting**: Stage 1+2 deferred 흡수. method_picker / portfolio_allocator 가 macro_report.regime / risk_report.systemic_score 의 staleness 를 명시적으로 검사 + 비정상 시 안전한 default. attribution 에 staleness 가시화.
2. **Task 1 — portfolio_allocator**: entry/exit log + safety_diag/factor_contributions 활용 + per_bucket_n/attempts/method trace. allocation_attribution dict 정리.
3. **Task 2 — method_picker**: inputs_trace 보강 + 8.0 systemic threshold named const + scenario_method downgrade 명시 logger.
4. **Task 3 — optimizers + _hrp_per_bucket**: cov 표본 부족 attribution 기록, single cap (0.20) named const, MIN_COV_OBS const, water-filling cap-all shortfall logger.
5. **Task 4 — overlay_apply**: 5-level escalation 가시화. final level / dropped constraints / fallback 사유 attribution + logger.
6. **Task 5 — 통합 sanity + 회귀**: 신규 integration test + Stage 3 audit summary.

---

## 3. 공통 패턴

A. 코드 정독 + 논리 점검 / B. 하드코딩 카탈로그 / C. 즉시 결함 수정 / D. observability 보강 / E. commit.

분석가별 1 commit. 회귀 매번 실행.

---

## 4. Task 0 — Cross-cutting: staleness 검사 + Stage 1+2 deferred 흡수

**Files:**
- `tradingagents/agents/allocator/portfolio_allocator.py` (entry, line 50-51)
- `tradingagents/skills/portfolio/method_picker.py` (line 87, regime/systemic 분기)

**Steps:**
- [ ] **0.1** allocator entry 에서 macro_report.regime.staleness_days, risk_report.systemic_score.staleness_days 검사. 둘 다 sentinel (≥99) 이면 attribution 에 `degraded_inputs: bool=True` 기록 + logger.warning.
- [ ] **0.2** method_picker 에 sentinel 입력 안전 기본값 명시: 둘 다 sentinel → **strict mode: MIN_VARIANCE 강제** (위험 회피). 추가 rule (rule_index=0, priority highest) 로 method_picker 분기 맨 앞 추가.
- [ ] **0.3** strict mode 발동 시 method_picker reasoning 에 명시 ("Both regime + systemic snapshots are sentinels — defensive MIN_VARIANCE").
- [ ] **0.4** allocator attribution["config"] 에 `regime_staleness`, `systemic_staleness` 추가.
- [ ] **0.5** commit: `audit(stage3): cross-cutting — staleness check at method_picker + allocator attribution [Task0]`.

**합격 기준:** Stage 1 의 sentinel snapshot 이 Stage 3 method 결정으로 silent 흡수 안 됨. degraded run 명시 가시화.

---

## 5. Task 1 — portfolio_allocator observability

**Files:**
- `tradingagents/agents/allocator/portfolio_allocator.py`

**Steps:**
- [ ] **1.1 — O** entry log: per_bucket_n, attempts, conviction, eligible ticker 수.
- [ ] **1.2 — D** Stage 2 의 safety_diagnostics (research_decision.safety_diagnostics) 를 attribution 에 thread + logger.warning 만약 mandate_violated_pre_projection / projection_intervened / extreme_factor_active 가 True.
- [ ] **1.3 — D** Stage 2 의 factor_contributions top-3 도 attribution["research_inputs"] 에 기록 (Stage 6 narrative 에 노출 가능).
- [ ] **1.4 — L** `_optimize_with_bucket_constraints` 의 cov 표본 부족 fallback (line 277-298) 의 excluded ticker 를 attribution 에도 기록 (현재 logger 만).
- [ ] **1.5 — L** 실제 적용 method (method_picker 결정 vs HRP 직접 실행 vs EF) 가 attribution 에 명확히 기록되는지 검증. 현재 method_picker.method 만 기록 — HRP 인지 EF 인지 trace.
- [ ] **1.6 — H** retry band 0.05 → `RETRY_BAND_WIDTH` const. MIN_COV_OBS=60 → const. single cap 0.20 → const.
- [ ] **1.7 — E** commit: `audit(stage3): portfolio_allocator — entry log + Stage 2 diag thread + named const [Task1]`.

**합격 기준:** allocator 결과 한 줄로 (a) 어느 method 적용, (b) Stage 2 safety_diag 어떻게, (c) 어떤 ticker 가 cov 부족으로 제외 trace 가능.

---

## 6. Task 2 — method_picker logger + const

**Files:**
- `tradingagents/skills/portfolio/method_picker.py`

**Steps:**
- [ ] **2.1 — H** systemic 극단 threshold 8.0, scenario downgrade conviction="low" rule → named const `SYSTEMIC_EXTREME_THRESHOLD`, `LOW_CONVICTION_HRP_DOWNGRADE = True`.
- [ ] **2.2 — O** 각 rule fire 시 logger.info 추가 (rule_fired + final method).
- [ ] **2.3 — D** inputs_trace 에 `regime_staleness`, `systemic_staleness` 추가 (Task 0 와 연계).
- [ ] **2.4 — L** scenario downgrade logic (line 110-112): HRP → RISK_PARITY 변경 시 logger 명시. attribution 에 `downgraded_from_hrp: bool` 기록.
- [ ] **2.5 — E** commit: `audit(stage3): method_picker — named const + per-rule logger + downgrade trace [Task2]`.

**합격 기준:** 어느 rule 가 fire 했는지 + 왜 그 method 인지 logger 만 봐도 명확.

---

## 7. Task 3 — optimizers + _hrp_per_bucket

**Files:**
- `tradingagents/agents/allocator/portfolio_allocator.py` (`_optimize_with_bucket_constraints`, `_hrp_per_bucket`)
- `tradingagents/skills/portfolio/optimizers.py` (108 lines, 직접 호출 거의 없음)

**Steps:**
- [ ] **3.1 — H** module-level const: `SINGLE_ASSET_CAP = 0.20`, `MIN_COV_OBS = 60`, `RETRY_BAND_WIDTH = 0.05`, `HRP_WATER_FILL_MAX_ITERS = 20`. 함수 시그니처 변경 없이 const 만.
- [ ] **3.2 — L** `_hrp_per_bucket` 의 water-filling cap-all 시점 (line ~458): 모든 자산이 cap 에 닿아서 bucket target 미충족 시 logger.warning + attribution 기록.
- [ ] **3.3 — L** `_optimize_with_bucket_constraints` 의 post-clip redistribute (line 343-358): cap clip 발동 시 attribution 기록.
- [ ] **3.4 — D** post-condition assertion 메시지 보강 (line 358, 519): 위반 자산 list 노출.
- [ ] **3.5 — E** commit: `audit(stage3): optimizer constraints — named const + cap-saturation logger [Task3]`.

**합격 기준:** cap 발동 / water-fill shortfall / cov 부족 모두 attribution + logger 에서 추적 가능.

---

## 8. Task 4 — overlay_apply 5-level escalation 가시화

**Files:**
- `tradingagents/agents/allocator/overlay_apply.py`

**Steps:**
- [ ] **4.1 — L** 5-level escalation 마다 logger.info 발동 level + dropped constraints (line ~150-220).
- [ ] **4.2 — D** 최종 success level (또는 all-fail) 을 attribution["overlay"] 에 기록: `final_level: int`, `dropped_constraints: list[str]`, `infeasible_levels: list[int]`.
- [ ] **4.3 — L** all-fail 시 Stage 3 결과 보존 사실을 logger.warning + attribution 에 명시.
- [ ] **4.4 — H** drop_level 5 단계 의미를 named enum 또는 const dict 로 정리.
- [ ] **4.5 — E** commit: `audit(stage3): overlay_apply escalation — visibility + attribution [Task4]`.

**합격 기준:** overlay 가 어느 level 에서 성공/실패했는지 attribution 만 봐도 trace.

---

## 9. Task 5 — Stage 3 통합 sanity

**Files:**
- `tests/integration/` 또는 신규 `tests/unit/agents/test_allocator_audit.py`

**Steps:**
- [ ] **5.1** 신규 integration test:
  - "regime + systemic 모두 sentinel → method_picker strict mode MIN_VARIANCE"
  - "Stage 2 safety_diag.projection_intervened → allocator attribution 에 thread"
  - "cap saturation → attribution 에 cap_violations list"
- [ ] **5.2** 전체 unit + integration regression: `pytest tests/unit tests/integration -q`. pre-existing 1 fail 제외 회귀 0.
- [ ] **5.3** `docs/stage3_audit.md` 작성 (Stage 1/2 와 동일 format).
- [ ] **5.4** commit: `audit(stage3): integration sanity + summary [Task5]`.

**합격 기준:** Stage 1+2 deferred (#1: method_picker staleness) 해결 + 신규 회귀 0 + audit summary.

---

## 10. Sign-off Checklist

- [ ] Task 0 — staleness 검사 + strict MIN_VARIANCE (Stage 1+2 deferred 해결)
- [ ] Task 1 — allocator observability + Stage 2 diag thread
- [ ] Task 2 — method_picker logger + named const
- [ ] Task 3 — optimizer named const + cap-saturation visibility
- [ ] Task 4 — overlay 5-level escalation 가시화
- [ ] Task 5 — integration sanity + summary
- [ ] `docs/stage3_audit.md` 작성

---

## 11. 범위 밖

- pypfopt 의 BlackLittermanModel views 자동 생성 → 별도 작업
- HRP cluster matrix 직접 활용 (Stage 4 risk_judge overlay) → 별도
- Single-cap 0.20 → 0.15 변경 (mandate change) → 별도
- TIPS baseline 0.30 tuning → backtest 필요

---

## 12. Risk

| Risk | Mitigation |
|---|---|
| Task 0 의 strict MIN_VARIANCE 가 정상 데이터에서도 발동 | sentinel 검사가 둘 다 ≥99 일 때만. 정상 1-7d stale 통과. |
| attribution 키 추가가 Stage 4-6 의 consumer 깨뜨림 | 키 추가만 (제거 없음). 기존 consumer 영향 0. |
| Task 4 의 overlay level 가시화 변경이 overlay 재시도 logic 깨뜨림 | logger 추가만, decision flow 불변. |
