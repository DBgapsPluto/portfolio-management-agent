# PR2a Regression Log

매 commit 직후 본 파일 에 entry 추가:
- Commit ID + message
- Unit test result (passed/failed count)
- Integration test result (passed/failed count)
- Δ from previous commit (new fail or new pass)
- 0 new failure 확인

## Baseline (post PR1 merge 3572d03 / pre PR2a C0, 2026-05-24)

```
$ uv run pytest tests/unit/ -q
2 failed, 741 passed, 6 warnings in 79.70s

  FAILED tests/unit/agents/test_technical_analyst.py::test_technical_analyst_returns_report
  FAILED tests/unit/skills/test_portfolio_attribution.py::test_select_etf_candidates_populates_attribution

$ uv run pytest tests/integration/ -q
18 failed, 26 passed, 2 warnings in 18.66s

  FAILED tests/integration/test_5_28_dry_run.py::test_5_28_dry_run_produces_artifacts
  FAILED tests/integration/test_eval_regime_classifier.py::test_regime_classifier_accuracy[…] × 8
  FAILED tests/integration/test_eval_systemic_score.py::test_systemic_score_accuracy[…] × 8
  FAILED tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts
```

Pre-existing fail: **2 unit + 18 integration** (post PR1 merge baseline).

NOTE: Plan 의 "3 unit failed" 예상치는 pre-PR1-merge 기준. PR1 merge (3572d03)
후 unit fail 이 3→2 로 감소. 본 baseline 이 PR2a 의 ground truth.

## Post-C0 (chore: execution safeguards) — commit 88621df

```
$ uv run pytest tests/unit/ -q
2 failed, 741 passed, 6 warnings in 74.42s

$ uv run pytest tests/integration/ -q
18 failed, 26 passed, 2 warnings in 16.64s
```

Δ from baseline: **0 new failure, 0 new pass**. Identical to baseline.

C0 의 모든 변경 (artifacts scaffolding + .gitignore 1줄) 은 production code
미수정 — regression 영향 없음 확인.

Status: PASS. C1 진행 가능.

## Post-C1 (feat: historical fetchers FRED + ALFRED + yfinance + pykrx)

```
$ uv run pytest tests/unit/ -q
2 failed, 752 passed, 6 warnings in 77.44s

$ uv run pytest tests/integration/ -q
18 failed, 26 passed, 2 warnings in 18.38s
```

Δ from baseline:
- Unit: +11 new pass (3 fred + 3 alfred + 3 yfinance + 2 pykrx). 0 new fail.
- Integration: unchanged.

**Plan errata fix (test-only, code unchanged)**:
- test_fetcher_alfred.py: cache date range alignment + mock boundary `<` → `<=`.
  Plan 의 test spec 의 self-consistency 미스 (cache range 와 request range
  불일치, mock 의 strict `<` 가 expected list 와 불일치). production logic
  은 정확 — test 만 보정.

Status: PASS. C2 진행 가능.

## Post-C2 (feat: quarterly aggregation + derived computations)

```
$ uv run pytest tests/unit/ -q
2 failed, 761 passed, 6 warnings in 76.02s

$ uv run pytest tests/integration/ -q
18 failed, 26 passed, 2 warnings in 16.60s
```

Δ from C1: Unit +9 new pass (8 derived + 1 panel structure). 0 new fail.
Integration: unchanged.

Deferred: Shiller CAPE CSV (Task 2.3) — `assemble_quarterly_panel` 의
graceful skip 으로 C2 commit 영향 없음. C5 (135Q sample 생성) 전 까지
보강 필요.

Status: PASS. C3 진행 가능.

## Post-C3 (feat: historical Stage 1 builder + KRW-basis bucket returns)

```
$ uv run pytest tests/unit/ -q
2 failed, 769 passed, 6 warnings in 78.55s

$ uv run pytest tests/integration/ -q
18 failed, 26 passed, 2 warnings in 17.45s
```

Δ from C2: Unit +8 new pass (5 builder + 3 bucket_returns). 0 new fail.
Integration: unchanged.

**Plan template substantial divergence (production schema 기준 재작성)**:
Plan 의 stage1_builder template 은 production PR1 schema 와 광범위하게 불일치
(MoveSnapshot/BreadthKRSnapshot/FundingSnapshot 부재 + EmploymentSnapshot/
KRExportSnapshot/RegimeClassification field 오류 + MacroReport 의 9+ required
field 누락). 실제 production schema 와 tests/integration/
test_factor_estimators_real_schema.py 의 `_build_baseline_*_report()` 패턴을
참조하여 self-contained baseline builder 구성. quarterly panel 의 column
값으로 일부 field overlay (model_copy with update).

Status: PASS. **grill-me #1 marker (Task 3.4)** 도달.

## Post-C4 (feat: factor_estimators mode='historical' flag — Critical 2)

```
$ uv run pytest tests/unit/ -q
2 failed, 773 passed, 6 warnings in 80.51s

$ uv run pytest tests/integration/ -q
18 failed, 26 passed, 2 warnings in 17.28s
```

Δ from C3: Unit +4 new pass (production-mode default backward-compat,
historical-mode drops news, confidence range, NEWS_DERIVED_COMPONENTS const).
Integration: unchanged.

**Backward compat 검증**:
- test_factor_estimators_real_schema (existing 83 tests) + 4 new = 87 PASS.
- production mode default 호출 → PR1 의 100% identical (test_production_mode_
  default_matches_explicit).

Status: PASS. C5 (135Q sample 생성) 진행 가능.

## Post-C5 (data: historical factor z + bucket returns 1991-2024)

```
$ uv run pytest tests/unit/ -q
2 failed, 774 passed, 6 warnings in 77.69s

$ uv run pytest tests/integration/ -q
18 failed, 26 passed, 2 warnings in 17.54s
```

Δ from C4: Unit +1 new pass (test_call_alfred_400_returns_none).
Integration: unchanged.

**Generation run (2026-05-24, 2 attempts)**:
- 1차 시도: 5/7 ALFRED series 가 첫 quarter (1991-03-31) 의 400 에러로
  전체 시리즈 fetch 중단. 해당 series 는 1991 년에 아직 발행 안 됨
  (CFNAI, NFCI, ANFCI, GDPNOW, PCEPILFE).
- Fix: `_call_alfred` 가 HTTP 400 을 None 으로 graceful 처리.
- 2차 시도: 7 ALFRED series 모두 성공 fetch. 각 시리즈 의 vintage 시작점
  자동 detect (CFNAI: 2011-06-30+, GDPNow: 2016-06-30+, UNRATE: 1991+).

**산출물**:
- backtest/historical/quarterly_indicators.parquet: 135Q × 37 col (49KB)
- backtest/historical/factor_z.parquet: 135Q × 18 col (23KB)
- backtest/historical/bucket_returns.parquet: 134Q × 5 col (11KB)
- backtest/historical/samples.parquet: 133 row × 23 col (31KB)
- raw cache: 3.9MB (gitignored)

**Sanity (2008-Q4 GFC)**: factor z 가 합리적인 stress signature:
- inflation_surprise = -2.21 (deflationary shock)
- real_rate = +1.31 (real rate spike during deflation)
- credit_cycle = +0.34 (credit stress)
- equity_vol_regime = +1.83 (high vol)

Status: PASS. **grill-me #2 marker (Task 5.4)** 도달.
