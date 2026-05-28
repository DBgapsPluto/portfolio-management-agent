# Stage 3 Phase 1 — Cash Spillover & Alpha Floor Design

**Date**: 2026-05-28
**Status**: Design (awaiting user review)
**Author**: Brainstorming session

## Goal

Stage 3 의 두 가지 구조적 누수를 차단한다:
1. **음수 alpha 강제 fill**: `require_positive_alpha=True` 임에도 양수 group 이 부족하면 음수 group 으로 슬롯을 채우던 fallback 메커니즘. 결과적으로 alpha 음수 자산이 portfolio 에 강제 편입되어 vol-low → HRP/Min-Vol 비중이 커지는 negative-carry drag.
2. **Bucket weight 절대화**: Stage 2 macro 결정이 `EF sector_constraints(equality)` 로 hard-enforce 되어, micro alpha 가 거부해도 bucket 채워야 하는 macro-micro 단절.

추가로 **AUM hard 필터를 제거**해 대회 universe (사전 큐레이션됨) 의 모든 종목을 후보 풀에 진입시킨다.

## Context

- **투자대회 (GAPS 12회) 에이전트** — universe 는 사전 정의된 188 ETF
- universe 분포: kr_equity 53, global_equity 78, fx_commodity 7, bond 41, cash_mmf 9
- 현 산출물 ([artifacts/2026-05-15/portfolio.json](../../../artifacts/2026-05-15/portfolio.json)) 에서 fx_commodity 17.6% 가 양수 alpha 1 + 음수 alpha 3 으로 채워짐 — 가장 큰 누수 사례
- Phase 2-4 는 별도 spec 으로 분리되어 점진 진행 예정

## Scope

### 포함

- AUM hard 필터 (`DEFAULT_MIN_AUM_KRW`, `_RELAXED_MIN_AUM_KRW`) 완전 제거
- `select_cluster_aware` 의 음수 alpha fill 분기 제거 (양수 group 부족 시 짧은 chosen 반환)
- 신규 모듈 `cash_spillover.py` — bucket conviction + bucket weight adjustment
- 신규 모듈 `diversification.py` — Effective Number of Bets (minimum-torsion) 측정
- allocator pipeline 에 2 개 hook 삽입 (candidate selection 직후 spillover, weight 산출 후 ENB)
- attribution dict 확장 (`cash_spillover`, `enb` 필드)

### 제외 (Phase 2+)

- impl_score 데이터 어댑터 (TE / 괴리율 / volume) — Phase 2
- ENB greedy forward selection — Phase 2
- Adaptive `per_bucket_n` — Phase 2
- NCO + Black-Litterman backbone — Phase 3
- Ledoit-Wolf nonlinear shrinkage — Phase 4
- Regime → (δ, c, τ) tilt — Phase 4
- ENB threshold 차단 동작 (Phase 1 은 warning-only) — Phase 4
- Schema 변경 (`BucketTarget`, `WeightVector`, `OptimizationMethod`) — 후속 Phase 에서 필요 시

## Architecture

기존 5-단계 파이프라인 (eligibility → alpha → cluster → optimize → validate) 의 **종목 선정 단계** 에 두 가지 누수를 차단하는 surgical 변경. 신규 모듈 2 개를 hook 으로 삽입, 기존 함수 한 곳의 fallback 분기 1 개를 제거. Schema 변경 없음.

```
[Stage 2 입력]
    │
    ▼
①  eligibility (AUM 필터 제거됨)        ← candidate_selector.py 변경
    │
    ▼
②  alpha 점수 계산                        (기존)
    │
    ▼
③  cluster + 대표 선정 (양수만)         ← factor_scorer.py 변경 (음수 fill 제거)
    │
    ▼
④  [NEW] cash spillover                  ← cash_spillover.py 신규
    │     bucket 별 conviction
    │     spillover_ratio = 1 - conviction/threshold
    │     cash overflow → high-conv bucket
    │
    ▼
⑤  method_picker                          (기존)
    │
    ▼
⑥  optimize (adjusted bucket_target)      (기존, 새 bucket_target)
    │
    ▼
⑦  [NEW] ENB 측정 (warning-only)         ← diversification.py 신규
    │     attribution["enb"] = ...
    │
    ▼
⑧  dust drop + sub_cat cap                (기존)
    │
    ▼
[Stage 4 로 전달]
```

## Components

### 신규 모듈 A: `tradingagents/skills/portfolio/cash_spillover.py`

**책임**: bucket 별 conviction 계산 + spillover 적용된 새 BucketTarget 반환

**Constants**:
```python
SPILLOVER_THRESHOLD_DEFAULT: float = 0.3
SPILLOVER_THRESHOLD_BY_BUCKET: dict[str, float] = {
    "fx_commodity": 0.15,    # universe 7 종목 구조적 한계 반영
}
CASH_CAP_FOR_SPILLOVER_TARGET: float = 0.40
```

**Pydantic schemas**:
```python
class ConvictionResult(BaseModel):
    bucket: str
    n_chosen: int
    mean_alpha: float
    enb: float
    threshold: float
    conviction: float
    spillover_ratio: float

class SpilloverResult(BaseModel):
    adjusted_bucket_target: BucketTarget
    convictions: dict[str, ConvictionResult]
    cash_overflow_to_buckets: dict[str, float]
    total_spillover_to_cash: float
    cash_cap_triggered: bool
    thresholds: dict[str, float]
```

**Public API**:
```python
def compute_bucket_conviction(
    bucket: str,
    chosen: list[str],
    alpha_scores: dict[str, float],
    returns: pd.DataFrame,
) -> ConvictionResult:
    """Bucket 의 conviction = (mean_alpha/threshold) × (ENB_equal_weight/√N).

    내부 처리:
    - `available = [t for t in chosen if t in returns.columns]`
    - `available` 비어있으면 ConvictionResult(n_chosen=0, mean_alpha=0,
      enb=0, conviction=0, spillover_ratio=1.0) 즉시 반환
    - `sigma = returns[available].dropna(axis=0, how="any").cov()`
    - `enb = compute_enb(equal_weights, sigma, method="minimum_torsion")`
    - threshold 는 SPILLOVER_THRESHOLD_BY_BUCKET.get(bucket, SPILLOVER_THRESHOLD_DEFAULT)
    """

def adjust_bucket_targets(
    bucket_target: BucketTarget,
    bucket_chosen: dict[str, list[str]],
    alpha_scores_by_bucket: dict[str, dict[str, float]],
    returns: pd.DataFrame,
) -> SpilloverResult:
    """5 개 bucket 모두에 대해 compute_bucket_conviction → 3-step redistribution.

    cash_mmf bucket 은 conviction 계산하되 spillover 대상에서 제외 (destination only).
    """
```

**의존**: `tradingagents.schemas.portfolio.BucketTarget`, `tradingagents.skills.portfolio.diversification.compute_enb`

### 신규 모듈 B: `tradingagents/skills/portfolio/diversification.py`

**책임**: ENB 계산 (Phase 2-4 에서도 재사용)

**Public API**:
```python
def compute_enb(
    weights: dict[str, float] | pd.Series,
    sigma: pd.DataFrame,
    method: Literal["minimum_torsion", "pca"] = "minimum_torsion",
) -> float: ...

def minimum_torsion_matrix(sigma: np.ndarray) -> np.ndarray: ...

def minimum_torsion_decomposition(
    w: np.ndarray,
    sigma: np.ndarray,
) -> np.ndarray: ...

def _matrix_inv_sqrt(A: np.ndarray) -> np.ndarray: ...
```

**의존**: numpy, scipy.linalg (eigendecomposition). 외부 데이터 없음.

### 변경 모듈 C: `tradingagents/skills/portfolio/candidate_selector.py`

**제거**:
- `DEFAULT_MIN_AUM_KRW = 50_000_000_000`
- `_RELAXED_MIN_AUM_KRW` dict
- `_min_aum_for_etf(etf, default_threshold)` 함수

**시그니처 단순화**:
- `_eligible_for_bucket(universe, cats)` (min_aum_krw 파라미터 제거)
- `list_eligible_tickers(universe, bucket_target, as_of)` (min_aum_krw 파라미터 제거)
- `select_etf_candidates(...)` (min_aum_krw 파라미터 제거)

**bond bucket alpha_scores 통합 보강** (cash_spillover 의존):
현재 `_select_bond_with_tips_quota` 는 sub_pool 단위로만 alpha 를 `breakdown_out["sub_pools"][label]["alpha_scores"]` 에 기록. cash_spillover 가 bond bucket 단위 conviction 을 계산하려면 bucket level 의 통합 `alpha_scores` 가 필요. 변경:

```python
# _select_bond_with_tips_quota 끝부분에 추가:
if breakdown_out is not None:
    # bucket level merged alpha_scores — cash_spillover._collect_alpha_scores_per_bucket 가 사용
    merged: dict[str, float] = {}
    for label, sp in sub_pool_breakdowns.items():
        merged.update(sp.get("alpha_scores", {}))
    breakdown_out["alpha_scores"] = merged
```

비-bond bucket path 는 이미 `bucket_attr["alpha_scores"] = alpha_scores` 를 [candidate_selector.py:240-243](../../../tradingagents/skills/portfolio/candidate_selector.py#L240-L243) 에서 채우므로 변경 불필요.

### 변경 모듈 D: `tradingagents/skills/portfolio/factor_scorer.py`

**변경**: `select_cluster_aware` 의 음수 alpha fill 분기 제거.

기존 ([factor_scorer.py:556-569](../../../tradingagents/skills/portfolio/factor_scorer.py#L556-L569)):
```python
if require_positive_alpha:
    positive_groups = [(a, r, g) for (a, r, g) in group_repr if a > 0]
    min_required = max(1, n // 2)
    if len(positive_groups) >= min_required:
        group_repr_filtered = positive_groups
    elif group_repr:
        negative_groups = [(a, r, g) for (a, r, g) in group_repr if a <= 0]
        shortfall = min_required - len(positive_groups)
        group_repr_filtered = positive_groups + negative_groups[:shortfall]   # <- 제거
    else:
        group_repr_filtered = []
```

새 동작:
```python
if require_positive_alpha:
    group_repr_filtered = [g for g in group_repr if g[0] > 0]   # 양수만, fill 없음
else:
    group_repr_filtered = group_repr
# chosen 이 n 보다 짧을 수 있음 — caller (cash_spillover) 가 처리
```

Padding 단계 ([factor_scorer.py:593-633](../../../tradingagents/skills/portfolio/factor_scorer.py#L593-L633)) 도 동일하게 양수만 fill (이미 부분 적용됨 — 음수 fill 분기만 추가 제거).

### 변경 모듈 E: `tradingagents/agents/allocator/portfolio_allocator.py`

**Module-level constants** (portfolio_allocator.py 상단):
```python
ENB_WARNING_THRESHOLD: float = 3.0
```

**Helper function** (portfolio_allocator.py 내부, allocator node 외부):
```python
def _collect_alpha_scores_per_bucket(
    attribution: dict,
) -> dict[str, dict[str, float]]:
    """attribution["buckets"][bucket]["alpha_scores"] 에서 추출.

    candidate_selector 가 이미 bucket_attr["alpha_scores"] = {ticker: alpha}
    형태로 채워둠 ([candidate_selector.py:240-243](../../../tradingagents/skills/portfolio/candidate_selector.py#L240-L243)).
    bond bucket 의 split path 도 변경 모듈 C 의 보강으로 같은 키 사용.
    """
    out: dict[str, dict[str, float]] = {}
    for bucket_name, bucket_attr in attribution.get("buckets", {}).items():
        alpha_scores = bucket_attr.get("alpha_scores") or {}
        out[bucket_name] = dict(alpha_scores)
    return out
```

**hook 1** (candidate selection 직후, line ~234 이후):
```python
from tradingagents.skills.portfolio.cash_spillover import adjust_bucket_targets

# candidates 산출 후
alpha_scores_by_bucket = _collect_alpha_scores_per_bucket(attribution)
spillover_result = adjust_bucket_targets(
    bucket_target=bucket_target,
    bucket_chosen=candidates.bucket_to_tickers,
    alpha_scores_by_bucket=alpha_scores_by_bucket,
    returns=returns,
)
bucket_target = spillover_result.adjusted_bucket_target
attribution["cash_spillover"] = spillover_result.model_dump()
```

**hook 2** (weight_vector 산출 직후, line ~283 이후):
```python
from tradingagents.skills.portfolio.diversification import compute_enb

enb_value = compute_enb(wv.weights, S, method="minimum_torsion")
attribution["enb"] = enb_value
if enb_value < ENB_WARNING_THRESHOLD:
    logger.warning(
        "ENB %.2f < %.2f — possible insufficient diversification",
        enb_value, ENB_WARNING_THRESHOLD,
    )
```

**호출부 정리**: `DEFAULT_MIN_AUM_KRW` 임포트 제거, `list_eligible_tickers` / `select_etf_candidates` 호출 시 `min_aum_krw` 인자 제거.

**`S` (sample_cov) 의 양 경로 보장**: 현재 [portfolio_allocator.py:431-437](../../../tradingagents/agents/allocator/portfolio_allocator.py#L431-L437) 에서 `S = risk_models.sample_cov(returns)` 는 HRP **이후** 경로에서만 산출됨. hook 2 의 ENB 측정이 두 경로 모두에서 동작하려면, **HRP 분기 진입 전에 `S` 를 항상 산출**하도록 옮긴다 (HRP 내부에서는 sub-pool sample_cov 를 별도 사용하므로 충돌 없음). 이 변경의 책임은 hook 2 도입과 함께 묶음.

## Conviction & Spillover 디테일

### Conviction 공식

```
conviction(bucket) = (mean_alpha / threshold) × (ENB_equal_weight / √N)
```

- `mean_alpha`: chosen 종목들의 alpha 평균 (scenario + macro + timing 보정 후 최종)
- `threshold`: spillover threshold (default 0.3, fx_commodity 0.15)
- `ENB_equal_weight`: chosen 종목들 **equal-weight** 가정 하 minimum-torsion ENB
- `N`: chosen 종목 수

### Spillover ratio (단일 threshold linear shutdown)

```python
if conviction >= threshold:
    spillover_ratio = 0.0
else:
    spillover_ratio = 1.0 - (conviction / threshold)
```

| conviction (threshold=0.3) | spillover_ratio |
|---|---|
| 0.0 | 1.0 (전체 cash) |
| 0.10 | 0.667 |
| 0.20 | 0.333 |
| 0.30 | 0.0 (전부 살림) |
| 0.50 | 0.0 |

### Cash cap-aware redistribution (3 단계)

**Step 1** — bucket → cash 로 spillover:
```python
for b in ["kr_equity", "global_equity", "fx_commodity", "bond"]:
    spillover_amount[b] = bucket_target[b] × spillover_ratio[b]
    adjusted[b] = bucket_target[b] - spillover_amount[b]
cash_new = bucket_target["cash_mmf"] + sum(spillover_amount.values())
```
(cash_mmf 자체는 spillover 대상 아님)

**Step 2** — cash cap check (CASH_CAP_FOR_SPILLOVER_TARGET = 0.40):
```python
# Macro 가 이미 cap 보다 큰 cash 결정 시 그 값을 effective cap 으로 사용.
# spec 정신: spillover 가 발동한 경우에만 cash 가 늘어나는 것을 제한.
# macro cash 자체를 일방적으로 깎지 않음.
effective_cap = max(CASH_CAP_FOR_SPILLOVER_TARGET, bucket_target.cash_mmf)
if cash_new <= effective_cap:
    adjusted["cash_mmf"] = cash_new
    overflow = 0.0
else:
    adjusted["cash_mmf"] = effective_cap
    overflow = cash_new - effective_cap
```

**Step 3** — overflow → high-conviction bucket conviction 가중 비례:
```python
high_conv = {b: c for b, c in conviction.items()
             if c >= threshold[b] and b != "cash_mmf"}
if high_conv:
    total_weight = sum(high_conv.values())
    for b, c in high_conv.items():
        adjusted[b] += overflow × (c / total_weight)
else:
    adjusted["cash_mmf"] += overflow
    logger.warning("all buckets low-conviction; cash_mmf exceeds cap")
```

### Invariants

- `abs(sum(adjusted.values()) - 1.0) < 1e-9` (합 1 보존)
- `adjusted.bond_tips_share == bucket_target.bond_tips_share` (비율 보존)
- 모든 `adjusted[b] >= 0`

**bond bucket spillover 시 tips/nominal 처리**: `adjust_bucket_targets` 는 `adjusted.bond` (bond bucket weight) 만 조정. tips/nominal split 은 `bond_tips_share` 비율을 유지하므로 절대 weight 은 자동 비례 축소됨:
```
adjusted_tips_weight    = adjusted.bond × bond_tips_share
adjusted_nominal_weight = adjusted.bond × (1 - bond_tips_share)
```
이 분배는 EF/HRP 의 `_build_sector_mapper_and_bounds` 가 `adjusted.bond` 기반으로 자동 계산하므로 추가 코드 불요.

### Edge cases

| 케이스 | 처리 |
|---|---|
| chosen 이 빈 bucket | conviction = 0, spillover_ratio = 1.0 |
| N = 1 | ENB = 1, 공식 그대로 |
| cash_mmf chosen 빈 경우 | cash_mmf 는 spillover 대상에서 제외, destination 으로만 사용 |
| 모든 bucket low conviction | cash > 40% 허용 + WARNING log |
| bond_tips_share = 0 | 기존 default, 정상 |

## ENB Minimum-Torsion 디테일

### Closed-form 알고리즘

입력: covariance `Σ` (n×n)
출력: torsion matrix `T` s.t. `T Σ Tᵀ = diag(diag(Σ))`

```
1. D = diag(diag(Σ))                 # 분산 행렬
2. C = D^(-1/2) Σ D^(-1/2)           # 상관 행렬
3. C^(-1/2) = symmetric inverse sqrt of C (via eigendecomp)
4. T = D^(1/2) × C^(-1/2) × D^(-1/2)
```

### 분산 분해

```python
exposures = solve(T.T, w)              # e = T^(-T) w
factor_var = exposures**2 × diag(Σ)
port_var = w.T @ Σ @ w
p = factor_var / port_var               # 합 1 (해석적)
```

### ENB

```python
p_safe = max(p, 1e-12)
ENB = exp(-sum(p_safe × log(p_safe)))
```

### 측정 지점 (Phase 1)

| 지점 | 입력 | 용도 |
|---|---|---|
| (a) bucket conviction 내부 | chosen 종목, equal-weight, sample_cov | conviction 계산 |
| (b) 전체 포트폴리오 사후 | 최종 weights, allocator 의 S | attribution + warning |

### Numerical safety

| 상황 | 처리 |
|---|---|
| Σ 비양정부호 (eigenvalue ≤ 0) | `_matrix_inv_sqrt` 가 1e-12 클립 + WARNING |
| 가중치 합 ≠ 1 | 자동 재정규화 (drift 1e-6 까지) |
| port_var ≈ 0 | equal split p = 1/n → ENB = n |
| n = 1 | 즉시 ENB = 1 반환 |

## Error Handling 원칙

Phase 1 신규 코드는 **fail-loud over fail-silent**. 기존 fail-safe (degraded_inputs 등) 는 유지.

| 상황 | 처리 |
|---|---|
| candidates 빈 (모든 bucket 후보 0) | `RuntimeError("No eligible candidates")` — 기존 동작 |
| 양수 alpha group 0 인 bucket | conviction=0, spillover_ratio=1.0 (정상) |
| 모든 bucket 양수 alpha 0 | cash_mmf 100%, WARNING log + 계속 진행 |
| Σ 비양정부호 | `_matrix_inv_sqrt` 클립 + WARNING |
| chosen 1개뿐 | ENB=1, conviction 공식 정상 |
| spillover 후 weight drift > 1e-9 | RuntimeError |
| bucket_target 입력 합 ≠ 1 | `assert abs(sum - 1.0) < 1e-9` |

## Testing Strategy

### A. Unit tests (모듈별)

**`tests/unit/skills/portfolio/test_diversification.py`** (신규):
- `test_enb_single_asset` — n=1 → ENB=1
- `test_enb_uncorrelated_equal_weight` — n 자산 무상관 등가중 → ENB=n
- `test_enb_perfectly_correlated` — corr=1 → ENB=1
- `test_enb_half_correlated_two_assets` — corr=0.5 → ENB ≈ 1.6
- `test_enb_scale_invariance` — σ × 100 → ENB 불변
- `test_enb_non_psd_warning` — eigenvalue 클립, warning emit
- `test_enb_zero_portfolio_variance` — equal split fallback
- `test_minimum_torsion_matrix_decorrelates` — `T Σ Tᵀ ≈ diag(diag(Σ))`

**`tests/unit/skills/portfolio/test_cash_spillover.py`** (신규):
- `test_conviction_full_strength` — mean_alpha=threshold, ENB=√N → conviction=1, spillover=0
- `test_conviction_zero_alpha` — mean_alpha=0 → conviction=0, spillover=1
- `test_conviction_low_diversification` — ENB=1, N=4 → 둘째 항 = 0.5
- `test_spillover_to_cash_simple` — fx_commodity 양수 1 → 일부 cash
- `test_spillover_to_cash_cap_overflow` — cash > 40% → high-conv 로
- `test_spillover_all_low_conviction` — 모두 음수 → 100% cash + warning
- `test_spillover_preserves_bond_tips_share` — invariant
- `test_spillover_sum_invariant` — 합 1.0 보존
- `test_fx_commodity_uses_specific_threshold` — 0.15 vs 0.3

### B. 회귀 tests (기존 모듈 변경)

**`tests/unit/skills/portfolio/test_candidate_selector.py`** (변경):
- 기존 테스트 시그니처 업데이트 (`min_aum_krw` 인자 제거)
- `test_eligibility_no_aum_filter` — AUM 1억 ETF 통과
- `test_inflation_linked_no_special_treatment` — relaxed AUM 제거 후 정상

**`tests/unit/skills/portfolio/test_factor_scorer.py`** (변경):
- `test_select_cluster_aware_no_negative_fill` — 양수 부족 시 짧은 chosen
- `test_select_cluster_aware_padding_positive_only` — padding 도 양수만
- `test_select_cluster_aware_all_negative_returns_empty_or_top1` — degenerate

### C. Integration tests (allocator pipeline)

**`tests/integration/test_allocator_phase1.py`** (신규):
- `test_allocator_with_normal_universe` — 5 bucket 양수 충분 → spillover 0, ENB 양호
- `test_allocator_with_fx_negative_only` — fx_commodity 음수만 → spillover 발동
- `test_allocator_with_global_low_conviction` — 부분 spillover
- `test_allocator_attribution_completeness` — cash_spillover / enb 필드 채워짐
- `test_allocator_cash_overflow_redistribution` — 동시 다 bucket → overflow → high-conv

검증 항목 (각 케이스):
- weight sum = 1
- 단일 cap 20% 준수
- bucket sum 매핑 (adjusted_bucket_target 과 일치, ±band)
- ENB > 0

### D. 회귀 시나리오 (기존 fixture)

**대상**: `artifacts/2025-04-15/`, `artifacts/2026-05-15/`

**절차**:
1. Phase 1 적용 전 산출물 git tag 백업
2. Phase 1 적용 후 같은 as_of 로 재실행
3. `scripts/regression_compare.py` (신규 작성) 로 비교

**`scripts/regression_compare.py` 신규 요구사항**:
- **입력**: `--baseline <dir>` `--new <dir>` — 각 디렉토리에 `portfolio.json` (allocator 산출물) 존재
- **다중 as_of 지원**: baseline/new 가 `2025-04-15/`, `2026-05-15/` 등 여러 subdir 가지면 각각 비교 후 집계
- **읽어들이는 필드** (portfolio.json):
  - `weights: dict[str, float]`
  - `bucket_target: dict[str, float]` (+ `bond_tips_share`)
  - `expected_sharpe: float | None`
  - `expected_volatility: float | None`
  - `allocation_attribution.cash_spillover` (new 만, baseline 에는 없음)
  - `allocation_attribution.enb` (new 만)
- **출력 metric**:
  - `weights` ticker set Jaccard similarity
  - `weights` L1 distance (`sum(|w_new - w_baseline|)`)
  - `expected_sharpe` relative delta
  - `expected_volatility` relative delta
  - bucket weight delta (per bucket: kr_equity, global_equity, fx_commodity, bond, cash_mmf)
  - chosen ticker set diff (added / removed)
  - cash_spillover 발동 여부 + amount per bucket
  - ENB 값 (new 만)
  - **acceptance check pass/fail** (위 acceptance criteria 5 항목 각각)
- **출력 format**:
  - stdout: human-readable summary (acceptance pass/fail 표시)
  - `--out <path>` 옵션: JSON dump
- **exit code**: acceptance criteria 모두 통과 시 0, 하나라도 실패 시 1

**Acceptance criteria** (regression_compare.py 의 exit code 0/1 판정 대상):
- (a) `new_expected_sharpe >= 0.95 × baseline_expected_sharpe` (relative degradation ≤ 5%)
- (b) `new_expected_volatility <= 1.02 × baseline_expected_volatility` (drag 감소 기대; 2% 이내 증가는 noise 허용)
- (c) attribution 에 `cash_spillover`, `enb` 필드 채워짐
- (d) fx_commodity (2026-05-15 케이스):
  - bucket weight 감소 확인 (baseline 17.6% 대비 감소)
  - chosen 종목 모두 alpha > 0
  - cash_mmf bucket weight 증가

**Fail recovery** (acceptance 실패 시 대응 절차 — 자동 retry 아님):
- (a) 미충족 시: spillover threshold 재검토. 1차 조정안 `SPILLOVER_THRESHOLD_DEFAULT 0.3 → 0.2` 또는 `fx_commodity 0.15 → 0.10` (덜 공격적인 spillover).
- (b) 미충족 시: ENB 계산이 turnover 폭증을 부르는지 점검. attribution 의 chosen ticker diff 확인.
- (d) 미충족 시: alpha 음수 fill 제거가 실제로 적용됐는지 코드 검증.

### Test 실행 명령

```bash
# 단위 + 회귀
pytest tests/unit/skills/portfolio/ -v

# 통합
pytest tests/integration/test_allocator_phase1.py -v

# 회귀 시나리오
python scripts/regression_compare.py \
    --baseline artifacts/baseline/ \
    --new artifacts/phase1/
```

## Out of Scope / Future Phases

- **Phase 2**: ENB greedy forward selection, adaptive `per_bucket_n`, impl_score 5-요소 composite, 데이터 어댑터 (TE/괴리율/volume)
- **Phase 3**: NCO + Black-Litterman backbone, `OptimizationMethod` 단일화
- **Phase 4**: Ledoit-Wolf nonlinear shrinkage, regime → (δ, c, τ) tilt, 사후 게이트 차단 동작

## Backward Compatibility

- `BucketTarget`, `WeightVector`, `OptimizationMethod` schema 변경 없음
- `attribution` dict 는 신규 키 추가만 (`cash_spillover`, `enb`) — 기존 키 변경 없음
- `method_picker` 동작 변경 없음
- 기존 fixture 산출물 (2025-04-15, 2026-05-15) 의 weight_vector 가 5% Sharpe 이내 차이로 유지되어야 함 (acceptance criterion)

## Open Questions

없음 (모든 design decision 확정). 구현 단계의 세부 ordering 은 별도 implementation plan 에서 다룸.
