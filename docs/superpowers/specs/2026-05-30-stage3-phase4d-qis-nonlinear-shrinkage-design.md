# Stage 3 Phase 4d — QIS Nonlinear Shrinkage Design

**Date:** 2026-05-30
**Stage:** 3 (Portfolio allocation)
**Phase:** 4d (Ledoit-Wolf 2020 QIS nonlinear shrinkage)
**Status:** Approved for implementation

## Goal

Phase 4a 의 `compute_robust_cov` 에 Ledoit-Wolf 2020 Quadratic-Inverse Shrinkage (QIS) 알고리즘 추가. eigenvalue-distribution-aware per-eigenvalue nonlinear shrinkage. default 를 QIS 로 전환하고 linear LW 는 `method="ledoit_wolf"` 옵션으로 보존.

## Rationale

Phase 4a 의 linear LW shrinkage 는 단일 δ 로 모든 eigenvalue 를 동일 강도 축소. small-T (T<200) 또는 large-N (N>50) 에서는 큰 eigenvalue 와 작은 eigenvalue 가 다른 noise 특성을 가짐 — per-eigenvalue 차등 shrinkage 가 더 정확. QIS 는 Stieltjes-transform 기반 closed-form 으로 각 eigenvalue 를 별도 조정.

## Scope

### In-scope

1. `tradingagents/skills/portfolio/cov_estimator.py`:
   - `_qis_cov(Y, k=1)` helper 신규 (Ledoit-Wolf 2020, NumPy 구현)
   - `compute_robust_cov` 시그니처 확장: `*, method: str = "qis"` 추가
   - `method="qis"` (default) | `"ledoit_wolf"` (Phase 4a 동작 보존)
   - Unknown method → sample_cov fallback + `method_attempted` 기록
2. 8 호출지 자동 QIS (signature 변경 없이 default 효과)
3. attribution.cov_breakdown.estimator = "qis" (default)

### Out-of-scope

- Per-eigenvalue intensity 세부 노출 (mean 값만 노출)
- Linear LW 제거 (보존 — A/B 비교 용)
- Backtest 검증 (별도 phase)
- pypfopt CovarianceShrinkage method override

## Architecture

```
                BEFORE (Phase 4a)                AFTER (Phase 4d)
─────────────────────────────────────────────────────────────────────
compute_robust_cov(                  compute_robust_cov(
  returns,                             returns,
  breakdown_out=None,                  *,
)                                      method: str = "qis",  ← NEW default
  Internal: pypfopt LW linear          breakdown_out=None,
                                     )
                                       if method == "qis":
                                         cov, intensity = _qis_cov(...)
                                       elif method == "ledoit_wolf":
                                         pypfopt LW linear (기존)
                                       else: raise → fallback

                                     + _qis_cov(Y, k=1) NumPy 구현

attribution.cov_breakdown:
  estimator: "ledoit_wolf"           estimator: "qis" (default)
  shrinkage_intensity: 0.0776 (δ)    shrinkage_intensity: mean(1 - d/λ)
                                       QIS: ∈ [-1, 1] (음수 가능 — 정상)
                                       linear: δ ∈ [0, 1] (기존)
```

## Components

### `tradingagents/skills/portfolio/cov_estimator.py`

**(a) `compute_robust_cov` 시그니처 확장**:

```python
def compute_robust_cov(
    returns: pd.DataFrame,
    *,
    method: str = "qis",
    breakdown_out: dict | None = None,
) -> pd.DataFrame:
    """
    Robust covariance estimator.

    Args:
        returns: T × N daily returns DataFrame (no NaN rows expected).
        method: "qis" (default, Ledoit-Wolf 2020 nonlinear) or
                "ledoit_wolf" (2004 linear, Phase 4a 동작 보존).
        breakdown_out: optional dict to record estimator + shrinkage_intensity
            + n_obs + n_assets for attribution.

    Returns:
        N × N robust covariance DataFrame.

    Fallback: unknown method or estimator failure → sample_cov +
    breakdown_out["fallback_reason"] + ["method_attempted"].
    """
    n_obs, n_assets = returns.shape
    try:
        if method == "qis":
            shrunk_np, intensity = _qis_cov(returns.values)
            shrunk = pd.DataFrame(
                shrunk_np,
                index=returns.columns,
                columns=returns.columns,
            )
            delta = intensity
        elif method == "ledoit_wolf":
            cs = risk_models.CovarianceShrinkage(returns, returns_data=True)
            shrunk = cs.ledoit_wolf()
            delta = float(cs.delta)
        else:
            raise ValueError(f"unknown method: {method}")
    except Exception as e:
        if breakdown_out is not None:
            breakdown_out["fallback_reason"] = f"shrinkage_failed: {type(e).__name__}"
            breakdown_out["n_obs"] = n_obs
            breakdown_out["n_assets"] = n_assets
            breakdown_out["method_attempted"] = method
        return risk_models.sample_cov(returns, returns_data=True)

    if breakdown_out is not None:
        breakdown_out["estimator"] = method
        breakdown_out["shrinkage_intensity"] = float(delta)
        breakdown_out["n_obs"] = n_obs
        breakdown_out["n_assets"] = n_assets

    return shrunk
```

**(b) `_qis_cov` helper 신규**:

```python
def _qis_cov(
    Y: np.ndarray,
    k: int = 1,
) -> tuple[np.ndarray, float]:
    """
    Quadratic-Inverse Shrinkage (Ledoit & Wolf 2020).

    Args:
        Y: T × N returns matrix.
        k: degrees of freedom adjustment (1 = sample mean removed).

    Returns:
        cov_shrunk: N × N nonlinear-shrinkage covariance (symmetric PSD).
        mean_intensity: scalar — mean(1 - shrunk_λ / sample_λ) over non-zero λ.
            QIS 는 per-eigenvalue 차등 shrinkage 라 단일 δ 가 없음.
            양수: 평균 축소, 음수: 평균 확장 (정상 — 작은 λ 가 커짐).

    Reference: Ledoit & Wolf (2020) "Analytical Nonlinear Shrinkage of
    Large-Dimensional Covariance Matrices", Annals of Statistics 48(5).
    Port of Olivier Ledoit's official MATLAB code (QIS function).
    """
    T, N = Y.shape
    # Centered returns
    Y = Y - Y.mean(axis=0, keepdims=True)
    n = T - k

    # Sample covariance
    sample = (Y.T @ Y) / n

    # Eigendecomposition (ascending eigenvalues)
    lambdas, u = np.linalg.eigh(sample)
    lambdas = lambdas.real
    lambdas = np.maximum(lambdas, 0.0)  # numerical floor

    # Concentration ratio & bandwidth
    c = N / n
    h = (min(c**2, 1.0 / c**2) ** 0.35) / N**0.35

    # Effective eigenvalues (drop zeros if N > n — over-determined case)
    n_eff = min(N, n)
    lam_eff = lambdas[N - n_eff:]

    # Pairwise differences
    L = np.outer(lam_eff, np.ones(n_eff)) - np.outer(np.ones(n_eff), lam_eff)
    denom = L**2 + (h * lam_eff[:, None])**2
    denom = np.where(denom > 0, denom, 1.0)  # avoid 0/0

    # Hilbert transform estimate
    Hcomponent = L / denom
    Htilde = Hcomponent.mean(axis=1)

    # Spectral density estimate
    fcomponent = (h * lam_eff[:, None]) / denom
    ftilde = (c / np.pi) * fcomponent.mean(axis=1)

    # QIS shrinkage formula (Eq 4.5)
    real_part = 1.0 - c - np.pi * c * lam_eff * Htilde
    imag_part = np.pi * c * lam_eff * ftilde
    d_star = lam_eff / (real_part**2 + imag_part**2 + 1e-30)

    # Pad zeros for over-determined case
    d_full = np.zeros(N)
    d_full[N - n_eff:] = d_star

    # Reconstruct shrunk cov + symmetrize
    cov_shrunk = u @ np.diag(d_full) @ u.T
    cov_shrunk = (cov_shrunk + cov_shrunk.T) / 2

    # Mean intensity (signed)
    mask = lam_eff > 1e-12
    if mask.any():
        intensity = float(np.mean(1.0 - d_star[mask] / lam_eff[mask]))
    else:
        intensity = 0.0

    return cov_shrunk, intensity
```

## Edge Cases

| Case | Behavior |
|---|---|
| `method="xyz"` | `ValueError` → except → sample_cov fallback + `method_attempted="xyz"` |
| T < N (over-determined) | `n_eff = T` 만 사용, 나머지 eigenvalue 0 |
| 자산 1개 (N=1) | shape (1,1). QIS 는 sample 과 동일. intensity=0. |
| 한 자산 constant returns | sample λ 일부 0. floor + 1e-30 분모 보호로 안정. |
| eigvalue 모두 0 | `intensity=0.0` (mask 모두 False) |
| Numerical asymmetry | symmetrize 후 반환 |
| T=1 | n=0 → 호출자가 T ≥ 30 보장 (Phase 4a MIN_COV_OBS) |

## Numerical Safety

- `lambdas = max(lambdas, 0)` floor
- 분모 `+ 1e-30` 으로 0-division 방지
- Symmetrize 후 반환
- `np.linalg.eigh` 사용 (대칭 행렬용, faster + more stable than eig)

## Performance

- Eigendecomposition O(N³). N=20, T=252 기준 < 10 ms
- 8 호출지 합쳐 < 100 ms 추가

## Backward Compat

- 시그니처 keyword-only `method=` 추가 — 기존 positional 호출 그대로
- 기본 method 변경 → weight 미세 변경 (회귀 baseline 갱신 권장)
- `method="ledoit_wolf"` 로 Phase 4a 동작 복원 → A/B 비교

## Testing Strategy

### Unit tests — `tests/unit/skills/test_portfolio_cov_estimator.py` (MODIFY)

**기존 2 tests 갱신**:
- `test_compute_robust_cov_records_breakdown` — `estimator` key 가 "qis" 로 변경
- `test_compute_robust_cov_shrinkage_intensity_in_unit_interval` — QIS 의 intensity 는 [-1, 1] (음수 가능)

**신규 6 tests**:

1. `test_qis_cov_basic_shape_psd_with_default` — default method, PSD, shape
2. `test_qis_cov_method_ledoit_wolf_explicit` — `method="ledoit_wolf"` → estimator="ledoit_wolf", δ ∈ [0, 1]
3. `test_qis_cov_method_qis_explicit` — `method="qis"` → estimator="qis"
4. `test_qis_cov_unknown_method_fallback` — `method="xyz"` → fallback + `method_attempted="xyz"`
5. `test_qis_cov_differs_from_linear` — QIS ≠ ledoit_wolf 결과 (non-degenerate input)
6. `test_qis_cov_intensity_in_signed_range` — QIS intensity ∈ [-1, 1]

### Integration tests — `tests/integration/test_allocator_phase4d.py` (NEW, 2 tests)

1. `test_allocator_cov_estimator_default_is_qis` — attribution.cov_breakdown.estimator == "qis"
2. `test_allocator_nco_cov_breakdown_estimator_qis` — NCO path 의 per-pool cov_breakdown 도 "qis"

### Regression — Phase 1/2a/2b/3a/3b/3c/4a/4b/4c

- Phase 4a 의 estimator="ledoit_wolf" 가정 assertion 갱신 (test_allocator_phase4a 의 1 test 정도).
- 그 외는 존재 검증 위주 → 영향 없음.

### Acceptance criteria

| # | Criterion | Verification |
|---|---|---|
| (a) | `method=qis` default | unit 1, 3, integration 1 |
| (b) | `method=ledoit_wolf` 명시 옵션 | unit 2 |
| (c) | unknown method fallback | unit 4 |
| (d) | QIS ≠ linear 결과 | unit 5 |
| (e) | intensity ∈ [-1, 1] | unit 6 |
| (f) | NCO breakdown estimator="qis" | integration 2 |
| (g) | 기존 250+ tests PASS | full regression |

총 8 신규 test (6 unit + 2 integration) + Phase 4a 1 assertion 갱신.

## Related Memory

- [[stage3_phase4a_followup]] — Ledoit-Wolf linear shrinkage (Phase 4d 가 확장)
- [[stage3_phase3a_followup]] — NCO bucket-internal (cov 입력)
- [[stage3_phase3b_followup]] — BL (cov 입력)
- [[stage3_phase2b_followup]] — "Phase 4 nonlinear shrinkage" 메모 (이 phase 로 해소)
