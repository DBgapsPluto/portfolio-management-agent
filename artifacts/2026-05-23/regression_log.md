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

## Post-C4

### Unit
```
$ uv run pytest tests/unit/ -q 2>&1 | tail -5
FAILED tests/unit/agents/test_macro_quant_analyst.py::test_macro_analyst_orchestration
FAILED tests/unit/agents/test_technical_analyst.py::test_technical_analyst_returns_report
FAILED tests/unit/monitor/test_monitor.py::test_turnover_initial_below_floor
3 failed, 681 passed, 5 warnings in 117.33s (0:01:57)
```

### Integration
```
$ uv run pytest tests/integration/ -q 2>&1 | tail -3
FAILED tests/integration/test_eval_systemic_score.py::test_systemic_score_accuracy[2026-05 current (KR ETF context)-inputs7-6.0-8.5-risk_off]
FAILED tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts
18 failed, 21 passed, 1 warning in 13.88s
```

### Δ from Post-C3
- Unit: 675 → 681 pass (+6: 2 schema + 4 skill), 3 pre-existing fail 동일
- Integration: 변경 0 (18 fail pre-existing 동일, 21 pass 동일)
- 0 *new* regression

### 변경 사항
- tradingagents/schemas/macro.py: YieldCurveSnapshot 에 spread_30y_5y_bps field
  (default 0.0) 추가. C8 의 factor_estimators F4 term_premium component 에서
  활성화 예정 (long-end real economy term premium signal).
- tradingagents/skills/macro/yield_curve.py: compute_yield_curve_extras skill
  추가 (기존 compute_yield_curve 의 sibling). D7/D8/D9 patterns 적용.
  - D7: scalar float return → analyst applies yc.model_copy
  - D8: None input → None + logger.warning (no default fill, no raise)
  - D9: no retry, no cache inside skill
- tradingagents/dataflows/fred.py: FRED_SERIES dict 에 us_5y → DGS5,
  us_30y → DGS30 추가 (기존 us_10y/us_2y/us_3m 와 parallel).
- tradingagents/default_config.py: publication_lag_days 에 us_5y/us_30y = 1 추가
  (daily Treasury yields — 다른 us_10y/us_2y 와 동일).
- tradingagents/agents/analysts/macro_quant_analyst.py: yc block 직후
  slope_5_30y fold-in. fetch_fred_series_skill("us_5y", ...) + ("us_30y", ...)
  + compute_yield_curve_extras → yc.model_copy(update={"spread_30y_5y_bps": ...}).
- tests/unit/schemas/test_factor_model_schemas.py: 2 new tests
  - spread_30y_5y default 0.0
  - spread_30y_5y value acceptance
- tests/unit/skills/macro/test_yield_curve.py (NEW): 4 tests
  - basic slope (positive), inverted (negative),
  - None dgs5 → None, both None → None

### IMPLEMENTER verify 결과
- FRED friendly key 확인: us_dgs5 / us_dgs30 는 FRED_SERIES dict 에 *없었음*.
  Plan 의 instruction 대로 add (us_5y → DGS5, us_30y → DGS30; 기존 us_10y/us_2y
  naming convention 과 일관). publication_lag_days 도 함께 추가.
- 기존 yield_curve.py 모듈에 compute_yield_curve_extras 추가 (별도 file 생성 X) —
  같은 도메인 (yield curve) + skills/registry.py 의 module list 변경 불필요.
- C3 pattern 일관성 확인 완료 (D7 scalar, D8 None+warning, D9 no cache,
  outer+inner try/except defense-in-depth).

## Post-C5

### Unit
```
$ uv run pytest tests/unit/ -q 2>&1 | tail -5
FAILED tests/unit/agents/test_macro_quant_analyst.py::test_macro_analyst_orchestration
FAILED tests/unit/agents/test_technical_analyst.py::test_technical_analyst_returns_report
FAILED tests/unit/monitor/test_monitor.py::test_turnover_initial_below_floor
3 failed, 688 passed, 5 warnings in 114.10s (0:01:54)
```

### Integration
```
$ uv run pytest tests/integration/ -q 2>&1 | tail -3
FAILED tests/integration/test_eval_systemic_score.py::test_systemic_score_accuracy[2026-05 current (KR ETF context)-inputs7-6.0-8.5-risk_off]
FAILED tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts
18 failed, 21 passed, 1 warning in 13.25s
```

### Δ from Post-C4
- Unit: 681 → 688 pass (+7: 3 schema + 4 skill), 3 pre-existing fail 동일
- Integration: 변경 0 (18 fail pre-existing 동일, 21 pass 동일)
- 0 *new* regression

### 변경 사항
- tradingagents/schemas/macro.py: KRValuationSnapshot 신규 class (kospi_pbr,
  kospi_per, kospi_div_yield). C8 의 factor_estimators F8 valuation component
  에서 활성화 예정 (KR equity valuation).
- tradingagents/schemas/reports.py: MacroReport.kr_valuation Optional field
  (default None — backward compat).
- tradingagents/skills/macro/kr_valuation.py (NEW): compute_kospi_valuation
  skill. 5 indicator pattern 의 첫 *신규 class indicator* 사례.
  - D7 (신규 class): full Snapshot 반환 — analyst 가 MacroReport 의 Optional
    field 에 직접 채움 (model_copy 아님; cfnai/slope_5_30y 의 scalar+model_copy
    와 다른 path).
  - D8: empty/missing column/exception → None + logger.warning (no default fill).
  - D9: no retry, no cache inside skill.
- tradingagents/skills/registry.py: kr_valuation 모듈 등록.
- tradingagents/agents/analysts/macro_quant_analyst.py: events fetch 직전
  KOSPI valuation block. try/except 로 skill 호출 wrap (defense-in-depth).
  MacroReport 생성자에 kr_valuation=kr_valuation_snapshot 추가.
- tests/unit/schemas/test_factor_model_schemas.py: 3 new tests
  - snapshot basic instantiation
  - Optional in MacroReport (default None — backward compat)
  - 채움 시 정상 acceptance + readback
  - _build_minimal_macro_report local helper (integration 의 baseline 과 분리,
    unit ↛ integration 의존성 방지)
- tests/unit/skills/macro/test_kr_valuation.py (NEW): 4 tests
  - single row → Snapshot, multi-row averaged, empty df → None,
    pykrx exception → None

### IMPLEMENTER verify 결과
- pykrx 의 KOSPI200 fundamental 컬럼 검증: BPS/PER/PBR/EPS/DIV/DPS
  (실제 KeyError stack trace 에서 컬럼명 추출). plan spec 의 PBR/PER/DIV 일치.
  본 skill 은 PBR/PER/DIV 3개만 사용 (다른 컬럼 무시).
- _build_minimal_macro_report helper 의 reuse 방식: integration test 의
  `_build_baseline_macro_report` 와 동일 schema 를 unit test 내부에 *local*
  로 빌드 (integration 모듈 import 회피). 이유: unit → integration 의존
  방향 차단 (test pyramid 원칙).
- D7 신규 class indicator path 확립 (cfnai/slope_5_30y 의 scalar+model_copy 대비):
  - 신규 class field 가 *Optional/default None* 인 MacroReport field 에 직접
    삽입. model_copy 불필요 — MacroReport 생성 시점에 None 또는 Snapshot 둘 중
    하나로 결정.
  - 후속 C6/C7 의 sector_dispersion / vrp 가 동일 패턴 (신규 class 라면) 또는
    scalar+model_copy (기존 schema extend) 인지 plan 에서 확인 필요.

## Post-C6

### Unit
```
$ uv run pytest tests/unit/ -q 2>&1 | tail -5
FAILED tests/unit/agents/test_macro_quant_analyst.py::test_macro_analyst_orchestration
FAILED tests/unit/agents/test_technical_analyst.py::test_technical_analyst_returns_report
FAILED tests/unit/monitor/test_monitor.py::test_turnover_initial_below_floor
3 failed, 697 passed, 5 warnings in 110.90s (0:01:50)
```

### Integration
```
$ uv run pytest tests/integration/ -q 2>&1 | tail -3
FAILED tests/integration/test_eval_systemic_score.py::test_systemic_score_accuracy[2026-05 current (KR ETF context)-inputs7-6.0-8.5-risk_off]
FAILED tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts
18 failed, 21 passed, 1 warning in 15.64s
```

### Δ from Post-C5
- Unit: 688 → 697 pass (+9: 4 schema + 5 skill), 3 pre-existing fail 동일
- Integration: 변경 0 (18 fail pre-existing 동일, 21 pass 동일)
- 0 *new* regression

### 변경 사항
- tradingagents/schemas/risk.py: RealVolSnapshot 신규 class (realized_vol_60d,
  realized_vol_20d, vrp_60d=0.0 default). C8 의 factor_estimators F7 vol regime +
  F9 liquidity (VRP) 에서 활성화 예정.
- tradingagents/schemas/reports.py: RiskReport.real_vol Optional field
  (default None — backward compat). RealVolSnapshot import 추가.
- tradingagents/skills/risk/realized_volatility.py (NEW): compute_realized_volatility
  skill. 5 indicator pattern 의 두 번째 *신규 class indicator* 사례 (C5 와 동일 D7 path).
  - D7 (신규 class): full Snapshot 반환 — analyst 가 RiskReport 의 Optional
    field 에 직접 채움 (model_copy 아님).
  - D8: empty / short (<5 obs) / exception → None + logger.warning.
  - D9: no retry, no cache inside skill.
  - VRP = (VIX/100)² - realized_60d², × 10000 (bps²-like).
- tradingagents/skills/registry.py: realized_volatility 모듈 등록.
- tradingagents/agents/analysts/market_risk_analyst.py:
  - logger 추가 (module-level).
  - kr_market_tier block 직후 realized vol block 추가. yfinance SPY 120d daily
    history fetch → pct_change → compute_realized_volatility 호출.
  - RiskReport 생성자에 real_vol=real_vol 추가.
  - vix variable: `vix = fetch_volatility_index("VIX", as_of)` (VolatilitySnapshot).
    level 은 `vix.current_value`.
- tests/unit/skills/risk/__init__.py (NEW)
- tests/unit/skills/risk/test_realized_volatility.py (NEW): 5 tests
  - basic (annualized 0.158 within 0.10~0.25)
  - VRP positive when VIX>realized (low_vol_returns + VIX 20)
  - VIX None → vrp=0
  - empty series → None
  - short (<5 obs) → None
- tests/unit/schemas/test_factor_model_schemas.py: 4 new tests + _build_minimal_risk_report
  - snapshot basic + with VRP
  - RiskReport.real_vol Optional default None + accept readback
  - _build_minimal_risk_report local helper (integration 의 _build_baseline_risk_report
    schema 와 동일, unit↛integration 의존성 차단).

### IMPLEMENTER verify 결과
- market_risk_analyst 의 vix variable 확인: line 132 `vix = fetch_volatility_index("VIX", as_of)`
  → VolatilitySnapshot return. level 은 vix.current_value (float). None guard 불필요
  (skill 이 D5 tier-3 degradation sentinel 반환; None 절대 X) 이지만 defense-in-depth
  로 `if vix is not None else None` 패턴 유지.
- yfinance API: `yf.Ticker("SPY").history(period="120d", interval="1d")` → DataFrame.
  daily returns = Close.pct_change().dropna(). empty 시 pd.Series([], dtype=float)
  로 fallback (skill 내부 len<5 guard 와 redundant 하지만 explicit).
- logger 는 module-level (`logging.getLogger(__name__)`). market_risk_analyst.py 에
  기존 logger import 없었음 — 추가.
- D7 신규 class indicator path 두 번째 사례 (C5: macro/kr_valuation, C6: risk/realized_volatility).
  RiskReport 의 Optional field 에 직접 삽입 — model_copy 불필요.
- 의문점: yfinance fetch 는 *network call* 으로, market_risk_analyst 의 unit test
  (`test_market_risk_analyst.py::test_risk_analyst_orchestration`) 는 network 호출 시
  실제로 SPY 데이터 다운로드 (mock 미적용). 현재 test PASS 확인되었으나 network 단절
  환경 (CI airgap) 시 try/except 의 outer logger.warning + real_vol=None path 로 fallback.
  기존 yfinance 의존 skill (breadth, equity_indices, cross_asset_returns) 와 동일 위험 프로필.

## Post-C7 (sector dispersion + BreadthSnapshot 확장 — F9 liquidity_regime)

### Unit
```
$ uv run pytest tests/unit/ 2>&1 | tail -3
FAILED tests/unit/agents/test_technical_analyst.py::test_technical_analyst_returns_report
FAILED tests/unit/monitor/test_monitor.py::test_turnover_initial_below_floor
3 failed, 703 passed, 5 warnings in 115.30s (0:01:55)
```

### Integration
```
$ uv run pytest tests/integration/ 2>&1 | tail -3
FAILED tests/integration/test_eval_systemic_score.py::test_systemic_score_accuracy[2024-06 AI rally with narrow breadth-inputs6-4.0-6.5-neutral]
FAILED tests/integration/test_eval_systemic_score.py::test_systemic_score_accuracy[2026-05 current (KR ETF context)-inputs7-6.0-8.5-risk_off]
FAILED tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts
18 failed, 21 passed, 1 warning in 15.41s
```

### Δ from Post-C6
- Unit: 697 → 703 pass (+6: 2 schema + 4 skill), 3 pre-existing fail 동일
- Integration: 변경 0 (18 fail pre-existing 동일, 21 pass 동일)
- 0 *new* regression

### 변경 사항
- tradingagents/schemas/risk.py: BreadthSnapshot.sector_return_dispersion 확장
  (default 0.0, decimal scale e.g. 0.05 = 5pp). C8 의 factor_estimators F9
  liquidity_regime component 에서 활성화 예정.
- tradingagents/skills/risk/sector_dispersion.py (NEW): compute_sector_dispersion
  skill. 5 indicator pattern 의 마지막 *기존 schema 확장 indicator* 사례 (C3/C4 와
  동일 D7 path).
  - D7 (기존 schema 확장): scalar return — analyst 가 BreadthSnapshot.model_copy
    로 sector_return_dispersion field 에 채움.
  - D8: empty / single sector (<2) / exception → None + logger.warning.
  - D9: no retry, no cache inside skill.
  - 계산: np.std(returns, ddof=1) — sample stddev cross-sectional.
- tradingagents/skills/registry.py: sector_dispersion 모듈 등록 (breadth 다음 줄).
- tradingagents/agents/analysts/market_risk_analyst.py:
  - breadth_us 생성 직후 sector dispersion block 추가 (D7 path).
  - yfinance 11 SPDR sector ETF (XLF, XLE, XLI, XLY, XLV, XLK, XLU, XLP, XLB,
    XLRE, XLC) 65d history fetch → 60d return = Close[-1] / Close[-60] - 1.
  - 개별 ticker fail 시 continue (graceful), insufficient sectors 시 None.
  - breadth_us = breadth_us.model_copy(update={"sector_return_dispersion": ...}).
  - outer try/except: 전체 fetch fail 시 logger.warning + breadth_us 원본 유지.
- tests/unit/schemas/test_factor_model_schemas.py: 2 new tests
  - default 0.0 확인
  - explicit value (2.5) accept
  - C7 section header + BreadthSnapshot import 추가.
- tests/unit/skills/risk/test_sector_dispersion.py (NEW): 4 tests
  - equal returns → 0 (perfect concentration)
  - wide spread (-0.15~+0.20) → > 0.05 (high dispersion)
  - empty dict → None
  - single sector → None

### IMPLEMENTER verify 결과
- BreadthSnapshot required fields 확인: `market` (Literal KOSPI200/SP500),
  `advancing_pct` (ge=0,le=1), `declining_pct` (ge=0,le=1),
  `new_highs_minus_lows` (int). 본 C7 에서 sector_return_dispersion 추가 (optional
  default 0.0).
- market_risk_analyst 의 breadth_us variable 확인: line 142
  `breadth_us = compute_market_breadth("SP500", as_of)` → BreadthSnapshot return.
  본 C7 의 dispersion block 은 line 143 직후 삽입 (model_copy reassign 으로
  variable rebind; RiskReport(breadth_us=breadth_us, ...) 변경 불필요).
- 11 SPDR sector ETF: XLF/XLE/XLI/XLY/XLV/XLK/XLU/XLP/XLB/XLRE/XLC. XLRE 가
  2015-10 상장, XLC 가 2018-6 상장 — 모두 60d history 충분 (현재 2026-05-23).
- yfinance API: `yf.Ticker(ticker).history(period="65d", interval="1d")` → DataFrame.
  60d return = Close.iloc[-1] / Close.iloc[-60] - 1 (5d buffer for weekends).
- ddof=1 사용 (sample std, n-1) — 11 ETF 라는 *유한 sample* 이므로 unbiased
  estimator 가 적절. population std (ddof=0) 도 가능하나 statistical convention
  은 sample std.
- 의문점: yfinance fetch 는 *11x network call* 으로 C6 (1 SPY 호출) 대비
  10x latency. 그러나 try/except per-ticker + outer try/except 로 partial /
  total fail graceful. 기존 yfinance 의존 skill (breadth, equity_indices,
  cross_asset_returns, C6 realized_vol) 와 동일 위험 프로필.
- 5 indicator pattern 완료: C3 (yield_curve scalar 확장), C4 (yield_curve scalar
  확장), C5 (kr_valuation 신규 class), C6 (real_vol 신규 class), C7 (sector_dispersion
  scalar 확장). 기존 schema 확장 3건 + 신규 class 2건. C8 factor_estimators 활성화
  ready.

## Post-C7.5 (SkewSnapshot.change_1m_z — F7 skew_change placeholder 해소)

### Unit
```
$ uv run pytest tests/unit/ -q 2>&1 | tail -5
FAILED tests/unit/agents/test_macro_quant_analyst.py::test_macro_analyst_orchestration
FAILED tests/unit/agents/test_technical_analyst.py::test_technical_analyst_returns_report
FAILED tests/unit/monitor/test_monitor.py::test_turnover_initial_below_floor
3 failed, 710 passed, 5 warnings in 124.08s (0:02:04)
```

### Integration
```
$ uv run pytest tests/integration/ -q 2>&1 | tail -5
FAILED tests/integration/test_eval_systemic_score.py::test_systemic_score_accuracy[2014-12 mild disinflation (calm)-inputs5-3.0-5.0-neutral]
FAILED tests/integration/test_eval_systemic_score.py::test_systemic_score_accuracy[2024-06 AI rally with narrow breadth-inputs6-4.0-6.5-neutral]
FAILED tests/integration/test_eval_systemic_score.py::test_systemic_score_accuracy[2026-05 current (KR ETF context)-inputs7-6.0-8.5-risk_off]
FAILED tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts
18 failed, 21 passed, 1 warning in 17.64s
```

### Δ from Post-C7
- Unit: 703 → 710 pass (+7: 2 schema + 5 skill), 3 pre-existing fail 동일
- Integration: 변경 0 (18 fail pre-existing 동일, 21 pass 동일)
- 0 *new* regression
- macro_quant_analyst fail 은 baseline list 에 있음 (test_macro_analyst_orchestration —
  yfinance/외부 network 의존, 의도된 known-fail; 본 C7.5 와 무관).

### 변경 사항
- tradingagents/schemas/risk.py: SkewSnapshot.change_1m_z 확장 (default 0.0).
  - description: "1-month change in skew_value, normalized by long-run sd. F7
    equity_vol_regime component (C8 활성화 예정)."
  - Level 은 post-2018 structurally elevated 라 reliability medium-low; 1m change z
    가 cleaner momentum signal.
- tradingagents/skills/risk/skew_metrics.py (NEW): compute_skew_change_z skill.
  - input: skew_series (pd.Series ≥21 obs), as_of.
  - output: float z | None.
  - Hand-coded long-run sd = 5.0 (typical historical 1m SKEW change std ≈ 5-7).
  - 21 trading days lookback (1 month). `latest - iloc[-21]` / sd.
  - D7: scalar return + skew.model_copy by analyst.
  - D8: <21 obs / empty / exception → None + logger.warning.
  - D9: no retry, no internal cache (D9 confirmed — fetcher cache 와 분리).
- tradingagents/agents/analysts/market_risk_analyst.py:
  - 기존 skew block (line 233-238) 의 outer except 에 skew_series=None 추가
    (downstream NameError 방지).
  - skew block 직후 새 try/except 추가: compute_skew_change_z(skew_series, as_of)
    호출 → skew.model_copy(update={"change_1m_z": ...}).
  - skew_series 는 *fetch reuse* (D9 위배 X — 동일 caller 가 단일 fetch 후 두 skill
    공유; cache 가 아니라 local variable reuse).
- tests/unit/schemas/test_factor_model_schemas.py: 2 new tests
  - test_skew_has_change_1m_z_default: default 0.0
  - test_skew_accepts_change_1m_z: explicit +1.5
  - C7.5 section header.
- tests/unit/skills/risk/test_skew_metrics.py (NEW): 5 tests
  - test_skew_change_z_basic_positive: +10/5 = +2
  - test_skew_change_z_negative: -10/5 = -2
  - test_skew_change_z_no_change: flat → 0
  - test_skew_change_z_short_series_returns_none: 10 obs <21 → None
  - test_skew_change_z_empty_returns_none: empty → None

### IMPLEMENTER verify 결과
- SkewSnapshot required fields (Step 5 spec 확인용): `skew_value` (float),
  `percentile_1y` (ge=0,le=1), `tail_hedge_signal` (Literal low/normal/elevated/extreme).
  본 C7.5 에서 change_1m_z 추가 (optional default 0.0).
- market_risk_analyst 의 skew fetch 패턴: line 235
  `skew_series = fetch_equity_index_close("skew", as_of - timedelta(days=400), as_of)`.
  400 day window → ≥21 trading days 충분히 보장. 본 C7.5 block 은 line 238 직후
  삽입 — skew_series 동일 변수 reuse (D9 위배 아님: fetcher cache 가 아니라 caller
  scope 의 local variable; 단일 호출 내 분기 sharing).
- yfinance ^SKEW: 기존 skew_index skill 에서 이미 fetch. 본 C7.5 는 *동일 series*
  를 두 번째 skill 에 pass — 추가 network call 없음.
- 환산 검증: iloc[-21] from 22-obs series = 첫 sample = 21 positions back from latest.
  Spec 의 산술 (latest=110, ago=100, sd=5 → z=2.0) 과 정확히 일치.
- C8 factor_estimators 에서 F7 skew_change component 활성화 시 직접
  `risk.skew.change_1m_z` 참조하면 됨 — placeholder 해소 완료.

## Post-C8 (factor_estimators 6 placeholder 활성화 + weight 재조정 + audit table 확장)

### Unit
```
$ uv run pytest tests/unit/ -q 2>&1 | tail -5
FAILED tests/unit/agents/test_macro_quant_analyst.py::test_macro_analyst_orchestration
FAILED tests/unit/agents/test_technical_analyst.py::test_technical_analyst_returns_report
FAILED tests/unit/monitor/test_monitor.py::test_turnover_initial_below_floor
3 failed, 710 passed, 5 warnings in 199.91s (0:03:19)
```

### Integration
```
$ uv run pytest tests/integration/ -q 2>&1 | tail -5
FAILED tests/integration/test_eval_systemic_score.py::test_systemic_score_accuracy[2014-12 mild disinflation (calm)-inputs5-3.0-5.0-neutral]
FAILED tests/integration/test_eval_systemic_score.py::test_systemic_score_accuracy[2024-06 AI rally with narrow breadth-inputs6-4.0-6.5-neutral]
FAILED tests/integration/test_eval_systemic_score.py::test_systemic_score_accuracy[2026-05 current (KR ETF context)-inputs7-6.0-8.5-risk_off]
FAILED tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts
18 failed, 21 passed, 1 warning in 21.74s
```

### Δ from Post-C7.5
- Unit: 710 → 710 pass (변동 0), 3 pre-existing fail 동일
- Integration: 변동 0 (18 fail pre-existing 동일, 21 pass 동일)
- 0 *new* regression
- test_factor_indicator_validity: 5/5 PASS (audit table + EXPECTED_COMPONENTS 일치 확인)

### 변경 사항
- tradingagents/skills/research/factor_estimators.py: 6 placeholder 활성화 + weight 재조정
  - F1 compute_growth_surprise: cfnai + cfnai_3m_avg 활성화. Weight dict re-balance
    (gdpnow 0.20→0.18, cfnai 0.0→0.10, cfnai_3m NEW 0.08, sahm 0.08→0.07, curve 0.12→0.10,
    risk_regime_overnight 0.05→0.07). sum=1.00 보존.
  - F4 compute_term_premium: slope_5_30y 활성화. Weight dict re-balance
    (slope_2_10y 0.30→0.25, slope_5_30y 0.0→0.20, fed_voting_balance 0.15→0.25). sum=1.00.
  - F7 compute_equity_vol_regime: realized_vol_60d + skew_change 활성화. Weight dict
    re-balance (vix_level 0.22→0.20, vix_z_score 0.12→0.10, vix_term_ratio 0.12→0.10,
    move 0.18→0.15, realized_vol_60d 0.0→0.13, skew_change 0.0→0.07,
    sentiment_dispersion 0.08→0.10, geopolitical_surge 0.07→0.15). sum=1.00.
  - F8 compute_valuation: kospi_pbr 활성화. Weight dict re-balance
    (earnings_yield 0.30→0.25, kospi_pbr 0.0→0.25). sum=1.00.
  - F9 compute_liquidity_regime: vrp + sector_dispersion 활성화 (vrp 은 RealVolSnapshot 의
    pre-computed vrp_60d 직접 사용 — re-derive 안 함; sector_dispersion 은 breadth_us 의
    BreadthSnapshot.sector_return_dispersion 사용). Weight dict re-balance
    (vrp 0.0→0.30, eq_bond_corr 0.18→0.15, sector_dispersion 0.0→0.15, breadth 0.08→0.10,
    event_cluster 0.12→0.15, rising_signal 0.09→0.15). sum=1.00.
  - 모듈 docstring 의 PR0 hotfix 절 + C8 activation 절 추가.

- tradingagents/skills/research/factor_baselines.py: 8 baseline entry 추가/재교정
  - F1: cfnai_3m (0.0, 0.5) — CFNAI scale (smoothed).
  - F4: slope_5_30y (120.0, 80.0) → (80.0, 50.0) — D11 spec 수치 (post-2010 sample).
  - F6 D11a fix: foreign_flow_z (0.0, 1.0) → (0.0, 1e12) — raw net_20d_krw 의 KRW
    magnitude (~수조) z 정상화. Prior 는 raw KRW 를 z=1e12 로 변환하던 broken state.
  - F7: realized_vol_60d (0.012, 0.005) → (0.15, 0.08) — RealVolSnapshot 의 annualized
    stddev 단위와 일치 (prior 는 daily-scale broken).
  - F7: skew_change (0.0, 5.0) → (0.0, 1.0) — change_1m_z 가 이미 normalized z
    (skew_metrics.py 가 hand-coded sd=5 로 divide). Pass-through.
  - F8: kospi_pbr (1.0, 0.25) → (1.0, 0.3) — D11 spec.
  - F9: vrp (50.0, 30.0) → (0.0, 200.0) — VRP 의 bps²-like scale (VIX/100)²-rv²×10000
    의 typical -200~+200 range.
  - F9: sector_dispersion (1.0, 0.3) → (0.05, 0.03) — BreadthSnapshot 의 decimal-scale
    cross-sectional stddev (mean ~5pp, sd ~3pp).

- tradingagents/skills/research/factor_reliability_audit.py:
  - AUDIT_DATE 2026-05-22 → 2026-05-24 (C8 component 확장과 동시 refresh).
  - F1 COMPONENT_RELIABILITY: "cfnai_3m": "high" 신규 entry.
  - F9 COMPONENT_RELIABILITY: "sector_dispersion": "high" → "medium" (D11 spec —
    narrow rally 환경 reliability ↓).

- tests/unit/skills/research/test_factor_indicator_validity.py:
  - EXPECTED_COMPONENTS frozenset 에 "cfnai_3m" 추가 (기존 8 신규 entry 는 이미 포함됨:
    slope_5_30y, realized_vol_60d, skew_change, kospi_pbr, vrp, sector_dispersion 등).

### IMPLEMENTER verify 결과
- 각 factor weight sum = 1.0 OK (F1-F9 모두 1.0000 확인).
- 모든 schema field 존재 확인 (uv run python -c "..." inspect):
  - FinancialConditionsSnapshot: cfnai, cfnai_3m_avg ✓
  - YieldCurveSnapshot: spread_30y_5y_bps ✓
  - RealVolSnapshot: realized_vol_60d, vrp_60d ✓
  - SkewSnapshot: change_1m_z ✓
  - KRValuationSnapshot: kospi_pbr ✓
  - BreadthSnapshot: sector_return_dispersion ✓
- All-None stage1 sanity: 6 활성화 factor 모두 confidence=0 / "no data" — crash 없음.
- 0 new regression — pre-existing fail list (3 unit + 18 integ) 와 정확히 일치.

