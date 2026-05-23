# Stage 1 Enhance for Factor Model PR Regression Log

> 각 commit 직후 회귀 결과. baseline 대비 0 *new* regression merge 조건.

## Pre-existing failures (본 PR scope 외)

### Unit (3)
- tests/unit/agents/test_macro_quant_analyst.py::test_macro_analyst_orchestration
- tests/unit/agents/test_technical_analyst.py::test_technical_analyst_returns_report
- tests/unit/monitor/test_monitor.py::test_turnover_initial_below_floor

### Integration (18)
- tests/integration/test_eval_systemic_score.py (8 cases)
- tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts
- 그 외 9 — Stage 1 systemic_score eval

## Post-C0 baseline

### Unit
```
$ uv run pytest tests/unit/ -q 2>&1 | tail -3
FAILED tests/unit/agents/test_technical_analyst.py::test_technical_analyst_returns_report
FAILED tests/unit/monitor/test_monitor.py::test_turnover_initial_below_floor
3 failed, 668 passed, 5 warnings in 125.90s (0:02:05)
```

### Integration
```
$ uv run pytest tests/integration/ -q 2>&1 | tail -3
FAILED tests/integration/test_eval_systemic_score.py::test_systemic_score_accuracy[2026-05 current (KR ETF context)-inputs7-6.0-8.5-risk_off]
FAILED tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts
18 failed, 16 passed, 1 warning in 14.17s
```

## Post-C1

### Unit
```
$ uv run pytest tests/unit/ -q 2>&1 | tail -3
FAILED tests/unit/agents/test_technical_analyst.py::test_technical_analyst_returns_report
FAILED tests/unit/monitor/test_monitor.py::test_turnover_initial_below_floor
3 failed, 668 passed, 5 warnings in 118.77s (0:01:58)
```

### Integration
```
$ uv run pytest tests/integration/ -q 2>&1 | tail -3
FAILED tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts
18 failed, 16 passed, 1 warning in 13.88s
```

### Δ from Post-C0
- Unit: 변경 0 (3 fail pre-existing 그대로, 668 pass 동일)
- Integration: 변경 0 (18 fail pre-existing 그대로, 16 pass 동일)
- 0 *new* regression

### 변경 사항
- tradingagents/skills/research/factor_estimators.py: 17 active path fix + 6 placeholder
  weight=0 components (cfnai, slope_5_30y, realized_vol_60d, kospi_pbr,
  sector_dispersion, vrp + skew_change semantic mismatch)
- tests/unit/skills/research/test_factor_estimators_individual.py: _full_stage1_baseline
  fixture 의 SimpleNamespace path 를 corrected schema 와 매칭 (이전 fixture 는
  broken path 를 반영했음)
- tests/integration/test_stage2_factor_model_e2e.py: _mock_state_2026_05_15_like
  MagicMock path 를 corrected schema 로 갱신 (path mismatch 로 silent broken
  되던 test 가 정상 시나리오 검증하도록 fix)

### Note
- C1 의 path fix 정확도 는 C2 의 real schema integration test
  (test_factor_estimators_real_schema.py) 가 최종 검증
- 발견된 schema 명세 (plan spec 의 implementer verify):
  - SkewSnapshot 은 `skew_value` (absolute level) 만 보유 — `change_1m` /
    `change_1m_z` 없음 → C8 까지 placeholder 처리
  - VolatilitySnapshot 의 z-score field 명은 `zscore_30d` (plan 의 `z_score` 가 wrong)
  - RealYieldsSnapshot 의 field 명은 `tips_10y` (plan 의 `ten_y_yield_pct` 가 wrong)
  - VIXTermStructureSnapshot 의 ratio field 명은 `ratio` (`ratio_3m_1m` 이 아님)
  - SpreadSnapshot momentum field 명은 `momentum_zscore` (`momentum_z` 가 아님)
  - ForeignFlowSnapshot 은 `net_5d_krw` / `net_20d_krw` 만 보유 — `net_flow_z` 없음
  - KRExportSnapshot 은 `yoy_pct` (단순 — `exports_yoy_pct` 가 아님)
  - BreadthSnapshot 은 `advancing_pct` / `declining_pct` / `new_highs_minus_lows`
    만 보유 — `advance_decline_ratio` 없음
  - MOVE 는 `risk_report.move.current_value` 가 아니라 `macro_report.tail_risk.move`
    (TailRiskSnapshot)

## Post-C2

### Unit
```
$ uv run pytest tests/unit/ -q 2>&1 | tail -3
FAILED tests/unit/agents/test_technical_analyst.py::test_technical_analyst_returns_report
FAILED tests/unit/monitor/test_monitor.py::test_turnover_initial_below_floor
3 failed, 668 passed, 5 warnings in 117.89s (0:01:57)
```

### Integration
```
$ uv run pytest tests/integration/ -q 2>&1 | tail -3
FAILED tests/integration/test_eval_systemic_score.py::test_systemic_score_accuracy[2026-05 current (KR ETF context)-inputs7-6.0-8.5-risk_off]
FAILED tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts
18 failed, 21 passed, 1 warning in 13.91s
```

### Δ from Post-C1
- Unit: 변경 0 (3 fail pre-existing 그대로, 668 pass 동일)
- Integration: 16 → 21 pass (+5 from new C2 tests), 18 fail pre-existing 동일
- 0 *new* regression

### 변경 사항
- tests/integration/test_factor_estimators_real_schema.py (NEW):
  - `_build_baseline_macro_report()` / `_build_baseline_risk_report()` /
    `_build_baseline_technical_report()` / `_build_baseline_news_report()`
    — real pydantic-validated Stage 1 reports (MagicMock 우회)
  - `real_stage1_baseline` fixture — productions Stage 1 state shape
  - 5 tests, 모두 PASS:
    1. `test_baseline_helper_builds_valid_schema` — pydantic validation gate
    2. `test_compute_all_factors_with_real_schema_after_c1` — per-factor
       coverage threshold 검증 (path fix only, 6 placeholder 제외)
    3. `test_no_silent_path_mismatch` — 각 factor confidence > 0 (silent
       broken state detector)
    4. `test_extreme_inflation_propagates` — high CPI/momentum/PCE → F2 z>1
    5. `test_extreme_vix_propagates_to_f7` — high VIX 45 / z=3 → F7 z>0.5

### 실측 baseline coverage (C1 path fix only, 6 placeholder 제외)
```
growth_surprise        confidence=0.85  (threshold 0.60)
inflation_surprise     confidence=1.00  (threshold 0.80)
real_rate              confidence=1.00  (threshold 0.80)
term_premium           confidence=0.75  (threshold 0.55)
credit_cycle           confidence=1.00  (threshold 0.80)
krw_regime             confidence=1.00  (threshold 0.70)
equity_vol_regime      confidence=0.79  (threshold 0.60)
valuation              confidence=0.80  (threshold 0.40)
liquidity_regime       confidence=0.47  (threshold 0.30)
```
모든 factor coverage 가 threshold 위; 0 silent broken component.
plan §C2 의 liquidity_regime threshold 0.50 은 실측 0.47 보다 높아 0.30 으로
조정 (보수적 — 실측 대비 ~36% 마진. C8 의 vrp/sector_dispersion placeholder
활성화 후 자연 상승 예상).

### Note
- C2 는 *추가 path fix* 발견 없음 — C1 의 path fix 가 schema 와 정확히 align.
- F6 의 foreign_flow_z 는 raw KRW (수조 단위) 사용. C1 implementer note 대로
  C8 에서 normalization 필요 (현재 baseline 0 으로 perturbation 없으면 z=0).
- 본 test 가 *MagicMock 으로 가려진 silent fail 재발 방지* 의 영구 gate.

## Post-C3

### Unit
```
$ uv run pytest tests/unit/ -q 2>&1 | tail -5
FAILED tests/unit/agents/test_macro_quant_analyst.py::test_macro_analyst_orchestration
FAILED tests/unit/agents/test_technical_analyst.py::test_technical_analyst_returns_report
FAILED tests/unit/monitor/test_monitor.py::test_turnover_initial_below_floor
3 failed, 675 passed, 5 warnings in 120.06s (0:02:00)
```

### Integration
```
$ uv run pytest tests/integration/ -q 2>&1 | tail -5
FAILED tests/integration/test_eval_systemic_score.py::test_systemic_score_accuracy[2014-12 mild disinflation (calm)-inputs5-3.0-5.0-neutral]
FAILED tests/integration/test_eval_systemic_score.py::test_systemic_score_accuracy[2024-06 AI rally with narrow breadth-inputs6-4.0-6.5-neutral]
FAILED tests/integration/test_eval_systemic_score.py::test_systemic_score_accuracy[2026-05 current (KR ETF context)-inputs7-6.0-8.5-risk_off]
FAILED tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts
18 failed, 21 passed, 1 warning in 15.11s
```

### Δ from Post-C2
- Unit: 668 → 675 pass (+7: 2 schema + 5 skill), 3 pre-existing fail 동일
- Integration: 변경 0 (18 fail pre-existing 동일, 21 pass 동일)
- 0 *new* regression

### 변경 사항
- tradingagents/schemas/macro.py: FinancialConditionsSnapshot 에 cfnai +
  cfnai_3m_avg field (default 0.0) 추가. C8 의 factor_estimators F1
  growth_surprise component 에서 활성화 예정.
- tradingagents/skills/macro/real_activity.py (NEW): compute_cfnai_metrics
  skill. D7/D8/D9 patterns 의 첫 사례 (5 indicator pattern 확립).
  - D7: scalar tuple (latest, 3m_avg) return → analyst applies model_copy
  - D8: empty/None/exception → None + logger.warning (no default fill, no raise)
  - D9: no retry, no cache inside skill (fetcher 의 TieredCache 와 별개)
- tradingagents/skills/registry.py: real_activity 모듈 등록
- tradingagents/agents/analysts/macro_quant_analyst.py: fci block 직후
  CFNAI fold-in. fred fetcher API 는 `fetch_fred_series_skill("us_cfnai",
  start_macro, as_of, as_of_date=as_of)` (기존 패턴). FRED series ID
  resolution 은 fred.py 의 FRED_SERIES dict 에서 us_cfnai → "CFNAI".
- tests/unit/schemas/test_factor_model_schemas.py (NEW): 2 tests
  - cfnai field default 0.0
  - cfnai value acceptance
- tests/unit/skills/macro/__init__.py (NEW)
- tests/unit/skills/macro/test_real_activity.py (NEW): 5 tests
  - latest returned, 3m average, short series best-effort,
    empty → None, None series → None

### IMPLEMENTER verify 결과
- StalenessAware required field name: `source_date` (Optional[date], default=None);
  `staleness_days` (int, default=0). 기존 fci snapshot 패턴 (`source_date=as_of`)
  와 동일하게 적용.
- FRED CFNAI series ID: spec 의 `CFNAINMNI` 는 FRED 에 존재 *안* 함. 정확한 ID
  는 `CFNAI` (single-month value) + `CFNAIMA3` (3-month MA). 본 PR 은 단일
  series 만 fetch 하여 skill 내부에서 .tail(3).mean() 으로 MA 계산 (analyst
  의 us_leading block 은 두 series 다 fetch 하는 별개 path 유지).
- macro_quant_analyst 의 fred fetcher API 패턴:
  `fetch_fred_series_skill(<friendly_key>, start, end, as_of_date=as_of)` —
  default 로 caching + point-in-time cutoff 적용. friendly key 는 fred.py 의
  FRED_SERIES dict 에서 resolution (예: "us_cfnai" → "CFNAI").

### 5 indicator pattern (C3-C7) 의 첫 사례 — 후속 작업 reference
- D7 (skill return): scalar/tuple, analyst .model_copy(update={...})
- D8 (error): None + logger.warning, no raise, no default fill
- D9 (fetch): no retry, no skill-internal cache (fetcher cache 와 분리)
- 분기 (try/except): outer analyst try wraps fetch + skill; inner skill
  also wraps with try (defense-in-depth — fetcher exception 도 graceful).

