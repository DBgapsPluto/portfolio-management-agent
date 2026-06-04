# Trader Step A — Scenario Modifier (Phase 2)

- **작성일:** 2026-06-03
- **대상:** Stage 3 trader/allocator 구현자
- **선행 의존:** [Phase 1 — quadrant anchor](./2026-06-03-trader-stepA-quadrant-anchor-design.md) (**구현·base 검증 완료**, 입력 민감도 −34%)
- **대상 파일:** `tradingagents/schemas/research.py`, `tradingagents/agents/researchers/research_cluster.py`, `tradingagents/skills/portfolio/scenario_anchor.py`, `tradingagents/agents/trader/trader_allocator.py`

---

## 0. TL;DR

Phase 1은 4개 regime quadrant 로 결정론적 baseline 을 잡고 LLM 이 bounded tilt 만 하게 했다. 그러나 **quadrant 축(성장↔침체 × 인플레↔디스인플레)에 직교하는 패턴**(한국 divergence, 신용경색, 테크 쏠림)은 quadrant baseline 이 표현하지 못한다 — 그건 Phase 1 에서 LLM tilt 에 맡겨져 변동의 원천이 된다.

Phase 2 는 그 직교 패턴을 **결정론적 modifier** 로 인코딩한다: 리서치 매니저가 직교 시나리오를 분류하면, 그 시나리오의 고정 delta 로 **quadrant baseline 의 center 를 옮긴다**(quadrant hard band 안으로 clamp). LLM 은 옮겨진 center 주변에서 tilt 한다.

**사용자 확정 결정:**
1. **enum 범위:** 직교 4개 + neutral 만 — `kr_boom`, `kr_stress`, `global_credit`, `ai_concentration`, `neutral`. (성장/인플레 패턴은 quadrant 가 이미 담당 → 중복 인코딩 안 함.)
2. **합성 방식:** **center 이동** — `modified_baseline = project_to_band(quadrant_baseline, modifier_delta, quadrant_hard_min, quadrant_hard_max)`. 이후 effective_band·LLM tilt·project 는 modified center 기준.
3. **모순 guard:** **구조적 clamp 만** — quadrant hard band 가 modifier 를 가둠. 별도 호환성 매트릭스 없음.
4. **dominant_scenario:** `Literal` enum + **enum 밖 값은 `neutral` 로 coerce**(`@field_validator`) — 구 archive("growth_inflation" 등) hydrate·replay 호환.

**검증:** 단위(neutral no-op, modifier center 이동+hard band 내, coerce-unknown, 모순 quadrant clamp) PASS, 통합(kr_stress → b1_kr_equity↓/b2_dm_core↑) PASS, 입력 민감도 재측정(Phase 1 −34% 유지/개선), regime×scenario E2E spot-check.

---

## 1. 동기 — quadrant 가 못 잡는 직교 패턴

Phase 1 의 4 quadrant 는 성장/인플레 2축이다. 다음은 그 축에 **직교**한다(어느 quadrant 에서도 발생 가능):

| 시나리오 | 의미 | quadrant 로 표현 불가능한 이유 |
|---|---|---|
| `kr_boom` | 한국만 강세 | 글로벌이 어떤 국면이든 한국만 좋을 수 있음 |
| `kr_stress` | 한국만 약세 (KR↓·글로벌↑ divergence) | 글로벌 goldilocks 중에도 한국만 스트레스 가능 |
| `global_credit` | 신용(회사채) 경색 | 크레딧 스프레드는 성장/인플레와 별개로 급변 |
| `ai_concentration` | AI·테크 쏠림 | 테크 리더십은 성장 국면 내에서도 강도가 다름 |

Phase 1 에선 이를 LLM 이 thesis 에서 알아채고 tilt 로 반영해야 한다 — 놓치거나 과반응하면 변동. Phase 2 는 이를 규칙으로 못박아 그 변동을 제거한다.

---

## 2. 설계

### 2.1. 데이터 흐름 (Phase 1 에 한 단계 삽입)

```
quadrant_baseline ─┐
                   ├─► apply_scenario_modifier(scenario)   ← project_to_band 재사용
scenario ──────────┘             │  (quadrant hard band 내 투영)
                                 ▼  modified_baseline (sum=1, hard band 내)
   → effective_band(modified_baseline, confidence, conviction)
   → LLM tilt (BucketTilt)
   → project_to_band(modified_baseline, tilt, eff_min, eff_max)
   → _clamp_to_pool_capacity → bucket_weights
```

modifier 와 LLM tilt 둘 다 `project_to_band` 로 처리(DRY): modifier 는 *quadrant hard band* 로, tilt 는 *effective band* 로 투영. modifier 가 quadrant 한도를 못 벗어나는 게 **구조적 모순 guard**.

### 2.2. 스키마 — `dominant_scenario` enum 화 (`schemas/research.py`)

```python
from typing import Literal, get_args
from pydantic import field_validator

ScenarioLabel = Literal[
    "kr_boom", "kr_stress", "global_credit", "ai_concentration", "neutral",
]
_VALID_SCENARIOS = frozenset(get_args(ScenarioLabel))
```

`InvestmentThesis` 와 `ResearchThesis` 의 `dominant_scenario` 를 `str` → `ScenarioLabel` 로 변경(default 유지 `"neutral"`), 그리고 **enum 밖 값을 neutral 로 coerce** 하는 before-validator 추가(두 모델 동일):

```python
    dominant_scenario: ScenarioLabel = "neutral"

    @field_validator("dominant_scenario", mode="before")
    @classmethod
    def _coerce_unknown_scenario(cls, v):
        # 구 archive / 옛 라벨("growth_inflation" 등) → neutral (modifier 없음). replay 호환.
        return v if v in _VALID_SCENARIOS else "neutral"
```

→ 구 `runs/*/research_decision.json` 의 자유 라벨도 hydrate 시 `neutral` 로 안전 강등(2026-06-03 replay hydration fix 와 함께 replay 완전 정상화).

### 2.3. manager 프롬프트 — 분류 대상 변경 (`research_cluster.py`)

`_MANAGER_SYSTEM` 의 `dominant_scenario` 지시를 교체. 현재는 "전체 레짐 라벨 1개"(quadrant 와 중복)인데, **직교 시나리오 분류**로 좁힌다:

```
dominant_scenario: 아래 직교 시나리오 중 현재 명백히 해당하는 것 하나, 없으면 neutral.
  - kr_boom: 한국만 두드러진 강세
  - kr_stress: 한국만 두드러진 약세(글로벌은 상대적 양호)
  - global_credit: 신용(회사채) 스프레드 급확대·경색
  - ai_concentration: AI·반도체·테크로의 쏠림
  - neutral: 위에 해당 없음 (대부분의 경우)
  ※ 성장/침체·인플레 국면 자체는 별도 macro regime 이 담당하므로 여기에 넣지 말 것.
```

### 2.4. modifier 테이블 + 적용 (`scenario_anchor.py`)

```python
# 직교 시나리오 → {bucket: delta}. 작고 net≈0, |delta| ≤ 0.05 (v1 시드, 튜닝 대상).
# keys ⊆ ScenarioLabel \ {neutral}  (단위테스트로 cross-check)
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

    neutral / 미정의 scenario → baseline 그대로. project_to_band 재사용 → sum=1, hard band 내 보장,
    불가 시 baseline fallback. modifier 가 hard band 를 못 벗어나는 게 구조적 모순 guard.
    """
    delta = SCENARIO_MODIFIER.get(scenario)
    if not delta:
        return dict(baseline)
    return project_to_band(baseline, delta, hard_min, hard_max)
```

> **`ai_concentration` 방향:** "테크 리더십에 기댄다"(테크↑) 로 해석 — 삭제된 BL 룰북 부호와 일치. 반대 해석(집중위험 축소 = 테크↓)을 원하면 delta 부호를 뒤집으면 됨. v1 은 lean-in.

### 2.5. node 배선 (`trader_allocator.py`)

Phase 1 Step A 블록에 modifier 한 단계 삽입 + 프롬프트에 scenario 전달:

```python
        quadrant = _resolve_quadrant(state)
        confidence = _resolve_confidence(state)
        rd = state.get("research_decision")
        conviction = (getattr(rd, "conviction", "medium") if rd else "medium") or "medium"
        scenario = (getattr(rd, "dominant_scenario", "neutral") if rd else "neutral") or "neutral"

        q_baseline = QUADRANT_BASELINE[quadrant]
        bands = {b: hard_band(quadrant, b, q_baseline[b]) for b in q_baseline}
        hmin = {b: bands[b][0] for b in bands}
        hmax = {b: bands[b][1] for b in bands}
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

`_step_a_prompt` 에 `scenario` 인자 추가 — 프롬프트에 `## Regime: {quadrant} / Scenario: {scenario}` 노출(LLM 이 modified anchor 의 맥락을 이해하도록). 나머지(Step B, within-bucket, risk, 출력)는 불변.

`scenario_anchor` import 에 `SCENARIO_MODIFIER, apply_scenario_modifier` 추가.

---

## 3. 에러 처리

- `scenario` = neutral / 미정의 / coerce 됨 → modifier 없음(baseline 그대로).
- 모순 조합(예: quadrant=goldilocks류 × scenario=kr_stress) → modifier 가 quadrant hard band 로 clamp 되어 자동 흡수. 별도 규칙 불필요.
- modifier delta 가 hard band 밖을 가리켜도 `project_to_band` 가 in-band 로 투영(불가 시 baseline).
- Stage 5 validator 가 risk≤70% 등 mandate 최종 검증 — 불변.

---

## 4. 영향 받는 파일

| 파일 | 변경 |
|---|---|
| `tradingagents/schemas/research.py` | `ScenarioLabel` Literal + `_VALID_SCENARIOS`; `InvestmentThesis`·`ResearchThesis` 의 `dominant_scenario` enum 화 + coerce-unknown validator |
| `tradingagents/agents/researchers/research_cluster.py` | `_MANAGER_SYSTEM` dominant_scenario 지시를 직교 시나리오 분류로 교체 |
| `tradingagents/skills/portfolio/scenario_anchor.py` | `SCENARIO_MODIFIER` 테이블 + `apply_scenario_modifier` |
| `tradingagents/agents/trader/trader_allocator.py` | node Step A 에 modifier 단계 삽입; `_step_a_prompt` 에 `scenario` 인자 추가 + 프롬프트 노출; import 확장 |
| `tests/unit/skills/portfolio/test_scenario_anchor.py` | modifier 단위 테스트 추가 |
| `tests/unit/agents/trader/test_trader_allocator.py` | scenario→modifier 통합 테스트 추가 |
| `tests/unit/.../test_research_*.py` | dominant_scenario coerce 테스트 |

---

## 5. 검증

| 단계 | 검증 | 통과 기준 |
|---|---|---|
| **L0 불변식** | modifier 테이블·적용 | `SCENARIO_MODIFIER` keys ⊆ ScenarioLabel\{neutral}; 각 delta `|·|≤0.05`; `apply_scenario_modifier` 결과 sum=1·hard band 내; neutral→baseline 동일 |
| **coerce** | enum 밖 값 강등 | `ResearchThesis(dominant_scenario="growth_inflation").dominant_scenario == "neutral"` |
| **모순 clamp** | 비호환 quadrant | recession quadrant × ai_concentration 적용 시 b3_global_tech 가 그 quadrant hard_max(≈0.10) 초과 안 함 |
| **방향성(통합)** | modifier 효과 | quadrant 고정 시 scenario=kr_stress 가 b1_kr_equity 를 neutral 대비 낮추고 b2_dm_core 를 높임 |
| **입력 민감도(재측정)** | Phase 1 게이트 유지 | `measure_stepA_input_sensitivity.py` Σ x-var stdev 가 Phase 1(0.0885) 대비 악화 없음(직교 패턴 결정론화로 동일/개선 기대) |
| **regime×scenario E2E** | 실데이터 | E2E 정상·validation pass, scenario 분류 그럴듯, modified anchor 합리적 |

---

## 6. 미해결 / 튜닝 파라미터

- `SCENARIO_MODIFIER` delta 값·방향 (v1 시드 → backtest 튜닝)
- `ai_concentration` lean-in vs 집중위험 축소 해석 (v1 = lean-in)
- 직교 시나리오 어휘 확장 여지(late_cycle 등) — 현재 4개로 한정

---

## 7. 범위 밖

- modifier delta 정밀 backtest 튜닝
- Step B(종목 선정) 결정론화 (별도 작업)
- scenario 의 confidence/강도(현재는 on/off; 강도 가중은 미래)
