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

## Post-C2, ..., Post-C11
(각 commit 후 갱신)
