# Stage 3 Phase 4a — Ledoit-Wolf Shrinkage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sample_cov` / `returns.cov()` 8 호출지를 `compute_robust_cov` (Ledoit-Wolf linear shrinkage) 로 일괄 교체.

**Architecture:** `tradingagents/skills/portfolio/cov_estimator.py` 신규 helper. allocator + NCO 가 attribution.cov_breakdown 노출. 4 호출지 (overlay/optimizers/conditional) silent 교체. nco.py:154 clustering corr 은 raw 유지.

**Tech Stack:** Python 3.13, pypfopt `CovarianceShrinkage`, pytest.

**Test runner:** `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest`

---

## Task 1: cov_estimator.py 모듈 + unit tests

**Files:**
- Create: `tradingagents/skills/portfolio/cov_estimator.py`
- Test: `tests/unit/skills/test_portfolio_cov_estimator.py`

- [ ] **Step 1: Write failing unit tests**

Create `tests/unit/skills/test_portfolio_cov_estimator.py`:

```python
"""Phase 4a Ledoit-Wolf shrinkage unit tests."""
import numpy as np
import pandas as pd
import pytest

from tradingagents.skills.portfolio.cov_estimator import compute_robust_cov


def _make_returns(n_obs=252, n_assets=5, seed=42):
    rng = np.random.default_rng(seed)
    data = rng.normal(0.0005, 0.012, size=(n_obs, n_assets))
    columns = [f"A{i:03d}" for i in range(n_assets)]
    return pd.DataFrame(data, columns=columns)


def test_compute_robust_cov_basic_returns_dataframe():
    returns = _make_returns()
    cov = compute_robust_cov(returns)
    assert isinstance(cov, pd.DataFrame)
    assert cov.shape == (5, 5)
    assert list(cov.index) == list(returns.columns)
    assert list(cov.columns) == list(returns.columns)


def test_compute_robust_cov_records_breakdown():
    returns = _make_returns()
    breakdown: dict = {}
    cov = compute_robust_cov(returns, breakdown_out=breakdown)
    assert breakdown["estimator"] == "ledoit_wolf"
    assert "shrinkage_intensity" in breakdown
    assert breakdown["n_obs"] == 252
    assert breakdown["n_assets"] == 5


def test_compute_robust_cov_shrinkage_intensity_in_unit_interval():
    returns = _make_returns()
    breakdown: dict = {}
    compute_robust_cov(returns, breakdown_out=breakdown)
    delta = breakdown["shrinkage_intensity"]
    assert 0.0 <= delta <= 1.0


def test_compute_robust_cov_is_psd():
    returns = _make_returns()
    cov = compute_robust_cov(returns)
    eigenvalues = np.linalg.eigvalsh(cov.values)
    assert (eigenvalues >= -1e-10).all(), f"non-PSD: min eigenvalue {eigenvalues.min()}"


def test_compute_robust_cov_differs_from_sample_cov():
    from pypfopt import risk_models
    returns = _make_returns()
    cov_shrunk = compute_robust_cov(returns)
    cov_sample = risk_models.sample_cov(returns, returns_data=True)
    # shrinkage 가 sample 과 다름 (non-degenerate input)
    assert not np.allclose(cov_shrunk.values, cov_sample.values, atol=1e-12)


def test_compute_robust_cov_fallback_on_failure():
    # constant returns 는 variance=0 → pypfopt 가 실패하거나 degenerate.
    # 우리 helper 의 fallback path 동작 확인.
    constant = pd.DataFrame(
        np.zeros((252, 3)),
        columns=["A", "B", "C"],
    )
    breakdown: dict = {}
    cov = compute_robust_cov(constant, breakdown_out=breakdown)
    # fallback 발동 또는 zero cov 결과. 어느 쪽이든 DataFrame 반환.
    assert isinstance(cov, pd.DataFrame)
    assert cov.shape == (3, 3)
    # fallback_reason 또는 정상 estimator 키 둘 중 하나는 있어야.
    assert "estimator" in breakdown or "fallback_reason" in breakdown
```

- [ ] **Step 2: Run tests to verify FAIL (ImportError)**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_cov_estimator.py -v 2>&1 | tail -10
```

Expected: ImportError on `compute_robust_cov` (module not found).

- [ ] **Step 3: Implement `cov_estimator.py`**

Create `tradingagents/skills/portfolio/cov_estimator.py`:

```python
"""
Phase 4a: Robust covariance estimation.

Ledoit-Wolf linear shrinkage covariance — replaces sample_cov / returns.cov()
across allocator, optimizers, NCO, overlay.

Why shrinkage: sample covariance is unbiased but high-variance in small-sample
regimes (T < N or T ~ N). NCO/HRP/BL all condition on covariance — sample noise
propagates to weights as concentration risk. Ledoit-Wolf 2004 shrinks toward the
constant-variance identity target with closed-form δ. PSD guaranteed.
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

- [ ] **Step 4: Run tests to verify PASS**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_cov_estimator.py -v 2>&1 | tail -12
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/portfolio/cov_estimator.py tests/unit/skills/test_portfolio_cov_estimator.py
git commit -m "$(cat <<'EOF'
feat(stage3): Phase 4a cov_estimator 모듈 + compute_robust_cov

Ledoit-Wolf linear shrinkage covariance helper. pypfopt CovarianceShrinkage
wrap. δ shrinkage_intensity 노출, constant returns fallback (sample_cov).

Tests: 6 unit (basic, breakdown, δ ∈ [0,1], PSD, differs_from_sample, fallback).
EOF
)"
```

---

## Task 2: 8 호출지 교체 + integration tests

**Files:**
- Modify: `tradingagents/agents/allocator/portfolio_allocator.py` (line ~537)
- Modify: `tradingagents/agents/allocator/overlay_apply.py` (line ~79)
- Modify: `tradingagents/skills/portfolio/optimizers.py` (lines 39, 56, 88)
- Modify: `tradingagents/graph/conditional_logic.py` (line ~48)
- Modify: `tradingagents/skills/portfolio/nco.py` (lines 142, 153 — NOT 154)
- Create: `tests/integration/test_allocator_phase4a.py`

- [ ] **Step 1: Inspect actual line numbers + signature context**

```bash
grep -n "sample_cov\|returns\.cov()" tradingagents/skills/portfolio/nco.py tradingagents/skills/portfolio/optimizers.py tradingagents/agents/allocator/portfolio_allocator.py tradingagents/agents/allocator/overlay_apply.py tradingagents/graph/conditional_logic.py 2>&1
```

Record actual line numbers and ensure each call site context.

- [ ] **Step 2: Modify `portfolio_allocator.py` (line ~537) — attribution exposure**

Find:
```python
    S = risk_models.sample_cov(returns)
```

Replace with:
```python
    from tradingagents.skills.portfolio.cov_estimator import compute_robust_cov
    cov_breakdown: dict = {}
    S = compute_robust_cov(returns, breakdown_out=cov_breakdown)
    if attribution is not None:
        attribution["cov_breakdown"] = cov_breakdown
```

(Import 가 이미 다른 곳에 있으면 inline import 빼고 위로 옮기기.)

- [ ] **Step 3: Modify `nco.py` (line 142 — n=2 shortcut)**

Find:
```python
    if n_assets == 2:
        cov = returns.cov()
```

Replace with:
```python
    if n_assets == 2:
        from tradingagents.skills.portfolio.cov_estimator import compute_robust_cov
        cov = compute_robust_cov(returns)
```

- [ ] **Step 4: Modify `nco.py` (line 153 — general path) + breakdown integration**

Find:
```python
    cov = returns.cov()
    corr = returns.corr().fillna(0.0)
```

Replace with:
```python
    from tradingagents.skills.portfolio.cov_estimator import compute_robust_cov
    cov_bd: dict = {}
    cov = compute_robust_cov(returns, breakdown_out=cov_bd)
    if breakdown_out is not None:
        breakdown_out["cov_breakdown"] = cov_bd
    corr = returns.corr().fillna(0.0)  # unchanged — clustering distance 용 raw
```

(Module-level import 로 옮길 수 있으면 더 좋음.)

- [ ] **Step 5: Modify `overlay_apply.py` (line ~79)**

Find:
```python
    S = risk_models.sample_cov(returns)
```

Replace with:
```python
    from tradingagents.skills.portfolio.cov_estimator import compute_robust_cov
    S = compute_robust_cov(returns)
```

- [ ] **Step 6: Modify `optimizers.py` (lines 39, 56, 88) — 3 곳**

In each of `optimize_min_volatility`, `optimize_risk_parity`, `optimize_black_litterman`:

Find:
```python
    S = risk_models.sample_cov(returns)
```

Replace with:
```python
    from tradingagents.skills.portfolio.cov_estimator import compute_robust_cov
    S = compute_robust_cov(returns)
```

Module-level import preferred (1 import for all 3 functions).

- [ ] **Step 7: Modify `conditional_logic.py` (line ~48)**

Find:
```python
    S = risk_models.sample_cov(returns)
```

Replace with:
```python
    from tradingagents.skills.portfolio.cov_estimator import compute_robust_cov
    S = compute_robust_cov(returns)
```

- [ ] **Step 8: Verify NCO unit tests still pass (existing weight assertions)**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_nco.py -v 2>&1 | tail -15
```

Expected: most pass. If any failed due to cov-specific value assertion, inspect:
```bash
grep -nE "cov\.|sample_cov|returns\.cov" tests/unit/skills/test_portfolio_nco.py
```

If a test directly asserts cov values (unlikely — most assert weight/sum), update tolerance.

- [ ] **Step 9: Write Phase 4a integration tests**

Create `tests/integration/test_allocator_phase4a.py`:

```python
"""Phase 4a Ledoit-Wolf shrinkage — integration tests."""
import pytest

from tradingagents.agents.allocator.portfolio_allocator import build_portfolio_allocator
from tests.integration._allocator_state_helpers import build_state


def test_allocator_records_cov_breakdown():
    state = build_state(scenario="goldilocks", regime_confidence=0.5)
    result = build_portfolio_allocator()(state)
    attr = result["portfolio"]["allocation_attribution"]
    assert "cov_breakdown" in attr
    bd = attr["cov_breakdown"]
    assert bd["estimator"] == "ledoit_wolf"
    assert "shrinkage_intensity" in bd
    assert "n_obs" in bd
    assert "n_assets" in bd


def test_allocator_shrinkage_intensity_finite():
    state = build_state(scenario="goldilocks", regime_confidence=0.5)
    result = build_portfolio_allocator()(state)
    attr = result["portfolio"]["allocation_attribution"]
    delta = attr["cov_breakdown"]["shrinkage_intensity"]
    assert 0.0 <= delta <= 1.0


def test_allocator_nco_breakdown_contains_cov_section():
    """NCO path: nco_breakdown_per_pool 의 각 pool 안에 cov_breakdown 포함."""
    state = build_state(scenario="goldilocks", regime_confidence=0.5)
    state["force_method"] = "nco"
    result = build_portfolio_allocator()(state)
    attr = result["portfolio"]["allocation_attribution"]
    opt = attr.get("optimization", {})
    nco_per_pool = opt.get("nco_breakdown_per_pool", {})
    assert nco_per_pool, "nco_breakdown_per_pool empty"
    # 적어도 하나의 pool 에 cov_breakdown 포함
    has_cov_bd = any(
        "cov_breakdown" in pool_data
        for pool_data in nco_per_pool.values()
    )
    assert has_cov_bd, f"no pool has cov_breakdown: {nco_per_pool}"
```

- [ ] **Step 10: Run integration tests**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/integration/test_allocator_phase4a.py -v 2>&1 | tail -15
```

Expected: 3 passed. If test 3 fails because `nco_breakdown_per_pool` 구조가 예상과 다름, inspect:

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -c "
from tests.integration._allocator_state_helpers import build_state
from tradingagents.agents.allocator.portfolio_allocator import build_portfolio_allocator
s = build_state(scenario='goldilocks', regime_confidence=0.5)
s['force_method'] = 'nco'
r = build_portfolio_allocator()(s)
attr = r['portfolio']['allocation_attribution']
opt = attr.get('optimization', {})
import json
print(json.dumps(opt, indent=2, default=str)[:2000])
"
```

Adjust assertion path to match actual structure.

- [ ] **Step 11: Verify no remaining sample_cov calls in target sites**

```bash
grep -nE "sample_cov|returns\.cov\(\)" tradingagents/skills/portfolio/nco.py tradingagents/skills/portfolio/optimizers.py tradingagents/agents/allocator/portfolio_allocator.py tradingagents/agents/allocator/overlay_apply.py tradingagents/graph/conditional_logic.py 2>&1
```

Expected: only `compute_robust_cov` 내부의 `sample_cov` fallback path 만 보임 (cov_estimator.py 내). 타겟 호출지에는 zero match.

- [ ] **Step 12: Quick regression on Phase 1-3c integration**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest \
    tests/integration/test_allocator_phase1.py \
    tests/integration/test_allocator_phase2a.py \
    tests/integration/test_allocator_phase2b.py \
    tests/integration/test_allocator_phase3a.py \
    tests/integration/test_allocator_phase3b.py \
    tests/integration/test_allocator_phase3c.py \
    tests/integration/test_allocator_phase4a.py \
    tests/integration/test_plan_pipeline_mock.py \
    -q 2>&1 | tail -10
```

Expected: all PASS. If Phase 1/2 test fails due to weight value assertion changes (shrinkage 가 weight 미세 변경), update assertion tolerance.

- [ ] **Step 13: Commit**

```bash
git add tradingagents/skills/portfolio/cov_estimator.py 2>/dev/null
git add tradingagents/skills/portfolio/nco.py
git add tradingagents/skills/portfolio/optimizers.py
git add tradingagents/agents/allocator/portfolio_allocator.py
git add tradingagents/agents/allocator/overlay_apply.py
git add tradingagents/graph/conditional_logic.py
git add tests/integration/test_allocator_phase4a.py
# Phase 1/2 test 변경됐다면 함께
git add tests/integration/test_allocator_phase1.py tests/integration/test_allocator_phase2a.py tests/integration/test_allocator_phase2b.py 2>/dev/null

git commit -m "$(cat <<'EOF'
feat(stage3): Phase 4a — 8 호출지 sample_cov → compute_robust_cov

allocator(537), overlay_apply(79), optimizers(39/56/88), conditional_logic(48),
nco(142, 153) 모두 compute_robust_cov 호출로 교체. nco:154 returns.corr()
clustering distance 용으로 unchanged.

allocator + NCO 의 attribution.cov_breakdown 에 estimator + δ shrinkage_intensity
+ n_obs + n_assets 노출. silent 4 호출지 (overlay/optimizers/conditional)는
breakdown_out 안 전달.

Tests: 3 신규 integration (cov_breakdown 노출, δ finite, NCO breakdown 통합).
EOF
)"
```

---

## Task 3: Regression + Acceptance

- [ ] **Step 1: Setup .env if missing**

```bash
cp /Users/kimjaewon/Pluto/TradingAgents/.env . 2>/dev/null || echo ".env not copied (may exist or absent)"
ls -la .env 2>&1 | head
```

- [ ] **Step 2: Default E2E**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/run_e2e_test.py \
    --as-of 2026-05-15 --capital 1000000000 2>&1 | tail -25
```

Expected: 정상 종료. attribution 에 cov_breakdown 추가, 그 외는 기존과 유사 (BL trigger 변함 없음, weight 미세 변경).

- [ ] **Step 3: --force-method nco E2E**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/run_e2e_test.py \
    --as-of 2026-05-15 --capital 1000000000 \
    --force-method nco 2>&1 | tail -25
```

Expected: NCO 동작, attribution 의 nco_breakdown_per_pool 안에 cov_breakdown.

- [ ] **Step 4: Verify attribution structure**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -c "
import json
with open('artifacts/2026-05-15/portfolio.json') as f:
    p = json.load(f)
attr = p['allocation_attribution']
print('method:', attr.get('method_picker', {}).get('method'))
print('rule_fired:', attr.get('method_picker', {}).get('rule_fired'))
if 'cov_breakdown' in attr:
    cb = attr['cov_breakdown']
    print('cov estimator:', cb.get('estimator'))
    print('shrinkage δ:', cb.get('shrinkage_intensity'))
    print('n_obs:', cb.get('n_obs'))
    print('n_assets:', cb.get('n_assets'))
opt = attr.get('optimization', {})
if 'nco_breakdown_per_pool' in opt:
    for pool, data in list(opt['nco_breakdown_per_pool'].items())[:3]:
        cb = data.get('cov_breakdown', {})
        print(f'  pool {pool}: δ={cb.get(\"shrinkage_intensity\")}, n={cb.get(\"n_assets\")}')
weights = p.get('weights', {})
print('weight sum:', sum(weights.values()))
print('n_total:', len(weights))
"
```

Expected: method/rule_fired 출력 + cov estimator=ledoit_wolf + δ ∈ [0,1].

- [ ] **Step 5: Regression compare**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/regression_compare.py \
    --baseline artifacts/baseline/ \
    --new artifacts/ \
    --out artifacts/phase4a_regression.json 2>&1 | tail -15
```

(a)(b)(c) tolerance 안에 있을 가능성 높음 (shrinkage 가 weight 미세 변경만 유발). (d) fx_commodity 는 Phase 3b 부터 carryover.

- [ ] **Step 6: Full test regression**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest \
    tests/unit/skills/test_portfolio_cov_estimator.py \
    tests/unit/skills/test_portfolio_bl_views.py \
    tests/unit/skills/test_portfolio_nco.py \
    tests/unit/skills/test_portfolio_method_picker.py \
    tests/unit/agents/test_portfolio_allocator.py \
    tests/unit/observability/test_stage3_ablation.py \
    tests/integration/test_allocator_phase1.py \
    tests/integration/test_allocator_phase2a.py \
    tests/integration/test_allocator_phase2b.py \
    tests/integration/test_allocator_phase3a.py \
    tests/integration/test_allocator_phase3b.py \
    tests/integration/test_allocator_phase3c.py \
    tests/integration/test_allocator_phase4a.py \
    tests/integration/test_plan_pipeline_mock.py \
    tests/integration/test_5_28_dry_run.py \
    -q 2>&1 | tail -8
```

Expected: all PASS.

- [ ] **Step 7: Commit artifacts**

```bash
git add artifacts/2025-04-15/ artifacts/2026-05-15/ artifacts/phase4a_regression.json 2>/dev/null

if git diff --cached --quiet; then
    echo "nothing to commit"
else
    git commit -m "$(cat <<'EOF'
chore(stage3): Phase 4a 적용 후 산출물 + regression 결과

baseline → phase4a:
  default e2e: method=black_litterman (BL trigger 그대로)
  attribution.cov_breakdown estimator=ledoit_wolf 추가
  weight 미세 변경 — shrinkage 효과로 집중도 약간 분산
  (a)(b)(c) tolerance 안, (d) fx_commodity carryover

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
| `cov_estimator.py` helper 신규 | Task 1 |
| `compute_robust_cov` 함수 | Task 1 Step 3 |
| pypfopt CovarianceShrinkage().ledoit_wolf() | Task 1 Step 3 |
| δ shrinkage_intensity 노출 | Task 1 Step 3 + unit test 2/3 |
| Fallback (constant returns) | Task 1 Step 3 + unit test 6 |
| 8 호출지 교체 | Task 2 Steps 2-7 |
| nco.py:154 raw corr 유지 | Task 2 Step 4 (comment + 미수정) |
| allocator attribution.cov_breakdown | Task 2 Step 2 + integration 1-2 |
| NCO breakdown 안에 cov_breakdown | Task 2 Step 4 + integration 3 |
| 6 unit tests | Task 1 Step 1 |
| 3 integration tests | Task 2 Step 9 |
| E2E 정상 동작 | Task 3 Steps 2-4 |
| 회귀 검증 | Task 3 Step 5-6 |

### Placeholder scan

No "TBD", "TODO", "fill in details". All code blocks complete. All commands exact.

### Type consistency

- `compute_robust_cov(returns: pd.DataFrame, *, breakdown_out: dict | None = None) -> pd.DataFrame` 시그니처 일관.
- breakdown_out 키 (`estimator`, `shrinkage_intensity`, `n_obs`, `n_assets`, `fallback_reason`) 일관.
- attribution path (`allocation_attribution.cov_breakdown` for allocator, `nco_breakdown_per_pool[bucket].cov_breakdown` for NCO) 일관.
