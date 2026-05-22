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

## Post-C2 ... Post-C8
(각 commit 직후 갱신)
