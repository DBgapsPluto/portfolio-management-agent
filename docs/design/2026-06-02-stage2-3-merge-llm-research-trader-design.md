# Stage 2/3 통합 — LLM 기반 Research Debate + Trader 설계

- **날짜**: 2026-06-02
- **브랜치**: feat/new-llm-based-agent
- **상태**: 설계 승인 완료, 구현 계획 대기

## 1. 목적

기존 Stage 2(factor model 기반 `research_manager`)와 Stage 3(`candidate_selector` + optimizer 기반 `portfolio_allocator`)를 **하나의 LLM 기반 클러스터로 통합**한다. factor model과 종목 선정용 최적화 머신러리를 **전부 제거**하고, 강세·약세 에이전트가 Stage 1 분석을 해석하고 → research manager가 종합하고 → trader가 14-bucket 비중과 종목을 직접 결정하는 구조로 교체한다.

### 성공 기준
- factor model / candidate_selector / optimizer 코드 전부 제거되고 해당 테스트도 정리됨.
- 새 클러스터가 mock LLM E2E에서 `weight_vector`(ticker→weight, sum=1, 단일≤20%, 위험자산≤70%)를 산출하고 Stage 4/5/6를 통과함.
- 14-bucket 배분(trader)과 위험자산 검사(per-ETF)가 분리되어 동작함.

### 비목표 (이번 작업 범위 밖)
- Stage 1(analysts) 변경.
- Stage 5(mandate validator) 룰 변경 — 위험/안전 정의는 **기존 그대로**.
- 토론 다중 라운드, BL/NCO 등 최적화 엔진 재도입.

## 2. 현재 상태 (교체 대상)

- **Stage 2** `research_manager.py`: `compute_all_factors` → 12-factor z-vector → `apply_factor_model_with_safety`(β·z + QP 투영) → BucketTarget(8). **제거.**
- **Stage 3** `portfolio_allocator.py`: `candidate_selector`(impl_score + ENB-greedy) → `method_picker`(8-rule) → optimizer(NCO/BL/HRP/MV) → WeightVector. **제거.**
- **그래프**(`builder.py`): `research_debate` 노드 → `allocator` 노드. D4 retry는 `allocator`로 루프백.

## 3. 아키텍처

기존 두 노드를 **단일 sub-graph 노드 `research_trade`**로 통합한다(기존 `research_debate` 단일 노드 wrapping 패턴 답습). 파이프라인 위치 불변(Stage 1 뒤, Stage 4 앞).

```
[Stage 1] 4 analysts ──(full *_summary)──┐
                                          ▼
┌──────────── research_trade (통합 노드) ────────────┐
│  ① Bull (LLM)  ─┐                                  │
│  ② Bear (LLM)  ─┴─→ ③ Research Manager (LLM)       │
│                          │ InvestmentThesis        │
│                          ▼                          │
│  ④ Trader (LLM, 2-step)                             │
│     step A → BucketTarget(14)                       │
│     step B → 버킷별 StockSelection                  │
│                          │                          │
│  ⑤ 종목내 AUM 가중 배분 (결정적, LLM 아님)         │
└──────────────────────────┬──────────────────────────┘
                            ▼ weight_vector + bucket_target(14) + research_decision + candidate_set
                  [Stage 4] risk overlay (비중보존 검사/축소)
                  [Stage 5] mandate validator (per-ETF 위험/안전, 변경 없음)
                  [Stage 6] portfolio manager
```

- **LLM 콜/run**: bull 1 + bear 1 + manager 1 + trader 2(step A/B) = **5콜**, deep tier. 토론 라운드 없음(단일 패스).
- **D4 retry**: validator 실패 시 통합 노드의 **trader step A부터** 재진입(violation feedback 주입). bull/bear/manager는 재실행하지 않음.

## 4. 버킷 & 위험자산 모델 (핵심)

두 개념을 **명확히 분리**한다.

| 개념 | 출처 | 단위 | 용도 |
|---|---|---|---|
| **14-bucket** (A1~A5 방어, B1~B9 성장) | `docs/GAPS_ETF_버킷분류_14.xlsx` (신규) | 버킷 | Trader 배분 어휘, BucketTarget 비중 |
| **위험/안전** (per-ETF) | `data/universe.json` `bucket` 필드 (기존) | 종목 | mandate "위험자산 ≤70%" 검사 |

**데이터로 확정된 사실 (188종 전수 검증):**
- 14-bucket 진영(방어/성장)과 universe 위험/안전은 **8개 종목에서 불일치**.
- 14-bucket 중 **A4(안전통화), A5(금·인플레헤지) 두 버킷만 위험/안전 혼재**(A4: 안전1/위험2, A5: 안전2/위험3). 나머지 12개 버킷은 동질.
  - A1~A3 = 전부 안전, A4/A5 = 혼재, B1~B8 = 전부 위험, B9(하이일드) = 전부 안전.

**결론:**
- **위험자산% 는 14-bucket 합으로 계산 불가 → 최종 `weight_vector`에 per-ETF 위험/안전 플래그를 적용해 계산**한다(기존 Stage 5 방식 유지).
- 14-bucket 매핑은 xlsx에서 universe.json에 **`gaps_bucket` 필드로 1회 병합**하는 스크립트로 처리(런타임에 xlsx 미접근). 위험/안전 `bucket` 필드는 그대로 둠.

### 14-bucket canonical key (snake_case)
```
a1_cash, a2_kr_rates, a3_us_rates, a4_safe_fx, a5_gold_infl,
b1_kr_equity, b2_dm_core, b3_global_tech, b4_china, b5_other_intl,
b6_defensive_equity, b7_reits, b8_cyclical_commodity, b9_risk_credit
```

## 5. 컴포넌트별 명세

### ① Bull / ② Bear (LLM, deep)
- **입력**: Stage 1 전체 summary(`macro_summary`, `risk_summary`, `technical_summary`, `news_summary`) — D2 핸드오프용 ≤2KB markdown 4종 전부.
- **출력**: 각자 관점(강세/약세)으로 해석한 thesis(markdown). 자산군 방향성 + 근거 + 무시하면 안 될 리스크.
- **프롬프트 원칙**: 같은 정보를 받되 자기 stance로 해석. 상대 반박은 하지 않음(단일 패스).

### ③ Research Manager (LLM, deep)
- **입력**: bull thesis + bear thesis + Stage 1 summary.
- **출력**: `InvestmentThesis`(manager 출력 전용 신규 스키마)
  - `thesis_md`: 종합 판단 markdown — 자산군/테마별 방향성 코멘트를 본문에 포함(trader가 prose로 소비).
  - `conviction`: high/medium/low.
  - `scenario_label`: 정성 시나리오명 1개(Stage 4 macro_conditional 호환용, factor_scores 대체 아님).
  - `key_risks`: list[str].
- **참고**: state에 저장되는 `research_decision`은 manager 출력만이 아니라 trader의 `bucket_target` + bull/bear thesis까지 합친 **`ResearchThesis` 종합 객체**다(§6 참조). `InvestmentThesis`는 그 부분집합.

### ④ Trader (LLM, deep, 2-step)

**Step A — 14-bucket 비중**
- **입력**: `InvestmentThesis` + 14-bucket 정의 + 제약 명세(단일 종목≤20%, 위험자산≤70% — 위험자산은 per-ETF 정의이며 A4/A5는 혼재임을 명시) + (retry 시) `allocation_feedback`.
- **출력**: `BucketAllocation` → `BucketTarget`(14-key, sum=1).
- **제약 가이드(프롬프트)**: 위험자산 ≈ B1~B9 + A5의 위험분 + A4의 위험분. 보수적으로 `sum(B1..B9) + a5_gold_infl` 를 ~70% 이하로 잡되, 하드 검사는 per-ETF로 사후 수행됨을 고지.

**Step B — 종목 선정**
- **입력**: Step A 비중 + **비중>0 버킷의 종목 풀만**(per-ETF: ticker, 이름, AUM, 유동성, 모멘텀/추세(technical_report에서), 위험/안전 플래그, 대표ETF 여부).
- **출력**: `StockSelection` → 버킷별 선정 ticker 리스트 → `CandidateSet`(bucket_to_tickers) 채움.
- **선정 수 제약**: 버킷 비중 W_b 인 버킷은 단일≤20% 충족을 위해 **최소 `ceil(W_b / 0.20)` 종목** 선정해야 함. 프롬프트에 명시 + 사후 검증.

### ⑤ 종목내 비중 배분 (결정적 알고리즘, AUM 가중)
버킷 비중 W_b 를 선정 종목 S_b 에 **AUM 비례** 배분 + 단일 20% cap(iterative water-filling):
```
raw_i = W_b * aum_i / Σ_{j∈S_b} aum_j
while max(raw_i) > 0.20 + eps:
    capped = {i: raw_i ≥ 0.20}
    excess = Σ_{capped}(raw_i − 0.20);  raw_i := 0.20 for capped
    redistribute excess to uncapped ∝ aum   # 모두 capped면 infeasible
if infeasible (버킷 종목 부족):  allocation_feedback 로 retry 트리거
```
- 최종 `weight_vector`(ticker→weight, sum=1) 생성. `method`는 `OptimizationMethod`에 신규 값 `AUM_WEIGHTED` 추가(또는 enum 확장).

## 6. 스키마 변경

### 변경
- `BucketTarget`: `weights` 8-key → **14-key**. `bond_tips_share` 필드 **제거**(candidate_selector 삭제로 소비처 없음). `risk_asset_weight` property는 14-bucket으로 계산 불가하므로 **제거**(위험자산은 weight_vector + per-ETF로 별도 계산). rationale 유지.
- `OptimizationMethod`: `AUM_WEIGHTED = "aum_weighted"` 추가.

### 재설계
- `research.py`의 `ResearchDecision` → **`ResearchThesis`로 교체**: `bucket_target`, `conviction`, `scenario_label`, `thesis_md`, `bull_view`, `bear_view`, `key_risks`. factor_scores/factor_contributions/baseline_bucket/safety_diagnostics **제거**.
  - state 키 `research_decision`은 이름 유지(downstream 호환), 타입만 `ResearchThesis`로.

### 신규
- `InvestmentThesis`(manager 출력), `BucketAllocation`(trader step A), `StockSelection`(trader step B).

### 유지(계약 불변)
- `WeightVector`(ticker→weight) — Stage 4/5/6 그대로.
- `CandidateSet`(bucket_to_tickers) — Stage 4 필수 입력, trader step B 결과로 채움.

## 7. Downstream 영향

### Stage 4 (risk overlay) — 비중보존 검사/축소로 단순화
- **재최적화 제거**: `overlay_apply.py`의 EfficientFrontier 2차 호출 삭제.
- 3 lens(tail_risk / concentration / macro_conditional) 산출은 **유지**, 적용만 변경:
  - 위험자산 multiplier → **per-ETF 위험 종목들을 비례 축소**, 줄인 만큼 안전 종목에 비례 재분배(weight_vector 직접 조작).
  - weight_ceilings / cluster_caps → 해당 종목 클립 후 재정규화.
  - trader가 정한 비중 구조 보존(전면 재배분 안 함).
- `macro_conditional_lens`: `factor_scores.F8_valuation` 부재 → valuation 트리거는 graceful None(이미 None 처리됨). `conviction`/`scenario_label`은 `ResearchThesis`에서 계속 공급.
- `candidate_set`·`bucket_target` 계약 유지(읽기만).

### Stage 5 (mandate validator) — 변경 없음
- 이미 per-ETF 위험/안전(universe.json)로 검사. `concentration_check.py`의 risk 판정이 universe `bucket` 필드 기반인지 확인해 일치 보장(필요 시 `RISK_BUCKET_NAMES` 경로를 per-ETF `bucket=="위험"`으로 정리).

### Stage 6 (portfolio manager)
- `philosophy.py`의 bucket 포맷터를 **14-bucket으로 갱신**(기존 5-bucket 하드코딩 결함 동시 해소). `research_decision` 신규 필드(thesis_md/bull_view/bear_view)를 narrative 근거로 사용.

### 그래프 / D4
- `builder.py`: `research_debate` + `allocator` 두 노드 → 단일 `research_trade` 노드. retry 라우트 `retry_allocator` → 통합 노드 재진입(trader step A부터). `conditional_logic.validation_router`의 `retry_allocator` 타겟 변경.

## 8. 삭제 대상 (factor model 일체)
- `skills/research/factor_to_bucket.py`, `factor_estimators.py`, `factor_calibration.py`, `factor_calibration_hierarchical.py`, `factor_baselines.py`, `factor_reliability_audit.py`, `factor_to_bucket` 관련 상수.
- `research_manager.py`의 factor 모델 로직 전체(파일은 새 manager로 교체 또는 신규 모듈).
- `skills/portfolio/candidate_selector*`, `method_picker*`, optimizer 분기(`_optimize_with_bucket_constraints`, NCO/BL/HRP/MV adapter), `cash_spillover`, ENB(minimum_torsion) 로직.
- **보존**: `cov_estimator.py`, `returns_matrix.py` — Stage 5 fallback normalizer(min-variance)가 사용. `bucket_for_etf`/`sub_category` — 위험/안전·14-bucket 매핑 참조용.
- 삭제 코드에 종속된 테스트는 함께 제거/이관.

## 9. 구현 단계 (phased)

1. **Phase 0 — 데이터/스키마**: xlsx→universe.json `gaps_bucket` 병합 스크립트; 14-bucket 상수 모듈(`gaps_buckets.py`: key·한글명·진영·소속 ticker); 신규/변경 Pydantic 스키마. → verify: 188종 매핑 + 스키마 단위테스트.
2. **Phase 1 — Research 클러스터**: bull/bear/manager 에이전트 + 프롬프트 + `InvestmentThesis`. → verify: mock LLM thesis 생성/구조 테스트.
3. **Phase 2 — Trader**: 2-step trader + AUM 종목내 배분 알고리즘. → verify: bucket sum=1, 단일≤20%, 위험자산(per-ETF)≤70%, 종목 부족 시 feedback — 단위테스트.
4. **Phase 3 — 통합/배선**: `research_trade` sub-graph 노드, D4 retry 재배선, Stage 4 단순화, Stage 6 포맷터. → verify: E2E mock 파이프라인 PASS.
5. **Phase 4 — 정리**: factor model 머신러리 삭제 + 죽은 테스트 정리. → verify: 전체 테스트 그린.

## 10. 테스트 전략
- 결정적 부분(⑤ AUM 배분, 위험자산 계산, 14-bucket 매핑, feasibility 가드)은 LLM 없이 단위테스트.
- LLM 부분(bull/bear/manager/trader)은 mock structured output으로 계약/경로 테스트.
- E2E는 기존 mock 파이프라인 픽스처 재사용, weight_vector가 mandate 통과하는지 검증.

## 11. 리스크 / 열린 질문
- **위험자산 70% 사전충족 정확도**: trader가 per-ETF 위험을 버킷 레벨에서 근사하므로 A4/A5 혼재로 약간 빗나갈 수 있음 → Stage 4 축소 + Stage 5 retry가 하드 보증. 다만 retry 빈발 시 trader 프롬프트의 위험자산 근사식을 보정 필요.
- **AUM 가중의 집중**: 대형 ETF로 쏠려 단일 20% cap에 자주 걸릴 수 있음 → water-filling으로 처리하되, 버킷당 최소 종목수 가이드를 trader 프롬프트에 강하게.
- **LLM 비용/지연**: 5콜/run. 추후 bull/bear를 1콜 batch로 묶는 최적화 여지(이번 범위 밖).
