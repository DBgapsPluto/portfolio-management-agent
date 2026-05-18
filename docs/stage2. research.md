# Stage 2 — Research (Scenario Estimator + Deterministic Mapping)

> 파이프라인 6 stage 중 두 번째 단계. Stage 1의 4 분석가 요약을 받아 자산배분 가이드 (BucketTarget)를 만든다.

> **Phase 1 재설계**: Bull/Bear 토론 옹호 구조를 폐기. 단일 estimator가 7개 직교 시나리오의 확률을 추정하고, 결정적 매핑 공식이 BucketTarget을 산출.

---

## 1. 한 줄 요약

> **deep_llm 1회 호출로 7개 직교 시나리오의 확률을 추정한 뒤, 사전 정의된 SCENARIO_BUCKETS의 확률 가중 평균으로 BucketTarget을 결정한다. Mandate (위험자산 ≤ 0.70) 안전성은 모든 시나리오가 ≤ 0.70인 선형 invariant로 자동 보장.**

---

## 2. 왜 토론 구조를 폐기했나

### 2.1 기존 Bull/Bear 옹호 구조의 본질적 결함

| 문제 | 설명 |
|---|---|
| **Motivated reasoning** | "결론을 옹호하라"는 task는 LLM이 evidence를 cherry-pick 하게 만든다 |
| **Prior commitment forcing** | `proposed_risk_tilt ≥0.55` (Bull) 같은 강제 prior는 합리적 토론 불가 |
| **Sycophancy 수렴** | 라운드 누적해도 같은 base LLM이므로 진짜 disagreement 측정 불가 |
| **재현성 0** | 매 실행마다 다른 BucketTarget, mandate constraint 위반 시 retry 의존 |
| **감사 불가** | LLM이 weights를 직접 산출 → 왜 0.65인지 단계 추적 어려움 |

### 2.2 Phase 1 디자인 원칙

1. **출력은 시나리오 확률 + 결정적 매핑** — LLM은 확률만, weights는 공식
2. **Advocacy 폐기** — "데이터로 추정하라", 옹호하지 말 것
3. **Mandate-safe invariant** — 모든 SCENARIO_BUCKETS 위험자산 ≤ 0.70 ⇒ 선형 결합 ≤ 0.70 (수학적 보장)
4. **재현 가능** — 동일 시나리오 확률은 동일 weights (결정적 mapper)

---

## 3. 어떤 데이터를 보는가

Stage 1 4 분석가의 `*_summary` 4개를 받는다 (정량 객체는 안 봄 — 사용자 결정).

| 입력 키 | 출처 | 크기 |
|---|---|---|
| `macro_summary` | macro_quant_analyst | ≤2KB markdown |
| `risk_summary` | market_risk_analyst | ≤2KB |
| `technical_summary` | technical_analyst | ≤2KB |
| `news_summary` | macro_news_analyst | ≤2KB |

→ 총 ≤8KB → deep_llm 1회 호출의 컨텍스트로 충분.

---

## 4. 7개 직교 시나리오 정의

### 4.1 직교 차원 4개

| 차원 | Stage 1 측정 도구 | 극단 |
|---|---|---|
| 글로벌 매크로 cycle | macro_quant `regime.quadrant` | growth-disinfl ↔ recession-disinfl |
| 시장 breadth | technical `universe_breadth.regime`, market_risk `breadth_*` | broad ↔ narrow |
| 신용/금융 안정성 | market_risk `systemic_score`, `funding_stress` | stable ↔ crisis |
| KR ↔ Global decoupling | macro_quant `kr_divergence`, market_risk `kr_*` | follow ↔ KR-specific |

### 4.2 7 시나리오

| Scenario | 핵심 특징 | Stage 1 신호 | 인용 사례 |
|---|---|---|---|
| **A. goldilocks** | growth + disinflation, broad | regime=growth_disinflation, breadth=broad_risk_on | 1995, 2017, 2024 초 |
| **B. ai_concentration** | growth + disinflation, narrow | momentum_spread>+15%, breadth=narrow | 2023-2024 mega-cap rally |
| **C. stagflation** | inflation 끈끈 | TIPS>2%, surprise bias=hawkish | 1973-80, 2022 |
| **D. broad_recession** | recession-disinflation, credit-stable | Sahm trigger, yield curve inverted, systemic<6 | 1990-91, 2001 |
| **E. global_credit** | systemic credit crisis | systemic≥8, funding=stress, HY>1000bp | 2008Q4, 2020Q1, 1998 |
| **F. kr_boom** | KR decoupling 호황 | kr_export accelerating, kr_market_tier=small_cap_risk_on | 2017 반도체, 2020Q4 |
| **G. kr_stress** | KR-specific 위기 | kr_yield_curve inverted, kr_corp=stress | 2022 레고랜드, 2023 PF |

페어별 L1 distance ≥ 0.20 (평균 0.45). 시나리오 확률이 조금만 쏠려도 BucketTarget이 의미있게 움직임.

### 4.3 SCENARIO_BUCKETS — Mandate-safe

| Scenario | kr_eq | gl_eq | fx_comm | bond | mmf | 위험자산 |
|---|---:|---:|---:|---:|---:|---:|
| goldilocks | 0.25 | 0.30 | 0.10 | 0.25 | 0.10 | **0.65** |
| ai_concentration | 0.15 | 0.45 | 0.10 | 0.25 | 0.05 | **0.70** |
| stagflation | 0.10 | 0.15 | 0.25 | 0.40 | 0.10 | **0.50** |
| broad_recession | 0.10 | 0.10 | 0.10 | 0.55 | 0.15 | **0.30** |
| global_credit | 0.05 | 0.05 | 0.10 | 0.45 | 0.35 | **0.20** |
| kr_boom | 0.40 | 0.20 | 0.05 | 0.30 | 0.05 | **0.65** |
| kr_stress | 0.05 | 0.30 | 0.10 | 0.45 | 0.10 | **0.45** |

**Invariant**: 모든 시나리오 위험자산 ≤ 0.70  ⇒ 임의 확률 분포의 가중 평균 = $\sum p_i \cdot \text{risk}_i \leq 0.70$ (선형 결합 보장). **자동 mandate 준수**.

모듈 import 시 `_validate()`가 sum=1, 위험자산 ≤ 0.70 자가 검증.

---

## 5. 어떻게 가공하는가 (3 단계)

### 5.1 Estimator (LLM)

`tradingagents/agents/managers/research_manager.py`

```python
prompt = """
당신은 자산배분 시나리오 분석가입니다.
[Scenario 정의 — 7개]
[Stage 1 요약 — 4개]

[추정 규칙]
1. 각 시나리오 확률 ∈ [0,1], 합 = 1.0 (엄격).
2. 각 결정은 위 요약의 구체 수치/regime을 인용. 직관 X.
3. reasoning ≤800자: dominant + 가장 의외인 시나리오를 자세히.
"""
probs: ScenarioProbabilities = deep_llm.invoke(prompt)
```

→ Pydantic `model_validator`가 합 = 1.0을 강제 (lenient 1e-3 tolerance).

### 5.2 Mapper (결정적 함수)

`tradingagents/skills/research/scenario_mapper.py`

```python
def map_probs_to_bucket(probs) -> ResearchDecision:
    accumulator = {asset: 0.0 for asset in BUCKET_ASSETS}
    for scenario, p in probs.as_dict().items():
        for asset, w in SCENARIO_BUCKETS[scenario].items():
            accumulator[asset] += p * w

    normalized = _renormalize(accumulator)  # 부동소수 오차 보정

    dominant = max(probs.as_dict(), key=...)
    conviction = ("high" if max_p ≥ 0.45
                  else "medium" if max_p ≥ 0.30
                  else "low")

    return ResearchDecision(bucket_target, scenario_probs, dominant, ...)
```

→ 완전 결정적. 같은 ScenarioProbabilities = 같은 BucketTarget.

### 5.3 Summary 생성

LLM 추가 호출 없이 결과를 markdown으로 포맷.

```markdown
## Research Decision
Dominant: goldilocks (42.0%, medium conviction)
Scenario probabilities:
  goldilocks         42.0%
  ai_concentration   18.0%
  kr_boom            14.0%
  stagflation         8.0%
  ...

## Bucket Target
국내주식: 22.4%, 해외주식: 28.6%, FX/원자재: 11.7%, 채권: 28.5%, MMF: 8.8%
위험자산 합: 62.7%
근거: Dominant goldilocks 42% (medium). ...
```

---

## 6. 출력 구조

### 6.1 `ResearchDecision` Pydantic 객체

`tradingagents/schemas/research.py`

```python
class ResearchDecision(BaseModel):
    bucket_target: BucketTarget                       # 기존 호환
    scenario_probabilities: ScenarioProbabilities     # 7 확률 + reasoning
    dominant_scenario: ScenarioName                   # max prob
    dominant_probability: float
    conviction: Literal["high", "medium", "low"]      # max_prob 기반
```

### 6.2 State wire (3 키)

```python
return {
    "bucket_target": BucketTarget(...),         # Stage 3-5 호환 (기존)
    "research_decision": ResearchDecision(...), # 신규 superset
    "research_debate_summary": summary,         # LLM-facing (Stage 6 리포트)
}
```

---

## 7. Downstream 영향 / 호환성

| 소비자 | 받는 키 | 비고 |
|---|---|---|
| `portfolio_allocator` (Stage 3) | `bucket_target` | 영향 0 — 기존 동일 |
| `risk_judge` (Stage 4 Plan 4) | `bucket_target`, 향후 `research_decision.conviction` 활용 가능 | conviction=low면 risk_score 가산 가능 |
| `mandate_validator` (Stage 5) | `bucket_target` | 영향 0 |
| 리포트 (Stage 6) | `research_debate_summary`, `research_decision` | 시나리오 분포 narrative |

→ Stage 3/4/5는 무수정. Stage 6만 풍부한 narrative로 업그레이드.

---

## 8. Graceful Degradation

| 실패 | Fallback |
|---|---|
| estimator LLM JSON parse 실패 | `invoke_with_structured_retry(max_retries=1)` 재시도 후 RuntimeError |
| 시나리오 확률 합 ≠ 1.0 | Pydantic validator 거부 → retry |
| `map_probs_to_bucket` 호출 | 부동소수 오차는 `_renormalize`로 자동 보정 |
| BucketTarget 합 ≠ 1.0 | `_renormalize`로 미연 방지, Pydantic validator도 backup |

→ 결정적 매핑이라 mapper 단계 실패는 사실상 불가능.

---

## 9. 비용 비교

| 항목 | Before (Bull/Bear) | After (Phase 1) | 변화 |
|---|---|---|---|
| LLM 호출 수 | 3-7회 (라운드 × Bull/Bear + Manager) | **1회** (deep_llm) | **70% ↓** |
| 코드량 | 205줄 | ~150줄 | 27% ↓ |
| 재현성 | 낮음 | 100% | ✅ |
| Mandate 준수 | LLM 노력 | 자동 (invariant) | ✅ |

---

## 10. 검증 결과

| 항목 | 결과 |
|---|---|
| 단위 테스트 (mapper) | **10 신규 test** — 시나리오 pure match / uniform / mandate invariant / conviction / L1 distance |
| 회귀 테스트 | **461 unit + integration pass** (회귀 0건) |
| 폐기 테스트 | 5 (bull/bear/research_manager old/adaptive_rounds) |
| Integration mock 패치 | 2 (plan_pipeline_mock, 5_28_dry_run) — research_manager 자체 monkeypatch로 5 ETF fixture 호환 |

---

## 11. 향후 로드맵 (Phase 2 / 3)

### Phase 2 (3-perspective ensemble) — Phase 1 운영 후 평가
- Estimator를 3개로 확장 (Q: 정량, M: 매크로, H: historical)
- Disagreement 측정 (시나리오 분산)
- Geometric mean 합성

판단 기준: Phase 1 단일 estimator의 확률 분포 안정성·변동성을 1-2 사이클 측정 후 Phase 2 가치 결정.

### Phase 3 (Critic + Threshold + Calibration)
- Disagreement 큰 시나리오만 Conditional Critic 호출
- max_prob 기반 threshold blending (dominant 우세 시 가중치, 불확실 시 평균)
- Hyperparameter (conviction threshold 0.45/0.30) backtest 튜닝

---

## 12. 파일 매니페스트

| 위치 | 파일 |
|---|---|
| 스키마 | `tradingagents/schemas/research.py` (ScenarioName, ScenarioProbabilities, ResearchDecision) |
| 시나리오 정의 | `tradingagents/skills/research/scenario_definitions.py` (7 시나리오 + SCENARIO_BUCKETS) |
| 결정적 매핑 | `tradingagents/skills/research/scenario_mapper.py` (map_probs_to_bucket) |
| Estimator + summary | `tradingagents/agents/managers/research_manager.py` |
| Sub-graph state | `tradingagents/agents/researchers/debate_state.py` (단순화) |
| Sub-graph builder | `tradingagents/graph/debate_subgraph.py` (`build_invest_debate_subgraph` 1-node) |
| 단위 테스트 | `tests/unit/skills/test_research_scenario_mapper.py` (10 test) |

폐기 파일:
- `tradingagents/agents/researchers/bull_researcher.py`
- `tradingagents/agents/researchers/bear_researcher.py`
- `tests/unit/agents/test_bull_researcher.py`
- `tests/unit/agents/test_bear_researcher.py`
- `tests/unit/agents/test_research_manager.py` (old version)
- `tests/unit/agents/test_invest_debate_state.py`
- `tests/unit/graph/test_debate_adaptive_rounds.py`

Commit: `07e13f0`.
