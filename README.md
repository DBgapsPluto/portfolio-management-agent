# DB GAPS Asset Allocation Agent (v0.3)

**제12회 DB GAPS 투자대회용 멀티 에이전트 자산배분 시스템.** 한국 ETF 188종목을 대상으로 top-down 매크로 진단 → 리서치 디베이트 → 포트폴리오 최적화 → 리스크 검증 → 의무사항 검증의 6 stage 파이프라인을 수행한다.

> **대회 기간**: 2026-06-01 ~ 2026-08-31 · **포트폴리오 제출 마감**: 2026-05-28 · **초기 자본**: 10억 KRW

## 프로젝트 상태

| Plan | 영역 | 상태 |
|---|---|---|
| 1 | Foundation (schema · dataflows · cache · BaseSubagent) | ✅ |
| 2 | Skills 카탈로그 (16 subagents · 4 optimizers · 4 mandate validators) | ✅ |
| 3 | Agents (4 analysts · debate sub-graphs · allocator · validator · PM) | ✅ |
| 4 | CLI · Reports · 3-tier rebalance · E2E mock test | ✅ |

- **테스트**: 275 passing · 9 deselected (`slow` E2E + `eval`은 opt-in)
- **5/28 ready**: `gaps plan` 실행 시 portfolio.json + philosophy.md + trade_plan.csv 3종 산출

## Setup

```bash
pip install -e ".[test]"            # pure Python (TA-Lib 시스템 패키지 불필요)
cp .env.example .env                # FRED_API_KEY, ECOS_API_KEY, OPENAI_API_KEY 등 입력
gaps universe sync                  # data/universe.json 생성 (188 ETF)
```

(선택) Observability: `.env`에 `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY=...`, `LANGSMITH_PROJECT=db-gaps-agent`을 추가하면 모든 multi-agent run이 https://smith.langchain.com/ 에 trace됨.

## 시스템 아키텍처

**Hybrid topology γ** — stage 간 summary handoff + debate cluster 내 shared state. 6 stage 파이프라인:

```
[stage 1] Analysts (병렬 4)
  ├─ macro_quant   ┐
  ├─ market_risk   │
  ├─ technical     ├─→ summaries
  └─ macro_news    ┘
        │
[stage 2] Research debate (sub-graph, D2 격리)
  Bull ⇄ Bear ↔ Research Manager → BucketTarget(5-bucket)
        │
[stage 3] Portfolio Allocator
  method_picker → 4 optimizers + constraint injection
  (단일 ETF ≤ 20%, sector cap, weight bounds)
        │
[stage 4] Risk debate (Aggressive/Conservative/Neutral → Risk Judge)
        │
[stage 5] Mandate Validator (4 룰)
  pass → finalize
  fail (≤2회) → Allocator 재시도
  fail (>2회) → fallback normalizer (clip + renormalize)
        │
[stage 6] Portfolio Manager → 3 산출물
```

핵심 결정사항(D1-D17)은 `docs/superpowers/specs/2026-05-09-db-gaps-agent-redesign-design.md` Appendix 참조.

## Skills 카탈로그 (16 subagents · 6 도메인)

| 도메인 | 모듈 |
|---|---|
| `macro` | regime_classifier, yield_curve, inflation, employment, divergence, calendar, fred_fetcher, ecos_fetcher |
| `risk` | systemic_score, volatility, correlation_pca, credit_spread, fear_greed, breadth |
| `technical` | correlation_cluster, momentum_ranker, ta_indicators, trend_state, price_batch |
| `news` | impact_classifier, news_fetcher, ranker, event_calendar |
| `portfolio` | candidate_selector, method_picker, optimizers (HRP/RP/MinVar/BL), returns_matrix |
| `mandate` | universe_check, concentration_check, turnover_check, correlation_check |

모든 LLM 콜은 Pydantic v2 schema-locked structured output. Tenacity 기반 retry + TieredCache(D5, max staleness 7일) fallback.

## Optimizer 4종 (PyPortfolioOpt 기반)

| 방법 | 적용 시 | 비고 |
|---|---|---|
| **HRP** (Hierarchical Risk Parity) | 기본값 (전 regime) | iterative water-filling으로 20% cap 보장 |
| **Risk Parity** | growth_disinflation | 동일 위험 기여도 |
| **Min Variance** | recession 계열 | `add_sector_constraints` + weight bounds |
| **Black-Litterman** | 강한 view 존재 시 | views를 BucketTarget으로 주입 |

⚠️ **Critical fix**: 기존 post-scaling 방식은 20% cap을 사후 위반. 현재 구현은 **constraint injection** (최적화 단계에서 강제) → mandate 자동 통과.

## 5/28 제출용 파이프라인

```bash
gaps universe sync                                # 188 ETF universe.json
gaps macro regime --date 2026-05-25               # 매크로 진단 미리 확인
gaps plan --date 2026-05-25 --capital 1000000000  # 풀 파이프라인 (3 산출물)

# 검증 + 분석
gaps analysis validate --portfolio artifacts/2026-05-25/portfolio.json
gaps analysis correlate --portfolio artifacts/2026-05-25/portfolio.json --cluster
gaps analysis simulate --portfolio artifacts/2026-05-25/portfolio.json --window 3y

# 보고서 (대회 §4 제출 형식)
gaps report philosophy --portfolio artifacts/2026-05-25/portfolio.json   # ≥4000자 한국어
gaps report trade-plan --portfolio artifacts/2026-05-25/portfolio.json   # MTS 입력 CSV
```

## 운용 중 (6/1~8/31) — 3-tier 리밸런싱

```bash
gaps rebalance daily                              # 매일 — 룰 기반 트리거 (LLM 없음)
                                                  # VIX/VKOSPI/yield curve/KOSPI/drift 평가
gaps rebalance weekly --week 24                   # 매주 — macro+risk만, ±5%p tilt
gaps rebalance monthly --month 6                  # 월말 — 풀 파이프라인 + 월간 보고서

# 모니터링
gaps monitor turnover --transactions june.csv     # 회전율 floor (초기 80% / 월 10%)
gaps monitor exposure --portfolio current.json    # 자산군별 비중 + risk/safe split
gaps monitor drift --portfolio current.json --prices-csv mts.csv  # 가격 변동 drift
gaps monitor cost --transactions june.csv         # 수수료 + 슬리피지 (bps)

# 월간 보고서 (대회 §4.2)
gaps report monthly --month 6 --actual june_pnl.csv
```

## CLI 전체 (22개 명령)

| 그룹 | 명령 | 비고 |
|---|---|---|
| `universe` | `sync` · `list` · `info` | xlsx → universe.json (188 ETF) |
| `macro` | `regime` · `risk` · `news` · `technical` | 단독 분석가 디버그 |
| `portfolio` | `plan` · `rebalance {daily,weekly,monthly}` · `optimize` | 메인 진입점 |
| `analysis` | `correlate` · `validate` · `simulate` | 1y/3y/5y 백테스트 포함 |
| `report` | `philosophy` · `monthly` · `trade-plan` | 3 산출물 생성 |
| `monitor` | `turnover` · `exposure` · `drift` · `cost` | 운용 중 추적 |
| `preset` | `list` · `run` | YAML 기반 프리셋 |

## DB GAPS mandate (자동 검증)

자동 검증은 stage 5에서 4-rule check + cycle (D4):

- ✅ **위험자산 ≤ 70%** — 단순 비중 합산 + 상관관계 cluster cap
- ✅ **단일 ETF ≤ 20%** — Allocator 제약 주입 단계에서 보장
- ✅ **회전율 floor** — 초기 5영업일 ≥ 80%, 월간 ≥ 10% (cap 없음, monitor만)
- ✅ **188 ETF 풀 외 매수 금지** — universe_check가 강제

위반 시 ≤ 2회 Allocator 재시도, 이후 fallback normalizer가 clip + renormalize로 강제 통과.

## 개발 / 테스트

```bash
pytest tests/ -m 'not slow and not eval'   # 단위 + 통합 (~3s, 275 passing)
pytest tests/ -m slow                       # 5/28 E2E gold-standard mock test
pytest tests/ -m eval                       # 8-case regime classifier eval (실 LLM 필요)
```

핵심 통합 테스트:
- `tests/integration/test_5_28_dry_run.py` — 풀 파이프라인 mock E2E (D9 gold standard)
- `tests/integration/test_validator_cycle.py` — D4 Validator → Allocator 사이클
- `tests/integration/test_cache_fallback.py` — D5 TieredCache fallback
- `tests/integration/test_eval_regime_classifier.py` — 8 historical regime cases (opt-in)

## 설계 문서

- 디자인 스펙: `docs/superpowers/specs/2026-05-09-db-gaps-agent-redesign-design.md` (17 결정 포함)
- 4개 plan: `docs/superpowers/plans/2026-05-10-db-gaps-plan-{1-foundation,2-skills,3-agents,4-cli}.md`
- 사전 요구: `docs/db-gaps-prerequisites.md`
- 테스트 플랜: `docs/db-gaps-test-plan.md`
- 미해결 follow-up: `TODOS.md`
- 대회 규칙: `docs/DB_GAPS_Investment_Tournament_Rules.md`

---

본 프로젝트는 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) 오픈소스 코드를 기반으로 구축되었습니다.
