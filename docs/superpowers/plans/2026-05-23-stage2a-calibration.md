# Stage 2a — Factor Model β Calibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (user choice — Q8 of brainstorming, PR1 방식 commit 순차 + grill-me 3회). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PR1 후속 — historical walk-forward Sharpe optimization 으로 `INITIAL_BETA` 를 data-driven 으로 교체 (acceptance gate PASS 시).

**Architecture:** Linux-first historical fetch (FRED + ALFRED vintage-aware + yfinance + pykrx) → quarterly indicator panel → date-parameterized minimal-proxy Stage 1 builder → `compute_all_factors(state, mode="historical")` → 135Q samples → walk-forward (7 folds) × shrinkage grid (5 values) → acceptance gate (5 strict-default condition + paired-t + diagnostic) → INITIAL_BETA 교체 (PASS) 또는 Issue 작성 (FAIL).

**Tech Stack:** Python 3.12, pydantic v2, pandas, scipy (L-BFGS-B + ttest_rel), numpy, fredapi (FRED+ALFRED), yfinance, pykrx, pytest, parquet (pyarrow).

**Spec:** `docs/superpowers/specs/2026-05-23-stage2a-calibration-design.md`

**Branch base:** PR1 의 마지막 commit (`feat/stage1-enhance-for-factor-model`, e52e2dc) 또는 그 merge 후의 main 등가.

**Quality gates:**
- 매 commit 후 regression test (pytest unit + integration) + `artifacts/2026-05-XX/regression_log.md` 갱신 (0 new failure 검증)
- Selective grill-me 3 시점 (after C3 / after C5 / after C8)

**Memory policies (필독):**
- `feedback_regression_tests.md`: 모든 코드 수정 시 regression test 의무
- `feedback_long_session_protocol.md`: long-session 환각 차단 8 원칙

---

## File Structure

### Created (production code)
- `tradingagents/backtest/historical/__init__.py`
- `tradingagents/backtest/historical/fetcher_fred.py` — latest-vintage FRED fetch (existing `dataflows/fred.py` 의 thin wrapper + parquet cache)
- `tradingagents/backtest/historical/fetcher_alfred.py` — ALFRED vintage-aware fetch (7 revising series, Critical 1)
- `tradingagents/backtest/historical/fetcher_yfinance.py` — yfinance daily Close fetch + parquet cache
- `tradingagents/backtest/historical/fetcher_pykrx.py` — pykrx KR fetch (KOSPI200 PBR/PER/DivYield + foreign flow) + parquet cache
- `tradingagents/backtest/historical/aggregate.py` — quarterly aggregation + derived computations
- `tradingagents/backtest/historical/stage1_builder.py` — date-parameterized minimal-proxy Stage 1 builder
- `tradingagents/backtest/historical/bucket_returns.py` — KRW basis 5-bucket quarterly returns
- `tradingagents/backtest/historical/shiller_cape_static.csv` — Shiller CAPE 정적 (~50KB)
- `tradingagents/backtest/acceptance.py` — acceptance gate (5 condition + paired-t + diagnostic)
- `scripts/generate_historical_factor_z.py` — end-to-end fetch → aggregate → build → compute → parquet
- `scripts/calibrate_factor_model.py` — walk-forward + shrinkage grid + acceptance runner

### Created (tests)
- `tests/unit/backtest/historical/__init__.py`
- `tests/unit/backtest/historical/test_fetcher_fred.py`
- `tests/unit/backtest/historical/test_fetcher_alfred.py`
- `tests/unit/backtest/historical/test_fetcher_yfinance.py`
- `tests/unit/backtest/historical/test_fetcher_pykrx.py`
- `tests/unit/backtest/historical/test_aggregate.py`
- `tests/unit/backtest/historical/test_stage1_builder.py`
- `tests/unit/backtest/historical/test_bucket_returns.py`
- `tests/unit/backtest/test_acceptance.py`
- `tests/unit/skills/research/test_factor_estimators_historical_mode.py` — Critical 2 backward-compat + historical renorm
- `tests/integration/test_calibration_pipeline_synthetic.py` — walk-forward + acceptance synthetic smoke
- `tests/integration/test_historical_factor_z_end_to_end.py` — opt-in (env var) Linux end-to-end

### Created (artifacts)
- `artifacts/2026-05-XX/decisions.md` — C0
- `artifacts/2026-05-XX/regression_log.md` — C0 + 매 commit entry
- `artifacts/2026-05-XX/job_status.json` — long fetch + calibration 작업 상태
- `artifacts/2026-05-XX/calibration_runs/per_fold/shrinkage_{s}_fold_{i}.json` (35 files, C8)
- `artifacts/2026-05-XX/calibration_runs/per_shrinkage_summary.json` (C8)
- `artifacts/2026-05-XX/calibration_runs/best_shrinkage.json` (C8)
- `artifacts/2026-05-XX/calibration_runs/vintage_sanity.json` (C8)
- `artifacts/2026-05-XX/calibration_runs/equi_weight_baseline.json` (C8)
- `artifacts/2026-05-XX/calibration_runs/learning_sensitivity.json` (C8)
- `artifacts/2026-05-XX/calibration_runs/validation_report.json` (C8)

### Created (data, committed)
- `backtest/historical/quarterly_indicators.parquet` (C5)
- `backtest/historical/factor_z.parquet` (C5)
- `backtest/historical/bucket_returns.parquet` (C5)
- `backtest/historical/samples.parquet` (C5)

### Modified
- `tradingagents/skills/research/factor_estimators.py` — `mode` parameter 추가 (C4)
- `tradingagents/skills/research/factor_to_bucket.py` — `INITIAL_BETA` 교체 (C9, PASS 시)
- `tests/unit/skills/research/test_factor_to_bucket.py` — INITIAL_BETA 의존 assertion update (C9, PASS 시)
- `.gitignore` — `backtest/historical/raw/` 추가 (C0)
- `docs/followup_issues.md` — Issue #18 status update (C10)
- `docs/superpowers/specs/2026-05-23-stage2a-calibration-design.md` — C10 의 status checkmark

---

## Task 0: Branch + Execution Safeguards (C0)

### Task 0.1: 새 branch 생성

**Files:** branch creation, no files yet

- [ ] **Step 1: 현재 상태 확인**

```bash
git status --short
git log --oneline -3
git branch --show-current
```

Expected: 현재 branch `feat/stage1-enhance-for-factor-model`, 최근 commit `e52e2dc docs(stage1): backlog (Issue #13-#23 status) + audit + decisions final (C11)`. 또는 PR1 merge 후의 main.

- [ ] **Step 2: 새 branch 생성**

```bash
git checkout -b feat/stage2a-beta-calibration
```

Expected: `Switched to a new branch 'feat/stage2a-beta-calibration'`.

- [ ] **Step 3: regression baseline 확인**

```bash
uv run pytest tests/unit/ -q 2>&1 | tail -3
uv run pytest tests/integration/ -q 2>&1 | tail -3
```

Expected (PR1 baseline 유지):
- Unit: 3 failed (pre-existing) / ~670+ passed
- Integration: 18 failed (pre-existing) / ~30 passed

→ 만약 baseline 가 다르면 PR1 merge 시 변경 발생 가능 — `artifacts/2026-05-23/regression_log.md` (PR1 마지막 entry) 와 비교 후 진행.

### Task 0.2: artifacts/<run-date>/ scaffolding

**Files:**
- Create: `artifacts/<run-date>/decisions.md`
- Create: `artifacts/<run-date>/regression_log.md`
- Create: `artifacts/<run-date>/job_status.json`
- Create: `artifacts/<run-date>/calibration_runs/.gitkeep`

`<run-date>` 는 본 PR2a 의 실제 실행 시작일 (YYYY-MM-DD). 보통 PR2a 시작 당일. 이후 모든 task 의 `2026-05-XX` 는 실제 `<run-date>` 로 치환.

- [ ] **Step 1: scaffolding directory + files 생성**

```bash
RUN_DATE=$(date +%Y-%m-%d)
mkdir -p artifacts/$RUN_DATE/calibration_runs
touch artifacts/$RUN_DATE/calibration_runs/.gitkeep
```

- [ ] **Step 2: decisions.md 생성 (spec section 0 의 결정 외부화)**

`artifacts/<run-date>/decisions.md`:

```markdown
# PR2a Calibration — Decisions Log

본 파일은 spec `2026-05-23-stage2a-calibration-design.md` 의 section 0 결정 의 외부화.
모든 grill-me 결정도 본 파일에 append.

## Brainstorming 결정 (확정 — 2026-05-23)

- Q1 Scope: 2-PR decompose (PR2a data+calibration / PR2b benchmarks+analysis)
- Q2 Window: 1991-Q1 to 2024-Q3 (135Q) with graceful per-factor degradation
- Q3 Calib target: β only (45 params) with shrinkage + sign penalty
- Q4 Calib protocol: shrinkage grid {0.1, 0.3, 0.5, 1.0, 2.0} × walk-forward (initial_train=80, test=7) → 7 folds
- Q5 Acceptance: strict-default 5-condition (Critical 3 강화)
- Q6 Reconstruction: production reuse with date-parameterized minimal-proxy Stage 1 builder
- Q7 Linux/cache: Linux-first + multi-tier cache (raw gitignored, quarterly + factor z + bucket returns + samples committed)
- Q8 Execution: PR1 방식 — commit 순차 + grill-me 3회 + per-commit regression
- Q9 Issue scope: 최소 범위 — Linux 우회 #20/#21, 영구 fix 별도 PR

## Critical issue 처리

- C1 (Point-in-time): ALFRED vintage fetch for 7 series (CFNAI, NFCI, ANFCI, GDPNOW, UNRATE, CPIAUCSL, PCEPILFE)
- C2 (News-sentinel mismatch): factor_estimators 의 mode="historical" flag — news weight 0 + quant renorm
- C3 (Gate strictness): paired-t p<0.20 + |IS-OOS|<0.30 + ≥6/7 folds positive
- C4 (Currency basis): KRW basis with USDKRW translation, pre-1996 kr_equity None

## grill-me decisions (appended at each grill point)

(grill-me #1: TBD)
(grill-me #2: TBD)
(grill-me #3: TBD)
```

- [ ] **Step 3: regression_log.md 생성**

`artifacts/<run-date>/regression_log.md`:

```markdown
# PR2a Regression Log

매 commit 직후 본 파일 에 entry 추가:
- Commit ID + message
- Unit test result (passed/failed count)
- Integration test result (passed/failed count)
- Δ from previous commit (new fail or new pass)
- 0 new failure 확인

## Baseline (post PR1 e52e2dc / pre PR2a C0)

```
$ uv run pytest tests/unit/ -q
[PR1 baseline output here]

$ uv run pytest tests/integration/ -q
[PR1 baseline output here]
```

Pre-existing fail: 3 unit + 18 integration.

## Post-C0 (chore: execution safeguards)
[fill at C0 commit time]
```

- [ ] **Step 4: job_status.json 생성**

`artifacts/<run-date>/job_status.json`:

```json
{
  "pr": "PR2a — Stage 2a β calibration",
  "branch": "feat/stage2a-beta-calibration",
  "started_at": "<ISO date>",
  "current_commit": "C0",
  "status": "scaffolding",
  "long_running_jobs": {},
  "notes": "PR1 후 / PR2b 전 — Issue #18 resolution"
}
```

- [ ] **Step 5: `.gitignore` 에 raw cache 추가**

`.gitignore` 끝에 추가:

```
# PR2a — historical raw data caches (gitignored, generated by Linux fetch)
backtest/historical/raw/
```

- [ ] **Step 6: commit**

```bash
git add artifacts/<run-date>/ .gitignore
git commit -m "$(cat <<'EOF'
chore(stage2a): execution safeguards + decisions/regression scaffolding (C0)

PR2a (factor model β calibration) 시작 의 safeguard scaffolding.

- artifacts/<run-date>/decisions.md: spec section 0 의 모든 결정 외부화 +
  grill-me decision 누적 영역.
- artifacts/<run-date>/regression_log.md: 매 commit baseline 비교 영역
  (PR1 의 3 unit + 18 integ pre-existing fail 유지).
- artifacts/<run-date>/job_status.json: long-running fetch (ALFRED ~1000
  call) + 35 calibration runs 의 progress tracking.
- .gitignore: backtest/historical/raw/ (daily parquet 캐시 gitignore).

다음 commit (C1) 부터 본 scaffold 사용.
EOF
)"
```

- [ ] **Step 7: post-C0 regression test (baseline 유지 확인)**

```bash
uv run pytest tests/unit/ -q 2>&1 | tail -3
uv run pytest tests/integration/ -q 2>&1 | tail -3
```

Expected: PR1 baseline 동일 (3 unit + 18 integ fail). `regression_log.md` 의 "## Post-C0" section 채움.

---

## Task 1: Historical Fetchers (C1)

본 commit 은 4 개 fetcher (FRED + ALFRED + yfinance + pykrx) + parquet cache + unit tests 단일 commit. 각 fetcher 는 기존 `tradingagents/dataflows/` 의 함수 위 thin wrapper + cache.

### Task 1.0: `tradingagents/backtest/historical/__init__.py` 생성

- [ ] **Step 1: 빈 init 파일 생성**

`tradingagents/backtest/historical/__init__.py`:

```python
"""Historical Stage 1 reconstruction for factor model β calibration (PR2a).

Sub-modules:
- fetcher_fred: FRED latest-vintage thin wrapper + parquet cache
- fetcher_alfred: ALFRED vintage-aware fetch (7 revising series) — Critical 1
- fetcher_yfinance: yfinance daily Close + parquet cache
- fetcher_pykrx: pykrx KR market data + parquet cache
- aggregate: daily/monthly → quarterly indicator panel + derived
- stage1_builder: date-parameterized minimal-proxy Stage 1 builder
- bucket_returns: KRW basis 5-bucket quarterly returns

본 패키지는 PR1 의 production code (factor_estimators, factor_calibration)
를 그대로 호출. 단 factor_estimators 는 mode='historical' 로 호출.
"""
```

- [ ] **Step 2: `tests/unit/backtest/historical/__init__.py` 생성** (빈 파일)

### Task 1.1: `fetcher_fred.py` — FRED latest-vintage thin wrapper + parquet cache

**Files:**
- Create: `tradingagents/backtest/historical/fetcher_fred.py`
- Create: `tests/unit/backtest/historical/test_fetcher_fred.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/backtest/historical/test_fetcher_fred.py`:

```python
"""Unit tests for fetcher_fred — thin wrapper + parquet cache."""
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.backtest.historical.fetcher_fred import (
    fetch_fred_latest, FRED_QUARTERLY_SERIES,
)


def test_fetch_fred_latest_uses_cache_if_available(tmp_path: Path) -> None:
    """Cache 가 있으면 FRED API call 없이 parquet 에서 read."""
    cache_path = tmp_path / "raw" / "fred" / "DGS10.parquet"
    cache_path.parent.mkdir(parents=True)
    cached = pd.Series(
        [3.0, 3.1, 3.2], index=pd.date_range("1991-01-01", periods=3, freq="D"),
        name="DGS10",
    )
    cached.to_frame("value").to_parquet(cache_path)

    with patch("tradingagents.backtest.historical.fetcher_fred.fetch_fred_series") as m:
        result = fetch_fred_latest("DGS10", date(1991, 1, 1), date(1991, 1, 3),
                                    cache_dir=tmp_path / "raw" / "fred")
        m.assert_not_called()
    assert len(result) == 3
    assert result.iloc[0] == 3.0


def test_fetch_fred_latest_fetches_and_caches_on_miss(tmp_path: Path) -> None:
    """Cache miss → fetch_fred_series 호출 → parquet 저장."""
    fake_series = pd.Series(
        [4.0, 4.1], index=pd.date_range("1991-01-01", periods=2, freq="D"),
        name="DGS10",
    )
    with patch(
        "tradingagents.backtest.historical.fetcher_fred.fetch_fred_series",
        return_value=fake_series,
    ) as m:
        result = fetch_fred_latest("DGS10", date(1991, 1, 1), date(1991, 1, 2),
                                    cache_dir=tmp_path / "raw" / "fred")
        m.assert_called_once()

    assert (tmp_path / "raw" / "fred" / "DGS10.parquet").exists()
    assert len(result) == 2


def test_fred_quarterly_series_includes_critical_indicators() -> None:
    """C1-C4 의 modeled indicator 가 series map 에 등록."""
    required = {"DGS10", "DGS2", "DGS5", "DGS30", "CPIAUCSL", "PCEPILFE",
                "DFII10", "DEXKOUS", "DTWEXM", "BAA", "AAA", "BAA10Y", "MICH",
                "T5YIFR", "VIXCLS", "UNRATE", "TB3MS"}
    assert required.issubset(set(FRED_QUARTERLY_SERIES))
```

- [ ] **Step 2: 테스트 실행 → fail 확인**

```bash
uv run pytest tests/unit/backtest/historical/test_fetcher_fred.py -v
```

Expected: ImportError — `tradingagents.backtest.historical.fetcher_fred` 부재.

- [ ] **Step 3: 최소 구현**

`tradingagents/backtest/historical/fetcher_fred.py`:

```python
"""FRED latest-vintage fetcher — thin wrapper + parquet cache.

기존 dataflows.fred.fetch_fred_series 를 wrap. Daily series 는 revise 없으므로
latest-vintage = 모든 시점 같음. Revised series (CFNAI, NFCI, GDPNOW 등) 는
fetcher_alfred 사용.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd

from tradingagents.dataflows.fred import fetch_fred_series

logger = logging.getLogger(__name__)


# C1 fetch 대상 FRED series — spec section 3.2 참조. ALFRED 대상 (revising) 은 제외.
FRED_QUARTERLY_SERIES: list[str] = [
    # Yield curve
    "DGS2", "DGS5", "DGS10", "DGS30",
    # Inflation (CPIAUCSL 은 ALFRED 으로 vintage fetch — 여기 latest-only 도 cross-check)
    "CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE",
    # Inflation expectations
    "T5YIFR", "MICH",
    # Real yields (no revise, daily)
    "DFII10", "DFII5",
    # Credit
    "BAA", "AAA", "BAA10Y",
    # FX
    "DEXKOUS", "DTWEXM",
    # Cash
    "TB3MS",
    # Vol
    "VIXCLS",
    # Recession dummy
    "USREC",
    # Labor (UNRATE 은 ALFRED — 여기 latest cross-check)
    "UNRATE",
]


def fetch_fred_latest(
    series_id: str,
    start: date,
    end: date,
    cache_dir: Path | str,
) -> pd.Series:
    """Latest-vintage FRED fetch with parquet cache.

    Cache strategy: per-series single parquet. Cache hit → read; miss → fetch + write.

    Args:
        series_id: FRED native ID (e.g., "DGS10"). NOT the alias map key
                   (use raw FRED ID, since cache file 이 series_id 로 명명).
        start, end: date range (inclusive).
        cache_dir: e.g., `backtest/historical/raw/fred/`.

    Returns:
        pd.Series indexed by date.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{series_id}.parquet"

    if cache_path.exists():
        df = pd.read_parquet(cache_path)
        series = df["value"]
        series.name = series_id
        # Verify cache covers [start, end]
        if series.index.min().date() <= start and series.index.max().date() >= end:
            logger.debug("FRED %s: cache hit (%s rows)", series_id, len(series))
            return series.loc[start:end]
        # Cache 가 부족 — fall through to refetch
        logger.info("FRED %s: cache stale, refetching", series_id)

    series = fetch_fred_series(series_id, start, end)
    series.name = series_id
    series.to_frame("value").to_parquet(cache_path)
    logger.info("FRED %s: fetched %s rows, cached", series_id, len(series))
    return series
```

- [ ] **Step 4: 테스트 재실행 → pass 확인**

```bash
uv run pytest tests/unit/backtest/historical/test_fetcher_fred.py -v
```

Expected: 3 tests pass.

### Task 1.2: `fetcher_alfred.py` — ALFRED vintage-aware fetch (Critical 1)

**Files:**
- Create: `tradingagents/backtest/historical/fetcher_alfred.py`
- Create: `tests/unit/backtest/historical/test_fetcher_alfred.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/backtest/historical/test_fetcher_alfred.py`:

```python
"""Unit tests for fetcher_alfred — vintage-aware FRED fetch (Critical 1)."""
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from tradingagents.backtest.historical.fetcher_alfred import (
    fetch_alfred_vintage_quarterly, ALFRED_SERIES,
)


def test_alfred_series_lists_7_revising() -> None:
    """7 revising series — Critical 1."""
    assert set(ALFRED_SERIES) == {
        "CFNAI", "NFCI", "ANFCI", "GDPNOW",
        "UNRATE", "CPIAUCSL", "PCEPILFE",
    }


def test_fetch_alfred_vintage_uses_cache(tmp_path: Path) -> None:
    """Cache hit → API call 없음."""
    cache_path = tmp_path / "raw" / "fred_alfred" / "CFNAI.parquet"
    cache_path.parent.mkdir(parents=True)
    cached = pd.DataFrame({
        "vintage_value": [-0.3, -0.2, -0.1],
    }, index=pd.to_datetime(["1991-03-31", "1991-06-30", "1991-09-30"]))
    cached.to_parquet(cache_path)

    with patch("tradingagents.backtest.historical.fetcher_alfred._call_alfred") as m:
        result = fetch_alfred_vintage_quarterly(
            "CFNAI", date(1991, 1, 1), date(1991, 12, 31),
            cache_dir=tmp_path / "raw" / "fred_alfred",
        )
        m.assert_not_called()
    assert len(result) == 3
    assert result["vintage_value"].iloc[0] == -0.3


def test_fetch_alfred_vintage_fetches_per_quarter(tmp_path: Path) -> None:
    """Cache miss → 각 quarter end 별 ALFRED API call → parquet 저장."""
    def fake_call(series_id, realtime_date):
        # Return vintage value at realtime_date — fake non-revised value
        return -0.5 if realtime_date < date(1991, 6, 30) else -0.3
    with patch(
        "tradingagents.backtest.historical.fetcher_alfred._call_alfred",
        side_effect=fake_call,
    ) as m:
        result = fetch_alfred_vintage_quarterly(
            "CFNAI", date(1991, 3, 31), date(1991, 9, 30),
            cache_dir=tmp_path / "raw" / "fred_alfred",
        )
        assert m.call_count == 3  # 3 quarters: 1991-Q1, Q2, Q3
    assert (tmp_path / "raw" / "fred_alfred" / "CFNAI.parquet").exists()
    assert list(result["vintage_value"]) == [-0.5, -0.5, -0.3]
```

- [ ] **Step 2: 테스트 실행 → fail 확인**

```bash
uv run pytest tests/unit/backtest/historical/test_fetcher_alfred.py -v
```

Expected: ImportError — `fetcher_alfred` 부재.

- [ ] **Step 3: 최소 구현**

`tradingagents/backtest/historical/fetcher_alfred.py`:

```python
"""ALFRED (Archival FRED) vintage-aware fetch — Critical 1.

기존 FRED 의 latest-vintage 가 1991-Q1 CFNAI 의 *2024 년 revised 최종값* 을
반환 → backtest 의 look-ahead bias. ALFRED API 는 realtime_start 시점에 알려져
있던 값을 반환 → point-in-time 정합성.

7 revising series 대상:
- CFNAI: Chicago Fed National Activity Index (monthly)
- NFCI, ANFCI: National Financial Conditions Index (weekly)
- GDPNOW: Atlanta Fed GDPNow (2011+)
- UNRATE: Unemployment rate (Sahm rule input)
- CPIAUCSL: CPI All Items
- PCEPILFE: Core PCE

API: https://api.stlouisfed.org/fred/series/observations
     ?series_id=<id>&realtime_start=<quarter_end>&realtime_end=<quarter_end>
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from tenacity import (
    retry, stop_after_attempt, wait_exponential, retry_if_exception_type,
)

logger = logging.getLogger(__name__)


ALFRED_SERIES: list[str] = [
    "CFNAI", "NFCI", "ANFCI", "GDPNOW",
    "UNRATE", "CPIAUCSL", "PCEPILFE",
]


def _quarter_ends(start: date, end: date) -> list[date]:
    """[start, end] 사이의 분기 말 (Mar 31, Jun 30, Sep 30, Dec 31) 의 list."""
    quarter_ends = []
    year, month = start.year, start.month
    # First quarter end >= start
    target_months = [3, 6, 9, 12]
    while True:
        # find next quarter end >= current
        for tm in target_months:
            if (year, tm) >= (start.year, start.month) or year > start.year:
                day = 31 if tm in (3, 12) else 30
                qe = date(year, tm, day)
                if qe >= start and qe <= end:
                    quarter_ends.append(qe)
                if qe > end:
                    return quarter_ends
        year += 1
        if year > end.year + 1:
            return quarter_ends


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
)
def _call_alfred(series_id: str, realtime_date: date) -> float | None:
    """ALFRED API: 특정 realtime_date 시점의 series 의 최신 vintage value.

    Returns None if no observation available at realtime_date (pre-publish).
    """
    import requests
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        raise RuntimeError("FRED_API_KEY not set")
    # ALFRED API: get all observations as of realtime_date, take latest
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "realtime_start": realtime_date.isoformat(),
        "realtime_end": realtime_date.isoformat(),
        "sort_order": "desc",
        "limit": 1,
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    obs = resp.json().get("observations", [])
    if not obs:
        return None
    val = obs[0].get("value")
    if val in (".", None, ""):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def fetch_alfred_vintage_quarterly(
    series_id: str,
    start: date,
    end: date,
    cache_dir: Path | str,
) -> pd.DataFrame:
    """각 quarter end 시점에 *알려져 있던* 값 (vintage-aware).

    Args:
        series_id: ALFRED series ID (e.g., "CFNAI").
        start, end: date range.
        cache_dir: e.g., `backtest/historical/raw/fred_alfred/`.

    Returns:
        DataFrame indexed by quarter end date, single column "vintage_value".
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{series_id}.parquet"

    if cache_path.exists():
        df = pd.read_parquet(cache_path)
        if not df.empty and df.index.min().date() <= start and df.index.max().date() >= end:
            logger.debug("ALFRED %s: cache hit (%s rows)", series_id, len(df))
            return df.loc[start:end]
        logger.info("ALFRED %s: cache stale, refetching", series_id)

    qs = _quarter_ends(start, end)
    logger.info("ALFRED %s: fetching %s quarter ends", series_id, len(qs))
    records = []
    for qe in qs:
        val = _call_alfred(series_id, qe)
        records.append({"date": qe, "vintage_value": val})
        time.sleep(0.6)  # FRED rate limit ~120/min → safe ~100/min
    df = pd.DataFrame(records).set_index("date")
    df.index = pd.to_datetime(df.index)
    df.to_parquet(cache_path)
    return df
```

- [ ] **Step 4: 테스트 재실행 → pass 확인**

```bash
uv run pytest tests/unit/backtest/historical/test_fetcher_alfred.py -v
```

Expected: 3 tests pass.

### Task 1.3: `fetcher_yfinance.py` — yfinance daily Close + parquet cache

**Files:**
- Create: `tradingagents/backtest/historical/fetcher_yfinance.py`
- Create: `tests/unit/backtest/historical/test_fetcher_yfinance.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/backtest/historical/test_fetcher_yfinance.py`:

```python
"""Unit tests for fetcher_yfinance — daily Close + parquet cache."""
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.backtest.historical.fetcher_yfinance import (
    fetch_yfinance_daily, YFINANCE_TICKERS,
)


def test_yfinance_tickers_include_critical() -> None:
    required = {"^GSPC", "^KS11", "^VIX", "^SKEW",
                "IEF", "TIP", "DJP", "GC=F", "^IRX"}
    assert required.issubset(set(YFINANCE_TICKERS))


def test_fetch_yfinance_daily_uses_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "raw" / "yfinance" / "GSPC.parquet"
    cache_path.parent.mkdir(parents=True)
    cached = pd.Series(
        [400.0, 405.0],
        index=pd.date_range("1991-01-02", periods=2, freq="B"),
        name="^GSPC",
    )
    cached.to_frame("close").to_parquet(cache_path)

    with patch("tradingagents.backtest.historical.fetcher_yfinance._yf_download") as m:
        result = fetch_yfinance_daily(
            "^GSPC", date(1991, 1, 1), date(1991, 1, 3),
            cache_dir=tmp_path / "raw" / "yfinance",
        )
        m.assert_not_called()
    assert len(result) == 2


def test_fetch_yfinance_daily_fetches_on_miss(tmp_path: Path) -> None:
    fake = pd.Series(
        [400.0, 405.0],
        index=pd.date_range("1991-01-02", periods=2, freq="B"),
        name="^GSPC",
    )
    with patch(
        "tradingagents.backtest.historical.fetcher_yfinance._yf_download",
        return_value=fake,
    ):
        result = fetch_yfinance_daily(
            "^GSPC", date(1991, 1, 1), date(1991, 1, 3),
            cache_dir=tmp_path / "raw" / "yfinance",
        )
    assert (tmp_path / "raw" / "yfinance" / "GSPC.parquet").exists()
    assert len(result) == 2
```

- [ ] **Step 2: 테스트 실행 → fail 확인**

```bash
uv run pytest tests/unit/backtest/historical/test_fetcher_yfinance.py -v
```

Expected: ImportError.

- [ ] **Step 3: 최소 구현**

`tradingagents/backtest/historical/fetcher_yfinance.py`:

```python
"""yfinance daily Close fetcher — thin wrapper + parquet cache.

Critical: Windows 한글 path 에서 curl_cffi SSL fail (Issue #20). PR2a 는
Linux 환경에서만 fetch — Windows 는 commit 된 parquet cache 만 read.
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


YFINANCE_TICKERS: list[str] = [
    # Equity
    "^GSPC",      # S&P 500 (1957+)
    "^KS11",      # KOSPI (1996+)
    # Volatility
    "^VIX",       # CBOE VIX (1990+)
    "^SKEW",      # CBOE SKEW (1990+)
    "^VIX9D",     # CBOE 9-day VIX (2011+, optional)
    # Bond ETFs
    "IEF",        # 7-10y UST (2002+)
    "TIP",        # TIPS (2003+)
    # Commodity / FX proxy
    "DJP",        # iPath Commodity (2006+)
    "GC=F",       # Gold futures (2000+)
    # Cash proxy
    "^IRX",       # 3m T-bill yield (1960+)
    # Sector ETFs — F9 sector_dispersion
    "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XLB",
]


def _ticker_to_filename(ticker: str) -> str:
    """Convert ticker for filesystem (^GSPC → GSPC, GC=F → GC_F)."""
    return ticker.replace("^", "").replace("=", "_")


def _yf_download(ticker: str, start: date, end: date) -> pd.Series:
    """yfinance Close, daily. 실패 시 빈 시리즈 반환 (Linux only safe)."""
    import yfinance as yf
    df = yf.download(
        ticker, start=start, end=end + timedelta(days=1),
        auto_adjust=True, progress=False, threads=False,
    )
    if df.empty:
        return pd.Series(dtype=float, name=ticker)
    if isinstance(df.columns, pd.MultiIndex):
        close = df["Close"].iloc[:, 0]
    else:
        close = df["Close"]
    close.index = pd.to_datetime(close.index)
    if close.index.tz is not None:
        close = close.tz_localize(None)
    close.name = ticker
    return close


def fetch_yfinance_daily(
    ticker: str,
    start: date,
    end: date,
    cache_dir: Path | str,
) -> pd.Series:
    """yfinance daily Close with parquet cache."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{_ticker_to_filename(ticker)}.parquet"

    if cache_path.exists():
        df = pd.read_parquet(cache_path)
        series = df["close"]
        series.name = ticker
        if (not series.empty and
                series.index.min().date() <= start and
                series.index.max().date() >= end):
            logger.debug("yfinance %s: cache hit (%s rows)", ticker, len(series))
            return series.loc[start:end]
        logger.info("yfinance %s: cache stale, refetching", ticker)

    series = _yf_download(ticker, start, end)
    series.to_frame("close").to_parquet(cache_path)
    logger.info("yfinance %s: fetched %s rows, cached", ticker, len(series))
    return series
```

- [ ] **Step 4: 테스트 재실행 → pass**

```bash
uv run pytest tests/unit/backtest/historical/test_fetcher_yfinance.py -v
```

Expected: 3 tests pass.

### Task 1.4: `fetcher_pykrx.py` — KOSPI200 PBR/PER + foreign flow + parquet cache

**Files:**
- Create: `tradingagents/backtest/historical/fetcher_pykrx.py`
- Create: `tests/unit/backtest/historical/test_fetcher_pykrx.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/backtest/historical/test_fetcher_pykrx.py`:

```python
"""Unit tests for fetcher_pykrx — KOSPI200 valuation + foreign flow."""
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.backtest.historical.fetcher_pykrx import (
    fetch_kospi200_valuation_monthly,
    fetch_foreign_flow_monthly,
)


def test_fetch_kospi200_valuation_uses_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "raw" / "pykrx" / "kospi200_valuation.parquet"
    cache_path.parent.mkdir(parents=True)
    cached = pd.DataFrame({
        "PBR": [1.1, 1.2],
        "PER": [15.0, 16.0],
        "DIV_YIELD": [2.0, 2.1],
    }, index=pd.to_datetime(["2010-01-31", "2010-02-28"]))
    cached.to_parquet(cache_path)

    with patch("tradingagents.backtest.historical.fetcher_pykrx._pykrx_fundamental_call") as m:
        result = fetch_kospi200_valuation_monthly(
            date(2010, 1, 1), date(2010, 2, 28),
            cache_dir=tmp_path / "raw" / "pykrx",
        )
        m.assert_not_called()
    assert len(result) == 2
    assert "PBR" in result.columns


def test_fetch_foreign_flow_uses_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "raw" / "pykrx" / "foreign_flow.parquet"
    cache_path.parent.mkdir(parents=True)
    cached = pd.DataFrame({
        "net_buy_krw": [100.0, -50.0],
    }, index=pd.to_datetime(["2010-01-31", "2010-02-28"]))
    cached.to_parquet(cache_path)

    with patch("tradingagents.backtest.historical.fetcher_pykrx._pykrx_foreign_call") as m:
        result = fetch_foreign_flow_monthly(
            date(2010, 1, 1), date(2010, 2, 28),
            cache_dir=tmp_path / "raw" / "pykrx",
        )
        m.assert_not_called()
    assert len(result) == 2
```

- [ ] **Step 2: 테스트 실행 → fail**

```bash
uv run pytest tests/unit/backtest/historical/test_fetcher_pykrx.py -v
```

Expected: ImportError.

- [ ] **Step 3: 최소 구현**

`tradingagents/backtest/historical/fetcher_pykrx.py`:

```python
"""pykrx KR market fetcher — KOSPI200 valuation + foreign flow.

Critical: Windows pykrx KOSPI200 API mismatch (Issue #21). Linux only safe.
"""
from __future__ import annotations

import logging
import time
from datetime import date
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


def _pykrx_fundamental_call(target_date: date) -> dict | None:
    """Returns KOSPI200 PBR/PER/DivYield at target_date (last KR business day if holiday)."""
    from pykrx import stock
    date_str = target_date.strftime("%Y%m%d")
    try:
        df = stock.get_index_fundamental(date_str, date_str, "1028")  # 1028 = KOSPI200
        if df.empty:
            return None
        row = df.iloc[0]
        return {
            "PBR": float(row.get("PBR", 0.0)),
            "PER": float(row.get("PER", 0.0)),
            "DIV_YIELD": float(row.get("배당수익률", 0.0)),
        }
    except Exception as e:
        logger.warning("pykrx KOSPI200 fundamental %s failed: %s", date_str, e)
        return None


def fetch_kospi200_valuation_monthly(
    start: date, end: date, cache_dir: Path | str,
) -> pd.DataFrame:
    """Monthly KOSPI200 valuation (PBR / PER / DIV_YIELD).

    Returns DataFrame indexed by month-end (or last business day) with columns
    PBR, PER, DIV_YIELD. Missing month → row 누락 (caller forward-fill 가능).
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / "kospi200_valuation.parquet"

    if cache_path.exists():
        df = pd.read_parquet(cache_path)
        if (not df.empty and df.index.min().date() <= start
                and df.index.max().date() >= end):
            logger.debug("pykrx KOSPI200 valuation: cache hit (%s rows)", len(df))
            return df.loc[start:end]
        logger.info("pykrx KOSPI200 valuation: cache stale, refetching")

    month_ends = pd.date_range(start, end, freq="ME").to_pydatetime()
    records = []
    for me in month_ends:
        # KR business day adjustment — use month-end day; pykrx 가 holiday 면 None
        rec = _pykrx_fundamental_call(me.date())
        if rec is not None:
            records.append({"date": me.date(), **rec})
        time.sleep(0.3)  # pykrx rate limit safety
    df = pd.DataFrame(records)
    if not df.empty:
        df = df.set_index("date")
        df.index = pd.to_datetime(df.index)
    df.to_parquet(cache_path)
    logger.info("pykrx KOSPI200 valuation: fetched %s months", len(df))
    return df


def _pykrx_foreign_call(start: date, end: date) -> pd.DataFrame:
    """Returns pykrx KOSPI foreign net buy daily DataFrame."""
    from tradingagents.dataflows.pykrx_data import fetch_foreign_flow
    return fetch_foreign_flow(start, end, market="KOSPI")


def fetch_foreign_flow_monthly(
    start: date, end: date, cache_dir: Path | str,
) -> pd.DataFrame:
    """Monthly aggregated foreign flow (KOSPI 외국인 순매수).

    Returns DataFrame indexed by month-end with single column net_buy_krw
    (monthly aggregate KRW).
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / "foreign_flow.parquet"

    if cache_path.exists():
        df = pd.read_parquet(cache_path)
        if (not df.empty and df.index.min().date() <= start
                and df.index.max().date() >= end):
            logger.debug("pykrx foreign flow: cache hit")
            return df.loc[start:end]
        logger.info("pykrx foreign flow: cache stale, refetching")

    daily_df = _pykrx_foreign_call(start, end)
    if daily_df.empty:
        logger.warning("pykrx foreign flow returned empty for %s-%s", start, end)
        out = pd.DataFrame(columns=["net_buy_krw"])
        out.to_parquet(cache_path)
        return out
    # Aggregate to monthly — sum of daily net buy
    net_col = daily_df.columns[0]  # adjusted per pykrx_data return shape
    monthly = daily_df[net_col].resample("ME").sum()
    out = monthly.to_frame("net_buy_krw")
    out.to_parquet(cache_path)
    logger.info("pykrx foreign flow: fetched %s months", len(out))
    return out
```

- [ ] **Step 4: 테스트 재실행 → pass**

```bash
uv run pytest tests/unit/backtest/historical/test_fetcher_pykrx.py -v
```

Expected: 2 tests pass.

### Task 1.5: Pre-commit regression + commit

- [ ] **Step 1: 전체 regression test**

```bash
uv run pytest tests/unit/ -q 2>&1 | tail -3
uv run pytest tests/integration/ -q 2>&1 | tail -3
```

Expected: PR1 baseline + 신규 ~12 unit test (3 fred + 3 alfred + 3 yfinance + 2 pykrx) — 0 new failure.

- [ ] **Step 2: `regression_log.md` 의 "## Post-C1" section 채움**

- [ ] **Step 3: commit**

```bash
git add tradingagents/backtest/historical/ tests/unit/backtest/historical/
git add artifacts/<run-date>/regression_log.md
git commit -m "$(cat <<'EOF'
feat(backtest): historical fetcher infrastructure (FRED + ALFRED + yfinance + pykrx) (C1)

PR2a 의 historical data fetch infrastructure. 4 개 fetcher + parquet cache
+ unit tests (mocked external API).

- fetcher_fred.py: 기존 dataflows.fred.fetch_fred_series 의 thin wrapper +
  per-series parquet cache (latest-vintage, daily/monthly).
- fetcher_alfred.py: ALFRED API vintage-aware fetch (Critical 1) for 7
  revising series (CFNAI, NFCI, ANFCI, GDPNOW, UNRATE, CPIAUCSL,
  PCEPILFE). 각 quarter end 시점의 vintage value.
- fetcher_yfinance.py: yfinance daily Close + parquet cache. Linux only
  (Issue #20 — Windows curl_cffi SSL fail).
- fetcher_pykrx.py: KOSPI200 monthly PBR/PER/DivYield + KOSPI foreign flow
  monthly aggregate. Linux only (Issue #21 — pykrx API mismatch).
- 모든 fetcher 가 parquet cache hit-first / miss-then-fetch + retry.

Unit tests: cache hit/miss/refetch — mocked external API. 12 tests.

신규 file:
- tradingagents/backtest/historical/__init__.py
- tradingagents/backtest/historical/fetcher_{fred,alfred,yfinance,pykrx}.py
- tests/unit/backtest/historical/test_fetcher_*.py

Pre-existing fail: 3 unit + 18 integ — 동일 유지.

EOF
)"
```

---

## Task 2: Quarterly Aggregation (C2)

`aggregate.py` 는 raw daily/monthly fetch → 135Q quarterly indicator panel + derived. Output: 단일 DataFrame indexed by quarter end, ~40 column.

### Task 2.1: `aggregate.py` 핵심 logic

**Files:**
- Create: `tradingagents/backtest/historical/aggregate.py`
- Create: `tests/unit/backtest/historical/test_aggregate.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/backtest/historical/test_aggregate.py`:

```python
"""Unit tests for aggregate.py — daily/monthly → quarterly panel + derived."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingagents.backtest.historical.aggregate import (
    daily_to_quarter_end_last,
    derive_yoy_pct,
    derive_3mo_annualized,
    derive_rolling_vol_pct,
    derive_yield_spread_bps,
    derive_3mo_avg,
    derive_sector_dispersion,
    derive_vrp_pct,
)


def test_daily_to_quarter_end_last_picks_last_trading_day() -> None:
    """1991-03-31 (Sun) → 1991-03-29 (Fri) close."""
    daily = pd.Series(
        [10.0, 11.0, 12.0],
        index=pd.to_datetime(["1991-03-28", "1991-03-29", "1991-04-01"]),
    )
    q = daily_to_quarter_end_last(daily)
    # quarter 1991-Q1 의 last entry = 1991-03-29 (value 11.0)
    assert q.loc["1991-03-31"] == 11.0  # resampled to quarter end label


def test_derive_yoy_pct_basic() -> None:
    monthly = pd.Series(
        np.arange(1, 25, dtype=float),  # 1, 2, ..., 24 over 24 months
        index=pd.date_range("1990-01-31", periods=24, freq="ME"),
    )
    yoy = derive_yoy_pct(monthly)
    # 1991-01 의 yoy = (13-1)/1 × 100 = 1200%
    assert yoy.loc["1991-01-31"] == pytest.approx(1200.0)


def test_derive_3mo_annualized_basic() -> None:
    monthly = pd.Series(
        [100.0, 101.0, 102.0, 103.0],
        index=pd.date_range("1990-01-31", periods=4, freq="ME"),
    )
    # 3-month change at idx=3: (103-100)/100 = 0.03 over 3 months → annualized 12.55%
    ann = derive_3mo_annualized(monthly)
    expected = ((103.0 / 100.0) ** 4 - 1) * 100
    assert ann.iloc[-1] == pytest.approx(expected, rel=1e-3)


def test_derive_rolling_vol_pct_annualized() -> None:
    """daily returns std × sqrt(252) × 100."""
    # Constant series → 0 vol
    flat = pd.Series([100.0] * 100, index=pd.date_range("1990-01-01", periods=100, freq="B"))
    vol = derive_rolling_vol_pct(flat, window=60)
    assert vol.iloc[-1] == pytest.approx(0.0, abs=1e-9)


def test_derive_yield_spread_bps_handles_nan_gap() -> None:
    """DGS30 의 2002-2006 gap 의 경우 spread = NaN."""
    s30 = pd.Series(
        [3.0, np.nan, 4.0],
        index=pd.to_datetime(["2001-12-31", "2003-12-31", "2007-12-31"]),
    )
    s5 = pd.Series(
        [2.5, 2.7, 3.5],
        index=pd.to_datetime(["2001-12-31", "2003-12-31", "2007-12-31"]),
    )
    spread = derive_yield_spread_bps(s30, s5)
    assert spread.iloc[0] == pytest.approx(50.0)  # 300-250 bps
    assert pd.isna(spread.iloc[1])
    assert spread.iloc[2] == pytest.approx(50.0)


def test_derive_3mo_avg() -> None:
    monthly = pd.Series(
        [1.0, 2.0, 3.0, 4.0],
        index=pd.date_range("1990-01-31", periods=4, freq="ME"),
    )
    avg = derive_3mo_avg(monthly, window=3)
    assert avg.iloc[-1] == pytest.approx(3.0)  # mean of 2,3,4


def test_derive_sector_dispersion_with_partial_sectors() -> None:
    """9 sector ETF daily Close → quarterly std of 60d returns dispersion."""
    sectors = {
        "XLE": pd.Series([100.0] * 100, index=pd.date_range("2010-01-04", periods=100, freq="B")),
        "XLF": pd.Series(np.linspace(100, 110, 100), index=pd.date_range("2010-01-04", periods=100, freq="B")),
    }
    disp = derive_sector_dispersion(sectors, window=60)
    # constant XLE 의 60d return = 0; growing XLF 의 60d return > 0 → std > 0
    assert disp.iloc[-1] > 0


def test_derive_vrp_pct_basic() -> None:
    """VRP = (VIX/100)^2 - realized_vol_60d^2, in % units."""
    vix = pd.Series([20.0, 25.0], index=pd.date_range("2010-01-01", periods=2, freq="QE"))
    rv60 = pd.Series([15.0, 18.0], index=pd.date_range("2010-01-01", periods=2, freq="QE"))
    vrp = derive_vrp_pct(vix, rv60)
    # (0.20)^2 - (0.15)^2 = 0.0175 → 1.75 (% squared, treated as % units)
    assert vrp.iloc[0] == pytest.approx(0.04 - 0.0225, rel=1e-3)
```

- [ ] **Step 2: 테스트 실행 → fail**

```bash
uv run pytest tests/unit/backtest/historical/test_aggregate.py -v
```

Expected: ImportError.

- [ ] **Step 3: 최소 구현**

`tradingagents/backtest/historical/aggregate.py`:

```python
"""Quarterly aggregation + derived computations.

Input: raw daily/monthly fetched series from fetcher_{fred,yfinance,pykrx,alfred}.
Output: quarterly indicator panel (135 rows × ~40 columns) indexed by quarter end.

Derived computations:
- YoY % (12-month difference / 12-month prior, × 100)
- 3-mo annualized % ((Pt/Pt-3)^4 - 1) × 100
- 60d realized vol % (annualized std × √252 × 100)
- Yield spread bps ((s_long - s_short) × 100, NaN if either NaN)
- 3-mo MA
- Sector dispersion (std of 60d returns across N sector ETFs)
- VRP % ((VIX/100)^2 - rv60^2, in % squared units)
"""
from __future__ import annotations

import logging
from typing import Mapping

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def daily_to_quarter_end_last(daily: pd.Series) -> pd.Series:
    """Daily → quarter end last value (last trading day in quarter)."""
    if daily.empty:
        return daily
    return daily.resample("QE").last()


def monthly_to_quarter_end_last(monthly: pd.Series) -> pd.Series:
    """Monthly → quarter end last value."""
    if monthly.empty:
        return monthly
    return monthly.resample("QE").last()


def derive_yoy_pct(monthly_or_quarterly: pd.Series, lag: int = 12) -> pd.Series:
    """YoY %: (Pt - Pt-lag) / Pt-lag × 100. lag=12 for monthly YoY."""
    if monthly_or_quarterly.empty:
        return monthly_or_quarterly
    return monthly_or_quarterly.pct_change(periods=lag) * 100


def derive_3mo_annualized(monthly: pd.Series) -> pd.Series:
    """3-month annualized %: ((Pt/Pt-3)^4 - 1) × 100."""
    if monthly.empty:
        return monthly
    ratio = monthly / monthly.shift(3)
    return (ratio ** 4 - 1) * 100


def derive_rolling_vol_pct(daily_close: pd.Series, window: int = 60) -> pd.Series:
    """Daily close → 60d rolling std of daily returns × √252 × 100 (% annualized)."""
    if daily_close.empty:
        return daily_close
    returns = daily_close.pct_change()
    return returns.rolling(window=window).std() * np.sqrt(252) * 100


def derive_yield_spread_bps(series_long: pd.Series, series_short: pd.Series) -> pd.Series:
    """(s_long - s_short) × 100. NaN propagates."""
    if series_long.empty or series_short.empty:
        return pd.Series(dtype=float)
    aligned = pd.concat([series_long, series_short], axis=1, keys=["long", "short"])
    return (aligned["long"] - aligned["short"]) * 100


def derive_3mo_avg(monthly: pd.Series, window: int = 3) -> pd.Series:
    """Rolling 3-month mean. NaN-aware."""
    if monthly.empty:
        return monthly
    return monthly.rolling(window=window, min_periods=1).mean()


def derive_sector_dispersion(
    sector_daily_closes: Mapping[str, pd.Series],
    window: int = 60,
) -> pd.Series:
    """Across N sector ETFs, std of trailing 60d return distribution.

    Returns quarterly series of dispersion (std of {60d return per sector}).
    """
    if not sector_daily_closes:
        return pd.Series(dtype=float)
    # 60d returns per sector
    returns_60d = {
        name: close.pct_change(window) for name, close in sector_daily_closes.items()
        if not close.empty
    }
    if not returns_60d:
        return pd.Series(dtype=float)
    df = pd.DataFrame(returns_60d)
    dispersion_daily = df.std(axis=1)
    return dispersion_daily.resample("QE").last()


def derive_vrp_pct(vix_qe: pd.Series, realized_vol_60d_qe: pd.Series) -> pd.Series:
    """VRP = (VIX/100)^2 - (rv60d/100)^2 (in fraction squared, % units)."""
    if vix_qe.empty or realized_vol_60d_qe.empty:
        return pd.Series(dtype=float)
    df = pd.concat([vix_qe, realized_vol_60d_qe], axis=1, keys=["vix", "rv"])
    return (df["vix"] / 100) ** 2 - (df["rv"] / 100) ** 2


def derive_move_proxy_pct(dgs10_daily: pd.Series, window: int = 60) -> pd.Series:
    """MOVE proxy: 10y yield 의 60d realized vol of *daily changes* × √252 × 100.

    Pure proxy — actual MOVE (Treasury option vol) 와 ~70% correlation.
    """
    if dgs10_daily.empty:
        return dgs10_daily
    daily_changes = dgs10_daily.diff()
    return daily_changes.rolling(window=window).std() * np.sqrt(252) * 100
```

- [ ] **Step 4: 테스트 재실행 → pass**

```bash
uv run pytest tests/unit/backtest/historical/test_aggregate.py -v
```

Expected: 8 tests pass.

### Task 2.2: `assemble_quarterly_panel` — end-to-end aggregation

- [ ] **Step 1: 실패 테스트 추가**

`tests/unit/backtest/historical/test_aggregate.py` 에 추가:

```python
def test_assemble_quarterly_panel_basic_structure(tmp_path):
    """Mocked raw fetch → quarterly panel with expected columns."""
    from tradingagents.backtest.historical.aggregate import assemble_quarterly_panel

    # Create minimal mocked raw cache
    raw_dir = tmp_path / "raw"
    fred_dir = raw_dir / "fred"
    fred_dir.mkdir(parents=True)
    # Stub DGS10 (daily)
    dgs10 = pd.Series(
        np.linspace(2.0, 3.0, 100),
        index=pd.date_range("1991-01-01", periods=100, freq="B"),
    )
    dgs10.to_frame("value").to_parquet(fred_dir / "DGS10.parquet")
    # ... (test fully populates DGS2, DGS5, DGS30, CPIAUCSL, etc. — abbreviated for brevity) ...

    # Run aggregation with limited subset (function 은 graceful on missing series)
    panel = assemble_quarterly_panel(
        start=date(1991, 1, 1), end=date(1991, 6, 30),
        raw_dir=raw_dir,
    )
    assert isinstance(panel, pd.DataFrame)
    assert panel.index.name == "quarter_end"
    # 빈 panel 도 columns 구조는 유지
    assert "dgs10_pct" in panel.columns
```

- [ ] **Step 2: 구현 추가 (`assemble_quarterly_panel` 함수)**

`tradingagents/backtest/historical/aggregate.py` 의 끝에 추가:

```python
def assemble_quarterly_panel(
    start: date, end: date, raw_dir: Path | str,
) -> pd.DataFrame:
    """End-to-end: raw fetch directories → quarterly indicator panel.

    Reads pre-fetched parquet from `raw_dir/{fred,fred_alfred,yfinance,pykrx}/`.
    Returns DataFrame indexed by quarter_end with ~40 columns.

    Missing series (e.g., pre-availability era) → NaN column / partial coverage.

    Columns (spec section 3.2):
    - dgs10_pct, dgs2_pct, dgs5_pct, dgs30_pct (yield curve)
    - spread_10y_2y_bps, spread_30y_5y_bps (derived)
    - cpi_yoy, core_cpi_yoy, pce_yoy, core_pce_yoy (vintage-aware where possible)
    - cpi_3mo_ann (momentum)
    - breakeven_5y5y, michigan_1y (inflation expectations)
    - real_yield_10y (DFII10)
    - cfnai, cfnai_3m_avg, nfci, anfci, gdp_nowcast (ALFRED vintage)
    - unrate (ALFRED), sahm_rule_triggered (derived: latest unrate vs 12m min)
    - baa_aaa_bps, baa_10y_bps (credit)
    - usdkrw, dxy_dtwexm (FX)
    - kr_base_rate, foreign_flow_z (KR)
    - vix, skew, realized_vol_60d_spx, move_proxy, vrp_pct
    - sector_dispersion (9-sector std)
    - kospi200_pbr, kospi200_per, kospi200_div_yield
    - shiller_cape (static csv)
    - usrec (recession dummy)
    """
    from pathlib import Path
    raw_dir = Path(raw_dir)
    cols: dict[str, pd.Series] = {}

    # Helper: load parquet if exists, else empty
    def _load_fred(name: str) -> pd.Series:
        path = raw_dir / "fred" / f"{name}.parquet"
        if not path.exists():
            return pd.Series(dtype=float)
        df = pd.read_parquet(path)
        return df["value"]

    def _load_alfred(name: str) -> pd.DataFrame:
        path = raw_dir / "fred_alfred" / f"{name}.parquet"
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path)

    def _load_yfinance(name: str) -> pd.Series:
        path = raw_dir / "yfinance" / f"{name.replace('^', '').replace('=', '_')}.parquet"
        if not path.exists():
            return pd.Series(dtype=float)
        df = pd.read_parquet(path)
        return df["close"]

    # Yield curve daily → quarter end last
    dgs2 = daily_to_quarter_end_last(_load_fred("DGS2"))
    dgs5 = daily_to_quarter_end_last(_load_fred("DGS5"))
    dgs10 = daily_to_quarter_end_last(_load_fred("DGS10"))
    dgs30 = daily_to_quarter_end_last(_load_fred("DGS30"))
    cols["dgs2_pct"] = dgs2
    cols["dgs5_pct"] = dgs5
    cols["dgs10_pct"] = dgs10
    cols["dgs30_pct"] = dgs30
    cols["spread_10y_2y_bps"] = derive_yield_spread_bps(dgs10, dgs2)
    cols["spread_30y_5y_bps"] = derive_yield_spread_bps(dgs30, dgs5)

    # Inflation — latest (CPI 의 vintage 는 ALFRED 로 cross-check)
    cpi_monthly = _load_fred("CPIAUCSL")
    core_cpi_monthly = _load_fred("CPILFESL")
    pce_monthly = _load_fred("PCEPI")
    core_pce_monthly = _load_fred("PCEPILFE")
    cols["cpi_yoy"] = monthly_to_quarter_end_last(derive_yoy_pct(cpi_monthly))
    cols["core_cpi_yoy"] = monthly_to_quarter_end_last(derive_yoy_pct(core_cpi_monthly))
    cols["pce_yoy"] = monthly_to_quarter_end_last(derive_yoy_pct(pce_monthly))
    cols["core_pce_yoy"] = monthly_to_quarter_end_last(derive_yoy_pct(core_pce_monthly))
    cols["cpi_3mo_ann"] = monthly_to_quarter_end_last(derive_3mo_annualized(cpi_monthly))

    # Inflation expectations
    cols["breakeven_5y5y"] = daily_to_quarter_end_last(_load_fred("T5YIFR"))
    cols["michigan_1y"] = monthly_to_quarter_end_last(_load_fred("MICH"))

    # Real yield
    cols["real_yield_10y_pct"] = daily_to_quarter_end_last(_load_fred("DFII10"))

    # ALFRED vintage — CFNAI / NFCI / ANFCI / GDPNOW / UNRATE / CPI / Core PCE
    cfnai_df = _load_alfred("CFNAI")
    cols["cfnai"] = cfnai_df["vintage_value"] if not cfnai_df.empty else pd.Series(dtype=float)
    # CFNAI 3m avg requires monthly CFNAI history — for simplicity, use rolling on vintage quarterly
    if not cfnai_df.empty:
        cols["cfnai_3m_avg"] = cfnai_df["vintage_value"].rolling(window=3, min_periods=1).mean()
    else:
        cols["cfnai_3m_avg"] = pd.Series(dtype=float)
    nfci_df = _load_alfred("NFCI")
    cols["nfci"] = nfci_df["vintage_value"] if not nfci_df.empty else pd.Series(dtype=float)
    anfci_df = _load_alfred("ANFCI")
    cols["anfci"] = anfci_df["vintage_value"] if not anfci_df.empty else pd.Series(dtype=float)
    gdpnow_df = _load_alfred("GDPNOW")
    cols["gdp_nowcast"] = gdpnow_df["vintage_value"] if not gdpnow_df.empty else pd.Series(dtype=float)
    unrate_df = _load_alfred("UNRATE")
    cols["unrate"] = unrate_df["vintage_value"] if not unrate_df.empty else pd.Series(dtype=float)
    # Sahm rule trigger: 3m-avg unrate >= 12m min + 0.5
    if not unrate_df.empty:
        u = unrate_df["vintage_value"]
        u_3m = u.rolling(window=3, min_periods=1).mean()
        u_12m_min = u.rolling(window=12, min_periods=1).min()
        cols["sahm_rule_triggered"] = (u_3m >= u_12m_min + 0.5).astype(float)

    # Credit
    baa = _load_fred("BAA")
    aaa = _load_fred("AAA")
    if not baa.empty and not aaa.empty:
        cols["baa_aaa_bps"] = monthly_to_quarter_end_last((baa - aaa) * 100)
    cols["baa_10y_bps"] = daily_to_quarter_end_last(_load_fred("BAA10Y")) * 100

    # FX
    cols["usdkrw"] = daily_to_quarter_end_last(_load_fred("DEXKOUS"))
    cols["dxy_dtwexm"] = daily_to_quarter_end_last(_load_fred("DTWEXM"))

    # Vol indicators
    vix_daily = _load_fred("VIXCLS")
    cols["vix"] = daily_to_quarter_end_last(vix_daily)
    cols["skew"] = daily_to_quarter_end_last(_load_yfinance("^SKEW"))
    # Realized vol from ^GSPC
    spx_daily = _load_yfinance("^GSPC")
    if not spx_daily.empty:
        cols["realized_vol_60d_spx_pct"] = daily_to_quarter_end_last(
            derive_rolling_vol_pct(spx_daily, window=60),
        )
    # MOVE proxy
    dgs10_daily = _load_fred("DGS10")
    if not dgs10_daily.empty:
        cols["move_proxy_pct"] = daily_to_quarter_end_last(derive_move_proxy_pct(dgs10_daily))
    # VRP
    if not vix_daily.empty and not spx_daily.empty:
        vix_qe = daily_to_quarter_end_last(vix_daily)
        rv60_qe = cols.get("realized_vol_60d_spx_pct", pd.Series(dtype=float))
        cols["vrp_pct"] = derive_vrp_pct(vix_qe, rv60_qe)

    # Sector dispersion
    sector_tickers = ["XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XLB"]
    sector_closes = {t: _load_yfinance(t) for t in sector_tickers}
    sector_closes = {t: s for t, s in sector_closes.items() if not s.empty}
    if sector_closes:
        cols["sector_dispersion"] = derive_sector_dispersion(sector_closes, window=60)

    # KOSPI200 valuation (monthly → quarter end)
    pykrx_val_path = raw_dir / "pykrx" / "kospi200_valuation.parquet"
    if pykrx_val_path.exists():
        val_df = pd.read_parquet(pykrx_val_path)
        cols["kospi200_pbr"] = val_df["PBR"].resample("QE").last()
        cols["kospi200_per"] = val_df["PER"].resample("QE").last()
        cols["kospi200_div_yield"] = val_df["DIV_YIELD"].resample("QE").last()

    # Foreign flow monthly → quarterly z-score (60-quarter rolling)
    ff_path = raw_dir / "pykrx" / "foreign_flow.parquet"
    if ff_path.exists():
        ff_df = pd.read_parquet(ff_path)
        ff_quarterly = ff_df["net_buy_krw"].resample("QE").sum()
        rolling_mean = ff_quarterly.rolling(window=60, min_periods=8).mean()
        rolling_std = ff_quarterly.rolling(window=60, min_periods=8).std()
        # Floor std to 1e-6 to avoid huge z (Issue #22 — F6 baseline sd)
        rolling_std_clamped = rolling_std.where(rolling_std > 1e-6, 1e-6)
        cols["foreign_flow_z"] = (ff_quarterly - rolling_mean) / rolling_std_clamped

    # Shiller CAPE (static csv)
    cape_path = Path(__file__).parent / "shiller_cape_static.csv"
    if cape_path.exists():
        cape_df = pd.read_csv(cape_path, parse_dates=["date"]).set_index("date")
        cols["shiller_cape"] = cape_df["cape"].resample("QE").last()

    # Recession dummy
    cols["usrec"] = monthly_to_quarter_end_last(_load_fred("USREC"))

    # Cash (3m T-bill yield, quarterly avg in %)
    tb3 = _load_fred("TB3MS")
    cols["tb3ms_pct"] = monthly_to_quarter_end_last(tb3)

    # Construct DataFrame on union index, filter to [start, end]
    panel = pd.DataFrame(cols)
    panel.index = pd.to_datetime(panel.index)
    panel = panel[(panel.index >= pd.Timestamp(start)) & (panel.index <= pd.Timestamp(end))]
    panel.index.name = "quarter_end"
    logger.info("assemble_quarterly_panel: %s rows × %s columns", *panel.shape)
    return panel
```

- [ ] **Step 3: 테스트 재실행 → pass**

```bash
uv run pytest tests/unit/backtest/historical/test_aggregate.py -v
```

Expected: 9 tests pass (8 derived + 1 assemble structure).

### Task 2.3: shiller_cape_static.csv 다운로드 + commit

Shiller CAPE 의 historical (1881+ monthly) 는 Robert Shiller 의 site (multpl.com / academic data) 에서 정적 download.

- [ ] **Step 1: Shiller CAPE CSV 준비**

`tradingagents/backtest/historical/shiller_cape_static.csv` 의 schema:

```csv
date,cape
1881-01-31,18.47
1881-02-28,18.94
...
2024-09-30,35.20
```

Source: Robert Shiller 의 [ie_data.xls](http://www.econ.yale.edu/~shiller/data.htm) 에서 "Cyclically Adjusted P/E Ratio" column (CAPE10) 을 csv 로 export. 또는 multpl.com 의 "Shiller PE Ratio" monthly export.

본 commit 에서는 1881-01 ~ 2024-12 monthly CAPE 정적 commit (대략 1700 rows, ~50KB).

- [ ] **Step 2: csv 가 aggregate 의 reference path 와 일치 확인**

```bash
ls -la tradingagents/backtest/historical/shiller_cape_static.csv
head -3 tradingagents/backtest/historical/shiller_cape_static.csv
```

Expected: 파일 존재, header `date,cape` + data rows.

### Task 2.4: Pre-commit regression + commit

- [ ] **Step 1: 전체 regression test**

```bash
uv run pytest tests/unit/ -q 2>&1 | tail -3
uv run pytest tests/integration/ -q 2>&1 | tail -3
```

Expected: pre-existing 3 + 18 fail 유지 + aggregate 9 신규 pass.

- [ ] **Step 2: `regression_log.md` 의 "## Post-C2" entry**

- [ ] **Step 3: commit**

```bash
git add tradingagents/backtest/historical/aggregate.py
git add tradingagents/backtest/historical/shiller_cape_static.csv
git add tests/unit/backtest/historical/test_aggregate.py
git add artifacts/<run-date>/regression_log.md
git commit -m "$(cat <<'EOF'
feat(backtest): quarterly aggregation + derived computations (C2)

C2 — raw daily/monthly fetch → 135Q quarterly indicator panel (~40 col).

- aggregate.py:
  - daily_to_quarter_end_last / monthly_to_quarter_end_last: resampling
  - derive_yoy_pct / derive_3mo_annualized / derive_3mo_avg: inflation momentum
  - derive_rolling_vol_pct: 60d realized vol (annualized, %)
  - derive_yield_spread_bps: spread with NaN propagation (handles DGS30
    2002-2006 gap)
  - derive_sector_dispersion: std of 60d returns across N sector ETFs
  - derive_vrp_pct: VIX² - rv60² (% squared)
  - derive_move_proxy_pct: DGS10 daily-change 60d realized vol (MOVE proxy)
  - assemble_quarterly_panel: end-to-end raw cache → quarterly panel
- shiller_cape_static.csv: Shiller CAPE10 monthly 1881-2024 (~50KB)

Issue #22 (foreign_flow baseline sd) partial mitigation: floor std at 1e-6
in assemble_quarterly_panel's foreign_flow_z computation.

Unit tests: 8 derived computation tests + 1 panel structure test.

EOF
)"
```

---

## Task 3: Stage1 Builder + Bucket Returns (C3)

`stage1_builder.py` 는 date-parameterized minimal-proxy Stage 1 builder. `bucket_returns.py` 는 KRW basis 5-bucket quarterly return.

### Task 3.1: `stage1_builder.py` — date-parameterized builder (Critical 2 의 base)

**Files:**
- Create: `tradingagents/backtest/historical/stage1_builder.py`
- Create: `tests/unit/backtest/historical/test_stage1_builder.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/backtest/historical/test_stage1_builder.py`:

```python
"""Unit tests for stage1_builder — date-parameterized minimal-proxy."""
from datetime import date

import pandas as pd
import pytest

from tradingagents.backtest.historical.stage1_builder import build_historical_stage1
from tradingagents.schemas.reports import (
    MacroReport, RiskReport, TechnicalReport, NewsReport,
)


def _sample_indicators_row(quarter_end: date, overrides: dict = None) -> pd.DataFrame:
    """1-row panel for one quarter, with default values."""
    base = {
        "dgs2_pct": 4.0, "dgs5_pct": 4.2, "dgs10_pct": 4.4, "dgs30_pct": 4.6,
        "spread_10y_2y_bps": 40.0, "spread_30y_5y_bps": 40.0,
        "cpi_yoy": 2.5, "core_cpi_yoy": 2.0,
        "pce_yoy": 2.2, "core_pce_yoy": 2.0,
        "cpi_3mo_ann": 2.5,
        "breakeven_5y5y": 2.3, "michigan_1y": 3.0,
        "real_yield_10y_pct": 0.5,
        "cfnai": 0.0, "cfnai_3m_avg": 0.0,
        "nfci": -0.5, "anfci": -0.5, "gdp_nowcast": 2.0,
        "unrate": 4.0, "sahm_rule_triggered": 0.0,
        "baa_aaa_bps": 80.0, "baa_10y_bps": 200.0,
        "usdkrw": 1250.0, "dxy_dtwexm": 100.0,
        "foreign_flow_z": 0.0,
        "vix": 18.0, "skew": 130.0,
        "realized_vol_60d_spx_pct": 15.0, "move_proxy_pct": 80.0,
        "vrp_pct": 0.01, "sector_dispersion": 0.02,
        "kospi200_pbr": 1.0, "kospi200_per": 14.0, "kospi200_div_yield": 2.0,
        "shiller_cape": 25.0,
        "usrec": 0.0,
        "tb3ms_pct": 4.0,
    }
    if overrides:
        base.update(overrides)
    return pd.DataFrame([base], index=pd.to_datetime([quarter_end]))


def test_build_historical_stage1_returns_4_reports() -> None:
    """본 builder 는 4-tuple (macro, risk, tech, news) 반환."""
    panel = _sample_indicators_row(date(2010, 3, 31))
    state = build_historical_stage1(date(2010, 3, 31), panel)
    assert isinstance(state, dict)
    assert isinstance(state["macro_report"], MacroReport)
    assert isinstance(state["risk_report"], RiskReport)
    assert isinstance(state["technical_report"], TechnicalReport)
    assert isinstance(state["news_report"], NewsReport)


def test_build_historical_stage1_populates_yield_curve() -> None:
    panel = _sample_indicators_row(date(2010, 3, 31), {
        "spread_10y_2y_bps": 80.0, "spread_30y_5y_bps": 50.0,
    })
    state = build_historical_stage1(date(2010, 3, 31), panel)
    yc = state["macro_report"].yield_curve
    assert yc.spread_10y_2y_bps == 80.0
    assert yc.spread_30y_5y_bps == 50.0


def test_build_historical_stage1_populates_cfnai() -> None:
    panel = _sample_indicators_row(date(2010, 3, 31), {
        "cfnai": -0.4, "cfnai_3m_avg": -0.3,
    })
    state = build_historical_stage1(date(2010, 3, 31), panel)
    fci = state["macro_report"].financial_conditions
    assert fci.cfnai == -0.4
    assert fci.cfnai_3m_avg == -0.3


def test_build_historical_stage1_news_is_sentinel() -> None:
    """news_report 의 LLM-derived field 는 sentinel (z=0)."""
    panel = _sample_indicators_row(date(2010, 3, 31))
    state = build_historical_stage1(date(2010, 3, 31), panel)
    news = state["news_report"]
    assert news.sentiment_dispersion_z == 0.0
    assert news.release_surprise.surprise_index_30d == 0.0
    assert news.geopolitical_surge == 0


def test_build_historical_stage1_pre_2011_gdp_nowcast_is_zero() -> None:
    """GDPNOW 가 2011+ — pre-2011 era 의 panel 에서 missing → 0 sentinel."""
    panel = _sample_indicators_row(date(2005, 3, 31), {"gdp_nowcast": None})
    state = build_historical_stage1(date(2005, 3, 31), panel)
    gdp = state["macro_report"].gdp_nowcast
    assert gdp.nowcast_pct == 0.0  # sentinel
```

- [ ] **Step 2: 테스트 실행 → fail**

```bash
uv run pytest tests/unit/backtest/historical/test_stage1_builder.py -v
```

Expected: ImportError.

- [ ] **Step 3: 최소 구현 — pydantic schema instantiation**

`tradingagents/backtest/historical/stage1_builder.py`:

```python
"""Date-parameterized minimal-proxy Stage 1 builder.

PR1 C2 의 `_build_real_stage1_baseline()` 패턴 (tests/integration/test_factor_estimators_real_schema.py)
의 date-parameterized 확장. 본 builder 는 quarterly indicator panel 의 한 row 를
받아 4 개 _AnalystReport pydantic instance (MacroReport / RiskReport /
TechnicalReport / NewsReport) 를 반환.

News-derived field 는 영구 sentinel (z=0) — historical LLM 재현 불가.
factor_estimators 가 mode="historical" 로 호출되면 news weight 가 자동 0 +
quant weight renormalize → factor z 가 production scale 매치.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pandas as pd

# Schema imports — PR1 의 enhanced schema
from tradingagents.schemas.reports import (
    MacroReport, RiskReport, TechnicalReport, NewsReport,
)
from tradingagents.schemas.macro import (
    YieldCurveSnapshot, InflationSnapshot, EmploymentSnapshot,
    FinancialConditionsSnapshot, GDPNowSnapshot, InflationExpectationsSnapshot,
    FedPathSnapshot, FXSnapshot, ForeignFlowSnapshot,
    DivergenceScore, RegimeClassification, KRExportSnapshot,
    KRValuationSnapshot,
)
from tradingagents.schemas.risk import (
    VolatilitySnapshot, SpreadSnapshot, RealYieldsSnapshot,
    SkewSnapshot, MoveSnapshot, VixTermSnapshot,
    BreadthSnapshot, BreadthKRSnapshot, FundingSnapshot,
    RealVolSnapshot,
)

logger = logging.getLogger(__name__)


def _g(row: dict, key: str, default: Any = 0.0) -> Any:
    """Safe get from indicator row; None or NaN → default."""
    val = row.get(key, default)
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return default
    return val


def build_historical_stage1(
    as_of: date,
    indicators_q: pd.DataFrame,
) -> dict:
    """Build 4 _AnalystReport pydantic instances for one quarter.

    Args:
        as_of: quarter-end date (e.g., 2010-03-31).
        indicators_q: quarterly panel (from aggregate.assemble_quarterly_panel).

    Returns:
        dict with keys macro_report, risk_report, technical_report, news_report.
    """
    if as_of not in indicators_q.index:
        # Try ts-equivalent lookup
        ts = pd.Timestamp(as_of)
        if ts not in indicators_q.index:
            raise KeyError(f"Quarter {as_of} not in indicators_q")
        as_of_idx = ts
    else:
        as_of_idx = as_of
    row = indicators_q.loc[as_of_idx].to_dict() if hasattr(indicators_q.loc[as_of_idx], "to_dict") else dict(indicators_q.loc[as_of_idx])

    # ---------- MacroReport ----------
    yield_curve = YieldCurveSnapshot(
        spread_10y_2y_bps=float(_g(row, "spread_10y_2y_bps")),
        spread_10y_3m_bps=float(_g(row, "spread_10y_2y_bps")) + 40.0,  # rough proxy if not available
        spread_30y_5y_bps=float(_g(row, "spread_30y_5y_bps")),
        inverted_days_count=0,  # derived elsewhere if needed
        percentile_5y=0.5,
    )

    inflation = InflationSnapshot(
        cpi_yoy=float(_g(row, "cpi_yoy", 2.0)),
        core_cpi_yoy=float(_g(row, "core_cpi_yoy", 2.0)),
        momentum_3mo=float(_g(row, "cpi_3mo_ann", 2.0)),
        momentum_6mo=float(_g(row, "cpi_3mo_ann", 2.0)),
        accelerating=False,
        pce_yoy=float(_g(row, "pce_yoy", 2.0)),
        core_pce_yoy=float(_g(row, "core_pce_yoy", 2.0)),
        pce_momentum_3mo=float(_g(row, "core_pce_yoy", 2.0)),
    )

    employment = EmploymentSnapshot(
        unemployment_rate=float(_g(row, "unrate", 4.0)),
        rate_change_3mo=0.0,
        sahm_rule_triggered=bool(_g(row, "sahm_rule_triggered", 0.0) > 0.5),
        non_farm_payrolls_3mo_avg=150.0,
    )

    fci = FinancialConditionsSnapshot(
        nfci=float(_g(row, "nfci", 0.0)),
        anfci=float(_g(row, "anfci", 0.0)),
        regime="neutral",
        tightening=bool(_g(row, "nfci", 0.0) > 0.3),
        cfnai=float(_g(row, "cfnai", 0.0)),
        cfnai_3m_avg=float(_g(row, "cfnai_3m_avg", 0.0)),
    )

    gdp_nowcast = GDPNowSnapshot(
        nowcast_pct=float(_g(row, "gdp_nowcast", 0.0)),
        change_from_prior=0.0,
    )

    infl_exp = InflationExpectationsSnapshot(
        breakeven_5y5y=float(_g(row, "breakeven_5y5y", 2.3)),
        michigan_1y=float(_g(row, "michigan_1y", 3.0)),
        anchored=True,
        unanchored_direction="none",
    )

    fed_path = FedPathSnapshot(
        current_rate_pct=float(_g(row, "tb3ms_pct", 4.0)),
        implied_2y_rate_pct=float(_g(row, "dgs2_pct", 4.0)),
        path_bps=0.0,
        market_view="hold",
    )

    fx = FXSnapshot(
        usd_krw=float(_g(row, "usdkrw", 1250.0)),
        dxy=float(_g(row, "dxy_dtwexm", 100.0)),
        krw_change_1m_pct=0.0,
        dxy_change_1m_pct=0.0,
        regime="neutral",
    )

    foreign_flow = ForeignFlowSnapshot(
        net_flow_5d=0.0,
        net_flow_1m=0.0,
        net_flow_3m=0.0,
        net_flow_z=float(_g(row, "foreign_flow_z", 0.0)),
        flow_regime="neutral",
    )

    kr_divergence = DivergenceScore(
        us_kr_rate_gap_bps=-100.0,
        us_kr_inflation_gap=0.5,
        score=0.0,
    )

    kr_export = KRExportSnapshot(
        export_yoy_pct=0.0,
        semiconductor_yoy_pct=0.0,
        days_to_release=15,
        flash_available=False,
    )

    regime = RegimeClassification(
        cycle="expansion", tail="benign", inflation="moderate",
    )

    # PR1 C5 의 KRValuationSnapshot (Optional)
    kr_valuation = None
    if not pd.isna(_g(row, "kospi200_pbr", float("nan"))) and _g(row, "kospi200_pbr", 0) > 0:
        kr_valuation = KRValuationSnapshot(
            kospi_pbr=float(_g(row, "kospi200_pbr", 1.0)),
            kospi_per=float(_g(row, "kospi200_per", 14.0)),
            kospi_div_yield=float(_g(row, "kospi200_div_yield", 2.0)),
        )

    macro_report = MacroReport(
        yield_curve=yield_curve,
        inflation=inflation,
        employment=employment,
        financial_conditions=fci,
        gdp_nowcast=gdp_nowcast,
        inflation_expectations=infl_exp,
        fed_path=fed_path,
        fx=fx,
        foreign_flow=foreign_flow,
        kr_divergence=kr_divergence,
        kr_export=kr_export,
        regime=regime,
        kr_valuation=kr_valuation,
        upcoming_events=[],
    )

    # ---------- RiskReport ----------
    vix = VolatilitySnapshot(
        vix=float(_g(row, "vix", 18.0)),
        vix_change_1m=0.0,
        vxn=float(_g(row, "vix", 18.0)) + 2.0,
        regime="normal",
    )
    real_yields = RealYieldsSnapshot(
        ten_y_yield_pct=float(_g(row, "real_yield_10y_pct", 0.5)),
        five_y_yield_pct=float(_g(row, "real_yield_10y_pct", 0.5)) - 0.2,
        change_1m_bps=0.0,
        regime="positive",
    )
    credit_spread_us_hy = SpreadSnapshot(
        spread_bps=float(_g(row, "baa_10y_bps", 200.0)),
        change_1m_bps=0.0,
        percentile_5y=0.5,
        regime="normal",
    )
    skew = SkewSnapshot(
        skew_index=float(_g(row, "skew", 130.0)),
        change_1m_z=0.0,
    )
    move = MoveSnapshot(
        move_index=float(_g(row, "move_proxy_pct", 80.0)),
        change_1m_z=0.0,
    )
    vix_term = VixTermSnapshot(
        front_month=float(_g(row, "vix", 18.0)),
        three_month=float(_g(row, "vix", 18.0)) + 2.0,
        ratio=1.1,
        regime="contango",
    )
    breadth_us = BreadthSnapshot(
        adv_dec_ratio=1.0,
        percent_above_200dma=0.55,
        sector_return_dispersion=float(_g(row, "sector_dispersion", 0.02)),
    )
    breadth_kr = BreadthKRSnapshot(
        kr_adv_dec_ratio=1.0,
        kr_percent_above_200dma=0.55,
    )
    funding = FundingSnapshot(
        sofr=float(_g(row, "tb3ms_pct", 4.0)),
        repo_rate=float(_g(row, "tb3ms_pct", 4.0)) + 0.05,
        spread_to_iorb_bps=5.0,
    )
    real_vol = RealVolSnapshot(
        realized_vol_60d=float(_g(row, "realized_vol_60d_spx_pct", 15.0)),
        realized_vol_20d=float(_g(row, "realized_vol_60d_spx_pct", 15.0)) - 1.0,
        vrp_60d=float(_g(row, "vrp_pct", 0.01)),
    )

    risk_report = RiskReport(
        vix=vix,
        real_yields=real_yields,
        credit_spread_us_hy=credit_spread_us_hy,
        credit_spread_us_ig=SpreadSnapshot(
            spread_bps=float(_g(row, "baa_aaa_bps", 80.0)),
            change_1m_bps=0.0, percentile_5y=0.5, regime="normal",
        ),
        skew=skew,
        move=move,
        vix_term=vix_term,
        breadth=breadth_us,
        breadth_kr=breadth_kr,
        funding=funding,
        real_vol=real_vol,
        regime="normal",
    )

    # ---------- TechnicalReport (mostly sentinel — KR market metrics historical 부재) ----------
    technical_report = TechnicalReport(
        kospi_breadth_z=0.0,
        kr_volatility_regime="normal",
        notes="historical reconstruction — sentinel",
    )

    # ---------- NewsReport (LLM-derived — 영구 sentinel z=0) ----------
    # PR1 의 NewsReport 시그니처에 따라 minimum required field 채움.
    news_report = NewsReport(
        sentiment_dispersion_z=0.0,
        geopolitical_surge=0,
        macro_event_pulse=0.0,
        release_surprise=type("S", (), {"surprise_index_30d": 0.0})(),
        change_1m_z=0.0,
        notes="historical reconstruction — sentinel",
    )

    return {
        "macro_report": macro_report,
        "risk_report": risk_report,
        "technical_report": technical_report,
        "news_report": news_report,
    }
```

**주의**: 위 구현은 spec 의 schema 시그니처 *최선 추정* — PR1 의 실제 schema field 와 100% 일치해야 함. C3 execution 시 `tradingagents/schemas/macro.py`, `tradingagents/schemas/risk.py`, `tradingagents/schemas/reports.py` 를 *직접 읽고* 모든 required field 채우기. 누락 field 는 pydantic ValidationError 로 detect 후 추가.

- [ ] **Step 4: 테스트 재실행 + schema field 조정 cycle**

```bash
uv run pytest tests/unit/backtest/historical/test_stage1_builder.py -v
```

Expected: 5 tests pass. ValidationError 시 schema 읽고 누락 field 추가.

### Task 3.2: `bucket_returns.py` — KRW basis 5-bucket quarterly return

**Files:**
- Create: `tradingagents/backtest/historical/bucket_returns.py`
- Create: `tests/unit/backtest/historical/test_bucket_returns.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/backtest/historical/test_bucket_returns.py`:

```python
"""Unit tests for bucket_returns — KRW basis 5-bucket quarterly."""
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tradingagents.backtest.historical.bucket_returns import (
    compute_bucket_returns_quarterly, BUCKETS_5,
)


def test_buckets_5_are_correct() -> None:
    assert BUCKETS_5 == ("kr_equity", "global_equity", "fx_commodity", "bond", "cash_mmf")


def test_compute_global_equity_krw_translation(tmp_path: Path) -> None:
    """SPX 10% USD return + KRW 10% depreciation → 21% KRW basis return."""
    raw = tmp_path / "raw"
    yf_dir = raw / "yfinance"
    yf_dir.mkdir(parents=True)
    fred_dir = raw / "fred"
    fred_dir.mkdir(parents=True)

    # 2 quarters of SPX: 4000 → 4400 (USD +10%)
    spx = pd.Series(
        [4000.0, 4400.0],
        index=pd.to_datetime(["2010-03-31", "2010-06-30"]),
    )
    spx.to_frame("close").to_parquet(yf_dir / "GSPC.parquet")

    # USDKRW: 1200 → 1320 (KRW depreciates 10%)
    usdkrw = pd.Series(
        [1200.0, 1320.0],
        index=pd.to_datetime(["2010-03-31", "2010-06-30"]),
    )
    usdkrw.to_frame("value").to_parquet(fred_dir / "DEXKOUS.parquet")

    returns = compute_bucket_returns_quarterly(
        start=date(2010, 3, 31), end=date(2010, 6, 30),
        raw_dir=raw, basis="KRW",
    )
    # global_equity quarterly return at 2010-06-30 = (1+0.10)(1+0.10) - 1 = 0.21
    assert returns.loc["2010-06-30", "global_equity"] == pytest.approx(0.21, rel=1e-3)


def test_pre_1996_kr_equity_is_nan(tmp_path: Path) -> None:
    """KOSPI 1996+ only. 1991-1995 의 kr_equity = NaN."""
    raw = tmp_path / "raw"
    (raw / "yfinance").mkdir(parents=True)
    (raw / "fred").mkdir(parents=True)
    # No KOSPI cache file → empty load
    # Provide DGS10 minimal (for yield-derived bond)
    pd.Series([6.0, 6.0], index=pd.to_datetime(["1991-03-31", "1991-06-30"])).to_frame(
        "value").to_parquet(raw / "fred" / "DGS10.parquet")
    pd.Series([700.0, 700.0], index=pd.to_datetime(["1991-03-31", "1991-06-30"])).to_frame(
        "value").to_parquet(raw / "fred" / "DEXKOUS.parquet")

    returns = compute_bucket_returns_quarterly(
        start=date(1991, 3, 31), end=date(1991, 6, 30),
        raw_dir=raw, basis="KRW",
    )
    assert pd.isna(returns.loc["1991-06-30", "kr_equity"])
```

- [ ] **Step 2: 테스트 실행 → fail**

```bash
uv run pytest tests/unit/backtest/historical/test_bucket_returns.py -v
```

Expected: ImportError.

- [ ] **Step 3: 최소 구현**

`tradingagents/backtest/historical/bucket_returns.py`:

```python
"""KRW basis 5-bucket quarterly returns (Critical 4).

5 buckets: kr_equity, global_equity, fx_commodity, bond, cash_mmf.

KRW basis translation: USD 자산 의 return = (1 + USD_return)(1 + USDKRW_change) - 1.

Pre-1996 kr_equity = NaN (KOSPI 부재).
Pre-2002 bond = yield-derived TR (duration × yield change + carry).
Pre-1981 USDKRW = NaN (DEXKOUS 1981+).

기존 tradingagents/backtest/data.py 의 logic 일부 재사용.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


BUCKETS_5: tuple[str, ...] = (
    "kr_equity", "global_equity", "fx_commodity", "bond", "cash_mmf",
)


def _load_yf_close(raw_dir: Path, ticker: str) -> pd.Series:
    fname = ticker.replace("^", "").replace("=", "_") + ".parquet"
    path = raw_dir / "yfinance" / fname
    if not path.exists():
        return pd.Series(dtype=float)
    return pd.read_parquet(path)["close"]


def _load_fred(raw_dir: Path, series_id: str) -> pd.Series:
    path = raw_dir / "fred" / f"{series_id}.parquet"
    if not path.exists():
        return pd.Series(dtype=float)
    return pd.read_parquet(path)["value"]


def _yield_based_bond_quarterly_tr(yields_pct: pd.Series, duration: float = 7.5) -> pd.Series:
    """yield daily → quarterly TR ≈ -duration × Δy + y × dt (annualized carry)."""
    if yields_pct.empty:
        return pd.Series(dtype=float)
    y_dec = yields_pct / 100.0
    monthly_y = y_dec.resample("ME").last()
    delta_y = monthly_y.diff()
    coupon_carry = monthly_y.shift(1) / 12.0
    monthly_tr = -duration * delta_y + coupon_carry
    # Quarterly compound (3-month product)
    quarterly_tr = (1 + monthly_tr).resample("QE").apply(lambda x: x.prod() - 1)
    return quarterly_tr


def compute_bucket_returns_quarterly(
    start: date,
    end: date,
    raw_dir: Path | str,
    basis: Literal["KRW", "USD"] = "KRW",
) -> pd.DataFrame:
    """5-bucket quarterly return matrix, indexed by quarter end.

    KRW basis: USD 자산 의 return × USDKRW change.
    Pre-1996 kr_equity = NaN.
    Pre-2002 bond = yield-derived from DGS10 (duration=7.5).
    """
    raw_dir = Path(raw_dir)

    # Daily Close → quarterly Close → quarterly return
    spx = _load_yf_close(raw_dir, "^GSPC")
    kospi = _load_yf_close(raw_dir, "^KS11")
    ief = _load_yf_close(raw_dir, "IEF")
    djp = _load_yf_close(raw_dir, "DJP")
    gold = _load_yf_close(raw_dir, "GC=F")
    irx = _load_yf_close(raw_dir, "^IRX")  # 3m T-bill yield %

    spx_q = spx.resample("QE").last().pct_change()
    kospi_q = kospi.resample("QE").last().pct_change() if not kospi.empty else pd.Series(dtype=float)

    # Bond: IEF ETF (2002+) + yield-derived (pre-2002)
    ief_q = ief.resample("QE").last().pct_change() if not ief.empty else pd.Series(dtype=float)
    dgs10 = _load_fred(raw_dir, "DGS10")
    bond_q_yld = _yield_based_bond_quarterly_tr(dgs10)
    bond_q = ief_q.combine_first(bond_q_yld) if not ief_q.empty else bond_q_yld

    # fx_commodity: DJP (2006+) ∪ gold (1971+ via GC=F + Shiller? — here just GC=F 2000+)
    djp_q = djp.resample("QE").last().pct_change() if not djp.empty else pd.Series(dtype=float)
    gold_q = gold.resample("QE").last().pct_change() if not gold.empty else pd.Series(dtype=float)
    fx_q = djp_q.combine_first(gold_q) if not djp_q.empty else gold_q

    # cash_mmf: ^IRX is daily yield % → quarterly carry approx = mean(yield)/4
    if not irx.empty:
        irx_q_mean = (irx / 100.0).resample("QE").mean()
        cash_q = irx_q_mean / 4.0  # quarterly carry (approximation)
    else:
        # Fallback: TB3MS monthly
        tb3 = _load_fred(raw_dir, "TB3MS")
        if not tb3.empty:
            tb3_q = (tb3 / 100.0).resample("QE").mean()
            cash_q = tb3_q / 4.0
        else:
            cash_q = pd.Series(dtype=float)

    # KRW basis translation: USDKRW change
    if basis == "KRW":
        usdkrw = _load_fred(raw_dir, "DEXKOUS")
        usdkrw_q = usdkrw.resample("QE").last() if not usdkrw.empty else pd.Series(dtype=float)
        usdkrw_chg = usdkrw_q.pct_change()

        def _krw_translate(usd_q: pd.Series) -> pd.Series:
            if usd_q.empty or usdkrw_chg.empty:
                return usd_q
            aligned = pd.concat([usd_q, usdkrw_chg], axis=1, keys=["r", "fx"]).dropna()
            return (1 + aligned["r"]) * (1 + aligned["fx"]) - 1

        spx_q = _krw_translate(spx_q)
        bond_q = _krw_translate(bond_q)
        fx_q = _krw_translate(fx_q)
        cash_q = _krw_translate(cash_q)
        # kr_equity (KOSPI) is already KRW — no translation

    # Construct DataFrame
    df = pd.DataFrame({
        "kr_equity": kospi_q,
        "global_equity": spx_q,
        "fx_commodity": fx_q,
        "bond": bond_q,
        "cash_mmf": cash_q,
    })
    df.index = pd.to_datetime(df.index)
    df = df[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
    df.index.name = "quarter_end"
    logger.info("compute_bucket_returns_quarterly: %s rows", len(df))
    return df
```

- [ ] **Step 4: 테스트 재실행 → pass**

```bash
uv run pytest tests/unit/backtest/historical/test_bucket_returns.py -v
```

Expected: 3 tests pass.

### Task 3.3: Pre-commit regression + commit

- [ ] **Step 1: 전체 regression test**

```bash
uv run pytest tests/unit/ -q 2>&1 | tail -3
uv run pytest tests/integration/ -q 2>&1 | tail -3
```

Expected: pre-existing 유지 + 8 신규 (5 builder + 3 bucket_returns) pass.

- [ ] **Step 2: `regression_log.md` 의 "## Post-C3" entry**

- [ ] **Step 3: commit**

```bash
git add tradingagents/backtest/historical/stage1_builder.py
git add tradingagents/backtest/historical/bucket_returns.py
git add tests/unit/backtest/historical/test_stage1_builder.py
git add tests/unit/backtest/historical/test_bucket_returns.py
git add artifacts/<run-date>/regression_log.md
git commit -m "$(cat <<'EOF'
feat(backtest): historical Stage 1 builder + KRW-basis bucket returns (C3)

C3 — date-parameterized minimal-proxy Stage 1 builder (Critical 2 의 base)
+ 5-bucket KRW-basis quarterly return (Critical 4).

- stage1_builder.py:
  - build_historical_stage1(as_of, indicators_q): quarterly panel row →
    4-tuple of pydantic _AnalystReport (MacroReport / RiskReport /
    TechnicalReport / NewsReport).
  - 모든 schema required field 채움 (CFNAI / NFCI / breakeven_5y5y /
    real_yield / VIX / SKEW / MOVE proxy / VRP / KOSPI200 valuation).
  - News-derived field 영구 sentinel (z=0) — historical LLM 재현 불가.
  - Pre-availability era field = sentinel (0.0) per spec 3.4.
- bucket_returns.py:
  - compute_bucket_returns_quarterly(start, end, raw_dir, basis):
    5-bucket × N-quarter return matrix.
  - KRW basis translation: USD 자산 × USDKRW change.
  - Pre-1996 kr_equity = NaN (KOSPI 부재).
  - Pre-2002 bond = yield-derived TR from DGS10 (duration=7.5).
  - basis="USD" 옵션도 지원 (PR2b sensitivity).

Unit tests: 5 builder + 3 bucket_returns (KRW translation, pre-1996, basic).

다음 commit (C4) 전 grill-me #1: fetcher API + sentinel policy + KRW basis
처리 review.

EOF
)"
```

### Task 3.4: [grill-me #1 marker]

본 시점에서 **executing-plans 가 일시 멈추고 grill-me #1 수행**.

Grill 대상:
1. **Fetcher API + retry/timeout** — production 의존도. ALFRED rate limit 8 분 fetch 의 retry 적정성. Cache invalidation 정책.
2. **Stage1 builder sentinel policy** — pre-2003 era 의 None vs 0.0 결정 일관성. 각 schema field 의 default 가 spec 3.4 와 일치하는지.
3. **Bucket returns KRW basis** — pre-1996 kr_equity NaN 처리 가 calibration 의 sample 에 미치는 영향. compute_sharpe / simulate_portfolio_returns 가 NaN bucket weight 처리 안전한지.

Grill 결과 → `artifacts/<run-date>/decisions.md` 의 "grill-me #1" section 에 기록.

---

## Task 4: factor_estimators `mode="historical"` Flag (C4)

Critical 2 — `compute_all_factors` 에 `mode` parameter 추가. `mode="historical"` 일 때 news-derived component weight 를 0 으로 + 나머지 quant weight 만으로 renormalize → factor z magnitude 가 production scale 매치.

Backward-compat 보장: default `mode="production"` → PR1 의 모든 production behavior 100% identical.

### Task 4.1: NEWS_DERIVED_COMPONENTS 식별 + 실패 테스트

**Files:**
- Modify: `tradingagents/skills/research/factor_estimators.py`
- Create: `tests/unit/skills/research/test_factor_estimators_historical_mode.py`

- [ ] **Step 1: NEWS_DERIVED_COMPONENTS 식별**

`factor_estimators.py` 에서 *news-derived* component 식별. 각 F1-F9 의 `components_raw` dict 에서 *news_report 출처* component 의 key 를 모두 grep:

```bash
grep -nE "news_report" tradingagents/skills/research/factor_estimators.py | head -20
```

Expected output 으로 news 출처 components: `release_surprise`, `sentiment_dispersion`, `geopolitical_surge`, `macro_event_pulse`, `news_change_1m` 등. 정확한 key 는 `factor_estimators.py` 의 각 compute_F* 안의 `_safe_get(stage1, "news_report", ...)` 패턴 + 그 결과를 components_raw 에 넣을 때 사용한 *key 이름* 으로 확정.

본 plan 작성 시점에 추정되는 NEWS_DERIVED_COMPONENTS:
```python
NEWS_DERIVED_COMPONENTS: Final[frozenset[str]] = frozenset({
    "release_surprise",
    "release_surprise_inflation",
    "sentiment_dispersion",
    "geopolitical_surge",
    "macro_event_pulse",
    "news_change_1m",
})
```

C4 execution 시 실제 components_raw key 와 reconcile.

- [ ] **Step 2: 실패 테스트 작성**

`tests/unit/skills/research/test_factor_estimators_historical_mode.py`:

```python
"""Critical 2 — factor_estimators mode='historical' flag.

Backward-compat 보장:
- mode='production' (default) → PR1 의 100% identical behavior
- mode='historical' → news weight 0 + quant weight renormalize
"""
from datetime import date
from copy import deepcopy

import pytest

from tradingagents.skills.research.factor_estimators import (
    compute_all_factors, NEWS_DERIVED_COMPONENTS,
)
from tests.integration.test_factor_estimators_real_schema import (
    _build_real_stage1_baseline,
)


def test_production_mode_default_matches_no_arg() -> None:
    """default mode = explicit 'production' — backward-compat 보장."""
    state = _build_real_stage1_baseline()
    no_arg = compute_all_factors(state)  # PR1 의 기존 호출
    explicit = compute_all_factors(state, mode="production")
    # FactorScore 의 모든 numeric field 가 동일
    for f in ("growth_surprise", "inflation_surprise", "real_rate",
              "term_premium", "credit_cycle", "krw_regime",
              "equity_vol_regime", "valuation", "liquidity_regime"):
        sa = getattr(no_arg, f)
        sb = getattr(explicit, f)
        assert sa.z_score == pytest.approx(sb.z_score, abs=1e-12), f
        assert sa.confidence == pytest.approx(sb.confidence, abs=1e-12), f


def test_historical_mode_drops_news_components() -> None:
    """historical mode 의 factor z 는 news component 영향 받지 않음."""
    state_base = _build_real_stage1_baseline()
    state_perturbed = deepcopy(state_base)
    # News field 의 큰 perturbation
    state_perturbed["news_report"].sentiment_dispersion_z = 3.0
    state_perturbed["news_report"].geopolitical_surge = 5

    # historical mode: 두 state 의 결과가 (news 영향 영역 안에서) identical
    h_base = compute_all_factors(state_base, mode="historical")
    h_pert = compute_all_factors(state_perturbed, mode="historical")
    # F1 growth_surprise: news_change 가 weight 가지므로 production 에서는 영향 있어야 했음
    # historical 에서는 동일
    assert h_base.growth_surprise.z_score == pytest.approx(
        h_pert.growth_surprise.z_score, abs=1e-12,
    )

    # production mode: 차이 있어야 함 (news 가 weight 가짐)
    p_base = compute_all_factors(state_base, mode="production")
    p_pert = compute_all_factors(state_perturbed, mode="production")
    # 적어도 1 개 factor 에서 차이 — F1 또는 F7 또는 F9
    diff_found = any(
        abs(getattr(p_base, f).z_score - getattr(p_pert, f).z_score) > 1e-6
        for f in ("growth_surprise", "equity_vol_regime", "liquidity_regime")
    )
    assert diff_found, "production mode should reflect news perturbation"


def test_historical_mode_renormalizes_quant_weights() -> None:
    """historical mode 의 confidence 는 quant-only weight sum (≤ 1)."""
    state = _build_real_stage1_baseline()
    hist = compute_all_factors(state, mode="historical")
    # confidence 는 sum of used original weights (pre-renorm).
    # historical mode 에서 news 가 dropped → confidence 는 quant 만의 sum.
    # 0 < confidence ≤ 1
    for f in ("growth_surprise", "inflation_surprise", "real_rate",
              "term_premium", "credit_cycle", "krw_regime",
              "equity_vol_regime", "valuation", "liquidity_regime"):
        score = getattr(hist, f)
        assert 0 < score.confidence <= 1.0, (
            f"{f} confidence {score.confidence} out of (0, 1]"
        )


def test_news_derived_components_set_defined() -> None:
    """NEWS_DERIVED_COMPONENTS module constant 정의 존재."""
    assert isinstance(NEWS_DERIVED_COMPONENTS, (set, frozenset))
    assert len(NEWS_DERIVED_COMPONENTS) >= 4  # 적어도 release_surprise, sentiment_dispersion, geopolitical_surge, macro_event_pulse
```

- [ ] **Step 3: 테스트 실행 → fail**

```bash
uv run pytest tests/unit/skills/research/test_factor_estimators_historical_mode.py -v
```

Expected: ImportError on NEWS_DERIVED_COMPONENTS, 또는 TypeError on mode argument.

- [ ] **Step 4: factor_estimators.py 의 _aggregate 수정**

`tradingagents/skills/research/factor_estimators.py` 의 file top 부근에 추가 (FACTOR/BUCKETS 같은 constant 옆):

```python
# Critical 2 — Historical mode 에서 dropped components.
# 본 set 의 component key 는 각 compute_F* 의 components_raw dict 에 *news_report
# 출처* 로 들어가는 component 의 이름. C4 grill 에서 final list 확정.
NEWS_DERIVED_COMPONENTS: Final[frozenset[str]] = frozenset({
    "release_surprise",
    "release_surprise_inflation",
    "sentiment_dispersion",
    "geopolitical_surge",
    "macro_event_pulse",
    "news_change_1m",
})
```

(execution 시 정확한 component 이름으로 update — grep 결과 기준)

`_aggregate` 의 시그니처 + 로직 수정:

```python
def _aggregate(
    factor_name: str,
    components_raw: dict[str, float | None],
    weights: dict[str, float],
    mode: Literal["production", "historical"] = "production",
) -> FactorScore:
    """Convert raw component values → final FactorScore.

    Args:
        mode: "production" (default, PR1 behavior) or "historical".
              In historical mode, NEWS_DERIVED_COMPONENTS weights are
              zeroed before further processing, then the remaining quant
              weights renormalize naturally via step 4.
    """
    # Critical 2 — historical mode 에서 news component drop.
    if mode == "historical":
        weights = {
            k: (0.0 if k in NEWS_DERIVED_COMPONENTS else v)
            for k, v in weights.items()
        }

    # Step 1+2: drop None, look up z-score via baseline.
    component_z: dict[str, float] = {}
    used_original_weights: dict[str, float] = {}
    for name, raw in components_raw.items():
        if raw is None:
            continue
        w = weights.get(name, 0.0)
        if w <= 0.0:
            continue  # mode='historical' 에서 news component 가 여기서 skip
        # ... 나머지 기존 logic 그대로 ...
```

(기존 _aggregate 의 나머지 logic 변경 없음 — Step 3 의 cap, Step 4 의 renorm 가 weights=0 인 component 를 자연스럽게 처리.)

- [ ] **Step 5: 각 compute_F* 와 compute_all_factors 에 mode 시그니처 추가**

`compute_all_factors` 수정:

```python
def compute_all_factors(
    stage1: Any,
    mode: Literal["production", "historical"] = "production",
) -> FactorScores:
    """Compute all 9 factor scores.

    Args:
        mode: "production" (default) — full quant + news.
              "historical" — news weights zeroed (Critical 2).
                              For factor model β calibration on historical
                              data where news LLM-derived field 가 재현 불가.
    """
    return FactorScores(
        growth_surprise=compute_growth_surprise(stage1, mode=mode),
        inflation_surprise=compute_inflation_surprise(stage1, mode=mode),
        real_rate=compute_real_rate(stage1, mode=mode),
        term_premium=compute_term_premium(stage1, mode=mode),
        credit_cycle=compute_credit_cycle(stage1, mode=mode),
        krw_regime=compute_krw_regime(stage1, mode=mode),
        equity_vol_regime=compute_equity_vol_regime(stage1, mode=mode),
        valuation=compute_valuation(stage1, mode=mode),
        liquidity_regime=compute_liquidity_regime(stage1, mode=mode),
    )
```

각 `compute_F*` 함수 (총 9 개) 의 시그니처 변경:

```python
def compute_growth_surprise(
    stage1: Any,
    mode: Literal["production", "historical"] = "production",
) -> FactorScore:
    """..."""
    # ... 기존 _safe_get 로직 ...
    return _aggregate("F1_growth", components_raw, weights, mode=mode)
```

(9 개 compute_F* 함수 동일 패턴으로 mode parameter 추가 + _aggregate 에 mode 전달)

`Literal` import 가 module top 에 있는지 확인:
```python
from typing import Literal  # if not already imported
```

- [ ] **Step 6: 테스트 재실행 → pass**

```bash
uv run pytest tests/unit/skills/research/test_factor_estimators_historical_mode.py -v
```

Expected: 4 tests pass.

### Task 4.2: Pre-commit regression (PR1 production test 100% unchanged)

- [ ] **Step 1: 전체 regression — PR1 production test 검증**

```bash
uv run pytest tests/unit/ -q 2>&1 | tail -3
uv run pytest tests/integration/ -q 2>&1 | tail -3
```

Expected: pre-existing 3 + 18 fail 동일. 신규 4 historical mode test pass. **PR1 의 production test (특히 `tests/integration/test_factor_estimators_real_schema.py`) 0 new failure**.

- [ ] **Step 2: `regression_log.md` 의 "## Post-C4" entry**

특히 PR1 production test 100% PASS 명시.

- [ ] **Step 3: commit**

```bash
git add tradingagents/skills/research/factor_estimators.py
git add tests/unit/skills/research/test_factor_estimators_historical_mode.py
git add artifacts/<run-date>/regression_log.md
git commit -m "$(cat <<'EOF'
feat(stage2): factor_estimators mode='historical' flag (C4, Critical 2)

PR1 의 compute_all_factors 에 backward-compat mode parameter 추가.

- mode='production' (default): PR1 의 100% identical behavior — 기존 호출자
  영향 0. 모든 production unit + integration test 가 0 new failure.
- mode='historical': NEWS_DERIVED_COMPONENTS 의 weight 를 0 으로 마스킹
  → 나머지 quant weight 만으로 step 4 의 renormalize 가 자연스럽게 처리.
  → factor z magnitude 가 production scale 과 동일 → PR2a calibration 의
  결과 가 production 에서 그대로 적용 가능.

NEWS_DERIVED_COMPONENTS module constant 신설 — release_surprise,
sentiment_dispersion, geopolitical_surge, macro_event_pulse 등.

각 compute_F* (9 함수) + compute_all_factors + _aggregate 의 시그니처에
mode parameter 추가 (Literal['production', 'historical'], default='production').

Unit tests (test_factor_estimators_historical_mode.py):
1. test_production_mode_default_matches_no_arg — PR1 의 100% backward
   compat regression
2. test_historical_mode_drops_news_components — news perturbation 이
   historical mode 에 영향 없음
3. test_historical_mode_renormalizes_quant_weights — confidence ∈ (0, 1]
4. test_news_derived_components_set_defined — module constant 존재 검증

Spec: docs/superpowers/specs/2026-05-23-stage2a-calibration-design.md
section 3.6.

EOF
)"
```

---

## Task 5: Historical Factor z + Bucket Returns Generation (C5)

`scripts/generate_historical_factor_z.py` 가 end-to-end pipeline 실행 — 모든 fetcher → aggregate → builder → compute_all_factors(mode='historical') → samples.parquet commit.

### Task 5.1: `generate_historical_factor_z.py` 스크립트

**Files:**
- Create: `scripts/generate_historical_factor_z.py`

- [ ] **Step 1: 스크립트 작성**

`scripts/generate_historical_factor_z.py`:

```python
"""End-to-end historical factor z + bucket returns generation (C5).

Pipeline (Linux only — Issues #20/#21):
1. Fetch all raw series → backtest/historical/raw/
2. Aggregate to quarterly indicator panel
3. For each quarter, build Stage 1 instance
4. Run compute_all_factors(state, mode='historical')
5. Compute bucket returns (KRW basis)
6. Join into HistoricalSample-equivalent records
7. Save to backtest/historical/*.parquet

Usage:
    FRED_API_KEY=... uv run python scripts/generate_historical_factor_z.py \\
        --start 1991-01-01 --end 2024-09-30 \\
        --output-dir backtest/historical
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from tradingagents.backtest.historical.fetcher_fred import (
    fetch_fred_latest, FRED_QUARTERLY_SERIES,
)
from tradingagents.backtest.historical.fetcher_alfred import (
    fetch_alfred_vintage_quarterly, ALFRED_SERIES,
)
from tradingagents.backtest.historical.fetcher_yfinance import (
    fetch_yfinance_daily, YFINANCE_TICKERS,
)
from tradingagents.backtest.historical.fetcher_pykrx import (
    fetch_kospi200_valuation_monthly, fetch_foreign_flow_monthly,
)
from tradingagents.backtest.historical.aggregate import assemble_quarterly_panel
from tradingagents.backtest.historical.stage1_builder import build_historical_stage1
from tradingagents.backtest.historical.bucket_returns import (
    compute_bucket_returns_quarterly, BUCKETS_5,
)
from tradingagents.skills.research.factor_estimators import compute_all_factors

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="1991-01-01")
    ap.add_argument("--end", default="2024-09-30")
    ap.add_argument("--output-dir", default="backtest/historical")
    ap.add_argument("--raw-dir", default="backtest/historical/raw")
    ap.add_argument("--skip-fetch", action="store_true",
                    help="Skip fetch (assume cache present) — faster iteration")
    args = ap.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    # ---- 1. Fetch all raw series ----
    if not args.skip_fetch:
        logger.info("Step 1: fetching raw series (Linux only — Issues #20/#21)")
        for series_id in FRED_QUARTERLY_SERIES:
            try:
                fetch_fred_latest(series_id, start, end, cache_dir=raw_dir / "fred")
            except Exception as e:
                logger.warning("FRED %s fetch failed: %s — continuing", series_id, e)

        for series_id in ALFRED_SERIES:
            try:
                fetch_alfred_vintage_quarterly(
                    series_id, start, end, cache_dir=raw_dir / "fred_alfred",
                )
            except Exception as e:
                logger.warning("ALFRED %s fetch failed: %s — continuing", series_id, e)

        for ticker in YFINANCE_TICKERS:
            try:
                fetch_yfinance_daily(ticker, start, end, cache_dir=raw_dir / "yfinance")
            except Exception as e:
                logger.warning("yfinance %s fetch failed: %s — continuing", ticker, e)

        try:
            fetch_kospi200_valuation_monthly(
                max(start, date(2001, 1, 1)), end, cache_dir=raw_dir / "pykrx",
            )
        except Exception as e:
            logger.warning("pykrx KOSPI200 valuation fetch failed: %s", e)

        try:
            fetch_foreign_flow_monthly(
                max(start, date(2003, 1, 1)), end, cache_dir=raw_dir / "pykrx",
            )
        except Exception as e:
            logger.warning("pykrx foreign flow fetch failed: %s", e)

    # ---- 2. Aggregate to quarterly indicator panel ----
    logger.info("Step 2: assembling quarterly indicator panel")
    panel = assemble_quarterly_panel(start=start, end=end, raw_dir=raw_dir)
    panel_path = output_dir / "quarterly_indicators.parquet"
    panel.to_parquet(panel_path)
    logger.info("Saved %s rows × %s columns to %s", *panel.shape, panel_path)

    # ---- 3. Bucket returns (KRW basis) ----
    logger.info("Step 3: computing bucket returns (KRW basis)")
    bucket_returns = compute_bucket_returns_quarterly(
        start=start, end=end, raw_dir=raw_dir, basis="KRW",
    )
    br_path = output_dir / "bucket_returns.parquet"
    bucket_returns.to_parquet(br_path)
    logger.info("Saved bucket returns %s rows to %s", len(bucket_returns), br_path)

    # ---- 4-5. Per-quarter factor z reconstruction ----
    logger.info("Step 4-5: per-quarter factor z reconstruction (mode='historical')")
    factor_records = []
    confidence_records = []
    for as_of in panel.index:
        as_of_date = as_of.date() if hasattr(as_of, "date") else as_of
        try:
            state = build_historical_stage1(as_of_date, panel)
            scores = compute_all_factors(state, mode="historical")
            factor_records.append({
                "quarter_end": as_of,
                "growth_surprise": scores.growth_surprise.z_score,
                "inflation_surprise": scores.inflation_surprise.z_score,
                "real_rate": scores.real_rate.z_score,
                "term_premium": scores.term_premium.z_score,
                "credit_cycle": scores.credit_cycle.z_score,
                "krw_regime": scores.krw_regime.z_score,
                "equity_vol_regime": scores.equity_vol_regime.z_score,
                "valuation": scores.valuation.z_score,
                "liquidity_regime": scores.liquidity_regime.z_score,
            })
            confidence_records.append({
                "quarter_end": as_of,
                "growth_surprise_conf": scores.growth_surprise.confidence,
                "inflation_surprise_conf": scores.inflation_surprise.confidence,
                "real_rate_conf": scores.real_rate.confidence,
                "term_premium_conf": scores.term_premium.confidence,
                "credit_cycle_conf": scores.credit_cycle.confidence,
                "krw_regime_conf": scores.krw_regime.confidence,
                "equity_vol_regime_conf": scores.equity_vol_regime.confidence,
                "valuation_conf": scores.valuation.confidence,
                "liquidity_regime_conf": scores.liquidity_regime.confidence,
            })
        except Exception as e:
            logger.error("Quarter %s factor z compute failed: %s", as_of_date, e)

    factor_z_df = pd.DataFrame(factor_records).set_index("quarter_end")
    conf_df = pd.DataFrame(confidence_records).set_index("quarter_end")
    combined = factor_z_df.join(conf_df)
    fz_path = output_dir / "factor_z.parquet"
    combined.to_parquet(fz_path)
    logger.info("Saved factor z %s rows × %s columns to %s",
                *combined.shape, fz_path)

    # ---- 6. Samples.parquet — joined factor z + bucket_returns_next ----
    logger.info("Step 6: assembling HistoricalSample equivalents")
    # bucket_returns_next: 각 quarter t 의 next quarter (t+1) 의 bucket return
    bucket_returns_next = bucket_returns.shift(-1)
    samples_df = combined.join(
        bucket_returns_next.rename(columns={b: f"next_{b}" for b in BUCKETS_5}),
        how="inner",
    )
    samples_df = samples_df.dropna(subset=[f"next_{b}" for b in ("global_equity", "bond", "cash_mmf")])
    samples_path = output_dir / "samples.parquet"
    samples_df.to_parquet(samples_path)
    logger.info("Saved samples %s rows × %s columns to %s",
                *samples_df.shape, samples_path)

    # Final summary
    print(json.dumps({
        "panel_rows": int(len(panel)),
        "factor_z_rows": int(len(combined)),
        "bucket_returns_rows": int(len(bucket_returns)),
        "samples_rows": int(len(samples_df)),
        "start": start.isoformat(),
        "end": end.isoformat(),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

### Task 5.2: 실행 — Linux 환경

- [ ] **Step 1: 환경 변수 + 실행**

Linux 환경 또는 CI 에서:

```bash
export FRED_API_KEY="<your-key>"
uv run python scripts/generate_historical_factor_z.py \
    --start 1991-01-01 --end 2024-09-30 \
    --output-dir backtest/historical \
    --raw-dir backtest/historical/raw
```

Expected:
- ~8 분 fetch (ALFRED rate limit) + ~5 분 build + compute
- 최종 stdout JSON:
  ```
  {"panel_rows": 135, "factor_z_rows": 135, "bucket_returns_rows": 135,
   "samples_rows": 130-135, "start": "1991-01-01", "end": "2024-09-30"}
  ```

samples_rows 가 ~130-135 (pre-1996 quarters 의 일부가 bucket return dropna 로 빠질 수 있음).

- [ ] **Step 2: 산출물 sanity check**

```bash
python -c "
import pandas as pd
panel = pd.read_parquet('backtest/historical/quarterly_indicators.parquet')
fz = pd.read_parquet('backtest/historical/factor_z.parquet')
br = pd.read_parquet('backtest/historical/bucket_returns.parquet')
samples = pd.read_parquet('backtest/historical/samples.parquet')
print('panel:', panel.shape)
print('factor_z:', fz.shape)
print('bucket_returns:', br.shape)
print('samples:', samples.shape)
print()
print('factor_z confidence by era:')
print('pre-2003:', fz[fz.index < '2003-01-01'][['growth_surprise_conf', 'real_rate_conf', 'valuation_conf']].mean())
print('post-2010:', fz[fz.index >= '2010-01-01'][['growth_surprise_conf', 'real_rate_conf', 'valuation_conf']].mean())
"
```

Expected:
- panel: ~(135, 40)
- factor_z: (135, 18) — 9 z + 9 conf
- bucket_returns: (135, 5)
- samples: ~(130, 23) — 18 factor + 5 next bucket
- Pre-2003 confidence 가 post-2010 보다 낮음 (TIPS / KOSPI valuation / sector dispersion 부재)
- All 9 factor 가 post-2010 에서 confidence > 0.7

### Task 5.3: Pre-commit regression + commit

- [ ] **Step 1: 전체 regression test** (production code 변경 없음 — fetch script + data 만)

```bash
uv run pytest tests/unit/ -q 2>&1 | tail -3
uv run pytest tests/integration/ -q 2>&1 | tail -3
```

Expected: PR1 baseline + C1-C4 신규 test 모두 PASS.

- [ ] **Step 2: `regression_log.md` 의 "## Post-C5" entry** — 특히 generation script 의 실행 시간 + 산출물 크기 명시.

- [ ] **Step 3: parquet 파일 + script commit**

```bash
git add scripts/generate_historical_factor_z.py
git add backtest/historical/quarterly_indicators.parquet
git add backtest/historical/factor_z.parquet
git add backtest/historical/bucket_returns.parquet
git add backtest/historical/samples.parquet
git add artifacts/<run-date>/regression_log.md
git commit -m "$(cat <<'EOF'
data(stage2a): historical factor z + bucket returns 1991-2024 (C5)

scripts/generate_historical_factor_z.py 의 end-to-end 실행 결과 commit.

- backtest/historical/quarterly_indicators.parquet: 135Q × ~40 col
  (FRED + ALFRED vintage + yfinance + pykrx + Shiller CAPE static)
- backtest/historical/factor_z.parquet: 135Q × 18 col (9 z + 9 confidence)
- backtest/historical/bucket_returns.parquet: 135Q × 5 bucket (KRW basis)
- backtest/historical/samples.parquet: ~130-135 row × 23 col (HistoricalSample
  equivalent — factor z + next-quarter bucket return)

Generation 환경: Linux + FRED_API_KEY. Total fetch + compute ~13 min.
mode='historical' 사용 (Critical 2) — news component weight 0,
quant weight renormalize.

본 commit 의 parquet 가 C6 calibration runner 의 input.

다음 commit (C6) 전 grill-me #2: factor z coverage by era + sample sanity
+ mode='historical' 효과 verify.

EOF
)"
```

### Task 5.4: [grill-me #2 marker]

본 시점에서 **executing-plans 가 일시 멈추고 grill-me #2 수행**.

Grill 대상:
1. **factor z coverage by era** — pre-2003 의 confidence 가 expected 수준인지 (TIPS/real_yield/KOSPI valuation 부재 영향). Post-2010 의 confidence 가 ≥ 0.85 인지.
2. **mode='historical' effect verify** — production mode 와 historical mode 의 factor z magnitude 차이 quantify. 비슷한 scale (news weight ≈ 10-15%) 인지.
3. **Sample sanity** — extreme outlier sample (예: 2008-Q4, 2020-Q1) 의 factor z + bucket return 이 reasonable 한지. NaN bucket return 의 quarter 수 확인.

Grill 결과 → `artifacts/<run-date>/decisions.md` 의 "grill-me #2" section 에 기록.

---

## Task 6: Calibrate Runner — Walk-forward + Shrinkage Grid (C6)

`scripts/calibrate_factor_model.py` 가 samples.parquet 로 walk-forward 7 folds × 5 shrinkage values × L-BFGS-B 최적화 = 35 calibration runs.

### Task 6.1: HistoricalSample loader + smoke test

**Files:**
- Create: `scripts/calibrate_factor_model.py`
- Create: `tests/integration/test_calibration_pipeline_synthetic.py`

- [ ] **Step 1: Synthetic smoke test 작성**

`tests/integration/test_calibration_pipeline_synthetic.py`:

```python
"""Integration test — calibrate pipeline on synthetic data."""
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tradingagents.skills.research.factor_to_bucket import (
    FACTORS, BUCKETS, INITIAL_BETA, SIGN_RESTRICTION,
)


def _build_synthetic_samples(n: int = 135, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic factor z + bucket returns with known underlying β."""
    rng = np.random.default_rng(seed)
    # 9 factor z ~ N(0, 1)
    factor_z = rng.standard_normal((n, len(FACTORS)))
    fz_df = pd.DataFrame(factor_z, columns=list(FACTORS))
    # 9 confidence ~ 0.85 (synthetic high coverage)
    conf_df = pd.DataFrame(
        np.full((n, len(FACTORS)), 0.85),
        columns=[f"{f}_conf" for f in FACTORS],
    )

    # Synthetic β (use INITIAL_BETA with noise)
    bucket_returns = np.zeros((n, len(BUCKETS)))
    for i in range(n):
        for j, b in enumerate(BUCKETS):
            for k, f in enumerate(FACTORS):
                bucket_returns[i, j] += INITIAL_BETA.get((f, b), 0.0) * factor_z[i, k]
            # baseline equity premium + noise
            if b in ("kr_equity", "global_equity"):
                bucket_returns[i, j] += 0.015
            elif b == "bond":
                bucket_returns[i, j] += 0.008
            elif b == "cash_mmf":
                bucket_returns[i, j] += 0.005
            bucket_returns[i, j] += rng.normal(0, 0.04)
    br_df = pd.DataFrame(bucket_returns,
                          columns=[f"next_{b}" for b in BUCKETS])

    index = pd.date_range("1991-03-31", periods=n, freq="QE")
    combined = pd.concat([fz_df, conf_df, br_df], axis=1)
    combined.index = index
    combined.index.name = "quarter_end"
    return combined


def test_load_samples_from_parquet(tmp_path: Path) -> None:
    """Load samples → HistoricalSample list."""
    from scripts.calibrate_factor_model import load_samples_from_parquet
    samples_df = _build_synthetic_samples(n=10)
    p = tmp_path / "samples.parquet"
    samples_df.to_parquet(p)

    samples = load_samples_from_parquet(p)
    assert len(samples) == 10
    s0 = samples[0]
    assert set(s0.factor_z.keys()) == set(FACTORS)
    assert set(s0.bucket_returns_next.keys()) == set(BUCKETS)


def test_walk_forward_synthetic_produces_7_folds(tmp_path: Path) -> None:
    """135 sample → walk_forward(initial_train=80, test=7) → 7 folds."""
    from scripts.calibrate_factor_model import load_samples_from_parquet
    from tradingagents.skills.research.factor_calibration import walk_forward

    samples_df = _build_synthetic_samples(n=135)
    p = tmp_path / "samples.parquet"
    samples_df.to_parquet(p)

    samples = load_samples_from_parquet(p)
    folds = walk_forward(samples, initial_train_size=80, test_window=7)
    assert len(folds) == 7
    # 각 fold 의 train+test 구조
    assert folds[0].train_end_idx == 80
    assert folds[6].test_end_idx == 129
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/integration/test_calibration_pipeline_synthetic.py -v
```

Expected: ImportError on `scripts.calibrate_factor_model`.

- [ ] **Step 3: `scripts/calibrate_factor_model.py` 최소 구현**

`scripts/calibrate_factor_model.py`:

```python
"""Walk-forward calibration + shrinkage grid + acceptance gate (C6/C7).

End-to-end:
1. Load samples.parquet → HistoricalSample list
2. Walk-forward (initial_train=80, test=7) → 7 folds
3. Shrinkage grid loop {0.1, 0.3, 0.5, 1.0, 2.0} × 7 folds = 35 runs
4. Prior baseline OOS Sharpe (no-fit walk-forward)
5. Equi-weight β=0 baseline OOS Sharpe (informational, M3)
6. Vintage sanity (latest-vintage β 와 비교) — opt-in if 2nd samples 제공
7. Learning sensitivity diagnostic |β_0.1 - β_2.0|_avg (M2)
8. Best shrinkage selection (mean_oos - 0.25 × std_oos, M5)
9. Acceptance gate evaluation → validation_report.json

Usage:
    uv run python scripts/calibrate_factor_model.py \\
        --samples backtest/historical/samples.parquet \\
        --output-dir artifacts/<run-date>/calibration_runs \\
        [--latest-vintage-samples backtest/historical/samples_latest_vintage.parquet]
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from tradingagents.skills.research.factor_calibration import (
    HistoricalSample, walk_forward, hybrid_calibration,
    aggregate_median_beta, simulate_portfolio_returns, compute_sharpe,
)
from tradingagents.skills.research.factor_to_bucket import (
    FACTORS, BUCKETS, INITIAL_BETA, SIGN_RESTRICTION,
)
from tradingagents.backtest.acceptance import evaluate_acceptance

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


SHRINKAGE_GRID: list[float] = [0.1, 0.3, 0.5, 1.0, 2.0]


def load_samples_from_parquet(path: Path) -> list[HistoricalSample]:
    """samples.parquet → list[HistoricalSample]."""
    df = pd.read_parquet(path)
    samples = []
    for idx, row in df.iterrows():
        date_str = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)
        factor_z = {f: float(row[f]) for f in FACTORS if f in row}
        factor_conf = {f: float(row.get(f"{f}_conf", 1.0)) for f in FACTORS}
        bucket_returns_next = {
            b: float(row.get(f"next_{b}", np.nan)) for b in BUCKETS
        }
        # Skip if all bucket returns NaN
        if all(pd.isna(v) for v in bucket_returns_next.values()):
            continue
        sample_quality = float(np.mean(list(factor_conf.values())))
        samples.append(HistoricalSample(
            date=date_str,
            factor_z=factor_z,
            bucket_returns_next=bucket_returns_next,
        ))
    logger.info("Loaded %s samples", len(samples))
    return samples


def compute_prior_baseline_oos(samples, initial_train_size=80, test_window=7):
    """Hand-coded INITIAL_BETA 의 walk-forward OOS Sharpe (no fitting)."""
    n = len(samples)
    oos_sharpes = []
    for end in range(initial_train_size, n - test_window + 1, test_window):
        test = samples[end : end + test_window]
        test_returns = simulate_portfolio_returns(test, INITIAL_BETA)
        oos_sharpes.append(compute_sharpe(test_returns))
    return float(np.mean(oos_sharpes)), oos_sharpes


def compute_equi_weight_baseline_oos(samples, initial_train_size=80, test_window=7):
    """β=0 (모든 weight 0, factor model 가 baseline 만 반환) 의 OOS Sharpe."""
    zero_beta = {k: 0.0 for k in INITIAL_BETA.keys()}
    n = len(samples)
    oos_sharpes = []
    for end in range(initial_train_size, n - test_window + 1, test_window):
        test = samples[end : end + test_window]
        test_returns = simulate_portfolio_returns(test, zero_beta)
        oos_sharpes.append(compute_sharpe(test_returns))
    return float(np.mean(oos_sharpes)), oos_sharpes


def run_shrinkage_grid(
    samples, output_dir: Path,
    initial_train_size: int = 80, test_window: int = 7,
):
    """5 shrinkage × 7 fold = 35 runs."""
    per_fold_dir = output_dir / "per_fold"
    per_fold_dir.mkdir(parents=True, exist_ok=True)

    per_shrinkage_results = {}
    for s in SHRINKAGE_GRID:
        logger.info("Shrinkage %s: running walk-forward", s)
        folds = walk_forward(
            samples, initial_train_size=initial_train_size,
            test_window=test_window, shrinkage=s, prior_beta=INITIAL_BETA,
        )
        # Save per-fold
        for fold in folds:
            with open(per_fold_dir / f"shrinkage_{s}_fold_{fold.fold_idx}.json", "w") as f:
                json.dump({
                    "shrinkage": s, "fold_idx": fold.fold_idx,
                    "train_end_idx": fold.train_end_idx,
                    "test_start_idx": fold.test_start_idx,
                    "test_end_idx": fold.test_end_idx,
                    "in_sample_sharpe": fold.in_sample_sharpe,
                    "oos_sharpe": fold.oos_sharpe,
                    "beta": {f"{k[0]}_{k[1]}": v for k, v in fold.beta.items()},
                }, f, indent=2)
        median_beta = aggregate_median_beta(folds)
        per_shrinkage_results[str(s)] = {
            "median_beta": {f"{k[0]}_{k[1]}": v for k, v in median_beta.items()},
            "median_beta_tuples": median_beta,  # for downstream
            "mean_is": float(np.mean([f.in_sample_sharpe for f in folds])),
            "mean_oos": float(np.mean([f.oos_sharpe for f in folds])),
            "std_oos": float(np.std([f.oos_sharpe for f in folds], ddof=1)),
            "per_fold_oos": [f.oos_sharpe for f in folds],
            "per_fold_is": [f.in_sample_sharpe for f in folds],
            "folds": folds,
        }

    # Save summary (without _tuples and folds — not JSON serializable)
    serializable = {}
    for s_key, r in per_shrinkage_results.items():
        serializable[s_key] = {
            k: v for k, v in r.items()
            if k not in ("median_beta_tuples", "folds")
        }
    with open(output_dir / "per_shrinkage_summary.json", "w") as f:
        json.dump(serializable, f, indent=2)
    return per_shrinkage_results


def select_best_shrinkage(per_shrinkage_results):
    """Best by mean_oos - 0.25 × std_oos (robustness, M5).
    Tie-break: smaller |mean_is - mean_oos|.
    """
    scores = {}
    for s_str, r in per_shrinkage_results.items():
        score = r["mean_oos"] - 0.25 * r["std_oos"]
        tiebreak = -abs(r["mean_is"] - r["mean_oos"])
        scores[s_str] = (score, tiebreak)
    best = max(scores, key=lambda k: scores[k])
    return best, per_shrinkage_results[best]


def compute_learning_sensitivity(per_shrinkage_results):
    """|β_0.1 - β_2.0|_avg (M2). Returns float."""
    b1 = per_shrinkage_results["0.1"]["median_beta_tuples"]
    b2 = per_shrinkage_results["2.0"]["median_beta_tuples"]
    diffs = [abs(b1[k] - b2[k]) for k in b1.keys() if k in b2]
    return float(np.mean(diffs)) if diffs else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", required=True)
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--latest-vintage-samples", default=None,
                    help="Opt-in: latest-vintage samples for vintage sanity check (Critical 1).")
    ap.add_argument("--initial-train-size", type=int, default=80)
    ap.add_argument("--test-window", type=int, default=7)
    args = ap.parse_args()

    samples = load_samples_from_parquet(Path(args.samples))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Shrinkage grid
    logger.info("Running shrinkage grid: %s × %s folds", SHRINKAGE_GRID, args.test_window)
    results = run_shrinkage_grid(samples, output_dir,
                                  initial_train_size=args.initial_train_size,
                                  test_window=args.test_window)

    # 2. Prior baseline
    logger.info("Computing prior baseline OOS Sharpe")
    prior_oos_mean, prior_per_fold = compute_prior_baseline_oos(
        samples, args.initial_train_size, args.test_window,
    )

    # 3. Equi-weight baseline (M3)
    logger.info("Computing equi-weight (β=0) baseline OOS Sharpe")
    equi_oos_mean, equi_per_fold = compute_equi_weight_baseline_oos(
        samples, args.initial_train_size, args.test_window,
    )
    with open(output_dir / "equi_weight_baseline.json", "w") as f:
        json.dump({
            "mean_oos_sharpe": equi_oos_mean,
            "per_fold_oos": equi_per_fold,
        }, f, indent=2)

    # 4. Best shrinkage
    best_shr, best_result = select_best_shrinkage(results)
    logger.info("Best shrinkage: %s (score %.4f)", best_shr,
                best_result["mean_oos"] - 0.25 * best_result["std_oos"])
    with open(output_dir / "best_shrinkage.json", "w") as f:
        json.dump({
            "shrinkage": float(best_shr),
            "mean_is_sharpe": best_result["mean_is"],
            "mean_oos_sharpe": best_result["mean_oos"],
            "std_oos_sharpe": best_result["std_oos"],
            "median_beta": best_result["median_beta"],
        }, f, indent=2)

    # 5. Vintage sanity (opt-in, Critical 1)
    vintage_sanity = {"pass": True, "skipped": True, "reason": "no latest-vintage samples provided"}
    if args.latest_vintage_samples:
        logger.info("Vintage sanity check: comparing with latest-vintage samples")
        lv_samples = load_samples_from_parquet(Path(args.latest_vintage_samples))
        lv_results = run_shrinkage_grid(lv_samples, output_dir / "vintage_latest",
                                         args.initial_train_size, args.test_window)
        _, lv_best = select_best_shrinkage(lv_results)
        b_vintage = best_result["median_beta_tuples"]
        b_latest = lv_best["median_beta_tuples"]
        diffs = [abs(b_vintage[k] - b_latest[k]) for k in b_vintage.keys() if k in b_latest]
        avg_diff = float(np.mean(diffs)) if diffs else 0.0
        vintage_sanity = {
            "pass": avg_diff < 0.05,
            "avg_abs_diff": avg_diff,
            "skipped": False,
        }
    with open(output_dir / "vintage_sanity.json", "w") as f:
        json.dump(vintage_sanity, f, indent=2)

    # 6. Learning sensitivity (M2)
    sens = compute_learning_sensitivity(results)
    with open(output_dir / "learning_sensitivity.json", "w") as f:
        json.dump({
            "avg_abs_diff_shrinkage_0.1_vs_2.0": sens,
            "warning_if_below": 0.01,
            "warning_triggered": sens < 0.01,
        }, f, indent=2)

    # 7. Acceptance gate
    logger.info("Evaluating acceptance gate")
    verdict = evaluate_acceptance(
        calibrated_beta=best_result["median_beta_tuples"],
        calibrated_folds=best_result["folds"],
        prior_oos_per_fold=prior_per_fold,
        prior_oos_mean=prior_oos_mean,
        equi_oos_mean=equi_oos_mean,
        vintage_sanity=vintage_sanity,
        learning_sensitivity=sens,
    )
    with open(output_dir / "validation_report.json", "w") as f:
        # 직렬화 가능한 부분만
        json.dump({
            "pass": verdict["pass"],
            "conditions": verdict["conditions"],
            "best_shrinkage": float(best_shr),
            "mean_is_sharpe": verdict["mean_is_sharpe"],
            "mean_oos_sharpe": verdict["mean_oos_sharpe"],
            "prior_oos_sharpe": prior_oos_mean,
            "equi_weight_oos_sharpe": equi_oos_mean,
            "improvement_delta": verdict["mean_oos_sharpe"] - prior_oos_mean,
            "paired_t_p": verdict["paired_t_p"],
            "diagnostic": verdict["diagnostic"],
            "calibrated_beta": {f"{k[0]}_{k[1]}": v
                                for k, v in best_result["median_beta_tuples"].items()},
        }, f, indent=2)

    print(json.dumps({
        "pass": verdict["pass"],
        "best_shrinkage": float(best_shr),
        "mean_oos_sharpe": verdict["mean_oos_sharpe"],
        "prior_oos_sharpe": prior_oos_mean,
        "improvement_delta": verdict["mean_oos_sharpe"] - prior_oos_mean,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

**주의**: `factor_calibration.walk_forward` 의 시그니처가 PR1 C6 에서 `shrinkage` parameter 를 받는지 확인. PR1 의 `walk_forward(samples, initial_train_size=80, test_window=8, shrinkage=0.5, prior_beta=None)` 이미 있음 (factor_calibration.py:170).

- [ ] **Step 4: smoke test 재실행 → pass**

```bash
uv run pytest tests/integration/test_calibration_pipeline_synthetic.py -v
```

Expected: 2 tests pass.

### Task 6.2: Pre-commit regression + commit

- [ ] **Step 1: 전체 regression**

```bash
uv run pytest tests/unit/ -q 2>&1 | tail -3
uv run pytest tests/integration/ -q 2>&1 | tail -3
```

Expected: pre-existing 유지 + synthetic smoke 2 pass.

(주: Task 7 의 `evaluate_acceptance` 가 아직 부재 — calibrate_factor_model.py 의 import 가 fail. 본 commit 의 smoke test 는 load + walk_forward 만 검증. C7 commit 후 end-to-end script 실행.)

- [ ] **Step 2: `regression_log.md` 의 "## Post-C6" entry**

- [ ] **Step 3: commit**

```bash
git add scripts/calibrate_factor_model.py
git add tests/integration/test_calibration_pipeline_synthetic.py
git add artifacts/<run-date>/regression_log.md
git commit -m "$(cat <<'EOF'
feat(backtest): walk-forward calibration runner with shrinkage grid (C6)

scripts/calibrate_factor_model.py — PR2a 의 calibration orchestration:

- load_samples_from_parquet: samples.parquet → HistoricalSample list
- run_shrinkage_grid: 5 shrinkage × 7 fold = 35 calibration runs.
  각 fold 의 hybrid_calibration (PR1 C6) call + per-fold json output.
- compute_prior_baseline_oos: hand-coded INITIAL_BETA 의 walk-forward OOS
  Sharpe (no fitting) — acceptance gate condition 1 의 baseline
- compute_equi_weight_baseline_oos: β=0 baseline — M3 informational
- select_best_shrinkage: mean_oos - 0.25 × std_oos (M5)
- compute_learning_sensitivity: |β_0.1 - β_2.0|_avg (M2 diagnostic)
- 최종 acceptance gate (C7 의 evaluate_acceptance 호출) 후 validation_
  report.json 작성

본 commit 에서 script 는 evaluate_acceptance import — C7 후 실행 가능.

Synthetic smoke test (test_calibration_pipeline_synthetic.py): load +
walk_forward fold 수 확인.

EOF
)"
```

---

## Task 7: Acceptance Gate (C7)

`tradingagents/backtest/acceptance.py` — 5 strict-default condition + paired-t-test + diagnostic.

### Task 7.1: `acceptance.py` 핵심 logic

**Files:**
- Create: `tradingagents/backtest/acceptance.py`
- Create: `tests/unit/backtest/test_acceptance.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/backtest/test_acceptance.py`:

```python
"""Unit tests for acceptance.py — strict default 5-condition gate (Critical 3)."""
from dataclasses import dataclass
import pytest

from tradingagents.skills.research.factor_to_bucket import (
    INITIAL_BETA, SIGN_RESTRICTION, FACTORS, BUCKETS,
)
from tradingagents.backtest.acceptance import evaluate_acceptance


@dataclass
class FakeFold:
    fold_idx: int
    in_sample_sharpe: float
    oos_sharpe: float
    beta: dict


def _good_calibrated_beta():
    """Calibrated β = INITIAL_BETA × 1.1 — sign respect 유지."""
    return {k: v * 1.1 for k, v in INITIAL_BETA.items()}


def _good_folds():
    return [FakeFold(i, 0.6, 0.5 + 0.01 * i, _good_calibrated_beta())
            for i in range(7)]


def test_acceptance_pass_default_strict() -> None:
    """default strict — all conditions pass."""
    folds = _good_folds()
    verdict = evaluate_acceptance(
        calibrated_beta=_good_calibrated_beta(),
        calibrated_folds=folds,
        prior_oos_per_fold=[0.3 + 0.005 * i for i in range(7)],
        prior_oos_mean=0.32,
        equi_oos_mean=0.1,
        vintage_sanity={"pass": True, "skipped": False, "avg_abs_diff": 0.02},
        learning_sensitivity=0.05,
    )
    assert verdict["pass"]
    assert verdict["conditions"]["improvement"]
    assert verdict["conditions"]["overfit_guard"]
    assert verdict["conditions"]["sign_respect"]
    assert verdict["conditions"]["saturation"]
    assert verdict["conditions"]["fold_positive"]


def test_acceptance_fail_overfit() -> None:
    """IS Sharpe 1.5, OOS 0.5 → overfit guard FAIL (Δ=1.0 > 0.30)."""
    folds = [FakeFold(i, 1.5, 0.5, _good_calibrated_beta()) for i in range(7)]
    verdict = evaluate_acceptance(
        calibrated_beta=_good_calibrated_beta(),
        calibrated_folds=folds,
        prior_oos_per_fold=[0.3] * 7,
        prior_oos_mean=0.3,
        equi_oos_mean=0.1,
        vintage_sanity={"pass": True, "skipped": True, "avg_abs_diff": 0.0},
        learning_sensitivity=0.05,
    )
    assert not verdict["pass"]
    assert not verdict["conditions"]["overfit_guard"]


def test_acceptance_fail_sign_violation() -> None:
    """β 의 sign 이 SIGN_RESTRICTION 위반."""
    bad_beta = dict(INITIAL_BETA)
    # F2 inflation_surprise × bond should be negative — flip to positive
    bad_beta[("inflation_surprise", "bond")] = abs(bad_beta[("inflation_surprise", "bond")])
    if SIGN_RESTRICTION.get(("inflation_surprise", "bond")) == "negative":
        folds = [FakeFold(i, 0.6, 0.5, bad_beta) for i in range(7)]
        verdict = evaluate_acceptance(
            calibrated_beta=bad_beta,
            calibrated_folds=folds,
            prior_oos_per_fold=[0.3] * 7,
            prior_oos_mean=0.3,
            equi_oos_mean=0.1,
            vintage_sanity={"pass": True, "skipped": True, "avg_abs_diff": 0.0},
            learning_sensitivity=0.05,
        )
        assert not verdict["conditions"]["sign_respect"]


def test_acceptance_fail_fold_positive() -> None:
    """fold positive 5/7 (lenient 였던 것) — strict 에선 ≥6/7 — FAIL."""
    folds = [FakeFold(i, 0.4, (0.1 if i < 5 else -0.1), _good_calibrated_beta())
             for i in range(7)]
    verdict = evaluate_acceptance(
        calibrated_beta=_good_calibrated_beta(),
        calibrated_folds=folds,
        prior_oos_per_fold=[0.05] * 7,
        prior_oos_mean=0.05,
        equi_oos_mean=0.0,
        vintage_sanity={"pass": True, "skipped": True, "avg_abs_diff": 0.0},
        learning_sensitivity=0.05,
    )
    assert not verdict["conditions"]["fold_positive"]
    # 5/7 — strict default ≥6 — FAIL


def test_acceptance_paired_t_p_required_for_improvement() -> None:
    """+0.05 mean improvement 만 으로는 부족 — paired_t p < 0.20 도 필요."""
    # 작은 mean 차이 + 큰 fold variance → paired-t p > 0.20
    folds = [FakeFold(i, 0.5, (0.35 + 0.3 * (i % 2) - 0.15), _good_calibrated_beta())
             for i in range(7)]
    # OOS Sharpes: 0.20, 0.50, 0.20, 0.50, 0.20, 0.50, 0.20 — mean ~0.327
    verdict = evaluate_acceptance(
        calibrated_beta=_good_calibrated_beta(),
        calibrated_folds=folds,
        prior_oos_per_fold=[0.25] * 7,  # constant prior
        prior_oos_mean=0.25,
        equi_oos_mean=0.1,
        vintage_sanity={"pass": True, "skipped": True, "avg_abs_diff": 0.0},
        learning_sensitivity=0.05,
    )
    # Improvement delta ~0.077 > 0.05 — but paired-t p?
    # 큰 variance 의 calibrated → paired-t marginal
    # 본 test 는 paired_t_p field 가 verdict 에 포함되는지만 verify
    assert "paired_t_p" in verdict
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/unit/backtest/test_acceptance.py -v
```

Expected: ImportError.

- [ ] **Step 3: `acceptance.py` 구현**

`tradingagents/backtest/acceptance.py`:

```python
"""Acceptance gate for PR2a INITIAL_BETA replacement (Critical 3 strict default).

5 conditions:
1. improvement: mean OOS > prior + 0.05 AND paired_t p < 0.20
2. overfit_guard: |mean_is - mean_oos| < 0.30
3. sign_respect: all calibrated β follow SIGN_RESTRICTION
4. saturation: fraction of |β| > 0.195 < 30%
5. fold_positive: ≥6 of 7 folds positive OOS Sharpe

Plus informational diagnostic:
- vintage_sanity (Critical 1)
- learning_sensitivity (M2)
- equi_weight_baseline (M3)
- saturated_fraction
- prior_stuck_fraction (M1)
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
from scipy import stats

from tradingagents.skills.research.factor_to_bucket import (
    SIGN_RESTRICTION, INITIAL_BETA,
)

logger = logging.getLogger(__name__)


_SATURATION_THRESHOLD = 0.195  # |β| > 0.195 (bound 0.20)
_SATURATION_FRACTION_CAP = 0.30
_OVERFIT_GUARD_LIMIT = 0.30
_IMPROVEMENT_MARGIN = 0.05
_PAIRED_T_P_THRESHOLD = 0.20
_FOLD_POSITIVE_MIN = 6  # out of 7
_PRIOR_STUCK_THRESHOLD = 1e-3  # |β - prior| < threshold = stuck
_PRIOR_STUCK_FRACTION_WARN = 0.80


def _check_sign(key: tuple[str, str], value: float) -> bool:
    """SIGN_RESTRICTION 의 expected sign 위반 검출."""
    expected = SIGN_RESTRICTION.get(key, "either")
    if expected == "positive":
        return value >= -1e-9
    if expected == "negative":
        return value <= 1e-9
    return True


def evaluate_acceptance(
    calibrated_beta: dict,
    calibrated_folds: list,
    prior_oos_per_fold: list[float],
    prior_oos_mean: float,
    equi_oos_mean: float,
    vintage_sanity: dict,
    learning_sensitivity: float,
) -> dict:
    """5-condition strict-default acceptance gate.

    Returns:
        {"pass": bool, "conditions": {...}, ..., "diagnostic": {...}}.
    """
    # Basic stats
    mean_is = float(np.mean([f.in_sample_sharpe for f in calibrated_folds]))
    mean_oos = float(np.mean([f.oos_sharpe for f in calibrated_folds]))
    calibrated_per_fold_oos = [f.oos_sharpe for f in calibrated_folds]

    # Paired-t-test (calibrated vs prior on per-fold)
    paired_t_p = 1.0
    if len(prior_oos_per_fold) == len(calibrated_per_fold_oos):
        try:
            stat, paired_t_p = stats.ttest_rel(
                calibrated_per_fold_oos, prior_oos_per_fold,
                alternative="greater",
            )
            paired_t_p = float(paired_t_p)
        except Exception as e:
            logger.warning("paired t-test failed: %s", e)
            paired_t_p = 1.0

    # Condition 1: improvement (margin + paired-t)
    improvement = (
        (mean_oos > prior_oos_mean + _IMPROVEMENT_MARGIN)
        and (paired_t_p < _PAIRED_T_P_THRESHOLD)
    )

    # Condition 2: overfit guard
    overfit_guard = abs(mean_is - mean_oos) < _OVERFIT_GUARD_LIMIT

    # Condition 3: sign respect
    sign_respect = all(
        _check_sign(k, v) for k, v in calibrated_beta.items()
    )

    # Condition 4: saturation
    saturated_count = sum(
        1 for v in calibrated_beta.values() if abs(v) > _SATURATION_THRESHOLD
    )
    saturated_fraction = saturated_count / max(1, len(calibrated_beta))
    saturation = saturated_fraction < _SATURATION_FRACTION_CAP

    # Condition 5: fold positive
    fold_positive_count = sum(1 for s in calibrated_per_fold_oos if s > 0)
    fold_positive = fold_positive_count >= _FOLD_POSITIVE_MIN

    overall_pass = (
        improvement and overfit_guard and sign_respect
        and saturation and fold_positive
    )

    # M1 diagnostic: prior-stuck fraction
    stuck_count = sum(
        1 for k, v in calibrated_beta.items()
        if abs(v - INITIAL_BETA.get(k, 0.0)) < _PRIOR_STUCK_THRESHOLD
    )
    stuck_fraction = stuck_count / max(1, len(calibrated_beta))

    return {
        "pass": bool(overall_pass),
        "conditions": {
            "improvement": bool(improvement),
            "overfit_guard": bool(overfit_guard),
            "sign_respect": bool(sign_respect),
            "saturation": bool(saturation),
            "fold_positive": bool(fold_positive),
        },
        "mean_is_sharpe": mean_is,
        "mean_oos_sharpe": mean_oos,
        "prior_oos_sharpe": prior_oos_mean,
        "equi_weight_oos_sharpe": equi_oos_mean,
        "improvement_delta": mean_oos - prior_oos_mean,
        "paired_t_p": paired_t_p,
        "diagnostic": {
            "vintage_sanity_pass": vintage_sanity.get("pass", True),
            "vintage_sanity_avg_diff": vintage_sanity.get("avg_abs_diff", None),
            "vintage_sanity_skipped": vintage_sanity.get("skipped", True),
            "learning_sensitivity": learning_sensitivity,
            "learning_sensitivity_warning": learning_sensitivity < 0.01,
            "saturated_count": saturated_count,
            "saturated_fraction": saturated_fraction,
            "prior_stuck_count": stuck_count,
            "prior_stuck_fraction": stuck_fraction,
            "prior_stuck_warning": stuck_fraction > _PRIOR_STUCK_FRACTION_WARN,
            "fold_positive_count": fold_positive_count,
        },
    }
```

- [ ] **Step 4: 테스트 재실행 → pass**

```bash
uv run pytest tests/unit/backtest/test_acceptance.py -v
```

Expected: 5 tests pass.

### Task 7.2: Pre-commit regression + commit

- [ ] **Step 1: 전체 regression**

```bash
uv run pytest tests/unit/ -q 2>&1 | tail -3
uv run pytest tests/integration/ -q 2>&1 | tail -3
```

Expected: pre-existing 유지 + 5 신규 acceptance test pass + C6 의 calibrate_factor_model script 의 import 가 이제 satisfy.

- [ ] **Step 2: `regression_log.md` 의 "## Post-C7" entry**

- [ ] **Step 3: commit**

```bash
git add tradingagents/backtest/acceptance.py
git add tests/unit/backtest/test_acceptance.py
git add artifacts/<run-date>/regression_log.md
git commit -m "$(cat <<'EOF'
feat(backtest): acceptance gate (5 strict-default condition + paired-t) (C7, Critical 3)

tradingagents/backtest/acceptance.py — PR2a INITIAL_BETA 교체 의 acceptance
gate. Critical 3 의 stricter default 적용.

5 conditions:
1. improvement: mean OOS > prior + 0.05 AND paired_t_p < 0.20
2. overfit_guard: |mean_is - mean_oos| < 0.30 (lenient 0.50 에서 강화)
3. sign_respect: all β follow SIGN_RESTRICTION
4. saturation: fraction of |β| > 0.195 < 30%
5. fold_positive: ≥6 of 7 folds positive OOS (5/7 lenient 에서 강화)

Informational diagnostic (gate 아님):
- vintage_sanity (Critical 1)
- learning_sensitivity (M2): |β_0.1 - β_2.0|_avg
- equi_weight_oos: β=0 baseline (M3)
- saturated_fraction: |β| > 0.195 비율
- prior_stuck_fraction (M1): |β - prior| < 0.001 비율 — 80% 초과 warn

Unit tests: 5 (pass default / overfit fail / sign violation / fold-positive
fail / paired-t p field present).

Spec: section 4.8.

EOF
)"
```

---

## Task 8: Calibration Runs Commit (C8)

`scripts/calibrate_factor_model.py` 의 실제 실행 → artifacts 산출물 commit.

### Task 8.1: Calibration script 실행

- [ ] **Step 1: Real samples 로 calibration 실행**

```bash
uv run python scripts/calibrate_factor_model.py \
    --samples backtest/historical/samples.parquet \
    --output-dir artifacts/<run-date>/calibration_runs \
    --initial-train-size 80 \
    --test-window 7
```

Expected:
- ~3-15 분 (35 calibration runs + baselines + diagnostic)
- stdout JSON:
  ```
  {
    "pass": true/false,
    "best_shrinkage": 0.5,
    "mean_oos_sharpe": 0.42,
    "prior_oos_sharpe": 0.31,
    "improvement_delta": 0.11
  }
  ```

- [ ] **Step 2: 산출물 sanity check**

```bash
ls artifacts/<run-date>/calibration_runs/
ls artifacts/<run-date>/calibration_runs/per_fold/ | wc -l
cat artifacts/<run-date>/calibration_runs/validation_report.json | head -30
```

Expected:
- `per_fold/` 안에 35 file (5 shrinkage × 7 fold)
- `per_shrinkage_summary.json`, `best_shrinkage.json`, `equi_weight_baseline.json`, `learning_sensitivity.json`, `vintage_sanity.json`, `validation_report.json` 모두 present
- `validation_report.json` 의 `pass` field 값 확인 (PASS or FAIL)

### Task 8.2: Pre-commit regression + commit

- [ ] **Step 1: 전체 regression**

```bash
uv run pytest tests/unit/ -q 2>&1 | tail -3
uv run pytest tests/integration/ -q 2>&1 | tail -3
```

Expected: pre-existing 유지 + C1-C7 신규 test 모두 pass.

- [ ] **Step 2: `regression_log.md` 의 "## Post-C8" entry + validation_report 결과 명시**

```markdown
## Post-C8 (data: calibration runs + validation_report)

Calibration verdict: PASS / FAIL (see validation_report.json)
Best shrinkage: <s>
Mean OOS Sharpe: <x>
Prior OOS Sharpe: <y>
Improvement delta: <x-y>
Paired-t p: <p>

Pre-existing fail: 3 unit + 18 integ — 동일.
```

- [ ] **Step 3: commit**

```bash
git add artifacts/<run-date>/calibration_runs/
git add artifacts/<run-date>/regression_log.md
git commit -m "$(cat <<'EOF'
data(stage2a): 35 walk-forward calibration runs + validation_report (C8)

scripts/calibrate_factor_model.py 의 실제 실행 결과 commit.

- per_fold/: 35 calibration runs (5 shrinkage × 7 fold) 의 β + IS Sharpe +
  OOS Sharpe per fold
- per_shrinkage_summary.json: 5 shrinkage 의 median β + mean/std OOS
- best_shrinkage.json: 선정된 shrinkage (M5 의 mean-0.25std criterion) +
  최종 median β
- vintage_sanity.json: Critical 1 의 vintage 효과 (skipped if no
  latest-vintage samples 제공)
- equi_weight_baseline.json: β=0 baseline (M3 informational)
- learning_sensitivity.json: |β_0.1 - β_2.0|_avg (M2 diagnostic)
- validation_report.json: 5 condition acceptance gate verdict + paired-t-p
  + diagnostic block

Verdict: PASS / FAIL (validation_report 의 'pass' field 확인).

다음 commit 전 grill-me #3: best β 해석 + acceptance verdict review +
INITIAL_BETA 교체 권한 confirm.

EOF
)"
```

### Task 8.3: [grill-me #3 marker]

본 시점에서 **executing-plans 가 일시 멈추고 grill-me #3 수행**.

Grill 대상:
1. **Best β magnitude 해석** — hand-coded INITIAL_BETA 와의 |Δβ|_avg. 어떤 (factor, bucket) 의 β 가 가장 크게 바뀌었나. 그게 economically sensible 한지.
2. **Sign 일관성** — sign flip 한 β 가 있는지. SIGN_RESTRICTION 의 "either" 영역 안에서의 flip 인지.
3. **Acceptance gate verdict** — 5 condition + paired-t-p + diagnostic 분석. 어느 condition 이 PASS/FAIL 했는지. Diagnostic warning (M1 prior_stuck > 80% / M2 learning_sensitivity < 0.01) trigger 됐는지.
4. **INITIAL_BETA 교체 권한** — user 의 final approval. PASS 시 C9, FAIL 시 C9-alt.

Grill 결과 → `artifacts/<run-date>/decisions.md` 의 "grill-me #3" section 에 기록.

---

## Task 9: INITIAL_BETA 교체 (C9 if PASS) 또는 Issue 작성 (C9-alt if FAIL)

`validation_report.json` 의 `pass` field 가 결정.

### Task 9a: INITIAL_BETA 교체 (PASS 시 — C9)

**Files:**
- Modify: `tradingagents/skills/research/factor_to_bucket.py`
- Modify: `tests/unit/skills/research/test_factor_to_bucket.py` (INITIAL_BETA 의존 assertion update)

- [ ] **Step 1: best_shrinkage.json 으로부터 새 INITIAL_BETA 값 추출**

```bash
python -c "
import json
with open('artifacts/<run-date>/calibration_runs/best_shrinkage.json') as f:
    data = json.load(f)
print('Best shrinkage:', data['shrinkage'])
print('Mean OOS Sharpe:', data['mean_oos_sharpe'])
print('Median β:')
for k, v in sorted(data['median_beta'].items()):
    print(f'  {k}: {v:.4f}')
"
```

Output 으로부터 calibrated β 값 확인.

- [ ] **Step 2: factor_to_bucket.py 의 INITIAL_BETA 교체**

기존 `INITIAL_BETA: Final[dict[tuple[str, str], float]] = {...}` 의 모든 entry 를 calibrated 값으로 replace. Source-of-truth comment block 추가:

```python
# tradingagents/skills/research/factor_to_bucket.py:74 부근

# ---- INITIAL_BETA (calibrated 2026-05-XX via PR2a) ----
# Auto-generated from artifacts/2026-05-XX/calibration_runs/best_shrinkage.json
# Best shrinkage: <value from json>
# Mean OOS Sharpe: <value>, prior OOS Sharpe: <value>, improvement Δ: <delta>
# Paired-t p-value: <p>
# Acceptance gate: PASS (all 5 conditions)
# Diagnostic: vintage_sanity=<pass>, learning_sensitivity=<value>,
#             saturated_fraction=<value>, prior_stuck_fraction=<value>
# Pre-calibration (hand-coded) values archived in git history at commit <pre-C9 sha>.
INITIAL_BETA: Final[dict[tuple[str, str], float]] = {
    ("growth_surprise", "kr_equity"): <calibrated_value>,
    ("growth_surprise", "global_equity"): <calibrated_value>,
    # ... (모든 45 entry)
}
```

- [ ] **Step 3: INITIAL_BETA 의존 unit test 갱신**

`tests/unit/skills/research/test_factor_to_bucket.py` (그리고 기타 INITIAL_BETA 의 magnitude/sign 에 직접 의존하는 test 찾기):

```bash
grep -rn "INITIAL_BETA" tests/ 2>&1
```

찾은 test 들의 expected value 를 *calibrated* 값으로 update. 단순 `INITIAL_BETA` reference 는 변경 0 (import 가 새 값 가져옴). 직접 hardcoded magnitude assertion 만 update.

- [ ] **Step 4: regression test — 모든 production test PASS 확인**

```bash
uv run pytest tests/unit/ -q 2>&1 | tail -3
uv run pytest tests/integration/ -q 2>&1 | tail -3
```

Expected: pre-existing 3 + 18 fail 유지 + 직접 magnitude assertion 갱신한 test PASS.

만약 production integration test (e.g., `test_factor_estimators_real_schema.py`) 의 *factor z magnitude* 가 변하면 expected coverage 가 영향 받음 — 그러나 *β 변화* 는 `apply_factor_model` (factor z → bucket weight) 만 영향, factor z 자체는 변경 0. → integration test 영향 0 이어야 함.

- [ ] **Step 5: `regression_log.md` 의 "## Post-C9 (PASS path)" entry**

- [ ] **Step 6: commit**

```bash
git add tradingagents/skills/research/factor_to_bucket.py
git add tests/unit/skills/research/test_factor_to_bucket.py
git add artifacts/<run-date>/regression_log.md
git commit -m "$(cat <<'EOF'
feat(stage2): INITIAL_BETA replaced with calibrated values (C9, PASS path)

PR2a 의 walk-forward calibration acceptance gate PASS — INITIAL_BETA 의
45 entry 를 hand-coded → data-driven 으로 replace.

Calibration metadata (artifacts/<run-date>/calibration_runs/best_shrinkage.json):
- Best shrinkage: <value>
- Mean OOS Sharpe: <value> (prior: <value>, Δ: +<delta>)
- Paired-t p-value: <p>
- Diagnostic: vintage_sanity, learning_sensitivity, saturated_fraction,
  prior_stuck_fraction (all within acceptable range)

Backward compat:
- INITIAL_BETA dict 구조 변경 0 — 같은 key/value structure
- 모든 호출자 (apply_factor_model 등) interface 변경 0
- Production output (bucket weight) 만 변화 — 2026-05-15 regen 별도 PR2b
  또는 follow-up commit

Unit test (test_factor_to_bucket.py) 의 hardcoded magnitude assertion
갱신. PR1 의 모든 production test 0 new failure.

Pre-calibration values archived in git at <pre-C9 sha>.

EOF
)"
```

### Task 9b: Issue 작성 (FAIL 시 — C9-alt)

**Files:**
- Modify: `docs/followup_issues.md`

- [ ] **Step 1: validation_report.json 의 fail conditions 분석**

```bash
python -c "
import json
with open('artifacts/<run-date>/calibration_runs/validation_report.json') as f:
    v = json.load(f)
print('Pass:', v['pass'])
print('Failed conditions:')
for k, passed in v['conditions'].items():
    if not passed:
        print(f'  - {k}')
print('Mean OOS:', v['mean_oos_sharpe'])
print('Prior OOS:', v['prior_oos_sharpe'])
print('Improvement Δ:', v['improvement_delta'])
print('Paired-t p:', v['paired_t_p'])
print('Diagnostic:', json.dumps(v['diagnostic'], indent=2))
"
```

- [ ] **Step 2: docs/followup_issues.md 에 신규 Issue 작성**

Issue 번호는 `docs/followup_issues.md` 의 마지막 issue 번호 + 1 (현재 #23 이 last → #24 사용; 또는 grep 후 결정).

```bash
grep -E "^## Issue #" docs/followup_issues.md | tail -3
```

`docs/followup_issues.md` 의 끝에 추가:

```markdown
---

## Issue #<next> — PR2a calibration acceptance FAIL: design 재검토 필요

### Problem
PR2a 의 walk-forward calibration acceptance gate FAIL — INITIAL_BETA 교체
중단. validation_report.json (`artifacts/<run-date>/calibration_runs/`) 참조.

### Failed conditions
- [list from analysis]: e.g., improvement (mean OOS Δ = +0.02, paired-t p = 0.35),
  fold_positive (5/7 instead of 6/7), ...

### Verdict diagnostic
- Mean OOS Sharpe: <value>
- Prior OOS Sharpe: <value>
- Improvement Δ: <delta> (target ≥ +0.05)
- Paired-t p: <p> (target < 0.20)
- Vintage sanity: <pass/fail>
- Learning sensitivity: <value>
- Saturated fraction: <value>
- Prior-stuck fraction: <value>

### Suggested 재검토
1. Sample window 조정 — pre-2003 era 의 sparse confidence 가 noise 일 수
   있음. 2003-2024 window 로 재시도.
2. Shrinkage grid 확장 — current grid 의 best 가 boundary (0.1 또는 2.0) 면
   더 넓은 grid 필요.
3. Bucket return basis sensitivity — KRW basis 가 결과에 미치는 영향. PR2b
   에서 USD basis 도 시도.
4. Calibration target 확장 — β only 가 부족하면 β + baseline joint.
5. News component 의 historical scale 가 production 과 different — mode 의
   weight 정규화 logic 재검토.

### Effort
~10-20시간 (재검토 + 재실행)

### Priority
High — PR2b 진행 전 해결 필요.

### Dependencies
PR2a 의 calibration infrastructure (Task 1-8) 그대로 재사용.
```

- [ ] **Step 3: `regression_log.md` 의 "## Post-C9-alt (FAIL path)" entry**

- [ ] **Step 4: commit**

```bash
git add docs/followup_issues.md
git add artifacts/<run-date>/regression_log.md
git commit -m "$(cat <<'EOF'
docs(stage2a): calibration acceptance FAIL — Issue #<n> 작성 (C9-alt)

PR2a 의 walk-forward calibration acceptance gate FAIL.
validation_report.json (artifacts/<run-date>/calibration_runs/) 의 verdict
'pass: false'.

Failed conditions: <list>
- e.g., improvement: mean OOS Δ +0.02 < +0.05 target, paired-t p 0.35 > 0.20
- e.g., fold_positive: 5/7 < 6/7 strict default

INITIAL_BETA 교체 skip (hand-coded 유지).

docs/followup_issues.md 에 Issue #<n> 작성 — 재검토 방향 + suggested fix.

PR2a deliverable: acceptance verdict 까지 (per spec section 6.4).

EOF
)"
```

---

## Task 10: Documentation + Backlog Update (C10)

마지막 commit — spec status checkmark + decisions.md final + Issue #18 status update.

### Task 10.1: spec status checkmark

- [ ] **Step 1: spec doc 의 sign-off checklist update**

`docs/superpowers/specs/2026-05-23-stage2a-calibration-design.md` 의 "## 11. Sign-off Checklist" section:

PASS path 의 경우:
```markdown
## 11. Sign-off Checklist (FINAL — PR2a 완료)

- [x] 모든 unit + integration test pass — pre-existing 3 + 18 fail 유지, 0 new
- [x] C1-C5 의 fetcher + aggregate + builder + bucket_returns + factor z
      generation 모든 unit test pass
- [x] C4 의 mode='production' regression test PASS
- [x] C5 의 factor z coverage by era 검증
- [x] C8 의 35 calibration runs 완료 + validation_report.json
- [x] Acceptance gate PASS — 5 conditions all true
- [x] C9 의 INITIAL_BETA 교체 + production test update
- [x] 3 grill-me 세션 의 decision 기록 (decisions.md)
- [x] regression_log.md 매 commit entry
- [x] Issue #18 status RESOLVED
- [x] Critical 1-4 + minor M1-M5 처리 결과 documentation

**Status: PR2a COMPLETE — INITIAL_BETA 교체 PASS.**
```

FAIL path 의 경우:
```markdown
## 11. Sign-off Checklist (FINAL — PR2a FAIL path)

- [x] 모든 unit + integration test pass
- [x] C1-C8 infrastructure 완료
- [x] Acceptance gate FAIL — failed conditions: <list>
- [x] C9-alt 의 Issue #<n> 작성 — design 재검토 follow-up
- [x] 3 grill-me decision 기록
- [x] regression_log.md
- [x] Issue #18 status PARTIAL FAIL — see Issue #<n>

**Status: PR2a FAIL — INITIAL_BETA 유지, design 재검토 별도 PR.**
```

### Task 10.2: decisions.md final

- [ ] **Step 1: artifacts/<run-date>/decisions.md 의 final section 추가**

`artifacts/<run-date>/decisions.md` 의 끝에:

```markdown
## Final Status (PR2a 완료)

[PASS path]
- Acceptance: PASS (all 5 conditions)
- Best shrinkage: <value>
- Improvement Δ: +<delta>
- INITIAL_BETA: data-driven 교체 완료 (C9)

[FAIL path]
- Acceptance: FAIL (conditions: <list>)
- Issue #<n> 작성 → design 재검토 follow-up
- INITIAL_BETA: hand-coded 유지

3 grill-me 결정 모두 본 파일 의 grill-me #1 #2 #3 sections 에 기록.

## Critical issue 처리 결과
- C1 ALFRED vintage: completed (7 series fetched, vintage_sanity result: <pass/skipped>)
- C2 mode='historical': completed (test_production_mode_unchanged 100% PASS)
- C3 strict default gate: applied (paired-t + 0.30 overfit + 6/7 fold)
- C4 KRW basis bucket: applied (pre-1996 kr_equity NaN as expected)
```

### Task 10.3: Issue #18 status update

- [ ] **Step 1: docs/followup_issues.md 의 Issue #18 section update**

PASS path:
```markdown
## Issue #18 — factor model β 의 real historical fetch + production calibration

### Status (PR2a 완료, <run-date>)
- **RESOLVED**: PR2a 의 walk-forward calibration acceptance PASS.
- INITIAL_BETA 가 data-driven 으로 교체됨 (commit C9).
- Improvement Δ: +<value> over hand-coded prior, paired-t p < 0.20.
- 다음 단계: PR2b 의 benchmark 비교 + empirical superiority 통계 검증.
```

FAIL path:
```markdown
## Issue #18 — factor model β 의 real historical fetch + production calibration

### Status (PR2a FAIL, <run-date>)
- **PARTIAL FAIL**: PR2a 의 calibration infrastructure 완료, acceptance
  gate FAIL.
- INITIAL_BETA hand-coded 유지.
- Failed conditions: <list>.
- 후속: Issue #<n> 의 design 재검토.
```

### Task 10.4: Pre-commit regression + commit

- [ ] **Step 1: Final regression**

```bash
uv run pytest tests/unit/ -q 2>&1 | tail -3
uv run pytest tests/integration/ -q 2>&1 | tail -3
```

Expected: pre-existing 유지 + PR2a 의 모든 신규 test pass. 0 new failure.

- [ ] **Step 2: `regression_log.md` 의 "## Post-C10 (FINAL)" entry**

```markdown
## Post-C10 (FINAL — PR2a 완료)

Final regression:
- Unit: 3 pre-existing fail + N new pass (total +60 new test)
- Integration: 18 pre-existing fail + M new pass
- 0 new failure

PR2a status: [PASS / FAIL]
INITIAL_BETA: [data-driven / hand-coded 유지]
Spec sign-off: complete.
```

- [ ] **Step 3: commit**

```bash
git add docs/superpowers/specs/2026-05-23-stage2a-calibration-design.md
git add docs/followup_issues.md
git add artifacts/<run-date>/decisions.md
git add artifacts/<run-date>/regression_log.md
git commit -m "$(cat <<'EOF'
docs(stage2a): spec checkmark + decisions final + Issue #18 status (C10)

PR2a 의 final commit.

- docs/superpowers/specs/2026-05-23-stage2a-calibration-design.md:
  Section 11 Sign-off Checklist 의 모든 [ ] → [x]. Status: [PASS / FAIL].
- artifacts/<run-date>/decisions.md: final section 추가 — Critical 1-4 +
  M1-M5 처리 결과 + 3 grill-me decision summary.
- docs/followup_issues.md: Issue #18 status update (RESOLVED 또는
  PARTIAL FAIL → see Issue #<n>).
- artifacts/<run-date>/regression_log.md: Post-C10 final entry.

PR2a 종착점:
- Production INITIAL_BETA: [data-driven (PASS) / hand-coded 유지 (FAIL)]
- tradingagents/backtest/historical/: fetcher + builder + cache 완비
- factor_estimators.py mode='historical': PR2b 재사용 가능
- 135Q samples.parquet: PR2b input

다음 PR2b: benchmark 비교 (24-cell / 60-40 / 1-N / risk parity) + empirical
superiority 통계 검증 + 2026-05-15 산출물 regen.

EOF
)"
```

---

## Self-Review Checklist (Plan 자체)

본 plan 의 무결성 확인 — execution 전 살펴볼 항목:

- [ ] Spec section 0 (Q1-Q9 + Critical 1-4 + M1-M5) 의 모든 결정 이 어느 Task 에서 implement 되는지 명확. (Q4 walk-forward params → Task 6.1; Critical 1 ALFRED → Task 1.2; Critical 2 mode flag → Task 4; Critical 3 strict gate → Task 7.1; Critical 4 KRW basis → Task 3.2)
- [ ] Spec section 2.2 의 모든 신규 / modified file 이 Task 의 Files block 에 등장
- [ ] 11 commit (C0-C10 + C9-alt) 의 각각이 Task 0-Task 10 와 1:1 mapping
- [ ] 3 grill-me 시점 (Task 3.4, Task 5.4, Task 8.3) 의 marker 가 명시
- [ ] 각 Task 의 TDD pattern: 실패 test → 실행/fail 확인 → 최소 구현 → 실행/pass 확인 → commit
- [ ] Production code 의 backward-compat — Task 4 의 mode parameter default 'production' (regression test 강제)
- [ ] FAIL path 의 graceful handling — Task 9b 의 conditional commit (PR2a 의 deliverable 은 acceptance verdict 까지)
- [ ] Placeholder 없음: TODO/TBD/FIXME/"implement later" 없음

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-23-stage2a-calibration.md`.

User 는 brainstorming Q8 에서 **PR1 방식 — commit 순차 + grill-me 3회 + per-commit regression** (inline executing-plans) 를 선택했음. 따라서:

**REQUIRED SUB-SKILL** (다음 세션): `superpowers:executing-plans`

각 Task 0-10 을 순차 실행. Task 3.4 / Task 5.4 / Task 8.3 의 grill-me marker 에서 일시 멈춰 user 와 review 후 진행. Task 9 는 Task 8 의 acceptance verdict 에 따라 9a (PASS) 또는 9b (FAIL) 선택.

Long-session protocol (memory/feedback_long_session_protocol.md) 의 8 원칙 strict 적용:
- decisions.md / regression_log.md / job_status.json 외부화
- 매 commit 직전 grep + verify
- Critical 1-4 처리 결과 명시






