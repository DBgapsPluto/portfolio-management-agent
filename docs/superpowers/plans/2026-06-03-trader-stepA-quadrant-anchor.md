# Trader Step A — Quadrant Anchor Harness (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Step A(버킷 비중)를 결정론적 quadrant 앵커(baseline + hard band)에서 출발해 LLM이 bounded tilt만 하도록 재구성해, 같은 입력의 run-to-run 변동(드리프트)을 줄인다.

**Architecture:** 신규 `scenario_anchor.py`가 4-quadrant × 14-bucket baseline과 밴드/투영 로직을 보유. LLM Step A는 `BucketTilt`(앵커 대비 sparse delta)를 출력하고, 코드가 `confidence·conviction`로 좁힌 동적 밴드 안으로 박스제약 투영한다. Step B·버킷내 배분·Stage 5 validator는 불변.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, LangGraph state.

**Spec:** [docs/superpowers/specs/2026-06-03-trader-stepA-quadrant-anchor-design.md](../specs/2026-06-03-trader-stepA-quadrant-anchor-design.md)

---

## File Structure

| 파일 | 책임 |
|---|---|
| `tradingagents/skills/portfolio/scenario_anchor.py` | **신규** — `QUADRANT_BASELINE`(4×14), `hard_band`, `effective_band`, `project_to_band` |
| `tradingagents/schemas/portfolio.py` | **추가** — `BucketTilt` |
| `tradingagents/agents/trader/trader_allocator.py` | `_resolve_quadrant/_resolve_confidence`, `_step_a_prompt` 재작성, `node` Step A 해석부 교체 |
| `tests/unit/skills/portfolio/test_scenario_anchor.py` | **신규** — L0 불변식 + L1 sanity + 밴드 + 투영 |
| `tests/unit/agents/trader/test_trader_allocator.py` | Step A 경로 갱신(BucketTilt → 투영), 14-bucket 테스트 universe |
| `scripts/measure_stepA_variance.py` | **신규** — L2 변동성 측정(obsolete `measure_llm_variance.py` 대체) |

> **risk≤70% 주의:** 앵커 baseline은 risk(위험자산 a5+B*) ≤0.70을 *지향*하지만, 밴드 극단에서는 초과 가능. **하드 보장은 기존 Stage 5 validator + D4 retry**가 담당(이 플랜에서 변경 없음). 투영은 risk를 강제하지 않는다.

---

## Task 1: `scenario_anchor.py` — baseline 데이터 + hard band + L0/L1 테스트

**Files:**
- Create: `tradingagents/skills/portfolio/scenario_anchor.py`
- Test: `tests/unit/skills/portfolio/test_scenario_anchor.py`

- [ ] **Step 1: 불변식 + sanity 테스트 작성 (실패 예정)**

```python
# tests/unit/skills/portfolio/test_scenario_anchor.py
import pytest
from tradingagents.skills.portfolio.gaps_buckets import (
    GAPS_BUCKET_KEYS, GROWTH_KEYS, DEFENSIVE_KEYS,
)
from tradingagents.skills.portfolio.scenario_anchor import (
    QUADRANT_BASELINE, hard_band,
)

QUADRANTS = ("growth_inflation", "growth_disinflation",
             "recession_inflation", "recession_disinflation")
RISK_PROXY = ("a5_gold_infl",) + GROWTH_KEYS   # a5 + 모든 성장버킷


@pytest.mark.parametrize("q", QUADRANTS)
def test_baseline_covers_all_14_buckets(q):
    assert set(QUADRANT_BASELINE[q]) == set(GAPS_BUCKET_KEYS)


@pytest.mark.parametrize("q", QUADRANTS)
def test_baseline_sums_to_one(q):
    assert sum(QUADRANT_BASELINE[q].values()) == pytest.approx(1.0, abs=1e-9)


@pytest.mark.parametrize("q", QUADRANTS)
def test_baseline_risk_proxy_at_most_70pct(q):
    risk = sum(QUADRANT_BASELINE[q][b] for b in RISK_PROXY)
    assert risk <= 0.70 + 1e-9


@pytest.mark.parametrize("q", QUADRANTS)
def test_hard_band_brackets_baseline_and_feasible(q):
    base = QUADRANT_BASELINE[q]
    lo = hi = 0.0
    for b, w in base.items():
        hmin, hmax = hard_band(q, b, w)
        assert 0.0 <= hmin <= w <= hmax
        lo += hmin
        hi += hmax
    assert lo <= 1.0 <= hi   # 투영 가능성


def test_l1_growth_tilts_to_growth_camp():
    for q in ("growth_inflation", "growth_disinflation"):
        base = QUADRANT_BASELINE[q]
        assert sum(base[b] for b in GROWTH_KEYS) > sum(base[b] for b in DEFENSIVE_KEYS)


def test_l1_recession_tilts_to_defensive_camp():
    for q in ("recession_inflation", "recession_disinflation"):
        base = QUADRANT_BASELINE[q]
        assert sum(base[b] for b in DEFENSIVE_KEYS) > sum(base[b] for b in GROWTH_KEYS)


def test_l1_inflation_lifts_gold_and_commodity():
    assert (QUADRANT_BASELINE["recession_inflation"]["a5_gold_infl"]
            > QUADRANT_BASELINE["growth_disinflation"]["a5_gold_infl"])
    assert (QUADRANT_BASELINE["growth_inflation"]["b8_cyclical_commodity"]
            > QUADRANT_BASELINE["growth_disinflation"]["b8_cyclical_commodity"])


def test_l1_broad_recession_has_max_duration():
    a3 = {q: QUADRANT_BASELINE[q]["a3_us_rates"] for q in QUADRANTS}
    assert a3["recession_disinflation"] == max(a3.values())
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/unit/skills/portfolio/test_scenario_anchor.py -q`
Expected: FAIL — `ModuleNotFoundError: scenario_anchor`

- [ ] **Step 3: `scenario_anchor.py` 작성 (baseline + hard_band)**

```python
"""Stage 3 trader Step A — quadrant 앵커 (baseline + hard band + 동적 밴드 + 투영).

앵커 key = macro_report.regime.quadrant (4개, 결정론). LLM 은 baseline 대비 tilt 만
하고, 코드가 confidence·conviction 로 좁힌 밴드 안으로 박스제약 투영.

baseline 수치는 v1 시드 (레짐→자산군 로직 + mandate ≤70% 지향 + 옛 BL 부호).
risk≤70% 하드 보장은 Stage 5 validator 담당 — 본 모듈은 강제하지 않는다.
"""
from __future__ import annotations

from typing import Literal

from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS, GROWTH_KEYS

RegimeQuadrant = Literal[
    "growth_inflation", "growth_disinflation",
    "recession_inflation", "recession_disinflation",
]

# quadrant → {bucket_key: baseline}. 각 quadrant 합 == 1.0 (단위테스트 강제).
QUADRANT_BASELINE: dict[str, dict[str, float]] = {
    "growth_disinflation": {
        "a1_cash": 0.08, "a2_kr_rates": 0.08, "a3_us_rates": 0.12,
        "a4_safe_fx": 0.04, "a5_gold_infl": 0.05,
        "b1_kr_equity": 0.11, "b2_dm_core": 0.16, "b3_global_tech": 0.14,
        "b4_china": 0.03, "b5_other_intl": 0.05, "b6_defensive_equity": 0.05,
        "b7_reits": 0.04, "b8_cyclical_commodity": 0.03, "b9_risk_credit": 0.02,
    },
    "growth_inflation": {
        "a1_cash": 0.09, "a2_kr_rates": 0.07, "a3_us_rates": 0.08,
        "a4_safe_fx": 0.07, "a5_gold_infl": 0.12,
        "b1_kr_equity": 0.10, "b2_dm_core": 0.09, "b3_global_tech": 0.11,
        "b4_china": 0.03, "b5_other_intl": 0.04, "b6_defensive_equity": 0.05,
        "b7_reits": 0.03, "b8_cyclical_commodity": 0.09, "b9_risk_credit": 0.03,
    },
    "recession_disinflation": {
        "a1_cash": 0.16, "a2_kr_rates": 0.10, "a3_us_rates": 0.24,
        "a4_safe_fx": 0.10, "a5_gold_infl": 0.10,
        "b1_kr_equity": 0.04, "b2_dm_core": 0.06, "b3_global_tech": 0.04,
        "b4_china": 0.01, "b5_other_intl": 0.02, "b6_defensive_equity": 0.07,
        "b7_reits": 0.02, "b8_cyclical_commodity": 0.02, "b9_risk_credit": 0.02,
    },
    "recession_inflation": {
        "a1_cash": 0.15, "a2_kr_rates": 0.07, "a3_us_rates": 0.10,
        "a4_safe_fx": 0.08, "a5_gold_infl": 0.15,
        "b1_kr_equity": 0.05, "b2_dm_core": 0.06, "b3_global_tech": 0.04,
        "b4_china": 0.02, "b5_other_intl": 0.03, "b6_defensive_equity": 0.08,
        "b7_reits": 0.03, "b8_cyclical_commodity": 0.11, "b9_risk_credit": 0.03,
    },
}

# hard band: baseline 에서의 절대 가감. 침체 quadrant 의 성장버킷은 상단 제한(risk-on 금지).
_BAND_DOWN: float = 0.06
_BAND_UP: float = 0.10
_BAND_UP_RECESSION_GROWTH: float = 0.05


def hard_band(quadrant: str, bucket: str, baseline: float) -> tuple[float, float]:
    """버킷의 절대 외곽 한계 [hard_min, hard_max]. hard_min ≤ baseline ≤ hard_max."""
    up = _BAND_UP
    if quadrant.startswith("recession") and bucket in GROWTH_KEYS:
        up = _BAND_UP_RECESSION_GROWTH
    hmin = round(max(0.0, baseline - _BAND_DOWN), 4)
    hmax = round(baseline + up, 4)
    return hmin, hmax
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/unit/skills/portfolio/test_scenario_anchor.py -q`
Expected: PASS (전 항목)

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/skills/portfolio/scenario_anchor.py tests/unit/skills/portfolio/test_scenario_anchor.py
git commit -m "feat(stage3): scenario_anchor QUADRANT_BASELINE 4x14 + hard_band (Step A Phase 1)"
```

---

## Task 2: `effective_band` — confidence·conviction 동적 latitude

**Files:**
- Modify: `tradingagents/skills/portfolio/scenario_anchor.py`
- Test: `tests/unit/skills/portfolio/test_scenario_anchor.py`

- [ ] **Step 1: 테스트 작성 (실패 예정)**

```python
# test_scenario_anchor.py 에 추가
from tradingagents.skills.portfolio.scenario_anchor import effective_band


def test_effective_band_brackets_baseline():
    # baseline 0.10, hard [0.04, 0.20]
    lo, hi = effective_band(0.10, 0.04, 0.20, confidence=0.8, conviction="high")
    assert 0.04 <= lo <= 0.10 <= hi <= 0.20


def test_low_confidence_low_conviction_narrows_toward_baseline():
    base, hmin, hmax = 0.10, 0.04, 0.20
    lo_lo, hi_lo = effective_band(base, hmin, hmax, confidence=0.05, conviction="low")
    lo_hi, hi_hi = effective_band(base, hmin, hmax, confidence=1.0, conviction="high")
    # 저신뢰·저확신 밴드가 baseline 에 더 가깝다
    assert (base - lo_lo) < (base - lo_hi)
    assert (hi_lo - base) < (hi_hi - base)


def test_high_confidence_high_conviction_reaches_hard_band():
    lo, hi = effective_band(0.10, 0.04, 0.20, confidence=1.0, conviction="high")
    assert lo == pytest.approx(0.04)
    assert hi == pytest.approx(0.20)
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/unit/skills/portfolio/test_scenario_anchor.py -q -k effective_band or narrows or reaches`
Expected: FAIL — `ImportError: cannot import name 'effective_band'`

- [ ] **Step 3: `effective_band` 구현 (scenario_anchor.py 추가)**

```python
CONV_FACTOR: dict[str, float] = {"high": 1.4, "medium": 1.0, "low": 0.6}
LAT_BASE: float = 1.0


def effective_band(
    baseline: float, hard_min: float, hard_max: float,
    confidence: float, conviction: str,
) -> tuple[float, float]:
    """동적 latitude — confidence·conviction 낮으면 baseline 에 수렴.

    half ∈ [~0.24, 1.4]. half≥1 이면 hard band 전체 사용.
    baseline ∈ [eff_min, eff_max] ⊆ [hard_min, hard_max] 항상 성립.
    """
    half = LAT_BASE * (0.4 + 0.6 * max(0.0, min(1.0, confidence))) \
        * CONV_FACTOR.get(conviction, 1.0)
    eff_min = max(hard_min, baseline - (baseline - hard_min) * half)
    eff_max = min(hard_max, baseline + (hard_max - baseline) * half)
    return eff_min, eff_max
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/unit/skills/portfolio/test_scenario_anchor.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/skills/portfolio/scenario_anchor.py tests/unit/skills/portfolio/test_scenario_anchor.py
git commit -m "feat(stage3): effective_band 동적 latitude (confidence·conviction scaling)"
```

---

## Task 3: `project_to_band` — 박스제약 water-filling 투영

**Files:**
- Modify: `tradingagents/skills/portfolio/scenario_anchor.py`
- Test: `tests/unit/skills/portfolio/test_scenario_anchor.py`

- [ ] **Step 1: 테스트 작성 (실패 예정)**

```python
# test_scenario_anchor.py 에 추가
from tradingagents.skills.portfolio.scenario_anchor import project_to_band

_B = {"x": 0.30, "y": 0.30, "z": 0.40}            # baseline (합 1.0)
_LO = {"x": 0.10, "y": 0.10, "z": 0.20}
_HI = {"x": 0.50, "y": 0.50, "z": 0.60}


def test_zero_tilt_returns_baseline():
    out = project_to_band(_B, {}, _LO, _HI)
    assert out == pytest.approx(_B)


def test_result_always_sums_to_one():
    out = project_to_band(_B, {"x": 0.15, "y": -0.05, "z": -0.05}, _LO, _HI)
    assert sum(out.values()) == pytest.approx(1.0, abs=1e-9)
    assert all(_LO[k] - 1e-9 <= out[k] <= _HI[k] + 1e-9 for k in _B)


def test_out_of_band_tilt_is_clamped():
    # x 를 밴드(0.50) 초과로 밀어도 ≤ hard_max, 잔차는 재분배
    out = project_to_band(_B, {"x": 0.40}, _LO, _HI)
    assert out["x"] <= 0.50 + 1e-9
    assert sum(out.values()) == pytest.approx(1.0, abs=1e-9)


def test_net_positive_tilt_redistributed_down():
    # 모든 tilt 가 +라 합>1 → 여유 있는 버킷에서 끌어내려 sum=1 유지
    out = project_to_band(_B, {"x": 0.10, "y": 0.10, "z": 0.10}, _LO, _HI)
    assert sum(out.values()) == pytest.approx(1.0, abs=1e-9)


def test_infeasible_numeric_falls_back_to_baseline():
    # eff_min 합이 1 초과(모순) → baseline 반환
    bad_lo = {"x": 0.40, "y": 0.40, "z": 0.40}
    out = project_to_band(_B, {"x": 0.05}, bad_lo, _HI)
    assert out == pytest.approx(_B)
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/unit/skills/portfolio/test_scenario_anchor.py -q -k project`
Expected: FAIL — `ImportError: cannot import name 'project_to_band'`

- [ ] **Step 3: `project_to_band` 구현**

```python
_EPS: float = 1e-9
_MAX_ITERS: int = 50


def project_to_band(
    baseline: dict[str, float],
    tilts: dict[str, float],
    eff_min: dict[str, float],
    eff_max: dict[str, float],
) -> dict[str, float]:
    """baseline + tilt 를 {sum=1, eff_min≤w≤eff_max} 로 투영. 불가 시 baseline."""
    keys = list(baseline)
    w = {b: min(max(baseline[b] + tilts.get(b, 0.0), eff_min[b]), eff_max[b])
         for b in keys}
    for _ in range(_MAX_ITERS):
        residual = 1.0 - sum(w.values())
        if abs(residual) < _EPS:
            break
        if residual > 0:
            head = {b: eff_max[b] - w[b] for b in keys}
        else:
            head = {b: w[b] - eff_min[b] for b in keys}
        cap = sum(v for v in head.values() if v > 0)
        if cap < _EPS:
            break
        for b in keys:
            if head[b] > 0:
                nw = w[b] + residual * head[b] / cap
                w[b] = min(max(nw, eff_min[b]), eff_max[b])
    if abs(1.0 - sum(w.values())) > 1e-6:
        return dict(baseline)
    return w
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/unit/skills/portfolio/test_scenario_anchor.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/skills/portfolio/scenario_anchor.py tests/unit/skills/portfolio/test_scenario_anchor.py
git commit -m "feat(stage3): project_to_band 박스제약 water-filling 투영"
```

---

## Task 4: `BucketTilt` schema

**Files:**
- Modify: `tradingagents/schemas/portfolio.py` (끝에 추가)
- Test: `tests/unit/skills/portfolio/test_scenario_anchor.py` (스키마 단독 테스트)

- [ ] **Step 1: 테스트 작성 (실패 예정)**

```python
# test_scenario_anchor.py 에 추가
from tradingagents.schemas.portfolio import BucketTilt


def test_bucket_tilt_defaults_empty():
    bt = BucketTilt()
    assert bt.tilts == {}
    assert bt.rationale == ""


def test_bucket_tilt_accepts_sparse_deltas():
    bt = BucketTilt(tilts={"b3_global_tech": 0.04, "b5_other_intl": -0.04})
    assert bt.tilts["b3_global_tech"] == pytest.approx(0.04)
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/unit/skills/portfolio/test_scenario_anchor.py -q -k bucket_tilt`
Expected: FAIL — `ImportError: cannot import name 'BucketTilt'`

- [ ] **Step 3: `BucketTilt` 추가 (`schemas/portfolio.py` 끝)**

```python
class BucketTilt(BaseModel):
    """Trader step A 출력 — quadrant 앵커 대비 버킷별 tilt (sparse, 미지정=0)."""
    tilts: dict[str, float] = Field(
        default_factory=dict,
        description="bucket key → 앵커 대비 가감(+/-). 오버웨이트는 언더웨이트로 펀딩(net≈0).",
    )
    rationale: str = Field(default="", max_length=500)
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/unit/skills/portfolio/test_scenario_anchor.py -q -k bucket_tilt`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/schemas/portfolio.py tests/unit/skills/portfolio/test_scenario_anchor.py
git commit -m "feat(stage3): BucketTilt 스키마 (Step A 앵커 대비 tilt 출력)"
```

---

## Task 5: `_resolve_quadrant` / `_resolve_confidence` 헬퍼

**Files:**
- Modify: `tradingagents/agents/trader/trader_allocator.py`
- Test: `tests/unit/agents/trader/test_trader_allocator.py`

- [ ] **Step 1: 테스트 작성 (실패 예정)**

```python
# test_trader_allocator.py 에 추가 (파일 상단 import 에 합류)
from tradingagents.agents.trader.trader_allocator import (
    _resolve_quadrant, _resolve_confidence,
)


class _FakeRegime:
    def __init__(self, quadrant, confidence):
        self.quadrant = quadrant
        self.confidence = confidence


class _FakeMacro:
    def __init__(self, regime):
        self.regime = regime


def test_resolve_quadrant_reads_macro_report():
    state = {"macro_report": _FakeMacro(_FakeRegime("recession_inflation", 0.7))}
    assert _resolve_quadrant(state) == "recession_inflation"
    assert _resolve_confidence(state) == pytest.approx(0.7)


def test_resolve_quadrant_falls_back_when_missing():
    assert _resolve_quadrant({}) == "growth_disinflation"
    assert _resolve_confidence({}) == pytest.approx(0.1)


def test_resolve_quadrant_rejects_unknown_label():
    state = {"macro_report": _FakeMacro(_FakeRegime("nonsense", 0.5))}
    assert _resolve_quadrant(state) == "growth_disinflation"
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/unit/agents/trader/test_trader_allocator.py -q -k resolve`
Expected: FAIL — `ImportError: cannot import name '_resolve_quadrant'`

- [ ] **Step 3: 헬퍼 구현 (`trader_allocator.py` — import + 함수 추가)**

`trader_allocator.py` 상단 import 블록에 추가:
```python
from tradingagents.skills.portfolio.scenario_anchor import (
    QUADRANT_BASELINE, hard_band, effective_band, project_to_band,
)
from tradingagents.schemas.portfolio import (
    BucketAllocation, StockSelection, BucketTarget, CandidateSet,
    WeightVector, OptimizationMethod, BucketTilt,   # BucketTilt 추가
)
```

`_pool_by_bucket` 아래에 추가:
```python
_VALID_QUADRANTS = set(QUADRANT_BASELINE)
_DEFAULT_QUADRANT = "growth_disinflation"   # macro degraded default 와 일치
_DEGRADED_CONFIDENCE = 0.1


def _resolve_quadrant(state) -> str:
    mr = state.get("macro_report")
    q = getattr(getattr(mr, "regime", None), "quadrant", None)
    return q if q in _VALID_QUADRANTS else _DEFAULT_QUADRANT


def _resolve_confidence(state) -> float:
    mr = state.get("macro_report")
    c = getattr(getattr(mr, "regime", None), "confidence", None)
    return float(c) if isinstance(c, (int, float)) else _DEGRADED_CONFIDENCE
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/unit/agents/trader/test_trader_allocator.py -q -k resolve`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/agents/trader/trader_allocator.py tests/unit/agents/trader/test_trader_allocator.py
git commit -m "feat(stage3): _resolve_quadrant/_confidence — macro_report.regime 읽기 + degraded fallback"
```

---

## Task 6: `_step_a_prompt` 재작성 — 추론 스캐폴드 + 앵커 노출

**Files:**
- Modify: `tradingagents/agents/trader/trader_allocator.py:43-77` (`_STEP_A_SYSTEM`, `_step_a_prompt`)
- Test: `tests/unit/agents/trader/test_trader_allocator.py`

- [ ] **Step 1: 프롬프트 내용 테스트 작성 (실패 예정)**

```python
# test_trader_allocator.py 에 추가
from tradingagents.agents.trader.trader_allocator import _step_a_prompt
from tradingagents.skills.portfolio.scenario_anchor import QUADRANT_BASELINE, hard_band, effective_band


def test_step_a_prompt_includes_quadrant_anchor_and_signals():
    q = "growth_disinflation"
    anchor = QUADRANT_BASELINE[q]
    eff = {b: effective_band(anchor[b], *hard_band(q, b, anchor[b]), 0.7, "high") for b in anchor}
    state = {
        "research_decision": ResearchThesis(
            conviction="high", dominant_scenario="x", thesis_md="강세 논거",
            key_risks=["중국 둔화"]),
        "macro_summary": "MACRO_X", "risk_summary": "r",
        "technical_summary": "t", "news_summary": "n",
        "allocation_feedback": [],
    }
    msgs = _step_a_prompt(state, q, 0.7, "high", anchor, eff)
    text = msgs[0]["content"] + msgs[1]["content"]
    assert q in text                       # regime 노출
    assert "b3_global_tech" in text        # 앵커 버킷 노출
    assert "중국 둔화" in text              # key_risks 노출
    assert "MACRO_X" in text               # Stage1 요약 노출
    assert "tilt" in text.lower()          # tilt 출력 지시
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/unit/agents/trader/test_trader_allocator.py -q -k step_a_prompt`
Expected: FAIL — `_step_a_prompt() takes 1 positional argument but 6 were given` (현 시그니처는 `(state)`)

- [ ] **Step 3: `_STEP_A_SYSTEM` + `_step_a_prompt` 교체**

`trader_allocator.py:43-48` `_STEP_A_SYSTEM` 를 교체:
```python
_STEP_A_SYSTEM = (
    "당신은 자산배분 트레이더다. 주어진 'regime 앵커(baseline)'에서 출발해, "
    "리서치 판단으로 버킷별 tilt(앵커 대비 가감)만 결정한다. 다음 순서로 사고하라:\n"
    "① 리스크 예산: conviction·regime 으로 위험자산 총량 방향(앵커가 이미 ≤70% 지향).\n"
    "② 방어(A1~A5): regime 따라 cash/듀레이션/금·인플레 가감.\n"
    "③ 성장(B1~B9): thesis·key_risks 로 버킷 tilt.\n"
    "④ 자가검증: tilt 는 허용밴드 내, 오버웨이트는 언더웨이트로 펀딩(net≈0).\n"
    "벗어나지 않을 버킷은 tilt 를 생략(=0)하라."
)
```

`trader_allocator.py:63-77` `_step_a_prompt` 를 교체:
```python
def _step_a_prompt(state, quadrant, confidence, conviction, anchor, eff) -> list[dict]:
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
        f"## Regime: {quadrant} (confidence {confidence:.2f}), conviction {conviction}\n\n"
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

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/unit/agents/trader/test_trader_allocator.py -q -k step_a_prompt`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/agents/trader/trader_allocator.py tests/unit/agents/trader/test_trader_allocator.py
git commit -m "feat(stage3): _step_a_prompt 재작성 — 추론 스캐폴드 + 앵커/밴드/구조화 입력 노출"
```

---

## Task 7: `node` Step A 배선 교체 + 기존 trader 테스트 갱신

**Files:**
- Modify: `tradingagents/agents/trader/trader_allocator.py:133-149` (`create_trader_allocator` / `node` Step A 부분)
- Test: `tests/unit/agents/trader/test_trader_allocator.py` (`_universe`/`_state`/기존 3 테스트 갱신)

- [ ] **Step 1: 14-bucket 테스트 universe + Step A 경로 테스트 작성 (실패 예정)**

기존 `_FakeStep`/`_universe`/`_state` 위에 14-bucket universe 헬퍼 추가, 그리고 노드 테스트를 BucketTilt 기준으로 신규 작성:
```python
# test_trader_allocator.py 에 추가
from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS
from tradingagents.schemas.portfolio import BucketTilt


def _universe_14(tmp_path):
    """14버킷 각 2 ETF (anchor 비중이 풀 부족으로 cash 로 쏠리지 않게)."""
    etfs = []
    for k in GAPS_BUCKET_KEYS:
        risk = "안전" if k[0] == "a" else "위험"
        for i in (1, 2):
            etfs.append({
                "ticker": f"T_{k}_{i}", "name": f"{k}{i}", "aum_krw": 100.0 * i,
                "underlying_index": f"idx_{k}_{i}", "bucket": risk,
                "category": "c", "gaps_bucket": k,
            })
    p = tmp_path / "u14.json"
    p.write_text(json.dumps({"version": "t", "etfs": etfs}, ensure_ascii=False))
    return str(p)


def _state_14(universe_path, macro=None):
    return {
        "research_decision": ResearchThesis(conviction="medium",
                                            dominant_scenario="neutral", thesis_md="t"),
        "universe_path": universe_path, "macro_report": macro,
        "macro_summary": "m", "risk_summary": "r",
        "technical_summary": "t", "news_summary": "n",
        "allocation_feedback": [],
    }


def test_zero_tilt_bucket_target_equals_baseline(tmp_path):
    """tilt 없으면 bucket_target == quadrant baseline (풀 충분)."""
    up = _universe_14(tmp_path)
    step_a = _FakeStep(BucketTilt())                       # 빈 tilt
    step_b = _FakeStep(StockSelection(selections={}))      # 코드가 AUM top-N 보충
    node = create_trader_allocator(step_a_llm=step_a, step_b_llm=step_b)
    out = node(_state_14(up))                              # macro 없음 → growth_disinflation
    from tradingagents.skills.portfolio.scenario_anchor import QUADRANT_BASELINE
    base = QUADRANT_BASELINE["growth_disinflation"]
    for b, w in base.items():
        assert out["bucket_target"].weights.get(b, 0.0) == pytest.approx(w, abs=1e-6)


def test_positive_tilt_increases_bucket_weight(tmp_path):
    up = _universe_14(tmp_path)
    step_b = _FakeStep(StockSelection(selections={}))
    base_node = create_trader_allocator(_FakeStep(BucketTilt()), step_b)
    tilt_node = create_trader_allocator(
        _FakeStep(BucketTilt(tilts={"b3_global_tech": 0.06, "b2_dm_core": -0.06})), step_b)
    w0 = base_node(_state_14(up))["bucket_target"].weights["b3_global_tech"]
    w1 = tilt_node(_state_14(up))["bucket_target"].weights["b3_global_tech"]
    assert w1 > w0


def test_node_outputs_valid_weight_vector(tmp_path):
    up = _universe_14(tmp_path)
    node = create_trader_allocator(_FakeStep(BucketTilt()), _FakeStep(StockSelection(selections={})))
    out = node(_state_14(up))
    wv = out["weight_vector"]
    assert wv.method == OptimizationMethod.AUM_WEIGHTED
    assert sum(wv.weights.values()) == pytest.approx(1.0, abs=1e-3)
    assert all(w <= 0.20 + 1e-6 for w in wv.weights.values())
    assert sum(out["bucket_target"].weights.values()) == pytest.approx(1.0, abs=1e-6)
```

**기존 3 테스트 삭제/대체:** `test_trader_produces_weight_vector_and_bucket_target`, `test_trader_normalizes_offsum_bucket_weights`, `test_trader_drops_unknown_bucket_keys` 는 `BucketAllocation` mock + 0.6 단정에 의존하므로 **삭제**(위 신규 3 테스트가 대체). `test_trader_clamps_oversized_thin_pool_bucket` 는 `_clamp_to_pool_capacity` 안전망 테스트로 **유지하되**, `step_a` mock 을 `BucketTilt()` 로 바꾸고 단정을 "crash 없이 sum=1·≤20%" 로 완화(앵커가 b7_reits 를 pool capacity 초과로 밀 수 없으므로 clamp 경로는 직접 함수 테스트로 충분 — 이 테스트는 node smoke 로 남김).

```python
def test_node_smoke_thin_pool_does_not_crash(tmp_path):   # 기존 clamp 테스트 대체
    import json
    etfs = [
        {"ticker": "R1", "name": "리츠1", "aum_krw": 100.0, "underlying_index": "i1",
         "bucket": "위험", "category": "c", "gaps_bucket": "b7_reits"},
        {"ticker": "R2", "name": "리츠2", "aum_krw": 100.0, "underlying_index": "i2",
         "bucket": "위험", "category": "c", "gaps_bucket": "b7_reits"},
        {"ticker": "C1", "name": "현금1", "aum_krw": 100.0, "underlying_index": "i3",
         "bucket": "안전", "category": "c", "gaps_bucket": "a1_cash"},
        {"ticker": "C2", "name": "현금2", "aum_krw": 100.0, "underlying_index": "i4",
         "bucket": "안전", "category": "c", "gaps_bucket": "a1_cash"},
    ]
    p = tmp_path / "u.json"
    p.write_text(json.dumps({"version": "t", "etfs": etfs}, ensure_ascii=False))
    node = create_trader_allocator(_FakeStep(BucketTilt()), _FakeStep(StockSelection(selections={})))
    out = node(_state_14(str(p)))   # must not raise
    wv = out["weight_vector"]
    assert sum(wv.weights.values()) == pytest.approx(1.0, abs=1e-3)
    assert all(w <= 0.20 + 1e-6 for w in wv.weights.values())
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/unit/agents/trader/test_trader_allocator.py -q`
Expected: FAIL — node 가 아직 `BucketAllocation` 경로(`structured_a` 가 BucketAllocation bind, `_step_a_prompt(state)` 1-arg 호출)

- [ ] **Step 3: `create_trader_allocator` Step A 배선 교체**

`trader_allocator.py` `create_trader_allocator` 의 `structured_a` 바인딩과 `node` Step A 해석부 교체:
```python
def create_trader_allocator(step_a_llm, step_b_llm):
    structured_a = bind_structured(step_a_llm, BucketTilt, "TraderStepA")   # was BucketAllocation
    structured_b = bind_structured(step_b_llm, StockSelection, "TraderStepB")

    def node(state):
        uni = _load_universe(state["universe_path"])
        pool = _pool_by_bucket(uni)
        aum = {e.ticker: e.aum_krw for e in uni.etfs}
        risk_flag = {e.ticker: e.bucket for e in uni.etfs}
        valid_tickers = set(aum)

        # --- Step A: quadrant 앵커 + LLM tilt + 투영 ---
        quadrant = _resolve_quadrant(state)
        confidence = _resolve_confidence(state)
        rd = state.get("research_decision")
        conviction = (getattr(rd, "conviction", "medium") if rd else "medium") or "medium"
        anchor = QUADRANT_BASELINE[quadrant]
        bands = {b: hard_band(quadrant, b, anchor[b]) for b in anchor}
        eff = {b: effective_band(anchor[b], bands[b][0], bands[b][1], confidence, conviction)
               for b in anchor}
        tilt = invoke_structured_obj(
            structured_a, _step_a_prompt(state, quadrant, confidence, conviction, anchor, eff),
            BucketTilt(), "TraderStepA",
        )
        bucket_weights = project_to_band(
            anchor, tilt.tilts,
            {b: eff[b][0] for b in eff}, {b: eff[b][1] for b in eff},
        )
        bucket_weights = _clamp_to_pool_capacity(bucket_weights, pool)
        # --- 이후 Step B / within-bucket / risk / 출력: 변경 없음 ---
```
(나머지 `node` 본문 — Step B 보충, `aum_weighted_allocation`, risk, 출력 dict — 은 그대로 유지.)

**고아 정리:** `_normalize_bucket_weights`([trader_allocator.py:103](../../../tradingagents/agents/trader/trader_allocator.py)) 는 본 변경으로 미사용 → **제거**. `BucketAllocation` import 는 다른 호출지 없으면 제거(grep 확인). `_bucket_menu` 가 더는 안 쓰이면 제거.

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/unit/agents/trader/test_trader_allocator.py -q`
Expected: PASS (신규 4 + 갱신 smoke)

- [ ] **Step 5: 전체 회귀 + 커밋**

Run: `pytest tests/unit -q`
Expected: PASS (신규 실패 0; 사전존재 실패는 무시 — 메모리 deferred 항목)

```bash
git add tradingagents/agents/trader/trader_allocator.py tests/unit/agents/trader/test_trader_allocator.py
git commit -m "feat(stage3): trader Step A 배선 교체 — quadrant 앵커+tilt 투영 (BucketAllocation 경로 제거)"
```

---

## Task 8: `scripts/measure_stepA_variance.py` — L2 변동성 측정

**Files:**
- Create: `scripts/measure_stepA_variance.py`
- Delete: `scripts/measure_llm_variance.py` (OBSOLETE 대체)

- [ ] **Step 1: 스크립트 작성**

```python
"""Step A(allocator) 변동성 측정 — 같은 archived state 에 N회 반복, 버킷별 stdev.

measure_llm_variance.py (OBSOLETE, 24-cell factor model 측정용) 대체.

Usage:
    set -a && source .env && set +a
    python scripts/measure_stepA_variance.py --as-of 2026-05-15 --runs 20

앵커 도입 전(현 코드)에서 한 번, Phase 1 후 다시 실행 → bucket stdev 비교(L2 게이트).
"""
from __future__ import annotations

import argparse
import logging
import statistics
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=_ROOT / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--as-of", required=True, help="YYYY-MM-DD (archived run 존재해야 함)")
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--preset", default="db_gaps")
    ap.add_argument("--capital", type=int, default=1_000_000_000)
    args = ap.parse_args()

    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.observability.replay import restore_state, run_stage

    config = dict(DEFAULT_CONFIG)
    graph = TradingAgentsGraph(preset_name=args.preset, config=config)
    state, missing = restore_state(
        as_of_date=args.as_of, stage="allocator",
        universe_path=config["universe_path"], capital_krw=args.capital,
        preset_name=args.preset,
    )
    if missing:
        logger.warning("missing prereq keys: %s", missing)

    samples: dict[str, list[float]] = {}
    for i in range(args.runs):
        result = run_stage(graph, "allocator", dict(state), write_to_archive=False)
        weights = result["bucket_target"].weights
        for b, w in weights.items():
            samples.setdefault(b, []).append(w)
        logger.info("run %d/%d done", i + 1, args.runs)

    print(f"\n=== Step A bucket weight variance ({args.runs} runs, as_of={args.as_of}) ===")
    print(f"{'bucket':<22}{'mean':>8}{'stdev':>8}{'min':>8}{'max':>8}")
    total_std = 0.0
    for b in sorted(samples):
        xs = samples[b]
        sd = statistics.pstdev(xs) if len(xs) > 1 else 0.0
        total_std += sd
        print(f"{b:<22}{statistics.fmean(xs):>8.3f}{sd:>8.3f}{min(xs):>8.3f}{max(xs):>8.3f}")
    print(f"\nΣ bucket stdev = {total_std:.4f}  (낮을수록 결정론적)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 구문/임포트 스모크**

Run: `python -c "import ast; ast.parse(open('scripts/measure_stepA_variance.py').read())"`
Expected: 종료코드 0 (구문 OK)

- [ ] **Step 3: obsolete 스크립트 제거 + 커밋**

```bash
git rm scripts/measure_llm_variance.py
git add scripts/measure_stepA_variance.py
git commit -m "feat(stage3): measure_stepA_variance — Step A 변동성 측정(L2), obsolete measure_llm_variance 대체"
```

---

## Validation — base 검증 게이트 (구현 후 실행)

> 코드 변경 작업(Task 1-8)이 끝난 뒤 실행. L0/L1 은 pytest(자동), L2/L3 은 실데이터+실LLM(수동).

- [ ] **L0/L1 — 자동:** `pytest tests/unit/skills/portfolio/test_scenario_anchor.py tests/unit/agents/trader/test_trader_allocator.py -q` → 전부 PASS.

- [ ] **L2 변동성 (핵심 게이트):**
  1. **before** — *Task 7 구현 전* 커밋에서 `python scripts/measure_stepA_variance.py --as-of <date> --runs 20` 실행해 `Σ bucket stdev` 기록. (또는 `git stash`/이전 커밋 체크아웃 후 측정.)
  2. **after** — Phase 1 구현 후 동일 실행.
  3. **게이트:** after 의 `Σ bucket stdev` 가 before 대비 유의미하게 감소(목표치는 before 측정 후 사용자와 확정). 미달이면 §6 — `LAT_BASE`/`CONV_FACTOR`/밴드 폭 튜닝.

- [ ] **L3 regime 적합성:** 4 quadrant 를 커버하는 과거 날짜들에 대해 `python scripts/run_backtest.py`(independent) 실행 →
  - quadrant 분류가 그럴듯한가
  - Step A `bucket_target` 가 risk≤70%·sum=1, validator 통과(또는 retry 후 통과), crash 0
  - 침체 날짜=방어 우위, goldilocks 날짜=risk-on 우위 직관 부합

- [ ] **L4 (부차, 게이트 아님):** `run_backtest.py` 성과 집계는 방향 참고만 (historical 데이터 품질 한계).

**Phase 1 합격 = L0·L1 PASS + L2 stdev 목표 감소 + L3 정상.** 통과 시 사용자와 Phase 2(scenario modifier) spec 논의.

---

## Self-Review 결과 (작성자 점검)

- **Spec 커버리지:** §2.1 앵커→Task1, §2.2 effective_band→Task2, §2.3 투영+BucketTilt→Task3·4, §2.4 스캐폴드→Task6, §2.5 배선/_resolve→Task5·7, §4 파일/§5 검증→Task8·Validation. **갭 없음.**
- **Spec 정합 보정:** spec §2.1 의 "risk-proxy Σhard_max≤0.70 (근사)" 는 느슨한 밴드로는 불성립 → 테스트는 **baseline risk≤0.70**(`test_baseline_risk_proxy_at_most_70pct`)으로 구현, 하드 보장은 Stage 5 명시. spec 의 데이터 형태 `(baseline, hard_min, hard_max)` 튜플 → `QUADRANT_BASELINE`(baseline만) + `hard_band()` 파생으로 단순화(magic number 감소).
- **Placeholder:** 없음 — 모든 코드/명령/기대출력 구체화.
- **타입 일관성:** `BucketTilt.tilts`, `QUADRANT_BASELINE`, `hard_band`/`effective_band`/`project_to_band` 시그니처가 Task 간 일치 확인.
