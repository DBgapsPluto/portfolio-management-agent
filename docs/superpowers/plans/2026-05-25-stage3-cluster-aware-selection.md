# Stage 3 Cluster-aware ETF Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stage 3 candidate selection을 cluster-aware로 고도화 — correlation cluster로 노출 그룹을 나눠 그룹 *간*은 alpha(어느 sector), 그룹 *내*는 implementation-quality(대체재 중 최선 vehicle)로 선택.

**Architecture:** `factor_scorer.py`에 (1) 강화된 alpha 점수(qual=sortino/calmar/maxDD 흡수, mom=trend_strength/accel 흡수, + timing overlay), (2) implementation 점수(Phase1=AUM, Phase2=ADV/괴리율/추적오차), (3) cluster-aware 선택기를 추가. `candidate_selector.py`가 technical 패널을 thread하고 cluster-aware 선택기를 호출. floor 1조→~500억 + 유동성은 impl_score로. 신규 입력 미제공 시 현행과 수학적으로 동일(backward-compat).

**Tech Stack:** Python 3.12, pydantic v2, numpy, pandas, pytest, pykrx(Phase2, Linux), pypfopt(불변).

**Spec:** `docs/superpowers/specs/2026-05-25-stage3-cluster-aware-selection-design.md`

**Branch:** `feat/stage3-cluster-aware-selection` (spec commit `c8d987b`).

**환경 제약:** 현 Windows 환경 = 단위/property/synthetic 테스트(합성 데이터)까지. 실제 파이프라인 run + economic backtest = pykrx 필요 → **Linux(친구 환경)**. Phase 2 + acceptance gate는 Linux에서 실행.

---

## File Structure

### Modify (production)
- `tradingagents/skills/portfolio/factor_scorer.py` — 신규: `_zscore_dict` 재사용, `compute_impl_score`, `_timing_overlay`, `select_cluster_aware`; 강화: `score_candidates`(optional 패널 인자). `select_diverse`는 fallback으로 유지.
- `tradingagents/skills/portfolio/candidate_selector.py` — floor 상수, eligibility 필터 단일 helper, `select_etf_candidates`/`_rank_by_factors`가 패널·clusters thread + cluster-aware 선택 호출.
- `tradingagents/agents/allocator/portfolio_allocator.py` — `technical_report`의 `risk_adjusted`/`trend_quantification`/`extended_indicators`/`individual_etf_states`/`correlation_clusters`를 select_etf_candidates로 thread.

### Modify (Phase 2, Linux)
- `tradingagents/dataflows/pykrx_data.py` — `fetch_etf_tracking_error`, `fetch_etf_price_deviation`.
- `scripts/enrich_universe_impl_quality.py` (신규) — universe.json에 `adv_krw`/`tracking_error`/`deviation` enrich.
- `scripts/backtest_candidate_selection.py` — "현행 vs 신규" 비교 모드.

### Test
- `tests/unit/skills/test_portfolio_factor_scorer.py` — 확장(family/timing/impl/cluster-aware + non-regression).
- `tests/unit/skills/test_portfolio_candidate.py` — 확장(floor/dedup/thread).
- `tests/unit/dataflows/test_pykrx_etf_impl.py` (신규, Phase2) — mocked pykrx.

### Constants (factor_scorer.py 상단)
```python
TIMING_DELTA: float = 0.1      # 신호당 가감점 (backtest 튜닝 대상)
TIMING_CAP: float = 0.3        # timing overlay bound
```

---

## Phase 1 — cluster-aware 선택 (현 환경 완결, 합성 데이터 검증)

## Task 1: `_timing_overlay` — extended_indicators 기반 bounded 가감점

**Files:**
- Modify: `tradingagents/skills/portfolio/factor_scorer.py`
- Test: `tests/unit/skills/test_portfolio_factor_scorer.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/unit/skills/test_portfolio_factor_scorer.py` 에 추가:
```python
from tradingagents.schemas.technical import (
    ExtendedIndicatorPanel, RiskAdjustedMetrics, TrendState,
)
from tradingagents.skills.portfolio.factor_scorer import (
    _timing_overlay, TIMING_CAP,
)


def _ext(ticker="A000001", *, rsi_div="none", macd_div="none",
         bb=0.5, mfi=50.0, stoch=50.0):
    return ExtendedIndicatorPanel(
        ticker=ticker, bb_percent_b=bb, bb_bandwidth=0.05, adx=25.0,
        stoch_k=stoch, stoch_d=stoch, obv=0.0, obv_slope_20d=0.0, mfi=mfi,
        rsi_divergence=rsi_div, macd_divergence=macd_div,
        weekly_ma50=100.0, weekly_rsi=50.0, weekly_trend="neutral",
    )


def test_timing_penalizes_bearish_divergence():
    base = _timing_overlay("A000001", _ext(), None, None)
    bear = _timing_overlay("A000001", _ext(rsi_div="bearish"), None, None)
    assert bear < base


def test_timing_penalizes_overbought():
    ob = _timing_overlay("A000001", _ext(bb=1.2, mfi=85.0), None, None)
    assert ob < 0


def test_timing_bonus_mean_reversion():
    ra = {"A000001": RiskAdjustedMetrics(
        ticker="A000001", sortino_60d=0.0, max_drawdown_12m=-0.1,
        calmar_12m=0.0, skewness_60d=0.0, excess_kurtosis_60d=0.0,
        return_z_30d=-2.0, is_mean_reversion_candidate=True)}
    mr = _timing_overlay("A000001", _ext(), None, ra)
    assert mr > 0


def test_timing_penalizes_breakdown_state():
    bd = _timing_overlay("A000001", _ext(), {"A000001": TrendState.BREAKDOWN}, None)
    assert bd < 0


def test_timing_is_bounded():
    worst = _timing_overlay(
        "A000001", _ext(rsi_div="bearish", macd_div="bearish", bb=1.5, mfi=95, stoch=95),
        {"A000001": TrendState.BREAKDOWN}, None)
    assert worst >= -TIMING_CAP - 1e-9


def test_timing_zero_when_no_panels():
    assert _timing_overlay("A000001", None, None, None) == 0.0
```

- [ ] **Step 2: 테스트 실행 → fail**

Run: `uv run pytest tests/unit/skills/test_portfolio_factor_scorer.py -k timing -v`
Expected: ImportError (`_timing_overlay` 없음).

- [ ] **Step 3: 구현**

`factor_scorer.py` 상단 상수 + 함수 추가:
```python
TIMING_DELTA: float = 0.1
TIMING_CAP: float = 0.3


def _timing_overlay(
    ticker: str,
    extended: "ExtendedIndicatorPanel | None",
    etf_states: "dict[str, object] | None",
    risk_adjusted: "dict[str, object] | None",
) -> float:
    """Bounded soft 가감점 (extended_indicators + trend_state + mean-reversion).

    누락 데이터는 0 기여. 반환 ∈ [-TIMING_CAP, +TIMING_CAP].
    """
    d = TIMING_DELTA
    score = 0.0
    if extended is not None:
        if extended.rsi_divergence == "bearish":
            score -= d
        elif extended.rsi_divergence == "bullish":
            score += d
        if extended.macd_divergence == "bearish":
            score -= d
        elif extended.macd_divergence == "bullish":
            score += d
        if extended.bb_percent_b > 1.0 or extended.mfi > 80.0 or extended.stoch_k > 80.0:
            score -= d
    if etf_states is not None:
        st = etf_states.get(ticker)
        st_val = getattr(st, "value", st)
        if st_val in ("breakdown", "downtrend"):
            score -= d
    if risk_adjusted is not None:
        ra = risk_adjusted.get(ticker)
        if ra is not None and getattr(ra, "is_mean_reversion_candidate", False):
            score += d
    return max(-TIMING_CAP, min(TIMING_CAP, score))
```
(import: 파일 상단에 `from tradingagents.schemas.technical import ExtendedIndicatorPanel` 등은 type-only이므로 문자열 annotation 사용 — 런타임 import 불필요.)

- [ ] **Step 4: 테스트 → pass**

Run: `uv run pytest tests/unit/skills/test_portfolio_factor_scorer.py -k timing -v`
Expected: 6 pass.

- [ ] **Step 5: commit**

```bash
git add tradingagents/skills/portfolio/factor_scorer.py tests/unit/skills/test_portfolio_factor_scorer.py
git commit -m "feat(stage3): timing overlay for selection (extended_indicators) [Task1]"
```

---

## Task 2: alpha family 강화 — `score_candidates`에 risk_adjusted/trend_quant 흡수

**Files:**
- Modify: `tradingagents/skills/portfolio/factor_scorer.py` (`score_candidates`)
- Test: `tests/unit/skills/test_portfolio_factor_scorer.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from tradingagents.schemas.technical import TrendQuantification
from tradingagents.skills.portfolio.factor_scorer import (
    FactorPanel, score_candidates,
)


def _panel(mom=0.0, vol=0.2, sharpe=0.0, aum=1e12):
    return FactorPanel(
        skip1m_mom_3m=mom, skip1m_mom_6m=mom, skip1m_mom_12m=mom,
        realized_vol_60d=vol, sharpe_60d=sharpe, log_aum=__import__("math").log(aum))


def _ra(t, sortino=0.0, calmar=0.0, maxdd=-0.1):
    from tradingagents.schemas.technical import RiskAdjustedMetrics
    return RiskAdjustedMetrics(
        ticker=t, sortino_60d=sortino, max_drawdown_12m=maxdd, calmar_12m=calmar,
        skewness_60d=0.0, excess_kurtosis_60d=0.0, return_z_30d=0.0,
        is_mean_reversion_candidate=False)


def test_qual_family_absorbs_sortino():
    # 동일 sharpe, 다른 sortino → 높은 sortino가 높은 점수 (qual family 강화 확인)
    panels = {"A": _panel(sharpe=0.5), "B": _panel(sharpe=0.5)}
    ra = {"A": _ra("A", sortino=2.0, calmar=2.0), "B": _ra("B", sortino=-2.0, calmar=-2.0)}
    scores = score_candidates(panels, "recession_disinflation", 1.0, risk_adjusted=ra)
    assert scores["A"] > scores["B"]


def test_mom_family_absorbs_trend_strength():
    panels = {"A": _panel(mom=0.05), "B": _panel(mom=0.05)}
    tq = {
        "A": TrendQuantification(ticker="A", trend_strength_score=0.9, time_in_state_days=10,
             distance_ma200_pct=5, distance_ma50_pct=2, momentum_3m_abs=0.05, momentum_3m_rel=0.01,
             momentum_12m_abs=0.1, momentum_12m_rel=0.02, momentum_acceleration=0.3, benchmark="KOSPI200"),
        "B": TrendQuantification(ticker="B", trend_strength_score=-0.9, time_in_state_days=10,
             distance_ma200_pct=-5, distance_ma50_pct=-2, momentum_3m_abs=0.05, momentum_3m_rel=0.01,
             momentum_12m_abs=0.1, momentum_12m_rel=0.02, momentum_acceleration=-0.3, benchmark="KOSPI200"),
    }
    scores = score_candidates(panels, "growth_disinflation", 1.0, trend_quant=tq)
    assert scores["A"] > scores["B"]
```

- [ ] **Step 2: 테스트 실행 → fail**

Run: `uv run pytest tests/unit/skills/test_portfolio_factor_scorer.py -k "qual_family or mom_family" -v`
Expected: FAIL (`score_candidates` TypeError: unexpected kwarg `risk_adjusted`).

- [ ] **Step 3: 구현 — `score_candidates` 시그니처/내부 강화**

`score_candidates`를 아래로 교체 (기존 4-family 로직 유지 + sub-composite):
```python
def score_candidates(
    panels: dict[str, FactorPanel],
    regime_quadrant: str | None,
    regime_confidence: float,
    *,
    risk_adjusted: dict[str, object] | None = None,
    trend_quant: dict[str, object] | None = None,
    extended: dict[str, object] | None = None,
    etf_states: dict[str, object] | None = None,
) -> dict[str, float]:
    """Composite alpha score. 신규 패널 미제공 시 현행 4-family와 동일."""
    if not panels:
        return {}

    # momentum sub-composite: skip1m mean (+ trend_strength + acceleration if 제공)
    mom_values: dict[str, float | None] = {}
    for t, p in panels.items():
        windows = [p.skip1m_mom_3m, p.skip1m_mom_6m, p.skip1m_mom_12m]
        valid = [w for w in windows if w is not None]
        mom_values[t] = float(np.mean(valid)) if valid else None
    z_mom_skip = _zscore(mom_values)

    z_mom_parts = [z_mom_skip]
    if trend_quant is not None:
        z_mom_parts.append(_zscore({t: getattr(trend_quant.get(t), "trend_strength_score", None)
                                    for t in panels}))
        z_mom_parts.append(_zscore({t: getattr(trend_quant.get(t), "momentum_acceleration", None)
                                    for t in panels}))
    z_mom = {t: float(np.mean([zp[t] for zp in z_mom_parts])) for t in panels}

    z_vol = _zscore({t: p.realized_vol_60d for t, p in panels.items()})

    # quality sub-composite: sharpe (+ sortino + calmar + (-maxdd) if 제공)
    z_qual_parts = [_zscore({t: p.sharpe_60d for t, p in panels.items()})]
    if risk_adjusted is not None:
        z_qual_parts.append(_zscore({t: getattr(risk_adjusted.get(t), "sortino_60d", None)
                                     for t in panels}))
        z_qual_parts.append(_zscore({t: getattr(risk_adjusted.get(t), "calmar_12m", None)
                                     for t in panels}))
        z_qual_parts.append(_zscore({t: (-getattr(risk_adjusted.get(t), "max_drawdown_12m", 0.0)
                                         if risk_adjusted.get(t) is not None else None)
                                     for t in panels}))
    z_qual = {t: float(np.mean([zp[t] for zp in z_qual_parts])) for t in panels}

    z_size = _zscore({t: p.log_aum for t, p in panels.items()})

    weights = blend_regime_weights(regime_quadrant, regime_confidence)
    scores: dict[str, float] = {}
    for t in panels:
        composite = (
            weights["mom"] * z_mom[t]
            + weights["lowvol"] * (-z_vol[t])
            + weights["qual"] * z_qual[t]
            + weights["size"] * z_size[t]
        )
        ext_t = extended.get(t) if extended is not None else None
        scores[t] = composite + _timing_overlay(t, ext_t, etf_states, risk_adjusted)
    return scores
```

- [ ] **Step 4: 테스트 → pass**

Run: `uv run pytest tests/unit/skills/test_portfolio_factor_scorer.py -k "qual_family or mom_family or timing" -v`
Expected: 8 pass.

- [ ] **Step 5: commit**

```bash
git add tradingagents/skills/portfolio/factor_scorer.py tests/unit/skills/test_portfolio_factor_scorer.py
git commit -m "feat(stage3): enrich alpha families (sortino/calmar/maxdd, trend_strength/accel) + timing [Task2]"
```

---

## Task 3: `compute_impl_score` — implementation-quality (Phase1=AUM, extensible)

**Files:**
- Modify: `tradingagents/skills/portfolio/factor_scorer.py`
- Test: `tests/unit/skills/test_portfolio_factor_scorer.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from tradingagents.skills.portfolio.factor_scorer import compute_impl_score


def test_impl_score_prefers_larger_aum_phase1():
    import math
    panels = {"A": _panel(aum=5e12), "B": _panel(aum=5e11)}
    impl = compute_impl_score(panels)
    assert impl["A"] > impl["B"]   # 대체재 중 큰(=더 유동) 쪽 우대


def test_impl_score_adds_adv_when_provided():
    panels = {"A": _panel(aum=1e12), "B": _panel(aum=1e12)}
    impl = compute_impl_score(panels, adv={"A": 1e10, "B": 1e8})
    assert impl["A"] > impl["B"]


def test_impl_score_penalizes_tracking_error():
    panels = {"A": _panel(aum=1e12), "B": _panel(aum=1e12)}
    impl = compute_impl_score(panels, tracking_error={"A": 0.001, "B": 0.02})
    assert impl["A"] > impl["B"]   # 낮은 추적오차 우대
```

- [ ] **Step 2: 테스트 → fail**

Run: `uv run pytest tests/unit/skills/test_portfolio_factor_scorer.py -k impl_score -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

```python
def compute_impl_score(
    panels: dict[str, FactorPanel],
    *,
    adv: dict[str, float] | None = None,           # 평균 거래대금 (KRW) — Phase2
    deviation: dict[str, float] | None = None,     # |괴리율| — Phase2
    tracking_error: dict[str, float] | None = None,  # 추적오차율 — Phase2
) -> dict[str, float]:
    """대체재 중 최선 vehicle 점수. 높을수록 좋음. 미제공 신호는 0 기여.

    Phase1: log_aum (= 큰 ETF = 더 유동/낮은 spread proxy).
    Phase2: + ADV↑, |괴리율|↓, 추적오차↓.
    """
    if not panels:
        return {}
    parts = [_zscore({t: p.log_aum for t, p in panels.items()})]
    if adv is not None:
        parts.append(_zscore({t: adv.get(t) for t in panels}))
    if deviation is not None:
        parts.append(_zscore({t: (-abs(deviation[t]) if deviation.get(t) is not None else None)
                              for t in panels}))
    if tracking_error is not None:
        parts.append(_zscore({t: (-tracking_error[t] if tracking_error.get(t) is not None else None)
                              for t in panels}))
    return {t: float(np.mean([zp[t] for zp in parts])) for t in panels}
```

- [ ] **Step 4: 테스트 → pass**

Run: `uv run pytest tests/unit/skills/test_portfolio_factor_scorer.py -k impl_score -v`
Expected: 3 pass.

- [ ] **Step 5: commit**

```bash
git add tradingagents/skills/portfolio/factor_scorer.py tests/unit/skills/test_portfolio_factor_scorer.py
git commit -m "feat(stage3): compute_impl_score (Phase1 AUM, extensible to ADV/deviation/tracking) [Task3]"
```

---

## Task 4: `select_cluster_aware` — 그룹 간 alpha / 그룹 내 impl

**Files:**
- Modify: `tradingagents/skills/portfolio/factor_scorer.py`
- Test: `tests/unit/skills/test_portfolio_factor_scorer.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from tradingagents.schemas.technical import Cluster
from tradingagents.skills.portfolio.factor_scorer import select_cluster_aware


def test_within_cluster_picks_best_impl_not_alpha():
    # A1,A2 같은 cluster(대체재). A1 alpha 높지만 impl 낮음; A2 alpha 낮지만 impl 높음.
    # 그룹 내 대표는 impl 기준 → A2 선택.
    alpha = {"A1": 2.0, "A2": 0.0, "B": 1.0}
    impl = {"A1": 0.0, "A2": 2.0, "B": 1.0}
    clusters = [Cluster(cluster_id="c1", members=["A1", "A2"],
                        avg_internal_correlation=0.95, category_label="dup")]
    chosen = select_cluster_aware(["A1", "A2", "B"], alpha, impl, clusters, n=2, returns=None)
    assert "A2" in chosen and "A1" not in chosen
    assert "B" in chosen


def test_across_groups_ranked_by_alpha():
    # 두 singleton 그룹 X,Y. n=1 → alpha 높은 X.
    alpha = {"X": 2.0, "Y": 0.5}
    impl = {"X": 0.0, "Y": 5.0}
    chosen = select_cluster_aware(["X", "Y"], alpha, impl, clusters=[], n=1, returns=None)
    assert chosen == ["X"]


def test_pads_when_groups_fewer_than_n():
    # 그룹 1개(대체재 A1,A2), n=2 → 대표 1 + 차순위 패딩으로 2개.
    alpha = {"A1": 2.0, "A2": 1.0}
    impl = {"A1": 2.0, "A2": 0.0}
    clusters = [Cluster(cluster_id="c1", members=["A1", "A2"],
                        avg_internal_correlation=0.95, category_label="dup")]
    chosen = select_cluster_aware(["A1", "A2"], alpha, impl, clusters, n=2, returns=None)
    assert len(chosen) == 2
```

- [ ] **Step 2: 테스트 → fail**

Run: `uv run pytest tests/unit/skills/test_portfolio_factor_scorer.py -k cluster_aware -v`
Expected: ImportError.

- [ ] **Step 3: 구현**

```python
def select_cluster_aware(
    eligible: list[str],
    alpha_scores: dict[str, float],
    impl_scores: dict[str, float],
    clusters: list[object] | None,
    n: int,
    returns: "pd.DataFrame | None",
    correlation_threshold: float = 0.85,
) -> list[str]:
    """그룹 간 alpha 랭킹으로 노출 선택, 그룹 내 impl 랭킹으로 대표 선택.

    clusters로 그룹화(멤버 공유=대체재); 미포함=singleton. clusters가 None/빈
    경우 pairwise-corr 그룹화(select_diverse 의미)로 fallback.
    """
    if n <= 0 or not eligible:
        return []
    elig = [t for t in eligible if t in alpha_scores]

    # 1. 그룹화
    groups: list[list[str]] = []
    if clusters:
        assigned: set[str] = set()
        member_to_cluster: dict[str, str] = {}
        for c in clusters:
            for m in getattr(c, "members", []):
                member_to_cluster.setdefault(m, getattr(c, "cluster_id"))
        by_cluster: dict[str, list[str]] = {}
        for t in elig:
            cid = member_to_cluster.get(t)
            if cid is None:
                groups.append([t])              # singleton
            else:
                by_cluster.setdefault(cid, []).append(t); assigned.add(t)
        groups.extend(by_cluster.values())
    elif returns is not None:
        groups = _corr_groups(elig, returns, correlation_threshold)   # fallback
    else:
        groups = [[t] for t in elig]            # 데이터 없음 → 전부 singleton

    # 2. 각 그룹: 대표 = impl 최고, group alpha = 대표(=멤버) 중 alpha 최고
    group_repr: list[tuple[float, str, list[str]]] = []
    for g in groups:
        rep = max(g, key=lambda t: impl_scores.get(t, 0.0))
        g_alpha = max(alpha_scores.get(t, 0.0) for t in g)
        group_repr.append((g_alpha, rep, g))
    group_repr.sort(key=lambda x: x[0], reverse=True)

    # 3. 그룹 간 alpha 순으로 대표 선택
    chosen: list[str] = [rep for _a, rep, _g in group_repr[:n]]

    # 4. 패딩: 그룹 수 < n이면 남은 ticker(그룹 차순위 포함)를 alpha 순
    if len(chosen) < n:
        remaining = [t for t in elig if t not in chosen]
        remaining.sort(key=lambda t: alpha_scores.get(t, 0.0), reverse=True)
        for t in remaining:
            chosen.append(t)
            if len(chosen) >= n:
                break
    return chosen[:n]


def _corr_groups(elig, returns, threshold) -> list[list[str]]:
    """fallback 그룹화: greedy — corr≥threshold면 같은 그룹."""
    groups: list[list[str]] = []
    for t in elig:
        placed = False
        for g in groups:
            head = g[0]
            if t in returns.columns and head in returns.columns:
                c = returns[t].corr(returns[head])
                if pd.notna(c) and abs(float(c)) >= threshold:
                    g.append(t); placed = True; break
        if not placed:
            groups.append([t])
    return groups
```
(파일 상단에 `import pandas as pd` 이미 있음 확인.)

- [ ] **Step 4: 테스트 → pass**

Run: `uv run pytest tests/unit/skills/test_portfolio_factor_scorer.py -k cluster_aware -v`
Expected: 3 pass.

- [ ] **Step 5: commit**

```bash
git add tradingagents/skills/portfolio/factor_scorer.py tests/unit/skills/test_portfolio_factor_scorer.py
git commit -m "feat(stage3): select_cluster_aware (cross-group alpha, within-group impl) [Task4]"
```

---

## Task 5: candidate_selector — floor 인하 + eligibility 필터 단일화

**Files:**
- Modify: `tradingagents/skills/portfolio/candidate_selector.py`
- Test: `tests/unit/skills/test_portfolio_candidate.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
from datetime import date
from tradingagents.dataflows.universe import ETFEntry, Universe
from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills.portfolio.candidate_selector import (
    DEFAULT_MIN_AUM_KRW, list_eligible_tickers,
)


def test_default_floor_is_500eok():
    assert DEFAULT_MIN_AUM_KRW == 50_000_000_000   # 500억


def test_floor_500eok_admits_midcap():
    u = Universe(version="t", etfs=[
        ETFEntry(ticker="A000001", name="big", aum_krw=6e11, underlying_index="x",
                 bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A000002", name="mid", aum_krw=1e11, underlying_index="x",
                 bucket="위험", category="국내주식_지수"),
    ])
    bt = BucketTarget(kr_equity=1.0, global_equity=0, fx_commodity=0, bond=0,
                      cash_mmf=0, rationale="t")
    out = list_eligible_tickers(u, bt, as_of=date(2025, 1, 2))
    assert set(out["kr_equity"]) == {"A000001", "A000002"}   # 둘 다 ≥500억
```

- [ ] **Step 2: 테스트 → fail**

Run: `uv run pytest tests/unit/skills/test_portfolio_candidate.py -k "floor" -v`
Expected: FAIL (`DEFAULT_MIN_AUM_KRW` 없음 / 기본 floor 1조).

- [ ] **Step 3: 구현**

`candidate_selector.py`:
```python
# 투자성 최소선: ~5 × 100억 운영자본 (포지션 < AUM 5% 가이드). 유동성 soft 선호는 impl_score.
DEFAULT_MIN_AUM_KRW: float = 50_000_000_000   # 500억
```
- `list_eligible_tickers` 와 `select_etf_candidates` 의 `min_aum_krw` 기본값을 `1_000_000_000_000` → `DEFAULT_MIN_AUM_KRW` 로 변경.
- 중복 필터 단일 helper 추출:
```python
def _eligible_for_bucket(universe, cats, min_aum_krw) -> list:
    return [e for e in universe.etfs
            if e.category in cats and e.aum_krw >= _min_aum_for_etf(e, min_aum_krw)]
```
`list_eligible_tickers` 와 `select_etf_candidates` 내부 필터를 이 helper 호출로 교체.

- [ ] **Step 4: 테스트 → pass**

Run: `uv run pytest tests/unit/skills/test_portfolio_candidate.py -k "floor" -v`
Expected: 2 pass.

- [ ] **Step 5: 전체 candidate 테스트 regression**

Run: `uv run pytest tests/unit/skills/test_portfolio_candidate.py -v`
Expected: 기존 테스트 통과 (floor 변경이 기존 fixture 깨면 fixture의 AUM 가정 점검 후 조정).

- [ ] **Step 6: commit**

```bash
git add tradingagents/skills/portfolio/candidate_selector.py tests/unit/skills/test_portfolio_candidate.py
git commit -m "feat(stage3): lower AUM floor 1조→500억 + unify eligibility filter [Task5]"
```

---

## Task 6: select_etf_candidates — 패널·clusters thread + cluster-aware 선택 통합

**Files:**
- Modify: `tradingagents/skills/portfolio/candidate_selector.py`
- Test: `tests/unit/skills/test_portfolio_candidate.py`

- [ ] **Step 1: 실패 테스트 작성 (backward-compat + cluster-aware 경로)**

```python
import numpy as np, pandas as pd
from tradingagents.skills.portfolio.factor_scorer import compute_factor_panel


def _returns(tickers, n=120, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-06-01", periods=n, freq="B")
    return pd.DataFrame({t: rng.normal(0.0005, 0.01, n) for t in tickers}, index=idx)


def test_select_backward_compat_without_panels():
    # clusters/패널 미제공 → 기존 select_diverse 경로와 동일 동작(에러 없이 n개 반환)
    tickers = ["A000001", "A000002", "A000003"]
    u = Universe(version="t", etfs=[
        ETFEntry(ticker=t, name=t, aum_krw=6e11, underlying_index="x",
                 bucket="위험", category="국내주식_지수") for t in tickers])
    bt = BucketTarget(kr_equity=1.0, global_equity=0, fx_commodity=0, bond=0,
                      cash_mmf=0, rationale="t")
    rets = _returns(tickers)
    fp = {t: compute_factor_panel(rets[t], 6e11) for t in tickers}
    from tradingagents.skills.portfolio.candidate_selector import select_etf_candidates
    cs = select_etf_candidates(u, bt, as_of=date(2025, 1, 2), returns=rets,
                               factor_panel=fp, per_bucket_n=2)
    assert len(cs.bucket_to_tickers["kr_equity"]) == 2
```

- [ ] **Step 2: 테스트 → fail 또는 pass(현행)**

Run: `uv run pytest tests/unit/skills/test_portfolio_candidate.py -k backward_compat -v`
Expected: 현행 시그니처면 PASS (backward-compat 보장 확인용). cluster-aware 인자 추가 후에도 유지돼야 함.

- [ ] **Step 3: 구현 — 시그니처 확장 + 분기 교체**

`select_etf_candidates`에 optional 인자 추가:
```python
    risk_adjusted: dict | None = None,
    trend_quant: dict | None = None,
    extended: dict | None = None,
    etf_states: dict | None = None,
    clusters: list | None = None,
```
non-bond 경로(현 `else` 블록, line ~144-156)를 교체:
```python
        else:
            alpha = _rank_scores(
                eligible, returns, aum_lookup, regime_quadrant, regime_confidence,
                precomputed_panel=factor_panel, dominant_scenario=dominant_scenario,
                risk_adjusted=risk_adjusted, trend_quant=trend_quant,
                extended=extended, etf_states=etf_states,
            )
            impl = _impl_scores(eligible, factor_panel)
            chosen = select_cluster_aware(
                [e.ticker for e in eligible], alpha, impl, clusters,
                n=per_bucket_n, returns=returns,
                correlation_threshold=correlation_threshold,
            )
```
`_rank_by_factors`를 점수 dict 반환하는 `_rank_scores`로 확장(또는 신규):
```python
def _rank_scores(eligible, returns, aum_lookup, regime_quadrant, regime_confidence,
                 *, precomputed_panel=None, dominant_scenario=None,
                 risk_adjusted=None, trend_quant=None, extended=None, etf_states=None):
    panels = _build_panels(eligible, returns, aum_lookup, precomputed_panel)
    scores = score_candidates(panels, regime_quadrant, regime_confidence,
                              risk_adjusted=risk_adjusted, trend_quant=trend_quant,
                              extended=extended, etf_states=etf_states)
    if dominant_scenario:
        sub = {e.ticker: e.sub_category for e in eligible}
        for t in scores:
            scores[t] += log_boost(dominant_scenario, sub.get(t))
    return scores


def _impl_scores(eligible, precomputed_panel):
    from tradingagents.skills.portfolio.factor_scorer import compute_impl_score
    panels = {e.ticker: precomputed_panel[e.ticker] for e in eligible
              if precomputed_panel and e.ticker in precomputed_panel}
    return compute_impl_score(panels)
```
(`_build_panels`는 기존 `_rank_by_factors`의 panel 구성 로직 추출. 기존 `_rank_by_factors`는 `sorted(scores)`를 반환하므로 bond quota 경로에서 계속 사용 — 또는 bond 경로도 `_rank_scores`+`sorted`로 통일.)
import 추가: `from tradingagents.skills.portfolio.factor_scorer import score_candidates, select_cluster_aware, compute_impl_score`.

- [ ] **Step 4: 테스트 → pass + 전체 candidate regression**

Run: `uv run pytest tests/unit/skills/test_portfolio_candidate.py -v`
Expected: backward_compat + 기존 테스트 통과.

- [ ] **Step 5: commit**

```bash
git add tradingagents/skills/portfolio/candidate_selector.py tests/unit/skills/test_portfolio_candidate.py
git commit -m "feat(stage3): thread technical panels + integrate cluster-aware select [Task6]"
```

---

## Task 7: portfolio_allocator — technical 패널 thread

**Files:**
- Modify: `tradingagents/agents/allocator/portfolio_allocator.py` (`select_etf_candidates` 호출부, ~line 82-93)
- Test: `tests/unit/skills/test_portfolio_candidate.py` (allocator 통합은 통합테스트가 별도; 여기선 호출 인자 전달 확인)

- [ ] **Step 1: 구현 — 호출부에 패널 전달**

`select_etf_candidates(...)` 호출에 추가:
```python
            risk_adjusted=getattr(tech_report, "risk_adjusted", None),
            trend_quant=getattr(tech_report, "trend_quantification", None),
            extended=getattr(tech_report, "extended_indicators", None),
            etf_states=getattr(tech_report, "individual_etf_states", None),
            clusters=getattr(tech_report, "correlation_clusters", None),
```

- [ ] **Step 2: 테스트 — getattr 안전성(필드 없거나 빈 dict면 None/empty → backward-compat)**

기존 allocator 통합/모킹 테스트가 있으면 실행. 없으면 Task 6의 backward_compat 테스트로 충분(allocator는 thin thread).

Run: `uv run pytest tests/unit/ -k "allocator or candidate" -q 2>&1 | tail -3`
Expected: 0 new failure.

- [ ] **Step 3: commit**

```bash
git add tradingagents/agents/allocator/portfolio_allocator.py
git commit -m "feat(stage3): allocator threads technical panels to selection [Task7]"
```

---

## Task 8: 전체 non-regression + synthetic backtest(mechanism)

**Files:**
- Modify: `scripts/backtest_candidate_selection.py` (synthetic 시나리오 추가)

- [ ] **Step 1: 전체 unit regression**

Run: `uv run pytest tests/unit/ -q 2>&1 | tail -3`
Expected: PR baseline 대비 0 new failure (신규 ~15 test 추가, 기존 통과). 깨지는 기존 테스트는 floor/시그니처 변경 영향 점검 후 fixture 조정.

- [ ] **Step 2: synthetic mechanism 시나리오 추가**

`scripts/backtest_candidate_selection.py`의 `run_synthetic_backtest`에 시나리오 추가:
- 대체재 그룹(고상관 A1,A2) + 큰 AUM A2 → A2가 대표로 선택되는지 (impl 우선).
- 차별 그룹(저상관 sector X high-mom, Y low-mom) → X 선택 (alpha 우선).

- [ ] **Step 3: 실행 (현 환경 가능 — 합성)**

Run: `uv run python scripts/backtest_candidate_selection.py --mode synthetic`
Expected: 신규 시나리오 PASS 출력.

- [ ] **Step 4: commit**

```bash
git add scripts/backtest_candidate_selection.py
git commit -m "test(stage3): synthetic mechanism scenarios for cluster-aware select [Task8]"
```

---

## Phase 2 — implementation-quality 데이터 + economic backtest (Linux, 친구 환경)

## Task 9: pykrx 추적오차·괴리율 fetch (mocked test)

**Files:**
- Modify: `tradingagents/dataflows/pykrx_data.py`
- Test: `tests/unit/dataflows/test_pykrx_etf_impl.py` (신규)

- [ ] **Step 1: 실패 테스트 (mocked pykrx)**

```python
from datetime import date
from unittest.mock import patch
import pandas as pd
from tradingagents.dataflows.pykrx_data import fetch_etf_tracking_error


def test_fetch_tracking_error_mocked():
    fake = pd.DataFrame({"NAV": [1.0], "지수": [1.0], "추적오차율": [0.012]},
                        index=pd.to_datetime(["2025-01-02"]))
    with patch("tradingagents.dataflows.pykrx_data._raw_tracking_error_call",
               return_value=fake):
        out = fetch_etf_tracking_error("A069500", date(2025, 1, 1), date(2025, 1, 3))
    assert "tracking_error" in out.columns
    assert float(out["tracking_error"].iloc[0]) == 0.012
```

- [ ] **Step 2: 테스트 → fail.** Run: `uv run pytest tests/unit/dataflows/test_pykrx_etf_impl.py -v` → ImportError.

- [ ] **Step 3: 구현**

```python
def _raw_tracking_error_call(ticker, start, end):
    from pykrx import stock
    return stock.get_etf_tracking_error(start.strftime("%Y%m%d"),
                                        end.strftime("%Y%m%d"), ticker)


def fetch_etf_tracking_error(ticker: str, start: date, end: date) -> pd.DataFrame:
    """ETF 추적오차율. 컬럼 tracking_error (mean 사용 권장). 실패 시 빈 DF."""
    try:
        raw = _raw_tracking_error_call(ticker, start, end)
    except Exception:
        return pd.DataFrame(columns=["tracking_error"])
    col = "추적오차율" if "추적오차율" in raw.columns else raw.columns[-1]
    out = raw.rename(columns={col: "tracking_error"})[["tracking_error"]]
    return out
```
(`fetch_etf_price_deviation`도 동형으로 `get_etf_price_deviation` → `괴리율` 컬럼.)

- [ ] **Step 4: 테스트 → pass.** Run: 동일 → PASS.

- [ ] **Step 5: commit**
```bash
git add tradingagents/dataflows/pykrx_data.py tests/unit/dataflows/test_pykrx_etf_impl.py
git commit -m "feat(stage3): pykrx ETF tracking_error/deviation fetch [Task9]"
```

---

## Task 10: universe enrich + impl_score 데이터 주입

**Files:**
- Create: `scripts/enrich_universe_impl_quality.py`
- Modify: `tradingagents/dataflows/universe.py` (ETFEntry에 optional `tracking_error`, `adv_krw`, `deviation`)
- Modify: `tradingagents/agents/allocator/portfolio_allocator.py` + `candidate_selector.py` (impl_score에 enrich 값 전달)

- [ ] **Step 1: ETFEntry 필드 추가 (optional, backward-compat)**

```python
    tracking_error: Optional[float] = Field(default=None)
    adv_krw: Optional[float] = Field(default=None)
    deviation: Optional[float] = Field(default=None)
```

- [ ] **Step 2: enrich 스크립트 (Linux 실행)**

`scripts/enrich_universe_impl_quality.py`: 각 ETF에 대해 `fetch_etf_tracking_error` 평균 + OHLCV로 ADV(거래대금 mean) + `fetch_etf_price_deviation` 평균을 universe.json에 기록. idempotent.

- [ ] **Step 3: `_impl_scores`가 enrich 값 사용**

`candidate_selector._impl_scores`를 eligible의 `e.tracking_error/adv_krw/deviation`를 모아 `compute_impl_score(panels, adv=..., deviation=..., tracking_error=...)`로 호출하도록 확장. (값 없으면 None → Phase1 동작.)

- [ ] **Step 4: 테스트 (mocked enrich 값으로 impl 반영 확인)**

Run: `uv run pytest tests/unit/skills/test_portfolio_candidate.py -k impl -v`
Expected: enrich 값 있는 ETF가 그룹 내 대표로 우대됨.

- [ ] **Step 5: commit**
```bash
git add scripts/enrich_universe_impl_quality.py tradingagents/dataflows/universe.py tradingagents/skills/portfolio/candidate_selector.py
git commit -m "feat(stage3): universe impl-quality enrich + impl_score injection [Task10]"
```

- [ ] **Step 6: (Linux) enrich 실행 + 품질 검증**

Run: `uv run python scripts/enrich_universe_impl_quality.py`
검증: 추적오차/괴리율 분포 sanity(음수·NaN·이상치), pykrx 공식 대비 spot check.

---

## Task 11: economic backtest (현행 vs 신규) + acceptance (Linux gate)

**Files:**
- Modify: `scripts/backtest_candidate_selection.py`

- [ ] **Step 1: "현행 vs 신규" 비교 모드 추가**

`run_krx_backtest`를 확장: 각 as_of에서 (a) 현행 select(패널/clusters 미전달), (b) 신규 select(패널/clusters/enrich 전달) 두 번 → forward 90d basket return/vol/intra-corr 비교. mean Δret, win-rate, Δvol, Δcorr 출력.

- [ ] **Step 2: (Linux) 실행**

Run: `uv run python scripts/backtest_candidate_selection.py --mode krx --horizon 90`
(전제: KRX creds + `data/.cache/pykrx_universe.parquet` prefetch + universe enrich 완료.)

- [ ] **Step 3: acceptance 판정**

PASS 조건: `mean(Δcorr) ≤ 0` AND `mean(Δvol) ≤ +0.002` AND `mean(Δreturn) ≥ -0.002`. win-rate는 참고.
- PASS → "개선" 결론 + 머지 진행.
- FAIL → 진단(어느 bucket/지표) 후 δ/cap/floor/ε 재튜닝 또는 설계 재검토. **FAIL 시 "더 낫다" 주장·머지 안 함.**

- [ ] **Step 4: 결과 기록 + commit**

`artifacts/<run-date>/stage3_selection_backtest.md`에 결과 표 + verdict 기록.
```bash
git add scripts/backtest_candidate_selection.py artifacts/
git commit -m "test(stage3): economic backtest current-vs-new + acceptance verdict [Task11]"
```

---

## Sign-off Checklist

- [ ] Phase 1: Task 1-8 — unit/property/non-regression/synthetic 전부 통과 (현 환경)
- [ ] non-regression: 신규 입력 미제공 시 선정 결과 현행과 동일
- [ ] Phase 2: Task 9-10 — pykrx fetch + enrich + 품질검증 (Linux)
- [ ] Task 11: economic backtest 실행 + acceptance(Δcorr≤0 ∧ Δvol≤+0.002 ∧ Δret≥-0.002)
- [ ] acceptance PASS 시에만 "개선" 주장 + 머지; FAIL 시 재튜닝/재검토
- [ ] 스키마(BucketTarget/CandidateSet/WeightVector)·optimizer(④)·Stage 2 불변 확인
- [ ] AP1/8/11(optimizer)·PR2a(Stage2) 미포함 확인

---

## Self-Review (작성자 기록)

- **Spec 커버리지:** D1(범위)=Task별 분리, D2/D3(floor+유동성)=Task5+Task3/10, D4(분리)=Task4, D5(family)=Task2, D6(timing)=Task1, D7(impl)=Task3/10, D8(cluster)=Task4, D9(acceptance)=Task11, D10(anchor OUT)=비범위. ✓
- **Placeholder:** 코드 블록 실제 내용 채움. enrich 스크립트(Task10 Step2)·krx 비교(Task11 Step1)는 구조 명시(실행 환경 Linux 의존이라 골격+검증 기준 제시).
- **Type 일관성:** `score_candidates`/`compute_impl_score`/`select_cluster_aware` 시그니처가 Task6 호출과 일치. `_timing_overlay`는 Task1 정의=Task2 사용 일치.
