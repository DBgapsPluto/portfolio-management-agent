# Stage 3 Phase 2a — ETF Metrics & impl_score 4-요소 Composite Design

**Date**: 2026-05-29
**Status**: Design (awaiting user review)
**Author**: Brainstorming session

## Goal

Phase 1 에서 impl_score 가 사실상 `log_aum` 단독으로 작동하고 있던 한계를 해소한다. KRX OpenAPI 에서 ETF 일별 NAV / 괴리율 / 거래대금 / 추적률을 fetch 해 4-요소 weighted composite 으로 확장. underlying duplicate (예: S&P 500 추종 10개) cluster 내에서 "큰 ETF" 가 아닌 **"운영 품질 좋은 ETF"** 가 자동 우대되도록 한다.

추가로 Phase 1 follow-up 의 작은 항목 2 가지 (Stage 2 bucket_target audit 보존, `_pca_decomposition` smoke test) 를 함께 처리한다.

## Context

- **Phase 1 (commit c0be9b2, 2026-05-28)** 완료: cash spillover + ENB warning. universe 의 188 ETF 가 사전 큐레이션.
- **현재 impl_score**: `compute_impl_score` 함수의 시그니처에 `adv`, `deviation`, `tracking_error` 옵션 인자가 이미 있으나 **데이터 source 미주입** → 사실상 `log_aum` 단독으로 작동.
- **GAPS 12회 universe**: S&P 500 추종 10개, NASDAQ 100 추종 5개, KOSPI 200 추종 7개 등 underlying duplicate 다수. 이들 cluster 내 vehicle 선택이 impl_score 의 핵심 작용 영역.
- **KRX OpenAPI infrastructure**: `tradingagents/dataflows/krx_openapi.py` 가 generic `fetch_krx_openapi(endpoint_path, basDd)` 로 구축됨. ETF endpoint wrapper 미작성.
- **데이터 신뢰성**: 기존 `pykrx` 는 일부 endpoint 가 KRX schema 변경으로 깨짐 ([memory: backtest_followup_2026_05_26](../../../.claude/projects/-Users-kimjaewon-Pluto-TradingAgents/memory/backtest_followup_2026_05_26.md)). KRX 공식 OpenAPI 가 더 안정.

## Scope

### 포함

- 신규 모듈 `tradingagents/dataflows/etf_metrics.py` — ETF 일별 메트릭 fetch + 12m TE / 30d median |괴리율| / 30d median volume/AUM 계산
- `tradingagents/dataflows/krx_openapi.py` 확장 — ETF 일별 detail endpoint wrapper 추가
- `tradingagents/skills/portfolio/factor_scorer.py` 의 `compute_impl_score` — 4-요소 weighted composite + 시그니처 정리 (`adv`→`volume_per_aum`, `deviation`→`premium_discount`)
- `tradingagents/skills/portfolio/candidate_selector.py` 의 `select_etf_candidates` — metrics fetch + 새 impl_score 인자 전달
- `tradingagents/agents/allocator/portfolio_allocator.py` — attribution 에 `etf_metrics_summary`, `bucket_target_stage2` 추가
- `tradingagents/skills/portfolio/diversification.py` — `_pca_decomposition` smoke test 추가
- 캐시 인프라 — `pykrx_data.py:ParquetCache` 패턴 재사용, 날짜별 parquet
- Test coverage — unit / regression / integration

### 제외 (Phase 2b+)

- ENB greedy forward selection (Phase 2b)
- Adaptive `per_bucket_n` (Phase 2b)
- `expense_ratio` (정적 데이터, Phase 4 검토)
- NCO + Black-Litterman backbone (Phase 3)
- Ledoit-Wolf nonlinear shrinkage (Phase 4)
- ENB threshold 차단 동작 (Phase 4)
- regression criterion (d) fragility 개선 (Phase 4)
- state mocking helpers for `test_allocator_phase1.py` 의 4 skip tests (Phase 2b 또는 4)
- Schema 변경 (`BucketTarget`, `WeightVector`, `ETFEntry`)

## Architecture

Phase 2a 는 ETF 의 메타데이터를 KRX OpenAPI 로 fetch 하는 **신규 데이터 모듈** + 기존 `compute_impl_score` 의 입력 확장. 종목 선정 로직 자체는 그대로 (Phase 2b 영역). impl_score 가 풍부해지므로 cluster 내 vehicle 선택이 정확해지고, underlying duplicate 에서 운영 품질 좋은 ETF 가 자동 우대.

```
[Stage 1 + Stage 2 입력]
        │
        ▼
①  eligibility + returns matrix              (기존)
        │
        ▼
②  alpha 점수 계산                              (기존)
        │
        ▼
③  [NEW] ETF metrics fetch                    ← etf_metrics.py 신규
   │   fetch_etf_metrics_window(eligible, window_start, as_of, cache_path)
   │   ↓
   │   ParquetCache 확인 → 누락 날짜만 KRX OpenAPI fetch
   │   ↓
   │   ticker × date multi-index DataFrame
   │   ↓
   │   compute_tracking_error_12m / compute_premium_discount_median /
   │   compute_volume_per_aum_median
        │
        ▼
④  cluster + 대표 선정 (양수만)              (기존, 단 impl_score 4-요소 사용)
   │   compute_impl_score(panels, tracking_error, premium_discount, volume_per_aum)
        │
        ▼
⑤  cash spillover (Phase 1)                   (기존)
        │
        ▼
⑥ ~ ⑧  method_picker → optimize → ENB        (기존)
        │
        ▼
[Stage 4 로 전달]
```

**Schema 정책**: `ETFEntry`, `BucketTarget`, `WeightVector`, `OptimizationMethod` 변경 없음. `attribution` dict 만 확장 (`etf_metrics_summary`, `bucket_target_stage2`, `impl_score_breakdown` per ticker).

**환경 변수**: 기존 `KRX_API_KEY` (krx_openapi.py 에서 이미 사용 중) 재활용.

## Components

### 신규 모듈 A: `tradingagents/dataflows/etf_metrics.py`

**책임**: KRX OpenAPI 에서 ETF 일별 메타데이터 fetch + 메트릭 계산 (TE / |괴리율| / volume/AUM).

```python
from pydantic import BaseModel
from datetime import date
from pathlib import Path

import pandas as pd


class ETFDailyMetrics(BaseModel):
    """단일 ticker × 단일 날짜 의 ETF 메타데이터."""
    ticker: str
    trade_date: date
    nav: float                       # 순자산가치
    market_price: float              # 시장종가
    premium_discount: float          # = market_price / nav - 1
    volume: int                      # 일일 거래량 (주)
    trade_value_krw: float           # 거래대금
    aum_krw: float                   # AUM (시가총액 ≈ 운용규모)
    tracking_rate: float | None      # KRX 공시 추적률 (% 단위, 없으면 None)


def fetch_etf_metrics_window(
    tickers: list[str],
    start: date,
    end: date,
    cache_path: Path | None = None,
) -> pd.DataFrame:
    """ticker × date multi-index DataFrame.

    Columns: nav, market_price, premium_discount, volume, trade_value_krw,
             aum_krw, tracking_rate.
    누락 날짜는 KRX OpenAPI 로 fetch, ParquetCache 영구 저장.
    """


def compute_tracking_error_12m(
    metrics: pd.DataFrame,
    ticker: str,
    index_returns: pd.Series | None = None,
) -> float | None:
    """12개월 추적오차 (annualized, % 단위).

    우선순위:
      1. KRX 공시 tracking_rate (%) 가 60일 이상 있으면 그 표준편차 (pp).
         단위 일관성: tracking_rate 가 % 단위이므로 std 도 pp.
      2. Fallback: ticker market_price daily returns vs index_returns 의
         std of difference × √252 × 100 = 연환산 % 단위.
      3. 데이터 부족 (< 60일) 시 None.

    반환 값은 항상 % 단위 — 단위 일관성은 z-score normalize 후 ranking 에만
    영향 (절대값은 비교용으로만 사용).
    """


def compute_premium_discount_median(
    metrics: pd.DataFrame, ticker: str, n_days: int = 30,
) -> float | None:
    """최근 n_days 의 median |premium_discount|. 부족 시 None."""


def compute_volume_per_aum_median(
    metrics: pd.DataFrame, ticker: str, n_days: int = 30,
) -> float | None:
    """최근 n_days 의 median (trade_value_krw / aum_krw). 유동성 proxy."""
```

**의존**: `krx_openapi.fetch_etf_daily_detail` (Module B), `ParquetCache` (pykrx_data.py 의 기존 클래스), `pandas`, `pydantic`.

### 변경 모듈 B: `tradingagents/dataflows/krx_openapi.py`

**책임**: ETF endpoint wrapper 추가.

```python
KRX_ETF_DAILY_ENDPOINT: str = "etf/etf_bydd_trd"  # 구현 시 endpoint discovery 로 확정


def fetch_etf_daily_detail(
    basDd: date,
    ticker: str | None = None,
) -> list[dict]:
    """ETF 일별 상세 정보. ticker=None 시 전 ETF 응답.

    응답 필드 (KRX 영문 컬럼, endpoint discovery 시 확정):
      ISU_SRT_CD (단축코드), BAS_DD (영업일 YYYYMMDD),
      NAV, TDD_CLSPRC (종가), ACC_TRDVOL (거래량),
      ACC_TRDVAL (거래대금), MKTCAP (시총=AUM proxy),
      TRC_RT (추종률, %), ...

    내부: fetch_krx_openapi(KRX_ETF_DAILY_ENDPOINT, basDd) 호출 후 ticker 필터링.
    """
```

**Endpoint discovery 절차** (구현 단계 Task 1 의 첫 step):
1. KRX 공식 카탈로그 (https://data.krx.co.kr/) ETF 일별 검색
2. 또는 `fetch_krx_openapi("etf/etf_bydd_trd", basDd)` 시도 → 응답 필드 확정
3. 응답 필드명 (한국어/영문) 확정 후 dict → `ETFDailyMetrics` 매핑 작성

### 변경 모듈 C: `factor_scorer.py` — `compute_impl_score` 4-요소 가중치

**현재 (단순 평균)**:
```python
parts = [normalize({t: p.log_aum for t, p in panels.items()})]
if adv is not None:        parts.append(normalize(adv))
if deviation is not None:  parts.append(normalize(-|deviation|))
if tracking_error:         parts.append(normalize(-tracking_error))
impl[t] = mean(parts[i][t])
```

**새 (가중치)**:
```python
# Signed weights — 부호가 contribution 방향. 절댓값 합 = 1.0.
IMPL_SCORE_WEIGHTS: dict[str, float] = {
    "log_aum":            0.33,   # 클수록 좋음
    "premium_discount":  -0.28,   # |괴리율| 클수록 나쁨 (음수 가중)
    "tracking_error":    -0.22,   # 클수록 나쁨
    "volume_per_aum":     0.17,   # 클수록 좋음
}
# 검증: sum(abs(v) for v in IMPL_SCORE_WEIGHTS.values()) == 1.0


def compute_impl_score(
    panels: dict[str, FactorPanel],
    *,
    volume_per_aum: dict[str, float | None] | None = None,
    premium_discount: dict[str, float | None] | None = None,
    tracking_error: dict[str, float | None] | None = None,
    normalization: str = "rank_percentile",
) -> dict[str, float]:
    """4-요소 weighted composite (Phase 2a, 2026-05-29).

    공식 (rank-percentile normalize 후 부호 있는 가중합):
      impl_score(t) = +0.33 × z(log_aum)
                    + 0.17 × z(volume_per_aum)
                    + (-0.28) × z(|premium_discount|)     # 절댓값 입력
                    + (-0.22) × z(tracking_error)

    각 신호는 raw (절댓값으로 입력) 를 normalize 후 signed weight 와 합성.
    → 큰 |premium_discount| 가 큰 z → 음수 가중치 × 큰 z = 매우 음수 기여 (정확).

    누락 신호 (None) 는 normalize 단계에서 0 (neutral z) 처리 → 가중치 × 0 = 0 기여.
    backward-compat: 모든 신호 None 시 impl_score = 0.33 × z(log_aum), log_aum 단독
    ordering (Phase 1 의 mean(log_aum) 과 ranking 동일).
    """
```

가중치 유래: Phase 1 spec "Recommendation 7" 의 5-요소 weight (0.30/-0.25/-0.20/+0.15/-0.10) 에서 expense_ratio (-0.10) 제거 후 합이 1.0 이 되도록 비례 재정규화 → (0.33, -0.28, -0.22, +0.17). 추후 Phase 4 backtest tuning 또는 expense 추가 검토.

**Backward-compat**: 기존 인자명 `adv` / `deviation` 은 alias 안 함. 호출처가 `candidate_selector.py` 1개뿐이라 직접 변경.

### 변경 모듈 D: `candidate_selector.py` — metrics fetch + impl_score 호출

`select_etf_candidates` 안에 metrics fetch 단계 추가:

```python
from tradingagents.dataflows.etf_metrics import (
    fetch_etf_metrics_window, compute_tracking_error_12m,
    compute_premium_discount_median, compute_volume_per_aum_median,
)

# returns matrix fetch 부근에 추가
metrics_window_start = as_of - timedelta(days=400)  # 12m TE 위한 buffer
fetch_start_time = time.monotonic()
try:
    etf_metrics = fetch_etf_metrics_window(
        eligible_tickers, metrics_window_start, as_of, cache_path=cache_path,
    )
    metrics_fetch_succeeded = True
    fallback_reason = None
except KRXOpenAPIError as e:
    logger.warning(
        "KRX OpenAPI fetch failed (%s) — impl_score falls back to log_aum only", e,
    )
    etf_metrics = None
    metrics_fetch_succeeded = False
    fallback_reason = str(e)
fetch_duration = time.monotonic() - fetch_start_time

# metrics 가용 시 계산
if etf_metrics is not None:
    tracking_error_by_ticker = {
        t: compute_tracking_error_12m(etf_metrics, t) for t in eligible_tickers
    }
    prem_disc_by_ticker = {
        t: compute_premium_discount_median(etf_metrics, t, n_days=30)
        for t in eligible_tickers
    }
    vol_aum_by_ticker = {
        t: compute_volume_per_aum_median(etf_metrics, t, n_days=30)
        for t in eligible_tickers
    }
else:
    tracking_error_by_ticker = None
    prem_disc_by_ticker = None
    vol_aum_by_ticker = None

# 기존 compute_impl_score 호출에 새 인자 전달
impl_scores = compute_impl_score(
    panels_for_impl,
    tracking_error=tracking_error_by_ticker,
    premium_discount=prem_disc_by_ticker,
    volume_per_aum=vol_aum_by_ticker,
    normalization=normalization,
)

# attribution
if attribution is not None:
    attribution["etf_metrics_summary"] = {
        "fetch_attempted": True,
        "fetch_succeeded": metrics_fetch_succeeded,
        "fallback_reason": fallback_reason,
        "n_tickers_with_te": sum(1 for v in (tracking_error_by_ticker or {}).values() if v is not None),
        "n_tickers_with_pd": sum(1 for v in (prem_disc_by_ticker or {}).values() if v is not None),
        "n_tickers_with_vol_aum": sum(1 for v in (vol_aum_by_ticker or {}).values() if v is not None),
        "fetch_duration_seconds": float(fetch_duration),
    }
```

각 bucket 의 attribution 에 `impl_score_breakdown` per ticker 추가 — Stage 6 narrative 가시화.

### 변경 모듈 E (Phase 1 followup): `portfolio_allocator.py`

`attribution["config"]["bucket_target"]` 가 spillover 후 overwrite 되는 문제 fix. Stage 2 와 post-spillover 둘 다 보존:

```python
# 기존: bucket_target snapshot 한 번만 저장 (spillover 후 덮어씀)
# 새: spillover 전에 Stage 2 원본 별도 저장
attribution["config"]["bucket_target_stage2"] = {
    "kr_equity":     bucket_target.kr_equity,
    "global_equity": bucket_target.global_equity,
    "fx_commodity":  bucket_target.fx_commodity,
    "bond":          bucket_target.bond,
    "cash_mmf":      bucket_target.cash_mmf,
    "bond_tips_share": bucket_target.bond_tips_share,
}
# spillover 후 (hook 1 코드 직후 — Phase 1 의 기존 snapshot 위치):
attribution["config"]["bucket_target_post_spillover"] = { ... }
attribution["config"]["bucket_target"] = attribution["config"]["bucket_target_post_spillover"]  # backward-compat alias
```

### 변경 모듈 F (Phase 1 followup): `diversification.py` — `_pca_decomposition` smoke test

`tests/unit/skills/test_portfolio_diversification.py` 끝에 append:
```python
def test_compute_enb_pca_method_works():
    """PCA method 로도 ENB 계산 가능 (smoke).

    minimum_torsion 이 default 이지만 pca fallback 도 정상 동작 확인.
    """
    sigma = _equal_corr_cov(3, rho=0.3)
    enb_mt = compute_enb(_equal_weights(sigma), sigma, method="minimum_torsion")
    enb_pca = compute_enb(_equal_weights(sigma), sigma, method="pca")
    # ENB ∈ [1, n] 범위
    assert 1.0 <= enb_mt <= 3.0
    assert 1.0 <= enb_pca <= 3.0
    # 두 방법은 일반적으로 다른 값을 줄 수 있음 (correlation 이 있을 때) — 단 둘 다 의미 있는 값
```

## KRX OpenAPI Endpoint + 데이터 흐름

### 호출 단위

- KRX OpenAPI 는 **basDd (날짜) 단위 호출** — 하루치 전 ETF 응답
- Ticker 별 호출 아님 — 응답에서 필터링
- 12 개월 데이터 = 약 252회 호출 (영업일)

### 캐시 전략

```
.cache/etf_metrics/
  ├── 2025-05-29.parquet   # 그 날 전체 ETF (188 rows × ~10 cols)
  ├── 2025-05-30.parquet
  ├── ...
  └── 2026-05-28.parquet
```

- **캐시 키**: 날짜 (`YYYY-MM-DD.parquet`). KRX 가 immutable → 평생 캐시.
- **Cache miss**: 누락 날짜만 fetch. 공휴일은 fetch 시도 → 빈 응답 → 빈 parquet 저장.
- **저장 위치**: `Path(cache_path) / "etf_metrics"` — 기존 `pykrx_data.py:ParquetCache` 패턴.

### Rate Limit 대응

- 기존 tenacity 재시도 (3회 + exponential backoff) 활용
- KRX rate limit 미공시 — 호출 사이 `sleep(0.1)` (보수적, 실측 후 조정)
- 초기 backfill: 252회 × (0.5s 응답 + 0.1s sleep) ≈ **150초 (2.5분)** 1회 비용
- 이후 daily incremental: 1회 fetch

### TE 계산 우선순위

```python
def compute_tracking_error_12m(metrics_df, ticker, index_returns=None):
    sub = metrics_df.xs(ticker, level="ticker")
    # 1순위: KRX 공시 tracking_rate (% 단위로 가정, e.g., 99.5 = 99.5%)
    if "tracking_rate" in sub.columns and sub["tracking_rate"].notna().any():
        recent_rates = sub["tracking_rate"].dropna().tail(252)
        if len(recent_rates) >= 60:
            # tracking_rate 의 std (pp 단위) — ETF 추종률의 변동성
            return float(recent_rates.std())
    # 2순위: fund returns vs index returns 직접 계산 (% 단위 연환산)
    if index_returns is None:
        return None
    fund_returns = sub["market_price"].pct_change().dropna()
    diff = fund_returns - index_returns.reindex(fund_returns.index)
    diff = diff.dropna()
    if len(diff) < 60:
        return None
    return float(diff.std() * np.sqrt(252) * 100)  # 연환산 %
```

`index_returns` 입력은 `factor_panel` 의 underlying_index returns 또는 별도 fetch (Phase 2a 에서는 None default, KRX 공시 추적률 의존).

## impl_score Formula 디테일

### 4-요소 가중치 합성

```
impl_score(t) = +0.33 × z(log_aum)
              + 0.17 × z(volume_per_aum)
              − 0.28 × z(|premium_discount|)
              − 0.22 × z(tracking_error)
```

`z()` 는 `_rank_normalize` (Phase 1 default) — bounded ∈ [-0.5, +0.5], scale-invariant.

### 가중치 합

Signed sum 은 0 (0.33 - 0.28 - 0.22 + 0.17 = 0), **절댓값 합 = 1.0**:

```python
assert abs(sum(abs(v) for v in IMPL_SCORE_WEIGHTS.values()) - 1.0) < 1e-9
```

부호는 의미적: 양수 가중치 = "클수록 좋음", 음수 가중치 = "클수록 나쁨". 합성 시 signed weight × normalized rank 형태로 자연스럽게 ordering 형성.

### 누락 신호 → Neutral z (0)

각 신호가 None 일 수 있는 케이스:
| 신호 | 누락 원인 | 처리 |
|---|---|---|
| `log_aum` | 누락 불가 (always present) | n/a |
| `premium_discount` | NAV 데이터 없음, 30일 미달 신규 ETF | 0 (neutral z) |
| `tracking_error` | KRX 추적률 부재 + index returns 부재, 12m 미달 | 0 |
| `volume_per_aum` | 30일 미달 | 0 |

**원칙**: None 은 0 기여 (other ETFs 대비 약간 우대 효과). Phase 4 에서 보수적 대안 검토.

### Backward Compatibility

모든 신호 None 입력 → impl_score 가 사실상 log_aum 단독:
- `IMPL_SCORE_WEIGHTS["log_aum"] = 0.33`, 나머지 3개 신호 z = 0
- 다른 ticker 들도 모두 동일 (None) → 모든 비교가 log_aum 기준
- Phase 1 동작과 **상대 ordering 동일** (절대값은 0.33 배 scale 차이)

`select_cluster_aware` 가 `argmax(impl_scores)` 만 보므로 ordering 만 중요. backward-compat 보장.

## Error Handling 원칙

Phase 1 의 **fail-loud over fail-silent** 정신 일관. 단 ETF metrics fetch 는 외부 의존성이 큰 영역이라 graceful degradation 일부 허용.

| 상황 | 처리 |
|---|---|
| `KRX_API_KEY` 미설정 | `KRXOpenAPIError` 즉시 raise (기존 동작) |
| KRX HTTP 5xx | tenacity 3회 재시도 후 raise |
| KRX HTTP 4xx (auth 실패) | raise, 재시도 안 함 |
| 특정 날짜 빈 응답 (공휴일) | 빈 parquet 저장, 정상 진행 |
| 일부 ticker 응답 누락 | metrics_df 행 부재, compute_*_median 가 None 반환 |
| `compute_*_median` 데이터 부족 (< n_days) | None 반환, impl_score 에서 neutral z (0) |
| **전체 fetch 실패** (network outage) | WARNING log + 모든 metrics None → log_aum 단독 fallback. allocator 계속 진행 |
| `tracking_rate` 필드 부재 | fund vs index returns 직접 계산 fallback. index returns 도 없으면 None |
| `NAV` 가 0 또는 NaN | premium_discount = NaN. `compute_premium_discount_median` 가 NaN 무시 |
| 12m 데이터 부족 (신규 ETF) | tracking_error = None → neutral z (0) |

전체 fetch 실패 시 fail-loud 가 너무 가혹 — allocator 자체는 동작 가능 (Phase 1 동작으로 회귀). WARNING 으로 사용자에게 알리고 계속.

## 운영 고려사항

### KRX API Key

- `.env` 에 `KRX_API_KEY=<key>` (기존 `krx_openapi.py` 가 이미 사용)
- 발급: KRX OpenAPI 서비스 신청 (https://openapi.krx.co.kr/ 또는 동등), 무료, 1-2 영업일
- Key 부재 시 fallback 모드 자동 (log_aum 단독, WARNING)

### 초기 Backfill 비용

- 첫 호출 시 12개월 × 252 영업일 ≈ 252 fetch 호출
- 호출당 0.5s 응답 + 0.1s sleep → **약 150초 (2.5분)** 1회 비용
- 이후 daily incremental: 1회 fetch
- 캐시 persist: `.cache/etf_metrics/*.parquet` git ignored, 사용자/운영 서버 머신 영속

### Endpoint Discovery (구현 시)

Phase 2a Task 1 의 첫 step:
1. KRX 공식 카탈로그에서 ETF 일별 endpoint 정식 path 확정
2. 응답 필드명 확정 (한국어 vs 영문, KRX 가 변경한 컬럼명 패턴 적용)
3. 1 ticker × 1 날짜 fetch 로 응답 구조 검증
4. `ETFDailyMetrics` 매핑 작성

### attribution 확장

```python
attribution["etf_metrics_summary"] = {
    "fetch_attempted": bool,
    "fetch_succeeded": bool,
    "fallback_reason": str | None,
    "n_tickers_with_te": int,
    "n_tickers_with_pd": int,
    "n_tickers_with_vol_aum": int,
    "cache_hits": int,
    "cache_misses": int,
    "fetch_duration_seconds": float,
}

attribution["buckets"][bucket_name]["impl_score_breakdown"] = {
    ticker: {
        "log_aum_z": float,
        "tracking_error_z": float,    # 누락 시 0
        "premium_discount_z": float,
        "volume_per_aum_z": float,
        "tracking_error_value": float | None,
        "premium_discount_value": float | None,
        "volume_per_aum_value": float | None,
        "final_impl_score": float,
    }
    for ticker in candidates_in_bucket
}
```

Stage 6 narrative 가 "같은 underlying 의 ETF 중 KODEX 가 선출된 이유: 추적오차 0.05% (vs TIGER 0.12%), 괴리율 ±0.02% (vs ±0.08%)" 같은 설명 가능.

## Testing Strategy

### A. Unit tests (모듈별, 신규)

**`tests/unit/dataflows/test_etf_metrics.py`** (신규):
- `test_fetch_etf_metrics_window_uses_cache` — 캐시된 날짜는 재호출 안 함
- `test_fetch_etf_metrics_window_fetches_missing` — 누락 날짜만 fetch
- `test_fetch_etf_metrics_window_concats_multi_dates` — 응답 concat → multi-index DataFrame
- `test_compute_tracking_error_12m_uses_krx_rate_when_available` — KRX 추적률 우선
- `test_compute_tracking_error_12m_falls_back_to_fund_index_diff` — 추적률 부재 시 직접 계산
- `test_compute_tracking_error_12m_returns_none_when_insufficient_data` — < 60일 시 None
- `test_compute_premium_discount_median_30day` — 30일 median |premium_discount|
- `test_compute_premium_discount_median_returns_none_when_no_data` — 데이터 없을 때 None
- `test_compute_volume_per_aum_median_30day` — 30일 median trade_value/AUM
- `test_etf_metrics_handles_holiday_empty_response` — 공휴일 빈 응답 처리
- `test_etf_metrics_handles_missing_ticker` — 응답에 없는 ticker

**`tests/unit/dataflows/test_krx_openapi_etf.py`** (신규):
- `test_fetch_etf_daily_detail_parses_response` — mock fetch_krx_openapi → list[dict]
- `test_fetch_etf_daily_detail_filters_by_ticker` — single ticker 지정 시 필터링
- `test_fetch_etf_daily_detail_handles_empty_response` — 빈 list 정상 처리
- `test_fetch_etf_daily_detail_raises_on_auth_failure` — KRX_API_KEY 미설정 시 raise

### B. Unit tests (기존 모듈, 확장)

**`tests/unit/skills/test_portfolio_factor_scorer.py`** (확장):
- `test_impl_score_4factor_composite` — 4-요소 가중치 합성 검증
- `test_impl_score_missing_signals_falls_back_to_log_aum` — 모든 입력 None 시 log_aum 단독 ordering
- `test_impl_score_weight_magnitudes_sum_to_one` — `sum(abs(v) for v in IMPL_SCORE_WEIGHTS.values()) == 1.0`
- `test_impl_score_high_te_lowers_score` — TE 큰 ETF 가 impl 낮음
- `test_impl_score_high_premium_discount_lowers_score` — |괴리율| 큰 ETF 가 impl 낮음
- `test_impl_score_high_volume_per_aum_raises_score` — volume/AUM 큰 ETF 가 impl 높음

**`tests/unit/skills/test_portfolio_candidate.py`** (회귀):
- 기존 테스트 모두 PASS (새 인자 미사용 시 backward-compat)
- `test_select_etf_candidates_uses_etf_metrics` — metrics 입력 시 다른 cluster rep 가 선출되는지 (예: AUM 큰 ETF 대신 TE 작은 ETF)

**`tests/unit/skills/test_portfolio_diversification.py`** (확장):
- `test_compute_enb_pca_method_works` — PCA fallback smoke (Phase 1 followup)

### C. Integration tests (allocator pipeline)

**`tests/integration/test_allocator_phase2a.py`** (신규):
- `test_allocator_uses_etf_metrics` — monkeypatch fetch_etf_metrics_window → mock metrics → impl_score 4-요소 확인
- `test_allocator_falls_back_when_metrics_unavailable` — fetch 실패 시 log_aum 단독 fallback (graceful, WARNING)
- `test_attribution_records_metrics_summary` — `etf_metrics_summary` + `impl_score_breakdown` per ticker
- `test_attribution_records_bucket_target_stage2` — Phase 1 followup, Stage 2 원본 보존

### D. 회귀 시나리오 (실 KRX API)

Phase 1 의 `scripts/regression_compare.py` 그대로 사용 가능 (acceptance criteria generic).

**`tests/unit/skills/test_portfolio_candidate.py`** 의 회귀:
- 기존 fixture (Phase 1 baseline) 대비 새 산출물 비교
- chosen ticker set diff (underlying duplicate cluster 내 ETF 변경)
- 새 attribution 필드 채워짐 확인

### Test 실행 명령

```bash
# 단위
pytest tests/unit/dataflows/test_etf_metrics.py tests/unit/dataflows/test_krx_openapi_etf.py -v

# 회귀
pytest tests/unit/skills/test_portfolio_*.py -v

# 통합
pytest tests/integration/test_allocator_phase2a.py -v

# 전체 회귀
pytest tests/unit/ tests/integration/ -q --ignore=tests/integration/test_eval_regime_classifier.py
```

## Acceptance Criteria

regression_compare.py 의 exit code 0/1 판정 대상:

- (a) `new_expected_sharpe >= 0.95 × baseline_expected_sharpe` (Phase 1 동등)
- (b) `new_expected_volatility <= 1.02 × baseline_expected_volatility` (Phase 1 동등)
- (c) attribution 에 `etf_metrics_summary`, `bucket_target_stage2`, `impl_score_breakdown` 모두 채워짐
- (d) underlying duplicate cluster 가 있는 케이스 (2026-05-15: S&P 500 ETF 다수):
  - chosen ticker 가 baseline 과 다를 수 있음 (impl_score 변경 반영)
  - 단 chosen 의 alpha 는 baseline 과 동등 또는 우수 (cluster alpha 기준은 동일)
- (e) `etf_metrics_summary.fetch_succeeded = True` 이고 `n_tickers_with_te >= n_eligible × 0.7` (70% 이상 ETF 의 TE 계산 성공)

**Fail Recovery** (acceptance 실패 시 절차):
- (e) 미충족 시: endpoint discovery 재검토 (응답 필드 변경 가능성), 캐시 정리 후 재 fetch
- (a)(b) 미충족 시: impl_score 가중치 재검토 (예: 0.33/-0.28/-0.22/+0.17 → 0.5/-0.2/-0.2/+0.1 더 보수적)

## Backward Compatibility

- `BucketTarget`, `WeightVector`, `OptimizationMethod`, `ETFEntry` schema 변경 없음
- `compute_impl_score` 시그니처에서 `adv`→`volume_per_aum`, `deviation`→`premium_discount` 인자명 변경 — 호출처 1개 (candidate_selector) 만 영향, 그 task 안에서 동시 update
- 모든 metrics 인자 None 시 `log_aum` 단독 ordering 유지 (Phase 1 동작과 동등)
- `attribution` dict 는 신규 키 추가만 (`etf_metrics_summary`, `bucket_target_stage2`, `impl_score_breakdown`) — 기존 키 변경 없음
- Phase 1 acceptance criteria (a)(b)(c)(d) 유지

## Out of Scope / Future Phases

- **Phase 2b**: ENB greedy forward selection, adaptive `per_bucket_n`, state mocking helpers for skip tests
- **Phase 3**: NCO + Black-Litterman backbone
- **Phase 4**: Ledoit-Wolf nonlinear shrinkage, regime → (δ, c, τ) tilt, ENB threshold 차단 동작, `expense_ratio` 추가 (5-요소 composite), regression criterion (d) fragility 개선

## Open Questions

없음 (모든 design decision 확정). KRX endpoint 정식 path 와 응답 필드명은 implementation Task 1 의 첫 step 에서 확정.
