# Black-Litterman 버킷 배분 전환 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stage 3 `trader_allocator`의 Step A(14버킷 비중)를 quadrant 앵커+LLM tilt에서 Black-Litterman(prior=δΣw_baseline 역산, view=LLM 상대순위+fx/credit 결정론, MQU **prior Σ**)으로 교체.

**Architecture:** 병렬 신규 모듈(`bucket_proxies`/`bucket_cov`/`bl_engine`) + `trader_allocator` 플래그 분기(옛 project_to_band ↔ 신 BL). 게이트2 통과 후 정리 Phase에서 옛 경로 삭제. 모든 감사 교정(MATH-1 prior Σ, FALSE-1 soft-clip, PARTIAL-1 버킷핀, PIT-1 as_of)을 테스트로 잠금.

**Tech Stack:** Python 3.13, PyPortfolioOpt 1.6.0(BlackLittermanModel·idzorek·EfficientFrontier), `cov_estimator.compute_robust_cov`(LW), numpy/scipy, pytest. 기존 fetch 재사용: `cross_asset_returns._raw_yf_batch`+`series_cache.fetch_frame_with_cache`(yfinance), `fred.fetch_fred_series`(us_3m=DGS3MO·dxy=DTWEXBGS, PIT), `returns_matrix.fetch_returns_matrix`(pykrx).

**spec:** `docs/superpowers/specs/2026-06-20-bl-allocator-design.md` (rev1, dcca22c).

**선행조건(차단):** ETF-선택 sub-project(`docs/superpowers/plans/2026-06-16-etf-selection-hybrid.md`)가 먼저 출시되어야 함 — `BucketTilt.sub_category_views`, `cluster_repair`(CLUSTER_CAP=0.35), validator 0.25→0.35. 본 plan의 Phase C는 그 위에 `bucket_ranking`을 *추가*한다.

**테스트 실행 규약:** 모든 pytest는 `PYTHONUTF8=1 .venv/Scripts/python -m pytest ... -v`. 모든 코드 변경 커밋 후 적대적 감사(서브에이전트/워크플로) + 의도부합 확인은 호출자(오케스트레이터)가 수행 — 각 Task 끝에 명시.

---

# Phase A — Σ 인프라 (LLM·BL 없음, 자족)

## Task A1: `bucket_proxies.py` — 교정 proxy 맵 + as_of fetch + 버킷별 폴오버

**Files:**
- Create: `tradingagents/backtest/bucket_proxies.py`
- Test: `tests/unit/backtest/test_bucket_proxies.py`

14버킷 각각을 대표 자산 1개 시계열로 대리. 소스별(yf/fred/pykrx/cash) dispatch, 1차 실패 시 대체proxy 폴오버, 끝점은 as_of(look-ahead 차단).

- [ ] **Step 1: 실패 테스트 작성** — `tests/unit/backtest/test_bucket_proxies.py`

```python
from datetime import date
import pandas as pd
import pytest
from tradingagents.backtest import bucket_proxies as bp


def test_proxy_map_covers_14_buckets():
    from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS
    assert set(bp.BUCKET_PROXY) == set(GAPS_BUCKET_KEYS)
    # 각 버킷 최소 1개 (source, key) 엔트리
    for k, specs in bp.BUCKET_PROXY.items():
        assert len(specs) >= 1
        for src, key in specs:
            assert src in ("yf", "fred", "pykrx", "cash")


def test_fetch_returns_respects_as_of_no_lookahead(monkeypatch):
    # 각 source fetch를 결정론 스텁으로 대체: as_of 이후 행이 없어야 한다
    idx = pd.bdate_range("2024-01-01", "2024-12-31")
    full = pd.Series(0.001, index=idx)

    def fake_yf(symbols, start, end):
        # _raw_yf_batch 흉내: end까지만 (end 이후 제거)
        sub = full[(full.index.date >= start) & (full.index.date <= end)]
        return pd.DataFrame({s: sub for s in symbols})

    monkeypatch.setattr(bp, "_raw_yf_batch_close", fake_yf)
    monkeypatch.setattr(bp, "_fred_returns", lambda key, start, end: full[(full.index.date >= start) & (full.index.date <= end)])
    monkeypatch.setattr(bp, "_pykrx_returns", lambda key, start, end: full[(full.index.date >= start) & (full.index.date <= end)])
    monkeypatch.setattr(bp, "_cash_returns", lambda key, start, end: full[(full.index.date >= start) & (full.index.date <= end)])

    as_of = date(2024, 6, 30)
    df = bp.fetch_bucket_proxy_returns(as_of, window_days=120)
    assert not df.empty
    assert df.index.max().date() <= as_of  # look-ahead 차단


def test_per_bucket_failover_to_alternate(monkeypatch):
    idx = pd.bdate_range("2024-01-01", "2024-12-31")
    good = pd.Series(0.001, index=idx)

    def fake_yf(symbols, start, end):
        out = {}
        for s in symbols:
            if s == "MCHI":   # b4 1차 proxy 실패 시뮬
                out[s] = pd.Series(dtype=float)
            else:
                out[s] = good[(good.index.date >= start) & (good.index.date <= end)]
        return pd.DataFrame(out)

    monkeypatch.setattr(bp, "_raw_yf_batch_close", fake_yf)
    monkeypatch.setattr(bp, "_fred_returns", lambda key, start, end: good)
    monkeypatch.setattr(bp, "_pykrx_returns", lambda key, start, end: good)
    monkeypatch.setattr(bp, "_cash_returns", lambda key, start, end: good)

    df = bp.fetch_bucket_proxy_returns(date(2024, 6, 30), window_days=120)
    # b4_china는 MCHI 실패 → 대체 FXI로 폴오버해 컬럼 존재
    assert "b4_china" in df.columns
    assert df["b4_china"].notna().sum() > 0
```

- [ ] **Step 2: 실패 확인** — `pytest tests/unit/backtest/test_bucket_proxies.py -v` → FAIL (module not found).

- [ ] **Step 3: 구현** — `tradingagents/backtest/bucket_proxies.py`

```python
"""14-bucket 대표 proxy 시계열 (BL Σ용). 소스별 dispatch + as_of 끝점 + 버킷별 폴오버.

각 버킷 = (source, key) 우선순위 리스트. 1차 실패 시 다음 대체로 폴오버.
끝점은 항상 as_of (look-ahead 차단). native 통화 수익 (글로벌=USD, 국내=KRW).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

logger = logging.getLogger(__name__)

# bucket → [(source, key), ...] 우선순위. source: yf|fred|pykrx|cash
BUCKET_PROXY: dict[str, list[tuple[str, str]]] = {
    "a1_cash":             [("cash", "us_3m")],
    "a2_kr_rates":         [("pykrx", "148070"), ("yf", "EWY")],   # 국고채10년; 폴오버는 차선(불완전)
    "a3_us_rates":         [("yf", "IEF")],
    "a4_safe_fx":          [("fred", "dxy"), ("yf", "UUP")],
    "a5_gold_infl":        [("yf", "GLD")],
    "b1_kr_equity":        [("pykrx", "069500"), ("yf", "EWY")],
    "b2_dm_core":          [("yf", "URTH"), ("yf", "ACWI")],
    "b3_global_tech":      [("yf", "QQQ")],
    "b4_china":            [("yf", "MCHI"), ("yf", "FXI")],
    "b5_other_intl":       [("yf", "EEM"), ("yf", "VEA")],
    "b6_defensive_equity": [("yf", "SPLV"), ("yf", "USMV")],
    "b7_reits":            [("yf", "VNQ"), ("yf", "RWO")],
    "b8_cyclical_commodity": [("yf", "DBC"), ("yf", "XLE")],
    "b9_risk_credit":      [("yf", "HYG"), ("yf", "JNK")],
}


def _raw_yf_batch_close(symbols: list[str], start: date, end: date) -> pd.DataFrame:
    """yfinance close 일별수익 (date × symbol). 재사용: cross_asset_returns._raw_yf_batch."""
    from tradingagents.dataflows.cross_asset_returns import _raw_yf_batch
    raw = _raw_yf_batch(symbols, start, end)
    if raw is None or raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        lvl0 = raw.columns.get_level_values(0)
        closes = raw["Close"] if "Close" in lvl0 else (raw["Adj Close"] if "Adj Close" in lvl0 else pd.DataFrame())
    else:
        closes = raw[["Close"]] if "Close" in raw.columns else raw
    if closes is None or closes.empty:
        return pd.DataFrame()
    return closes.pct_change().dropna(how="all")


def _fred_returns(key: str, start: date, end: date) -> pd.Series:
    """FRED 인덱스(예 dxy) 일별수익. PIT: as_of_date=end."""
    from tradingagents.dataflows.fred import fetch_fred_series
    s = fetch_fred_series(key, start, end, as_of_date=end)
    if s is None or s.empty:
        return pd.Series(dtype=float)
    return s.sort_index().pct_change().dropna()


def _pykrx_returns(key: str, start: date, end: date) -> pd.Series:
    """pykrx ETF(예 069500) 일별수익. fetch_returns_matrix 재사용."""
    from tradingagents.skills.portfolio.returns_matrix import fetch_returns_matrix
    df = fetch_returns_matrix([key], start, end)
    if df is None or df.empty or key not in df.columns:
        return pd.Series(dtype=float)
    return df[key].dropna()


def _cash_returns(key: str, start: date, end: date) -> pd.Series:
    """현금: 단기금리(연%)/252 일별수익. 분산≈0 (bucket_cov가 floor)."""
    from tradingagents.dataflows.fred import fetch_fred_series
    lvl = fetch_fred_series(key, start, end, as_of_date=end)
    if lvl is None or lvl.empty:
        return pd.Series(dtype=float)
    return (lvl.sort_index() / 100.0 / 252.0).dropna()


def _fetch_one(source: str, key: str, start: date, end: date) -> pd.Series:
    if source == "yf":
        df = _raw_yf_batch_close([key], start, end)
        return df[key].dropna() if (not df.empty and key in df.columns) else pd.Series(dtype=float)
    if source == "fred":
        return _fred_returns(key, start, end)
    if source == "pykrx":
        return _pykrx_returns(key, start, end)
    if source == "cash":
        return _cash_returns(key, start, end)
    return pd.Series(dtype=float)


def fetch_bucket_proxy_returns(as_of: date, window_days: int = 730) -> pd.DataFrame:
    """14버킷 일별수익 DataFrame (date × bucket_key). 끝점=as_of, 버킷별 폴오버.

    빈 컬럼(전 proxy 실패)은 그대로 비워 둠 — bucket_cov가 핀 처리.
    """
    start = as_of - timedelta(days=int(window_days * 1.6))  # 영업일/달력 여유
    cols: dict[str, pd.Series] = {}
    for bkey, specs in BUCKET_PROXY.items():
        ser = pd.Series(dtype=float)
        for source, key in specs:
            try:
                ser = _fetch_one(source, key, start, as_of)
            except Exception as e:  # noqa: BLE001
                logger.warning("proxy %s/%s fetch fail (%s): %s", bkey, key, source, e)
                ser = pd.Series(dtype=float)
            if not ser.empty:
                break  # 1차 성공 → 폴오버 중단
        # as_of 이후 절대 미포함 (look-ahead 차단)
        if not ser.empty:
            ser = ser[ser.index <= pd.Timestamp(as_of)]
        cols[bkey] = ser
    df = pd.DataFrame(cols)
    return df
```

- [ ] **Step 4: 통과 확인** — `pytest tests/unit/backtest/test_bucket_proxies.py -v` → 3 PASS.

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/backtest/bucket_proxies.py tests/unit/backtest/test_bucket_proxies.py
git commit -m "feat(bl): bucket_proxies — 교정 proxy 맵 + as_of fetch + 버킷별 폴오버 (Phase A)"
```

- [ ] **Step 6: 적대적 감사 + 의도부합** — 오케스트레이터가 (a) look-ahead가 정말 차단되는지(as_of 경계), (b) 폴오버가 1차 성공 시 중단되는지, (c) spec §4.1 맵과 일치하는지 확인.

---

## Task A2: `bucket_cov.py` — inner-join → LW → ×252 → 버킷핀 → currency dial

**Files:**
- Create: `tradingagents/skills/portfolio/bucket_cov.py`
- Test: `tests/unit/skills/portfolio/test_bucket_cov.py`

PARTIAL-1 핵심: pairwise cov 금지, inner-join(`dropna how='any'`) 공통윈도에서만 LW. 비-NaN<252 버킷은 baseline 핀(컬럼 제외 표시). a1 분산 floor. ×252 연환산. PD 보장.

- [ ] **Step 1: 실패 테스트 작성** — `tests/unit/skills/portfolio/test_bucket_cov.py`

```python
from datetime import date
import numpy as np
import pandas as pd
import pytest
from tradingagents.skills.portfolio import bucket_cov as bc


def _good_frame(n=400, cols=None):
    cols = cols or [f"b{i}" for i in range(5)]
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2023-01-02", periods=n)
    return pd.DataFrame(rng.normal(0, 0.01, size=(n, len(cols))), index=idx, columns=cols)


def test_annualized_and_psd():
    df = _good_frame()
    Sigma, meta = bc.bucket_covariance(df, min_obs=252)
    # ×252 연환산: 대각 ≈ daily_var*252
    daily_var = df.var().mean()
    assert Sigma.values.diagonal().mean() == pytest.approx(daily_var * 252, rel=0.5)
    # PSD
    eig = np.linalg.eigvalsh(Sigma.values)
    assert eig.min() > -1e-10
    assert meta["pinned"] == []


def test_inner_join_no_pairwise():
    # 한 컬럼이 앞부분 NaN → inner-join이면 공통 행만 사용, 결과 NaN 없음
    df = _good_frame(cols=["x", "y", "z"])
    df.loc[df.index[:50], "z"] = np.nan
    Sigma, meta = bc.bucket_covariance(df, min_obs=100)
    assert not Sigma.isna().any().any()
    assert "z" in Sigma.columns  # 350 obs ≥ 100 → 유지


def test_short_bucket_pinned():
    # 한 컬럼이 비-NaN 30개뿐 → min_obs 미달 → 핀(컬럼 제외)
    df = _good_frame(cols=["x", "y", "short"])
    df["short"] = np.nan
    df.iloc[-30:, df.columns.get_loc("short")] = 0.01
    Sigma, meta = bc.bucket_covariance(df, min_obs=252)
    assert "short" in meta["pinned"]
    assert "short" not in Sigma.columns
    assert set(Sigma.columns) == {"x", "y"}


def test_cash_variance_floor():
    # 거의 상수 컬럼(현금) → floor 적용으로 분산 > 0 (특이 회피)
    df = _good_frame(cols=["a1_cash", "b1"])
    df["a1_cash"] = 0.0001  # 상수
    Sigma, meta = bc.bucket_covariance(df, min_obs=100, cash_keys=("a1_cash",))
    assert Sigma.loc["a1_cash", "a1_cash"] >= bc.CASH_VAR_FLOOR_ANNUAL * 0.99
```

- [ ] **Step 2: 실패 확인** — `pytest tests/unit/skills/portfolio/test_bucket_cov.py -v` → FAIL.

- [ ] **Step 3: 구현** — `tradingagents/skills/portfolio/bucket_cov.py`

```python
"""14-bucket 공분산 Σ (BL prior 역산·MQU용).

PARTIAL-1: inner-join(dropna how='any') 공통윈도에서만 단일 cov→LW 수축 (pairwise 금지).
비-NaN < min_obs 버킷은 호출자가 baseline 핀 (meta['pinned']). a1 분산 floor. ×252 연환산.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252
CASH_VAR_FLOOR_ANNUAL = (0.005) ** 2   # 0.5%/년 변동성 → 연분산 floor


def bucket_covariance(
    returns: pd.DataFrame,
    *,
    min_obs: int = 252,
    cash_keys: tuple[str, ...] = ("a1_cash",),
    method: str = "ledoit_wolf",
) -> tuple[pd.DataFrame, dict]:
    """returns(date×bucket, native) → (연환산 LW Σ, meta).

    meta = {pinned: [핀된 버킷], n_obs: 공통윈도 행수, shrinkage: δ}.
    핀: 비-NaN 관측 < min_obs 인 버킷은 제외 (호출자가 w_baseline 고정).
    """
    meta: dict = {"pinned": [], "n_obs": 0}
    if returns is None or returns.empty:
        return pd.DataFrame(), meta

    # 1) 버킷별 비-NaN 관측 수로 핀 판정
    valid_counts = returns.notna().sum()
    keep = [c for c in returns.columns if valid_counts[c] >= min_obs]
    meta["pinned"] = [c for c in returns.columns if c not in keep]
    if len(keep) < 2:
        return pd.DataFrame(), meta

    # 2) inner-join 공통윈도 (pairwise 금지)
    joined = returns[keep].dropna(how="any")
    meta["n_obs"] = len(joined)
    if len(joined) < min_obs:
        # 공통윈도 자체가 부족 → 빈 Σ (호출자 전체폴백)
        meta["pinned"] = list(returns.columns)
        return pd.DataFrame(), meta

    # 3) LW 수축 (clean inner-joined frame이라 안전) → 연환산
    from tradingagents.skills.portfolio.cov_estimator import compute_robust_cov
    bd: dict = {}
    daily = compute_robust_cov(joined, method=method, breakdown_out=bd)
    Sigma = daily * TRADING_DAYS
    meta["shrinkage"] = bd.get("shrinkage_intensity")

    # 4) a1 현금 분산 floor (특이/MQU 폭주 방지)
    for ck in cash_keys:
        if ck in Sigma.columns and Sigma.loc[ck, ck] < CASH_VAR_FLOOR_ANNUAL:
            Sigma.loc[ck, ck] = CASH_VAR_FLOOR_ANNUAL

    # 5) PD 보강 (수축 후에도 수치적 안전망)
    Sigma = _nearest_pd(Sigma)
    return Sigma, meta


def _nearest_pd(S: pd.DataFrame) -> pd.DataFrame:
    arr = S.values
    arr = (arr + arr.T) / 2
    eig = np.linalg.eigvalsh(arr)
    if eig.min() < 1e-12:
        arr = arr + np.eye(arr.shape[0]) * (1e-12 - eig.min())
    return pd.DataFrame(arr, index=S.index, columns=S.columns)
```

- [ ] **Step 4: 통과 확인** — `pytest tests/unit/skills/portfolio/test_bucket_cov.py -v` → 4 PASS.

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/skills/portfolio/bucket_cov.py tests/unit/skills/portfolio/test_bucket_cov.py
git commit -m "feat(bl): bucket_cov — inner-join LW 연환산 Σ + 버킷핀 + a1 floor (Phase A, PARTIAL-1)"
```

- [ ] **Step 6: 적대적 감사 + 의도부합** — (a) pairwise가 정말 안 쓰이는지(inner-join 후 cov), (b) 핀 임계 동작, (c) ×252·floor·PD, (d) spec §4.2와 일치 확인.

---

# Phase B — BL 엔진 + 게이트2 (게이트2 통과 후 Phase C)

## Task B1: 상대 view 구성 — tier→s, 평균제거, P/Q (MATH-3·BLOW-1)

**Files:**
- Create: `tradingagents/skills/portfolio/bl_engine.py` (일부)
- Test: `tests/unit/skills/portfolio/test_bl_views.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/unit/skills/portfolio/test_bl_views.py`

```python
import numpy as np
from tradingagents.skills.portfolio import bl_engine as be


def test_tier_score_and_mean_removal():
    buckets = ["b1", "b2", "b3", "b4"]
    ranking = {
        "b1": ("strong_OW", 1.0), "b2": ("OW", 1.0),
        "b3": ("UW", 1.0), "b4": ("strong_UW", 1.0),
    }
    s = be.tier_scores(buckets, ranking)
    assert abs(s.sum()) < 1e-12  # 평균제거 zero-sum
    assert s[0] > s[1] > s[2] > s[3]


def test_all_same_tier_gives_empty_views():
    buckets = ["b1", "b2", "b3"]
    ranking = {b: ("strong_OW", 0.9) for b in buckets}  # 일색
    P, Q, conf = be.build_relative_views(buckets, ranking, base_spread=0.04)
    assert P.shape[0] == 0  # 평균제거 후 전부 0 → view=∅


def test_relative_view_zero_sum_and_magnitude():
    buckets = ["b1", "b2", "b3"]
    ranking = {"b1": ("strong_OW", 1.0), "b2": ("neutral", 0.0), "b3": ("strong_UW", 1.0)}
    P, Q, conf = be.build_relative_views(buckets, ranking, base_spread=0.04)
    # 비중립 2개 → 2 views, 각 P행 zero-sum
    assert P.shape == (2, 3)
    assert np.allclose(P.sum(axis=1), 0.0)
    assert np.all(np.abs(Q) <= 0.04 + 1e-9)


def test_conviction_capped_at_095():
    buckets = ["b1", "b2"]
    ranking = {"b1": ("strong_OW", 5.0), "b2": ("strong_UW", 5.0)}  # >0.95 입력
    P, Q, conf = be.build_relative_views(buckets, ranking, base_spread=0.04)
    assert np.all(conf <= 0.95 + 1e-9)
```

- [ ] **Step 2: 실패 확인** — `pytest tests/unit/skills/portfolio/test_bl_views.py -v` → FAIL.

- [ ] **Step 3: 구현** — `tradingagents/skills/portfolio/bl_engine.py` (생성, view 파트)

```python
"""Black-Litterman 버킷 배분 엔진.

prior 역산 (Π=δΣw_baseline, δ-항등) + 상대 view (tier 평균제거·P=e_i−1/N) +
Idzorek Ω + BL 결합 + max_quadratic_utility(**prior Σ**) + camp별 soft-clip.

핵심 불변식: view=∅ → 사후=prior=baseline 정확복원 (prior Σ 사용 시).
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

TAU = 0.05
CONVICTION_CAP = 0.95

_TIER_SCORE = {
    "strong_OW": 1.0, "OW": 0.5, "neutral": 0.0, "UW": -0.5, "strong_UW": -1.0,
}


def tier_scores(buckets: list[str], ranking: dict[str, tuple[str, float]]) -> np.ndarray:
    """tier·conviction → 부호화 점수 s_i, 평균제거(zero-sum). 미지정 버킷=neutral(0)."""
    raw = np.array([
        _TIER_SCORE.get((ranking.get(b) or ("neutral", 0.0))[0], 0.0)
        * min(max(float((ranking.get(b) or ("neutral", 0.0))[1]), 0.0), CONVICTION_CAP)
        for b in buckets
    ])
    return raw - raw.mean()


def build_relative_views(
    buckets: list[str], ranking: dict[str, tuple[str, float]], base_spread: float = 0.04,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """랭킹 → (P, Q, view_confidences). 비중립(s_i≠0) 버킷마다 P_i=e_i−1/N, Q_i=base_spread·s_i.

    전부 0(일색/중립) → 빈 (0×N, 0, 0) → 호출자가 view=∅ 처리.
    """
    n = len(buckets)
    s = tier_scores(buckets, ranking)
    active = [i for i in range(n) if abs(s[i]) > 1e-9]
    if not active:
        return np.zeros((0, n)), np.zeros(0), np.zeros(0)
    P = np.zeros((len(active), n))
    Q = np.zeros(len(active))
    conf = np.zeros(len(active))
    for row, i in enumerate(active):
        P[row, :] = -1.0 / n
        P[row, i] += 1.0
        Q[row] = base_spread * s[i]
        conf[row] = min(abs(s[i]), CONVICTION_CAP)  # |s_i| ∈ (0,0.95]
    return P, Q, conf
```

- [ ] **Step 4: 통과 확인** — `pytest tests/unit/skills/portfolio/test_bl_views.py -v` → 4 PASS.

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/skills/portfolio/bl_engine.py tests/unit/skills/portfolio/test_bl_views.py
git commit -m "feat(bl): bl_engine 상대 view — tier 평균제거·zero-sum P·conviction cap (Phase B, MATH-3)"
```

- [ ] **Step 6: 적대적 감사 + 의도부합** — all-same-tier→∅, zero-sum, conviction≤0.95, spec §5(2) 일치.

---

## Task B2: Π 역산 + Idzorek BL 결합 + MQU(prior Σ) + 정확복원 (MATH-1·MATH-2)

**Files:**
- Modify: `tradingagents/skills/portfolio/bl_engine.py` (append)
- Test: `tests/unit/skills/portfolio/test_bl_combine.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/unit/skills/portfolio/test_bl_combine.py`

```python
import numpy as np
import pandas as pd
import pytest
from tradingagents.skills.portfolio import bl_engine as be


def _toy(n=5, seed=1):
    rng = np.random.default_rng(seed)
    A = rng.normal(0, 1, (n, n))
    Sigma = pd.DataFrame(A @ A.T / n * 0.04, index=[f"b{i}" for i in range(n)], columns=[f"b{i}" for i in range(n)])
    w = pd.Series(1.0 / n, index=Sigma.index)
    return Sigma, w


@pytest.mark.parametrize("delta", [1.0, 2.5, 4.0, 8.0])
def test_no_view_recovers_baseline_exact(delta):
    Sigma, w_base = _toy()
    w = be.bl_bucket_weights(
        Sigma, w_base, ranking={}, delta=delta, base_spread=0.04,
        growth_keys=set(), mandate_risk_keys=set(),  # 제약 slack
    )
    assert np.allclose(w.values, w_base.values, atol=1e-6)  # 임의 δ 정확복원


def test_split_delta_breaks_recovery():
    # 역산 δ≠최적화 δ 면 복원 깨짐 (음성 테스트, δ-항등 입증)
    Sigma, w_base = _toy()
    w = be._bl_weights_split_delta(Sigma, w_base, delta_inv=2.5, delta_opt=8.0)
    assert not np.allclose(w.values, w_base.values, atol=1e-3)


def test_known_view_directionally_correct():
    Sigma, w_base = _toy()
    ranking = {"b0": ("strong_OW", 0.9), "b4": ("strong_UW", 0.9)}
    w = be.bl_bucket_weights(Sigma, w_base, ranking=ranking, delta=2.5, base_spread=0.04,
                             growth_keys=set(), mandate_risk_keys=set())
    assert w["b0"] > w_base["b0"]   # OW 버킷 ↑
    assert w["b4"] < w_base["b4"]   # UW 버킷 ↓
    assert abs(w.sum() - 1.0) < 1e-6
```

- [ ] **Step 2: 실패 확인** — `pytest tests/unit/skills/portfolio/test_bl_combine.py -v` → FAIL.

- [ ] **Step 3: 구현** — `bl_engine.py` append

```python
def implied_prior_returns(Sigma: "pd.DataFrame", w_baseline: "pd.Series", delta: float) -> "pd.Series":
    """Π = δ·Σ·w_baseline. δ-항등: 호출자는 최적화에도 같은 δ 사용."""
    import pandas as pd
    pi = delta * Sigma.values @ w_baseline.reindex(Sigma.index).values
    return pd.Series(pi, index=Sigma.index)


def _posterior_mu(Sigma, pi, P, Q, conf, delta):
    """μ_BL via pypfopt Idzorek. 실패 시 pi (prior) 반환."""
    import pandas as pd
    if P.shape[0] == 0:
        return pi.copy()
    try:
        from pypfopt.black_litterman import BlackLittermanModel
        bl = BlackLittermanModel(
            Sigma, pi=pi, P=P, Q=Q,
            omega="idzorek", view_confidences=conf,
            tau=TAU, risk_aversion=delta,
        )
        return pd.Series(bl.bl_returns().values, index=Sigma.index)
    except Exception as e:  # noqa: BLE001
        logger.warning("BL combine failed (%s) → prior μ", e)
        return pi.copy()


def _max_quad_utility(mu, Sigma, delta, growth_keys, mandate_risk_keys,
                      growth_cap=0.70, mandate_cap=0.68):
    """max_quadratic_utility(mu, **prior Σ**, δ) + 그룹제약. 실패 시 None (호출자 폴백)."""
    try:
        import cvxpy as cp
        from pypfopt import EfficientFrontier
        cols = list(Sigma.index)
        ef = EfficientFrontier(mu, Sigma, weight_bounds=(0, 1))
        if growth_keys:
            gi = [cols.index(b) for b in cols if b in growth_keys]
            if gi:
                ef.add_constraint(lambda w, gi=gi: cp.sum(w[gi]) <= growth_cap)
        if mandate_risk_keys:
            mi = [cols.index(b) for b in cols if b in mandate_risk_keys]
            if mi:
                ef.add_constraint(lambda w, mi=mi: cp.sum(w[mi]) <= mandate_cap)
        ef.max_quadratic_utility(risk_aversion=delta)
        import pandas as pd
        return pd.Series(ef.clean_weights(rounding=None), index=cols).reindex(cols)
    except Exception as e:  # noqa: BLE001
        logger.warning("MQU failed (%s)", e)
        return None


def bl_bucket_weights(Sigma, w_baseline, ranking, *, delta=2.5, base_spread=0.04,
                      growth_keys=None, mandate_risk_keys=None,
                      extra_views=None):
    """전체 BL: Π 역산 → 상대view(+extra) → μ_BL → MQU(prior Σ). 실패 시 w_baseline.

    extra_views: (P_extra, Q_extra, conf_extra) fx/credit 결정론 view (선택).
    """
    import numpy as np
    import pandas as pd
    buckets = list(Sigma.index)
    w_baseline = w_baseline.reindex(buckets)
    pi = implied_prior_returns(Sigma, w_baseline, delta)
    P, Q, conf = build_relative_views(buckets, ranking, base_spread)
    if extra_views is not None:
        Pe, Qe, ce = extra_views
        if Pe.shape[0] > 0:
            P = np.vstack([P, Pe]) if P.shape[0] else Pe
            Q = np.concatenate([Q, Qe]) if Q.shape[0] else Qe
            conf = np.concatenate([conf, ce]) if conf.shape[0] else ce
    mu = _posterior_mu(Sigma, pi, P, Q, conf, delta)
    w = _max_quad_utility(mu, Sigma, delta, growth_keys or set(), mandate_risk_keys or set())
    if w is None or w.isna().any():
        return w_baseline.copy()
    return w


def _bl_weights_split_delta(Sigma, w_baseline, delta_inv, delta_opt):
    """음성 테스트 전용: 역산·최적화 δ 분리 시 복원 깨짐 입증."""
    pi = implied_prior_returns(Sigma, w_baseline, delta_inv)
    w = _max_quad_utility(pi, Sigma, delta_opt, set(), set())
    return w if w is not None else w_baseline.copy()
```

- [ ] **Step 4: 통과 확인** — `pytest tests/unit/skills/portfolio/test_bl_combine.py -v` → PASS (정확복원 4 param + split-delta + known-view).

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/skills/portfolio/bl_engine.py tests/unit/skills/portfolio/test_bl_combine.py
git commit -m "feat(bl): Π 역산 + Idzorek 결합 + MQU(prior Σ) — no-view 정확복원·δ-항등 (Phase B, MATH-1/2)"
```

- [ ] **Step 6: 적대적 감사 + 의도부합** — (a) MQU가 **prior Σ**(bl_cov 아님)를 쓰는지, (b) 임의 δ 정확복원, (c) split-delta 음성, (d) 그룹제약 인덱싱, spec §5(4)(5) 일치.

---

## Task B3: camp별 soft-clip + water-fill (FALSE-1)

**Files:**
- Modify: `tradingagents/skills/portfolio/bl_engine.py` (append)
- Test: `tests/unit/skills/portfolio/test_bl_softclip.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/unit/skills/portfolio/test_bl_softclip.py`

```python
import pandas as pd
from tradingagents.skills.portfolio import bl_engine as be


def test_growth_bucket_soft_clipped_not_fallback():
    w = pd.Series({"b3_global_tech": 0.45, "a1_cash": 0.30, "a3_us_rates": 0.25})
    growth = {"b3_global_tech"}
    out = be.soft_clip(w, growth_keys=growth, growth_cap=0.30, defensive_cap=0.50)
    assert out["b3_global_tech"] <= 0.30 + 1e-9   # 성장 천장
    assert abs(out.sum() - 1.0) < 1e-9            # water-fill로 sum 보존


def test_defensive_bucket_higher_ceiling_no_false_trip():
    # 침체기 a3 OW 0.40 — 방어천장 0.50 → clip 안 됨 (false-trip 부재)
    w = pd.Series({"a3_us_rates": 0.40, "b1_kr_equity": 0.35, "a1_cash": 0.25})
    out = be.soft_clip(w, growth_keys={"b1_kr_equity"}, growth_cap=0.30, defensive_cap=0.50)
    assert out["a3_us_rates"] == pytest.approx(0.40, abs=1e-9)  # 방어 → 유지
    assert out["b1_kr_equity"] <= 0.30 + 1e-9                   # 성장 → clip
```

(상단에 `import pytest` 추가)

- [ ] **Step 2: 실패 확인** — `pytest tests/unit/skills/portfolio/test_bl_softclip.py -v` → FAIL.

- [ ] **Step 3: 구현** — `bl_engine.py` append

```python
def soft_clip(w, *, growth_keys, growth_cap=0.30, defensive_cap=0.50):
    """camp별 단일 버킷 천장 soft-clip + 잔여 water-fill (baseline 폴백 아님).

    성장 버킷 ≤ growth_cap, 방어 버킷 ≤ defensive_cap. 초과분을 비-clip 버킷에
    head(천장 여유) 비례 재분배. _clamp_to_pool_capacity 패턴.
    """
    import pandas as pd
    w = w.copy().astype(float)
    cap = pd.Series(
        {b: (growth_cap if b in growth_keys else defensive_cap) for b in w.index}
    )
    for _ in range(50):
        over = (w - cap).clip(lower=0.0)
        excess = float(over.sum())
        if excess < 1e-12:
            break
        w = w.clip(upper=cap)
        head = (cap - w).clip(lower=0.0)
        room = float(head.sum())
        if room < 1e-12:
            break
        w = w + excess * head / room
    return w
```

- [ ] **Step 4: 통과 확인** — `pytest tests/unit/skills/portfolio/test_bl_softclip.py -v` → 2 PASS.

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/skills/portfolio/bl_engine.py tests/unit/skills/portfolio/test_bl_softclip.py
git commit -m "feat(bl): camp별 soft-clip + water-fill — 침체 방어 OW false-trip 제거 (Phase B, FALSE-1)"
```

- [ ] **Step 6: 적대적 감사 + 의도부합** — 성장 clip·방어 천장 상향·sum 보존·baseline 폴백 아님, spec §5.1 일치.

---

## Task B4: `bl_allocate` 오케스트레이터 — A+B 결합 + 폴백 + attribution meta

**Files:**
- Modify: `tradingagents/skills/portfolio/bl_engine.py` (append `bl_allocate`)
- Test: `tests/unit/skills/portfolio/test_bl_allocate.py`

버킷핀(부분실패) → (14−k) BL + 핀 버킷 baseline 고정 → soft-clip. 전체폴백 조건. attribution용 status meta.

- [ ] **Step 1: 실패 테스트 작성** — `tests/unit/skills/portfolio/test_bl_allocate.py`

```python
import numpy as np
import pandas as pd
from tradingagents.skills.portfolio import bl_engine as be
from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS, GROWTH_KEYS


def _sigma14(pinned=()):
    keep = [b for b in GAPS_BUCKET_KEYS if b not in pinned]
    rng = np.random.default_rng(2)
    A = rng.normal(0, 1, (len(keep), len(keep)))
    return pd.DataFrame(A @ A.T / len(keep) * 0.04, index=keep, columns=keep)


def _baseline14():
    from tradingagents.skills.portfolio.scenario_anchor import QUADRANT_BASELINE
    return pd.Series(QUADRANT_BASELINE["growth_disinflation"])


def test_pinned_bucket_fixed_others_bl():
    # b4_china 핀: Σ에서 빠짐 → b4는 baseline 고정, 나머지 BL, 합=1
    Sigma = _sigma14(pinned=("b4_china",))
    base = _baseline14()
    res = be.bl_allocate(Sigma, base, ranking={"b3_global_tech": ("strong_OW", 0.9)},
                         pinned=["b4_china"], delta=2.5, growth_keys=set(GROWTH_KEYS))
    w = res["weights"]
    assert abs(w.sum() - 1.0) < 1e-6
    assert w["b4_china"] == pytest.approx(base["b4_china"], abs=1e-9)  # 핀 고정
    assert res["meta"]["b4_china"]["status"] == "baseline_pinned"


def test_empty_sigma_full_fallback():
    base = _baseline14()
    res = be.bl_allocate(pd.DataFrame(), base, ranking={}, pinned=list(GAPS_BUCKET_KEYS),
                         delta=2.5, growth_keys=set(GROWTH_KEYS))
    assert np.allclose(res["weights"].reindex(base.index).values, base.values, atol=1e-9)
    assert res["meta"]["__global__"]["status"] == "full_fallback"
```

(상단 `import pytest`)

- [ ] **Step 2: 실패 확인** — `pytest tests/unit/skills/portfolio/test_bl_allocate.py -v` → FAIL.

- [ ] **Step 3: 구현** — `bl_engine.py` append

```python
def bl_allocate(Sigma, w_baseline, ranking, *, pinned=None, delta=2.5, base_spread=0.04,
                growth_keys=None, mandate_risk_keys=None, extra_views=None,
                growth_cap=0.30, defensive_cap=0.50):
    """BL 배분 오케스트레이터: 부분실패 버킷핀 + (14−k) BL + soft-clip + attribution meta.

    반환 {weights: pd.Series(14), meta: {bucket: {status, ...}, __global__: {...}}}.
    status: bl | baseline_pinned | full_fallback.
    """
    import pandas as pd
    pinned = set(pinned or [])
    all_buckets = list(w_baseline.index)
    meta: dict = {}

    # 전체폴백: Σ 비거나 ≥절반 핀
    if Sigma is None or Sigma.empty or len(pinned) >= (len(all_buckets) + 1) // 2:
        meta["__global__"] = {"status": "full_fallback", "reason": "empty_sigma_or_majority_pinned"}
        return {"weights": w_baseline.copy(), "meta": meta}

    bl_buckets = [b for b in all_buckets if b not in pinned]
    pin_weight = float(w_baseline[list(pinned)].sum()) if pinned else 0.0
    budget = 1.0 - pin_weight  # BL 버킷에 배분할 예산

    Sigma_bl = Sigma.reindex(index=bl_buckets, columns=bl_buckets)
    base_bl = w_baseline[bl_buckets]
    base_bl = base_bl / base_bl.sum() if base_bl.sum() > 0 else base_bl  # BL 내부 정규화

    gk = {b for b in (growth_keys or set()) if b in bl_buckets}
    mk = {b for b in (mandate_risk_keys or set()) if b in bl_buckets}
    rk = {k: v for k, v in ranking.items() if k in bl_buckets}

    w_bl = bl_bucket_weights(Sigma_bl, base_bl, rk, delta=delta, base_spread=base_spread,
                             growth_keys=gk, mandate_risk_keys=mk, extra_views=extra_views)
    w_bl = soft_clip(w_bl, growth_keys=gk, growth_cap=growth_cap, defensive_cap=defensive_cap)
    w_bl = w_bl * budget  # 예산 스케일

    out = pd.Series(0.0, index=all_buckets)
    for b in bl_buckets:
        out[b] = float(w_bl.get(b, 0.0))
        meta[b] = {"status": "bl"}
    for b in pinned:
        out[b] = float(w_baseline[b])
        meta[b] = {"status": "baseline_pinned"}
    # 수치 정규화 (sum=1 보장)
    if out.sum() > 0:
        out = out / out.sum()
    meta["__global__"] = {"status": "bl", "n_pinned": len(pinned)}
    return {"weights": out, "meta": meta}
```

- [ ] **Step 4: 통과 확인** — `pytest tests/unit/skills/portfolio/test_bl_allocate.py -v` → 2 PASS. 전체 bl_engine 회귀: `pytest tests/unit/skills/portfolio/test_bl_*.py -v`.

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/skills/portfolio/bl_engine.py tests/unit/skills/portfolio/test_bl_allocate.py
git commit -m "feat(bl): bl_allocate 오케스트레이터 — 버킷핀·전체폴백·soft-clip·attribution meta (Phase B, PARTIAL-1)"
```

- [ ] **Step 6: 적대적 감사 + 의도부합** — 핀 예산 보존·전체폴백 조건·sum=1·status meta, spec §8 일치.

---

## Task B5: §17 사후 w 유계 불변식 테스트 (BLOW-1)

**Files:**
- Test: `tests/unit/skills/portfolio/test_bl_invariants.py`

코드 추가 없이 폭주방지 계약을 테스트로 잠금(실패 시 B1-B4로 회귀).

- [ ] **Step 1: 테스트 작성**

```python
import numpy as np
import pandas as pd
from tradingagents.skills.portfolio import bl_engine as be
from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS, GROWTH_KEYS
from tradingagents.skills.portfolio.scenario_anchor import QUADRANT_BASELINE


def _real_sigma(seed=3):
    keep = list(GAPS_BUCKET_KEYS)
    rng = np.random.default_rng(seed)
    vols = rng.uniform(0.05, 0.30, len(keep))
    C = rng.uniform(0.1, 0.6, (len(keep), len(keep)))
    C = (C + C.T) / 2
    np.fill_diagonal(C, 1.0)
    S = np.outer(vols, vols) * C
    S = S @ S.T / len(keep) + np.eye(len(keep)) * 1e-4
    return pd.DataFrame(S, index=keep, columns=keep)


def test_full_conviction_single_view_bounded():
    Sigma = _real_sigma()
    base = pd.Series(QUADRANT_BASELINE["growth_disinflation"])
    res = be.bl_allocate(Sigma, base, ranking={"b3_global_tech": ("strong_OW", 0.95)},
                         delta=2.5, growth_keys=set(GROWTH_KEYS),
                         growth_cap=0.30, defensive_cap=0.50)
    w = res["weights"]
    assert w.max() <= 0.50 + 1e-9            # camp 천장 이내
    assert np.abs(w - base).sum() <= 0.40    # L1 유계
    defensive = [b for b in base.index if b not in GROWTH_KEYS]
    assert w[defensive].sum() >= base[defensive].sum() * 0.5  # 방어합 붕괴 안 함


def test_sigma_vol_perturbation_stays_bounded():
    base = pd.Series(QUADRANT_BASELINE["growth_disinflation"])
    for scale in (0.8, 1.0, 1.2):
        Sigma = _real_sigma() * scale
        res = be.bl_allocate(Sigma, base, ranking={"b3_global_tech": ("strong_OW", 0.95)},
                             delta=2.5, growth_keys=set(GROWTH_KEYS),
                             growth_cap=0.30, defensive_cap=0.50)
        assert res["weights"].max() <= 0.50 + 1e-9
```

- [ ] **Step 2: 실행** — `pytest tests/unit/skills/portfolio/test_bl_invariants.py -v`. PASS 기대. FAIL이면 soft_clip/cap 조정(B3) 회귀.

- [ ] **Step 3: 커밋**

```bash
git add tests/unit/skills/portfolio/test_bl_invariants.py
git commit -m "test(bl): §17 사후 w 유계 불변식 (폭주방지 회귀가드, BLOW-1)"
```

- [ ] **Step 4: 적대적 감사** — 천장·L1·방어합 단언이 실제 폭주를 잡는지, Σ 섭동 견고성.

---

## Task B6: `trader_allocator` 분기 플래그 + as_of 배선 (고정-view BL 경로) (PIT-1)

**Files:**
- Modify: `tradingagents/agents/trader/trader_allocator.py`
- Test: `tests/unit/agents/test_trader_allocator_bl_branch.py`

`portfolio_dials["use_bl"]` 플래그로 BL 분기. as_of 추출→bucket_cov fetch. Phase B에서는 고정 view(state["bl_fixed_ranking"] 주입)로만 — LLM ranking은 Phase C.

- [ ] **Step 1: 실패 테스트 작성**

```python
from datetime import date
import numpy as np
import pandas as pd
import pytest
from tradingagents.agents.trader import trader_allocator as ta


def test_bl_branch_uses_as_of_and_returns_bucket_weights(monkeypatch, tmp_path):
    # bucket_proxies/bucket_cov 스텁: as_of 전달 확인
    captured = {}

    def fake_proxies(as_of, window_days=730):
        captured["as_of"] = as_of
        idx = pd.bdate_range(end=pd.Timestamp(as_of), periods=400)
        from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS
        rng = np.random.default_rng(0)
        return pd.DataFrame(rng.normal(0, 0.01, (400, 14)), index=idx, columns=list(GAPS_BUCKET_KEYS))

    monkeypatch.setattr(ta, "fetch_bucket_proxy_returns", fake_proxies, raising=False)
    # 최소 universe state로 build_bl_bucket_weights 직접 호출
    aso = date(2026, 5, 10)
    bw = ta.build_bl_bucket_weights(
        as_of=aso, quadrant="growth_disinflation",
        ranking={"b3_global_tech": ("strong_OW", 0.9)},
        fx_regime="neutral", credit_regime="neutral",
    )
    assert captured["as_of"] == aso
    assert abs(sum(bw.values()) - 1.0) < 1e-6
    assert set(bw).issubset(set(__import__(
        "tradingagents.skills.portfolio.gaps_buckets", fromlist=["GAPS_BUCKET_KEYS"]
    ).GAPS_BUCKET_KEYS))
```

- [ ] **Step 2: 실패 확인** — FAIL (`build_bl_bucket_weights`/`fetch_bucket_proxy_returns` 미존재).

- [ ] **Step 3: 구현** — `trader_allocator.py` 상단 import + 신규 함수 추가, node에 분기

import 추가:
```python
from tradingagents.backtest.bucket_proxies import fetch_bucket_proxy_returns
from tradingagents.skills.portfolio.bucket_cov import bucket_covariance
from tradingagents.skills.portfolio import bl_engine
from tradingagents.skills.portfolio.gaps_buckets import GROWTH_KEYS
from tradingagents.skills.mandate.concentration_check import RISK_BUCKET_NAMES
```

신규 함수 (모듈 레벨, `create_trader_allocator` 위):
```python
# camp→mandate-RISK 근사 (spec §5(5)): b1-b8 + a5_gold + a4_safe_fx
_MANDATE_RISK_BUCKETS = {
    "b1_kr_equity", "b2_dm_core", "b3_global_tech", "b4_china", "b5_other_intl",
    "b6_defensive_equity", "b7_reits", "b8_cyclical_commodity",
    "a5_gold_infl", "a4_safe_fx",
}
_FX_CREDIT_SPREAD = 0.02


def _fx_credit_extra_views(buckets, fx_regime, credit_regime, base_spread=_FX_CREDIT_SPREAD):
    """fx/credit 결정론 상대 view → (P,Q,conf). spec §5(3)."""
    import numpy as np
    rows = []   # (over_bucket, under_bucket)
    if credit_regime == "crisis":
        rows.append(("a3_us_rates", "b9_risk_credit"))
    if fx_regime == "usd_risk_off":
        rows.append(("a4_safe_fx", "b1_kr_equity"))
    n = len(buckets)
    if not rows:
        return np.zeros((0, n)), np.zeros(0), np.zeros(0)
    P = np.zeros((len(rows), n)); Q = np.zeros(len(rows)); conf = np.zeros(len(rows))
    for r, (ov, un) in enumerate(rows):
        if ov in buckets and un in buckets:
            P[r, buckets.index(ov)] = 0.5; P[r, buckets.index(un)] = -0.5
            P[r, :] -= P[r, :].mean()   # zero-sum 보정
            Q[r] = base_spread; conf[r] = 0.9
    return P, Q, conf


def build_bl_bucket_weights(as_of, quadrant, ranking, *, fx_regime="neutral",
                            credit_regime="neutral", delta=2.5, base_spread=0.04,
                            window_days=730):
    """BL 버킷 비중 (dict). Σ fetch(as_of) → bl_allocate. 실패 시 baseline."""
    import pandas as pd
    base = pd.Series(QUADRANT_BASELINE[quadrant])
    try:
        rets = fetch_bucket_proxy_returns(as_of, window_days=window_days)
        Sigma, cov_meta = bucket_covariance(rets, min_obs=252)
        pinned = cov_meta.get("pinned", list(base.index)) if Sigma.empty else cov_meta.get("pinned", [])
    except Exception as e:  # noqa: BLE001
        logger.warning("BL Σ fetch failed (%s) → baseline", e)
        return {k: float(v) for k, v in base.items()}
    buckets = list(base.index)
    extra = _fx_credit_extra_views(buckets, fx_regime, credit_regime)
    res = bl_engine.bl_allocate(
        Sigma if not Sigma.empty else None, base, ranking,
        pinned=pinned, delta=delta, base_spread=base_spread,
        growth_keys=set(GROWTH_KEYS), mandate_risk_keys=_MANDATE_RISK_BUCKETS,
        extra_views=extra,
    )
    return {k: float(v) for k, v in res["weights"].items() if v > 1e-9}, res["meta"]
```

(반환 튜플로 수정: `return ({...}, res["meta"])`; baseline 경로도 `return ({...}, {"__global__": {"status": "baseline_no_sigma"}})`)

node 분기 — 현 `bucket_weights = project_to_band(...)` 직전에:
```python
        _dials = state.get("portfolio_dials") or {}
        use_bl = bool(_dials.get("use_bl", False))
        bl_meta = {}
        if use_bl:
            as_of = date.fromisoformat(state["as_of_date"])
            ranking = state.get("bl_fixed_ranking") or {}   # Phase C: LLM ranking 주입
            bucket_weights, bl_meta = build_bl_bucket_weights(
                as_of, quadrant, ranking, fx_regime=fx_regime, credit_regime=credit_regime,
                delta=float(_dials.get("bl_delta", 2.5)),
                base_spread=float(_dials.get("bl_base_spread", 0.04)),
            )
            bucket_weights = _clamp_to_pool_capacity(bucket_weights, pool)
        else:
            # --- 옛 경로 (정리 Phase에서 제거) ---
            <기존 anchor/eff/tilt/project_to_band/vol_haircut/clamp 블록 그대로>
```

(파일 상단에 `from datetime import date` 확인 — 이미 trader_allocator는 미import면 추가.)

- [ ] **Step 4: 통과 확인** — `pytest tests/unit/agents/test_trader_allocator_bl_branch.py -v` → PASS. 기존 회귀: `pytest tests/unit/agents/ -k allocator -v`.

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/agents/trader/trader_allocator.py tests/unit/agents/test_trader_allocator_bl_branch.py
git commit -m "feat(bl): trader_allocator BL 분기 플래그 + as_of 배선 + fx/credit view (Phase B, PIT-1)"
```

- [ ] **Step 6: 적대적 감사 + 의도부합** — (a) as_of가 정말 fetch로 흘러 look-ahead 차단, (b) 옛 경로 무손상(플래그 off 시 동일), (c) fx/credit view zero-sum, spec §3·§5(3) 일치.

---

## Task B7: `scripts/backtest_bl_gate2.py` — 게이트2 ⓐ–ⓕ + native/KRW 발산 + base_spread 스윕

**Files:**
- Create: `scripts/backtest_bl_gate2.py`
- Test: `tests/unit/backtest/test_gate2.py` (sanity 판정 함수만 단위테스트)

게이트2는 LLM·하네스 불필요. 고정 view로 ⓐ–ⓕ sanity. 보정(base_spread 스윕)은 비차단.

- [ ] **Step 1: 실패 테스트 작성** — `tests/unit/backtest/test_gate2.py`

```python
import numpy as np
import pandas as pd
from scripts.backtest_bl_gate2 import gate2_checks
from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS, GROWTH_KEYS
from tradingagents.skills.portfolio.scenario_anchor import QUADRANT_BASELINE


def _sigma():
    keep = list(GAPS_BUCKET_KEYS)
    rng = np.random.default_rng(7)
    A = rng.normal(0, 1, (14, 14))
    return pd.DataFrame(A @ A.T / 14 * 0.04, index=keep, columns=keep)


def test_gate2_no_view_exact_recovery_and_direction():
    Sigma = _sigma()
    base = pd.Series(QUADRANT_BASELINE["growth_disinflation"])
    rep = gate2_checks(Sigma, base, growth_keys=set(GROWTH_KEYS),
                       mandate_risk_keys=set(), delta=2.5, base_spread=0.04)
    assert rep["d_no_view_recovers"] is True     # ⓓ L1<1e-6
    assert rep["a_direction"] is True            # ⓐ b3↑ a3↓
    assert rep["b_not_inert"] is True            # ⓑ L1≥0.05
    assert rep["c_no_blowup"] is True            # ⓒ max≤천장
```

- [ ] **Step 2: 실패 확인** — FAIL.

- [ ] **Step 3: 구현** — `scripts/backtest_bl_gate2.py`

```python
"""게이트2 (차단·LLM불필요·하네스불필요): 고정 view sanity ⓐ–ⓕ + native/KRW 발산.

ⓐ 방향, ⓑ inert 아님(L1≥0.05), ⓒ 폭주 없음(soft-clip 후 max≤천장),
ⓓ no-view 정확복원(L1<1e-6, prior Σ), ⓔ 방어 OW false-trip 부재,
ⓕ realized-RISK 차단(고정 view 위험합 cap·repair 훼손 측정).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from tradingagents.skills.portfolio import bl_engine


def _l1(a, b):
    return float(np.abs(a.reindex(b.index).fillna(0) - b).sum())


def gate2_checks(Sigma, baseline, *, growth_keys, mandate_risk_keys, delta=2.5,
                 base_spread=0.04, growth_cap=0.30, defensive_cap=0.50, eps_min=0.05):
    """sanity 딕셔너리 반환. 모든 키 True면 게이트2 PASS."""
    # ⓓ no-view
    w0 = bl_engine.bl_allocate(Sigma, baseline, {}, delta=delta, base_spread=base_spread,
                               growth_keys=growth_keys, mandate_risk_keys=mandate_risk_keys,
                               growth_cap=growth_cap, defensive_cap=defensive_cap)["weights"]
    d_ok = _l1(w0, baseline) < 1e-6
    # ⓐⓑⓒ 고정 view: b3 OW, a3 UW
    rk = {"b3_global_tech": ("strong_OW", 0.9), "a3_us_rates": ("strong_UW", 0.9)}
    w1 = bl_engine.bl_allocate(Sigma, baseline, rk, delta=delta, base_spread=base_spread,
                               growth_keys=growth_keys, mandate_risk_keys=mandate_risk_keys,
                               growth_cap=growth_cap, defensive_cap=defensive_cap)["weights"]
    a_ok = (w1["b3_global_tech"] > baseline["b3_global_tech"]) and (w1["a3_us_rates"] < baseline["a3_us_rates"])
    b_ok = _l1(w1, baseline) >= eps_min
    c_ok = w1.max() <= max(growth_cap, defensive_cap) + 1e-9
    return {
        "d_no_view_recovers": bool(d_ok), "a_direction": bool(a_ok),
        "b_not_inert": bool(b_ok), "c_no_blowup": bool(c_ok),
        "l1_no_view": _l1(w0, baseline), "l1_view": _l1(w1, baseline),
        "max_bucket": float(w1.max()),
    }


def gate2_defensive_false_trip(Sigma, baseline, *, growth_keys, mandate_risk_keys,
                               delta=2.5, base_spread=0.04, growth_cap=0.30, defensive_cap=0.50):
    """ⓔ recession_disinflation a3 strong_OW → soft-clip graceful, 전체폴백 아님."""
    rk = {"a3_us_rates": ("strong_OW", 0.95)}
    res = bl_engine.bl_allocate(Sigma, baseline, rk, delta=delta, base_spread=base_spread,
                                growth_keys=growth_keys, mandate_risk_keys=mandate_risk_keys,
                                growth_cap=growth_cap, defensive_cap=defensive_cap)
    w = res["weights"]
    not_fallback = res["meta"]["__global__"]["status"] != "full_fallback"
    a3_moved_up = w["a3_us_rates"] > baseline["a3_us_rates"]   # view 반영됨(전손 아님)
    return {"e_no_false_trip": bool(not_fallback and a3_moved_up), "a3": float(w["a3_us_rates"])}
```

(메인 `if __name__ == "__main__":` 블록은 실제 proxy fetch로 Σ를 만들어 위 함수들 + native/KRW 발산 + base_spread 스윕을 출력 — 실행시 보고용. 단위테스트는 함수만.)

- [ ] **Step 4: 통과 확인** — `pytest tests/unit/backtest/test_gate2.py -v` → PASS.

- [ ] **Step 5: 게이트2 실행 (라이브 Σ)** — `PYTHONUTF8=1 .venv/Scripts/python scripts/backtest_bl_gate2.py --as-of 2026-05-10` → ⓐ–ⓕ 전부 PASS인지 출력 확인. **FAIL이면 STOP**, δ·base_spread·Σ 재보정·사용자 보고.

- [ ] **Step 6: 커밋**

```bash
git add scripts/backtest_bl_gate2.py tests/unit/backtest/test_gate2.py
git commit -m "feat(bl): 게이트2 sanity ⓐ-ⓕ + native/KRW 발산 + base_spread 스윕 (Phase B, HARNESS-1)"
```

- [ ] **Step 7: 적대적 감사 + 의도부합** — ⓐ–ⓕ가 spec §7과 정확히 일치, ⓓ가 prior Σ로 통과, ⓔ false-trip 부재.

> **⚠️ STOP 게이트:** 게이트2 ⓐ–ⓕ 전부 PASS여야 Phase C 진행. FAIL이면 사용자 보고 후 재논의.

---

# Phase C — LLM 상대 view + attribution + 철학 facts (게이트2 통과 후)

## Task C1: `BucketTilt.bucket_ranking` 스키마

**Files:**
- Modify: `tradingagents/schemas/portfolio.py:95-101`
- Test: `tests/unit/schemas/test_bucket_ranking.py`

> 선행 ETF-선택이 이미 `sub_category_views`를 추가했다고 가정. 본 Task는 `bucket_ranking`만 추가.

- [ ] **Step 1: 실패 테스트 작성**

```python
from tradingagents.schemas.portfolio import BucketTilt, BucketRanking


def test_bucket_ranking_field():
    bt = BucketTilt(bucket_ranking={
        "b3_global_tech": BucketRanking(tier="strong_OW", conviction=0.8, rationale="AI"),
    })
    assert bt.bucket_ranking["b3_global_tech"].tier == "strong_OW"
    assert 0.0 <= bt.bucket_ranking["b3_global_tech"].conviction <= 0.95


def test_conviction_clamped():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        BucketRanking(tier="OW", conviction=1.5, rationale="x")
```

- [ ] **Step 2: 실패 확인** — FAIL.

- [ ] **Step 3: 구현** — `schemas/portfolio.py`

```python
from typing import Literal


class BucketRanking(BaseModel):
    """버킷 상대순위 view (BL). LLM은 tier·conviction만, 수익숫자는 코드 변환."""
    tier: Literal["strong_OW", "OW", "neutral", "UW", "strong_UW"]
    conviction: float = Field(ge=0.0, le=0.95)
    rationale: str = Field(default="", max_length=200)
```
`BucketTilt`에 필드 추가:
```python
    bucket_ranking: dict[str, BucketRanking] = Field(
        default_factory=dict,
        description="bucket key → 상대순위 view (BL). tier+conviction.",
    )
```

- [ ] **Step 4: 통과 확인** — `pytest tests/unit/schemas/test_bucket_ranking.py -v` → PASS.

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/schemas/portfolio.py tests/unit/schemas/test_bucket_ranking.py
git commit -m "feat(bl): BucketTilt.bucket_ranking 스키마 (Phase C)"
```

- [ ] **Step 6: 적대적 감사** — conviction [0,0.95] clamp, tier Literal, ETF-선택 sub_category_views와 공존.

---

## Task C2: Step-A 프롬프트 상대순위 + LLM ranking → BL 배선

**Files:**
- Modify: `tradingagents/agents/trader/trader_allocator.py` (`_STEP_A_SYSTEM`, `_step_a_prompt`, node)
- Test: `tests/unit/agents/test_trader_allocator_bl_llm.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from tradingagents.agents.trader import trader_allocator as ta
from tradingagents.schemas.portfolio import BucketTilt, BucketRanking


def test_ranking_to_engine_format():
    bt = BucketTilt(bucket_ranking={
        "b3_global_tech": BucketRanking(tier="strong_OW", conviction=0.8, rationale="x"),
        "a3_us_rates": BucketRanking(tier="UW", conviction=0.5, rationale="y"),
    })
    rk = ta._ranking_from_tilt(bt)
    assert rk["b3_global_tech"] == ("strong_OW", 0.8)
    assert rk["a3_us_rates"] == ("UW", 0.5)
```

- [ ] **Step 2: 실패 확인** — FAIL.

- [ ] **Step 3: 구현** — `trader_allocator.py`

`_STEP_A_SYSTEM` 교체(BL 경로용 — 상대순위):
```python
_STEP_A_SYSTEM_BL = (
    "당신은 자산배분 트레이더다. 14개 버킷을 매력도 tier로 순위매겨라:\n"
    "strong_OW/OW/neutral/UW/strong_UW 중 하나 + conviction(0~0.95).\n"
    "절대 수익률을 예측하지 말고, 버킷 간 '상대 매력도 순서'만 판단하라.\n"
    "확신 없는 버킷은 neutral. 모두 OW 같은 일색은 금지(상대순위가 의미 없어짐)."
)
```

헬퍼 + 프롬프트:
```python
def _ranking_from_tilt(bt):
    """BucketTilt.bucket_ranking → bl_engine 포맷 {bucket: (tier, conviction)}."""
    return {k: (v.tier, float(v.conviction)) for k, v in (bt.bucket_ranking or {}).items()}


def _step_a_prompt_bl(state, quadrant, fx_regime, credit_regime):
    rd = state.get("research_decision")
    thesis = getattr(rd, "thesis_md", "") if rd else ""
    key_risks = getattr(rd, "key_risks", []) if rd else []
    from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS, BUCKET_KR_NAME
    bucket_list = "\n".join(f"  {b} ({BUCKET_KR_NAME[b]})" for b in GAPS_BUCKET_KEYS)
    body = (
        f"## Regime: {quadrant}, fx: {fx_regime}, credit: {credit_regime}\n\n"
        f"## 14 버킷 (각각 tier+conviction 부여)\n{bucket_list}\n\n"
        f"## 리서치 종합\n{thesis}\n\n"
        f"## 핵심 리스크\n" + ("\n".join(f"  - {r}" for r in key_risks) or "  (없음)") + "\n\n"
        f"## Stage1 요약\n매크로: {state.get('macro_summary','(없음)')}\n"
        f"리스크: {state.get('risk_summary','(없음)')}\n뉴스: {state.get('news_summary','(없음)')}\n\n"
        "각 버킷의 tier+conviction 상대순위를 출력하라."
    )
    return [{"role": "system", "content": _STEP_A_SYSTEM_BL}, {"role": "user", "content": body}]
```

node BL 분기 수정 — 고정 ranking 대신 LLM 호출:
```python
        if use_bl:
            as_of = date.fromisoformat(state["as_of_date"])
            if state.get("bl_fixed_ranking") is not None:
                ranking = state["bl_fixed_ranking"]          # 게이트2/테스트
            else:
                tilt = state.get("cached_tilt") or invoke_structured_obj(
                    structured_a, _step_a_prompt_bl(state, quadrant, fx_regime, credit_regime),
                    BucketTilt(), "TraderStepA",
                )
                ranking = _ranking_from_tilt(tilt)
            bucket_weights, bl_meta = build_bl_bucket_weights(
                as_of, quadrant, ranking, fx_regime=fx_regime, credit_regime=credit_regime,
                delta=float(_dials.get("bl_delta", 2.5)),
                base_spread=float(_dials.get("bl_base_spread", 0.04)),
            )
            bucket_weights = _clamp_to_pool_capacity(bucket_weights, pool)
```

- [ ] **Step 4: 통과 확인** — `pytest tests/unit/agents/test_trader_allocator_bl_llm.py -v` → PASS.

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/agents/trader/trader_allocator.py tests/unit/agents/test_trader_allocator_bl_llm.py
git commit -m "feat(bl): Step-A 상대순위 프롬프트 + LLM ranking→BL 배선 (Phase C)"
```

- [ ] **Step 6: 적대적 감사 + 의도부합** — 프롬프트가 절대수익 아닌 상대순위 요구, 일색 금지 지시, ranking 변환, spec §6 일치.

---

## Task C3: BL-native attribution (ATTR-1·ATTR-2)

**Files:**
- Modify: `tradingagents/agents/trader/trader_allocator.py` (attribution 블록)
- Test: `tests/unit/agents/test_bl_attribution.py`

BL 경로는 tilts/scenario_delta가 없으므로 `{prior, view_contribution, optimizer_shift, final, realized}` 분해.

- [ ] **Step 1: 실패 테스트 작성**

```python
from tradingagents.agents.trader import trader_allocator as ta
import pandas as pd


def test_bl_attribution_decomposition():
    base = {"b3_global_tech": 0.14, "a3_us_rates": 0.12}
    final = {"b3_global_tech": 0.20, "a3_us_rates": 0.10}
    realized = {"b3_global_tech": 0.18, "a3_us_rates": 0.10}
    bl_meta = {"b3_global_tech": {"status": "bl"}, "a3_us_rates": {"status": "bl"},
               "__global__": {"status": "bl"}}
    attr = ta._bl_step_a_attribution(base, final, realized, bl_meta)
    assert attr["method"] == "bl"
    b3 = attr["buckets"]["b3_global_tech"]
    assert b3["baseline"] == 0.14 and b3["final"] == 0.20 and b3["realized"] == 0.18
    assert "view_shift" in b3
```

- [ ] **Step 2: 실패 확인** — FAIL.

- [ ] **Step 3: 구현** — `trader_allocator.py`

```python
def _bl_step_a_attribution(baseline, final, realized, bl_meta):
    """BL 경로 attribution: prior→final(의도)→realized + 버킷 status. spec §8."""
    buckets = {}
    for b in set(baseline) | set(final) | set(realized):
        base_r = round(float(baseline.get(b, 0.0)), 6)
        fin_r = round(float(final.get(b, 0.0)), 6)
        real_r = round(float(realized.get(b, 0.0)), 6)
        if abs(base_r) < 1e-9 and abs(fin_r) < 1e-9 and abs(real_r) < 1e-9:
            continue
        buckets[b] = {
            "baseline": base_r,
            "view_shift": round(fin_r - base_r, 6),     # prior→의도 (BL view 기여)
            "final": fin_r,
            "realized": real_r,
            "intent_vs_realized": round(real_r - fin_r, 6),
            "status": (bl_meta.get(b) or {}).get("status", "bl"),
        }
    return {"method": "bl", "buckets": buckets, "global": bl_meta.get("__global__", {})}
```

node에서 BL 경로일 때 `attribution["step_a"]`를 위 함수로 채움 (use_bl 분기):
```python
        if use_bl:
            attribution["step_a"] = _bl_step_a_attribution(
                {k: q_baseline.get(k, 0.0) for k in GAPS_BUCKET_KEYS},
                bucket_weights, realized_bucket_weights, bl_meta,
            )
```

- [ ] **Step 4: 통과 확인** — `pytest tests/unit/agents/test_bl_attribution.py -v` → PASS.

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/agents/trader/trader_allocator.py tests/unit/agents/test_bl_attribution.py
git commit -m "feat(bl): BL-native attribution (prior→view_shift→final→realized) (Phase C, ATTR)"
```

- [ ] **Step 6: 적대적 감사 + 의도부합** — 분해축이 BL에 맞고 의도/실현 분리, status 노출, spec §8 일치.

---

## Task C4: 철학 결정론 facts — prior 정당화 + 상관 분석 (PHIL-4)

**Files:**
- Modify: `tradingagents/agents/.../philosophy.py` (facts block) — 정확 경로는 구현 시 `grep -rn "_build_facts_block\|format_step_a" tradingagents/` 로 확인
- Test: `tests/unit/.../test_philosophy_bl_facts.py`

- [ ] **Step 1: 위치 확인** — `grep -rn "_build_facts_block\|단일 리스크\|format_step_a" tradingagents/agents/` 로 philosophy facts 함수 위치 파악.

- [ ] **Step 2: 실패 테스트 작성** — `bl_correlation_facts(Corr, growth_keys)` 가 최고 상관쌍·클러스터 비중합을 결정론 문자열로 반환

```python
import numpy as np
import pandas as pd
from tradingagents.skills.portfolio.bl_facts import bl_correlation_facts, prior_justification_facts


def test_correlation_facts_top_pair():
    keys = ["b1_kr_equity", "b3_global_tech", "a1_cash"]
    Corr = pd.DataFrame([[1.0, 0.85, 0.1], [0.85, 1.0, 0.05], [0.1, 0.05, 1.0]], index=keys, columns=keys)
    txt = bl_correlation_facts(Corr, weights={"b1_kr_equity": 0.2, "b3_global_tech": 0.18, "a1_cash": 0.1})
    assert "b1_kr_equity" in txt and "b3_global_tech" in txt and "0.85" in txt


def test_prior_justification_lists_baseline():
    txt = prior_justification_facts("recession_inflation")
    assert "a5_gold_infl" in txt and "0.17" in txt   # 인플레헤지 금
```

- [ ] **Step 3: 실패 확인** — FAIL.

- [ ] **Step 4: 구현** — `tradingagents/skills/portfolio/bl_facts.py`

```python
"""철학 리포트용 결정론 facts (PHIL-4): prior 정당화 + 상관 분석. LLM 인용, 날조 금지."""
from __future__ import annotations

import numpy as np
import pandas as pd

from tradingagents.skills.portfolio.scenario_anchor import QUADRANT_BASELINE


def prior_justification_facts(quadrant: str) -> str:
    base = QUADRANT_BASELINE.get(quadrant, {})
    top = sorted(base.items(), key=lambda kv: -kv[1])[:5]
    lines = [f"- {k}: {v:.2f}" for k, v in top]
    return f"[Prior(baseline) {quadrant} 상위 5]\n" + "\n".join(lines)


def correlation_from_cov(Sigma: pd.DataFrame) -> pd.DataFrame:
    d = np.sqrt(np.diag(Sigma.values))
    d[d == 0] = 1.0
    Dinv = np.diag(1.0 / d)
    C = Dinv @ Sigma.values @ Dinv
    return pd.DataFrame(C, index=Sigma.index, columns=Sigma.columns)


def bl_correlation_facts(Corr: pd.DataFrame, weights: dict[str, float] | None = None) -> str:
    pairs = []
    cols = list(Corr.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            pairs.append((cols[i], cols[j], float(Corr.iloc[i, j])))
    pairs.sort(key=lambda t: -abs(t[2]))
    top = pairs[:3]
    lines = [f"- {a}~{b}: corr {c:.2f}" for a, b, c in top]
    out = "[최고 상관쌍]\n" + "\n".join(lines)
    if weights and top:
        hi = {top[0][0], top[0][1]}
        s = sum(weights.get(k, 0.0) for k in hi)
        out += f"\n[최고상관 클러스터 비중합 {','.join(hi)}: {s:.2f}]"
    return out
```

philosophy facts 블록에서 BL 경로일 때 위 두 함수 결과를 facts에 주입 (Step 1에서 찾은 함수에 호출 추가).

- [ ] **Step 5: 통과 확인** — `pytest tests/unit/skills/portfolio/test_bl_facts.py -v` → PASS.

- [ ] **Step 6: 커밋**

```bash
git add tradingagents/skills/portfolio/bl_facts.py tests/unit/skills/portfolio/test_bl_facts.py
git commit -m "feat(bl): 철학 결정론 facts — prior 정당화 + 상관 분석 (Phase C, PHIL-4)"
```

- [ ] **Step 7: 적대적 감사 + 의도부합** — facts가 결정론(LLM 날조 차단), 상관/클러스터가 규칙 line 77 충족, spec §7 일치.

---

# Phase D — 정리 (게이트2·라이브 검증 후)

## Task D1: 옛 경로 제거 + 플래그 제거

**Files:**
- Modify: `tradingagents/agents/trader/trader_allocator.py`, `tradingagents/skills/portfolio/scenario_anchor.py`, `tradingagents/schemas/portfolio.py`
- Modify: 관련 테스트

> **선행:** Task B7 게이트2 PASS + Task D2 라이브 검증 PASS 후에만 실행.

- [ ] **Step 1: 옛 경로 참조 확인** — `grep -rn "project_to_band\|apply_macro_modifiers\|_risk_tilt_delta\|apply_vol_haircut\|tilt.tilts\|\.tilts" tradingagents/ tests/` 로 제거 대상 전수.

- [ ] **Step 2: trader_allocator 정리** — node에서 `use_bl` 분기의 옛 블록(anchor/eff/tilt/project_to_band/vol_haircut) 삭제, BL 경로를 기본(무조건)으로. `_STEP_A_SYSTEM`/`_step_a_prompt`(옛) 삭제, import 정리(scenario_anchor에서 hard_band/effective_band/project_to_band/apply_macro_modifiers, vol_haircut 제거).

- [ ] **Step 3: scenario_anchor 정리** — `project_to_band`/`apply_macro_modifiers`/`_risk_tilt_delta`/`RISK_TILT_AMOUNT`/`CREDIT_MODIFIER`/`FX_MODIFIER`/`hard_band`/`effective_band` 삭제. `QUADRANT_BASELINE`만 유지.

- [ ] **Step 4: 스키마 정리** — `BucketTilt.tilts` 필드 제거(`bucket_ranking`·`sub_category_views`·`rationale`만).

- [ ] **Step 5: 테스트 갱신·실행** — 옛 경로 테스트 삭제/갱신, `PYTHONUTF8=1 .venv/Scripts/python -m pytest tests/ -q` 전체 통과 확인.

- [ ] **Step 6: 커밋**

```bash
git add -A
git commit -m "refactor(bl): 옛 Step-A 경로 제거 (project_to_band/vol_haircut/tilts), BL 기본화 (Phase D)"
```

- [ ] **Step 7: 적대적 감사** — 죽은 코드 0 잔존(grep), BL 기본 경로 무결, 전체 테스트 green.

---

## Task D2: 풀 라이브 재검증

**Files:** 없음 (실행만)

- [ ] **Step 1: 풀 파이프라인 실행** — `PYTHONUTF8=1 .venv/Scripts/python -m <파이프라인 진입점> --as-of 2026-05-10` (정확한 진입점은 `grep -rn "def main\|argparse" scripts/ replay_stage*` 로 확인). validation_passed + 3 artifacts 확인, BL 경로로 동작·attribution이 BL-native인지 확인.

- [ ] **Step 2: 결과 보고** — BL 버킷 비중·realized risk%·attribution·철학 facts를 사용자에게 보고. (커밋 불필요 — 검증 산출물.)

- [ ] **Step 3: 적대적 감사** — 라이브 결과가 spec 의도(방어성+상대view 틸트, top-30 레버는 ETF층)와 부합하는지, look-ahead 없는지(as_of) 최종 확인.

---

## 자기 검토 (작성자 체크)

**1. spec 커버리지:** §3 데이터흐름(B6 as_of·C3 attribution), §4.1 proxy맵(A1), §4.2 cov(A2), §5(1)Π(B2), §5(2)view(B1), §5(3)fx/credit(B6), §5(4)(5)결합·MQU prior Σ(B2), §5.1 soft-clip(B3), §5.2 mandate제약(B2/B6), §6 LLM계약(C1/C2), §7 게이트2(B7)·철학facts(C4), §8 폴백·attribution(B4/C3), §9 테스트(전 Task), §10 Phase(A-D) → 전 항목 Task 매핑됨. ✅

**2. placeholder:** D1/D2/C4 Step1은 `grep`으로 위치를 *확인*하는 실제 동작(정확 경로가 코드베이스 탐색 필요) — TODO 아님. 그 외 전 Task에 완전 코드. ✅

**3. 타입 일관성:** `bl_allocate`(B4) 반환 `{weights, meta}`, `build_bl_bucket_weights`(B6) 반환 `(dict, meta)`, `bl_bucket_weights`(B2)는 Series — 호출 일관. `bucket_covariance`(A2) `(Sigma, meta)`, `fetch_bucket_proxy_returns`(A1) DataFrame. ✅
