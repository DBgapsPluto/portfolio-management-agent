# Trader Step A — Harness Engineering (Quadrant Anchor + Reasoning Scaffold)

- **작성일:** 2026-06-03
- **대상:** Stage 3 trader/allocator 구현자
- **선행 의존:** [Stage 2/3 merge — LLM research+trader](./2026-06-02-stage2-3-merge-llm-research-trader-design.md) (현 LLM 2-step trader, `feat/new-llm-based-agent`)
- **대상 파일:** `tradingagents/agents/trader/trader_allocator.py`, `tradingagents/skills/portfolio/` (신규 `scenario_anchor.py`), `tradingagents/schemas/portfolio.py`

---

## 0. TL;DR

현 `trader_allocator.py` Step A는 `thesis_md + conviction`만 받아 **14버킷 비중을 백지에서 LLM이 출력**한다 → 같은 입력에도 run-to-run 변동이 크고(드리프트), 버킷 비중 기준이 흔들린다. 본 spec은 Step A를 **하네스 엔지니어링**으로 재구성한다: LLM 판단은 유지하되, **결정론적 시나리오 앵커(baseline + hard band)에서 출발해 LLM이 bounded tilt만** 하도록 구조화한다.

**사용자 확정 결정:**
1. **결정 분리:** Step A(버킷 비중)는 **LLM 판단 유지 + 하네스**, Step B(종목 선정)는 **결정론 다요소 점수**(별도 작업, 본 spec 범위 외).
2. **앵커 방식:** 옵션2 **hybrid** (quadrant base + scenario modifier) — 단 **본 spec은 Phase 1 = quadrant base only**. scenario modifier는 Phase 2 (base 검증 통과 후 별도 spec).
3. **앵커 key:** `macro_report.regime.quadrant` (4개, **결정론**). 자유텍스트 `dominant_scenario`는 앵커 key로 쓰지 않음.
4. **밴드:** hard band (시나리오별 `[hard_min, hard_max]`) + `confidence·conviction`로 동적 latitude scaling.
5. **tilt 방식:** LLM이 **버킷별 tilt delta**(앵커 대비) 출력 → 코드가 박스제약 투영.

**검증 (base 검증 게이트):** L0 불변식 PASS, L1 앵커 sanity PASS, **L2 변동성: 앵커 전 대비 버킷별 weight stdev 목표 감소(핵심)**, L3 5-regime E2E in-band·risk≤70%·crash 0. 이 게이트 통과 후 Phase 2 진입.

---

## 1. 현재 상태 (ground-truth)

### 1.1. Step A는 백지 LLM 출력

`trader_allocator.py:63-77` `_step_a_prompt`:
```python
return [
    {"role": "system", "content": _STEP_A_SYSTEM},
    {"role": "user", "content": (
        f"## 리서치 종합 (conviction={conviction})\n{thesis}\n\n"
        f"## 14 버킷\n{_bucket_menu()}\n\n"
        + (피드백)
        + "각 버킷 key 에 0~1 비중을 배정(합 1.0). 위험자산 ≤70% 준수."
    )},
]
```
→ 입력은 `thesis_md`(LLM 산문) + `conviction`(enum)뿐. 출력은 14개 비중을 자유롭게. **앵커·밴드·구조화된 신호 없음.**

### 1.2. 이미 손 안에 있는데 안 쓰는 구조화 신호

`state`에 다음이 **Stage 3까지 전달**되지만 Step A가 미사용:

| 필드 (경로) | 타입 | 신뢰도 |
|---|---|---|
| `macro_report.regime.quadrant` | `Literal[growth_inflation, growth_disinflation, recession_inflation, recession_disinflation]` ([macro.py:9](../../../tradingagents/schemas/macro.py)) | **결정론** |
| `macro_report.regime.confidence` | `float [0,1]` | **결정론** |
| `macro_report.regime.drivers` | `list[str]` (1~5) | 결정론 |
| `research_decision.conviction` | `Literal[high, medium, low]` | 신뢰(enum) |
| `research_decision.dominant_scenario` | `str` (default `"neutral"`) | ⚠️ **자유텍스트** (Phase 1 미사용) |
| `research_decision.thesis_md` / `bull_view` / `bear_view` | `str ≤20000` | LLM 산문 |
| `research_decision.key_risks` | `list[str]` | LLM |
| `macro/risk/technical/news_summary` | `str ≤2KB` | Stage 1 |
| `allocation_feedback` | `list[Violation]` | 결정론 (retry) |

`macro_report`는 `Optional[MacroReport]` 상태 필드로 보존됨 ([agent_states.py:33](../../../tradingagents/agents/utils/agent_states.py)).

### 1.3. 변하지 않는 것 (Phase 1 범위 밖, 그대로 유지)

- 14-bucket taxonomy ([gaps_buckets.py](../../../tradingagents/skills/portfolio/gaps_buckets.py))
- Step B 종목 선정 (현 LLM — 별도 작업에서 결정론화)
- 버킷내 AUM water-filling ([within_bucket.py](../../../tradingagents/skills/portfolio/within_bucket.py))
- `_clamp_to_pool_capacity`, `realized_risk_weight`, Stage 5 validator + D4 retry 루프

---

## 2. 설계

### 2.1. 신규 모듈 `scenario_anchor.py`

`gaps_buckets.py` 패턴의 typed 데이터 모듈. quadrant별 14버킷 `(baseline, hard_min, hard_max)`:

```python
RegimeQuadrant = Literal[
    "growth_inflation", "growth_disinflation",
    "recession_inflation", "recession_disinflation",
]

# quadrant → {bucket_key: (baseline, hard_min, hard_max)}
# 불변식 (단위테스트 강제):
#   Σ baseline == 1.0
#   hard_min ≤ baseline ≤ hard_max  (모든 버킷)
#   Σ hard_min ≤ 1 ≤ Σ hard_max     (가능성)
#   risk-proxy 버킷(A5 + B*) Σ hard_max ≤ 0.70 설계  (※근사 — 실제 risk는 per-ETF
#     위험/안전 플래그 기준이라 버킷 레벨은 지향치. 하드 보장은 Stage 5 validator)
QUADRANT_ANCHOR: dict[str, dict[str, tuple[float, float, float]]] = { ... }
```

**v1 시드 — `growth_disinflation` (goldilocks류, risk-on, 검증: Σ=1.00, risk=0.68):**

| 버킷 | baseline | hard_min | hard_max |
|---|---|---|---|
| a1_cash | 0.08 | 0.03 | 0.18 |
| a2_kr_rates | 0.08 | 0.02 | 0.16 |
| a3_us_rates | 0.12 | 0.04 | 0.22 |
| a4_safe_fx | 0.04 | 0.00 | 0.10 |
| a5_gold_infl | 0.05 | 0.00 | 0.12 |
| b1_kr_equity | 0.11 | 0.02 | 0.22 |
| b2_dm_core | 0.16 | 0.06 | 0.26 |
| b3_global_tech | 0.14 | 0.04 | 0.26 |
| b4_china | 0.03 | 0.00 | 0.10 |
| b5_other_intl | 0.05 | 0.00 | 0.12 |
| b6_defensive_equity | 0.05 | 0.00 | 0.12 |
| b7_reits | 0.04 | 0.00 | 0.10 |
| b8_cyclical_commodity | 0.03 | 0.00 | 0.10 |
| b9_risk_credit | 0.02 | 0.00 | 0.08 |

**나머지 3 quadrant — `growth_disinflation` 대비 구조적 tilt (정확한 4×14 수치는 구현 시 확정, 불변식 테스트가 Σ=1.0 보장):**

- **`growth_inflation`** (overheating): 실물 ↑ (a5_gold_infl≈0.09, b8_cyclical_commodity≈0.09), 듀레이션 ↓ (a3_us_rates≈0.10), 테크 소폭 ↓. risk≈0.68.
- **`recession_disinflation`** (broad recession): 방어 ↑↑ (a1_cash≈0.15, a3_us_rates 듀레이션≈0.22), 성장 ↓↓ (b3_global_tech `hard_max≈0.10`). risk≈0.30.
- **`recession_inflation`** (stagflation): 금·원자재 ↑↑ (a5_gold_infl≈0.14, b8≈0.10), 주식 ↓ (b1/b2/b3 낮게), 듀레이션 중립. risk≈0.50 (대부분 실물).

> 모든 baseline 수치는 **v1 시드**다. 근거: ① 레짐→자산군 로직(성장↔침체=위험총량, 인플레↔디스인플레=듀레이션 vs 실물), ② mandate(risk≤70%·single20%) 사전 충족, ③ 삭제된 BL 기대수익률 테이블([bl_views.py](../../../tradingagents/skills/portfolio/bl_views.py) 과거본) 부호 cross-check. 실데이터 튜닝은 §5.

### 2.2. 동적 latitude (밴드 폭 scaling)

hard band는 **절대 외곽 한계**. LLM의 실제 tilt 여유는 `confidence·conviction`으로 좁힌다:

```python
CONV_FACTOR = {"high": 1.4, "medium": 1.0, "low": 0.6}
LAT_BASE = 1.0  # 튜닝

def effective_band(baseline, hard_min, hard_max, confidence, conviction):
    # confidence 낮으면 baseline에 붙임
    half = LAT_BASE * (0.4 + 0.6 * confidence) * CONV_FACTOR[conviction]
    span = (hard_max - hard_min)
    eff_min = max(hard_min, baseline - half * span / 2)
    eff_max = min(hard_max, baseline + half * span / 2)
    return eff_min, eff_max
```

- `baseline ∈ [eff_min, eff_max] ⊆ [hard_min, hard_max]` 항상 성립.
- `Σ baseline == 1` 이고 `eff_min ≤ baseline ≤ eff_max` 이므로 `Σ eff_min ≤ 1 ≤ Σ eff_max` → **투영 항상 가능**(fallback은 수치적 예외만).
- 저confidence·저conviction → 밴드가 baseline로 수렴(드리프트 최소). 고confidence·고conviction → 넓게(판단 표현).

### 2.3. tilt 메커니즘 (T2 — sparse delta + 박스제약 투영)

**LLM 출력 = 앵커 대비 tilt delta** (벗어나려는 버킷만, 나머지 0):

```python
# schemas/portfolio.py 신규
class BucketTilt(BaseModel):
    """Step A 출력 — quadrant 앵커 대비 버킷별 tilt (sparse, 미지정=0)."""
    tilts: dict[str, float] = Field(default_factory=dict,
        description="bucket key → 앵커 대비 가감(+/-). 오버웨이트는 언더웨이트로 펀딩(net≈0).")
    rationale: str = Field(default="", max_length=500)
```

**투영 (box-constrained water-filling, `within_bucket`·`_clamp_to_pool_capacity` 패턴 재사용):**

```python
def project_to_band(baseline, tilts, eff_min, eff_max):
    w = {b: clip(baseline[b] + tilts.get(b, 0.0), eff_min[b], eff_max[b]) for b in baseline}
    for _ in range(MAX_ITERS):
        r = 1.0 - sum(w.values())
        if abs(r) < EPS: break
        # 필요 방향으로 여유 있는 버킷에 잔차 비례 분배
        head = {b: (eff_max[b]-w[b]) if r > 0 else (w[b]-eff_min[b]) for b in w}
        cap = sum(v for v in head.values() if v > 0)
        if cap < EPS: break
        for b in w:
            if head[b] > 0:
                w[b] = clip(w[b] + r * head[b]/cap, eff_min[b], eff_max[b])
    if abs(1.0 - sum(w.values())) > TOL:
        return dict(baseline)   # 수치적 fallback (baseline은 정의상 sum=1·in-band)
    return w
```

### 2.4. 추론 스캐폴드 (프롬프트)

`_step_a_prompt` 재작성. 시스템 메시지에 **4단계 결정 절차** 명시 + 사용자 메시지에 **구조화된 입력 + 앵커 + 동적 밴드** 제시:

```
[system] 너는 자산배분 트레이더다. 주어진 'regime 앵커'에서 출발해, 리서치 판단으로
  버킷별 tilt(가감)만 결정한다. 다음 순서로 사고하라:
   ① 리스크 예산: conviction·regime 으로 위험자산 총량 방향 (앵커가 이미 ≤70% 반영)
   ② 방어(A1~A5): regime 따라 cash/듀레이션/금·인플레 가감
   ③ 성장(B1~B9): thesis·key_risks 로 버킷 tilt
   ④ 자가검증: tilt 는 밴드 내, 오버웨이트는 언더웨이트로 펀딩(net≈0)
[user]
  ## Regime: {quadrant} (confidence {confidence})  drivers: {drivers}
  ## Conviction: {conviction}
  ## 앵커 baseline + 허용밴드 (이 안에서만 tilt)
    {bucket}: base {baseline} 허용[{eff_min}, {eff_max}]
    ...
  ## 리서치 종합\n{thesis_md}
  ## 핵심 리스크\n{key_risks}
  ## Stage1 요약 (macro/risk/technical/news)\n{summaries}
  ## 직전 위반 피드백 (있으면)\n{allocation_feedback}
  각 버킷의 tilt(앵커 대비 가감)를 출력하라. 벗어나지 않을 버킷은 생략(=0).
```

### 2.5. 노드 배선 변경 (`trader_allocator.py` `node`)

```python
# 변경: Step A 출력 해석부 (현 _normalize_bucket_weights(ba.weights) 경로 대체)
quadrant = _resolve_quadrant(state)            # macro_report.regime.quadrant; None→neutral default
confidence = _resolve_confidence(state)        # regime.confidence; None→0.1 (degraded)
conviction = getattr(rd, "conviction", "medium")
anchor = QUADRANT_ANCHOR[quadrant]
eff = {b: effective_band(*anchor[b], confidence, conviction) for b in anchor}
tilt = invoke_structured_obj(structured_a, _step_a_prompt(state, quadrant, eff, anchor),
                             BucketTilt(), "TraderStepA")
bucket_weights = project_to_band({b: anchor[b][0] for b in anchor}, tilt.tilts,
                                 {b: eff[b][0] for b in eff}, {b: eff[b][1] for b in eff})
bucket_weights = _clamp_to_pool_capacity(bucket_weights, pool)   # 기존 유지
# 이후 Step B / within-bucket / risk / validator: 변경 없음
```

- `_resolve_quadrant`: `macro_report` None이거나 staleness degraded면 **`growth_disinflation`**(macro 분석가의 degraded default와 일치, [macro_quant_analyst.py:220](../../../tradingagents/agents/analysts/macro_quant_analyst.py)) 사용.
- `BucketAllocation` schema는 보존(다른 호출지 호환); Step A 출력만 `BucketTilt`로 교체.

---

## 3. 범위 밖 (roadmap)

- **Phase 2 (별도 spec):** scenario modifier. `dominant_scenario`를 `Literal` enum으로 제약(`InvestmentThesis` schema + manager 프롬프트) + **직교 시나리오만**(kr_boom/kr_stress/global_credit/ai_concentration) bucket modifier delta. quadrant×scenario 모순 guard. **base 검증 게이트 통과 후 착수.**
- **Step B 결정론화 (별도 작업):** `score = AUM(주축) + 업력(listed_since) + sub_category 적합도`, underlying_index dedup, `N=ceil(w/0.20)(+다양화)`. LLM Step B 제거.

---

## 4. 영향 받는 파일

| 파일 | 변경 |
|---|---|
| `tradingagents/skills/portfolio/scenario_anchor.py` | **신규** — `QUADRANT_ANCHOR`, `effective_band`, `project_to_band` |
| `tradingagents/schemas/portfolio.py` | **추가** — `BucketTilt` |
| `tradingagents/agents/trader/trader_allocator.py` | `_step_a_prompt` 재작성, `node` Step A 해석부 교체, `_resolve_quadrant/_confidence` 추가 |
| `tests/unit/skills/portfolio/test_scenario_anchor.py` | **신규** — L0 불변식 + L1 sanity + 투영 |
| `tests/unit/agents/trader/test_trader_allocator.py` | Step A 경로 갱신 (tilt→투영) |
| `scripts/measure_stepA_variance.py` | **신규** (obsolete `measure_llm_variance.py` 대체) — L2 |

---

## 5. 검증 (base 검증 게이트)

순서: **스펙 → 구현 → base 검증(게이트) → Phase 2**. 앵커가 코드에 있어야 변동성 측정 가능.

| 단계 | 검증 | 도구 | 통과 기준 |
|---|---|---|---|
| **L0 불변식** | 기계 정확성 (LLM 무관) | `pytest test_scenario_anchor.py` | quadrant별 Σbaseline=1.0; hard_min≤baseline≤hard_max; Σhard_min≤1≤Σhard_max; 위험버킷 Σhard_max≤0.70. 투영: in-band tilt 보존·sum=1, 이탈 clamp, 잔차분배 수렴, 수치 예외→baseline |
| **L1 앵커 sanity** | 경제적 타당성 | 관계 assert | camp 합(`GROWTH_KEYS` vs `DEFENSIVE_KEYS`, [gaps_buckets.py](../../../tradingagents/skills/portfolio/gaps_buckets.py))으로: growth_*는 성장camp>방어camp, recession_*는 방어camp>성장camp; recession_inflation a5_gold_infl > growth_disinflation a5; recession_disinflation a3_us_rates(듀레이션) 최대. BL 부호 cross-check |
| **L2 ⭐ 변동성** | **드리프트 감소(핵심 목표)** | `scripts/measure_stepA_variance.py` + `replay_stage.py` | 동일 archived state에 Step A N회(≥20) 반복 → 버킷별 weight stdev. **앵커 전 baseline 측정 → Phase1 후 목표 비율 감소**(목표치는 before 측정 후 확정) |
| **L3 regime 적합성** | 실데이터 합리성 | `run_backtest.py` (independent, 5 날짜) | 4 quadrant 커버 날짜에서 quadrant 분류 그럴듯, Step A in-band·risk≤70%·crash 0, 침체=방어/goldilocks=risk-on 직관 부합 |
| L4 성과 (부차) | 수익/리스크 | `run_backtest.py` 성과 | **게이트 아님** — historical 데이터 품질 한계로 방향 참고만 |

**Phase 1 합격 = L0·L1 PASS + L2 stdev 목표 감소 + L3 5날짜 정상.** 통과 시 Phase 2 spec 착수.

---

## 6. 미해결 / 튜닝 파라미터

- 4×14 baseline/hard band 정확값 (v1 시드 → `anchor` 실데이터 튜닝)
- `LAT_BASE`, `CONV_FACTOR`, latitude 공식 형태
- L2 stdev 목표 감소율 (before 측정 후 확정)
- `_resolve_quadrant` degraded fallback이 `growth_disinflation`로 맞는지 (대안: 중립 전용 baseline 추가)
