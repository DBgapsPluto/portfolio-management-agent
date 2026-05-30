# Stage 3 Phase 3a — NCO (Nested Clustered Optimization) Bucket-Internal Design

**Date**: 2026-05-30
**Status**: Design (awaiting user review)
**Author**: Brainstorming session

## Goal

기존 5 method (EF/HRP/MIN_VAR/RISK_PARITY/MAX_SHARPE) 와 **공존**하는 NCO (Nested Clustered Optimization, Lopez de Prado 2019) optimizer 신규 도입. 5 bucket 각각의 chosen 종목들에 hierarchical clustering + intra-cluster CVO + reduced Σ + inter-cluster CVO 적용. parallel optimizer 로 A/B 테스트 가능, Phase 3c 에서 cutover.

## Context

- **Phase 1 (c0be9b2, 2026-05-28)** 완료: cash spillover, ENB warning, AUM 필터 제거
- **Phase 2a (1993d6c, 2026-05-29)** 완료: impl_score 4-요소 (KRX endpoint fallback)
- **Phase 2b (9bd46c9, 2026-05-30)** 완료: ENB greedy + adaptive n_max + state mocking helpers. n_total 50% 감소 (18→9)
- **현재 backbone 한계** ([Phase 1 평가](../specs/2026-05-28-stage3-phase1-cash-spillover-design.md)):
  1. HRP 의 hierarchical recursive bisection 은 cluster info 활용이 제한적
  2. EF 의 max_sharpe 가 mean_historical mu 에 매우 sensitive (noise → alpha 착각)
  3. method_picker 의 scenario-별 swap 이 backtest 비교 어려움
- **NCO 의 장점** (Lopez de Prado 2019, *MLAM* §7.6):
  1. signal-induced instability 에 robust (Markowitz 보다)
  2. hierarchical structure 가 cluster duplicate 자동 처리
  3. Phase 2b ENB greedy 결과 (양수 alpha + ΔENB > 0.15) 와 자연 호환

## Scope

### 포함

- 신규 모듈 `tradingagents/skills/portfolio/nco.py` — NCO 알고리즘 (compute_nco_weights, hierarchical cluster, intra/inter CVO, opt_port 폐쇄형)
- `tradingagents/schemas/portfolio.py` — `OptimizationMethod.NCO` enum 값 추가
- `tradingagents/agents/allocator/portfolio_allocator.py` — `_nco_per_bucket` helper + `_optimize_with_bucket_constraints` 의 NCO 분기 + `state["force_method"]` A/B 메커니즘
- `tests/unit/skills/test_portfolio_nco.py` (신규)
- `tests/integration/test_allocator_phase3a.py` (신규)

### 제외 (Phase 3b/3c+)

- BL views adapter (Phase 3b): alpha → Q, Idzorek-Walters Ω 폐쇄형
- method_picker → tilt dial (Phase 3c): regime → (δ, c, τ)
- 기존 5 method 폐기 (Phase 3c)
- Ledoit-Wolf shrinkage (Phase 4)
- expense_ratio 5-요소 composite (Phase 4)
- regression criterion (d) fragility 개선 (Phase 4)
- Schema 변경 (`BucketTarget`, `WeightVector`, `ETFEntry`, `FactorPanel`)

## Architecture

NCO 가 **bucket 내부 optimizer** 로 작동 — 5 bucket 각각 안에서 hierarchical clustering + intra/inter CVO. Bucket 간 weight 는 `bucket_target` 비례 (HRP-per-bucket 패턴 동일). Phase 1 의 spillover, Phase 2b 의 ENB greedy 그대로 호환.

```
[bucket × chosen 종목들 (Phase 2b 결과)]
        │
        ▼
①  bucket sub-cov 추출 (returns.cov() 의 부분행렬)
        │
        ▼
②  Hierarchical clustering
   │   distance = √((1-corr)/2)
   │   linkage = single
   │   silhouette score → best k ∈ [2, n//2]
        │
        ▼
③  Intra-cluster CVO
   │   cluster 안에서 min-var (mu=None) 또는 max-sharpe (mu given)
   │   intra_weights (n_assets × n_clusters)
        │
        ▼
④  Reduced Σ̂ = intra.T @ Σ @ intra
        │
        ▼
⑤  Inter-cluster CVO
   │   reduced Σ̂ 에 min-var/max-sharpe → cluster allocations
        │
        ▼
⑥  Final = intra @ inter
   │   (single_asset_cap clip + 재정규화)
        │
        ▼
[bucket-level weight vector]
```

**Schema 정책**: `OptimizationMethod` enum 만 확장 (`NCO = "nco"`). `BucketTarget`, `WeightVector`, `ETFEntry`, `FactorPanel` 변경 없음. `attribution` dict 확장 (`nco_breakdown` per bucket).

**A/B 테스트 메커니즘**:
- (i) **테스트 환경**: `MethodChoice` 직접 주입 (단위/통합 테스트)
- (ii) **운영 A/B**: `state["force_method"] = "nco"` 시 method_picker override. attribution 에 `"rule_fired": "state_override"`.

**Backward compatibility**:
- 기존 5 method 동작 변경 없음. NCO 는 추가 옵션.
- `method_picker` 변경 없음 → 기존 rule 동일 결과. NCO 는 force_method 또는 향후 Phase 3c 의 cutover 시 활성화.
- `WeightVector.method = "nco"` 값을 다운스트림 (risk_judge, validator, narrative) 이 처리하는지 점검 (known limitation).

**의존성**: scipy.cluster.hierarchy (linkage, fcluster), scipy.spatial.distance (squareform), sklearn.metrics (silhouette_score), numpy, pandas, pypfopt (risk_models).

## Components

### 신규 모듈 A: `tradingagents/skills/portfolio/nco.py`

**책임**: NCO 알고리즘 + hierarchical clustering + closed-form CVO.

**Constants** (module level):
```python
NCO_MAX_NUM_CLUSTERS_RATIO: float = 0.5
NCO_MIN_NUM_CLUSTERS: int = 2
NCO_LINKAGE_METHOD: str = "single"
NCO_MIN_VAR_REGULARIZATION: float = 1e-8
```

**Public API**:
```python
def compute_nco_weights(
    returns: pd.DataFrame,
    mu: pd.Series | None = None,
    max_num_clusters: int | None = None,
    breakdown_out: dict | None = None,
) -> pd.Series:
    """NCO weights (Lopez de Prado 2019).

    1. Hierarchical clustering (1-corr distance)
    2. Intra-cluster CVO (min-var if mu=None, else max-sharpe)
    3. Reduced Σ̂ = intra.T @ Σ @ intra
    4. Inter-cluster CVO on reduced Σ̂
    5. Final = intra @ inter

    Args:
        returns: ticker × date returns DataFrame (columns=tickers).
        mu: expected returns Series. None → min-var. Phase 3a default None.
        max_num_clusters: silhouette 평가 최대 k. None → max(2, int(n × 0.5)).
        breakdown_out: 제공 시 dict 채움 (n_clusters, silhouette, cluster_labels,
            intra_weights, inter_weights, mu_provided).

    Returns:
        ticker → weight Series (sum=1, weight >= 0).

    Raises:
        ValueError: n_assets < 2.
    """


def _hierarchical_cluster(
    corr: pd.DataFrame,
    max_num_clusters: int,
) -> tuple[np.ndarray, float | None]:
    """Single-linkage clustering on √((1-corr)/2) distance.

    silhouette score 평가 후 best k 선택. 단일 cluster fallback 시 silhouette=None.
    """


def _intra_cluster_weights(
    cov: pd.DataFrame,
    labels: np.ndarray,
    mu: pd.Series | None = None,
) -> pd.DataFrame:
    """n_assets × n_clusters DataFrame. ticker 는 자기 cluster 의 column 에만 non-zero."""


def _inter_cluster_weights(
    reduced_cov: pd.DataFrame,
    reduced_mu: pd.Series | None = None,
) -> pd.Series:
    """Inter-cluster CVO."""


def _opt_port(
    cov: pd.DataFrame,
    mu: pd.Series | None = None,
) -> pd.Series:
    """Closed-form CVO (long-only normalized).

    mu=None → min-var: w = (Σ + εI)^(-1) × 1 / (1^T (Σ + εI)^(-1) 1)
    mu given → max-sharpe: w = (Σ + εI)^(-1) × μ / (1^T (Σ + εI)^(-1) μ)

    음수 weight clip + 재정규화 (long-only).
    cov singular 시 equal weight fallback.
    """
```

**의존**: scipy.cluster.hierarchy, scipy.spatial.distance, sklearn.metrics, numpy, pandas.

### 변경 모듈 B: `tradingagents/schemas/portfolio.py`

```python
class OptimizationMethod(str, Enum):
    MIN_VARIANCE = "min_variance"
    RISK_PARITY = "risk_parity"
    MAX_SHARPE = "max_sharpe"
    BLACK_LITTERMAN = "black_litterman"
    HRP = "hrp"
    NCO = "nco"   # NEW (Phase 3a)
```

backward-compat: 기존 5 값 유지. Pydantic 자동 JSON 처리.

### 변경 모듈 C: `tradingagents/agents/allocator/portfolio_allocator.py`

**신규 helper `_nco_per_bucket`** — HRP-per-bucket 패턴 따라 (`_hrp_per_bucket` 구조 참고):

```python
def _nco_per_bucket(
    returns: pd.DataFrame,
    candidates,
    bucket_target: BucketTarget,
    sub_category_lookup: dict[str, str | None] | None = None,
    attribution: dict | None = None,
) -> WeightVector:
    """NCO per bucket × bucket_target weight.

    각 bucket 의 chosen 종목들에 compute_nco_weights 호출 → bucket_target 비례
    scale → single asset cap (water-fill, HRP 코드 재사용) → 최종 normalize.
    bond bucket: bond_tips_share > 0 시 tips/nominal sub-pool 분리 (HRP 패턴 동일).
    """
```

**`_optimize_with_bucket_constraints` 분기 추가** (대략 line 521 부근):
```python
# HRP 분기 (기존)
if method == OptimizationMethod.HRP:
    wv = _hrp_per_bucket(...)
    return wv, sigma_df

# NCO 분기 (Phase 3a NEW)
if method == OptimizationMethod.NCO:
    wv = _nco_per_bucket(returns, candidates, bucket_target, sub_category_lookup,
                         attribution=attribution)
    sigma_df = ...  # HRP path 와 동일
    return wv, sigma_df

# 기존 EF/BL/MIN_VAR/RISK_PARITY/MAX_SHARPE path (변경 없음)
```

`MIN_COV_OBS` 데이터 reduction 은 NCO 에 적용 안 함 (NCO 가 bucket 별 sub-cov 사용 — HRP 와 동일 패턴).

**`state["force_method"]` 메커니즘** (`node` 함수 내부, method_picker 호출 전):
```python
# Phase 3a — method override (A/B 테스트용)
force_method = state.get("force_method")
if force_method is not None:
    method_choice = MethodChoice(
        method=OptimizationMethod(force_method),
        reasoning=f"forced via state['force_method']={force_method}",
        rule_fired="state_override",
        rule_index=-1,
        inputs={"force_method": force_method},
    )
else:
    method_choice = pick_optimization_method(...)
```

attribution 에 `attribution["method_picker"]["rule_fired"] = "state_override"` 로 가시화.

### 변경 모듈 D: `tradingagents/skills/portfolio/method_picker.py`

**변경 없음**. Phase 3c 에서 (δ, c, τ) 다이얼로 전환 시 변경.

### 신규 모듈 E: `tests/unit/skills/test_portfolio_nco.py`

13 단위 테스트 (NCO 알고리즘 + 헬퍼).

### 신규 모듈 F: `tests/integration/test_allocator_phase3a.py`

7 통합 테스트 (allocator NCO end-to-end).

## NCO 알고리즘 디테일

### Pseudo-code

```python
def compute_nco_weights(returns, mu=None, max_num_clusters=None, breakdown_out=None):
    n_assets = returns.shape[1]
    if n_assets < 2:
        raise ValueError(f"NCO requires >= 2 assets, got {n_assets}")

    # n=2 shortcut: cluster 의미 없음
    if n_assets == 2:
        cov = returns.cov()
        weights = _opt_port(cov, mu)
        if breakdown_out is not None:
            breakdown_out["n_clusters"] = 1
            breakdown_out["silhouette"] = None
            breakdown_out["cluster_labels"] = {t: 0 for t in returns.columns}
            breakdown_out["intra_weights"] = weights.to_dict()
            breakdown_out["inter_weights"] = {0: 1.0}
            breakdown_out["mu_provided"] = mu is not None
        return weights

    cov = returns.cov()
    corr = returns.corr().fillna(0.0)

    if max_num_clusters is None:
        max_num_clusters = max(NCO_MIN_NUM_CLUSTERS, int(n_assets * NCO_MAX_NUM_CLUSTERS_RATIO))
    max_num_clusters = min(max_num_clusters, n_assets - 1)

    labels, silh = _hierarchical_cluster(corr, max_num_clusters)

    intra_weights = _intra_cluster_weights(cov, labels, mu)

    reduced_cov_arr = intra_weights.values.T @ cov.values @ intra_weights.values
    reduced_cov = pd.DataFrame(
        reduced_cov_arr, index=intra_weights.columns, columns=intra_weights.columns,
    )

    reduced_mu = None
    if mu is not None:
        reduced_mu = pd.Series(
            intra_weights.values.T @ mu.reindex(intra_weights.index).fillna(0.0).values,
            index=intra_weights.columns,
        )

    inter_weights = _inter_cluster_weights(reduced_cov, reduced_mu)
    final = intra_weights.values @ inter_weights.values
    final_series = pd.Series(final, index=intra_weights.index)
    final_series = final_series / final_series.sum()

    if breakdown_out is not None:
        breakdown_out["n_clusters"] = int(len(set(labels)))
        breakdown_out["silhouette"] = float(silh) if silh is not None else None
        breakdown_out["cluster_labels"] = {
            ticker: int(label) for ticker, label in zip(returns.columns, labels)
        }
        breakdown_out["intra_weights"] = intra_weights.to_dict()
        breakdown_out["inter_weights"] = inter_weights.to_dict()
        breakdown_out["mu_provided"] = mu is not None

    return final_series
```

### Hierarchical Clustering

```python
def _hierarchical_cluster(corr, max_num_clusters):
    n = corr.shape[0]
    dist_matrix = np.sqrt(((1 - corr.values).clip(min=0)) / 2.0)
    np.fill_diagonal(dist_matrix, 0.0)
    cond_dist = squareform(dist_matrix, checks=False)
    Z = linkage(cond_dist, method=NCO_LINKAGE_METHOD)

    best_score = -np.inf
    best_labels = None
    for k in range(NCO_MIN_NUM_CLUSTERS, max_num_clusters + 1):
        labels = fcluster(Z, k, criterion="maxclust")
        if len(set(labels)) < 2:
            continue
        score = silhouette_score(dist_matrix, labels, metric="precomputed")
        if score > best_score:
            best_score = score
            best_labels = labels

    if best_labels is None:
        best_labels = np.ones(n, dtype=int)
        return best_labels, None

    return best_labels, best_score
```

### Closed-form CVO

```python
def _opt_port(cov, mu=None):
    n = cov.shape[0]
    sigma_reg = cov.values + np.eye(n) * NCO_MIN_VAR_REGULARIZATION

    try:
        inv_sigma = np.linalg.inv(sigma_reg)
    except np.linalg.LinAlgError:
        return pd.Series(np.ones(n) / n, index=cov.index)

    if mu is None:
        w_raw = inv_sigma @ np.ones(n)
    else:
        w_raw = inv_sigma @ mu.reindex(cov.index).fillna(0.0).values

    w_clipped = np.maximum(w_raw, 0.0)
    w_sum = w_clipped.sum()
    if w_sum > 0:
        w = w_clipped / w_sum
    else:
        w = np.ones(n) / n

    return pd.Series(w, index=cov.index)
```

### Intra-cluster Weights

```python
def _intra_cluster_weights(cov, labels, mu=None):
    tickers = list(cov.index)
    unique_clusters = sorted(set(labels))
    intra = pd.DataFrame(0.0, index=tickers, columns=unique_clusters)

    for k in unique_clusters:
        members = [tickers[i] for i, lbl in enumerate(labels) if lbl == k]
        if len(members) == 1:
            intra.loc[members[0], k] = 1.0
            continue
        cov_sub = cov.loc[members, members]
        mu_sub = mu.reindex(members) if mu is not None else None
        w = _opt_port(cov_sub, mu_sub)
        intra.loc[members, k] = w.values

    return intra
```

### Edge Cases

| 케이스 | 처리 |
|---|---|
| n=1 (단일 ticker) | `_nco_per_bucket` 가 `compute_nco_weights` 호출 안 함; weight=1.0 직접 |
| n=2 | 2-asset shortcut: _opt_port 직접 |
| 모든 corr ≈ 1 | silhouette 미평가, 1 cluster fallback → 내부 min-var |
| cov singular | regularization (ε=1e-8) → 실패 시 equal weight |
| mu 일부 NaN | reindex + fillna(0.0) neutral |
| sub_returns < 2 행 (cov 불가) | bucket skip + WARNING |
| bond TIPS split path 한쪽 빈 경우 | 기존 HRP 패턴: target 흡수 |
| single asset cap (20%) 초과 | water-fill iterate (HRP 코드 재사용) |
| 최종 weight sum != 1 | normalize (drift 1e-9 까지) |

### Attribution 확장 (allocator level)

```python
attribution["optimization"]["nco_breakdown"] = {
    "kr_equity": {
        "n_clusters": int,
        "silhouette": float | None,
        "cluster_labels": {ticker: int, ...},
        "intra_weights": {...},
        "inter_weights": {...},
        "mu_provided": bool,
    },
    "global_equity": {...},
    "fx_commodity": {...},
    "bond_tips": {...},   # bond split 시
    "bond_nominal": {...},
    "cash_mmf": {...},
}
```

## Allocator 통합

### `_optimize_with_bucket_constraints` 분기

`MIN_COV_OBS` 데이터 reduction 은 NCO 에 적용 안 함 (HRP 와 동일 패턴 — bucket 별 sub-cov 사용):

```python
if method not in (OptimizationMethod.HRP, OptimizationMethod.NCO) and len(returns) < MIN_COV_OBS:
    # data reduction (기존 동일)
    ...

S = risk_models.sample_cov(returns)

if method == OptimizationMethod.HRP:
    wv = _hrp_per_bucket(...)
    sigma_df = ...
    return wv, sigma_df

if method == OptimizationMethod.NCO:
    wv = _nco_per_bucket(returns, candidates, bucket_target, sub_category_lookup,
                         attribution=attribution)
    sigma_df = S if isinstance(S, pd.DataFrame) else pd.DataFrame(
        S, index=returns.columns, columns=returns.columns)
    return wv, sigma_df

# 기존 EF/BL/MIN_VAR/RISK_PARITY/MAX_SHARPE path...
```

### `state["force_method"]` A/B 메커니즘

```python
# node 함수 내부, method_picker 호출 전
force_method = state.get("force_method")
if force_method is not None:
    method_choice = MethodChoice(
        method=OptimizationMethod(force_method),
        reasoning=f"forced via state['force_method']={force_method}",
        rule_fired="state_override",
        rule_index=-1,
        inputs={"force_method": force_method},
    )
else:
    method_choice = pick_optimization_method(...)
```

attribution 에 `"rule_fired": "state_override"` 기록 — Phase 3a 의 A/B 테스트 가시화.

## Error Handling

Phase 1, 2a, 2b 의 fail-loud over fail-silent 정신 일관. NCO 는 외부 의존성 없음 — graceful degradation 일부 (regularization, equal-weight fallback).

| 상황 | 처리 |
|---|---|
| bucket 의 chosen 0개 | bucket 자체 skip (target 비례 0%) |
| bucket 의 chosen 1개 | `_nco_per_bucket` 가 weight=1.0 직접 (NCO 호출 안 함) |
| `compute_nco_weights` 의 cov singular | regularization → equal weight fallback |
| silhouette 평가 실패 (모두 1 cluster) | fallback: 1 cluster, log warning |
| sub_returns < 2 행 | bucket skip + WARNING |
| bond TIPS split 한쪽 빈 경우 | 기존 HRP 패턴 (target 흡수) |
| single asset cap (20%) 초과 | water-fill (HRP 코드 재사용) |
| `OptimizationMethod(force_method)` 잘못된 값 | `ValueError` (Pydantic enum) |

## Backward Compatibility

- 기존 5 method 동작 변경 없음. NCO 는 추가 옵션.
- `OptimizationMethod` enum 확장 — Pydantic 자동 JSON 처리. 기존 산출물 (Phase 1, 2a, 2b artifacts) 의 `method=hrp` 등 그대로 호환.
- `method_picker` 변경 없음 → 기존 rule (regime, scenario) 동일 결과. NCO 는 force_method 또는 Phase 3c cutover 시 활성화.
- `WeightVector.method = "nco"` 다운스트림 영향:
  - `risk_judge`: method enum 값 사용처 점검 (rationale 등)
  - `validator`: method 별 분기 없음 — 영향 없음
  - `reports`, `narrative`: method 값을 narrative 가 처리하는지 점검 (알 수 없는 method 시 generic fallback)
- `attribution.optimization.nco_breakdown` 신규 키만 추가 — 기존 키 변경 없음
- `state["force_method"]` 신규 키 — 기존 state 에 없으면 `None` → 기존 method_picker 동작

## Testing Strategy

### A. Unit tests — NCO 모듈

**`tests/unit/skills/test_portfolio_nco.py`** (신규, 13 테스트):

- `test_compute_nco_weights_uncorrelated_returns_equal_weight` — n=4 uncorrelated → equal weight (분석적)
- `test_compute_nco_weights_two_clusters_inter_balance` — 명시적 2 cluster → inter 균등
- `test_compute_nco_weights_perfectly_correlated_one_cluster` — corr ≈ 1 → 1 cluster fallback
- `test_compute_nco_weights_weights_sum_to_one` — invariant
- `test_compute_nco_weights_non_negative` — long-only
- `test_compute_nco_weights_with_mu_max_sharpe_path` — mu given → max-sharpe
- `test_compute_nco_weights_breakdown_out_recorded` — attribution 채움
- `test_compute_nco_weights_raises_when_insufficient_tickers` — n=1 → ValueError
- `test_compute_nco_weights_handles_n_equals_two` — n=2 shortcut
- `test_hierarchical_cluster_silhouette_picks_best_k` — silhouette 가 best k 선택
- `test_intra_cluster_weights_matrix_shape` — n_assets × n_clusters
- `test_opt_port_min_var_analytical` — 3-asset 분석적 검증
- `test_opt_port_handles_singular_cov` — equal weight fallback

### B. Integration tests

**`tests/integration/test_allocator_phase3a.py`** (신규, 7 테스트):

- `test_allocator_with_method_nco_runs_to_completion` — state["force_method"]="nco", weight sum=1
- `test_allocator_nco_attribution_records_breakdown` — `attribution.optimization.nco_breakdown` per bucket
- `test_allocator_nco_respects_single_asset_cap` — 20% 준수
- `test_allocator_nco_bucket_sum_approximates_target` — bucket weight ≈ bucket_target
- `test_allocator_nco_handles_single_ticker_bucket` — chosen 1 개 bucket 정상
- `test_allocator_nco_vs_hrp_same_inputs_different_weights` — 동일 입력에 NCO ≠ HRP
- `test_allocator_nco_with_correlated_etfs_uses_single_cluster` — 같은 underlying 1 cluster

### C. 회귀 tests

- 기존 method (HRP, EF 등) unit/통합 테스트 회귀 무손실
- `test_plan_pipeline_mock`, `test_5_28_dry_run` 등 method_picker 가 NCO 선택 안 하므로 영향 없음
- `test_allocator_phase1/2a/2b` 전체 통과

### D. E2E

`scripts/run_e2e_test.py --as-of 2026-05-15 --force-method nco` (인자 추가):
- 정상 종료
- `attribution.optimization.nco_breakdown` 채움
- `attribution.method_picker.rule_fired == "state_override"`
- weight sum = 1, single asset cap 20% 준수

regression_compare 는 force_method 없는 경우 기존 method 그대로 (회귀 무손실 검증).

## Acceptance Criteria

regression_compare 의 exit code + 별도 force_method 검증:

- (a) **회귀 무손실**: regression_compare 의 기존 acceptance (a)(b)(c) 모두 PASS (Phase 1, 2a, 2b 와 동일 — NCO 가 method_picker 에서 선택 안 됨)
- (b) **NCO unit tests**: 13개 모두 PASS
- (c) **NCO integration tests**: 7개 모두 PASS
- (d) **force_method E2E**: `scripts/run_e2e_test.py --force-method nco --as-of 2026-05-15` 정상 종료 + attribution.optimization.nco_breakdown 채워짐
- (e) **Phase 1+2a+2b 회귀**: 모든 기존 unit + integration tests PASS (337+ tests)

**Fail Recovery**:
- (a) 미충족 (회귀 손실): NCO 코드가 기존 path 에 영향 — diff 검토 후 NCO 분기 격리 강화
- (b)(c) 미충족: NCO 알고리즘 issue — unit test 추가 보강 후 재시도
- (d) 미충족: state["force_method"] 메커니즘 또는 attribution 구조 점검

## Out of Scope / Future Phases

- **Phase 3b**: BL views adapter (alpha → Q, Idzorek-Walters Ω 폐쇄형, c-confidence 다이얼)
- **Phase 3c**: method_picker → tilt dial (regime → (δ, c, τ)), 기존 5 method 폐기, OptimizationMethod 단일화
- **Phase 4**: Ledoit-Wolf nonlinear shrinkage, regime-conditional tilt, ENB threshold 차단, expense_ratio 5-요소 composite, regression criterion (d) fragility 개선

## Open Questions

없음 (모든 design decision 확정). NCO 의 max-sharpe path 는 mu 인자로 활성화되며 Phase 3a 의 default 는 min-var (mu=None). 구현 세부 ordering 은 별도 implementation plan.
