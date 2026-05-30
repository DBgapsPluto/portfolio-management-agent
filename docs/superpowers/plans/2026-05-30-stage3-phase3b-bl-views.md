# Stage 3 Phase 3b — Black-Litterman Views Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stage 2 의 `scenario` + `regime_confidence` 에서 BL views 를 결정적으로 생성하는 adapter (`bl_views.py`) 신규 + `method_picker` BL trigger rule + `portfolio_allocator` BL 분기 활성화.

**Architecture:** `bl_views.py` 가 `SCENARIO_BUCKET_RULEBOOK` (9 scenario × 5 bucket) 에서 `(absolute_views, view_confidences)` 를 생성. `method_picker` 는 `regime_confidence ≥ 0.7` + known scenario 시 `_bl_trigger=True` sentinel 만 출력. `portfolio_allocator` BL 분기가 sentinel 보고 adapter 호출.

**Tech Stack:** Python 3.13, pypfopt (BlackLittermanModel + omega="idzorek"), pytest, Pydantic.

**Test runner:** `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest`

---

## Task 1: bl_views 모듈 skeleton + RULEBOOK 상수

**Files:**
- Create: `tradingagents/skills/portfolio/bl_views.py`
- Test: `tests/unit/skills/test_portfolio_bl_views.py`

- [ ] **Step 1: Write the failing rulebook tests**

Add to `tests/unit/skills/test_portfolio_bl_views.py`:

```python
"""Unit tests for Phase 3b BL views adapter."""
import math
import pytest

from tradingagents.skills.portfolio.bl_views import (
    SCENARIO_BUCKET_RULEBOOK,
    BL_VIEW_MIN_CONFIDENCE,
)
from tradingagents.skills.portfolio.method_picker import _SCENARIO_METHOD


def test_rulebook_covers_all_scenarios():
    """RULEBOOK 의 key 가 method_picker._SCENARIO_METHOD key 와 정확히 일치."""
    assert set(SCENARIO_BUCKET_RULEBOOK.keys()) == set(_SCENARIO_METHOD.keys())


def test_rulebook_returns_finite_decimals():
    """모든 cell finite, |ret| ≤ 0.30."""
    for scenario, bucket_returns in SCENARIO_BUCKET_RULEBOOK.items():
        for bucket, ret in bucket_returns.items():
            assert math.isfinite(ret), f"{scenario}/{bucket}: {ret} not finite"
            assert -0.30 <= ret <= 0.30, f"{scenario}/{bucket}: {ret} out of range"


def test_rulebook_has_all_5_buckets():
    """모든 scenario 가 5 bucket 모두 포함."""
    expected_buckets = {"kr_equity", "global_equity", "fx_commodity", "bond", "cash_mmf"}
    for scenario, bucket_returns in SCENARIO_BUCKET_RULEBOOK.items():
        assert set(bucket_returns.keys()) == expected_buckets, scenario


def test_min_confidence_floor_is_positive():
    """confidence floor 가 0 보다 크고 1 미만."""
    assert 0.0 < BL_VIEW_MIN_CONFIDENCE < 1.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_bl_views.py -v 2>&1 | tail -10
```

Expected: ImportError — module `tradingagents.skills.portfolio.bl_views` not found.

- [ ] **Step 3: Create bl_views.py skeleton with RULEBOOK + floor constant**

Create `tradingagents/skills/portfolio/bl_views.py`:

```python
"""
Phase 3b: Black-Litterman views adapter.

Generates absolute BL views (P, Q) and view_confidences from Stage 2 scenario +
regime_confidence using a deterministic rulebook (no LLM).

Used by portfolio_allocator BL branch when method_picker outputs BLACK_LITTERMAN
with params={"_bl_trigger": True}, or when state["force_method"]="black_litterman".
"""
from __future__ import annotations

# 9 scenario × 5 bucket → annualized expected return (decimal).
# scenario keys MUST equal method_picker._SCENARIO_METHOD keys (test enforced).
# cash_mmf ≈ KOFR floor (2.5%). Returns capped at |0.30| (test enforced).
SCENARIO_BUCKET_RULEBOOK: dict[str, dict[str, float]] = {
    "goldilocks":       {"kr_equity": 0.10, "global_equity": 0.12,
                         "fx_commodity": 0.02, "bond": 0.04,  "cash_mmf": 0.025},
    "overheating":      {"kr_equity": 0.06, "global_equity": 0.08,
                         "fx_commodity": 0.10, "bond": 0.02,  "cash_mmf": 0.025},
    "late_cycle":       {"kr_equity": 0.02, "global_equity": 0.04,
                         "fx_commodity": 0.08, "bond": 0.06,  "cash_mmf": 0.025},
    "stagflation":      {"kr_equity": -0.05, "global_equity": -0.03,
                         "fx_commodity": 0.12, "bond": 0.01,  "cash_mmf": 0.025},
    "broad_recession":  {"kr_equity": -0.08, "global_equity": -0.05,
                         "fx_commodity": -0.02, "bond": 0.08, "cash_mmf": 0.025},
    "kr_stress":        {"kr_equity": -0.10, "global_equity": 0.05,
                         "fx_commodity": 0.03, "bond": 0.05,  "cash_mmf": 0.025},
    "global_credit":    {"kr_equity": -0.05, "global_equity": -0.08,
                         "fx_commodity": -0.02, "bond": 0.07, "cash_mmf": 0.025},
    "ai_concentration": {"kr_equity": 0.05, "global_equity": 0.10,
                         "fx_commodity": 0.02, "bond": 0.03,  "cash_mmf": 0.025},
    "kr_boom":          {"kr_equity": 0.13, "global_equity": 0.08,
                         "fx_commodity": 0.02, "bond": 0.03,  "cash_mmf": 0.025},
}

# Idzorek-Walters Ω 가 numerically 안정하려면 view confidence > 0 이어야 함.
BL_VIEW_MIN_CONFIDENCE: float = 0.10
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_bl_views.py -v 2>&1 | tail -10
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/portfolio/bl_views.py tests/unit/skills/test_portfolio_bl_views.py
git commit -m "feat(stage3): Phase 3b BL views 모듈 skeleton + SCENARIO_BUCKET_RULEBOOK

9 scenario × 5 bucket annualized expected return matrix. method_picker
_SCENARIO_METHOD key 와 일치 검증. BL_VIEW_MIN_CONFIDENCE=0.10."
```

---

## Task 2: `generate_bl_views` 기본 동작 (known scenario)

**Files:**
- Modify: `tradingagents/skills/portfolio/bl_views.py`
- Modify: `tests/unit/skills/test_portfolio_bl_views.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/skills/test_portfolio_bl_views.py`:

```python
from tradingagents.skills.portfolio.bl_views import generate_bl_views


def test_generate_bl_views_known_scenario_basic():
    """scenario=goldilocks → bucket 별 ticker 모두 rulebook 값."""
    candidates = {
        "kr_equity":     ["A069500", "A102110"],
        "global_equity": ["A360750"],
        "bond":          ["A148070"],
        "cash_mmf":      ["A130730"],
    }
    views, confs = generate_bl_views(
        scenario="goldilocks",
        regime_confidence=0.8,
        candidates=candidates,
    )
    assert views["A069500"] == 0.10
    assert views["A102110"] == 0.10
    assert views["A360750"] == 0.12
    assert views["A148070"] == 0.04
    assert views["A130730"] == 0.025
    assert len(views) == 5
    assert len(confs) == 5
    assert all(c == 0.8 for c in confs)


def test_generate_bl_views_records_breakdown():
    """breakdown_out 의 모든 키 + 값."""
    candidates = {"kr_equity": ["A069500"], "bond": ["A148070", "A114260"]}
    breakdown: dict = {}
    views, confs = generate_bl_views(
        scenario="late_cycle",
        regime_confidence=0.75,
        candidates=candidates,
        breakdown_out=breakdown,
    )
    assert breakdown["scenario"] == "late_cycle"
    assert breakdown["regime_confidence_raw"] == 0.75
    assert breakdown["confidence_used"] == 0.75
    assert breakdown["n_views_per_bucket"] == {"kr_equity": 1, "bond": 2}
    assert breakdown["rulebook_returns_used"] == {
        "kr_equity": 0.02, "bond": 0.06,
    }


def test_generate_bl_views_ticker_returns_match_bucket_rulebook():
    """bucket 의 모든 ticker 가 같은 rulebook 값을 받음."""
    candidates = {"kr_equity": ["A1", "A2", "A3"]}
    views, _ = generate_bl_views(
        scenario="kr_boom",
        regime_confidence=0.8,
        candidates=candidates,
    )
    assert views["A1"] == views["A2"] == views["A3"] == 0.13
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_bl_views.py -v 2>&1 | tail -15
```

Expected: 3 new tests FAIL (ImportError on `generate_bl_views`).

- [ ] **Step 3: Implement `generate_bl_views`**

Append to `tradingagents/skills/portfolio/bl_views.py`:

```python
def generate_bl_views(
    *,
    scenario: str | None,
    regime_confidence: float,
    candidates: dict[str, list[str]],
    sub_category_lookup: dict[str, str] | None = None,
    breakdown_out: dict | None = None,
) -> tuple[dict[str, float], list[float]]:
    """
    Generate absolute Black-Litterman views from rulebook.

    Each ticker in bucket B gets SCENARIO_BUCKET_RULEBOOK[scenario][B] as its
    absolute view return. Each view's confidence = max(regime_confidence,
    BL_VIEW_MIN_CONFIDENCE).

    Returns ({}, []) when scenario unknown to rulebook — caller should fall
    back to historical mu.

    Args:
        scenario: Stage 2 dominant_scenario string.
        regime_confidence: Stage 1 regime confidence ∈ [0, 1].
        candidates: dict[bucket → list[ticker]] from Phase 2b ENB greedy.
        sub_category_lookup: optional reverse lookup (unused in current impl,
            kept for parity with allocator helpers).
        breakdown_out: optional dict to receive trace (scenario, n_views,
            rulebook_returns_used, ...).
    """
    if scenario is None or scenario not in SCENARIO_BUCKET_RULEBOOK:
        if breakdown_out is not None:
            breakdown_out["fallback_reason"] = "unknown_scenario"
            breakdown_out["scenario"] = scenario
        return {}, []

    bucket_returns = SCENARIO_BUCKET_RULEBOOK[scenario]
    conf_value = max(regime_confidence, BL_VIEW_MIN_CONFIDENCE)

    absolute_views: dict[str, float] = {}
    view_confidences: list[float] = []
    n_per_bucket: dict[str, int] = {}
    for bucket, tickers in candidates.items():
        if bucket not in bucket_returns:
            continue  # bucket-agnostic: rulebook 미정의 bucket skip
        expected_ret = bucket_returns[bucket]
        for ticker in tickers:
            absolute_views[ticker] = expected_ret
            view_confidences.append(conf_value)
        n_per_bucket[bucket] = len(tickers)

    if breakdown_out is not None:
        breakdown_out["scenario"] = scenario
        breakdown_out["regime_confidence_raw"] = regime_confidence
        breakdown_out["confidence_used"] = conf_value
        breakdown_out["n_views_per_bucket"] = n_per_bucket
        breakdown_out["rulebook_returns_used"] = {
            b: bucket_returns[b] for b in n_per_bucket
        }

    return absolute_views, view_confidences
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_bl_views.py -v 2>&1 | tail -10
```

Expected: 7 passed (4 from Task 1 + 3 new).

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/portfolio/bl_views.py tests/unit/skills/test_portfolio_bl_views.py
git commit -m "feat(stage3): generate_bl_views 기본 동작 (known scenario)

bucket 내 모든 ticker 에 rulebook 값 부여. confidence = max(regime_conf, floor).
breakdown_out 에 scenario, n_views_per_bucket, rulebook_returns_used 기록."
```

---

## Task 3: `generate_bl_views` edge cases

**Files:**
- Modify: `tests/unit/skills/test_portfolio_bl_views.py`

- [ ] **Step 1: Write the failing edge case tests**

Append to `tests/unit/skills/test_portfolio_bl_views.py`:

```python
def test_generate_bl_views_unknown_scenario_returns_empty():
    """scenario unknown → ({}, []), fallback_reason 기록."""
    breakdown: dict = {}
    views, confs = generate_bl_views(
        scenario="xyz_unknown",
        regime_confidence=0.8,
        candidates={"kr_equity": ["A069500"]},
        breakdown_out=breakdown,
    )
    assert views == {}
    assert confs == []
    assert breakdown["fallback_reason"] == "unknown_scenario"
    assert breakdown["scenario"] == "xyz_unknown"


def test_generate_bl_views_none_scenario_returns_empty():
    """scenario=None → ({}, []), fallback_reason 기록."""
    breakdown: dict = {}
    views, confs = generate_bl_views(
        scenario=None,
        regime_confidence=0.8,
        candidates={"kr_equity": ["A069500"]},
        breakdown_out=breakdown,
    )
    assert views == {}
    assert confs == []
    assert breakdown["fallback_reason"] == "unknown_scenario"


def test_generate_bl_views_confidence_floor():
    """regime_confidence=0.05 → BL_VIEW_MIN_CONFIDENCE=0.10 floor."""
    views, confs = generate_bl_views(
        scenario="goldilocks",
        regime_confidence=0.05,
        candidates={"kr_equity": ["A069500"]},
    )
    assert confs[0] == BL_VIEW_MIN_CONFIDENCE


def test_generate_bl_views_bucket_agnostic():
    """candidates 에 rulebook 미정의 bucket → skip."""
    candidates = {
        "kr_equity":     ["A069500"],
        "alt_realestate": ["AXYZ"],  # 9-bucket 확장 가정, rulebook 미정의
        "bond":          ["A148070"],
    }
    breakdown: dict = {}
    views, confs = generate_bl_views(
        scenario="goldilocks",
        regime_confidence=0.8,
        candidates=candidates,
        breakdown_out=breakdown,
    )
    assert "A069500" in views
    assert "A148070" in views
    assert "AXYZ" not in views
    assert "alt_realestate" not in breakdown["n_views_per_bucket"]


def test_generate_bl_views_empty_candidates():
    """candidates={} → ({}, [])."""
    views, confs = generate_bl_views(
        scenario="goldilocks",
        regime_confidence=0.8,
        candidates={},
    )
    assert views == {}
    assert confs == []
```

- [ ] **Step 2: Run tests to verify they pass (impl from Task 2 should cover)**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_bl_views.py -v 2>&1 | tail -15
```

Expected: 12 passed (7 + 5 new).

- [ ] **Step 3: Commit**

```bash
git add tests/unit/skills/test_portfolio_bl_views.py
git commit -m "test(stage3): generate_bl_views edge case 5종

unknown scenario / None scenario / confidence floor / bucket-agnostic /
empty candidates 모두 통과 (Task 2 impl 그대로)."
```

---

## Task 4: method_picker BL trigger rule

**Files:**
- Modify: `tradingagents/skills/portfolio/method_picker.py`
- Modify: `tests/unit/skills/test_method_picker.py`

- [ ] **Step 1: Inspect existing method_picker test file**

```bash
grep -n "def test_\|rule_index\|rule_fired" tests/unit/skills/test_method_picker.py 2>&1 | head -30
ls tests/unit/skills/test_method_picker.py 2>/dev/null || echo "TEST FILE NOT FOUND — search alternative"
find tests -name "test_method_picker*" 2>&1 | head
```

If file not found, locate it:

```bash
grep -rln "pick_optimization_method" tests/ 2>&1 | head -3
```

Use the discovered path going forward.

- [ ] **Step 2: Write the failing BL picker tests**

Append to discovered test file (default `tests/unit/skills/test_method_picker.py`):

```python
from tradingagents.skills.portfolio.method_picker import (
    pick_optimization_method,
    BL_TRIGGER_CONFIDENCE,
)
from tradingagents.schemas.portfolio import OptimizationMethod


def test_picker_bl_trigger_high_confidence_known_scenario():
    """regime_confidence ≥ threshold + known scenario → BLACK_LITTERMAN."""
    choice = pick_optimization_method(
        regime_quadrant="growth_inflation",
        regime_confidence=0.8,
        systemic_score=5.0,
        systemic_regime="neutral",
        dominant_scenario="goldilocks",
        conviction="high",
    )
    assert choice.method == OptimizationMethod.BLACK_LITTERMAN
    assert choice.rule_fired == "bl_high_confidence"
    assert choice.params == {"_bl_trigger": True}


def test_picker_bl_not_triggered_low_confidence():
    """regime_confidence < threshold → scenario_mapping 폴백."""
    choice = pick_optimization_method(
        regime_quadrant="growth_inflation",
        regime_confidence=0.5,
        systemic_score=5.0,
        systemic_regime="neutral",
        dominant_scenario="goldilocks",
        conviction="high",
    )
    assert choice.method != OptimizationMethod.BLACK_LITTERMAN
    assert choice.rule_fired == "scenario_mapping"


def test_picker_bl_not_triggered_no_scenario():
    """scenario=None → BL rule skip, regime rule 진행."""
    choice = pick_optimization_method(
        regime_quadrant="growth_inflation",
        regime_confidence=0.9,
        systemic_score=5.0,
        systemic_regime="neutral",
        dominant_scenario=None,
        conviction="high",
    )
    assert choice.method != OptimizationMethod.BLACK_LITTERMAN


def test_picker_bl_trigger_precedes_scenario_mapping():
    """rule order regression 가드: BL trigger 가 scenario_mapping 보다 먼저."""
    # scenario_mapping[goldilocks] = HRP. BL trigger 조건 만족 시 BL 선택되어야.
    choice = pick_optimization_method(
        regime_quadrant="growth_inflation",
        regime_confidence=BL_TRIGGER_CONFIDENCE,
        systemic_score=5.0,
        systemic_regime="neutral",
        dominant_scenario="goldilocks",
        conviction="high",
    )
    assert choice.method == OptimizationMethod.BLACK_LITTERMAN
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_method_picker.py -v 2>&1 | tail -15
```

Expected: 4 new FAIL (ImportError on `BL_TRIGGER_CONFIDENCE` or rule not present).

- [ ] **Step 4: Implement method_picker BL rule + rule_index shift**

Edit `tradingagents/skills/portfolio/method_picker.py`:

Add import + constant at module top (near `LOW_CONVICTION_HRP_DOWNGRADE`):

```python
from tradingagents.skills.portfolio.bl_views import SCENARIO_BUCKET_RULEBOOK

BL_TRIGGER_CONFIDENCE: float = 0.7
```

Add the new rule between rule 1 (systemic_extreme) and rule 2 (scenario_mapping).

Find the rule 2 block (currently `# 2. Stage 2 dominant scenario 우선`) and insert BEFORE it:

```python
    # 2. Phase 3b: Black-Litterman trigger — scenario_mapping 보다 먼저 평가.
    if (
        scenario_in
        and regime_confidence >= BL_TRIGGER_CONFIDENCE
        and scenario_in in SCENARIO_BUCKET_RULEBOOK
    ):
        choice = MethodChoice(
            method=OptimizationMethod.BLACK_LITTERMAN,
            reasoning=(
                f"regime_confidence={regime_confidence:.2f} ≥ "
                f"{BL_TRIGGER_CONFIDENCE}, scenario={scenario_in}: "
                f"BL views from rulebook."
            )[:300],
            rule_fired="bl_high_confidence",
            rule_index=2,
            inputs=inputs_trace,
            params={"_bl_trigger": True},
        )
        logger.info(
            "method_picker rule 2 (bl_high_confidence): conf=%.2f scenario=%s → BL",
            regime_confidence, scenario_in,
        )
        return choice
```

Then update rule_index on subsequent rules (+1 each):
- existing rule 2 (scenario_mapping): `rule_index=2` → `rule_index=3`
- existing rule 3 (regime_recession): `rule_index=3` → `rule_index=4`
- existing rule 4 (systemic_risk_off): `rule_index=4` → `rule_index=5`
- existing rule 5 (regime_growth_inflation): `rule_index=5` → `rule_index=6`
- existing rule 6 (default HRP): `rule_index=6` → `rule_index=7`

Use `grep -n "rule_index=" tradingagents/skills/portfolio/method_picker.py` to locate and edit each.

- [ ] **Step 5: Run BL picker tests to verify they pass**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_method_picker.py -v 2>&1 | tail -15
```

Expected: 4 new PASS. Existing tests may FAIL if they hard-code `rule_index` integers — inspect & fix:

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_method_picker.py -v 2>&1 | grep -E "FAIL|rule_index" | head
```

If existing tests use `rule_index == 2` for scenario_mapping, update to `== 3`, etc.

- [ ] **Step 6: Verify full picker test suite + bl_views tests pass**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_method_picker.py tests/unit/skills/test_portfolio_bl_views.py -v 2>&1 | tail -10
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add tradingagents/skills/portfolio/method_picker.py tests/unit/skills/test_method_picker.py
git commit -m "feat(stage3): method_picker BL trigger rule (Phase 3b)

regime_confidence ≥ 0.7 + known scenario → BLACK_LITTERMAN, rule_fired=
bl_high_confidence, params={_bl_trigger: True}. rule_index 2 (scenario_mapping
보다 먼저 평가). 기존 rule 2~6 rule_index +1 shift."
```

---

## Task 5: portfolio_allocator BL 분기 활성화

**Files:**
- Modify: `tradingagents/agents/allocator/portfolio_allocator.py`

- [ ] **Step 1: Inspect current BL branch + caller**

```bash
grep -n "BLACK_LITTERMAN\|_optimize_with_bucket_constraints\|method_params\|scenario\|regime_confidence" tradingagents/agents/allocator/portfolio_allocator.py | head -50
```

Identify:
- Line ~553: `if method == OptimizationMethod.BLACK_LITTERMAN:` (BL branch)
- Line ~477: `def _optimize_with_bucket_constraints(...)` signature
- Line ~324: caller of `_optimize_with_bucket_constraints` (inside `node`)
- node() has `dominant_scenario` (line ~133) and `regime.confidence` (line ~219) available.

- [ ] **Step 2: Add scenario + regime_confidence to `_optimize_with_bucket_constraints` signature**

Edit signature (around line 477):

```python
def _optimize_with_bucket_constraints(
    method: OptimizationMethod,
    returns: pd.DataFrame,
    candidates,
    bucket_target,
    method_params: dict,
    attempts: int,
    sub_category_lookup: dict[str, str | None] | None = None,
    attribution: dict | None = None,
    *,
    scenario: str | None = None,                    # Phase 3b NEW
    regime_confidence: float = 0.5,                 # Phase 3b NEW
) -> tuple[WeightVector, pd.DataFrame]:
```

- [ ] **Step 3: Pass scenario + regime_confidence from caller**

In `node()` around line 324, where `_optimize_with_bucket_constraints` is called, add the two new kwargs:

```python
        wv, sigma_df = _optimize_with_bucket_constraints(
            # ... existing args ...
            sub_category_lookup=sub_category_lookup,
            # Phase 3b: BL views adapter context
            scenario=dominant_scenario,
            regime_confidence=regime.confidence if regime else 0.5,
        )
```

(Use the same expressions that already appear on lines ~219 and ~133 for consistency.)

- [ ] **Step 4: Replace BL branch with sentinel-aware version**

Find BL branch (currently around line 553):

```python
    if method == OptimizationMethod.BLACK_LITTERMAN:
        from pypfopt import BlackLittermanModel
        views = method_params.get("views", {})
        confs = method_params.get("view_confidences", [])
        if views:
            bl = BlackLittermanModel(
                S, absolute_views=views, omega="idzorek", view_confidences=confs,
            )
            mu = bl.bl_returns()
        else:
            mu = expected_returns.mean_historical_return(returns, returns_data=True)
    else:
        mu = expected_returns.mean_historical_return(returns, returns_data=True)
```

Replace with:

```python
    if method == OptimizationMethod.BLACK_LITTERMAN:
        from pypfopt import BlackLittermanModel
        from tradingagents.skills.portfolio.bl_views import generate_bl_views

        if method_params.get("_bl_trigger"):
            bl_breakdown: dict = {}
            views, confs = generate_bl_views(
                scenario=scenario,
                regime_confidence=regime_confidence,
                candidates=candidates,
                sub_category_lookup=sub_category_lookup,
                breakdown_out=bl_breakdown,
            )
            if attribution is not None:
                attribution["bl_views_breakdown"] = bl_breakdown
        else:
            views = method_params.get("views", {})
            confs = method_params.get("view_confidences", [])

        if views:
            bl = BlackLittermanModel(
                S, absolute_views=views, omega="idzorek", view_confidences=confs,
            )
            mu = bl.bl_returns()
        else:
            mu = expected_returns.mean_historical_return(returns, returns_data=True)
            if attribution is not None:
                attribution["bl_views_fallback"] = "empty_views_historical_fallback"
    else:
        mu = expected_returns.mean_historical_return(returns, returns_data=True)
```

- [ ] **Step 5: Run existing allocator unit tests to verify no regression**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/agents/test_portfolio_allocator.py -v 2>&1 | tail -15
```

Expected: all PASS (no behavior change for non-BL methods; BL branch dead code → live code with same external default behavior when `_bl_trigger=False` and no views).

- [ ] **Step 6: Commit**

```bash
git add tradingagents/agents/allocator/portfolio_allocator.py
git commit -m "feat(stage3): portfolio_allocator BL 분기 활성화 (Phase 3b)

_optimize_with_bucket_constraints 시그니처에 scenario + regime_confidence 추가.
BL 분기에서 method_params['_bl_trigger']=True 면 generate_bl_views 호출,
attribution['bl_views_breakdown'] 기록. views 빈 dict 면 historical 폴백
+ attribution['bl_views_fallback'] 기록 (force_method='bl' + unknown scenario)."
```

---

## Task 6: Phase 3b integration tests

**Files:**
- Create: `tests/integration/test_allocator_phase3b.py`

- [ ] **Step 1: Inspect Phase 3a integration helper pattern**

```bash
grep -n "_setup_state_nco\|_setup_state\|_allocator_state_helpers\|force_method" tests/integration/test_allocator_phase3a.py 2>&1 | head -15
ls tests/integration/_allocator_state_helpers.py 2>/dev/null && head -50 tests/integration/_allocator_state_helpers.py
```

Identify the helper signature (state builder) and reuse it.

- [ ] **Step 2: Write 7 Phase 3b integration tests**

Create `tests/integration/test_allocator_phase3b.py`:

```python
"""Phase 3b BL views adapter — integration tests."""
import pytest

from tradingagents.agents.allocator.portfolio_allocator import build_portfolio_allocator
from tests.integration._allocator_state_helpers import build_state


def _setup_state_bl(*, force_method=None, scenario="goldilocks",
                    regime_confidence=0.8):
    state = build_state(
        scenario=scenario,
        regime_confidence=regime_confidence,
    )
    if force_method is not None:
        state["force_method"] = force_method
    return state


def test_allocator_with_method_bl_runs_to_completion():
    state = _setup_state_bl(force_method="black_litterman")
    node = build_portfolio_allocator()
    result = node(state)
    weights = result["weight_vector"].weights
    assert abs(sum(weights.values()) - 1.0) < 1e-4


def test_allocator_bl_attribution_records_breakdown():
    state = _setup_state_bl(force_method="black_litterman",
                             scenario="goldilocks")
    result = build_portfolio_allocator()(state)
    attr = result["portfolio"]["allocation_attribution"]
    opt = attr.get("optimization", {})
    assert "bl_views_breakdown" in opt
    bd = opt["bl_views_breakdown"]
    assert bd["scenario"] == "goldilocks"
    assert bd["n_views_per_bucket"]
    assert bd["rulebook_returns_used"]


def test_allocator_bl_respects_single_asset_cap():
    from tradingagents.agents.allocator.portfolio_allocator import SINGLE_ASSET_CAP
    state = _setup_state_bl(force_method="black_litterman")
    result = build_portfolio_allocator()(state)
    weights = result["weight_vector"].weights
    assert all(w <= SINGLE_ASSET_CAP + 1e-4 for w in weights.values())


def test_allocator_bl_high_confidence_triggers_via_picker():
    """force_method 없이 high confidence + known scenario → method=BL."""
    state = _setup_state_bl(scenario="goldilocks", regime_confidence=0.8)
    result = build_portfolio_allocator()(state)
    attr = result["portfolio"]["allocation_attribution"]
    mp = attr["method_picker"]
    assert mp["method"] == "black_litterman"
    assert mp["rule_fired"] == "bl_high_confidence"


def test_allocator_bl_low_confidence_falls_through_to_hrp():
    """confidence < 0.7 → scenario_mapping (goldilocks → HRP)."""
    state = _setup_state_bl(scenario="goldilocks", regime_confidence=0.5)
    result = build_portfolio_allocator()(state)
    attr = result["portfolio"]["allocation_attribution"]
    mp = attr["method_picker"]
    assert mp["method"] != "black_litterman"
    assert mp["rule_fired"] == "scenario_mapping"


def test_allocator_bl_unknown_scenario_with_force_method_falls_back():
    """force_method=bl + unknown scenario → views={} → historical 폴백 + fallback 기록."""
    state = _setup_state_bl(force_method="black_litterman", scenario=None)
    result = build_portfolio_allocator()(state)
    attr = result["portfolio"]["allocation_attribution"]
    opt = attr.get("optimization", {})
    assert opt.get("bl_views_fallback") == "empty_views_historical_fallback"


def test_allocator_bl_vs_hrp_same_inputs_different_method_labels():
    """동일 입력에 force_method 만 다르게 → method label 다름."""
    state_bl = _setup_state_bl(force_method="black_litterman")
    state_hrp = _setup_state_bl(force_method="hrp")
    res_bl = build_portfolio_allocator()(state_bl)
    res_hrp = build_portfolio_allocator()(state_hrp)
    mp_bl = res_bl["portfolio"]["allocation_attribution"]["method_picker"]
    mp_hrp = res_hrp["portfolio"]["allocation_attribution"]["method_picker"]
    assert mp_bl["method"] == "black_litterman"
    assert mp_hrp["method"] == "hrp"
```

If `build_state` helper does not accept `scenario` / `regime_confidence` kwargs, inspect it and add minimal support:

```bash
grep -n "def build_state\|scenario\|regime_confidence" tests/integration/_allocator_state_helpers.py 2>&1 | head -15
```

Adjust the helper or the test setup as the implementer sees fit — keep changes minimal.

- [ ] **Step 3: Run integration tests**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/integration/test_allocator_phase3b.py -v 2>&1 | tail -20
```

Expected: 7 passed. If any fails:
- Verify `attribution["optimization"]["bl_views_breakdown"]` path matches actual allocator output structure.
- Verify state helper exposes scenario + regime_confidence injection.

- [ ] **Step 4: Run regression on Phase 1/2a/2b/3a integration**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest \
    tests/integration/test_allocator_phase1.py \
    tests/integration/test_allocator_phase2a.py \
    tests/integration/test_allocator_phase2b.py \
    tests/integration/test_allocator_phase3a.py \
    tests/integration/test_allocator_phase3b.py \
    tests/integration/test_plan_pipeline_mock.py \
    -q 2>&1 | tail -5
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_allocator_phase3b.py tests/integration/_allocator_state_helpers.py
git commit -m "test(stage3): Phase 3b BL views allocator integration 테스트

7 tests: run-to-completion, attribution.bl_views_breakdown, single asset cap,
picker high-conf trigger, picker low-conf fallthrough, force_method unknown
scenario fallback, force_method label."
```

---

## Task 7: Regression + Acceptance

- [ ] **Step 1: Setup .env if missing**

```bash
cp /Users/kimjaewon/Pluto/TradingAgents/.env . 2>/dev/null || echo ".env not copied (may exist or absent)"
```

- [ ] **Step 2: Default E2E (회귀 무손실 검증)**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/run_e2e_test.py \
    --as-of 2026-05-15 --capital 1000000000 2>&1 | tail -25
```

Expected: same method as Phase 3a default (e.g., hrp or risk_parity). BL must NOT trigger (regime_confidence < 0.7 in synthetic data).

- [ ] **Step 3: BL E2E (force_method)**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/run_e2e_test.py \
    --as-of 2026-05-15 --capital 1000000000 \
    --force-method black_litterman 2>&1 | tail -25
```

Expected: 정상 종료.

- [ ] **Step 4: Verify BL attribution**

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
print('opt keys:', list(opt.keys()))
if 'bl_views_breakdown' in opt:
    print('bl scenario:', opt['bl_views_breakdown'].get('scenario'))
    print('bl confidence_used:', opt['bl_views_breakdown'].get('confidence_used'))
    print('bl n_views_per_bucket:', opt['bl_views_breakdown'].get('n_views_per_bucket'))
elif 'bl_views_fallback' in opt:
    print('bl fallback:', opt['bl_views_fallback'])
weights = p.get('weights', {})
print('n_total:', len(weights))
print('weight sum:', sum(weights.values()))
print('max single weight:', max(weights.values()) if weights else 0)
"
```

Expected:
- `method: black_litterman`, `rule_fired: state_override`
- Either `bl_views_breakdown` (if synthetic data scenario is known) OR `bl_views_fallback` (if unknown)
- `weight sum ≈ 1.0`, all weights `≤ SINGLE_ASSET_CAP`

- [ ] **Step 5: Regression compare**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/regression_compare.py \
    --baseline artifacts/baseline/ \
    --new artifacts/ \
    --out artifacts/phase3b_regression.json 2>&1 | tail -20
```

Expected: (a)(b)(c) PASS. (d) may FAIL due to method divergence (BL ≠ HRP).

- [ ] **Step 6: Full test regression**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest \
    tests/unit/skills/test_portfolio_bl_views.py \
    tests/unit/skills/test_portfolio_nco.py \
    tests/unit/skills/test_method_picker.py \
    tests/unit/agents/test_portfolio_allocator.py \
    tests/unit/observability/test_stage3_ablation.py \
    tests/integration/test_allocator_phase1.py \
    tests/integration/test_allocator_phase2a.py \
    tests/integration/test_allocator_phase2b.py \
    tests/integration/test_allocator_phase3a.py \
    tests/integration/test_allocator_phase3b.py \
    tests/integration/test_plan_pipeline_mock.py \
    tests/integration/test_5_28_dry_run.py \
    -q 2>&1 | tail -8
```

Expected: all PASS (Phase 3a 228 + 12 BL unit + 4 picker BL + 7 integration = ~251).

- [ ] **Step 7: Commit artifacts**

```bash
git add artifacts/2025-04-15/ artifacts/2026-05-15/ artifacts/phase3b_regression.json 2>/dev/null

if git diff --cached --quiet; then
    echo "nothing to commit"
else
    git commit -m "$(cat <<'EOF'
chore(stage3): Phase 3b 적용 후 산출물 + regression 결과

baseline → phase3b:
  default method: 회귀 무손실 (regime_confidence < BL_TRIGGER_CONFIDENCE)
  --force-method black_litterman: BL 활성화, attribution.bl_views_breakdown 또는
    bl_views_fallback 기록, rule_fired='state_override'

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
fi
```

---

## Self-Review (controller, before dispatching subagents)

### Spec coverage

| Spec section | Task |
|---|---|
| `bl_views.py` SCENARIO_BUCKET_RULEBOOK | Task 1 |
| `bl_views.py` BL_VIEW_MIN_CONFIDENCE | Task 1 |
| `generate_bl_views` known scenario | Task 2 |
| `generate_bl_views` breakdown_out | Task 2 |
| `generate_bl_views` edge cases (unknown / None / floor / agnostic / empty) | Task 3 |
| method_picker BL_TRIGGER_CONFIDENCE | Task 4 |
| method_picker BL trigger rule (rule_index=2) | Task 4 |
| method_picker rule_index shift | Task 4 |
| allocator BL branch sentinel handling | Task 5 |
| allocator scenario / regime_confidence kwargs | Task 5 |
| attribution.bl_views_breakdown / bl_views_fallback | Task 5 |
| 9 unit BL tests | Task 1+2+3 (4 + 3 + 5 = 12) |
| 4 picker BL tests | Task 4 |
| 7 integration tests | Task 6 |
| Default e2e 회귀 | Task 7 |
| force_method e2e | Task 7 |

### Placeholder scan

No "TBD", "TODO", "fill in details". All code blocks complete. All commands exact.

### Type consistency

- `generate_bl_views` signature consistent: `scenario: str | None`, `regime_confidence: float`, `candidates: dict[str, list[str]]`, returns `tuple[dict[str, float], list[float]]`.
- `_optimize_with_bucket_constraints` adds `scenario: str | None = None, regime_confidence: float = 0.5` kwargs.
- `method_params["_bl_trigger"]: bool` sentinel — same name in method_picker output and allocator consumption.
- attribution keys: `bl_views_breakdown` (dict), `bl_views_fallback` (string) — consistent across allocator and tests.

Note: Unit test count is 12 (not 9 as initially planned in spec). 9 was an early estimate; 12 covers all edge cases. Picker tests are 4. Integration tests are 7. Total = 23 as in spec.
