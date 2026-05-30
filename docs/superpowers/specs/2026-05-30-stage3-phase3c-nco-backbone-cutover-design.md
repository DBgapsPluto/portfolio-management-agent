# Stage 3 Phase 3c — NCO Backbone Cutover Design

**Date:** 2026-05-30
**Stage:** 3 (Portfolio allocation)
**Phase:** 3c (NCO backbone cutover)
**Status:** Approved for implementation

## Goal

`method_picker` 의 모든 HRP 출력을 `NCO` 로 교체하여 NCO 를 production backbone 으로 cutover.

## Rationale

Phase 3a 에서 NCO (Lopez de Prado 2019) 가 `OptimizationMethod.NCO` enum + `compute_nco_weights` + `_nco_per_bucket` 으로 구현되고 force_method A/B 로 검증됨. Phase 3c 는 method_picker rule 의 HRP 출력 5 곳을 NCO 로 교체해 NCO 를 default + 4 scenario 의 production method 로 격상.

## Scope

### In-scope (6 변경)

1. `_SCENARIO_METHOD["overheating"]`: HRP → NCO
2. `_SCENARIO_METHOD["goldilocks"]`: HRP → NCO
3. `_SCENARIO_METHOD["ai_concentration"]`: HRP → NCO
4. `_SCENARIO_METHOD["kr_boom"]`: HRP → NCO
5. `LOW_CONVICTION_HRP_DOWNGRADE` 상수 + scenario_mapping rule 의 downgrade 블록 제거
6. Rule 7 default: HRP → NCO

### Out-of-scope

- `OptimizationMethod.HRP` enum 자체 제거 (Phase 3d 검토 — A/B `force_method="hrp"` 유지 위해 보존)
- `_hrp_per_bucket`, allocator HRP 분기 코드 제거 (Phase 3d)
- MV/RP 사용처 제거 (defensive rule 로 그대로 유지)
- backtest 검증 (별도 Phase)
- 9 bucket 전환 (Stage 2)

## Architecture

```
                   BEFORE (Phase 3b)                  AFTER (Phase 3c)
─────────────────────────────────────────────────────────────────────
rule 0 degraded_inputs            → MV               → MV (unchanged)
rule 1 systemic_extreme           → MV               → MV (unchanged)
rule 2 bl_high_confidence         → BL               → BL (unchanged)
rule 3 scenario_mapping
  global_credit                   → MV               → MV (unchanged)
  broad_recession                 → MV               → MV (unchanged)
  kr_stress                       → MV               → MV (unchanged)
  stagflation                     → RP               → RP (unchanged)
  overheating                     → HRP              → NCO ★
  goldilocks                      → HRP              → NCO ★
  late_cycle                      → RP               → RP (unchanged)
  ai_concentration                → HRP              → NCO ★
  kr_boom                         → HRP              → NCO ★
  + LOW_CONVICTION_HRP_DOWNGRADE  (HRP+low → RP)     → 제거 ★
rule 4 regime_recession           → MV               → MV (unchanged)
rule 5 systemic_risk_off          → MV               → MV (unchanged)
rule 6 regime_growth_inflation    → RP               → RP (unchanged)
rule 7 default                    → HRP              → NCO ★
```

Method precedence (실제 발동 순서): BL > NCO > MV/RP > HRP (HRP 는 force_method 호출 시만).

## Components

### `tradingagents/skills/portfolio/method_picker.py`

**(a) `LOW_CONVICTION_HRP_DOWNGRADE` 상수 제거** (현재 line 31):

```python
# 제거:
LOW_CONVICTION_HRP_DOWNGRADE: bool = True
```

**(b) `_SCENARIO_METHOD` 4 cell 변경**:

```python
_SCENARIO_METHOD: dict[str, tuple[OptimizationMethod, str]] = {
    "global_credit":    (OptimizationMethod.MIN_VARIANCE, <기존 reason 그대로>),
    "broad_recession":  (OptimizationMethod.MIN_VARIANCE, <기존 reason 그대로>),
    "kr_stress":        (OptimizationMethod.MIN_VARIANCE, <기존 reason 그대로>),
    "stagflation":      (OptimizationMethod.RISK_PARITY, <기존 reason 그대로>),
    "overheating":      (OptimizationMethod.NCO,
                         "overheating (growth+inflation) → equity tilt + 분산, NCO"),
    "goldilocks":       (OptimizationMethod.NCO,
                         "goldilocks → 분산 친화, NCO"),
    "late_cycle":       (OptimizationMethod.RISK_PARITY, <기존 reason 그대로>),
    "ai_concentration": (OptimizationMethod.NCO,
                         "ai_concentration → narrow leadership 위험, NCO로 corr 감안"),
    "kr_boom":          (OptimizationMethod.NCO,
                         "kr_boom → KR 호황 분산, NCO"),
}
```

**(c) `scenario_mapping` rule 의 downgrade 블록 제거**:

변경 전:
```python
if scenario_in and scenario_in in _SCENARIO_METHOD:
    method, reason = _SCENARIO_METHOD[scenario_in]
    downgraded = False
    if (
        LOW_CONVICTION_HRP_DOWNGRADE
        and conviction_in == "low"
        and method == OptimizationMethod.HRP
    ):
        method = OptimizationMethod.RISK_PARITY
        reason = f"{scenario_in} but low conviction → risk_parity downgrade"
        downgraded = True
    inputs_trace["downgraded_from_hrp"] = downgraded
    choice = MethodChoice(
        method=method,
        reasoning=f"scenario={scenario_in}, conviction={conviction_in}: {reason}"[:300],
        rule_fired="scenario_mapping",
        rule_index=3,
        inputs=inputs_trace,
    )
    logger.info(
        "method_picker rule 3 (scenario=%s, conviction=%s) → %s%s",
        scenario_in, conviction_in, method.value,
        " (HRP downgraded to RISK_PARITY)" if downgraded else "",
    )
    return choice
```

변경 후:
```python
if scenario_in and scenario_in in _SCENARIO_METHOD:
    method, reason = _SCENARIO_METHOD[scenario_in]
    choice = MethodChoice(
        method=method,
        reasoning=f"scenario={scenario_in}, conviction={conviction_in}: {reason}"[:300],
        rule_fired="scenario_mapping",
        rule_index=3,
        inputs=inputs_trace,
    )
    logger.info(
        "method_picker rule 3 (scenario=%s, conviction=%s) → %s",
        scenario_in, conviction_in, method.value,
    )
    return choice
```

제거:
- `downgraded` local var
- `LOW_CONVICTION_HRP_DOWNGRADE` 참조 if 블록
- `inputs_trace["downgraded_from_hrp"]` 기록 (downgrade 개념 자체가 사라짐)

**(d) Rule 7 default HRP → NCO**:

```python
choice = MethodChoice(
    method=OptimizationMethod.NCO,
    reasoning=(
        f"default NCO (regime={regime_quadrant}, "
        f"systemic={systemic_score:.1f}/{systemic_regime})"
    )[:300],
    rule_fired="default",
    rule_index=7,
    inputs=inputs_trace,
)
logger.info(
    "method_picker rule 7 (default, regime=%s, systemic=%.1f/%s) → NCO",
    regime_quadrant, systemic_score, systemic_regime,
)
```

### Implementation note on `downgraded_from_hrp` attribution key

`grep -rn "downgraded_from_hrp"` 으로 downstream 소비처 확인 필요. Stage 6 narrative 등이 이 key 를 읽으면 KeyError 가능. 사용처 발견 시 함께 제거.

## Edge Cases

| Case | Before (Phase 3b) | After (Phase 3c) |
|---|---|---|
| `scenario=None`, low confidence | rule 7 → HRP | rule 7 → NCO |
| `scenario="overheating"`, high confidence (≥0.7) | rule 2 BL trigger → BL | rule 2 BL trigger → BL (no change) |
| `scenario="overheating"`, low confidence | rule 3 → HRP | rule 3 → NCO |
| `scenario="goldilocks"`, conviction=low | rule 3 → RP (downgrade) | rule 3 → NCO (no downgrade) |
| `scenario="stagflation"` | rule 3 → RP | rule 3 → RP (unchanged) |
| `scenario="broad_recession"` | rule 3 → MV | rule 3 → MV (unchanged) |
| `force_method="hrp"` | allocator `_hrp_per_bucket` 직접 호출 | unchanged (코드 유지) |
| `force_method="nco"` | NCO | unchanged |
| `degraded_inputs=True` | rule 0 → MV | unchanged |

**핵심**: BL trigger 가 우선이므로 `regime_confidence ≥ 0.7` + known scenario 인 경우 NCO 가 안 보임. NCO 발동 영역:
- low confidence (<0.7) + 4 NCO scenario
- low confidence + 알 수 없는 scenario (default)

E2E 실 데이터 (regime_conf=0.91) 에서는 BL 이 계속 트리거. NCO backbone cutover 의 가시적 효과는 unit/integration test 에서 검증.

## Testing Strategy

### Unit tests — `tests/unit/skills/test_portfolio_method_picker.py` (MODIFY)

**갱신 (HRP → NCO 기대값)**:
- `test_picker_default_regime_returns_hrp` → NCO
- `test_picker_scenario_overheating_returns_hrp` → NCO
- `test_picker_scenario_goldilocks_returns_hrp` → NCO
- `test_picker_scenario_ai_concentration_returns_hrp` → NCO
- `test_picker_scenario_kr_boom_returns_hrp` → NCO
- 정확한 test 이름은 grep 으로 발견 후 갱신

**제거**:
- `LOW_CONVICTION_HRP_DOWNGRADE` 관련 test (예: `test_picker_low_conviction_downgrades_hrp_to_rp`)

**신규 7 tests**:

1. `test_picker_default_regime_returns_nco` — scenario=None, regime_quadrant=growth_disinflation → NCO
2. `test_picker_overheating_returns_nco` — scenario="overheating", confidence<0.7 → NCO
3. `test_picker_goldilocks_returns_nco` — same for goldilocks
4. `test_picker_ai_concentration_returns_nco` — same for ai_concentration
5. `test_picker_kr_boom_returns_nco` — same for kr_boom
6. `test_picker_low_conviction_does_not_downgrade_nco` — overheating + conviction=low + confidence<0.7 → NCO (RP 아님)
7. `test_picker_no_downgrade_flag_in_inputs_trace` — `downgraded_from_hrp` key 부재

### Integration tests — `tests/integration/test_allocator_phase3c.py` (NEW, 3 tests)

1. `test_allocator_default_method_is_nco_when_no_scenario` — scenario=None, low confidence → method=nco
2. `test_allocator_overheating_scenario_uses_nco` — scenario=overheating, low confidence → method=nco
3. `test_allocator_low_conviction_no_downgrade` — overheating + conviction=low + low confidence → method=nco (not rp downgrade)

### Regression (Phase 1/2a/2b/3a/3b)

기존 통합 테스트 전수 PASS. 실패 시:
- helper 의 default scenario 가 NCO 대상이면 method assertion 갱신
- 이전 HRP 출력을 가정한 테스트는 NCO 로 수정

### E2E

regime_conf=0.91 → BL 계속 트리거. method label 동일 (black_litterman). 회귀 무손실 — 단 BL trigger 조건 안 되는 데이터에선 method 가 HRP → NCO 로 바뀜.

### Acceptance criteria

| # | Criterion | Verification |
|---|---|---|
| (a) | _SCENARIO_METHOD 의 4 NCO 매핑 | unit tests 2-5 |
| (b) | default rule NCO | unit test 1 |
| (c) | downgrade 제거 | unit tests 6-7 |
| (d) | Phase 3c integration | 3 new integration tests |
| (e) | E2E 회귀 (BL trigger 시 변화 없음) | regression check |
| (f) | 기존 250+ tests PASS | full regression |

총 10 신규 test (7 unit + 3 integration). Phase 3a (27) / 3b (23) 보다 훨씬 작음 — backbone cutover 의 단순성 반영.

## Related Memory

- [[stage3_phase3a_followup]] — NCO bucket-internal optimizer + force_method A/B (Phase 3c 의 backbone)
- [[stage3_phase3b_followup]] — BL trigger rule_index=2, BL_TRIGGER_CONFIDENCE=0.7 (NCO 보다 우선)
- [[stage3_phase2b_followup]] — ENB greedy + candidates per bucket (NCO 의 입력)
