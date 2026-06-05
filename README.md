# DB GAPS Asset Allocation Agent

**제12회 DB GAPS 투자대회용 멀티에이전트 자산배분 시스템.** 국내 상장 ETF 유니버스를 대상으로 *top-down 매크로 진단 → 리서치 디베이트 → 포트폴리오 최적화 → 의무사항 검증 → 산출물 생성*을 자동화한다. LLM의 정성 판단과 정량 최적화를 결합하되, 대회 규칙(의무사항) 준수는 **결정론적으로 강제**한다.

> 대회 기간 2026-06-01 ~ 2026-08-31 · 초기 자본 10억 KRW · 투자 대상 국내 상장 ETF 188종(개별 주식 불가)

---

## 1. 목표 — 무엇을 푸는가

이 대회는 단순 수익률 경쟁이 아니라 **자산배분 철학**을 평가한다 (수익률 30점 + 투자철학 70점). 따라서 시스템의 목표는 두 가지다.

1. **건전한 top-down 자산배분** — 매크로 국면(regime)과 시장 시나리오를 진단하고, 그에 맞춰 위험/안전 자산을 분산 배분한다. 집중도·상관관계를 통제하는 게 수익률 추격보다 우선이다.
2. **대회 의무사항 자동 준수** — 규칙 위반은 경고 없이 즉시 컷오프(탈락)되므로, 시스템이 매 실행마다 검증 책임을 진다.

**의무사항(mandate) — `gaps`가 매 실행마다 검증:**

| 규칙 | 제약 |
|---|---|
| 위험자산 비중 | ≤ **70%** (국내·해외 주식 + FX·원자재 ETF) |
| 단일 ETF 비중 | ≤ **20%** |
| 초기 회전율 | ≥ **80%** (개시 후 5영업일 내) |
| 월간 회전율 | ≥ **10%** (매월) |
| 상관 클러스터 | 고상관 군집 비중 cap |

산출물은 매 실행 3종: `portfolio.json`(전체 추적), `philosophy.md`(투자철학 서술서, 대회 제출용 ≥4쪽), `trade_plan.csv`(MTS 입력용 매매계획).

---

## 2. 아키텍처 — 어떻게 구성돼 있는가

[LangGraph](https://github.com/langchain-ai/langgraph) 기반 6-stage 파이프라인. 진입점은 [`TradingAgentsGraph`](tradingagents/graph/trading_graph.py), 그래프 조립은 [`graph/builder.py`](tradingagents/graph/builder.py)에 있다.

```
                        ┌─ macro_quant  (매크로 regime)
                        ├─ market_risk  (시스템 리스크)
   START ──(병렬)──────┤                                  Stage 1: 분석가 4종
                        ├─ technical    (가격 모멘텀)
                        └─ macro_news   (뉴스·이벤트·테마)
                              │  (각자 요약 handoff)
                              ▼
                     research_debate     Stage 2: Bull / Bear / Manager 디베이트
                              │            → 확신도(conviction) + 시나리오(scenario)
                              ▼
                       allocator         Stage 3: 14-bucket 배분 → ETF 가중치
                              │            (regime anchor → LLM tilt → 결정론적 후보선정 → 최적화)
                              ▼
                       validator         Stage 5: 의무사항 4종 검증
                              │
                 ┌────────────┼────────────┐  (validation_router)
            finalize     retry_allocator  fallback
                 │            (≤2회)         │  (clip + min-variance 강제 통과)
                 ▼                           ▼
                       portfolio_manager   Stage 6: portfolio.json + philosophy.md + trade_plan.csv
                              │
                             END
```

> Stage 4(별도 risk overlay)는 제거됐다 — allocator가 직접 위험 cap을 수선(repair)하고 validator로 직결된다.

각 stage는 **요약(summary) handoff** 방식으로 연결된다. 분석가는 ≤2KB 마크다운 요약 + 구조화된 Pydantic report만 다음 stage로 넘기고, 디베이트 같은 클러스터는 내부 shared state를 쓰되 부모에게는 요약만 반환한다. 모든 LLM 출력은 Pydantic 스키마에 묶여(schema-locked) 있어 형식 붕괴를 막는다.

---

## 3. 파이프라인 상세

### Stage 1 — 분석가 4종 (병렬)

서로 **직교(orthogonal)하는 4개 축**으로 시장을 분해한다. 각 분석가는 다수의 결정론적 skill을 오케스트레이션해 스냅샷 report를 만들고, ≤500자 한국어 narrative로 요약한다.

| 분석가 | 무엇을 보는가 | 핵심 출력 |
|---|---|---|
| [`macro_quant`](tradingagents/agents/analysts/macro_quant_analyst.py) | 매크로 펀더멘털 (FRED·ECOS) → 성장/인플레 **regime 분류(4사분면)** | `RegimeClassification`(quadrant, confidence) |
| [`market_risk`](tradingagents/agents/analysts/market_risk_analyst.py) | 시스템 리스크 (VIX/VKOSPI, 신용스프레드, breadth, PCA, 펀딩) | `systemic_score`(0–10) |
| [`technical`](tradingagents/agents/analysts/technical_analyst.py) | 유니버스 가격 신호 (skip-1m 모멘텀, 상관 클러스터, breadth, 섹터 회전) | 모멘텀 랭킹·추세 상태 |
| [`macro_news`](tradingagents/agents/analysts/macro_news_analyst.py) | 뉴스·이벤트 (RSS + SAVE 브리핑) — 5-tier | 카테고리·테마·감성 스냅샷 |

**왜 4축으로 나눴나** — 매크로 ≠ 리스크 ≠ 모멘텀 ≠ 뉴스. 예컨대 regime 분류는 **가격이 아니라 매크로 변수만**으로 한다(내생성 회피). 신용 사이클은 GDP 사이클과 다르고, 가격 모멘텀은 펀더멘털과 다르며, FOMC·지정학 충격은 FRED에 안 잡힌다. 4축을 독립 계산하면 각 축을 따로 검증·디버깅할 수 있고, Stage 2 디베이트가 각 분석가의 요약을 **독립적으로 인용**해 논거를 조립할 수 있다.

> **`macro_news`는 최근 개선됨** ([categorizer.py](tradingagents/skills/news/categorizer.py)): ① 거시·지정학 RSS 소스를 보강하고, ② `prioritize_macro_relevant`로 거시·지정학 뉴스를 impact-classify 예산(상위 N건) 앞쪽에 배치해 종목 뉴스 볼륨에 묻히지 않게 했으며, ③ `category`(성격)와 **직교하는 `ThemeTag` 6종**(ai_semis·ev_battery·energy·defense_space·biotech_health·crypto_fintech)을 더해 섹터 테마 지형을 stage2로 전달한다.

### Stage 2 — 리서치 디베이트 (Bull / Bear / Manager)

[`research_cluster`](tradingagents/agents/researchers/research_cluster.py)가 Stage 1 요약을 받아 **강세론(bull)·약세론(bear)**을 각각 전개하고, manager가 둘을 종합해 구조화된 투자 thesis를 만든다.

- **출력**: `conviction`(high/medium/low) + `dominant_scenario`(kr_boom·kr_stress·global_credit·ai_concentration·neutral 등) + `thesis_md` + `key_risks`
- **왜 디베이트인가** — 단일 모델은 편향된다. bull/bear가 동일 사실을 적대적으로 재해석해 완전성을 확보한다. 그리고 `conviction`은 다운스트림 배분의 **허용 밴드(latitude)**를 정량적으로 좌우한다(high ×1.4, medium ×1.0, low ×0.6). 약한 신호에 과도하게 기울지 않게 하는 장치다. `scenario`는 Stage 3의 bucket tilt에 직접 연결된다.

### Stage 3 — 포트폴리오 최적화 (핵심)

[`trader_allocator`](tradingagents/agents/trader/trader_allocator.py)가 매크로 regime + 시나리오를 **14-bucket** 가중치로, 다시 개별 ETF 가중치로 변환한다.

**14 allocation buckets** ([gaps_buckets.py](tradingagents/skills/portfolio/gaps_buckets.py)):
- 방어 A1–A5: 현금·KR금리·US금리·안전FX·금/인플레헤지
- 성장 B1–B9: KR주식·선진코어·글로벌테크·중국·기타해외·방어주식·리츠·경기민감원자재·위험크레딧

**2단계 배분:**
1. **Step A (LLM tilt)** — regime 4사분면별 `QUADRANT_BASELINE` 앵커에서 시작 → 시나리오 modifier(±5%p, 합≈0)를 더한 뒤 → LLM이 confidence·conviction으로 좁혀진 **hard band 안에서만** 기울인다. LLM은 구조적 한계를 깰 수 없다.
2. **Step B (결정론적 후보 선정)** — bucket별로 후보 ETF를 거르고(카테고리·AUM·상장일), regime-조건부 필터(인플레 국면엔 단기 듀레이션, 달러 강세엔 unhedged 우선)로 점수화·선정한다. LLM 변동 없이 매일 재현 가능하다.

**최적화 엔진:**
- **method 선택**(deterministic lookup): regime·시나리오·systemic_score → HRP(기본) / Risk Parity / Min-Variance / **Black-Litterman**(강한 view 시)
- **NCO**(Nested Clustered Optimization, [nco.py](tradingagents/skills/portfolio/nco.py)) — 상관 기반 계층 군집으로 집중 위험을 구조적으로 분산
- **공분산 shrinkage** ([cov_estimator.py](tradingagents/skills/portfolio/cov_estimator.py)) — Ledoit-Wolf 선형 + QIS 비선형 (소표본 공분산의 잡음 억제)
- **Black-Litterman views** ([bl_views.py](tradingagents/skills/portfolio/bl_views.py)) — 시나리오별 기대수익 rulebook을 view로 주입(ETF별 alpha 추정 불필요)
- **ENB**(Effective Number of Bets) 제약 — 허상 분산(near-collinear 자산)을 감지하면 등가중 fallback
- **제약 주입 + water-filling** — 20% 단일 cap, 70% 위험자산 cap을 사후 clip이 아니라 최적화 단계에서 강제

**왜 이렇게** — 14-bucket은 5-자산군보다 세분돼 regime별 헤징 규칙(채권 듀레이션, FX 헤지)을 분리 적용할 수 있다. NCO·BL·shrinkage는 순수 평균-분산 최적화(MVO)의 약점(소표본 불안정, 집중)을 보완한다. Step B를 결정론적으로 둔 건 **같은 입력 → 같은 결정**(재현성)을 위해서다.

### Stage 5 / 6 — 검증 + 포트폴리오 매니저

[`mandate_validator`](tradingagents/agents/validator/mandate_validator.py)가 **LLM 없이** 의무사항 4종 + 무결성(weight 합=1, NaN/Inf)을 검사한다. hard violation이 나면 [`validation_router`](tradingagents/graph/conditional_logic.py)가 분기한다:

```
통과 → portfolio_manager
실패 & 시도<2 → allocator 재시도 (위반 피드백을 LLM 프롬프트에 주입)
실패 & 시도≥2 → fallback_normalizer (엄격 bound로 min-variance 재최적화, 최후엔 안전자산 등가중)
```

**왜 검증→재시도→fallback 사이클인가** — allocator가 soft-cap을 해도 최적화 결과가 hard 제약을 어길 수 있다. validator를 allocator와 **독립**으로 둬 defense-in-depth를 만들고, 실패 시 결정론적 재시도 → 수학적으로 보장된 fallback으로 **운용 중단(블랙박스)을 회피**한다.

[`portfolio_manager`](tradingagents/agents/managers/portfolio_manager.py)는 최종 3종을 만든다:
- `portfolio.json` — Stage 1–5 전 과정 attribution을 담은 full trace
- `philosophy.md` — Stage 1–5 분석을 인용한 6섹션 투자철학 서술 (LLM, ≥4000자)
- `trade_plan.csv` — `수량 = 매수금액 ÷ 직전 영업일 종가` (KRX OpenAPI는 T+1~T+2 지연이라 당일 종가가 없으면 최근 영업일로 walk-back)

---

## 4. 데이터 레이어 — 방어적으로 설계

[`tradingagents/dataflows/`](tradingagents/dataflows/)는 외부 소스를 방어적으로 가져온다.

| 소스 | 가져오는 것 |
|---|---|
| **FRED** | 미국 매크로 50+ 시계열 (금리·CPI/PCE·고용·CFNAI·NFCI·스프레드) |
| **ECOS** (한은) | 한국 매크로 (기준금리·CPI·수출입·산업생산·CLI·BSI·국고채) |
| **pykrx / KRX OpenAPI** | 188 ETF 일별 OHLCV, KOSPI/VKOSPI, 현재가 |
| **KOFIA FreeSIS** | 시장 전체 신용잔고 (유일한 공식 소스) |
| **yfinance** | 글로벌 주식·섹터·overnight 지수 (STOXX/N225/WTI/USDKRW 등) |
| **BIS / Shiller / GPR** | 중국 신용 impulse, 미국 CAPE, 지정학 리스크 지수 |
| **SAVE 브리핑** | 매크로 애널리스트 일일 브리핑 (GitHub repo에서 fetch) |

**3중 방어:**
1. **Rate-limit gate** — FRED 120/분 한도를 110/분으로 선제 제어 + 429 재시도(exponential backoff)
2. **Hard timeout** ([`_run_with_timeout`](tradingagents/dataflows/pykrx_data.py)) — pykrx 소켓 hang을 daemon thread 30s로 격리 (파이프라인 freeze 방지)
3. **PIT guard** ([`pit_guard.py`](tradingagents/dataflows/pit_guard.py)) — `as_of`가 7일 이상 과거면 live-only 데이터를 비워 backtest look-ahead 편향 차단

여기에 **TieredCache**(당일 0-API, 빈 캐시 `{}`는 miss로 처리), **publication lag**(CPI 15d·JOLTS 45d 등 발표 지연 반영), **FRED fallback 체인**이 라이브 신뢰성을 받친다.

---

## 5. 왜 이렇게 설계했는가 (핵심 원칙)

1. **정량 결정 + LLM 서술 분리** — regime 분류·systemic 점수·method 선택·후보 선정은 모두 결정론적이다. LLM은 사실이 확정된 뒤 **서술(thesis·philosophy)과 밴드 내 미세 tilt**만 맡는다. 주간 재배분의 재현성을 위해 의사결정 게이트에서 LLM 비결정성을 배제한다.
2. **멀티에이전트 분업** — 4 분석가 병렬 → bull/bear가 사실을 재발견하지 않고 *해석*만 → allocator는 raw 메시지가 아닌 요약을 읽어 인지 집중 → validator는 allocator 추론과 독립으로 규칙 검사. 단계별 책임 분리(defense-in-depth).
3. **요약 handoff topology** — 단계 간엔 요약만, 디베이트 클러스터 내부만 shared state. 모놀리식 공유 대비 토큰·상태 폭발을 줄인다.
4. **결정론적 의무 검증을 LLM 위에** — 최적화기가 규칙을 어겨도 validator가 잡고, 재시도→fallback으로 수학적 안전망을 둔다.
5. **regime/scenario 기반 배분** — "알아서 배분해줘" 프롬프트 대신, 시장 분류체계(4사분면 × 시나리오)를 존중하는 결정론적 DAG로 bucket target·method·테마 부스트를 유도한다.
6. **데이터 방어 우선** — 라이브 API는 불안정하다는 전제로 cache·timeout·rate-limit·PIT·fallback을 겹겹이 쌓는다. 최후엔 안전자산 등가중 포트폴리오로 착지한다.

---

## 6. 사용법

```bash
# 설치 (pure Python — TA-Lib 시스템 패키지 불필요)
pip install -e ".[test]"

# 환경변수: FRED_API_KEY, ECOS_API_KEY, OPENAI_API_KEY, KRX OpenAPI 키 등
cp .env.example .env        # 편집

# 유니버스 생성/갱신 (188 ETF)
gaps universe sync

# 전체 파이프라인 실행 → artifacts/{date}/ 에 3종 산출
gaps plan --date 2026-06-05 --capital 1000000000
```

`gaps`는 Click 기반 CLI([`cli/main.py`](cli/main.py))이며 주요 서브커맨드:

| 명령 | 용도 |
|---|---|
| `gaps plan` | 전체 파이프라인 (분석→배분→검증→산출물) |
| `gaps rebalance` | 3-tier 재배분 (일/주/월) |
| `gaps macro` | 단일 분석가 디버그 (regime/risk/news/technical) |
| `gaps validate` | 포트폴리오 의무사항 검증 |
| `gaps simulate` | 과거 성과 시뮬레이션 (수익/변동성/MDD/Sharpe) |
| `gaps report` | 리포트 생성 (philosophy/monthly/trade-plan) |
| `gaps monitor` | 운영 모니터링 (회전율/노출/drift) |
| `gaps universe` | 유니버스 관리 |

> (선택) Observability: `.env`에 `LANGSMITH_TRACING=true` 등을 넣으면 모든 run이 [LangSmith](https://smith.langchain.com/)에 trace된다. 모든 stage 출력은 `~/.tradingagents/runs/{date}/`에 archive되어 [`scripts/replay_stage.py`](scripts/replay_stage.py)로 LLM 재호출 없이 단일 stage 재현이 가능하다.

---

## 7. 프로젝트 구조

```
tradingagents/
├── graph/          # LangGraph 조립 — trading_graph(진입점), builder(topology), conditional_logic(router/fallback)
├── agents/
│   ├── analysts/   # Stage 1: macro_quant · market_risk · technical · macro_news
│   ├── researchers/# Stage 2: research_cluster (bull/bear/manager)
│   ├── trader/     # Stage 3: trader_allocator
│   ├── validator/  # Stage 5: mandate_validator
│   └── managers/   # Stage 6: portfolio_manager
├── skills/         # 결정론적 skill 카탈로그 (@register_skill) — macro/risk/technical/news/portfolio/mandate
│   └── portfolio/  # 배분 핵심: gaps_buckets · candidate_selector · nco · bl_views · cov_estimator · scenario_anchor
├── dataflows/      # 데이터 fetcher + 캐시 + 방어 (fred/ecos/pykrx/krx_openapi/kofia/.../cache/pit_guard)
├── schemas/        # Pydantic 모델 (macro/news/research/mandate/reports)
├── observability/  # run archive + stage replay
├── presets/        # YAML preset 로더 (db_gaps.yaml = 기본 구성)
└── llm_clients/    # 2-tier LLM 팩토리 (deep/quick, OpenAI/Anthropic/Google/...)

cli/                # gaps CLI (Click) — commands/{portfolio,macro,analysis,report,monitor,universe,preset}
scripts/            # 운영·재현 스크립트 (fetch_save_brief, enrich_universe, run_backtest, replay_stage, ...)
data/               # universe.json(188 ETF) · SAVE/(브리핑) · historical_anchors · cache
presets/ · prompts/ · docs/
tests/              # 단위·통합·smoke·eval 테스트 (pytest, 마커: unit/integration/slow/eval/network)
```

**구성 가능성**: skill은 `@register_skill` 데코레이터로 등록되고, 파이프라인 topology는 preset YAML로 정의된다. 비엔지니어도 stage·병렬성·모델 tier를 코드 수정 없이 바꿀 수 있다. LLM은 2-tier(추론 무거운 deep / 경량 quick)로 비용·지연을 최적화한다.

## 8. 개발 / 테스트

```bash
pytest tests/unit -q                       # 단위 테스트 (빠름)
pytest tests/ -m 'not slow and not eval'   # 단위 + 통합
pytest tests/ -m slow                       # 풀 파이프라인 E2E (mock)
pytest tests/ -m eval                       # LLM 품질 eval (실 API 필요)
```

설계 배경 문서는 [`docs/`](docs/) (디자인 스펙·아키텍처 리뷰·대회 규칙), 미해결 항목은 [`TODOS.md`](TODOS.md) 참조.

---

*이 README는 현재 `gaps` 파이프라인([`graph/trading_graph.py`](tradingagents/graph/trading_graph.py) 기준)을 반영한다. 과거 단일 종목 트레이딩 코드 일부가 패키지에 남아 있으나, 현재 자산배분 파이프라인의 실행 경로에는 포함되지 않는다.*

*본 프로젝트는 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) 오픈소스를 기반으로 출발했으며, DB GAPS 자산배분 과제에 맞춰 재설계됐다.*
