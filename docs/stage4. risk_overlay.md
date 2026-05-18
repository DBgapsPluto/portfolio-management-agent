# Stage 4 — Risk Overlay (3 lens + severity gate + 2차 optimization)

> 파이프라인 6 stage 중 네 번째 단계. Stage 3가 산출한 1차 `WeightVector`에 runtime risk override를 적용해 mandate-safe하면서도 시장 충격에 즉시 반응하는 final weight를 산출. 결과는 Stage 5 (Validator)로 전달.

> **Phase 1/2 재설계 (Stage 1·2·3 정신 완전 일관)**:
> - **Phase 1** — WeightAdjustment.delta(LLM이 weight 직접 산출) 폐기 → RiskOverlay(LLM은 제약만, optimizer가 풀이) 도입.
> - **Phase 2** — Stage 3.5 PortfolioNumerics + 3 deterministic lens + severity-gated aggregation.

---

## 1. 한 줄 요약

> **Stage 3 weight + Stage 1·2 정량 입력으로 portfolio-level risk metric(HHI/CVaR/cluster)을 사전 계산하고, 3개 lens(tail_risk / concentration / macro_conditional)가 deterministic threshold로 RiskOverlay를 산출 → severity-gated 합의로 단일 overlay → Stage 3 optimizer를 2차 호출해 mandate-safe하게 적용. LLM 호출 0회.**

---

## 2. 왜 재설계했나

### 2.1 폐기한 두 가지 안티패턴

**(1) `WeightAdjustment.delta` — LLM이 weight 직접 산출**

```python
class WeightAdjustment(BaseModel):
    delta: dict[str, float] = ...  # ticker → -0.05~+0.05
```

→ Stage 3가 mandate-safe(20% cap + bucket sum)하게 풀어놓은 결과를 LLM이 후처리로 깨뜨릴 위험. Stage 2 Bull/Bear 폐기 사유와 같은 결함:
- mandate 위반 가능성
- 재현성 0
- 감사 어려움

**(2) Aggressive / Conservative / Neutral debator (3-way advocacy)**

```python
# aggressive_debator.py
AGGRESSIVE_PROMPT = "Push for HIGHER conviction. Argue for concentration on highest-momentum bets."
```

→ Stage 2 Bull/Bear와 같은 강제 옹호 패턴:
- Motivated reasoning
- Sycophancy 수렴
- 진짜 disagreement 측정 불가

### 2.2 Phase 1/2 디자인 원칙

| 원칙 | 적용 |
|---|---|
| **LLM은 제약을 만들고 optimizer가 풀이** | RiskOverlay = constraint만, Stage 3 optimizer가 mandate-safe 풀이 |
| **Advocacy 폐기** | 3 lens는 *측면 측정* (옹호 X) |
| **Multi-round 회피** | 단일 흐름 (debate round X) |
| **Stage 5와 책임 분리** | Stage 4는 weight 조정, mandate 강제 검증은 Stage 5 |
| **무한 루프 회피** | Stage 4는 1회만, D4 retry는 Stage 3 2차에서만 |
| **자유 텍스트 차단** | LensConcern Pydantic 구조화 강제 |

---

## 3. 어떤 데이터를 보는가

### 3.1 Input — state에서 읽는 키

| Key | 출처 | 사용처 |
|---|---|---|
| `weight_vector` | Stage 3 (1차) | numerics 계산 + overlay 적용 베이스 |
| `candidate_set` | Stage 3 | sector_mapper (bucket constraint 변환) |
| `bucket_target` | Stage 2 | bucket sum constraint baseline |
| `research_decision.dominant_scenario` | Stage 2 estimator | macro_conditional lens 입력 |
| `research_decision.conviction` | Stage 2 estimator | macro_conditional lens 입력 (low → 보수) |
| `risk_report.systemic_score` | Stage 1 market_risk | tail_risk lens |
| `risk_report.vix_term.regime` | Stage 1 market_risk Tier-1 | tail_risk lens |
| `risk_report.funding_stress.regime` | Stage 1 market_risk Tier-2 | tail_risk lens |
| `macro_report.regime.quadrant` | Stage 1 macro_quant | macro_conditional lens |
| `technical_report.correlation_clusters` | Stage 1 technical | cluster_exposure 계산 (numerics) |
| `as_of_date` | config | returns matrix fetch + archive 키 |

→ Stage 4는 외부 fetch가 **단 한번** (returns matrix, 그것도 Stage 3가 이미 캐시한 것 재사용). 모든 다른 입력은 in-memory state.

---

## 4. 어떻게 가공하는가 (6 단계)

```
Stage 3 1차 WeightVector + Stage 1·2 정량 객체
                    │
                    ▼
[1] returns matrix fetch (Stage 3 ParquetCache hit)
                    │
                    ▼
[2] Stage 3.5: compute_portfolio_numerics (LLM 없음)
                    │
       ┌────────────┼────────────┐
       ▼            ▼            ▼
[3a] tail_risk  [3b] concen-  [3c] macro_
   _lens          tration       conditional
   (det.)        _lens (det.)   _lens (det.)
       │            │            │
       └────────────┴────────────┘
                    ▼
[4] severity-gated aggregation → 단일 RiskOverlay
                    │
                    ▼
[5] overlay.is_empty()?
       ├─ Yes → Stage 3 weight 그대로 통과
       └─ No  → apply_risk_overlay (Stage 3 2차 호출)
                    │
                    ▼
[6] archive (runs/{date}/risk_overlay.json 등)
```

### 4.1 Stage 3.5 PortfolioNumerics (LLM 없음)

`tradingagents/skills/risk/portfolio_metrics.py`

```python
@register_skill("compute_portfolio_numerics", category="risk")
def compute_portfolio_numerics(weight_vector, returns, clusters) -> PortfolioNumerics:
    # 집중도
    hhi               = Σ w_i²
    top1_weight       = max(w)
    top3_weight_sum   = sum(sorted(w, reverse=True)[:3])

    # Cluster 노출
    cluster_exposure[cid]  = Σ w_i for i in cluster.members
    max_cluster_exposure   = max(cluster_exposure.values())

    # Tail risk (historical simulation)
    pf_returns         = w @ returns
    realized_vol_60d   = std(pf_returns.tail(60))
    var_95_1d          = np.percentile(-pf_returns, 95)   # 양수 = 손실
    cvar_95_1d         = mean(losses[losses >= var_95])

    return PortfolioNumerics(...)
```

**기존 Stage 1·2·3 미커버 차원**:
- **HHI / top-N**: 우리 portfolio 자체의 집중도 (Stage 1은 시장 PCA만)
- **cluster_exposure**: Stage 1 correlation_clusters에 대한 우리 weight 노출
- **CVaR / VaR**: portfolio 1-day 95% 손실 (historical sim)

이 차원이 lens들의 정량 evidence로 직접 사용.

### 4.2 3 deterministic lens

LLM 호출 없이 threshold + preset overlay template으로 결정. 각 lens는 *특정 정량 차원*에 집중 → motivated reasoning 회피.

#### Tail risk lens (`agents/risk_lens/tail_risk_lens.py`)

```python
# threshold (보수적 초기값, Phase 3 calibration 예정)
critical: CVaR ≥ 4% OR systemic ≥ 9 OR (VIX backwardation AND funding stress)
high:     CVaR ≥ 3% OR systemic ≥ 8 OR VIX backwardation OR funding stress
medium:   CVaR ≥ 2.5% OR systemic ≥ 7
low:      CVaR ≥ 2% OR systemic ≥ 6
none:     else

# preset overlay
critical: risk_asset_multiplier = 0.6
high:     risk_asset_multiplier = 0.75
medium:   risk_asset_multiplier = 0.9
low/none: empty
```

#### Concentration lens (`concentration_lens.py`)

```python
critical: HHI > 0.20 OR max_cluster > 0.50 OR top1 > 0.19
high:     HHI > 0.15 OR max_cluster > 0.40 OR top3 > 0.50
medium:   HHI > 0.12 OR max_cluster > 0.30
low:      HHI > 0.10
none:     else

# preset overlay
critical: weight_ceilings = {top-2 ticker: 0.15}, cluster_caps = {top-1: 0.30}
high:     weight_ceilings = {top-1: 0.17}, cluster_caps = {top-1: 0.35}
medium:   cluster_caps = {top-1: 0.40}
low/none: empty
```

#### Macro-conditional lens (`macro_conditional_lens.py`)

```python
# 현재 weight × dominant_scenario / conviction / regime mismatch 검사
critical:  dominant=global_credit AND risk_asset_weight > 0.30
high:      (broad_recession OR kr_stress) AND systemic>7 AND risk>0.45
           OR dominant=global_credit AND risk>0.20
           OR recession_regime AND risk>0.65
medium:    conviction=low AND risk>0.60
           OR recession_regime AND risk>0.55
           OR (broad_recession OR kr_stress) AND risk>0.50
none:      else

# preset overlay
critical: risk_asset_multiplier = 0.65
high:     risk_asset_multiplier = 0.80
medium:   risk_asset_multiplier = 0.92
```

→ Stage 1·2·3와 *직교*하는 차원:
- Stage 3는 *시나리오로부터 weight 생성*
- macro_conditional은 *생성된 weight가 현재 상태에 적합한가 사후 검증*

### 4.3 Severity-gated aggregation

`tradingagents/skills/risk/severity_aggregator.py`

```python
# 보수적 초기값 (Phase 3 backtest calibration 예정)
n_critical ≥ 2  → strength 1.0 (full)
n_critical = 1  → 0.7
n_high     ≥ 2  → 0.5
n_high     = 1  → 0.3
n_medium   ≥ 2  → 0.2
else            → empty (archive only)
```

**머지 룰** (3 lens deltas → 단일 overlay, strength 적용):

| 필드 | 머지 방식 |
|---|---|
| `weight_ceilings` | 가장 엄격 (min). strength로 0.20에서 ceiling 사이 보간 |
| `cluster_caps` | 가장 엄격 (min) |
| `risk_asset_multiplier` | 가장 defensive (min). strength=0.3 → 1.0에서 multiplier 사이 보간 |
| `tail_hedge_floor` | 가장 강력 (max). strength로 곱셈 |

**예시**: tail high (mult=0.7), conc high (mult=0.8) → strength 0.5 (high≥2)
- tail blended: `1.0 - (1-0.7)×0.5 = 0.85`
- conc blended: `1.0 - (1-0.8)×0.5 = 0.90`
- final: min = **0.85** (가장 defensive 채택)

### 4.4 RiskOverlay → Stage 3 optimizer constraint 변환

`tradingagents/agents/allocator/overlay_apply.py:apply_risk_overlay`

```python
def apply_risk_overlay(weight_vector_1, overlay, candidates, returns,
                      bucket_target, method) -> WeightVector:
    if overlay.is_empty():
        return weight_vector_1

    try:
        return _solve_with_overlay(...)         # 1차 시도: 풀 강도
    except (InfeasibleError, OptimizationFailure):
        try:
            return _solve_with_overlay(_half_strength(overlay))  # 2차: 절반 강도
        except:
            return weight_vector_1              # 최종: 1차 그대로 (overlay 무시)
```

**Constraint 변환**:

| RiskOverlay 필드 | Stage 3 optimizer 변환 |
|---|---|
| `risk_asset_multiplier` | `_shrink_bucket_by_multiplier` — bucket_target 재정규화 (위험자산 ↓, bond/mmf ↑) |
| `weight_ceilings[ticker]` | EfficientFrontier `add_constraint(w[i] <= ceiling)` |
| `tail_hedge_floor[ticker]` | EfficientFrontier `add_constraint(w[i] >= floor)` |
| `cluster_caps[cluster_id]` | (Phase 2 wire 보류 — cluster ID ↔ ticker 매핑 별도) |

**HRP 처리**: HRP는 `sector_constraints` 미지원이라 overlay 적용 시 **MIN_VARIANCE로 swap**. Stage 3 1차 결과는 HRP라도 OK.

### 4.5 Mandate 자동 보장

다음 invariant들이 결합되어 **2차 결과도 mandate-safe**:
1. `risk_asset_multiplier ∈ [0.5, 1.0]` (Pydantic validator)
2. `weight_ceilings ≤ 0.20` (단일 cap)
3. EfficientFrontier `weight_bounds=(0, 0.20)` 강제
4. `add_sector_constraints(bucket_lower, bucket_upper)` 강제
5. infeasible 시 fallback이 1차 결과 (이미 mandate-safe)

→ Phase 2 unit test가 모든 분기에서 단일 자산 ≤ 0.20 + sum=1.0 검증.

### 4.6 Archive (Phase 3 패턴)

```python
risk_judge = archive_wrap_node(
    create_risk_judge(quick, deep),
    ["risk_overlay", "weight_vector", "risk_debate_summary"],
)
# → runs/{date}/risk_overlay.json
#    runs/{date}/weight_vector.json   (Stage 4 갱신 시 덮어쓰기)
#    runs/{date}/risk_debate_summary.json
```

Stage 4 결과 trace + Phase 3 향후 signal persistence용.

---

## 5. RiskOverlay 스키마 (Phase 1 핵심 디자인)

```python
class RiskOverlayDelta(BaseModel):
    """단일 lens가 제안하는 overlay 부분 — Judge가 머지."""
    weight_ceilings:        dict[str, float] = {}     # ticker → max
    cluster_caps:           dict[str, float] = {}     # cluster_id → max sum
    risk_asset_multiplier:  float = 1.0               # ∈ [0.5, 1.0]
    tail_hedge_floor:       dict[str, float] = {}     # ticker → min

class LensConcern(BaseModel):
    lens:               Literal["tail_risk","concentration","macro_conditional"]
    level:              Literal["none","low","medium","high","critical"]
    proposed_overlay:   RiskOverlayDelta
    evidence:           str (≤300)                    # 정량 수치 인용 강제

class RiskOverlay(StalenessAware):
    # Constraint (final merged)
    weight_ceilings, cluster_caps, risk_asset_multiplier, tail_hedge_floor
    # Provenance
    severity_decision:  str (≤200)
    strength_applied:   float ∈ [0, 1]
    lens_concerns:      list[LensConcern]              # archive용 raw 출력
```

핵심 차이 (vs 폐기된 `WeightAdjustment.delta`):
- `delta`: LLM이 ticker별 weight 산출 → **dangerous**
- `RiskOverlay`: LLM은 *제약*만, optimizer가 weight 풀이 → **safe**

---

## 6. 출력 구조

### 6.1 state wire

```python
return {
    "weight_vector":      WeightVector(...),     # Stage 3 1차 또는 2차 (덮어쓰기)
    "risk_overlay":       RiskOverlay(...),      # 신규 (lens_concerns 포함)
    "portfolio_numerics": PortfolioNumerics(...),# 신규 (HHI/CVaR/cluster)
    "risk_debate_summary": str (≤2000),
}
```

### 6.2 LLM-facing `risk_debate_summary` (예시)

```markdown
## Risk Overlay
Lens decisions:
  tail_risk: high — CVaR_95_1d=3.24%, systemic_score=8.2, vix_term=flat, funding=elevated
  concentration: medium — HHI=0.133, top1=14.5%, top3_sum=42.1%, max_cluster=32.5%
  macro_conditional: high — risk_asset_weight=58.2%, scenario=broad_recession, conviction=medium, systemic=8.2, regime=recession_disinflation

Severity: high ≥2 consensus (n=2) → 50% strength
Strength applied: 0.50
multiplier=0.85, ceilings=0, floors=0
Weight vector updated by 2nd allocator.
```

→ Bull/Bear가 아닌 Stage 6 리포트 + Stage 5 validator가 활용. 1.5KB 정도.

---

## 7. Downstream 영향 / 호환성

| 소비자 | 받는 키 | 영향 |
|---|---|---|
| Stage 5 Validator | `weight_vector` (Stage 4 갱신) | 영향 0 — 동일 schema |
| Stage 6 Portfolio Manager | `weight_vector`, `risk_overlay`, `portfolio_numerics` | 신규 정보 활용 가능 |
| D4 retry cycle | 변경 없음 | Stage 4는 1회만, retry는 Stage 3 2차에서만 |
| 리포트 | `risk_debate_summary` + `runs/{date}/risk_overlay.json` | 풍부한 trace |

---

## 8. Graceful Degradation

| 실패 | Fallback |
|---|---|
| `weight_vector` / `candidate_set` / `bucket_target` 없음 | `RiskOverlay.no_concerns()` 즉시 반환 (no-op) |
| returns matrix fetch 실패 | empty overlay + summary 메시지 |
| lens 호출 실패 | 해당 lens만 level=none으로 polyfill (다른 lens는 계속) |
| `apply_risk_overlay` 1차 infeasible | half_strength로 2차 시도 |
| half_strength도 infeasible | **1차 WeightVector 그대로 반환 + rationale에 로그** |
| Stage 1 정량 객체 없음 (systemic_score 등) | 안전 기본값 (5.0 / contango / calm) |

→ Stage 4가 실패해도 Stage 3 결과는 보존. 파이프라인 절대 안 죽음.

---

## 9. 비용 / 복잡도 비교

| 항목 | Before (advocacy stub) | After (Phase 1+2) |
|---|---|---|
| **Stage 4 LLM 호출 (매일)** | 0 (stub) | **0회** (deterministic) |
| **실제 동작** | weight_vector 그대로 통과 (no-op) | **lens 평가 + overlay 적용** |
| **mandate 안전성** | Stage 3에 의존 | overlay → constraint → 자동 보장 |
| **재현성** | 100% (no-op) | **100%** (deterministic) |
| **감사 가능성** | 없음 (no-op) | **완전** (lens evidence + severity decision) |
| **극단 시장 대응** | 없음 (Stage 3 결과만) | **즉시 defensive shift** (systemic≥9 등) |
| **코드량** | ~170 LOC (dead) + stub 4줄 | ~1,930 LOC active |

→ 사용자 원안의 "quick LLM × 3 + deep × 1" 대비 LLM 0회. Phase 3에서 lens evidence narrative LLM 보강은 옵션.

---

## 10. 검증 결과

| 항목 | 결과 |
|---|---|
| 단위 테스트 | **562 passing** (회귀 0건) |
| 신규 unit test (Phase 1+2) | **+36 신규** (overlay/numerics/severity/3 lens) |
| Integration | 4 passing (subgraph isolation, phase1 smoke, plan pipeline, 5_28 dry run) |
| 폐기 테스트 | 2 (test_risk_debaters, test_risk_debate_state) |

### 핵심 invariant 검증
- 모든 분기에서 단일 자산 ≤ 0.20 + sum=1.0 (post-condition assert)
- `risk_asset_multiplier ∈ [0.5, 1.0]` Pydantic validator
- 5가지 severity 분기 모두 unit test (critical×2/critical×1/high×2/high×1/medium×2)
- 3 lens × 4 level 분기 (none/low/medium/high/critical) 모두 unit test
- Infeasibility fallback chain (primary → half → 1st) test

---

## 11. Stage 1 / 2 / 3 / 4 디자인 일관성

| 항목 | Stage 1 | Stage 2 | Stage 3 | Stage 4 |
|---|---|---|---|---|
| LLM 사용 (매일) | quick + subagents | deep 1회 (시나리오) | **0회** | **0회** |
| 결정 방식 | LLM + 결정적 mix | 시나리오 확률 → 결정적 매핑 | 결정적 함수 | **결정적 룰 + optimizer** |
| Mandate | 입력 검증 | invariant | weight_bounds + sector | overlay → optimizer constraint |
| Archive | runs/{date}/{report}.json | research_decision.json | candidate/weight/method.json | **overlay/weight/summary.json** |
| Stage 1·2·3 미커버 차원 | (분석가 본진) | 시나리오 통합 | sub_category | **HHI / CVaR / cluster / macro mismatch** |

→ Stage 4 도입 후에도 Stage 1·2·3 정신과 완전 일관. 모든 stage가 *LLM은 좁은 영역, 결정적 룰이 핵심*.

---

## 12. Phase 누적 결과

| Phase | 작업 | 효과 | Commit |
|---|---|---|---|
| Baseline | risk_debate_stub (실제 동작 X) + advocacy 코드 미연결 (~170 LOC dead) | mandate는 Stage 3에 의존 | (pre-existing) |
| **Phase 1** | `WeightAdjustment.delta` 폐기 → `RiskOverlay` 도입, advocacy 코드 삭제 (Aggressive/Conservative/Neutral + sub-graph), stub → 실제 risk_judge no-op placeholder, `apply_risk_overlay` (overlay → constraint → 2차 optimization + infeasibility fallback), Stage 4 archive | 인프라 완비 (실제 동작은 Phase 2까지 empty overlay) | `0910e9c` |
| **Phase 2** | `Stage 3.5 PortfolioNumerics` (HHI/CVaR/cluster) + 3 deterministic lens + severity-gated aggregation + risk_judge wire 완성 | 실제 risk override 동작 — 시장 극단 시 자동 defensive | `37b601d` |

**총 변화**:
- Stage 4 LLM: 0회 (stub과 동일하지만 *실제 동작* 차이)
- 신규 코드: ~1,930 LOC active
- 폐기 코드: ~170 LOC (advocacy + sub-graph builder)
- 신규 test: 36개
- 회귀: 0건

---

## 13. 운영 절차

매일 운영에서 Stage 4는 **완전 자동**. 코드 변경 없이:
1. Stage 1·2·3 출력이 state에 있음 → Stage 4 자동 실행
2. lens 모두 level=none/low → empty overlay → Stage 3 weight 그대로 통과
3. 어떤 lens라도 medium+ → severity gate 발동 → 2차 optimization

**개입이 필요한 경우 (Phase 3)**:
- 60일 운영 후 lens가 너무 자주 발동 → threshold 완화
- 너무 드물게 발동 → threshold 강화
- backtest로 strength 룰 calibration

---

## 14. 파일 매니페스트

| 위치 | 파일 |
|---|---|
| 노드 (judge) | `tradingagents/agents/managers/risk_judge.py` (Phase 2 wire) |
| 3 lens | `tradingagents/agents/risk_lens/{tail_risk, concentration, macro_conditional}_lens.py` |
| Overlay 변환 + 2차 optimization | `tradingagents/agents/allocator/overlay_apply.py` |
| Stage 3.5 numerics | `tradingagents/skills/risk/portfolio_metrics.py` |
| Severity aggregator | `tradingagents/skills/risk/severity_aggregator.py` |
| 스키마 | `tradingagents/schemas/risk_overlay.py` (RiskOverlay, LensConcern, RiskOverlayDelta) |
| State 필드 | `tradingagents/agents/utils/agent_states.py` (`risk_overlay`, `portfolio_numerics`) |
| Graph wire | `tradingagents/graph/trading_graph.py:risk_judge` (archive_wrap_node) |
| 단위 테스트 | `tests/unit/agents/{test_overlay_apply, test_risk_lenses}.py`, `tests/unit/skills/{test_risk_portfolio_metrics, test_risk_severity_aggregator}.py`, `tests/unit/schemas/test_risk_overlay.py` |
| Integration | `tests/integration/test_risk_subgraph_isolation.py` (Phase 2) |

---

## 15. 디자인 의사결정 기록

### 왜 advocacy 토론 폐기?

기존 `aggressive_debator.py:AGGRESSIVE_PROMPT` = "Push for HIGHER conviction. Argue for concentration on highest-momentum bets." → Stage 2 Bull/Bear 폐기 사유와 같은 *prior commitment forcing*. lens 측면 측정으로 대체.

### 왜 LLM 호출 0회?

사용자 원안은 "quick × 3 + deep × 1". 우리는 lens들이 *deterministic threshold + preset overlay template*로 결정. 이유:
1. Stage 1·2·3가 이미 풍부한 정량 신호 제공 (CVaR, systemic_score, scenario 등)
2. LLM이 lens마다 1회 호출 → motivated reasoning 위험 잔존
3. 60일 시뮬에서 LLM의 nuance가 영향 미미 (사용자 Stage 3 분석과 동일 논리)
4. 재현성·감사 가능성·비용 모두 deterministic이 우월

→ Phase 3에서 lens evidence narrative LLM 보강은 옵션 (decision은 여전히 deterministic).

### 왜 log_boost가 아닌 multiplier?

Stage 3 sub_category boost는 `log(boost)` 가산 (부호 안전). Stage 4는 multiplier × bucket weight (선형). 이유:
- Stage 3: factor score (음수 가능)에 boost 가산 → log
- Stage 4: bucket weight (항상 양수)에 직접 적용 → multiplier 직관

### 왜 strength_applied로 보간?

`severity = high(1)` → strength 0.3. 이 때 lens가 제안한 multiplier=0.7 → blended `1.0 - (1-0.7)×0.3 = 0.91`. 즉 30% 강도로만 적용.

이유: severity gate가 *얼마나 많은 lens가 동시에 신호를 보냈는가*를 반영. 단일 lens만 신호 → 보수적으로만 적용 (false positive 위험). 다중 합의 → 강하게.

### 왜 HRP는 overlay 적용 시 MIN_VARIANCE로 swap?

`HRPOpt`는 pypfopt의 sector_constraints 미지원. 우리 `apply_risk_overlay`는 EfficientFrontier 기반. HRP method 선택된 경우라도 overlay 발동 시 더 풍부한 constraint 처리 가능한 MIN_VARIANCE로 자연 fallback.

→ Phase 3에서 HRP-with-constraints 별도 구현 가능 (현재 우선순위 낮음).

### 왜 cluster_caps Phase 2에서 wire 보류?

cluster_id ↔ ticker 매핑 별도 state가 필요 (Stage 1 `correlation_clusters`에서 members 추출). concentration lens가 `cluster_caps` 제안은 하지만 실제 constraint 변환은 Phase 3에서 wire 예정. 현재는 HHI/top-N/multiplier로 충분.

---

## 16. 향후 로드맵 (Phase 3, 선택적)

### Phase 3 옵션들 — 운영 후 (5/28 이후) 평가

**A. Threshold backtest calibration**
- 60일 운영 데이터로 lens threshold 검증 (너무 빈번? 너무 드물?)
- severity gate strength 룰 fine-tune

**B. Signal persistence**
- 같은 lens가 N일 연속 같은 level → 1단계 자동 승격
- Phase 3 archive 활용

**C. Lens evidence narrative LLM 보강**
- decision은 deterministic 유지
- `LensConcern.evidence`만 quick_llm으로 풍부화 (Stage 6 리포트용)

**D. cluster_caps 실제 wire**
- Phase 2 보류분 — `add_constraint(Σ w_i for i in cluster ≤ cap)`

**E. BL views 자동 생성**
- Stage 2 `ScenarioProbabilities` → 자산군 expected return 매핑
- Stage 3 method=BL일 때 활성화

각 phase는 baseline (Phase 1+2)에 대한 **선택적 확장**. 모두 LLM 사용을 최소화하면서 정량 측정 풍부화 방향.
