# Stage 3 Phase 4a — Ledoit-Wolf Covariance Shrinkage Design

**Date:** 2026-05-30
**Stage:** 3 (Portfolio allocation)
**Phase:** 4a (Ledoit-Wolf shrinkage covariance)
**Status:** Approved for implementation

## Goal

NCO / HRP / BL / EF 가 모두 condition 하는 covariance 추정량을 `risk_models.sample_cov` (sample covariance) 에서 Ledoit-Wolf linear shrinkage 로 일괄 교체. 표본 noise 가 weight 의 집중도 위험으로 propagate 되는 것을 차단한다.

## Rationale

Sample covariance 는 unbiased 이지만 small-sample (T ~ N 또는 T < N) 에서 high-variance — eigenvalues 가 양극화되어 inversion 시 outlier asset 으로 weight 집중. Ledoit-Wolf 2004 linear shrinkage 는 closed form δ 로 identity target 쪽으로 shrink — Bias-Variance tradeoff 의 최적해. PSD 보장.

## Scope

### In-scope (8 호출지 일괄 교체 + 1 helper 신규)

1. `tradingagents/skills/portfolio/cov_estimator.py` (신규): `compute_robust_cov(returns, *, breakdown_out=None)`
2. `portfolio_allocator.py:537`: `S = risk_models.sample_cov(returns)` → `compute_robust_cov(...)` + attribution 노출
3. `overlay_apply.py:79`: 동일 교체
4. `optimizers.py:39` (min_volatility): 동일 교체
5. `optimizers.py:56` (risk_parity): 동일 교체
6. `optimizers.py:88` (BL): 동일 교체
7. `conditional_logic.py:48`: 동일 교체
8. `nco.py:142` (n=2 shortcut): `cov = returns.cov()` → `compute_robust_cov(returns)`
9. `nco.py:153` (general): 동일 교체 + breakdown_out 통합

### Out-of-scope

- `nco.py:154` 의 `returns.corr()` (clustering distance) — raw 유지
- Nonlinear shrinkage (Ledoit-Wolf 2020 QIS) — Phase 4 후속 검토
- BL views 의 prior covariance — Phase 4b 후보
- Backtest 검증 (별도 phase)

## Architecture

```
                      BEFORE                          AFTER
─────────────────────────────────────────────────────────────────────
allocator._optimize... line 537   risk_models.sample_cov(returns)
overlay_apply.py:79               risk_models.sample_cov(returns)
optimizers.py:39 (min_vol)        risk_models.sample_cov(returns)
optimizers.py:56 (risk_parity)    risk_models.sample_cov(returns)   → compute_robust_cov(returns)
optimizers.py:88 (BL)             risk_models.sample_cov(returns)
conditional_logic.py:48           risk_models.sample_cov(returns)
nco.py:142 (n=2)                  returns.cov()
nco.py:153 (general)              returns.cov()
nco.py:154 (clustering corr)      returns.corr()                     ← raw 유지 (unchanged)
```

Helper 도입 정당화:
- DRY: 8 호출지 동일 동작
- Attribution trace: shrinkage intensity (δ) 노출
- 미래 확장: estimator 교체 시 1 곳만 수정
- Test 용이: helper 단독 검증으로 8 호출지 동작 보장

## Components

### `tradingagents/skills/portfolio/cov_estimator.py` (NEW)

```python
"""
Phase 4a: Robust covariance estimation.

Ledoit-Wolf linear shrinkage covariance — replaces sample_cov / returns.cov()
across allocator, optimizers, NCO, overlay.
"""
from __future__ import annotations

import pandas as pd
from pypfopt import risk_models


def compute_robust_cov(
    returns: pd.DataFrame,
    *,
    breakdown_out: dict | None = None,
) -> pd.DataFrame:
    """
    Ledoit-Wolf linear shrinkage covariance.

    Args:
        returns: T × N daily returns DataFrame (no NaN rows expected).
        breakdown_out: optional dict to record shrinkage_intensity (δ),
            n_obs, n_assets, estimator label for attribution.

    Returns:
        N × N shrinkage covariance DataFrame.

    Fallback: if estimator fails (constant returns, degenerate input),
    returns sample_cov + breakdown_out["fallback_reason"]="shrinkage_failed".
    """
    n_obs, n_assets = returns.shape
    try:
        cs = risk_models.CovarianceShrinkage(returns, returns_data=True)
        shrunk = cs.ledoit_wolf()
        delta = float(cs.delta)
    except Exception as e:
        if breakdown_out is not None:
            breakdown_out["fallback_reason"] = f"shrinkage_failed: {type(e).__name__}"
            breakdown_out["n_obs"] = n_obs
            breakdown_out["n_assets"] = n_assets
        return risk_models.sample_cov(returns, returns_data=True)

    if breakdown_out is not None:
        breakdown_out["estimator"] = "ledoit_wolf"
        breakdown_out["shrinkage_intensity"] = delta
        breakdown_out["n_obs"] = n_obs
        breakdown_out["n_assets"] = n_assets

    return shrunk
```

### 호출지 교체 패턴

**`portfolio_allocator.py:537`** — attribution 노출:

```python
cov_breakdown: dict = {}
S = compute_robust_cov(returns, breakdown_out=cov_breakdown)
if attribution is not None:
    attribution["cov_breakdown"] = cov_breakdown
```

**`nco.py:142` (n=2 shortcut)**:

```python
cov = compute_robust_cov(returns)
```

**`nco.py:153` (general)** — breakdown 통합:

```python
cov_bd: dict = {}
cov = compute_robust_cov(returns, breakdown_out=cov_bd)
if breakdown_out is not None:
    breakdown_out["cov_breakdown"] = cov_bd
corr = returns.corr().fillna(0.0)  # unchanged — clustering 용 raw
```

**`overlay_apply.py:79`, `optimizers.py:39/56/88`, `conditional_logic.py:48`** — 단순 1-line 교체:

```python
S = compute_robust_cov(returns)
```

(attribution scope 가 아닌 곳은 breakdown_out 안 줌.)

## Attribution Structure

allocator 경로:
```json
{
  "allocation_attribution": {
    "cov_breakdown": {
      "estimator": "ledoit_wolf",
      "shrinkage_intensity": 0.42,
      "n_obs": 252,
      "n_assets": 12
    }
  }
}
```

NCO 경로 (`nco_breakdown_per_pool[bucket]` 내):
```json
{
  "kr_equity": {
    "n_clusters": 2,
    "silhouette": 0.31,
    "cov_breakdown": {
      "estimator": "ledoit_wolf",
      "shrinkage_intensity": 0.38,
      "n_obs": 252,
      "n_assets": 3
    }
  }
}
```

## Edge Cases

| Case | Behavior |
|---|---|
| T < 30 | Ledoit-Wolf 자동 처리 (δ↑ → identity 쪽 강하게 shrink) |
| 자산 1개 (N=1) | sample_cov scalar 와 동일 결과 (shrink 의미 없음, pypfopt 가 처리) |
| 한 자산 constant returns | pypfopt 가 처리. 실패 시 fallback → sample_cov + fallback_reason 기록 |
| NaN in returns | 호출자가 dropna 후 전달 전제 (현재 코드 패턴) |
| pypfopt delta attribute | `cs.ledoit_wolf()` 호출 후 `cs.delta` 접근 (instance 보존 패턴) |

## Numerical Safety

- Ledoit-Wolf 결과는 항상 PSD (수학적 보장)
- `NCO_MIN_VAR_REGULARIZATION` (1e-8) 유지 — inversion 보장 용, shrinkage 와 직교
- pypfopt `clean_weights()` 영향 없음

## Backward Compat

- 시그니처 변경 없음 — `compute_robust_cov(returns)` 는 `sample_cov(returns)` 와 동일 in/out
- Weight 결과는 달라짐 (shrinkage 효과). 회귀 baseline 갱신 권장
- Phase 1/2a/2b/3a/3b/3c 통합 테스트는 method/cap/sum/structure 검증 위주라 영향 적을 것

## Performance

- Ledoit-Wolf closed form (eigendecomposition 불필요). N=20, T=252 기준 ~1-2 ms (sample_cov ~2x)
- 총 8 호출지 합쳐 E2E < 100 ms 추가 — 무시 가능

## Testing Strategy

### Unit tests — `tests/unit/skills/test_portfolio_cov_estimator.py` (NEW, 6 tests)

1. `test_compute_robust_cov_basic_returns_dataframe` — PSD DataFrame, shape, index/columns
2. `test_compute_robust_cov_records_breakdown` — 4 키 (estimator, shrinkage_intensity, n_obs, n_assets)
3. `test_compute_robust_cov_shrinkage_intensity_in_unit_interval` — 0 ≤ δ ≤ 1
4. `test_compute_robust_cov_is_psd` — eigenvalues ≥ 0
5. `test_compute_robust_cov_differs_from_sample_cov` — shrinkage ≠ sample (non-degenerate input)
6. `test_compute_robust_cov_fallback_on_failure` — constant returns → sample_cov fallback + fallback_reason

### NCO unit tests — `tests/unit/skills/test_portfolio_nco.py` (MODIFY)

- grep cov-assertion 테스트 후 갱신. weight sum/normalization 검증은 영향 없음.

### Integration — `tests/integration/test_allocator_phase4a.py` (NEW, 3 tests)

1. `test_allocator_records_cov_breakdown` — attribution["cov_breakdown"] 4 키
2. `test_allocator_shrinkage_intensity_finite` — 0 ≤ δ ≤ 1 E2E
3. `test_allocator_nco_breakdown_contains_cov_section` — NCO path 의 breakdown 안에 cov_breakdown 포함

### Regression — Phase 1/2a/2b/3a/3b/3c

기존 통합 250+ 모두 PASS 유지 기대. weight assertion 가진 test 가 있다면 영향 가능 — sum/cap/method/structure 검증만 있는 게 대다수. grep 으로 사전 확인.

### Acceptance criteria

| # | Criterion | Verification |
|---|---|---|
| (a) | helper 동작 (PSD, δ ∈ [0,1], breakdown) | unit 1-6 |
| (b) | 8 호출지 모두 교체 | grep `sample_cov`/`returns.cov()` 결과 확인 |
| (c) | NCO clustering corr 는 raw 유지 | grep `returns.corr()` 보존 |
| (d) | allocator attribution.cov_breakdown 노출 | integration 1-2 |
| (e) | NCO breakdown 안에 cov_breakdown 포함 | integration 3 |
| (f) | 기존 250+ tests PASS | full regression |
| (g) | E2E 정상 동작 (BL/NCO 경로) | e2e default + --force-method nco |

총 9 신규 test (6 unit + 3 integration).

## Related Memory

- [[stage3_phase3a_followup]] — NCO bucket-internal optimizer (cov 입력 받음)
- [[stage3_phase3b_followup]] — BL views adapter (cov 입력 받음)
- [[stage3_phase3c_followup]] — NCO backbone cutover (NCO 의 cov 영향 가장 큼)
- [[stage3_phase2b_followup]] — "Phase 4: Ledoit-Wolf nonlinear shrinkage" 메모 (이 spec 으로 부분 해소, nonlinear 는 후속)
