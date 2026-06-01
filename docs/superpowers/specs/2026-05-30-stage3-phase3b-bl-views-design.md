# Stage 3 Phase 3b — Black-Litterman Views Adapter Design

**Date:** 2026-05-30
**Stage:** 3 (Portfolio allocation)
**Phase:** 3b (Black-Litterman views adapter + method_picker BL rule)
**Status:** Approved for implementation

## Goal

`OptimizationMethod.BLACK_LITTERMAN` 분기를 dead code 상태(views 빈 dict → historical 폴백)에서 live optimizer 로 활성화한다. 그를 위해:

1. Stage 2 의 `scenario` + `regime_confidence` 에서 BL views (P, Q, confidence) 를 결정적으로 생성하는 adapter (`bl_views.py`) 를 신규 구현.
2. `method_picker` 에 BL trigger rule 을 추가해 `regime_confidence ≥ threshold` 인 scenario 에서 BL 이 자동 선택되게 한다.
3. `portfolio_allocator` 의 BL 분기를 sentinel 기반으로 적절히 views 를 주입하도록 수정.

Phase 3a 의 `state["force_method"]` A/B 메커니즘 위에서 BL 도 A/B 테스트 가능.

## Scope

### In-scope
- `tradingagents/skills/portfolio/bl_views.py` (신규 모듈)
  - `SCENARIO_BUCKET_RULEBOOK`: 9 scenario × 5 bucket → expected return matrix
  - `BL_VIEW_MIN_CONFIDENCE`: confidence floor 상수
  - `generate_bl_views(...)`: views/confidence 결정적 생성
- `tradingagents/skills/portfolio/method_picker.py` 변경
  - `BL_TRIGGER_CONFIDENCE` 상수 추가 (기본 0.7)
  - rule 1 (systemic_extreme) 과 rule 2 (scenario_mapping) 사이에 BL trigger rule 삽입 (scenario_mapping 보다 먼저 평가)
- `tradingagents/agents/allocator/portfolio_allocator.py` 변경
  - BL 분기: `_bl_trigger` sentinel 시 `generate_bl_views` 호출
  - `attribution["bl_views_breakdown"]`, `attribution["bl_views_fallback"]` 기록
- 신규 단위 테스트: `tests/unit/skills/test_portfolio_bl_views.py`
- 기존 단위 테스트 확장: `tests/unit/skills/test_method_picker.py`
- 신규 통합 테스트: `tests/integration/test_allocator_phase3b.py`

### Out-of-scope (Phase 3c)
- method_picker 의 tilt dial (HRP/NCO/BL 비중 조정)
- 5 method 제거 (MIN_VARIANCE/RISK_PARITY/MAX_SHARPE 등 deprecation)
- 9-bucket 확장에 따른 rulebook 셀 추가 (Stage 2 9-bucket 완료 시 별도 commit)
- Backtest 검증으로 BL alpha 입증 (별도 Phase)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Stage 2 outputs                                            │
│    regime_quadrant / regime_confidence /                    │
│    dominant_scenario (9 scenario) / candidates per bucket   │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Phase 3b: BL Views Adapter (NEW)                            │
│    tradingagents/skills/portfolio/bl_views.py                │
│      SCENARIO_BUCKET_RULEBOOK + generate_bl_views(...)       │
│    → (absolute_views: dict[ticker,ret], view_confidences)    │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  method_picker (MODIFIED)                                    │
│    rule 1 (systemic_extreme) → rule 2 (bl_high_confidence,   │
│    NEW) → rule 3 (scenario_mapping) → rule 4 ...             │
│    IF regime_confidence ≥ BL_TRIGGER_CONFIDENCE              │
│       AND scenario in SCENARIO_BUCKET_RULEBOOK               │
│    → MethodChoice(BLACK_LITTERMAN,                           │
│                    params={"_bl_trigger": True})             │
└──────────────────────┬──────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  portfolio_allocator (EXISTING BL branch 활성화)              │
│    if method_params["_bl_trigger"]: generate_bl_views(...)   │
│    BlackLittermanModel(omega="idzorek") → max_sharpe         │
└─────────────────────────────────────────────────────────────┘
```

## Components

### `tradingagents/skills/portfolio/bl_views.py` (NEW)

```python
SCENARIO_BUCKET_RULEBOOK: dict[str, dict[str, float]] = {
    "goldilocks":       {"kr_equity": 0.10, "global_equity": 0.12,
                         "fx_commodity": 0.02, "bond": 0.04,  "cash_mmf": 0.025},
    "overheating":      {"kr_equity": 0.06, "global_equity": 0.08,
                         "fx_commodity": 0.10, "bond": 0.02,  "cash_mmf": 0.025},
    "late_cycle":       {"kr_equity": 0.02, "global_equity": 0.04,
                         "fx_commodity": 0.08, "bond": 0.06,  "cash_mmf": 0.025},
    "stagflation":      {"kr_equity": -0.05, "global_equity": -0.03,
                         "fx_commodity": 0.12, "bond": 0.01,  "cash_mmf": 0.025},
    "broad_recession":  {"kr_equity": -0.08, "global_equity": -0.05,
                         "fx_commodity": -0.02, "bond": 0.08, "cash_mmf": 0.025},
    "kr_stress":        {"kr_equity": -0.10, "global_equity": 0.05,
                         "fx_commodity": 0.03, "bond": 0.05,  "cash_mmf": 0.025},
    "global_credit":    {"kr_equity": -0.05, "global_equity": -0.08,
                         "fx_commodity": -0.02, "bond": 0.07, "cash_mmf": 0.025},
    "ai_concentration": {"kr_equity": 0.05, "global_equity": 0.10,
                         "fx_commodity": 0.02, "bond": 0.03,  "cash_mmf": 0.025},
    "kr_boom":          {"kr_equity": 0.13, "global_equity": 0.08,
                         "fx_commodity": 0.02, "bond": 0.03,  "cash_mmf": 0.025},
}

BL_VIEW_MIN_CONFIDENCE: float = 0.10

def generate_bl_views(
    *,
    scenario: str,
    regime_confidence: float,
    candidates: dict[str, list[str]],
    sub_category_lookup: dict[str, str] | None = None,
    breakdown_out: dict | None = None,
) -> tuple[dict[str, float], list[float]]:
    """
    Generate absolute Black-Litterman views from regime/scenario rulebook.

    Each ticker in bucket B gets rulebook[scenario][B] as its absolute view return.
    Each view's confidence = max(regime_confidence, BL_VIEW_MIN_CONFIDENCE).

    Returns:
        absolute_views: {ticker: expected_return}
        view_confidences: list[float] (parallel to absolute_views.items())
        Returns ({}, []) when scenario unknown to rulebook (caller falls back
        to historical mu).
    """
```

**Rulebook 설계 원칙**:
- 9 scenario (Stage 2 dominant_scenario 의 완전 집합) × 5 bucket (Stage 3 현재 구조)
- 값: 연환산 expected return (decimal).
- cash_mmf 는 KOFR 근방 (0.025) 고정 — Stage 2 scenario 의 영향 최소.
- 합리 범위: -0.30 ≤ ret ≤ 0.30 (unit test 로 검증).
- bucket-agnostic 코드: candidates 의 bucket 이 rulebook 에 없으면 skip → 9-bucket 확장 시 rulebook 만 추가하면 됨.

### `tradingagents/skills/portfolio/method_picker.py` (MODIFIED)

**모듈 상단에 신규 상수**:
```python
BL_TRIGGER_CONFIDENCE: float = 0.7
```

**Import**:
```python
from tradingagents.skills.portfolio.bl_views import SCENARIO_BUCKET_RULEBOOK
```

**Rule 추가 위치**: 기존 rule 1 (systemic_extreme) 다음, rule 2 (scenario_mapping) 앞.

이유: scenario_mapping 이 매칭되면 즉시 return 되므로, BL trigger 가 scenario_mapping 뒤에 있으면 도달 불가. BL 은 "high confidence + known scenario" 인 경우에만 우선 트리거하고, 그 외엔 기존 scenario_mapping 으로 폴백되어야 함.

```python
# 2. Phase 3b: Black-Litterman trigger (scenario_mapping 보다 먼저 평가)
if (
    scenario_in
    and regime_confidence >= BL_TRIGGER_CONFIDENCE
    and scenario_in in SCENARIO_BUCKET_RULEBOOK
):
    choice = MethodChoice(
        method=OptimizationMethod.BLACK_LITTERMAN,
        reasoning=(
            f"regime_confidence={regime_confidence:.2f} ≥ {BL_TRIGGER_CONFIDENCE}"
            f", scenario={scenario_in}: BL views from rulebook"
        )[:300],
        rule_fired="bl_high_confidence",
        rule_index=2,
        inputs=inputs_trace,
        params={"_bl_trigger": True},
    )
    logger.info(
        "method_picker rule 2 (bl_high_confidence): confidence=%.2f scenario=%s → BL",
        regime_confidence, scenario_in,
    )
    return choice

# 3. Stage 2 dominant scenario (기존 rule 2, 이제 rule_index 3)
if scenario_in and scenario_in in _SCENARIO_METHOD:
    # ... 기존 로직, rule_index=3 으로 변경 ...
```

**rule_index 정책**:
- 기존 rule 1 (systemic_extreme): `rule_index=1` 유지.
- 새 BL trigger rule: `rule_fired="bl_high_confidence"`, `rule_index=2`.
- 기존 rule 2 (scenario_mapping) → `rule_index=3`. 기존 rule 3 (regime_recession) → `rule_index=4`. 이하 모두 +1 시프트.
- `rule_index` 는 attribution trace 용 — 본질 식별자는 `rule_fired` 이름. 기존 테스트가 rule_index 정수 값을 hard-code 하면 같이 수정.

### `tradingagents/agents/allocator/portfolio_allocator.py` (MODIFIED)

BL 분기 (기존 553 line) 수정:

```python
if method == OptimizationMethod.BLACK_LITTERMAN:
    from pypfopt import BlackLittermanModel
    from tradingagents.skills.portfolio.bl_views import generate_bl_views

    if method_params.get("_bl_trigger"):
        bl_breakdown: dict = {}
        views, confs = generate_bl_views(
            scenario=scenario,
            regime_confidence=regime_confidence,
            candidates=candidates_per_bucket,
            sub_category_lookup=sub_category_lookup,
            breakdown_out=bl_breakdown,
        )
        if attribution is not None:
            attribution["bl_views_breakdown"] = bl_breakdown
    else:
        views = method_params.get("views", {})
        confs = method_params.get("view_confidences", [])

    if views:
        bl = BlackLittermanModel(
            S, absolute_views=views, omega="idzorek", view_confidences=confs,
        )
        mu = bl.bl_returns()
    else:
        mu = expected_returns.mean_historical_return(returns, returns_data=True)
        if attribution is not None:
            attribution["bl_views_fallback"] = "empty_views_historical_fallback"
```

**호출 인자 확보**: allocator 의 진입점에서 state 로부터 `scenario`, `regime_confidence`, `candidates_per_bucket`, `sub_category_lookup` 을 받아 BL 분기 호출 컨텍스트로 전달. 기존 코드에서 어떻게 접근 가능한지는 implementation plan 에서 정확한 변수명/경로로 확인.

## Algorithm & Edge Cases

### `generate_bl_views` 알고리즘

```
1. If scenario not in SCENARIO_BUCKET_RULEBOOK:
     breakdown_out["fallback_reason"] = "unknown_scenario"
     return ({}, [])

2. bucket_returns = SCENARIO_BUCKET_RULEBOOK[scenario]
   conf_value = max(regime_confidence, BL_VIEW_MIN_CONFIDENCE)

3. absolute_views, view_confidences = {}, []
   n_per_bucket = {}
   for bucket, tickers in candidates.items():
       if bucket not in bucket_returns:
           continue  # bucket-agnostic
       expected_ret = bucket_returns[bucket]
       for ticker in tickers:
           absolute_views[ticker] = expected_ret
           view_confidences.append(conf_value)
       n_per_bucket[bucket] = len(tickers)

4. If breakdown_out:
     breakdown_out["scenario"] = scenario
     breakdown_out["regime_confidence_raw"] = regime_confidence
     breakdown_out["confidence_used"] = conf_value
     breakdown_out["n_views_per_bucket"] = n_per_bucket
     breakdown_out["rulebook_returns_used"] = {
         b: bucket_returns[b] for b in n_per_bucket
     }

5. return (absolute_views, view_confidences)
```

### Edge cases

| Case | Behavior |
|---|---|
| `scenario=None` | method_picker 의 `scenario_in in RULEBOOK` 가 False → BL trigger rule fail → 다음 rule. adapter 직접 호출 시 `({}, [])` |
| scenario 알려졌지만 RULEBOOK 에 없음 | adapter 가 `({}, [])` 반환, `fallback_reason="unknown_scenario"` |
| `regime_confidence=0.0` | `BL_VIEW_MIN_CONFIDENCE=0.10` floor. method_picker rule 의 ≥0.7 threshold 에선 트리거 안 됨 |
| candidates bucket 이 rulebook 에 없음 (9-bucket 확장) | 해당 bucket skip, 다른 bucket 만 view 생성 |
| `candidates={}` | `({}, [])` → allocator historical 폴백 |
| pypfopt numerical 오류 | 기존 try/except 가 RuntimeError 변환 → validator retry. 추가 처리 없음 |
| `force_method="black_litterman"` + scenario unknown | allocator 분기에서 `_bl_trigger=False`, `method_params["views"]` 빈 dict → historical 폴백, `bl_views_fallback` 기록 |

### Numerical safety

- `omega="idzorek"` 는 pypfopt 내장 (Idzorek-Walters 2014 closed form, numerical 검증됨).
- view_confidences 가 모두 동일 값 → Ω diagonal → well-conditioned.
- 작은 universe (n_views < n_assets) 는 pypfopt 가 처리.

### Regression 무손실

- BL trigger threshold `regime_confidence ≥ 0.7` 가 높음.
- 기존 e2e 의 regime_confidence 는 보통 0.5-0.6 — Phase 3b 도입해도 트리거 안 됨.
- Default e2e (force_method 없음) → Phase 3a 와 동일 method 선택, 동일 weights.

## Testing Strategy

### Unit tests — `tests/unit/skills/test_portfolio_bl_views.py` (NEW, 9 tests)

1. `test_rulebook_covers_all_scenarios` — SCENARIO_BUCKET_RULEBOOK key 가 method_picker `_SCENARIO_METHOD` key 와 일치
2. `test_rulebook_returns_finite_decimals` — 모든 cell finite, |ret| ≤ 0.30
3. `test_generate_bl_views_known_scenario_basic` — scenario="goldilocks", confidence=0.8
4. `test_generate_bl_views_unknown_scenario_returns_empty` — `({}, [])`, fallback_reason
5. `test_generate_bl_views_confidence_floor` — regime_confidence=0.05 → 0.10 floor
6. `test_generate_bl_views_bucket_agnostic` — unknown bucket skip
7. `test_generate_bl_views_empty_candidates` — `candidates={}` → `({}, [])`
8. `test_generate_bl_views_records_breakdown` — breakdown_out 의 모든 키
9. `test_generate_bl_views_ticker_returns_match_bucket_rulebook` — view[ticker] = rulebook[scenario][bucket]

### Method picker unit tests — `tests/unit/skills/test_method_picker.py` (MODIFY, 4 tests 추가)

10. `test_picker_bl_trigger_high_confidence_known_scenario` — regime_confidence=0.8, scenario="goldilocks" → BLACK_LITTERMAN, rule_fired="bl_high_confidence", params={"_bl_trigger": True}
11. `test_picker_bl_not_triggered_low_confidence` — regime_confidence=0.5, scenario="goldilocks" → scenario_mapping → HRP
12. `test_picker_bl_not_triggered_unknown_scenario` — regime_confidence=0.9, scenario=None → 다음 rule
13. `test_picker_bl_trigger_precedes_scenario_mapping` — BL trigger rule 이 scenario_mapping 보다 먼저 평가 (rule order regression 방지)

### Integration tests — `tests/integration/test_allocator_phase3b.py` (NEW, 7 tests)

14. `test_allocator_with_method_bl_runs_to_completion`
15. `test_allocator_bl_attribution_records_breakdown`
16. `test_allocator_bl_respects_single_asset_cap`
17. `test_allocator_bl_high_confidence_triggers_via_picker`
18. `test_allocator_bl_low_confidence_falls_through_to_hrp`
19. `test_allocator_bl_unknown_scenario_with_force_method_falls_back`
20. `test_allocator_bl_vs_hrp_same_inputs_different_weights`

### Regression

21. Default e2e (force_method 없음, 2026-05-15) → Phase 3a 와 동일 method (회귀 무손실)
22. `--force-method black_litterman` e2e → method=bl, rule_fired=state_override, attribution.bl_views_breakdown
23. 기존 228+ tests (Phase 1/2a/2b/3a integration + unit) → 모두 PASS

### Acceptance criteria

| # | Criterion | Verification |
|---|---|---|
| (a) | Adapter 단독 동작 | unit 1-9 |
| (b) | method_picker BL trigger | unit 10-13 |
| (c) | Allocator BL live 동작 | integration 14-20 |
| (d) | Default e2e 회귀 무손실 | regression 21 |
| (e) | A/B 메커니즘 (force_method=bl) | regression 22 |
| (f) | 기존 228+ tests PASS | regression 23 |

총 23 test (9 unit BL + 4 unit picker + 7 integration + 3 regression).

## Related Memory

- [[stage3_phase3a_followup]] — NCO + force_method A/B 메커니즘 (Phase 3b 가 동일 구조 활용)
- [[stage3_phase2b_followup]] — ENB greedy + adaptive n_max + candidates per bucket (Phase 3b 의 입력)
- [[stage3_audit_deferred]] — "BL views 자동" (잔존 #1) 해소
