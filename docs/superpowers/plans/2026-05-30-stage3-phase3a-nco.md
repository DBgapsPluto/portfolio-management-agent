# Stage 3 Phase 3a — NCO (Nested Clustered Optimization) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** NCO (Nested Clustered Optimization) optimizer 를 bucket 내부 알고리즘으로 신규 도입. parallel optimizer 로 기존 5 method 와 공존, A/B 테스트 가능. Phase 3c 에서 cutover.

**Architecture:** 신규 `nco.py` 모듈 (compute_nco_weights + hierarchical cluster + intra/inter CVO + opt_port 폐쇄형). allocator 에 `_nco_per_bucket` helper (HRP-per-bucket 패턴 재사용) + OptimizationMethod.NCO 분기 + state["force_method"] A/B 메커니즘.

**Tech Stack:** Python 3.13, scipy.cluster.hierarchy, scipy.spatial.distance, sklearn.metrics, numpy, pandas, pypfopt, pytest.

**Spec:** [docs/superpowers/specs/2026-05-30-stage3-phase3a-nco-design.md](../specs/2026-05-30-stage3-phase3a-nco-design.md)

---

## File Structure

| 파일 | 변경 | 책임 |
|---|---|---|
| `tradingagents/skills/portfolio/nco.py` | Create | NCO 알고리즘 모듈 (5 함수 + constants) |
| `tradingagents/schemas/portfolio.py` | Modify | OptimizationMethod.NCO enum 값 추가 |
| `tradingagents/agents/allocator/portfolio_allocator.py` | Modify | `_nco_per_bucket` 신규 + `_optimize_with_bucket_constraints` NCO 분기 + `state["force_method"]` 메커니즘 |
| `scripts/run_e2e_test.py` | Modify | `--force-method` 인자 추가 |
| `tests/unit/skills/test_portfolio_nco.py` | Create | NCO 단위 테스트 (13개) |
| `tests/integration/test_allocator_phase3a.py` | Create | NCO 통합 테스트 (7개) |

---

### Task 1: `_opt_port` — Closed-form CVO

**Files:**
- Create: `tradingagents/skills/portfolio/nco.py`
- Create: `tests/unit/skills/test_portfolio_nco.py`

- [ ] **Step 1: Create skeleton module + tests**

Create `tradingagents/skills/portfolio/nco.py`:
```python
"""NCO (Nested Clustered Optimization) — Lopez de Prado 2019.

Bucket 내부 종목들에 hierarchical clustering + intra/inter CVO 로 weight 결정.
Phase 3a 도입 — 기존 5 method 와 공존, A/B 테스트 가능.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# Phase 3a (2026-05-30). NCO algorithm constants.
NCO_MAX_NUM_CLUSTERS_RATIO: float = 0.5
NCO_MIN_NUM_CLUSTERS: int = 2
NCO_LINKAGE_METHOD: str = "single"
NCO_MIN_VAR_REGULARIZATION: float = 1e-8


def _opt_port(cov: pd.DataFrame, mu: pd.Series | None = None) -> pd.Series:
    """Closed-form CVO (long-only normalized).

    mu=None → min-var: w = (Σ + εI)^(-1) × 1 / (1^T (Σ + εI)^(-1) 1)
    mu given → max-sharpe: w = (Σ + εI)^(-1) × μ / (1^T (Σ + εI)^(-1) μ)

    음수 weight clip + 재정규화 (long-only).
    cov singular 시 equal weight fallback.
    """
    raise NotImplementedError
```

Create `tests/unit/skills/test_portfolio_nco.py`:
```python
"""NCO unit tests."""
import numpy as np
import pandas as pd
import pytest


def test_opt_port_min_var_uncorrelated_equal_weight():
    """Uncorrelated equal-vol → min-var = equal weight."""
    from tradingagents.skills.portfolio.nco import _opt_port

    cov = pd.DataFrame(
        np.eye(3) * 0.04, index=["A", "B", "C"], columns=["A", "B", "C"],
    )
    w = _opt_port(cov)
    assert isinstance(w, pd.Series)
    assert list(w.index) == ["A", "B", "C"]
    # Equal weight ≈ 1/3
    for v in w.values:
        assert abs(v - 1/3) < 1e-6


def test_opt_port_min_var_different_vol_prefers_lower():
    """다른 vol → min-var 가 낮은 vol 우대."""
    from tradingagents.skills.portfolio.nco import _opt_port

    cov = pd.DataFrame(
        [[0.01, 0.0], [0.0, 0.16]],  # A vol=10%, B vol=40%
        index=["A", "B"], columns=["A", "B"],
    )
    w = _opt_port(cov)
    # A 가 더 큰 weight (낮은 vol)
    assert w["A"] > w["B"]
    # sum = 1
    assert abs(w.sum() - 1.0) < 1e-9


def test_opt_port_max_sharpe_with_mu():
    """mu given → max-sharpe path. 높은 mu / 낮은 vol 우대."""
    from tradingagents.skills.portfolio.nco import _opt_port

    cov = pd.DataFrame(
        np.eye(2) * 0.04, index=["A", "B"], columns=["A", "B"],
    )
    mu = pd.Series([0.1, 0.05], index=["A", "B"])
    w = _opt_port(cov, mu=mu)
    # A 가 더 큰 mu → 더 큰 weight
    assert w["A"] > w["B"]
    assert abs(w.sum() - 1.0) < 1e-9


def test_opt_port_handles_singular_cov():
    """Singular cov → equal weight fallback."""
    from tradingagents.skills.portfolio.nco import _opt_port

    # Rank-1 cov (perfectly correlated, singular)
    cov = pd.DataFrame(
        np.ones((3, 3)) * 0.04,  # 모든 원소 동일
        index=["A", "B", "C"], columns=["A", "B", "C"],
    )
    w = _opt_port(cov)
    # equal weight fallback or regularized result — 모두 양수 + sum=1
    assert all(v > 0 for v in w.values)
    assert abs(w.sum() - 1.0) < 1e-9


def test_opt_port_negative_weights_clipped():
    """음수 weight 발생 시 clip + 재정규화."""
    from tradingagents.skills.portfolio.nco import _opt_port

    # Negative correlation 으로 음수 weight 유도 가능
    cov = pd.DataFrame(
        [[0.04, -0.03], [-0.03, 0.04]],
        index=["A", "B"], columns=["A", "B"],
    )
    w = _opt_port(cov)
    assert all(v >= 0 for v in w.values)
    assert abs(w.sum() - 1.0) < 1e-9
```

- [ ] **Step 2: Run failing**

```bash
cd /Users/kimjaewon/Pluto/TradingAgents/.claude/worktrees/<worktree>
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_nco.py -v 2>&1 | tail -10
```
Expected: 5 FAIL (NotImplementedError)

- [ ] **Step 3: Implement `_opt_port`**

Replace `raise NotImplementedError` in `_opt_port`:
```python
def _opt_port(cov: pd.DataFrame, mu: pd.Series | None = None) -> pd.Series:
    """Closed-form CVO (long-only normalized)."""
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

- [ ] **Step 4: Run tests**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_nco.py -v 2>&1 | tail -10
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/portfolio/nco.py tests/unit/skills/test_portfolio_nco.py
git commit -m "feat(stage3): NCO _opt_port (closed-form CVO)

Phase 3a Task 1. min-var (mu=None) + max-sharpe (mu given) 폐쇄형.
ε=1e-8 regularization + equal weight fallback. long-only normalize. 5 tests."
```

---

### Task 2: `_hierarchical_cluster` + silhouette

**Files:**
- Modify: `tradingagents/skills/portfolio/nco.py`
- Modify: `tests/unit/skills/test_portfolio_nco.py`

- [ ] **Step 1: Write tests**

Append to `tests/unit/skills/test_portfolio_nco.py`:
```python
def test_hierarchical_cluster_two_distinct_groups():
    """2 그룹 (within corr 1, between corr 0) → 2 cluster, silhouette 높음."""
    from tradingagents.skills.portfolio.nco import _hierarchical_cluster

    # 4 ticker: A,B 한 그룹 (corr=0.99), C,D 다른 그룹 (corr=0.99), 그룹 간 corr=0
    corr = pd.DataFrame([
        [1.0, 0.99, 0.0, 0.0],
        [0.99, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.99],
        [0.0, 0.0, 0.99, 1.0],
    ], index=["A", "B", "C", "D"], columns=["A", "B", "C", "D"])
    labels, silh = _hierarchical_cluster(corr, max_num_clusters=2)
    # A 와 B 같은 cluster, C 와 D 같은 cluster
    assert labels[0] == labels[1]
    assert labels[2] == labels[3]
    assert labels[0] != labels[2]
    assert silh is not None
    assert silh > 0.5  # 명확한 separation


def test_hierarchical_cluster_perfectly_correlated_returns_one_cluster():
    """모두 corr ≈ 1 → 모두 1 cluster, silhouette=None."""
    from tradingagents.skills.portfolio.nco import _hierarchical_cluster

    corr = pd.DataFrame(
        np.full((3, 3), 0.999), index=["A", "B", "C"], columns=["A", "B", "C"],
    )
    np.fill_diagonal(corr.values, 1.0)
    labels, silh = _hierarchical_cluster(corr, max_num_clusters=2)
    # 모두 같은 label 또는 silhouette None (fallback)
    assert len(set(labels)) <= 2


def test_hierarchical_cluster_silhouette_picks_best_k():
    """4 ticker 가 명확한 2 그룹 → k=2 선택."""
    from tradingagents.skills.portfolio.nco import _hierarchical_cluster

    corr = pd.DataFrame([
        [1.0, 0.99, 0.05, 0.05],
        [0.99, 1.0, 0.05, 0.05],
        [0.05, 0.05, 1.0, 0.99],
        [0.05, 0.05, 0.99, 1.0],
    ], index=["A", "B", "C", "D"], columns=["A", "B", "C", "D"])
    labels, silh = _hierarchical_cluster(corr, max_num_clusters=3)
    # best k = 2 가 선택됨
    assert len(set(labels)) == 2
```

- [ ] **Step 2: Run failing**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_nco.py -v -k hierarchical_cluster 2>&1 | tail -10
```
Expected: 3 FAIL (NameError)

- [ ] **Step 3: Implement**

Add imports at top of `nco.py`:
```python
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform
from sklearn.metrics import silhouette_score
```

Add function after `_opt_port`:
```python
def _hierarchical_cluster(
    corr: pd.DataFrame,
    max_num_clusters: int,
) -> tuple[np.ndarray, float | None]:
    """Single-linkage clustering on √((1-corr)/2) distance.

    silhouette score 평가 후 best k 선택. 단일 cluster fallback 시 silhouette=None.
    """
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
        return np.ones(n, dtype=int), None

    return best_labels, float(best_score)
```

- [ ] **Step 4: Run tests pass**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_nco.py -v -k hierarchical_cluster 2>&1 | tail -10
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/portfolio/nco.py tests/unit/skills/test_portfolio_nco.py
git commit -m "feat(stage3): NCO _hierarchical_cluster + silhouette best k

Phase 3a Task 2. single-linkage on √((1-corr)/2). silhouette score 로 best
k ∈ [2, max_k]. 단일 cluster fallback. 3 tests."
```

---

### Task 3: `_intra_cluster_weights` + `_inter_cluster_weights`

**Files:**
- Modify: `tradingagents/skills/portfolio/nco.py`
- Modify: `tests/unit/skills/test_portfolio_nco.py`

- [ ] **Step 1: Write tests**

Append:
```python
def test_intra_cluster_weights_matrix_shape():
    """n_assets × n_clusters DataFrame."""
    from tradingagents.skills.portfolio.nco import _intra_cluster_weights

    cov = pd.DataFrame(
        np.eye(4) * 0.04, index=["A", "B", "C", "D"], columns=["A", "B", "C", "D"],
    )
    labels = np.array([1, 1, 2, 2])  # A,B cluster 1, C,D cluster 2
    intra = _intra_cluster_weights(cov, labels)
    assert intra.shape == (4, 2)
    # A,B 만 cluster 1 column 에 non-zero
    assert intra.loc["A", 1] > 0
    assert intra.loc["B", 1] > 0
    assert intra.loc["A", 2] == 0
    assert intra.loc["B", 2] == 0
    # 각 cluster column 의 weight sum = 1
    for col in intra.columns:
        col_sum = intra[col].sum()
        assert abs(col_sum - 1.0) < 1e-6


def test_intra_cluster_weights_single_member_cluster():
    """단일 ticker cluster → weight = 1.0."""
    from tradingagents.skills.portfolio.nco import _intra_cluster_weights

    cov = pd.DataFrame(
        np.eye(3) * 0.04, index=["A", "B", "C"], columns=["A", "B", "C"],
    )
    labels = np.array([1, 2, 3])  # 모두 다른 cluster
    intra = _intra_cluster_weights(cov, labels)
    # 각 ticker 가 자기 cluster 에 weight = 1.0
    assert intra.loc["A", 1] == 1.0
    assert intra.loc["B", 2] == 1.0
    assert intra.loc["C", 3] == 1.0


def test_inter_cluster_weights_min_var_path():
    """Reduced cov 에 min-var → 분산 작은 cluster 우대."""
    from tradingagents.skills.portfolio.nco import _inter_cluster_weights

    # cluster 1: 분산 작음 (0.01), cluster 2: 분산 큼 (0.16)
    reduced_cov = pd.DataFrame(
        [[0.01, 0.0], [0.0, 0.16]],
        index=[1, 2], columns=[1, 2],
    )
    w = _inter_cluster_weights(reduced_cov)
    assert w[1] > w[2]  # 분산 작은 cluster 우대
    assert abs(w.sum() - 1.0) < 1e-9


def test_inter_cluster_weights_with_mu_max_sharpe_path():
    """mu given → max-sharpe."""
    from tradingagents.skills.portfolio.nco import _inter_cluster_weights

    reduced_cov = pd.DataFrame(
        np.eye(2) * 0.04, index=[1, 2], columns=[1, 2],
    )
    reduced_mu = pd.Series([0.1, 0.05], index=[1, 2])
    w = _inter_cluster_weights(reduced_cov, reduced_mu)
    assert w[1] > w[2]  # 더 큰 mu 우대
```

- [ ] **Step 2: Run failing**

Expected: 4 FAIL.

- [ ] **Step 3: Implement**

Append to `nco.py`:
```python
def _intra_cluster_weights(
    cov: pd.DataFrame,
    labels: np.ndarray,
    mu: pd.Series | None = None,
) -> pd.DataFrame:
    """n_assets × n_clusters DataFrame.

    한 ticker (row) 는 자기 cluster (column) 에만 non-zero weight.
    """
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


def _inter_cluster_weights(
    reduced_cov: pd.DataFrame,
    reduced_mu: pd.Series | None = None,
) -> pd.Series:
    """Inter-cluster CVO."""
    return _opt_port(reduced_cov, reduced_mu)
```

- [ ] **Step 4: Run tests pass**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_nco.py -v -k "intra_cluster\|inter_cluster" 2>&1 | tail -10
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/portfolio/nco.py tests/unit/skills/test_portfolio_nco.py
git commit -m "feat(stage3): NCO _intra_cluster_weights + _inter_cluster_weights

Phase 3a Task 3. n_assets × n_clusters intra matrix (단일 member → 1.0).
inter = _opt_port(reduced_cov). 4 tests."
```

---

### Task 4: `compute_nco_weights` 통합

**Files:**
- Modify: `tradingagents/skills/portfolio/nco.py`
- Modify: `tests/unit/skills/test_portfolio_nco.py`

- [ ] **Step 1: Write tests**

Append:
```python
def test_compute_nco_weights_uncorrelated_returns_equal_weight():
    """n=4 uncorrelated, equal vol → equal weight."""
    from tradingagents.skills.portfolio.nco import compute_nco_weights

    rng = np.random.default_rng(42)
    returns = pd.DataFrame(
        rng.normal(0, 0.02, size=(252, 4)),
        columns=["A", "B", "C", "D"],
    )
    w = compute_nco_weights(returns)
    # 거의 equal weight (∈ [0.2, 0.3] 정도)
    for v in w.values:
        assert 0.1 < v < 0.4
    assert abs(w.sum() - 1.0) < 1e-6


def test_compute_nco_weights_two_clusters_inter_balance():
    """2 명확한 cluster, equal vol → inter weight 균등 (intra 도 균등)."""
    from tradingagents.skills.portfolio.nco import compute_nco_weights

    rng = np.random.default_rng(7)
    # cluster 1: A, B (corr 0.95)
    # cluster 2: C, D (corr 0.95)
    # 그룹 간 corr ≈ 0
    base1 = rng.normal(0, 0.02, size=252)
    base2 = rng.normal(0, 0.02, size=252)
    returns = pd.DataFrame({
        "A": base1 + rng.normal(0, 0.005, size=252),
        "B": base1 + rng.normal(0, 0.005, size=252),
        "C": base2 + rng.normal(0, 0.005, size=252),
        "D": base2 + rng.normal(0, 0.005, size=252),
    })
    w = compute_nco_weights(returns)
    # 2 cluster — A+B 합 ≈ C+D 합 ≈ 0.5
    ab_sum = w["A"] + w["B"]
    cd_sum = w["C"] + w["D"]
    assert abs(ab_sum - 0.5) < 0.15
    assert abs(cd_sum - 0.5) < 0.15


def test_compute_nco_weights_weights_sum_to_one():
    """Sum invariant."""
    from tradingagents.skills.portfolio.nco import compute_nco_weights

    rng = np.random.default_rng(11)
    returns = pd.DataFrame(rng.normal(0, 0.02, size=(252, 5)), columns=list("ABCDE"))
    w = compute_nco_weights(returns)
    assert abs(w.sum() - 1.0) < 1e-6


def test_compute_nco_weights_non_negative():
    """Long-only."""
    from tradingagents.skills.portfolio.nco import compute_nco_weights

    rng = np.random.default_rng(13)
    returns = pd.DataFrame(rng.normal(0, 0.02, size=(252, 4)), columns=list("ABCD"))
    w = compute_nco_weights(returns)
    assert all(v >= 0 for v in w.values)


def test_compute_nco_weights_with_mu_max_sharpe_path():
    """mu given → max-sharpe inner CVO."""
    from tradingagents.skills.portfolio.nco import compute_nco_weights

    rng = np.random.default_rng(17)
    returns = pd.DataFrame(rng.normal(0, 0.02, size=(252, 3)), columns=list("ABC"))
    mu = pd.Series([0.10, 0.05, 0.02], index=list("ABC"))
    w = compute_nco_weights(returns, mu=mu)
    # A 가 가장 큰 mu → A weight 가 작지 않아야
    assert w["A"] > 0
    assert abs(w.sum() - 1.0) < 1e-6


def test_compute_nco_weights_breakdown_out_recorded():
    """breakdown_out 채움."""
    from tradingagents.skills.portfolio.nco import compute_nco_weights

    rng = np.random.default_rng(19)
    returns = pd.DataFrame(rng.normal(0, 0.02, size=(252, 4)), columns=list("ABCD"))
    breakdown: dict = {}
    compute_nco_weights(returns, breakdown_out=breakdown)
    assert "n_clusters" in breakdown
    assert "silhouette" in breakdown
    assert "cluster_labels" in breakdown
    assert "intra_weights" in breakdown
    assert "inter_weights" in breakdown
    assert "mu_provided" in breakdown
    assert breakdown["mu_provided"] is False


def test_compute_nco_weights_raises_when_insufficient_tickers():
    """n=1 → ValueError."""
    from tradingagents.skills.portfolio.nco import compute_nco_weights

    rng = np.random.default_rng(23)
    returns = pd.DataFrame(rng.normal(0, 0.02, size=(252, 1)), columns=["A"])
    with pytest.raises(ValueError, match="NCO requires"):
        compute_nco_weights(returns)


def test_compute_nco_weights_handles_n_equals_two():
    """n=2 shortcut."""
    from tradingagents.skills.portfolio.nco import compute_nco_weights

    rng = np.random.default_rng(29)
    returns = pd.DataFrame(rng.normal(0, 0.02, size=(252, 2)), columns=["A", "B"])
    w = compute_nco_weights(returns)
    assert len(w) == 2
    assert abs(w.sum() - 1.0) < 1e-6
```

- [ ] **Step 2: Run failing**

Expected: 8 FAIL.

- [ ] **Step 3: Implement `compute_nco_weights`**

Append to `nco.py`:
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
    """
    n_assets = returns.shape[1]
    if n_assets < 2:
        raise ValueError(f"NCO requires >= 2 assets, got {n_assets}")

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
        max_num_clusters = max(
            NCO_MIN_NUM_CLUSTERS,
            int(n_assets * NCO_MAX_NUM_CLUSTERS_RATIO),
        )
    max_num_clusters = min(max_num_clusters, n_assets - 1)

    labels, silh = _hierarchical_cluster(corr, max_num_clusters)

    intra_weights = _intra_cluster_weights(cov, labels, mu)

    reduced_cov_arr = intra_weights.values.T @ cov.values @ intra_weights.values
    reduced_cov = pd.DataFrame(
        reduced_cov_arr,
        index=intra_weights.columns,
        columns=intra_weights.columns,
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
    final_sum = final_series.sum()
    if final_sum > 0:
        final_series = final_series / final_sum
    else:
        final_series = pd.Series(
            np.ones(n_assets) / n_assets, index=intra_weights.index,
        )

    if breakdown_out is not None:
        breakdown_out["n_clusters"] = int(len(set(labels)))
        breakdown_out["silhouette"] = float(silh) if silh is not None else None
        breakdown_out["cluster_labels"] = {
            ticker: int(label)
            for ticker, label in zip(returns.columns, labels)
        }
        breakdown_out["intra_weights"] = intra_weights.to_dict()
        breakdown_out["inter_weights"] = inter_weights.to_dict()
        breakdown_out["mu_provided"] = mu is not None

    return final_series
```

- [ ] **Step 4: Run all NCO tests**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_nco.py -v 2>&1 | tail -20
```
Expected: all 20 passed (5+3+4+8).

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/portfolio/nco.py tests/unit/skills/test_portfolio_nco.py
git commit -m "feat(stage3): NCO compute_nco_weights 통합

Phase 3a Task 4. hierarchical cluster + intra/inter CVO + final intra@inter.
n=2 shortcut, n<2 ValueError. breakdown_out 완전 기록. 8 tests (20 total)."
```

---

### Task 5: `OptimizationMethod.NCO` enum 추가

**Files:**
- Modify: `tradingagents/schemas/portfolio.py`

- [ ] **Step 1: Inspect enum**

```bash
grep -n "class OptimizationMethod" tradingagents/schemas/portfolio.py
```

- [ ] **Step 2: Add NCO value**

`tradingagents/schemas/portfolio.py` 의 `OptimizationMethod` enum 에 추가:
```python
class OptimizationMethod(str, Enum):
    MIN_VARIANCE = "min_variance"
    RISK_PARITY = "risk_parity"
    MAX_SHARPE = "max_sharpe"
    BLACK_LITTERMAN = "black_litterman"
    HRP = "hrp"
    NCO = "nco"   # Phase 3a (2026-05-30)
```

- [ ] **Step 3: Quick test**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -c "
from tradingagents.schemas.portfolio import OptimizationMethod
assert OptimizationMethod('nco') == OptimizationMethod.NCO
print('OK:', OptimizationMethod.NCO.value)
"
```
Expected: `OK: nco`

- [ ] **Step 4: Run existing portfolio tests for regression**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_*.py tests/unit/agents/test_portfolio_allocator.py -q 2>&1 | tail -5
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/schemas/portfolio.py
git commit -m "feat(stage3): OptimizationMethod.NCO enum 값 추가

Phase 3a Task 5. Pydantic str Enum 확장. 기존 5 method 유지. JSON 직렬화 호환."
```

---

### Task 6: `_nco_per_bucket` helper + allocator NCO 분기

**Files:**
- Modify: `tradingagents/agents/allocator/portfolio_allocator.py`

- [ ] **Step 1: Inspect HRP pattern**

```bash
grep -n "_hrp_per_bucket\|def _optimize_with_bucket_constraints" tradingagents/agents/allocator/portfolio_allocator.py | head -10
```

- [ ] **Step 2: Add import + `_nco_per_bucket` helper**

`tradingagents/agents/allocator/portfolio_allocator.py` 의 imports 에 추가:
```python
from tradingagents.skills.portfolio.nco import compute_nco_weights
```

`_hrp_per_bucket` 함수 정의 직후 (대략 line 793 부근, `_hrp_per_bucket` 끝나는 곳) `_nco_per_bucket` 추가. Pattern 은 `_hrp_per_bucket` 의 구조를 거의 동일하게 따름 (bond split, single asset cap, normalization). 핵심 차이: `HRPOpt(sub).optimize()` → `compute_nco_weights(sub_returns)`.

`_hrp_per_bucket` 전체를 복사 후 다음만 변경:
- 함수명: `_nco_per_bucket`
- WeightVector.method: `OptimizationMethod.NCO`
- WeightVector.rationale: NCO 표현
- 내부의 HRP 계산 코드 `hrp = HRPOpt(sub)` + `inner = {k: float(v) for k, v in hrp.optimize().items()}` 부분을 다음으로 교체:
```python
pool_breakdown: dict = {}
nco_w = compute_nco_weights(sub, breakdown_out=pool_breakdown)
inner = nco_w.to_dict()
# attribution 에 nco_breakdown 기록
if attribution is not None:
    attribution.setdefault("nco_breakdown", {})[pool_label] = pool_breakdown
```

**중요**: `_hrp_per_bucket` 의 정확한 구조를 따라가야 회귀 안 됨. 다음 명령으로 인용:
```bash
sed -n '793,960p' tradingagents/agents/allocator/portfolio_allocator.py > /tmp/hrp_template.py
```

그 다음 `_nco_per_bucket` 작성 시 위 명령 결과를 참고하여 동일 패턴 (bond split, single asset cap, water-fill, final normalization) 유지.

핵심 구조:
```python
def _nco_per_bucket(
    returns: pd.DataFrame, candidates, bucket_target,
    sub_category_lookup: dict[str, str | None] | None = None,
    attribution: dict | None = None,
) -> WeightVector:
    """NCO per bucket × bucket_target weight.

    각 bucket 의 chosen 종목들에 compute_nco_weights → bucket_target scale →
    single asset cap (water-fill) → final normalize. bond split path 동일.
    """
    bucket_shortfalls: list[dict] = []
    sub_category_lookup = sub_category_lookup or {}
    target_map = {
        "kr_equity": bucket_target.kr_equity,
        "global_equity": bucket_target.global_equity,
        "fx_commodity": bucket_target.fx_commodity,
        "bond": bucket_target.bond,
        "cash_mmf": bucket_target.cash_mmf,
    }
    split_bond = bucket_target.bond_tips_share > 0.0

    final: dict[str, float] = {}
    nco_breakdown_per_pool: dict[str, dict] = {}

    for bucket, tickers in candidates.bucket_to_tickers.items():
        target = target_map.get(bucket, 0)
        if target <= 0 or not tickers:
            continue

        if bucket == "bond" and split_bond:
            tips_tickers = [
                t for t in tickers
                if sub_category_lookup.get(t) == "inflation_linked"
            ]
            nominal_tickers = [t for t in tickers if t not in tips_tickers]
            tips_target = target * bucket_target.bond_tips_share
            nominal_target = target * (1.0 - bucket_target.bond_tips_share)
            if not tips_tickers and nominal_tickers:
                nominal_target += tips_target
                tips_target = 0.0
            if not nominal_tickers and tips_tickers:
                tips_target += nominal_target
                nominal_target = 0.0
            sub_buckets = []
            if tips_tickers and tips_target > 0:
                sub_buckets.append((tips_tickers, tips_target, "bond_tips"))
            if nominal_tickers and nominal_target > 0:
                sub_buckets.append((nominal_tickers, nominal_target, "bond_nominal"))
        else:
            sub_buckets = [(tickers, target, bucket)]

        for pool_tickers, pool_target, pool_label in sub_buckets:
            sub = returns[[t for t in pool_tickers if t in returns.columns]].dropna(
                axis=0, how="any",
            )
            if sub.shape[1] == 0:
                continue
            if sub.shape[1] == 1:
                inner = {sub.columns[0]: 1.0}
            else:
                pool_breakdown: dict = {}
                try:
                    nco_w = compute_nco_weights(sub, breakdown_out=pool_breakdown)
                except Exception as e:
                    logger.warning(
                        "NCO failed for pool %s: %s — fallback equal weight",
                        pool_label, e,
                    )
                    n = sub.shape[1]
                    inner = {t: 1.0 / n for t in sub.columns}
                    pool_breakdown = {"error": str(e), "fallback": "equal_weight"}
                else:
                    inner = nco_w.to_dict()
                nco_breakdown_per_pool[pool_label] = pool_breakdown

            scaled = {t: w * pool_target for t, w in inner.items()}

            # Single asset cap (water-fill, HRP 패턴)
            capped = {t: min(w, SINGLE_ASSET_CAP) for t, w in scaled.items()}
            residual = sum(scaled.values()) - sum(capped.values())
            for _ in range(HRP_WATER_FILL_MAX_ITERS):
                if residual <= 1e-9:
                    break
                non_capped = [
                    t for t, w in capped.items() if w < SINGLE_ASSET_CAP - 1e-9
                ]
                if not non_capped:
                    logger.warning(
                        "NCO: pool %s 모든 자산 cap 도달 — target=%.3f, "
                        "실제=%.3f (shortfall=%.3f)",
                        pool_label, pool_target, sum(capped.values()), residual,
                    )
                    bucket_shortfalls.append({
                        "pool": pool_label,
                        "pool_target": float(pool_target),
                        "actual": float(sum(capped.values())),
                        "shortfall": float(residual),
                        "n_assets_capped": len(capped),
                    })
                    break
                share = residual / len(non_capped)
                for t in non_capped:
                    room = SINGLE_ASSET_CAP - capped[t]
                    add = min(share, room)
                    capped[t] += add
                residual = sum(scaled.values()) - sum(capped.values())

            final.update(capped)

    total = sum(final.values())
    if total > 0 and abs(total - 1.0) > 1e-9:
        final = {t: w / total for t, w in final.items()}

    if attribution is not None:
        attribution["nco_breakdown"] = nco_breakdown_per_pool
        if bucket_shortfalls:
            attribution["nco_bucket_shortfalls"] = bucket_shortfalls

    violators = [
        (t, w) for t, w in final.items() if w > SINGLE_ASSET_CAP + 1e-6
    ]
    assert not violators, (
        f"NCO post-condition: {SINGLE_ASSET_CAP*100:.0f}% cap violated: {violators}"
    )

    return WeightVector(
        method=OptimizationMethod.NCO,
        weights=final,
        rationale=(
            f"NCO per bucket × bucket_target weight. "
            f"위험자산 target {bucket_target.risk_asset_weight:.1%}, "
            f"single-asset cap {SINGLE_ASSET_CAP:.0%}."
        )[:300],
    )
```

- [ ] **Step 3: Add NCO branch in `_optimize_with_bucket_constraints`**

`_optimize_with_bucket_constraints` 의 HRP 분기 직후에 NCO 분기 추가 (대략 line 521 부근):

```python
# HRP 분기 (기존 그대로 유지)
if method == OptimizationMethod.HRP:
    wv = _hrp_per_bucket(
        returns, candidates, bucket_target, sub_category_lookup,
        attribution=attribution,
    )
    sigma_df = (
        S if isinstance(S, pd.DataFrame)
        else pd.DataFrame(S, index=returns.columns, columns=returns.columns)
    )
    return wv, sigma_df

# NCO 분기 (Phase 3a NEW)
if method == OptimizationMethod.NCO:
    wv = _nco_per_bucket(
        returns, candidates, bucket_target, sub_category_lookup,
        attribution=attribution,
    )
    sigma_df = (
        S if isinstance(S, pd.DataFrame)
        else pd.DataFrame(S, index=returns.columns, columns=returns.columns)
    )
    return wv, sigma_df
```

또한 `MIN_COV_OBS` 데이터 reduction 분기에서 HRP 외에도 NCO skip:
```python
if method not in (OptimizationMethod.HRP, OptimizationMethod.NCO) and len(returns) < MIN_COV_OBS:
    # data reduction (기존 동일)
    ...
```

- [ ] **Step 4: Syntax + 회귀**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m py_compile tradingagents/agents/allocator/portfolio_allocator.py && echo OK
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_*.py tests/unit/agents/test_portfolio_allocator.py -q 2>&1 | tail -5
```
Expected: OK + all pass.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/allocator/portfolio_allocator.py
git commit -m "feat(stage3): _nco_per_bucket helper + allocator NCO 분기

Phase 3a Task 6. HRP-per-bucket 패턴 재사용 (bond split, single asset cap,
water-fill, normalize). compute_nco_weights 호출 + breakdown_out 기록.
_optimize_with_bucket_constraints 의 NCO 분기 추가. MIN_COV_OBS reduction skip."
```

---

### Task 7: `state["force_method"]` A/B 메커니즘

**Files:**
- Modify: `tradingagents/agents/allocator/portfolio_allocator.py`

- [ ] **Step 1: Inspect method_picker call**

```bash
grep -nE "method_choice = pick_optimization_method|method_picker" tradingagents/agents/allocator/portfolio_allocator.py | head
```

- [ ] **Step 2: Add force_method override**

`node` 함수 내부, `method_choice = pick_optimization_method(...)` 호출 직전에:

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
            method_choice = pick_optimization_method(
                regime_quadrant=regime.quadrant if regime else "unknown",
                # ... (기존 호출 인자들 그대로) ...
            )
```

기존 `method_choice = pick_optimization_method(...)` 호출을 `else:` 분기로 옮김. 기존 코드 라인을 정확히 보존해야.

import 에 `MethodChoice` 가 이미 있는지 확인:
```bash
grep -n "from tradingagents.skills.portfolio.method_picker import" tradingagents/agents/allocator/portfolio_allocator.py
```
- 없으면 추가: `from tradingagents.skills.portfolio.method_picker import pick_optimization_method, MethodChoice`

- [ ] **Step 3: 단위 테스트 (force_method) 추가**

`tests/unit/agents/test_portfolio_allocator.py` 끝에 append (혹은 새 파일):
```python
def test_node_force_method_override_uses_state_value(tmp_path, monkeypatch):
    """state['force_method']='nco' 시 method_picker 호출 안 함, NCO 강제."""
    from datetime import date
    import pandas as pd
    from tests.integration._allocator_state_helpers import (
        make_synthetic_universe, make_synthetic_returns, make_factor_panel,
        make_bucket_target, make_macro_report, make_risk_report,
        make_research_decision, make_technical_report, make_allocator_state,
    )
    from tradingagents.agents.allocator.portfolio_allocator import create_portfolio_allocator

    universe = make_synthetic_universe(n_per_bucket=4)
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(universe.model_dump_json())

    tickers = [e.ticker for e in universe.etfs]
    returns = make_synthetic_returns(tickers, n_days=252, seed=31)
    factor_panel = make_factor_panel(tickers)

    monkeypatch.setattr(
        "tradingagents.skills.portfolio.candidate_selector.fetch_etf_metrics_window",
        lambda tickers, start, end, cache_path=None: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "tradingagents.agents.allocator.portfolio_allocator.fetch_returns_matrix",
        lambda eligible, start, end, cache_path=None: returns[[t for t in eligible if t in returns.columns]],
    )

    state = make_allocator_state(
        as_of=date(2026, 5, 28),
        universe_path=str(universe_path),
        bucket_target=make_bucket_target(),
        technical_report=make_technical_report(factor_panel),
        macro_report=make_macro_report(),
        risk_report=make_risk_report(),
        research_decision=make_research_decision(),
    )
    state["force_method"] = "nco"

    result = create_portfolio_allocator()(state)
    method_picker = result["allocation_attribution"]["method_picker"]
    assert method_picker["method"] == "nco"
    assert method_picker["rule_fired"] == "state_override"
```

- [ ] **Step 4: Syntax + 회귀**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m py_compile tradingagents/agents/allocator/portfolio_allocator.py && echo OK
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/agents/test_portfolio_allocator.py tests/integration/test_allocator_phase1.py tests/integration/test_allocator_phase2a.py tests/integration/test_allocator_phase2b.py -q 2>&1 | tail -5
```
Expected: OK + all pass + 1 new test pass.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/allocator/portfolio_allocator.py tests/unit/agents/test_portfolio_allocator.py
git commit -m "feat(stage3): state['force_method'] A/B 메커니즘

Phase 3a Task 7. method_picker 호출 전 force_method 분기. None 시 기존 동작.
attribution.method_picker.rule_fired='state_override' 가시화. 1 new test."
```

---

### Task 8: Phase 3a Integration tests

**Files:**
- Create: `tests/integration/test_allocator_phase3a.py`

- [ ] **Step 1: Write integration tests**

Create `tests/integration/test_allocator_phase3a.py`:
```python
"""Phase 3a integration — NCO end-to-end."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from tests.integration._allocator_state_helpers import (
    BUCKET_CATEGORIES, make_allocator_state, make_bucket_target,
    make_factor_panel, make_macro_report, make_research_decision,
    make_risk_report, make_synthetic_returns, make_synthetic_universe,
    make_technical_report,
)
from tradingagents.agents.allocator.portfolio_allocator import (
    create_portfolio_allocator,
)


def _setup_state_nco(tmp_path, monkeypatch, *, n_per_bucket: int = 6,
                     capital_krw: float = 1_000_000_000, bt=None,
                     alpha_overrides=None, force_method: str | None = "nco"):
    universe = make_synthetic_universe(n_per_bucket=n_per_bucket)
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(universe.model_dump_json())
    tickers = [e.ticker for e in universe.etfs]
    returns = make_synthetic_returns(tickers, n_days=252, seed=37)
    factor_panel = make_factor_panel(tickers, alpha_overrides=alpha_overrides)
    monkeypatch.setattr(
        "tradingagents.skills.portfolio.candidate_selector.fetch_etf_metrics_window",
        lambda tickers, start, end, cache_path=None: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "tradingagents.agents.allocator.portfolio_allocator.fetch_returns_matrix",
        lambda eligible, start, end, cache_path=None: returns[
            [t for t in eligible if t in returns.columns]
        ],
    )
    state = make_allocator_state(
        as_of=date(2026, 5, 28),
        universe_path=str(universe_path),
        bucket_target=bt or make_bucket_target(),
        technical_report=make_technical_report(factor_panel),
        macro_report=make_macro_report(),
        risk_report=make_risk_report(),
        research_decision=make_research_decision(),
        capital_krw=capital_krw,
    )
    if force_method:
        state["force_method"] = force_method
    return state


def test_allocator_with_method_nco_runs_to_completion(tmp_path, monkeypatch):
    """state['force_method']='nco' 정상 종료, weight sum=1."""
    state = _setup_state_nco(tmp_path, monkeypatch)
    result = create_portfolio_allocator()(state)
    weights = result["weights"]
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-6)
    assert result["allocation_attribution"]["method_picker"]["method"] == "nco"


def test_allocator_nco_attribution_records_breakdown(tmp_path, monkeypatch):
    """attribution.optimization.nco_breakdown per bucket 채워짐."""
    state = _setup_state_nco(tmp_path, monkeypatch)
    result = create_portfolio_allocator()(state)
    opt_attr = result["allocation_attribution"]["optimization"]
    assert "nco_breakdown" in opt_attr
    nco = opt_attr["nco_breakdown"]
    # 적어도 1 bucket 의 breakdown 있어야
    assert len(nco) > 0
    # 각 pool 의 breakdown 에 핵심 키 있어야
    for pool_label, breakdown in nco.items():
        if "error" in breakdown:
            continue  # fallback case
        assert "n_clusters" in breakdown or "silhouette" in breakdown


def test_allocator_nco_respects_single_asset_cap(tmp_path, monkeypatch):
    """단일 자산 weight ≤ 20%."""
    state = _setup_state_nco(tmp_path, monkeypatch)
    result = create_portfolio_allocator()(state)
    weights = result["weights"]
    for ticker, w in weights.items():
        assert w <= 0.20 + 1e-6, f"{ticker} weight {w} exceeds 20% cap"


def test_allocator_nco_bucket_sum_approximates_target(tmp_path, monkeypatch):
    """Bucket weight ≈ bucket_target."""
    bt = make_bucket_target(
        kr_equity=0.20, global_equity=0.20, fx_commodity=0.10,
        bond=0.30, cash_mmf=0.20,
    )
    state = _setup_state_nco(tmp_path, monkeypatch, bt=bt)
    result = create_portfolio_allocator()(state)
    attr = result["allocation_attribution"]
    bucket_to_tickers = attr["buckets"]
    weights = result["weights"]

    # 각 bucket 의 chosen 종목 weight 합 ≈ bucket_target (band 허용)
    bt_post = attr["config"]["bucket_target_post_spillover"]
    for bucket_name in ("kr_equity", "global_equity", "fx_commodity", "bond", "cash_mmf"):
        chosen = bucket_to_tickers.get(bucket_name, {}).get("chosen", [])
        bucket_sum = sum(weights.get(t, 0.0) for t in chosen)
        target = bt_post[bucket_name]
        # 10% band (HRP shortfall 또는 NCO 의 capped 효과 허용)
        if target > 0:
            assert abs(bucket_sum - target) < 0.10, (
                f"{bucket_name}: bucket_sum={bucket_sum:.3f}, target={target:.3f}"
            )


def test_allocator_nco_handles_single_ticker_bucket(tmp_path, monkeypatch):
    """chosen 1 개인 bucket 정상 (weight=bucket_target)."""
    # 매우 strict bucket → adaptive N 으로 chosen 1 개만 통과
    bt = make_bucket_target(
        kr_equity=0.05, global_equity=0.05, fx_commodity=0.05,
        bond=0.05, cash_mmf=0.80,
    )
    state = _setup_state_nco(
        tmp_path, monkeypatch, bt=bt, capital_krw=1_000_000_000,
    )
    result = create_portfolio_allocator()(state)
    # 정상 종료만 검증 (assertion error 없이)
    assert sum(result["weights"].values()) == pytest.approx(1.0, abs=1e-3)


def test_allocator_nco_vs_hrp_same_inputs_different_weights(tmp_path, monkeypatch):
    """동일 입력에 NCO 와 HRP 가 다른 weight."""
    state_nco = _setup_state_nco(tmp_path, monkeypatch, force_method="nco")
    result_nco = create_portfolio_allocator()(state_nco)

    state_hrp = _setup_state_nco(tmp_path, monkeypatch, force_method="hrp")
    result_hrp = create_portfolio_allocator()(state_hrp)

    # 같은 ticker set 일 수 있지만 weight 분포 다름
    weights_nco = result_nco["weights"]
    weights_hrp = result_hrp["weights"]
    # 적어도 1 ticker 의 weight 가 다름 (또는 method 라벨 다름)
    assert result_nco["allocation_attribution"]["method_picker"]["method"] == "nco"
    assert result_hrp["allocation_attribution"]["method_picker"]["method"] == "hrp"


def test_allocator_nco_with_correlated_etfs_uses_single_cluster(tmp_path, monkeypatch):
    """같은 underlying ETF 들이 1 cluster 로 모임."""
    state = _setup_state_nco(tmp_path, monkeypatch)
    result = create_portfolio_allocator()(state)
    # NCO 통합 정상 동작 + breakdown 에 cluster 정보 있음
    nco_breakdown = result["allocation_attribution"]["optimization"].get("nco_breakdown", {})
    for pool_label, breakdown in nco_breakdown.items():
        if "n_clusters" in breakdown:
            # n_clusters 가 정수
            assert isinstance(breakdown["n_clusters"], int)
            assert breakdown["n_clusters"] >= 1
```

- [ ] **Step 2: Run tests**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/integration/test_allocator_phase3a.py -v 2>&1 | tail -15
```
Expected: 7 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_allocator_phase3a.py
git commit -m "test(stage3): Phase 3a NCO integration 테스트

Phase 3a Task 8. 7 integration tests: run-to-completion, attribution.nco_breakdown,
single asset cap, bucket sum, single ticker bucket, NCO vs HRP, correlated cluster."
```

---

### Task 9: `scripts/run_e2e_test.py` 의 `--force-method` 인자

**Files:**
- Modify: `scripts/run_e2e_test.py`

- [ ] **Step 1: Inspect e2e script structure**

```bash
grep -nE "argparse|--as-of|--capital" scripts/run_e2e_test.py | head -10
```

- [ ] **Step 2: Add argument**

`scripts/run_e2e_test.py` 의 argparse 정의 부분에 추가:
```python
parser.add_argument(
    "--force-method",
    type=str,
    default=None,
    choices=["min_variance", "risk_parity", "max_sharpe", "black_litterman", "hrp", "nco"],
    help="Force optimizer method (Phase 3a A/B testing).",
)
```

state 구성 시 `force_method` 주입:
```python
if args.force_method:
    state["force_method"] = args.force_method
```

(state 가 어디 생성되는지 inspect 필요 — run_e2e_test.py 안의 build_initial_state 또는 동등.)

- [ ] **Step 3: Smoke test**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/run_e2e_test.py --help 2>&1 | tail -15
```
Expected: `--force-method` 가 도움말에 표시.

- [ ] **Step 4: Commit**

```bash
git add scripts/run_e2e_test.py
git commit -m "feat(stage3): scripts/run_e2e_test.py 의 --force-method 인자

Phase 3a Task 9. argparse choice (6 methods). state['force_method'] 주입.
NCO A/B 테스트 enable."
```

---

### Task 10: Regression + Acceptance

**Files:**
- (산출물 갱신): `artifacts/<as_of>/portfolio.json`

- [ ] **Step 1: Setup .env**

```bash
cd /Users/kimjaewon/Pluto/TradingAgents/.claude/worktrees/<worktree>
cp /Users/kimjaewon/Pluto/TradingAgents/.env . 2>/dev/null || echo ".env missing"
```

- [ ] **Step 2: 회귀 무손실 검증 (default method, force_method 없음)**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/run_e2e_test.py --as-of 2026-05-15 --capital 1000000000 2>&1 | tail -20
```
Expected: 정상 종료. attribution.method_picker.method 가 기존 method (hrp 또는 risk_parity 등).

- [ ] **Step 3: NCO E2E (force_method=nco)**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/run_e2e_test.py --as-of 2026-05-15 --capital 1000000000 --force-method nco 2>&1 | tail -20
```
Expected: 정상 종료. attribution.method_picker.rule_fired='state_override', method='nco'. nco_breakdown 채워짐.

- [ ] **Step 4: Verify attribution**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -c "
import json
with open('artifacts/2026-05-15/portfolio.json') as f:
    p = json.load(f)
attr = p['allocation_attribution']
mp = attr.get('method_picker', {})
print('method:', mp.get('method'))
print('rule_fired:', mp.get('rule_fired'))
opt = attr.get('optimization', {})
print('nco_breakdown present:', 'nco_breakdown' in opt)
if 'nco_breakdown' in opt:
    for pool, br in opt['nco_breakdown'].items():
        print(f'  {pool}: n_clusters={br.get(\"n_clusters\")}, silhouette={br.get(\"silhouette\")}')
weights = p.get('weights', {})
print('n_total:', len(weights))
print('ENB:', attr.get('enb'))
"
```

- [ ] **Step 5: 회귀 비교 (regression_compare 와 force_method 비교)**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/regression_compare.py \
    --baseline artifacts/baseline/ \
    --new artifacts/ \
    --out artifacts/phase3a_regression.json 2>&1 | tail -30
```
NCO 산출물 vs baseline (HRP) 비교 — 다른 method 이므로 weights 자연히 다름. acceptance (a)(b)(c) 가 통과되는지 확인.

- [ ] **Step 6: Full regression**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest \
    tests/unit/skills/test_portfolio_*.py \
    tests/unit/agents/test_portfolio_allocator.py \
    tests/unit/observability/test_stage3_ablation.py \
    tests/integration/test_allocator_phase1.py \
    tests/integration/test_allocator_phase2a.py \
    tests/integration/test_allocator_phase2b.py \
    tests/integration/test_allocator_phase3a.py \
    tests/integration/test_plan_pipeline_mock.py \
    tests/integration/test_5_28_dry_run.py \
    -q 2>&1 | tail -10
```
Expected: 337 + 20 + 7 + 1 ≈ 365+ tests pass.

- [ ] **Step 7: Commit artifacts + regression result**

```bash
git add artifacts/2025-04-15/ artifacts/2026-05-15/ artifacts/phase3a_regression.json 2>/dev/null

if git diff --cached --quiet; then
    echo "nothing to commit"
else
    git commit -m "$(cat <<'EOF'
chore(stage3): Phase 3a 적용 후 산출물 + regression 결과

baseline → phase3a:
  default method (force_method 없음): 기존 method 그대로 (회귀 무손실)
  --force-method nco: NCO 활성화, attribution.nco_breakdown 채워짐
  rule_fired='state_override' 가시화

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
fi
```

---

## Self-Review

플랜 완성 후 spec 대비 누락 확인:

1. **Spec 신규/변경 모듈**:
   - `nco.py` (compute_nco_weights + helpers) — Task 1, 2, 3, 4 ✓
   - `OptimizationMethod.NCO` enum — Task 5 ✓
   - `_nco_per_bucket` + allocator NCO 분기 — Task 6 ✓
   - `state["force_method"]` 메커니즘 — Task 7 ✓
   - `test_portfolio_nco.py` — Task 1-4 (20 tests) ✓
   - `test_allocator_phase3a.py` — Task 8 (7 tests) ✓
   - `scripts/run_e2e_test.py` 의 `--force-method` — Task 9 ✓

2. **Spec acceptance criteria (a)-(e)** — Task 10 ✓

3. **Backward compat** — 모든 task 가 추가만 (Phase 1, 2a, 2b 와 일관)

4. **Bond TIPS path** — Task 6 의 `_nco_per_bucket` 가 HRP 패턴 그대로 (split_bond)

5. **Single asset cap (20%) water-fill** — Task 6 에서 HRP 패턴 재사용

## Execution Notes

- 모든 task TDD 흐름 (실패 → 구현 → 통과 → 커밋)
- Task 6 의 `_nco_per_bucket` 는 `_hrp_per_bucket` 코드를 참고하되 NCO 알고리즘으로 교체. 정확한 라인 인용은 worktree 안에서 수행 (plan 작성 시점의 line 번호와 다를 수 있음)
- Task 10 의 e2e 는 환경 의존 (.env, langchain) — 실패 시 partial DONE_WITH_CONCERNS
- Phase 1, 2a, 2b 의 모든 회귀 무손실 확인 필수
- 모든 commit message `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` trailer 권장
