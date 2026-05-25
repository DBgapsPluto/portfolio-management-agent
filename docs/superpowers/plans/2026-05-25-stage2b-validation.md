# Stage 2b — Validation + Benchmark Comparison + Regen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PR2a INITIAL_BETA (calibrated +41% Sharpe gain) 의 robustness 와 production 통합 검증 — 5 benchmark 비교 + NBER regime decomposition + sensitivity sweep + 2026-05-15 산출물 regen.

**Architecture:** Domain-grouped 6 commits (C0-C5). PR2a 의 samples.parquet 를 input 으로 4 신규 utility module (benchmarks/regime/statistics) + 2 신규 script (validate_factor_model / sensitivity_sweep) 작성. Production regen 은 기존 scripts/replay_stage.py 재사용. 2 grill-me checkpoints (C2 직후 / C4 직후).

**Tech Stack:** Python 3.12, pyportfolioopt (risk parity), scipy.stats (ttest_rel, Cohen's d), pandas, numpy, pytest, parquet.

**Spec:** `docs/superpowers/specs/2026-05-25-stage2b-validation-design.md`

**Branch base:** `main` (PR2a 가 main 에 머지 완료, commit `2efac94` 이후).

**Quality gates:**
- 매 commit 후 regression test (pytest unit + integration) + `artifacts/2026-05-25/regression_log.md` 갱신 (0 new failure 검증)
- 2 grill-me 시점 (after C2 validation 실행 / after C4 production regen)

**Run date:** `<run-date>` = 2026-05-25 (plan 의 모든 path 의 `2026-05-25` 는 실제 실행일 로 치환).

---

## File Structure

### Created (production code)
- `tradingagents/backtest/benchmarks.py` — 5 bucket weight 생성 함수 + pre-PR2a hand-coded β snapshot
- `tradingagents/backtest/regime.py` — NBER USREC classifier + sample split helper
- `tradingagents/backtest/statistics.py` — paired_t_vs_benchmark, regime_decomposition, drawdown_analysis

### Created (tests)
- `tests/unit/backtest/test_benchmarks.py` — equal_weight + risk_parity + 60_40 + hand-coded snapshot tests (5+ tests)
- `tests/unit/backtest/test_regime.py` — NBER classifier + sample split tests (4+ tests)
- `tests/unit/backtest/test_statistics.py` — paired_t + regime_decomp + drawdown tests (5+ tests)

### Created (scripts)
- `scripts/validate_factor_model.py` — load samples → 6 strategies' walk-forward OOS → report
- `scripts/sensitivity_sweep.py` — era split + robustness penalty + sample quality stratified

### Created (artifacts)
- `artifacts/2026-05-25/decisions.md`
- `artifacts/2026-05-25/regression_log.md`
- `artifacts/2026-05-25/job_status.json`
- `artifacts/2026-05-25/validation/validation_report.md`
- `artifacts/2026-05-25/validation/validation_report.json`
- `artifacts/2026-05-25/sensitivity/era_split.json`
- `artifacts/2026-05-25/sensitivity/robustness_penalty.json`
- `artifacts/2026-05-25/sensitivity/sample_quality.json`
- `artifacts/2026-05-25/sensitivity/sensitivity_report.md`
- `artifacts/2026-05-25/regen/diff_report.md`

### Modified
- `artifacts/2026-05-15/*.{json,md,csv}` (C4 production regen 산출 — git history 보존)
- `docs/followup_issues.md` — Issue #18 FULLY VERIFIED status

---

## Task 0: Scaffolding + Branch (C0)

### Task 0.1: 새 branch 생성 + working tree 확인

**Files:** branch creation, no files yet

- [ ] **Step 1: 현재 상태 확인**

```bash
git status --short
git branch --show-current
git log --oneline -3
```

Expected: 현재 branch `feat/stage2b-validation` (이미 spec commit `26241e8` 으로 생성됨). 작업 트리 clean.

- [ ] **Step 2: regression baseline 확인**

```bash
uv run python -m pytest tests/unit/ -q 2>&1 | tail -3
uv run python -m pytest tests/integration/ -q 2>&1 | tail -3
```

Expected baseline (post PR2a merge):
- Unit: 2 failed (`test_technical_analyst_returns_report`, `test_select_etf_candidates_populates_attribution`) / 786+ passed
- Integration: 18 failed (eval_systemic_score variants + eval_regime_classifier variants + test_plan_pipeline_mock + test_5_28_dry_run) / 28+ passed

→ 실제 결과가 baseline 와 다르면 plan 시작 전 검토.

### Task 0.2: artifacts/2026-05-25/ scaffolding

**Files:**
- Create: `artifacts/2026-05-25/decisions.md`
- Create: `artifacts/2026-05-25/regression_log.md`
- Create: `artifacts/2026-05-25/job_status.json`
- Create: `artifacts/2026-05-25/validation/.gitkeep`
- Create: `artifacts/2026-05-25/sensitivity/.gitkeep`
- Create: `artifacts/2026-05-25/regen/.gitkeep`

- [ ] **Step 1: 디렉토리 + .gitkeep 생성**

```bash
mkdir -p artifacts/2026-05-25/validation artifacts/2026-05-25/sensitivity artifacts/2026-05-25/regen
touch artifacts/2026-05-25/validation/.gitkeep
touch artifacts/2026-05-25/sensitivity/.gitkeep
touch artifacts/2026-05-25/regen/.gitkeep
```

- [ ] **Step 2: decisions.md 생성**

`artifacts/2026-05-25/decisions.md`:

```markdown
# PR2b Validation — Decisions Log

본 파일은 spec `2026-05-25-stage2b-validation-design.md` 의 section 0 결정 외부화.
2 grill-me 결정 본 파일에 append.

## Brainstorming 결정 (확정 — 2026-05-25)

- Q1 Final goal: Full PR2b scope (benchmark + validation + sensitivity + regen)
- Q2 Regime classifier: NBER recession (FRED USREC), 2-state (expansion / recession)
- Q3 Sensitivity sweeps: Full (era split pre/post-2010 + robustness penalty {0.10, 0.50} + sample_quality stratified)
- Q4 Regen scope: Full pipeline replay (scripts/replay_stage.py, LLM 포함)
- Q5 Commit structure: Approach B (domain-grouped 6 commits C0-C5)
- Q6 Grill-me: 2회 (C2 직후 + C4 직후)

## Critical issues 처리

- K1 (caveat reporting): validation_report 에 calibrated < benchmark 항목 명시
- K2 (NBER small N): Cohen's d 효과크기 병행
- K3 (regen LLM 실패): grill-me #2 결정 (skip 또는 partial)
- K4 (working tree 정리): C0 step 1 에서 main 기준 새 branch 확인

## grill-me decisions (appended at each grill point)

(grill-me #1: TBD — C2 validation 실행 직후)
(grill-me #2: TBD — C4 regen 실행 직후)
```

- [ ] **Step 3: regression_log.md 생성**

`artifacts/2026-05-25/regression_log.md`:

```markdown
# PR2b Regression Log

매 commit 직후 본 파일 에 entry 추가:
- Commit ID + message
- Unit test result (passed/failed count)
- Integration test result (passed/failed count)
- Δ from previous commit
- 0 new failure 검증

## Baseline (post PR2a merge / pre PR2b C0, 2026-05-25)

```
$ uv run python -m pytest tests/unit/ -q
2 failed, 786 passed (or current main count)

$ uv run python -m pytest tests/integration/ -q
18 failed, 28 passed (or current main count)
```

Pre-existing fail (PR2a post-merge baseline).

## Post-C0 (chore: scaffolding)
[fill at C0 commit time]
```

- [ ] **Step 4: job_status.json 생성**

`artifacts/2026-05-25/job_status.json`:

```json
{
  "pr": "PR2b — Stage 2b validation + benchmark + regen",
  "branch": "feat/stage2b-validation",
  "started_at": "2026-05-25T00:00:00Z",
  "current_commit": "C0",
  "status": "scaffolding",
  "long_running_jobs": {},
  "notes": "PR2a merge 후. INITIAL_BETA = calibrated. samples.parquet (133 rows) 사용."
}
```

- [ ] **Step 5: commit**

```bash
git add -f artifacts/2026-05-25/decisions.md \
            artifacts/2026-05-25/regression_log.md \
            artifacts/2026-05-25/job_status.json \
            artifacts/2026-05-25/validation/.gitkeep \
            artifacts/2026-05-25/sensitivity/.gitkeep \
            artifacts/2026-05-25/regen/.gitkeep

git commit -m "$(cat <<'EOF'
chore(stage2b): scaffolding + decisions/regression baseline (C0)

PR2b (validation + benchmark + regen) 시작 의 safeguard scaffolding.

- artifacts/2026-05-25/decisions.md: spec section 0 결정 외부화 + grill-me
  decision 누적 영역.
- artifacts/2026-05-25/regression_log.md: 매 commit baseline 비교 영역
  (PR2a post-merge baseline 기록).
- artifacts/2026-05-25/job_status.json: long-running job (validation /
  sensitivity / regen) progress tracking.
- validation/ sensitivity/ regen/ 하위 디렉토리 (.gitkeep).

다음 commit (C1) 부터 본 scaffold 사용.
EOF
)"
```

- [ ] **Step 6: post-C0 regression**

```bash
uv run python -m pytest tests/unit/ -q 2>&1 | tail -3
uv run python -m pytest tests/integration/ -q 2>&1 | tail -3
```

Expected: baseline 동일 (production code 변경 무). `regression_log.md` 의 "## Post-C0" entry 채움.

---

## Task 1: Validation Utilities (C1)

본 commit 은 3 utility module (benchmarks / regime / statistics) + 각각 의 unit test 단일 commit. 모두 production code 의 신규 module 이며 기존 import 영향 없음.

### Task 1.0: Pre-PR2a hand-coded INITIAL_BETA snapshot 확보

PR2a 가 INITIAL_BETA 를 교체했으므로 hand-coded 원본 은 git history 에 있음. benchmarks.py 에 inline literal 로 보존.

- [ ] **Step 1: git history 에서 추출**

```bash
git show 3572d03:tradingagents/skills/research/factor_to_bucket.py | sed -n '74,130p'
```

Expected: 45 entries 의 hand-coded β literal (Task 1.1 의 HAND_CODED_BETA_PR2A_PRE constant 로 사용).

### Task 1.1: `benchmarks.py` — 5 bucket weight 함수 + hand-coded snapshot

**Files:**
- Create: `tradingagents/backtest/benchmarks.py`
- Create: `tests/unit/backtest/test_benchmarks.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/backtest/test_benchmarks.py`:

```python
"""Unit tests for benchmarks.py — 5 bucket weight functions."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tradingagents.backtest.benchmarks import (
    HAND_CODED_BETA_PR2A_PRE,
    equal_weight,
    kr_tilted_60_40,
    risk_parity,
)
from tradingagents.skills.research.factor_to_bucket import BUCKETS, FACTORS


def test_equal_weight_sums_to_one_per_bucket() -> None:
    """1/N: 각 bucket = 0.2, sum=1.0."""
    w = equal_weight()
    assert set(w.keys()) == set(BUCKETS)
    for b in BUCKETS:
        assert w[b] == pytest.approx(0.2)
    assert sum(w.values()) == pytest.approx(1.0)


def test_kr_tilted_60_40_specific_weights() -> None:
    """60-40 KR-tilted: kr_eq 0.20 + gl_eq 0.40 + bond 0.40."""
    w = kr_tilted_60_40()
    assert w["kr_equity"] == pytest.approx(0.20)
    assert w["global_equity"] == pytest.approx(0.40)
    assert w["bond"] == pytest.approx(0.40)
    assert w["fx_commodity"] == pytest.approx(0.0)
    assert w["cash_mmf"] == pytest.approx(0.0)
    assert sum(w.values()) == pytest.approx(1.0)


def test_risk_parity_weights_sum_to_one_and_inverse_to_vol() -> None:
    """Risk parity: σ-inverse weighted."""
    # 5 bucket × 100 quarter synthetic returns.
    rng = np.random.default_rng(42)
    n = 100
    returns = pd.DataFrame(
        {b: rng.normal(0, 0.01 * (i + 1), n) for i, b in enumerate(BUCKETS)},
    )
    w = risk_parity(returns, window=60)
    assert set(w.keys()) == set(BUCKETS)
    assert sum(w.values()) == pytest.approx(1.0, rel=1e-6)
    # Lower-vol bucket (first) should have higher weight than highest-vol bucket (last).
    assert w[BUCKETS[0]] > w[BUCKETS[-1]]


def test_hand_coded_beta_pr2a_pre_45_entries() -> None:
    """45 entries (9 factors × 5 buckets)."""
    assert len(HAND_CODED_BETA_PR2A_PRE) == 45
    for f in FACTORS:
        for b in BUCKETS:
            assert (f, b) in HAND_CODED_BETA_PR2A_PRE


def test_hand_coded_beta_pr2a_pre_row_sums_zero() -> None:
    """Hand-coded prior 의 row sum = 0 invariant (pre-PR2a 설계)."""
    for f in FACTORS:
        row_sum = sum(
            HAND_CODED_BETA_PR2A_PRE.get((f, b), 0.0) for b in BUCKETS
        )
        assert abs(row_sum) < 1e-6, f"{f}: row sum {row_sum}"
```

- [ ] **Step 2: 테스트 실행 → fail**

```bash
uv run python -m pytest tests/unit/backtest/test_benchmarks.py -v
```

Expected: ImportError — `benchmarks.py` 부재.

- [ ] **Step 3: 최소 구현**

`tradingagents/backtest/benchmarks.py`:

```python
"""Benchmark bucket weight generators for PR2b validation.

5 strategies:
1. equal_weight (1/N)
2. kr_tilted_60_40 (60-40 KR-tilted)
3. risk_parity (σ-inverse, 60Q rolling cov)
4. (calibrated PR2a — uses INITIAL_BETA via factor_to_bucket.apply_factor_model)
5. (hand-coded prior — HAND_CODED_BETA_PR2A_PRE → apply_factor_model with beta=...)

24-cell legacy 는 별도 wrapper (cell_24_legacy) 에서 optimize.fit_all 호출.
"""
from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd

from tradingagents.skills.research.factor_to_bucket import BUCKETS, FACTORS


# Pre-PR2a hand-coded INITIAL_BETA snapshot (from git commit 3572d03).
# Used as a benchmark in PR2b validation. PR2a 가 main 의 INITIAL_BETA 를
# calibrated 로 교체했으므로 git history snapshot 을 inline literal 로 보존.
HAND_CODED_BETA_PR2A_PRE: Final[dict[tuple[str, str], float]] = {
    # F1 growth (+z = growth → +equity, -bond)
    ("F1_growth", "kr_equity"):     +0.04,
    ("F1_growth", "global_equity"): +0.06,
    ("F1_growth", "fx_commodity"):  +0.01,
    ("F1_growth", "bond"):          -0.08,
    ("F1_growth", "cash_mmf"):      -0.03,
    # F2 inflation
    ("F2_inflation", "kr_equity"):     -0.02,
    ("F2_inflation", "global_equity"): -0.03,
    ("F2_inflation", "fx_commodity"):  +0.07,
    ("F2_inflation", "bond"):          -0.05,
    ("F2_inflation", "cash_mmf"):      +0.03,
    # F3 real_rate
    ("F3_real_rate", "kr_equity"):     -0.02,
    ("F3_real_rate", "global_equity"): -0.03,
    ("F3_real_rate", "fx_commodity"):  -0.01,
    ("F3_real_rate", "bond"):          -0.05,
    ("F3_real_rate", "cash_mmf"):      +0.11,
    # F4 term_premium
    ("F4_term_premium", "kr_equity"):     +0.02,
    ("F4_term_premium", "global_equity"): +0.03,
    ("F4_term_premium", "fx_commodity"):  0.0,
    ("F4_term_premium", "bond"):          +0.02,
    ("F4_term_premium", "cash_mmf"):      -0.07,
    # F5 credit_cycle
    ("F5_credit_cycle", "kr_equity"):     -0.05,
    ("F5_credit_cycle", "global_equity"): -0.06,
    ("F5_credit_cycle", "fx_commodity"):  +0.01,
    ("F5_credit_cycle", "bond"):          -0.02,
    ("F5_credit_cycle", "cash_mmf"):      +0.12,
    # F6 krw_regime
    ("F6_krw_regime", "kr_equity"):     -0.05,
    ("F6_krw_regime", "global_equity"): +0.04,
    ("F6_krw_regime", "fx_commodity"):  +0.03,
    ("F6_krw_regime", "bond"):          -0.01,
    ("F6_krw_regime", "cash_mmf"):      -0.01,
    # F7 equity_vol_regime
    ("F7_equity_vol_regime", "kr_equity"):     -0.04,
    ("F7_equity_vol_regime", "global_equity"): -0.06,
    ("F7_equity_vol_regime", "fx_commodity"):  -0.02,
    ("F7_equity_vol_regime", "bond"):          +0.04,
    ("F7_equity_vol_regime", "cash_mmf"):      +0.08,
    # F8 valuation
    ("F8_valuation", "kr_equity"):     -0.03,
    ("F8_valuation", "global_equity"): -0.04,
    ("F8_valuation", "fx_commodity"):  +0.01,
    ("F8_valuation", "bond"):          +0.04,
    ("F8_valuation", "cash_mmf"):      +0.02,
    # F9 liquidity_regime
    ("F9_liquidity_regime", "kr_equity"):     -0.03,
    ("F9_liquidity_regime", "global_equity"): -0.05,
    ("F9_liquidity_regime", "fx_commodity"):  -0.01,
    ("F9_liquidity_regime", "bond"):          +0.04,
    ("F9_liquidity_regime", "cash_mmf"):      +0.05,
}


def equal_weight() -> dict[str, float]:
    """1/N: 각 bucket = 1/len(BUCKETS) = 0.2."""
    n = len(BUCKETS)
    return {b: 1.0 / n for b in BUCKETS}


def kr_tilted_60_40() -> dict[str, float]:
    """60-40 KR-tilted static: kr_eq 0.20 + gl_eq 0.40 + bond 0.40.

    PR2a 의 benchmark_60_40_returns 의 weight 와 동일.
    """
    return {
        "kr_equity": 0.20,
        "global_equity": 0.40,
        "fx_commodity": 0.0,
        "bond": 0.40,
        "cash_mmf": 0.0,
    }


def risk_parity(
    returns: pd.DataFrame,
    window: int = 60,
) -> dict[str, float]:
    """σ-inverse weighted (simple risk parity), 60Q rolling std.

    Args:
        returns: bucket × time DataFrame (columns = BUCKETS, rows = quarter).
        window: rolling window size (default 60Q).

    Returns:
        weight dict summing to 1.0. Higher weight for lower-σ bucket.

    Note: 완전한 risk parity (HRP) 가 아닌 1/σ 단순 weighting. PR2b 의 목적
    상 simple risk parity 가 충분 (benchmark 비교용, optimization aim 아님).
    """
    if returns.empty:
        return equal_weight()
    # Last `window` quarters std per bucket.
    tail = returns.tail(window) if len(returns) >= window else returns
    sigmas = {b: float(tail[b].std(ddof=1)) for b in BUCKETS if b in tail.columns}
    # Floor very small sigmas to avoid division blow-up.
    inv_sigmas = {b: 1.0 / max(s, 1e-6) for b, s in sigmas.items()}
    total = sum(inv_sigmas.values())
    if total <= 0:
        return equal_weight()
    return {b: inv_sigmas.get(b, 0.0) / total for b in BUCKETS}
```

- [ ] **Step 4: 테스트 재실행 → pass**

```bash
uv run python -m pytest tests/unit/backtest/test_benchmarks.py -v
```

Expected: 5 tests pass.

### Task 1.2: `regime.py` — NBER classifier

**Files:**
- Create: `tradingagents/backtest/regime.py`
- Create: `tests/unit/backtest/test_regime.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/backtest/test_regime.py`:

```python
"""Unit tests for regime.py — NBER classifier + sample split."""
from datetime import date

import pandas as pd
import pytest

from tradingagents.backtest.regime import (
    nber_recession_quarterly_from_series,
    split_samples_by_regime,
)
from tradingagents.skills.research.factor_calibration import HistoricalSample


def test_nber_recession_quarterly_from_monthly_series() -> None:
    """monthly USREC → quarterly (any month=1 in quarter → recession=True)."""
    # 2008-Q4: USREC=1 in Dec 2008 → recession quarter.
    # 2009-Q1: USREC=1 all 3 months → recession.
    # 2010-Q1: USREC=0 → expansion.
    monthly = pd.Series(
        [0, 0, 0, 1, 1, 1, 1, 1, 1, 0, 0, 0],
        index=pd.date_range("2008-10-01", periods=12, freq="MS"),
        name="USREC",
    )
    q = nber_recession_quarterly_from_series(monthly)
    assert q.loc["2008-12-31"] == True   # Oct/Nov/Dec — Dec=1
    assert q.loc["2009-03-31"] == True
    assert q.loc["2009-06-30"] == True
    assert q.loc["2009-09-30"] == False  # all 0


def test_split_samples_by_regime_partitions_correctly() -> None:
    """sample 의 date 기준으로 expansion / recession 분리."""
    samples = [
        HistoricalSample(date="2007-12-31", factor_z={}, bucket_returns_next={}),
        HistoricalSample(date="2008-12-31", factor_z={}, bucket_returns_next={}),
        HistoricalSample(date="2009-12-31", factor_z={}, bucket_returns_next={}),
        HistoricalSample(date="2010-12-31", factor_z={}, bucket_returns_next={}),
    ]
    recession = pd.Series(
        [False, True, True, False],
        index=pd.to_datetime(["2007-12-31", "2008-12-31",
                              "2009-12-31", "2010-12-31"]),
    )
    exp, rec = split_samples_by_regime(samples, recession)
    assert len(exp) == 2
    assert len(rec) == 2
    assert exp[0].date == "2007-12-31"
    assert rec[0].date == "2008-12-31"


def test_split_samples_unknown_date_defaults_to_expansion() -> None:
    """Recession Series 에 없는 sample date → expansion (보수적 default)."""
    samples = [
        HistoricalSample(date="1991-03-31", factor_z={}, bucket_returns_next={}),
    ]
    recession = pd.Series([], dtype=bool)
    exp, rec = split_samples_by_regime(samples, recession)
    assert len(exp) == 1
    assert len(rec) == 0


def test_nber_recession_handles_partial_quarter() -> None:
    """Quarter 의 1개월만 USREC=1 → recession=True (정책)."""
    monthly = pd.Series(
        [0, 0, 1],  # Jan/Feb 0, Mar 1 → Q1 recession
        index=pd.date_range("2020-01-01", periods=3, freq="MS"),
    )
    q = nber_recession_quarterly_from_series(monthly)
    assert q.loc["2020-03-31"] == True
```

- [ ] **Step 2: 테스트 실행 → fail**

```bash
uv run python -m pytest tests/unit/backtest/test_regime.py -v
```

Expected: ImportError.

- [ ] **Step 3: 최소 구현**

`tradingagents/backtest/regime.py`:

```python
"""NBER recession classifier + sample split utilities for PR2b validation.

USREC (FRED) = NBER 공식 recession dummy. Monthly. resample('QE').max() 으로
quarter 별 boolean (any month=1 in quarter → recession=True).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Sequence

import pandas as pd

from tradingagents.skills.research.factor_calibration import HistoricalSample


def nber_recession_quarterly_from_series(
    usrec_monthly: pd.Series,
) -> pd.Series:
    """Monthly USREC → quarterly boolean (any month=1 → True).

    Args:
        usrec_monthly: pd.Series indexed by month, values ∈ {0, 1}.

    Returns:
        pd.Series indexed by quarter end (Mar 31 / Jun 30 / Sep 30 / Dec 31),
        bool dtype.
    """
    if usrec_monthly.empty:
        return pd.Series(dtype=bool)
    # Coerce to bool: any value > 0 in a quarter → True.
    bool_monthly = (usrec_monthly > 0).astype(bool)
    quarterly = bool_monthly.resample("QE").max()
    return quarterly.astype(bool)


def nber_recession_quarterly_from_parquet(
    cache_path: Path | str,
) -> pd.Series:
    """Read USREC.parquet (from PR2a fetcher_fred cache) → quarterly bool.

    Args:
        cache_path: path to FRED USREC cache parquet.

    Returns:
        quarterly bool Series.
    """
    cache_path = Path(cache_path)
    if not cache_path.exists():
        return pd.Series(dtype=bool)
    df = pd.read_parquet(cache_path)
    series = df["value"]
    series.index = pd.to_datetime(series.index)
    return nber_recession_quarterly_from_series(series)


def split_samples_by_regime(
    samples: Sequence[HistoricalSample],
    recession_quarterly: pd.Series,
) -> tuple[list[HistoricalSample], list[HistoricalSample]]:
    """Partition samples into (expansion, recession) by date.

    Args:
        samples: list of HistoricalSample (with .date = YYYY-MM-DD string).
        recession_quarterly: bool Series indexed by quarter end date.

    Returns:
        (expansion_samples, recession_samples).
        Sample with date not in recession Series → expansion (default).
    """
    expansion, recession = [], []
    for s in samples:
        ts = pd.Timestamp(s.date)
        is_recession = bool(recession_quarterly.get(ts, False))
        if is_recession:
            recession.append(s)
        else:
            expansion.append(s)
    return expansion, recession
```

- [ ] **Step 4: 테스트 재실행 → pass**

```bash
uv run python -m pytest tests/unit/backtest/test_regime.py -v
```

Expected: 4 tests pass.

### Task 1.3: `statistics.py` — paired-t + Cohen's d + regime decomp + drawdown

**Files:**
- Create: `tradingagents/backtest/statistics.py`
- Create: `tests/unit/backtest/test_statistics.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/backtest/test_statistics.py`:

```python
"""Unit tests for statistics.py — paired-t, Cohen's d, regime decomp, drawdown."""
import numpy as np
import pytest

from tradingagents.backtest.statistics import (
    cohens_d,
    drawdown_analysis,
    paired_t_vs_benchmark,
    regime_decomposition,
)


def test_paired_t_calibrated_strictly_higher_returns_low_p() -> None:
    """Calibrated 의 모든 fold OOS Sharpe 가 benchmark 보다 크면 p << 0.5."""
    calibrated = np.array([0.8, 0.9, 1.0, 1.1, 0.85, 0.95, 1.05])
    benchmark = np.array([0.3, 0.4, 0.5, 0.4, 0.35, 0.45, 0.5])
    result = paired_t_vs_benchmark(calibrated, benchmark)
    assert result["paired_t_p"] < 0.05
    assert result["mean_diff"] > 0


def test_paired_t_same_distributions_returns_high_p() -> None:
    """동일 분포 → p ≈ 0.5."""
    rng = np.random.default_rng(42)
    a = rng.standard_normal(20)
    b = a.copy()
    result = paired_t_vs_benchmark(a, b)
    # Identical → mean_diff = 0, p ≥ 0.5 ('greater' alternative).
    assert result["mean_diff"] == pytest.approx(0.0)
    assert result["paired_t_p"] >= 0.49


def test_cohens_d_zero_for_identical_distributions() -> None:
    a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    b = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    assert cohens_d(a, b) == pytest.approx(0.0)


def test_cohens_d_positive_for_higher_calibrated() -> None:
    a = np.array([2.0, 3.0, 4.0])  # higher mean
    b = np.array([0.0, 1.0, 2.0])
    d = cohens_d(a, b)
    assert d > 0
    # Standard interpretation: |d| > 0.8 = large effect.
    assert d > 0.8


def test_regime_decomposition_separates_recession_returns() -> None:
    """recession mask = True 인 sample 의 return 으로 별도 Sharpe."""
    returns = {"calibrated": np.array([0.05, -0.10, 0.08, -0.15, 0.04, 0.06])}
    recession = np.array([False, True, False, True, False, False])
    result = regime_decomposition(returns, recession)
    assert "calibrated" in result
    # Expansion: 0.05, 0.08, 0.04, 0.06 → positive mean.
    # Recession: -0.10, -0.15 → negative mean.
    assert result["calibrated"]["expansion_mean"] > 0
    assert result["calibrated"]["recession_mean"] < 0
    assert result["calibrated"]["expansion_n"] == 4
    assert result["calibrated"]["recession_n"] == 2


def test_drawdown_analysis_max_drawdown_recovery() -> None:
    """returns [0.1, -0.5, 0.2, 0.3] — drawdown at q=1, recovery at q=3."""
    returns = np.array([0.1, -0.5, 0.2, 0.3])
    result = drawdown_analysis(returns)
    # Cumulative wealth: 1.10 → 0.55 → 0.66 → 0.858.
    # Peak before drawdown = 1.10. Trough = 0.55.
    # max DD = (0.55 - 1.10) / 1.10 = -0.50.
    assert result["max_drawdown"] == pytest.approx(-0.50, abs=1e-3)
    assert result["drawdown_peak_idx"] == 0
    assert result["drawdown_trough_idx"] == 1
    # Not yet recovered (cumulative 0.858 < peak 1.10).
    assert result["recovery_idx"] is None


def test_drawdown_analysis_recovered() -> None:
    """returns [0.1, -0.5, 0.5, 0.5] — recovery achieved at end."""
    returns = np.array([0.1, -0.5, 0.5, 0.5])
    result = drawdown_analysis(returns)
    # cumulative: 1.10 → 0.55 → 0.825 → 1.2375 (recovers above 1.10).
    assert result["recovery_idx"] == 3
```

- [ ] **Step 2: 테스트 실행 → fail**

```bash
uv run python -m pytest tests/unit/backtest/test_statistics.py -v
```

Expected: ImportError.

- [ ] **Step 3: 최소 구현**

`tradingagents/backtest/statistics.py`:

```python
"""Statistical tests for PR2b validation:
- paired_t_vs_benchmark: scipy ttest_rel + mean diff
- cohens_d: standardized mean difference (effect size, important for small N)
- regime_decomposition: per-strategy Sharpe in expansion / recession
- drawdown_analysis: max drawdown + recovery from cumulative returns
"""
from __future__ import annotations

import logging
from typing import Mapping

import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)


def paired_t_vs_benchmark(
    calibrated_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    alternative: str = "greater",
) -> dict:
    """Paired-t test: H0 mean(calibrated - benchmark) = 0.

    Args:
        calibrated_returns: per-fold or per-quarter return array.
        benchmark_returns: matching length, paired.
        alternative: "greater" (default — calibrated > benchmark) or "two-sided".

    Returns:
        {
            "mean_diff": float (calibrated - benchmark mean),
            "paired_t_stat": float,
            "paired_t_p": float ∈ [0, 1],
            "cohens_d": float (effect size),
            "n": int,
        }
    """
    n = min(len(calibrated_returns), len(benchmark_returns))
    if n < 2:
        return {
            "mean_diff": 0.0, "paired_t_stat": 0.0,
            "paired_t_p": 1.0, "cohens_d": 0.0, "n": n,
        }
    a = np.asarray(calibrated_returns[:n], dtype=float)
    b = np.asarray(benchmark_returns[:n], dtype=float)
    try:
        result = stats.ttest_rel(a, b, alternative=alternative)
        t_stat = float(result.statistic)
        p_value = float(result.pvalue)
    except Exception as e:
        logger.warning("paired-t failed: %s", e)
        t_stat, p_value = 0.0, 1.0
    return {
        "mean_diff": float(np.mean(a - b)),
        "paired_t_stat": t_stat,
        "paired_t_p": p_value,
        "cohens_d": cohens_d(a, b),
        "n": n,
    }


def cohens_d(a: np.ndarray, b: np.ndarray) -> float:
    """Cohen's d effect size: (mean_a - mean_b) / pooled_std.

    Interpretation:
        |d| < 0.2  — negligible
        |d| < 0.5  — small
        |d| < 0.8  — medium
        |d| ≥ 0.8  — large

    Important for small N (e.g., NBER recession N=13) where paired-t p
    has low power.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    n_a, n_b = len(a), len(b)
    if n_a < 2 or n_b < 2:
        return 0.0
    var_a, var_b = float(np.var(a, ddof=1)), float(np.var(b, ddof=1))
    pooled = np.sqrt(((n_a - 1) * var_a + (n_b - 1) * var_b) / (n_a + n_b - 2))
    if pooled <= 0:
        return 0.0
    return float((np.mean(a) - np.mean(b)) / pooled)


def regime_decomposition(
    returns_per_strategy: Mapping[str, np.ndarray],
    recession_mask: np.ndarray,
) -> dict:
    """Per-strategy mean return + Sharpe in expansion vs recession.

    Args:
        returns_per_strategy: {strategy_name: per-quarter return array}.
        recession_mask: bool array, True = recession quarter.

    Returns:
        {strategy: {expansion_mean, expansion_std, expansion_sharpe, expansion_n,
                     recession_mean, recession_std, recession_sharpe, recession_n}}
    """
    rec_mask = np.asarray(recession_mask, dtype=bool)
    exp_mask = ~rec_mask
    out = {}
    for name, returns in returns_per_strategy.items():
        r = np.asarray(returns, dtype=float)
        n = min(len(r), len(rec_mask))
        r = r[:n]
        exp_r = r[exp_mask[:n]]
        rec_r = r[rec_mask[:n]]
        out[name] = {
            "expansion_mean": float(np.mean(exp_r)) if len(exp_r) else 0.0,
            "expansion_std":  float(np.std(exp_r, ddof=1)) if len(exp_r) > 1 else 0.0,
            "expansion_sharpe": _sharpe(exp_r),
            "expansion_n": int(len(exp_r)),
            "recession_mean": float(np.mean(rec_r)) if len(rec_r) else 0.0,
            "recession_std":  float(np.std(rec_r, ddof=1)) if len(rec_r) > 1 else 0.0,
            "recession_sharpe": _sharpe(rec_r),
            "recession_n": int(len(rec_r)),
        }
    return out


def _sharpe(returns: np.ndarray, periods_per_year: int = 4) -> float:
    """Annualized Sharpe (quarterly default). 0.0 if std≤0 or len<2."""
    if len(returns) < 2:
        return 0.0
    mean = float(np.mean(returns))
    std = float(np.std(returns, ddof=1))
    if std <= 0:
        return 0.0
    return mean / std * np.sqrt(periods_per_year)


def drawdown_analysis(returns: np.ndarray) -> dict:
    """Max drawdown + recovery from cumulative wealth.

    Args:
        returns: per-period return array (e.g., quarterly).

    Returns:
        {
            "max_drawdown": float (worst peak-to-trough fractional loss, ≤ 0),
            "drawdown_peak_idx": int (index of peak before max DD),
            "drawdown_trough_idx": int (index of trough at max DD),
            "recovery_idx": int | None (index when cumulative returns to peak),
            "duration_quarters": int (trough - peak),
        }
    """
    r = np.asarray(returns, dtype=float)
    if len(r) < 1:
        return {
            "max_drawdown": 0.0, "drawdown_peak_idx": 0,
            "drawdown_trough_idx": 0, "recovery_idx": None,
            "duration_quarters": 0,
        }
    cumulative = np.cumprod(1 + r)
    running_max = np.maximum.accumulate(cumulative)
    drawdown = (cumulative - running_max) / running_max  # ≤ 0
    trough_idx = int(np.argmin(drawdown))
    max_dd = float(drawdown[trough_idx])
    # Peak index: last running_max equal to running_max[trough_idx], at or before trough.
    peak_value = running_max[trough_idx]
    peak_idx = int(np.where(cumulative[:trough_idx + 1] >= peak_value - 1e-12)[0][0]) \
        if trough_idx >= 0 else 0
    # Recovery: first idx after trough where cumulative ≥ peak_value.
    recovery_idx = None
    for i in range(trough_idx + 1, len(cumulative)):
        if cumulative[i] >= peak_value - 1e-12:
            recovery_idx = i
            break
    return {
        "max_drawdown": max_dd,
        "drawdown_peak_idx": peak_idx,
        "drawdown_trough_idx": trough_idx,
        "recovery_idx": recovery_idx,
        "duration_quarters": trough_idx - peak_idx,
    }
```

- [ ] **Step 4: 테스트 재실행 → pass**

```bash
uv run python -m pytest tests/unit/backtest/test_statistics.py -v
```

Expected: 7 tests pass.

### Task 1.4: Pre-commit regression + commit

- [ ] **Step 1: 전체 regression test**

```bash
uv run python -m pytest tests/unit/ -q 2>&1 | tail -3
uv run python -m pytest tests/integration/ -q 2>&1 | tail -3
```

Expected: PR2a baseline + 16 new pass (5 benchmark + 4 regime + 7 statistics). 0 new fail.

- [ ] **Step 2: `regression_log.md` 의 "## Post-C1" entry**

`artifacts/2026-05-25/regression_log.md` 끝에 append:

```markdown
## Post-C1 (feat: validation utilities — benchmarks, regime, statistics)

```
$ uv run python -m pytest tests/unit/ -q
2 failed, 802 passed (PR2a baseline + 16 new)

$ uv run python -m pytest tests/integration/ -q
18 failed, 28 passed (unchanged)
```

Δ: Unit +16 new pass. Integration unchanged. 0 new failure.
```

- [ ] **Step 3: commit**

```bash
git add tradingagents/backtest/benchmarks.py \
        tradingagents/backtest/regime.py \
        tradingagents/backtest/statistics.py \
        tests/unit/backtest/test_benchmarks.py \
        tests/unit/backtest/test_regime.py \
        tests/unit/backtest/test_statistics.py
git add -f artifacts/2026-05-25/regression_log.md

git commit -m "$(cat <<'EOF'
feat(backtest): validation utilities — benchmarks + regime + statistics (C1)

PR2b 의 validation infrastructure. 3 신규 module + 16 unit test.

- benchmarks.py: 5 bucket weight 함수 + HAND_CODED_BETA_PR2A_PRE snapshot.
  - equal_weight, kr_tilted_60_40, risk_parity (60Q rolling σ-inverse)
  - HAND_CODED_BETA_PR2A_PRE: PR2a 가 교체한 hand-coded β 의 git history
    snapshot (45 entries, row-sum=0 invariant 보존).
- regime.py: NBER USREC classifier — monthly → quarterly (any month=1 →
  recession). split_samples_by_regime: sample.date 기준 partition.
- statistics.py: paired_t_vs_benchmark (scipy ttest_rel + Cohen's d),
  regime_decomposition (per-strategy expansion/recession Sharpe),
  drawdown_analysis (max DD + peak/trough/recovery idx).

본 module 들은 production code 변경 없는 신규 utility. PR2b validate_factor_
model.py (C2) 와 sensitivity_sweep.py (C3) 에서 import.

Regression: Unit +16 new pass (5 benchmark + 4 regime + 7 statistics).
Integration unchanged. 0 new failure.
EOF
)"
```

- [ ] **Step 4: post-C1 regression**

```bash
uv run python -m pytest tests/unit/ -q 2>&1 | tail -3
uv run python -m pytest tests/integration/ -q 2>&1 | tail -3
```

`regression_log.md` 갱신 확인.

---

## Task 2: Validation Runner + Execute (C2)

`scripts/validate_factor_model.py` 가 samples.parquet 를 input 으로 받아 6 strategies 의 walk-forward OOS returns 계산 + 통계 검증 + report 작성.

### Task 2.1: `validate_factor_model.py` 작성

**Files:**
- Create: `scripts/validate_factor_model.py`

- [ ] **Step 1: 작성**

`scripts/validate_factor_model.py`:

```python
"""PR2b validation runner — 6 strategies' walk-forward OOS + statistics + report.

End-to-end:
1. Load samples.parquet (PR2a output)
2. Compute walk-forward OOS returns for 6 strategies:
   - calibrated (INITIAL_BETA = PR2a)
   - hand-coded prior (HAND_CODED_BETA_PR2A_PRE)
   - 24-cell legacy (skipped — complex setup, requires macro_q DataFrame
     reconstruction; logged as 'deferred' in report)
   - 60-40 KR-tilted (factor_calibration.benchmark_60_40_returns)
   - 1-N equal weight
   - Risk parity (σ-inverse, 60Q rolling)
3. NBER USREC quarterly recession mask
4. Paired-t each benchmark vs calibrated + Cohen's d
5. Regime decomposition (expansion / recession per strategy)
6. Drawdown analysis per strategy
7. Output validation_report.md + .json

Usage:
    uv run python scripts/validate_factor_model.py \\
        --samples backtest/historical/samples.parquet \\
        --usrec-cache backtest/historical/raw/fred/USREC.parquet \\
        --output-dir artifacts/2026-05-25/validation
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import sys
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from tradingagents.backtest.benchmarks import (
    HAND_CODED_BETA_PR2A_PRE,
    equal_weight,
    kr_tilted_60_40,
    risk_parity,
)
from tradingagents.backtest.regime import (
    nber_recession_quarterly_from_parquet,
)
from tradingagents.backtest.statistics import (
    cohens_d,
    drawdown_analysis,
    paired_t_vs_benchmark,
    regime_decomposition,
)
from tradingagents.skills.research.factor_calibration import (
    HistoricalSample,
    compute_sharpe,
    simulate_portfolio_returns,
)
from tradingagents.skills.research.factor_to_bucket import (
    BUCKETS, FACTORS, INITIAL_BETA,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# Reuse the parquet→sample loader from PR2a calibration script via importlib.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CALIBRATE_PATH = _PROJECT_ROOT / "scripts" / "calibrate_factor_model.py"
_spec = importlib.util.spec_from_file_location(
    "_pr2a_calibrate", _CALIBRATE_PATH,
)
_calibrate_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_calibrate_mod)
load_samples_from_parquet = _calibrate_mod.load_samples_from_parquet


def _walk_forward_oos_with_fixed_weights(
    samples: list[HistoricalSample],
    weight_fn: Callable[[list[HistoricalSample]], dict[str, float]],
    initial_train_size: int = 80,
    test_window: int = 7,
) -> tuple[np.ndarray, list[float]]:
    """Walk-forward OOS returns with a fixed-weight strategy.

    weight_fn(train_samples) → bucket weight dict (same weight applied to all
    test samples in the fold).

    Returns:
        (per_quarter_oos_returns, per_fold_sharpe)
    """
    n = len(samples)
    all_returns: list[float] = []
    per_fold_sharpe: list[float] = []
    for end in range(initial_train_size, n - test_window + 1, test_window):
        train = samples[:end]
        test = samples[end:end + test_window]
        w = weight_fn(train)
        fold_returns = []
        for s in test:
            ret = sum(w.get(b, 0.0) * s.bucket_returns_next.get(b, 0.0) for b in BUCKETS)
            fold_returns.append(ret)
        all_returns.extend(fold_returns)
        per_fold_sharpe.append(compute_sharpe(np.array(fold_returns)))
    return np.array(all_returns), per_fold_sharpe


def _walk_forward_oos_with_beta(
    samples: list[HistoricalSample],
    beta: dict[tuple[str, str], float],
    initial_train_size: int = 80,
    test_window: int = 7,
) -> tuple[np.ndarray, list[float]]:
    """Walk-forward OOS returns using a fixed β (no training)."""
    n = len(samples)
    all_returns: list[float] = []
    per_fold_sharpe: list[float] = []
    for end in range(initial_train_size, n - test_window + 1, test_window):
        test = samples[end:end + test_window]
        fold_returns = simulate_portfolio_returns(test, beta)
        all_returns.extend(fold_returns.tolist())
        per_fold_sharpe.append(compute_sharpe(fold_returns))
    return np.array(all_returns), per_fold_sharpe


def _samples_to_returns_df(samples: list[HistoricalSample]) -> pd.DataFrame:
    """HistoricalSample list → DataFrame (rows = quarter, cols = bucket)."""
    rows = []
    for s in samples:
        row = {b: s.bucket_returns_next.get(b, 0.0) for b in BUCKETS}
        row["date"] = pd.Timestamp(s.date)
        rows.append(row)
    df = pd.DataFrame(rows).set_index("date").sort_index()
    return df


def _risk_parity_weight_fn_factory(returns_df: pd.DataFrame):
    """Returns a weight_fn that uses risk_parity on train samples' returns df."""
    def fn(train: list[HistoricalSample]) -> dict[str, float]:
        train_dates = pd.to_datetime([s.date for s in train])
        sub = returns_df.loc[returns_df.index.isin(train_dates)]
        return risk_parity(sub, window=60)
    return fn


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", required=True)
    ap.add_argument("--usrec-cache", default="backtest/historical/raw/fred/USREC.parquet")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--initial-train-size", type=int, default=80)
    ap.add_argument("--test-window", type=int, default=7)
    args = ap.parse_args()

    samples = load_samples_from_parquet(Path(args.samples))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # NBER recession mask aligned to OOS test windows.
    recession_q = nber_recession_quarterly_from_parquet(Path(args.usrec_cache))
    logger.info("NBER recession quarters loaded: %s", len(recession_q))

    returns_df = _samples_to_returns_df(samples)

    # 5 strategies (24-cell deferred — complex, requires macro_q reconstruction).
    strategies = {
        "calibrated": lambda: _walk_forward_oos_with_beta(
            samples, INITIAL_BETA,
            args.initial_train_size, args.test_window,
        ),
        "hand_coded_prior": lambda: _walk_forward_oos_with_beta(
            samples, HAND_CODED_BETA_PR2A_PRE,
            args.initial_train_size, args.test_window,
        ),
        "60_40_kr_tilted": lambda: _walk_forward_oos_with_fixed_weights(
            samples, lambda _: kr_tilted_60_40(),
            args.initial_train_size, args.test_window,
        ),
        "equal_weight": lambda: _walk_forward_oos_with_fixed_weights(
            samples, lambda _: equal_weight(),
            args.initial_train_size, args.test_window,
        ),
        "risk_parity": lambda: _walk_forward_oos_with_fixed_weights(
            samples, _risk_parity_weight_fn_factory(returns_df),
            args.initial_train_size, args.test_window,
        ),
    }

    results = {}
    for name, fn in strategies.items():
        logger.info("Computing %s walk-forward OOS", name)
        oos, fold_sharpes = fn()
        results[name] = {
            "oos_returns": oos,
            "mean_oos_sharpe": float(np.mean(fold_sharpes)) if fold_sharpes else 0.0,
            "std_oos_sharpe": float(np.std(fold_sharpes, ddof=1)) if len(fold_sharpes) > 1 else 0.0,
            "per_fold_sharpe": fold_sharpes,
            "full_period_sharpe": compute_sharpe(oos),
            "drawdown": drawdown_analysis(oos),
        }

    # Recession mask aligned to OOS sample dates.
    # OOS sample = samples[initial_train_size : initial_train_size + 7*7]
    n = len(samples)
    oos_sample_dates = []
    for end in range(args.initial_train_size, n - args.test_window + 1, args.test_window):
        for s in samples[end:end + args.test_window]:
            oos_sample_dates.append(pd.Timestamp(s.date))
    rec_mask = np.array([
        bool(recession_q.get(d, False)) for d in oos_sample_dates
    ])
    logger.info(
        "OOS sample dates: %s total, %s recession",
        len(oos_sample_dates), int(rec_mask.sum()),
    )

    # Pairwise stats: each benchmark vs calibrated.
    calib_returns = results["calibrated"]["oos_returns"]
    pairwise = {}
    for name in strategies.keys():
        if name == "calibrated":
            continue
        bench = results[name]["oos_returns"]
        pairwise[name] = paired_t_vs_benchmark(calib_returns, bench, alternative="greater")

    # Regime decomposition.
    returns_per_strategy = {n: r["oos_returns"] for n, r in results.items()}
    regime = regime_decomposition(returns_per_strategy, rec_mask)

    # Serialize.
    json_out = {
        "samples_n": len(samples),
        "oos_n": len(oos_sample_dates),
        "recession_n": int(rec_mask.sum()),
        "strategies": {
            name: {
                "mean_oos_sharpe": r["mean_oos_sharpe"],
                "std_oos_sharpe": r["std_oos_sharpe"],
                "per_fold_sharpe": r["per_fold_sharpe"],
                "full_period_sharpe": r["full_period_sharpe"],
                "drawdown": r["drawdown"],
            }
            for name, r in results.items()
        },
        "pairwise_vs_calibrated": pairwise,
        "regime_decomposition": regime,
        "deferred_strategies": ["24_cell_legacy"],  # complex setup, separate task
    }
    with open(output_dir / "validation_report.json", "w") as f:
        json.dump(json_out, f, indent=2, default=str)

    # Markdown report.
    md = _write_markdown_report(json_out)
    with open(output_dir / "validation_report.md", "w") as f:
        f.write(md)

    print(json.dumps({
        "calibrated_mean_oos_sharpe": results["calibrated"]["mean_oos_sharpe"],
        "best_benchmark": _best_benchmark_name(results),
        "best_benchmark_sharpe": _best_benchmark_sharpe(results),
        "calibrated_beats_all": _calibrated_beats_all(results),
    }, indent=2))
    return 0


def _best_benchmark_name(results: dict) -> str:
    names = [n for n in results if n != "calibrated"]
    return max(names, key=lambda n: results[n]["mean_oos_sharpe"])


def _best_benchmark_sharpe(results: dict) -> float:
    return max(
        results[n]["mean_oos_sharpe"] for n in results if n != "calibrated"
    )


def _calibrated_beats_all(results: dict) -> bool:
    calib = results["calibrated"]["mean_oos_sharpe"]
    return all(
        calib > results[n]["mean_oos_sharpe"]
        for n in results if n != "calibrated"
    )


def _write_markdown_report(data: dict) -> str:
    lines = []
    lines.append("# PR2b Validation Report (2026-05-25)\n")
    lines.append("## Executive Summary\n")
    calib_sharpe = data["strategies"]["calibrated"]["mean_oos_sharpe"]
    best_bench = max(
        (n for n in data["strategies"] if n != "calibrated"),
        key=lambda n: data["strategies"][n]["mean_oos_sharpe"],
    )
    best_bench_sharpe = data["strategies"][best_bench]["mean_oos_sharpe"]
    delta = calib_sharpe - best_bench_sharpe
    verdict = "PASS" if delta > 0 else "FAIL"
    lines.append(
        f"Calibrated (PR2a) mean OOS Sharpe = **{calib_sharpe:.3f}**. "
        f"Best non-calibrated benchmark = **{best_bench}** ({best_bench_sharpe:.3f}). "
        f"Δ = {delta:+.3f}. Verdict: **{verdict}**.\n"
    )

    lines.append("## Section 1: Benchmark Comparison (Full Period)\n")
    lines.append("| Strategy | Mean OOS Sharpe | Std OOS | Full-period Sharpe | Max DD | vs Calibrated p | Cohen's d | N |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for name, r in data["strategies"].items():
        if name == "calibrated":
            lines.append(
                f"| {name} | {r['mean_oos_sharpe']:.3f} | {r['std_oos_sharpe']:.3f} | "
                f"{r['full_period_sharpe']:.3f} | {r['drawdown']['max_drawdown']:.3f} | — | — | — |"
            )
        else:
            p = data["pairwise_vs_calibrated"][name]
            lines.append(
                f"| {name} | {r['mean_oos_sharpe']:.3f} | {r['std_oos_sharpe']:.3f} | "
                f"{r['full_period_sharpe']:.3f} | {r['drawdown']['max_drawdown']:.3f} | "
                f"{p['paired_t_p']:.3f} | {p['cohens_d']:+.3f} | {p['n']} |"
            )

    lines.append("\n## Section 2: NBER Regime Decomposition\n")
    rec_n = data["recession_n"]
    exp_n = data["oos_n"] - rec_n
    lines.append(f"OOS samples: total **{data['oos_n']}**, expansion **{exp_n}**, recession **{rec_n}**.\n")
    lines.append("| Strategy | Expansion Sharpe | Recession Sharpe | Spread |")
    lines.append("|---|---|---|---|")
    for name, r in data["regime_decomposition"].items():
        exp_s = r["expansion_sharpe"]
        rec_s = r["recession_sharpe"]
        lines.append(f"| {name} | {exp_s:+.3f} (N={r['expansion_n']}) | {rec_s:+.3f} (N={r['recession_n']}) | {exp_s - rec_s:+.3f} |")

    lines.append("\n## Section 3: Drawdown Analysis\n")
    lines.append("| Strategy | Max DD | Peak idx | Trough idx | Recovery idx | Duration (Q) |")
    lines.append("|---|---|---|---|---|---|")
    for name, r in data["strategies"].items():
        dd = r["drawdown"]
        rec = dd["recovery_idx"] if dd["recovery_idx"] is not None else "—"
        lines.append(
            f"| {name} | {dd['max_drawdown']:.3f} | {dd['drawdown_peak_idx']} | "
            f"{dd['drawdown_trough_idx']} | {rec} | {dd['duration_quarters']} |"
        )

    lines.append("\n## Section 4: Deferred\n")
    for s in data["deferred_strategies"]:
        lines.append(f"- {s}: 24-cell legacy 는 macro_q DataFrame reconstruction 이 필요 (별도 PR 또는 task).")

    lines.append("\n## Section 5: Conclusion\n")
    if delta > 0.05:
        lines.append(f"PR2a calibrated 가 5 benchmark 중 가장 우월 (Δ={delta:+.3f} > 0.05).")
    elif delta > 0:
        lines.append(f"PR2a calibrated 가 marginally 우월 (Δ={delta:+.3f}).")
    else:
        lines.append(f"⚠️ PR2a calibrated 가 best benchmark ({best_bench}) 대비 underperform (Δ={delta:+.3f}). INITIAL_BETA 재검토 필요.")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: dry-run smoke (import 검증만)**

```bash
uv run python -c "
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('vfm', 'scripts/validate_factor_model.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print('OK validate_factor_model imports')
"
```

Expected: `OK validate_factor_model imports`.

### Task 2.2: USREC vintage cache 확보

PR2a fetcher_fred 가 USREC 를 fetch 했어야 함. 캐시 확인 + 없으면 fetch.

- [ ] **Step 1: USREC cache 존재 확인**

```bash
ls backtest/historical/raw/fred/USREC.parquet
```

Expected (PR2a 완료 후): 존재. 없으면 step 2 실행.

- [ ] **Step 2: 부재 시 fetch (조건부)**

```bash
uv run python -c "
from datetime import date
from pathlib import Path
from tradingagents.backtest.historical.fetcher_fred import fetch_fred_latest
fetch_fred_latest('USREC', date(1991, 1, 1), date(2024, 12, 31),
                  cache_dir=Path('backtest/historical/raw/fred'))
print('USREC fetched')
"
```

Expected: parquet 생성됨.

### Task 2.3: Validation 실행 + 결과 검증

- [ ] **Step 1: validation 실행**

```bash
uv run python scripts/validate_factor_model.py \
    --samples backtest/historical/samples.parquet \
    --usrec-cache backtest/historical/raw/fred/USREC.parquet \
    --output-dir artifacts/2026-05-25/validation \
    --initial-train-size 80 --test-window 7
```

Expected stdout JSON:
```json
{
  "calibrated_mean_oos_sharpe": 1.171,
  "best_benchmark": "<some name>",
  "best_benchmark_sharpe": <float>,
  "calibrated_beats_all": true | false
}
```

산출물:
- `artifacts/2026-05-25/validation/validation_report.json`
- `artifacts/2026-05-25/validation/validation_report.md`

- [ ] **Step 2: validation_report.md 검토**

```bash
cat artifacts/2026-05-25/validation/validation_report.md
```

Expected:
- Section 1: 5 strategies' Sharpe + drawdown + paired-t p + Cohen's d
- Section 2: NBER regime decomposition (expansion vs recession Sharpe)
- Section 3: drawdown analysis
- Section 5: PASS / PASS marginal / FAIL verdict

### Task 2.4: [grill-me #1 marker]

본 시점에서 **executing-plans 가 일시 멈추고 grill-me #1 수행**.

Grill 대상:
1. **Benchmark 결과**: calibrated 가 5 benchmark 모두 이겼나? 어느 benchmark 가 가장 가까운가?
2. **NBER regime decomposition**: recession 구간 (N=13~20) 에서도 calibrated 가 우월? Cohen's d 효과크기 어느 정도?
3. **Drawdown**: calibrated 의 max DD 가 60-40 같은 conservative benchmark 보다 큰가?

Grill 결과 → `artifacts/2026-05-25/decisions.md` 의 "grill-me #1" section 에 기록.

### Task 2.5: Pre-commit regression + commit

- [ ] **Step 1: regression**

```bash
uv run python -m pytest tests/unit/ -q 2>&1 | tail -3
uv run python -m pytest tests/integration/ -q 2>&1 | tail -3
```

Expected: 동일 baseline (production code 변경 없음, script + artifacts 만 추가).

- [ ] **Step 2: regression_log.md "## Post-C2" entry**

`artifacts/2026-05-25/regression_log.md`:

```markdown
## Post-C2 (data: validation runner + execute)

[paste pytest output]

Δ: 0 new failure. validation_report.md + .json 산출됨.
Grill-me #1 verdict: [PASS / PASS with caveat / FAIL] (see decisions.md).
```

- [ ] **Step 3: commit**

```bash
git add scripts/validate_factor_model.py
git add -f artifacts/2026-05-25/validation/validation_report.md \
            artifacts/2026-05-25/validation/validation_report.json \
            artifacts/2026-05-25/regression_log.md \
            artifacts/2026-05-25/decisions.md

git commit -m "$(cat <<'EOF'
data(stage2b): 5-strategy validation report — calibrated vs benchmarks (C2)

scripts/validate_factor_model.py — 5 strategies' walk-forward OOS (1991-2024)
+ paired-t + Cohen's d + NBER regime decomposition + drawdown analysis.

Strategies (24-cell legacy deferred — complex macro_q reconstruction):
- calibrated (PR2a INITIAL_BETA)
- hand_coded_prior (HAND_CODED_BETA_PR2A_PRE git history snapshot)
- 60_40_kr_tilted (static 20/40/40)
- equal_weight (1/N)
- risk_parity (60Q rolling σ-inverse)

Validation report:
- artifacts/2026-05-25/validation/validation_report.md
- artifacts/2026-05-25/validation/validation_report.json

Verdict: see executive summary. grill-me #1 결과 decisions.md.

Regression: 0 new failure (script + artifacts only).
EOF
)"
```

---

## Task 3: Sensitivity Sweeps (C3)

3 sub-sweeps: era split + robustness penalty + sample_quality stratified.

### Task 3.1: `sensitivity_sweep.py` 작성

**Files:**
- Create: `scripts/sensitivity_sweep.py`

- [ ] **Step 1: 작성**

`scripts/sensitivity_sweep.py`:

```python
"""PR2b sensitivity sweep — era split + robustness penalty + sample_quality.

End-to-end:
1. Era split: split samples at 2010-01-01, calibrate each separately, β diff.
2. Robustness penalty: rerun select_best_shrinkage with {0.10, 0.50}.
3. Sample quality stratified: weighted hybrid_calibration (sample_weight =
   mean per-quarter confidence).

Usage:
    uv run python scripts/sensitivity_sweep.py \\
        --samples backtest/historical/samples.parquet \\
        --output-dir artifacts/2026-05-25/sensitivity
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from tradingagents.skills.research.factor_calibration import (
    compute_sharpe,
    hybrid_calibration,
    simulate_portfolio_returns,
)
from tradingagents.skills.research.factor_to_bucket import INITIAL_BETA

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CALIBRATE_PATH = _PROJECT_ROOT / "scripts" / "calibrate_factor_model.py"
_spec = importlib.util.spec_from_file_location("calib", _CALIBRATE_PATH)
_calib_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_calib_mod)
load_samples_from_parquet = _calib_mod.load_samples_from_parquet


SHRINKAGE_GRID: list[float] = [0.1, 0.3, 0.5, 1.0, 2.0]


def era_split_sweep(samples: list, era_split_date: str = "2010-01-01") -> dict:
    """Split samples at era_split_date → calibrate each separately → β diff."""
    split_ts = pd.Timestamp(era_split_date)
    pre = [s for s in samples if pd.Timestamp(s.date) < split_ts]
    post = [s for s in samples if pd.Timestamp(s.date) >= split_ts]
    logger.info("Era split: pre %s, post %s", len(pre), len(post))

    def _best_beta(subset):
        if len(subset) < 30:
            return None, None
        # Use full subset as train (no walk-forward for sensitivity — quicker).
        beta, sharpe = hybrid_calibration(subset, shrinkage=2.0, prior_beta=INITIAL_BETA)
        return beta, sharpe

    pre_beta, pre_sharpe = _best_beta(pre)
    post_beta, post_sharpe = _best_beta(post)

    # β stability metric: mean |pre - post| across keys both betas have.
    if pre_beta is not None and post_beta is not None:
        common = set(pre_beta.keys()) & set(post_beta.keys())
        diffs = [abs(pre_beta[k] - post_beta[k]) for k in common]
        avg_diff = float(np.mean(diffs)) if diffs else 0.0
    else:
        avg_diff = None

    return {
        "pre_2010_n": len(pre),
        "post_2010_n": len(post),
        "pre_2010_in_sample_sharpe": pre_sharpe,
        "post_2010_in_sample_sharpe": post_sharpe,
        "beta_avg_abs_diff_pre_vs_post": avg_diff,
        "pre_2010_beta": {f"{k[0]}_{k[1]}": v for k, v in pre_beta.items()} if pre_beta else None,
        "post_2010_beta": {f"{k[0]}_{k[1]}": v for k, v in post_beta.items()} if post_beta else None,
    }


def robustness_penalty_sweep(per_shrinkage_results: dict) -> dict:
    """select_best_shrinkage 의 0.25 계수 → {0.10, 0.50} 변경 시 best 변화."""
    def best(coef: float) -> str:
        scores = {}
        for s_str, r in per_shrinkage_results.items():
            scores[s_str] = r["mean_oos"] - coef * r["std_oos"]
        return max(scores, key=lambda k: scores[k])

    return {
        "best_at_0.10": best(0.10),
        "best_at_0.25_default": best(0.25),
        "best_at_0.50": best(0.50),
        "sensitive": best(0.10) != best(0.50),
    }


def sample_quality_sweep(samples: list, initial_train_size: int = 80, test_window: int = 7) -> dict:
    """Sample quality stratified: weight samples by confidence.

    samples.parquet 의 *_conf columns 평균 = sample_quality. 본 sweep 은
    weighted simulate_portfolio_returns 로 confidence-weighted Sharpe 비교
    (unweighted baseline 대비).
    """
    # 본 sweep 은 단순화: per-quarter sample_quality 계산 → quartile 분류 →
    # quartile 별 mean OOS Sharpe (calibrated INITIAL_BETA).
    df = pd.read_parquet("backtest/historical/samples.parquet")
    conf_cols = [c for c in df.columns if c.endswith("_conf")]
    df["sample_quality"] = df[conf_cols].mean(axis=1)
    # Quartile mapping.
    df["quality_quartile"] = pd.qcut(df["sample_quality"], 4, labels=["Q1", "Q2", "Q3", "Q4"], duplicates="drop")

    # Per-quartile OOS Sharpe of calibrated.
    out = {}
    for q in df["quality_quartile"].cat.categories:
        sub_dates = set(df[df["quality_quartile"] == q].index)
        sub_samples = [s for s in samples if pd.Timestamp(s.date) in sub_dates]
        if len(sub_samples) < 5:
            out[str(q)] = {"n": len(sub_samples), "sharpe": None}
            continue
        returns = simulate_portfolio_returns(sub_samples, INITIAL_BETA)
        out[str(q)] = {
            "n": len(sub_samples),
            "sharpe": compute_sharpe(returns),
            "mean_return": float(np.mean(returns)),
            "mean_quality": float(df[df["quality_quartile"] == q]["sample_quality"].mean()),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--per-shrinkage-summary",
                    default="artifacts/2026-05-24/calibration_runs/per_shrinkage_summary.json",
                    help="PR2a 의 per-shrinkage results (robustness sweep input).")
    args = ap.parse_args()

    samples = load_samples_from_parquet(Path(args.samples))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Era split
    logger.info("Running era split sweep")
    era = era_split_sweep(samples)
    with open(output_dir / "era_split.json", "w") as f:
        json.dump(era, f, indent=2)

    # 2. Robustness penalty (uses PR2a's per-shrinkage results).
    logger.info("Running robustness penalty sweep")
    if Path(args.per_shrinkage_summary).exists():
        with open(args.per_shrinkage_summary) as f:
            psr = json.load(f)
        robustness = robustness_penalty_sweep(psr)
    else:
        robustness = {"error": f"missing {args.per_shrinkage_summary}"}
    with open(output_dir / "robustness_penalty.json", "w") as f:
        json.dump(robustness, f, indent=2)

    # 3. Sample quality
    logger.info("Running sample quality sweep")
    quality = sample_quality_sweep(samples)
    with open(output_dir / "sample_quality.json", "w") as f:
        json.dump(quality, f, indent=2, default=str)

    # Markdown report
    md = _write_markdown_report(era, robustness, quality)
    with open(output_dir / "sensitivity_report.md", "w") as f:
        f.write(md)

    print(json.dumps({
        "era_beta_avg_abs_diff": era.get("beta_avg_abs_diff_pre_vs_post"),
        "robustness_sensitive": robustness.get("sensitive"),
        "quality_quartile_count": len(quality),
    }, indent=2, default=str))
    return 0


def _write_markdown_report(era: dict, robustness: dict, quality: dict) -> str:
    lines = ["# PR2b Sensitivity Report (2026-05-25)\n"]

    # Era split
    lines.append("## Section 1: Era Split (pre/post 2010-01-01)\n")
    lines.append(f"- pre-2010: N={era['pre_2010_n']}, in-sample Sharpe={era['pre_2010_in_sample_sharpe']}")
    lines.append(f"- post-2010: N={era['post_2010_n']}, in-sample Sharpe={era['post_2010_in_sample_sharpe']}")
    diff = era['beta_avg_abs_diff_pre_vs_post']
    if diff is not None:
        verdict = "STABLE" if diff < 0.03 else ("MODERATE DRIFT" if diff < 0.06 else "DRIFT")
        lines.append(f"- |β_pre - β_post|_avg = **{diff:.4f}** ({verdict})")
    lines.append("")

    # Robustness
    lines.append("## Section 2: Robustness Penalty {0.10, 0.25, 0.50}\n")
    if "error" in robustness:
        lines.append(f"⚠️ {robustness['error']}")
    else:
        lines.append("| Penalty coefficient | Best shrinkage |")
        lines.append("|---|---|")
        lines.append(f"| 0.10 | {robustness['best_at_0.10']} |")
        lines.append(f"| 0.25 (default) | {robustness['best_at_0.25_default']} |")
        lines.append(f"| 0.50 | {robustness['best_at_0.50']} |")
        verdict = "SENSITIVE — best shrinkage 가 계수에 의존" if robustness["sensitive"] else "STABLE — 계수 변경 무관"
        lines.append(f"\n**Verdict**: {verdict}")
    lines.append("")

    # Sample quality
    lines.append("## Section 3: Sample Quality Stratified\n")
    lines.append("| Quartile | N | Mean confidence | OOS Sharpe (calibrated) |")
    lines.append("|---|---|---|---|")
    for q, r in quality.items():
        s = r.get("sharpe")
        s_str = f"{s:.3f}" if s is not None else "n/a"
        mc = r.get("mean_quality", 0.0)
        lines.append(f"| {q} | {r['n']} | {mc:.3f} | {s_str} |")
    lines.append("")

    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
```

### Task 3.2: Sensitivity 실행

- [ ] **Step 1: 실행**

```bash
uv run python scripts/sensitivity_sweep.py \
    --samples backtest/historical/samples.parquet \
    --output-dir artifacts/2026-05-25/sensitivity \
    --per-shrinkage-summary artifacts/2026-05-24/calibration_runs/per_shrinkage_summary.json
```

Expected stdout:
```json
{
  "era_beta_avg_abs_diff": <float>,
  "robustness_sensitive": false | true,
  "quality_quartile_count": 4
}
```

산출물:
- `artifacts/2026-05-25/sensitivity/{era_split, robustness_penalty, sample_quality}.json`
- `artifacts/2026-05-25/sensitivity/sensitivity_report.md`

- [ ] **Step 2: sensitivity_report.md 검토**

```bash
cat artifacts/2026-05-25/sensitivity/sensitivity_report.md
```

### Task 3.3: Pre-commit regression + commit

- [ ] **Step 1: regression**

```bash
uv run python -m pytest tests/unit/ -q 2>&1 | tail -3
uv run python -m pytest tests/integration/ -q 2>&1 | tail -3
```

Expected: baseline 동일.

- [ ] **Step 2: regression_log.md "## Post-C3" entry**

- [ ] **Step 3: commit**

```bash
git add scripts/sensitivity_sweep.py
git add -f artifacts/2026-05-25/sensitivity/era_split.json \
            artifacts/2026-05-25/sensitivity/robustness_penalty.json \
            artifacts/2026-05-25/sensitivity/sample_quality.json \
            artifacts/2026-05-25/sensitivity/sensitivity_report.md \
            artifacts/2026-05-25/regression_log.md

git commit -m "$(cat <<'EOF'
data(stage2b): sensitivity sweeps — era + robustness + sample_quality (C3)

scripts/sensitivity_sweep.py — 3 sub-sweeps:

1. Era split (2010-01-01 boundary, ALFRED data coverage break):
   - pre-2010 separate calibrate vs post-2010 → β stability metric
     |β_pre - β_post|_avg.
2. Robustness penalty: select_best_shrinkage 의 0.25 계수 → {0.10, 0.50}
   변경 시 best_shrinkage 가 stable 한지.
3. Sample quality stratified: per-quarter mean confidence 의 quartile 별
   OOS Sharpe (calibrated INITIAL_BETA).

산출물:
- era_split.json + robustness_penalty.json + sample_quality.json
- sensitivity_report.md (markdown table)

Verdict: see sensitivity_report.md.

Regression: 0 new failure.
EOF
)"
```

---

## Task 4: Production Regen (C4)

`scripts/replay_stage.py` 로 2026-05-15 시점의 full pipeline 재실행.

### Task 4.1: 기존 artifacts/2026-05-15/* 백업 + 사전 검토

기존 산출물 은 git history 에 보존되어 있으므로 별도 백업 불요. Diff 비교용 으로 기존 portfolio.json 의 bucket weight 메모.

- [ ] **Step 1: 기존 portfolio.json 의 bucket weight 추출**

```bash
uv run python -c "
import json
with open('artifacts/2026-05-15/portfolio.json') as f:
    d = json.load(f)
# bucket weight 위치 검출 — 보통 'bucket_weights' 또는 'allocations'.
import sys
print(json.dumps({k: d.get(k) for k in ('bucket_weights', 'allocations', 'targets')
                  if k in d}, indent=2, default=str)[:500])
"
```

(기존 schema 에 따라 key 명 다를 수 있음 — 필요 시 grep)

### Task 4.2: replay_stage.py 실행

- [ ] **Step 1: 환경 변수 + 실행**

```bash
set -a && source .env && set +a

uv run python scripts/replay_stage.py \
    --as-of 2026-05-15 \
    --stage portfolio_manager \
    --write-archive \
    2>&1 | tee /tmp/c4_regen.log
```

**중요**: `--stage portfolio_manager` 는 prerequisite chain (macro_quant → research_debate → allocator → risk_debate → validator → portfolio_manager) 을 자동 실행. LLM 호출 포함, ~5 분 소요.

Expected: artifacts/2026-05-15/* 4 files (backtest_summary.json, philosophy.md, portfolio.json, trade_plan.csv) 가 새 INITIAL_BETA 기반으로 갱신.

- [ ] **Step 2: 실행 결과 확인**

```bash
ls -la artifacts/2026-05-15/*.{json,md,csv}
git diff --stat artifacts/2026-05-15/
```

Expected: 4 files modified.

### Task 4.3: Diff report 작성

- [ ] **Step 1: 새 portfolio.json 의 bucket weight 추출 + diff 계산**

`artifacts/2026-05-25/regen/diff_report.md`:

```markdown
# PR2b 2026-05-15 Regen Diff Report

## Methodology

`scripts/replay_stage.py --as-of 2026-05-15 --stage portfolio_manager --write-archive`
실행 결과를 git history 의 이전 artifacts/2026-05-15/* 와 비교.

## Bucket Weight Comparison

| Bucket | Old (hand-coded β) | New (calibrated β) | Δ |
|---|---|---|---|
| kr_equity | <old> | <new> | <delta> |
| global_equity | <old> | <new> | <delta> |
| fx_commodity | <old> | <new> | <delta> |
| bond | <old> | <new> | <delta> |
| cash_mmf | <old> | <new> | <delta> |

## Key Metric Changes

| Metric | Old | New |
|---|---|---|
| dominant_cycle | <old> | <new> |
| conviction | <old> | <new> |
| dominant_cell.cycle | <old> | <new> |

## Narrative Diff (philosophy.md)

[brief notes on whether the LLM-authored narrative changed meaningfully]
```

- [ ] **Step 2: diff_report.md 자동 채움 스크립트**

```bash
uv run python -c "
import json, subprocess
# Read new
with open('artifacts/2026-05-15/portfolio.json') as f:
    new = json.load(f)
with open('artifacts/2026-05-15/backtest_summary.json') as f:
    new_bs = json.load(f)
# Read old (git HEAD~1)
old_pf = json.loads(subprocess.check_output(['git', 'show', 'HEAD:artifacts/2026-05-15/portfolio.json']))
old_bs = json.loads(subprocess.check_output(['git', 'show', 'HEAD:artifacts/2026-05-15/backtest_summary.json']))
print('OLD portfolio:', list(old_pf.keys())[:5])
print('NEW portfolio:', list(new.keys())[:5])
print('OLD bs:', old_bs)
print('NEW bs:', new_bs)
" 2>&1 | head -30
```

기존 schema 보고 diff_report.md 의 빈 칸 채우기. 정확한 schema 가 portfolio.json 마다 다르므로 manual fill-in.

### Task 4.4: [grill-me #2 marker]

본 시점에서 **executing-plans 가 일시 멈추고 grill-me #2 수행**.

Grill 대상:
1. **Regen 성공 여부**: 4 artifacts 모두 갱신 됐는가? LLM 호출 실패는?
2. **Bucket weight 변화**: hand-coded β 산출물 대비 의미 있는 변화? 너무 큰 변화면 calibration 의 production 의미 우려.
3. **Narrative 차이**: philosophy.md 의 톤 / 결론 변화 합리적?

만약 LLM 호출 실패 / partial regen 인 경우: user 가 partial 수용 또는 retry 결정.

Grill 결과 → decisions.md 의 "grill-me #2" section 에 기록.

### Task 4.5: Pre-commit regression + commit

- [ ] **Step 1: regression**

```bash
uv run python -m pytest tests/unit/ -q 2>&1 | tail -3
uv run python -m pytest tests/integration/ -q 2>&1 | tail -3
```

Expected: baseline 동일.

- [ ] **Step 2: regression_log.md "## Post-C4" entry**

- [ ] **Step 3: commit**

```bash
git add artifacts/2026-05-15/
git add -f artifacts/2026-05-25/regen/diff_report.md \
            artifacts/2026-05-25/regression_log.md \
            artifacts/2026-05-25/decisions.md

git commit -m "$(cat <<'EOF'
data(stage2b): 2026-05-15 production regen with new INITIAL_BETA (C4)

scripts/replay_stage.py --as-of 2026-05-15 --stage portfolio_manager
--write-archive 실행. Prerequisite chain (macro_quant → research_debate →
allocator → risk_debate → validator → portfolio_manager) 으로 stage 1-6
전체 재실행. LLM 호출 포함, ~5분.

산출물 (artifacts/2026-05-15/):
- backtest_summary.json
- philosophy.md
- portfolio.json
- trade_plan.csv

Diff vs hand-coded β 결과 산출물:
artifacts/2026-05-25/regen/diff_report.md (bucket weight Δ + narrative
diff).

Grill-me #2 결정: see decisions.md.

Regression: 0 new failure (production code 변경 무).
EOF
)"
```

---

## Task 5: Docs Final (C5)

decisions.md final + Issue #18 update + sign-off checklist.

### Task 5.1: decisions.md final section

- [ ] **Step 1: artifacts/2026-05-25/decisions.md 의 끝에 append**

```markdown
## Final Status (PR2b 완료, 2026-05-25)

[PASS path — calibrated 가 모든 benchmark 우월 + regime 모두 우월]
- Verdict: PASS
- Best benchmark: <name>, Δ vs calibrated = <value>
- NBER recession Sharpe: calibrated <value> vs best benchmark <value>
- Era β stability: |β_pre - β_post|_avg = <value> (STABLE / DRIFT)
- Robustness penalty: STABLE / SENSITIVE
- Regen: 4 artifacts 갱신 완료

[PASS with caveat path — calibrated 가 1 benchmark 또는 1 regime 에서 underperform]
- Verdict: PASS with caveat (see Section X of validation_report.md)
- Caveat: <specific benchmark / regime>
- 권장: INITIAL_BETA 유지 + caveat 를 followup_issues.md 에 기록

[FAIL path — calibrated 가 best benchmark 에 underperform]
- Verdict: FAIL
- Underperform vs <name>: Δ = <value>
- 권장: INITIAL_BETA revert (별도 PR) — PR2a 결과 미신뢰

## Critical issue 처리 결과
- K1 (caveat reporting): completed (validation_report Section X)
- K2 (NBER small N): Cohen's d 병행 (Section 1)
- K3 (regen LLM 실패): [skipped / partial / full success]
- K4 (working tree): main 기준 clean branch 에서 시작 (C0 step 1 확인)

## 2 grill-me decisions
[summary of grill-me #1 and #2 decisions]
```

### Task 5.2: Issue #18 status update

- [ ] **Step 1: docs/followup_issues.md 의 Issue #18 update**

기존 PR2a 의 "RESOLVED" → "FULLY VERIFIED" (PASS path) 또는 caveat 추가 (PASS with caveat path).

```markdown
## Issue #18 — factor model β 의 real historical fetch + production calibration

### Status (PR2b 완료, 2026-05-25) — **FULLY VERIFIED** (or **VERIFIED with caveat**)

PR2b 의 validation report 가 calibrated 의 우월성을 5 strategy 비교, NBER
regime decomposition, era stability sensitivity, production regen 검증.

- 5-strategy comparison: calibrated 가 4/4 (또는 3/4) 비교에서 우월
- NBER regime decomposition: expansion + recession 모두 calibrated 우월
- Era stability: |β_pre - β_post|_avg = <value>, [STABLE / DRIFT]
- Production regen: 2026-05-15 산출물 갱신 (artifacts/2026-05-15/* 4 files)

Full validation: artifacts/2026-05-25/validation/validation_report.md.

### (Historical) Status (PR2a 완료, 2026-05-24) — RESOLVED
[기존 내용 유지]
```

### Task 5.3: Spec sign-off

- [ ] **Step 1: spec section 9 의 모든 [ ] → [x]**

```bash
# docs/superpowers/specs/2026-05-25-stage2b-validation-design.md 의
# Section 9 Sign-off Checklist 의 모든 체크박스 확인 + [x] 로 변경.
```

(manual edit — checkbox 위치 sec 9)

### Task 5.4: Final regression + commit

- [ ] **Step 1: 전체 regression**

```bash
uv run python -m pytest tests/unit/ -q 2>&1 | tail -3
uv run python -m pytest tests/integration/ -q 2>&1 | tail -3
```

Expected: baseline 동일.

- [ ] **Step 2: regression_log.md "## Post-C5 (FINAL)" entry**

```markdown
## Post-C5 (FINAL — PR2b 완료)

[paste pytest]

Total new unit pass since PR2b baseline: +16 (C1 utilities).
0 new failure through PR2b C0-C5.

PR2b status: [PASS / PASS with caveat / FAIL]
INITIAL_BETA: [keep / keep with caveat / revert recommended]
Spec sign-off: complete.
```

- [ ] **Step 3: commit**

```bash
git add docs/superpowers/specs/2026-05-25-stage2b-validation-design.md
git add docs/followup_issues.md
git add -f artifacts/2026-05-25/decisions.md \
            artifacts/2026-05-25/regression_log.md

git commit -m "$(cat <<'EOF'
docs(stage2b): spec sign-off + Issue #18 FULLY VERIFIED + decisions final (C5)

PR2b 의 final commit.

- docs/superpowers/specs/2026-05-25-stage2b-validation-design.md:
  Section 9 Sign-off Checklist 의 모든 [ ] → [x]. Status: [PASS / PASS
  with caveat / FAIL].
- docs/followup_issues.md: Issue #18 status FULLY VERIFIED 또는 VERIFIED
  with caveat.
- artifacts/2026-05-25/decisions.md: final section + 2 grill-me decision
  + Critical 1-4 처리 결과.
- artifacts/2026-05-25/regression_log.md: Post-C5 final entry.

PR2b 종착점:
- 5-strategy benchmark comparison: validation_report.md
- NBER regime decomposition: 2 regime Sharpe
- Sensitivity sweeps (era / robustness / sample_quality): sensitivity_report.md
- 2026-05-15 production regen: 4 artifacts 갱신
- INITIAL_BETA: [keep / keep with caveat / revert]

다음 단계: PR2c (24-cell legacy benchmark 또는 quarterly re-calibration
cadence 또는 다른 sensitivity).
EOF
)"
```

---

## Self-Review Checklist (Plan 자체)

본 plan 의 무결성 확인 — execution 전 살펴볼 항목:

- [x] Spec section 0 (Q1-Q6 + Critical K1-K4) 의 모든 결정 이 어느 Task 에서 implement 되는지 명확
  - Q1 Full scope → C0~C5 전체
  - Q2 NBER regime → C1 Task 1.2 (regime.py) + C2 validate_factor_model.py
  - Q3 Full sensitivity → C3 sensitivity_sweep.py
  - Q4 Full regen → C4 replay_stage.py
  - Q5 6 commits → C0-C5 ✓
  - Q6 2 grill-me → Task 2.4 (#1) + Task 4.4 (#2)
- [x] Spec section 2.2 의 모든 신규 / modified file 이 Task 의 Files block 에 등장
- [x] 6 commit (C0-C5) 가 Task 0-5 와 1:1 mapping
- [x] 2 grill-me 시점 (Task 2.4, Task 4.4) 의 marker 명시
- [x] 각 Task 의 TDD pattern: 실패 test → 실행/fail 확인 → 최소 구현 → 실행/pass 확인 → commit
- [x] 24-cell legacy 는 spec 의 deferred 와 명시 일치 (Task 2.1 의 strategies dict 에 미포함)
- [x] Placeholder 없음 — 모든 code block actual content

**Note on Task 4.2**: `replay_stage.py --stage portfolio_manager` 가 prerequisite chain 으로 stage 1-6 모두 실행 한다는 가정 — 만약 실제 동작이 다르면 (예: 단일 stage 만 실행) C4 plan 의 step 1 을 수정 필요 (예: 각 stage 를 sequential 호출 또는 다른 entry point).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-25-stage2b-validation.md`.

본 plan 은 PR2a 와 동일 패턴 (commit 순차 + grill-me 2회 + per-commit regression) 사용. executing-plans skill 이 task 0-5 를 순차 실행. Task 2.4 / Task 4.4 의 grill-me marker 에서 일시 멈춰 user 와 review 후 진행.

다음 세션: `superpowers:executing-plans` 또는 `superpowers:subagent-driven-development` (subagent 지원 시) 로 실행.
