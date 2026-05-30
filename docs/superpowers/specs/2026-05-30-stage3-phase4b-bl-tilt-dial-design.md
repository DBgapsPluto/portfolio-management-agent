# Stage 3 Phase 4b — Black-Litterman Tilt Dial Design

**Date:** 2026-05-30
**Stage:** 3 (Portfolio allocation)
**Phase:** 4b (BL tilt dial — regime별 τ + view_conf multiplier)
**Status:** Approved for implementation

## Goal

Phase 3b 의 고정 `view_confidences = [regime_confidence] × n_views` 와 pypfopt default `tau=0.05` 를 regime/scenario 별로 differentiated tilt dial 로 교체. growth scenario 는 BL 강하게 (τ↑, view_multi↑), defensive scenario 는 prior 우세 (τ↓, view_multi↓).

## Rationale

Phase 3b BL trigger 의 `regime_confidence` 만으로는 "scenario 가 view 를 얼마나 신뢰해야 하는지" 의 정보가 미반영. 동일 0.91 confidence 라도 goldilocks 에서는 view 우세, broad_recession 에서는 prior 우세가 자연스러움. Idzorek-Walters Ω 의 입력 (view_confidence) 과 BL 의 prior uncertainty (τ) 를 scenario × (τ, multi) 매트릭스로 dial 화하면 동일 BL 분기에서 scenario-aware tilt 가 가능.

## Scope

### In-scope

1. `tradingagents/skills/portfolio/bl_views.py`:
   - `SCENARIO_BL_TILT` 매트릭스 신규 (9 scenario × {tau, view_conf_multi})
   - 상수 4종: `BL_VIEW_CONF_MIN_AFTER_MULTI=0.05`, `BL_VIEW_CONF_MAX_AFTER_MULTI=1.0`, `BL_TAU_DEFAULT=0.05`, `BL_VIEW_CONF_MULTI_DEFAULT=1.0`
   - `generate_bl_views` 시그니처 확장: return tuple [2] → [3] (tilt_params 추가)
2. `tradingagents/agents/allocator/portfolio_allocator.py`:
   - BL 분기에서 `tilt_params` 받아 `tau=tilt_params["tau"]` 전달
   - `view_confidences` 는 generate_bl_views 가 이미 multi 적용 후 반환
   - force_method 외부 주입 경로는 tilt 비적용 (`view_conf_multi_applied=False`)
3. attribution.bl_views_breakdown 에 `tilt_params` 노출

### Out-of-scope

- δ (risk aversion) dial — Phase 4c 검토
- prior π 명시 (pypfopt default historical) — 별도 phase
- 9 bucket 전환 시 RULEBOOK 확장 (Stage 2)
- backtest 검증

## Architecture

```
                BEFORE (Phase 3b/4a)              AFTER (Phase 4b)
─────────────────────────────────────────────────────────────────────
bl_views.py:
  SCENARIO_BUCKET_RULEBOOK         unchanged
  generate_bl_views() returns      (views, confs, tilt_params)
    (views, confs)
  + SCENARIO_BL_TILT (NEW)         9 scenario × {tau, view_conf_multi}

allocator BL 분기:
  BlackLittermanModel(             BlackLittermanModel(
    S, absolute_views,               S, absolute_views,
    omega="idzorek",                 omega="idzorek",
    view_confidences=confs           view_confidences=confs (pre-clipped),
  )                                  tau=tilt_params["tau"],
                                   )

attribution.bl_views_breakdown:
  + "tilt_params": {                ← NEW
      "tau": 0.05,
      "view_conf_multi": 0.8,
      "view_conf_multi_applied": true,
    }
```

## Components

### `tradingagents/skills/portfolio/bl_views.py`

**(a) 상수 신규 (module top)**:

```python
# Idzorek-Walters Ω 안정성 boundary (post-multiplier clipping)
BL_VIEW_CONF_MIN_AFTER_MULTI: float = 0.05
BL_VIEW_CONF_MAX_AFTER_MULTI: float = 1.0

# Unknown scenario fallback (Phase 3b 동작 보존)
BL_TAU_DEFAULT: float = 0.05
BL_VIEW_CONF_MULTI_DEFAULT: float = 1.0
```

**(b) `SCENARIO_BL_TILT` 매트릭스**:

```python
# 9 scenario × (tau, view_conf_multi)
# tau ∈ [0.025, 0.10] (pypfopt default 0.05 기준 ±2x)
# view_conf_multi ∈ [0.5, 1.5] (post-multiplier clip [0.05, 1.0])
SCENARIO_BL_TILT: dict[str, dict[str, float]] = {
    "goldilocks":       {"tau": 0.10, "view_conf_multi": 1.3},
    "kr_boom":          {"tau": 0.10, "view_conf_multi": 1.3},
    "overheating":      {"tau": 0.07, "view_conf_multi": 1.0},
    "ai_concentration": {"tau": 0.07, "view_conf_multi": 1.0},
    "late_cycle":       {"tau": 0.05, "view_conf_multi": 0.8},
    "stagflation":      {"tau": 0.05, "view_conf_multi": 0.7},
    "broad_recession":  {"tau": 0.025, "view_conf_multi": 0.5},
    "kr_stress":        {"tau": 0.025, "view_conf_multi": 0.5},
    "global_credit":    {"tau": 0.025, "view_conf_multi": 0.5},
}
```

**dial 의 의미**:
- growth scenario (goldilocks/kr_boom): τ=0.10 (prior uncertainty 큼 → view 우세), multi=1.3 → BL 강함
- 중간 (overheating/ai_concentration): τ=0.07, multi=1.0 — pypfopt default 보다 살짝 강함
- 약간 보수 (late_cycle/stagflation): τ=0.05, multi=0.7-0.8 — view 약화
- 강한 보수 (broad_recession/kr_stress/global_credit): τ=0.025, multi=0.5 — prior 우세

**(c) `generate_bl_views` 시그니처 변경**:

```python
def generate_bl_views(
    *,
    scenario: str | None,
    regime_confidence: float,
    candidates: dict[str, list[str]],
    sub_category_lookup: dict[str, str] | None = None,
    breakdown_out: dict | None = None,
) -> tuple[dict[str, float], list[float], dict[str, float]]:
    """
    Returns:
        absolute_views: {ticker: expected_return}
        view_confidences: list[float] — post-multiplier, clipped [0.05, 1.0]
        tilt_params: {"tau": τ, "view_conf_multi": m, "view_conf_multi_applied": bool}

    Unknown scenario: returns ({}, [], {tau:0.05, multi:1.0, applied:False}).
    """
```

**(d) 흐름 변경**:

```
1. (기존) scenario in RULEBOOK 확인. unknown → 빈 결과 + default tilt
2. (기존) bucket_returns + conf_value (= max(regime_confidence, FLOOR))
3. (NEW) tilt = SCENARIO_BL_TILT.get(scenario, default_tilt)
4. (기존) views 생성, raw_confs (= [conf_value] × n_views)
5. (NEW) post_multi = [c × tilt["view_conf_multi"] for c in raw_confs]
6. (NEW) view_confidences = [clip(c, BL_VIEW_CONF_MIN_AFTER_MULTI,
                                      BL_VIEW_CONF_MAX_AFTER_MULTI)
                                    for c in post_multi]
7. (NEW) tilt_params = {"tau": tilt["tau"],
                        "view_conf_multi": tilt["view_conf_multi"],
                        "view_conf_multi_applied": True}
8. (NEW) breakdown_out["tilt_params"] = tilt_params (if breakdown_out)
9. return (views, view_confidences, tilt_params)
```

### `tradingagents/agents/allocator/portfolio_allocator.py`

BL 분기 (current line ~567) 수정:

```python
if method == OptimizationMethod.BLACK_LITTERMAN:
    from pypfopt import BlackLittermanModel
    from tradingagents.skills.portfolio.bl_views import (
        generate_bl_views, BL_TAU_DEFAULT, BL_VIEW_CONF_MULTI_DEFAULT,
    )

    tilt_params: dict[str, float | bool]
    if method_params.get("_bl_trigger"):
        bl_breakdown: dict = {}
        views, confs, tilt_params = generate_bl_views(
            scenario=scenario,
            regime_confidence=regime_confidence,
            candidates=candidates.bucket_to_tickers,
            sub_category_lookup=sub_category_lookup,
            breakdown_out=bl_breakdown,
        )
        if attribution is not None:
            attribution["bl_views_breakdown"] = bl_breakdown
    else:
        # force_method='bl' 외부 주입 — tilt 비적용 (기존 동작 보존)
        views = method_params.get("views", {})
        confs = method_params.get("view_confidences", [])
        tilt_params = {
            "tau": BL_TAU_DEFAULT,
            "view_conf_multi": BL_VIEW_CONF_MULTI_DEFAULT,
            "view_conf_multi_applied": False,
        }

    if views:
        bl = BlackLittermanModel(
            S, absolute_views=views, omega="idzorek",
            view_confidences=confs,
            tau=tilt_params["tau"],
        )
        mu = bl.bl_returns()
    else:
        mu = expected_returns.mean_historical_return(returns, returns_data=True)
        if attribution is not None:
            attribution["bl_views_fallback"] = "empty_views_historical_fallback"
else:
    mu = expected_returns.mean_historical_return(returns, returns_data=True)
```

## Edge Cases

| Case | Behavior |
|---|---|
| `scenario=None` / unknown | `({}, [], default_tilt)` 반환. allocator 빈 views → historical 폴백. tilt 비적용. |
| `regime_confidence=0.05` + goldilocks (multi=1.3) | conf = max(0.05, 0.10) = 0.10 × 1.3 = 0.13. [0.05, 1.0] 안. |
| `regime_confidence=0.91` + goldilocks (multi=1.3) | conf = 0.91 × 1.3 = 1.183 → cap 1.0 |
| `regime_confidence=0.1` + broad_recession (multi=0.5) | conf = max(0.1, 0.10) = 0.10 × 0.5 = 0.05 (floor 정확) |
| `force_method="black_litterman"` 외부 views (`_bl_trigger=False`) | tilt 비적용, tau=0.05 (pypfopt default). 기존 Phase 3b 동작 그대로. |
| BL_TILT 에 없는 scenario (RULEBOOK 만 추가됐을 때) | default tilt 사용. log warning |
| `tau=0.025` (강한 보수) | prior 강 → BL ≈ historical mu |
| `tau=0.10` (공격) | view 우세 → BL ≈ view 쪽 |

## Numerical Safety

- post-multiplier clip `[0.05, 1.0]` → Idzorek-Walters Ω 안정성 보장
- `tau ∈ [0.025, 0.10]` → pypfopt 견고 처리
- view_confidences 가 빈 list 인 경우 allocator 가 빈 views 분기로 폴백 → BL 자체 진입 안 함

## Backward Compat

- `generate_bl_views` 시그니처 변경 (return tuple [3]) — **caller 함께 update 필수**.
- `force_method='black_litterman'` + 외부 views 경로: tilt 비적용 → pypfopt default tau 0.05 → 기존 동작 보존
- 자동 BL trigger 경로: 결과 weight 가 scenario tilt 만큼 달라짐. **회귀 baseline 갱신 권장**

## Performance

- Negligible — 매트릭스 lookup + list comprehension 만 추가

## Testing Strategy

### Unit tests — `tests/unit/skills/test_portfolio_bl_views.py` (MODIFY)

기존 12 tests 갱신 (`views, confs = generate_bl_views(...)` → `views, confs, tilt = generate_bl_views(...)`).

**신규 8 tests**:

1. `test_scenario_bl_tilt_covers_all_scenarios` — `SCENARIO_BL_TILT` key == `SCENARIO_BUCKET_RULEBOOK` key
2. `test_scenario_bl_tilt_values_in_range` — τ ∈ [0.025, 0.10], multi ∈ [0.5, 1.5]
3. `test_generate_bl_views_returns_tilt_params` — tilt_params 의 3 key
4. `test_generate_bl_views_growth_scenario_high_tilt` — goldilocks → tilt={tau:0.10, multi:1.3, applied:True}
5. `test_generate_bl_views_recession_scenario_low_tilt` — broad_recession → tilt={tau:0.025, multi:0.5, applied:True}
6. `test_generate_bl_views_view_conf_clipped_high` — conf × multi > 1.0 → 1.0 cap
7. `test_generate_bl_views_view_conf_clipped_low` — multi=0.5 + floor → 결과 [0.05, 1.0] 안
8. `test_generate_bl_views_records_tilt_in_breakdown` — breakdown_out["tilt_params"]

### Integration tests — `tests/integration/test_allocator_phase4b.py` (NEW, 4 tests)

1. `test_allocator_bl_breakdown_contains_tilt_params` — attribution.bl_views_breakdown.tilt_params 의 4 key
2. `test_allocator_bl_growth_scenario_tau_matches_tilt` — goldilocks → tau=0.10
3. `test_allocator_bl_recession_scenario_tau_matches_tilt` — broad_recession → tau=0.025
4. `test_allocator_bl_force_method_no_tilt_applied` — force_method="bl" + views 외부 주입 → view_conf_multi_applied=False

### Regression

- Phase 3b 기존 integration 7 tests: tuple unpack 갱신 외 logic 영향 없음.
- Phase 1/2a/2b/3a/3c/4a 통합 250+ tests: BL path 비활성 → 영향 없음.

### Acceptance criteria

| # | Criterion | Verification |
|---|---|---|
| (a) | SCENARIO_BL_TILT 매트릭스 | unit 1-2 |
| (b) | generate_bl_views tilt_params 반환 | unit 3 |
| (c) | growth/recession 양극 dial | unit 4-5 |
| (d) | view_conf clipping | unit 6-7 |
| (e) | breakdown tilt 기록 | unit 8 |
| (f) | allocator tau 사용 | integration 2-3 |
| (g) | force_method 경로 tilt 비적용 | integration 4 |
| (h) | 기존 250+ tests PASS | full regression |

총 12 신규 test (8 unit + 4 integration). Phase 3b 의 23 보다 작음 — 시그니처 확장 + 매트릭스 추가.

## Related Memory

- [[stage3_phase3b_followup]] — BL views adapter (Phase 4b 가 확장)
- [[stage3_phase4a_followup]] — Ledoit-Wolf shrinkage (BL 의 S 입력)
- [[stage3_phase3c_followup]] — NCO backbone (Phase 4b 와 별개 method)
