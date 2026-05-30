# Stage 3 Phase 2b — ENB Greedy Forward Selection + Adaptive N Design

**Date**: 2026-05-30
**Status**: Design (awaiting user review)
**Author**: Brainstorming session

## Goal

Stage 3 종목 선정을 cluster-aware top-N (고정 4 종목) 에서 ENB greedy forward selection 으로 교체. 매 step ΔENB 최대 자산 추가, 한계효용 미달 또는 capacity cap 도달 시 중단. 종목 수가 bucket 별로 자동 결정되어 작은 bucket 의 dust 자동 제거 + 큰 bucket 의 실질 분산 보장. Phase 2a 의 impl_score 가 처음으로 ranking 에 실질 영향.

추가로 Phase 1 follow-up 의 state mocking helpers 를 작성해 `test_allocator_phase1.py` 의 4 skip integration tests 를 enable.

## Context

- **Phase 1 (c0be9b2, 2026-05-28)** 완료: cash spillover, ENB warning, AUM 필터 제거.
- **Phase 2a (1993d6c, 2026-05-29)** 완료: ETF metrics (KRX OpenAPI) + impl_score 4-요소 weighted composite. KRX endpoint 404 로 현재 fallback (log_aum 단독) 작동.
- **현재 cluster-aware top-N 한계** ([Phase 1 평가](../../../docs/pipeline-analysis/) 의 "①, ②, ③" 비판):
  1. `per_bucket_n = 4` 고정 → 작은 bucket 에 dust position (2-3% positions)
  2. "다른 cluster = 분산" 의 binary 측정 — corr 0.69 ETF 둘이 다른 그룹으로 분류돼도 헤지 효과 0
  3. Stage 1 `correlation_clusters` 가 top-5 per category 만 cover → 누락 ETF 가 silent duplicate
- **GAPS 12회 universe**: 188 ETF. 작은 bucket 의 chosen 4 종목이 capital 100M 미만 (1B 자본 × 10% = 100M, 4 종목 → 25M each) 으로 dust 위험.

## Scope

### 포함

- `tradingagents/skills/portfolio/factor_scorer.py` — `select_cluster_aware` 를 `select_by_enb_greedy` 로 replace, `compute_adaptive_n_max` 신규
- `tradingagents/skills/portfolio/candidate_selector.py` — `select_etf_candidates` 시그니처 확장 (`sigma`, `capital_krw` 추가, `per_bucket_n` 제거)
- `tradingagents/agents/allocator/portfolio_allocator.py` — `sigma` 계산 + `capital_krw` 추출 + `per_bucket_n` 로직 폐기
- 신규 모듈 `tests/integration/_allocator_state_helpers.py` — state mock builder (Phase 1 followup)
- `tests/integration/test_allocator_phase1.py` — 4 skip tests enable
- 신규 `tests/integration/test_allocator_phase2b.py` — adaptive N + ENB greedy 통합 검증

### 제외 (Phase 3+)

- Bond TIPS path (`_select_bond_with_tips_quota`) 의 impl_score 4-요소 통합 — 별도 작은 followup 또는 Phase 3 NCO 도입 시 자연 해결
- NCO + Black-Litterman backbone (Phase 3)
- Ledoit-Wolf nonlinear shrinkage (Phase 4)
- ENB threshold 차단 동작 (현재 warning-only, Phase 4)
- `expense_ratio` 추가 (5-요소 composite, Phase 4)
- KRX endpoint discovery (Phase 2a 의 운영 issue, 별도)
- Schema 변경 (BucketTarget, WeightVector, FactorPanel 등)

## Architecture

Phase 2b 는 종목 선정 알고리즘을 ENB greedy forward selection 으로 교체. 종목 수가 bucket 별로 자동 결정. Stage 1 correlation_clusters 와 underlying_index merge 는 명시적으로 사용 안 함 — ENB greedy 가 같은 underlying ETF (corr ≈ 1) 의 ΔENB ≈ 0 으로 자동 배제.

```
[Stage 1 + Stage 2 입력]
        │
        ▼
①  eligibility + returns matrix              (기존)
        │
        ▼
②  alpha 점수 계산 (Phase 2a impl_score)      (기존)
        │
        ▼
③  ETF metrics fetch (Phase 2a)              (기존)
        │
        ▼
④  [NEW] sigma 계산 (sample_cov) + capital 추출
   │   sigma = returns.cov() 또는 sample_cov(returns)
   │   capital_krw = state.get("capital_krw") or 1_000_000_000
        │
        ▼
⑤  [REPLACED] ENB greedy selection per bucket
   │   for each bucket:
   │     n_max = compute_adaptive_n_max(positive_alpha, weight, capital)
   │     composite = alpha_impl_blend × z(alpha) + (1 - blend) × z(impl)
   │     selected = [composite top-1]
   │     while pool and len(selected) < n_max:
   │       j* = argmax_j ΔENB(selected ∪ {j})
   │       if ΔENB < threshold and len ≥ n_min: stop
   │       selected.append(j*)
        │
        ▼
⑥  cash spillover (Phase 1)                   (기존)
        │
        ▼
⑦  method_picker → optimize → ENB measure     (기존)
        │
        ▼
[Stage 4 로 전달]
```

**Schema 정책**: `BucketTarget`, `WeightVector`, `OptimizationMethod`, `ETFEntry`, `FactorPanel` 변경 없음. `attribution` dict 확장 (`selection_trace` per bucket).

**Backward compatibility**:
- `per_bucket_n` 인자 — 시그니처에서 제거. 호출처 1곳 (allocator) 만 영향.
- `select_cluster_aware` 함수명 — `select_by_enb_greedy` 로 rename + 시그니처 변경 (cluster 정보 인자 제거).
- attribution `per_bucket_n` 키 제거, 새 `selection_strategy="enb_greedy"`.

## Components

### 변경 모듈 A: `factor_scorer.py` — `select_by_enb_greedy` + `compute_adaptive_n_max`

**Constants** (module level):
```python
ENB_DELTA_THRESHOLD: float = 0.15          # 한계효용 임계
ABS_MAX_PER_BUCKET: int = 8                # 절대 상한
MIN_POSITION_KRW: float = 50_000_000       # 5천만 원 per position
MIN_BUCKET_POSITION_RATIO: float = 0.025   # bucket weight 의 최소 position 비중 (2.5%)
N_MIN_HARD_FLOOR: int = 1                  # n_min
ALPHA_IMPL_BLEND_DEFAULT: float = 0.85     # composite score = 0.85α + 0.15 impl
```

**Public API**:

```python
def compute_adaptive_n_max(
    *,
    n_positive_alpha: int,
    bucket_weight: float,
    capital_krw: float,
) -> int:
    """n_max = min(4 cap).

    4 cap:
      n_positive_alpha                              # 양수 alpha 후보 수
      max(1, bucket_weight / 0.025)                 # 2.5% per position
      max(1, bucket_weight × capital / 50M KRW)     # 5천만 per position
      ABS_MAX_PER_BUCKET (=8)                       # 절대 상한

    bucket_weight = 0 시 즉시 0 반환.
    """


def select_by_enb_greedy(
    *,
    eligible: list[str],
    alpha_scores: dict[str, float],
    impl_scores: dict[str, float],
    sigma: pd.DataFrame,
    n_max: int,
    n_min: int = N_MIN_HARD_FLOOR,
    enb_delta_threshold: float = ENB_DELTA_THRESHOLD,
    alpha_impl_blend: float = ALPHA_IMPL_BLEND_DEFAULT,
    selection_trace: dict | None = None,
) -> list[str]:
    """Forward greedy ENB-incremental selection.

    1. Pool = {t in eligible | alpha_scores[t] > 0}  (alpha floor, Phase 1 정신)
    2. Composite(t) = blend × z(alpha) + (1 - blend) × z(impl)
    3. Seed = composite top-1
    4. While pool and len < n_max:
         j* = argmax_j (ENB(selected ∪ {j}) - ENB(selected))
         if ΔENB < threshold and len ≥ n_min: break
         selected.append(j*)
    5. selection_trace dict 채움 (제공 시).
    """
```

**의존**: `tradingagents.skills.portfolio.diversification.compute_enb`, `_rank_normalize` (기존), numpy, pandas.

**기존 함수 처리**:
- `select_cluster_aware` 삭제 (rename → `select_by_enb_greedy` + 시그니처 변경)
- `_corr_groups` 삭제 (cluster grouping 명시적 사용 안 함)
- `select_diverse` 유지 — bond TIPS path 에서 여전히 사용 (Phase 2b scope 외)

### 변경 모듈 B: `candidate_selector.py`

**시그니처 확장**:
```python
def select_etf_candidates(
    universe: Universe,
    bucket_target: BucketTarget,
    as_of: date,
    *,
    returns: pd.DataFrame,
    factor_panel: dict[str, FactorPanel],
    sigma: pd.DataFrame,                          # NEW (Phase 2b)
    capital_krw: float,                           # NEW
    # 제거: per_bucket_n
    correlation_threshold: float = 0.85,          # bond TIPS path 에서만 사용 (select_diverse)
    longlist_multiplier: int = 3,
    dominant_scenario: str | None = None,
    attribution: dict | None = None,
    normalization: str = "rank_percentile",
    boost_scale: float = DEFAULT_BOOST_SCALE,
    risk_adjusted: dict | None = None,
    trend_quant: dict | None = None,
    extended: dict | None = None,
    etf_states: dict | None = None,
    clusters: list | None = None,                  # 인자는 유지 (호환), 무시 (사용 안 함)
    factor_scores: dict[str, float] | None = None,
) -> CandidateSet:
```

본문에서 기존 `select_cluster_aware(...)` 호출을 다음으로 교체:

```python
# Adaptive n_max per bucket
n_positive_alpha = sum(1 for a in alpha_scores.values() if a > 0)
n_max = compute_adaptive_n_max(
    n_positive_alpha=n_positive_alpha,
    bucket_weight=bucket_weight,
    capital_krw=capital_krw,
)

# Sigma slice for ENB
bucket_eligible = [e.ticker for e in eligible]
sigma_sub = sigma.loc[bucket_eligible, bucket_eligible]

selection_trace = {}
chosen = select_by_enb_greedy(
    eligible=bucket_eligible,
    alpha_scores=alpha_scores,
    impl_scores=impl_scores,
    sigma=sigma_sub,
    n_max=n_max,
    selection_trace=selection_trace,
)

bucket_to_tickers[bucket_name] = chosen
if bucket_attr is not None:
    bucket_attr["selection_trace"] = selection_trace
```

**Bond bucket** (`_select_bond_with_tips_quota`): Phase 2b scope 외. 기존 `_rank_by_factors` + `select_diverse` 유지.

### 변경 모듈 C: `portfolio_allocator.py`

allocator node 변경:
```python
# 기존 per_bucket_n 결정 블록 (라인 ~108-114) 전체 삭제:
# per_bucket_n = 4
# if research_decision conviction low: per_bucket_n = 5
# if attempts > 0: per_bucket_n = max(per_bucket_n + 2, 6)

# returns matrix 산출 후 (returns 가 None/empty 검증 통과 직후) 추가:
sigma = risk_models.sample_cov(returns)  # 이미 _optimize_with_bucket_constraints 에서 사용하므로 동일 패턴
capital_krw = float(state.get("capital_krw") or state.get("capital") or 1_000_000_000)

# select_etf_candidates 호출 (라인 ~211) 수정:
candidates = select_etf_candidates(
    universe, bucket_target, as_of,
    returns=returns,
    factor_panel=factor_panel,
    sigma=sigma,                # NEW
    capital_krw=capital_krw,    # NEW
    # 기존 인자들 그대로 (per_bucket_n 제거)
    ...
)
```

attribution 변경:
```python
# 제거:
# attribution["config"]["per_bucket_n"] = per_bucket_n

# 추가:
attribution["config"]["selection_strategy"] = "enb_greedy"
attribution["config"]["capital_krw"] = capital_krw
attribution["config"]["enb_delta_threshold"] = ENB_DELTA_THRESHOLD
attribution["config"]["abs_max_per_bucket"] = ABS_MAX_PER_BUCKET
```

`_optimize_with_bucket_constraints` 의 sigma 인자 영향 검토 — 이미 Phase 1 에서 sigma_df 반환하도록 변경됨. allocator 가 산출한 sigma 를 그대로 재사용 가능 (또는 _optimize 내부에서 별도 산출 — Phase 1 패턴 유지). 결정: **allocator 가 sigma 한 번 계산해서 둘 다에 사용** (DRY + 일관).

### 신규 모듈 D: `tests/integration/_allocator_state_helpers.py`

Allocator state dict 합성 builder. allocator node 가 read 하는 모든 키 채움.

```python
"""Allocator state mocking helpers (Phase 2b followup).

allocator node 가 기대하는 state dict 합성. 4 skip tests enable.
"""
from datetime import date
from pathlib import Path

import math
import numpy as np
import pandas as pd

from tradingagents.dataflows.universe import ETFEntry, Universe
from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills.portfolio.factor_scorer import FactorPanel


BUCKET_CATEGORIES: dict[str, tuple[str, str, str | None]] = {
    "kr_equity":     ("국내주식_지수",          "위험", None),
    "global_equity": ("해외주식_지수",          "위험", None),
    "fx_commodity":  ("FX 및 원자재",          "위험", "gold"),
    "bond":          ("국내채권_종합",          "안전", "nominal"),
    "cash_mmf":      ("금리연계형/초단기채권",  "안전", None),
}


def make_synthetic_universe(
    n_per_bucket: int = 4,
    base_aum: float = 50_000_000_000,
) -> Universe:
    """5 bucket × n_per_bucket ETFs. underlying_index unique per ticker."""

def make_underlying_duplicate_universe(
    bucket: str = "global_equity",
    n_duplicates: int = 3,
    base_aum: float = 50_000_000_000,
) -> Universe:
    """같은 underlying_index 의 duplicate ETF n개 + 다른 bucket 1개씩."""

def make_synthetic_returns(
    tickers: list[str],
    n_days: int = 252,
    vol: float = 0.02,
    correlation_pairs: list[tuple[str, str]] | None = None,
    seed: int = 42,
) -> pd.DataFrame: ...

def make_factor_panel(
    tickers: list[str],
    aum_by_ticker: dict[str, float] | None = None,
    alpha_overrides: dict[str, float] | None = None,
) -> dict[str, FactorPanel]: ...

def make_bucket_target(
    *, kr_equity: float = 0.20, global_equity: float = 0.20,
    fx_commodity: float = 0.15, bond: float = 0.30, cash_mmf: float = 0.15,
    bond_tips_share: float = 0.0, rationale: str = "test",
) -> BucketTarget: ...

# 외부 schema (research, macro, risk, technical) 도 비슷한 패턴
def make_research_decision(...) -> "ResearchDecision": ...
def make_macro_report(...) -> "MacroReport": ...
def make_risk_report(...) -> "RiskReport": ...
def make_technical_report(...) -> "TechnicalReport": ...

def make_allocator_state(
    *,
    as_of: date,
    universe_path: str,
    bucket_target: BucketTarget,
    technical_report,
    macro_report,
    risk_report,
    research_decision,
    capital_krw: float = 1_000_000_000,
    allocation_feedback: list | None = None,
    allocation_attempts: int = 0,
) -> dict:
    """allocator node 가 read 하는 state dict."""
```

### 변경 모듈 E: `tests/integration/test_allocator_phase1.py` — 4 skip enable

각 test 의 `@pytest.mark.skip` 데코레이터 제거 + state builder 활용한 실제 구현 (Section 4 의 Phase 2b design 참고).

4 tests:
- `test_allocator_with_normal_universe` — 5 bucket 양수 충분 → spillover ≈ 0, ENB > 2.0
- `test_allocator_with_fx_negative_only` — fx alpha 음수 → bucket weight 감소
- `test_allocator_with_global_low_conviction` — global alpha 낮음 → 부분 spillover
- `test_allocator_cash_overflow_redistribution` — 다중 spillover → cash > 40% → overflow → high-conv

### 신규 모듈 F: `tests/integration/test_allocator_phase2b.py`

Phase 2b 특화 통합 검증:
- `test_adaptive_n_max_small_bucket_uses_capacity_cap` — kr_equity 10% × 1B = 100M capital → n_max=2
- `test_adaptive_n_max_large_bucket_uses_abs_max` — bond 30% × 1B = 300M → 6, but abs cap 8 검증
- `test_enb_greedy_stops_at_delta_threshold` — ΔENB < 0.15 시 stop
- `test_enb_greedy_attribution_has_progression` — selection_trace 모든 키 채움
- `test_enb_greedy_underlying_duplicate_picks_one` — corr 0.99 ETF 3개 → 1개만 chosen

## ENB Greedy 알고리즘

### Pseudo-code

```python
def select_by_enb_greedy(*, eligible, alpha_scores, impl_scores, sigma,
                         n_max, n_min=1, enb_delta_threshold=0.15,
                         alpha_impl_blend=0.85, selection_trace=None):
    # 1. Alpha floor — Phase 1 정신
    pool = [t for t in eligible if alpha_scores.get(t, 0.0) > 0]
    if not pool:
        if selection_trace is not None:
            selection_trace["stop_reason"] = "no_positive_alpha"
            selection_trace["enb_progression"] = []
            selection_trace["rejected"] = [
                {"ticker": t, "reason": "alpha_negative"} for t in eligible
                if alpha_scores.get(t, 0.0) <= 0
            ]
        return []

    if n_max <= 0:
        if selection_trace is not None:
            selection_trace["stop_reason"] = "capacity_zero"
            selection_trace["enb_progression"] = []
            selection_trace["rejected"] = []
        return []

    # 2. Composite score
    z_alpha = _rank_normalize({t: alpha_scores[t] for t in pool})
    z_impl  = _rank_normalize({t: impl_scores.get(t, 0.0) for t in pool})
    composite = {
        t: alpha_impl_blend * z_alpha[t] + (1 - alpha_impl_blend) * z_impl[t]
        for t in pool
    }
    pool.sort(key=lambda t: composite[t], reverse=True)

    # 3. Seed
    selected = [pool.pop(0)]
    progression = [{"step": 0, "ticker": selected[0], "enb": 1.0}]
    rejected_deltas: list[dict] = []

    # 4. Greedy forward
    stop_reason = "pool_exhausted"
    while pool and len(selected) < n_max:
        prev_enb = _enb_equal_weight(selected, sigma)
        best_t, best_delta = None, -float("inf")
        for j in pool:
            candidate_set = selected + [j]
            try:
                new_enb = _enb_equal_weight(candidate_set, sigma)
            except Exception as e:
                logger.warning("enb compute failed for %s: %s", j, e)
                continue
            delta = new_enb - prev_enb
            if delta > best_delta:
                best_delta, best_t = delta, j

        if best_t is None:
            stop_reason = "numerical_failure"
            break

        if best_delta < enb_delta_threshold and len(selected) >= n_min:
            stop_reason = "delta_below_threshold"
            rejected_deltas.extend(
                {"ticker": t, "reason": "delta_too_small", "delta": best_delta}
                for t in pool
            )
            break

        selected.append(best_t)
        pool.remove(best_t)
        progression.append({
            "step": len(selected) - 1, "ticker": best_t,
            "enb": prev_enb + best_delta, "delta": best_delta,
        })
    else:
        # while pool 이 빈 경우는 stop_reason="pool_exhausted"
        # while len ≥ n_max 인 경우는 아래 처리
        if len(selected) >= n_max:
            stop_reason = "n_max_reached"

    # 5. Trace
    if selection_trace is not None:
        selection_trace["stop_reason"] = stop_reason
        selection_trace["enb_progression"] = progression
        rejected = [
            {"ticker": t, "reason": "alpha_negative"} for t in eligible
            if alpha_scores.get(t, 0.0) <= 0
        ]
        rejected.extend(rejected_deltas)
        selection_trace["rejected"] = rejected
        selection_trace["alpha_impl_blend_used"] = alpha_impl_blend

    return selected
```

### Equal-weight ENB

```python
def _enb_equal_weight(selected: list[str], sigma: pd.DataFrame) -> float:
    n = len(selected)
    if n == 0:
        return 0.0
    if n == 1:
        return 1.0
    sub_sigma = sigma.loc[selected, selected]
    equal_w = {t: 1.0 / n for t in selected}
    return compute_enb(equal_w, sub_sigma, method="minimum_torsion")
```

비중 미결정 단계라 equal-weight 가정. 실제 비중은 이후 stage (HRP/MIN_VAR 등).

### Composite 가중치 `alpha_impl_blend`

- Default: 0.85 (85% alpha, 15% impl)
- 동일 underlying ETF 군 (alpha 거의 같음) → impl 차이로 vehicle 선택
- backtest tuning 대상

### Adaptive `n_max` 공식

```python
def compute_adaptive_n_max(*, n_positive_alpha, bucket_weight, capital_krw):
    if bucket_weight <= 0:
        return 0
    weight_cap = max(1, int(bucket_weight / MIN_BUCKET_POSITION_RATIO))
    capital_cap = max(1, int(bucket_weight * capital_krw / MIN_POSITION_KRW))
    return min(
        max(0, n_positive_alpha),
        weight_cap,
        capital_cap,
        ABS_MAX_PER_BUCKET,
    )
```

**예시** (1B KRW 자본, default constants):

| bucket | weight | positive_alpha | weight_cap | capital_cap | abs | n_max |
|---|---|---|---|---|---|---|
| kr_equity | 0.10 | 12 | 4 | 2 | 8 | **2** (capital) |
| global_equity | 0.08 | 18 | 3 | 1 | 8 | **1** (capital) |
| fx_commodity | 0.18 | 1 | 7 | 3 | 8 | **1** (alpha) |
| bond | 0.31 | 14 | 12 | 6 | 8 | **6** (capital) |
| cash_mmf | 0.32 | 0 | 12 | 6 | 8 | **0** (alpha) |

총 ≈ 10 종목 (현 20+ 대비 절반).

### Stop Condition

| 조건 | stop_reason |
|---|---|
| len(selected) >= n_max | `"n_max_reached"` |
| best_delta < ENB_DELTA_THRESHOLD AND len ≥ n_min | `"delta_below_threshold"` |
| not pool (모든 후보 추가) | `"pool_exhausted"` |
| not pool_with_positive_alpha (양수 없음) | `"no_positive_alpha"` |
| n_max ≤ 0 (capacity 0) | `"capacity_zero"` |
| compute_enb 전체 실패 | `"numerical_failure"` |

### Attribution 확장

```python
attribution["buckets"][bucket_name]["selection_trace"] = {
    "n_max_components": {
        "n_positive_alpha": int,
        "weight_cap": int,
        "capital_cap": int,
        "abs_max": int,
        "n_max_chosen": int,
    },
    "enb_progression": [
        {"step": 0, "ticker": str, "enb": float},
        {"step": 1, "ticker": str, "enb": float, "delta": float},
        ...
    ],
    "stop_reason": str,
    "rejected": [
        {"ticker": str, "reason": "alpha_negative"},
        {"ticker": str, "reason": "delta_too_small", "delta": float},
    ],
    "alpha_impl_blend_used": float,
}
```

## State Mocking Helpers + Skip Tests Enable

Section 4 of design — Phase 1 의 4 skip tests 의 actual implementation patterns. 외부 의존성 없이 (LLM, KRX, pykrx 모두 mock 또는 합성) 풀 파이프라인 검증.

### 의도적 제한

- KRX OpenAPI — `monkeypatch` 로 `fetch_etf_metrics_window` 가 빈 DataFrame 반환. impl_score 가 log_aum 단독 fallback (Phase 2a 의 graceful path).
- LLM 호출 — Stage 2 결과를 `state["research_decision"]` 직접 주입.
- pykrx — returns 합성으로 skip.

## Error Handling

Phase 1, 2a 의 fail-loud 정신 일관. ENB greedy 는 외부 의존 없음.

| 상황 | 처리 |
|---|---|
| sigma 에 ticker 누락 | warning + 그 ticker pool 에서 제거 |
| compute_enb numerical 실패 | warning + 후보의 delta = 0 (다른 시도) |
| n_max = 0 | `[]` 반환, stop_reason="capacity_zero" |
| 양수 alpha 없음 | `[]` 반환, cash spillover 자연 처리 |
| bucket_weight = 0 | n_max = 0 즉시 반환 |
| capital_krw ≤ 0 | `RuntimeError` |
| state["capital_krw"] 없음 | 1_000_000_000 default (backward compat) |

## Backward Compatibility

- `per_bucket_n` 인자 — `select_etf_candidates` 시그니처에서 제거. 호출처 1 곳 (allocator) 만 영향, 동시 update. 테스트 fixture 호출도 update.
- `select_cluster_aware` 함수 — `select_by_enb_greedy` 로 rename + 시그니처 변경. **clean break**.
- `_corr_groups` 함수 — 삭제. 호출처 없음 (cluster-aware 안에서만 사용됨).
- `select_diverse` 함수 — **유지**. bond TIPS path 에서 사용.
- attribution `per_bucket_n` 키 → `selection_strategy` + `capital_krw` 등으로 대체. Stage 6 narrative 가 옛 키 참조 시 영향 — 별도 점검.
- 기존 attribution `selection_trace` 키 — Phase 1 의 cluster-aware 가 일부 채웠음. 새 schema 로 덮어씀 (필드 다름).

## Testing Strategy

### A. Unit tests — ENB greedy 핵심

**`tests/unit/skills/test_portfolio_factor_scorer.py`** 신규 추가:
- `test_compute_adaptive_n_max_capital_cap`
- `test_compute_adaptive_n_max_alpha_cap`
- `test_compute_adaptive_n_max_weight_cap`
- `test_compute_adaptive_n_max_abs_max`
- `test_compute_adaptive_n_max_zero_bucket_weight`
- `test_select_by_enb_greedy_seed_from_top_composite`
- `test_select_by_enb_greedy_stops_at_delta_threshold`
- `test_select_by_enb_greedy_stops_at_n_max`
- `test_select_by_enb_greedy_alpha_floor_only_positive`
- `test_select_by_enb_greedy_handles_no_positive_alpha`
- `test_select_by_enb_greedy_duplicates_picked_once`
- `test_select_by_enb_greedy_attribution_progression_recorded`
- `test_select_by_enb_greedy_alpha_impl_blend_weighting`

### B. Unit tests — 기존 회귀

**`tests/unit/skills/test_portfolio_candidate.py`** update:
- 기존 `per_bucket_n` 사용 케이스 → `sigma`, `capital_krw` 인자로 변경
- 새 케이스 `test_select_etf_candidates_adaptive_n_caps_small_capital`
- 새 케이스 `test_select_etf_candidates_attribution_records_selection_trace`

### C. Integration tests

**`tests/integration/test_allocator_phase1.py`** — 4 skip enable (Section 4)

**`tests/integration/test_allocator_phase2b.py`** 신규 — Phase 2b 특화

**`tests/integration/test_plan_pipeline_mock.py`, `test_5_28_dry_run.py`** — sigma 인자 영향 회귀

### D. 회귀 시나리오

`scripts/regression_compare.py` 그대로 + 추가 acceptance 확인 (n_total, selection_trace).

## Acceptance Criteria

regression_compare 의 exit 0/1 판정:

Phase 1, 2a 동일:
- (a) Sharpe degradation ≤ 5%
- (b) Volatility ≤ +2%
- (c) attribution[cash_spillover, enb, etf_metrics_summary, bucket_target_stage2] 채워짐

Phase 2b 신규:
- (d) `attribution["buckets"][b]["selection_trace"]["enb_progression"]` — 양수 alpha 있는 bucket 모두 채워짐
- (e) `attribution["buckets"][b]["selection_trace"]["stop_reason"]` — 유효 값
- (f) **n_total_new ≤ n_total_baseline × 1.1** (종목 수 감소 또는 동등, Phase 1 baseline 20+ → Phase 2b 10-15 예상)
- (g) 작은 bucket (weight < 0.10) 의 chosen 종목 수 ≤ 2 (capital cap 작동)

**Fail Recovery**:
- (f) 미충족: `ENB_DELTA_THRESHOLD` 상향 (0.15 → 0.20)
- (g) 미충족: `MIN_BUCKET_POSITION_RATIO` / `MIN_POSITION_KRW` 조정
- (a) Sharpe degradation: `alpha_impl_blend` 0.85 → 0.90 (alpha 가중 강화)

## Out of Scope / Future Phases

- **Phase 3**: NCO + Black-Litterman backbone. `OptimizationMethod` 단일화. Bond TIPS path 자연 통합.
- **Phase 4**: Ledoit-Wolf nonlinear shrinkage, regime → (δ, c, τ) tilt, ENB threshold 차단, expense_ratio 5-요소 composite, regression criterion (d) fragility 개선
- **KRX endpoint discovery**: 운영 issue (Phase 2a known limitation), 별도 작업
- **Bond TIPS impl_score 4-요소 통합**: 별도 작은 followup 또는 Phase 3

## Open Questions

없음 (모든 design decision 확정). 구현 세부 ordering 은 별도 implementation plan.
