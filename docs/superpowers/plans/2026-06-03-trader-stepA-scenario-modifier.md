# Trader Step A — Scenario Modifier (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** quadrant 축에 직교하는 명명 시나리오(kr_boom/kr_stress/global_credit/ai_concentration)를 결정론적 modifier로 인코딩해, Phase 1 quadrant baseline의 center를 그 방향으로 옮긴다(quadrant hard band 내 clamp). LLM은 옮겨진 center 주변에서 tilt.

**Architecture:** `dominant_scenario`를 `Literal` enum으로 제약(enum 밖 값은 neutral coerce). `scenario_anchor.py`에 `SCENARIO_MODIFIER` 테이블 + `apply_scenario_modifier`(기존 `project_to_band` 재사용) 추가. trader node가 baseline→modifier→effective_band→tilt→project 순서로 한 단계 삽입. manager 프롬프트는 직교 시나리오 분류로 재정의.

**Tech Stack:** Python 3.12, Pydantic v2 (Annotated + BeforeValidator), pytest.

**Spec:** [docs/superpowers/specs/2026-06-03-trader-stepA-scenario-modifier-design.md](../specs/2026-06-03-trader-stepA-scenario-modifier-design.md)

---

## File Structure

| 파일 | 책임 |
|---|---|
| `tradingagents/schemas/research.py` | `ScenarioLabel` Literal + coerce; `InvestmentThesis`·`ResearchThesis` 의 `dominant_scenario` enum 화 |
| `tradingagents/skills/portfolio/scenario_anchor.py` | `SCENARIO_MODIFIER` + `apply_scenario_modifier` (project_to_band 재사용) |
| `tradingagents/agents/researchers/research_cluster.py` | `_MANAGER_SYSTEM` 의 dominant_scenario 분류 지시 교체 |
| `tradingagents/agents/trader/trader_allocator.py` | node Step A 에 modifier 단계; `_step_a_prompt` 에 scenario 인자 |
| 테스트 4파일 | 아래 각 task 참조 |

> **불변(건드리지 말 것):** `ResearchDecision`(구 factor schema — agent_states/philosophy 가 아직 참조), Step B, within-bucket, validator. `test_portfolio_manager_full_trace.py` 는 `SimpleNamespace` mock 이라 coerce 영향 없음 — 수정 불필요.

---

## Task 1: `dominant_scenario` enum 화 + coerce + 깨지는 테스트 수정

**Files:**
- Modify: `tradingagents/schemas/research.py`
- Test: `tests/unit/schemas/test_research_trade_schemas.py`
- Fix (coerce blast radius): `tests/unit/agents/researchers/test_research_cluster.py`, `tests/integration/test_plan_pipeline_mock.py`

- [ ] **Step 1: coerce 테스트 작성 + 기존 단정 갱신 (`test_research_trade_schemas.py`)**

`test_research_thesis_compat_fields` 의 `"goldilocks"` 를 유효 라벨로 바꾸고, 새 coerce 테스트를 추가:
```python
def test_research_thesis_compat_fields():
    t = ResearchThesis(conviction="high", dominant_scenario="kr_stress",
                       thesis_md="t", bull_view="b", bear_view="r")
    assert getattr(t, "dominant_scenario") == "kr_stress"
    assert getattr(t, "conviction") == "high"
    assert getattr(t, "factor_scores", None) is None


def test_dominant_scenario_coerces_unknown_to_neutral():
    # 구 라벨 / free text (enum 밖) → neutral (replay·구 archive 호환)
    assert ResearchThesis(dominant_scenario="growth_inflation").dominant_scenario == "neutral"
    assert InvestmentThesis(thesis_md="x", dominant_scenario="goldilocks").dominant_scenario == "neutral"
    # 유효 직교 라벨은 보존
    assert ResearchThesis(dominant_scenario="kr_boom").dominant_scenario == "kr_boom"
    assert InvestmentThesis(thesis_md="x", dominant_scenario="ai_concentration").dominant_scenario == "ai_concentration"
```
(`test_investment_thesis_defaults` 의 `default == "neutral"` 단정은 그대로 유효 — 변경 없음.)

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/unit/schemas/test_research_trade_schemas.py -q`
Expected: FAIL — `test_dominant_scenario_coerces_unknown_to_neutral` (validator 미존재, `"growth_inflation"` 그대로 통과되어 assert 실패) + `test_research_thesis_compat_fields` 는 PASS(아직 free str).

- [ ] **Step 3: `research.py` 에 enum + coerce 구현**

import 라인 교체:
```python
from typing import Annotated, Literal, get_args

from pydantic import BaseModel, BeforeValidator, Field
```
`ConvictionLevel = Literal[...]` 아래에 추가:
```python
ScenarioLabel = Literal[
    "kr_boom", "kr_stress", "global_credit", "ai_concentration", "neutral",
]
_VALID_SCENARIOS = frozenset(get_args(ScenarioLabel))


def _coerce_scenario(v: object) -> object:
    """enum 밖 값(구 라벨/free text) → neutral. replay·구 archive 호환."""
    return v if v in _VALID_SCENARIOS else "neutral"


# 두 모델 공용 — Annotated + BeforeValidator 로 coercion 을 타입에 부착(DRY).
ScenarioField = Annotated[ScenarioLabel, BeforeValidator(_coerce_scenario)]
```
`InvestmentThesis` 의 `dominant_scenario` 교체:
```python
    dominant_scenario: ScenarioField = "neutral"
```
`ResearchThesis` 의 `dominant_scenario` 교체:
```python
    dominant_scenario: ScenarioField = "neutral"
```
(둘 다 `Field(default="neutral", max_length=40)` → `ScenarioField = "neutral"` 로. max_length 는 Literal 에 불필요.)

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/pytest tests/unit/schemas/test_research_trade_schemas.py -q`
Expected: PASS (defaults, compat_fields, coerce 전부).

- [ ] **Step 5: coerce 로 깨지는 다른 테스트 2곳 수정**

`tests/unit/agents/researchers/test_research_cluster.py` `test_cluster_synthesizes_research_thesis`:
```python
    thesis = InvestmentThesis(thesis_md="종합", conviction="high",
                              dominant_scenario="kr_stress",
                              key_risks=["인플레 재점화"])
    ...
    assert rd.dominant_scenario == "kr_stress"
```
(`"goldilocks"` → `"kr_stress"` 두 곳: fixture 와 assert.)

`tests/integration/test_plan_pipeline_mock.py` `_fixture_thesis`:
```python
    _fixture_thesis = ResearchThesis(
        conviction="high",
        dominant_scenario="neutral",
        thesis_md="fixture thesis",
        bull_view="bull",
        bear_view="bear",
    )
```
(`"goldilocks"` → `"neutral"`; 값 단정 없음, 명확성 위해 valid 라벨로.)

- [ ] **Step 6: 영향 suite 전체 green 확인 + 커밋**

Run: `.venv/bin/pytest tests/unit/schemas tests/unit/agents/researchers tests/integration/test_plan_pipeline_mock.py -q`
Expected: PASS (no failures)

```bash
git add tradingagents/schemas/research.py tests/unit/schemas/test_research_trade_schemas.py \
        tests/unit/agents/researchers/test_research_cluster.py tests/integration/test_plan_pipeline_mock.py
git commit -m "feat(stage3): dominant_scenario Literal enum + coerce-unknown→neutral (Phase 2)"
```

---

## Task 2: `SCENARIO_MODIFIER` + `apply_scenario_modifier` (scenario_anchor.py)

**Files:**
- Modify: `tradingagents/skills/portfolio/scenario_anchor.py`
- Test: `tests/unit/skills/portfolio/test_scenario_anchor.py`

- [ ] **Step 1: 테스트 작성 (실패 예정)**

`test_scenario_anchor.py` 에 추가 (상단 import 에 합류):
```python
from tradingagents.skills.portfolio.scenario_anchor import (
    SCENARIO_MODIFIER, apply_scenario_modifier,
)
from tradingagents.schemas.research import _VALID_SCENARIOS


def test_modifier_keys_are_valid_orthogonal_scenarios():
    # neutral 은 modifier 없음, 나머지 키는 유효 시나리오여야
    assert "neutral" not in SCENARIO_MODIFIER
    assert set(SCENARIO_MODIFIER) <= (_VALID_SCENARIOS - {"neutral"})
    # 각 delta 는 14-bucket 키이고 |delta| ≤ 0.05
    for deltas in SCENARIO_MODIFIER.values():
        assert all(b in GAPS_BUCKET_KEYS for b in deltas)
        assert all(abs(d) <= 0.05 + 1e-9 for d in deltas.values())


def test_neutral_scenario_is_noop():
    base = dict(QUADRANT_BASELINE["growth_disinflation"])
    hmin = {b: hard_band("growth_disinflation", b, base[b])[0] for b in base}
    hmax = {b: hard_band("growth_disinflation", b, base[b])[1] for b in base}
    assert apply_scenario_modifier(base, "neutral", hmin, hmax) == pytest.approx(base)
    assert apply_scenario_modifier(base, "definitely_unknown", hmin, hmax) == pytest.approx(base)


def test_kr_stress_shifts_kr_down_global_up_within_band_sum1():
    q = "growth_disinflation"
    base = dict(QUADRANT_BASELINE[q])
    hmin = {b: hard_band(q, b, base[b])[0] for b in base}
    hmax = {b: hard_band(q, b, base[b])[1] for b in base}
    out = apply_scenario_modifier(base, "kr_stress", hmin, hmax)
    assert out["b1_kr_equity"] < base["b1_kr_equity"]      # 한국주식 ↓
    assert out["b2_dm_core"] > base["b2_dm_core"]          # 미국주식 ↑
    assert sum(out.values()) == pytest.approx(1.0, abs=1e-9)
    assert all(hmin[b] - 1e-9 <= out[b] <= hmax[b] + 1e-9 for b in out)


def test_modifier_clamped_by_quadrant_hard_band():
    # 침체 quadrant 에서 ai_concentration(테크↑) 적용해도 b3_global_tech 가 그 quadrant hard_max 초과 안 함
    q = "recession_disinflation"
    base = dict(QUADRANT_BASELINE[q])
    hmin = {b: hard_band(q, b, base[b])[0] for b in base}
    hmax = {b: hard_band(q, b, base[b])[1] for b in base}
    out = apply_scenario_modifier(base, "ai_concentration", hmin, hmax)
    assert out["b3_global_tech"] <= hmax["b3_global_tech"] + 1e-9
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/unit/skills/portfolio/test_scenario_anchor.py -q -k "modifier or neutral_scenario or kr_stress"`
Expected: FAIL — `ImportError: cannot import name 'SCENARIO_MODIFIER'`

- [ ] **Step 3: `scenario_anchor.py` 에 구현 (파일 끝, project_to_band 아래)**

```python
# 직교 시나리오 → {bucket: delta}. 작고 net≈0, |delta| ≤ 0.05 (v1 시드, 튜닝 대상).
# keys ⊆ ScenarioLabel \ {neutral} (test_scenario_anchor 가 cross-check).
SCENARIO_MODIFIER: dict[str, dict[str, float]] = {
    "kr_boom":          {"b1_kr_equity": 0.05, "b5_other_intl": -0.03, "b2_dm_core": -0.02},
    "kr_stress":        {"b1_kr_equity": -0.05, "b2_dm_core": 0.03, "a1_cash": 0.02},
    "global_credit":    {"b9_risk_credit": -0.04, "a3_us_rates": 0.04},
    "ai_concentration": {"b3_global_tech": 0.05, "b6_defensive_equity": -0.03, "b5_other_intl": -0.02},
    # "neutral" 없음 → no-op
}


def apply_scenario_modifier(
    baseline: dict[str, float], scenario: str,
    hard_min: dict[str, float], hard_max: dict[str, float],
) -> dict[str, float]:
    """quadrant baseline 에 scenario modifier 를 더해 center 이동, quadrant hard band 로 투영.

    neutral / 미정의 scenario → baseline 그대로. project_to_band 재사용 → sum=1·hard band 내
    보장, 불가 시 baseline fallback. modifier 가 hard band 를 못 벗어나는 게 구조적 모순 guard.
    """
    delta = SCENARIO_MODIFIER.get(scenario)
    if not delta:
        return dict(baseline)
    return project_to_band(baseline, delta, hard_min, hard_max)
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/pytest tests/unit/skills/portfolio/test_scenario_anchor.py -q`
Expected: PASS (전체)

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/skills/portfolio/scenario_anchor.py tests/unit/skills/portfolio/test_scenario_anchor.py
git commit -m "feat(stage3): SCENARIO_MODIFIER + apply_scenario_modifier (직교 시나리오 center 이동)"
```

---

## Task 3: manager 프롬프트 — 직교 시나리오 분류로 재정의

**Files:**
- Modify: `tradingagents/agents/researchers/research_cluster.py:12-19` (`_MANAGER_SYSTEM`)
- Test: `tests/unit/agents/researchers/test_research_cluster.py`

- [ ] **Step 1: 프롬프트 내용 테스트 작성 (실패 예정)**

`test_research_cluster.py` 에 추가:
```python
from tradingagents.agents.researchers.research_cluster import _MANAGER_SYSTEM


def test_manager_prompt_lists_orthogonal_scenarios():
    for label in ("kr_boom", "kr_stress", "global_credit", "ai_concentration", "neutral"):
        assert label in _MANAGER_SYSTEM
    # quadrant 개념(성장/인플레)은 macro regime 담당 — 시나리오로 넣지 말라는 지시 포함
    assert "macro regime" in _MANAGER_SYSTEM
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/unit/agents/researchers/test_research_cluster.py -q -k manager_prompt`
Expected: FAIL — 라벨들이 현재 프롬프트에 없음

- [ ] **Step 3: `_MANAGER_SYSTEM` 교체**

`research_cluster.py:12-19` 의 `_MANAGER_SYSTEM` 을 교체:
```python
_MANAGER_SYSTEM = (
    "당신은 자산배분 팀의 리서치 매니저다. 강세(bull) 리서처와 약세(bear) 리서처의 "
    "주장, 그리고 Stage 1 매크로/리스크/기술적/뉴스 분석을 모두 검토해 균형 잡힌 "
    "투자 판단을 종합한다. 한쪽으로 치우치지 말고 양측 논거의 강도를 평가해 결론을 "
    "내려라. 결과는 thesis_md(한국어 종합 판단), conviction(high/medium/low), "
    "key_risks(주요 리스크 리스트), 그리고 dominant_scenario 로 구조화하라.\n"
    "dominant_scenario: 아래 직교 시나리오 중 현재 명백히 해당하는 것 하나, 없으면 neutral.\n"
    "  - kr_boom: 한국만 두드러진 강세\n"
    "  - kr_stress: 한국만 두드러진 약세(글로벌은 상대적 양호)\n"
    "  - global_credit: 신용(회사채) 스프레드 급확대·경색\n"
    "  - ai_concentration: AI·반도체·테크로의 쏠림\n"
    "  - neutral: 위에 해당 없음 (대부분의 경우)\n"
    "  ※ 성장/침체·인플레 국면 자체는 별도 macro regime 이 담당하므로 여기에 넣지 말 것."
)
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/pytest tests/unit/agents/researchers/test_research_cluster.py -q`
Expected: PASS (manager_prompt + 기존 cluster 테스트 — Task 1 에서 fixture 수정됨)

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/agents/researchers/research_cluster.py tests/unit/agents/researchers/test_research_cluster.py
git commit -m "feat(stage3): manager 프롬프트를 직교 시나리오 분류로 재정의 (Phase 2)"
```

---

## Task 4: node 배선 — modifier 단계 삽입 + `_step_a_prompt` scenario 인자

**Files:**
- Modify: `tradingagents/agents/trader/trader_allocator.py`
- Test: `tests/unit/agents/trader/test_trader_allocator.py`

- [ ] **Step 1: 통합 테스트 작성 + 기존 prompt 테스트 호출 갱신 (실패 예정)**

`test_trader_allocator.py` 에 추가 (이미 있는 `_universe_14`, `_state_14`, `_FakeStep`, `_FakeRegime`, `_FakeMacro`, `BucketTilt`, `StockSelection`, `ResearchThesis`, `create_trader_allocator` 활용):
```python
from tradingagents.skills.portfolio.scenario_anchor import QUADRANT_BASELINE


def test_kr_stress_modifier_shifts_kr_equity_down(tmp_path):
    up = _universe_14(tmp_path)
    macro = _FakeMacro(_FakeRegime("growth_disinflation", 0.5))

    def run(scenario):
        st = _state_14(up, macro)
        st["research_decision"] = ResearchThesis(
            conviction="medium", dominant_scenario=scenario, thesis_md="t")
        node = create_trader_allocator(_FakeStep(BucketTilt()),
                                       _FakeStep(StockSelection(selections={})))
        return node(st)["bucket_target"].weights["b1_kr_equity"]

    assert run("kr_stress") < run("neutral")   # kr_stress 가 한국주식을 낮춤
```

그리고 기존 `test_step_a_prompt_includes_quadrant_anchor_and_signals` 의 `_step_a_prompt(...)` 호출에 `scenario` 인자를 추가하고 scenario 노출을 단정:
```python
    msgs = _step_a_prompt(state, q, "kr_stress", 0.7, "high", anchor, eff)
    text = msgs[0]["content"] + msgs[1]["content"]
    assert q in text
    assert "kr_stress" in text          # scenario 노출
    assert "b3_global_tech" in text
    assert "중국 둔화" in text
    assert "MACRO_X" in text
    assert "tilt" in text.lower()
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/unit/agents/trader/test_trader_allocator.py -q -k "kr_stress or step_a_prompt"`
Expected: FAIL — `_step_a_prompt() takes 6 positional args but 7 given` (현 시그니처) + kr_stress 테스트가 modifier 미적용으로 동일값

- [ ] **Step 3: `_step_a_prompt` 시그니처/본문 + node 배선 수정**

(a) `_step_a_prompt` 에 `scenario` 인자 추가 (현 `def _step_a_prompt(state, quadrant, confidence, conviction, anchor, eff)` → ):
```python
def _step_a_prompt(state, quadrant, scenario, confidence, conviction, anchor, eff) -> list[dict]:
```
그리고 body 의 Regime 라인을 교체:
```python
        f"## Regime: {quadrant} / Scenario: {scenario} "
        f"(confidence {confidence:.2f}), conviction {conviction}\n\n"
```
(나머지 본문 동일.)

(b) import 에 추가:
```python
from tradingagents.skills.portfolio.scenario_anchor import (
    QUADRANT_BASELINE, hard_band, effective_band, project_to_band,
    SCENARIO_MODIFIER, apply_scenario_modifier,
)
```

(c) node Step A 블록에 modifier 단계 삽입 + 프롬프트 scenario 전달 (현 블록 교체):
```python
        quadrant = _resolve_quadrant(state)
        confidence = _resolve_confidence(state)
        rd = state.get("research_decision")
        conviction = (getattr(rd, "conviction", "medium") if rd else "medium") or "medium"
        scenario = (getattr(rd, "dominant_scenario", "neutral") if rd else "neutral") or "neutral"

        q_baseline = QUADRANT_BASELINE[quadrant]
        hard_bands = {b: hard_band(quadrant, b, q_baseline[b]) for b in q_baseline}
        hmin = {b: hard_bands[b][0] for b in hard_bands}
        hmax = {b: hard_bands[b][1] for b in hard_bands}
        anchor = apply_scenario_modifier(q_baseline, scenario, hmin, hmax)   # ← Phase 2 center 이동
        eff = {b: effective_band(anchor[b], hmin[b], hmax[b], confidence, conviction)
               for b in anchor}
        tilt = invoke_structured_obj(
            structured_a,
            _step_a_prompt(state, quadrant, scenario, confidence, conviction, anchor, eff),
            BucketTilt(), "TraderStepA",
        )
        eff_lo = {b: eff[b][0] for b in eff}
        eff_hi = {b: eff[b][1] for b in eff}
        bucket_weights = project_to_band(anchor, tilt.tilts, eff_lo, eff_hi)
        bucket_weights = _clamp_to_pool_capacity(bucket_weights, pool)
```
(이후 Step B/within-bucket/risk/출력 불변.)

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/pytest tests/unit/agents/trader/test_trader_allocator.py -q`
Expected: PASS (신규 kr_stress + 갱신 prompt + 기존 zero-tilt/positive-tilt/valid-vector/smoke 전부)

- [ ] **Step 5: 전체 회귀 + 커밋**

Run: `.venv/bin/pytest tests/unit -q`
Expected: PASS (신규 실패 0)

```bash
git add tradingagents/agents/trader/trader_allocator.py tests/unit/agents/trader/test_trader_allocator.py
git commit -m "feat(stage3): trader node 에 scenario modifier 단계 삽입 + _step_a_prompt scenario 노출 (Phase 2)"
```

---

## Validation (구현 후)

- [ ] **단위/통합:** `.venv/bin/pytest tests/unit -q` 전체 green.
- [ ] **입력 민감도 재측정 (Phase 1 게이트 유지):** Phase 1 archive(`~/.tradingagents/runs/2026-05-15`)로 `.venv/bin/python scripts/measure_stepA_input_sensitivity.py --as-of 2026-05-15 --repeat 3` → Σ x-var stdev 가 Phase 1(0.0885) 대비 악화 없음. (이 archive 의 scenario 는 neutral 일 가능성 높아 modifier no-op → 동일 기대. scenario 가 직교일 때의 효과는 아래 E2E 에서.)
- [ ] **regime×scenario E2E spot-check:** 직교 시나리오가 분류될 만한 날짜로 `.venv/bin/python scripts/run_e2e_test.py --as-of <date>` → validation pass, manager 가 직교 라벨/neutral 을 적절히 분류, modified anchor 가 합리적(예: kr_stress 시 b1_kr_equity 하향).

---

## Self-Review 결과 (작성자 점검)

- **Spec 커버리지:** §2.2 enum+coerce→Task1, §2.4 modifier+apply→Task2, §2.3 manager 프롬프트→Task3, §2.5 node+prompt→Task4, §5 검증→Validation. **갭 없음.**
- **Spec 정합 보정:** spec §2.2 는 per-class `@field_validator` 를 보였으나, 본 plan 은 `Annotated[ScenarioLabel, BeforeValidator(...)]` 로 두 모델에 DRY 하게 부착(동작 동일). spec §4 의 test 영향 목록 보정: `test_portfolio_manager_full_trace` 는 SimpleNamespace mock 이라 **영향 없음**(수정 불필요), 실제 깨지는 건 `test_research_trade_schemas`·`test_research_cluster`(Task1 수정), `test_plan_pipeline_mock` 은 명확성 갱신.
- **Placeholder:** 없음 — 모든 코드/명령/기대출력 구체화.
- **타입 일관성:** `ScenarioLabel`/`_VALID_SCENARIOS`/`apply_scenario_modifier`/`_step_a_prompt(... scenario ...)` 시그니처가 Task 간 일치 확인. `_step_a_prompt` 인자 순서 `(state, quadrant, scenario, confidence, conviction, anchor, eff)` 를 Task4 본문·테스트 양쪽에서 동일 사용.
