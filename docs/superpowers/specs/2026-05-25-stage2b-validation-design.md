# PR2b — Stage 2b Benchmark Comparison + Validation + Regen Design Spec

> Companion plan: `docs/superpowers/plans/2026-05-25-stage2b-validation.md`
> Status spec: draft (2026-05-25)
> Branch: `feat/stage2b-validation` (from `feat/stage2a-beta-calibration` HEAD or post-merge main)

---

## 0. Section 0 — Brainstorming decisions (2026-05-25)

| Key | Decision | Source |
|---|---|---|
| Q1 Final goal | Full PR2b scope — benchmark + validation + sensitivity + regen | brainstorm Q1 |
| Q2 Regime classifier | NBER recession (FRED USREC) — 2-state (expansion / recession) | brainstorm Q2 |
| Q3 Sensitivity sweeps | Full sweep — era split (pre-2010 / post-2010) + robustness penalty {0.10, 0.50} + sample_quality stratified | brainstorm Q3 |
| Q4 Regen scope | Full pipeline replay — `scripts/replay_stage.py --as-of 2026-05-15 --write-archive`, LLM 포함 | brainstorm Q4 |
| Q5 Commit structure | Approach B — domain-grouped 6 commits (C0-C5) | brainstorm Q5 |
| Q6 Grill-me checkpoints | 2개 — C2 직후 (validation 결과 확인), C4 직후 (regen 확인) | derived from B |

### 0.1 Out of scope

- **Re-calibration**: PR2a 의 INITIAL_BETA 그대로 사용 (PR2a 결과 신뢰)
- **새 benchmark 추가**: 4 benchmark fix (24-cell / 60-40 / 1-N / risk parity)
- **다른 시점 산출물 regen**: 2026-05-15 만 (다른 날짜는 별도 follow-up)
- **자동 PR 머지 / production 배포**: human review 후 별도

### 0.2 Critical issues

| ID | Issue | Mitigation |
|---|---|---|
| K1 | Calibrated 가 어떤 benchmark 에 짐 | 명시적 경고 reporting, "PASS but with caveat" verdict 가능 |
| K2 | NBER recession sample size 작음 (1991-2024 중 ~13 quarters) | paired-t 약함 → 효과크기 (effect size, Cohen's d) + descriptive reporting 병행 |
| K3 | Production regen LLM 실패 | grill-me #2 에서 user 결정 — partial replay 또는 skip |
| K4 | Working tree 의 user/linter 25+ files 평행 수정 | PR2b 시작 전 별도 commit 또는 stash 처리 (plan C0 의 step 0) |

### 0.3 Minor (informational only)

| ID | Note | Disposition |
|---|---|---|
| m1 | risk parity 의 covariance estimation window (60Q rolling vs full sample) | Plan C1 의 implementation note |
| m2 | sample_quality stratified 의 weight scheme (linear vs squared) | Plan C3 의 implementation note |
| m3 | era split boundary (2010-01-01 vs 2011-06-30 ALFRED first vintage) | Plan C3 의 implementation note — 기본 2010-01-01 |

---

## 1. Goal

PR2a 의 walk-forward calibration 결과 (INITIAL_BETA, +41% OOS Sharpe vs hand-coded prior) 의 **robustness 와 production 통합** 검증.

답해야 할 5개 질문:
1. Hand-coded 외 4 benchmark (24-cell / 60-40 / 1-N / risk parity) 대비도 우월한가?
2. NBER expansion vs recession 두 regime 모두에서 우월한가?
3. Era split (pre-2010 / post-2010) 에서 β 가 stable 한가?
4. Robustness penalty 계수 변경 시 best shrinkage 가 stable 한가?
5. Production pipeline 통합 시 의미 있는 portfolio 변화 발생하는가?

---

## 2. Architecture overview

### 2.1 Pipeline

```
[backtest/historical/samples.parquet]  ← PR2a output, 133 samples
        │
        ▼
[scripts/validate_factor_model.py]
        │
        ├──→ Benchmark suite (4):
        │     - calibrated (INITIAL_BETA = PR2a)
        │     - hand-coded prior (pre-PR2a, hardcoded snapshot)
        │     - 24-cell legacy (optimize.fit_all)
        │     - 60-40 KR-tilted (factor_calibration.benchmark_60_40_returns)
        │     - 1-N equal weight (NEW)
        │     - Risk parity (NEW, pyportfolioopt)
        │
        ├──→ Regime classifier:
        │     NBER USREC FRED daily → quarterly (any USREC=1 → recession)
        │
        ├──→ Statistical tests:
        │     - Paired-t calibrated vs each benchmark
        │     - Per-regime Sharpe (expansion vs recession)
        │     - Drawdown analysis per strategy
        │
        ▼
[artifacts/2026-05-25/validation/validation_report.md, .json]
        │
        ▼ (C3)
[scripts/sensitivity_sweep.py]
        │
        ├──→ Era split: pre-2010 / post-2010 각각 calibrate, β diff
        ├──→ Robustness {0.10, 0.50}: best_shrinkage 변화
        ├──→ Sample quality stratified: confidence-weighted vs unweighted
        │
        ▼
[artifacts/2026-05-25/sensitivity/{era_split,robustness_penalty,sample_quality}.json]
[artifacts/2026-05-25/sensitivity/sensitivity_report.md]
        │
        ▼ (C4)
[scripts/replay_stage.py --as-of 2026-05-15 --write-archive]
        │
        ▼
[artifacts/2026-05-15/*.{json,md,csv}]  ← 교체
[artifacts/2026-05-25/regen/diff_report.md]  ← 이전/이후 비교
```

### 2.2 신규 / Modified files

**Created (production code)**:
- `tradingagents/backtest/benchmarks.py` — equal_weight, risk_parity bucket weight 함수
- `tradingagents/backtest/regime.py` — NBER classifier (USREC FRED 사용)
- `tradingagents/backtest/statistics.py` — paired_t_vs_benchmark, regime_decomposition, drawdown

**Created (tests)**:
- `tests/unit/backtest/test_benchmarks.py`
- `tests/unit/backtest/test_regime.py`
- `tests/unit/backtest/test_statistics.py`

**Created (scripts)**:
- `scripts/validate_factor_model.py`
- `scripts/sensitivity_sweep.py`

**Modified**:
- `artifacts/2026-05-15/*` — production regen 후 교체 (4 files)
- `docs/followup_issues.md` — Issue #18 FULLY VERIFIED status update

**Created (artifacts)**:
- `artifacts/2026-05-25/decisions.md`
- `artifacts/2026-05-25/regression_log.md`
- `artifacts/2026-05-25/job_status.json`
- `artifacts/2026-05-25/validation/{validation_report.md, validation_report.json}`
- `artifacts/2026-05-25/sensitivity/{era_split.json, robustness_penalty.json, sample_quality.json, sensitivity_report.md}`
- `artifacts/2026-05-25/regen/diff_report.md`

---

## 3. Components

### 3.1 `benchmarks.py` — bucket weight 생성 함수 4개

```python
def equal_weight() -> dict[str, float]:
    """1/N: 각 bucket = 0.2."""

def risk_parity(
    returns: pd.DataFrame,  # bucket × time matrix
    window: int = 60,  # 60-quarter rolling covariance
) -> dict[str, float]:
    """σ-inverse weighted. pyportfolioopt.HRPOpt 또는 1/σ 단순."""

def cell_24_legacy(
    macro_q: pd.DataFrame,  # quarterly indicator panel
    sample_date: date,
) -> dict[str, float]:
    """24-cell legacy: classify cells → fit_all → bucket allocation."""

def kr_tilted_60_40() -> dict[str, float]:
    """Wrapper for existing 60_40: {kr_eq: 0.20, gl_eq: 0.40, bond: 0.40}."""
```

**Note**: `hand_coded_prior` 는 별도 함수 불요 — factor_to_bucket 의 INITIAL_BETA 가 PR2a 에서 이미 교체 됐으므로, hand-coded 는 git history snapshot 또는 hardcoded dict 로 보존.

### 3.2 `regime.py` — NBER classifier

```python
def fetch_nber_recession_quarterly(
    start: date, end: date,
    cache_dir: Path | None = None,
) -> pd.Series:
    """FRED USREC monthly → resample('QE').max()  (quarter 내 1개월 이상 recession → recession)
    Returns: bool Series indexed by quarter end.
    """

def split_samples_by_regime(
    samples: list[HistoricalSample],
    recession_flag: pd.Series,
) -> tuple[list, list]:
    """(expansion_samples, recession_samples) — sample_date 기준."""
```

### 3.3 `statistics.py` — 통계 검증 utilities

```python
def paired_t_vs_benchmark(
    calibrated_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    alternative: str = "greater",
) -> dict:
    """scipy.stats.ttest_rel + Cohen's d effect size."""

def regime_decomposition(
    returns_per_strategy: dict[str, np.ndarray],
    recession_mask: np.ndarray,
) -> dict:
    """Per-strategy Sharpe in expansion vs recession."""

def drawdown_analysis(
    returns: np.ndarray,
) -> dict:
    """{max_drawdown, drawdown_start, drawdown_end, recovery_quarters}."""
```

### 3.4 `scripts/validate_factor_model.py`

**Inputs**:
- `--samples backtest/historical/samples.parquet`
- `--output-dir artifacts/2026-05-25/validation/`
- `--initial-train-size 80 --test-window 7` (PR2a 와 동일 walk-forward)

**Pipeline**:
1. load samples → 6 strategies' walk-forward OOS returns
   (calibrated / hand-coded prior / 24-cell / 60-40 / 1-N / risk parity)
2. NBER recession mask (cached or FRED fetch)
3. Pairwise stats: calibrated vs 5 benchmarks (5 paired-t tests)
4. Per-regime Sharpe for all 6 strategies
5. Drawdown analysis for all 6
6. Output validation_report.md + .json

### 3.5 `scripts/sensitivity_sweep.py`

**Three sub-runs**:

1. **Era split**: split samples at 2010-01-01
   - Run calibration on pre-2010 (~70 samples)
   - Run calibration on post-2010 (~63 samples)
   - Compute β_pre vs β_post divergence (|β_pre - β_post|_avg)

2. **Robustness penalty**: rerun `select_best_shrinkage` with {0.10, 0.50}
   - best_shrinkage 변화 여부 (현재 0.25 → 2.0 best)
   - Δ best_shrinkage (with 0.10) vs (with 0.50)

3. **Sample quality stratified**: weight samples by mean confidence
   - Weighted hybrid_calibration (custom — 또는 sample 별 sample_weight scaling)
   - β_weighted vs β_unweighted divergence

**Output**: 3 json + sensitivity_report.md (markdown table 형식)

### 3.6 `scripts/replay_stage.py` — production regen

**기존 스크립트 재사용**. PR2b 에서는 추가 작성 없음.

```bash
uv run python scripts/replay_stage.py --as-of 2026-05-15 --write-archive
```

산출물: `artifacts/2026-05-15/*` 교체.

**Diff report** (PR2b 자체 작성):
- old artifacts (git history) vs new artifacts diff
- portfolio.json 의 bucket weight 변화
- philosophy.md 의 narrative 차이 (LLM-derived 라 deterministic 아님)
- backtest_summary.json 의 metric 변화

---

## 4. Validation report format

**`artifacts/2026-05-25/validation/validation_report.md`**:

```markdown
# PR2b Validation Report (2026-05-25)

## Executive Summary
[1-paragraph: PR2a +41% Sharpe gain holds across 5 benchmarks and 2 NBER regimes]

## Methodology
- Samples: 133 quarters (1991-Q2 ~ 2024-Q2)
- Walk-forward: initial_train=80, test_window=7, 7 folds
- Best shrinkage: 2.0 (from PR2a)
- Significance: paired-t alternative='greater', p < 0.20

## Section 1: Benchmark Comparison (Full Period)

| Strategy | Mean OOS Sharpe | Std OOS | Max DD | vs Calibrated p | Cohen's d |
|---|---|---|---|---|---|
| Calibrated (PR2a) | 1.17 | ... | ... | — | — |
| Hand-coded prior | 0.83 | ... | ... | 0.080 | ... |
| 24-cell legacy | ... | ... | ... | ... | ... |
| 60-40 KR-tilted | ... | ... | ... | ... | ... |
| 1-N equal weight | ... | ... | ... | ... | ... |
| Risk parity | ... | ... | ... | ... | ... |

**Verdict**: [PASS / PASS with caveat / FAIL]

## Section 2: NBER Regime Decomposition

| Strategy | Expansion Sharpe (N=~120) | Recession Sharpe (N=~13) | Spread |
|---|---|---|---|
| Calibrated | ... | ... | ... |
| ... | ... | ... | ... |

## Section 3: Drawdown Analysis

| Strategy | Max DD | DD Start | DD End | Recovery Q |
|---|---|---|---|---|

## Section 4: Conclusion
[Robust? Any benchmark > calibrated? Recession concern? Recommend INITIAL_BETA keep/revert/refine?]
```

---

## 5. Sensitivity report format

**`artifacts/2026-05-25/sensitivity/sensitivity_report.md`**:

```markdown
# PR2b Sensitivity Report (2026-05-25)

## Section 1: Era Split (pre-2010 / post-2010)

| Metric | Pre-2010 (N=~70) | Post-2010 (N=~63) | Full (N=133) |
|---|---|---|---|
| Best shrinkage | ... | ... | 2.0 |
| Mean OOS Sharpe | ... | ... | 1.17 |
| |β diff vs full|_avg | ... | ... | — |

**Stability verdict**: [STABLE / DRIFT detected]

## Section 2: Robustness Penalty {0.10, 0.25, 0.50}

| Penalty coefficient | Best shrinkage | Mean OOS Sharpe |
|---|---|---|
| 0.10 | ... | ... |
| 0.25 (default) | 2.0 | 1.17 |
| 0.50 | ... | ... |

**Stability verdict**: [STABLE / SENSITIVE]

## Section 3: Sample Quality Stratified

| Weighting | Best shrinkage | Mean OOS Sharpe | |β diff vs unweighted|_avg |
|---|---|---|---|
| Unweighted (default) | 2.0 | 1.17 | — |
| Confidence-weighted | ... | ... | ... |

**Verdict**: [Quality-stratification 영향 negligible / Significant]
```

---

## 6. Test strategy

- Unit tests: each utility module (benchmarks / regime / statistics) 별 ~5 tests
- Synthetic integration: small fake samples 로 validate_factor_model.py + sensitivity_sweep.py smoke
- 0 new regression failure (PR2a baseline: 2 unit + 18 integ fail)

---

## 7. Backward compatibility

- 신규 file 만 추가 (production code 변경 무)
- Exception: `artifacts/2026-05-15/*` 교체 (production output regen) — git history 보존됨
- Test 변경 없음

---

## 8. Risks + Mitigation

| Risk | Probability | Mitigation |
|---|---|---|
| Calibrated 가 60-40 같은 simple benchmark 에 짐 | 중 | 명시적 reporting, INITIAL_BETA 유지 또는 refine 권장 |
| NBER recession N=13 너무 작아 paired-t 무의미 | 높음 | Cohen's d 효과크기 병행 reporting |
| pyportfolioopt risk_parity 가 numerical 문제 | 낮음 | Fallback 으로 1/σ 단순 weighting |
| Production regen 의 LLM 호출 실패 (API timeout, rate) | 중 | grill-me #2 에서 user 결정 (skip 또는 partial) |
| 2026-05-15 의 외부 데이터 fetch 실패 (FRED/yfinance) | 중 | TieredCache 활용 (PR1 의 기존 cache) |

---

## 9. Sign-off Checklist

본 PR2b merge 의 조건:

- [ ] 모든 unit + integration test pass (PR2a baseline 2 unit + 18 integ 외 0 new failure)
- [ ] C1 의 4 utility module unit test pass (15+ tests)
- [ ] C2 의 validation_report.md generated + 모든 5 benchmark 결과 포함
- [ ] C3 의 sensitivity_report.md generated + 3 sub-report 모두 작성
- [ ] C4 의 production regen — 4 artifacts (backtest_summary, philosophy, portfolio, trade_plan) 교체 또는 partial success 명시
- [ ] 2 grill-me 세션의 decision 기록 (artifacts/2026-05-25/decisions.md)
- [ ] regression_log.md 매 commit 별 entry — 0 new failure 검증
- [ ] docs/followup_issues.md Issue #18 status update (FULLY VERIFIED 또는 caveat)
- [ ] PR2b conclusion: keep / refine / revert INITIAL_BETA 결정 명시

---

## 10. PR2b 종착점 (다음 단계 입력)

- **PASS verdict**: INITIAL_BETA = PR2a calibrated → production 유지. 다음 단계 = PR2c (다른 sensitivity 또는 ablation 또는 quarterly re-calibration cadence)
- **PASS with caveat**: keep INITIAL_BETA but log caveat in followup_issues.md
- **FAIL**: INITIAL_BETA revert to hand-coded — PR2a 결과 미신뢰. Issue 신설.

---

## 11. 참조

- PR2a spec: `docs/superpowers/specs/2026-05-23-stage2a-calibration-design.md`
- PR2a plan: `docs/superpowers/plans/2026-05-23-stage2a-calibration.md`
- PR2a final decisions: `artifacts/2026-05-24/decisions.md`
- PR2a validation: `artifacts/2026-05-24/calibration_runs/validation_report.json`
- Backlog: `docs/followup_issues.md` Issue #18
