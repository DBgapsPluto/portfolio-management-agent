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
