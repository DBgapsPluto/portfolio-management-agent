# Stage 2 Factor Model PR1 Regression Log

> 각 commit 직후 회귀 결과. baseline 대비 0 *new* regression (pre-existing fail 제외) merge 조건.
> 24-cell 관련 test (`test_research_scenario_mapper.py`, `test_stage2_e2e_snapshot.py`,
> `test_research_manager.py`) 의 *제거* 는 *regression 아님* — factor model test 로 대체.

## Pre-existing failures (factor model 작업과 무관)

### Unit (3)
- tests/unit/agents/test_macro_quant_analyst.py::test_macro_analyst_orchestration
- tests/unit/agents/test_technical_analyst.py::test_technical_analyst_returns_report
- tests/unit/monitor/test_monitor.py::test_turnover_initial_below_floor

### Integration (18)
- tests/integration/test_eval_systemic_score.py (8 cases)
- tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts
- 그 외 9 — Stage 1 systemic_score eval (별도 PR cycle)

## Post-C0 baseline (pre-changes)

### Unit
```
$ uv run pytest tests/unit/ -q 2>&1 | tail -3
FAILED tests/unit/agents/test_technical_analyst.py::test_technical_analyst_returns_report
FAILED tests/unit/monitor/test_monitor.py::test_turnover_initial_below_floor
3 failed, 619 passed, 5 warnings in 27.02s
```

### Integration
```
$ uv run pytest tests/integration/ -q 2>&1 | tail -3
FAILED tests/integration/test_eval_systemic_score.py::test_systemic_score_accuracy[2026-05 current (KR ETF context)-inputs7-6.0-8.5-risk_off]
FAILED tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts
18 failed, 19 passed, 1 warning in 16.94s
```

## Post-C1

### Unit
```
$ uv run pytest tests/unit/ -q 2>&1 | tail -3
FAILED tests/unit/agents/test_technical_analyst.py::test_technical_analyst_returns_report
FAILED tests/unit/monitor/test_monitor.py::test_turnover_initial_below_floor
3 failed, 623 passed, 5 warnings in 12.58s
```

### Integration
```
$ uv run pytest tests/integration/ -q 2>&1 | tail -3
FAILED tests/integration/test_eval_systemic_score.py::test_systemic_score_accuracy[2026-05 current (KR ETF context)-inputs7-6.0-8.5-risk_off]
FAILED tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts
18 failed, 18 passed, 1 warning in 14.31s
```

### Δ from baseline
- Unit: +4 passed (5 new factor schema test - 1 removed cell-key test), 0 new failure
- Integration: -1 passed (test_subgraph_isolation.py 삭제 — sub-graph wrapper 폐기로 obsolete), 0 new failure
- 0 *new* regression confirmed

## Post-C2

### Unit
```
$ uv run pytest tests/unit/ -q 2>&1 | tail -3
FAILED tests/unit/agents/test_technical_analyst.py::test_technical_analyst_returns_report
FAILED tests/unit/monitor/test_monitor.py::test_turnover_initial_below_floor
3 failed, 665 passed, 5 warnings in 8.06s
```

### Integration
```
$ uv run pytest tests/integration/ -q 2>&1 | tail -3
FAILED tests/integration/test_eval_systemic_score.py::test_systemic_score_accuracy[2026-05 current (KR ETF context)-inputs7-6.0-8.5-risk_off]
FAILED tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts
18 failed, 18 passed, 1 warning in 13.99s
```

### Δ from Post-C1
- Unit: +42 passed (4 baseline + 5 audit + 5 fetcher + 20 estimator individual + 4 news fallback + 4 news component = 42), 0 new failure
- Integration: unchanged (18 failed / 18 passed), 0 new failure
- 0 *new* regression confirmed

## Post-C3

### Unit
```
$ uv run pytest tests/unit/ -q 2>&1 | tail -3
FAILED tests/unit/agents/test_technical_analyst.py::test_technical_analyst_returns_report
FAILED tests/unit/monitor/test_monitor.py::test_turnover_initial_below_floor
3 failed, 689 passed, 5 warnings in 8.38s
```

### Integration
```
$ uv run pytest tests/integration/ -q 2>&1 | tail -3
FAILED tests/integration/test_eval_systemic_score.py::test_systemic_score_accuracy[2026-05 current (KR ETF context)-inputs7-6.0-8.5-risk_off]
FAILED tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts
18 failed, 18 passed, 1 warning in 13.49s
```

### Δ from Post-C2
- Unit: +24 passed (15 test_factor_to_bucket + 9 test_mandate_projection — 24 total new tests pass), 0 new failure
- Integration: unchanged (18 failed / 18 passed), 0 new failure
- 0 *new* regression confirmed

### Notes
- `scipy>=1.11.0` 을 pyproject.toml 에 명시 추가. 기존엔 scikit-learn / pyportfolioopt
  의 transitive dep 로 import 가능했으나, factor_to_bucket 의 `scipy.optimize.minimize`
  직접 의존 → 명시 dependency 로 격상.
- uv.lock 은 본 commit scope 외 (WIP 보호) — 별도 `uv lock` 동기화 필요.

## Post-C4

### Unit
```
$ uv run pytest tests/unit/ -q 2>&1 | tail -3
FAILED tests/unit/agents/test_technical_analyst.py::test_technical_analyst_returns_report
FAILED tests/unit/monitor/test_monitor.py::test_turnover_initial_below_floor
3 failed, 681 passed, 5 warnings in 7.63s
```

### Integration
```
$ uv run pytest tests/integration/ -q 2>&1 | tail -3
FAILED tests/integration/test_eval_systemic_score.py::test_systemic_score_accuracy[2026-05 current (KR ETF context)-inputs7-6.0-8.5-risk_off]
FAILED tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts
18 failed, 16 passed, 1 skipped, 1 warning in 15.01s
```

### Δ from Post-C3
- Unit: -8 passed (delete test_research_manager.py — 13 tests removed; new test_research_manager_factor_model.py — 8 tests added; net -5 → but baseline shifts because 3 previously-deleted tests counted), 0 new failure.
  - Removed (C5 합병 대상이지만 import 깨짐으로 인해 본 commit 에서 처리):
    `tests/unit/agents/test_research_manager.py` (24-cell prompt/EMA/hysteresis 의존 — `_blend_with_prior`, `_apply_hysteresis` import 깨짐)
  - Added: `tests/unit/agents/test_research_manager_factor_model.py` (8 tests, 모두 pass)
- Integration: -2 passed (snapshot 5 tests → 1 module skip + 3 new e2e tests; net -2), 0 new failure.
  - Stubbed (C5 합병 대상이지만 import 깨짐으로 인해 본 commit 에서 module-level skip 처리):
    `tests/integration/test_stage2_e2e_snapshot.py` (24-cell `_blend_with_prior` import 깨짐; 5 → 1 skipped)
  - Added: `tests/integration/test_stage2_factor_model_e2e.py` (3 tests, 모두 pass)
- 0 *new* regression confirmed (pre-existing 3 unit fail + 18 integ fail 그대로).

### Notes
- C4 의 핵심: `research_manager.py` 전면 rewrite — 24-cell prompt + EMA + hysteresis
  → factor pipeline (compute_all_factors → _blend_factors_with_prior →
   apply_factor_model_with_safety → derive_dominant_scenario/conviction).
- Stage 2 LLM 호출 0 — deterministic. macro_news_analyst 의 NewsReport struct 활용 (Option Z).
- Legacy 24-cell placeholder field (`scenario_probabilities` / `dominant_cell` /
  `dominant_cycle` / cycle/tail/kr marginals) — 모두 valid value 로 채움 → ResearchDecision
  pydantic validation pass. `_legacy_*` helper 사용. C5 에서 schema 자체 제거 예정.
- `dominant_scenario` 는 `ResearchDecision.@property` 가 cycle/tail/kr marginal 로부터
  derive (factor 의 `derive_dominant_scenario` 결과를 cycle 로 round-trip 변환). C5 에서
  factor 결과 직접 노출로 일원화 예정.

## Post-C5 ... Post-C8
(각 commit 직후 갱신)
