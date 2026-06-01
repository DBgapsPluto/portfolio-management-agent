# Stage 3 Phase 1 — Cash Spillover & Alpha Floor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stage 3 종목 선정 단계의 두 누수 (음수 alpha 강제 fill, bucket weight 절대화) 를 차단하고 AUM hard 필터를 제거한다.

**Architecture:** 기존 5-단계 파이프라인의 candidate selection 직후와 weight 산출 직후에 2개 hook 삽입. 신규 모듈 `cash_spillover` (bucket conviction + redistribution), `diversification` (ENB minimum-torsion). 기존 `factor_scorer` 의 음수 fill 분기 제거, `candidate_selector` 의 AUM 필터 제거. Schema 변경 없음.

**Tech Stack:** Python 3.12+, pydantic, numpy, scipy.linalg, pandas, pypfopt, pytest.

**Spec:** [docs/superpowers/specs/2026-05-28-stage3-phase1-cash-spillover-design.md](../specs/2026-05-28-stage3-phase1-cash-spillover-design.md)

---

### Task 1: diversification 모듈 skeleton + ENB canonical 테스트

**Files:**
- Create: `tradingagents/skills/portfolio/diversification.py`
- Test:   `tests/unit/skills/test_portfolio_diversification.py`

- [ ] **Step 1: 빈 모듈 + Public API stub 작성**

`tradingagents/skills/portfolio/diversification.py`:
```python
"""Effective Number of Bets (ENB) via Minimum-Linear-Torsion.

Phase 1 도입. Meucci-Santangelo-Deguest 2015 의 minimum-linear-torsion 으로
포트폴리오 분산을 비상관 factor 들로 분해한 뒤 entropy-based ENB 계산.
"""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

ENB_NUMERICAL_FLOOR: float = 1e-12


def _matrix_inv_sqrt(A: np.ndarray) -> np.ndarray:
    """대칭 행렬의 역제곱근. 음수 eigenvalue 는 ENB_NUMERICAL_FLOOR 로 클립."""
    raise NotImplementedError


def minimum_torsion_matrix(sigma: np.ndarray) -> np.ndarray:
    """T such that T Σ Tᵀ = diag(diag(Σ))."""
    raise NotImplementedError


def minimum_torsion_decomposition(w: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """반환: p_i 분포 (합 1, 음수 자산 비상관 factor 분산 기여)."""
    raise NotImplementedError


def compute_enb(
    weights: dict[str, float] | pd.Series,
    sigma: pd.DataFrame,
    method: Literal["minimum_torsion", "pca"] = "minimum_torsion",
) -> float:
    """ENB = exp(-Σ p_i ln p_i)."""
    raise NotImplementedError
```

- [ ] **Step 2: canonical ENB 테스트 작성 (8개)**

`tests/unit/skills/test_portfolio_diversification.py`:
```python
"""Canonical ENB tests — minimum_torsion correctness on textbook cases."""
import math

import numpy as np
import pandas as pd
import pytest

from tradingagents.skills.portfolio.diversification import (
    compute_enb,
    minimum_torsion_decomposition,
    minimum_torsion_matrix,
)


def _diag_cov(n: int, vol: float = 0.02) -> pd.DataFrame:
    tickers = [f"A{i:06d}" for i in range(n)]
    sigma = np.eye(n) * (vol ** 2)
    return pd.DataFrame(sigma, index=tickers, columns=tickers)


def _equal_corr_cov(n: int, rho: float, vol: float = 0.02) -> pd.DataFrame:
    tickers = [f"A{i:06d}" for i in range(n)]
    corr = np.full((n, n), rho)
    np.fill_diagonal(corr, 1.0)
    sigma = corr * (vol ** 2)
    return pd.DataFrame(sigma, index=tickers, columns=tickers)


def _equal_weights(sigma: pd.DataFrame) -> dict[str, float]:
    tickers = list(sigma.index)
    n = len(tickers)
    return {t: 1.0 / n for t in tickers}


def test_enb_single_asset():
    sigma = _diag_cov(1)
    enb = compute_enb({"A000000": 1.0}, sigma)
    assert enb == pytest.approx(1.0, abs=1e-9)


def test_enb_uncorrelated_equal_weight():
    for n in (2, 4, 8):
        sigma = _diag_cov(n)
        enb = compute_enb(_equal_weights(sigma), sigma)
        assert enb == pytest.approx(n, abs=1e-6), f"n={n}"


def test_enb_perfectly_correlated():
    sigma = _equal_corr_cov(4, rho=0.999999)
    enb = compute_enb(_equal_weights(sigma), sigma)
    assert enb == pytest.approx(1.0, abs=1e-2)


def test_enb_half_correlated_two_assets():
    sigma = _equal_corr_cov(2, rho=0.5)
    enb = compute_enb(_equal_weights(sigma), sigma)
    # 2 자산 corr 0.5 등가중 → 분석적 ENB ≈ 1.6 (Meucci 예시)
    assert 1.4 < enb < 1.8


def test_enb_scale_invariance():
    sigma_a = _equal_corr_cov(3, rho=0.3, vol=0.02)
    sigma_b = _equal_corr_cov(3, rho=0.3, vol=2.0)  # 100배
    enb_a = compute_enb(_equal_weights(sigma_a), sigma_a)
    enb_b = compute_enb(_equal_weights(sigma_b), sigma_b)
    assert enb_a == pytest.approx(enb_b, abs=1e-6)


def test_enb_non_psd_warning(caplog):
    # 음수 eigenvalue 인 가짜 cov — 클립 + 경고
    n = 3
    tickers = [f"A{i:06d}" for i in range(n)]
    M = np.array([[0.01, 0.02, 0.0], [0.02, 0.01, 0.0], [0.0, 0.0, 0.01]])
    sigma = pd.DataFrame(M, index=tickers, columns=tickers)  # not PSD
    with caplog.at_level("WARNING"):
        enb = compute_enb(_equal_weights(sigma), sigma)
    assert enb > 0  # 클립 후 계산 성공
    assert any("non-PSD" in r.message or "eigenvalue" in r.message.lower()
               for r in caplog.records)


def test_enb_zero_portfolio_variance():
    n = 3
    tickers = [f"A{i:06d}" for i in range(n)]
    sigma = pd.DataFrame(np.eye(n) * 1e-20, index=tickers, columns=tickers)
    enb = compute_enb(_equal_weights(sigma), sigma)
    # equal split → ENB = n
    assert enb == pytest.approx(n, abs=1e-6)


def test_minimum_torsion_matrix_decorrelates():
    sigma = _equal_corr_cov(4, rho=0.4).values
    T = minimum_torsion_matrix(sigma)
    transformed = T @ sigma @ T.T
    expected_diag = np.diag(np.diag(sigma))
    # off-diagonal 가 거의 0 (numerical 1e-9)
    off_diag = transformed - np.diag(np.diag(transformed))
    assert np.max(np.abs(off_diag)) < 1e-9
    # 분산은 보존 (diag(diag(Σ)) 와 동일)
    assert np.allclose(np.diag(transformed), np.diag(expected_diag), atol=1e-9)
```

- [ ] **Step 3: 테스트 실행 — 모두 NotImplementedError 로 실패 확인**

Run: `pytest tests/unit/skills/test_portfolio_diversification.py -v`
Expected: 8 tests, all FAILED (NotImplementedError)

- [ ] **Step 4: 커밋 (skeleton + 실패 테스트)**

```bash
git add tradingagents/skills/portfolio/diversification.py \
        tests/unit/skills/test_portfolio_diversification.py
git commit -m "feat(stage3): diversification 모듈 skeleton + ENB canonical 테스트

Phase 1 spec docs/superpowers/specs/2026-05-28-stage3-phase1-cash-spillover-design.md
의 ENB minimum-torsion 측정 모듈. 현 단계는 NotImplementedError stub + 8개
canonical 테스트 (single/uncorr/perf-corr/half-corr/scale-inv/non-PSD/zero-var/
torsion-decorrelates) 모두 실패."
```

---

### Task 2: minimum_torsion 알고리즘 구현

**Files:**
- Modify: `tradingagents/skills/portfolio/diversification.py`

- [ ] **Step 1: `_matrix_inv_sqrt`, `minimum_torsion_matrix`, `minimum_torsion_decomposition` 구현**

`tradingagents/skills/portfolio/diversification.py` 의 stub 들을 실제 구현으로 교체:

```python
import logging
logger = logging.getLogger(__name__)


def _matrix_inv_sqrt(A: np.ndarray) -> np.ndarray:
    """대칭 행렬의 역제곱근. 음수 eigenvalue 는 클립 + WARNING."""
    vals, vecs = np.linalg.eigh(A)
    n_clipped = int(np.sum(vals < ENB_NUMERICAL_FLOOR))
    if n_clipped > 0:
        logger.warning(
            "non-PSD matrix: %d/%d eigenvalues < %.0e — clipping",
            n_clipped, len(vals), ENB_NUMERICAL_FLOOR,
        )
    vals_clipped = np.maximum(vals, ENB_NUMERICAL_FLOOR)
    return vecs @ np.diag(1.0 / np.sqrt(vals_clipped)) @ vecs.T


def minimum_torsion_matrix(sigma: np.ndarray) -> np.ndarray:
    """T such that T Σ Tᵀ = diag(diag(Σ)).

    Closed form (Meucci-Santangelo-Deguest 2015):
        T = D^(1/2) × C^(-1/2) × D^(-1/2)
    where D = diag(diag(Σ)), C = D^(-1/2) Σ D^(-1/2).
    """
    diag_var = np.diag(sigma)
    if np.any(diag_var <= 0):
        raise ValueError(
            f"non-positive diagonal in covariance: min={diag_var.min():.3e}"
        )
    D_sqrt = np.diag(np.sqrt(diag_var))
    D_inv_sqrt = np.diag(1.0 / np.sqrt(diag_var))
    C = D_inv_sqrt @ sigma @ D_inv_sqrt
    C_inv_sqrt = _matrix_inv_sqrt(C)
    return D_sqrt @ C_inv_sqrt @ D_inv_sqrt


def minimum_torsion_decomposition(w: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """반환 p_i: 비상관 factor i 의 분산 기여 (합 1).

    e = T^(-T) w   (exposures, n-vector)
    factor_var_i = e_i² × diag(Σ)_i
    p_i = factor_var_i / (w^T Σ w)
    """
    n = len(w)
    if n == 1:
        return np.array([1.0])
    T = minimum_torsion_matrix(sigma)
    exposures = np.linalg.solve(T.T, w)
    diag_var = np.diag(sigma)
    factor_var = exposures ** 2 * diag_var
    port_var = float(w @ sigma @ w)
    if port_var <= ENB_NUMERICAL_FLOOR:
        return np.full(n, 1.0 / n)
    p = factor_var / port_var
    p = np.maximum(p, 0.0)
    s = p.sum()
    return p / s if s > 0 else np.full(n, 1.0 / n)
```

- [ ] **Step 2: `test_minimum_torsion_matrix_decorrelates` 통과 확인**

Run: `pytest tests/unit/skills/test_portfolio_diversification.py::test_minimum_torsion_matrix_decorrelates -v`
Expected: PASS

- [ ] **Step 3: 커밋**

```bash
git add tradingagents/skills/portfolio/diversification.py
git commit -m "feat(stage3): minimum_torsion 알고리즘 구현 (Meucci-Santangelo-Deguest 2015)

closed-form T = D^(1/2) C^(-1/2) D^(-1/2). 음수 eigenvalue 는 1e-12 로 클립 +
warning. test_minimum_torsion_matrix_decorrelates 통과."
```

---

### Task 3: `compute_enb` 구현 + 나머지 7개 canonical 테스트 통과

**Files:**
- Modify: `tradingagents/skills/portfolio/diversification.py`

- [ ] **Step 1: `compute_enb` 구현**

```python
def compute_enb(
    weights: dict[str, float] | pd.Series,
    sigma: pd.DataFrame,
    method: Literal["minimum_torsion", "pca"] = "minimum_torsion",
) -> float:
    """ENB = exp(-Σ p_i ln p_i). p_i 는 method 따라 분해."""
    tickers = list(sigma.index)
    n = len(tickers)
    if n == 0:
        return 0.0
    if n == 1:
        return 1.0

    # weights → ndarray aligned with sigma index
    if isinstance(weights, pd.Series):
        w_dict = weights.to_dict()
    else:
        w_dict = weights
    w = np.array([float(w_dict.get(t, 0.0)) for t in tickers], dtype=float)
    w_sum = w.sum()
    if w_sum <= 0:
        return float(n)  # degenerate → equal split
    if abs(w_sum - 1.0) > 1e-6:
        w = w / w_sum

    S = sigma.values
    if method == "minimum_torsion":
        p = minimum_torsion_decomposition(w, S)
    elif method == "pca":
        p = _pca_decomposition(w, S)
    else:
        raise ValueError(
            f"unknown method {method!r} (expected 'minimum_torsion' or 'pca')"
        )

    p_safe = np.maximum(p, ENB_NUMERICAL_FLOOR)
    return float(np.exp(-np.sum(p_safe * np.log(p_safe))))


def _pca_decomposition(w: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """PCA 기반 분산 분해 (보조)."""
    vals, vecs = np.linalg.eigh(sigma)
    port_var = float(w @ sigma @ w)
    if port_var <= ENB_NUMERICAL_FLOOR:
        return np.full(len(w), 1.0 / len(w))
    factor_loadings = vecs.T @ w
    factor_var = factor_loadings ** 2 * vals
    p = factor_var / port_var
    p = np.maximum(p, 0.0)
    s = p.sum()
    return p / s if s > 0 else np.full(len(w), 1.0 / len(w))
```

- [ ] **Step 2: 전체 ENB 테스트 실행 — 8개 모두 통과**

Run: `pytest tests/unit/skills/test_portfolio_diversification.py -v`
Expected: 8 passed

- [ ] **Step 3: 커밋**

```bash
git add tradingagents/skills/portfolio/diversification.py
git commit -m "feat(stage3): compute_enb + PCA fallback 구현, 8 canonical 테스트 통과

ENB = exp(-Σ p_i ln p_i). minimum_torsion default + pca fallback.
single/uncorr/perf-corr/half-corr/scale-inv/non-PSD/zero-var/decorrelates 모두 PASS."
```

---

### Task 4: cash_spillover 모듈 schema + Constants

**Files:**
- Create: `tradingagents/skills/portfolio/cash_spillover.py`
- Test:   `tests/unit/skills/test_portfolio_cash_spillover.py`

- [ ] **Step 1: schema + constants + API stub 작성**

`tradingagents/skills/portfolio/cash_spillover.py`:
```python
"""Cash spillover — bucket-level conviction → redistribution to cash.

Phase 1 도입. Stage 2 macro bucket_target 을 micro evidence (alpha + ENB) 기반
conviction 으로 조정. conviction < threshold 면 비례 spillover, cash bucket cap
초과 시 high-conviction bucket 으로 재분배.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills.portfolio.diversification import compute_enb

logger = logging.getLogger(__name__)


SPILLOVER_THRESHOLD_DEFAULT: float = 0.3
SPILLOVER_THRESHOLD_BY_BUCKET: dict[str, float] = {
    "fx_commodity": 0.15,
}
CASH_CAP_FOR_SPILLOVER_TARGET: float = 0.40
SPILLOVER_NUMERICAL_TOLERANCE: float = 1e-9


class ConvictionResult(BaseModel):
    bucket: str
    n_chosen: int
    mean_alpha: float
    enb: float
    threshold: float
    conviction: float
    spillover_ratio: float = Field(ge=0.0, le=1.0)


class SpilloverResult(BaseModel):
    adjusted_bucket_target: BucketTarget
    convictions: dict[str, ConvictionResult]
    cash_overflow_to_buckets: dict[str, float]
    total_spillover_to_cash: float
    cash_cap_triggered: bool
    thresholds: dict[str, float]


def _threshold_for(bucket: str) -> float:
    return SPILLOVER_THRESHOLD_BY_BUCKET.get(bucket, SPILLOVER_THRESHOLD_DEFAULT)


def compute_bucket_conviction(
    bucket: str,
    chosen: list[str],
    alpha_scores: dict[str, float],
    returns: pd.DataFrame,
) -> ConvictionResult:
    """Bucket conviction = (mean_alpha/threshold) × (ENB_equal_weight/√N)."""
    raise NotImplementedError


def adjust_bucket_targets(
    bucket_target: BucketTarget,
    bucket_chosen: dict[str, list[str]],
    alpha_scores_by_bucket: dict[str, dict[str, float]],
    returns: pd.DataFrame,
) -> SpilloverResult:
    """5 bucket conviction 계산 → 3-step redistribution.

    Step 1: bucket → cash_mmf 비례 spillover (cash_mmf 자체는 대상 아님)
    Step 2: effective_cap = max(0.40, bucket_target.cash_mmf) — macro 보존
    Step 3: overflow → high-conviction bucket conviction 가중 비례
    """
    raise NotImplementedError
```

- [ ] **Step 2: conviction 계산 단위 테스트 작성 (5개)**

`tests/unit/skills/test_portfolio_cash_spillover.py`:
```python
"""cash_spillover unit tests — conviction + redistribution invariants."""
import logging

import numpy as np
import pandas as pd
import pytest

from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills.portfolio.cash_spillover import (
    CASH_CAP_FOR_SPILLOVER_TARGET,
    SPILLOVER_THRESHOLD_BY_BUCKET,
    SPILLOVER_THRESHOLD_DEFAULT,
    ConvictionResult,
    adjust_bucket_targets,
    compute_bucket_conviction,
)


def _make_returns(tickers: list[str], n_days: int = 252, vol: float = 0.02, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    data = rng.normal(0.0, vol, size=(n_days, len(tickers)))
    return pd.DataFrame(data, columns=tickers)


def test_conviction_full_strength():
    """mean_alpha = threshold AND ENB = √N → conviction = 1.0, spillover_ratio = 0."""
    tickers = ["A000001", "A000002", "A000003", "A000004"]
    returns = _make_returns(tickers, seed=1)
    # alpha 평균이 SPILLOVER_THRESHOLD_DEFAULT 와 동일하게 설계
    alpha_scores = {t: SPILLOVER_THRESHOLD_DEFAULT for t in tickers}
    result = compute_bucket_conviction("kr_equity", tickers, alpha_scores, returns)
    assert result.bucket == "kr_equity"
    assert result.n_chosen == 4
    assert result.mean_alpha == pytest.approx(SPILLOVER_THRESHOLD_DEFAULT, abs=1e-9)
    assert result.threshold == SPILLOVER_THRESHOLD_DEFAULT
    # ENB 가 √N 에 가까우면 conviction ≈ 1
    assert result.conviction >= 0.9
    assert result.spillover_ratio == pytest.approx(0.0, abs=0.1)


def test_conviction_zero_alpha():
    """mean_alpha = 0 → conviction = 0, spillover_ratio = 1.0."""
    tickers = ["A000001", "A000002"]
    returns = _make_returns(tickers, seed=2)
    alpha_scores = {t: 0.0 for t in tickers}
    result = compute_bucket_conviction("kr_equity", tickers, alpha_scores, returns)
    assert result.conviction == pytest.approx(0.0, abs=1e-9)
    assert result.spillover_ratio == pytest.approx(1.0, abs=1e-9)


def test_conviction_empty_chosen():
    """chosen = [] → conviction 0, spillover 1.0, ENB 0."""
    returns = _make_returns(["A000001"], seed=3)
    result = compute_bucket_conviction("fx_commodity", [], {}, returns)
    assert result.n_chosen == 0
    assert result.mean_alpha == 0.0
    assert result.enb == 0.0
    assert result.conviction == 0.0
    assert result.spillover_ratio == 1.0


def test_conviction_fx_commodity_uses_specific_threshold():
    """fx_commodity 는 threshold 0.15 사용."""
    tickers = ["A411060", "A261220"]
    returns = _make_returns(tickers, seed=4)
    alpha_scores = {t: 0.1 for t in tickers}
    result = compute_bucket_conviction("fx_commodity", tickers, alpha_scores, returns)
    assert result.threshold == SPILLOVER_THRESHOLD_BY_BUCKET["fx_commodity"]
    assert result.threshold == 0.15


def test_conviction_single_chosen():
    """N=1 → ENB = 1. 공식 (mean_alpha/threshold) × (1/1) = mean_alpha/threshold."""
    tickers = ["A411060"]
    returns = _make_returns(tickers, seed=5)
    alpha_scores = {"A411060": 0.075}  # threshold/2
    result = compute_bucket_conviction("fx_commodity", tickers, alpha_scores, returns)
    assert result.n_chosen == 1
    assert result.enb == pytest.approx(1.0, abs=1e-9)
    expected_conviction = 0.075 / 0.15 * 1.0 / 1.0  # = 0.5
    assert result.conviction == pytest.approx(expected_conviction, abs=1e-9)
    assert result.spillover_ratio == pytest.approx(0.5, abs=1e-9)
```

- [ ] **Step 3: 실패 확인 + 커밋**

Run: `pytest tests/unit/skills/test_portfolio_cash_spillover.py -v`
Expected: 5 FAILED (NotImplementedError)

```bash
git add tradingagents/skills/portfolio/cash_spillover.py \
        tests/unit/skills/test_portfolio_cash_spillover.py
git commit -m "feat(stage3): cash_spillover schema + constants + conviction 테스트

ConvictionResult/SpilloverResult schema, threshold 상수 (default 0.3, fx 0.15),
cash cap 0.40. compute_bucket_conviction/adjust_bucket_targets stub.
5개 conviction 테스트 (full_strength, zero_alpha, empty, fx-threshold, single) 실패."
```

---

### Task 5: `compute_bucket_conviction` 구현

**Files:**
- Modify: `tradingagents/skills/portfolio/cash_spillover.py`

- [ ] **Step 1: 구현**

```python
def compute_bucket_conviction(
    bucket: str,
    chosen: list[str],
    alpha_scores: dict[str, float],
    returns: pd.DataFrame,
) -> ConvictionResult:
    threshold = _threshold_for(bucket)

    if not chosen:
        return ConvictionResult(
            bucket=bucket, n_chosen=0, mean_alpha=0.0, enb=0.0,
            threshold=threshold, conviction=0.0, spillover_ratio=1.0,
        )

    available = [t for t in chosen if t in returns.columns]
    if not available:
        return ConvictionResult(
            bucket=bucket, n_chosen=0, mean_alpha=0.0, enb=0.0,
            threshold=threshold, conviction=0.0, spillover_ratio=1.0,
        )

    # mean alpha 는 chosen 전부에 대해 (returns 누락 종목도 포함)
    alphas = [alpha_scores.get(t, 0.0) for t in chosen]
    mean_alpha = float(np.mean(alphas))

    n = len(available)
    if n == 1:
        enb = 1.0
    else:
        sub_returns = returns[available].dropna(axis=0, how="any")
        if sub_returns.empty or len(sub_returns) < 2:
            enb = float(n)  # cov 계산 불가 → equal split fallback
        else:
            sigma = sub_returns.cov()
            equal_w = {t: 1.0 / n for t in available}
            enb = compute_enb(equal_w, sigma, method="minimum_torsion")

    conviction = (mean_alpha / threshold) * (enb / np.sqrt(n))
    spillover_ratio = max(0.0, min(1.0, 1.0 - conviction / threshold)) if conviction < threshold else 0.0

    return ConvictionResult(
        bucket=bucket, n_chosen=n, mean_alpha=mean_alpha, enb=float(enb),
        threshold=threshold, conviction=float(conviction),
        spillover_ratio=float(spillover_ratio),
    )
```

- [ ] **Step 2: 5개 conviction 테스트 통과 확인**

Run: `pytest tests/unit/skills/test_portfolio_cash_spillover.py -v -k conviction`
Expected: 5 passed

- [ ] **Step 3: 커밋**

```bash
git add tradingagents/skills/portfolio/cash_spillover.py
git commit -m "feat(stage3): compute_bucket_conviction 구현

conviction = (mean_alpha/threshold) × (ENB_equal_weight/√N).
edge cases: empty chosen, N=1, returns 누락, cov 계산 불가 모두 처리.
5개 conviction 테스트 통과."
```

---

### Task 6: `adjust_bucket_targets` (3-step redistribution) 구현

**Files:**
- Modify: `tradingagents/skills/portfolio/cash_spillover.py`
- Test:   `tests/unit/skills/test_portfolio_cash_spillover.py` (테스트 추가)

- [ ] **Step 1: redistribution 테스트 추가 (5개)**

`tests/unit/skills/test_portfolio_cash_spillover.py` 끝에 append:
```python
def _make_full_universe_returns():
    tickers = (
        [f"K{i:05d}" for i in range(4)]    # kr_equity
        + [f"G{i:05d}" for i in range(4)]  # global_equity
        + [f"F{i:05d}" for i in range(2)]  # fx_commodity
        + [f"B{i:05d}" for i in range(4)]  # bond
        + [f"C{i:05d}" for i in range(2)]  # cash_mmf
    )
    return _make_returns(tickers, seed=42)


def _baseline_bucket_target() -> BucketTarget:
    return BucketTarget(
        kr_equity=0.20, global_equity=0.20, fx_commodity=0.15,
        bond=0.30, cash_mmf=0.15, bond_tips_share=0.30,
        rationale="test",
    )


def test_spillover_no_spillover_when_full_conviction():
    """모든 bucket conviction ≥ threshold → spillover 0, adjusted == original."""
    returns = _make_full_universe_returns()
    bt = _baseline_bucket_target()
    chosen = {
        "kr_equity":     [f"K{i:05d}" for i in range(4)],
        "global_equity": [f"G{i:05d}" for i in range(4)],
        "fx_commodity":  [f"F{i:05d}" for i in range(2)],
        "bond":          [f"B{i:05d}" for i in range(4)],
        "cash_mmf":      [f"C{i:05d}" for i in range(2)],
    }
    # 모두 alpha = threshold (full strength)
    alphas = {
        "kr_equity":     {t: 0.3 for t in chosen["kr_equity"]},
        "global_equity": {t: 0.3 for t in chosen["global_equity"]},
        "fx_commodity":  {t: 0.15 for t in chosen["fx_commodity"]},
        "bond":          {t: 0.3 for t in chosen["bond"]},
        "cash_mmf":      {t: 0.0 for t in chosen["cash_mmf"]},  # cash 항상 0
    }
    result = adjust_bucket_targets(bt, chosen, alphas, returns)
    assert result.total_spillover_to_cash == pytest.approx(0.0, abs=1e-9)
    assert result.cash_cap_triggered is False
    adj = result.adjusted_bucket_target
    assert adj.kr_equity == pytest.approx(bt.kr_equity, abs=1e-9)
    assert adj.bond == pytest.approx(bt.bond, abs=1e-9)


def test_spillover_fx_negative_only_goes_to_cash():
    """fx_commodity 모두 alpha=0 → bucket 100% cash 로 spillover."""
    returns = _make_full_universe_returns()
    bt = _baseline_bucket_target()
    chosen = {
        "kr_equity":     [f"K{i:05d}" for i in range(4)],
        "global_equity": [f"G{i:05d}" for i in range(4)],
        "fx_commodity":  [f"F{i:05d}" for i in range(2)],
        "bond":          [f"B{i:05d}" for i in range(4)],
        "cash_mmf":      [f"C{i:05d}" for i in range(2)],
    }
    alphas = {
        "kr_equity":     {t: 0.3 for t in chosen["kr_equity"]},
        "global_equity": {t: 0.3 for t in chosen["global_equity"]},
        "fx_commodity":  {t: 0.0 for t in chosen["fx_commodity"]},  # 음수만
        "bond":          {t: 0.3 for t in chosen["bond"]},
        "cash_mmf":      {t: 0.0 for t in chosen["cash_mmf"]},
    }
    result = adjust_bucket_targets(bt, chosen, alphas, returns)
    adj = result.adjusted_bucket_target
    assert adj.fx_commodity == pytest.approx(0.0, abs=1e-9)
    # fx bucket (0.15) 전체가 cash 로 흘러야 함. cash 0.15 + 0.15 = 0.30 (cap 0.40 이하)
    assert adj.cash_mmf == pytest.approx(0.30, abs=1e-9)
    assert result.total_spillover_to_cash == pytest.approx(0.15, abs=1e-9)
    assert result.cash_cap_triggered is False


def test_spillover_cash_cap_overflow_redistributes():
    """다수 bucket spillover → cash > 40% → overflow → high-conv bucket 으로."""
    returns = _make_full_universe_returns()
    bt = _baseline_bucket_target()
    chosen = {
        "kr_equity":     [f"K{i:05d}" for i in range(4)],
        "global_equity": [f"G{i:05d}" for i in range(4)],
        "fx_commodity":  [f"F{i:05d}" for i in range(2)],
        "bond":          [f"B{i:05d}" for i in range(4)],
        "cash_mmf":      [f"C{i:05d}" for i in range(2)],
    }
    alphas = {
        "kr_equity":     {t: 0.3 for t in chosen["kr_equity"]},  # high conv (keeps)
        "global_equity": {t: 0.0 for t in chosen["global_equity"]},  # full spillover
        "fx_commodity":  {t: 0.0 for t in chosen["fx_commodity"]},   # full spillover
        "bond":          {t: 0.0 for t in chosen["bond"]},           # full spillover
        "cash_mmf":      {t: 0.0 for t in chosen["cash_mmf"]},
    }
    result = adjust_bucket_targets(bt, chosen, alphas, returns)
    adj = result.adjusted_bucket_target
    # cash_new = 0.15 + 0.20 + 0.15 + 0.30 = 0.80 → cap 0.40 → overflow 0.40
    # overflow 0.40 가 high_conv (kr_equity only) 로
    assert result.cash_cap_triggered is True
    assert adj.cash_mmf == pytest.approx(0.40, abs=1e-9)
    assert adj.kr_equity == pytest.approx(0.20 + 0.40, abs=1e-9)


def test_spillover_all_low_conviction_warning(caplog):
    """모두 alpha=0 → cash 100% + warning."""
    returns = _make_full_universe_returns()
    bt = _baseline_bucket_target()
    chosen = {
        "kr_equity":     [f"K{i:05d}" for i in range(4)],
        "global_equity": [f"G{i:05d}" for i in range(4)],
        "fx_commodity":  [f"F{i:05d}" for i in range(2)],
        "bond":          [f"B{i:05d}" for i in range(4)],
        "cash_mmf":      [f"C{i:05d}" for i in range(2)],
    }
    alphas = {
        bucket: {t: 0.0 for t in chosen[bucket]}
        for bucket in chosen
    }
    with caplog.at_level(logging.WARNING):
        result = adjust_bucket_targets(bt, chosen, alphas, returns)
    # 모든 bucket low conviction → high_conv 비어있음 → cash > 40% 허용
    assert result.adjusted_bucket_target.cash_mmf > 0.40
    assert any("low-conviction" in r.message.lower() for r in caplog.records)


def test_spillover_invariants():
    """합 1 보존 + bond_tips_share 보존."""
    returns = _make_full_universe_returns()
    bt = _baseline_bucket_target()
    chosen = {
        "kr_equity":     [f"K{i:05d}" for i in range(4)],
        "global_equity": [f"G{i:05d}" for i in range(4)],
        "fx_commodity":  [f"F{i:05d}" for i in range(2)],
        "bond":          [f"B{i:05d}" for i in range(4)],
        "cash_mmf":      [f"C{i:05d}" for i in range(2)],
    }
    alphas = {
        "kr_equity":     {t: 0.20 for t in chosen["kr_equity"]},
        "global_equity": {t: 0.30 for t in chosen["global_equity"]},
        "fx_commodity":  {t: 0.05 for t in chosen["fx_commodity"]},
        "bond":          {t: 0.30 for t in chosen["bond"]},
        "cash_mmf":      {t: 0.0 for t in chosen["cash_mmf"]},
    }
    result = adjust_bucket_targets(bt, chosen, alphas, returns)
    adj = result.adjusted_bucket_target
    total = adj.kr_equity + adj.global_equity + adj.fx_commodity + adj.bond + adj.cash_mmf
    assert abs(total - 1.0) < 1e-9
    assert adj.bond_tips_share == bt.bond_tips_share
    # 모든 weight 비음수
    for b in ("kr_equity", "global_equity", "fx_commodity", "bond", "cash_mmf"):
        assert getattr(adj, b) >= 0.0
```

- [ ] **Step 2: 실행 — 5개 실패 확인**

Run: `pytest tests/unit/skills/test_portfolio_cash_spillover.py -v -k spillover`
Expected: 5 FAILED

- [ ] **Step 3: `adjust_bucket_targets` 구현**

`tradingagents/skills/portfolio/cash_spillover.py` 의 `adjust_bucket_targets` stub 교체:
```python
def adjust_bucket_targets(
    bucket_target: BucketTarget,
    bucket_chosen: dict[str, list[str]],
    alpha_scores_by_bucket: dict[str, dict[str, float]],
    returns: pd.DataFrame,
) -> SpilloverResult:
    # 입력 sanity
    total_in = (
        bucket_target.kr_equity + bucket_target.global_equity
        + bucket_target.fx_commodity + bucket_target.bond
        + bucket_target.cash_mmf
    )
    assert abs(total_in - 1.0) < SPILLOVER_NUMERICAL_TOLERANCE, (
        f"bucket_target sum {total_in} != 1.0"
    )

    bucket_names = ("kr_equity", "global_equity", "fx_commodity", "bond", "cash_mmf")

    # 1. 5 bucket conviction 계산
    convictions: dict[str, ConvictionResult] = {}
    for b in bucket_names:
        convictions[b] = compute_bucket_conviction(
            bucket=b,
            chosen=bucket_chosen.get(b, []),
            alpha_scores=alpha_scores_by_bucket.get(b, {}),
            returns=returns,
        )

    # 2. Step 1 — bucket → cash 비례 spillover (cash_mmf 제외)
    adjusted = {b: getattr(bucket_target, b) for b in bucket_names}
    spillover_amounts: dict[str, float] = {}
    for b in ("kr_equity", "global_equity", "fx_commodity", "bond"):
        amt = adjusted[b] * convictions[b].spillover_ratio
        spillover_amounts[b] = amt
        adjusted[b] -= amt
    cash_new = adjusted["cash_mmf"] + sum(spillover_amounts.values())

    # 3. Step 2 — effective_cap = max(0.40, macro cash) → macro 보존
    effective_cap = max(CASH_CAP_FOR_SPILLOVER_TARGET, bucket_target.cash_mmf)
    if cash_new <= effective_cap:
        adjusted["cash_mmf"] = cash_new
        overflow = 0.0
        cash_cap_triggered = False
    else:
        adjusted["cash_mmf"] = effective_cap
        overflow = cash_new - effective_cap
        cash_cap_triggered = True

    # 4. Step 3 — overflow → high-conviction bucket
    cash_overflow_to_buckets: dict[str, float] = {}
    if overflow > 0:
        high_conv = {
            b: convictions[b].conviction
            for b in ("kr_equity", "global_equity", "fx_commodity", "bond")
            if convictions[b].conviction >= convictions[b].threshold
        }
        if high_conv:
            total_weight = sum(high_conv.values())
            for b, c in high_conv.items():
                add = overflow * (c / total_weight)
                adjusted[b] += add
                cash_overflow_to_buckets[b] = add
        else:
            adjusted["cash_mmf"] += overflow
            logger.warning(
                "all buckets low-conviction; cash_mmf %.3f exceeds cap %.2f",
                adjusted["cash_mmf"], effective_cap,
            )

    # 5. 합 invariant 검증
    total_out = sum(adjusted.values())
    if abs(total_out - 1.0) > SPILLOVER_NUMERICAL_TOLERANCE:
        raise RuntimeError(
            f"spillover sum invariant broken: total_out={total_out}"
        )

    # 6. BucketTarget 새 instance (bond_tips_share 보존)
    adjusted_bt = BucketTarget(
        kr_equity=adjusted["kr_equity"],
        global_equity=adjusted["global_equity"],
        fx_commodity=adjusted["fx_commodity"],
        bond=adjusted["bond"],
        cash_mmf=adjusted["cash_mmf"],
        bond_tips_share=bucket_target.bond_tips_share,
        rationale=(
            f"{bucket_target.rationale or ''} | spillover {sum(spillover_amounts.values()):.3f} → cash"
        )[:300],
    )

    return SpilloverResult(
        adjusted_bucket_target=adjusted_bt,
        convictions=convictions,
        cash_overflow_to_buckets=cash_overflow_to_buckets,
        total_spillover_to_cash=sum(spillover_amounts.values()),
        cash_cap_triggered=cash_cap_triggered,
        thresholds={b: _threshold_for(b) for b in bucket_names},
    )
```

- [ ] **Step 4: 전체 cash_spillover 테스트 통과 확인**

Run: `pytest tests/unit/skills/test_portfolio_cash_spillover.py -v`
Expected: 10 passed (5 conviction + 5 spillover)

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/skills/portfolio/cash_spillover.py \
        tests/unit/skills/test_portfolio_cash_spillover.py
git commit -m "feat(stage3): adjust_bucket_targets 3-step redistribution 구현

Step 1: bucket → cash 비례 spillover. Step 2: effective_cap = max(0.40, macro_cash)
로 macro 침해 방지. Step 3: overflow → high-conv bucket 가중 비례.
bond_tips_share 보존, 합 1 invariant 검증. 10개 테스트 통과."
```

---

### Task 7: `candidate_selector.py` — AUM 필터 제거

**Files:**
- Modify: `tradingagents/skills/portfolio/candidate_selector.py`
- Modify: `tests/unit/skills/test_portfolio_candidate.py`

- [ ] **Step 1: 기존 candidate 테스트에 새 케이스 추가**

`tests/unit/skills/test_portfolio_candidate.py` 끝에 append:
```python
def test_eligibility_no_aum_filter():
    """AUM 필터 제거 후: 100억 ETF 도 통과."""
    from datetime import date

    from tradingagents.dataflows.universe import ETFEntry, Universe
    from tradingagents.schemas.portfolio import BucketTarget
    from tradingagents.skills.portfolio.candidate_selector import list_eligible_tickers

    universe = Universe(version="test", etfs=[
        ETFEntry(
            ticker="A111111", name="Big", aum_krw=100_000_000_000,
            underlying_index="X", bucket="위험", category="국내주식_지수",
        ),
        ETFEntry(
            ticker="A222222", name="Small", aum_krw=10_000_000_000,  # 100억
            underlying_index="X", bucket="위험", category="국내주식_지수",
        ),
    ])
    bt = BucketTarget(
        kr_equity=0.5, global_equity=0.0, fx_commodity=0.0,
        bond=0.0, cash_mmf=0.5, bond_tips_share=0.0,
        rationale="test",
    )
    eligible = list_eligible_tickers(universe, bt, as_of=date(2026, 5, 28))
    assert "A111111" in eligible["kr_equity"]
    assert "A222222" in eligible["kr_equity"]  # 100억도 통과
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/unit/skills/test_portfolio_candidate.py::test_eligibility_no_aum_filter -v`
Expected: FAIL (TypeError or AUM 필터로 제외됨)

- [ ] **Step 3: candidate_selector.py 에서 AUM 관련 제거**

`tradingagents/skills/portfolio/candidate_selector.py` — 다음 항목 모두 제거:

```python
# 제거: DEFAULT_MIN_AUM_KRW = 50_000_000_000   (line 34)
# 제거: _RELAXED_MIN_AUM_KRW dict              (line 38-40)
# 제거: _min_aum_for_etf 함수                  (line 51-60)
```

`_eligible_for_bucket` 수정 (line 63-68):
```python
def _eligible_for_bucket(universe: Universe, cats: list[str]):
    return [e for e in universe.etfs if e.category in cats]
```

`list_eligible_tickers` 수정 (line 71-96):
```python
def list_eligible_tickers(
    universe: Universe,
    bucket_target: BucketTarget,
    as_of: date,
) -> dict[str, list[str]]:
    """Return tickers passing hard filters (tradable + category), pre-ranking."""
    universe = universe.tradable_at(as_of)
    out: dict[str, list[str]] = {}
    for bucket_name, weight in [
        ("kr_equity", bucket_target.kr_equity),
        ("global_equity", bucket_target.global_equity),
        ("fx_commodity", bucket_target.fx_commodity),
        ("bond", bucket_target.bond),
        ("cash_mmf", bucket_target.cash_mmf),
    ]:
        if weight <= 0:
            out[bucket_name] = []
            continue
        cats = BUCKET_TO_CATEGORIES[bucket_name]
        out[bucket_name] = [e.ticker for e in _eligible_for_bucket(universe, cats)]
    return out
```

`select_etf_candidates` 시그니처에서 `min_aum_krw` 파라미터 제거 (line 100-124). 본문 line 142 의 `min_aum_krw` 참조 모두 제거. 본문에서 `_eligible_for_bucket(universe, cats, min_aum_krw)` 호출 (line 187, 200 등) 도 `_eligible_for_bucket(universe, cats)` 로 단순화. attribution 의 `"min_aum_krw":` 키 (line 159) 제거.

`_select_bond_with_tips_quota` 의 호출부에 `min_aum_krw` 가 안 나오는지 확인. (실제로 호출 안 함, OK)

- [ ] **Step 4: 새 테스트 + 기존 candidate 테스트 회귀 통과 확인**

Run: `pytest tests/unit/skills/test_portfolio_candidate.py -v`
Expected: all tests pass (기존 + 새 1개)

기존 테스트에 `min_aum_krw=` 키워드 인자 사용처가 있으면 TypeError 발생할 수 있음 → 해당 테스트에서 인자 제거.

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/skills/portfolio/candidate_selector.py \
        tests/unit/skills/test_portfolio_candidate.py
git commit -m "refactor(stage3): candidate_selector AUM hard 필터 제거

대회 universe (GAPS 12회) 가 사전 큐레이션되어 추가 AUM 필터 불요. 신호 손실
방지를 위해 DEFAULT_MIN_AUM_KRW, _RELAXED_MIN_AUM_KRW, _min_aum_for_etf 모두 제거.
list_eligible_tickers / select_etf_candidates / _eligible_for_bucket 시그니처에서
min_aum_krw 파라미터 제거. test_eligibility_no_aum_filter 추가."
```

---

### Task 8: `candidate_selector.py` — bond bucket alpha_scores merge 보강

**Files:**
- Modify: `tradingagents/skills/portfolio/candidate_selector.py`
- Modify: `tests/unit/skills/test_portfolio_candidate.py`

- [ ] **Step 1: bond 통합 alpha_scores 테스트 추가**

`tests/unit/skills/test_portfolio_candidate.py` 끝에 append:
```python
def test_bond_split_path_populates_bucket_alpha_scores():
    """_select_bond_with_tips_quota 후 attribution['buckets']['bond']['alpha_scores']
    가 sub_pool 들의 alpha 를 통합해 채워져 있어야 함 (cash_spillover 의존)."""
    from datetime import date
    import pandas as pd
    import numpy as np

    from tradingagents.dataflows.universe import ETFEntry, Universe
    from tradingagents.schemas.portfolio import BucketTarget
    from tradingagents.skills.portfolio.candidate_selector import select_etf_candidates
    from tradingagents.skills.portfolio.factor_scorer import FactorPanel

    # bond bucket 후보: TIPS 1개 + nominal 2개
    etfs = [
        ETFEntry(
            ticker="A_TIPS01", name="TIPS01", aum_krw=10_000_000_000,
            underlying_index="ICE TIPS", bucket="안전", category="해외채권_종합",
            sub_category="inflation_linked",
        ),
        ETFEntry(
            ticker="A_NOM01", name="NOM01", aum_krw=50_000_000_000,
            underlying_index="KIS A", bucket="안전", category="국내채권_종합",
            sub_category="nominal",
        ),
        ETFEntry(
            ticker="A_NOM02", name="NOM02", aum_krw=30_000_000_000,
            underlying_index="KIS B", bucket="안전", category="국내채권_종합",
            sub_category="nominal",
        ),
    ]
    universe = Universe(version="test", etfs=etfs)
    bt = BucketTarget(
        kr_equity=0.0, global_equity=0.0, fx_commodity=0.0,
        bond=0.7, cash_mmf=0.3, bond_tips_share=0.3,
        rationale="test",
    )
    # 가짜 returns + factor_panel
    rng = np.random.default_rng(7)
    returns = pd.DataFrame(
        rng.normal(0, 0.01, size=(252, 3)),
        columns=["A_TIPS01", "A_NOM01", "A_NOM02"],
    )
    factor_panel = {
        t: FactorPanel(
            skip1m_mom_3m=0.0, skip1m_mom_6m=0.0, skip1m_mom_12m=0.0,
            realized_vol_60d=0.05, sharpe_60d=0.5,
            log_aum=np.log(50_000_000_000),
        )
        for t in ["A_TIPS01", "A_NOM01", "A_NOM02"]
    }
    attribution: dict = {}
    select_etf_candidates(
        universe, bt, as_of=date(2026, 5, 28),
        returns=returns, factor_panel=factor_panel,
        per_bucket_n=3, attribution=attribution,
    )
    bond_attr = attribution["buckets"]["bond"]
    assert "alpha_scores" in bond_attr
    # TIPS + nominal 모든 ticker 가 통합 alpha_scores 에 포함
    assert set(bond_attr["alpha_scores"].keys()) >= {"A_TIPS01", "A_NOM01", "A_NOM02"}
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/unit/skills/test_portfolio_candidate.py::test_bond_split_path_populates_bucket_alpha_scores -v`
Expected: FAIL (KeyError or alpha_scores 누락)

- [ ] **Step 3: `_select_bond_with_tips_quota` 보강**

`tradingagents/skills/portfolio/candidate_selector.py` 의 `_select_bond_with_tips_quota` 끝부분 (line 348-356, `breakdown_out is not None` 블록) 에 alpha_scores 통합 merge 추가:

```python
if breakdown_out is not None:
    breakdown_out["bond_split"] = True
    breakdown_out["tips_share"] = tips_share
    breakdown_out["tips_quota"] = tips_quota
    breakdown_out["nominal_quota"] = nominal_quota
    breakdown_out["sub_pools"] = sub_pool_breakdowns
    breakdown_out["selection_traces"] = sub_pool_traces
    breakdown_out["tips_picks"] = tips_picks
    breakdown_out["nominal_picks"] = nominal_picks
    # NEW: bucket level merged alpha_scores — cash_spillover 가 사용
    merged_alpha: dict[str, float] = {}
    for label, sp in sub_pool_breakdowns.items():
        per_t = sp.get("per_ticker") or {}
        for t, info in per_t.items():
            score = info.get("final_score")
            if score is None:
                score = info.get("base_score", 0.0)
            merged_alpha[t] = float(score)
    breakdown_out["alpha_scores"] = merged_alpha
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/unit/skills/test_portfolio_candidate.py::test_bond_split_path_populates_bucket_alpha_scores -v`
Expected: PASS

전체 candidate 테스트 회귀:
Run: `pytest tests/unit/skills/test_portfolio_candidate.py -v`
Expected: all pass

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/skills/portfolio/candidate_selector.py \
        tests/unit/skills/test_portfolio_candidate.py
git commit -m "refactor(stage3): bond bucket alpha_scores merge 보강

_select_bond_with_tips_quota 의 sub_pool (tips/nominal) per_ticker alpha 들을
bucket level alpha_scores 로 통합 — cash_spillover._collect_alpha_scores_per_bucket
이 의존."
```

---

### Task 9: `factor_scorer.py` — `select_cluster_aware` 음수 fill 제거

**Files:**
- Modify: `tradingagents/skills/portfolio/factor_scorer.py`
- Modify: `tests/unit/skills/test_portfolio_factor_scorer.py`

- [ ] **Step 1: 새 테스트 3개 추가**

`tests/unit/skills/test_portfolio_factor_scorer.py` 끝에 append:
```python
def _alpha_scores(values: dict[str, float]) -> dict[str, float]:
    return values


def _impl_scores(values: dict[str, float]) -> dict[str, float]:
    return values


def test_select_cluster_aware_no_negative_fill():
    """양수 group < n//2 면 음수 fill 안 함, 짧은 chosen 반환."""
    from tradingagents.skills.portfolio.factor_scorer import select_cluster_aware

    eligible = ["A", "B", "C", "D"]
    alpha = _alpha_scores({"A": 0.5, "B": -0.1, "C": -0.2, "D": -0.3})
    impl = _impl_scores({t: 1.0 for t in eligible})
    chosen = select_cluster_aware(
        eligible=eligible, alpha_scores=alpha, impl_scores=impl,
        clusters=None, n=4, returns=None,
        require_positive_alpha=True,
    )
    # 양수 1개 + 음수 fill 없음 → chosen 1개 (A 만)
    assert chosen == ["A"]


def test_select_cluster_aware_padding_positive_only():
    """padding 단계도 양수만 fill — 양수 부족해도 음수 추가하지 않음."""
    from tradingagents.skills.portfolio.factor_scorer import select_cluster_aware

    eligible = ["A", "B", "C", "D", "E"]
    # 그룹이 모두 singleton, 양수 2개, 나머지 음수
    alpha = _alpha_scores({"A": 0.5, "B": 0.4, "C": -0.1, "D": -0.2, "E": -0.3})
    impl = _impl_scores({t: 1.0 for t in eligible})
    chosen = select_cluster_aware(
        eligible=eligible, alpha_scores=alpha, impl_scores=impl,
        clusters=None, n=5, returns=None,
        require_positive_alpha=True,
    )
    # 양수 2개만, padding 도 양수만
    assert chosen == ["A", "B"]


def test_select_cluster_aware_all_negative_returns_empty():
    """모든 group alpha 음수 → require_positive_alpha=True 면 빈 chosen."""
    from tradingagents.skills.portfolio.factor_scorer import select_cluster_aware

    eligible = ["A", "B"]
    alpha = _alpha_scores({"A": -0.1, "B": -0.2})
    impl = _impl_scores({"A": 1.0, "B": 1.0})
    chosen = select_cluster_aware(
        eligible=eligible, alpha_scores=alpha, impl_scores=impl,
        clusters=None, n=3, returns=None,
        require_positive_alpha=True,
    )
    assert chosen == []
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/unit/skills/test_portfolio_factor_scorer.py -v -k cluster_aware`
Expected: 새 3개 FAIL (현재 코드가 음수 fill 함)

- [ ] **Step 3: `select_cluster_aware` 음수 fill 제거**

`tradingagents/skills/portfolio/factor_scorer.py` line 556-569:
```python
# 기존
if require_positive_alpha:
    positive_groups = [(a, r, g) for (a, r, g) in group_repr if a > 0]
    min_required = max(1, n // 2)
    if len(positive_groups) >= min_required:
        group_repr_filtered = positive_groups
    elif group_repr:
        negative_groups = [(a, r, g) for (a, r, g) in group_repr if a <= 0]
        shortfall = min_required - len(positive_groups)
        group_repr_filtered = positive_groups + negative_groups[:shortfall]
    else:
        group_repr_filtered = []
else:
    group_repr_filtered = group_repr
```
→ 새 코드:
```python
if require_positive_alpha:
    group_repr_filtered = [(a, r, g) for (a, r, g) in group_repr if a > 0]
else:
    group_repr_filtered = group_repr
```

Padding 단계 (line 608-618) 도 음수 fill 분기 제거:
```python
# 기존
if require_positive_alpha:
    min_required_total = max(1, n // 2)
    positive_remaining = [
        t for t in remaining if alpha_scores.get(t, float("-inf")) > 0
    ]
    if len(chosen) + len(positive_remaining) >= min_required_total:
        remaining = positive_remaining
    # else: 양수 부족 → remaining 그대로 (음수 포함)
```
→ 새 코드:
```python
if require_positive_alpha:
    remaining = [
        t for t in remaining if alpha_scores.get(t, float("-inf")) > 0
    ]
```

selection_trace 의 "[excluded: alpha ≤ 0]" reason 표시 (line 580-587) 은 유지 — 음수 group 정보는 attribution 에 남김.

- [ ] **Step 4: 새 3개 + 기존 factor_scorer 회귀 통과 확인**

Run: `pytest tests/unit/skills/test_portfolio_factor_scorer.py -v`
Expected: all pass

기존 테스트 중 음수 fill 을 기대하던 케이스가 있으면 update (chosen 길이가 짧아진 새 동작 반영).

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/skills/portfolio/factor_scorer.py \
        tests/unit/skills/test_portfolio_factor_scorer.py
git commit -m "refactor(stage3): select_cluster_aware 음수 alpha fill 제거

require_positive_alpha=True 시 양수 group 만 chosen 에 포함. padding 단계도
양수만. chosen 이 n 보다 짧을 수 있음 — caller (cash_spillover) 가 처리.
3개 새 테스트 (no_negative_fill, padding_positive_only, all_negative_empty) 통과."
```

---

### Task 10: `portfolio_allocator.py` — module constants + helper 함수

**Files:**
- Modify: `tradingagents/agents/allocator/portfolio_allocator.py`

- [ ] **Step 1: ENB_WARNING_THRESHOLD + helper 추가**

`tradingagents/agents/allocator/portfolio_allocator.py` 상단 (named constants 섹션, line 30 부근) 에 추가:
```python
# Phase 1 (Stage 3 phase1-cash-spillover spec, 2026-05-28).
ENB_WARNING_THRESHOLD: float = 3.0
```

기존 import 블록 (line 12-25) 에 추가:
```python
from tradingagents.skills.portfolio.cash_spillover import adjust_bucket_targets
from tradingagents.skills.portfolio.diversification import compute_enb
```

모듈 끝 (`return node` 다음, 모듈 함수 자리) 에 helper 추가:
```python
def _collect_alpha_scores_per_bucket(
    attribution: dict,
) -> dict[str, dict[str, float]]:
    """attribution['buckets'][bucket]['alpha_scores'] 에서 추출.

    candidate_selector 가 채워둠. bond bucket 의 split path 도 변경 모듈 C
    의 보강으로 같은 키 사용.
    """
    out: dict[str, dict[str, float]] = {}
    for bucket_name, bucket_attr in (attribution.get("buckets") or {}).items():
        alpha_scores = bucket_attr.get("alpha_scores") or {}
        out[bucket_name] = dict(alpha_scores)
    return out
```

- [ ] **Step 2: 임포트 정상 동작 확인**

Run: `python -c "from tradingagents.agents.allocator.portfolio_allocator import _collect_alpha_scores_per_bucket; print('ok')"`
Expected: `ok`

- [ ] **Step 3: 커밋**

```bash
git add tradingagents/agents/allocator/portfolio_allocator.py
git commit -m "feat(stage3): allocator 에 ENB_WARNING_THRESHOLD + helper 추가

Phase 1 hook 들이 사용할 ENB warning threshold (3.0) 와
_collect_alpha_scores_per_bucket helper. 다음 task 에서 hook 통합."
```

---

### Task 11: `portfolio_allocator.py` — `S` (sample_cov) 양 경로 보장

**Files:**
- Modify: `tradingagents/agents/allocator/portfolio_allocator.py`

- [ ] **Step 1: `S` 산출을 HRP 분기 이전으로 이동**

기존 `_optimize_with_bucket_constraints` line 405-453 의 흐름:
```python
# (기존)
if method == OptimizationMethod.HRP:
    return _hrp_per_bucket(...)
S = risk_models.sample_cov(returns)
...
```

새 코드:
```python
# 표본 부족 처리 후, HRP 분기 진입 전에 S 항상 산출.
# HRP 경로는 자체 sub-pool cov 를 별도로 계산하므로 충돌 없음.
S = risk_models.sample_cov(returns)

if method == OptimizationMethod.HRP:
    wv = _hrp_per_bucket(
        returns, candidates, bucket_target, sub_category_lookup,
        attribution=attribution,
    )
    return wv, S   # NEW: S 도 함께 반환
```

`_optimize_with_bucket_constraints` 시그니처/반환 타입을 `(WeightVector, pd.DataFrame)` 으로 변경:
```python
def _optimize_with_bucket_constraints(
    ...
) -> tuple[WeightVector, pd.DataFrame]:
    ...
    # EF/BL/MaxSharpe 경로 끝
    return WeightVector(...), pd.DataFrame(S, index=returns.columns, columns=returns.columns)
```

HRP 분기에서도 `(wv, pd.DataFrame(S, index=..., columns=...))` 반환.

- [ ] **Step 2: 호출부 (line ~273) update**

기존:
```python
wv = _optimize_with_bucket_constraints(...)
```
→
```python
wv, sigma_df = _optimize_with_bucket_constraints(...)
```

- [ ] **Step 3: 기존 allocator 테스트 회귀 확인**

Run: `pytest tests/unit/skills/test_portfolio_optimizers.py tests/unit/skills/test_portfolio_attribution.py -v`
Expected: all pass (회귀 무손실)

- [ ] **Step 4: 커밋**

```bash
git add tradingagents/agents/allocator/portfolio_allocator.py
git commit -m "refactor(stage3): _optimize_with_bucket_constraints 가 (WeightVector, Σ) 반환

HRP 경로에서도 ENB 측정용 sigma_df 가 필요. risk_models.sample_cov 산출을
HRP 분기 이전으로 이동 후 양 경로에서 함께 반환. 기존 테스트 회귀 무손실."
```

---

### Task 12: `portfolio_allocator.py` — hook 1 (spillover) 통합

**Files:**
- Modify: `tradingagents/agents/allocator/portfolio_allocator.py`

- [ ] **Step 1: candidate selection 직후 spillover hook 삽입**

allocator node 의 line ~234 (candidates 산출 직후, `all_candidates = [...]` 라인 이전) 에 삽입:
```python
# Phase 1 — cash spillover (Stage 2 macro ↔ Stage 3 micro 화해)
alpha_scores_by_bucket = _collect_alpha_scores_per_bucket(attribution)
spillover_result = adjust_bucket_targets(
    bucket_target=bucket_target,
    bucket_chosen=candidates.bucket_to_tickers,
    alpha_scores_by_bucket=alpha_scores_by_bucket,
    returns=returns,
)
bucket_target = spillover_result.adjusted_bucket_target
attribution["cash_spillover"] = spillover_result.model_dump()
logger.info(
    "spillover: total_to_cash=%.4f, cap_triggered=%s, overflow_buckets=%s",
    spillover_result.total_spillover_to_cash,
    spillover_result.cash_cap_triggered,
    list(spillover_result.cash_overflow_to_buckets.keys()),
)
```

- [ ] **Step 2: method_picker, _optimize_with_bucket_constraints 가 새 bucket_target 사용 확인**

line ~257 (`method_choice = pick_optimization_method(...)`) 과 line ~273 (`wv, sigma_df = _optimize_with_bucket_constraints(...)`) 가 모두 갱신된 `bucket_target` 을 자동으로 사용 (변수 재할당). 추가 변경 없음.

attribution["config"]["bucket_target"] 의 값도 update 되어야 함. line 159-165 (attribution config 초기 채움) 이후 spillover 발생했으니, 다시 한 번 sync:
```python
# attribution config 의 bucket_target snapshot 도 update (감사 용이).
attribution["config"]["bucket_target"] = {
    "kr_equity":     bucket_target.kr_equity,
    "global_equity": bucket_target.global_equity,
    "fx_commodity":  bucket_target.fx_commodity,
    "bond":          bucket_target.bond,
    "cash_mmf":      bucket_target.cash_mmf,
}
attribution["config"]["bond_tips_share"] = bucket_target.bond_tips_share
```

이걸 spillover hook 직후에 삽입.

- [ ] **Step 3: 기존 통합 테스트 + smoke 통과 확인**

Run: `pytest tests/integration/test_phase1_smoke.py -v` (있다면)
Expected: pass

Run: `pytest tests/unit/skills/test_portfolio_attribution.py -v`
Expected: pass

(테스트 깨지면 attribution 의 새 키 `cash_spillover` 가 schema 검증을 통과하는지 확인. allocation_attribution 은 dict 형태라 자유 — 보통 OK)

- [ ] **Step 4: 커밋**

```bash
git add tradingagents/agents/allocator/portfolio_allocator.py
git commit -m "feat(stage3): allocator hook 1 — cash spillover 통합

candidate selection 직후 adjust_bucket_targets 호출. bucket_target 갱신 후
method_picker/optimize 가 새 bucket_target 사용. attribution['cash_spillover']
+ attribution['config']['bucket_target'] snapshot 도 sync."
```

---

### Task 13: `portfolio_allocator.py` — hook 2 (ENB) 통합

**Files:**
- Modify: `tradingagents/agents/allocator/portfolio_allocator.py`

- [ ] **Step 1: weight_vector 산출 직후 ENB 측정**

`wv, sigma_df = _optimize_with_bucket_constraints(...)` 호출 직후 (line ~283 기준) 에 삽입:
```python
# Phase 1 — ENB 사후 측정 (warning-only)
try:
    enb_value = compute_enb(wv.weights, sigma_df, method="minimum_torsion")
except Exception as e:
    logger.warning("ENB 계산 실패: %s", e)
    enb_value = 0.0
attribution["enb"] = float(enb_value)
if enb_value > 0 and enb_value < ENB_WARNING_THRESHOLD:
    logger.warning(
        "ENB %.2f < %.2f — possible insufficient diversification",
        enb_value, ENB_WARNING_THRESHOLD,
    )
```

- [ ] **Step 2: 기존 통합 테스트 회귀 확인**

Run: `pytest tests/integration/test_phase1_smoke.py tests/unit/skills/test_portfolio_attribution.py -v`
Expected: pass

- [ ] **Step 3: 커밋**

```bash
git add tradingagents/agents/allocator/portfolio_allocator.py
git commit -m "feat(stage3): allocator hook 2 — ENB 사후 측정 (warning-only)

weight_vector 산출 직후 compute_enb(wv.weights, sigma_df). attribution['enb']
에 기록 + ENB < 3.0 시 warning log. 차단 동작은 Phase 4."
```

---

### Task 14: Integration 테스트 — allocator phase1

**Files:**
- Create: `tests/integration/test_allocator_phase1.py`

- [ ] **Step 1: 통합 테스트 5개 작성**

`tests/integration/test_allocator_phase1.py`:
```python
"""Phase 1 integration — allocator pipeline 의 spillover + ENB 통합 검증.

가짜 universe 와 returns 로 5 개 시나리오:
  1. 정상 universe (모두 양수 alpha) → spillover 0, ENB 양호
  2. fx_commodity 음수 only → fx 100% spillover
  3. global low conviction → 부분 spillover
  4. attribution completeness
  5. cash overflow → high-conv redistribution
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingagents.dataflows.universe import ETFEntry, Universe
from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.schemas.research import ResearchDecision
from tradingagents.agents.allocator.portfolio_allocator import (
    create_portfolio_allocator,
)


@pytest.fixture
def synthetic_universe(tmp_path):
    """5 bucket × 4 ticker = 20 ETF universe."""
    etfs = []
    for prefix, cat, sub in [
        ("KR", "국내주식_지수", None),
        ("GL", "해외주식_지수", None),
        ("FX", "FX 및 원자재", "gold"),
        ("BD", "국내채권_종합", "nominal"),
        ("CS", "금리연계형/초단기채권", None),
    ]:
        for i in range(4):
            etfs.append(ETFEntry(
                ticker=f"A_{prefix}{i:02d}", name=f"{prefix}{i}",
                aum_krw=50_000_000_000,
                underlying_index=f"{prefix}_idx_{i}",
                bucket="안전" if prefix in ("BD", "CS") else "위험",
                category=cat, sub_category=sub,
            ))
    universe = Universe(version="test", etfs=etfs)
    path = tmp_path / "universe.json"
    path.write_text(universe.model_dump_json())
    return path


def _make_state(universe_path, alpha_overrides=None):
    """Allocator state stub. alpha_overrides: dict[bucket, dict[ticker, alpha]]."""
    # 실제 state 구성은 build process 모킹 — 여기선 직접 호출 인터페이스 가정
    raise NotImplementedError(
        "이 테스트는 allocator state 구성 helper 가 필요합니다. "
        "현재는 spec 의 acceptance criterion (d) 를 검증할 수 있는 골격으로만 작성. "
        "실제 통합은 tests/integration/test_phase1_smoke.py 기존 fixture 확장으로 진행."
    )


@pytest.mark.skip(reason="state mocking 헬퍼 후속 작업 — Task 15 의 regression_compare 가 더 직접적")
def test_allocator_with_normal_universe(synthetic_universe):
    """5 bucket 양수 충분 → spillover 0, ENB > ENB_WARNING_THRESHOLD."""
    pass


@pytest.mark.skip(reason="state mocking 헬퍼 후속 작업")
def test_allocator_with_fx_negative_only(synthetic_universe):
    """fx_commodity 음수만 → fx bucket weight 감소, cash 증가."""
    pass


@pytest.mark.skip(reason="state mocking 헬퍼 후속 작업")
def test_allocator_with_global_low_conviction(synthetic_universe):
    """global 알파 낮음 → 부분 spillover."""
    pass


def test_allocator_attribution_completeness_via_smoke(tmp_path):
    """기존 phase1_smoke fixture 가 새 attribution 키 (cash_spillover, enb) 를 채우는지 검증."""
    # 가장 가벼운 통합 검증: smoke fixture 결과에서 allocation_attribution 가 확장됐는지.
    # 실 fixture 가 없으면 skip 처리. (있으면 그 산출물 검사)
    import os
    smoke_artifact = "artifacts/2026-05-15/portfolio.json"
    if not os.path.exists(smoke_artifact):
        pytest.skip(f"{smoke_artifact} 없음 — 회귀 케이스는 Task 15 의 regression_compare 에서 검증")
    import json
    with open(smoke_artifact) as f:
        portfolio = json.load(f)
    attribution = portfolio.get("allocation_attribution") or {}
    # Phase 1 적용 후 산출물이라면 이 키들이 있어야 함
    assert "cash_spillover" in attribution, (
        "Phase 1 적용 후 산출물에 cash_spillover 누락 — hook 1 미통합"
    )
    assert "enb" in attribution, (
        "Phase 1 적용 후 산출물에 enb 누락 — hook 2 미통합"
    )
    # 타입 검증
    assert isinstance(attribution["cash_spillover"], dict)
    assert isinstance(attribution["enb"], (int, float))


@pytest.mark.skip(reason="state mocking 헬퍼 후속 작업")
def test_allocator_cash_overflow_redistribution(synthetic_universe):
    """동시 다 bucket spillover → cash > 40% → overflow → high-conv 로."""
    pass
```

- [ ] **Step 2: 실행 — 통합 테스트 1개 pass / 나머지 skip 확인**

Run: `pytest tests/integration/test_allocator_phase1.py -v`
Expected: 1 pass (또는 skip), 4 skip

Phase 1 적용 전이면 `test_allocator_attribution_completeness_via_smoke` 가 fail. 이건 의도된 동작 — Task 16 (regression run) 에서 새 산출물 만든 후 통과.

- [ ] **Step 3: 커밋**

```bash
git add tests/integration/test_allocator_phase1.py
git commit -m "test(stage3): Phase 1 integration 테스트 골격 추가

5개 시나리오 (normal, fx-neg, global-low, attribution, cash-overflow). 4개는
state mocking 헬퍼 후속 작업으로 skip, attribution completeness 는 기존
smoke artifact 활용. 실 회귀 검증은 Task 15-16 의 regression_compare 가 담당."
```

---

### Task 15: `scripts/regression_compare.py` 신규 작성

**Files:**
- Create: `scripts/regression_compare.py`

- [ ] **Step 1: 스크립트 작성**

`scripts/regression_compare.py`:
```python
#!/usr/bin/env python3
"""Phase 1 regression comparator — baseline vs new artifacts.

사용:
    python scripts/regression_compare.py \
        --baseline artifacts/baseline/ \
        --new artifacts/phase1/ \
        [--out diff.json]

각 디렉토리 안에 portfolio.json 또는 YYYY-MM-DD/portfolio.json 다중 as_of.

Spec (acceptance criteria) 검증:
  (a) new_sharpe >= 0.95 × baseline_sharpe
  (b) new_vol <= 1.02 × baseline_vol
  (c) attribution['cash_spillover'], attribution['enb'] 채워짐
  (d) fx_commodity case: bucket weight 감소, chosen 모두 alpha > 0, cash 증가

exit code: 0 = 전부 PASS, 1 = 하나라도 FAIL.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_portfolio_jsons(root: Path) -> dict[str, dict]:
    """root 아래 portfolio.json 들을 {as_of: payload} 로 반환."""
    out: dict[str, dict] = {}
    if (root / "portfolio.json").exists():
        with open(root / "portfolio.json") as f:
            payload = json.load(f)
        out[payload.get("as_of_date", "unknown")] = payload
        return out
    for sub in sorted(root.iterdir()):
        if sub.is_dir():
            p = sub / "portfolio.json"
            if p.exists():
                with open(p) as f:
                    payload = json.load(f)
                out[sub.name] = payload
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / max(len(a | b), 1)


def _l1_weight_distance(wa: dict, wb: dict) -> float:
    keys = set(wa) | set(wb)
    return sum(abs(wa.get(k, 0.0) - wb.get(k, 0.0)) for k in keys)


def _relative_delta(new: float | None, baseline: float | None) -> float | None:
    if new is None or baseline is None or baseline == 0:
        return None
    return (new - baseline) / abs(baseline)


def compare_one(as_of: str, baseline: dict, new: dict) -> dict:
    """as_of 별 비교. returns acceptance pass/fail per criterion."""
    bw = baseline.get("weights") or {}
    nw = new.get("weights") or {}
    bbt = baseline.get("bucket_target") or {}
    nbt = new.get("bucket_target") or {}
    n_attr = new.get("allocation_attribution") or {}

    sharpe_b = baseline.get("expected_sharpe")
    sharpe_n = new.get("expected_sharpe")
    vol_b = baseline.get("expected_volatility")
    vol_n = new.get("expected_volatility")

    bucket_delta = {
        b: (nbt.get(b, 0.0) - bbt.get(b, 0.0))
        for b in ("kr_equity", "global_equity", "fx_commodity", "bond", "cash_mmf")
    }

    # Acceptance
    sharpe_ratio = (sharpe_n / sharpe_b) if (sharpe_b and sharpe_n is not None) else None
    accept_a = (sharpe_ratio is not None and sharpe_ratio >= 0.95) or sharpe_b is None
    vol_ratio = (vol_n / vol_b) if (vol_b and vol_n is not None) else None
    accept_b = (vol_ratio is not None and vol_ratio <= 1.02) or vol_b is None
    accept_c = ("cash_spillover" in n_attr) and ("enb" in n_attr)

    # (d) fx_commodity case 만 적용 (2026-05-15 등에서)
    fx_baseline = bbt.get("fx_commodity", 0.0)
    fx_new = nbt.get("fx_commodity", 0.0)
    cash_baseline = bbt.get("cash_mmf", 0.0)
    cash_new = nbt.get("cash_mmf", 0.0)
    fx_alpha_breakdown = (n_attr.get("buckets", {}).get("fx_commodity", {})
                          .get("alpha_scores") or {})
    fx_chosen = (n_attr.get("buckets", {}).get("fx_commodity", {})
                 .get("chosen") or [])
    fx_chosen_all_positive = (
        all(fx_alpha_breakdown.get(t, 0.0) > 0 for t in fx_chosen)
        if fx_chosen else True
    )
    accept_d = (
        (fx_new <= fx_baseline + 1e-6)
        and fx_chosen_all_positive
        and (cash_new >= cash_baseline - 1e-6)
    )

    return {
        "as_of": as_of,
        "weight_jaccard": _jaccard(set(bw), set(nw)),
        "weight_l1": _l1_weight_distance(bw, nw),
        "sharpe_baseline": sharpe_b,
        "sharpe_new": sharpe_n,
        "sharpe_ratio": sharpe_ratio,
        "vol_baseline": vol_b,
        "vol_new": vol_n,
        "vol_ratio": vol_ratio,
        "bucket_delta": bucket_delta,
        "tickers_added": sorted(set(nw) - set(bw)),
        "tickers_removed": sorted(set(bw) - set(nw)),
        "cash_spillover_present": "cash_spillover" in n_attr,
        "enb_value": n_attr.get("enb"),
        "fx_bucket_baseline": fx_baseline,
        "fx_bucket_new": fx_new,
        "fx_chosen_all_positive": fx_chosen_all_positive,
        "acceptance": {
            "(a) sharpe": accept_a,
            "(b) volatility": accept_b,
            "(c) attribution": accept_c,
            "(d) fx_commodity": accept_d,
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    baselines = _load_portfolio_jsons(args.baseline)
    news = _load_portfolio_jsons(args.new)
    common = sorted(set(baselines) & set(news))
    if not common:
        print(f"ERROR: no common as_of between {args.baseline} and {args.new}", file=sys.stderr)
        sys.exit(1)

    results = []
    overall_pass = True
    for as_of in common:
        r = compare_one(as_of, baselines[as_of], news[as_of])
        results.append(r)
        all_pass = all(r["acceptance"].values())
        if not all_pass:
            overall_pass = False
        print(f"\n=== {as_of} ===")
        print(f"  weight Jaccard:  {r['weight_jaccard']:.3f}")
        print(f"  weight L1:       {r['weight_l1']:.4f}")
        print(f"  sharpe: {r['sharpe_baseline']} → {r['sharpe_new']} "
              f"(ratio={r['sharpe_ratio']})")
        print(f"  vol:    {r['vol_baseline']} → {r['vol_new']} "
              f"(ratio={r['vol_ratio']})")
        print(f"  fx bucket: {r['fx_bucket_baseline']:.3f} → {r['fx_bucket_new']:.3f}")
        print(f"  ENB:    {r['enb_value']}")
        print(f"  tickers added:   {r['tickers_added'][:5]}{'...' if len(r['tickers_added']) > 5 else ''}")
        print(f"  tickers removed: {r['tickers_removed'][:5]}{'...' if len(r['tickers_removed']) > 5 else ''}")
        print(f"  acceptance:")
        for k, v in r["acceptance"].items():
            mark = "✓" if v else "✗"
            print(f"    {mark} {k}: {v}")

    if args.out:
        args.out.write_text(json.dumps(results, indent=2))
        print(f"\nDetailed JSON: {args.out}")

    print(f"\n{'='*40}")
    print(f"OVERALL: {'PASS' if overall_pass else 'FAIL'}")
    sys.exit(0 if overall_pass else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 실행 권한 부여 + 도움말 확인**

```bash
chmod +x scripts/regression_compare.py
python scripts/regression_compare.py --help
```
Expected: argparse help 출력

- [ ] **Step 3: 커밋**

```bash
git add scripts/regression_compare.py
git commit -m "feat(stage3): scripts/regression_compare.py 신규

baseline vs new artifacts/ 의 portfolio.json 비교. Sharpe/vol/bucket delta +
acceptance criteria (a)-(d) 자동 판정. 다중 as_of 지원. exit code 0/1."
```

---

### Task 16: Regression 실행 + acceptance 검증

**Files:**
- (산출물 갱신): `artifacts/<as_of>/portfolio.json`

- [ ] **Step 1: 현 산출물을 baseline 으로 백업**

```bash
mkdir -p artifacts/baseline
cp -r artifacts/2025-04-15 artifacts/baseline/
cp -r artifacts/2026-05-15 artifacts/baseline/
git tag phase1-baseline -m "Pre-Phase1 산출물 baseline"
```

- [ ] **Step 2: Phase 1 적용 후 두 as_of 재실행**

```bash
# (프로젝트의 실제 실행 명령 — scripts/run_e2e_test.py 또는 동등)
python scripts/run_e2e_test.py --as-of 2025-04-15
python scripts/run_e2e_test.py --as-of 2026-05-15
```
Expected: 정상 종료, artifacts/2025-04-15/portfolio.json 과 artifacts/2026-05-15/portfolio.json 갱신.

(실행 명령이 다르면 README 또는 `scripts/run_e2e_test.py` 확인)

- [ ] **Step 3: regression_compare 실행**

```bash
python scripts/regression_compare.py \
    --baseline artifacts/baseline/ \
    --new artifacts/ \
    --out artifacts/phase1_regression.json
```
Expected: 
- 각 as_of 의 acceptance (a)-(d) 모두 ✓
- OVERALL: PASS
- exit code 0

만약 FAIL:
- (a) Sharpe degradation > 5%: spec 의 Fail Recovery 절차 (threshold 조정 — default 0.3 → 0.2 등)
- (b) Volatility 증가: ENB 계산이 turnover 폭증을 유발하는지 attribution 확인
- (d) fx case: 코드 검증 — `select_cluster_aware` 음수 fill 제거가 실제 반영됐는지

- [ ] **Step 4: phase1_smoke 통합 테스트 통과 확인**

Run: `pytest tests/integration/test_allocator_phase1.py::test_allocator_attribution_completeness_via_smoke -v`
Expected: PASS (이제 artifact 가 새 키를 포함)

- [ ] **Step 5: 전체 unit + integration 테스트 회귀 확인**

```bash
pytest tests/unit/skills/test_portfolio_diversification.py \
       tests/unit/skills/test_portfolio_cash_spillover.py \
       tests/unit/skills/test_portfolio_candidate.py \
       tests/unit/skills/test_portfolio_factor_scorer.py \
       tests/unit/skills/test_portfolio_attribution.py \
       tests/unit/skills/test_portfolio_optimizers.py \
       tests/integration/test_allocator_phase1.py \
       -v
```
Expected: all pass

- [ ] **Step 6: 산출물 + 회귀 결과 커밋**

```bash
git add artifacts/2025-04-15/ artifacts/2026-05-15/ artifacts/phase1_regression.json
git commit -m "chore(stage3): Phase 1 적용 후 산출물 갱신 + 회귀 결과

baseline → phase1 regression all acceptance PASS:
  (a) Sharpe degradation ≤ 5%
  (b) Volatility ≤ +2%
  (c) attribution[cash_spillover, enb] 채워짐
  (d) fx_commodity: bucket weight 감소, chosen 모두 양수 alpha, cash 증가

baseline tag: phase1-baseline."
```

---

## 자가 검증 (Self-Review)

플랜 완성 후 다음 체크리스트로 spec 대비 누락 확인:

1. **Spec 의 신규 모듈 2개** (`cash_spillover`, `diversification`) — Task 1-6 ✓
2. **Spec 의 변경 모듈 3개**:
   - `candidate_selector` (AUM 제거 + bond alpha merge) — Task 7-8 ✓
   - `factor_scorer` (음수 fill 제거) — Task 9 ✓
   - `portfolio_allocator` (helper + S 보장 + hook 1 + hook 2) — Task 10-13 ✓
3. **Spec 의 ENB_WARNING_THRESHOLD const 위치** — Task 10 ✓
4. **Spec 의 invariants** (합 1, bond_tips_share, weight ≥ 0) — Task 6 테스트 ✓
5. **Spec 의 effective_cap = max(0.40, macro_cash)** — Task 6 구현 ✓
6. **Spec 의 acceptance criteria (a)-(d)** — Task 15 regression_compare ✓
7. **Spec 의 Fail recovery** — Task 16 Step 3 에 명시 ✓
8. **Spec 의 backward compat** (schema 변경 없음) — 모든 task 가 attribution dict 만 확장 ✓

## Execution Notes

- 모든 task 는 TDD 흐름 (실패 테스트 → 구현 → 통과 → 커밋)
- Task 7-9 의 회귀 테스트가 기존 fixture 와 충돌 시 update (음수 fill 의존 케이스가 있다면 새 동작 반영)
- Task 11 의 `_optimize_with_bucket_constraints` 시그니처 변경은 호출부 정확히 1곳 — line ~273 의 `wv = ...` 만 영향
- Task 16 의 acceptance fail 시 자동 retry 안 함. 사람이 spec Fail Recovery 절차 적용
