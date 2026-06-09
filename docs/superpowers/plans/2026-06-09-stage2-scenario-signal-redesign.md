# Stage 2 시나리오 신호 체계 재설계 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 현 `dominant_scenario`(단일 라벨 5개) + 죽은 `conviction`을 폐기하고, 비중 시프트를 "정량 2(fx·credit, Stage 1 재활용) + 정성 1(risk_tilt, Stage 2 신규)" 신호로 분리한다.

**Architecture:** Stage 1 `macro_report`의 `fx.regime`·`financial_conditions.regime`(이미 산출)을 Stage 3가 직접 읽어 비중 modifier로 쓰고, Stage 2 LLM은 `risk_tilt`(offensive/neutral/defensive)만 종합 판단한다. 세 신호의 bucket delta를 합산해 기존 `project_to_band`로 hard band에 투영한다. 카테고리 cap은 기존 `_repair_all`+Stage 5가 그대로 보장한다(중복 구현 없음).

**Tech Stack:** Python 3, pydantic v2, pytest. 순수 결정론 함수(scenario_anchor) + LangGraph 노드(trader_allocator, research_cluster).

**설계 문서:** `docs/superpowers/specs/2026-06-09-stage2-scenario-signal-redesign-design.md`

---

## File Structure

| 파일 | 책임 | 변경 |
|---|---|---|
| `tradingagents/skills/portfolio/scenario_anchor.py` | baseline→비중 결정론 코어 | SCENARIO_MODIFIER/apply_scenario_modifier 제거, RISK_TILT/CREDIT/FX modifier + apply_macro_modifiers 추가 |
| `tradingagents/schemas/research.py` | Stage 2 스키마 | ResearchThesis/InvestmentThesis에 risk_tilt 추가, dominant_scenario·conviction 제거, ScenarioLabel/ScenarioField 제거 |
| `tradingagents/agents/researchers/research_cluster.py` | bull→bear→manager 종합 | 매니저 프롬프트 risk_tilt 산출 |
| `tradingagents/skills/portfolio/candidate_selector.py` | 종목 선정 | _UNHEDGED_SCENARIOS → fx_regime 기반 prefer_unhedged/prefer_hedged |
| `tradingagents/agents/trader/trader_allocator.py` | Stage 3 Step A 통합 | fx.regime·financial_conditions.regime 읽어 apply_macro_modifiers 호출, risk_tilt 추출, attribution |
| `tradingagents/reports/philosophy.py` | 리포팅 | scenario/conviction → risk_tilt/fx/credit 표시 |

**의존성 순서:** Task 1(scenario_anchor) → Task 2(schemas) → Task 3(research_cluster), Task 4(candidate_selector) → Task 5(trader_allocator 통합) → Task 6(philosophy) → Task 7(회귀).

**비범위:** `bl_views.py`(legacy, force_method=black_litterman 전용), daily `validate_rebalance` category 점검.

---

## Task 1: scenario_anchor — apply_macro_modifiers (3신호 합성)

**Files:**
- Modify: `tradingagents/skills/portfolio/scenario_anchor.py`
- Test: `tests/unit/skills/portfolio/test_scenario_anchor.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/unit/skills/portfolio/test_scenario_anchor.py` 끝에 추가

```python
from tradingagents.skills.portfolio.scenario_anchor import apply_macro_modifiers
from tradingagents.skills.portfolio.gaps_buckets import GROWTH_KEYS, DEFENSIVE_KEYS

def _hb(baseline):
    from tradingagents.skills.portfolio.scenario_anchor import hard_band
    lo = {b: hard_band("growth_disinflation", b, baseline[b])[0] for b in baseline}
    hi = {b: hard_band("growth_disinflation", b, baseline[b])[1] for b in baseline}
    return lo, hi

def test_macro_modifiers_neutral_is_baseline():
    base = QUADRANT_BASELINE["growth_disinflation"]
    lo, hi = _hb(base)
    out = apply_macro_modifiers(base, "neutral", "neutral", "neutral", lo, hi)
    assert out == pytest.approx(base)

def test_macro_modifiers_defensive_cuts_growth():
    base = QUADRANT_BASELINE["growth_disinflation"]
    lo, hi = _hb(base)
    out = apply_macro_modifiers(base, "defensive", "neutral", "neutral", lo, hi)
    g0 = sum(base[b] for b in GROWTH_KEYS)
    g1 = sum(out[b] for b in GROWTH_KEYS)
    assert g1 < g0                                  # 성장 축소
    assert abs(sum(out.values()) - 1.0) < 1e-9      # 합 1

def test_macro_modifiers_credit_crisis_cuts_hy():
    base = QUADRANT_BASELINE["growth_disinflation"]
    lo, hi = _hb(base)
    out = apply_macro_modifiers(base, "neutral", "crisis", "neutral", lo, hi)
    assert out["b9_risk_credit"] < base["b9_risk_credit"]
    assert out["a3_us_rates"] > base["a3_us_rates"]

def test_macro_modifiers_fx_usd_riskoff_lifts_safe_fx():
    base = QUADRANT_BASELINE["growth_disinflation"]
    lo, hi = _hb(base)
    out = apply_macro_modifiers(base, "neutral", "neutral", "usd_risk_off", lo, hi)
    assert out["a4_safe_fx"] > base["a4_safe_fx"]
    assert out["b1_kr_equity"] < base["b1_kr_equity"]

def test_macro_modifiers_strong_defensive_cuts_more():
    base = QUADRANT_BASELINE["growth_disinflation"]
    lo, hi = _hb(base)
    mild = apply_macro_modifiers(base, "defensive", "neutral", "neutral", lo, hi)
    strong = apply_macro_modifiers(base, "strong_defensive", "neutral", "neutral", lo, hi)
    assert sum(strong[b] for b in GROWTH_KEYS) < sum(mild[b] for b in GROWTH_KEYS)
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/skills/portfolio/test_scenario_anchor.py -k macro_modifiers -v`
Expected: FAIL — `ImportError: cannot import name 'apply_macro_modifiers'`

- [ ] **Step 3: 구현** — `scenario_anchor.py`에서 다음을 수정/추가/삭제

import 라인(파일 상단)에 `DEFENSIVE_KEYS` 추가:
```python
from tradingagents.skills.portfolio.gaps_buckets import GROWTH_KEYS, DEFENSIVE_KEYS
```

기존 `SCENARIO_MODIFIER`/`apply_scenario_modifier` 는 **그대로 둔다**(trader_allocator 가 Task 5 전환까지 사용 — Task 7 에서 삭제). 파일 끝에 다음을 **추가**:
```python
# === 매크로 신호 → bucket delta (v1 시드, 튜닝 대상). net≈0, |delta| 작게. ===
# risk_tilt 5단 → 성장버킷 합 조정폭 (regime baseline 대비 위험자산 ±). v1 시드.
RISK_TILT_AMOUNT: dict[str, float] = {
    "strong_offensive": 0.05, "offensive": 0.025, "neutral": 0.0,
    "defensive": -0.025, "strong_defensive": -0.05,
}

CREDIT_MODIFIER: dict[str, dict[str, float]] = {
    "tight":  {"b9_risk_credit": -0.02, "a3_us_rates": 0.02},
    "crisis": {"b9_risk_credit": -0.04, "a3_us_rates": 0.04},
    # easy / neutral → no-op
}

FX_MODIFIER: dict[str, dict[str, float]] = {
    "usd_risk_off": {"a4_safe_fx": 0.03, "b1_kr_equity": -0.03},
    # krw_weak / krw_strong / neutral → 비중 no-op (종목 환헤지로만 작동)
}


def _risk_tilt_delta(baseline: dict[str, float], risk_tilt: str) -> dict[str, float]:
    """regime baseline 대비 위험자산 ±. 성장버킷 합을 amt(baseline 비례) → 방어버킷 비례 역방향."""
    amt = RISK_TILT_AMOUNT.get(risk_tilt, 0.0)
    if amt == 0.0:
        return {}
    gsum = sum(baseline[b] for b in GROWTH_KEYS) or 1.0
    dsum = sum(baseline[b] for b in DEFENSIVE_KEYS) or 1.0
    delta: dict[str, float] = {}
    for b in GROWTH_KEYS:
        delta[b] = amt * baseline[b] / gsum
    for b in DEFENSIVE_KEYS:
        delta[b] = -amt * baseline[b] / dsum
    return delta


def apply_macro_modifiers(
    baseline: dict[str, float], risk_tilt: str, credit_regime: str, fx_regime: str,
    hard_min: dict[str, float], hard_max: dict[str, float],
) -> dict[str, float]:
    """risk_tilt(정성) + credit·fx(정량) 의 bucket delta 를 합산해 hard band 로 투영.

    전부 neutral/normal → baseline 그대로. project_to_band 재사용으로 sum=1·hard band 보장,
    불가 시 baseline fallback.
    """
    delta: dict[str, float] = {}

    def _add(src: dict[str, float] | None) -> None:
        if src:
            for b, d in src.items():
                delta[b] = delta.get(b, 0.0) + d

    _add(_risk_tilt_delta(baseline, risk_tilt))
    _add(CREDIT_MODIFIER.get(credit_regime))
    _add(FX_MODIFIER.get(fx_regime))
    if not delta:
        return dict(baseline)
    return project_to_band(baseline, delta, hard_min, hard_max)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/skills/portfolio/test_scenario_anchor.py -v && python -m pytest tests/unit -q`
Expected: PASS (신규 5개 포함 + 전체 unit 회귀 0 — apply_scenario_modifier 유지로 trader_allocator 안 깨짐)

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/skills/portfolio/scenario_anchor.py tests/unit/skills/portfolio/test_scenario_anchor.py
git commit -m "feat(scenario): SCENARIO_MODIFIER → apply_macro_modifiers (risk_tilt+credit+fx 합성)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: schemas/research — risk_tilt 필드

**Files:**
- Modify: `tradingagents/schemas/research.py`
- Test: `tests/unit/schemas/test_research_thesis.py` (없으면 생성)

- [ ] **Step 1: 실패 테스트 작성** — `tests/unit/schemas/test_research_thesis.py` 생성

```python
from tradingagents.schemas.research import ResearchThesis, InvestmentThesis

def test_research_thesis_defaults_neutral():
    rt = ResearchThesis()
    assert rt.risk_tilt == "neutral"

def test_research_thesis_accepts_risk_tilt():
    rt = ResearchThesis(risk_tilt="defensive", thesis_md="x", key_risks=["a"])
    assert rt.risk_tilt == "defensive"

def test_investment_thesis_risk_tilt():
    it = InvestmentThesis(thesis_md="x", risk_tilt="offensive")
    assert it.risk_tilt == "offensive"
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/schemas/test_research_thesis.py -v`
Expected: FAIL — `risk_tilt` 미정의

- [ ] **Step 3: 구현** — `research.py` 수정

`Literal` 은 이미 `from typing import Annotated, Literal, get_args` 로 import 되어 있다. import·`ScenarioLabel`·`ScenarioField`·`ConvictionLevel`·`_coerce_scenario` 는 **그대로 둔다**(Task 7 에서 정리).

`InvestmentThesis` 에 `risk_tilt` 필드만 추가 (나머지 기존 필드 유지):
```python
class InvestmentThesis(BaseModel):
    """Research Manager(Stage 2) 출력 — bull/bear 종합. structured LLM 타깃."""
    thesis_md: str = Field(max_length=20000)
    risk_tilt: Literal["strong_offensive", "offensive", "neutral", "defensive", "strong_defensive"] = "neutral"
    conviction: ConvictionLevel = "medium"
    dominant_scenario: ScenarioField = "neutral"
    key_risks: list[str] = Field(default_factory=list)
```

`ResearchThesis` 에 `risk_tilt` 필드만 추가 (나머지 기존 필드 유지):
```python
class ResearchThesis(BaseModel):
    """Stage 2 종합 state 객체 (state['research_decision'])."""
    risk_tilt: Literal["strong_offensive", "offensive", "neutral", "defensive", "strong_defensive"] = "neutral"
    conviction: ConvictionLevel = "medium"
    dominant_scenario: ScenarioField = "neutral"
    thesis_md: str = Field(default="", max_length=20000)
    bull_view: str = Field(default="", max_length=20000)
    bear_view: str = Field(default="", max_length=20000)
    key_risks: list[str] = Field(default_factory=list)
    model_config = {"extra": "ignore"}
```

(`ResearchDecision` 클래스는 비범위 — 변경하지 않음.)

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/schemas/test_research_thesis.py -v`
Expected: PASS (3개)

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/schemas/research.py tests/unit/schemas/test_research_thesis.py
git commit -m "feat(schema): ResearchThesis/InvestmentThesis risk_tilt 필드 추가

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: research_cluster — 매니저 프롬프트 risk_tilt 산출

**Files:**
- Modify: `tradingagents/agents/researchers/research_cluster.py`
- Test: `tests/unit/agents/researchers/test_research_cluster.py` (없으면 생성)

- [ ] **Step 1: 실패 테스트 작성** — 해당 경로에 생성/추가

```python
from tradingagents.agents.researchers.research_cluster import create_research_cluster
from tradingagents.schemas.research import InvestmentThesis

class _StubLLM:
    """structured 호출 시 고정 InvestmentThesis 반환하는 mock."""
    def __init__(self, view): self._view = view
    def with_structured_output(self, *a, **k): return self
    def invoke(self, *a, **k): return self._view

def test_research_cluster_outputs_risk_tilt(monkeypatch):
    import tradingagents.agents.researchers.research_cluster as rc
    monkeypatch.setattr(rc, "invoke_structured_obj",
                        lambda *a, **k: InvestmentThesis(thesis_md="t", risk_tilt="defensive", key_risks=["r"]))
    # bull/bear 노드는 텍스트만 반환하도록 단순 stub
    monkeypatch.setattr(rc, "create_bull_researcher", lambda llm: (lambda s: {"bull_view": "B"}))
    monkeypatch.setattr(rc, "create_bear_researcher", lambda llm: (lambda s: {"bear_view": "R"}))
    node = create_research_cluster(object(), object(), object())
    out = node({})
    assert out["research_decision"].risk_tilt == "defensive"
    assert "risk_tilt: defensive" in out["research_debate_summary"]
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/agents/researchers/test_research_cluster.py -v`
Expected: FAIL — fallback/decision 이 `dominant_scenario` 사용 또는 risk_tilt 부재

- [ ] **Step 3: 구현** — `research_cluster.py` 수정

`_MANAGER_SYSTEM` 교체:
```python
_MANAGER_SYSTEM = (
    "당신은 자산배분 팀의 리서치 매니저다. 강세(bull) 리서처와 약세(bear) 리서처의 "
    "주장, 그리고 Stage 1 매크로/리스크/기술적/뉴스 분석을 모두 검토해 균형 잡힌 "
    "투자 판단을 종합한다. 한쪽으로 치우치지 말고 양측 논거의 강도를 평가해 결론을 "
    "내려라. 결과는 thesis_md(한국어 종합 판단), risk_tilt, key_risks 로 구조화하라.\n"
    "risk_tilt: regime baseline 이 정한 위험수준 '대비' 위험자산을 어느 방향·강도로 조정할지.\n"
    "  - strong_offensive: 위험자산 대폭 확대 (강세 논거 압도)\n"
    "  - offensive: 위험자산 소폭 확대\n"
    "  - neutral: regime baseline 유지 (대부분의 경우)\n"
    "  - defensive: 위험자산 소폭 축소\n"
    "  - strong_defensive: 위험자산 대폭 축소 (약세·위험 논거 압도)\n"
    "  ※ 환율·신용 등 정량 신호는 Stage 1 이 별도 처리하므로 여기서 판단하지 말 것."
)
```

`node` 내부 `fallback` 과 `decision`, `summary` 교체:
```python
        fallback = InvestmentThesis(
            thesis_md="(manager 종합 실패 — 중립 유지)", risk_tilt="neutral", key_risks=[],
        )
        thesis = invoke_structured_obj(
            structured_mgr, _manager_prompt(state, bull_view, bear_view),
            fallback, "ResearchManager",
        )

        decision = ResearchThesis(
            risk_tilt=thesis.risk_tilt,
            thesis_md=thesis.thesis_md,
            bull_view=bull_view,
            bear_view=bear_view,
            key_risks=thesis.key_risks,
        )
        summary = (
            f"## Research Thesis\n"
            f"risk_tilt: {decision.risk_tilt}\n"
            f"{decision.thesis_md[:1200]}\n"
            f"key risks: {', '.join(decision.key_risks) or '(none)'}\n"
        )[:2000]
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/agents/researchers/test_research_cluster.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/agents/researchers/research_cluster.py tests/unit/agents/researchers/test_research_cluster.py
git commit -m "feat(research): 매니저 프롬프트 dominant_scenario → risk_tilt 산출

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: candidate_selector — fx.regime 기반 환헤지 선호

**Files:**
- Modify: `tradingagents/skills/portfolio/candidate_selector.py`
- Test: `tests/unit/skills/portfolio/test_candidate_selector.py` (없으면 생성)

- [ ] **Step 1: 실패 테스트 작성**

```python
from tradingagents.skills.portfolio.candidate_selector import regime_selection_prefs

def test_prefs_usd_risk_off_prefers_unhedged():
    short, unhedged, hedged = regime_selection_prefs("growth_disinflation", "usd_risk_off")
    assert unhedged is True and hedged is False

def test_prefs_krw_strong_prefers_hedged():
    short, unhedged, hedged = regime_selection_prefs("growth_disinflation", "krw_strong")
    assert hedged is True and unhedged is False

def test_prefs_neutral_no_fx_pref():
    short, unhedged, hedged = regime_selection_prefs("growth_disinflation", "neutral")
    assert unhedged is False and hedged is False
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/skills/portfolio/test_candidate_selector.py -v`
Expected: FAIL — `regime_selection_prefs` 가 2-tuple 반환 / fx_regime 미지원

- [ ] **Step 3: 구현** — `candidate_selector.py` 수정

`_UNHEDGED_SCENARIOS` 상수 **삭제**. `regime_selection_prefs` 교체:
```python
def regime_selection_prefs(
    quadrant: str | None, fx_regime: str | None,
) -> tuple[bool, bool, bool]:
    """(prefer_short_duration, prefer_unhedged, prefer_hedged). fx.regime 기반."""
    prefer_short = quadrant in _INFLATION_QUADRANTS
    prefer_unhedged = fx_regime in ("krw_weak", "usd_risk_off")
    prefer_hedged = fx_regime == "krw_strong"
    return prefer_short, prefer_unhedged, prefer_hedged
```

`select_representative_candidates` 시그니처에 `fx_regime: str | None = None` 을 **추가**(기존
`dominant_scenario: str | None = None` 파라미터는 미사용으로 **유지** — trader_allocator 가 아직
`dominant_scenario=` 로 호출하므로 제거하면 깨짐. Task 5 에서 호출부 전환, Task 7 에서 파라미터 제거).
본문의 prefs 언패킹과 `_hedge_pen` 교체:
```python
    prefer_short, prefer_unhedged, prefer_hedged = regime_selection_prefs(quadrant, fx_regime)

    def _hedge_pen(t: str) -> int:
        if bucket_key not in _HEDGE_BUCKETS:
            return 0
        h = is_hedged(name.get(t, ""))
        if prefer_unhedged and h:      # 환노출 선호인데 헤지 → 페널티
            return 1
        if prefer_hedged and not h:    # 헤지 선호인데 환노출 → 페널티
            return 1
        return 0
```
(docstring의 `dominant_scenario` 언급을 `fx_regime` 로 갱신.)

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/skills/portfolio/test_candidate_selector.py -v && python -m pytest tests/unit -q`
Expected: PASS (신규 3개 + 전체 회귀 0). dominant_scenario 파라미터 유지로 trader_allocator 호출 안 깨짐.
기존 candidate_selector 테스트가 dominant_scenario 기반 환헤지를 검증하던 것이면 obsolete → fx_regime 으로 갱신.

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/skills/portfolio/candidate_selector.py tests/unit/skills/portfolio/test_candidate_selector.py
git commit -m "feat(candidate): 환헤지 선호를 fx.regime 기반으로 (prefer_unhedged/prefer_hedged)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: trader_allocator — 통합 배선

**Files:**
- Modify: `tradingagents/agents/trader/trader_allocator.py`
- Test: `tests/unit/agents/trader/test_trader_allocator.py`

- [ ] **Step 1: 실패 테스트 작성** — 기존 파일에 추가

```python
def test_allocator_reads_fx_and_credit_and_risk_tilt():
    """mr.fx.regime=usd_risk_off → a4 상승, rd.risk_tilt=defensive → 성장 축소."""
    import types
    from tradingagents.schemas.research import ResearchThesis
    from tradingagents.schemas.portfolio import BucketTilt
    mr = types.SimpleNamespace(
        regime=types.SimpleNamespace(quadrant="growth_disinflation", confidence=0.8),
        fx=types.SimpleNamespace(regime="usd_risk_off"),
        financial_conditions=types.SimpleNamespace(regime="neutral"),
    )
    state = {
        "macro_report": mr,
        "research_decision": ResearchThesis(risk_tilt="defensive", thesis_md="t"),
        "universe_path": "data/universe.json",
        "capital_krw": 100_000_000,
        "cached_tilt": BucketTilt(),     # LLM 우회 (tilt=0)
    }
    node = create_trader_allocator(object())
    out = node(state)
    sa = out["allocation_attribution"]["step_a"]
    assert sa["risk_tilt"] == "defensive"
    assert sa["fx_regime"] == "usd_risk_off"
    assert sa["credit_regime"] == "neutral"
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/agents/trader/test_trader_allocator.py -k fx_and_credit -v`
Expected: FAIL — `apply_macro_modifiers` 미사용 / attribution 에 risk_tilt·fx_regime 부재

- [ ] **Step 3: 구현** — `trader_allocator.py` 수정

import 교체 (라인 31-34 블록):
```python
from tradingagents.skills.portfolio.scenario_anchor import (
    QUADRANT_BASELINE, hard_band, effective_band, project_to_band,
    apply_macro_modifiers,
)
```

`_resolve_quadrant`/`_resolve_confidence` 아래에 helper 추가:
```python
def _resolve_fx_regime(state) -> str:
    mr = state.get("macro_report")
    return getattr(getattr(mr, "fx", None), "regime", None) or "neutral"


def _resolve_credit_regime(state) -> str:
    mr = state.get("macro_report")
    return getattr(getattr(mr, "financial_conditions", None), "regime", None) or "neutral"
```

`node` 내부 Step A 진입부(현 conviction/scenario 추출 + anchor 계산) 교체:
```python
        quadrant = _resolve_quadrant(state)
        confidence = _resolve_confidence(state)
        rd = state.get("research_decision")
        risk_tilt = (getattr(rd, "risk_tilt", "neutral") if rd else "neutral") or "neutral"
        fx_regime = _resolve_fx_regime(state)
        credit_regime = _resolve_credit_regime(state)

        q_baseline = QUADRANT_BASELINE[quadrant]
        hard_bands = {b: hard_band(quadrant, b, q_baseline[b]) for b in q_baseline}
        hmin = {b: hard_bands[b][0] for b in hard_bands}
        hmax = {b: hard_bands[b][1] for b in hard_bands}
        anchor = apply_macro_modifiers(q_baseline, risk_tilt, credit_regime, fx_regime, hmin, hmax)
        eff = {b: effective_band(anchor[b], hmin[b], hmax[b], confidence)
               for b in anchor}
        tilt = state.get("cached_tilt") or invoke_structured_obj(
            structured_a,
            _step_a_prompt(state, quadrant, risk_tilt, fx_regime, credit_regime, confidence, anchor, eff),
            BucketTilt(), "TraderStepA",
        )
```

candidate_selector 호출부(현 `dominant_scenario=scenario`)를 교체:
```python
                name=name_of, quadrant=quadrant, fx_regime=fx_regime,
```

`_step_a_prompt` 시그니처/본문 교체:
```python
def _step_a_prompt(state, quadrant, risk_tilt, fx_regime, credit_regime, confidence, anchor, eff) -> list[dict]:
    rd = state.get("research_decision")
    thesis = getattr(rd, "thesis_md", "") if rd else ""
    key_risks = getattr(rd, "key_risks", []) if rd else []
    fb = state.get("allocation_feedback") or []
    fb_txt = "\n".join(f"  - {getattr(v, 'message', str(v))}" for v in fb)

    anchor_lines = "\n".join(
        f"  {b} ({BUCKET_KR_NAME[b]}): base {anchor[b]:.2f} "
        f"허용[{eff[b][0]:.2f}, {eff[b][1]:.2f}]"
        for b in GAPS_BUCKET_KEYS
    )
    body = (
        f"## Regime: {quadrant} / risk_tilt: {risk_tilt} "
        f"(confidence {confidence:.2f}), fx: {fx_regime}, credit: {credit_regime}\n\n"
        f"## 앵커 baseline + 허용밴드 (이 안에서만 tilt)\n{anchor_lines}\n\n"
        f"## 리서치 종합\n{thesis}\n\n"
        f"## 핵심 리스크\n" + ("\n".join(f"  - {r}" for r in key_risks) or "  (없음)") + "\n\n"
        f"## Stage1 요약\n"
        f"매크로: {state.get('macro_summary','(없음)')}\n"
        f"리스크: {state.get('risk_summary','(없음)')}\n"
        f"기술적: {state.get('technical_summary','(없음)')}\n"
        f"뉴스: {state.get('news_summary','(없음)')}\n\n"
        + (f"## 직전 위반 피드백 (반영 필수)\n{fb_txt}\n\n" if fb_txt else "")
        + "각 버킷의 tilt(앵커 대비 가감)를 출력하라. 0 인 버킷은 생략."
    )
    return [
        {"role": "system", "content": _STEP_A_SYSTEM},
        {"role": "user", "content": body},
    ]
```

`_STEP_A_SYSTEM`의 "① 리스크 예산: conviction·regime …" 문구를 교체:
```python
    "① 리스크 예산: risk_tilt·regime 으로 위험자산 총량 방향(앵커가 이미 ≤70% 지향).\n"
```

attribution `step_a` dict(현 scenario/confidence/conviction) 교체:
```python
            "step_a": {
                "quadrant": quadrant,
                "risk_tilt": risk_tilt,
                "fx_regime": fx_regime,
                "credit_regime": credit_regime,
                "confidence": confidence,
                "tilt_rationale": tilt.rationale,
                "tilt": dict(tilt.tilts),
                "buckets": step_a_buckets,
            },
```

`bucket_target.rationale`(현 `dominant_scenario` 참조, 라인 260 부근) 교체:
```python
            rationale=(f"risk_tilt={risk_tilt} fx={fx_regime} credit={credit_regime}"
                       + f" / risk={risk_pct*100:.1f}%")[:500],
```

(주의: `step_a_buckets` 의 `"scenario_delta"` 키는 그대로 둔다 — anchor−baseline 의미는 유지되고
philosophy 표가 이 키를 읽는다. Task 6에서 라벨만 갱신.)

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/agents/trader/test_trader_allocator.py -v && python -m pytest tests/unit -q`
Expected: PASS (신규 + 기존 + 전체 unit 회귀 0). 기존 테스트가 conviction/scenario 참조로 깨지면 risk_tilt/fx/credit 로 갱신.
(integration eval 테스트는 OpenAI API key 미설정으로 실패하는 환경 문제 — unit 기준으로 판단.)

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/agents/trader/trader_allocator.py tests/unit/agents/trader/test_trader_allocator.py
git commit -m "feat(trader): apply_macro_modifiers 통합 — fx/credit(Stage1)+risk_tilt(Stage2) 배선

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: philosophy — 리포팅 3신호 표시

**Files:**
- Modify: `tradingagents/reports/philosophy.py`
- Test: `tests/unit/reports/test_philosophy.py` (없으면 생성)

- [ ] **Step 1: 실패 테스트 작성**

```python
from tradingagents.reports.philosophy import format_step_a_decomposition, _format_scenario_probs
from tradingagents.schemas.research import ResearchThesis

def test_step_a_decomp_shows_risk_tilt():
    attribution = {"step_a": {
        "quadrant": "growth_disinflation", "risk_tilt": "defensive",
        "fx_regime": "usd_risk_off", "credit_regime": "tight", "confidence": 0.8,
        "tilt_rationale": "r",
        "buckets": {"a1_cash": {"baseline": 0.08, "scenario_delta": 0.0,
                                "tilt_applied": 0.0, "final": 0.08}},
    }}
    out = format_step_a_decomposition(attribution)
    assert "risk_tilt defensive" in out
    assert "fx usd_risk_off" in out

def test_format_scenario_probs_risk_tilt():
    assert "risk_tilt=offensive" in _format_scenario_probs(ResearchThesis(risk_tilt="offensive"))
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/unit/reports/test_philosophy.py -v`
Expected: FAIL — 현 출력이 `Scenario …/conviction …` / `dominant=…`

- [ ] **Step 3: 구현** — `philosophy.py` 수정

`_format_scenario_probs` 교체:
```python
def _format_scenario_probs(rd) -> str:
    """Stage 2 risk_tilt 한 줄 요약."""
    if rd is None:
        return "(none)"
    rt = getattr(rd, "risk_tilt", None) or (
        rd.get("risk_tilt") if isinstance(rd, dict) else None
    ) or "neutral"
    return f"risk_tilt={rt}"
```

`format_step_a_decomposition` 의 헤더 라인(현 `Scenario … conviction …`) 교체:
```python
        f"Regime {sa.get('quadrant', '?')} / risk_tilt {sa.get('risk_tilt', '?')} "
        f"(conf {float(sa.get('confidence', 0)) * 100:.0f}%, "
        f"fx {sa.get('fx_regime', '?')} / credit {sa.get('credit_regime', '?')})",
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/unit/reports/test_philosophy.py -v`
Expected: PASS (2개)

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/reports/philosophy.py tests/unit/reports/test_philosophy.py
git commit -m "feat(report): philosophy scenario/conviction → risk_tilt/fx/credit

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: 회귀 + 잔여 참조 정리

**Files:**
- 전체 (grep으로 잔여 참조 확인)

- [ ] **Step 1: 잔여 참조 검색**

Run: `grep -rn "dominant_scenario\|apply_scenario_modifier\|SCENARIO_MODIFIER\|\.conviction\|_UNHEDGED_SCENARIOS\|ScenarioLabel\|ScenarioField" tradingagents/ --include="*.py" | grep -v "ResearchDecision\|bl_views"`
Expected: 결과 없음(legacy ResearchDecision/bl_views 제외). 남으면 해당 파일 수정.

이 Task 에서 삭제할 것 (각각 grep 으로 다른 사용처 0 확인 후):
- `scenario_anchor.py`: `SCENARIO_MODIFIER`/`apply_scenario_modifier` 정의 (Task 5 전환 후 미사용)
- `research.py`: `InvestmentThesis`/`ResearchThesis` 의 `conviction`·`dominant_scenario` 필드, `ScenarioLabel`/`_VALID_SCENARIOS`/`_coerce_scenario`/`ScenarioField` 정의, orphan 된 import(`Annotated`/`BeforeValidator`/`get_args`). 단 `ConvictionLevel` 은 `ResearchDecision`(legacy)이 참조하면 유지.
- `tests/unit/schemas/test_research_thesis.py` 에 제거 검증 추가: `rt = ResearchThesis(conviction="high", dominant_scenario="kr_boom")` 후 `assert not hasattr(rt, "conviction") and not hasattr(rt, "dominant_scenario")`.

- [ ] **Step 2: 전체 unit 회귀**

Run: `python -m pytest tests/unit -q`
Expected: PASS (기존 1036 + 신규 ~16, 실패 0). 실패 시 해당 테스트가 구 라벨(dominant_scenario/conviction)을 참조하는지 확인하고 risk_tilt/fx/credit으로 갱신.

- [ ] **Step 3: neutral 동작 보존 확인**

Run: `python -m pytest tests/unit/skills/portfolio/test_scenario_anchor.py::test_macro_modifiers_neutral_is_baseline -v`
Expected: PASS — risk_tilt=neutral, credit=neutral, fx=neutral 입력이 baseline과 동일(현 neutral scenario 동작 보존 증명).

- [ ] **Step 4: 커밋**

```bash
git add -A
git commit -m "test(scenario): 잔여 참조 정리 + 전체 회귀 통과 확인

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (작성자 점검 결과)

**1. Spec coverage:**
- §3.1 신호 체계(정량2+정성1) → Task 1·2·5 ✓
- §3.2 스키마(risk_tilt 추가, dominant_scenario/conviction 제거) → Task 2 ✓
- §3.3 비중 매핑(risk_tilt/credit/fx) → Task 1 ✓
- §3.4 종목 환헤지(fx.regime) → Task 4 ✓
- §3.5 합성(apply_macro_modifiers) → Task 1·5 ✓
- §3.6 Stage2 출력/Stage3 입력 → Task 3·5 ✓
- §3.7 category cap(중복 구현 안 함, 회귀로 유지 확인) → Task 7 ✓
- §4 영향 범위 6파일 → Task 1·2·3·4·5·6 전부 커버 ✓
- §6 테스트 전략 → 각 Task의 TDD + Task 7 회귀 ✓

**2. Placeholder scan:** TBD/TODO/"적절히" 없음. 모든 code step에 실제 코드. ✓

**3. Type consistency:**
- `apply_macro_modifiers(baseline, risk_tilt, credit_regime, fx_regime, hard_min, hard_max)` — Task 1 정의 = Task 5 호출 시그니처 일치 ✓
- `regime_selection_prefs` 3-tuple(short, unhedged, hedged) — Task 4 정의 = 본문 언패킹 일치 ✓
- `risk_tilt`/`fx_regime`/`credit_regime` 키 — Task 5 attribution = Task 6 philosophy 읽기 일치 ✓
- `_step_a_prompt(state, quadrant, risk_tilt, fx_regime, credit_regime, confidence, anchor, eff)` — Task 5 정의 = 호출 일치 ✓
