# Black-Litterman Allocator 전환 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stage 3 Step A 비중 결정을 공분산 기반 Black-Litterman(prior=regime baseline+Σ, view=LLM Idzorek + fx/credit 결정론)으로 전환하되, prior를 backtest로 먼저 검증한다.

**Architecture:** `regime baseline → Π=δΣw`(reverse-opt) + `LLM view(Idzorek)` → `pypfopt BlackLitterman posterior` → MV opt → 14버킷 비중 → 기존 mandate 투영·종목선정·cap repair. 종목·리밸런싱 엔진은 재사용.

**Tech Stack:** Python 3, pydantic v2, pytest, pandas, numpy, **pypfopt 1.6.0**(BlackLittermanModel·EfficientFrontier·risk_models).

**설계 문서:** `docs/superpowers/specs/2026-06-09-bl-allocator-design.md`

---

## ⚠️ STOP 게이트 (실행 순서의 핵심)

- **게이트 1** (Phase 1 후): 결정론 골격이 벤치마크(60/40·risk parity·단일 baseline·1/N) 대비 의미 있는 우위 → 없으면 **regime 골격 재고, Phase 2+ 중단**.
- **게이트 2** (Phase 2 후): BL(고정 view) vs 현행 비중 차이가 hard band 안 노이즈 초과 → 노이즈면 **BL 과잉설계, Phase 3 재고**.
- 게이트는 LLM 없이 측정. **Phase 3(LLM view)는 두 게이트 통과 후에만.**

---

## File Structure

| 파일 | 책임 | 변경 |
|---|---|---|
| `tradingagents/skills/portfolio/bucket_cov.py` | 종목→버킷 AUM 합성 수익률 + 14×14 Σ | 신규 |
| `tradingagents/backtest/bucket_proxies.py` | 14버킷 → 대표 지수 proxy 장기 시계열 (§12.1 정비 보류) | 신규 |
| `tradingagents/backtest/baseline_backtest.py` | 결정론 골격 backtest 루프 + summarize + regime 분류(PIT) | 신규 |
| `tradingagents/backtest/benchmarks.py` | 벤치마크 4종(60/40·risk parity·1/N) | 신규 |
| `tradingagents/backtest/data.py` | `fetch_macro_quarterly_extended`에 `as_of_date`·CFNAI-MA3 추가(PIT, #21) | 수정 |
| `scripts/backtest_baseline.py` | backtest 진입점 + 게이트1 정량 판정(net-of-cost) | 신규 |
| `tradingagents/skills/portfolio/bl_engine.py` | Π + BL 결합 + MV opt | 신규 |
| `tradingagents/skills/portfolio/signal_aggregation.py` | Stage1 지표 → 14버킷×카테고리 z 테이블 | 신규 |
| `tradingagents/agents/trader/trader_allocator.py` | Step A 코어 BL 교체 | 수정 |
| `tradingagents/schemas/portfolio.py` | `BucketTilt` → BL view 벡터 | 수정 |
| `tradingagents/schemas/research.py` | `risk_tilt` 강등 | 수정 |
| `tradingagents/agents/researchers/research_cluster.py` | bull/bear 강등 | 수정 |
| `tradingagents/skills/portfolio/scenario_anchor.py` | modifier 폐기(밴드/baseline 유지) | 수정 |
| `tradingagents/skills/portfolio/vol_haircut.py` | 제거 | 삭제 |

**의존성 순서:** Phase 1 → 게이트 1 → Phase 2 → 게이트 2 → Phase 3 → Phase 4.

---

# Phase 1 — 결정론 골격 + Backtest (게이트 1)

LLM 없이 `regime baseline + Σ + 리밸런싱`을 15-20년 backtest해 prior(baseline)를 검증한다. **이 Phase만으로 "baseline이 벤치마크를 이기는가"라는 독립 deliverable**이 나온다.

## Task 1.1: 14버킷 → 대표 지수 proxy 장기 시계열

**Files:**
- Create: `tradingagents/backtest/bucket_proxies.py`
- Test: `tests/unit/backtest/test_bucket_proxies.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/unit/backtest/test_bucket_proxies.py
from datetime import date
from tradingagents.backtest.bucket_proxies import BUCKET_PROXY, fetch_bucket_proxy_returns
from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS

def test_every_bucket_has_proxy():
    for b in GAPS_BUCKET_KEYS:
        assert b in BUCKET_PROXY, f"{b} proxy 누락"

def test_fetch_returns_shape(monkeypatch):
    import tradingagents.backtest.bucket_proxies as bp
    import pandas as pd
    monkeypatch.setattr(bp, "_fetch_proxy_series",
        lambda key, s, e: pd.Series([0.01, -0.02, 0.03],
            index=pd.to_datetime(["2020-01-31","2020-02-29","2020-03-31"])))
    df = fetch_bucket_proxy_returns(date(2020,1,1), date(2020,3,31))
    assert set(df.columns) == set(GAPS_BUCKET_KEYS)
    assert len(df) == 3
```

- [ ] **Step 2: 실패 확인** — `pytest tests/unit/backtest/test_bucket_proxies.py -v` → FAIL (ImportError)

- [ ] **Step 3: 구현** — 14버킷→지수 매핑 + 월간 수익률 fetch

```python
# tradingagents/backtest/bucket_proxies.py
"""14버킷 → 대표 지수 proxy 장기 시계열 (backtest 전용, §11 design)."""
from __future__ import annotations
from datetime import date
import pandas as pd
from tradingagents.dataflows.equity_indices import fetch_equity_index_close
from tradingagents.dataflows.fred import fetch_fred_series
from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS

# bucket → (source, key). source: "yf"(equity_indices) | "fred"(yield→듀레이션 price proxy) | "cash"(단기금리 level/12)
# ⚠️ v1 proxy는 6버킷으로 붕괴(중복/방향오류) — 설계 §12.1 보류 결정 참조.
#    구현 시 옵션 A(권장: a5→gold, a4→DXY/JPY, a2→KR국채, b6→SPLV) 채택 여부 확정 후 이 표 교체.
BUCKET_PROXY: dict[str, tuple[str, str]] = {
    "a1_cash":              ("cash", "us_3m_tbill"),  # 현금: yield level/12 (duration≈0), 듀레이션 분기 금지
    "a2_kr_rates":          ("fred", "us_10y"),       # §12.1: KR국채(ECOS)로 교체 검토 (현재 a3와 완전상관)
    "a3_us_rates":          ("fred", "us_10y"),
    "a4_safe_fx":           ("yf",   "usdcnh"),        # §12.1: DXY/JPY 분리 검토 (현재 b4와 공유·방향반대)
    "a5_gold_infl":         ("yf",   "iron_ore"),      # §12.1: GLD/금선물로 교체 검토 (현재 b8과 동인반대)
    "b1_kr_equity":         ("yf",   "kospi200"),
    "b2_dm_core":           ("yf",   "ndx"),
    "b3_global_tech":       ("yf",   "sox"),
    "b4_china":             ("yf",   "usdcnh"),        # §12.1: 중국 ETF(FXI/MCHI)로 교체 검토
    "b5_other_intl":        ("yf",   "eem"),
    "b6_defensive_equity":  ("yf",   "rut"),           # §12.1: 소형주=고베타 → SPLV/저변동·배당으로 교체 검토
    "b7_reits":             ("yf",   "vnq"),
    "b8_cyclical_commodity":("yf",   "iron_ore"),
    "b9_risk_credit":       ("yf",   "hyg"),
}

def _fetch_proxy_series(key_tuple: tuple[str, str], start: date, end: date) -> pd.Series:
    source, key = key_tuple
    if source == "cash":
        # 현금/단기물: 월수익 ≈ yield_level/12 (duration≈0). 듀레이션 곱 금지(must_fix).
        s = fetch_fred_series(key, start, end)            # 단기금리 %(연율)
        monthly = s.resample("ME").last().dropna()
        return (monthly / 100.0 / 12.0).dropna()
    if source == "fred":
        # 채권: yield → 월간 가격수익 proxy ≈ -Δyield × duration(근사 7). a2/a3 전용.
        s = fetch_fred_series(key, start, end)
        monthly = s.resample("ME").last().dropna()
        return (-(monthly.diff()) * 7.0 / 100.0).dropna()
    px = fetch_equity_index_close(key, start, end)
    monthly = px.resample("ME").last().dropna()
    return monthly.pct_change().dropna()

def fetch_bucket_proxy_returns(start: date, end: date) -> pd.DataFrame:
    """14버킷 월간 수익률 (month_end × bucket). 결측은 NaN 유지 → 공통가용 구간으로 절단.
    ⚠️ fillna(0.0) 금지(must_fix): 0 채움은 σ≈0 위조 → risk_parity(1/σ) 폭발·gate 오염."""
    cols: dict[str, pd.Series] = {}
    for b in GAPS_BUCKET_KEYS:
        try:
            s = _fetch_proxy_series(BUCKET_PROXY[b], start, end)
            if not s.empty:
                cols[b] = s
        except Exception:
            pass  # 결측 버킷은 drop (0 채움 아님)
    df = pd.DataFrame(cols).sort_index()
    return df.dropna(how="any")   # 모든 버킷 공통 가용 구간만 (가장 늦은 proxy 시작 기준)
```

- [ ] **Step 4: 통과 확인** — `pytest tests/unit/backtest/test_bucket_proxies.py -v` → PASS

- [ ] **Step 5: proxy 품질 점검 + §12.1 보류 결정 확정(수동)** — `python -c "from datetime import date; from tradingagents.backtest.bucket_proxies import fetch_bucket_proxy_returns; df=fetch_bucket_proxy_returns(date(2008,1,1), date(2025,12,31)); print(df.describe()); print('공통구간', df.index.min(), df.index.max(), len(df))"` → 공통 가용 구간(dropna 후) 길이·각 버킷 σ 확인. **여기서 설계 §12.1의 proxy 정비 옵션(A 선결교정/B 핵심만/C 격하)을 사용자와 확정**한다. 옵션 A 선택 시 `BUCKET_PROXY` 표를 GLD/DXY/KR국채(ECOS)/SPLV로 교체하고 필요한 `EQUITY_INDEX_TICKERS`·FRED 시리즈를 보강(별도 sub-task). σ≈0이거나 공통구간이 비정상적으로 짧은 버킷이 있으면 proxy 결함 신호.

- [ ] **Step 6: 커밋** — `git add ... && git commit -m "feat(backtest): 14버킷 proxy 장기 시계열"`

## Task 1.2: 14버킷 공분산 (bucket_cov)

**Files:**
- Create: `tradingagents/skills/portfolio/bucket_cov.py`
- Test: `tests/unit/skills/portfolio/test_bucket_cov.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/unit/skills/portfolio/test_bucket_cov.py
import pandas as pd, numpy as np
from tradingagents.skills.portfolio.bucket_cov import bucket_returns_from_holdings, bucket_covariance

def test_bucket_returns_aum_weighted():
    etf_ret = pd.DataFrame({"A": [0.01, 0.02], "B": [0.03, -0.01]})
    members = {"b1_kr_equity": ["A", "B"]}
    aum = {"A": 100.0, "B": 300.0}   # B 가중 3배
    out = bucket_returns_from_holdings(etf_ret, members, aum)
    assert "b1_kr_equity" in out.columns
    # 0.01*0.25 + 0.03*0.75 = 0.025
    assert abs(out["b1_kr_equity"].iloc[0] - 0.025) < 1e-9

def test_bucket_cov_psd():
    rng = np.random.default_rng(0)
    ret = pd.DataFrame(rng.normal(0, 0.01, (300, 3)), columns=["b1_kr_equity","b2_dm_core","a1_cash"])
    cov = bucket_covariance(ret)
    eig = np.linalg.eigvalsh(cov.values)
    assert (eig > -1e-8).all()   # PSD
    assert list(cov.columns) == list(ret.columns)
```

- [ ] **Step 2: 실패 확인** — FAIL (ImportError)

- [ ] **Step 3: 구현**

```python
# tradingagents/skills/portfolio/bucket_cov.py
"""종목 수익률 → 버킷 AUM 가중 합성 → 14×14 Σ (design §5 N1)."""
from __future__ import annotations
import pandas as pd
from tradingagents.skills.portfolio.cov_estimator import compute_robust_cov

def bucket_returns_from_holdings(
    etf_returns: pd.DataFrame, members: dict[str, list[str]], aum: dict[str, float],
) -> pd.DataFrame:
    """각 버킷의 보유 ETF를 AUM 가중 합성한 버킷 수익률 (date × bucket)."""
    out: dict[str, pd.Series] = {}
    for bucket, tickers in members.items():
        cols = [t for t in tickers if t in etf_returns.columns]
        if not cols:
            continue
        w = pd.Series({t: max(aum.get(t, 0.0), 0.0) for t in cols})
        if w.sum() <= 0:
            w = pd.Series({t: 1.0 for t in cols})
        w = w / w.sum()
        out[bucket] = (etf_returns[cols] * w).sum(axis=1)
    return pd.DataFrame(out)

def bucket_covariance(bucket_returns: pd.DataFrame, *, method: str = "qis") -> pd.DataFrame:
    """버킷 수익률 → 강건 공분산 (cov_estimator 재활용)."""
    return compute_robust_cov(bucket_returns, method=method)
```

- [ ] **Step 4: 통과 확인** — PASS

- [ ] **Step 5: 커밋**

## Task 1.3: 벤치마크 (60/40 · risk parity · 단일 baseline · 1/N)

**Files:**
- Create: `tradingagents/backtest/benchmarks.py`
- Test: `tests/unit/backtest/test_benchmarks.py`

- [ ] **Step 1: 실패 테스트**

```python
# tests/unit/backtest/test_benchmarks.py
import pandas as pd, numpy as np
from tradingagents.backtest.benchmarks import equal_weight, sixty_forty, risk_parity_weights

def test_equal_weight_sums_one():
    w = equal_weight(["b1_kr_equity","a1_cash","b2_dm_core"])
    assert abs(sum(w.values()) - 1.0) < 1e-9 and all(abs(v-1/3) < 1e-9 for v in w.values())

def test_sixty_forty_split():
    w = sixty_forty()
    growth = sum(v for k,v in w.items() if k.startswith("b"))
    assert abs(growth - 0.6) < 1e-9

def test_risk_parity_lower_vol_higher_weight():
    rng = np.random.default_rng(0)
    ret = pd.DataFrame({"a1_cash": rng.normal(0,0.001,300),
                        "b1_kr_equity": rng.normal(0,0.02,300)})
    w = risk_parity_weights(ret)
    assert w["a1_cash"] > w["b1_kr_equity"]   # 저변동 자산에 더 큰 비중
```

- [ ] **Step 2: 실패 확인** — FAIL

- [ ] **Step 3: 구현**

```python
# tradingagents/backtest/benchmarks.py
"""baseline backtest 벤치마크 4종 (design §3-10)."""
from __future__ import annotations
import numpy as np, pandas as pd
from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS, GROWTH_KEYS, DEFENSIVE_KEYS
from tradingagents.skills.portfolio.cov_estimator import compute_robust_cov

def equal_weight(keys: list[str]) -> dict[str, float]:
    n = len(keys)
    return {k: 1.0 / n for k in keys}

def sixty_forty() -> dict[str, float]:
    """성장(B) 0.6 / 방어(A) 0.4, 진영 내 균등."""
    w = {}
    for k in GROWTH_KEYS:
        w[k] = 0.6 / len(GROWTH_KEYS)
    for k in DEFENSIVE_KEYS:
        w[k] = 0.4 / len(DEFENSIVE_KEYS)
    return w

def risk_parity_weights(bucket_returns: pd.DataFrame) -> dict[str, float]:
    """역변동성 근사 risk parity (1/σ 비례). 골격 벤치마크용 단순화."""
    cov = compute_robust_cov(bucket_returns)
    vol = np.sqrt(np.diag(cov.values))
    inv = 1.0 / np.where(vol > 1e-12, vol, 1e-12)
    w = inv / inv.sum()
    return {c: float(w[i]) for i, c in enumerate(cov.columns)}
```
단일 고정 baseline 벤치마크는 `QUADRANT_BASELINE["growth_disinflation"]`을 regime 무시하고 고정 사용 — Task 1.4에서 직접 참조(별도 함수 불필요).

- [ ] **Step 4: 통과 확인** — PASS
- [ ] **Step 5: 커밋**

## Task 1.4: regime baseline backtest 하네스

**Files:**
- Create: `tradingagents/backtest/baseline_backtest.py`
- Test: `tests/unit/backtest/test_baseline_backtest.py`

핵심: 과거 각 월말에 (a) regime 분류 → baseline 선택, (b) 월간 리밸런싱(no_trade_band 적용), (c) 다음 달 proxy 수익률로 포트폴리오 수익 적립. **LLM 없이** regime은 결정론 규칙 또는 archive된 과거 regime 사용.

- [ ] **Step 1: 실패 테스트**

```python
# tests/unit/backtest/test_baseline_backtest.py
import pandas as pd
from tradingagents.backtest.baseline_backtest import run_strategy_backtest

def test_backtest_returns_series():
    ret = pd.DataFrame({"b1_kr_equity":[0.01,0.02,-0.01], "a1_cash":[0.0,0.001,0.001]},
                       index=pd.to_datetime(["2020-01-31","2020-02-29","2020-03-31"]))
    # 고정 가중 전략
    weights_fn = lambda dt: {"b1_kr_equity":0.5, "a1_cash":0.5}
    perf = run_strategy_backtest(ret, weights_fn)
    assert "monthly_returns" in perf and len(perf["monthly_returns"]) == 2  # 첫달은 진입
```

- [ ] **Step 2: 실패 확인** — FAIL

- [ ] **Step 3: 구현** — 전략 무관 backtest 루프 (weights_fn 주입)

```python
# tradingagents/backtest/baseline_backtest.py
"""결정론 골격 backtest 루프 (design §9 게이트1). LLM 0."""
from __future__ import annotations
from collections.abc import Callable
import pandas as pd

def run_strategy_backtest(
    bucket_returns: pd.DataFrame,
    weights_fn: Callable[[pd.Timestamp], dict[str, float]],
    *, no_trade_band: float = 0.005,
) -> dict:
    """월간 리밸런싱 backtest. weights_fn(date)->목표비중. 반환: monthly_returns + turnover."""
    dates = list(bucket_returns.index)
    prev_w: dict[str, float] = {}
    rets, turns = [], []
    for i in range(len(dates) - 1):
        dt = dates[i]
        tgt = weights_fn(dt)
        # no_trade_band: 작은 변화 무시
        new_w = dict(prev_w)
        for k, v in tgt.items():
            if abs(v - prev_w.get(k, 0.0)) > no_trade_band:
                new_w[k] = v
        s = sum(new_w.values()) or 1.0
        new_w = {k: v / s for k, v in new_w.items()}
        turns.append(sum(abs(new_w.get(k,0)-prev_w.get(k,0)) for k in set(new_w)|set(prev_w)) / 2)
        nxt = bucket_returns.iloc[i + 1]
        rets.append(sum(new_w.get(k, 0.0) * nxt.get(k, 0.0) for k in new_w))
        prev_w = new_w
    return {"monthly_returns": pd.Series(rets, index=dates[1:]),
            "turnover": pd.Series(turns, index=dates[:-1])}
```

- [ ] **Step 4a: PIT 데이터 선행 보강** (결정 #21) — `tradingagents/backtest/data.py`의 `fetch_macro_quarterly_extended`에 `as_of_date` 파라미터를 추가해 내부 `fetch_fred_series(..., as_of_date=...)`로 publication lag 적용. **USREC(NBER 사후개정) 컬럼 사용 중단** → 실시간 침체 대용으로 `CFNAI-MA3`(FRED CFNAI 3개월 평균) 또는 Sahm rule(실업률) 컬럼 추가. (look-ahead 차단)

- [ ] **Step 4b: regime 결정론 분류 함수 (PIT)** — `resolve_historical_quadrant(dt, macro_q) -> str` + `_realtime_recession`을 추가하고 테스트 작성.

```python
def resolve_historical_quadrant(dt, macro_q: pd.DataFrame) -> str:
    """월말 dt의 quadrant (결정론, PIT). recession × inflation 2×2.
    ⚠️ PIT(#21): recession은 USREC(사후개정) 금지 → 실시간 대용. macro_q는 as_of_date PIT 산출물.
    ⚠️ §12.2 보류: 이 결정론 2×2 vs production LLM 분류기 불일치 — 구현 시 확정.
       기존 classify.py::_cycle/assign_cycle 재사용 검토(중복 제거 + 'live와 다름' 한계 명시)."""
    row = macro_q.asof(dt)
    recession = _realtime_recession(row)
    inflation = float(row.get("cpi_yoy", 0) or 0) > 3.0
    if recession and inflation: return "recession_inflation"
    if recession:               return "recession_disinflation"
    if inflation:               return "growth_inflation"
    return "growth_disinflation"

def _realtime_recession(row) -> bool:
    """USREC(사후개정) 대신 실시간 침체 판정(PIT). CFNAI-MA3 < -0.7."""
    cfnai_ma3 = row.get("cfnai_ma3")
    if cfnai_ma3 is not None and not pd.isna(cfnai_ma3):
        return float(cfnai_ma3) < -0.7
    return False   # 대용 부재 시 침체 아님으로 보수 처리(USREC look-ahead 사용 금지)
```

- [ ] **Step 5: 통과 확인 + 커밋**

## Task 1.5: 게이트 1 리포트 (성과 비교)

**Files:**
- Create: `scripts/backtest_baseline.py`
- Test: 통합 — 수동 실행 리포트

- [ ] **Step 1: summarize 신규 + 성과지표 재활용** — `baseline_backtest.py`에 `summarize(net_monthly_returns)->dict` 추가(TDD). `statistics.py`의 `drawdown_analysis`는 재활용하되 `_sharpe`는 **`periods_per_year=12` 명시 전달**(must_fix: 기본 4=분기라 월간 경로에서 연율화 오류).

```python
# baseline_backtest.py 에 추가
def summarize(monthly_returns) -> dict:
    """net 월수익 → 연율 지표. (statistics._sharpe 기본 periods=4 함정 회피)"""
    import numpy as np
    r = monthly_returns.dropna()
    if len(r) == 0:
        return {"cagr": 0.0, "ann_sharpe": 0.0, "mdd": 0.0}
    years = len(r) / 12
    cagr = float((1 + r).prod() ** (1 / years) - 1) if years > 0 else 0.0
    ann_sharpe = float(r.mean() / r.std() * np.sqrt(12)) if r.std() > 0 else 0.0
    curve = (1 + r).cumprod()
    mdd = float((curve / curve.cummax() - 1).min())   # 음수
    return {"cagr": cagr, "ann_sharpe": ann_sharpe, "mdd": mdd}
```

- [ ] **Step 2: 비교 스크립트 작성 (net-of-cost, PIT)**

```python
# scripts/backtest_baseline.py
"""게이트1: regime baseline vs 벤치마크 4종 (net-of-cost 10bps, PIT). 설계 §9·#20·#22."""
from datetime import date
from tradingagents.backtest.bucket_proxies import fetch_bucket_proxy_returns
from tradingagents.backtest.baseline_backtest import (
    run_strategy_backtest, resolve_historical_quadrant, summarize)
from tradingagents.backtest.benchmarks import equal_weight, sixty_forty, risk_parity_weights
from tradingagents.backtest.statistics import paired_t_vs_benchmark
from tradingagents.backtest.data import fetch_macro_quarterly_extended   # ← 경로 fix(must_fix): dataflows 아님
from tradingagents.skills.portfolio.scenario_anchor import QUADRANT_BASELINE
from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS

COST_BPS = 10   # 버킷 편도 거래비용 (결정 #22)

def main(start=date(2008, 1, 1), end=date(2025, 12, 31)):
    ret = fetch_bucket_proxy_returns(start, end)               # 공통구간으로 절단됨(NaN drop)
    macro_q = fetch_macro_quarterly_extended(start, end)       # PIT: as_of_date 내부 처리 (Task 1.4 Step 4a)
    strategies = {
        "regime_baseline": lambda dt: QUADRANT_BASELINE[resolve_historical_quadrant(dt, macro_q)],
        "single_baseline": lambda dt: QUADRANT_BASELINE["growth_disinflation"],
        "sixty_forty":     lambda dt: sixty_forty(),
        "equal_weight":    lambda dt: equal_weight(list(ret.columns)),
        "risk_parity":     lambda dt: (risk_parity_weights(ret.loc[:dt].tail(36))
                                       if len(ret.loc[:dt]) >= 36 else equal_weight(list(ret.columns))),
    }
    perfs = {}
    for name, fn in strategies.items():
        p = run_strategy_backtest(ret, fn)
        turn = p["turnover"].reindex(p["monthly_returns"].index).fillna(0.0)
        net = p["monthly_returns"] - turn * COST_BPS / 1e4     # net-of-cost
        perfs[name] = {"net": net, **summarize(net), "avg_turnover": float(p["turnover"].mean())}
        print(name, {k: round(v, 4) for k, v in perfs[name].items() if k != "net"})

    # 게이트1 판정 (결정 #20): Sharpe ≥3/4 초과 AND (p<0.10 또는 d>0.2) AND MDD 열위 아님
    base = perfs["regime_baseline"]
    benches = ["single_baseline", "sixty_forty", "equal_weight", "risk_parity"]
    n_beat = sum(base["ann_sharpe"] > perfs[b]["ann_sharpe"] for b in benches)
    stats = {b: paired_t_vs_benchmark(base["net"].values, perfs[b]["net"].values) for b in benches}
    # paired_t_vs_benchmark 반환에서 p_value/cohens_d 키 추출 (statistics.py 시그니처 Step 3에서 확인)
    sig_ok = any((s.get("p_value", 1) < 0.10 or abs(s.get("cohens_d", 0)) > 0.2) for s in stats.values())
    mdd_ok = all(base["mdd"] >= perfs[b]["mdd"] for b in benches)   # mdd 음수 → 큰 값이 우위
    passed = n_beat >= 3 and sig_ok and mdd_ok
    print(f"\n게이트1: Sharpe {n_beat}/4 초과, 유의성={sig_ok}, MDD열위아님={mdd_ok} → {'PASS' if passed else 'FAIL → regime 골격 재고'}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 실행 + 게이트 1 정량 판정**

Run: `python scripts/backtest_baseline.py`
먼저 `paired_t_vs_benchmark`의 실제 반환 키(`p_value`/`cohens_d` 명칭)를 `statistics.py`에서 확인해 스크립트와 맞출 것.
**게이트 1 (결정 #20)**: `Sharpe ≥3/4 초과 AND (p<0.10 또는 |d|>0.2) AND MDD 열위 아님`
- ✅ PASS → Phase 2 진행
- ❌ FAIL → **STOP**. regime 골격/baseline 재고 (BL 구현 무의미). 사용자에게 결과 보고 후 방향 재논의.

- [ ] **Step 4: 결과 커밋** — backtest 결과·게이트 판정을 `docs/superpowers/specs/`에 리포트로 첨부, 커밋.

---

# Phase 2 — BL 결합 (게이트 2) — *게이트 1 통과 후*

prior(Π) + 고정 view로 BL을 조립하고, 현행 비중과의 차이를 측정한다. **LLM view 없이** 고정 결정론 view로.

## Task 2.1: Π reverse-optimization

**Files:** Create `tradingagents/skills/portfolio/bl_engine.py`; Test `tests/unit/skills/portfolio/test_bl_engine.py`

- [ ] **Step 1: 실패 테스트** — `implied_prior_returns(cov, w_baseline, delta=2.5)` 가 `δΣw` 반환

```python
import pandas as pd, numpy as np
from tradingagents.skills.portfolio.bl_engine import implied_prior_returns

def test_pi_equals_delta_sigma_w():
    cov = pd.DataFrame(np.eye(2)*0.04, index=["b1_kr_equity","a1_cash"], columns=["b1_kr_equity","a1_cash"])
    w = {"b1_kr_equity":0.6, "a1_cash":0.4}
    pi = implied_prior_returns(cov, w, delta=2.5)
    assert abs(pi["b1_kr_equity"] - 2.5*0.04*0.6) < 1e-9
```

- [ ] **Step 2: 실패 확인 → Step 3: 구현**

```python
# tradingagents/skills/portfolio/bl_engine.py (일부)
import pandas as pd
def implied_prior_returns(cov: pd.DataFrame, w_baseline: dict[str, float], *, delta: float = 2.5) -> pd.Series:
    w = pd.Series(w_baseline).reindex(cov.columns).fillna(0.0)
    return delta * cov.dot(w)
```

- [ ] **Step 4: 통과 + 커밋**

## Task 2.2: BL 결합 + MV 최적화 (고정 view)

- [ ] **Step 1: 실패 테스트** — `bl_optimize(cov_annual, w_baseline, views, confidences, bounds, delta, tau)`. view 없으면 baseline을 **정확 복원**(max_quadratic_utility), sum=1.

```python
def test_bl_no_view_recovers_baseline():
    import numpy as np, pandas as pd
    from tradingagents.skills.portfolio.bl_engine import bl_optimize
    cols = ["b1_kr_equity", "a1_cash"]
    cov = pd.DataFrame(np.array([[0.04, 0.0], [0.0, 0.0004]]), index=cols, columns=cols)  # 연율 Σ
    base = {"b1_kr_equity": 0.6, "a1_cash": 0.4}
    bounds = {"b1_kr_equity": (0.0, 1.0), "a1_cash": (0.0, 1.0)}
    w = bl_optimize(cov, base, views={}, confidences={}, bounds=bounds)
    assert abs(sum(w.values()) - 1.0) < 1e-6
    assert abs(w["b1_kr_equity"] - 0.6) < 0.02   # max_quadratic_utility → baseline 복원 (max_sharpe면 실패)

def test_bl_respects_bounds():
    import numpy as np, pandas as pd
    from tradingagents.skills.portfolio.bl_engine import bl_optimize
    cols = ["b3_global_tech", "a1_cash"]
    cov = pd.DataFrame(np.array([[0.05, 0.0], [0.0, 0.0004]]), index=cols, columns=cols)
    base = {"b3_global_tech": 0.14, "a1_cash": 0.08}
    bounds = {"b3_global_tech": (0.08, 0.19), "a1_cash": (0.0, 0.5)}   # b3 상한 0.19
    w = bl_optimize(cov, base, views={"b3_global_tech": 0.04}, confidences={"b3_global_tech": 0.5}, bounds=bounds)
    assert w["b3_global_tech"] <= 0.19 + 1e-6   # 강한 view 와도 상한 준수 (옵티마이저 제약)
```

- [ ] **Step 2: 실패 확인 → Step 3: 구현** (pypfopt)

```python
# bl_engine.py (이어서)
from pypfopt import BlackLittermanModel, EfficientFrontier

def bl_optimize(cov_annual, w_baseline, views: dict[str, float], confidences: dict[str, float],
                bounds: dict[str, tuple[float, float]], *, delta: float = 2.5, tau: float = 0.05) -> dict[str, float]:
    """cov_annual: 연율 Σ(=Σ_daily×252, 결정 #17). views: {bucket: prior 대비 연간 기대수익 delta}.
    confidences: {bucket: 0..1}. bounds: {bucket: (hard_min, hard_max)} — 옵티마이저에 직접 부과(#19).
    view 없으면 baseline 정확 복원(max_quadratic_utility, #18). 실패 시 baseline fallback(#16)."""
    pi = implied_prior_returns(cov_annual, w_baseline, delta=delta)
    try:
        if not views:
            mu = pi
        else:
            absviews = {b: float(pi[b]) + v for b, v in views.items()}   # prior + 연간 view delta (Q/P 자동 도출)
            conf = [confidences.get(b, 0.5) for b in views]
            bl = BlackLittermanModel(cov_annual, pi=pi, absolute_views=absviews,
                                     omega="idzorek", view_confidences=conf,   # Idzorek Ω 신규 배선
                                     tau=tau, risk_aversion=delta)
            mu = bl.bl_returns()
        wb = [bounds.get(b, (0.0, 1.0)) for b in cov_annual.columns]   # per-bucket bounds, 컬럼 순서
        ef = EfficientFrontier(mu, cov_annual, weight_bounds=wb)
        ef.max_quadratic_utility(risk_aversion=delta)   # max_sharpe 아님 — baseline 복원 (#18)
        return dict(ef.clean_weights())
    except Exception:
        return dict(w_baseline)
```

- [ ] **Step 4: 통과 + 커밋**

## Task 2.3: trader_allocator BL 분기 배선

**Files:** Modify `tradingagents/agents/trader/trader_allocator.py`; Test `tests/unit/agents/trader/test_trader_allocator.py`

- [ ] **Step 1: 실패 테스트** — allocator가 BL 경로로 14버킷 비중 산출, `weight_vector.method == OptimizationMethod.BLACK_LITTERMAN` **AND `out["method_choice"]["method"] == "black_litterman"`**(둘 다, must_fix), attribution `step_a`에 `bl` trace(quadrant·pi·views), 그리고 `rd`에 risk_tilt가 없어도 동작(AttributeError 없음).
- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현** — Step A 코어 교체:
  - `_resolve_quadrant`로 baseline 선택(유지), `baseline = QUADRANT_BASELINE[quadrant]`
  - `hard_bands = {b: hard_band(quadrant, b, baseline[b]) for b in baseline}` → `bounds = hard_bands` (dict[bucket,(lo,hi)])
  - 보유 후보 종목 returns(`fetch_returns_matrix`, ~3년) → `bucket_returns_from_holdings(etf_ret, members, aum)` → `bucket_covariance(...)` → **`cov_annual = cov * 252`**(연율화, #17)
  - fx/credit 결정론 view 구성 `_macro_views(state) -> (views, confidences)`: `mr.fx.regime`/`mr.financial_conditions.regime` 읽어 `usd_risk_off→{a4_safe_fx:+0.03, b1_kr_equity:-0.03}`, `credit tight→{b9:-0.02, a3:+0.02}` 등(연간 delta), confidence 0.8
  - `bucket_weights = bl_optimize(cov_annual, baseline, views, confidences, bounds)` → 14버킷 비중 (이미 hard_band 내·sum=1)
  - ⚠️ **`project_to_band` 호출하지 않음** — weight_bounds가 hard_band를 옵티마이저 단계에서 이미 부과(#19). (사후 클램프 제거 → must_fix 시그니처 오용도 함께 해소)
  - 이후 candidate_selector/within_bucket/repair(유지)
  - ⚠️ **`vol_haircut`·`apply_vol_haircut` 호출 제거**(#7)
  - attribution `step_a` = `{quadrant, pi: dict(pi), views, confidences, bucket_weights}`
- [ ] **Step 3b: risk_tilt 잔존 참조 제거** (Task 4.2 schema 제거의 선결조건, must_fix) — `trader_allocator.py`에서 `risk_tilt = getattr(rd, "risk_tilt", ...)`(현 line~176) 및 그 사용처(prompt·attribution·`bucket_target.rationale`, 현 line~184/270/306) 전부 제거. `grep -n "risk_tilt" tradingagents/agents/trader/trader_allocator.py` → 0건 확인.
- [ ] **Step 3c: method_choice 갱신** (must_fix) — node 반환의 `"method_choice": {"method": "aum_weighted"}`(현 line~319)를 `{"method": "black_litterman"}`로. `weight_vector.method`(OptimizationMethod.BLACK_LITTERMAN)와 일치시켜 portfolio.json/philosophy 리포트 불일치 제거.
- [ ] **Step 4: 통과 확인** — `pytest tests/unit/agents/trader/ -v`
- [ ] **Step 5: 커밋**

## Task 2.4: 게이트 2 — BL vs 현행 ROI 측정

- [ ] **Step 1: 비교 스크립트** — 같은 입력(과거 N개 as_of_date)으로 현행 더하기 vs BL(고정 view) 14버킷 비중 차이 분포 측정. `scripts/compare_bl_vs_current.py`.
- [ ] **Step 2: 실행 + 게이트 2 판정** — 비중 차이 L1이 hard band(±6~10%p) 안 노이즈 수준인가?
  - ✅ 유의미 → Phase 3 진행
  - ❌ 노이즈 → **STOP**. BL 과잉설계. 사용자 보고 후 재논의.
- [ ] **Step 3: 커밋**

---

# Phase 3 — LLM view (신호집계 + view agent) — *게이트 2 통과 후*

## Task 3.1: 신호 집계 레이어

**Files:** Create `tradingagents/skills/portfolio/signal_aggregation.py`; Test 동일.

- [ ] **Step 1: 실패 테스트** — Stage1 지표 dict → 14버킷×카테고리(밸류/모멘텀/펀더/포지셔닝) z 테이블. double-counting 필터(regime/상관/변동성/fx·credit 제외), 시계열 percentile 기반, 카테고리 내 상관 높은 지표 묶기.
- [ ] **Step 2~4:** 구현(카테고리별 동일가중 z 합성, design §5 N2 / Part 논의) + 통과 + 커밋.
- [ ] **세부 카테고리·지표 매핑**은 게이트 통과 후 Stage1 산출물 실측으로 확정(설계 §5 표 + 직전 논의 우선순위: 뉴스·포지셔닝 1순위, 밸류·carry 2순위, fold-in 펀더 3순위).

## Task 3.2: BucketTilt → BL view 스키마 (M2)

**Files:** Modify `schemas/portfolio.py`.

- [ ] **Step 1: 실패 테스트** — 신규 `BucketView(direction, magnitude, confidence)` 또는 `BucketTilt` 확장. 버킷별 벡터.
- [ ] **Step 2~4:** 구현 + 통과 + 커밋. magnitude→Q 매핑(strong/moderate/weak = ±0.04/0.02/0.01, design §7).

## Task 3.3: LLM view agent (N3) + Idzorek 연결

**Files:** Modify `trader_allocator.py` (`_step_a_prompt`, view 생성).

- [ ] **Step 1: 실패 테스트** — LLM(structured `BucketView`) 출력 → `weight tilt → Q` 변환 → `bl_optimize`에 LLM view + fx/credit view 합산 주입.
- [ ] **Step 2~4:** 구현 + 통과 + 커밋.
  - 프롬프트 입력 = 14버킷 집계 테이블(Task 3.1) + 정성 컨텍스트(뉴스/포지셔닝). thesis_md telephone game 제거.
  - confidence 전 view 동일 고정(design §3-14).

## Task 3.4: view ON/OFF 검증

- [ ] view ON vs OFF로 거래비용 후 성과 차이 측정(forward_perf). view가 가치 더하는지. 라벨/confidence 분포 모니터링(死신호 감시).

---

# Phase 4 — 정리 (폐기 + 강등 + 리밸런싱)

## Task 4.1: scenario modifier · vol_haircut 폐기

**Files:** Modify `scenario_anchor.py`; Delete `vol_haircut.py`; Modify imports.

- [ ] **Step 1: 잔여 참조 검색** — `grep -rn "apply_scenario_modifier\|apply_macro_modifiers\|SCENARIO_MODIFIER\|RISK_TILT_AMOUNT\|vol_haircut\|apply_vol_haircut" tradingagents --include="*.py" | grep -v test`
- [ ] **Step 2:** 호출처 0 확인 후 `scenario_anchor.py`에서 modifier 블록 삭제(hard_band/effective_band/project_to_band/QUADRANT_BASELINE 유지), `vol_haircut.py` 삭제, import 정리.
- [ ] **Step 3:** `pytest tests/unit -q` 회귀 + 커밋.

## Task 4.2: ResearchThesis risk_tilt 강등 (M3) + bull/bear (M4)

**Files:** Modify `schemas/research.py`, `research_cluster.py`.

- [ ] `risk_tilt`/`dominant_scenario`/`conviction` 제거(또는 리포팅 전용). bull/bear/thesis는 정성 보조+리포팅으로, 비중 critical path에서 분리. 테스트 갱신 + 커밋.

## Task 4.3: 리밸런싱 통합 (turnover_floor 충돌)

**Files:** Modify `rebalance/` (engine/triggers), N5 입력 변화 트리거.

- [ ] BL target = monthly 재계산, daily drift 감시(target 고정). `turnover_floor_monthly` 미달분을 고확신 view 자산에 우선 배분(design §10). 입력 변화 트리거(N5) 추가. 테스트 + 커밋.

## Task 4.4: 전체 회귀

- [ ] `pytest tests/unit -q` 전체 통과. 잔여 dominant_scenario/conviction/risk_tilt 참조 0(legacy 제외). 커밋.

---

## Self-Review (작성자 점검)

**1. Spec coverage:** §3 결정 16개 → Phase 1-4 매핑 ✓ (게이트 §9 → Task 1.5·2.4 ✓, Σ §5-N1 → Task 1.2·2.3 ✓, BL §6 → Task 2.2 ✓, view §7 → Task 3.2·3.3 ✓, 폐기 → Task 4.1 ✓, 리밸런싱 §10 → Task 4.3 ✓).

**2. Placeholder scan:** Phase 1·2는 완전 코드. Phase 3·4는 게이트 통과 후 세부 확장 명시(placeholder 아닌 조건부) — 게이트 미통과 시 불필요하므로 의도적. 실행 전 Phase 3 진입 시 Task 3.1 카테고리 매핑을 Stage1 실측으로 확정.

**3. Type consistency:** `bl_optimize(cov, w_baseline, views, confidences, delta, tau)` — Task 2.2 정의 = 2.3·3.3 호출 일치 ✓. `implied_prior_returns` 2.1=2.2 ✓. `bucket_returns_from_holdings`/`bucket_covariance` 1.2 정의 = 2.3 호출 ✓. `fetch_macro_quarterly_extended` import 경로 = `tradingagents/backtest/data.py`(조사 확인) — Task 1.5 실행 시 확정.

**adversarial 검토 반영(2026-06-09, wx3a5j452):** must_fix 11개 전부 반영 — import 경로(Task 1.5), a1_cash duration·fillna(0) 위조(Task 1.1), Q/P→absolute_views 통일(spec §6·Task 2.2), force_method/Idzorek 표현 정정(spec §5·§6), project_to_band 시그니처·사후클램프 제거(Task 2.3), risk_tilt 잔존 제거 step(Task 2.3 Step 3b), method_choice 갱신(Step 3c), _sharpe periods=12·summarize 신규(Task 1.5). 확정 결정 6개(#17–22) 반영 — 연율 Σ·max_quadratic_utility·weight_bounds·게이트 정량임계·PIT·net-of-cost.

**보류(구현 시 사용자 확정):** ① proxy 정비(§12.1: A 선결교정 권장 / B / C) — Task 1.1 Step 5 ② regime 분류기(§12.2: 결정론+한계명시 권장) — Task 1.4 Step 4b ③ Task 3.1 카테고리·지표 매핑은 게이트 통과 후 Stage1 실측으로 확정.

**실행 중 확인 필요:** `paired_t_vs_benchmark` 반환 키(`p_value`/`cohens_d`)는 Task 1.5 Step 3에서 `statistics.py` 실측 확인 후 스크립트와 정합.
