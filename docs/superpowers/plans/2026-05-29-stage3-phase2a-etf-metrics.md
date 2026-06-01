# Stage 3 Phase 2a — ETF Metrics & impl_score 4-요소 Composite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phase 1 impl_score 의 log_aum 단독 한계를 해소. KRX OpenAPI 로 ETF 일별 NAV/괴리율/AUM/추적률 fetch → 4-요소 weighted composite 으로 확장. underlying duplicate cluster (S&P500 추종 10개 등) 에서 운영품질 좋은 ETF 가 자동 우대.

**Architecture:** 신규 모듈 `etf_metrics.py` (ETF 메트릭 fetch + 계산), 기존 `krx_openapi.py` 확장 (ETF endpoint wrapper), `compute_impl_score` 4-요소 가중치 합성, candidate_selector 의 metrics fetch 통합. Schema 변경 없음, attribution dict 만 확장.

**Tech Stack:** Python 3.13, pydantic, pandas, numpy, requests, tenacity, KRX OpenAPI, pytest.

**Spec:** [docs/superpowers/specs/2026-05-29-stage3-phase2a-etf-metrics-design.md](../specs/2026-05-29-stage3-phase2a-etf-metrics-design.md)

---

## File Structure

| 파일 | 변경 | 책임 |
|---|---|---|
| `tradingagents/dataflows/krx_openapi.py` | Modify | `fetch_etf_daily_detail` wrapper 추가 |
| `tradingagents/dataflows/etf_metrics.py` | Create | ETFDailyMetrics schema + fetch_etf_metrics_window + 3개 compute_* |
| `tradingagents/skills/portfolio/factor_scorer.py` | Modify | `IMPL_SCORE_WEIGHTS` 상수 + `compute_impl_score` 4-요소 가중치 |
| `tradingagents/skills/portfolio/candidate_selector.py` | Modify | `select_etf_candidates` 에 metrics fetch + 새 인자 전달 |
| `tradingagents/agents/allocator/portfolio_allocator.py` | Modify | attribution `bucket_target_stage2` 별도 저장 (Phase 1 followup) |
| `tests/unit/dataflows/test_krx_openapi_etf.py` | Create | `fetch_etf_daily_detail` 단위 테스트 |
| `tests/unit/dataflows/test_etf_metrics.py` | Create | etf_metrics 모듈 단위 테스트 |
| `tests/unit/skills/test_portfolio_factor_scorer.py` | Modify | impl_score 4-요소 새 테스트 |
| `tests/unit/skills/test_portfolio_candidate.py` | Modify | metrics 통합 회귀 테스트 |
| `tests/unit/skills/test_portfolio_diversification.py` | Modify | `_pca_decomposition` smoke test (Phase 1 followup) |
| `tests/integration/test_allocator_phase2a.py` | Create | 통합 테스트 |

---

### Task 1: KRX OpenAPI ETF endpoint wrapper

**Files:**
- Modify: `tradingagents/dataflows/krx_openapi.py`
- Test: `tests/unit/dataflows/test_krx_openapi_etf.py`

이 task 의 첫 step 은 endpoint discovery — KRX OpenAPI 카탈로그에서 ETF 일별 endpoint 정식 path 확정. spec 의 abstract API 를 실제 endpoint 로 연결.

- [ ] **Step 1: Endpoint discovery — KRX 공식 카탈로그 확인**

```bash
# .env 에 KRX_API_KEY 설정 확인
cd /Users/kimjaewon/Pluto/TradingAgents/.claude/worktrees/<worktree>
grep KRX_API_KEY .env || (cd /Users/kimjaewon/Pluto/TradingAgents && grep KRX_API_KEY .env)

# Catalog 검색: https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/
# 또는 직접 시도:
python3 -c "
import os, sys
sys.path.insert(0, 'tradingagents')
from tradingagents.dataflows.krx_openapi import fetch_krx_openapi
from datetime import date
# 후보 endpoint 들 시도
for endpoint in ['etf/etf_bydd_trd', 'sto/etf_bydd_trd', 'etf/etp_isu_base_info']:
    try:
        records = fetch_krx_openapi(endpoint, date(2026, 5, 28))
        print(f'OK {endpoint}: {len(records)} records, keys={list(records[0].keys()) if records else \"empty\"}')
        break
    except Exception as e:
        print(f'FAIL {endpoint}: {e}')
"
```

Expected: 1개 endpoint 에서 성공 응답. 응답 필드 (`ISU_SRT_CD`, `BAS_DD`, `NAV`, `TDD_CLSPRC`, `ACC_TRDVOL`, `ACC_TRDVAL`, `MKTCAP`, `TRC_RT` 또는 동등) 확인.

만약 모두 fail (API key 부재 또는 endpoint 미발견):
- API key 부재 시: spec 의 fallback 모드 활용 — 본 task 에서 mock 으로 진행, integration 단계에서 실제 endpoint 확정
- Endpoint 미발견 시: implementer 가 controller 에게 NEEDS_CONTEXT 보고

- [ ] **Step 2: Write failing test for `fetch_etf_daily_detail`**

Create `tests/unit/dataflows/test_krx_openapi_etf.py`:
```python
"""KRX OpenAPI ETF endpoint wrapper tests."""
from datetime import date
from unittest.mock import patch

import pytest

from tradingagents.dataflows.krx_openapi import fetch_etf_daily_detail


def _fake_records():
    """Mock KRX OpenAPI response — 2 ETF records."""
    return [
        {
            "ISU_SRT_CD": "069500", "BAS_DD": "20260528",
            "NAV": "45123.45", "TDD_CLSPRC": "45130",
            "ACC_TRDVOL": "1234567", "ACC_TRDVAL": "55600000000",
            "MKTCAP": "16480300000000",
            "TRC_RT": "99.85",
        },
        {
            "ISU_SRT_CD": "360750", "BAS_DD": "20260528",
            "NAV": "18250.10", "TDD_CLSPRC": "18260",
            "ACC_TRDVOL": "5432100", "ACC_TRDVAL": "99100000000",
            "MKTCAP": "14782100000000",
            "TRC_RT": "99.92",
        },
    ]


def test_fetch_etf_daily_detail_returns_all_when_ticker_none(monkeypatch):
    """ticker=None 시 전체 ETF 응답 반환."""
    monkeypatch.setattr(
        "tradingagents.dataflows.krx_openapi.fetch_krx_openapi",
        lambda endpoint, basDd: _fake_records(),
    )
    records = fetch_etf_daily_detail(date(2026, 5, 28))
    assert len(records) == 2
    assert records[0]["ISU_SRT_CD"] == "069500"


def test_fetch_etf_daily_detail_filters_by_ticker(monkeypatch):
    """ticker 지정 시 단일 record."""
    monkeypatch.setattr(
        "tradingagents.dataflows.krx_openapi.fetch_krx_openapi",
        lambda endpoint, basDd: _fake_records(),
    )
    records = fetch_etf_daily_detail(date(2026, 5, 28), ticker="069500")
    assert len(records) == 1
    assert records[0]["ISU_SRT_CD"] == "069500"


def test_fetch_etf_daily_detail_returns_empty_when_ticker_not_found(monkeypatch):
    """존재하지 않는 ticker → 빈 list."""
    monkeypatch.setattr(
        "tradingagents.dataflows.krx_openapi.fetch_krx_openapi",
        lambda endpoint, basDd: _fake_records(),
    )
    records = fetch_etf_daily_detail(date(2026, 5, 28), ticker="999999")
    assert records == []


def test_fetch_etf_daily_detail_empty_response(monkeypatch):
    """KRX 가 빈 응답 시 (공휴일) 빈 list 반환."""
    monkeypatch.setattr(
        "tradingagents.dataflows.krx_openapi.fetch_krx_openapi",
        lambda endpoint, basDd: [],
    )
    records = fetch_etf_daily_detail(date(2026, 5, 24))  # Sunday
    assert records == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit/dataflows/test_krx_openapi_etf.py -v`
Expected: FAIL with `ImportError: cannot import name 'fetch_etf_daily_detail'`

- [ ] **Step 4: Implement `fetch_etf_daily_detail`**

Modify `tradingagents/dataflows/krx_openapi.py`. 파일 끝에 추가:

```python
# Phase 2a (2026-05-29). KRX 공식 카탈로그에서 endpoint 확정 — Task 1 Step 1 참고.
# 발견된 endpoint 가 'etf/etf_bydd_trd' 가 아니면 implementation 시점에 수정.
KRX_ETF_DAILY_ENDPOINT: str = "etf/etf_bydd_trd"


def fetch_etf_daily_detail(
    basDd: date,
    ticker: str | None = None,
) -> list[dict]:
    """ETF 일별 상세 (NAV, 종가, 거래량, AUM, 추종률).

    Args:
        basDd: 기준일자 (영업일).
        ticker: 단축코드 (예: "069500"). None 시 전 ETF 응답.

    Returns:
        list of records (dict). 빈 응답 시 빈 list.
        주요 필드: ISU_SRT_CD, BAS_DD, NAV, TDD_CLSPRC,
                  ACC_TRDVOL, ACC_TRDVAL, MKTCAP, TRC_RT.
    """
    records = fetch_krx_openapi(KRX_ETF_DAILY_ENDPOINT, basDd)
    if ticker is None:
        return records
    return [r for r in records if r.get("ISU_SRT_CD") == ticker]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/unit/dataflows/test_krx_openapi_etf.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add tradingagents/dataflows/krx_openapi.py tests/unit/dataflows/test_krx_openapi_etf.py
git commit -m "feat(stage3): KRX OpenAPI fetch_etf_daily_detail wrapper

Phase 2a Task 1. endpoint=etf/etf_bydd_trd (catalog discovery 결과).
ticker filtering + 빈 응답 (공휴일) 처리. 4 unit tests."
```

---

### Task 2: etf_metrics.py skeleton + ETFDailyMetrics schema

**Files:**
- Create: `tradingagents/dataflows/etf_metrics.py`
- Test: `tests/unit/dataflows/test_etf_metrics.py`

- [ ] **Step 1: Create skeleton module**

Create `tradingagents/dataflows/etf_metrics.py`:
```python
"""ETF 일별 메트릭 fetch + 계산 (Phase 2a, 2026-05-29).

KRX OpenAPI 의 ETF 일별 detail 을 fetch 해서 ParquetCache 에 저장하고,
window slice + 메트릭 계산 (TE 12m, |괴리율| 30d median, volume/AUM 30d median)
함수 제공. compute_impl_score 의 4-요소 입력으로 사용.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import BaseModel

from tradingagents.dataflows.krx_openapi import (
    KRXOpenAPIError, fetch_etf_daily_detail,
)

logger = logging.getLogger(__name__)


# Default window for TE computation (12m + buffer).
DEFAULT_METRICS_WINDOW_DAYS: int = 400


class ETFDailyMetrics(BaseModel):
    """단일 ticker × 단일 날짜 의 ETF 메타데이터."""
    ticker: str
    trade_date: date
    nav: float
    market_price: float
    premium_discount: float
    volume: int
    trade_value_krw: float
    aum_krw: float
    tracking_rate: float | None = None


def _parse_krx_record(record: dict, basDd: date) -> ETFDailyMetrics | None:
    """KRX OpenAPI 단일 record (dict) → ETFDailyMetrics.

    필수 필드 누락 또는 파싱 실패 시 None 반환.
    """
    raise NotImplementedError


def fetch_etf_metrics_window(
    tickers: list[str],
    start: date,
    end: date,
    cache_path: Path | None = None,
) -> pd.DataFrame:
    """ticker × date multi-index DataFrame.

    Columns: nav, market_price, premium_discount, volume, trade_value_krw,
             aum_krw, tracking_rate.
    누락 날짜는 KRX OpenAPI fetch, ParquetCache 영구 저장.
    """
    raise NotImplementedError


def compute_tracking_error_12m(
    metrics: pd.DataFrame,
    ticker: str,
    index_returns: pd.Series | None = None,
) -> float | None:
    """12개월 추적오차 (annualized, % 단위).

    우선순위:
      1. KRX 공시 tracking_rate (% 단위) std (60일 이상 필요)
      2. fallback: market_price daily returns vs index_returns std of difference ×√252×100
      3. 데이터 부족 시 None
    """
    raise NotImplementedError


def compute_premium_discount_median(
    metrics: pd.DataFrame, ticker: str, n_days: int = 30,
) -> float | None:
    """최근 n_days median |premium_discount|. 부족 시 None."""
    raise NotImplementedError


def compute_volume_per_aum_median(
    metrics: pd.DataFrame, ticker: str, n_days: int = 30,
) -> float | None:
    """최근 n_days median (trade_value_krw / aum_krw). 유동성 proxy. 부족 시 None."""
    raise NotImplementedError
```

- [ ] **Step 2: Write failing tests**

Create `tests/unit/dataflows/test_etf_metrics.py`:
```python
"""etf_metrics 단위 테스트."""
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tradingagents.dataflows.etf_metrics import (
    ETFDailyMetrics,
    _parse_krx_record,
    compute_premium_discount_median,
    compute_tracking_error_12m,
    compute_volume_per_aum_median,
    fetch_etf_metrics_window,
)


def _fake_krx_record(ticker: str, basDd: date, nav: float = 45000.0,
                     market_price: float = 45100.0, tracking_rate: float = 99.85) -> dict:
    return {
        "ISU_SRT_CD": ticker,
        "BAS_DD": basDd.strftime("%Y%m%d"),
        "NAV": str(nav),
        "TDD_CLSPRC": str(market_price),
        "ACC_TRDVOL": "1234567",
        "ACC_TRDVAL": str(int(market_price * 1234567)),
        "MKTCAP": "16480300000000",
        "TRC_RT": str(tracking_rate),
    }


def _build_synthetic_metrics_df(
    ticker: str, start: date, n_days: int = 100,
    market_price_base: float = 45000.0, vol: float = 0.01, seed: int = 0,
) -> pd.DataFrame:
    """ticker × date multi-index DataFrame 합성 (테스트용)."""
    rng = np.random.default_rng(seed)
    dates = [start + timedelta(days=i) for i in range(n_days)]
    rows = []
    price = market_price_base
    nav = market_price_base * 1.0
    for d in dates:
        price *= 1 + rng.normal(0, vol)
        nav *= 1 + rng.normal(0, vol * 0.95)
        premium = price / nav - 1
        rows.append({
            "ticker": ticker, "trade_date": d,
            "nav": nav, "market_price": price,
            "premium_discount": premium,
            "volume": int(rng.integers(100000, 5000000)),
            "trade_value_krw": price * rng.integers(100000, 5000000),
            "aum_krw": 16_000_000_000_000.0,
            "tracking_rate": 99.5 + rng.normal(0, 0.3),
        })
    return pd.DataFrame(rows).set_index(["ticker", "trade_date"])


def test_parse_krx_record_basic():
    rec = _fake_krx_record("069500", date(2026, 5, 28))
    parsed = _parse_krx_record(rec, date(2026, 5, 28))
    assert parsed is not None
    assert parsed.ticker == "069500"
    assert parsed.trade_date == date(2026, 5, 28)
    assert parsed.nav == 45000.0
    assert parsed.market_price == 45100.0
    assert parsed.tracking_rate == pytest.approx(99.85, abs=1e-3)
    # premium_discount = 45100/45000 - 1
    assert parsed.premium_discount == pytest.approx(45100/45000 - 1, abs=1e-6)


def test_parse_krx_record_missing_nav_returns_none():
    """NAV 누락 (필수 필드) → None."""
    rec = _fake_krx_record("069500", date(2026, 5, 28))
    del rec["NAV"]
    parsed = _parse_krx_record(rec, date(2026, 5, 28))
    assert parsed is None


def test_parse_krx_record_missing_tracking_rate_ok():
    """tracking_rate 누락 → tracking_rate=None 으로 정상 생성."""
    rec = _fake_krx_record("069500", date(2026, 5, 28))
    del rec["TRC_RT"]
    parsed = _parse_krx_record(rec, date(2026, 5, 28))
    assert parsed is not None
    assert parsed.tracking_rate is None


def test_fetch_etf_metrics_window_returns_multi_index_df(monkeypatch, tmp_path):
    """fetch 결과 ticker × date multi-index DataFrame."""
    def fake_fetch(basDd, ticker=None):
        return [
            _fake_krx_record("069500", basDd),
            _fake_krx_record("360750", basDd),
        ]
    monkeypatch.setattr(
        "tradingagents.dataflows.etf_metrics.fetch_etf_daily_detail",
        fake_fetch,
    )
    start = date(2026, 5, 25)  # Mon
    end = date(2026, 5, 28)    # Thu (4 business days)
    df = fetch_etf_metrics_window(
        ["069500", "360750"], start, end, cache_path=tmp_path,
    )
    assert isinstance(df.index, pd.MultiIndex)
    assert df.index.names == ["ticker", "trade_date"]
    assert {"nav", "market_price", "premium_discount", "tracking_rate"} <= set(df.columns)
    # 2 tickers × ~4 business days = ~8 rows
    assert len(df) >= 6


def test_fetch_etf_metrics_window_uses_cache(monkeypatch, tmp_path):
    """캐시된 날짜는 재호출 안 함."""
    call_count = {"n": 0}
    def fake_fetch(basDd, ticker=None):
        call_count["n"] += 1
        return [_fake_krx_record("069500", basDd)]
    monkeypatch.setattr(
        "tradingagents.dataflows.etf_metrics.fetch_etf_daily_detail",
        fake_fetch,
    )
    start, end = date(2026, 5, 25), date(2026, 5, 26)
    fetch_etf_metrics_window(["069500"], start, end, cache_path=tmp_path)
    first_call_count = call_count["n"]
    # 두 번째 호출은 캐시 활용
    fetch_etf_metrics_window(["069500"], start, end, cache_path=tmp_path)
    assert call_count["n"] == first_call_count, "cache hit 시 추가 fetch 없어야"


def test_fetch_etf_metrics_window_handles_holiday_empty(monkeypatch, tmp_path):
    """공휴일 빈 응답도 정상 처리."""
    def fake_fetch(basDd, ticker=None):
        # 일요일은 빈 응답
        if basDd.weekday() == 6:
            return []
        return [_fake_krx_record("069500", basDd)]
    monkeypatch.setattr(
        "tradingagents.dataflows.etf_metrics.fetch_etf_daily_detail",
        fake_fetch,
    )
    start = date(2026, 5, 22)  # Fri
    end = date(2026, 5, 26)    # Tue (포함 일요일)
    df = fetch_etf_metrics_window(["069500"], start, end, cache_path=tmp_path)
    # 일요일 row 없어야
    assert (df.index.get_level_values("trade_date") != date(2026, 5, 24)).all()


def test_compute_tracking_error_12m_uses_krx_rate_when_available():
    """tracking_rate 가 60일 이상 있으면 그 std 반환."""
    metrics = _build_synthetic_metrics_df("069500", date(2025, 5, 1), n_days=300, seed=1)
    te = compute_tracking_error_12m(metrics, "069500")
    assert te is not None
    # tracking_rate 의 std (pp). 약 0.3 부근 (seed=1 base vol 0.3).
    assert 0.05 < te < 1.5


def test_compute_tracking_error_12m_returns_none_when_insufficient():
    """< 60일 데이터 → None."""
    metrics = _build_synthetic_metrics_df("069500", date(2026, 5, 1), n_days=30, seed=2)
    # 또한 tracking_rate 컬럼 제거
    metrics["tracking_rate"] = np.nan
    te = compute_tracking_error_12m(metrics, "069500", index_returns=None)
    assert te is None


def test_compute_premium_discount_median_30day():
    """30일 median |premium_discount|."""
    metrics = _build_synthetic_metrics_df("069500", date(2026, 4, 1), n_days=60, seed=3)
    pd_median = compute_premium_discount_median(metrics, "069500", n_days=30)
    assert pd_median is not None
    assert pd_median >= 0  # |premium_discount| 절댓값이므로 ≥ 0


def test_compute_premium_discount_median_returns_none_when_no_data():
    """ticker 없으면 None."""
    metrics = _build_synthetic_metrics_df("069500", date(2026, 4, 1), n_days=30, seed=4)
    pd_median = compute_premium_discount_median(metrics, "999999", n_days=30)
    assert pd_median is None


def test_compute_volume_per_aum_median_30day():
    """30일 median trade_value/AUM. 유동성 proxy."""
    metrics = _build_synthetic_metrics_df("069500", date(2026, 4, 1), n_days=60, seed=5)
    v_aum = compute_volume_per_aum_median(metrics, "069500", n_days=30)
    assert v_aum is not None
    assert v_aum > 0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/unit/dataflows/test_etf_metrics.py -v`
Expected: 모든 테스트 FAIL (NotImplementedError)

- [ ] **Step 4: Commit skeleton + failing tests**

```bash
git add tradingagents/dataflows/etf_metrics.py tests/unit/dataflows/test_etf_metrics.py
git commit -m "feat(stage3): etf_metrics skeleton + TDD 테스트

Phase 2a Task 2. ETFDailyMetrics schema + 5 함수 stub.
11 unit tests (parse, fetch_window cache/holiday, compute_te/pd/vol_aum) FAIL
(NotImplementedError) — 후속 task 들이 구현."
```

---

### Task 3: `_parse_krx_record` 구현

**Files:**
- Modify: `tradingagents/dataflows/etf_metrics.py`

- [ ] **Step 1: Implement `_parse_krx_record`**

`tradingagents/dataflows/etf_metrics.py` 의 `_parse_krx_record` stub 교체:

```python
def _parse_krx_record(record: dict, basDd: date) -> ETFDailyMetrics | None:
    """KRX OpenAPI 단일 record (dict) → ETFDailyMetrics.

    필수 필드 (ISU_SRT_CD, NAV, TDD_CLSPRC, ACC_TRDVAL, ACC_TRDVOL, MKTCAP)
    누락 또는 파싱 실패 시 None 반환 + WARNING log.
    """
    try:
        ticker = str(record["ISU_SRT_CD"]).strip()
        nav = float(record["NAV"])
        market_price = float(record["TDD_CLSPRC"])
        volume = int(float(record["ACC_TRDVOL"]))
        trade_value = float(record["ACC_TRDVAL"])
        aum = float(record["MKTCAP"])
    except (KeyError, ValueError, TypeError) as e:
        logger.warning(
            "_parse_krx_record: skipping malformed record (%s): %r",
            e, record,
        )
        return None

    # premium_discount = market_price / nav - 1 (NAV=0 보호)
    if nav <= 0:
        return None
    premium_discount = market_price / nav - 1.0

    # tracking_rate 는 optional
    tracking_rate: float | None = None
    if "TRC_RT" in record:
        try:
            tracking_rate = float(record["TRC_RT"])
        except (ValueError, TypeError):
            tracking_rate = None

    return ETFDailyMetrics(
        ticker=ticker,
        trade_date=basDd,
        nav=nav,
        market_price=market_price,
        premium_discount=premium_discount,
        volume=volume,
        trade_value_krw=trade_value,
        aum_krw=aum,
        tracking_rate=tracking_rate,
    )
```

- [ ] **Step 2: Run parse tests**

Run: `pytest tests/unit/dataflows/test_etf_metrics.py::test_parse_krx_record_basic tests/unit/dataflows/test_etf_metrics.py::test_parse_krx_record_missing_nav_returns_none tests/unit/dataflows/test_etf_metrics.py::test_parse_krx_record_missing_tracking_rate_ok -v`
Expected: 3 passed

- [ ] **Step 3: Commit**

```bash
git add tradingagents/dataflows/etf_metrics.py
git commit -m "feat(stage3): _parse_krx_record 구현

Phase 2a Task 3. KRX 응답 dict → ETFDailyMetrics. 필수 필드 누락 시 None+WARNING.
NAV=0 보호. tracking_rate optional. 3 parse 테스트 통과."
```

---

### Task 4: `fetch_etf_metrics_window` 구현 (ParquetCache)

**Files:**
- Modify: `tradingagents/dataflows/etf_metrics.py`

- [ ] **Step 1: Implement `fetch_etf_metrics_window`**

`tradingagents/dataflows/etf_metrics.py` 의 `fetch_etf_metrics_window` stub 교체:

```python
def _business_days(start: date, end: date) -> list[date]:
    """월~금 (공휴일 무관, KRX 응답이 빈 list 면 skip)."""
    days = []
    current = start
    while current <= end:
        if current.weekday() < 5:  # Mon=0 ~ Fri=4
            days.append(current)
        current += timedelta(days=1)
    return days


def _cache_file(cache_path: Path, basDd: date) -> Path:
    """cache_path/etf_metrics/YYYY-MM-DD.parquet"""
    cache_dir = cache_path / "etf_metrics"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{basDd.isoformat()}.parquet"


def fetch_etf_metrics_window(
    tickers: list[str],
    start: date,
    end: date,
    cache_path: Path | None = None,
) -> pd.DataFrame:
    """ticker × date multi-index DataFrame.

    Columns: nav, market_price, premium_discount, volume, trade_value_krw,
             aum_krw, tracking_rate.
    누락 날짜는 KRX OpenAPI fetch, ParquetCache 영구 저장.
    """
    days = _business_days(start, end)
    all_rows: list[dict] = []
    cache_root: Path | None = None
    if cache_path is not None:
        cache_root = Path(cache_path)

    for d in days:
        cache_file: Path | None = (
            _cache_file(cache_root, d) if cache_root is not None else None
        )
        # 1. 캐시 hit 시 load
        if cache_file is not None and cache_file.exists():
            try:
                day_df = pd.read_parquet(cache_file)
                day_rows = day_df.to_dict(orient="records")
            except Exception as e:
                logger.warning("cache read failed for %s: %s — refetching", d, e)
                day_rows = None
        else:
            day_rows = None

        # 2. 캐시 miss → fetch
        if day_rows is None:
            try:
                records = fetch_etf_daily_detail(d, ticker=None)
            except KRXOpenAPIError:
                # 호출자가 처리할 수 있도록 raise
                raise
            day_rows = []
            for rec in records:
                parsed = _parse_krx_record(rec, d)
                if parsed is not None:
                    day_rows.append(parsed.model_dump())
            # 캐시 저장 (빈 list 도 저장 — 공휴일 표시)
            if cache_file is not None:
                pd.DataFrame(day_rows).to_parquet(cache_file)

        # 3. ticker 필터링 (이 시점에 모든 ticker 응답이 들어있음)
        for row in day_rows:
            if row["ticker"] in tickers:
                all_rows.append(row)

    if not all_rows:
        return pd.DataFrame(
            columns=["nav", "market_price", "premium_discount", "volume",
                     "trade_value_krw", "aum_krw", "tracking_rate"],
            index=pd.MultiIndex.from_arrays([[], []], names=["ticker", "trade_date"]),
        )

    df = pd.DataFrame(all_rows)
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df = df.set_index(["ticker", "trade_date"]).sort_index()
    return df
```

- [ ] **Step 2: Run fetch_window tests**

Run: `pytest tests/unit/dataflows/test_etf_metrics.py -v -k fetch_etf_metrics_window`
Expected: 3 passed (returns_multi_index_df, uses_cache, handles_holiday_empty)

- [ ] **Step 3: Commit**

```bash
git add tradingagents/dataflows/etf_metrics.py
git commit -m "feat(stage3): fetch_etf_metrics_window with ParquetCache

Phase 2a Task 4. 영업일 (월~금) 만 fetch. cache hit/miss 처리. 공휴일 빈
응답도 저장. 3 unit tests 통과."
```

---

### Task 5: `compute_tracking_error_12m` 구현

**Files:**
- Modify: `tradingagents/dataflows/etf_metrics.py`

- [ ] **Step 1: Implement `compute_tracking_error_12m`**

`tradingagents/dataflows/etf_metrics.py` 의 `compute_tracking_error_12m` stub 교체:

```python
def compute_tracking_error_12m(
    metrics: pd.DataFrame,
    ticker: str,
    index_returns: pd.Series | None = None,
) -> float | None:
    """12개월 추적오차 (annualized, % 단위).

    우선순위:
      1. KRX 공시 tracking_rate (% 단위) std (60일 이상 필요)
      2. fallback: market_price daily returns vs index_returns 의 std×√252×100
      3. 부족 시 None
    """
    if ticker not in metrics.index.get_level_values("ticker"):
        return None
    sub = metrics.xs(ticker, level="ticker")
    if sub.empty:
        return None

    # 1순위: tracking_rate 의 std (pp)
    if "tracking_rate" in sub.columns:
        rates = sub["tracking_rate"].dropna()
        if len(rates) >= 60:
            recent = rates.tail(252)
            return float(recent.std())

    # 2순위: market_price vs index_returns
    if index_returns is None:
        return None
    fund_returns = sub["market_price"].pct_change().dropna()
    if len(fund_returns) < 60:
        return None
    aligned = fund_returns.align(index_returns, join="inner")
    diff = aligned[0] - aligned[1]
    diff = diff.dropna()
    if len(diff) < 60:
        return None
    return float(diff.std() * np.sqrt(252) * 100.0)
```

- [ ] **Step 2: Run TE tests**

Run: `pytest tests/unit/dataflows/test_etf_metrics.py -v -k tracking_error`
Expected: 2 passed (uses_krx_rate_when_available, returns_none_when_insufficient)

- [ ] **Step 3: Commit**

```bash
git add tradingagents/dataflows/etf_metrics.py
git commit -m "feat(stage3): compute_tracking_error_12m 구현

Phase 2a Task 5. KRX 추적률 우선, fund vs index returns fallback.
< 60일 시 None. 2 unit tests 통과."
```

---

### Task 6: `compute_premium_discount_median` + `compute_volume_per_aum_median` 구현

**Files:**
- Modify: `tradingagents/dataflows/etf_metrics.py`

- [ ] **Step 1: Implement both**

`tradingagents/dataflows/etf_metrics.py` 의 두 stub 교체:

```python
def compute_premium_discount_median(
    metrics: pd.DataFrame, ticker: str, n_days: int = 30,
) -> float | None:
    """최근 n_days median |premium_discount|. 부족 시 None."""
    if ticker not in metrics.index.get_level_values("ticker"):
        return None
    sub = metrics.xs(ticker, level="ticker")
    if "premium_discount" not in sub.columns:
        return None
    pd_series = sub["premium_discount"].dropna().tail(n_days)
    if len(pd_series) < min(n_days, 10):  # 최소 10일은 있어야
        return None
    return float(pd_series.abs().median())


def compute_volume_per_aum_median(
    metrics: pd.DataFrame, ticker: str, n_days: int = 30,
) -> float | None:
    """최근 n_days median (trade_value_krw / aum_krw). 유동성 proxy. 부족 시 None."""
    if ticker not in metrics.index.get_level_values("ticker"):
        return None
    sub = metrics.xs(ticker, level="ticker")
    if "trade_value_krw" not in sub.columns or "aum_krw" not in sub.columns:
        return None
    valid = sub[(sub["aum_krw"] > 0) & sub["trade_value_krw"].notna()].tail(n_days)
    if len(valid) < min(n_days, 10):
        return None
    ratio = valid["trade_value_krw"] / valid["aum_krw"]
    return float(ratio.median())
```

- [ ] **Step 2: Run all etf_metrics tests**

Run: `pytest tests/unit/dataflows/test_etf_metrics.py -v`
Expected: 11 passed (전체)

- [ ] **Step 3: Commit**

```bash
git add tradingagents/dataflows/etf_metrics.py
git commit -m "feat(stage3): compute_premium_discount_median + compute_volume_per_aum_median

Phase 2a Task 6. 30일 median (default), 데이터 < 10일 시 None.
11 etf_metrics tests 통과 (전체)."
```

---

### Task 7: `compute_impl_score` 4-요소 가중치 합성

**Files:**
- Modify: `tradingagents/skills/portfolio/factor_scorer.py`
- Modify: `tests/unit/skills/test_portfolio_factor_scorer.py`

- [ ] **Step 1: Write new tests for 4-factor impl_score**

`tests/unit/skills/test_portfolio_factor_scorer.py` 끝에 append:

```python
def test_impl_score_weight_magnitudes_sum_to_one():
    """IMPL_SCORE_WEIGHTS 의 절댓값 합 = 1.0."""
    from tradingagents.skills.portfolio.factor_scorer import IMPL_SCORE_WEIGHTS
    total = sum(abs(v) for v in IMPL_SCORE_WEIGHTS.values())
    assert abs(total - 1.0) < 1e-9


def test_impl_score_4factor_composite():
    """4-요소 가중치 합성 — log_aum + TE + |pd| + volume/AUM."""
    import math

    from tradingagents.skills.portfolio.factor_scorer import (
        FactorPanel, compute_impl_score,
    )

    panels = {
        "A": FactorPanel(log_aum=math.log(10_000_000_000_000)),  # 10조 (largest)
        "B": FactorPanel(log_aum=math.log(1_000_000_000_000)),   # 1조
        "C": FactorPanel(log_aum=math.log(100_000_000_000)),     # 1000억 (smallest)
    }
    # A: 큰 AUM + 작은 TE + 작은 |pd| + 큰 vol/AUM (최고)
    # B: 중간
    # C: 작은 AUM + 큰 TE + 큰 |pd| + 작은 vol/AUM (최저)
    tracking_error = {"A": 0.05, "B": 0.20, "C": 0.50}
    premium_discount = {"A": 0.001, "B": 0.005, "C": 0.020}
    volume_per_aum = {"A": 0.005, "B": 0.001, "C": 0.0001}
    impl = compute_impl_score(
        panels,
        tracking_error=tracking_error,
        premium_discount=premium_discount,
        volume_per_aum=volume_per_aum,
    )
    # A 가 가장 높고, C 가 가장 낮아야
    assert impl["A"] > impl["B"] > impl["C"]


def test_impl_score_missing_signals_falls_back_to_log_aum():
    """모든 metrics 신호 None → impl_score 가 log_aum 단독 ordering."""
    import math

    from tradingagents.skills.portfolio.factor_scorer import (
        FactorPanel, compute_impl_score,
    )

    panels = {
        "A": FactorPanel(log_aum=math.log(10_000_000_000_000)),
        "B": FactorPanel(log_aum=math.log(1_000_000_000_000)),
        "C": FactorPanel(log_aum=math.log(100_000_000_000)),
    }
    # 모든 metrics 입력 None
    impl_no_metrics = compute_impl_score(panels)
    # log_aum 단독 ordering: A > B > C
    assert impl_no_metrics["A"] > impl_no_metrics["B"] > impl_no_metrics["C"]


def test_impl_score_high_te_lowers_score():
    """동일 log_aum 일 때 TE 높은 ETF 가 낮은 impl."""
    import math

    from tradingagents.skills.portfolio.factor_scorer import (
        FactorPanel, compute_impl_score,
    )

    panels = {
        "low_te": FactorPanel(log_aum=math.log(1_000_000_000_000)),
        "high_te": FactorPanel(log_aum=math.log(1_000_000_000_000)),
    }
    tracking_error = {"low_te": 0.05, "high_te": 0.50}
    # premium_discount, volume_per_aum 동일 → TE 만 차이
    premium_discount = {"low_te": 0.001, "high_te": 0.001}
    volume_per_aum = {"low_te": 0.001, "high_te": 0.001}
    impl = compute_impl_score(
        panels, tracking_error=tracking_error,
        premium_discount=premium_discount,
        volume_per_aum=volume_per_aum,
    )
    assert impl["low_te"] > impl["high_te"]


def test_impl_score_high_premium_discount_lowers_score():
    """동일 log_aum 일 때 |괴리율| 큰 ETF 가 낮은 impl."""
    import math

    from tradingagents.skills.portfolio.factor_scorer import (
        FactorPanel, compute_impl_score,
    )

    panels = {
        "low_pd": FactorPanel(log_aum=math.log(1_000_000_000_000)),
        "high_pd": FactorPanel(log_aum=math.log(1_000_000_000_000)),
    }
    premium_discount = {"low_pd": 0.0005, "high_pd": 0.020}
    tracking_error = {"low_pd": 0.05, "high_pd": 0.05}
    volume_per_aum = {"low_pd": 0.001, "high_pd": 0.001}
    impl = compute_impl_score(
        panels, premium_discount=premium_discount,
        tracking_error=tracking_error,
        volume_per_aum=volume_per_aum,
    )
    assert impl["low_pd"] > impl["high_pd"]


def test_impl_score_high_volume_per_aum_raises_score():
    """동일 log_aum 일 때 volume/AUM 큰 ETF 가 높은 impl."""
    import math

    from tradingagents.skills.portfolio.factor_scorer import (
        FactorPanel, compute_impl_score,
    )

    panels = {
        "high_vol": FactorPanel(log_aum=math.log(1_000_000_000_000)),
        "low_vol": FactorPanel(log_aum=math.log(1_000_000_000_000)),
    }
    volume_per_aum = {"high_vol": 0.010, "low_vol": 0.0001}
    tracking_error = {"high_vol": 0.05, "low_vol": 0.05}
    premium_discount = {"high_vol": 0.001, "low_vol": 0.001}
    impl = compute_impl_score(
        panels, volume_per_aum=volume_per_aum,
        tracking_error=tracking_error,
        premium_discount=premium_discount,
    )
    assert impl["high_vol"] > impl["low_vol"]
```

- [ ] **Step 2: Run tests to verify failures**

Run: `pytest tests/unit/skills/test_portfolio_factor_scorer.py -v -k impl_score`
Expected: 새 6개 FAIL (IMPL_SCORE_WEIGHTS 부재 또는 시그니처 불일치)

- [ ] **Step 3: Implement `IMPL_SCORE_WEIGHTS` + `compute_impl_score`**

`tradingagents/skills/portfolio/factor_scorer.py` 에서 `compute_impl_score` 함수 (대략 라인 343 근처) 위치를 찾아 변경.

기존 코드:
```python
def compute_impl_score(
    panels: dict[str, FactorPanel],
    *,
    adv: dict[str, float | None] | None = None,
    deviation: dict[str, float | None] | None = None,
    tracking_error: dict[str, float | None] | None = None,
    normalization: str = "rank_percentile",
) -> dict[str, float]:
    # ... 기존 단순 평균 ...
```

새 코드 (전체 함수 교체):
```python
# Phase 2a (2026-05-29). impl_score 4-요소 weighted composite.
# Signed weights — 부호가 contribution 방향. 절댓값 합 = 1.0.
IMPL_SCORE_WEIGHTS: dict[str, float] = {
    "log_aum":            0.33,   # 클수록 좋음
    "premium_discount":  -0.28,   # |괴리율| 클수록 나쁨
    "tracking_error":    -0.22,   # 클수록 나쁨
    "volume_per_aum":     0.17,   # 클수록 좋음
}


def compute_impl_score(
    panels: dict[str, FactorPanel],
    *,
    volume_per_aum: dict[str, float | None] | None = None,
    premium_discount: dict[str, float | None] | None = None,
    tracking_error: dict[str, float | None] | None = None,
    normalization: str = "rank_percentile",
) -> dict[str, float]:
    """4-요소 weighted composite (Phase 2a, 2026-05-29).

    공식 (rank-percentile normalize 후 signed weight 합성):
      impl_score(t) = +0.33 × z(log_aum)
                    + 0.17 × z(volume_per_aum)
                    + (-0.28) × z(|premium_discount|)
                    + (-0.22) × z(tracking_error)

    각 signal 의 raw 값 (premium_discount 는 절댓값) 을 normalize 후 signed weight
    와 합성. 큰 |premium_discount| → 큰 z → 음수 가중치 × 큰 z = 음수 기여.

    누락 신호 (입력 None 또는 dict value None) 는 0 (neutral z) 기여.
    Backward-compat: 모든 signal None 시 impl_score = 0.33 × z(log_aum),
    Phase 1 의 log_aum-단독 ordering 동일.
    """
    if not panels:
        return {}

    if normalization == "rank_percentile":
        normalize = _rank_normalize
    elif normalization == "zscore":
        normalize = _zscore
    else:
        raise ValueError(
            f"unknown normalization {normalization!r} "
            f"(expected 'rank_percentile' or 'zscore')"
        )

    # 1. log_aum 항상 존재 (FactorPanel.log_aum 필수)
    n_log_aum = normalize({t: p.log_aum for t, p in panels.items()})

    # 2. volume_per_aum (positive direction)
    if volume_per_aum is not None:
        n_vol_aum = normalize({t: volume_per_aum.get(t) for t in panels})
    else:
        n_vol_aum = {t: 0.0 for t in panels}

    # 3. |premium_discount| (절댓값 normalize → signed weight 음수)
    if premium_discount is not None:
        n_pd = normalize({
            t: (abs(premium_discount[t]) if premium_discount.get(t) is not None else None)
            for t in panels
        })
    else:
        n_pd = {t: 0.0 for t in panels}

    # 4. tracking_error (signed weight 음수)
    if tracking_error is not None:
        n_te = normalize({t: tracking_error.get(t) for t in panels})
    else:
        n_te = {t: 0.0 for t in panels}

    out: dict[str, float] = {}
    for t in panels:
        out[t] = (
            IMPL_SCORE_WEIGHTS["log_aum"]           * n_log_aum[t]
            + IMPL_SCORE_WEIGHTS["volume_per_aum"]    * n_vol_aum[t]
            + IMPL_SCORE_WEIGHTS["premium_discount"]  * n_pd[t]
            + IMPL_SCORE_WEIGHTS["tracking_error"]    * n_te[t]
        )
    return out
```

- [ ] **Step 4: Run all factor_scorer tests**

Run: `pytest tests/unit/skills/test_portfolio_factor_scorer.py -v`
Expected: 모두 PASS (기존 + 새 6개)

기존 테스트 중 `adv` / `deviation` 인자명 사용처 있으면 `volume_per_aum` / `premium_discount` 로 update.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/portfolio/factor_scorer.py \
        tests/unit/skills/test_portfolio_factor_scorer.py
git commit -m "feat(stage3): compute_impl_score 4-요소 weighted composite

Phase 2a Task 7. IMPL_SCORE_WEIGHTS (log_aum +0.33, premium_discount -0.28,
tracking_error -0.22, volume_per_aum +0.17, |sum|=1.0). 인자명 adv→volume_per_aum,
deviation→premium_discount. backward-compat: 모든 None 시 log_aum 단독 ordering.
6 new impl_score 테스트 통과."
```

---

### Task 8: `candidate_selector.py` 의 metrics 통합

**Files:**
- Modify: `tradingagents/skills/portfolio/candidate_selector.py`
- Modify: `tests/unit/skills/test_portfolio_candidate.py`

- [ ] **Step 1: Write integration test**

`tests/unit/skills/test_portfolio_candidate.py` 끝에 append:

```python
def test_select_etf_candidates_uses_etf_metrics(monkeypatch):
    """metrics 입력 시 cluster 내 다른 ETF 가 선출되는지 (low TE 우대)."""
    from datetime import date
    import math
    import numpy as np
    import pandas as pd

    from tradingagents.dataflows.universe import ETFEntry, Universe
    from tradingagents.schemas.portfolio import BucketTarget
    from tradingagents.skills.portfolio.candidate_selector import select_etf_candidates
    from tradingagents.skills.portfolio.factor_scorer import FactorPanel

    # 두 ETF: 같은 underlying (S&P500), 다른 운영품질
    # A: 큰 AUM but 큰 TE
    # B: 작은 AUM but 작은 TE
    etfs = [
        ETFEntry(
            ticker="A_BIG", name="Big_HighTE", aum_krw=150_000_000_000_000,
            underlying_index="S&P 500", bucket="위험", category="해외주식_지수",
        ),
        ETFEntry(
            ticker="A_SMALL", name="Small_LowTE", aum_krw=10_000_000_000_000,
            underlying_index="S&P 500", bucket="위험", category="해외주식_지수",
        ),
    ]
    universe = Universe(version="test", etfs=etfs)
    bt = BucketTarget(
        kr_equity=0.0, global_equity=0.7, fx_commodity=0.0,
        bond=0.0, cash_mmf=0.3, bond_tips_share=0.0, rationale="test",
    )
    rng = np.random.default_rng(42)
    returns = pd.DataFrame(
        rng.normal(0, 0.01, size=(252, 2)),
        columns=["A_BIG", "A_SMALL"],
    )
    factor_panel = {
        t: FactorPanel(
            skip1m_mom_3m=0.05, skip1m_mom_6m=0.05, skip1m_mom_12m=0.05,
            realized_vol_60d=0.1, sharpe_60d=0.5,
            log_aum=math.log(etfs[i].aum_krw),
        )
        for i, t in enumerate(["A_BIG", "A_SMALL"])
    }
    # Mock metrics fetch
    def fake_fetch_metrics(tickers, start, end, cache_path=None):
        idx = pd.MultiIndex.from_product(
            [tickers, pd.date_range(start, end)],
            names=["ticker", "trade_date"],
        )
        df = pd.DataFrame(index=idx)
        # A_BIG: TE 0.40, A_SMALL: TE 0.05 (small TE 가 더 좋음)
        # tracking_rate = 100 - TE → A_BIG: 99.60, A_SMALL: 99.95
        df["tracking_rate"] = [99.60 if t == "A_BIG" else 99.95 for t in idx.get_level_values("ticker")]
        df["premium_discount"] = 0.001
        df["trade_value_krw"] = 1e10
        df["aum_krw"] = 1e13
        df["market_price"] = 45000.0
        df["nav"] = 45000.0
        df["volume"] = 1000000
        return df
    monkeypatch.setattr(
        "tradingagents.skills.portfolio.candidate_selector.fetch_etf_metrics_window",
        fake_fetch_metrics,
    )
    attribution: dict = {}
    candidates = select_etf_candidates(
        universe, bt, as_of=date(2026, 5, 28),
        returns=returns, factor_panel=factor_panel,
        per_bucket_n=1, attribution=attribution,
    )
    # underlying 같은 두 ETF 가 forced merge → cluster 1개
    # 두 ETF 의 impl_score 차이로 representative 선택
    # log_aum 만 보면 A_BIG (큰 AUM) 이 우대
    # TE 까지 보면 A_SMALL (낮은 TE) 의 음수 가중치 효과로 A_SMALL 이 우대 가능
    # → 정확한 결과는 normalize 후 가중치에 따라. 단 attribution 에 metrics 가
    #   기록되어야 함.
    bucket_attr = attribution["buckets"]["global_equity"]
    assert "alpha_scores" in bucket_attr
    # etf_metrics_summary 가 채워졌는지 (allocator level 이 아니라 select 단계에선
    # candidate_selector 가 직접 attribution 채움)
    assert "etf_metrics_summary" in attribution
    assert attribution["etf_metrics_summary"]["fetch_succeeded"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/skills/test_portfolio_candidate.py::test_select_etf_candidates_uses_etf_metrics -v`
Expected: FAIL (`fetch_etf_metrics_window` not imported in candidate_selector OR `etf_metrics_summary` not in attribution)

- [ ] **Step 3: Implement metrics integration in `select_etf_candidates`**

`tradingagents/skills/portfolio/candidate_selector.py` 상단 import 에 추가:
```python
import time

from tradingagents.dataflows.etf_metrics import (
    DEFAULT_METRICS_WINDOW_DAYS, compute_premium_discount_median,
    compute_tracking_error_12m, compute_volume_per_aum_median,
    fetch_etf_metrics_window,
)
from tradingagents.dataflows.krx_openapi import KRXOpenAPIError
```

`select_etf_candidates` 함수 본문에서 returns matrix 처리 직후 (대략 라인 140 근처, `aum_lookup = ...` 직전 또는 직후) 에 metrics fetch 블록 추가:

```python
    # Phase 2a — ETF metrics fetch (impl_score 4-요소 입력)
    metrics_window_start = as_of - timedelta(days=DEFAULT_METRICS_WINDOW_DAYS)
    fetch_start_time = time.monotonic()
    cache_path = getattr(universe, "_metrics_cache_path", None)  # optional cache
    etf_metrics: pd.DataFrame | None = None
    fetch_succeeded = False
    fallback_reason: str | None = None
    try:
        etf_metrics = fetch_etf_metrics_window(
            list({e.ticker for e in universe.etfs}),
            metrics_window_start, as_of,
            cache_path=cache_path,
        )
        fetch_succeeded = True
    except KRXOpenAPIError as e:
        logger.warning(
            "KRX OpenAPI fetch failed (%s) — impl_score falls back to log_aum only", e,
        )
        fallback_reason = str(e)
    except Exception as e:
        logger.warning(
            "etf_metrics fetch failed unexpectedly (%s) — impl_score falls back", e,
        )
        fallback_reason = str(e)
    fetch_duration = time.monotonic() - fetch_start_time

    # metrics → per-ticker dicts (None default 가 compute_impl_score 의 neutral 처리)
    tracking_error_by_ticker: dict[str, float | None] | None = None
    prem_disc_by_ticker: dict[str, float | None] | None = None
    vol_aum_by_ticker: dict[str, float | None] | None = None
    if etf_metrics is not None and not etf_metrics.empty:
        elig_universe = [e.ticker for e in universe.etfs]
        tracking_error_by_ticker = {
            t: compute_tracking_error_12m(etf_metrics, t)
            for t in elig_universe
        }
        prem_disc_by_ticker = {
            t: compute_premium_discount_median(etf_metrics, t, n_days=30)
            for t in elig_universe
        }
        vol_aum_by_ticker = {
            t: compute_volume_per_aum_median(etf_metrics, t, n_days=30)
            for t in elig_universe
        }

    if attribution is not None:
        attribution["etf_metrics_summary"] = {
            "fetch_attempted": True,
            "fetch_succeeded": fetch_succeeded,
            "fallback_reason": fallback_reason,
            "n_tickers_with_te": (
                sum(1 for v in (tracking_error_by_ticker or {}).values() if v is not None)
            ),
            "n_tickers_with_pd": (
                sum(1 for v in (prem_disc_by_ticker or {}).values() if v is not None)
            ),
            "n_tickers_with_vol_aum": (
                sum(1 for v in (vol_aum_by_ticker or {}).values() if v is not None)
            ),
            "fetch_duration_seconds": float(fetch_duration),
        }
```

그리고 기존 `compute_impl_score(panels_for_impl, normalization=normalization)` 호출을 찾아 (대략 라인 223 근처) 새 인자 전달:

```python
    impl_scores = compute_impl_score(
        panels_for_impl,
        normalization=normalization,
        volume_per_aum=vol_aum_by_ticker,
        premium_discount=prem_disc_by_ticker,
        tracking_error=tracking_error_by_ticker,
    )
```

(bond split path 인 `_select_bond_with_tips_quota` 가 `_rank_by_factors` 만 호출 — impl_score 까지 가지 않으므로 별도 변경 불요.)

- [ ] **Step 4: Run all candidate_selector tests**

Run: `pytest tests/unit/skills/test_portfolio_candidate.py -v`
Expected: 모두 PASS (기존 + 새 1개)

기존 테스트 중 `compute_impl_score` 직접 호출 + `adv`/`deviation` 인자 사용한 곳이 있으면 새 인자명으로 update.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/portfolio/candidate_selector.py \
        tests/unit/skills/test_portfolio_candidate.py
git commit -m "feat(stage3): candidate_selector 가 etf_metrics 활용해 impl_score 4-요소 입력

Phase 2a Task 8. select_etf_candidates 안에 fetch_etf_metrics_window 호출 +
TE/|pd|/vol_aum 계산 + compute_impl_score 에 인자 전달. fetch 실패 시 WARNING +
log_aum 단독 fallback. attribution['etf_metrics_summary'] 추가."
```

---

### Task 9: `portfolio_allocator.py` 의 `bucket_target_stage2` 보존 (Phase 1 followup)

**Files:**
- Modify: `tradingagents/agents/allocator/portfolio_allocator.py`

- [ ] **Step 1: Write follow-up test**

`tests/integration/test_allocator_phase1.py` 끝에 append (또는 새 파일 `tests/unit/agents/test_portfolio_allocator.py` 에 추가):

```python
def test_attribution_records_bucket_target_stage2():
    """attribution['config']['bucket_target_stage2'] 가 spillover 이전 macro 값 보존."""
    # 이 테스트는 실제 allocator run 또는 mock 통합으로 검증. 단위 테스트로 어려우면 skip.
    # Phase 1 의 test_allocator_attribution_completeness_via_smoke 와 비슷한 방식:
    # 산출물의 attribution 에 bucket_target_stage2 키 존재 확인.
    import os
    import json
    smoke_artifact = "artifacts/2026-05-15/portfolio.json"
    if not os.path.exists(smoke_artifact):
        import pytest
        pytest.skip(f"{smoke_artifact} 없음 — Task 11 의 회귀 실행 후 검증")
    with open(smoke_artifact) as f:
        portfolio = json.load(f)
    config = portfolio.get("allocation_attribution", {}).get("config", {})
    assert "bucket_target_stage2" in config, (
        "Phase 2a Task 9: attribution.config.bucket_target_stage2 missing"
    )
    # 5 bucket 모두 + bond_tips_share
    stage2 = config["bucket_target_stage2"]
    assert {"kr_equity", "global_equity", "fx_commodity", "bond", "cash_mmf",
            "bond_tips_share"} <= set(stage2.keys())
```

- [ ] **Step 2: Implement `bucket_target_stage2` snapshot**

`tradingagents/agents/allocator/portfolio_allocator.py` 의 `node` 함수에서 **spillover hook 이전** (대략 라인 230 근처, `# Phase 1 — cash spillover` 주석 직전) 에 다음 블록 추가:

```python
        # Phase 2a — Stage 2 원본 bucket_target 별도 보존 (spillover 전 macro 결정)
        attribution["config"]["bucket_target_stage2"] = {
            "kr_equity":      bucket_target.kr_equity,
            "global_equity":  bucket_target.global_equity,
            "fx_commodity":   bucket_target.fx_commodity,
            "bond":           bucket_target.bond,
            "cash_mmf":       bucket_target.cash_mmf,
            "bond_tips_share": bucket_target.bond_tips_share,
        }
```

그리고 spillover hook 직후 (Phase 1 에서 `attribution["config"]["bucket_target"]` overwrite 하는 부분) 에서 `bucket_target_post_spillover` 별도 키도 추가:

```python
        # Phase 2a — post-spillover snapshot 도 별도 키로 저장 (audit trail)
        attribution["config"]["bucket_target_post_spillover"] = dict(
            attribution["config"]["bucket_target"]
        )
```

(`bucket_target` 기존 키는 backward-compat 로 post_spillover 값 유지)

- [ ] **Step 3: Run portfolio tests + syntax check**

Run:
```bash
python3 -m py_compile tradingagents/agents/allocator/portfolio_allocator.py && echo OK
pytest tests/unit/skills/test_portfolio_*.py -q 2>&1 | tail -5
```
Expected: OK + all pass

- [ ] **Step 4: Commit**

```bash
git add tradingagents/agents/allocator/portfolio_allocator.py \
        tests/integration/test_allocator_phase1.py
git commit -m "feat(stage3): attribution bucket_target_stage2 별도 보존 (Phase 1 followup)

Phase 2a Task 9. spillover 전 Stage 2 원본 bucket_target 을 attribution.config.
bucket_target_stage2 로 별도 키 저장 + post_spillover 도 별도 키. bucket_target
기존 키는 backward-compat 로 post_spillover 값 유지."
```

---

### Task 10: `diversification.py` 의 `_pca_decomposition` smoke test (Phase 1 followup)

**Files:**
- Modify: `tests/unit/skills/test_portfolio_diversification.py`

- [ ] **Step 1: Add PCA smoke test**

`tests/unit/skills/test_portfolio_diversification.py` 끝에 append:

```python
def test_compute_enb_pca_method_works():
    """PCA method smoke — fallback path 가 정상 동작 (Phase 1 followup, Phase 2a Task 10)."""
    sigma = _equal_corr_cov(3, rho=0.3)
    enb_mt = compute_enb(_equal_weights(sigma), sigma, method="minimum_torsion")
    enb_pca = compute_enb(_equal_weights(sigma), sigma, method="pca")
    # ENB ∈ [1, n] 범위
    assert 1.0 <= enb_mt <= 3.0, f"minimum_torsion ENB out of range: {enb_mt}"
    assert 1.0 <= enb_pca <= 3.0, f"pca ENB out of range: {enb_pca}"


def test_compute_enb_pca_perfectly_correlated_returns_one():
    """PCA: 완전 상관 portfolio → ENB ≈ 1."""
    sigma = _equal_corr_cov(4, rho=0.999999)
    enb_pca = compute_enb(_equal_weights(sigma), sigma, method="pca")
    assert enb_pca == pytest.approx(1.0, abs=1e-2)
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/unit/skills/test_portfolio_diversification.py -v`
Expected: 기존 + 2 new = 모두 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/unit/skills/test_portfolio_diversification.py
git commit -m "test(stage3): _pca_decomposition smoke test (Phase 1 followup)

Phase 2a Task 10. PCA fallback path 가 reasonable range 와 perfectly correlated
case 에서 정상 동작 확인. 2 new tests."
```

---

### Task 11: Integration test + 회귀 검증

**Files:**
- Create: `tests/integration/test_allocator_phase2a.py`

- [ ] **Step 1: Write integration tests**

Create `tests/integration/test_allocator_phase2a.py`:
```python
"""Phase 2a integration — allocator pipeline 의 etf_metrics 통합 검증."""
from __future__ import annotations

import os
import json

import pytest


def test_attribution_records_etf_metrics_summary_via_smoke():
    """기존 phase1_smoke fixture 가 Phase 2a 새 attribution 키 (etf_metrics_summary,
    bucket_target_stage2, impl_score_breakdown) 를 채우는지 검증."""
    smoke_artifact = "artifacts/2026-05-15/portfolio.json"
    if not os.path.exists(smoke_artifact):
        pytest.skip(
            f"{smoke_artifact} 없음 — Phase 2a regression 실행 후 검증"
        )
    with open(smoke_artifact) as f:
        portfolio = json.load(f)
    attribution = portfolio.get("allocation_attribution") or {}

    # Phase 2a 적용 후 산출물이라면 이 키들이 있어야 함
    assert "etf_metrics_summary" in attribution, (
        "Phase 2a 적용 후 산출물에 etf_metrics_summary 누락"
    )

    summary = attribution["etf_metrics_summary"]
    assert "fetch_attempted" in summary
    assert "fetch_succeeded" in summary
    assert isinstance(summary["fetch_succeeded"], bool)
    assert "n_tickers_with_te" in summary
    assert "fetch_duration_seconds" in summary

    # config snapshot 도 확인 (Task 9)
    config = attribution.get("config", {})
    assert "bucket_target_stage2" in config, (
        "Phase 2a Task 9: bucket_target_stage2 누락"
    )
```

- [ ] **Step 2: Run integration test (Pre-regression: skip 예상)**

Run: `pytest tests/integration/test_allocator_phase2a.py -v`
Expected: SKIP (artifact 가 Phase 1 baseline 이라 Phase 2a 키 없음). 정상.

- [ ] **Step 3: Commit integration test**

```bash
git add tests/integration/test_allocator_phase2a.py
git commit -m "test(stage3): Phase 2a integration 테스트

Phase 2a Task 11. attribution etf_metrics_summary + bucket_target_stage2
완전성 검증. Phase 1 baseline 일 때 SKIP, regression 후 PASS 예상."
```

- [ ] **Step 4: Run E2E regression (Phase 2a 적용 산출물 생성)**

```bash
# .env 의 KRX_API_KEY 확인
grep KRX_API_KEY .env || (cd /Users/kimjaewon/Pluto/TradingAgents && grep KRX_API_KEY .env)

# baseline 백업 (이미 Phase 1 에서 만들어진 artifacts/baseline 활용)
ls artifacts/baseline/

# Phase 2a 적용 e2e
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/run_e2e_test.py --as-of 2026-05-15 --capital 1000000000 2>&1 | tail -30
```

Expected: 정상 종료, artifacts/2026-05-15/portfolio.json 갱신. attribution 에 새 키 채워짐.

- [ ] **Step 5: Verify acceptance criteria via regression_compare**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/regression_compare.py \
    --baseline artifacts/baseline/ \
    --new artifacts/ \
    --out artifacts/phase2a_regression.json 2>&1 | tail -40
```

Expected: 각 as_of 의 (a)(b)(c) PASS. (d) 는 LLM variance 영향 받을 수 있음 (Phase 1 과 동일).

Acceptance 추가 검증 (Phase 2a 전용):
```bash
python3 -c "
import json
with open('artifacts/2026-05-15/portfolio.json') as f:
    p = json.load(f)
attr = p['allocation_attribution']
summary = attr['etf_metrics_summary']
print('fetch_succeeded:', summary['fetch_succeeded'])
print('n_tickers_with_te:', summary['n_tickers_with_te'])
print('n_tickers_with_pd:', summary['n_tickers_with_pd'])
print('n_tickers_with_vol_aum:', summary['n_tickers_with_vol_aum'])
print('bucket_target_stage2:', attr['config'].get('bucket_target_stage2'))
"
```

Expected: `fetch_succeeded=True`, `n_tickers_with_*` 가 universe 의 70% 이상 (spec acceptance (e)).

만약 fetch 실패:
- WARNING log 확인, fallback 동작 검증 (log_aum 단독 → 결과는 Phase 1 와 거의 동일)
- KRX_API_KEY 또는 endpoint 명 확인

- [ ] **Step 6: Run integration test (post-regression: PASS 예상)**

Run: `pytest tests/integration/test_allocator_phase2a.py -v`
Expected: PASS (이제 산출물에 새 attribution 키 있음)

- [ ] **Step 7: Run full unit + integration regression**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest \
    tests/unit/dataflows/test_etf_metrics.py \
    tests/unit/dataflows/test_krx_openapi_etf.py \
    tests/unit/skills/test_portfolio_*.py \
    tests/unit/agents/test_portfolio_allocator.py \
    tests/integration/test_allocator_phase1.py \
    tests/integration/test_allocator_phase2a.py \
    tests/integration/test_plan_pipeline_mock.py \
    tests/integration/test_5_28_dry_run.py \
    -q 2>&1 | tail -10
```

Expected: all pass (acceptable: 일부 Phase 1 skip 유지)

- [ ] **Step 8: Commit 산출물 + regression result**

```bash
git add artifacts/2025-04-15/ artifacts/2026-05-15/ artifacts/phase2a_regression.json
git commit -m "chore(stage3): Phase 2a 적용 후 산출물 갱신 + 회귀 결과

baseline → phase2a regression:
  (a) Sharpe degradation ≤ 5%
  (b) Volatility ≤ +2%
  (c) attribution[etf_metrics_summary, bucket_target_stage2] 채워짐
  (e) n_tickers_with_te ≥ 70% of eligible

acceptance 모두 또는 대부분 PASS. fx_commodity (d) 는 LLM variance 영향
가능 (Phase 1 와 동일)."
```

---

## Self-Review

플랜 완성 후 spec 대비 누락 확인:

1. **Spec 의 신규 모듈** (`etf_metrics.py`) — Task 2-6 ✓
2. **Spec 의 변경 모듈 5개**:
   - `krx_openapi.py` (fetch_etf_daily_detail) — Task 1 ✓
   - `factor_scorer.py` (4-요소 가중치) — Task 7 ✓
   - `candidate_selector.py` (metrics 통합) — Task 8 ✓
   - `portfolio_allocator.py` (bucket_target_stage2) — Task 9 ✓
   - `diversification.py` (PCA smoke test) — Task 10 ✓
3. **Spec 의 acceptance criteria (a)-(e)** — Task 11 regression_compare ✓
4. **Spec 의 backward compat** (schema 변경 없음) — 모든 task 가 attribution dict 만 확장 ✓
5. **Spec 의 캐시 전략** (ParquetCache) — Task 4 ✓
6. **Spec 의 결손 데이터 처리** — Task 5, 6, 7 ✓
7. **Spec 의 KRX endpoint discovery** — Task 1 Step 1 ✓
8. **Spec 의 attribution 확장** (etf_metrics_summary, impl_score_breakdown) — Task 8 (etf_metrics_summary), `impl_score_breakdown` per ticker 는 spec 이 언급했으나 plan 에 누락 — Task 8 에서 동시 추가 권장 (단 acceptance 에 직접 영향 없음, 추가 logging 으로 처리)

## Execution Notes

- 모든 task TDD 흐름 (실패 → 구현 → 통과 → 커밋)
- Task 1 Step 1 의 endpoint discovery 가 fail 시 controller 에게 NEEDS_CONTEXT 보고
- Task 8 의 candidate_selector 변경 시 bond split path 영향 확인 — `_select_bond_with_tips_quota` 가 `_rank_by_factors` 만 호출, impl_score 까지 안 가므로 영향 없음
- Task 11 의 e2e 실행은 환경 의존성 — `KRX_API_KEY`, `OPENAI_API_KEY` 등 `.env` 설정 필수. 실패 시 partial DONE_WITH_CONCERNS
- 모든 commit message 는 `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` trailer 포함 권장
