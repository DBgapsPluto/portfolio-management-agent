# 개별 ETF 선택 하이브리드 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 이질 버킷(b2/b3/b5)의 within-bucket ETF 선택을 AUM 가중에서 "LLM 테마 view로 좁힘 → 위험조정 모멘텀 top-K 선정·가중"으로 전환한다.

**Architecture:** Step-A 트레이더 LLM 출력(`BucketTilt`)에 `sub_category_views`를 더해(별도 LLM 콜 0) 테마 선호를 받고, `candidate_selector` 이질 분기가 그 선호로 후보를 좁힌 뒤 위험조정 모멘텀으로 top-K를 고르고, `within_bucket`가 모멘텀 가중하고, 신규 `cluster_repair`가 상관군집을 35%로 graceful 강제한다. 동질 버킷·BL·오버레이는 불변.

**Tech Stack:** Python 3.13, pydantic v2, numpy/pandas, pytest. spec: `docs/superpowers/specs/2026-06-16-etf-selection-hybrid-design.md` (rev3, 4e180a8). 브랜치 `rework/pipeline-methodology`.

**테스트 실행(항상):** `PYTHONUTF8=1 PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest <path> -q -p no:cacheprovider`

**정책:** 코드 변경마다 테스트 통과 + (Task 9) 적대적 감사 필수.

---

## File Structure

| 파일 | 책임 | 변경 |
|---|---|---|
| `tradingagents/schemas/portfolio.py` | BucketTilt 스키마 | M1: `sub_category_views` 필드 추가 |
| `tradingagents/skills/portfolio/factor_scorer.py` | 팩터 z 프리미티브 | 신규 `risk_adjusted_momentum()` |
| `tradingagents/skills/portfolio/candidate_selector.py` | 버킷내 ETF 선정 | M3: 이질 분기(테마필터+모멘텀랭크+top-K) |
| `tradingagents/skills/portfolio/within_bucket.py` | 선정종목 가중 | M4: `momentum_weighted_allocation()` |
| `tradingagents/skills/mandate/cluster_repair.py` (신규) | 군집 35% repair | M5 |
| `tradingagents/skills/mandate/correlation_check.py` | 군집 validator | M5: `DEFAULT_CLUSTER_CAP` 0.25→0.35 |
| `tradingagents/agents/trader/trader_allocator.py` | Step A/B 통합 | M2: 프롬프트+배선+attribution |
| `tradingagents/default_config.py` | dials | `min_etf_aum_krw`/`top_k_heterogeneous`/`w_vol`/`softmax_temperature` |
| `scripts/backtest_etf_selection.py` (신규) | 경량 백테스트 | Task 8 |

빌드 순서(leaf→통합): M1 → 모멘텀헬퍼 → M3 → M4 → M5 → M2(통합) → clawback 정량화 → 백테스트 → 적대적 감사.

---

### Task 1: M1 — `BucketTilt.sub_category_views` 필드

**Files:**
- Modify: `tradingagents/schemas/portfolio.py:95-101`
- Test: `tests/unit/schemas/test_portfolio_schema.py` (없으면 생성)

- [ ] **Step 1: 실패 테스트 작성**
```python
# tests/unit/schemas/test_portfolio_schema.py
from tradingagents.schemas.portfolio import BucketTilt

def test_bucket_tilt_default_sub_category_views_empty():
    bt = BucketTilt()
    assert bt.sub_category_views == {}          # backward-compat: 기본 빈 dict

def test_bucket_tilt_accepts_sub_category_views():
    bt = BucketTilt(tilts={"b3_global_tech": 0.0},
                    sub_category_views={"b3_global_tech": {"semiconductor": 0.8, "battery_ev": -0.4}})
    assert bt.sub_category_views["b3_global_tech"]["semiconductor"] == 0.8
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/unit/schemas/test_portfolio_schema.py -q` · Expected: FAIL (`sub_category_views` 없음 → AttributeError/ValidationError)

- [ ] **Step 3: 구현** — `portfolio.py` BucketTilt에 필드 추가:
```python
class BucketTilt(BaseModel):
    """Trader step A 출력 — quadrant 앵커 대비 버킷별 tilt (sparse, 미지정=0)."""
    tilts: dict[str, float] = Field(
        default_factory=dict,
        description="bucket key → 앵커 대비 가감(+/-). 오버웨이트는 언더웨이트로 펀딩(net≈0).",
    )
    sub_category_views: dict[str, dict[str, float]] = Field(
        default_factory=dict,
        description="이질 버킷 한정 — bucket key → {sub_category: 선호 ∈ [-1,+1]}. +선호/-배제/0중립.",
    )
    rationale: str = Field(default="", max_length=500)
```

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/unit/schemas/test_portfolio_schema.py -q` · Expected: PASS. 회귀: `pytest tests/unit/agents/trader/test_trader_allocator.py -q` (BucketTilt() fallback 불변) · Expected: PASS

- [ ] **Step 5: 커밋**
```bash
git add tradingagents/schemas/portfolio.py tests/unit/schemas/test_portfolio_schema.py
git commit -m "feat(schema): BucketTilt.sub_category_views (ETF theme view seed)"
```

---

### Task 2: 위험조정 모멘텀 헬퍼

**Files:**
- Modify: `tradingagents/skills/portfolio/factor_scorer.py` (신규 함수 추가)
- Test: `tests/unit/skills/test_portfolio_factor_scorer.py` (기존 파일에 추가)

- [ ] **Step 1: 실패 테스트 작성**
```python
# tests/unit/skills/test_portfolio_factor_scorer.py 에 추가
from tradingagents.skills.portfolio.factor_scorer import FactorPanel, risk_adjusted_momentum

def _panel(m3, m6, m12, vol):
    return FactorPanel(skip1m_mom_3m=m3, skip1m_mom_6m=m6, skip1m_mom_12m=m12,
                       realized_vol_60d=vol, sharpe_60d=None, log_aum=1.0)

def test_risk_adj_momentum_higher_mom_ranks_higher():
    panels = {"A": _panel(0.30,0.30,0.30, 0.20), "B": _panel(0.05,0.05,0.05, 0.20)}
    s = risk_adjusted_momentum(panels, w_vol=0.4)
    assert s["A"] > s["B"]

def test_risk_adj_momentum_penalizes_high_vol():
    # 같은 모멘텀, A가 변동성 큼 → A가 낮아야
    panels = {"A": _panel(0.20,0.20,0.20, 0.60), "B": _panel(0.20,0.20,0.20, 0.10)}
    s = risk_adjusted_momentum(panels, w_vol=0.4)
    assert s["B"] > s["A"]

def test_risk_adj_momentum_all_none_is_neg_inf():
    panels = {"A": _panel(None,None,None, None), "B": _panel(0.10,0.10,0.10, 0.20)}
    s = risk_adjusted_momentum(panels, w_vol=0.4)
    assert s["A"] == float("-inf")
    assert s["B"] > float("-inf")
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/unit/skills/test_portfolio_factor_scorer.py -k risk_adj -q` · Expected: FAIL (`risk_adjusted_momentum` 없음)

- [ ] **Step 3: 구현** — `factor_scorer.py`에 추가 (기존 `_rank_normalize` 재사용):
```python
def risk_adjusted_momentum(
    panels: dict[str, "FactorPanel | None"], w_vol: float = 0.4,
) -> dict[str, float]:
    """위험조정 모멘텀 = mean(rank_norm(skip1m_mom_{3,6,12})) - w_vol*rank_norm(realized_vol_60d).

    panels: ticker -> FactorPanel(or None). cross-section은 panels 키 전체.
    모멘텀 3개 전부 None인 ticker -> -inf (최하위, 버킷 비우지 않음).
    """
    def _field(name: str) -> dict[str, float | None]:
        return {t: (getattr(p, name, None) if p is not None else None) for t, p in panels.items()}

    m3 = _rank_normalize(_field("skip1m_mom_3m"))
    m6 = _rank_normalize(_field("skip1m_mom_6m"))
    m12 = _rank_normalize(_field("skip1m_mom_12m"))
    vol = _rank_normalize(_field("realized_vol_60d"))

    out: dict[str, float] = {}
    for t, p in panels.items():
        raw = [getattr(p, n, None) if p is not None else None
               for n in ("skip1m_mom_3m", "skip1m_mom_6m", "skip1m_mom_12m")]
        if all(v is None for v in raw):
            out[t] = float("-inf")
        else:
            out[t] = (m3[t] + m6[t] + m12[t]) / 3.0 - w_vol * vol[t]
    return out
```

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/unit/skills/test_portfolio_factor_scorer.py -k risk_adj -q` · Expected: PASS

- [ ] **Step 5: 커밋**
```bash
git add tradingagents/skills/portfolio/factor_scorer.py tests/unit/skills/test_portfolio_factor_scorer.py
git commit -m "feat(factor): risk_adjusted_momentum helper (mom-z penalized by vol-z)"
```

---

### Task 3: M3 — `candidate_selector` 이질 분기

**Files:**
- Modify: `tradingagents/skills/portfolio/candidate_selector.py` (신규 상수 + 이질 분기 + 시그니처)
- Test: `tests/unit/skills/test_candidate_selector.py` (기존 파일에 추가)

- [ ] **Step 1: 실패 테스트 작성**
```python
# tests/unit/skills/test_candidate_selector.py 에 추가
from tradingagents.skills.portfolio.candidate_selector import (
    select_representative_candidates, HETEROGENEOUS_BUCKETS, SUBCAT_PREF_THRESHOLD,
)

def test_het_branch_picks_high_momentum_favored_subcat():
    # b3: 반도체(고모멘텀, 선호) vs 2차전지(저모멘텀, 배제) → 반도체 선정
    eligible = ["SEMI", "BATT", "BROAD"]
    aum = {"SEMI": 2e11, "BATT": 2e11, "BROAD": 3e11}
    sub = {"SEMI": "semiconductor", "BATT": "battery_ev", "BROAD": "us_tech_nasdaq"}
    idx = {"SEMI": "ix_semi", "BATT": "ix_batt", "BROAD": "ix_broad"}
    mom = {"SEMI": 1.2, "BATT": -0.5, "BROAD": 0.1}
    sel = select_representative_candidates(
        bucket_key="b3_global_tech", eligible=eligible, aum=aum, sub_category=sub,
        underlying_index=idx, bucket_weight=0.12, capital_krw=1e9,
        sub_category_views={"semiconductor": 0.8, "battery_ev": -0.5},
        momentum=mom, min_etf_aum_krw=1e10, top_k=3,
    )
    assert "BATT" not in sel                      # 배제(pref<-τ)
    assert sel[0] == "SEMI"                        # 선호+최고모멘텀 1순위

def test_het_branch_top_k_limits_selection():
    eligible = [f"E{i}" for i in range(6)]
    aum = {t: 5e11 for t in eligible}
    sub = {t: "semiconductor" for t in eligible}
    idx = {t: f"ix{i}" for i, t in enumerate(eligible)}
    mom = {t: float(i) for i, t in enumerate(eligible)}   # E5 최고
    sel = select_representative_candidates(
        bucket_key="b3_global_tech", eligible=eligible, aum=aum, sub_category=sub,
        underlying_index=idx, bucket_weight=0.10, capital_krw=1e9,
        sub_category_views=None, momentum=mom, min_etf_aum_krw=1e10, top_k=3,
    )
    assert len(sel) == 3 and sel[0] == "E5"       # top-3 by momentum

def test_homogeneous_bucket_unchanged():
    # 동질 버킷은 기존 core-by-AUM (momentum/views 무시)
    eligible = ["X", "Y"]
    aum = {"X": 3e11, "Y": 1e11}
    sub = {"X": "index_broad", "Y": "index_broad"}
    idx = {"X": "ixX", "Y": "ixY"}
    sel = select_representative_candidates(
        bucket_key="b1_kr_equity", eligible=eligible, aum=aum, sub_category=sub,
        underlying_index=idx, bucket_weight=0.10, capital_krw=1e9,
        momentum={"X": -1.0, "Y": 5.0}, sub_category_views={"index_broad": -0.9},
    )
    assert sel == ["X"]                            # AUM 최대(momentum/views 무시)
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/unit/skills/test_candidate_selector.py -k "het_branch or homogeneous_bucket_unchanged" -q` · Expected: FAIL (신규 인자/상수 없음)

- [ ] **Step 3: 구현** — `candidate_selector.py`:
  (a) 상단에 상수 추가:
```python
HETEROGENEOUS_BUCKETS: set[str] = {"b2_dm_core", "b3_global_tech", "b5_other_intl"}
SUBCAT_PREF_THRESHOLD: float = 0.3
```
  (b) `select_representative_candidates` 시그니처에 keyword-only 인자 추가 (기존 `*,` 뒤):
```python
    sub_category_views: dict[str, float] | None = None,   # this bucket: sub_cat -> pref
    momentum: dict[str, float] | None = None,
    min_etf_aum_krw: float | None = None,
    top_k: int | None = None,
```
  (c) 함수 본문 맨 앞(`if not eligible: return []` 다음)에 이질 분기:
```python
    if bucket_key in HETEROGENEOUS_BUCKETS and momentum is not None:
        return _select_heterogeneous(
            bucket_key=bucket_key, eligible=eligible, aum=aum,
            sub_category=sub_category, underlying_index=underlying_index,
            bucket_weight=bucket_weight, sub_category_views=sub_category_views or {},
            momentum=momentum, min_etf_aum_krw=min_etf_aum_krw or 0.0,
            top_k=top_k or 3, trace=trace,
        )
    # (이하 기존 동질 경로 그대로)
```
  (d) 신규 내부 함수 `_select_heterogeneous` (기존 `_dedup`/`_normalize_index` 재사용):
```python
def _select_heterogeneous(*, bucket_key, eligible, aum, sub_category, underlying_index,
                          bucket_weight, sub_category_views, momentum, min_etf_aum_krw,
                          top_k, trace):
    tau = SUBCAT_PREF_THRESHOLD
    revert = None
    # 1. 배제 (pref < -tau)
    pool = [t for t in eligible if sub_category_views.get(sub_category.get(t), 0.0) >= -tau]
    # 2. 유동성 floor
    floored = [t for t in pool if aum.get(t, 0.0) >= min_etf_aum_krw]
    if not floored and pool:
        floored, revert = pool, "floor_relaxed"      # floor가 전부 컷 → 무시
    pool = floored
    # 3. 선호 좁힘 (pref > +tau 있으면 그것만)
    favored = [t for t in pool if sub_category_views.get(sub_category.get(t), 0.0) > tau]
    if favored:
        pool = favored
    # 공백 → core-by-AUM fallback
    if not pool:
        if trace is not None:
            trace.update({"bucket": bucket_key, "revert": "core_aum"})
        return _select_core_by_aum(bucket_key, eligible, aum, sub_category,
                                   underlying_index, bucket_weight)
    # 4. 위험조정 모멘텀 desc, tiebreak (-aum, t)
    ranked = sorted(pool, key=lambda t: (-momentum.get(t, float("-inf")), -aum.get(t, 0.0), t))
    # 5. dedup → top max(n_floor, min(top_k, |pool|))
    deduped = _dedup(ranked, set())
    n_floor = max(1, math.ceil(bucket_weight / SINGLE_CAP - 1e-9))
    n = min(max(n_floor, min(top_k, len(deduped))), len(deduped))
    selected = deduped[:n]
    if trace is not None:
        trace.update({"bucket": bucket_key, "selected": list(selected),
                      "revert": revert, "n_floor": n_floor})
    return selected
```
  (e) 기존 동질 본문(line 171-214)을 `_select_core_by_aum(...)` 헬퍼로 추출(시그니처: `bucket_key, eligible, aum, sub_category, underlying_index, bucket_weight, quadrant=None, fx_regime=None, name=None`)하고, 기존 호출 경로는 이 헬퍼를 호출하도록 변경. (regime 인자는 동질 경로 전용이므로 그대로 전달.)

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/unit/skills/test_candidate_selector.py -q` · Expected: PASS (신규 3 + 기존 전부)

- [ ] **Step 5: 커밋**
```bash
git add tradingagents/skills/portfolio/candidate_selector.py tests/unit/skills/test_candidate_selector.py
git commit -m "feat(selector): heterogeneous-bucket branch (theme filter + risk-adj momentum top-K)"
```

---

### Task 4: M4 — `within_bucket.momentum_weighted_allocation`

**Files:**
- Modify: `tradingagents/skills/portfolio/within_bucket.py` (신규 함수)
- Test: `tests/unit/skills/test_within_bucket.py` (기존 파일에 추가)

- [ ] **Step 1: 실패 테스트 작성**
```python
# tests/unit/skills/test_within_bucket.py 에 추가
import math
from tradingagents.skills.portfolio.within_bucket import momentum_weighted_allocation

def test_momentum_weight_higher_score_gets_more():
    bw = {"b3_global_tech": 0.12}
    sel = {"b3_global_tech": ["A", "B"]}
    score = {"A": 2.0, "B": 0.0}
    out = momentum_weighted_allocation(bw, sel, score, temperature=1.0)
    assert out["A"] > out["B"]
    assert abs(sum(out.values()) - 0.12) < 1e-9
    assert all(w <= 0.20 + 1e-9 for w in out.values())

def test_momentum_weight_neg_inf_score_gets_zero_share():
    bw = {"b3_global_tech": 0.10}
    sel = {"b3_global_tech": ["A", "B"]}
    score = {"A": 1.0, "B": float("-inf")}
    out = momentum_weighted_allocation(bw, sel, score)
    assert out.get("B", 0.0) < 1e-9 and abs(out["A"] - 0.10) < 1e-9
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/unit/skills/test_within_bucket.py -k momentum_weight -q` · Expected: FAIL

- [ ] **Step 3: 구현** — `within_bucket.py`에 추가 (기존 `aum_weighted_allocation` 재사용 — softmax weight를 "aum"으로 전달):
```python
def _softmax(scores: dict[str, float], temperature: float) -> dict[str, float]:
    """비-음수 softmax weight. -inf -> 0. 전부 -inf -> 균등."""
    finite = [s for s in scores.values() if s != float("-inf")]
    if not finite:
        return {t: 1.0 for t in scores}            # 전부 -inf → 균등(aum_weighted가 분배)
    mx = max(finite)
    exps = {t: (math.exp((s - mx) / temperature) if s != float("-inf") else 0.0)
            for t, s in scores.items()}
    return exps

def momentum_weighted_allocation(
    bucket_weights: dict[str, float],
    selections: dict[str, list[str]],
    score: dict[str, float],
    temperature: float = 1.0,
) -> dict[str, float]:
    """버킷 비중을 선정 종목에 softmax(score/T) 비례 배분 + 단일 20% cap.

    score(위험조정 모멘텀)는 z라 음수 가능 → softmax로 비-음수 변환 후
    aum_weighted_allocation 의 cap water-fill 을 그대로 재사용.
    """
    weight_proxy: dict[str, float] = {}
    for tickers in selections.values():
        weight_proxy.update(_softmax({t: score.get(t, float("-inf")) for t in tickers},
                                     temperature))
    return aum_weighted_allocation(bucket_weights, selections, weight_proxy)
```

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/unit/skills/test_within_bucket.py -q` · Expected: PASS

- [ ] **Step 5: 커밋**
```bash
git add tradingagents/skills/portfolio/within_bucket.py tests/unit/skills/test_within_bucket.py
git commit -m "feat(within_bucket): momentum_weighted_allocation (softmax of risk-adj momentum)"
```

---

### Task 5: M5 — `cluster_repair` + cluster cap 0.25→0.35

**Files:**
- Create: `tradingagents/skills/mandate/cluster_repair.py`
- Modify: `tradingagents/skills/mandate/correlation_check.py:9` (`DEFAULT_CLUSTER_CAP` 0.25→0.35)
- Test: `tests/unit/skills/test_cluster_repair.py` (신규)

- [ ] **Step 1: 실패 테스트 작성**
```python
# tests/unit/skills/test_cluster_repair.py
from tradingagents.schemas.technical import Cluster
from tradingagents.skills.mandate.cluster_repair import repair_cluster_cap, CLUSTER_CAP

def _cl(members):
    return Cluster(cluster_id=1, members=members, avg_internal_correlation=0.8,
                   category_label="semi")

def test_cluster_over_cap_scaled_down():
    w = {"A": 0.25, "B": 0.25, "C": 0.30, "CASH": 0.20}   # A+B=0.50 > 0.35
    out = repair_cluster_cap(w, [_cl(["A", "B"])], cap=0.35)
    assert sum(out[t] for t in ("A", "B")) <= 0.35 + 1e-6
    assert abs(sum(out.values()) - 1.0) < 1e-6

def test_cluster_under_cap_noop():
    w = {"A": 0.15, "B": 0.15, "CASH": 0.70}
    out = repair_cluster_cap(w, [_cl(["A", "B"])], cap=0.35)
    assert out == w

def test_default_cluster_cap_is_035():
    assert CLUSTER_CAP == 0.35
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/unit/skills/test_cluster_repair.py -q` · Expected: FAIL (모듈 없음)

- [ ] **Step 3: 구현**
  (a) `cluster_repair.py` 생성 (risk_repair 패턴 미러):
```python
"""상관군집 cap deterministic repair (군집합 ≤ cap). self-imposed 35% (대회 규칙 아님).

trader 노드가 ETF weight 확정 후 호출. 초과 군집 멤버를 비례 축소, freed 를
비-군집(어느 군집에도 없는) 포지션에 water-fill(단일 20% 한도) 후 renormalize.
순수·결정론. correlation_check(validator) 와 동일 임계.
"""
from __future__ import annotations

from tradingagents.schemas.technical import Cluster
from tradingagents.skills.portfolio.within_bucket import SINGLE_CAP

CLUSTER_CAP: float = 0.35     # self-imposed (DB GAPS 규칙엔 cluster cap 없음; A2 완화)
FLOAT_TOLERANCE: float = 1e-6
_MAX_ITERS: int = 50


def repair_cluster_cap(
    weights: dict[str, float], clusters: list[Cluster], cap: float = CLUSTER_CAP,
) -> dict[str, float]:
    if not weights or not clusters:
        return dict(weights)
    out = dict(weights)
    all_cluster_members = {t for c in clusters for t in c.members}
    for cluster in clusters:
        members = [t for t in cluster.members if t in out]
        csum = sum(out[t] for t in members)
        if csum <= cap + FLOAT_TOLERANCE:
            continue
        scale = cap / csum
        for t in members:
            out[t] *= scale
        freed = csum - cap
        # freed 를 비-군집(어느 군집에도 없는) 포지션에 water-fill (단일 cap)
        recipients = [t for t in out if t not in all_cluster_members]
        for _ in range(_MAX_ITERS):
            if freed <= 1e-12:
                break
            eligible = {t: out[t] for t in recipients if out[t] < SINGLE_CAP - 1e-12}
            base = sum(eligible.values()) or float(len(eligible))
            if not eligible:
                break
            give = min(freed, sum(SINGLE_CAP - v for v in eligible.values()))
            for t in eligible:
                share = (out[t] / base) if sum(eligible.values()) > 1e-12 else (1.0 / len(eligible))
                out[t] = min(SINGLE_CAP, out[t] + give * share)
            freed -= give
    s = sum(out.values())
    return {t: w / s for t, w in out.items()} if s > 0 else dict(weights)
```
  (b) `correlation_check.py:9` `DEFAULT_CLUSTER_CAP: float = 0.25` → `0.35`, 주석을 "self-imposed (DB GAPS 규칙엔 cluster cap 없음; A2 35% 완화) — validator/repair 동기화"로 갱신.

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/unit/skills/test_cluster_repair.py tests/unit/agents/test_mandate_validator.py -q` · Expected: PASS (validator 임계 0.35로 일관). 회귀: `pytest tests/unit/rebalance -q -m "not network"`

- [ ] **Step 5: 커밋**
```bash
git add tradingagents/skills/mandate/cluster_repair.py tradingagents/skills/mandate/correlation_check.py tests/unit/skills/test_cluster_repair.py
git commit -m "feat(mandate): cluster_repair (graceful 35% cluster cap) + relax validator 0.25->0.35"
```

---

### Task 6: M2 — `trader_allocator` 통합 (프롬프트 + 배선 + attribution)

**Files:**
- Modify: `tradingagents/agents/trader/trader_allocator.py` (프롬프트 90-130, Step B 루프 196-220, repair 247-259)
- Modify: `tradingagents/default_config.py` (dials)
- Test: `tests/unit/agents/trader/test_trader_allocator.py` (기존 + 추가)

- [ ] **Step 1: 실패 테스트 작성** (이질 버킷 통합 — Step A LLM mock이 sub_category_views 출력 → 반도체 선택 + 군집 ≤35%)
```python
# test_trader_allocator.py 에 추가 — 기존 _FakeStep/_universe_14 픽스처 패턴 사용
def test_het_bucket_selects_high_momentum_semi(monkeypatch, _universe_14_path):
    # _FakeStep 이 sub_category_views 포함한 BucketTilt 반환하도록 구성,
    # technical_report.factor_panel 에 반도체 ETF 고모멘텀 주입.
    # 결과 weight_vector 에서 반도체 ETF 선택 + 상관군집 합 <= 0.35 검증.
    ...  # (구현 시 기존 픽스처에 factor_panel + sub_category_views 추가)
```
> 구현자 메모: 기존 `test_trader_allocator.py`의 `_FakeStep`(BucketTilt 반환)·`_universe_14`·factor_panel mock 패턴을 따른다. 핵심 assert: (1) `result["weight_vector"].weights`에 고모멘텀 반도체 ETF가 존재, (2) `result["allocation_attribution"]["step_a"]`에 `sub_category_views`/선택 기록, (3) 상관군집 합 ≤ 0.35.

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/unit/agents/trader/test_trader_allocator.py -k het_bucket -q` · Expected: FAIL

- [ ] **Step 3: 구현**
  (a) `default_config.py`의 `rebalance`/`portfolio_dials`에 추가:
```python
    "min_etf_aum_krw": 10_000_000_000,
    "top_k_heterogeneous": 3,
    "w_vol": 0.4,
    "softmax_temperature": 1.0,
```
  (b) `_STEP_A_SYSTEM`(90-98) ③에 추가: *"이질 버킷(b2_dm_core·b3_global_tech·b5_other_intl)은 sub_category 선호(+선호/−배제/0중립, [-1,1])도 함께 출력하라. 밸류·모멘텀·뉴스 테마 신호 기반. 그 외 버킷은 sub_category_views 비워라."*
  (c) `_step_a_prompt`(101-130) body에 §7 신호 테이블(이질 버킷별 sub_category: mom_z·n·top_etf·theme_tag) 렌더 추가.
  (d) `node`(163~)의 Step B 루프(196-220):
```python
        from tradingagents.skills.portfolio.factor_scorer import risk_adjusted_momentum
        from tradingagents.skills.portfolio.candidate_selector import HETEROGENEOUS_BUCKETS
        from tradingagents.skills.portfolio.within_bucket import momentum_weighted_allocation
        w_vol = _dials.get("w_vol", 0.4)
        momentum = risk_adjusted_momentum({t: fp.get(t) for t in aum}, w_vol=w_vol)
        # ... 버킷별 select 호출에 신규 인자:
        sel = select_representative_candidates(
            ...,  # 기존 인자
            sub_category_views=(tilt.sub_category_views.get(bkey)
                                if bkey in HETEROGENEOUS_BUCKETS else None),
            momentum=momentum,
            min_etf_aum_krw=_dials.get("min_etf_aum_krw", 10e9),
            top_k=_dials.get("top_k_heterogeneous", 3),
        )
```
  (e) 가중: 이질 버킷은 `momentum_weighted_allocation(...,score=momentum,temperature=_dials.get("softmax_temperature",1.0))`, 동질은 기존 `aum_weighted_allocation`. (버킷별로 분기하거나, 이질 선택 결과만 모멘텀 가중.)
  (f) repair: `_repair_all` 호출부(247-259)에 `repair_cluster_cap(weights, state.get("correlation_clusters") or [], cap=0.35)` 추가 (category/risk repair 다음).
  (g) attribution `step_a`에 `sub_category_views`·이질 선택·revert 사유 기록.

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/unit/agents/trader/test_trader_allocator.py -q` · Expected: PASS. 회귀: `pytest tests/unit/agents tests/integration -q -m "not network and not slow and not eval"`

- [ ] **Step 5: 커밋**
```bash
git add tradingagents/agents/trader/trader_allocator.py tradingagents/default_config.py tests/unit/agents/trader/test_trader_allocator.py
git commit -m "feat(trader): wire LLM theme view + risk-adj momentum selection + cluster_repair (Step B)"
```

---

### Task 7: repair-clawback 실현 집중 정량화

**Files:**
- Create: `tests/integration/test_etf_selection_realized_concentration.py`

- [ ] **Step 1: 테스트 작성** — 멜트업 스냅샷(반도체 고모멘텀)으로 Step B→repair 전 과정 실행 후 *실현* 반도체(상관군집) 비중 측정·assert.
```python
def test_realized_semi_concentration_within_35_and_meaningful(_universe_14_path):
    # 반도체 sub_cat ETF 다수에 고모멘텀, b2/b3 cross-bucket 군집 구성.
    # full node 실행 → 최종 weights 의 반도체 군집 합 측정.
    # assert: 0.10 < semi_cluster_sum <= 0.35 (의미 있는 집중 + 35% 천장)
    ...
```
> 구현자 메모: 이게 spec §7의 "clawback 정량화 Task". 실제 측정값을 테스트 docstring/주석에 기록해 *진짜 레버 크기*를 문서화한다.

- [ ] **Step 2-4: 실패→구현(테스트 자체가 통합 검증)→통과** — Run: `pytest tests/integration/test_etf_selection_realized_concentration.py -q` · Expected: PASS, 측정값 출력
- [ ] **Step 5: 커밋** — `git commit -m "test(integration): quantify realized semi concentration after repair clawback"`

---

### Task 8: 경량 백테스트

**Files:**
- Create: `scripts/backtest_etf_selection.py`

- [ ] **Step 1: 스크립트 작성** — 이질 버킷에서 월간 재선택, **위험조정모멘텀 top-K vs AUM-top**의 net-of-cost(10bps) 누적수익·Sharpe·MDD. warm-up 273거래일, 최소 24개월, full-history ETF 제한 + 월별 coverage 보고. b8 제외.
```python
# scripts/backtest_etf_selection.py — fetch_returns_matrix + compute_factor_panel(슬라이스)
# 각 월말 as_of: momentum-pick top-K vs AUM-pick → 다음달 수익 누적, turnover×10bps 차감.
# 출력: per-bucket 누적수익/Sharpe/MDD 비교 + GO/NO-GO 판정.
```
> 구현자 메모: `fetch_returns_matrix`(returns_matrix.py)·`compute_factor_panel`(factor_scorer.py:90) 사용. GO = 위험조정모멘텀이 AUM 대비 수익/Sharpe 우위 AND MDD 열위 아님.

- [ ] **Step 2: 실행** — Run: `PYTHONUTF8=1 ./.venv/Scripts/python.exe scripts/backtest_etf_selection.py` (`.env` 로드 필요) · Expected: per-bucket 비교표 + GO/NO-GO
- [ ] **Step 3: 커밋** — `git commit -m "feat(backtest): ETF-selection momentum-vs-AUM sanity (GO/NO-GO)"`

---

### Task 9: 적대적 감사 + 전체 회귀

- [ ] **Step 1: 전체 스위트** — Run: `PYTHONUTF8=1 PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest tests/ -q -p no:cacheprovider -m "not eval and not network"` · Expected: 신규 통과 + 기존 회귀 0(환경 한정 2건 제외)
- [ ] **Step 2: 적대적 감사** — 변경(M1-M5+배선)에 대해 적대적 감사 워크플로(코드 타당성·엣지·회귀) 실행, must-fix 인라인 수정 (사용자 정책).
- [ ] **Step 3: 백테스트 GO 확인** — Task 8 결과가 GO인지 확인. NO-GO면 W_VOL/horizon/top_k 재조정 후 재실행.
- [ ] **Step 4: 최종 커밋** — `git commit -m "test: full regression + adversarial audit for ETF-selection hybrid"`

---

## Self-Review (작성자 체크)

- **Spec 커버리지:** M1(T1)·모멘텀(T2)·M3(T3)·M4(T4)·M5(T5)·M2 통합(T6)·clawback 정량화(T7, spec §7)·백테스트(T8, spec §9)·적대적 감사(T9, spec §11). §3 self-imposed cap 주석 정정 = T5(b). 누락 없음.
- **타입 일관성:** `risk_adjusted_momentum(panels, w_vol)`(T2) → T3/T6에서 동일 시그니처. `momentum_weighted_allocation(bw, sel, score, temperature)`(T4) → T6에서 동일. `repair_cluster_cap(weights, clusters, cap)`(T5) → T6에서 동일. `sub_category_views: dict[str,dict[str,float]]`(T1) → T6에서 `tilt.sub_category_views.get(bkey)`로 per-bucket dict 추출(일치).
- **placeholder:** T6 Step1·T7·T8 테스트 본문은 기존 픽스처 의존이라 "구현자 메모"로 명시(완전 코드 대신 정확한 지시 + assert 조건). 그 외 전 구현 step은 완전 코드.
