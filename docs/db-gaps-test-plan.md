# DB GAPS 에이전트 — 테스트 플랜

- **작성일:** 2026-05-10
- **참조 스펙:** `docs/superpowers/specs/2026-05-09-db-gaps-agent-redesign-design.md`
- **테스트 프레임워크:** pytest (markers: unit / integration / smoke)
- **목표 커버리지:** 신규 코드 100%, 회귀 테스트 IRON RULE

본 문서는 plan-eng-review 결과를 바탕으로 구현 시 작성해야 할 테스트를 단위·통합·E2E·eval 단위로 정리. CLI·skill·analyst·debate·validator 별로 GAP 표시. 구현 시 각 GAP에 대응하는 pytest 파일 생성.

## 1. Affected Modules / Routes

신규 또는 재작성 모듈:
- `tradingagents/dataflows/{universe,pykrx_data,fred,ecos,volatility,news_macro,cache}.py`
- `tradingagents/skills/{_base.py,_helpers.py,registry.py,macro/*,risk/*,technical/*,news/*,portfolio/*,mandate/*}`
- `tradingagents/schemas/*` (~30 Pydantic 모델)
- `tradingagents/presets/*.yaml`, `tradingagents/presets/spec.py` (loader)
- `tradingagents/agents/{analysts/*,allocator,managers/portfolio_manager}` (rewrite)
- `tradingagents/agents/researchers,risk_mgmt` (prompt + sub-graph)
- `cli/main.py` (22 서브커맨드)
- `tradingagents/graph/{trading_graph,setup,conditional_logic}.py` (rewrite)

레거시 갱신 대상:
- `tests/test_memory_log.py` → D8 결정 (deprecate 또는 portfolio_decisions.jsonl로 재작성)
- `tests/test_ticker_symbol_handling.py` → ETF ticker 형식으로 갱신
- `tests/test_structured_agents.py` → 신규 분석가 스키마로 재작성
- `tests/test_signal_processing.py` → BUY/HOLD/SELL → weight vector 처리로 재작성

## 2. Key Interactions to Verify

### 2.1 데이터 레이어
- `gaps universe sync` 명령 → xlsx 파싱 → 188개 ETF 정확 추출 → JSON 스키마 검증 통과
- `tiered_cache` (D5) → live API → D-1 캐시 → D-7 캐시 → hard fail 단계별 동작
- `staleness_days` 필드가 모든 분석가 출력에 propagation
- pykrx 일괄 fetch가 188개 ETF에 대해 합리적 시간(<60초) 안에 완료

### 2.2 Skill 레이어
- `@register_skill` 데코레이터 → registry lookup 정상
- `BaseSubagent.invoke()` → schema 성공 / 1회 retry 후 성공 / 2회 실패 후 raise
- `invoke_with_structured_retry` helper → ValidationError catch + retry + 최종 raise
- `subagent_model_policy` lookup → skill별 deep/quick model 정확히 선택

### 2.3 분석가 노드
- 각 분석가가 정해진 skill 시퀀스 호출 → Pydantic schema 강제 출력
- `narrative` 필드가 500자 이내
- 모든 수치 필드가 skill 출력에서 직접 옴 (LLM이 임의 생성 X)

### 2.4 토론 클러스터 (D2 결정 검증)
- Bull/Bear sub-graph의 raw messages가 parent state에 누설되지 X
- judge 노드가 summary str + structured 결정만 parent에 return
- Risk debate sub-graph도 동일

### 2.5 Allocator
- `select_etf_candidates` → AUM·momentum·diversity 필터 적용
- PyPortfolioOpt 4종 optimizer 호출 → weight 합 = 1.0 ± 1e-6
- `pick_optimization_method` subagent → regime별 method 매핑

### 2.6 Mandate Validator (대회 룰 hard rule)
- `validate_universe`: 188 안 / 밖 케이스
- `validate_concentration`: 위험자산 정확히 70.0% / 70.001% 경계, 단일 20.0% / 20.001%
- `validate_turnover_feasibility`: 5영업일 80% floor 가능/불가, 월 10% 가능/불가
- `validate_correlation_concentration`: 클러스터 합 cap 위반 검출

### 2.7 Validator → Allocator cycle (D3 결정 검증)
- 위반 weight → feedback 주입 → Allocator 재호출 → 통과
- 2회 실패 → deterministic fallback (clip + renormalize) → 사용자 warning 포함 final

### 2.8 CLI (22개)
- 각 명령 `--help` 동작
- 각 명령 happy path smoke (mock fixture 사용)

### 2.9 보고서 생성
- `philosophy.md` → 워드 4장 분량 (≥4000자) 검증
- `monthly_report_{month}.md` → 3섹션 (수익률 자체평가 / 변경 사유 / 향후 전망) 모두 존재
- `trade_plan.csv` → 컬럼 검증 (티커·매수가·수량·총금액·자산군)
- 본문에 ETF 상품 설명서·뉴스 기사 verbatim 인용 없음 (대회 §4 위반 방지)

## 3. Edge Cases

- xlsx 파일이 없거나 손상된 경우 → 명확한 에러 메시지
- 188개 중 일부 ETF 가격 fetch 실패 → 부분 성공 처리, narrative에 누락 종목 명시
- regime 분류 confidence < 0.5 → narrative에 불확실성 명시
- 모든 자산이 한 클러스터에 속하는 극단 케이스 (분산 불가능) → mandate validator가 catch
- 5/28 자정 직전 timezone 처리 (KST vs UTC)
- 회전율 분모 평균자산이 0인 경우 (리밸런싱 직후 동일 시점) → 0으로 안 나누기
- subagent의 LLM이 빈 문자열·None 필드 채워서 schema 통과 시도 → 1회 retry 후 raise

## 4. Critical Paths

### 4.1 5/28 E2E dry-run (D9 결정: Mock fixture 기반)

**파일:** `tests/integration/test_5_28_dry_run.py`

**Fixture (6종):**
- `tests/fixtures/fred_macro.json` — DGS10/DGS2/CPI/UNRATE 시계열 sample
- `tests/fixtures/ecos_macro.json` — 한국 기준금리/M2/CPI sample
- `tests/fixtures/pykrx_etf_prices.parquet` — 188 ETF × 30 영업일 (3년 전체 아닌 sub-set)
- `tests/fixtures/llm_mock_responses.json` — 각 LLM 호출에 대응하는 deterministic 응답
- `tests/fixtures/pyportfolioopt_fake.py` — HRP/RP/MinVar/BL 호출에 대해 사전 정의된 weights 반환
- `tests/fixtures/universe_test.json` — 188 ETF 메타데이터 (실제 sync 결과)

**검증 단계:**
1. universe sync → 188 ETF 카운트 정확
2. plan 풀 파이프라인 실행 → 에러 없이 종료
3. portfolio.json 산출 → mandate 검증 통과
4. philosophy.md 생성 → 분량 4000자+
5. trade_plan.csv 컬럼 정확
6. analysis_appendix.md 생성

### 4.2 5/28 수동 live dry-run (D9 결정: 별도)

`gaps plan --dry-run --as-of 2026-05-25` 명령으로 실제 FRED·ECOS·pykrx·LLM 호출. 5/27 전 적어도 1회 수동 실행. 결과 artifacts 시각 확인.

### 4.3 Validator cycle (D3 결정 검증)

**파일:** `tests/integration/test_validator_cycle.py`
- 의도적으로 단일 25% weight 생성 → Validator catch
- feedback prompt 주입 검증
- 재호출 후 통과 또는 fallback 도달 검증
- attempt_count 정확

### 4.4 Tiered cache (D5 결정 검증)

**파일:** `tests/integration/test_cache_fallback.py`
- pykrx mock으로 live success / live fail / D-1 hit / D-7 hit / hard fail 5가지 시나리오
- staleness_days 필드 propagation 검증

### 4.5 Hybrid topology subgraph (D2 결정 검증)

**파일:** `tests/integration/test_subgraph_isolation.py`
- Bull/Bear sub-graph 실행 후 parent state.messages가 sub-graph raw 미포함 검증
- judge 출력만 parent에 reflect

## 5. LLM Eval

**파일:** `tests/eval/test_regime_classifier_eval.py`

`classify_regime` subagent의 4-quadrant 분류 정확도 평가:
- 8개 history 케이스 (예: 2008-09 침체×디스인플레, 2022-06 성장×인플레, 2020-04 침체×인플레, 2017-Q3 성장×디스인플레, ...)
- 정답 confidence 0.7+ 비율 ≥ 75%
- baseline 비교 (prompt 변경 전후)

## 6. Quality Targets

- 회귀 검출: ★★★ (validator, cache fallback, E2E)
- skill 단위: ★★ (행복 경로 + 핵심 edge case)
- CLI smoke: ★ (--help + 1 happy path)

GAPS 합계: ~80개 (5 E2E, 1 eval, ~74 unit/integration)

## 7. CI 정책

- 모든 unit / integration test는 mock fixture 기반 → CI에서 외부 API 의존 X
- live API 검증은 별도 `--marker live` (개발자 머신에서만)
- LLM 호출 비용 절감 위해 mock LLM client 사용

## 8. 회귀 IRON RULE

이 프로젝트는 greenfield (in-place 갈아끼움이지만 코드 의미는 새것). 따라서 회귀 케이스는:
- 보존되는 기존 자산 (memory log D8 결정으로 deprecate, checkpointer, LangGraph 골격) 기능에 대한 테스트는 기존 테스트 파일 갱신
- 새 코드는 회귀 X (신규)
- **D12 (`_hrp_per_bucket` 반복 재분배)는 plan-eng-review 2차에서 발견·수정한 수학 버그 회귀 — IRON RULE 적용 (Section 9)**

---

## 9. Revision Coverage (plan-eng-review 1차·2차 후 추가된 경로)

두 라운드 production hardening revision으로 코드 경로 12개가 신규로 추가됨. 모두 unit test 작성 필수.

### 9.1 Plan 1 신규 경로

#### 9.1.1 `Universe.tradable_at(as_of)` (Plan 1 Task 14)
**파일:** `tests/unit/test_universe.py` 추가 케이스
- `tradable_at`이 listed_since > as_of ETF 제외
- `tradable_at`이 delisted_at <= as_of ETF 제외
- `listed_since=None`은 항상 tradable
- 부분 케이스 (일부 ETF만 listed_since 값 있음)

#### 9.1.2 `fetch_fred_series(as_of_date=...)` publication_lag (Plan 1 Task 17)
**파일:** `tests/unit/test_fred.py` 추가
- as_of=2026-05-25, lag=15 (us_cpi) → 2026-05-10까지만 반환
- as_of=None (live mode) → 전체 반환
- lag=1 (daily series) 기본값

#### 9.1.3 `fetch_ecos_series(as_of_date=...)` publication_lag (Plan 1 Task 18)
**파일:** `tests/unit/test_ecos.py` 추가
- 위와 동일 패턴, ECOS 시리즈 코드로

#### 9.1.4 `fetch_etf_snapshot_by_date` (Plan 1 Task 16)
**파일:** `tests/unit/test_pykrx_data.py` 추가
- 평일 → 188 ETF 한 번에 반환
- 주말/공휴일 → 빈 DataFrame
- cache 인자 전달 시 자동 append

#### 9.1.5 `setup_tracing` 분기 (Plan 1 Task 24)
**파일:** `tests/unit/test_tracing.py` 추가
- `LANGSMITH_TRACING=false` → no-op
- `LANGSMITH_TRACING=true` + key 있음 → 활성화 로그
- `LANGSMITH_TRACING=true` + key 없음 → 강제 disable + warning

#### 9.1.6 `traced` decorator pass-through (Plan 1 Task 24)
**파일:** `tests/unit/test_tracing.py`
- langsmith 미설치(또는 mock ImportError) 시 함수 그대로 반환
- D14 결정 후 dead code 블록 제거됨 — 단일 try/except 경로만 검증

### 9.2 Plan 2 신규 경로

#### 9.2.1 Direction-aware dedup (Plan 2 Task 22) **[→EVAL]**
**파일:** `tests/unit/skills/test_news_ranker.py` 추가
- "Fed cuts rates 25bp" + impact.direction="up" + assets={us_bond, us_equity}
- "Fed hikes rates 25bp" + impact.direction="down" + assets={us_bond, us_equity}
- 두 헤드라인 string similarity ≈ 0.92이지만 **dedup되지 않아야** (NOT same event)
- 같은 방향 + 같은 자산군 + 높은 유사도 → dedup
- Jaccard < 0.5 → dedup하지 않음

### 9.3 Plan 3 신규 경로 — 가장 critical

#### 9.3.1 `_optimize_with_bucket_constraints` strict equality (Plan 3 Task 14)
**파일:** `tests/unit/agents/test_portfolio_allocator.py` 추가
- 5-bucket weight (kr=0.15, global=0.30, fx=0.10, bond=0.35, cash=0.10) + 단일 cap 0.20
- attempts=0 → strict equality, 솔버 성공 케이스
- post-condition: 모든 weight ≤ 0.20 + 1e-6
- post-condition: 각 버킷 합 = target ± 1e-6

#### 9.3.2 `_optimize_with_bucket_constraints` ±5%p band fallback
- attempts=1 → strict 실패 mock + ±5%p band로 재시도 → 성공
- 버킷 합이 [target-0.05, target+0.05] 범위

#### 9.3.3 `_optimize_with_bucket_constraints` 합동 infeasibility
- 버킷 타겟·단일 cap·candidate 수가 jointly infeasible 케이스 → RuntimeError raise
- 예: bucket_target=0.95 + 4 candidates × 0.20 = 0.80 < 0.95

#### 9.3.4 **CRITICAL [REGRESSION]** `_hrp_per_bucket` bucket-sum 보존
**파일:** `tests/unit/agents/test_portfolio_allocator.py`
**IRON RULE — D12 수정한 수학 버그 회귀 방지**
- HRP가 (0.60, 0.20, 0.10, 0.10) 산출 + bucket_target=0.80 케이스
- 반복 재분배 후 sum(weights) ≈ 0.80 (단일 패스가 아닌 수렴)
- 모든 weight ≤ 0.20
- 추가 극단 케이스: HRP가 (0.95, 0.05, 0, 0) 산출 + target=0.20 → cap 안 걸림 정상
- HRP가 (0.4, 0.3, 0.2, 0.1) + target=0.70 → 4×0.175=0.70 cap 미만, 정상

#### 9.3.5 `select_etf_candidates(..., as_of)` (D13 적용 후)
**파일:** `tests/unit/skills/test_portfolio_candidate.py` 추가
- universe에 listed_since=2026-08-01 ETF 1개 + 2026-01-01 listed 4개
- as_of=2026-05-25 → 5개 중 4개만 후보 풀
- as_of=2026-09-01 → 5개 모두 후보 풀
- bucket_to_tickers 필드에 listed 안 된 ETF 미포함

#### 9.3.6 `_emergency_cash_portfolio`
**파일:** `tests/unit/agents/test_fallback.py`
- universe에 cash_mmf 카테고리 5개 → 균등 0.20씩
- universe에 cash_mmf 0개 → RuntimeError (manual review 필요)
- universe에 cash_mmf 3개 → 균등 0.333씩 (cap 안 걸림)

#### 9.3.7 `create_fallback_normalizer` 재최적화 경로
**파일:** `tests/unit/agents/test_fallback.py`
- 1차: original optimizer 결과 단일 25% 위반 → fallback 트리거
- 2차: fallback의 constrained min-volatility 성공 (모든 weight ≤ 0.20, sum ≈ 1.0)
- 3차: PyPortfolioOpt도 실패 mock → `_emergency_cash_portfolio`로 escalate

### 9.4 Plan 4 신규 경로

#### 9.4.1 `_ConditionParser` (Plan 4 Task 9, D14 후 eval 대체)
**파일:** `tests/unit/cli/test_daily_triggers.py` 추가
- `vix > 30` (단일 비교) — true/false 케이스
- `vix > 30 OR vkospi > 25` (OR)
- `spread_10y_2y_bps < -50 AND vix > 25` (AND)
- 알 수 없는 변수 → KeyError raise
- 잘못된 문법 → ValueError raise
- 음수 (`< -50`) 정상 파싱
- **eval()이 호출되지 않음** 명시 (보안 회귀 검증)

#### 9.4.2 daily_triggers 컨텍스트 4개 데이터 패치 (D15 후)
**파일:** `tests/unit/rebalance/test_daily_triggers.py` 추가
- vix_change_1d 계산 (FRED 2일치 mock)
- spread_10y_2y_bps 계산 (us_10y/us_2y mock)
- kospi_return_1d 계산 (pykrx index mock)
- any_etf_weight 계산 (portfolio.json + 가격 mock)
- 모든 값이 채워진 후 5개 트리거 모두 평가됨

### 9.5 신규 경로 합계

- Plan 1: 6개
- Plan 2: 1개 (eval 포함)
- Plan 3: 7개 (1개는 IRON RULE)
- Plan 4: 2개

**총 16개 추가 단위 테스트 + 1 eval.** 기존 ~80 GAPS와 합쳐 ~96 GAPS.

### 9.6 우선순위

1. **CRITICAL (IRON RULE):** 9.3.4 `_hrp_per_bucket` REGRESSION
2. **High:** 9.3.1~9.3.3, 9.3.5, 9.3.7 (Allocator 핵심 경로)
3. **Medium:** 9.1.x (data layer + tracing), 9.2.1 (news dedup eval)
4. **Low:** 9.4.x (CLI), 9.3.6 (cash 5개 가정)
