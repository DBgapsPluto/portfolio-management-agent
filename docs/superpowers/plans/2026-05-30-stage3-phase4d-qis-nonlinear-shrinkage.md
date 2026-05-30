# Stage 3 Phase 4d — QIS Nonlinear Shrinkage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `cov_estimator.py` 에 `_qis_cov` NumPy 구현 + `compute_robust_cov` 시그니처에 `method=` 추가 (default "qis"). 8 호출지 자동 QIS, linear LW 는 `method="ledoit_wolf"` 옵션으로 보존.

**Architecture:** Phase 4a 의 `compute_robust_cov` 분기 확장 (method 별). `_qis_cov(Y, k=1)` 신규 NumPy 구현 (Ledoit-Wolf 2020 Algorithm 1). attribution.cov_breakdown.estimator 값이 "qis" 가 default.

**Tech Stack:** Python 3.13, NumPy (eigh), pytest.

**Test runner:** `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest`

---

## Task 1: `_qis_cov` 구현 + 6 unit tests + 기존 2 갱신

**Files:**
- Modify: `tradingagents/skills/portfolio/cov_estimator.py`
- Modify: `tests/unit/skills/test_portfolio_cov_estimator.py`

- [ ] **Step 1: Inspect existing structure**

```bash
cat tradingagents/skills/portfolio/cov_estimator.py
grep -n "test_compute_robust_cov_records_breakdown\|test_compute_robust_cov_shrinkage_intensity" tests/unit/skills/test_portfolio_cov_estimator.py
```

- [ ] **Step 2: Write failing unit tests (6 new + identify 2 to update)**

Append to `tests/unit/skills/test_portfolio_cov_estimator.py`:

```python
def test_qis_cov_basic_shape_psd_with_default():
    """default method='qis' → PSD DataFrame, shape."""
    returns = _make_returns(n_obs=252, n_assets=5)
    cov = compute_robust_cov(returns)  # default method="qis"
    assert isinstance(cov, pd.DataFrame)
    assert cov.shape == (5, 5)
    eigenvalues = np.linalg.eigvalsh(cov.values)
    assert (eigenvalues >= -1e-9).all()


def test_qis_cov_method_ledoit_wolf_explicit():
    """method='ledoit_wolf' → Phase 4a 동작 (δ ∈ [0,1])."""
    returns = _make_returns(n_obs=252, n_assets=5)
    breakdown: dict = {}
    compute_robust_cov(returns, method="ledoit_wolf", breakdown_out=breakdown)
    assert breakdown["estimator"] == "ledoit_wolf"
    delta = breakdown["shrinkage_intensity"]
    assert 0.0 <= delta <= 1.0


def test_qis_cov_method_qis_explicit():
    """method='qis' 명시 → estimator='qis'."""
    returns = _make_returns(n_obs=252, n_assets=5)
    breakdown: dict = {}
    compute_robust_cov(returns, method="qis", breakdown_out=breakdown)
    assert breakdown["estimator"] == "qis"


def test_qis_cov_unknown_method_fallback():
    """method='xyz' → sample_cov fallback + method_attempted='xyz'."""
    returns = _make_returns(n_obs=252, n_assets=5)
    breakdown: dict = {}
    cov = compute_robust_cov(returns, method="xyz", breakdown_out=breakdown)
    assert isinstance(cov, pd.DataFrame)
    assert cov.shape == (5, 5)
    assert "fallback_reason" in breakdown
    assert breakdown.get("method_attempted") == "xyz"


def test_qis_cov_differs_from_linear():
    """QIS ≠ ledoit_wolf 결과 (non-degenerate input)."""
    returns = _make_returns(n_obs=252, n_assets=5)
    cov_qis = compute_robust_cov(returns, method="qis")
    cov_lw = compute_robust_cov(returns, method="ledoit_wolf")
    assert not np.allclose(cov_qis.values, cov_lw.values, atol=1e-12)


def test_qis_cov_intensity_in_signed_range():
    """QIS intensity ∈ [-1, 1] (음수 가능)."""
    returns = _make_returns(n_obs=252, n_assets=5)
    breakdown: dict = {}
    compute_robust_cov(returns, method="qis", breakdown_out=breakdown)
    intensity = breakdown["shrinkage_intensity"]
    assert -1.0 <= intensity <= 1.0
```

**기존 2 tests 갱신** — `test_compute_robust_cov_records_breakdown` 의 `estimator == "ledoit_wolf"` assertion 을 `== "qis"` 로, `test_compute_robust_cov_shrinkage_intensity_in_unit_interval` 의 `[0, 1]` 범위를 `[-1, 1]` 로 변경. (또는 두 test 를 두 method 모두 검증하도록 분리 — Step 7 에서 결정.)

- [ ] **Step 3: Run, expect FAIL (method param 미존재)**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_cov_estimator.py -v 2>&1 | tail -20
```

Expected: 6 new tests FAIL.

- [ ] **Step 4: Replace `compute_robust_cov` body**

Edit `tradingagents/skills/portfolio/cov_estimator.py`. Add `import numpy as np` if missing. Replace `compute_robust_cov` function:

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
        method: "qis" (Ledoit-Wolf 2020 nonlinear, default) or
                "ledoit_wolf" (2004 linear).
        breakdown_out: optional trace dict.

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

- [ ] **Step 5: Add `_qis_cov` helper**

Append to `tradingagents/skills/portfolio/cov_estimator.py`:

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
        cov_shrunk: N × N nonlinear-shrinkage covariance (symmetric).
        mean_intensity: scalar — mean(1 - shrunk_λ / sample_λ) over non-zero λ.
            QIS 는 per-eigenvalue 차등 shrinkage 라 단일 δ 가 없음.
            양수: 평균 축소, 음수: 평균 확장 (정상 — 작은 λ 가 커짐).

    Reference: Ledoit & Wolf (2020) "Analytical Nonlinear Shrinkage of
    Large-Dimensional Covariance Matrices", Annals of Statistics 48(5).
    """
    T, N = Y.shape
    Y = Y - Y.mean(axis=0, keepdims=True)
    n = T - k

    sample = (Y.T @ Y) / n

    lambdas, u = np.linalg.eigh(sample)
    lambdas = lambdas.real
    lambdas = np.maximum(lambdas, 0.0)

    c = N / n
    h = (min(c**2, 1.0 / c**2) ** 0.35) / N**0.35

    n_eff = min(N, n)
    lam_eff = lambdas[N - n_eff:]

    L = np.outer(lam_eff, np.ones(n_eff)) - np.outer(np.ones(n_eff), lam_eff)
    denom = L**2 + (h * lam_eff[:, None])**2
    denom = np.where(denom > 0, denom, 1.0)

    Hcomponent = L / denom
    Htilde = Hcomponent.mean(axis=1)

    fcomponent = (h * lam_eff[:, None]) / denom
    ftilde = (c / np.pi) * fcomponent.mean(axis=1)

    real_part = 1.0 - c - np.pi * c * lam_eff * Htilde
    imag_part = np.pi * c * lam_eff * ftilde
    d_star = lam_eff / (real_part**2 + imag_part**2 + 1e-30)

    d_full = np.zeros(N)
    d_full[N - n_eff:] = d_star

    cov_shrunk = u @ np.diag(d_full) @ u.T
    cov_shrunk = (cov_shrunk + cov_shrunk.T) / 2

    mask = lam_eff > 1e-12
    if mask.any():
        intensity = float(np.mean(1.0 - d_star[mask] / lam_eff[mask]))
    else:
        intensity = 0.0

    return cov_shrunk, intensity
```

- [ ] **Step 6: Run 6 new tests to verify PASS**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_cov_estimator.py -k "qis_cov" -v 2>&1 | tail -15
```

Expected: 6 PASS.

- [ ] **Step 7: Update 2 existing tests**

Find and edit:

```bash
grep -n "test_compute_robust_cov_records_breakdown\|test_compute_robust_cov_shrinkage_intensity_in_unit_interval" tests/unit/skills/test_portfolio_cov_estimator.py
```

In `test_compute_robust_cov_records_breakdown`:
```python
# Change:
assert breakdown["estimator"] == "ledoit_wolf"
# To:
assert breakdown["estimator"] == "qis"
```

In `test_compute_robust_cov_shrinkage_intensity_in_unit_interval`:
```python
# Change:
assert 0.0 <= delta <= 1.0
# To:
assert -1.0 <= delta <= 1.0
```

- [ ] **Step 8: Run full cov_estimator suite**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_cov_estimator.py -v 2>&1 | tail -20
```

Expected: 12 PASS (6 existing updated + 6 new).

- [ ] **Step 9: Commit**

```bash
git add tradingagents/skills/portfolio/cov_estimator.py tests/unit/skills/test_portfolio_cov_estimator.py
git commit -m "$(cat <<'EOF'
feat(stage3): Phase 4d _qis_cov + compute_robust_cov method param

_qis_cov(Y, k=1) — Ledoit-Wolf 2020 Quadratic-Inverse Shrinkage NumPy 구현.
Eigendecomposition + Hilbert transform + spectral density 기반 per-eigenvalue
nonlinear shrinkage (Eq 4.5).

compute_robust_cov 시그니처 확장: *, method='qis' default.
method='ledoit_wolf' 옵션으로 Phase 4a 동작 보존. unknown method →
sample_cov fallback + method_attempted 기록.

attribution.cov_breakdown.estimator: 'qis' (default).
shrinkage_intensity 의미: linear δ ∈ [0,1], QIS mean(1-d/λ) ∈ [-1,1].

Tests: 6 신규 unit + 2 기존 갱신 (estimator 값 + intensity 범위).
EOF
)"
```

---

## Task 2: integration tests + Phase 4a 1 assertion 갱신

**Files:**
- Create: `tests/integration/test_allocator_phase4d.py`
- Modify: `tests/integration/test_allocator_phase4a.py` (1 assertion)

- [ ] **Step 1: Inspect Phase 4a integration tests for estimator assertion**

```bash
grep -n "estimator.*ledoit_wolf\|estimator.*=" tests/integration/test_allocator_phase4a.py
```

Identify lines that assert `estimator == "ledoit_wolf"` — these need update to `"qis"`.

- [ ] **Step 2: Create Phase 4d integration tests**

Create `tests/integration/test_allocator_phase4d.py`:

```python
"""Phase 4d QIS nonlinear shrinkage — integration tests."""
import pytest

from tradingagents.agents.allocator.portfolio_allocator import build_portfolio_allocator
from tests.integration._allocator_state_helpers import build_state


def test_allocator_cov_estimator_default_is_qis():
    """attribution.cov_breakdown.estimator == 'qis' (default)."""
    state = build_state(scenario="goldilocks", regime_confidence=0.5)
    result = build_portfolio_allocator()(state)
    attr = result["portfolio"]["allocation_attribution"]
    bd = attr.get("cov_breakdown") or attr.get("optimization", {}).get("cov_breakdown")
    assert bd is not None, f"cov_breakdown missing, keys: {list(attr.keys())}"
    assert bd["estimator"] == "qis"


def test_allocator_nco_cov_breakdown_estimator_qis():
    """NCO path per-pool cov_breakdown 도 'qis'."""
    state = build_state(scenario="goldilocks", regime_confidence=0.5)
    state["force_method"] = "nco"
    result = build_portfolio_allocator()(state)
    attr = result["portfolio"]["allocation_attribution"]
    opt = attr.get("optimization", {})
    nco_per_pool = opt.get("nco_breakdown_per_pool", {})
    assert nco_per_pool, "nco_breakdown_per_pool empty"
    qis_pools = [
        p for p, data in nco_per_pool.items()
        if data.get("cov_breakdown", {}).get("estimator") == "qis"
    ]
    assert qis_pools, f"no pool has estimator='qis': {nco_per_pool}"
```

- [ ] **Step 3: Run, expect PASS (default 가 이미 qis)**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/integration/test_allocator_phase4d.py -v 2>&1 | tail -15
```

Expected: 2 PASS.

- [ ] **Step 4: Update Phase 4a estimator assertion (if any)**

Find via grep (Step 1). If Phase 4a integration tests assert `estimator == "ledoit_wolf"`, change to `"qis"`:

```python
# Before
assert bd["estimator"] == "ledoit_wolf"
# After
assert bd["estimator"] == "qis"
```

(Phase 4a's spec said `estimator == "ledoit_wolf"` but Phase 4d changes default — Phase 4a integration tests verify the keys exist; if they assert estimator value specifically, that needs update.)

- [ ] **Step 5: Run Phase 1-4c integration regression**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest \
    tests/integration/test_allocator_phase1.py \
    tests/integration/test_allocator_phase2a.py \
    tests/integration/test_allocator_phase2b.py \
    tests/integration/test_allocator_phase3a.py \
    tests/integration/test_allocator_phase3b.py \
    tests/integration/test_allocator_phase3c.py \
    tests/integration/test_allocator_phase4a.py \
    tests/integration/test_allocator_phase4b.py \
    tests/integration/test_allocator_phase4c.py \
    tests/integration/test_allocator_phase4d.py \
    tests/integration/test_plan_pipeline_mock.py \
    -q 2>&1 | tail -10
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_allocator_phase4d.py
git add tests/integration/test_allocator_phase4a.py 2>/dev/null
git commit -m "$(cat <<'EOF'
test(stage3): Phase 4d integration + Phase 4a estimator assertion 갱신

2 신규 integration: allocator default estimator='qis', NCO per-pool
cov_breakdown estimator='qis'. Phase 4a integration test 의 estimator
ledoit_wolf 단언을 qis 로 갱신 (default 변경 반영).
EOF
)"
```

---

## Task 3: Regression + Acceptance

- [ ] **Step 1: Setup .env**

```bash
cp /Users/kimjaewon/Pluto/TradingAgents/.env . 2>/dev/null || echo ".env missing"
ls -la .env 2>&1 | head
```

- [ ] **Step 2: Default E2E**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/run_e2e_test.py \
    --as-of 2026-05-15 --capital 1000000000 2>&1 | tail -25
```

Expected: 정상 종료. attribution 에 estimator="qis".

- [ ] **Step 3: NCO E2E**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/run_e2e_test.py \
    --as-of 2026-05-15 --capital 1000000000 \
    --force-method nco 2>&1 | tail -25
```

- [ ] **Step 4: Verify attribution**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -c "
import json
with open('artifacts/2026-05-15/portfolio.json') as f:
    p = json.load(f)
attr = p['allocation_attribution']
bd = attr.get('cov_breakdown') or attr.get('optimization', {}).get('cov_breakdown') or {}
print('estimator:', bd.get('estimator'))
print('shrinkage_intensity (QIS mean):', bd.get('shrinkage_intensity'))
print('n_obs:', bd.get('n_obs'))
print('n_assets:', bd.get('n_assets'))
opt = attr.get('optimization', {})
if 'nco_breakdown_per_pool' in opt:
    for pool, data in list(opt['nco_breakdown_per_pool'].items())[:3]:
        cb = data.get('cov_breakdown', {})
        print(f'  pool {pool}: estimator={cb.get(\"estimator\")}, intensity={cb.get(\"shrinkage_intensity\")}, n={cb.get(\"n_assets\")}')
weights = p.get('weights', {})
print('weight sum:', sum(weights.values()))
print('n_total:', len(weights))
"
```

Expected: estimator='qis', intensity ∈ [-1, 1].

- [ ] **Step 5: Regression compare**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/regression_compare.py \
    --baseline artifacts/baseline/ \
    --new artifacts/ \
    --out artifacts/phase4d_regression.json 2>&1 | tail -15
```

- [ ] **Step 6: Full test regression**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest \
    tests/unit/skills/test_portfolio_bl_views.py \
    tests/unit/skills/test_portfolio_nco.py \
    tests/unit/skills/test_portfolio_method_picker.py \
    tests/unit/skills/test_portfolio_cov_estimator.py \
    tests/unit/agents/test_portfolio_allocator.py \
    tests/unit/observability/test_stage3_ablation.py \
    tests/integration/test_allocator_phase1.py \
    tests/integration/test_allocator_phase2a.py \
    tests/integration/test_allocator_phase2b.py \
    tests/integration/test_allocator_phase3a.py \
    tests/integration/test_allocator_phase3b.py \
    tests/integration/test_allocator_phase3c.py \
    tests/integration/test_allocator_phase4a.py \
    tests/integration/test_allocator_phase4b.py \
    tests/integration/test_allocator_phase4c.py \
    tests/integration/test_allocator_phase4d.py \
    tests/integration/test_plan_pipeline_mock.py \
    tests/integration/test_5_28_dry_run.py \
    -q 2>&1 | tail -8
```

Expected: all PASS.

- [ ] **Step 7: Commit artifacts**

```bash
git add artifacts/2025-04-15/ artifacts/2026-05-15/ artifacts/phase4d_regression.json 2>/dev/null
if git diff --cached --quiet; then
    echo "nothing"
else
    git commit -m "$(cat <<'EOF'
chore(stage3): Phase 4d 적용 후 산출물 + regression

baseline → phase4d:
  attribution.cov_breakdown.estimator: 'ledoit_wolf' → 'qis'
  shrinkage_intensity 의미 변경: QIS per-eigenvalue 의 평균 (음수 가능)
  weight 가 nonlinear shrinkage 효과로 약간 달라짐

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
fi
```

---

## Self-Review

### Spec coverage

| Spec section | Task |
|---|---|
| `_qis_cov(Y, k=1)` NumPy 구현 | Task 1 Step 5 |
| `compute_robust_cov` method param | Task 1 Step 4 |
| default "qis" | Task 1 Step 4 |
| Unknown method fallback | Task 1 Step 4 |
| `method_attempted` 기록 | Task 1 Step 4 |
| Phase 4a integration test estimator 갱신 | Task 2 Step 4 |
| 6 unit + 2 기존 갱신 | Task 1 Steps 2/7 |
| 2 integration (default qis, NCO qis) | Task 2 Step 2 |
| Full regression | Task 3 Steps 5-6 |
| attribution intensity ∈ [-1, 1] | Task 1 Step 7 |

### Placeholder scan

No "TBD", "TODO". 모든 code block complete.

### Type consistency

- `_qis_cov(Y: np.ndarray, k: int = 1) -> tuple[np.ndarray, float]` 일관.
- `compute_robust_cov(returns, *, method: str = "qis", breakdown_out=None) -> pd.DataFrame` 일관.
- attribution key: `estimator` (str), `shrinkage_intensity` (float), `n_obs` (int), `n_assets` (int), optional `fallback_reason`, `method_attempted`.
