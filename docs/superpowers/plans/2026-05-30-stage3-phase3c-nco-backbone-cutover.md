# Stage 3 Phase 3c — NCO Backbone Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `method_picker` 의 모든 HRP 출력을 NCO 로 교체하여 NCO 를 production backbone 으로 cutover.

**Architecture:** `_SCENARIO_METHOD` 4 cell (overheating/goldilocks/ai_concentration/kr_boom) HRP→NCO + rule 7 default HRP→NCO + `LOW_CONVICTION_HRP_DOWNGRADE` 상수 및 downgrade 블록 제거. HRP enum + `_hrp_per_bucket` + allocator HRP 분기는 force_method A/B 용으로 보존.

**Tech Stack:** Python 3.13, pytest.

**Test runner:** `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest`

---

## Task 1: method_picker 코드 변경 + unit tests 갱신/추가

**Files:**
- Modify: `tradingagents/skills/portfolio/method_picker.py`
- Modify: `tests/unit/skills/test_portfolio_method_picker.py`

- [ ] **Step 1: Inspect existing HRP-related tests**

```bash
grep -nE "HRP|hrp|LOW_CONVICTION|downgrad|scenario_mapping|default" tests/unit/skills/test_portfolio_method_picker.py | head -40
grep -n "OptimizationMethod\." tradingagents/skills/portfolio/method_picker.py | head -30
grep -rn "downgraded_from_hrp" tradingagents/ 2>&1 | head
grep -rn "downgraded_from_hrp" tests/ 2>&1 | head
```

Record:
- Which tests assert HRP for scenarios overheating/goldilocks/ai_concentration/kr_boom (need NCO update)
- Which tests assert HRP for default (need NCO update)
- Which tests cover LOW_CONVICTION_HRP_DOWNGRADE (need removal or rewrite)
- Whether `downgraded_from_hrp` is consumed anywhere (likely method_picker only)

- [ ] **Step 2: Write new failing tests (7 new)**

Append to `tests/unit/skills/test_portfolio_method_picker.py`:

```python
from tradingagents.skills.portfolio.method_picker import pick_optimization_method
from tradingagents.schemas.portfolio import OptimizationMethod


def test_picker_default_regime_returns_nco():
    """rule 7 default → NCO (이전 HRP)."""
    choice = pick_optimization_method(
        regime_quadrant="growth_disinflation",
        regime_confidence=0.5,
        systemic_score=5.0,
        systemic_regime="neutral",
        dominant_scenario=None,
        conviction="high",
    )
    assert choice.method == OptimizationMethod.NCO
    assert choice.rule_fired == "default"


def test_picker_overheating_returns_nco():
    """scenario=overheating + confidence<0.7 → rule 3 → NCO (이전 HRP)."""
    choice = pick_optimization_method(
        regime_quadrant="growth_inflation",
        regime_confidence=0.5,
        systemic_score=5.0,
        systemic_regime="neutral",
        dominant_scenario="overheating",
        conviction="high",
    )
    assert choice.method == OptimizationMethod.NCO
    assert choice.rule_fired == "scenario_mapping"


def test_picker_goldilocks_returns_nco():
    choice = pick_optimization_method(
        regime_quadrant="growth_disinflation",
        regime_confidence=0.5,
        systemic_score=5.0,
        systemic_regime="neutral",
        dominant_scenario="goldilocks",
        conviction="high",
    )
    assert choice.method == OptimizationMethod.NCO
    assert choice.rule_fired == "scenario_mapping"


def test_picker_ai_concentration_returns_nco():
    choice = pick_optimization_method(
        regime_quadrant="growth_disinflation",
        regime_confidence=0.5,
        systemic_score=5.0,
        systemic_regime="neutral",
        dominant_scenario="ai_concentration",
        conviction="high",
    )
    assert choice.method == OptimizationMethod.NCO
    assert choice.rule_fired == "scenario_mapping"


def test_picker_kr_boom_returns_nco():
    choice = pick_optimization_method(
        regime_quadrant="growth_disinflation",
        regime_confidence=0.5,
        systemic_score=5.0,
        systemic_regime="neutral",
        dominant_scenario="kr_boom",
        conviction="high",
    )
    assert choice.method == OptimizationMethod.NCO
    assert choice.rule_fired == "scenario_mapping"


def test_picker_low_conviction_does_not_downgrade_nco():
    """overheating + conviction=low + confidence<0.7 → NCO (이전엔 RP 로 downgrade)."""
    choice = pick_optimization_method(
        regime_quadrant="growth_inflation",
        regime_confidence=0.5,
        systemic_score=5.0,
        systemic_regime="neutral",
        dominant_scenario="overheating",
        conviction="low",
    )
    assert choice.method == OptimizationMethod.NCO
    assert choice.rule_fired == "scenario_mapping"


def test_picker_no_downgrade_flag_in_inputs_trace():
    """downgraded_from_hrp key 가 inputs trace 에서 사라짐."""
    choice = pick_optimization_method(
        regime_quadrant="growth_inflation",
        regime_confidence=0.5,
        systemic_score=5.0,
        systemic_regime="neutral",
        dominant_scenario="overheating",
        conviction="low",
    )
    assert "downgraded_from_hrp" not in choice.inputs
```

- [ ] **Step 3: Run new tests to verify FAIL**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_method_picker.py -v -k "returns_nco or no_downgrade or does_not_downgrade" 2>&1 | tail -15
```

Expected: 7 FAIL (method currently returns HRP/RP).

- [ ] **Step 4: Edit `_SCENARIO_METHOD` (4 cell HRP→NCO)**

In `tradingagents/skills/portfolio/method_picker.py`, find `_SCENARIO_METHOD` (around line 46) and change 4 cells:

```python
    "overheating":      (OptimizationMethod.NCO,
                         "overheating (growth+inflation) → equity tilt + 분산, NCO"),
    "goldilocks":       (OptimizationMethod.NCO,
                         "goldilocks → 분산 친화, NCO"),
    "ai_concentration": (OptimizationMethod.NCO,
                         "ai_concentration → narrow leadership 위험, NCO로 corr 감안"),
    "kr_boom":          (OptimizationMethod.NCO,
                         "kr_boom → KR 호황 분산, NCO"),
```

(global_credit/broad_recession/kr_stress 의 MIN_VARIANCE, stagflation/late_cycle 의 RISK_PARITY 는 unchanged.)

- [ ] **Step 5: Remove `LOW_CONVICTION_HRP_DOWNGRADE` constant**

Find around line 31 and delete:

```python
LOW_CONVICTION_HRP_DOWNGRADE: bool = True
```

- [ ] **Step 6: Simplify scenario_mapping rule (remove downgrade block)**

In `pick_optimization_method`, find the scenario_mapping rule (currently rule 3 after Phase 3b's rule_index shift). Replace the downgrade block:

```python
    if scenario_in and scenario_in in _SCENARIO_METHOD:
        method, reason = _SCENARIO_METHOD[scenario_in]
        choice = MethodChoice(
            method=method,
            reasoning=(
                f"scenario={scenario_in}, conviction={conviction_in}: {reason}"
            )[:300],
            rule_fired="scenario_mapping",
            rule_index=3,
            inputs=inputs_trace,
        )
        logger.info(
            "method_picker rule 3 (scenario=%s, conviction=%s) → %s",
            scenario_in, conviction_in, method.value,
        )
        return choice
```

(Remove: `downgraded` var, `LOW_CONVICTION_HRP_DOWNGRADE` if block, `inputs_trace["downgraded_from_hrp"]` assignment.)

- [ ] **Step 7: Change rule 7 default HRP → NCO**

Find rule 7 default block (around line 224 in current source, after Phase 3b's shift it's rule_index=7). Change `method=OptimizationMethod.HRP` to `OptimizationMethod.NCO` and update reasoning + logger:

```python
    choice = MethodChoice(
        method=OptimizationMethod.NCO,
        reasoning=(
            f"default NCO (regime={regime_quadrant}, "
            f"systemic={systemic_score:.1f}/{systemic_regime})"
        )[:300],
        rule_fired="default",
        rule_index=7,
        inputs=inputs_trace,
    )
    logger.info(
        "method_picker rule 7 (default, regime=%s, systemic=%.1f/%s) → NCO",
        regime_quadrant, systemic_score, systemic_regime,
    )
```

- [ ] **Step 8: Update existing tests that assert HRP**

From Step 1's inspection, identify and update any existing test that asserts HRP for:
- scenario=overheating/goldilocks/ai_concentration/kr_boom
- default rule (no scenario, low confidence)
- LOW_CONVICTION_HRP_DOWNGRADE behavior (any test with `conviction="low"` + HRP scenario expecting RP) — DELETE or convert to expect NCO.

Use grep to find:
```bash
grep -nE "OptimizationMethod\.HRP|\.method.*hrp|RISK_PARITY.*downgrad" tests/unit/skills/test_portfolio_method_picker.py
```

Inspect each match and update assertion. Expected pattern:
```python
# Before
assert choice.method == OptimizationMethod.HRP
# After
assert choice.method == OptimizationMethod.NCO
```

Also: remove or convert any test referencing `LOW_CONVICTION_HRP_DOWNGRADE` import or downgrade behavior.

- [ ] **Step 9: Run full method_picker test suite to verify PASS**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_method_picker.py -v 2>&1 | tail -30
```

Expected: all PASS. If failures remain, inspect and update assertions (case missed in Step 8).

- [ ] **Step 10: Quick downstream check for `downgraded_from_hrp`**

```bash
grep -rn "downgraded_from_hrp" tradingagents/ tests/ 2>&1
```

Expected: zero matches outside method_picker (now removed). If any consumer found, file an issue note in the commit message but don't try to remove other code's reference without separate analysis.

- [ ] **Step 11: Commit**

```bash
git add tradingagents/skills/portfolio/method_picker.py tests/unit/skills/test_portfolio_method_picker.py
git commit -m "$(cat <<'EOF'
feat(stage3): Phase 3c NCO backbone cutover — method_picker

_SCENARIO_METHOD: overheating, goldilocks, ai_concentration, kr_boom 4개 cell
HRP → NCO. rule 7 default 도 HRP → NCO. LOW_CONVICTION_HRP_DOWNGRADE 상수 +
scenario_mapping rule 의 downgrade 블록 + inputs_trace['downgraded_from_hrp']
모두 제거. NCO 가 cluster-aware diversification 이라 low conviction 도 그대로 신뢰.

Preserved: HRP enum, _hrp_per_bucket, allocator HRP 분기 (force_method='hrp'
A/B 용). MV/RP 4 cell (global_credit, broad_recession, kr_stress, stagflation,
late_cycle) unchanged.

Tests: 7 신규 unit (returns_nco × 5, low_conviction_does_not_downgrade,
no_downgrade_flag) + 기존 HRP-expecting test 갱신.
EOF
)"
```

---

## Task 2: Phase 3c integration tests

**Files:**
- Create: `tests/integration/test_allocator_phase3c.py`

- [ ] **Step 1: Inspect Phase 3b integration helper pattern**

```bash
head -60 tests/integration/test_allocator_phase3b.py
grep -n "build_state\|_setup_state\|force_method\|scenario" tests/integration/_allocator_state_helpers.py | head -20
```

Identify:
- Helper signature: `build_state(scenario=..., regime_confidence=...)`
- Default `regime_confidence` in helper (Phase 3b set it to 0.6 to avoid BL trigger)
- Whether `conviction` kwarg is exposed

If `conviction` is not exposed by the helper, the test for low-conviction may need direct state manipulation.

- [ ] **Step 2: Write 3 integration tests**

Create `tests/integration/test_allocator_phase3c.py`:

```python
"""Phase 3c NCO backbone cutover — integration tests.

NCO 가 backbone 으로 격상되어 method_picker 의 HRP 출력 자리에 NCO 가 들어가는지
실 allocator 흐름으로 검증.
"""
import pytest

from tradingagents.agents.allocator.portfolio_allocator import build_portfolio_allocator
from tests.integration._allocator_state_helpers import build_state


def test_allocator_default_method_is_nco_when_no_scenario():
    """scenario=None, low confidence → rule 7 default → method=nco."""
    state = build_state(scenario=None, regime_confidence=0.5)
    result = build_portfolio_allocator()(state)
    attr = result["portfolio"]["allocation_attribution"]
    mp = attr["method_picker"]
    assert mp["method"] == "nco"
    assert mp["rule_fired"] == "default"


def test_allocator_overheating_scenario_uses_nco():
    """scenario=overheating, low confidence → rule 3 → method=nco (이전 HRP)."""
    state = build_state(scenario="overheating", regime_confidence=0.5)
    result = build_portfolio_allocator()(state)
    attr = result["portfolio"]["allocation_attribution"]
    mp = attr["method_picker"]
    assert mp["method"] == "nco"
    assert mp["rule_fired"] == "scenario_mapping"


def test_allocator_low_conviction_no_downgrade():
    """overheating + conviction=low + confidence<0.7 → method=nco (이전엔 RP downgrade)."""
    state = build_state(scenario="overheating", regime_confidence=0.5)
    # Helper 의 conviction 처리 방식 확인 후, low 로 명시적으로 변경.
    # 이 part 는 helper 의 conviction 노출 방식에 따라 조정 — 가장 단순하게
    # research_decision 의 conviction 을 'low' 로 강제하거나 state 직접 수정.
    if "research_decision" in state and hasattr(state["research_decision"], "conviction"):
        state["research_decision"].conviction = "low"
    elif "research_decision" in state and isinstance(state["research_decision"], dict):
        state["research_decision"]["conviction"] = "low"
    result = build_portfolio_allocator()(state)
    attr = result["portfolio"]["allocation_attribution"]
    mp = attr["method_picker"]
    # 핵심 검증: NCO 가 유지되고 RP 로 downgrade 안 됨.
    assert mp["method"] == "nco"
    assert mp["rule_fired"] == "scenario_mapping"
    # inputs trace 에 downgraded_from_hrp key 부재.
    assert "downgraded_from_hrp" not in mp.get("inputs", {})
```

- [ ] **Step 3: Run integration tests**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/integration/test_allocator_phase3c.py -v 2>&1 | tail -20
```

Expected: 3 PASS. If test 3 fails due to conviction injection logic, inspect actual state structure:

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -c "
from tests.integration._allocator_state_helpers import build_state
s = build_state(scenario='overheating', regime_confidence=0.5)
rd = s.get('research_decision')
print('type:', type(rd))
print('conviction:', getattr(rd, 'conviction', None) if hasattr(rd, 'conviction') else (rd.get('conviction') if isinstance(rd, dict) else 'N/A'))
"
```

Adjust test 3 to match actual structure.

- [ ] **Step 4: Run regression on Phase 1/2a/2b/3a/3b integration**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest \
    tests/integration/test_allocator_phase1.py \
    tests/integration/test_allocator_phase2a.py \
    tests/integration/test_allocator_phase2b.py \
    tests/integration/test_allocator_phase3a.py \
    tests/integration/test_allocator_phase3b.py \
    tests/integration/test_allocator_phase3c.py \
    tests/integration/test_plan_pipeline_mock.py \
    -q 2>&1 | tail -10
```

If failures appear, inspect — most likely cause is a Phase 1/2 test that expected HRP/RP and now gets NCO. Update assertion if so.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_allocator_phase3c.py
git commit -m "$(cat <<'EOF'
test(stage3): Phase 3c NCO backbone integration 테스트

3 tests: default→NCO, overheating scenario→NCO, low_conviction→NCO (no
downgrade). 모두 method_picker rule + allocator end-to-end 흐름으로 검증.
EOF
)"
```

If Phase 1/2 integration tests were updated to reflect new method, include them in the same commit.

---

## Task 3: Regression + Acceptance validation

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

Expected: regime_confidence=0.91 → BL 계속 트리거. method=black_litterman, rule_fired=bl_high_confidence. NCO backbone 영향은 BL trigger 가 우선이므로 가시적 변화 없음. 회귀 무손실.

- [ ] **Step 3: NCO scenario E2E (BL 회피)**

force a non-BL path to verify NCO backbone:

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/run_e2e_test.py \
    --as-of 2026-05-15 --capital 1000000000 \
    --force-method nco 2>&1 | tail -20
```

Expected: NCO 동작, attribution.nco_breakdown_per_pool 채워짐 (Phase 3a 그대로).

- [ ] **Step 4: Verify default-rule activation in mock context**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -c "
from tradingagents.skills.portfolio.method_picker import pick_optimization_method
from tradingagents.schemas.portfolio import OptimizationMethod

# default rule
c = pick_optimization_method(
    regime_quadrant='growth_disinflation',
    regime_confidence=0.5,
    systemic_score=5.0,
    systemic_regime='neutral',
    dominant_scenario=None,
    conviction='high',
)
print('default:', c.method.value, c.rule_fired)
assert c.method == OptimizationMethod.NCO, f'expected NCO, got {c.method}'

# scenario_mapping (4 NCO cells)
for s in ['overheating', 'goldilocks', 'ai_concentration', 'kr_boom']:
    c = pick_optimization_method(
        regime_quadrant='growth_disinflation',
        regime_confidence=0.5,
        systemic_score=5.0,
        systemic_regime='neutral',
        dominant_scenario=s,
        conviction='high',
    )
    print(f'{s}:', c.method.value, c.rule_fired)
    assert c.method == OptimizationMethod.NCO, f'{s}: expected NCO, got {c.method}'

# low_conviction no downgrade
c = pick_optimization_method(
    regime_quadrant='growth_inflation',
    regime_confidence=0.5,
    systemic_score=5.0,
    systemic_regime='neutral',
    dominant_scenario='overheating',
    conviction='low',
)
print('overheating+low:', c.method.value, c.rule_fired)
assert c.method == OptimizationMethod.NCO, f'expected NCO (no downgrade), got {c.method}'
assert 'downgraded_from_hrp' not in c.inputs, 'downgraded_from_hrp 가 inputs 에 남음'

print('All acceptance checks PASS')
"
```

Expected: All checks PASS, 6 lines print + final "All acceptance checks PASS".

- [ ] **Step 5: Regression compare**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/regression_compare.py \
    --baseline artifacts/baseline/ \
    --new artifacts/ \
    --out artifacts/phase3c_regression.json 2>&1 | tail -15
```

Expected: BL trigger 가 발동하는 default e2e 경로에서는 method 동일 (black_litterman). (a)(b)(c) PASS 기대. (d) fx_commodity 는 Phase 3b 와 동일하게 scenario divergence 로 FAIL 가능 (Phase 3c 무관, pre-existing).

- [ ] **Step 6: Full test regression**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest \
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
    tests/integration/test_plan_pipeline_mock.py \
    tests/integration/test_5_28_dry_run.py \
    -q 2>&1 | tail -8
```

Expected: all PASS. If Phase 1/2 integration test fails because helper default scenario changed effect (HRP→NCO), update assertion in those tests as part of Task 2 commit (no scope leak).

- [ ] **Step 7: Commit artifacts**

```bash
git add artifacts/2025-04-15/ artifacts/2026-05-15/ artifacts/phase3c_regression.json 2>/dev/null

if git diff --cached --quiet; then
    echo "nothing to commit"
else
    git commit -m "$(cat <<'EOF'
chore(stage3): Phase 3c 적용 후 산출물 + regression 결과

baseline → phase3c:
  default e2e (BL trigger 발동): method=black_litterman (변화 없음, 회귀 무손실)
  --force-method nco: Phase 3a NCO path 그대로 동작
  NCO backbone cutover 의 가시적 효과는 unit/integration test 로 검증
  (BL trigger 가 NCO 보다 우선이므로 실 데이터 default e2e 에선 가려짐)

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
| `_SCENARIO_METHOD` 4 cell HRP→NCO | Task 1 Step 4 |
| `LOW_CONVICTION_HRP_DOWNGRADE` 상수 제거 | Task 1 Step 5 |
| scenario_mapping rule downgrade 블록 제거 | Task 1 Step 6 |
| `downgraded_from_hrp` inputs_trace key 제거 | Task 1 Step 6 (in rewritten block) |
| Rule 7 default HRP→NCO | Task 1 Step 7 |
| Unit tests 갱신 (HRP→NCO) | Task 1 Step 8 |
| 7 신규 unit tests | Task 1 Step 2 |
| 3 신규 integration tests | Task 2 Step 2 |
| `downgraded_from_hrp` downstream 사용처 확인 | Task 1 Step 10 |
| HRP enum + `_hrp_per_bucket` 보존 (force_method='hrp' A/B) | Out-of-scope (보존만 함, 변경 없음) |
| MV/RP cells unchanged | Task 1 Step 4 note |
| E2E 회귀 (BL trigger 시 변화 없음) | Task 3 Step 2 |
| Default rule mock 검증 | Task 3 Step 4 |
| Full test regression | Task 3 Step 6 |

### Placeholder scan

No "TBD", "TODO", "fill in details". All code blocks complete. Task 2 Step 2 의 conviction 주입 로직은 helper 구조에 따라 조정이 필요할 수 있음 — 이는 구현자가 inspection 으로 처리하도록 명시.

### Type consistency

- `OptimizationMethod.NCO` enum 은 Phase 3a 에서 이미 정의됨 — 신규 정의 없음.
- `MethodChoice` schema 의 모든 field (method/reasoning/rule_fired/rule_index/inputs/params) 는 Phase 3b 에서 정의된 그대로 사용.
- `_SCENARIO_METHOD: dict[str, tuple[OptimizationMethod, str]]` 시그니처 변경 없음 (cell 값만 교체).
- attribution key 변경 없음 — `bl_views_breakdown`, `nco_breakdown_per_pool` 등은 Phase 3a/3b 그대로.
