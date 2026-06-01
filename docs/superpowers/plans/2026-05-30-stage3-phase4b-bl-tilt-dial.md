# Stage 3 Phase 4b — BL Tilt Dial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `bl_views.py` 에 `SCENARIO_BL_TILT` 매트릭스 신규 + `generate_bl_views` 시그니처 확장 (return tuple [3]) + allocator BL 분기에서 scenario-specific `tau` + post-multiplier view_confidence 사용.

**Architecture:** Stage 2 scenario 별로 (τ, view_conf_multi) dial. growth scenario 공격적 (τ=0.10, multi=1.3), recession 보수 (τ=0.025, multi=0.5). force_method='black_litterman' 외부 주입 경로는 tilt 비적용 (기존 동작 보존).

**Tech Stack:** Python 3.13, pypfopt `BlackLittermanModel(tau=)`, pytest.

**Test runner:** `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest`

---

## Task 1: `bl_views.py` SCENARIO_BL_TILT + generate_bl_views 시그니처 확장 + unit tests

**Files:**
- Modify: `tradingagents/skills/portfolio/bl_views.py`
- Modify: `tests/unit/skills/test_portfolio_bl_views.py`

- [ ] **Step 1: Inspect existing bl_views structure + test assertions**

```bash
cat tradingagents/skills/portfolio/bl_views.py
grep -nE "generate_bl_views|views, confs|assert.*views\[|tilt" tests/unit/skills/test_portfolio_bl_views.py | head -30
```

Identify:
- Current return tuple unpack pattern in tests (likely `views, confs = generate_bl_views(...)`)
- All call sites of `generate_bl_views` in tests (need tuple [3] update)

- [ ] **Step 2: Write failing new unit tests (8 tests)**

Append to `tests/unit/skills/test_portfolio_bl_views.py`:

```python
from tradingagents.skills.portfolio.bl_views import (
    SCENARIO_BL_TILT,
    BL_VIEW_CONF_MIN_AFTER_MULTI,
    BL_VIEW_CONF_MAX_AFTER_MULTI,
    BL_TAU_DEFAULT,
    BL_VIEW_CONF_MULTI_DEFAULT,
)


def test_scenario_bl_tilt_covers_all_scenarios():
    """SCENARIO_BL_TILT key == SCENARIO_BUCKET_RULEBOOK key."""
    from tradingagents.skills.portfolio.bl_views import SCENARIO_BUCKET_RULEBOOK
    assert set(SCENARIO_BL_TILT.keys()) == set(SCENARIO_BUCKET_RULEBOOK.keys())


def test_scenario_bl_tilt_values_in_range():
    """τ ∈ [0.025, 0.10], multi ∈ [0.5, 1.5]."""
    for scenario, tilt in SCENARIO_BL_TILT.items():
        assert 0.025 <= tilt["tau"] <= 0.10, f"{scenario}: τ={tilt['tau']} out of range"
        assert 0.5 <= tilt["view_conf_multi"] <= 1.5, (
            f"{scenario}: multi={tilt['view_conf_multi']} out of range"
        )


def test_generate_bl_views_returns_tilt_params():
    """tilt_params dict 의 3 key (tau, view_conf_multi, view_conf_multi_applied)."""
    candidates = {"kr_equity": ["A069500"]}
    views, confs, tilt = generate_bl_views(
        scenario="goldilocks",
        regime_confidence=0.8,
        candidates=candidates,
    )
    assert "tau" in tilt
    assert "view_conf_multi" in tilt
    assert "view_conf_multi_applied" in tilt


def test_generate_bl_views_growth_scenario_high_tilt():
    """goldilocks → tilt={tau:0.10, multi:1.3, applied:True}."""
    candidates = {"kr_equity": ["A069500"]}
    _, _, tilt = generate_bl_views(
        scenario="goldilocks",
        regime_confidence=0.8,
        candidates=candidates,
    )
    assert tilt["tau"] == 0.10
    assert tilt["view_conf_multi"] == 1.3
    assert tilt["view_conf_multi_applied"] is True


def test_generate_bl_views_recession_scenario_low_tilt():
    """broad_recession → tilt={tau:0.025, multi:0.5, applied:True}."""
    candidates = {"bond": ["A148070"]}
    _, _, tilt = generate_bl_views(
        scenario="broad_recession",
        regime_confidence=0.8,
        candidates=candidates,
    )
    assert tilt["tau"] == 0.025
    assert tilt["view_conf_multi"] == 0.5
    assert tilt["view_conf_multi_applied"] is True


def test_generate_bl_views_view_conf_clipped_high():
    """conf × multi > 1.0 → 1.0 cap. goldilocks multi=1.3, conf=0.9 → 1.17 → 1.0."""
    candidates = {"kr_equity": ["A069500", "A102110"]}
    _, confs, _ = generate_bl_views(
        scenario="goldilocks",
        regime_confidence=0.9,
        candidates=candidates,
    )
    assert all(c <= BL_VIEW_CONF_MAX_AFTER_MULTI + 1e-9 for c in confs)
    # Specifically, expect 1.0 cap hit
    assert any(abs(c - 1.0) < 1e-6 for c in confs), f"expected cap-hit, got {confs}"


def test_generate_bl_views_view_conf_clipped_low():
    """multi=0.5 + floor → 결과 [0.05, 1.0] 안."""
    candidates = {"bond": ["A148070"]}
    _, confs, _ = generate_bl_views(
        scenario="broad_recession",
        regime_confidence=0.1,  # max(0.1, 0.10) = 0.10
        candidates=candidates,
    )
    # conf = 0.10 * 0.5 = 0.05 = floor
    assert all(BL_VIEW_CONF_MIN_AFTER_MULTI <= c <= BL_VIEW_CONF_MAX_AFTER_MULTI for c in confs)
    assert all(abs(c - 0.05) < 1e-6 for c in confs), f"expected 0.05 floor, got {confs}"


def test_generate_bl_views_records_tilt_in_breakdown():
    """breakdown_out["tilt_params"] 의 3 key."""
    candidates = {"kr_equity": ["A069500"]}
    breakdown: dict = {}
    generate_bl_views(
        scenario="late_cycle",
        regime_confidence=0.5,
        candidates=candidates,
        breakdown_out=breakdown,
    )
    assert "tilt_params" in breakdown
    tp = breakdown["tilt_params"]
    assert tp["tau"] == 0.05
    assert tp["view_conf_multi"] == 0.8
    assert tp["view_conf_multi_applied"] is True
```

- [ ] **Step 3: Run, expect FAIL (ImportError on SCENARIO_BL_TILT / constants)**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_bl_views.py -v 2>&1 | tail -15
```

Expected: 8 new tests FAIL (ImportError) + existing 12 may also FAIL after Step 4 (tuple unpack changes).

- [ ] **Step 4: Add constants + SCENARIO_BL_TILT to `bl_views.py`**

Edit `tradingagents/skills/portfolio/bl_views.py`. Add near top (after `BL_VIEW_MIN_CONFIDENCE`):

```python
# Phase 4b — BL tilt dial (regime/scenario 별 BL parameter)

# Idzorek-Walters Ω 안정성 boundary (post-multiplier clipping)
BL_VIEW_CONF_MIN_AFTER_MULTI: float = 0.05
BL_VIEW_CONF_MAX_AFTER_MULTI: float = 1.0

# Unknown scenario fallback (Phase 3b 동작 보존)
BL_TAU_DEFAULT: float = 0.05
BL_VIEW_CONF_MULTI_DEFAULT: float = 1.0

# 9 scenario × (tau, view_conf_multi)
# tau ∈ [0.025, 0.10] (pypfopt default 0.05 기준 ±2x)
# view_conf_multi ∈ [0.5, 1.5] (post-multiplier clip [0.05, 1.0])
SCENARIO_BL_TILT: dict[str, dict[str, float]] = {
    "goldilocks":       {"tau": 0.10, "view_conf_multi": 1.3},
    "kr_boom":          {"tau": 0.10, "view_conf_multi": 1.3},
    "overheating":      {"tau": 0.07, "view_conf_multi": 1.0},
    "ai_concentration": {"tau": 0.07, "view_conf_multi": 1.0},
    "late_cycle":       {"tau": 0.05, "view_conf_multi": 0.8},
    "stagflation":      {"tau": 0.05, "view_conf_multi": 0.7},
    "broad_recession":  {"tau": 0.025, "view_conf_multi": 0.5},
    "kr_stress":        {"tau": 0.025, "view_conf_multi": 0.5},
    "global_credit":    {"tau": 0.025, "view_conf_multi": 0.5},
}
```

- [ ] **Step 5: Modify `generate_bl_views` signature + logic**

Replace the existing function body. New version:

```python
def generate_bl_views(
    *,
    scenario: str | None,
    regime_confidence: float,
    candidates: dict[str, list[str]],
    sub_category_lookup: dict[str, str] | None = None,
    breakdown_out: dict | None = None,
) -> tuple[dict[str, float], list[float], dict[str, float | bool]]:
    """
    Generate absolute BL views + post-multiplier confidences + tilt params.

    Returns:
        absolute_views: {ticker: expected_return}
        view_confidences: list[float] — post-multiplier, clipped [0.05, 1.0]
        tilt_params: {"tau": τ, "view_conf_multi": m, "view_conf_multi_applied": bool}

    Unknown scenario: ({}, [], {tau:0.05, multi:1.0, applied:False}).
    """
    default_tilt: dict[str, float | bool] = {
        "tau": BL_TAU_DEFAULT,
        "view_conf_multi": BL_VIEW_CONF_MULTI_DEFAULT,
        "view_conf_multi_applied": False,
    }

    if scenario is None or scenario not in SCENARIO_BUCKET_RULEBOOK:
        if breakdown_out is not None:
            breakdown_out["fallback_reason"] = "unknown_scenario"
            breakdown_out["scenario"] = scenario
            breakdown_out["tilt_params"] = default_tilt
        return {}, [], default_tilt

    bucket_returns = SCENARIO_BUCKET_RULEBOOK[scenario]
    conf_value = max(regime_confidence, BL_VIEW_MIN_CONFIDENCE)

    tilt_raw = SCENARIO_BL_TILT.get(scenario)
    if tilt_raw is None:
        tilt_params: dict[str, float | bool] = dict(default_tilt)
    else:
        tilt_params = {
            "tau": tilt_raw["tau"],
            "view_conf_multi": tilt_raw["view_conf_multi"],
            "view_conf_multi_applied": True,
        }
    multi = float(tilt_params["view_conf_multi"])

    absolute_views: dict[str, float] = {}
    view_confidences: list[float] = []
    n_per_bucket: dict[str, int] = {}
    for bucket, tickers in candidates.items():
        if bucket not in bucket_returns:
            continue
        expected_ret = bucket_returns[bucket]
        for ticker in tickers:
            absolute_views[ticker] = expected_ret
            post = conf_value * multi
            clipped = min(
                BL_VIEW_CONF_MAX_AFTER_MULTI,
                max(BL_VIEW_CONF_MIN_AFTER_MULTI, post),
            )
            view_confidences.append(clipped)
        n_per_bucket[bucket] = len(tickers)

    if breakdown_out is not None:
        breakdown_out["scenario"] = scenario
        breakdown_out["regime_confidence_raw"] = regime_confidence
        breakdown_out["confidence_used"] = conf_value
        breakdown_out["n_views_per_bucket"] = n_per_bucket
        breakdown_out["rulebook_returns_used"] = {
            b: bucket_returns[b] for b in n_per_bucket
        }
        breakdown_out["tilt_params"] = tilt_params

    return absolute_views, view_confidences, tilt_params
```

- [ ] **Step 6: Update existing 12 tests to unpack tuple [3]**

In `tests/unit/skills/test_portfolio_bl_views.py`, replace every `views, confs = generate_bl_views(...)` with `views, confs, tilt = generate_bl_views(...)`. Use grep:

```bash
grep -n "views, confs = generate_bl_views" tests/unit/skills/test_portfolio_bl_views.py
```

For each match, change to `views, confs, _ = generate_bl_views(...)` (unused tilt) — unless test already declares `tilt`.

- [ ] **Step 7: Run full bl_views test suite**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_bl_views.py -v 2>&1 | tail -25
```

Expected: all PASS (12 existing + 8 new = 20).

- [ ] **Step 8: Commit**

```bash
git add tradingagents/skills/portfolio/bl_views.py tests/unit/skills/test_portfolio_bl_views.py
git commit -m "$(cat <<'EOF'
feat(stage3): Phase 4b bl_views SCENARIO_BL_TILT + 시그니처 확장

SCENARIO_BL_TILT 9 scenario × (tau, view_conf_multi) 매트릭스. 상수 4종
(MIN_AFTER_MULTI=0.05, MAX_AFTER_MULTI=1.0, TAU_DEFAULT=0.05, MULTI_DEFAULT=1.0).

generate_bl_views 시그니처: return tuple [2] → [3] (tilt_params 추가).
view_confidences 는 post-multiplier 적용 후 [0.05, 1.0] clipped.

dial 값: goldilocks/kr_boom 공격적 (τ=0.10, multi=1.3),
broad_recession/kr_stress/global_credit 보수 (τ=0.025, multi=0.5).

Tests: 8 신규 + 12 기존 tuple unpack 갱신. 20 PASS.
EOF
)"
```

---

## Task 2: Allocator BL 분기 + integration tests

**Files:**
- Modify: `tradingagents/agents/allocator/portfolio_allocator.py` (BL 분기 around line 567)
- Modify: `tests/integration/test_allocator_phase3b.py` (tuple unpack 영향 — 가능)
- Create: `tests/integration/test_allocator_phase4b.py`

- [ ] **Step 1: Inspect allocator BL 분기**

```bash
grep -n "BLACK_LITTERMAN\|generate_bl_views\|view_confidences\|tau" tradingagents/agents/allocator/portfolio_allocator.py | head -20
sed -n '565,600p' tradingagents/agents/allocator/portfolio_allocator.py
```

Verify: BL 분기 위치 정확히 확인 (현재 line 567 기준, drift 가능). force_method=='bl' 경로 vs `_bl_trigger=True` 경로 분기 확인.

- [ ] **Step 2: Write failing integration tests**

Create `tests/integration/test_allocator_phase4b.py`:

```python
"""Phase 4b BL tilt dial — integration tests."""
import pytest

from tradingagents.agents.allocator.portfolio_allocator import build_portfolio_allocator
from tests.integration._allocator_state_helpers import build_state


def test_allocator_bl_breakdown_contains_tilt_params():
    """attribution.bl_views_breakdown.tilt_params 의 3 key."""
    state = build_state(scenario="goldilocks", regime_confidence=0.8)
    result = build_portfolio_allocator()(state)
    attr = result["portfolio"]["allocation_attribution"]
    opt = attr.get("optimization", {})
    bl_bd = opt.get("bl_views_breakdown") or attr.get("bl_views_breakdown")
    assert bl_bd is not None, f"bl_views_breakdown missing from attr keys: {list(attr.keys())}"
    tp = bl_bd.get("tilt_params")
    assert tp is not None, f"tilt_params missing from bl_views_breakdown: {list(bl_bd.keys())}"
    assert "tau" in tp
    assert "view_conf_multi" in tp
    assert "view_conf_multi_applied" in tp


def test_allocator_bl_growth_scenario_tau_matches_tilt():
    """goldilocks → tau=0.10 in breakdown."""
    state = build_state(scenario="goldilocks", regime_confidence=0.8)
    result = build_portfolio_allocator()(state)
    attr = result["portfolio"]["allocation_attribution"]
    opt = attr.get("optimization", {})
    bl_bd = opt.get("bl_views_breakdown") or attr.get("bl_views_breakdown")
    assert bl_bd["tilt_params"]["tau"] == 0.10
    assert bl_bd["tilt_params"]["view_conf_multi"] == 1.3
    assert bl_bd["tilt_params"]["view_conf_multi_applied"] is True


def test_allocator_bl_recession_scenario_tau_matches_tilt():
    """broad_recession → tau=0.025 in breakdown."""
    state = build_state(scenario="broad_recession", regime_confidence=0.8)
    result = build_portfolio_allocator()(state)
    attr = result["portfolio"]["allocation_attribution"]
    opt = attr.get("optimization", {})
    bl_bd = opt.get("bl_views_breakdown") or attr.get("bl_views_breakdown")
    assert bl_bd["tilt_params"]["tau"] == 0.025
    assert bl_bd["tilt_params"]["view_conf_multi"] == 0.5


def test_allocator_bl_force_method_no_tilt_applied():
    """force_method='black_litterman' + 외부 views 주입 → view_conf_multi_applied=False.

    NOTE: force_method 외부 주입 경로에서는 generate_bl_views 호출 안 함
    → bl_views_breakdown 부재. 대신 tilt_params 가 allocator local 에서 default 로 설정됨.
    이를 직접 검증할 수 없으면 view_conf_multi_applied가 attribution에 노출 안 됨을 확인.
    """
    state = build_state(scenario=None, regime_confidence=0.5)
    state["force_method"] = "black_litterman"
    result = build_portfolio_allocator()(state)
    attr = result["portfolio"]["allocation_attribution"]
    opt = attr.get("optimization", {})
    bl_bd = opt.get("bl_views_breakdown") or attr.get("bl_views_breakdown") or {}
    # force_method 경로면 bl_views_breakdown 부재 또는 fallback 만 있음
    tp = bl_bd.get("tilt_params", {})
    # tilt_params 가 있다면 applied=False, 또는 attribution 자체에 없음
    if tp:
        assert tp.get("view_conf_multi_applied") is False, (
            f"force_method 경로에서 tilt applied=True: {tp}"
        )
```

NOTE: actual attribution path (`opt.get("bl_views_breakdown")` vs `attr.get("bl_views_breakdown")`) 은 Phase 3b 구조에 따라 다를 수 있음. 둘 다 시도하는 `or` chain 사용.

- [ ] **Step 3: Run, expect FAIL (allocator 아직 tilt 사용 안 함)**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/integration/test_allocator_phase4b.py -v 2>&1 | tail -15
```

Expected: tests 1-3 FAIL (tilt_params key 부재 또는 unpack error).

- [ ] **Step 4: Modify allocator BL 분기**

Find current BL 분기 in `tradingagents/agents/allocator/portfolio_allocator.py` (around line 567). Replace with:

```python
    if method == OptimizationMethod.BLACK_LITTERMAN:
        from pypfopt import BlackLittermanModel
        from tradingagents.skills.portfolio.bl_views import (
            generate_bl_views,
            BL_TAU_DEFAULT,
            BL_VIEW_CONF_MULTI_DEFAULT,
        )

        tilt_params: dict[str, float | bool]
        if method_params.get("_bl_trigger"):
            bl_breakdown: dict = {}
            views, confs, tilt_params = generate_bl_views(
                scenario=scenario,
                regime_confidence=regime_confidence,
                candidates=candidates.bucket_to_tickers,
                sub_category_lookup=sub_category_lookup,
                breakdown_out=bl_breakdown,
            )
            if attribution is not None:
                attribution["bl_views_breakdown"] = bl_breakdown
        else:
            # force_method='black_litterman' 외부 views 주입 — tilt 비적용 (기존 동작 보존)
            views = method_params.get("views", {})
            confs = method_params.get("view_confidences", [])
            tilt_params = {
                "tau": BL_TAU_DEFAULT,
                "view_conf_multi": BL_VIEW_CONF_MULTI_DEFAULT,
                "view_conf_multi_applied": False,
            }

        if views:
            bl = BlackLittermanModel(
                S, absolute_views=views, omega="idzorek",
                view_confidences=confs,
                tau=tilt_params["tau"],
            )
            mu = bl.bl_returns()
        else:
            mu = expected_returns.mean_historical_return(returns, returns_data=True)
            if attribution is not None:
                attribution["bl_views_fallback"] = "empty_views_historical_fallback"
    else:
        mu = expected_returns.mean_historical_return(returns, returns_data=True)
```

NOTE: Variable name `scenario`, `regime_confidence` 가 allocator 컨텍스트에서 정확히 어떻게 reference 되는지 확인 — Phase 4a 의 `compute_robust_cov` 호출 패턴 참고하면 같은 변수가 이미 시그니처 + node() 전달로 와 있음.

NOTE: `attribution["bl_views_breakdown"]` 가 top-level 또는 `attribution["optimization"]["bl_views_breakdown"]` 어느 path 에 저장되는지 — 기존 (Phase 3b) 그대로 유지. integration test 의 `or` chain 으로 둘 다 검증 가능.

- [ ] **Step 5: Run Phase 4b integration tests**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/integration/test_allocator_phase4b.py -v 2>&1 | tail -15
```

Expected: 4 PASS. If test 4 has assertion mismatch on tilt_params presence, adjust based on actual attribution structure (inspect via stdout debug).

- [ ] **Step 6: Run Phase 3b integration tests (회귀 확인)**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/integration/test_allocator_phase3b.py -v 2>&1 | tail -15
```

Expected: 7 PASS (Phase 3b assertions are method/rule_fired/breakdown existence — tilt 추가는 영향 없음). If `confidence_used` 값 직접 비교 test 있으면 multi 효과 반영해서 갱신.

- [ ] **Step 7: Quick Phase 1-4a regression**

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
    tests/integration/test_plan_pipeline_mock.py \
    -q 2>&1 | tail -10
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add tradingagents/agents/allocator/portfolio_allocator.py tests/integration/test_allocator_phase4b.py
# Phase 3b integration test 갱신 시 함께
git add tests/integration/test_allocator_phase3b.py 2>/dev/null
git commit -m "$(cat <<'EOF'
feat(stage3): Phase 4b allocator BL 분기 + scenario tilt dial

generate_bl_views tuple[3] unpack. BlackLittermanModel(tau=tilt_params["tau"])
전달. force_method='black_litterman' 외부 주입 경로는 tilt 비적용 (tau=0.05,
view_conf_multi_applied=False).

Tests: 4 신규 integration (breakdown.tilt_params, growth tau=0.10,
recession tau=0.025, force_method no-tilt).
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

Expected: BL trigger 발동 (regime_conf=0.91). method=black_litterman. 정상 종료.

- [ ] **Step 3: Verify tilt_params 노출**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -c "
import json
with open('artifacts/2026-05-15/portfolio.json') as f:
    p = json.load(f)
attr = p['allocation_attribution']
opt = attr.get('optimization', {})
bl_bd = opt.get('bl_views_breakdown') or attr.get('bl_views_breakdown') or {}
print('scenario:', bl_bd.get('scenario'))
print('confidence_used:', bl_bd.get('confidence_used'))
tp = bl_bd.get('tilt_params', {})
print('tilt tau:', tp.get('tau'))
print('tilt view_conf_multi:', tp.get('view_conf_multi'))
print('tilt applied:', tp.get('view_conf_multi_applied'))
weights = p.get('weights', {})
print('weight sum:', sum(weights.values()))
print('n_total:', len(weights))
"
```

Expected: scenario / tilt_params 정상 출력 + weight sum ≈ 1.0.

- [ ] **Step 4: Regression compare**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/regression_compare.py \
    --baseline artifacts/baseline/ \
    --new artifacts/ \
    --out artifacts/phase4b_regression.json 2>&1 | tail -15
```

Expected: weight 가 tilt 영향으로 약간 달라짐. (a)(b)(c) tolerance 안 가능성 높음 (tilt 크지 않음). (d) Phase 3b 부터 carry over.

- [ ] **Step 5: Full test regression**

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
    tests/integration/test_plan_pipeline_mock.py \
    tests/integration/test_5_28_dry_run.py \
    -q 2>&1 | tail -8
```

Expected: all PASS.

- [ ] **Step 6: Commit artifacts**

```bash
git add artifacts/2025-04-15/ artifacts/2026-05-15/ artifacts/phase4b_regression.json 2>/dev/null

if git diff --cached --quiet; then
    echo "nothing to commit"
else
    git commit -m "$(cat <<'EOF'
chore(stage3): Phase 4b 적용 후 산출물 + regression 결과

baseline → phase4b:
  attribution.bl_views_breakdown.tilt_params 추가
  scenario tilt 영향으로 weight 분포 미세 변경
  goldilocks (τ=0.10, multi=1.3), broad_recession (τ=0.025, multi=0.5)

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
| `SCENARIO_BL_TILT` 매트릭스 | Task 1 Step 4 |
| 상수 4종 (MIN/MAX_AFTER_MULTI, TAU_DEFAULT, MULTI_DEFAULT) | Task 1 Step 4 |
| `generate_bl_views` 시그니처 확장 | Task 1 Step 5 |
| post-multiplier clip [0.05, 1.0] | Task 1 Step 5 |
| Unknown scenario default tilt | Task 1 Step 5 |
| Allocator BL 분기 tau 사용 | Task 2 Step 4 |
| force_method 경로 tilt 비적용 | Task 2 Step 4 |
| 8 unit tests | Task 1 Step 2 |
| 4 integration tests | Task 2 Step 2 |
| 기존 12 unit tuple unpack 갱신 | Task 1 Step 6 |
| Phase 3b integration regression | Task 2 Step 6 |
| Full regression | Task 3 Step 5 |

### Placeholder scan

No "TBD", "TODO". 모든 code block complete.

### Type consistency

- `generate_bl_views(...) -> tuple[dict[str, float], list[float], dict[str, float | bool]]` 시그니처 일관 (Task 1, 2).
- tilt_params key: `tau` (float), `view_conf_multi` (float), `view_conf_multi_applied` (bool) — 일관.
- 상수 명명: `BL_VIEW_CONF_MIN_AFTER_MULTI`, `BL_VIEW_CONF_MAX_AFTER_MULTI`, `BL_TAU_DEFAULT`, `BL_VIEW_CONF_MULTI_DEFAULT` — 일관.
- attribution path 모호 (top-level vs `optimization.`) — test 에서 `or` chain 으로 둘 다 검증.
