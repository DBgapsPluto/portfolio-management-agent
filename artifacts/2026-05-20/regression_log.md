# Stage 2 Mega-PR Regression Log (2026-05-20)

> 각 commit (C1-C5) 직후 회귀 결과 raw 기록. 본 baseline 대비 0 *new* regression
> (pre-existing 3 unit + 18 integration fail 제외) 이 mega-PR merge 조건.

## Pre-existing failures (Stage 2 작업과 무관, baseline noise)

Unit (Stage 1 / Stage 6 영역):
- `tests/unit/agents/test_macro_quant_analyst.py::test_macro_analyst_orchestration`
- `tests/unit/agents/test_technical_analyst.py::test_technical_analyst_returns_report`
- `tests/unit/monitor/test_monitor.py::test_turnover_initial_below_floor`

Integration (Stage 1 systemic_score eval + plan pipeline):
- `tests/integration/test_eval_systemic_score.py` (8 cases)
- `tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts`
- 그 외 9개 — 본 plan 범위 외, Stage 1 후속 issue 로 별도 처리.

해당 test 파일은 Stage 1 commit 들(`3bcbe64`, `698400e`, `3cdbb89`, `bb848dd`)이 마지막 수정. Stage 2 변경 (`schemas/research.py`, `scenario_mapper.py`, `method_picker.py`, `research_manager.py`, `conditional_stress.py`, `kr_residual_signals.py`) 과 교차 영역 없음.

C1-C5 의 의무: 위 fail set 이 *증가하지 않을 것*. 새로운 fail 발생 시 즉시 root cause.

---

## Post-C0 baseline (pre-changes)

### Unit test
```
$ uv run pytest tests/unit/ -q 2>&1 | tail -3
FAILED tests/unit/monitor/test_monitor.py::test_turnover_initial_below_floor
3 failed, 595 passed, 5 warnings in 26.02s
```

### Integration test
```
$ uv run pytest tests/integration/ -q 2>&1 | tail -3
FAILED tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts
18 failed, 14 passed, 1 warning in 52.90s
```

## Post-C1

### Unit test
```
$ uv run pytest tests/unit/ -q 2>&1 | tail -3
FAILED tests/unit/monitor/test_monitor.py::test_turnover_initial_below_floor
3 failed, 604 passed, 5 warnings in 16.33s
```
Δ vs baseline: +9 tests (7 dominant_scenario + 2 overheating). 0 new failures.

### Integration test
```
$ uv run pytest tests/integration/ -q 2>&1 | tail -3
FAILED tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts
18 failed, 14 passed, 1 warning in 25.08s
```
Δ vs baseline: identical (18/14). 0 new failures.

## Post-C2

### Unit test
```
$ uv run pytest tests/unit/ -q 2>&1 | tail -3
FAILED tests/unit/monitor/test_monitor.py::test_turnover_initial_below_floor
3 failed, 604 passed, 5 warnings in 47.97s
```
Δ vs Post-C1: identical (604 passed, 3 pre-existing fails). C2 신규 6 smoke tests 는 `tests/scripts/` 위치 (sibling) 라 별도 path 로 collect.

### Scripts smoke test (신규 path)
```
$ uv run pytest tests/scripts/ -v 2>&1 | tail -3
============================== 6 passed in 0.14s ==============================
```

### Integration test
```
$ uv run pytest tests/integration/ -q 2>&1 | tail -3
FAILED tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts
18 failed, 14 passed, 1 warning in 51.03s
```
Δ vs baseline: identical (18/14). 0 new regressions.

## Post-C3
(C3 commit 직후 갱신)

## Post-C4
(C4 commit 직후 갱신)

## Post-C5
(C5 commit 직후 갱신)
