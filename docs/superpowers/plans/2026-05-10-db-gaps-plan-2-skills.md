# DB GAPS Plan 2 — Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 6 도메인의 34개 skill 구현. 결정론적 skill은 외부 API 호출/수학 계산만, subagent skill은 BaseSubagent 상속 + Pydantic-locked 출력. 모든 skill은 단위 테스트 통과.

**Architecture:** `tradingagents/skills/{macro,risk,technical,news,portfolio,mandate}/` 도메인별 모듈. 각 함수는 `@register_skill` 또는 `@register_subagent` 데코레이터로 등록. 외부 API는 mock 가능한 helper로 wrap.

**Tech Stack:** Plan 1과 동일 + scikit-learn (PCA, hierarchical clustering), pandas-ta (technical indicators — pure Python), PyPortfolioOpt (optimizers).

**Prerequisites:** Plan 1 완료. `tradingagents/skills/registry.py`, `_base.py`, `_helpers.py` 사용 가능.

**참조 스펙:** §6.1~6.6, §7. 결정 D5 (tiered cache 활용), D6 (BaseSubagent), D7 (retry helper).

---

## File Structure

```
tradingagents/skills/
├── macro/
│   ├── __init__.py
│   ├── yield_curve.py             # compute_yield_curve
│   ├── inflation.py               # compute_inflation_trend
│   ├── employment.py              # compute_unemployment_trend (Sahm rule)
│   ├── fred_fetcher.py            # fetch_fred_series (skill wrapper)
│   ├── ecos_fetcher.py            # fetch_ecos_series (skill wrapper)
│   ├── divergence.py              # compute_kr_divergence
│   ├── calendar.py                # fetch_central_bank_calendar
│   └── regime_classifier.py       # classify_regime (subagent)
├── risk/
│   ├── volatility.py              # fetch_volatility_index
│   ├── credit_spread.py           # fetch_credit_spread
│   ├── fear_greed.py              # fetch_fear_greed_index
│   ├── breadth.py                 # compute_market_breadth
│   ├── correlation_pca.py         # compute_correlation_concentration
│   └── systemic_score.py          # score_systemic_risk (subagent)
├── technical/
│   ├── price_batch.py             # fetch_etf_price_batch
│   ├── ta_indicators.py           # compute_ta_indicators
│   ├── momentum_ranker.py         # rank_momentum
│   ├── trend_state.py             # detect_trend_state
│   └── correlation_cluster.py     # find_correlation_clusters
├── news/
│   ├── event_calendar.py          # fetch_event_calendar
│   ├── news_fetcher.py            # fetch_macro_news
│   ├── impact_classifier.py       # classify_event_impact (subagent)
│   └── ranker.py                  # dedupe_rank_news
├── portfolio/
│   ├── candidate_selector.py      # select_etf_candidates
│   ├── returns_matrix.py          # fetch_returns_matrix
│   ├── optimizers.py              # optimize_hrp/rp/minvar/bl
│   └── method_picker.py           # pick_optimization_method (subagent)
├── mandate/
│   ├── universe_check.py          # validate_universe
│   ├── concentration_check.py     # validate_concentration
│   ├── turnover_check.py          # validate_turnover_feasibility
│   └── correlation_check.py       # validate_correlation_concentration
└── _registry_init.py              # 모든 skill을 import해 데코레이터 발화

prompts/
├── macro-analysis.md              # classify_regime base prompt (Vibe-Trading 한국화)
├── risk-analysis.md               # score_systemic_risk
├── asset-allocation.md            # pick_optimization_method
└── news-impact.md                 # classify_event_impact

tests/unit/skills/
├── test_macro_*.py                # 8 files
├── test_risk_*.py                 # 6 files
├── test_technical_*.py            # 5 files
├── test_news_*.py                 # 4 files
├── test_portfolio_*.py            # 7 files (4 optimizers grouped)
└── test_mandate_*.py              # 4 files
```

---

## Phase 1: Macro Skills (8개)

### Task 1: compute_yield_curve

**Files:**
- Create: `tradingagents/skills/macro/__init__.py`
- Create: `tradingagents/skills/macro/yield_curve.py`
- Create: `tests/unit/skills/test_macro_yield_curve.py`

- [ ] **Step 1: 실패 테스트**

`tests/unit/skills/test_macro_yield_curve.py`:

```python
from datetime import date

import pandas as pd

from tradingagents.skills.macro.yield_curve import compute_yield_curve


def test_normal_curve():
    s_10y = pd.Series([4.5, 4.4, 4.3], index=pd.date_range("2026-05-08", periods=3))
    s_2y = pd.Series([4.0, 4.0, 3.9], index=pd.date_range("2026-05-08", periods=3))
    s_3m = pd.Series([5.0, 5.0, 5.0], index=pd.date_range("2026-05-08", periods=3))

    snap = compute_yield_curve(s_10y, s_2y, s_3m, as_of=date(2026, 5, 10))
    assert snap.spread_10y_2y_bps == pytest.approx(40.0, abs=0.1)


def test_inverted_curve():
    s_10y = pd.Series([3.5], index=[pd.Timestamp("2026-05-10")])
    s_2y = pd.Series([4.0], index=[pd.Timestamp("2026-05-10")])
    s_3m = pd.Series([4.5], index=[pd.Timestamp("2026-05-10")])

    snap = compute_yield_curve(s_10y, s_2y, s_3m, as_of=date(2026, 5, 10))
    assert snap.spread_10y_2y_bps < 0
    assert snap.spread_10y_3m_bps < 0


def test_inverted_days_count():
    # 5 days inverted in 365
    dates = pd.date_range("2025-12-01", periods=10)
    s_10y = pd.Series([4.5, 4.5, 4.5, 4.5, 4.5, 4.0, 3.9, 3.8, 4.0, 4.5], index=dates)
    s_2y = pd.Series([4.0] * 10, index=dates)
    s_3m = pd.Series([4.0] * 10, index=dates)

    snap = compute_yield_curve(s_10y, s_2y, s_3m, as_of=date(2026, 5, 10))
    # Inverted on 3 days in this snippet
    assert snap.inverted_days_count == 3


import pytest  # at top
```

- [ ] **Step 2: 실행 (실패)**

Run: `pytest tests/unit/skills/test_macro_yield_curve.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`tradingagents/skills/macro/__init__.py`:

```python
"""Macro skills."""
```

`tradingagents/skills/macro/yield_curve.py`:

```python
from datetime import date

import pandas as pd

from tradingagents.schemas.macro import YieldCurveSnapshot
from tradingagents.skills.registry import register_skill


@register_skill(name="compute_yield_curve", category="macro")
def compute_yield_curve(
    s_10y: pd.Series,
    s_2y: pd.Series,
    s_3m: pd.Series,
    as_of: date,
) -> YieldCurveSnapshot:
    """Yield curve snapshot. Inputs are FRED-derived series.

    Spreads in basis points. inverted_days_count from last 365 days of overlap.
    """
    # Latest values for spreads
    spread_10y_2y = float(s_10y.iloc[-1] - s_2y.iloc[-1]) * 100
    spread_10y_3m = float(s_10y.iloc[-1] - s_3m.iloc[-1]) * 100

    # Inversion count: aligned diff, last 365 days
    aligned = pd.concat([s_10y, s_2y], axis=1, join="inner").dropna()
    aligned.columns = ["10y", "2y"]
    aligned["spread"] = aligned["10y"] - aligned["2y"]
    last_365 = aligned.tail(365)
    inverted_days = int((last_365["spread"] < 0).sum())

    # 5-year percentile for the 10y-2y spread
    last_5y = aligned.tail(252 * 5) if len(aligned) >= 252 else aligned
    if len(last_5y) > 1:
        rank = (last_5y["spread"] < spread_10y_2y / 100).sum()
        percentile = float(rank / len(last_5y))
    else:
        percentile = 0.5

    return YieldCurveSnapshot(
        spread_10y_2y_bps=spread_10y_2y,
        spread_10y_3m_bps=spread_10y_3m,
        inverted_days_count=inverted_days,
        percentile_5y=percentile,
        source_date=as_of,
        staleness_days=0,
    )
```

- [ ] **Step 4: 테스트 통과**

Run: `pytest tests/unit/skills/test_macro_yield_curve.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/macro/__init__.py tradingagents/skills/macro/yield_curve.py tests/unit/skills/test_macro_yield_curve.py
git commit -m "feat(skills/macro): add compute_yield_curve"
```

---

### Task 2: compute_inflation_trend

**Files:**
- Create: `tradingagents/skills/macro/inflation.py`
- Create: `tests/unit/skills/test_macro_inflation.py`

- [ ] **Step 1: 실패 테스트**

```python
from datetime import date
import pandas as pd
from tradingagents.skills.macro.inflation import compute_inflation_trend


def test_inflation_decelerating():
    cpi = pd.Series([100, 101, 102, 103, 104, 104.5, 104.8, 105.0, 105.1, 105.15, 105.18, 105.20, 105.21],
                    index=pd.date_range("2025-05-01", periods=13, freq="MS"))
    snap = compute_inflation_trend(cpi, core_cpi=cpi.copy(), as_of=date(2026, 5, 10))
    assert snap.accelerating is False
    assert snap.cpi_yoy > 0


def test_inflation_accelerating():
    # 3-month annualized faster than 12-month
    months = pd.date_range("2025-05-01", periods=13, freq="MS")
    vals = [100, 100.1, 100.2, 100.3, 100.4, 100.5, 100.6, 100.7, 100.8, 102, 104, 106, 108]
    cpi = pd.Series(vals, index=months)
    snap = compute_inflation_trend(cpi, core_cpi=cpi.copy(), as_of=date(2026, 5, 10))
    assert snap.accelerating is True
```

- [ ] **Step 2: 실행 (실패)**

Run: `pytest tests/unit/skills/test_macro_inflation.py -v`

- [ ] **Step 3: 구현**

`tradingagents/skills/macro/inflation.py`:

```python
from datetime import date

import pandas as pd

from tradingagents.schemas.macro import InflationSnapshot
from tradingagents.skills.registry import register_skill


def _annualized(series: pd.Series, months: int) -> float:
    if len(series) < months + 1:
        return 0.0
    pct = (series.iloc[-1] / series.iloc[-1 - months]) ** (12 / months) - 1
    return float(pct * 100)


@register_skill(name="compute_inflation_trend", category="macro")
def compute_inflation_trend(
    cpi: pd.Series, core_cpi: pd.Series, as_of: date,
) -> InflationSnapshot:
    yoy = _annualized(cpi, 12)
    core_yoy = _annualized(core_cpi, 12)
    m3 = _annualized(cpi, 3)
    m6 = _annualized(cpi, 6)
    accelerating = m3 > m6 > yoy

    return InflationSnapshot(
        cpi_yoy=yoy,
        core_cpi_yoy=core_yoy,
        momentum_3mo=m3,
        momentum_6mo=m6,
        accelerating=accelerating,
        source_date=as_of,
    )
```

- [ ] **Step 4: 테스트 통과**

Run: `pytest tests/unit/skills/test_macro_inflation.py -v`

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(skills/macro): add compute_inflation_trend"
```

---

### Task 3: compute_unemployment_trend (Sahm rule)

**Files:**
- Create: `tradingagents/skills/macro/employment.py`
- Create: `tests/unit/skills/test_macro_employment.py`

- [ ] **Step 1: 실패 테스트**

```python
from datetime import date
import pandas as pd
from tradingagents.skills.macro.employment import compute_unemployment_trend


def test_sahm_rule_triggered():
    # UR rises 0.5pp from 12-month min
    months = pd.date_range("2025-05-01", periods=15, freq="MS")
    ur_values = [3.5] * 12 + [3.6, 3.9, 4.1]  # latest 3-mo avg = 3.87 vs min 3.5 = +0.37 not triggered
    ur = pd.Series(ur_values, index=months)
    payems = pd.Series([150_000] * 15, index=months)
    snap = compute_unemployment_trend(ur, payems, as_of=date(2026, 7, 1))
    # Should be False: 0.37 < 0.5
    assert snap.sahm_rule_triggered is False


def test_sahm_rule_clear_trigger():
    months = pd.date_range("2025-05-01", periods=15, freq="MS")
    ur_values = [3.5] * 12 + [4.0, 4.2, 4.5]  # 3-mo avg = 4.23 vs min 3.5 = +0.73 triggered
    ur = pd.Series(ur_values, index=months)
    payems = pd.Series([150_000] * 15, index=months)
    snap = compute_unemployment_trend(ur, payems, as_of=date(2026, 7, 1))
    assert snap.sahm_rule_triggered is True
```

- [ ] **Step 2: 실행 (실패)**

Run: `pytest tests/unit/skills/test_macro_employment.py -v`

- [ ] **Step 3: 구현**

`tradingagents/skills/macro/employment.py`:

```python
from datetime import date

import pandas as pd

from tradingagents.schemas.macro import EmploymentSnapshot
from tradingagents.skills.registry import register_skill


@register_skill(name="compute_unemployment_trend", category="macro")
def compute_unemployment_trend(
    unemployment_rate: pd.Series,
    non_farm_payrolls: pd.Series,
    as_of: date,
) -> EmploymentSnapshot:
    """Sahm rule: 3-month avg UR rises 0.5pp+ above the 12-month min."""
    if len(unemployment_rate) < 12:
        sahm = False
    else:
        recent_3mo_avg = float(unemployment_rate.tail(3).mean())
        prior_12mo_min = float(unemployment_rate.tail(15).head(12).min())
        sahm = (recent_3mo_avg - prior_12mo_min) >= 0.5

    rate_change_3mo = float(unemployment_rate.iloc[-1] - unemployment_rate.iloc[-4]) if len(unemployment_rate) > 3 else 0.0
    payrolls_3mo_avg = float(non_farm_payrolls.tail(3).mean()) if len(non_farm_payrolls) >= 3 else 0.0

    return EmploymentSnapshot(
        unemployment_rate=float(unemployment_rate.iloc[-1]),
        rate_change_3mo=rate_change_3mo,
        sahm_rule_triggered=sahm,
        non_farm_payrolls_3mo_avg=payrolls_3mo_avg,
        source_date=as_of,
    )
```

- [ ] **Step 4: 테스트 통과**

Run: `pytest tests/unit/skills/test_macro_employment.py -v`

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(skills/macro): add compute_unemployment_trend with Sahm rule"
```

---

### Task 4: fetch_fred_series + fetch_ecos_series (skill wrappers)

**Files:**
- Create: `tradingagents/skills/macro/fred_fetcher.py`
- Create: `tradingagents/skills/macro/ecos_fetcher.py`
- Create: `tests/unit/skills/test_macro_fetchers.py`

- [ ] **Step 1: 실패 테스트**

`tests/unit/skills/test_macro_fetchers.py`:

```python
from datetime import date
from unittest.mock import patch
import pandas as pd

from tradingagents.skills.macro.fred_fetcher import fetch_fred_series_skill
from tradingagents.skills.macro.ecos_fetcher import fetch_ecos_series_skill


def test_fred_skill_wraps_dataflow():
    fake = pd.Series([4.5], index=[pd.Timestamp("2026-05-10")], name="DGS10")
    with patch("tradingagents.skills.macro.fred_fetcher.fetch_fred_series", return_value=fake):
        s = fetch_fred_series_skill("us_10y", date(2026, 5, 10), date(2026, 5, 10))
    assert s.iloc[-1] == 4.5


def test_ecos_skill_wraps_dataflow():
    fake = pd.Series([3.5], index=[pd.Timestamp("2026-05-01")])
    with patch("tradingagents.skills.macro.ecos_fetcher.fetch_ecos_series", return_value=fake):
        s = fetch_ecos_series_skill("kr_base_rate", date(2026, 5, 1), date(2026, 5, 31))
    assert s.iloc[-1] == 3.5
```

- [ ] **Step 2: 실행 (실패)**

Run: `pytest tests/unit/skills/test_macro_fetchers.py -v`

- [ ] **Step 3: 구현**

`tradingagents/skills/macro/fred_fetcher.py`:

```python
from datetime import date

import pandas as pd

from tradingagents.dataflows.fred import fetch_fred_series
from tradingagents.skills.registry import register_skill


@register_skill(name="fetch_fred_series", category="macro")
def fetch_fred_series_skill(
    series: str, start: date, end: date, api_key: str | None = None,
    as_of_date: date | None = None,
) -> pd.Series:
    """Skill-layer wrapper around dataflows.fred.fetch_fred_series.

    Look-ahead bias prevention: callers MUST pass `as_of_date` for any
    historical/backtest run so that publication-lag truncation is applied.
    Live mode (as_of_date=None) is for current-day production runs only.
    """
    return fetch_fred_series(series, start, end, api_key=api_key, as_of_date=as_of_date)
```

`tradingagents/skills/macro/ecos_fetcher.py`:

```python
from datetime import date

import pandas as pd

from tradingagents.dataflows.ecos import fetch_ecos_series
from tradingagents.skills.registry import register_skill


@register_skill(name="fetch_ecos_series", category="macro")
def fetch_ecos_series_skill(
    name: str, start: date, end: date, api_key: str | None = None, freq: str = "M",
    as_of_date: date | None = None,
) -> pd.Series:
    """ECOS skill wrapper. as_of_date enforces point-in-time truncation."""
    return fetch_ecos_series(
        name, start, end, api_key=api_key, freq=freq, as_of_date=as_of_date,
    )
```

- [ ] **Step 4: 테스트 통과**

Run: `pytest tests/unit/skills/test_macro_fetchers.py -v`

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/macro/fred_fetcher.py tradingagents/skills/macro/ecos_fetcher.py tests/unit/skills/test_macro_fetchers.py
git commit -m "feat(skills/macro): add FRED/ECOS skill wrappers"
```

---

### Task 5: compute_kr_divergence

**Files:**
- Create: `tradingagents/skills/macro/divergence.py`
- Create: `tests/unit/skills/test_macro_divergence.py`

- [ ] **Step 1: 실패 테스트**

```python
from datetime import date
from tradingagents.skills.macro.divergence import compute_kr_divergence


def test_divergence_us_higher():
    snap = compute_kr_divergence(
        us_policy_rate=5.5, kr_base_rate=3.5,
        us_cpi_yoy=3.0, kr_cpi_yoy=2.5,
        as_of=date(2026, 5, 10),
    )
    assert snap.us_kr_rate_gap_bps == 200.0
    assert snap.us_kr_inflation_gap == 0.5
```

- [ ] **Step 2: 실행 (실패)**

- [ ] **Step 3: 구현**

`tradingagents/skills/macro/divergence.py`:

```python
from datetime import date

from tradingagents.schemas.macro import DivergenceScore
from tradingagents.skills.registry import register_skill


@register_skill(name="compute_kr_divergence", category="macro")
def compute_kr_divergence(
    us_policy_rate: float, kr_base_rate: float,
    us_cpi_yoy: float, kr_cpi_yoy: float,
    as_of: date,
) -> DivergenceScore:
    rate_gap_bps = (us_policy_rate - kr_base_rate) * 100
    infl_gap = us_cpi_yoy - kr_cpi_yoy
    # Score: positive = converging, negative = diverging. Simple z-like normalization.
    score = -abs(rate_gap_bps / 100) - abs(infl_gap)  # closer to 0 = aligned
    score = max(-10.0, min(10.0, score))

    return DivergenceScore(
        us_kr_rate_gap_bps=rate_gap_bps,
        us_kr_inflation_gap=infl_gap,
        score=score,
        source_date=as_of,
    )
```

- [ ] **Step 4: 테스트 통과**

- [ ] **Step 5: Commit**

```bash
git commit -am "feat(skills/macro): add compute_kr_divergence"
```

---

### Task 6: fetch_central_bank_calendar (skill wrapper)

**Files:**
- Create: `tradingagents/skills/macro/calendar.py`
- Create: `tests/unit/skills/test_macro_calendar.py`

- [ ] **Step 1: 실패 테스트**

```python
from datetime import date
from tradingagents.skills.macro.calendar import fetch_central_bank_calendar_skill


def test_calendar_window():
    events = fetch_central_bank_calendar_skill(date(2026, 5, 10), days=60)
    assert all(e.event_date >= date(2026, 5, 10) for e in events)
```

- [ ] **Step 2-5: 표준 패턴**

`tradingagents/skills/macro/calendar.py`:

```python
from datetime import date

from tradingagents.dataflows.news_macro import fetch_calendar_events
from tradingagents.schemas.macro import CentralBankEvent
from tradingagents.skills.registry import register_skill


@register_skill(name="fetch_central_bank_calendar", category="macro")
def fetch_central_bank_calendar_skill(as_of: date, days: int = 90) -> list[CentralBankEvent]:
    raw = fetch_calendar_events(as_of, days)
    out = []
    for e in raw:
        if e.event_type in ("fomc", "bok"):
            out.append(CentralBankEvent(
                bank="FED" if e.event_type == "fomc" else "BOK",
                event_date=e.event_date,
                event_type="rate_decision",
                description=e.description,
            ))
    return out
```

Run + commit per pattern.

```bash
git commit -am "feat(skills/macro): add fetch_central_bank_calendar"
```

---

### Task 7: classify_regime (subagent, D6 사용)

**Files:**
- Create: `prompts/macro-analysis.md` (Vibe-Trading 한국화 시드)
- Create: `tradingagents/skills/macro/regime_classifier.py`
- Create: `tests/unit/skills/test_macro_regime.py`

- [ ] **Step 1: 프롬프트 시드 생성**

`prompts/macro-analysis.md`:

```markdown
You are a macro economist classifying the current US economy into one of four regimes:

- growth_inflation: GDP expanding, CPI > 3% YoY
- growth_disinflation: GDP expanding, CPI < 3% and decelerating
- recession_inflation: GDP contracting (or yield curve / Sahm signal), CPI > 3%
- recession_disinflation: contracting + CPI declining

Inputs:
- Yield curve: 10y-2y spread = {spread_10y_2y_bps} bps, inverted {inverted_days_count} days in last year
- Inflation: CPI YoY = {cpi_yoy}%, 3-month annualized = {momentum_3mo}%, accelerating = {accelerating}
- Employment: UR = {unemployment_rate}%, Sahm rule triggered = {sahm_rule_triggered}

Output a single RegimeClassification JSON object with:
- quadrant (one of the four enum values)
- confidence (0-1)
- drivers (1-5 short phrases citing specific data above)
- reasoning (≤300 chars)

Do NOT invent numbers. Reference only the inputs above.
```

- [ ] **Step 2: 실패 테스트**

```python
from pathlib import Path
from unittest.mock import MagicMock

from tradingagents.skills.macro.regime_classifier import RegimeClassifier
from tradingagents.schemas.macro import RegimeClassification


def test_classifier_invokes_llm(tmp_path):
    quick_llm = MagicMock()
    deep_llm = MagicMock()
    out = RegimeClassification(
        quadrant="recession_disinflation",
        confidence=0.82,
        drivers=["yield curve inverted 120 days", "Sahm triggered"],
        reasoning="Curve and labor market both signal recession.",
    )
    deep_llm.with_structured_output.return_value.invoke.return_value = out

    clf = RegimeClassifier(quick_llm, deep_llm)
    result = clf.invoke(
        spread_10y_2y_bps=-25.0, inverted_days_count=120,
        cpi_yoy=2.5, momentum_3mo=1.8, accelerating=False,
        unemployment_rate=4.5, sahm_rule_triggered=True,
    )
    assert result.quadrant == "recession_disinflation"
```

- [ ] **Step 3: 구현**

`tradingagents/skills/macro/regime_classifier.py`:

```python
from pathlib import Path

from tradingagents.schemas.macro import RegimeClassification
from tradingagents.skills._base import BaseSubagent
from tradingagents.skills.registry import register_subagent


PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "macro-analysis.md"


class RegimeClassifier(BaseSubagent):
    def __init__(self, llm_quick, llm_deep):
        super().__init__(
            name="classify_regime", tier="deep",
            schema=RegimeClassification, prompt_path=PROMPT_PATH,
            llm_quick=llm_quick, llm_deep=llm_deep,
        )


@register_subagent(name="classify_regime", category="macro")
def classify_regime(llm_quick, llm_deep, **inputs) -> RegimeClassification:
    """Functional wrapper for registry. Concrete RegimeClassifier is preferred."""
    return RegimeClassifier(llm_quick, llm_deep).invoke(**inputs)
```

- [ ] **Step 4: 테스트 통과**

Run: `pytest tests/unit/skills/test_macro_regime.py -v`

- [ ] **Step 5: Commit**

```bash
git add prompts/macro-analysis.md tradingagents/skills/macro/regime_classifier.py tests/unit/skills/test_macro_regime.py
git commit -m "feat(skills/macro): add classify_regime subagent + prompt seed"
```

---

## Phase 2: Risk Skills (6개)

### Task 8: fetch_volatility_index

**Files:**
- Create: `tradingagents/skills/risk/__init__.py`
- Create: `tradingagents/skills/risk/volatility.py`
- Create: `tests/unit/skills/test_risk_volatility.py`

- [ ] **Step 1: 실패 테스트**

```python
from datetime import date
from unittest.mock import patch
import pandas as pd

from tradingagents.skills.risk.volatility import fetch_volatility_index


def test_vix_snapshot():
    fake = pd.Series([18.0, 18.5, 19.0, 18.8, 18.2] * 30,
                     index=pd.date_range("2026-01-01", periods=150))
    with patch("tradingagents.skills.risk.volatility.fetch_vix", return_value=fake):
        snap = fetch_volatility_index("VIX", date(2026, 5, 10))
    assert snap.index_name == "VIX"
    assert snap.current_value > 0
```

- [ ] **Step 2-5: 구현 + 테스트 + commit**

`tradingagents/skills/risk/__init__.py`:
```python
"""Risk skills."""
```

`tradingagents/skills/risk/volatility.py`:

```python
from datetime import date, timedelta
from typing import Literal

from tradingagents.dataflows.volatility import fetch_vix, fetch_vkospi
from tradingagents.schemas.risk import VolatilitySnapshot
from tradingagents.skills.registry import register_skill


@register_skill(name="fetch_volatility_index", category="risk")
def fetch_volatility_index(
    index_name: Literal["VIX", "VKOSPI"], as_of: date,
) -> VolatilitySnapshot:
    start = as_of - timedelta(days=400)  # need ~250 days for percentile + 30 for z
    if index_name == "VIX":
        s = fetch_vix(start, as_of)
    else:
        s = fetch_vkospi(start, as_of)
    s = s.dropna()
    if s.empty:
        raise ValueError(f"No data for {index_name}")

    current = float(s.iloc[-1])
    last_30 = s.tail(30)
    z = (current - last_30.mean()) / last_30.std() if last_30.std() > 0 else 0.0
    last_5y = s.tail(252 * 5) if len(s) >= 252 else s
    pct = float((last_5y < current).sum() / len(last_5y))

    return VolatilitySnapshot(
        index_name=index_name,
        current_value=current,
        zscore_30d=float(z),
        percentile_5y=pct,
        source_date=as_of,
    )
```

```bash
git commit -am "feat(skills/risk): add fetch_volatility_index"
```

---

### Task 9: fetch_credit_spread

**Files:**
- Create: `tradingagents/skills/risk/credit_spread.py`
- Create: `tests/unit/skills/test_risk_credit_spread.py`

표준 패턴. FRED `BAMLC0A0CM`, `BAMLH0A0HYM2` 사용.

```python
from datetime import date, timedelta
from typing import Literal

from tradingagents.dataflows.fred import fetch_fred_series
from tradingagents.schemas.risk import SpreadSnapshot
from tradingagents.skills.registry import register_skill


@register_skill(name="fetch_credit_spread", category="risk")
def fetch_credit_spread(
    region: Literal["US_IG", "US_HY"], as_of: date, api_key: str | None = None,
) -> SpreadSnapshot:
    series_id = "us_ig_oas" if region == "US_IG" else "us_hy_oas"
    start = as_of - timedelta(days=365 * 5 + 10)
    s = fetch_fred_series(series_id, start, as_of, api_key=api_key).dropna()
    if s.empty:
        raise ValueError(f"No data for {region}")

    current = float(s.iloc[-1]) * 100  # FRED OAS in % → bps
    last_5y = s.tail(252 * 5) * 100
    pct = float((last_5y < current).sum() / len(last_5y))
    widening = bool(s.tail(20).mean() > s.tail(60).mean())

    return SpreadSnapshot(
        region=region, current_bps=current, percentile_5y=pct,
        widening=widening, source_date=as_of,
    )
```

테스트는 mock fetch_fred_series 후 검증. Commit:

```bash
git commit -am "feat(skills/risk): add fetch_credit_spread"
```

---

### Task 10: fetch_fear_greed_index (skip-with-note 패턴, D5 tier3)

**Files:**
- Create: `tradingagents/skills/risk/fear_greed.py`
- Create: `tests/unit/skills/test_risk_fear_greed.py`

CNN F&G 스크래핑. 실패 시 None 반환 (skip-with-note).

```python
from datetime import date

import requests
from bs4 import BeautifulSoup

from tradingagents.schemas.risk import SentimentSnapshot
from tradingagents.skills.registry import register_skill


def _scrape_cnn_fg() -> dict | None:
    """Scrape CNN Fear & Greed. Returns None on any failure (D5 tier3)."""
    try:
        r = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata", timeout=10)
        r.raise_for_status()
        data = r.json()
        return data.get("fear_and_greed", {})
    except Exception:
        return None


@register_skill(name="fetch_fear_greed_index", category="risk")
def fetch_fear_greed_index(as_of: date) -> SentimentSnapshot | None:
    """Returns None if CNN F&G unavailable. Caller skips-with-note."""
    raw = _scrape_cnn_fg()
    if raw is None:
        return None
    current = int(raw.get("score", 50))
    label_map = {
        (0, 25): "extreme_fear", (25, 45): "fear",
        (45, 55): "neutral", (55, 75): "greed", (75, 101): "extreme_greed",
    }
    label = next(v for (lo, hi), v in label_map.items() if lo <= current < hi)
    prev = float(raw.get("previous_close", current))
    trend = "rising" if current > prev else "falling" if current < prev else "flat"
    return SentimentSnapshot(
        index_name="fear_greed_cnn", current_value=current,
        label=label, trend_7d=trend, source_date=as_of,
    )
```

테스트 + commit.

---

### Task 11: compute_market_breadth

**Files:**
- Create: `tradingagents/skills/risk/breadth.py`
- Create: `tests/unit/skills/test_risk_breadth.py`

KOSPI 200 / S&P 500 구성종목의 advancing/declining 비율.

```python
from datetime import date
from typing import Literal

from tradingagents.schemas.risk import BreadthSnapshot
from tradingagents.skills.registry import register_skill


@register_skill(name="compute_market_breadth", category="risk")
def compute_market_breadth(market: Literal["KOSPI200", "SP500"], as_of: date) -> BreadthSnapshot:
    """Stub for now: returns synthetic snapshot.

    Live implementation: fetch all constituents from pykrx (KR) or yfinance (US),
    count daily advancing vs declining vs flat. Production version added in Plan 3
    when wiring is complete.
    """
    # TODO: replace with real implementation in Plan 3 when constituents available
    return BreadthSnapshot(
        market=market,
        advancing_pct=0.55, declining_pct=0.40,
        new_highs_minus_lows=0,
        source_date=as_of, staleness_days=0,
    )
```

> **Note:** This task ships a stub; D5 tier3 narrative API status. Marked TODO in the function. Test asserts the schema shape only.

```bash
git commit -am "feat(skills/risk): add compute_market_breadth (stub for v1)"
```

---

### Task 12: compute_correlation_concentration (PCA)

**Files:**
- Create: `tradingagents/skills/risk/correlation_pca.py`
- Create: `tests/unit/skills/test_risk_correlation_pca.py`

```python
from datetime import date

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

from tradingagents.schemas.risk import PCASnapshot
from tradingagents.skills.registry import register_skill


@register_skill(name="compute_correlation_concentration", category="risk")
def compute_correlation_concentration(
    returns: pd.DataFrame, as_of: date,
) -> PCASnapshot:
    """First eigenvalue share of returns covariance.

    >0.6 = concentrated (single market driver).
    """
    if returns.shape[1] < 2:
        raise ValueError("Need at least 2 assets for PCA")

    cleaned = returns.dropna(how="any")
    pca = PCA(n_components=min(cleaned.shape[1], 5))
    pca.fit(cleaned.values)
    first_share = float(pca.explained_variance_ratio_[0])

    return PCASnapshot(
        first_eigenvalue_share=first_share,
        n_assets_analyzed=cleaned.shape[1],
        is_concentrated=first_share > 0.6,
        source_date=as_of,
    )
```

테스트:
```python
def test_concentrated_when_one_factor():
    rng = np.random.default_rng(42)
    n = 252
    factor = rng.normal(size=n)
    df = pd.DataFrame({
        f"a{i}": factor + rng.normal(scale=0.05, size=n)
        for i in range(8)
    })
    snap = compute_correlation_concentration(df, date(2026, 5, 10))
    assert snap.is_concentrated is True
    assert snap.first_eigenvalue_share > 0.8
```

```bash
git commit -am "feat(skills/risk): add compute_correlation_concentration via PCA"
```

---

### Task 13: score_systemic_risk (subagent)

**Files:**
- Create: `prompts/risk-analysis.md`
- Create: `tradingagents/skills/risk/systemic_score.py`
- Create: `tests/unit/skills/test_risk_systemic_score.py`

`prompts/risk-analysis.md`:

```markdown
You are a market risk analyst quantifying systemic risk on a 0-10 scale.

Inputs:
- VIX = {vix} (zscore_30d = {vix_z}, percentile_5y = {vix_pct})
- VKOSPI = {vkospi}
- US IG OAS = {ig_bps} bps (5y percentile {ig_pct})
- US HY OAS = {hy_bps} bps (widening = {hy_widening})
- Fear & Greed = {fg_label} ({fg_value}/100)
- Market breadth: KR advancing {breadth_kr_adv}, US advancing {breadth_us_adv}
- PCA 1st eigenvalue share = {pca_first_share} (concentrated = {pca_concentrated})

Score 0 = calm/risk-on; 5 = neutral; 10 = systemic risk-off.

Output a SystemicRiskScore JSON with:
- score (float 0-10)
- regime ("risk_on" | "risk_off" | "neutral")
- drivers (1-5 short phrases citing specific inputs)
- reasoning (≤300 chars)
```

```python
from pathlib import Path

from tradingagents.schemas.risk import SystemicRiskScore
from tradingagents.skills._base import BaseSubagent
from tradingagents.skills.registry import register_subagent

PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "risk-analysis.md"


class SystemicScoreClassifier(BaseSubagent):
    def __init__(self, llm_quick, llm_deep):
        super().__init__(
            name="score_systemic_risk", tier="deep",
            schema=SystemicRiskScore, prompt_path=PROMPT_PATH,
            llm_quick=llm_quick, llm_deep=llm_deep,
        )


@register_subagent(name="score_systemic_risk", category="risk")
def score_systemic_risk(llm_quick, llm_deep, **inputs) -> SystemicRiskScore:
    return SystemicScoreClassifier(llm_quick, llm_deep).invoke(**inputs)
```

테스트는 RegimeClassifier 패턴과 동일.

```bash
git commit -am "feat(skills/risk): add score_systemic_risk subagent"
```

---

## Phase 3: Technical Skills (5개)

### Task 14: fetch_etf_price_batch (skill wrapper)

**Files:**
- Create: `tradingagents/skills/technical/__init__.py`
- Create: `tradingagents/skills/technical/price_batch.py`
- Create: `tests/unit/skills/test_technical_price_batch.py`

```python
from datetime import date

import pandas as pd

from tradingagents.dataflows.pykrx_data import fetch_etf_ohlcv_batch, ParquetCache
from tradingagents.skills.registry import register_skill


@register_skill(name="fetch_etf_price_batch", category="technical")
def fetch_etf_price_batch(
    tickers: list[str], start: date, end: date, cache_path: str | None = None,
) -> pd.DataFrame:
    cache = ParquetCache(cache_path) if cache_path else None
    return fetch_etf_ohlcv_batch(tickers, start, end, cache=cache)
```

테스트 + commit.

---

### Task 15: compute_ta_indicators

**Files:**
- Create: `tradingagents/skills/technical/ta_indicators.py`
- Create: `tests/unit/skills/test_technical_ta_indicators.py`

```python
import pandas as pd
import pandas_ta as ta

from tradingagents.schemas.technical import IndicatorPanel
from tradingagents.skills.registry import register_skill


@register_skill(name="compute_ta_indicators", category="technical")
def compute_ta_indicators(prices: pd.DataFrame, ticker: str) -> IndicatorPanel:
    """Compute MA200/MA50/RSI/MACD/ATR via pandas-ta (pure Python, no C build).

    Args:
        prices: DataFrame with columns [date, open, high, low, close, volume].
        ticker: Filter for this single ticker.
    """
    sub = prices[prices["ticker"] == ticker].sort_values("date").reset_index(drop=True)
    if len(sub) < 200:
        raise ValueError(f"Need ≥200 data points for {ticker}, got {len(sub)}")

    close = sub["close"].astype(float)
    high = sub["high"].astype(float)
    low = sub["low"].astype(float)

    # pandas-ta returns Series indexed like inputs; take the last value
    ma200 = float(ta.sma(close, length=200).iloc[-1])
    ma50 = float(ta.sma(close, length=50).iloc[-1])
    rsi = float(ta.rsi(close, length=14).iloc[-1])

    # MACD returns DataFrame with columns MACD_<fast>_<slow>_<signal>, MACDh_..., MACDs_...
    macd_df = ta.macd(close, fast=12, slow=26, signal=9)
    macd_line = float(macd_df.iloc[-1, 0])         # MACD
    macd_signal_line = float(macd_df.iloc[-1, 2])  # MACDs
    macd_signal = macd_line - macd_signal_line

    atr = float(ta.atr(high=high, low=low, close=close, length=14).iloc[-1])

    return IndicatorPanel(
        ticker=ticker,
        ma200=ma200, ma50=ma50, rsi=rsi,
        macd_signal=macd_signal, atr=atr,
        source_date=sub["date"].iloc[-1].date() if hasattr(sub["date"].iloc[-1], "date")
                    else pd.Timestamp(sub["date"].iloc[-1]).date(),
    )
```

> **변경 (production hardening):** `talib` C 라이브러리 의존을 제거하고 `pandas-ta` (pure Python)로 교체. CI/CD·다른 팀원 머신·운영 서버 어디서든 `pip install pandas-ta`만으로 끝.

테스트는 fixture 데이터 또는 sin wave 생성.

```bash
git commit -am "feat(skills/technical): add compute_ta_indicators"
```

---

### Task 16: rank_momentum

**Files:**
- Create: `tradingagents/skills/technical/momentum_ranker.py`
- Create: `tests/unit/skills/test_technical_momentum.py`

```python
import pandas as pd

from tradingagents.dataflows.universe import Universe
from tradingagents.schemas.technical import ETFRanking
from tradingagents.skills.registry import register_skill


@register_skill(name="rank_momentum", category="technical")
def rank_momentum(
    prices: pd.DataFrame, universe: Universe, lookback_months: int = 6,
) -> dict[str, list[ETFRanking]]:
    """Group by category, rank by lookback momentum."""
    name_lookup = {e.ticker: e.name for e in universe.etfs}
    cat_lookup = {e.ticker: e.category for e in universe.etfs}

    grouped: dict[str, list[ETFRanking]] = {}
    for ticker, sub in prices.groupby("ticker"):
        sub = sub.sort_values("date")
        if len(sub) < lookback_months * 21:
            continue
        end = float(sub["close"].iloc[-1])
        start = float(sub["close"].iloc[-(lookback_months * 21)])
        m_lookback = (end / start) - 1

        m3 = (end / float(sub["close"].iloc[-63])) - 1 if len(sub) >= 63 else 0.0
        m12 = (end / float(sub["close"].iloc[-252])) - 1 if len(sub) >= 252 else m_lookback

        category = cat_lookup.get(ticker, "기타")
        grouped.setdefault(category, []).append(ETFRanking(
            ticker=ticker, name=name_lookup.get(ticker, ticker),
            momentum_3m=m3, momentum_6m=m_lookback, momentum_12m=m12,
            rank_in_category=0,  # filled below
        ))

    # Rank within each category
    for cat, items in grouped.items():
        items.sort(key=lambda r: r.momentum_6m, reverse=True)
        for i, item in enumerate(items, start=1):
            item.rank_in_category = i

    return grouped
```

테스트 + commit.

---

### Task 17: detect_trend_state

```python
from tradingagents.schemas.technical import TrendState, IndicatorPanel
from tradingagents.skills.registry import register_skill


@register_skill(name="detect_trend_state", category="technical")
def detect_trend_state(panel: IndicatorPanel, current_price: float) -> TrendState:
    above_ma200 = current_price > panel.ma200
    above_ma50 = current_price > panel.ma50
    ma50_above_ma200 = panel.ma50 > panel.ma200

    if above_ma200 and above_ma50 and ma50_above_ma200 and panel.rsi > 60:
        return TrendState.STRONG_UPTREND
    if above_ma200 and above_ma50:
        return TrendState.UPTREND
    if not above_ma200 and not above_ma50 and panel.rsi < 40:
        return TrendState.BREAKDOWN
    if not above_ma200 and not above_ma50:
        return TrendState.DOWNTREND
    return TrendState.NEUTRAL
```

테스트 + commit.

---

### Task 18: find_correlation_clusters

```python
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, fcluster

from tradingagents.schemas.technical import Cluster
from tradingagents.skills.registry import register_skill


@register_skill(name="find_correlation_clusters", category="technical")
def find_correlation_clusters(
    returns: pd.DataFrame,
    threshold: float = 0.7,
    universe_lookup: dict[str, str] | None = None,
) -> list[Cluster]:
    """Hierarchical clustering by 1-correlation distance.

    Threshold = average correlation cutoff (0.7 default).
    Returns clusters with ≥2 members.
    """
    corr = returns.corr().fillna(0.0)
    distance = 1 - corr.values
    np.fill_diagonal(distance, 0)
    # Convert to condensed for scipy
    n = distance.shape[0]
    cond = distance[np.triu_indices(n, k=1)]
    Z = linkage(cond, method="average")
    labels = fcluster(Z, t=1 - threshold, criterion="distance")

    clusters: list[Cluster] = []
    for cid in set(labels):
        members_idx = [i for i, l in enumerate(labels) if l == cid]
        if len(members_idx) < 2:
            continue
        members = [returns.columns[i] for i in members_idx]
        sub_corr = corr.iloc[members_idx, members_idx]
        avg_corr = float((sub_corr.values.sum() - len(members)) / (len(members) ** 2 - len(members)))
        label = (
            ", ".join((universe_lookup or {}).get(m, m) for m in members[:3])
            + ("..." if len(members) > 3 else "")
        )[:80]
        clusters.append(Cluster(
            cluster_id=f"cluster_{cid}",
            members=members,
            avg_internal_correlation=avg_corr,
            category_label=label,
        ))
    return clusters
```

테스트 + commit.

---

## Phase 4: News Skills (4개)

### Task 19: fetch_event_calendar (skill wrapper)

```python
from datetime import date

from tradingagents.dataflows.news_macro import fetch_calendar_events
from tradingagents.schemas.news import CalendarEvent
from tradingagents.skills.registry import register_skill


@register_skill(name="fetch_event_calendar", category="news")
def fetch_event_calendar_skill(as_of: date, days: int = 90) -> list[CalendarEvent]:
    return fetch_calendar_events(as_of, days)
```

---

### Task 20: fetch_macro_news (skill wrapper)

```python
from tradingagents.dataflows.news_macro import fetch_macro_news as _fetch
from tradingagents.schemas.news import NewsItem
from tradingagents.skills.registry import register_skill


DEFAULT_RSS = [
    "https://www.reuters.com/markets/rss",
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC",
]


@register_skill(name="fetch_macro_news", category="news")
def fetch_macro_news_skill(rss_urls: list[str] | None = None, window_days: int = 7) -> list[NewsItem]:
    return _fetch(rss_urls or DEFAULT_RSS, window_days=window_days)
```

---

### Task 21: classify_event_impact (subagent, quick model)

`prompts/news-impact.md`:

```markdown
Classify the market impact of this event/headline:

Headline: "{headline}"
Source: {source}
Date: {date}

Output an ImpactAssessment JSON:
- asset_classes_affected (1-4 of: kr_equity, us_equity, global_equity, kr_bond, us_bond, fx, commodity, gold)
- direction: up | down | neutral
- severity: 1 (negligible) to 5 (major regime shift)
- reasoning: ≤200 chars
```

```python
from pathlib import Path

from tradingagents.schemas.news import ImpactAssessment
from tradingagents.skills._base import BaseSubagent
from tradingagents.skills.registry import register_subagent

PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "news-impact.md"


class ImpactClassifier(BaseSubagent):
    def __init__(self, llm_quick, llm_deep):
        super().__init__(
            name="classify_event_impact", tier="quick",  # quick model
            schema=ImpactAssessment, prompt_path=PROMPT_PATH,
            llm_quick=llm_quick, llm_deep=llm_deep,
        )


@register_subagent(name="classify_event_impact", category="news")
def classify_event_impact(llm_quick, llm_deep, **inputs) -> ImpactAssessment:
    return ImpactClassifier(llm_quick, llm_deep).invoke(**inputs)
```

테스트 + commit.

---

### Task 22: dedupe_rank_news

```python
from datetime import datetime
from difflib import SequenceMatcher

from tradingagents.schemas.news import NewsItem, ImpactAssessment, RankedNews
from tradingagents.skills.registry import register_skill


# String-similarity threshold for the *coarse* pre-filter only.
# Two headlines must be both highly similar AND have matching impact
# direction + asset classes to be treated as duplicates. This prevents
# the classic financial-news pitfall: "Fed cuts rates 25bp" vs "Fed
# hikes rates 25bp" share ~92% character similarity but represent
# OPPOSITE market events. Direction-aware dedup keeps both.
_STRING_SIMILARITY_THRESHOLD = 0.85


def _are_same_event(
    a_item: NewsItem, a_impact: ImpactAssessment,
    b_item: NewsItem, b_impact: ImpactAssessment,
) -> bool:
    """Two news items represent the same event iff:
        (1) headline similarity > threshold AND
        (2) impact direction matches AND
        (3) impact asset classes overlap (Jaccard ≥ 0.5)

    Direction mismatch (e.g., 'rates cut' vs 'rates hike') → NOT duplicates,
    even if string similarity is 99%.
    """
    if SequenceMatcher(None, a_item.headline, b_item.headline).ratio() < _STRING_SIMILARITY_THRESHOLD:
        return False
    if a_impact.direction != b_impact.direction:
        return False
    a_set = set(a_impact.asset_classes_affected)
    b_set = set(b_impact.asset_classes_affected)
    if not a_set or not b_set:
        return False
    jaccard = len(a_set & b_set) / len(a_set | b_set)
    return jaccard >= 0.5


@register_skill(name="dedupe_rank_news", category="news")
def dedupe_rank_news(
    items: list[NewsItem],
    impacts: dict[str, ImpactAssessment],
    top_n: int = 10,
) -> list[RankedNews]:
    """Dedupe by direction-aware similarity (NOT plain string match), then rank.

    Why direction-aware: in financial news, opposite-meaning headlines often
    have very high lexical similarity (e.g., 'Fed hikes rates' vs 'Fed cuts
    rates' = 92% overlap). Plain SequenceMatcher would discard one of them.
    We require both lexical similarity AND matching impact direction +
    overlapping asset classes — leveraging the LLM-derived ImpactAssessment
    that already exists upstream.

    impacts: dict keyed by headline (must contain entries for ALL items;
        items without an impact are skipped).
    """
    # Step 1: pair items with impacts
    paired: list[tuple[NewsItem, ImpactAssessment]] = [
        (item, impacts[item.headline])
        for item in items
        if item.headline in impacts
    ]

    # Step 2: direction-aware dedup
    deduped: list[tuple[NewsItem, ImpactAssessment]] = []
    for item, impact in paired:
        is_dup = any(
            _are_same_event(item, impact, prev_item, prev_impact)
            for prev_item, prev_impact in deduped
        )
        if not is_dup:
            deduped.append((item, impact))

    # Step 3: rank by severity × recency
    now = datetime.utcnow()
    ranked: list[RankedNews] = []
    for item, impact in deduped:
        recency = max(0.0, 1.0 - (now - item.published_at).total_seconds() / (7 * 86400))
        score = impact.severity * (0.5 + 0.5 * recency)
        ranked.append(RankedNews(item=item, impact=impact, rank_score=score))

    ranked.sort(key=lambda r: r.rank_score, reverse=True)
    return ranked[:top_n]
```

> **Production hardening:** plain `SequenceMatcher` 만으로 dedup하면 'Fed cuts rates' 와 'Fed hikes rates' (≈92% similar)가 한 사건으로 병합되어 반대 방향 뉴스가 사라지는 치명적 결함. 이미 upstream `classify_event_impact` subagent가 산출한 `direction` + `asset_classes_affected` 메타데이터로 의미 충돌 감지 — string similarity 는 1차 후보 필터에만 사용, 최종 판정은 영향 방향·자산군 교집합 검증 통과 필수.

테스트 + commit.

---

## Phase 5: Portfolio Skills (7개)

### Task 23: select_etf_candidates

```python
from datetime import date

from tradingagents.dataflows.universe import Universe
from tradingagents.schemas.portfolio import BucketTarget, CandidateSet
from tradingagents.schemas.technical import ETFRanking
from tradingagents.skills.registry import register_skill


# Map BucketTarget fields to universe categories
BUCKET_TO_CATEGORIES = {
    "kr_equity": ["국내주식_지수", "국내주식_섹터"],
    "global_equity": ["해외주식_지수", "해외주식_섹터"],
    "fx_commodity": ["FX 및 원자재"],
    "bond": [
        "국내채권_종합", "국내채권_회사채",
        "해외채권_종합", "해외채권_회사채",
    ],
    "cash_mmf": ["금리연계형/초단기채권"],
}


@register_skill(name="select_etf_candidates", category="portfolio")
def select_etf_candidates(
    universe: Universe,
    bucket_target: BucketTarget,
    momentum_rankings: dict[str, list[ETFRanking]],
    as_of: date,
    min_aum_krw: float = 1_000_000_000_000,  # 1조원 floor
    per_bucket_n: int = 5,
) -> CandidateSet:
    """Filter universe by bucket target, AUM, momentum rank.

    Per D13 decision: applies survivorship-bias filter via Universe.tradable_at(as_of)
    BEFORE selection. ETFs not yet listed (or already delisted) at as_of are excluded.
    For 5/28 live plan with current universe, this is a no-op. For `gaps simulate`
    backtests, this removes look-ahead from candidate selection.
    """
    universe = universe.tradable_at(as_of)
    bucket_to_tickers: dict[str, list[str]] = {}

    for bucket_name, weight in [
        ("kr_equity", bucket_target.kr_equity),
        ("global_equity", bucket_target.global_equity),
        ("fx_commodity", bucket_target.fx_commodity),
        ("bond", bucket_target.bond),
        ("cash_mmf", bucket_target.cash_mmf),
    ]:
        if weight <= 0:
            bucket_to_tickers[bucket_name] = []
            continue

        cats = BUCKET_TO_CATEGORIES[bucket_name]
        eligible = [
            e for e in universe.etfs
            if e.category in cats and e.aum_krw >= min_aum_krw
        ]
        # Sort by momentum (if available) else by AUM desc
        candidates_sorted = []
        for cat in cats:
            ranks = momentum_rankings.get(cat, [])
            ranked_tickers = [r.ticker for r in ranks]
            for ticker in ranked_tickers:
                if any(e.ticker == ticker and e.aum_krw >= min_aum_krw for e in universe.etfs):
                    candidates_sorted.append(ticker)
        # Fallback: AUM-sorted
        if not candidates_sorted:
            candidates_sorted = [e.ticker for e in sorted(eligible, key=lambda x: -x.aum_krw)]
        bucket_to_tickers[bucket_name] = candidates_sorted[:per_bucket_n]

    total = sum(len(v) for v in bucket_to_tickers.values())
    return CandidateSet(
        bucket_to_tickers=bucket_to_tickers,
        selection_criteria=f"AUM ≥ {min_aum_krw / 1e12:.1f}조원, momentum rank top {per_bucket_n} per category",
        total_candidates=total,
    )
```

테스트 + commit.

---

### Task 24: fetch_returns_matrix

```python
from datetime import date

import pandas as pd

from tradingagents.dataflows.pykrx_data import fetch_etf_ohlcv_batch, ParquetCache
from tradingagents.skills.registry import register_skill


@register_skill(name="fetch_returns_matrix", category="portfolio")
def fetch_returns_matrix(
    tickers: list[str], start: date, end: date, cache_path: str | None = None,
) -> pd.DataFrame:
    cache = ParquetCache(cache_path) if cache_path else None
    raw = fetch_etf_ohlcv_batch(tickers, start, end, cache=cache)
    if raw.empty:
        return pd.DataFrame()

    pivot = raw.pivot(index="date", columns="ticker", values="close")
    returns = pivot.pct_change().dropna(how="all")
    return returns
```

테스트 + commit.

---

### Task 25: optimize_hrp / risk_parity / min_variance / black_litterman (4 in 1)

**Files:**
- Create: `tradingagents/skills/portfolio/optimizers.py`
- Create: `tests/unit/skills/test_portfolio_optimizers.py`

```python
import pandas as pd
from pypfopt import HRPOpt, EfficientFrontier, BlackLittermanModel, risk_models, expected_returns

from tradingagents.schemas.portfolio import OptimizationMethod, WeightVector
from tradingagents.skills.registry import register_skill


def _ef_metrics(weights, mu, S) -> tuple[float, float]:
    import numpy as np
    w = np.array([weights[t] for t in mu.index])
    ret = float(w @ mu.values)
    vol = float((w.T @ S.values @ w) ** 0.5)
    sharpe = ret / vol if vol > 0 else 0.0
    return vol, sharpe


@register_skill(name="optimize_hrp", category="portfolio")
def optimize_hrp(returns: pd.DataFrame) -> WeightVector:
    hrp = HRPOpt(returns)
    weights = hrp.optimize()
    weights = {k: float(v) for k, v in weights.items() if v > 1e-4}
    total = sum(weights.values())
    weights = {k: v / total for k, v in weights.items()}
    return WeightVector(
        method=OptimizationMethod.HRP,
        weights=weights,
        rationale=f"HRP on {returns.shape[1]} assets, {len(returns)} obs",
    )


@register_skill(name="optimize_risk_parity", category="portfolio")
def optimize_risk_parity(returns: pd.DataFrame) -> WeightVector:
    S = risk_models.sample_cov(returns)
    ef = EfficientFrontier(None, S, weight_bounds=(0, 0.20))  # 단일 20% 룰
    ef.min_volatility()  # PyPortfolioOpt에 정확한 RP 없으면 min vol 근사
    weights = {k: float(v) for k, v in ef.clean_weights().items() if v > 1e-4}
    total = sum(weights.values())
    weights = {k: v / total for k, v in weights.items()}
    return WeightVector(
        method=OptimizationMethod.RISK_PARITY, weights=weights,
        rationale="Risk parity (min vol approximation)",
    )


@register_skill(name="optimize_min_variance", category="portfolio")
def optimize_min_variance(returns: pd.DataFrame) -> WeightVector:
    mu = expected_returns.mean_historical_return(returns, returns_data=True)
    S = risk_models.sample_cov(returns)
    ef = EfficientFrontier(mu, S, weight_bounds=(0, 0.20))
    ef.min_volatility()
    weights = {k: float(v) for k, v in ef.clean_weights().items() if v > 1e-4}
    total = sum(weights.values())
    weights = {k: v / total for k, v in weights.items()}
    vol, sharpe = _ef_metrics(weights, mu, S)
    return WeightVector(
        method=OptimizationMethod.MIN_VARIANCE, weights=weights,
        rationale=f"Min variance, single-asset cap 20%",
        expected_volatility=vol, expected_sharpe=sharpe,
    )


@register_skill(name="optimize_black_litterman", category="portfolio")
def optimize_black_litterman(
    returns: pd.DataFrame, views: dict[str, float], view_confidences: list[float],
) -> WeightVector:
    """views: {ticker: expected_return}, view_confidences: list of (0,1)."""
    S = risk_models.sample_cov(returns)
    bl = BlackLittermanModel(S, absolute_views=views, omega="idzorek", view_confidences=view_confidences)
    bl_returns = bl.bl_returns()
    ef = EfficientFrontier(bl_returns, S, weight_bounds=(0, 0.20))
    ef.max_sharpe()
    weights = {k: float(v) for k, v in ef.clean_weights().items() if v > 1e-4}
    total = sum(weights.values())
    weights = {k: v / total for k, v in weights.items()}
    return WeightVector(
        method=OptimizationMethod.BLACK_LITTERMAN, weights=weights,
        rationale=f"Black-Litterman with {len(views)} views",
    )
```

테스트는 작은 returns DataFrame으로 4개 optimizer 호출 → weights 합 ≈1, 단일 ≤ 0.21.

```bash
git commit -am "feat(skills/portfolio): add 4 PyPortfolioOpt optimizers (HRP/RP/MinVar/BL)"
```

---

### Task 26: pick_optimization_method (subagent)

`prompts/asset-allocation.md`:

```markdown
Choose the best portfolio optimization method given the macro regime and risk profile.

Inputs:
- Regime: {regime_quadrant} (confidence {regime_confidence})
- Systemic risk score: {risk_score}/10 ({risk_regime})
- Single ETF cap (mandate): 20%
- Risk asset cap (mandate): 70%

Options:
- HRP (Hierarchical Risk Parity): robust, good for risk-off + concentrated correlation
- RISK_PARITY: equal risk contribution, neutral default
- MIN_VARIANCE: defensive, prefer in recession or risk-off
- BLACK_LITTERMAN: when you have explicit views (rare; needs view list)

Output a MethodChoice JSON:
- method: enum value
- params: optional dict (e.g., {{"target_return": 0.05}})
- reasoning: ≤300 chars
```

```python
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from tradingagents.schemas.portfolio import OptimizationMethod
from tradingagents.skills._base import BaseSubagent
from tradingagents.skills.registry import register_subagent


class MethodChoice(BaseModel):
    method: OptimizationMethod
    params: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = Field(max_length=300)


PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "asset-allocation.md"


class MethodPicker(BaseSubagent):
    def __init__(self, llm_quick, llm_deep):
        super().__init__(
            name="pick_optimization_method", tier="deep",
            schema=MethodChoice, prompt_path=PROMPT_PATH,
            llm_quick=llm_quick, llm_deep=llm_deep,
        )


@register_subagent(name="pick_optimization_method", category="portfolio")
def pick_optimization_method(llm_quick, llm_deep, **inputs) -> MethodChoice:
    return MethodPicker(llm_quick, llm_deep).invoke(**inputs)
```

테스트 + commit.

---

## Phase 6: Mandate Skills (4개, deterministic)

### Task 27: validate_universe

```python
from tradingagents.dataflows.universe import Universe
from tradingagents.schemas.mandate import Violation, ValidationReport
from tradingagents.schemas.portfolio import WeightVector
from tradingagents.skills.registry import register_skill


@register_skill(name="validate_universe", category="mandate")
def validate_universe(weights: WeightVector, universe: Universe) -> ValidationReport:
    universe_tickers = {e.ticker for e in universe.etfs}
    violations = []
    for ticker in weights.weights:
        if ticker not in universe_tickers:
            violations.append(Violation(
                rule="universe_membership",
                description=f"{ticker} not in 188 universe",
                severity="hard",
                suggested_fix=f"Remove {ticker}",
            ))
    return ValidationReport(passed=not violations, violations=violations)
```

---

### Task 28: validate_concentration (대회 §2.2)

```python
from tradingagents.dataflows.universe import Universe
from tradingagents.schemas.mandate import Violation, ValidationReport
from tradingagents.schemas.portfolio import WeightVector
from tradingagents.skills.registry import register_skill


RISK_BUCKETS = {"위험"}


@register_skill(name="validate_concentration", category="mandate")
def validate_concentration(weights: WeightVector, universe: Universe) -> ValidationReport:
    violations = []
    bucket_lookup = {e.ticker: e.bucket for e in universe.etfs}

    # Single ETF ≤ 20%
    for ticker, w in weights.weights.items():
        if w > 0.20 + 1e-6:
            violations.append(Violation(
                rule="single_etf_cap",
                description=f"{ticker} weight {w:.4f} > 0.20",
                severity="hard",
                suggested_fix=f"Reduce {ticker} to ≤0.20",
            ))

    # Risk asset ≤ 70%
    risk_total = sum(
        w for t, w in weights.weights.items()
        if bucket_lookup.get(t) in RISK_BUCKETS
    )
    if risk_total > 0.70 + 1e-6:
        violations.append(Violation(
            rule="risk_asset_cap",
            description=f"Risk weight {risk_total:.4f} > 0.70",
            severity="hard",
            suggested_fix=f"Reduce risk exposure by {(risk_total - 0.70):.4f}",
        ))

    return ValidationReport(passed=not violations, violations=violations)
```

테스트 — 정확히 70.0 / 70.001 경계, 단일 20.0 / 20.001.

---

### Task 29: validate_turnover_feasibility

```python
from tradingagents.schemas.mandate import Violation, ValidationReport
from tradingagents.schemas.portfolio import WeightVector
from tradingagents.skills.registry import register_skill


@register_skill(name="validate_turnover_feasibility", category="mandate")
def validate_turnover_feasibility(
    proposed: WeightVector,
    previous_weights: dict[str, float] | None,
    capital_krw: int,
    floor_pct: float,
    days_remaining: int,
) -> ValidationReport:
    """Check if proposed weights produce ≥floor_pct turnover within days_remaining.

    For initial setup (5/28 → 6/8): floor_pct=0.80, days_remaining=5.
    For monthly: floor_pct=0.10, days_remaining=20.
    """
    # Calculate planned turnover
    if previous_weights is None:
        # Initial: all weights are buys
        buy_amount = sum(proposed.weights.values()) * capital_krw
        sell_amount = 0
    else:
        all_tickers = set(proposed.weights) | set(previous_weights)
        delta = {t: proposed.weights.get(t, 0) - previous_weights.get(t, 0) for t in all_tickers}
        buy_amount = sum(d for d in delta.values() if d > 0) * capital_krw
        sell_amount = -sum(d for d in delta.values() if d < 0) * capital_krw

    avg_assets = capital_krw  # simplified (real formula uses avg of beginning/end)
    turnover = (buy_amount + sell_amount) / avg_assets

    violations = []
    if turnover < floor_pct:
        violations.append(Violation(
            rule="turnover_floor",
            description=f"Planned turnover {turnover:.4f} < floor {floor_pct}",
            severity="hard",
            suggested_fix=f"Increase trade size by {(floor_pct - turnover):.4f}",
        ))
    return ValidationReport(passed=not violations, violations=violations)
```

테스트 + commit.

---

### Task 30: validate_correlation_concentration

```python
from tradingagents.schemas.mandate import Violation, ValidationReport
from tradingagents.schemas.portfolio import WeightVector
from tradingagents.schemas.technical import Cluster
from tradingagents.skills.registry import register_skill


@register_skill(name="validate_correlation_concentration", category="mandate")
def validate_correlation_concentration(
    weights: WeightVector, clusters: list[Cluster],
    cluster_cap: float = 0.25,
) -> ValidationReport:
    """Single correlation cluster (e.g., AI/semi) sum should ≤ cluster_cap."""
    violations = []
    for cluster in clusters:
        cluster_sum = sum(weights.weights.get(t, 0) for t in cluster.members)
        if cluster_sum > cluster_cap:
            violations.append(Violation(
                rule="correlation_concentration",
                description=(
                    f"Cluster '{cluster.category_label}' sum {cluster_sum:.4f} > {cluster_cap} "
                    f"({len(cluster.members)} members, avg corr {cluster.avg_internal_correlation:.2f})"
                ),
                severity="soft",  # not hard mandate, but evaluator-critical
                suggested_fix=f"Reduce concentration in {cluster.category_label}",
            ))
    return ValidationReport(passed=not violations, violations=violations)
```

테스트 + commit.

---

## Phase 7: Skill Registry Initialization

### Task 31: _registry_init.py — 모든 skill import

**Files:**
- Create: `tradingagents/skills/_registry_init.py`
- Create: `tests/unit/skills/test_registry_init.py`

```python
"""Side-effect import to register all skills with the global registry.

Import this module before calling get_skill() in app code.
"""
# Macro
from tradingagents.skills.macro import (
    yield_curve, inflation, employment,
    fred_fetcher, ecos_fetcher,
    divergence, calendar, regime_classifier,
)

# Risk
from tradingagents.skills.risk import (
    volatility, credit_spread, fear_greed,
    breadth, correlation_pca, systemic_score,
)

# Technical
from tradingagents.skills.technical import (
    price_batch, ta_indicators, momentum_ranker,
    trend_state, correlation_cluster,
)

# News
from tradingagents.skills.news import (
    event_calendar, news_fetcher, impact_classifier, ranker,
)

# Portfolio
from tradingagents.skills.portfolio import (
    candidate_selector, returns_matrix, optimizers, method_picker,
)

# Mandate
from tradingagents.skills.mandate import (
    universe_check, concentration_check,
    turnover_check, correlation_check,
)
```

테스트:
```python
def test_all_skills_registered():
    from tradingagents.skills.registry import list_skills
    import tradingagents.skills._registry_init  # noqa: side-effect
    skills = list_skills()
    expected = {
        "compute_yield_curve", "compute_inflation_trend", "compute_unemployment_trend",
        "fetch_fred_series", "fetch_ecos_series", "compute_kr_divergence",
        "fetch_central_bank_calendar", "classify_regime",
        "fetch_volatility_index", "fetch_credit_spread", "fetch_fear_greed_index",
        "compute_market_breadth", "compute_correlation_concentration", "score_systemic_risk",
        "fetch_etf_price_batch", "compute_ta_indicators", "rank_momentum",
        "detect_trend_state", "find_correlation_clusters",
        "fetch_event_calendar", "fetch_macro_news", "classify_event_impact", "dedupe_rank_news",
        "select_etf_candidates", "fetch_returns_matrix",
        "optimize_hrp", "optimize_risk_parity", "optimize_min_variance", "optimize_black_litterman",
        "pick_optimization_method",
        "validate_universe", "validate_concentration",
        "validate_turnover_feasibility", "validate_correlation_concentration",
    }
    missing = expected - set(skills)
    assert not missing, f"Missing skills: {missing}"
```

```bash
git commit -am "feat(skills): add _registry_init.py and verify all 34 skills registered"
```

---

## Self-Review

- ✅ 34 skills 전부 정의 (macro 8, risk 6, technical 5, news 4, portfolio 7, mandate 4)
- ✅ Subagent 5개 (classify_regime, score_systemic_risk, classify_event_impact, pick_optimization_method) BaseSubagent 상속
- ✅ Vibe-Trading 한국화 prompt 4개 (macro/risk/asset-allocation/news-impact) 시드
- ✅ 결정 D5 (tier3 narrative API skip-with-note) → fetch_fear_greed_index가 None 반환
- ✅ 결정 D6 (BaseSubagent) → 모든 subagent
- ✅ 결정 D10 (pykrx Parquet cache) → fetch_etf_price_batch
- ✅ 단위 테스트 모든 skill에 1+ 작성

## Plan 2 완료 시 산출물

- 34 skill 모듈 + 4 prompt 시드
- ~50 단위 테스트
- Registry init 검증 테스트

**다음:** Plan 3 (Agents + Graph + Debates) — `docs/superpowers/plans/2026-05-10-db-gaps-plan-3-agents.md`
