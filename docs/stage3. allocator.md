# Stage 3 — Portfolio Allocator (완전 함수화 + 시나리오 친화 종목 선정)

> 파이프라인 6 stage 중 세 번째 단계. Stage 2가 결정한 BucketTarget (5 자산군 비중) 안에 실제 ETF 종목을 어떻게 채울지 결정. 결과는 `WeightVector` (ticker → weight)로 Stage 4 (Risk Judge) → Stage 5 (Validator) → Stage 6 (Portfolio Manager)에 전달.

> **Phase A/B/C 재설계 (Stage 1·2 정신 일관)**:
> - **Phase A** — method_picker LLM 제거, 결정적 매핑. Stage 3 LLM 호출 0회.
> - **Phase B** — universe.json에 `sub_category` 필드 추가 (LLM 1회 enrichment).
> - **Phase C** — Stage 2 dominant_scenario별 sub_category boost (semantic filtering).

---

## 1. 한 줄 요약

> **Stage 1의 정량 출력(factor_panel + regime + systemic_score) + Stage 2의 시나리오 확률을 받아, 100% 결정적 함수로 종목 후보 풀 구성 → 최적화 방법 선택 → mandate-safe weight를 산출한다. 매일 운영에서 LLM 호출 0회.**

---

## 2. 왜 재설계했나 — Stage 1·2 정신 일관성

기존 Stage 3는 두 가지 비일관성이 있었다:

| 기존 문제 | 영향 |
|---|---|
| `method_picker`가 LLM 호출 (HRP/RP/MV/BL 선택) | 매번 다른 답 가능, 재현성 ↓ |
| `candidate_selector`의 modes 3개 중 2개 unused (legacy + middle) | dead code, 코드 가독성 ↓ |
| Stage 2 `ResearchDecision`을 보지 않음 | conviction·scenario 정보 손실 |
| Stage 3 산출 (candidate_set·weight_vector) archive 없음 | backtest·사후 분석 불가 |
| 종목 선정에 "정성적 신호" 부재 | "AI 시나리오인데 모멘텀 1등이 2차전지" 같은 의미 미스매치 |

**해결 원칙** (Stage 1·2와 동일):
1. **결정적 함수 우선** — LLM은 정성적 정보가 진짜 필요한 좁은 영역에만
2. **Stage 1 정량 객체 활용** — factor_panel, regime.quadrant, systemic_score를 직접 input
3. **Stage 2 출력 활용** — bucket_target은 물론 dominant_scenario, conviction까지
4. **Mandate 자동 보장** — `weight_bounds=(0, 0.20)` + bucket constraint 동시
5. **Archive 패턴 적용** — 매 실행 영구 저장

---

## 3. 어떤 데이터를 보는가

### 3.1 Input — state에서 읽는 키 (Stage 1 + Stage 2 출력)

| Key | 출처 | 사용처 |
|---|---|---|
| `bucket_target` | Stage 2 mapper | 자산군별 weight target (kr_eq/gl_eq/fx_comm/bond/mmf) |
| `research_decision.dominant_scenario` | Stage 2 estimator | method_picker + sub_category boost |
| `research_decision.conviction` | Stage 2 estimator | per_bucket_n 조정, method 보수화 |
| `macro_report.regime` | Stage 1 macro_quant | regime.quadrant → method_picker |
| `risk_report.systemic_score` | Stage 1 market_risk | score≥8 → MIN_VARIANCE 강제 |
| `technical_report.factor_panel` | Stage 1 technical | 188 ETF의 momentum/vol/sharpe/size |
| `universe_path` | config | universe.json (188 ETF + sub_category) |
| `allocation_attempts` / `allocation_feedback` | D4 retry cycle | per_bucket_n 확장, bucket band ±5%p |

### 3.2 외부 데이터 (Stage 3 자체 fetch)

| 함수 | 데이터 | 캐시 |
|---|---|---|
| `fetch_returns_matrix(tickers, start, as_of)` | 3년 OHLCV → daily returns | **ParquetCache** (`~/.tradingagents/cache/etf_prices.parquet`) ✅ |

→ 외부 fetch 단 1회. 다른 모든 input은 in-memory state.

---

## 4. 어떻게 가공하는가 (6 단계)

### 4.1 Hard filter — `list_eligible_tickers`

```python
universe.tradable_at(as_of)         # 미래 ETF skip (D13 survivorship)
× category ∈ BUCKET_TO_CATEGORIES   # 매핑
× aum_krw ≥ 1조원                    # 유동성 floor
```

→ 보통 188 ETF 중 50-90개가 통과.

### 4.2 Returns matrix fetch

```python
returns = fetch_returns_matrix(eligible, start=as_of-3y, end=as_of)
# rows=date, cols=ticker
```

ParquetCache로 누적 보관 — 동일 ETF 재요청 시 0 API.

### 4.3 Multi-factor 후보 선정 — `select_etf_candidates`

각 bucket마다 다음을 수행:

```python
1. eligible 추출 (universe × category × AUM)
2. _rank_by_factors:
   - Stage 1 factor_panel 재사용 (FactorPanel: skip-1m mom, vol, Sharpe, log AUM)
   - score_candidates: regime-conditional weighted z-score 합성
   - + log_boost(scenario, sub_category)  ← Phase C
3. longlist (per_bucket_n × 2)
4. select_diverse: corr 0.85 threshold greedy de-dup
5. final per_bucket_n picks
```

**per_bucket_n 동적 조정**:
- 기본 4
- conviction=low → 5 (불확실 시 다양화)
- attempts > 0 → 6 (retry 시 확장)

### 4.4 Method picker — 결정적 매핑 (LLM 0회)

```python
def pick_optimization_method(regime_quadrant, systemic_score, systemic_regime,
                             research_decision, feedback) -> MethodChoice:
    # 1. extreme systemic
    if systemic_score >= 8.0:
        return MIN_VARIANCE

    # 2. Stage 2 dominant_scenario 우선 (boost dict 기반 메이크)
    if research_decision:
        scenario, conviction = research_decision.dominant_scenario, research_decision.conviction
        if scenario in _SCENARIO_METHOD:
            method = _SCENARIO_METHOD[scenario]
            if conviction == "low" and method == HRP:
                method = RISK_PARITY  # 보수형 격하
            return method

    # 3. macro regime fallback
    if regime_quadrant in ("recession_*"):
        return MIN_VARIANCE

    # 4. systemic_regime fallback
    if systemic_regime == "risk_off":
        return MIN_VARIANCE

    # 5. growth + inflation balanced
    if regime_quadrant == "growth_inflation":
        return RISK_PARITY

    # 6. default
    return HRP
```

**시나리오 → method 매핑** (`_SCENARIO_METHOD`):

| Scenario | Method | 이유 |
|---|---|---|
| goldilocks | HRP | 분산 친화, broad risk-on |
| ai_concentration | HRP | narrow rally + corr regime 감안 |
| stagflation | RISK_PARITY | 균형 분산, 인플레 hedge |
| broad_recession | MIN_VARIANCE | defensive |
| global_credit | MIN_VARIANCE | 극단 defensive |
| kr_boom | HRP | KR 호황 분산 |
| kr_stress | MIN_VARIANCE | KR 위기 → defensive |

### 4.5 Sub_category boost — Phase C 핵심

Stage 1·2 정량 신호가 풍부해도 못 잡는 **의미적 종목 매핑** 영역.

```python
# scenario 별 sub_category → boost 배율 [0.3, 2.0]
SCENARIO_SUBCATEGORY_BOOST = {
    "ai_concentration": {
        "ai_robotics": 2.0, "semiconductor": 1.8,
        "us_tech_nasdaq": 2.0, "ai_theme_global": 2.0,
        "it_software": 1.4,
    },
    "stagflation": {
        "gold": 2.0, "oil_energy": 1.8, "broad_commodity": 1.6,
        "inflation_linked": 1.8, "materials_energy": 1.5,
    },
    "global_credit": {
        "us_treasury": 2.0, "kr_treasury": 1.8,
        "mmf_kr": 1.5, "mmf_usd": 1.5,
        "us_high_yield": 0.3, "em_bond": 0.5,    # 회피
    },
    # ... (5개 시나리오 더)
}
```

**적용 방식 — log_boost (부호 안전 가산)**:
```python
scores[ticker] += log(boost)
# boost=1.0 → +0    (영향 없음)
# boost=2.0 → +0.69 (선호)
# boost=0.3 → -1.20 (회피)
```

→ 곱셈이 아니라 가산이라 음수 score에도 안전. mom/vol/Sharpe/size factor를 가리지 않고 비례 효과.

**Backward compat**:
- ETF에 `sub_category=None` → boost 0, 기존 동작과 같음
- `dominant_scenario=None` → boost 0
- universe.json refresh + Phase B enrichment 후에만 효과 발생

### 4.6 Joint optimization (D12 — bucket × single-cap 동시)

기존 디자인이 가졌던 fatal 문제 (20% cap 후 bucket 스케일링으로 cap 위반)를 해결.

#### HRP (`_hrp_per_bucket`)
```python
for bucket, tickers in candidates:
    inner_weights = HRPOpt(returns[tickers]).optimize()
    scaled = {t: w * bucket_target[bucket] for t, w in inner_weights.items()}
    # iterative water-filling: 20% cap 적용 + 잔여 비제약 자산에 재분배
    capped, residual = clip_and_redistribute(scaled, cap=0.20, max_iters=10)
```

#### EfficientFrontier 계열 (MV / RP / BL)
```python
sector_mapper = {ticker: bucket for ...}
sector_lower = {bucket: target_weight, ...}   # attempts=0이면 equality
sector_upper = {bucket: target_weight, ...}
# attempts > 0이면 ±5%p band로 완화

ef = EfficientFrontier(mu, S, weight_bounds=(0, 0.20))
ef.add_sector_constraints(sector_mapper, sector_lower, sector_upper)
ef.min_volatility() / ef.max_sharpe()    # method에 따라
```

**Mandate 자동 보장**:
- 위험자산 ≤ 0.70: Stage 2의 SCENARIO_BUCKETS 선형 invariant로 이미 보장
- 단일 자산 ≤ 0.20: `weight_bounds=(0, 0.20)` + iterative water-filling

### 4.7 Archive (Phase 3 패턴 확장)

```python
allocator = archive_wrap_node(
    create_portfolio_allocator(...),
    ["candidate_set", "weight_vector", "method_choice"],
)
# → ~/.tradingagents/runs/{as_of_date}/candidate_set.json
#    ~/.tradingagents/runs/{as_of_date}/weight_vector.json
#    ~/.tradingagents/runs/{as_of_date}/method_choice.json
```

backtest 재현 + 사후 분석 가능.

---

## 5. 출력 구조

### 5.1 `WeightVector` Pydantic 객체 (Stage 5 validator + Stage 6에 전달)

```python
class WeightVector(BaseModel):
    method:               OptimizationMethod  # HRP/RP/MV/BL enum
    weights:              dict[str, float]    # ticker → weight (sum=1, all ≤ 0.20)
    rationale:            str (≤500)
    expected_volatility:  float | None
    expected_sharpe:      float | None
```

자동 검증: `_normalize` validator가 합=1.0, 음수 weight 거부.

### 5.2 `CandidateSet` (선정된 ETF 풀)

```python
class CandidateSet(BaseModel):
    bucket_to_tickers:   dict[str, list[str]]  # bucket → 선정된 ticker list
    selection_criteria:  str (≤300)            # AUM/mode/per_bucket_n/corr_thresh
    total_candidates:    int
```

### 5.3 State wire (Stage 3 → 다운스트림)

```python
return {
    "candidate_set":       CandidateSet(...),
    "weight_vector":       WeightVector(...),
    "method_choice":       MethodChoice(...),    # 신규 (Phase A)
    "allocation_attempts": attempts + 1,
}
```

---

## 6. Downstream 영향 / 호환성

| Stage | 받는 키 | 변경 영향 |
|---|---|---|
| Stage 4 Risk Judge (Plan 4) | `weight_vector` + `method_choice` | 영향 0 (호환), `method_choice`는 신규 활용 가능 |
| Stage 5 Validator | `weight_vector` (위험자산 ≤ 0.70, 단일 ≤ 0.20 검증) | 영향 0 |
| Stage 6 Portfolio Manager | `weight_vector` + `candidate_set` | 영향 0 |
| 리포트 | `runs/{date}/*.json` archive 활용 가능 | 신규 데이터 소스 |

---

## 7. Graceful Degradation

| 실패 | Fallback |
|---|---|
| `bucket_target` 없음 | RuntimeError ("Research Manager failed") — Stage 2 의존 |
| `technical_report.factor_panel` 없음 | RuntimeError — Stage 1 의존 |
| Eligible tickers 비어 있음 | RuntimeError ("No eligible tickers") |
| `returns matrix` 비어 있음 | RuntimeError — Stage 1 cache + yfinance 둘 다 실패 시 |
| `select_etf_candidates` 후 후보 <3개 | RuntimeError ("Too few candidates") — D4 retry로 per_bucket_n↑ |
| `EfficientFrontier` infeasible (첫 시도) | RuntimeError → D4 retry → ±5%p band로 완화 후 재시도 |
| HRP iterative water-filling | 10회 iter cap, 잔여는 normalize로 흡수 |
| `expected_volatility/sharpe` 계산 실패 | `logger.warning` + None (silent → logged) |
| `sub_category` 없음 (Phase B 미실행) | `log_boost=0`, 기존 동작 그대로 |
| `dominant_scenario` 없음 | `log_boost=0` |

→ Stage 1·2 데이터 부재는 hard fail (시스템 무결성). 외부 데이터 부재는 graceful.

---

## 8. 비용 비교 (Before / After)

| 항목 | Before (LLM 기반) | After (Phase A/B/C) | 변화 |
|---|---|---|---|
| **Stage 3 LLM 호출 (매일)** | 1회 (deep_llm, method_picker) | **0회** | **100% ↓** |
| **Stage 3 LLM 호출 (universe refresh)** | 0 | 1회 (gpt-4o-mini, ~$0.05) | NEW (분기/년 1회) |
| **재현성** | 낮음 (LLM 흔들림) | **100%** | ✅ |
| **감사 가능성** | 부분 (LLM reasoning만) | **완전** (룰 trace) | ✅ |
| **속도** | API latency 추가 | 단순 함수 호출 | ms 단위 |
| **mandate 위반 가능성** | 가능 (LLM 실수) | 0 (룰 + invariant) | ✅ |
| **candidate_selector 코드** | 195줄 (3 modes) | 165줄 (1 mode) | -15% |
| **시나리오 의미적 매핑** | 없음 | sub_category boost | NEW |

---

## 9. 검증 결과

| 항목 | 결과 |
|---|---|
| 단위 테스트 | **503 passing** (회귀 0건) |
| 신규 unit test (Phase A/B/C) | **+28 신규** (method_picker 12, sub_category 8, scenario boost 8) |
| Integration 테스트 | **4 passing** (subgraph isolation, phase1 smoke, plan pipeline, 5_28 dry run) |
| 폐기 테스트 | 1 (test_portfolio_method_picker old version, LLM subagent 가정) |

### 핵심 invariant 검증

- 모든 페어 sub_category L1 distance ≥ 0.20 (시나리오 boost 의미 있음)
- 모든 SCENARIO_SUBCATEGORY_BOOST 값 ∈ [0.3, 2.0] (극단 boost 회피)
- bucket 간 sub_category 라벨 중복 0 (thematic_other 제외)
- mandate-safe invariant: 단일 자산 cap 20% post-condition (assert in code)

---

## 10. Stage 1 / 2 / 3 비교 (디자인 일관성)

| 항목 | Stage 1 (analysts) | Stage 2 (research) | Stage 3 (allocator) |
|---|---|---|---|
| 역할 | 정량 신호 + 정성 변환 | bucket 결정 | 종목 선정 + 최적화 |
| LLM 사용 (매일) | quick_llm narrative + subagent (regime/systemic/categorize 등) | deep_llm 1회 (시나리오 확률) | **0회** |
| LLM 사용 (refresh) | — | — | 1회 (sub_category enrichment) |
| 결정 방식 | LLM + 결정적 룰 mix | 시나리오 확률 → 결정적 매핑 | **100% 결정적 함수** |
| Mandate 준수 | 입력 데이터 검증 | SCENARIO_BUCKETS invariant | weight_bounds + sector_constraints |
| 재현성 | 부분 (LLM) | 100% (매핑) | 100% (함수) |
| Archive | runs/{date}/{report_key}.json (Phase 3) | research_decision.json (Phase 3) | candidate/weight/method.json (Phase A) |

→ Stage 3가 가장 결정적. Stage 1은 LLM이 정성→정량 변환의 핵심이라 줄이기 어려움. Stage 2/3는 정량 정보가 풍부해서 함수화 가능.

---

## 11. 3 Phase 누적 결과

| Phase | 작업 | 효과 | Commit |
|---|---|---|---|
| Baseline (D12) | bucket × single-cap joint optimization | mandate 안전성 보장 | (pre-existing) |
| **Phase A** | method_picker 결정적 매핑, ResearchDecision 활용, legacy mode 제거, archive | LLM 1 → 0, 재현 100% | `3630446` |
| **Phase B** | universe.json sub_category 필드 + LLM enrichment 스크립트 | 의미적 ETF 분류 인프라 | `6ecc83a` |
| **Phase C** | 시나리오별 sub_category boost (log_boost) | semantic candidate filtering | `3977289` |

**총 변화**:
- Stage 3 LLM: 매일 1회 → 0회
- 신규 skill 1개 (`sub_category` enrichment helpers)
- 신규 CLI 1개 (`scripts/enrich_universe_subcategory.py`)
- 신규 unit test 28개
- 회귀 0건

---

## 12. 운영 절차

### 일상 운영 (매일 자동)

코드 변경 없이 다음만 보장:
1. `universe.json`이 최신 (188 ETF, sub_category 채워짐)
2. Stage 1·2 출력이 state에 있음

→ Stage 3는 자동으로 정상 동작.

### Universe refresh (분기/년 1회)

```bash
# 1. universe.json 갱신 (대회 ETF 리스트 업데이트 시)
python -m tradingagents.dataflows.universe sync_from_xlsx \
    "data/제12회 GAPS ETF 리스트.xlsx" data/universe.json

# 2. sub_category enrichment (LLM 1회)
python scripts/enrich_universe_subcategory.py \
    --universe data/universe.json \
    --provider openai --model gpt-4o-mini
# → universe.json에 188 ETF의 sub_category 영구 저장
# → 자동 backup (.bak)
# → 비용 ≈ $0.05
```

### sub_category 없는 경우 (Phase B 미실행)

- Phase C boost 효과 = 0 (sub_category=None이면 log_boost=0)
- Stage 3는 Phase A 룰만 적용 (regime + systemic + scenario method)
- 정량 신호 (factor_panel) 기반 종목 선정은 정상 작동
- **Phase B는 optional enhancement** — 매일 운영에 필수 아님

---

## 13. 파일 매니페스트

| 위치 | 파일 |
|---|---|
| 노드 | `tradingagents/agents/allocator/portfolio_allocator.py` |
| 결정적 method picker | `tradingagents/skills/portfolio/method_picker.py` |
| Candidate selector | `tradingagents/skills/portfolio/candidate_selector.py` |
| Sub_category 라벨 + LLM enrichment | `tradingagents/skills/portfolio/sub_category.py` |
| Factor scorer | `tradingagents/skills/portfolio/factor_scorer.py` |
| Returns matrix fetcher | `tradingagents/skills/portfolio/returns_matrix.py` |
| Optimizers (pypfopt wrappers) | `tradingagents/skills/portfolio/optimizers.py` |
| 스키마 | `tradingagents/schemas/portfolio.py` (BucketTarget, WeightVector, CandidateSet, OptimizationMethod) |
| Universe 스키마 (sub_category 필드) | `tradingagents/dataflows/universe.py` |
| CLI 도구 | `scripts/enrich_universe_subcategory.py` |
| 단위 테스트 | `tests/unit/skills/test_portfolio_method_picker.py`, `test_portfolio_candidate.py`, `test_portfolio_sub_category.py`, `test_portfolio_scenario_boost.py`, `test_portfolio_optimizers.py` |

---

## 14. 디자인 의사결정 기록

### 왜 method_picker LLM 제거?

선택 기준 (regime + systemic + scenario)이 모두 정량/enum이고, 4 method 중 매핑은 단순 룰로 표현 가능. LLM이 가져올 nuance는 60일 시뮬에서 거의 영향 없음. 재현성·감사·비용 측면 모두 결정적 함수가 우월.

### 왜 BL은 제거 안 하나?

코드에는 남겨두지만 결정적 룰이 BL을 선택하지 않음 (`_SCENARIO_METHOD` 매핑에 없음). 사실상 미사용. 향후 Phase D에서 시나리오 확률 → BL views 자동 생성하면 활성화 가능 — 그 때 다시 평가.

### 왜 sub_category를 매일 LLM이 아니라 universe refresh 시 1회?

- 188 ETF의 의미 (semiconductor vs ai_robotics vs battery_ev)는 변하지 않음
- 매일 호출 = 매일 동일 답 = 비용 낭비
- universe.json에 영구 저장 → 매일 운영에 LLM 0회

### 왜 곱셈이 아니라 log_boost (가산)?

`score_candidates` 결과는 z-score 합성이라 음수 가능. boost 곱셈은 부호 뒤집힘 + 음수 score 자산이 boost 받아도 더 안 좋아짐. 가산은 부호 안전 + 다른 factor와 비례 효과 유지.

### 왜 boost 값을 [0.3, 2.0]로 제한?

- 2.0배 = ln(2) ≈ +0.69 (충분히 의미 있는 boost)
- 0.3배 = ln(0.3) ≈ -1.20 (강한 페널티)
- 너무 큰 값(예: 10배 = +2.3)은 다른 factor (mom/vol/Sharpe/size)를 가림 — Stage 1 정량 분석의 가치 소실
- 너무 작은 값 (0.1배)은 effective elimination이라 black/white 결정이 됨

---

## 15. 향후 로드맵 (Phase D / E)

### Phase D (검토 중) — BL views 자동 생성
- Stage 2 ScenarioProbabilities → 자산군별 expected return 매핑
- BL을 매핑 dict로 활성화 (LLM 없이)
- 단점: hyperparameter 추가, sensitivity 평가 필요

### Phase E — Backtest 모드
- archive된 reports + raw 캐시로 60일 전체 재실행
- LLM 호출 없이 빠른 종목 선정 → 최적화만 재실행
- 시나리오 → method 룰의 historical 성과 측정

각 phase는 현재 시스템에 대한 **선택적 확장**. Phase A/B/C가 baseline.

---

# Phase D (2026-05-22) — Observability + Validation Framework

이 섹션은 Phase A/B/C 이후의 **관찰성 + 검증 인프라**를 정리. 코드 동작 자체보다는 **"가중치가 맞는지 어떻게 알지?"** 를 답하기 위한 도구들.

## D.1 동기

Stage 1·2·3 디자인은 LLM 호출을 줄이고 결정적 함수로 만들었지만, **"가중치/boost 값들이 진짜 최적인가?"** 라는 질문에는 답할 수 없었다. 다음 한계:

- 결과만 보고는 어느 component가 결정에 기여했는지 모름
- weight 0.50 vs 0.45 차이가 실제로 어떤 영향을 주는지 측정 불가
- "이 시점에 이런 portfolio가 맞다"는 합의 vs 시스템 출력 비교 부재

→ Phase D는 **세 가지 관찰성 도구 + 한 가지 검증 프레임워크**를 도입.

## D.2 변경 — 코드/구조 일람

### D.2.1 `rank_percentile` 정규화 (요인 score 안정화)

**문제**: z-score 분포가 factor별로 spread가 크게 달라서 size factor가 압도적으로 dominate. 한 ETF의 size z-score +2.8σ → contribution 0.7로 다른 factor 합을 압도.

**해결**: `_rank_normalize()` 추가. ranking을 [-0.5, +0.5]로 균등 분포. scale-invariant, outlier 영향 차단.

**위치**: `tradingagents/skills/portfolio/factor_scorer.py:114-148`

```python
def _rank_normalize(values: dict[str, float | None]) -> dict[str, float]:
    """Rank-based percentile normalization → uniform [-0.5, +0.5]."""
    ...
```

**기본값 변경**: `score_candidates_with_components(..., normalization="rank_percentile")` — 이전 default `"zscore"` 폐기. zscore도 옵션으로 유지 (비교용).

**측정 효과 (KR boom 시점)**:
| Factor contribution range | z-score | rank_percentile |
|---|---|---|
| mom | 2.065 | 0.438 |
| size | 0.712 | 0.175 |
| factor 압도 정도 | 큼 | 평탄 |

### D.2.2 `longlist_multiplier=3` (corr 필터에 여유 확보)

**문제**: per_bucket_n=4 × longlist_multiplier=2 → top 8개만 longlist. corr 0.85 필터 후 1-2개만 남는 KR equity 같은 경우 padding fallback이 너무 자주 발동.

**해결**: `longlist_multiplier` default 2 → **3** 변경. top 12개 longlist → corr 필터 후 4개 안정 확보.

**위치**: `tradingagents/skills/portfolio/candidate_selector.py:84` (select_etf_candidates default)

### D.2.3 `boost_scale=1.0` 명시화 + 파라미터 노출

**배경**: rank_percentile 도입 후 boost log 값 (±0.7)이 factor signal (±0.5)보다 강해지는 부작용. 임시로 0.5로 줄였다가 anchor 검증 결과 boost 1.0이 substitute 인식과 합쳐서 적합함을 확인.

**상태**: `DEFAULT_BOOST_SCALE = 1.0` (현재) + `boost_scale` 파라미터로 튜닝 가능.

**위치**: `tradingagents/skills/portfolio/candidate_selector.py:38-46`

### D.2.4 cov matrix 표본 부족 방어 (yen_carry crash fix)

**문제**: 늦게 상장된 ETF가 후보 풀에 섞이면 `returns.dropna(how="any")`이 738행 → 3행으로 폭락. `risk_models.sample_cov()`가 PSD 보장 못 함 → `numpy.linalg.LinAlgError: Eigenvalues did not converge` crash.

**해결**: cov 계산 직전 표본 수 확인. < 60 row면 데이터 적은 ticker부터 제거하며 회복.

**위치**: `tradingagents/agents/allocator/portfolio_allocator.py:268-290`

```python
MIN_COV_OBS = 60
if method != OptimizationMethod.HRP and len(returns) < MIN_COV_OBS:
    # 데이터 적은 ticker부터 제거하며 표본 회복
    ...
```

**검증**: 2024-08 yen_carry anchor 정상 통과 (이전엔 crash).

## D.3 Attribution 로깅

**목적**: "왜 이 ETF가 선정됐는가?" 즉답 가능하도록 모든 점수 component를 dict로 분해 보존.

### 데이터 구조

매 Stage 3 실행 결과에 새 키 `state["allocation_attribution"]` 추가:

```jsonc
{
  "as_of_date": "2026-05-15",
  "config": {
    "regime_quadrant": "growth_inflation", "regime_confidence": 0.82,
    "dominant_scenario": "B_N_F", "systemic_score": 6.7,
    "bond_tips_share": 0.79, "per_bucket_n": 4
  },
  "method_picker": {
    "method": "hrp",
    "rule_fired": "scenario_mapping", "rule_index": 2,
    "inputs": { /* regime/systemic/scenario inputs to method picker */ }
  },
  "buckets": {
    "kr_equity": {
      "eligible_count": 21, "longlist_n": 12,
      "regime_weights": { "mom": 0.44, "lowvol": 0.14, "qual": 0.25, "size": 0.18 },
      "ranked_order": [...],
      "per_ticker": {
        "A069500": {
          "raw": { "mom_value": 0.819, "vol_value": 0.636, ... },
          "normalized": { "mom": 0.21, "vol": -0.23, ... },
          "contributions": { "mom": 0.06, "lowvol": 0.04, ... },
          "base_score": 0.95,
          "sub_category": "index_broad",
          "scenario_boost": {
            "scenario": "B_N_F", "axes": ["B","N","F"],
            "composed_mult": 1.0, "log_boost": 0.0,
            "boost_scale": 1.0, "boost_applied": 0.0
          },
          "final_score": 0.95
        }
      },
      "selection_trace": {
        "A069500": { "selected": true, "reason": "first pick", "corr_max": null }
      },
      "chosen": ["A069500", ...]
    }
  }
}
```

### 핵심 위치

| 컴포넌트 | 함수 | 파일 |
|---|---|---|
| z-score → 분해 dict | `score_candidates_with_components` | `factor_scorer.py:79-150` |
| corr 필터 trace | `select_diverse(..., selection_trace=...)` | `factor_scorer.py:198-282` |
| factor + scenario_boost 합산 trace | `_rank_by_factors(..., breakdown_out=...)` | `candidate_selector.py:265-340` |
| bond TIPS quota 분리 trace | `_select_bond_with_tips_quota(..., breakdown_out=...)` | `candidate_selector.py:177-251` |
| 전체 attribution 조립 | `create_portfolio_allocator` 노드 | `portfolio_allocator.py:54-160` |
| Archive 저장 | `archive_wrap_node`의 keys에 `"allocation_attribution"` 추가 | `trading_graph.py:84-87` |

### 사용

```bash
# 매 실행마다 자동 저장
ls ~/.tradingagents/runs/{date}/allocation_attribution.json
```

```python
# 직접 조회
import json
attr = json.load(open("~/.tradingagents/runs/2026-05-15/allocation_attribution.json"))
print(attr["buckets"]["kr_equity"]["per_ticker"]["A069500"]["contributions"])
# → {"mom": 0.061, "lowvol": 0.039, "qual": 0.149, "size": 0.706}
# 이 ETF가 size factor에서 압도적으로 점수 받은 것 즉각 확인
```

## D.4 Ablation 도구 (변형 비교)

**목적**: 같은 state에 (a) regime weight off (b) scenario boost off (c) 둘 다 off 변형 실행해서 ranking 차이 측정. 각 component의 실제 영향력 정량화.

### Variants (4개)

```python
VARIANT_OVERRIDES = {
    "baseline":    {},
    "no_regime":   {"regime_confidence": 0.0},        # equal weight factors
    "no_boost":    {"dominant_scenario": None},        # log_boost = 0
    "raw_factors": {"regime_confidence": 0.0, "dominant_scenario": None},
}
```

### Output

bucket별 Jaccard (top-N 종목 겹침) + Spearman (ranking 순위 상관) 비교.

### 사용

```bash
python scripts/stage3_ablation.py --as-of 2026-05-15
# 출력 예시:
#   variant         mean_jaccard  mean_spearman diff_picks
#   no_regime              0.920          0.973          2
#   no_boost               1.000          0.600          0
#   raw_factors            0.920          0.973          2
```

→ 결과 해석: 이 날에는 boost가 ranking 순위는 흔들지만 최종 선정 종목은 같음. regime weight 변경은 global_equity 1종목 교체 효과.

### 위치
- Module: `tradingagents/observability/stage3_ablation.py`
- CLI: `scripts/stage3_ablation.py`
- Tests: `tests/unit/observability/test_stage3_ablation.py` (9 tests)

## D.5 Historical Anchor Framework

**목적**: 시스템 출력을 **사후 합의** 기준점에 비교. "이 시점에 이런 portfolio가 합리적이었다"는 광범위 합의를 카탈로그화하고 자동 채점.

### 카탈로그 구조

```
data/historical_anchors/
├── README.md                          # 원칙 + 운영 방침
├── _schema.json                       # JSON Schema
├── 2023-10_overheating.json
├── 2023-12_disinflation_rally.json
├── 2024-03_goldilocks.json
├── 2024-08_yen_carry.json
├── 2024-11_kr_boom.json
├── 2025-04_tariff_shock.json
└── 2025-08_kr_political_shock.json    # 7 anchors total
```

### Anchor 구성 — 핵심 통찰: outcome-based ≠ label-based

**잘못된 디자인 (Phase 초기)**: `"required_sub_categories": ["semiconductor"]` 같은 라벨 강제.
→ "KOSPI 200이 사실상 반도체 35%인데 별도 semiconductor ETF 강요" 같은 부조리.

**올바른 디자인 (Phase 후기)**: `required_substitute_groups` — substitute 인정.
```jsonc
"required_substitute_groups": [
  {
    "name": "kr_growth_theme",
    "any_of": ["semiconductor", "ai_robotics", "battery_ev", "index_broad"],
    "min_total_weight": 0.15,
    "description": "KOSPI200(=암묵적 반도체 35%)으로도 충족 가능"
  }
]
```

### 7-8축 채점

| 축 | 조건 |
|---|---|
| method_ok | Stage 3 선택 method ∈ acceptable_methods |
| required_present | required_sub_categories 모두 weight > 0 (strict) |
| substitute_groups_met | 각 group의 any_of 합산 weight ≥ min_total_weight |
| forbidden_absent | forbidden_sub_categories 합산 weight ≈ 0 |
| min_weights_met | 개별 sub_category min 임계 충족 |
| max_weights_met | 개별 sub_category max 임계 미만 |
| diversity_ok | unique sub_category 수 ≥ 임계 |
| risk_asset_ok | 위험자산 합 ≤ risk_asset_max |

**단일 score 아님** — 다축 보고서. 어느 축에서 실패하는지 명시 → 단일 metric 함정 회피.

### 위치
- Module: `tradingagents/observability/anchor_evaluator.py`
- Live (Stage 1 실측 모드): `tradingagents/observability/anchor_live.py`
- CLI (synthetic): `scripts/anchor_eval.py`
- CLI (live): `scripts/anchor_eval_live.py`
- Tests: `tests/unit/observability/test_anchor_evaluator.py`

### 검증 결과 (2026-05-22 기준)

| Anchor | Synthetic | LIVE | 일치 |
|---|---|---|---|
| 2023-10 overheating | 8/8 hrp | 8/8 hrp | ✓ |
| 2023-12 disinflation_rally | 8/8 hrp | (LIVE 미실행) | — |
| 2024-03 goldilocks | 8/8 hrp | 8/8 hrp | ✓ |
| 2024-08 yen_carry | 8/8 min_variance | 8/8 min_variance | ✓ |
| 2024-11 kr_boom | 8/8 hrp | 8/8 hrp | ✓ |
| 2025-04 tariff_shock | 7/8 risk_parity | 7/8 min_variance | method만 다름 (둘 다 acceptable) |
| 2025-08 kr_political_shock | 8/8 min_variance | (LIVE 미실행) | — |
| **Total** | **55/56 (98%)** | — | — |

**의미**: 다양한 macro regime (overheating, goldilocks, kr_boom, kr_stress, stagflation, yen_carry tail)에서 일관되게 합의 충족. regime weight + boost dict 값이 historical 데이터에서 robust.

### 잔존 1 fail

**2025-04 tariff_shock — safe_haven_treasury 누락**:
- bond bucket의 nominal quota 1자리 → kr_corporate가 factor 1위로 차지
- us_treasury 30년물은 backward-looking factor에서 약함 (2024-25 금리 급등기)
- kr_treasury는 kr_corporate와 corr 0.95 → corr 필터로 reject
- → 시스템의 corr-aware 분산이 정확히 작동했지만 anchor의 "long treasury 필요" 가정이 시대 착오일 수 있음 (2022 TLT -31%)

이건 anchor 자체의 ground truth가 의심되는 의미 있는 잔존 신호로 보존.

## D.6 Live Anchor Harness (라이브 검증)

**목적**: anchor의 Stage 1·2 hand-spec 값이 라이브 데이터와 정합한지 검증.

**흐름**:
1. anchor as_of_date에 Stage 1 (macro_quant + market_risk + technical) **LIVE 실행** → REAL macro_report/risk_report/technical_report
2. Stage 2 (research_decision + bucket_target) 는 anchor 명세 사용 (LLM 기반이라 historical 재현 어려움)
3. Stage 3 호출 → 평가

**LLM 비용**: anchor당 ~$0.05, 5 anchor 전체 ~$0.25.

**사용**:
```bash
python scripts/anchor_eval_live.py --compare-synthetic
# 출력: synthetic vs LIVE pass count 나란히 비교
```

**핵심 발견** (2026-05-22):
- 4/4 anchor에서 LIVE pass count = synthetic pass count
- 1개만 method 차이 (tariff_shock: risk_parity → min_variance, 둘 다 acceptable set)
- → **regime_weight + boost_dict이 historical 라이브 데이터에서도 동일한 결정 유도**. hand-spec에 과적합 X.

## D.7 Sensitivity Analysis

**목적**: 각 regime weight + boost multiplier를 ±20% 흔들었을 때 anchor pass count가 얼마나 바뀌는지 정량화.

- 변동 큼 = sensitive parameter (튜닝 영향력 큼)
- 변동 0 = robust (마진 충분, 안전한 값)

### 사용
```bash
# Regime weight만 (16 weight × 2 ≈ 8분)
python scripts/sensitivity_analysis.py --no-boost --delta 20

# 전체 (regime + boost, ~30-50분)
python scripts/sensitivity_analysis.py --delta 20

# 결과는 artifacts/sensitivity.json + stdout 표
```

### 위치
- Module: `tradingagents/observability/sensitivity.py`
- CLI: `scripts/sensitivity_analysis.py`

## D.8 운영 가이드 — 새 anchor 추가하기

1. 시점 선정 (광범위 사후 합의 있는 macro 사건)
2. `data/historical_anchors/{YYYY-MM_event}.json` 파일 작성
   - `consensus_reasoning` 출처 명시 (Howard Marks memo, BoFA FMS 등)
   - `stage1`: regime quadrant, systemic score 합의 값
   - `stage2`: dominant_cell, bucket_target 합의 값
   - `expected_stage3`: substitute_groups, max/min, forbidden, risk_asset_max
3. `python scripts/anchor_eval.py --anchor {anchor_id}` 로 검증
4. `pytest tests/unit/observability/test_anchor_evaluator.py` 회귀 확인
5. PR review로 합의 강화 (혼자 추가 X — convergent validation 원칙)

## D.9 핵심 invariant — 무엇이 검증되었나

Phase D 이후의 시스템에 대한 정량적 자신감:

1. **size dominance 해결**: rank_percentile로 모든 factor가 같은 [-0.5, +0.5] 범위
2. **corr-aware 분산**: KOSPI200/반도체ETF (corr 0.89), kr_treasury/kr_corporate (corr 0.95) 모두 substitute로 인식
3. **scenario boost 작동**: KR boom의 ai_robotics 1위 진입, stagflation의 inflation_linked 진입
4. **mandate 무결성**: 7 anchor 모두 단일자산 ≤ 20%, 위험자산 ≤ bucket target 준수
5. **historical robustness**: 2023-10 ~ 2025-08 (다양한 regime) 7 anchor 중 6 anchor 8/8, 1 anchor 7/8
6. **synthetic vs live 일치**: 4/4 anchor에서 LIVE = synthetic (pass count 동일)
7. **graceful degradation**: yen_carry crash fix로 cov 표본 부족 시에도 ticker 자동 제외 후 정상 풀이

## D.10 파일 매니페스트 (Phase D 신규/수정)

| 위치 | 역할 |
|---|---|
| `tradingagents/observability/anchor_evaluator.py` | 7-8축 anchor 채점 |
| `tradingagents/observability/anchor_live.py` | Stage 1 LIVE 실행 + Stage 3 평가 |
| `tradingagents/observability/stage3_ablation.py` | 4 variant ranking 비교 |
| `tradingagents/observability/sensitivity.py` | weight/boost perturbation 영향 측정 |
| `scripts/anchor_eval.py` | synthetic anchor CLI |
| `scripts/anchor_eval_live.py` | live anchor CLI |
| `scripts/stage3_ablation.py` | ablation CLI |
| `scripts/sensitivity_analysis.py` | sensitivity CLI |
| `data/historical_anchors/_schema.json` | anchor JSON Schema |
| `data/historical_anchors/README.md` | 카탈로그 운영 원칙 |
| `data/historical_anchors/*.json` | 7 historical anchors |
| **수정**: `tradingagents/skills/portfolio/factor_scorer.py` | `_rank_normalize` 추가, `score_candidates_with_components` 도입 |
| **수정**: `tradingagents/skills/portfolio/candidate_selector.py` | `attribution` 인자, `longlist_multiplier=3`, `boost_scale`, `normalization` |
| **수정**: `tradingagents/skills/portfolio/method_picker.py` | `MethodChoice`에 `rule_fired`/`rule_index`/`inputs` |
| **수정**: `tradingagents/agents/allocator/portfolio_allocator.py` | `allocation_attribution` 수집, cov 표본 부족 fix |
| **수정**: `tradingagents/graph/trading_graph.py` | archive_wrap에 `"allocation_attribution"` |
| **수정**: `tradingagents/agents/utils/agent_states.py` | `AgentState.allocation_attribution` 필드 |
| **수정**: `prompts/macro-analysis.md` | EPU placeholder 제거 (Stage 1 e2e 가능) |
| 단위 테스트 (신규) | `test_portfolio_attribution.py` (14), `test_stage3_ablation.py` (9), `test_anchor_evaluator.py` (7) |

## D.11 결론 — Phase D가 답한 것

> **Phase A/B/C 디자인 결정의 정량 가중치들이 실제로 합리적인 결과를 내는지 검증할 수 있게 됐다.**

지금까지의 "이 값이 적절한지 어떻게 알지?" 라는 막연한 의심에 대한 답:
- **Attribution**: 결정의 원인 즉답
- **Ablation**: 각 component 영향력 측정
- **Anchor**: 광범위 합의에 비교
- **Live harness**: synthetic spec과 실측의 정합 확인
- **Sensitivity**: 가중치 마진/취약점 측정

→ Phase A/B/C 가중치는 **historical 7 anchor에 대해 robust** (55/56 pass). 더 이상 임의 튜닝이 아니라 audit 가능한 값.

다음 phase E (backtest 모드)는 forward return을 metric으로 도입할 수 있으나 — 그건 별도 작업.
