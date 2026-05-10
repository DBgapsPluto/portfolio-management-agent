# DB GAPS Plan 1 — Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 데이터 레이어, Pydantic 스키마, 스킬 인프라(레지스트리, BaseSubagent, 헬퍼), Preset YAML 로더를 구축한다. 후속 plan들의 토대.

**Architecture:** `tradingagents/dataflows/` 에 외부 API 클라이언트(pykrx/FRED/ECOS) + tiered cache. `tradingagents/schemas/` 에 도메인별 Pydantic 모델. `tradingagents/skills/` 에 데코레이터 기반 레지스트리 + BaseSubagent 추상 클래스. `tradingagents/presets/` 에 YAML 로더. 모두 외부 API mock 가능, 단위 테스트 100% 커버.

**Tech Stack:** Python 3.10+, pydantic, pyyaml, pykrx, fredapi, requests (ECOS), pandas, pyarrow (Parquet), pytest, pytest-mock.

**참조 스펙:** `docs/superpowers/specs/2026-05-09-db-gaps-agent-redesign-design.md` §5, §6, §13. 결정 D3, D5, D6, D7 적용.

---

## File Structure

생성될 파일들:

```
tradingagents/
├── dataflows/
│   ├── universe.py                    # xlsx → JSON, ETF universe loader
│   ├── cache.py                       # tiered cache (live → D-1 → D-7 → fail)
│   ├── pykrx_data.py                  # KR ETF OHLCV + Parquet cache
│   ├── fred.py                        # 미국 거시지표
│   ├── ecos.py                        # 한국은행 거시지표
│   ├── volatility.py                  # VIX/VKOSPI
│   └── news_macro.py                  # 캘린더·뉴스 RSS
├── schemas/
│   ├── __init__.py
│   ├── _base.py                       # StalenessAware 베이스
│   ├── macro.py                       # YieldCurveSnapshot, RegimeClassification, ...
│   ├── risk.py                        # VolatilitySnapshot, SystemicRiskScore, ...
│   ├── technical.py                   # IndicatorPanel, TrendState, Cluster, ...
│   ├── news.py                        # CalendarEvent, ImpactAssessment, ...
│   ├── portfolio.py                   # CandidateSet, WeightVector, BucketTarget, ...
│   ├── mandate.py                     # ValidationReport, Violation, ...
│   └── reports.py                     # MacroReport, RiskReport, TechnicalReport, NewsReport
├── skills/
│   ├── __init__.py
│   ├── _base.py                       # BaseSubagent 추상 클래스
│   ├── _helpers.py                    # invoke_with_structured_retry
│   └── registry.py                    # @register_skill, @subagent 데코레이터
├── presets/
│   ├── __init__.py
│   ├── spec.py                        # PresetSpec, AgentSpec, StageSpec Pydantic
│   └── loader.py                      # PresetLoader
└── default_config.py                  # 신규 키 추가 (subagent_model_policy 등)

tests/
├── unit/
│   ├── test_universe.py
│   ├── test_cache.py
│   ├── test_pykrx_data.py
│   ├── test_fred.py
│   ├── test_ecos.py
│   ├── test_volatility.py
│   ├── test_news_macro.py
│   ├── test_schemas_base.py
│   ├── test_skill_registry.py
│   ├── test_base_subagent.py
│   ├── test_helpers.py
│   └── test_preset_loader.py
└── fixtures/
    ├── universe_test.xlsx              # 188 ETF mini 샘플
    ├── fred_macro.json
    ├── ecos_macro.json
    ├── pykrx_etf_prices.parquet
    └── preset_minimal.yaml
```

---

## Phase 0: Setup

### Task 1: pyproject.toml 의존성 추가

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: 의존성 추가**

`[project] dependencies` 섹션에 추가:

```toml
dependencies = [
    # ... 기존 ...
    "pykrx>=1.0.45",
    "pyportfolioopt>=1.5.5",
    "pandas-ta>=0.3.14b",       # pure Python TA — replaces TA-Lib (no C build pain)
    "openpyxl>=3.1.0",
    "python-docx>=1.1.0",
    "pyyaml>=6.0",
    "scikit-learn>=1.3.0",
    "pyarrow>=14.0.0",
    "feedparser>=6.0.10",
    "beautifulsoup4>=4.12.0",
    "tenacity>=8.2.0",          # rate-limit / network retry (used in dataflows)
    "langsmith>=0.1.0",         # tracing for multi-agent debugging
]

[project.optional-dependencies]
test = [
    "pytest>=7.4.0",
    "pytest-mock>=3.12.0",
    "pytest-asyncio>=0.23.0",
]
```

- [ ] **Step 2: 설치 확인**

Run: `pip install -e ".[test]"`
Expected: 모든 패키지 pure Python으로 설치 성공. C 빌드 단계 없음 (pandas-ta로 교체했기 때문).

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add DB GAPS dependencies (pykrx, pyportfolioopt, pandas-ta, langsmith, tenacity)"
```

---

### Task 2a: TA-Lib 시스템 패키지 설치 안내 (삭제됨)

> **변경:** TA-Lib 의존성이 `pandas-ta`로 교체됨. 시스템 패키지 설치 단계가 더 이상 필요 없음. pure Python이라 `pip install pandas-ta`만으로 끝.

### Task 2: default_config.py 신규 키 추가

**Files:**
- Modify: `tradingagents/default_config.py`

- [ ] **Step 1: 신규 설정 키 추가**

기존 `DEFAULT_CONFIG` 끝에 추가:

```python
DEFAULT_CONFIG.update({
    # DB GAPS 설정
    "preset_dir": "./presets",
    "prompt_dir": "./prompts",
    "universe_path": "./data/universe.json",
    "artifacts_dir": "./artifacts",
    "default_preset": "db_gaps",
    "subagent_model_policy": {
        "classify_regime": "deep",
        "score_systemic_risk": "deep",
        "pick_optimization_method": "deep",
        "classify_event_impact": "quick",
    },
    # API 키
    "fred_api_key": os.getenv("FRED_API_KEY"),
    "ecos_api_key": os.getenv("ECOS_API_KEY"),
    "tradingeconomics_key": os.getenv("TRADINGECONOMICS_KEY"),
    # Cache
    "etf_price_cache_path": os.path.join(_TRADINGAGENTS_HOME, "cache", "etf_prices.parquet"),
    "macro_cache_dir": os.path.join(_TRADINGAGENTS_HOME, "cache", "macro"),
    "cache_staleness_d1": 1,    # D-1
    "cache_staleness_d7": 7,    # D-7
    "cache_staleness_d30": 30,  # D-30 (월간 지표)

    # Macro data publication lag (look-ahead bias prevention)
    # Each FRED/ECOS series has a real-world release delay; the agent must
    # NOT see data that wasn't actually published by the simulation as_of_date.
    "publication_lag_days": {
        # FRED — typical release lag in calendar days
        "us_cpi": 15,           # CPI: ~mid-month for previous month
        "us_core_cpi": 15,
        "us_unrate": 7,         # NFP/UR: first Friday of next month
        "us_payems": 7,
        "us_10y": 1, "us_2y": 1, "us_3m": 1,  # Daily series, T-1 default
        "us_policy_rate": 1,
        "us_ig_oas": 1, "us_hy_oas": 1,
        "vix_close": 1,
        "fed_balance_sheet": 8,  # Weekly H.4.1 release Thursday
        # ECOS — Korean macro
        "kr_base_rate": 0,       # Same-day MPC announcement
        "kr_cpi": 5,             # Statistics Korea: ~early month for prior
        "kr_m2": 60,             # Monthly with ~2 month lag
        "kr_export": 1,          # Customs first-of-month
        "kr_import": 1,
        "kr_industrial_production": 30,
        "kr_unrate": 15,
    },

    # Tracing / observability
    "langsmith_enabled": os.getenv("LANGSMITH_TRACING", "false").lower() == "true",
    "langsmith_project": os.getenv("LANGSMITH_PROJECT", "db-gaps-agent"),
})
```

- [ ] **Step 2: 단위 테스트 작성**

`tests/unit/test_default_config.py`:

```python
from tradingagents.default_config import DEFAULT_CONFIG


def test_db_gaps_keys_present():
    required = [
        "preset_dir", "prompt_dir", "universe_path",
        "artifacts_dir", "default_preset",
        "subagent_model_policy",
        "etf_price_cache_path", "macro_cache_dir",
    ]
    for key in required:
        assert key in DEFAULT_CONFIG, f"missing key: {key}"


def test_subagent_model_policy_has_critical_skills():
    policy = DEFAULT_CONFIG["subagent_model_policy"]
    assert policy["classify_regime"] == "deep"
    assert policy["pick_optimization_method"] == "deep"
    assert policy["classify_event_impact"] == "quick"
```

- [ ] **Step 3: 테스트 통과 확인**

Run: `pytest tests/unit/test_default_config.py -v`
Expected: 2 PASSED.

- [ ] **Step 4: Commit**

```bash
git add tradingagents/default_config.py tests/unit/test_default_config.py
git commit -m "feat(config): add DB GAPS config keys and subagent model policy"
```

---

## Phase 1: Pydantic Schemas (Base + Domains)

### Task 3: StalenessAware 베이스 스키마

**Files:**
- Create: `tradingagents/schemas/__init__.py`
- Create: `tradingagents/schemas/_base.py`
- Create: `tests/unit/test_schemas_base.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/test_schemas_base.py`:

```python
from datetime import date
from tradingagents.schemas._base import StalenessAware


def test_staleness_aware_default_zero():
    class Snap(StalenessAware):
        value: float = 0.0
    s = Snap()
    assert s.staleness_days == 0
    assert s.is_stale is False


def test_staleness_aware_d7_marks_stale():
    class Snap(StalenessAware):
        value: float = 0.0
    s = Snap(staleness_days=7)
    assert s.is_stale is True


def test_staleness_aware_serializes_json():
    class Snap(StalenessAware):
        value: float = 1.5
    s = Snap(value=1.5, staleness_days=2, source_date=date(2026, 5, 10))
    payload = s.model_dump_json()
    assert "staleness_days" in payload
    assert "1.5" in payload
```

- [ ] **Step 2: 테스트 실행 (실패 확인)**

Run: `pytest tests/unit/test_schemas_base.py -v`
Expected: ImportError — `StalenessAware`가 정의되지 않음.

- [ ] **Step 3: 구현**

`tradingagents/schemas/__init__.py`:

```python
"""Pydantic schemas for DB GAPS asset allocation agent."""
```

`tradingagents/schemas/_base.py`:

```python
from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class StalenessAware(BaseModel):
    """모든 외부 데이터 기반 스냅샷의 베이스. staleness 추적."""

    staleness_days: int = Field(
        default=0,
        ge=0,
        description="Days since the source data was current. 0 = live, >7 = stale.",
    )
    source_date: Optional[date] = Field(
        default=None,
        description="The 'as-of' date of the underlying data (not fetch time).",
    )

    @property
    def is_stale(self) -> bool:
        """True if data is more than 1 day old."""
        return self.staleness_days > 1

    @property
    def is_severely_stale(self) -> bool:
        """True if data is more than 7 days old."""
        return self.staleness_days > 7
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/unit/test_schemas_base.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/schemas/ tests/unit/test_schemas_base.py
git commit -m "feat(schemas): add StalenessAware base for all external-data snapshots"
```

---

### Task 4: Macro 도메인 스키마

**Files:**
- Create: `tradingagents/schemas/macro.py`
- Create: `tests/unit/test_schemas_macro.py`

- [ ] **Step 1: 실패 테스트**

`tests/unit/test_schemas_macro.py`:

```python
import pytest
from pydantic import ValidationError
from tradingagents.schemas.macro import (
    YieldCurveSnapshot,
    InflationSnapshot,
    EmploymentSnapshot,
    RegimeClassification,
    DivergenceScore,
    CentralBankEvent,
)


def test_yield_curve_inverted():
    yc = YieldCurveSnapshot(
        spread_10y_2y_bps=-25.5,
        spread_10y_3m_bps=-40.0,
        inverted_days_count=120,
        percentile_5y=0.05,
    )
    assert yc.spread_10y_2y_bps < 0


def test_regime_classification_enum():
    rc = RegimeClassification(
        quadrant="recession_disinflation",
        confidence=0.85,
        drivers=["yield curve inversion", "rising unemployment"],
        reasoning="Sahm rule triggered, 10y-2y at -25bp",
    )
    assert rc.quadrant == "recession_disinflation"
    assert 0 <= rc.confidence <= 1


def test_regime_rejects_bad_quadrant():
    with pytest.raises(ValidationError):
        RegimeClassification(
            quadrant="random_string",
            confidence=0.5,
            drivers=["x"],
            reasoning="y",
        )


def test_employment_with_sahm():
    emp = EmploymentSnapshot(
        unemployment_rate=4.2,
        rate_change_3mo=0.5,
        sahm_rule_triggered=True,
        non_farm_payrolls_3mo_avg=150_000,
    )
    assert emp.sahm_rule_triggered is True
```

- [ ] **Step 2: 실행 (실패 확인)**

Run: `pytest tests/unit/test_schemas_macro.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`tradingagents/schemas/macro.py`:

```python
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from tradingagents.schemas._base import StalenessAware


RegimeQuadrant = Literal[
    "growth_inflation",
    "growth_disinflation",
    "recession_inflation",
    "recession_disinflation",
]


class YieldCurveSnapshot(StalenessAware):
    spread_10y_2y_bps: float = Field(description="10Y - 2Y in basis points")
    spread_10y_3m_bps: float = Field(description="10Y - 3M in basis points")
    inverted_days_count: int = Field(ge=0, description="Days inverted in last 365")
    percentile_5y: float = Field(ge=0, le=1, description="5y historical percentile")


class InflationSnapshot(StalenessAware):
    cpi_yoy: float = Field(description="CPI YoY %")
    core_cpi_yoy: float = Field(description="Core CPI YoY %")
    momentum_3mo: float = Field(description="3-month annualized rate")
    momentum_6mo: float = Field(description="6-month annualized rate")
    accelerating: bool = Field(description="True if 3mo > 6mo > 12mo")


class EmploymentSnapshot(StalenessAware):
    unemployment_rate: float
    rate_change_3mo: float = Field(description="3-month change in UR")
    sahm_rule_triggered: bool = Field(description="Sahm rule recession indicator")
    non_farm_payrolls_3mo_avg: float


class DivergenceScore(StalenessAware):
    us_kr_rate_gap_bps: float = Field(description="US policy rate - KR base rate")
    us_kr_inflation_gap: float
    score: float = Field(ge=-10, le=10, description="Negative = divergence, positive = convergence")


class CentralBankEvent(BaseModel):
    """Not StalenessAware — calendar events are forward-looking."""
    bank: Literal["FED", "BOK", "ECB", "BOJ", "PBOC"]
    event_date: date
    event_type: Literal["rate_decision", "minutes", "speech", "press_conference"]
    description: str = Field(max_length=200)


class RegimeClassification(StalenessAware):
    """Subagent output — schema-locked."""
    quadrant: RegimeQuadrant
    confidence: float = Field(ge=0, le=1)
    drivers: list[str] = Field(min_length=1, max_length=5)
    reasoning: str = Field(max_length=300)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/unit/test_schemas_macro.py -v`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/schemas/macro.py tests/unit/test_schemas_macro.py
git commit -m "feat(schemas): add macro domain (YieldCurve, Inflation, Employment, Regime, Divergence)"
```

---

### Task 5: Risk 도메인 스키마

**Files:**
- Create: `tradingagents/schemas/risk.py`
- Create: `tests/unit/test_schemas_risk.py`

- [ ] **Step 1: 실패 테스트**

`tests/unit/test_schemas_risk.py`:

```python
from tradingagents.schemas.risk import (
    VolatilitySnapshot,
    SpreadSnapshot,
    SentimentSnapshot,
    BreadthSnapshot,
    PCASnapshot,
    SystemicRiskScore,
)


def test_volatility_with_zscore():
    v = VolatilitySnapshot(
        index_name="VIX",
        current_value=18.5,
        zscore_30d=0.4,
        percentile_5y=0.55,
    )
    assert v.current_value == 18.5


def test_systemic_risk_score_bounded():
    s = SystemicRiskScore(
        score=6.5,
        regime="risk_off",
        drivers=["VIX spike", "credit spread widening"],
    )
    assert 0 <= s.score <= 10


def test_pca_concentration():
    p = PCASnapshot(
        first_eigenvalue_share=0.72,
        n_assets_analyzed=12,
        is_concentrated=True,
    )
    assert p.is_concentrated is True
```

- [ ] **Step 2: 실행 (실패 확인)**

Run: `pytest tests/unit/test_schemas_risk.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`tradingagents/schemas/risk.py`:

```python
from typing import Literal

from pydantic import Field

from tradingagents.schemas._base import StalenessAware


class VolatilitySnapshot(StalenessAware):
    index_name: Literal["VIX", "VKOSPI"]
    current_value: float = Field(ge=0)
    zscore_30d: float
    percentile_5y: float = Field(ge=0, le=1)


class SpreadSnapshot(StalenessAware):
    region: Literal["US_IG", "US_HY", "KR_IG"]
    current_bps: float
    percentile_5y: float = Field(ge=0, le=1)
    widening: bool


class SentimentSnapshot(StalenessAware):
    index_name: Literal["fear_greed_cnn", "fear_greed_alt"]
    current_value: int = Field(ge=0, le=100)
    label: Literal["extreme_fear", "fear", "neutral", "greed", "extreme_greed"]
    trend_7d: Literal["rising", "falling", "flat"]


class BreadthSnapshot(StalenessAware):
    market: Literal["KOSPI200", "SP500"]
    advancing_pct: float = Field(ge=0, le=1)
    declining_pct: float = Field(ge=0, le=1)
    new_highs_minus_lows: int


class PCASnapshot(StalenessAware):
    first_eigenvalue_share: float = Field(ge=0, le=1, description="Variance explained by PC1")
    n_assets_analyzed: int = Field(ge=2)
    is_concentrated: bool = Field(description="True if first_eigenvalue_share > 0.6")


class SystemicRiskScore(StalenessAware):
    """Subagent output."""
    score: float = Field(ge=0, le=10)
    regime: Literal["risk_on", "risk_off", "neutral"]
    drivers: list[str] = Field(min_length=1, max_length=5)
    reasoning: str = Field(max_length=300, default="")
```

- [ ] **Step 4: 테스트 통과**

Run: `pytest tests/unit/test_schemas_risk.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/schemas/risk.py tests/unit/test_schemas_risk.py
git commit -m "feat(schemas): add risk domain (volatility, spread, sentiment, breadth, PCA, systemic)"
```

---

### Task 6: Technical 도메인 스키마

**Files:**
- Create: `tradingagents/schemas/technical.py`
- Create: `tests/unit/test_schemas_technical.py`

- [ ] **Step 1: 실패 테스트**

`tests/unit/test_schemas_technical.py`:

```python
from tradingagents.schemas.technical import (
    IndicatorPanel,
    TrendState,
    ETFRanking,
    Cluster,
)


def test_trend_state_enum():
    assert TrendState.STRONG_UPTREND.value == "strong_uptrend"


def test_indicator_panel():
    p = IndicatorPanel(
        ticker="A069500",
        ma200=425.0,
        ma50=440.0,
        rsi=62.0,
        macd_signal=2.5,
        atr=8.3,
    )
    assert p.ticker == "A069500"


def test_cluster_with_members():
    c = Cluster(
        cluster_id="ai_semis",
        members=["A381180", "A395160", "A446770"],
        avg_internal_correlation=0.83,
        category_label="AI/Semiconductor",
    )
    assert len(c.members) == 3
    assert c.avg_internal_correlation > 0.7
```

- [ ] **Step 2: 실행**

Run: `pytest tests/unit/test_schemas_technical.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`tradingagents/schemas/technical.py`:

```python
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from tradingagents.schemas._base import StalenessAware


class TrendState(str, Enum):
    STRONG_UPTREND = "strong_uptrend"
    UPTREND = "uptrend"
    NEUTRAL = "neutral"
    DOWNTREND = "downtrend"
    BREAKDOWN = "breakdown"


class IndicatorPanel(StalenessAware):
    ticker: str = Field(pattern=r"^A\d{6}[A-Z0-9]?$")
    ma200: float
    ma50: float
    rsi: float = Field(ge=0, le=100)
    macd_signal: float
    atr: float = Field(ge=0)


class ETFRanking(BaseModel):
    """Pure derivation from price data — no staleness here, parent carries it."""
    ticker: str
    name: str
    momentum_3m: float
    momentum_6m: float
    momentum_12m: float
    rank_in_category: int = Field(ge=1)


class Cluster(BaseModel):
    cluster_id: str
    members: list[str] = Field(min_length=2, description="Tickers in this cluster")
    avg_internal_correlation: float = Field(ge=-1, le=1)
    category_label: str = Field(max_length=80, description="Human label for the theme")
```

- [ ] **Step 4: 테스트 통과**

Run: `pytest tests/unit/test_schemas_technical.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/schemas/technical.py tests/unit/test_schemas_technical.py
git commit -m "feat(schemas): add technical domain (IndicatorPanel, TrendState, ETFRanking, Cluster)"
```

---

### Task 7: News 도메인 스키마

**Files:**
- Create: `tradingagents/schemas/news.py`
- Create: `tests/unit/test_schemas_news.py`

- [ ] **Step 1: 실패 테스트**

`tests/unit/test_schemas_news.py`:

```python
from datetime import datetime
from tradingagents.schemas.news import (
    CalendarEvent,
    NewsItem,
    ImpactAssessment,
    RankedNews,
)


def test_news_headline_only():
    item = NewsItem(
        headline="Fed signals 25bp cut at next meeting",
        source="Reuters",
        published_at=datetime(2026, 5, 10, 14, 30),
        url="https://reuters.com/x",
    )
    assert item.headline.startswith("Fed")


def test_impact_assessment_schema():
    impact = ImpactAssessment(
        asset_classes_affected=["us_bond", "us_equity"],
        direction="up",
        severity=4,
        reasoning="Lower rates positive for bonds and equities",
    )
    assert impact.severity == 4
    assert "us_bond" in impact.asset_classes_affected
```

- [ ] **Step 2: 실행**

Run: `pytest tests/unit/test_schemas_news.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`tradingagents/schemas/news.py`:

```python
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


AssetClass = Literal[
    "kr_equity", "us_equity", "global_equity",
    "kr_bond", "us_bond",
    "fx", "commodity", "gold",
]


class CalendarEvent(BaseModel):
    event_date: date
    region: Literal["US", "KR", "EU", "JP", "CN", "GLOBAL"]
    event_type: Literal["fomc", "bok", "cpi", "gdp", "employment", "pmi", "other"]
    description: str = Field(max_length=200)
    consensus: str | None = Field(default=None, max_length=80)


class NewsItem(BaseModel):
    headline: str = Field(max_length=300)
    source: str
    published_at: datetime
    url: str  # HttpUrl validates strictly; use str for resilience to bad sources


class ImpactAssessment(BaseModel):
    """Subagent output."""
    asset_classes_affected: list[AssetClass] = Field(min_length=1, max_length=4)
    direction: Literal["up", "down", "neutral"]
    severity: int = Field(ge=1, le=5)
    reasoning: str = Field(max_length=200)


class RankedNews(BaseModel):
    item: NewsItem
    impact: ImpactAssessment
    rank_score: float = Field(description="severity * recency_weight")
```

- [ ] **Step 4: 테스트 통과**

Run: `pytest tests/unit/test_schemas_news.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/schemas/news.py tests/unit/test_schemas_news.py
git commit -m "feat(schemas): add news domain (CalendarEvent, NewsItem, ImpactAssessment)"
```

---

### Task 8: Portfolio 도메인 스키마

**Files:**
- Create: `tradingagents/schemas/portfolio.py`
- Create: `tests/unit/test_schemas_portfolio.py`

- [ ] **Step 1: 실패 테스트**

`tests/unit/test_schemas_portfolio.py`:

```python
import pytest
from pydantic import ValidationError
from tradingagents.schemas.portfolio import (
    BucketTarget,
    CandidateSet,
    WeightVector,
    OptimizationMethod,
)


def test_bucket_target_sums_to_one():
    bt = BucketTarget(
        kr_equity=0.15,
        global_equity=0.30,
        fx_commodity=0.10,
        bond=0.35,
        cash_mmf=0.10,
        rationale="Recession-disinflation regime, defensive tilt",
    )
    assert abs(bt.total - 1.0) < 1e-6


def test_bucket_rejects_non_unit_sum():
    with pytest.raises(ValidationError):
        BucketTarget(
            kr_equity=0.5,
            global_equity=0.5,
            fx_commodity=0.5,
            bond=0.0,
            cash_mmf=0.0,
            rationale="bad",
        )


def test_weight_vector_normalized():
    wv = WeightVector(
        method=OptimizationMethod.HRP,
        weights={"A069500": 0.4, "A411060": 0.3, "A114260": 0.3},
        rationale="HRP based on 3y returns",
        expected_volatility=0.12,
        expected_sharpe=0.85,
    )
    assert abs(sum(wv.weights.values()) - 1.0) < 1e-6
```

- [ ] **Step 2: 실행**

Run: `pytest tests/unit/test_schemas_portfolio.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`tradingagents/schemas/portfolio.py`:

```python
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class OptimizationMethod(str, Enum):
    HRP = "hrp"
    RISK_PARITY = "risk_parity"
    MIN_VARIANCE = "min_variance"
    BLACK_LITTERMAN = "black_litterman"


class BucketTarget(BaseModel):
    """Asset class weight target from Research Manager."""
    kr_equity: float = Field(ge=0, le=1)
    global_equity: float = Field(ge=0, le=1)
    fx_commodity: float = Field(ge=0, le=1)
    bond: float = Field(ge=0, le=1)
    cash_mmf: float = Field(ge=0, le=1)
    rationale: str = Field(max_length=500)

    @property
    def total(self) -> float:
        return self.kr_equity + self.global_equity + self.fx_commodity + self.bond + self.cash_mmf

    @model_validator(mode="after")
    def _sum_to_one(self):
        if abs(self.total - 1.0) > 1e-6:
            raise ValueError(f"Bucket weights must sum to 1.0, got {self.total}")
        return self

    @property
    def risk_asset_weight(self) -> float:
        """위험자산 합계 (대회 §2.2 룰: ≤70%)."""
        return self.kr_equity + self.global_equity + self.fx_commodity


class CandidateSet(BaseModel):
    """Allocator의 후보 ETF 풀."""
    bucket_to_tickers: dict[str, list[str]]
    selection_criteria: str = Field(max_length=300)
    total_candidates: int = Field(ge=1)


class WeightVector(BaseModel):
    """Allocator의 최종 weight."""
    method: OptimizationMethod
    weights: dict[str, float] = Field(min_length=1, description="ticker → weight")
    rationale: str = Field(max_length=500)
    expected_volatility: float | None = Field(default=None, ge=0)
    expected_sharpe: float | None = None

    @model_validator(mode="after")
    def _normalize(self):
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-3:
            raise ValueError(f"Weights must sum to ~1.0, got {total}")
        if any(w < 0 for w in self.weights.values()):
            raise ValueError("Negative weights not allowed")
        return self
```

- [ ] **Step 4: 테스트 통과**

Run: `pytest tests/unit/test_schemas_portfolio.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/schemas/portfolio.py tests/unit/test_schemas_portfolio.py
git commit -m "feat(schemas): add portfolio domain (BucketTarget, CandidateSet, WeightVector)"
```

---

### Task 9: Mandate 도메인 스키마

**Files:**
- Create: `tradingagents/schemas/mandate.py`
- Create: `tests/unit/test_schemas_mandate.py`

- [ ] **Step 1: 실패 테스트**

`tests/unit/test_schemas_mandate.py`:

```python
from tradingagents.schemas.mandate import Violation, ValidationReport


def test_violation_with_details():
    v = Violation(
        rule="single_etf_cap",
        description="A381180 weight 0.22 exceeds 0.20 cap",
        severity="hard",
        suggested_fix="Reduce A381180 to 0.20",
    )
    assert v.severity == "hard"


def test_validation_report_passed():
    r = ValidationReport(passed=True, violations=[], suggestions=[])
    assert r.passed is True
    assert len(r.violations) == 0


def test_validation_report_failed_blocks():
    r = ValidationReport(
        passed=False,
        violations=[
            Violation(
                rule="risk_asset_cap",
                description="Risk weight 0.73 > 0.70",
                severity="hard",
                suggested_fix="Reduce equity exposure by 3%",
            )
        ],
        suggestions=["Consider increasing 안전자산"],
    )
    assert r.has_hard_violations is True
```

- [ ] **Step 2: 실행**

Run: `pytest tests/unit/test_schemas_mandate.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`tradingagents/schemas/mandate.py`:

```python
from typing import Literal

from pydantic import BaseModel, Field


class Violation(BaseModel):
    rule: Literal[
        "universe_membership",
        "risk_asset_cap",      # 70%
        "single_etf_cap",      # 20%
        "turnover_floor",
        "correlation_concentration",
    ]
    description: str = Field(max_length=500)
    severity: Literal["hard", "soft"]
    suggested_fix: str = Field(max_length=300)


class ValidationReport(BaseModel):
    passed: bool
    violations: list[Violation]
    suggestions: list[str] = Field(default_factory=list)

    @property
    def has_hard_violations(self) -> bool:
        return any(v.severity == "hard" for v in self.violations)

    @property
    def hard_violations(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "hard"]
```

- [ ] **Step 4: 테스트 통과**

Run: `pytest tests/unit/test_schemas_mandate.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/schemas/mandate.py tests/unit/test_schemas_mandate.py
git commit -m "feat(schemas): add mandate domain (Violation, ValidationReport)"
```

---

### Task 10: Reports 도메인 스키마 (분석가 출력 통합)

**Files:**
- Create: `tradingagents/schemas/reports.py`
- Create: `tests/unit/test_schemas_reports.py`

- [ ] **Step 1: 실패 테스트**

`tests/unit/test_schemas_reports.py`:

```python
import pytest
from pydantic import ValidationError
from tradingagents.schemas.reports import (
    MacroReport, RiskReport, TechnicalReport, NewsReport,
)
from tradingagents.schemas.macro import (
    YieldCurveSnapshot, InflationSnapshot, EmploymentSnapshot,
    DivergenceScore, RegimeClassification,
)


def test_macro_report_narrative_max_length():
    yc = YieldCurveSnapshot(
        spread_10y_2y_bps=-25.0, spread_10y_3m_bps=-30.0,
        inverted_days_count=120, percentile_5y=0.05,
    )
    infl = InflationSnapshot(
        cpi_yoy=2.8, core_cpi_yoy=3.2, momentum_3mo=2.5,
        momentum_6mo=3.0, accelerating=False,
    )
    emp = EmploymentSnapshot(
        unemployment_rate=4.2, rate_change_3mo=0.5,
        sahm_rule_triggered=True, non_farm_payrolls_3mo_avg=140_000,
    )
    div = DivergenceScore(us_kr_rate_gap_bps=200.0, us_kr_inflation_gap=0.5, score=2.5)
    regime = RegimeClassification(
        quadrant="recession_disinflation", confidence=0.85,
        drivers=["yield curve"], reasoning="x",
    )
    report = MacroReport(
        yield_curve=yc, inflation=infl, employment=emp,
        kr_divergence=div, regime=regime,
        upcoming_events=[], narrative="짧은 매크로 요약",
        summary_for_downstream="recession-disinflation, 35% risk asset",
    )
    assert len(report.narrative) <= 500


def test_narrative_too_long_rejected():
    with pytest.raises(ValidationError):
        # Build with valid sub-objects but narrative too long
        # (omitted for brevity; just check the constraint)
        from tradingagents.schemas.reports import MacroReport
        MacroReport.model_validate({
            "yield_curve": {"spread_10y_2y_bps": 0, "spread_10y_3m_bps": 0,
                            "inverted_days_count": 0, "percentile_5y": 0.5},
            "inflation": {"cpi_yoy": 0, "core_cpi_yoy": 0, "momentum_3mo": 0,
                          "momentum_6mo": 0, "accelerating": False},
            "employment": {"unemployment_rate": 0, "rate_change_3mo": 0,
                           "sahm_rule_triggered": False, "non_farm_payrolls_3mo_avg": 0},
            "kr_divergence": {"us_kr_rate_gap_bps": 0, "us_kr_inflation_gap": 0, "score": 0},
            "regime": {"quadrant": "growth_inflation", "confidence": 0.5,
                       "drivers": ["x"], "reasoning": "y"},
            "upcoming_events": [],
            "narrative": "x" * 501,  # too long
            "summary_for_downstream": "y",
        })
```

- [ ] **Step 2: 실행**

Run: `pytest tests/unit/test_schemas_reports.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`tradingagents/schemas/reports.py`:

```python
from pydantic import BaseModel, Field

from tradingagents.schemas.macro import (
    YieldCurveSnapshot, InflationSnapshot, EmploymentSnapshot,
    DivergenceScore, RegimeClassification, CentralBankEvent,
)
from tradingagents.schemas.risk import (
    VolatilitySnapshot, SpreadSnapshot, SentimentSnapshot,
    BreadthSnapshot, PCASnapshot, SystemicRiskScore,
)
from tradingagents.schemas.technical import (
    IndicatorPanel, TrendState, ETFRanking, Cluster,
)
from tradingagents.schemas.news import CalendarEvent, RankedNews


# 공통: 모든 분석가 출력은 narrative ≤500 + summary_for_downstream ≤2000
NARRATIVE_MAX = 500
SUMMARY_MAX = 2000


class _AnalystReport(BaseModel):
    narrative: str = Field(max_length=NARRATIVE_MAX, description="LLM-authored prose; data must come from skill outputs")
    summary_for_downstream: str = Field(
        max_length=SUMMARY_MAX,
        description="Markdown summary handoff to next stage (D2 hybrid topology)",
    )


class MacroReport(_AnalystReport):
    yield_curve: YieldCurveSnapshot
    inflation: InflationSnapshot
    employment: EmploymentSnapshot
    kr_divergence: DivergenceScore
    regime: RegimeClassification
    upcoming_events: list[CentralBankEvent]


class RiskReport(_AnalystReport):
    vix: VolatilitySnapshot
    vkospi: VolatilitySnapshot
    credit_spread_us_ig: SpreadSnapshot
    credit_spread_us_hy: SpreadSnapshot
    fear_greed: SentimentSnapshot
    breadth_kr: BreadthSnapshot
    breadth_us: BreadthSnapshot
    correlation_concentration: PCASnapshot
    systemic_score: SystemicRiskScore


class TechnicalReport(_AnalystReport):
    asset_class_momentum: dict[str, list[ETFRanking]] = Field(
        description="Category name → top-N ETFs"
    )
    individual_etf_states: dict[str, TrendState]
    correlation_clusters: list[Cluster]


class NewsReport(_AnalystReport):
    upcoming_events: list[CalendarEvent]
    ranked_news: list[RankedNews]
```

- [ ] **Step 4: 테스트 통과**

Run: `pytest tests/unit/test_schemas_reports.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/schemas/reports.py tests/unit/test_schemas_reports.py
git commit -m "feat(schemas): add analyst report schemas (Macro/Risk/Technical/News)"
```

---

## Phase 2: Skill Infrastructure

### Task 11: Skill Registry (데코레이터 + lookup)

**Files:**
- Create: `tradingagents/skills/__init__.py`
- Create: `tradingagents/skills/registry.py`
- Create: `tests/unit/test_skill_registry.py`

- [ ] **Step 1: 실패 테스트**

`tests/unit/test_skill_registry.py`:

```python
import pytest
from tradingagents.skills.registry import (
    register_skill, get_skill, list_skills, clear_registry,
)


def test_register_and_lookup():
    clear_registry()

    @register_skill(name="test_double", category="test")
    def double(x: int) -> int:
        return x * 2

    fn = get_skill("test_double")
    assert fn(5) == 10


def test_unknown_skill_raises():
    clear_registry()
    with pytest.raises(KeyError, match="unknown_skill"):
        get_skill("unknown_skill")


def test_list_skills_by_category():
    clear_registry()

    @register_skill(name="a", category="macro")
    def a(): pass

    @register_skill(name="b", category="risk")
    def b(): pass

    @register_skill(name="c", category="macro")
    def c(): pass

    macro_skills = list_skills(category="macro")
    assert sorted(macro_skills) == ["a", "c"]


def test_duplicate_registration_raises():
    clear_registry()

    @register_skill(name="dup", category="x")
    def dup1(): pass

    with pytest.raises(ValueError, match="already registered"):
        @register_skill(name="dup", category="x")
        def dup2(): pass
```

- [ ] **Step 2: 실행 (실패)**

Run: `pytest tests/unit/test_skill_registry.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`tradingagents/skills/__init__.py`:

```python
"""Skill infrastructure for DB GAPS analyst orchestration."""
```

`tradingagents/skills/registry.py`:

```python
from collections.abc import Callable
from typing import Any

_REGISTRY: dict[str, dict[str, Any]] = {}


def register_skill(name: str, category: str) -> Callable:
    """Decorator to register a deterministic skill function.

    Usage:
        @register_skill(name="fetch_fred_series", category="macro")
        def fetch_fred_series(series_id: str, ...) -> TimeSeries:
            ...
    """
    def decorator(fn: Callable) -> Callable:
        if name in _REGISTRY:
            raise ValueError(f"Skill '{name}' already registered")
        _REGISTRY[name] = {"fn": fn, "category": category, "kind": "deterministic"}
        return fn
    return decorator


def register_subagent(name: str, category: str) -> Callable:
    """Decorator to register a subagent (small LLM + schema-locked output)."""
    def decorator(fn: Callable) -> Callable:
        if name in _REGISTRY:
            raise ValueError(f"Skill '{name}' already registered")
        _REGISTRY[name] = {"fn": fn, "category": category, "kind": "subagent"}
        return fn
    return decorator


def get_skill(name: str) -> Callable:
    if name not in _REGISTRY:
        raise KeyError(f"unknown_skill: {name!r} not in registry")
    return _REGISTRY[name]["fn"]


def list_skills(category: str | None = None) -> list[str]:
    if category is None:
        return list(_REGISTRY.keys())
    return [n for n, meta in _REGISTRY.items() if meta["category"] == category]


def clear_registry() -> None:
    """Test-only: clear the global registry."""
    _REGISTRY.clear()
```

- [ ] **Step 4: 테스트 통과**

Run: `pytest tests/unit/test_skill_registry.py -v`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/__init__.py tradingagents/skills/registry.py tests/unit/test_skill_registry.py
git commit -m "feat(skills): add registry with @register_skill / @register_subagent decorators"
```

---

### Task 12: invoke_with_structured_retry helper (D7 결정)

**Files:**
- Create: `tradingagents/skills/_helpers.py`
- Create: `tests/unit/test_helpers.py`

- [ ] **Step 1: 실패 테스트**

`tests/unit/test_helpers.py`:

```python
from unittest.mock import MagicMock
import pytest
from pydantic import BaseModel, Field, ValidationError

from tradingagents.skills._helpers import invoke_with_structured_retry


class _Out(BaseModel):
    label: str
    score: float = Field(ge=0, le=1)


def test_first_call_succeeds():
    llm = MagicMock()
    structured = MagicMock()
    structured.invoke.return_value = _Out(label="ok", score=0.5)
    llm.with_structured_output.return_value = structured

    result = invoke_with_structured_retry(llm, _Out, [{"role": "user", "content": "x"}])
    assert result.label == "ok"
    assert structured.invoke.call_count == 1


def test_first_validation_fails_retry_succeeds():
    llm = MagicMock()
    structured = MagicMock()
    # First call returns invalid (score > 1), second succeeds
    structured.invoke.side_effect = [
        ValidationError.from_exception_data("Out", []),
        _Out(label="recovered", score=0.7),
    ]
    llm.with_structured_output.return_value = structured

    # Note: ValidationError isn't easy to raise from MagicMock side_effect directly;
    # instead, use a callable that raises on first call.
    calls = {"n": 0}
    def fake_invoke(messages):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValidationError.from_exception_data("Out", [])
        return _Out(label="recovered", score=0.7)
    structured.invoke = fake_invoke

    result = invoke_with_structured_retry(llm, _Out, [{"role": "user", "content": "x"}])
    assert result.label == "recovered"
    assert calls["n"] == 2


def test_two_failures_raises():
    llm = MagicMock()
    structured = MagicMock()
    def always_fail(messages):
        raise ValidationError.from_exception_data("Out", [])
    structured.invoke = always_fail
    llm.with_structured_output.return_value = structured

    with pytest.raises(ValidationError):
        invoke_with_structured_retry(llm, _Out, [{"role": "user", "content": "x"}], max_retries=1)
```

- [ ] **Step 2: 실행 (실패)**

Run: `pytest tests/unit/test_helpers.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`tradingagents/skills/_helpers.py`:

```python
import logging
from typing import TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def invoke_with_structured_retry(
    llm,
    schema: type[T],
    messages: list[dict],
    max_retries: int = 1,
) -> T:
    """Invoke an LLM with a Pydantic-locked schema, retrying on validation failure.

    Used by both BaseSubagent and analyst nodes per D7 decision.

    Args:
        llm: A LangChain LLM client (must support .with_structured_output).
        schema: Pydantic class for output schema.
        messages: List of {"role": ..., "content": ...} dicts.
        max_retries: Number of retries on ValidationError (default 1).

    Returns:
        Validated schema instance.

    Raises:
        ValidationError: If retries exhausted.
    """
    structured = llm.with_structured_output(schema)
    last_err: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return structured.invoke(messages)
        except ValidationError as e:
            last_err = e
            logger.warning(
                "Schema validation failed on attempt %d/%d for %s: %s",
                attempt + 1, max_retries + 1, schema.__name__, e,
            )
            if attempt < max_retries:
                # Inject the error into the conversation so the model can self-correct.
                messages = list(messages) + [
                    {
                        "role": "system",
                        "content": (
                            f"Your previous response failed schema validation: {e}. "
                            f"Output ONLY a valid {schema.__name__} JSON object."
                        ),
                    }
                ]
    assert last_err is not None
    raise last_err
```

- [ ] **Step 4: 테스트 통과**

Run: `pytest tests/unit/test_helpers.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/_helpers.py tests/unit/test_helpers.py
git commit -m "feat(skills): add invoke_with_structured_retry helper (D7)"
```

---

### Task 13: BaseSubagent 추상 클래스 (D6 결정)

**Files:**
- Create: `tradingagents/skills/_base.py`
- Create: `tests/unit/test_base_subagent.py`

- [ ] **Step 1: 실패 테스트**

`tests/unit/test_base_subagent.py`:

```python
from unittest.mock import MagicMock
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from tradingagents.skills._base import BaseSubagent


class _OutSchema(BaseModel):
    label: str
    score: float = Field(ge=0, le=1)


def test_subagent_invoke_with_template(tmp_path):
    prompt_file = tmp_path / "p.md"
    prompt_file.write_text("Classify the input: {input}")

    quick_llm = MagicMock()
    deep_llm = MagicMock()
    out = _OutSchema(label="ok", score=0.7)
    structured = MagicMock()
    structured.invoke.return_value = out
    deep_llm.with_structured_output.return_value = structured

    sub = BaseSubagent(
        name="test_sub",
        tier="deep",
        schema=_OutSchema,
        prompt_path=prompt_file,
        llm_quick=quick_llm,
        llm_deep=deep_llm,
    )
    result = sub.invoke(input="hello")
    assert result.label == "ok"
    deep_llm.with_structured_output.assert_called_once_with(_OutSchema)


def test_subagent_uses_quick_when_tier_quick(tmp_path):
    prompt_file = tmp_path / "p.md"
    prompt_file.write_text("Hi {x}")
    quick_llm = MagicMock()
    deep_llm = MagicMock()
    quick_llm.with_structured_output.return_value.invoke.return_value = _OutSchema(label="q", score=0.1)

    sub = BaseSubagent(
        name="quick_sub", tier="quick", schema=_OutSchema,
        prompt_path=prompt_file, llm_quick=quick_llm, llm_deep=deep_llm,
    )
    sub.invoke(x="y")
    quick_llm.with_structured_output.assert_called_once()
    deep_llm.with_structured_output.assert_not_called()
```

- [ ] **Step 2: 실행 (실패)**

Run: `pytest tests/unit/test_base_subagent.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`tradingagents/skills/_base.py`:

```python
import logging
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel

from tradingagents.skills._helpers import invoke_with_structured_retry

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
ModelTier = Literal["deep", "quick"]


class BaseSubagent:
    """Abstract subagent: small LLM + Pydantic-locked output.

    Per D6 decision: every subagent inherits this contract.
    Per D7: retry/validation handled by invoke_with_structured_retry helper.
    """

    def __init__(
        self,
        name: str,
        tier: ModelTier,
        schema: type[T],
        prompt_path: Path | str,
        llm_quick,
        llm_deep,
        max_retries: int = 1,
    ):
        self.name = name
        self.tier: ModelTier = tier
        self.schema = schema
        self.prompt_template = Path(prompt_path).read_text(encoding="utf-8")
        self.llm = llm_deep if tier == "deep" else llm_quick
        self.max_retries = max_retries

    def _build_messages(self, **inputs) -> list[dict]:
        """Render the prompt template with inputs."""
        try:
            user_content = self.prompt_template.format(**inputs)
        except KeyError as e:
            raise KeyError(f"Subagent {self.name!r} prompt missing variable: {e}")
        return [{"role": "user", "content": user_content}]

    def invoke(self, **inputs) -> T:
        messages = self._build_messages(**inputs)
        logger.debug("Subagent %s invoking with tier=%s", self.name, self.tier)
        return invoke_with_structured_retry(
            self.llm, self.schema, messages, max_retries=self.max_retries
        )
```

- [ ] **Step 4: 테스트 통과**

Run: `pytest tests/unit/test_base_subagent.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/_base.py tests/unit/test_base_subagent.py
git commit -m "feat(skills): add BaseSubagent abstract class (D6)"
```

---

## Phase 3: Universe & Cache

### Task 14: Universe loader (xlsx → JSON)

**Files:**
- Create: `tradingagents/dataflows/universe.py`
- Create: `tests/fixtures/universe_test.xlsx` (수동: 실제 5개 ETF만 담은 미니 파일)
- Create: `tests/unit/test_universe.py`

- [ ] **Step 1: 픽스처 생성**

다음 Python 스크립트를 한 번 실행해 fixture 생성:

```python
import openpyxl
wb = openpyxl.Workbook()
ws = wb.active
ws.title = "ETF"
rows = [
    [None, "샘플 ETF 리스트 (테스트용)", None, None, None, None, None],
    [None, None, None, None, None, None, None],
    [None, None, None, None, None, None, None],
    [None, None, None, None, None, None, None],
    [None, "티커", "ETF명", "AUM(억원)", "기초지수", "구분1", "구분2"],
    [None, "A069500", "KODEX 200", 164802.5, "코스피 200", "위험", "국내주식_지수"],
    [None, "A360750", "TIGER 미국S&P500", 147821.0, "S&P 500", "위험", "해외주식_지수"],
    [None, "A411060", "ACE KRX금현물", 52302.9, "KRX 금현물지수", "위험", "FX 및 원자재"],
    [None, "A114260", "KODEX 국고채3년", 5352.6, "MKF 국고채지수(총수익)", "안전", "국내채권_종합"],
    [None, "A459580", "KODEX CD금리액티브(합성)", 79731.3, "KAP CD금리지수(총수익지수)", "안전", "금리연계형/초단기채권"],
]
for r in rows:
    ws.append(r)
wb.save("tests/fixtures/universe_test.xlsx")
```

- [ ] **Step 2: 실패 테스트**

`tests/unit/test_universe.py`:

```python
import json
from pathlib import Path

import pytest

from tradingagents.dataflows.universe import sync_from_xlsx, load_universe


FIX = Path("tests/fixtures/universe_test.xlsx")


def test_sync_extracts_5_etfs(tmp_path):
    out = tmp_path / "universe.json"
    sync_from_xlsx(FIX, out)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert len(payload["etfs"]) == 5


def test_sync_normalizes_ticker():
    out_path = Path("/tmp/u.json")
    sync_from_xlsx(FIX, out_path)
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    tickers = [e["ticker"] for e in payload["etfs"]]
    assert "A069500" in tickers
    assert all(t.startswith("A") for t in tickers)


def test_load_returns_typed():
    out_path = Path("/tmp/u2.json")
    sync_from_xlsx(FIX, out_path)
    universe = load_universe(out_path)
    kodex_200 = next(e for e in universe.etfs if e.ticker == "A069500")
    assert kodex_200.bucket == "위험"
    assert kodex_200.aum_krw > 1_000_000_000_000  # 16조+


def test_sync_rejects_bad_ticker(tmp_path):
    """If xlsx has malformed ticker, sync should raise."""
    bad = tmp_path / "bad.xlsx"
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([None, None, None, None, None, None, None])
    ws.append([None] * 7)
    ws.append([None] * 7)
    ws.append([None] * 7)
    ws.append([None, "티커", "ETF명", "AUM(억원)", "기초지수", "구분1", "구분2"])
    ws.append([None, "BAD", "Bad", 100.0, "x", "위험", "국내주식_지수"])
    wb.save(bad)
    out = tmp_path / "u.json"
    with pytest.raises(ValueError, match="invalid ticker"):
        sync_from_xlsx(bad, out)
```

- [ ] **Step 3: 실행 (실패)**

Run: `pytest tests/unit/test_universe.py -v`
Expected: ImportError.

- [ ] **Step 4: 구현**

`tradingagents/dataflows/universe.py`:

```python
import json
import re
from datetime import date
from pathlib import Path
from typing import Literal

import openpyxl
from pydantic import BaseModel, Field

TICKER_RE = re.compile(r"^A\d{6}[A-Z0-9]?$")
HEADER_ROW_INDEX = 5  # xlsx의 5번째 row가 헤더 (1-indexed)


class ETFEntry(BaseModel):
    ticker: str
    name: str
    aum_krw: float = Field(ge=0)
    underlying_index: str
    bucket: Literal["위험", "안전"]
    category: str
    # Survivorship-bias prevention (set by sync via pykrx if available).
    # listed_since=None means "predates our data window" → always tradable.
    # delisted_at=None means still tradable.
    listed_since: date | None = Field(
        default=None,
        description="Listing date — used to filter for backtests with as_of < listed_since",
    )
    delisted_at: date | None = Field(
        default=None,
        description="Delisting date — for survivorship-bias-aware backtests",
    )


class Universe(BaseModel):
    version: str
    etfs: list[ETFEntry]

    def tradable_at(self, as_of: date) -> "Universe":
        """Return a sub-universe of ETFs that were tradable at as_of.

        Critical for `gaps simulate` (historical backtests). For 5/28 plan
        with as_of=2026-05-25, all current ETFs apply (listing dates ≤ as_of).
        For backtests at as_of=2024-01-01, ETFs listed after that date must
        be filtered out — otherwise we get survivorship bias.
        """
        tradable: list[ETFEntry] = []
        for e in self.etfs:
            if e.listed_since is not None and e.listed_since > as_of:
                continue  # not yet listed
            if e.delisted_at is not None and e.delisted_at <= as_of:
                continue  # already delisted
            tradable.append(e)
        return Universe(version=self.version, etfs=tradable)


def _fetch_listed_since(ticker: str) -> date | None:
    """Best-effort listing date lookup via pykrx. Returns None on failure
    (treated as 'predates our data window' for tradable_at filtering).

    KRX exposes listing date via the ETF info API. If unavailable for a
    ticker, the survivorship filter falls back to "always tradable" — safe
    for v1 5/28 (current universe, as_of 2026), but documented as a known
    limitation for `gaps simulate` against pre-2024 dates (TODO #6).
    """
    try:
        from pykrx import stock
        info = stock.get_etf_isin(ticker)
        # pykrx returns various shapes; handle defensively
        if hasattr(info, "상장일"):
            raw = info.상장일
            return date.fromisoformat(str(raw)[:10])
        return None
    except Exception:
        return None


def sync_from_xlsx(
    xlsx_path: Path, out_path: Path,
    fetch_listing_dates: bool = False,
) -> Universe:
    """Parse the GAPS xlsx and write a normalized JSON.

    Args:
        fetch_listing_dates: If True, call pykrx for each ticker to populate
            `listed_since`. Adds ~60s to sync (188 calls). Skip for fast iterations
            when only doing live (current-date) plans. Required for backtests.

    Returns the in-memory Universe object as well.
    """
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.active

    etfs: list[ETFEntry] = []
    rows = list(ws.iter_rows(values_only=True))

    # Find header row by content
    header_idx = None
    for i, row in enumerate(rows):
        if row and "티커" in row:
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("xlsx missing '티커' header row")

    for row in rows[header_idx + 1:]:
        if not row or row[1] is None:
            continue
        ticker = str(row[1]).strip()
        if not TICKER_RE.match(ticker):
            raise ValueError(f"invalid ticker: {ticker!r}")
        # AUM is in 억원; convert to KRW (multiply by 1e8)
        aum_krw = float(row[3] or 0) * 1e8
        listed_since = _fetch_listed_since(ticker) if fetch_listing_dates else None
        etfs.append(ETFEntry(
            ticker=ticker,
            name=str(row[2] or "").strip(),
            aum_krw=aum_krw,
            underlying_index=str(row[4] or "").strip(),
            bucket=str(row[5] or "").strip(),  # type: ignore
            category=str(row[6] or "").strip(),
            listed_since=listed_since,
            delisted_at=None,  # current xlsx is current — delisted ETFs not present
        ))

    universe = Universe(version=date.today().isoformat(), etfs=etfs)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(universe.model_dump_json(indent=2), encoding="utf-8")
    return universe


def load_universe(path: Path) -> Universe:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return Universe.model_validate(payload)
```

- [ ] **Step 5: 테스트 통과**

Run: `pytest tests/unit/test_universe.py -v`
Expected: 4 PASSED.

- [ ] **Step 6: Commit**

```bash
git add tradingagents/dataflows/universe.py tests/fixtures/universe_test.xlsx tests/unit/test_universe.py
git commit -m "feat(dataflows): add universe.py — xlsx → typed JSON loader"
```

---

### Task 15: Tiered cache (D5 결정 — pykrx tier1)

**Files:**
- Create: `tradingagents/dataflows/cache.py`
- Create: `tests/unit/test_cache.py`

- [ ] **Step 1: 실패 테스트**

`tests/unit/test_cache.py`:

```python
from datetime import date, timedelta
from pathlib import Path

import pytest

from tradingagents.dataflows.cache import (
    TieredCache, CacheMiss, FetchFailure,
)


def _ok_fetch(value):
    def f():
        return value
    return f


def _fail_fetch():
    def f():
        raise FetchFailure("upstream down")
    return f


def test_live_success(tmp_path):
    c = TieredCache(cache_dir=tmp_path, name="test")
    today = date(2026, 5, 10)
    val, staleness = c.fetch_with_fallback(_ok_fetch({"x": 1}), as_of=today)
    assert val == {"x": 1}
    assert staleness == 0


def test_live_fail_d1_hit(tmp_path):
    c = TieredCache(cache_dir=tmp_path, name="test")
    yesterday = date(2026, 5, 9)
    today = date(2026, 5, 10)
    # Seed yesterday's cache
    c.write(yesterday, {"x": "old"})
    val, staleness = c.fetch_with_fallback(_fail_fetch(), as_of=today)
    assert val == {"x": "old"}
    assert staleness == 1


def test_live_fail_no_cache_raises(tmp_path):
    c = TieredCache(cache_dir=tmp_path, name="test")
    today = date(2026, 5, 10)
    with pytest.raises(CacheMiss):
        c.fetch_with_fallback(_fail_fetch(), as_of=today, max_staleness=7)


def test_live_fail_d8_too_stale(tmp_path):
    c = TieredCache(cache_dir=tmp_path, name="test")
    today = date(2026, 5, 10)
    eight_days_ago = today - timedelta(days=8)
    c.write(eight_days_ago, {"x": "ancient"})
    with pytest.raises(CacheMiss):
        c.fetch_with_fallback(_fail_fetch(), as_of=today, max_staleness=7)
```

- [ ] **Step 2: 실행**

Run: `pytest tests/unit/test_cache.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`tradingagents/dataflows/cache.py`:

```python
import json
import logging
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FetchFailure(Exception):
    """Upstream API failure."""


class CacheMiss(Exception):
    """Live failed and cache lookup also failed within staleness budget."""


class TieredCache:
    """File-backed JSON cache with date-keyed entries.

    Per D5 decision (data-tiered policy):
    - tier1 (pykrx prices): max_staleness=7
    - tier2 (FRED/ECOS macros): max_staleness=1 typically, more for monthly indicators
    - tier3 (narrative APIs): caller decides skip-with-note rather than using cache
    """

    def __init__(self, cache_dir: Path | str, name: str):
        self.cache_dir = Path(cache_dir) / name
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.name = name

    def _path(self, d: date) -> Path:
        return self.cache_dir / f"{d.isoformat()}.json"

    def write(self, d: date, payload: Any) -> None:
        self._path(d).write_text(json.dumps(payload, default=str), encoding="utf-8")

    def read(self, d: date) -> Any | None:
        p = self._path(d)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def fetch_with_fallback(
        self,
        fetcher: Callable[[], Any],
        as_of: date,
        max_staleness: int = 7,
    ) -> tuple[Any, int]:
        """Try live fetcher; on failure, walk back through cache.

        Returns:
            (payload, staleness_days). staleness_days=0 means live.

        Raises:
            CacheMiss if live fails and no cache within max_staleness.
        """
        try:
            payload = fetcher()
            self.write(as_of, payload)
            return payload, 0
        except Exception as e:
            logger.warning("Cache %s: live fetch failed: %s — trying fallback", self.name, e)

        for delta in range(1, max_staleness + 1):
            d = as_of - timedelta(days=delta)
            cached = self.read(d)
            if cached is not None:
                logger.warning(
                    "Cache %s: serving stale data from %s (staleness=%d)",
                    self.name, d.isoformat(), delta,
                )
                return cached, delta

        raise CacheMiss(
            f"Cache {self.name}: live failed and no cache within {max_staleness} days of {as_of.isoformat()}"
        )
```

- [ ] **Step 4: 테스트 통과**

Run: `pytest tests/unit/test_cache.py -v`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/cache.py tests/unit/test_cache.py
git commit -m "feat(dataflows): add TieredCache with date-keyed fallback (D5)"
```

---

## Phase 4: External Data Modules

### Task 16: pykrx 데이터 모듈 (Parquet cache, D10 결정)

**Files:**
- Create: `tradingagents/dataflows/pykrx_data.py`
- Create: `tests/unit/test_pykrx_data.py`

- [ ] **Step 1: 실패 테스트**

`tests/unit/test_pykrx_data.py`:

```python
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.dataflows.pykrx_data import (
    fetch_etf_ohlcv, fetch_etf_ohlcv_batch, ParquetCache,
)


@pytest.fixture
def fake_pykrx_response():
    return pd.DataFrame({
        "시가": [40000, 40100, 40200],
        "고가": [40500, 40400, 40400],
        "저가": [39800, 39900, 40000],
        "종가": [40200, 40150, 40300],
        "거래량": [100000, 110000, 105000],
    }, index=pd.to_datetime(["2026-05-08", "2026-05-09", "2026-05-10"]))


def test_fetch_single_etf(fake_pykrx_response):
    with patch("tradingagents.dataflows.pykrx_data._raw_pykrx_call",
               return_value=fake_pykrx_response):
        df = fetch_etf_ohlcv("A069500", date(2026, 5, 8), date(2026, 5, 10))
    assert "close" in df.columns
    assert len(df) == 3
    assert df["close"].iloc[0] == 40200


def test_batch_fetch_uses_cache(tmp_path, fake_pykrx_response):
    cache = ParquetCache(tmp_path / "etf.parquet")
    tickers = ["A069500", "A360750"]

    with patch("tradingagents.dataflows.pykrx_data._raw_pykrx_call",
               return_value=fake_pykrx_response) as mock_call:
        df1 = fetch_etf_ohlcv_batch(tickers, date(2026, 5, 8), date(2026, 5, 10), cache=cache)
        # Second call should hit cache
        df2 = fetch_etf_ohlcv_batch(tickers, date(2026, 5, 8), date(2026, 5, 10), cache=cache)

    assert mock_call.call_count == 2  # One per ticker, second batch all cached
    assert len(df1) == 6  # 3 days × 2 tickers
    assert df1.equals(df2)
```

- [ ] **Step 2: 실행 (실패)**

Run: `pytest tests/unit/test_pykrx_data.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`tradingagents/dataflows/pykrx_data.py`:

```python
import logging
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)


from tenacity import (
    retry, stop_after_attempt, wait_exponential, retry_if_exception_type,
)


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
)
def _raw_pykrx_call(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Direct pykrx call. Wrapped for mocking + retry on transient failures.

    Retry: up to 3 attempts with exponential backoff (1s, 2s, 4s).
    KRX rate-limits aggressive callers; we keep workers serial AND retry only
    on network-level errors. Empty DataFrame is NOT retried.
    """
    from pykrx import stock
    return stock.get_market_ohlcv(
        start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), ticker
    )


def fetch_etf_ohlcv(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Fetch one ETF's OHLCV. Returns columns [open, high, low, close, volume].

    Korean column names are translated.
    """
    raw = _raw_pykrx_call(ticker, start, end)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    rename = {
        "시가": "open", "고가": "high", "저가": "low",
        "종가": "close", "거래량": "volume",
    }
    df = raw.rename(columns=rename)[["open", "high", "low", "close", "volume"]]
    df["ticker"] = ticker
    df.index.name = "date"
    return df.reset_index()


class ParquetCache:
    """Parquet-backed price cache for ETF OHLCV.

    Per D10 decision: sequential pykrx fetch + Parquet cache + cron pre-fetch.
    Schema: ticker, date, open, high, low, close, volume.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> pd.DataFrame:
        if not self.path.exists():
            return pd.DataFrame(columns=["ticker", "date", "open", "high", "low", "close", "volume"])
        return pd.read_parquet(self.path)

    def has(self, ticker: str, start: date, end: date) -> bool:
        df = self.read()
        if df.empty:
            return False
        sub = df[df["ticker"] == ticker]
        if sub.empty:
            return False
        sub_dates = pd.to_datetime(sub["date"]).dt.date
        return sub_dates.min() <= start and sub_dates.max() >= end

    def write_append(self, new_data: pd.DataFrame) -> None:
        existing = self.read()
        merged = pd.concat([existing, new_data], ignore_index=True)
        merged = merged.drop_duplicates(subset=["ticker", "date"], keep="last")
        merged.to_parquet(self.path, index=False)


def fetch_etf_ohlcv_batch(
    tickers: list[str],
    start: date,
    end: date,
    cache: ParquetCache | None = None,
) -> pd.DataFrame:
    """Fetch multiple ETFs' OHLCV (time-series, ticker-by-ticker).

    Use this when you need a 3-year history matrix (Allocator/optimization).
    For SINGLE-DAY snapshots across all 188 ETFs (drift monitor, trade-plan
    pricing, cron incremental update), use `fetch_etf_snapshot_by_date`
    instead — single API call returns all tickers at once.

    If cache hits for a ticker+range, skip pykrx call. Otherwise fetch and write.
    Sequential per D10 (no ThreadPool to avoid KRX rate limit).
    """
    frames: list[pd.DataFrame] = []
    for t in tickers:
        if cache is not None and cache.has(t, start, end):
            cached = cache.read()
            sub = cached[cached["ticker"] == t]
            sub_dates = pd.to_datetime(sub["date"]).dt.date
            mask = (sub_dates >= start) & (sub_dates <= end)
            frames.append(sub[mask])
            continue
        df = fetch_etf_ohlcv(t, start, end)
        if not df.empty and cache is not None:
            cache.write_append(df)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
)
def _raw_pykrx_snapshot_call(target_date: date) -> pd.DataFrame:
    """Direct pykrx snapshot call — all ETFs on a single date in one shot."""
    from pykrx import stock
    return stock.get_etf_ohlcv_by_ticker(target_date.strftime("%Y%m%d"))


def fetch_etf_snapshot_by_date(
    target_date: date, cache: ParquetCache | None = None,
) -> pd.DataFrame:
    """One pykrx call returns OHLCV for ALL ~600 KRX-listed ETFs on `target_date`.

    Use cases (snapshot — single date, all tickers):
      - Daily drift monitoring (`gaps monitor drift`)
      - Trade-plan current price (`gaps report trade-plan`)
      - Cron incremental cache update (D-1 snapshot append)

    NOT a substitute for `fetch_etf_ohlcv_batch`, which provides time-series
    history needed by the optimizer. Use both:
      - History (one-time 3-year build): batch_ohlcv (188 sequential calls, ~60s)
      - Daily incremental updates: snapshot_by_date (1 call, ~1s)

    Returns columns [ticker, date, open, high, low, close, volume].
    """
    raw = _raw_pykrx_snapshot_call(target_date)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["ticker", "date", "open", "high", "low", "close", "volume"])

    df = raw.reset_index().rename(columns={
        "티커": "ticker", "시가": "open", "고가": "high", "저가": "low",
        "종가": "close", "거래량": "volume",
    })
    df["date"] = pd.Timestamp(target_date)
    df = df[["ticker", "date", "open", "high", "low", "close", "volume"]]
    if cache is not None:
        cache.write_append(df)
    return df
```

> **Production hardening:** 188개 ETF × 3년 시계열은 ticker-by-ticker fetch가 정확하지만, 일별 모니터링·trade plan 현재가·cron 증분 갱신처럼 단일 날짜 전체 ETF 가격이 필요한 경우엔 snapshot API가 ~60배 빠름 (1 call vs 188 calls). 두 함수를 use-case별로 분리.

- [ ] **Step 4: 테스트 통과**

Run: `pytest tests/unit/test_pykrx_data.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/pykrx_data.py tests/unit/test_pykrx_data.py
git commit -m "feat(dataflows): add pykrx data module with Parquet cache (D10)"
```

---

### Task 17: FRED 모듈

**Files:**
- Create: `tradingagents/dataflows/fred.py`
- Create: `tests/unit/test_fred.py`

- [ ] **Step 1: 실패 테스트**

`tests/unit/test_fred.py`:

```python
from datetime import date
from unittest.mock import patch

import pandas as pd

from tradingagents.dataflows.fred import fetch_fred_series, FRED_SERIES


def test_fetch_yield_returns_pandas():
    fake = pd.Series([4.5, 4.45, 4.4],
                     index=pd.to_datetime(["2026-05-08", "2026-05-09", "2026-05-10"]),
                     name="DGS10")
    with patch("tradingagents.dataflows.fred._raw_fred_call", return_value=fake):
        s = fetch_fred_series("DGS10", date(2026, 5, 8), date(2026, 5, 10))
    assert s.iloc[-1] == 4.4


def test_known_series_constants():
    assert "DGS10" in FRED_SERIES.values()
    assert "CPIAUCSL" in FRED_SERIES.values()
```

- [ ] **Step 2: 실행 (실패)**

Run: `pytest tests/unit/test_fred.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`tradingagents/dataflows/fred.py`:

```python
import logging
import os
from datetime import date, timedelta

import pandas as pd
from tenacity import (
    retry, stop_after_attempt, wait_exponential, retry_if_exception_type,
)

from tradingagents.default_config import DEFAULT_CONFIG

logger = logging.getLogger(__name__)


# Curated subset of series IDs we use
FRED_SERIES = {
    "us_10y": "DGS10",
    "us_2y": "DGS2",
    "us_3m": "DGS3MO",
    "us_cpi": "CPIAUCSL",
    "us_core_cpi": "CPILFESL",
    "us_unrate": "UNRATE",
    "us_payems": "PAYEMS",
    "fed_balance_sheet": "WALCL",
    "us_policy_rate": "DFF",
    "us_ig_oas": "BAMLC0A0CM",
    "us_hy_oas": "BAMLH0A0HYM2",
    "vix_close": "VIXCLS",
}


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
)
def _raw_fred_call(series_id: str, start: date, end: date, api_key: str) -> pd.Series:
    """Wrapped for mocking + transient retry."""
    from fredapi import Fred
    fred = Fred(api_key=api_key)
    return fred.get_series(series_id, observation_start=start, observation_end=end)


def _publication_cutoff(as_of_date: date, friendly_key: str) -> date:
    """Latest data point that was *actually published* by as_of_date.

    Prevents look-ahead bias: e.g., May CPI is released ~mid-June, so a
    simulation with as_of=2026-05-25 must NOT see May CPI. Lag table is in
    DEFAULT_CONFIG['publication_lag_days'].

    NOTE on US/KR timezone: All FRED series timestamps are US ET. For asset
    pricing alignment with KR market close (15:30 KST = 02:30 ET), data
    released on a given calendar date is conservatively treated as available
    only the NEXT KR business day. This is a coarse approximation; tighter
    handling deferred (see TODOS.md for follow-up).
    """
    lag = DEFAULT_CONFIG["publication_lag_days"].get(friendly_key, 1)
    return as_of_date - timedelta(days=lag)


def fetch_fred_series(
    series_id: str, start: date, end: date, api_key: str | None = None,
    as_of_date: date | None = None,
) -> pd.Series:
    """Fetch a single FRED series with point-in-time integrity.

    Args:
        series_id: friendly key (e.g., 'us_cpi') or raw FRED ID.
        start, end: requested observation window.
        as_of_date: If provided, truncates the result to data that was actually
            available at that date (publication lag applied). Critical for
            backtests and historical simulations to avoid look-ahead bias.
            None means use raw end (live mode).
    """
    key = api_key or os.environ.get("FRED_API_KEY")
    if not key:
        raise RuntimeError("FRED_API_KEY not set")

    resolved = FRED_SERIES.get(series_id, series_id)
    series = _raw_fred_call(resolved, start, end, key)

    # Apply publication-lag cutoff
    if as_of_date is not None:
        cutoff = _publication_cutoff(as_of_date, series_id)
        series = series[series.index.date <= cutoff]
        logger.debug(
            "FRED %s point-in-time cutoff %s (as_of=%s, lag applied)",
            series_id, cutoff, as_of_date,
        )

    return series
```

- [ ] **Step 4: 테스트 통과**

Run: `pytest tests/unit/test_fred.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/fred.py tests/unit/test_fred.py
git commit -m "feat(dataflows): add FRED module with curated series IDs"
```

---

### Task 18: ECOS 모듈

**Files:**
- Create: `tradingagents/dataflows/ecos.py`
- Create: `tests/unit/test_ecos.py`

- [ ] **Step 1: 실패 테스트**

`tests/unit/test_ecos.py`:

```python
from datetime import date
from unittest.mock import patch

import pandas as pd

from tradingagents.dataflows.ecos import fetch_ecos_series, ECOS_STAT_CODES


def test_known_codes_present():
    assert "kr_base_rate" in ECOS_STAT_CODES
    assert "kr_cpi" in ECOS_STAT_CODES
    assert "kr_m2" in ECOS_STAT_CODES


def test_fetch_returns_pandas():
    fake_payload = {
        "StatisticSearch": {
            "row": [
                {"TIME": "202604", "DATA_VALUE": "3.5", "ITEM_NAME1": "한국은행 기준금리"},
                {"TIME": "202605", "DATA_VALUE": "3.5", "ITEM_NAME1": "한국은행 기준금리"},
            ]
        }
    }
    with patch("tradingagents.dataflows.ecos._raw_ecos_call", return_value=fake_payload):
        s = fetch_ecos_series("kr_base_rate", date(2026, 4, 1), date(2026, 5, 31), api_key="dummy")
    assert len(s) == 2
    assert s.iloc[-1] == 3.5
```

- [ ] **Step 2: 실행 (실패)**

Run: `pytest tests/unit/test_ecos.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`tradingagents/dataflows/ecos.py`:

```python
import logging
import os
from datetime import date

import pandas as pd
import requests

logger = logging.getLogger(__name__)


# 한국은행 ECOS 통계코드 (2026 기준 — 코드 변경 가능, 운용 중 검증 필요)
ECOS_STAT_CODES = {
    "kr_base_rate": ("722Y001", "0101000"),     # (통계코드, 항목코드)
    "kr_cpi": ("901Y009", "0"),
    "kr_m2": ("101Y004", "BBHA00"),
    "kr_export": ("403Y001", "*AA"),
    "kr_import": ("403Y003", "*AA"),
    "kr_industrial_production": ("901Y033", "*"),
    "kr_unrate": ("901Y027", "I31A"),
}


from datetime import timedelta

from tenacity import (
    retry, stop_after_attempt, wait_exponential, retry_if_exception_type,
)

from tradingagents.default_config import DEFAULT_CONFIG


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((requests.RequestException, ConnectionError, TimeoutError)),
)
def _raw_ecos_call(
    stat_code: str, item_code: str, freq: str,
    start: str, end: str, api_key: str,
) -> dict:
    """Direct ECOS REST call. Wrapped for mocking + retry on transient failures."""
    url = (
        f"https://ecos.bok.or.kr/api/StatisticSearch/{api_key}/json/kr/1/1000/"
        f"{stat_code}/{freq}/{start}/{end}/{item_code}"
    )
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()


def _ecos_publication_cutoff(as_of_date: date, friendly_key: str) -> date:
    """ECOS publication-lag cutoff (look-ahead bias prevention)."""
    lag = DEFAULT_CONFIG["publication_lag_days"].get(friendly_key, 5)
    return as_of_date - timedelta(days=lag)


def fetch_ecos_series(
    name: str, start: date, end: date, api_key: str | None = None,
    freq: str = "M", as_of_date: date | None = None,
) -> pd.Series:
    """Fetch a Bank of Korea ECOS series by friendly name.

    Frequency codes: M=월, Q=분기, A=연.

    Args:
        as_of_date: If provided, truncates to data published by that date
            (publication lag applied). None = live mode.
    """
    key = api_key or os.environ.get("ECOS_API_KEY")
    if not key:
        raise RuntimeError("ECOS_API_KEY not set")
    if name not in ECOS_STAT_CODES:
        raise KeyError(f"unknown ECOS series: {name!r}")

    stat_code, item_code = ECOS_STAT_CODES[name]
    fmt = "%Y%m" if freq in ("M", "Q") else "%Y"
    payload = _raw_ecos_call(
        stat_code, item_code, freq,
        start.strftime(fmt), end.strftime(fmt), key,
    )

    rows = payload.get("StatisticSearch", {}).get("row", [])
    if not rows:
        return pd.Series(dtype=float, name=name)

    times = []
    values = []
    for row in rows:
        t = row["TIME"]
        if freq == "M":
            ts = pd.Timestamp(year=int(t[:4]), month=int(t[4:6]), day=1)
        else:
            ts = pd.Timestamp(year=int(t[:4]), month=1, day=1)
        times.append(ts)
        values.append(float(row["DATA_VALUE"]))
    series = pd.Series(values, index=times, name=name)

    # Point-in-time cutoff (look-ahead bias prevention)
    if as_of_date is not None:
        cutoff = _ecos_publication_cutoff(as_of_date, name)
        series = series[series.index.date <= cutoff]

    return series
```

- [ ] **Step 4: 테스트 통과**

Run: `pytest tests/unit/test_ecos.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/ecos.py tests/unit/test_ecos.py
git commit -m "feat(dataflows): add ECOS module with curated stat codes"
```

---

### Task 19: Volatility (VIX/VKOSPI) 모듈

**Files:**
- Create: `tradingagents/dataflows/volatility.py`
- Create: `tests/unit/test_volatility.py`

- [ ] **Step 1: 실패 테스트**

`tests/unit/test_volatility.py`:

```python
from datetime import date
from unittest.mock import patch

import pandas as pd

from tradingagents.dataflows.volatility import fetch_vix, fetch_vkospi


def test_fetch_vix_returns_close_series():
    fake = pd.Series([18.5, 19.0, 18.7],
                     index=pd.to_datetime(["2026-05-08", "2026-05-09", "2026-05-10"]),
                     name="VIXCLS")
    with patch("tradingagents.dataflows.fred._raw_fred_call", return_value=fake):
        s = fetch_vix(date(2026, 5, 8), date(2026, 5, 10), api_key="x")
    assert s.iloc[-1] == 18.7


def test_fetch_vkospi_pykrx():
    fake_df = pd.DataFrame({
        "종가": [21.0, 22.5, 20.8],
    }, index=pd.to_datetime(["2026-05-08", "2026-05-09", "2026-05-10"]))
    with patch("tradingagents.dataflows.volatility._raw_pykrx_index_call",
               return_value=fake_df):
        s = fetch_vkospi(date(2026, 5, 8), date(2026, 5, 10))
    assert s.iloc[-1] == 20.8
```

- [ ] **Step 2: 실행 (실패)**

Run: `pytest tests/unit/test_volatility.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`tradingagents/dataflows/volatility.py`:

```python
from datetime import date

import pandas as pd

from tradingagents.dataflows.fred import fetch_fred_series


VKOSPI_INDEX_CODE = "1037"  # KRX VKOSPI 지수 코드


def fetch_vix(start: date, end: date, api_key: str | None = None) -> pd.Series:
    """VIX from FRED (VIXCLS)."""
    return fetch_fred_series("vix_close", start, end, api_key=api_key)


def _raw_pykrx_index_call(code: str, start: date, end: date) -> pd.DataFrame:
    """Direct pykrx index call. Wrapped for mocking."""
    from pykrx import stock
    return stock.get_index_ohlcv(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), code)


def fetch_vkospi(start: date, end: date) -> pd.Series:
    """VKOSPI close from KRX via pykrx."""
    df = _raw_pykrx_index_call(VKOSPI_INDEX_CODE, start, end)
    return df["종가"].rename("VKOSPI")
```

- [ ] **Step 4: 테스트 통과**

Run: `pytest tests/unit/test_volatility.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/volatility.py tests/unit/test_volatility.py
git commit -m "feat(dataflows): add volatility module (VIX from FRED, VKOSPI from pykrx)"
```

---

### Task 20: News Macro 모듈 (RSS + 캘린더)

**Files:**
- Create: `tradingagents/dataflows/news_macro.py`
- Create: `tests/unit/test_news_macro.py`

- [ ] **Step 1: 실패 테스트**

`tests/unit/test_news_macro.py`:

```python
from datetime import date, datetime
from unittest.mock import patch

from tradingagents.dataflows.news_macro import (
    fetch_macro_news, fetch_calendar_events,
)
from tradingagents.schemas.news import NewsItem, CalendarEvent


def test_fetch_news_returns_items():
    fake_feed = type("F", (), {})()
    fake_feed.entries = [
        {
            "title": "Fed signals 25bp cut",
            "link": "https://example.com/x",
            "published_parsed": (2026, 5, 10, 14, 30, 0, 0, 0, 0),
        },
    ]
    with patch("feedparser.parse", return_value=fake_feed):
        items = fetch_macro_news(["https://reuters.example/rss"], window_days=7)
    assert len(items) == 1
    assert isinstance(items[0], NewsItem)
    assert items[0].headline.startswith("Fed")


def test_fetch_calendar_minimal():
    events = fetch_calendar_events(date(2026, 5, 10), days=30)
    # FOMC schedule is hardcoded for now; check return type
    assert all(isinstance(e, CalendarEvent) for e in events)
```

- [ ] **Step 2: 실행 (실패)**

Run: `pytest tests/unit/test_news_macro.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`tradingagents/dataflows/news_macro.py`:

```python
import logging
from datetime import date, datetime, timedelta
from time import mktime

import feedparser

from tradingagents.schemas.news import CalendarEvent, NewsItem

logger = logging.getLogger(__name__)


# 2026 FOMC + BOK 일정 (수동 시드; 운용 중 신규 발표 시 갱신)
FOMC_DATES_2026 = [
    date(2026, 5, 14), date(2026, 6, 18), date(2026, 7, 30),
    date(2026, 9, 17), date(2026, 11, 5), date(2026, 12, 17),
]
BOK_DATES_2026 = [
    date(2026, 5, 22), date(2026, 7, 10), date(2026, 8, 28),
    date(2026, 10, 16), date(2026, 11, 27),
]


def fetch_macro_news(rss_urls: list[str], window_days: int = 7) -> list[NewsItem]:
    """Pull headlines from RSS sources. No body fetched (intentional — D2 schema lock)."""
    cutoff = datetime.utcnow() - timedelta(days=window_days)
    items: list[NewsItem] = []
    for url in rss_urls:
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            logger.warning("RSS fetch failed for %s: %s", url, e)
            continue
        for entry in feed.entries[:50]:
            try:
                published = datetime.fromtimestamp(mktime(entry["published_parsed"]))
                if published < cutoff:
                    continue
                items.append(NewsItem(
                    headline=entry["title"][:300],
                    source=feed.feed.get("title", url) if hasattr(feed, "feed") else url,
                    published_at=published,
                    url=entry.get("link", ""),
                ))
            except (KeyError, TypeError):
                continue
    return items


def fetch_calendar_events(as_of: date, days: int = 30) -> list[CalendarEvent]:
    """Return FOMC/BOK events within window."""
    end = as_of + timedelta(days=days)
    events: list[CalendarEvent] = []
    for d in FOMC_DATES_2026:
        if as_of <= d <= end:
            events.append(CalendarEvent(
                event_date=d, region="US", event_type="fomc",
                description="FOMC rate decision", consensus=None,
            ))
    for d in BOK_DATES_2026:
        if as_of <= d <= end:
            events.append(CalendarEvent(
                event_date=d, region="KR", event_type="bok",
                description="한국은행 통화정책방향 결정회의", consensus=None,
            ))
    return sorted(events, key=lambda e: e.event_date)
```

- [ ] **Step 4: 테스트 통과**

Run: `pytest tests/unit/test_news_macro.py -v`
Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/news_macro.py tests/unit/test_news_macro.py
git commit -m "feat(dataflows): add news_macro module (RSS + FOMC/BOK calendar)"
```

---

## Phase 5: Preset YAML Loader (D3 결정)

### Task 21: PresetSpec Pydantic 모델

**Files:**
- Create: `tradingagents/presets/__init__.py`
- Create: `tradingagents/presets/spec.py`
- Create: `tests/unit/test_preset_spec.py`

- [ ] **Step 1: 실패 테스트**

`tests/unit/test_preset_spec.py`:

```python
import pytest
from pydantic import ValidationError

from tradingagents.presets.spec import (
    PresetSpec, AgentSpec, StageSpec, ClusterMode,
)


def test_minimal_preset():
    p = PresetSpec(
        name="test",
        universe="data/u.json",
        capital_krw=1_000_000_000,
        stages=[
            StageSpec(
                id="analysts", parallel=True,
                agents=[
                    AgentSpec(
                        id="macro", skills=["fred_series"],
                        output_schema="MacroReport", model="deep",
                    )
                ],
            ),
        ],
    )
    assert p.name == "test"
    assert p.stages[0].parallel is True


def test_cluster_mode_enum():
    s = StageSpec(
        id="debate", cluster_mode=ClusterMode.SHARED_STATE,
        agents=[AgentSpec(id="bull", skills=[], output_schema="DebateMessage")],
    )
    assert s.cluster_mode == "shared_state"


def test_invalid_yaml_rejected():
    with pytest.raises(ValidationError):
        PresetSpec(
            name="bad",
            universe="x",
            capital_krw=-1,  # negative invalid
            stages=[],
        )
```

- [ ] **Step 2: 실행 (실패)**

Run: `pytest tests/unit/test_preset_spec.py -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

`tradingagents/presets/__init__.py`:

```python
"""Preset YAML system for DB GAPS agent (D3)."""
```

`tradingagents/presets/spec.py`:

```python
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ClusterMode(str, Enum):
    SHARED_STATE = "shared_state"      # debate cluster (D2)
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


ModelTier = Literal["deep", "quick"]


class AgentSpec(BaseModel):
    id: str
    skills: list[str] = Field(default_factory=list, description="Whitelisted skill names")
    output_schema: Optional[str] = Field(default=None, description="Pydantic class name")
    model: ModelTier = "deep"
    timeout_seconds: int = Field(default=180, ge=10)
    max_iterations: int = Field(default=25, ge=1)
    skill_prompt_base: Optional[str] = Field(default=None, description="Path to base prompt MD")
    cited_evidence_required: bool = False
    input_from: dict[str, str] = Field(
        default_factory=dict,
        description="Map of {context_key: source_agent_id} for handoff",
    )


class StageSpec(BaseModel):
    id: str
    parallel: bool = False
    cluster_mode: Optional[ClusterMode] = None
    rounds: int = Field(default=1, ge=1)
    agents: list[AgentSpec] = Field(min_length=1)
    judge: Optional[AgentSpec] = None
    on_fail: Optional[str] = Field(default=None, description="e.g., 'rerun_from(allocation, max_attempts=2)'")


class PresetSpec(BaseModel):
    name: str = Field(min_length=1)
    universe: str = Field(description="Path to universe.json")
    capital_krw: int = Field(ge=1)
    stages: list[StageSpec]
```

- [ ] **Step 4: 테스트 통과**

Run: `pytest tests/unit/test_preset_spec.py -v`
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/presets/__init__.py tradingagents/presets/spec.py tests/unit/test_preset_spec.py
git commit -m "feat(presets): add PresetSpec Pydantic models (D3)"
```

---

### Task 22: PresetLoader (YAML → typed)

**Files:**
- Create: `tradingagents/presets/loader.py`
- Create: `tests/fixtures/preset_minimal.yaml`
- Create: `tests/unit/test_preset_loader.py`

- [ ] **Step 1: 픽스처 생성**

`tests/fixtures/preset_minimal.yaml`:

```yaml
name: test_preset
universe: tests/fixtures/universe_test.json
capital_krw: 1_000_000_000

stages:
  - id: analysts
    parallel: true
    agents:
      - id: macro_quant
        skills: [fetch_fred_series, classify_regime]
        output_schema: MacroReport
        model: deep
        timeout_seconds: 180
        skill_prompt_base: prompts/macro-analysis.md
```

- [ ] **Step 2: 실패 테스트**

`tests/unit/test_preset_loader.py`:

```python
from pathlib import Path

import pytest

from tradingagents.presets.loader import PresetLoader, PresetLoadError
from tradingagents.skills.registry import (
    register_skill, clear_registry,
)


@pytest.fixture
def setup_skills():
    clear_registry()

    @register_skill(name="fetch_fred_series", category="macro")
    def f(): pass

    @register_skill(name="classify_regime", category="macro")
    def g(): pass


def test_load_validates_skills_exist(setup_skills):
    p = PresetLoader.from_yaml(Path("tests/fixtures/preset_minimal.yaml"))
    assert p.name == "test_preset"
    assert len(p.stages) == 1


def test_load_rejects_unknown_skill(tmp_path):
    clear_registry()
    bad = tmp_path / "bad.yaml"
    bad.write_text("""
name: bad
universe: x
capital_krw: 1
stages:
  - id: s1
    agents:
      - id: a1
        skills: [nonexistent_skill]
        output_schema: MacroReport
""")
    with pytest.raises(PresetLoadError, match="unknown skill"):
        PresetLoader.from_yaml(bad)
```

- [ ] **Step 3: 실행 (실패)**

Run: `pytest tests/unit/test_preset_loader.py -v`
Expected: ImportError.

- [ ] **Step 4: 구현**

`tradingagents/presets/loader.py`:

```python
from pathlib import Path

import yaml
from pydantic import ValidationError

from tradingagents.presets.spec import PresetSpec
from tradingagents.skills.registry import list_skills


class PresetLoadError(Exception):
    """Preset YAML failed to load or validate."""


class PresetLoader:
    """Load and validate a preset YAML file (D3)."""

    @staticmethod
    def from_yaml(path: Path | str) -> PresetSpec:
        path = Path(path)
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise PresetLoadError(f"YAML parse error in {path}: {e}") from e

        try:
            spec = PresetSpec.model_validate(raw)
        except ValidationError as e:
            raise PresetLoadError(f"Schema error in {path}: {e}") from e

        # Validate skill names against registry
        known = set(list_skills())
        for stage in spec.stages:
            for agent in stage.agents:
                for skill_name in agent.skills:
                    if skill_name not in known:
                        raise PresetLoadError(
                            f"unknown skill {skill_name!r} in agent {agent.id!r} "
                            f"(stage {stage.id!r}). Known: {sorted(known)[:5]}..."
                        )
        return spec
```

- [ ] **Step 5: 테스트 통과**

Run: `pytest tests/unit/test_preset_loader.py -v`
Expected: 2 PASSED.

- [ ] **Step 6: Commit**

```bash
git add tradingagents/presets/loader.py tests/fixtures/preset_minimal.yaml tests/unit/test_preset_loader.py
git commit -m "feat(presets): add PresetLoader with skill registry validation"
```

---

## Phase 6: Smoke 통합

### Task 23: Phase 1 통합 smoke 테스트

**Files:**
- Create: `tests/integration/test_phase1_smoke.py`

- [ ] **Step 1: smoke 테스트 작성**

`tests/integration/test_phase1_smoke.py`:

```python
"""End-to-end smoke for Phase 1 — wire everything together with mocks."""
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.dataflows.universe import sync_from_xlsx, load_universe
from tradingagents.dataflows.cache import TieredCache
from tradingagents.dataflows.pykrx_data import fetch_etf_ohlcv_batch, ParquetCache
from tradingagents.skills.registry import (
    register_skill, register_subagent, list_skills, clear_registry,
)


def test_phase1_wiring(tmp_path):
    """Universe + cache + skill registry all instantiate without errors."""
    # 1. Universe
    universe_json = tmp_path / "universe.json"
    sync_from_xlsx(Path("tests/fixtures/universe_test.xlsx"), universe_json)
    universe = load_universe(universe_json)
    assert len(universe.etfs) == 5

    # 2. Cache
    cache = TieredCache(cache_dir=tmp_path / "cache", name="smoke")
    val, staleness = cache.fetch_with_fallback(
        lambda: {"hello": "world"}, as_of=date(2026, 5, 10)
    )
    assert staleness == 0

    # 3. ParquetCache + pykrx
    parq = ParquetCache(tmp_path / "etf.parquet")
    fake_df = pd.DataFrame({
        "시가": [100], "고가": [110], "저가": [99], "종가": [105], "거래량": [1000]
    }, index=pd.to_datetime(["2026-05-10"]))
    with patch("tradingagents.dataflows.pykrx_data._raw_pykrx_call", return_value=fake_df):
        df = fetch_etf_ohlcv_batch(["A069500"], date(2026, 5, 10), date(2026, 5, 10), cache=parq)
    assert len(df) == 1

    # 4. Registry
    clear_registry()

    @register_skill(name="dummy", category="macro")
    def dummy(): pass

    assert "dummy" in list_skills()
```

- [ ] **Step 2: 실행**

Run: `pytest tests/integration/test_phase1_smoke.py -v`
Expected: 1 PASSED.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_phase1_smoke.py
git commit -m "test: add Phase 1 integration smoke (universe + cache + registry wiring)"
```

---

### Task 24: LangSmith tracing wrapper

**Files:**
- Create: `tradingagents/observability/__init__.py`
- Create: `tradingagents/observability/tracing.py`
- Create: `tests/unit/test_tracing.py`

- [ ] **Step 1: 실패 테스트**

```python
import os
from tradingagents.observability.tracing import setup_tracing, traced


def test_setup_no_op_when_disabled(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    setup_tracing()  # must not raise


def test_traced_decorator_passes_through():
    @traced(name="test_fn")
    def add(a, b):
        return a + b
    assert add(2, 3) == 5
```

- [ ] **Step 2: 구현**

`tradingagents/observability/__init__.py`:

```python
"""Observability — structured logging + LangSmith tracing."""
```

`tradingagents/observability/tracing.py`:

```python
"""Multi-agent tracing via LangSmith.

When LANGSMITH_TRACING=true, every analyst node, subagent skill, and LLM call
is captured as a span. View the run tree at https://smith.langchain.com/.

Usage:
    from tradingagents.observability.tracing import setup_tracing, traced
    setup_tracing()  # call once at app start

    @traced(name="my_skill")
    def my_skill(x):
        return x * 2
"""
import logging
import os
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def setup_tracing() -> None:
    """Enable LangSmith tracing if LANGSMITH_TRACING=true and key present.

    Must be called once at application start. LangChain auto-detects the
    environment variables; we just verify and log.
    """
    if os.getenv("LANGSMITH_TRACING", "false").lower() != "true":
        logger.info("LangSmith tracing disabled (set LANGSMITH_TRACING=true to enable)")
        return
    if not os.getenv("LANGSMITH_API_KEY"):
        logger.warning("LANGSMITH_TRACING=true but LANGSMITH_API_KEY missing; disabling")
        os.environ["LANGSMITH_TRACING"] = "false"
        return
    project = os.getenv("LANGSMITH_PROJECT", "db-gaps-agent")
    logger.info("LangSmith tracing enabled, project=%s", project)


def traced(name: str | None = None) -> Callable:
    """Decorator: wrap a callable as a LangSmith span.

    No-op when langsmith is not installed. Use on analyst nodes, skills, and
    any function whose I/O is worth inspecting in the run tree.
    """
    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        try:
            from langsmith import traceable
        except ImportError:
            return fn  # langsmith not installed — pass-through
        return traceable(name=name or fn.__name__)(fn)

    return decorator
```

- [ ] **Step 3: 테스트 통과**

Run: `pytest tests/unit/test_tracing.py -v`
Expected: 2 PASSED.

- [ ] **Step 4: Commit**

```bash
git add tradingagents/observability/ tests/unit/test_tracing.py
git commit -m "feat(observability): add LangSmith tracing wrapper for multi-agent debugging"
```

---

## Self-Review Checklist

Plan 1을 작성한 후 점검:

- ✅ 결정 사항 D3 (Pydantic PresetSpec + skill registry) → Task 11, 21, 22
- ✅ 결정 D5 (tiered cache) → Task 15
- ✅ 결정 D6 (BaseSubagent + 데코레이터) → Task 11, 13
- ✅ 결정 D7 (invoke_with_structured_retry helper) → Task 12
- ✅ 결정 D10 (pykrx 순차 + Parquet) → Task 16
- ✅ 스펙 §13 State 스키마 위한 토대 → Phase 1 Pydantic 모델
- ✅ 스펙 §14 환경 변수 → Task 2 default_config
- ✅ **Production hardening (revision 1):** TA-Lib → pandas-ta (Task 1)
- ✅ **Production hardening (revision 2):** tenacity 실제 적용 (Task 16, 17, 18)
- ✅ **Production hardening (revision 3):** publication_lag (look-ahead bias 방지) (Task 17, 18)
- ✅ **Production hardening (revision 4):** LangSmith tracing (Task 24)
- 코드 step마다 TDD 5-step 패턴 (write test → run fail → implement → run pass → commit)
- 모든 step에 실제 코드 포함, "TBD" 없음

---

## Plan 1 완료 시 산출물

24 tasks 완료 시:
- ✅ `tradingagents/dataflows/`: universe.py, cache.py, pykrx_data.py (tenacity), fred.py (point-in-time + tenacity), ecos.py (point-in-time + tenacity), volatility.py, news_macro.py
- ✅ `tradingagents/schemas/`: 7 도메인 모듈 (base, macro, risk, technical, news, portfolio, mandate, reports)
- ✅ `tradingagents/skills/`: registry.py, _base.py, _helpers.py
- ✅ `tradingagents/presets/`: spec.py, loader.py
- ✅ `tradingagents/observability/`: tracing.py (LangSmith)
- ✅ `tradingagents/default_config.py` 갱신 (publication_lag_days 포함)
- ✅ `pyproject.toml` 갱신 (TA-Lib 폐기, pandas-ta 채택)
- ✅ ~52개 단위 테스트 + 1개 통합 smoke

**다음:** Plan 2 (24 skills 구현) — `docs/superpowers/plans/2026-05-10-db-gaps-plan-2-skills.md`
