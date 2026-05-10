# DB GAPS 자산배분 에이전트 — 아키텍처 재설계 (Spec)

- **작성일:** 2026-05-09
- **대상 코드베이스:** `/Users/kimjaewon/Pluto/TradingAgents` (TradingAgents v0.2.4 fork)
- **대회:** 제12회 DB GAPS 투자대회 (2026-06-01 ~ 2026-08-31)
- **목적:** 기존 종목 단위 stock-picking 프레임워크를 KR ETF 188종 자산배분 의사결정 지원 시스템으로 in-place 갈아끼움

---

## 1. 문제 정의

### 1.1 대회 제약 (요약)
- **유니버스:** KR 상장 ETF/ETN 188종 (외부 xlsx로 고정)
- **자본:** 10억 KRW, 6/1~8/31 (3개월), MTS 수동 매매
- **비중 한도:** 위험자산 ≤70%, 단일 ETF ≤20%, 안전자산 무제한
- **회전율 floor (컷오프 직결):** 초기 5영업일 누적 ≥80%, 월별 ≥10%
- **평가:** 수익률 30점 + **투자철학 70점** (철학 일관성 + 시장 충격 방어 논리 + **단일 리스크 통제** 핵심)
- **보고서:** 5/28 투자계획서, 6·7·8월 운용보고서 (직접 작성 필수)

### 1.2 기존 TradingAgents의 부적합성
- 단일 종목 stock-picking (Fundamentals + Sentiment) — ETF 자산배분에 0% 적용
- BUY/HOLD/SELL 결정 — weight vector가 아님
- 종목별 토론 — 188종에 적용 불가능

### 1.3 본 설계의 핵심 명제
**"LLM은 narrative composer, 데이터·계산·판단은 결정론적 skill"** (Anthropic financial-services 패턴 + Vibe-Trading의 DAG handoff 토폴로지 결합)

---

## 2. 목표 / 비목표

### 2.1 목표
1. KR ETF 188종 유니버스에서 top-down 자산배분 의사결정 지원
2. 5/28 투자계획서·6·7·8월 월간 보고서 자동 생성 (사람이 손볼 가능한 마크다운/docx)
3. 일·주·월 3-tier 리밸런싱 (트리거 기반 daily, 전술 weekly, 전략 monthly)
4. Mandate Validator로 대회 룰 hard 검증 (위반 시 자동 재토론)
5. 회전율 floor 추적 + 자산군 노출도 모니터링
6. CLI 22개 서브커맨드, 각 명령은 독립 실행 + chain 가능

### 2.2 비목표
- 자동 매매 (MTS 수동 매매 전제)
- 단일 종목 alpha 분석 (DART 등 폐기)
- 188개 ETF 종목별 LLM 토론
- 백테스트 엔진 풀 구현 (PyPortfolioOpt 자체 metric으로 충분)
- 다중 통화 처리 (KRW 단일)

---

## 3. 아키텍처 개관

### 3.1 Top-down 깔때기

```
거시지표·시장리스크·뉴스·188 ETF 가격 (raw)
              ↓
    [Stage 1: 4 ANALYSTS — skill orchestrators]
              ↓ summary handoff (Pydantic + ≤500자 narrative)
    [Stage 2: BULL/BEAR DEBATE — 자산군 비중 토론, 클러스터 내 공유 state]
              ↓ summary handoff
    [Stage 3: RESEARCH MANAGER — 5-bucket weight target]
              ↓ summary handoff
    [Stage 4: PORTFOLIO ALLOCATOR — 188 → 18~25개 후보 + PyPortfolioOpt weights]
              ↓ summary handoff
    [Stage 5: RISK DEBATE — Aggressive/Conservative/Neutral, 클러스터 내 공유 state]
              ↓ summary handoff
    [Stage 6: MANDATE VALIDATOR — 결정론적 hard rule]
              ↓ pass | fail (재토론 트리거)
    [Stage 7: PORTFOLIO MANAGER — 산출물 3종 생성]
              ↓
artifacts/{portfolio.json, philosophy.md, trade_plan.csv}
```

### 3.2 그래프 토폴로지: 하이브리드 (결정 1 = γ)

| 단계 간 (stage-to-stage) | summary handoff (≤2KB markdown + Pydantic 구조화 데이터) |
|---|---|
| 토론 클러스터 내 (Bull↔Bear, Risk 3인) | 공유 state (raw message, cross-examination 가능) |

**구현 방식:**
- 외부 그래프: LangGraph state에 `analyst_summaries: dict[str, AnalystSummary]` 형태로 요약만 보관
- 토론 클러스터: 별도 sub-graph로 컴파일, 자체 `messages` 누적, 클러스터 종료 시 summary만 외부 state에 다시 주입
- 비용: 단일 공유 state 대비 토큰 ~70% 절감, 토론 품질은 유지

### 3.3 Skill-based Analyst 패턴

```
┌──────────────────────────────────────────────────┐
│ Analyst LLM (얇은 orchestrator)                   │
│  ① Pydantic 출력 스키마 강제                       │
│  ② 화이트리스트된 skill만 호출                       │
│  ③ narrative 필드(≤500자)만 자유 작성               │
│  ④ 모든 숫자·날짜는 skill 결과에서만 가져옴          │
└──────────────────────────────────────────────────┘
       ↓
┌──────────────────────────────────────────────────┐
│ Skills (2종)                                     │
│ ▸ Deterministic skill: Python (API/수학), LLM x  │
│ ▸ Subagent skill: 작은 LLM + Pydantic schema lock │
└──────────────────────────────────────────────────┘
```

**Subagent 모델 정책 (결정 C):** skill별 지정. 핵심 판단(`classify_regime`, `pick_optimization_method`, `score_systemic_risk`)은 deep model, 보조 판단(`classify_event_impact` 등)은 quick model.

---

## 4. Preset YAML 시스템 (결정 2)

### 4.1 동기
대회 변형·전략 변형·실험을 코드 변경 없이 지원하기 위해 분석가·토론자·할당자 구성을 YAML로 선언.

### 4.2 구조

```yaml
# presets/db_gaps.yaml
name: db_gaps_v1
universe: data/universe_2026-05-09.json
capital_krw: 1_000_000_000

stages:
  - id: analysts
    parallel: true
    agents:
      - id: macro_quant
        skills: [fred_series, ecos_series, yield_curve, inflation_trend,
                 employment_trend, regime_classifier, kr_divergence,
                 central_bank_calendar]
        output_schema: MacroReport
        model: deep
        timeout_seconds: 180
        skill_prompt_base: prompts/macro-analysis.md  # Vibe-Trading 한국화 본문

      - id: market_risk
        skills: [volatility_index, credit_spread, fear_greed,
                 market_breadth, correlation_breakdown, systemic_score]
        output_schema: RiskReport
        model: deep

      - id: technical
        skills: [etf_price_batch, ta_indicators, rank_momentum,
                 detect_trend_state, find_correlation_clusters]
        output_schema: TechnicalReport
        model: quick   # 거의 narrative만

      - id: macro_news
        skills: [event_calendar, macro_news_fetch, classify_event_impact,
                 dedupe_rank_news]
        output_schema: NewsReport
        model: quick

  - id: research_debate
    cluster_mode: shared_state
    rounds: 1
    agents:
      - id: bull_researcher
        cited_evidence_required: true
      - id: bear_researcher
        cited_evidence_required: true
    judge:
      id: research_manager
      output_schema: BucketTarget    # 5-bucket weight target

  - id: allocation
    agents:
      - id: portfolio_allocator
        skills: [select_etf_candidates, fetch_returns_matrix,
                 optimize_hrp, optimize_risk_parity, optimize_min_variance,
                 optimize_black_litterman, pick_optimization_method]
        input_from:
          bucket_target: research_manager
          universe: universe_loader
          regime: macro_quant
          risk_score: market_risk
          clusters: technical
        output_schema: WeightVector

  - id: risk_debate
    cluster_mode: shared_state
    rounds: 1
    agents:
      - id: aggressive_debator
      - id: conservative_debator
      - id: neutral_debator
    judge:
      id: risk_judge
      output_schema: WeightAdjustment

  - id: validation
    agents:
      - id: mandate_validator   # deterministic, no LLM
        skills: [validate_universe, validate_concentration,
                 validate_turnover_feasibility, validate_correlation_concentration]
        on_fail: rerun_from(allocation, max_attempts=2)

  - id: finalize
    agents:
      - id: portfolio_manager
        outputs: [portfolio_json, philosophy_md, trade_plan_csv]
```

### 4.3 향후 확장
- `presets/db_gaps_emergency.yaml` (위기 모드, 안전자산 강조)
- `presets/db_gaps_offensive.yaml` (공격 모드)
- `presets/research_only.yaml` (분석만, 매매 X)
- `presets/db_gaps_v2.yaml` (다음 회차)

---

## 5. 데이터 레이어

### 5.1 유니버스 캐시
- **소스:** `docs/제12회 GAPS ETF 리스트 (2026-5-9 게시).xlsx`
- **변환:** `gaps universe sync` 명령이 다음 구조로 정규화

```json
{
  "version": "2026-05-09",
  "etfs": [
    {
      "ticker": "A411060",
      "name": "ACE KRX금현물",
      "aum_krw": 5230295139554,
      "underlying_index": "KRX 금현물지수",
      "bucket": "위험",
      "category": "FX 및 원자재",
      "price_source": "pykrx"
    }
  ],
  "buckets": {
    "위험": {"max_weight": 0.70},
    "안전": {"max_weight": null}
  },
  "categories": [
    "FX 및 원자재", "해외주식_지수", "해외주식_섹터",
    "국내주식_지수", "국내주식_섹터",
    "금리연계형/초단기채권", "해외채권_회사채", "해외채권_종합",
    "국내채권_회사채", "국내채권_종합"
  ]
}
```

### 5.2 데이터 모듈

| 모듈 | 책임 | 외부 API |
|---|---|---|
| `tradingagents/dataflows/pykrx_data.py` | KR ETF OHLCV·종목 메타 | pykrx |
| `tradingagents/dataflows/fred.py` | 미 거시지표 | FRED API (`FRED_API_KEY` env) |
| `tradingagents/dataflows/ecos.py` | 한국은행 거시지표 | ECOS Open API (`ECOS_API_KEY` env) |
| `tradingagents/dataflows/volatility.py` | VIX·VKOSPI 인덱스 | yfinance + KRX |
| `tradingagents/dataflows/news_macro.py` | 매크로 뉴스·이벤트 캘린더 | tradingeconomics RSS, BOK 캘린더 |
| `tradingagents/dataflows/universe.py` | xlsx → JSON 변환 + 검증 | openpyxl |

기존 `dataflows/y_finance.py`, `alpha_vantage_*.py`, `interface.py` 는 보존 (US ETF 검증·과거 호환). DART(`fundamental_data_tools.py`)는 deprecate.

### 5.3 가격 데이터 캐싱
- 188 ETF × 3년 일별 OHLCV ≈ 200KB JSON. local Parquet 캐시 (`~/.tradingagents/cache/etf_prices/`) 일 1회 갱신.
- TTL: 장 마감 후 18:00에 무효화.

---

## 6. Skill 카탈로그 (초기 v1, 34개)

### 6.1 Macro 도메인 (8 skills)
| Skill | 종류 | 입력 → 출력 | Vibe-Trading 출처 |
|---|---|---|---|
| `fetch_fred_series` | Det | (series_id, start, end) → TimeSeries | tushare 패턴 |
| `fetch_ecos_series` | Det | (stat_code, period) → TimeSeries | tushare 패턴 |
| `compute_yield_curve` | Det | (10y, 2y, 3m series) → YieldCurveSnapshot | quant-statistics |
| `compute_inflation_trend` | Det | (CPI series) → InflationSnapshot | macro-analysis |
| `compute_unemployment_trend` | Det | (UR series) → EmploymentSnapshot (Sahm rule 포함) | macro-analysis |
| `classify_regime` | **Sub(deep)** | (지표 dict) → RegimeClassification (4-quadrant + confidence) | macro-analysis prompt 기반 |
| `compute_kr_divergence` | Det | (FRED + ECOS) → DivergenceScore | global-macro |
| `fetch_central_bank_calendar` | Det | (window) → list[Event] | global-macro |

### 6.2 Risk 도메인 (6 skills)
| Skill | 종류 | 입출력 |
|---|---|---|
| `fetch_volatility_index` | Det | (VIX, VKOSPI) → VolatilitySnapshot + 30일 z-score |
| `fetch_credit_spread` | Det | (IG, HY yields) → SpreadSnapshot + 5y percentile |
| `fetch_fear_greed_index` | Det | () → SentimentSnapshot |
| `compute_market_breadth` | Det | (지수 구성종목) → BreadthSnapshot |
| `compute_correlation_concentration` | Det | (자산군 returns) → PCASnapshot (1st eigenvalue 비중) |
| `score_systemic_risk` | **Sub(deep)** | (위 5종) → SystemicRiskScore (0~10 + drivers) |

### 6.3 Technical 도메인 (5 skills)
| Skill | 종류 | 입출력 |
|---|---|---|
| `fetch_etf_price_batch` | Det | (tickers[], window) → MultiTickerOHLCV |
| `compute_ta_indicators` | Det | (prices, [MA200, RSI, MACD, ATR]) → IndicatorPanel |
| `rank_momentum` | Det | (universe, lookback) → RankingByCategory |
| `detect_trend_state` | Det | (price, MAs) → TrendState enum |
| `find_correlation_clusters` | Det | (returns, threshold=0.7) → list[Cluster] |

### 6.4 News 도메인 (4 skills)
| Skill | 종류 | 입출력 |
|---|---|---|
| `fetch_event_calendar` | Det | (window) → list[CalendarEvent] |
| `fetch_macro_news` | Det | (window, keywords) → list[NewsItem] (헤드라인+메타만) |
| `classify_event_impact` | **Sub(quick)** | (event) → ImpactAssessment |
| `dedupe_rank_news` | Det | (news, scores) → list[RankedNews] |

### 6.5 Portfolio 도메인 (7 skills)
| Skill | 종류 | 입출력 |
|---|---|---|
| `select_etf_candidates` | Det | (universe, bucket_targets, criteria) → CandidateSet |
| `fetch_returns_matrix` | Det | (tickers, lookback) → ReturnsMatrix |
| `optimize_hrp` | Det | (returns) → Weights (Hierarchical Risk Parity) |
| `optimize_risk_parity` | Det | (returns) → Weights |
| `optimize_min_variance` | Det | (returns, constraints) → Weights |
| `optimize_black_litterman` | Det | (returns, views, conf) → Weights |
| `pick_optimization_method` | **Sub(deep)** | (regime, risk_score, mandate) → MethodChoice |

### 6.6 Mandate 도메인 (4 skills, 모두 Det)
| Skill | 입출력 |
|---|---|
| `validate_universe` | (weights, universe) → ValidationResult (모든 ticker가 188 안에 있는가) |
| `validate_concentration` | (weights) → ValidationResult (위험 ≤70%, 단일 ≤20%) |
| `validate_turnover_feasibility` | (weights, prev_portfolio, capital, days_remaining) → ValidationResult (회전율 floor 충족 가능?) |
| `validate_correlation_concentration` | (weights, clusters) → ValidationResult (단일 클러스터 합 ≤ X%) |

### 6.7 Skill 베이스 prompt 출처 (결정 i)
- `classify_regime`: Vibe-Trading `skills/macro-analysis/SKILL.md` 본문 (메릴린치 사이클) → 한국화·KR 매크로 추가
- `score_systemic_risk`: Vibe-Trading `skills/risk-analysis/SKILL.md` → KR 시장 사례 추가
- `find_correlation_clusters` 보조 prompt: `skills/correlation-analysis/SKILL.md`
- `pick_optimization_method`: `skills/asset-allocation/SKILL.md` 290줄 본문 통째 한국화

위 4개 본문은 `prompts/` 디렉토리에 마크다운으로 저장, preset YAML이 path로 참조.

---

## 7. 분석가별 상세 (4 analysts + Allocator + Validator)

### 7.1 Macro/Quant Analyst
- **출력 스키마:** `MacroReport(yield_curve, inflation, employment, kr_divergence, regime, upcoming_events, narrative≤500)`
- **오케스트레이션:** 고정 파이프라인 (LLM 결정 X). 8개 skill 순차 호출, 마지막에 narrative 작성.
- **모델:** deep (regime 판단이 평가 70점 토대)
- **다운스트림:** Bull/Bear 양쪽이 인용, RM의 bucket target 1차 입력

### 7.2 Market Risk Analyst
- **출력 스키마:** `RiskReport(vix, vkospi, credit_spread, fear_greed, breadth, correlation_concentration, systemic_score, narrative)`
- **오케스트레이션:** 고정 파이프라인
- **모델:** deep
- **다운스트림:** Conservative 토론자 핵심 근거, daily 트리거 입력

### 7.3 Technical Analyst
- **출력 스키마:** `TechnicalReport(asset_class_momentum, individual_etf_states, correlation_clusters, narrative)`
- **오케스트레이션:** 고정 파이프라인 (188 ETF batch 처리는 Python, LLM은 narrative만)
- **모델:** quick
- **다운스트림:** Allocator의 후보 선정·Risk debate의 클러스터 분석

### 7.4 Macro News Analyst
- **출력 스키마:** `NewsReport(upcoming_events, ranked_news, narrative)`
- **오케스트레이션:** 고정 파이프라인 + impact 분류 subagent
- **모델:** quick (impact 분류는 schema lock)
- **다운스트림:** Bull/Bear 토론, 월간 보고서 "향후 전망" 섹션

### 7.5 Portfolio Allocator
- **출력 스키마:** `WeightVector(method, weights: dict[ticker, float], rationale, expected_metrics)`
- **오케스트레이션:** subagent로 method 결정 → 결정론 optimizer 호출 → narrative
- **모델:** method 결정 subagent만 deep, 최적화는 LLM 없음
- **다운스트림:** Risk debate 입력, Mandate Validator 입력

### 7.6 Mandate Validator
- **LLM 호출 0.** 4개 결정론 skill 호출 후 ValidationReport 반환.
- **출력:** `ValidationReport(passed: bool, violations: list[Violation], suggestions: list[str])`
- **on_fail:** preset에서 `rerun_from(allocation, max_attempts=2)` — Allocator 재실행, 두 번째 실패 시 사용자 수동 개입 요청

---

## 8. 토론 클러스터 (공유 state 영역)

### 8.1 Researcher Debate (Bull/Bear)
- **주제:** 자산군 비중 (종목 X)
- **공유 state:** 4 analyst의 summary + 클러스터 내 message 누적
- **라운드:** 기본 1 (preset 조정 가능)
- **각 발언 스키마:** `DebateMessage(speaker, cited_evidence: list[Citation], proposed_adjustment: BucketAdjustment, reasoning≤400)`
- **종료 시:** Research Manager가 `BucketTarget(국내주식, 해외주식, FX/원자재, 채권, MMF)` Pydantic 모델로 결정

### 8.2 Risk Debate (3인)
- **주제:** Allocator가 제안한 weight vector의 적정성
- **공유 state:** Allocator 출력 + 클러스터 내 message 누적
- **각 발언 스키마:** `RiskDebateMessage(speaker, cited_evidence, proposed_adjustment: WeightAdjustment, reasoning)`
- **종료 시:** Risk Judge가 `WeightAdjustment` 결정, Allocator로 피드백 (weight 보정)

---

## 9. 3-tier 리밸런싱

| Tier | 명령 | 호출 노드 | LLM 토론 | 산출물 | 비용 (대략) |
|---|---|---|---|---|---|
| Daily | `gaps rebalance daily [--date]` | Market Risk + 룰 트리거 | 없음 | 알림 또는 긴급 매매안 | ~$0.10 |
| Weekly | `gaps rebalance weekly --week N` | Macro + Risk 2명, Bull/Bear 1라운드 | 가벼운 1라운드 | 전술 매매 delta CSV | ~$2 |
| Monthly | `gaps rebalance monthly --month N` | 풀 파이프라인 | 풀 토론 | 매매명세서 + 월간 보고서 | ~$15 |

### 9.1 Daily 트리거 룰 (구성 가능)
```yaml
# presets/triggers_default.yaml
triggers:
  - name: vix_spike
    condition: "vix > 30 OR vix_change_1d > 0.20"
    action: emergency_defensive_proposal
  - name: vkospi_spike
    condition: "vkospi > 25"
    action: emergency_defensive_proposal
  - name: yield_curve_deep_inversion
    condition: "spread_10y_2y_bps < -50"
    action: alert
  - name: kospi_drop
    condition: "kospi_return_1d < -0.02"
    action: alert
  - name: drift_breach_imminent
    condition: "any_etf_weight > 0.18"   # 단일 20% 룰 근접
    action: rebalance_proposal
```

### 9.2 Weekly tilt 제약
- 코어 weight 보존, ±5%p 범위 내 조정만
- philosophy 문서 재생성 X (월간만)
- 회전율 floor 추적 표시

---

## 10. CLI 명령 (총 22개)

### 10.1 Universe & Data (3)
```
gaps universe sync                      # xlsx → universe.json 캐시 빌드
gaps universe list [--bucket] [--category] [--top N]
gaps universe info <ticker>
```

### 10.2 Macro Analysis (4)
```
gaps macro regime [--date]              # Macro/Quant 단독
gaps macro risk                         # Market Risk 단독
gaps macro news [--window 30]           # Macro News 단독
gaps macro technical [--ticker]         # Technical 단독
```

### 10.3 Portfolio Design (3)
```
gaps plan [--date] [--capital]          # 풀 파이프라인 (5/28 제출용)
gaps rebalance {monthly,weekly,daily} [...]
gaps optimize --method {hrp|rp|minvar|bl} --candidates ...
```

### 10.4 Risk / Correlation (3)
```
gaps correlate --portfolio ... [--cluster]
gaps validate --portfolio ...
gaps simulate --portfolio ... --window 3y
```

### 10.5 Reporting (3)
```
gaps report philosophy [--portfolio]
gaps report monthly --month N --actual results/...csv
gaps report trade-plan --portfolio ...
```

### 10.6 Monitoring (4)
```
gaps monitor turnover [--as-of]         # floor 추적, 상한 X
gaps monitor exposure --portfolio ...
gaps monitor drift --portfolio ... --current ...
gaps monitor cost [--as-of]             # 수수료·슬리피지 (룰 X)
```

### 10.7 메타 (2)
```
gaps preset list                        # 사용 가능한 preset
gaps preset run <name>                  # preset 직접 실행
```

---

## 11. 산출물 (artifacts)

### 11.1 5/28 투자계획서 제출 패키지
```
artifacts/2026-05-25/
├── portfolio.json              # 25개 ETF × 가중치 × 수량 × 매수금액
├── trade_plan.csv              # MTS 입력용
├── philosophy.md               # 워드 4장 분량 투자철학 문서
└── analysis_appendix.md        # 매크로 데이터·상관행렬·클러스터 분석
```

### 11.2 월간 운용보고서 패키지 (6/말, 7/말, 8/말)
```
artifacts/2026-07-31/
├── portfolio_july.json
├── trade_plan_july.csv
├── monthly_report_july.md      # 수익률 자체평가 + 변경 사유 + 향후 전망 (A4 2장+)
└── analysis_appendix_july.md
```

### 11.3 Daily/Weekly 산출물
```
artifacts/2026-06-15/
├── daily_alert.md              # 트리거 평가 결과
└── weekly_delta_W24.csv        # 변경 종목·수량 (생성 시)
```

### 11.4 보고서 작성 규정 준수
대회 §4.2 "복붙 금지·자체 언어로 재구조화" 준수를 위해:
- 모든 보고서 prompt에 "Do not quote ETF prospectus or news article verbatim"
- 모든 수치 인용은 skill 출력 직접 참조 (출처 자동 첨부)
- 섹션별 분량 제약 (philosophy ≥ 4page, monthly ≥ 2page)

---

## 12. 기존 코드 매핑 (in-place 갈아끼움)

| 기존 | 신규 | 처리 |
|---|---|---|
| `agents/analysts/fundamentals_analyst.py` | `agents/analysts/macro_quant_analyst.py` | **delete + new** |
| `agents/analysts/social_media_analyst.py` | `agents/analysts/market_risk_analyst.py` | delete + new |
| `agents/analysts/market_analyst.py` | `agents/analysts/technical_analyst.py` | rewrite (TA-Lib 도구 일부 유지) |
| `agents/analysts/news_analyst.py` | `agents/analysts/macro_news_analyst.py` | rewrite |
| `agents/trader/trader.py` | `agents/allocator/portfolio_allocator.py` | delete + new |
| `agents/researchers/{bull,bear}_researcher.py` | 동일 위치, prompt 교체 | rewrite |
| `agents/risk_mgmt/{aggressive,conservative,neutral}_debator.py` | 동일 위치, prompt 교체 | rewrite |
| `agents/managers/research_manager.py` | 동일, BucketTarget 출력 | rewrite |
| `agents/managers/portfolio_manager.py` | 동일, Mandate Validator hook 추가 | extend |
| `agents/utils/agent_states.py` | 신규 필드 다수 | extend |
| `agents/utils/agent_utils.py` | tool 정의 변경 | rewrite |
| `agents/utils/fundamental_data_tools.py` | (DART 등) | **deprecate** |
| `dataflows/alpha_vantage_*.py` | (보존, US ETF용) | keep |
| `dataflows/y_finance.py` | 보존 + 확장 | keep |
| `dataflows/{pykrx_data,fred,ecos,volatility,news_macro,universe}.py` | 신규 | new |
| `tradingagents/skills/` | 신규 디렉토리 (24 skill) | new |
| `tradingagents/schemas/` | 신규 디렉토리 (Pydantic 모델) | new |
| `tradingagents/presets/` | YAML preset | new |
| `tradingagents/prompts/` | skill base prompt 마크다운 | new |
| `graph/trading_graph.py` | preset YAML loader + 하이브리드 토폴로지 | rewrite |
| `graph/setup.py` | preset 기반 그래프 구성 | rewrite |
| `graph/conditional_logic.py` | 토론 cluster 종료 조건 | extend |
| `cli/main.py` | 22개 서브커맨드 | rewrite |
| `tests/` | 기존 종목 단위 테스트 deprecate, skill 단위 테스트 추가 | partial rewrite |

### 12.1 보존되는 자산
- LangGraph 골격 (StateGraph, ToolNode)
- Memory log 시스템 (`agents/utils/memory.py`)
- Checkpoint resume (`graph/checkpointer.py`)
- LLM client provider 추상화 (`llm_clients/`)
- Reflection 시스템 (월간 자체평가에 활용)

---

## 13. State 스키마 변경

```python
class AgentState(MessagesState):
    # 기존 → 폐기
    # company_of_interest: str         (단일 티커)
    # market_report: str               (단일 종목 리포트)
    # ...

    # 신규
    as_of_date: str
    universe_path: str
    capital_krw: int
    preset_name: str

    # Stage 1 산출 (analyst summaries)
    macro_report: MacroReport
    risk_report: RiskReport
    technical_report: TechnicalReport
    news_report: NewsReport

    # Stage 2 산출
    research_debate_messages: list[DebateMessage]   # cluster 내부 (요약 후 폐기 옵션)
    research_debate_summary: str

    # Stage 3 산출
    bucket_target: BucketTarget

    # Stage 4 산출
    candidate_set: CandidateSet
    weight_vector: WeightVector

    # Stage 5 산출
    risk_debate_messages: list[RiskDebateMessage]
    risk_debate_summary: str
    weight_adjustment: WeightAdjustment

    # Stage 6 산출
    validation_report: ValidationReport

    # Stage 7 산출
    final_portfolio: Portfolio
    philosophy_doc_path: str
    trade_plan_csv_path: str

    # Cross-run
    previous_portfolio: Optional[Portfolio]    # 리밸런싱 시 주입
    past_context: str                          # memory log
```

---

## 14. 환경 변수 / 설정

```env
# 데이터 API
FRED_API_KEY=...
ECOS_API_KEY=...

# LLM provider (기존 유지)
OPENAI_API_KEY=...   # 또는 ANTHROPIC_API_KEY 등

# 캐시
TRADINGAGENTS_CACHE_DIR=~/.tradingagents/cache
TRADINGAGENTS_RESULTS_DIR=~/.tradingagents/logs

# 산출물
GAPS_ARTIFACTS_DIR=./artifacts
GAPS_DEFAULT_PRESET=db_gaps
```

`tradingagents/default_config.py` 확장:
```python
DEFAULT_CONFIG.update({
    "preset_dir": "./presets",
    "prompt_dir": "./prompts",
    "universe_path": "./data/universe.json",
    "artifacts_dir": "./artifacts",
    "default_preset": "db_gaps",
    "subagent_model_policy": {
        "classify_regime": "deep",
        "score_systemic_risk": "deep",
        "pick_optimization_method": "deep",
        "classify_event_impact": "quick",
    },
})
```

---

## 15. 위험·미해결 사항

### 15.1 알려진 위험
1. **ECOS·FRED API 안정성:** 시연 직전 다운 시 fallback 데이터 캐시 정책 필요. 일 1회 raw 데이터 백업 cron 추가 권장.
2. **pykrx 데이터 지연:** 장 마감 후 18:00 데이터 갱신 — daily 트리거의 "동일 영업일 즉시" 평가는 불가, 익일 예약.
3. **회전율 계산 정확성:** 수수료·세금 포함 여부, 매도금액에 양도세가 포함되는지 등 대회 공식 계산 공식과 정확히 일치 검증 필요. (현재 룰북 §3 공식 그대로 사용)
4. **Subagent 모델 cost 폭주:** §9 표의 monthly ~$15는 deep×5 + quick×10 가정의 거친 추정. 실제 분석가 4 + 토론 클러스터 + Allocator + Risk 3인 + subagent 누적치는 첫 dry-run 후 측정·조정 필요. 비용 폭주 시 토론 1라운드로 제한, technical/news 분석가를 quick model 고정.
5. **Pydantic 스키마 강제와 LLM 거부:** 일부 모델은 strict schema 출력에서 누락 필드를 빈 문자열로 채움 → validator에서 catch + 1회 재시도 로직 필요.

### 15.2 향후 결정 (구현 단계에서)
- 백테스트 엔진 도입 여부 (현재 비목표지만 simulate 명령에서 최소 구현 필요)
- docx 생성 라이브러리 선택 (python-docx vs pandoc)
- daily 트리거 cron 배포 방식 (사용자 로컬 vs Conductor)
- LLM provider 기본값 (Anthropic vs OpenAI vs Google)

---

## 16. 마이그레이션·구현 순서 (개략)

상세 implementation plan은 별도 문서에서 다룸. 본 문서는 spec까지 정리.

대략적 순서:
1. 데이터 레이어 (universe.json, pykrx, FRED, ECOS) + 기본 스키마
2. Skill 레이어 (24개 skill, 단위 테스트)
3. Preset YAML loader + 그래프 빌더 (하이브리드 토폴로지)
4. 분석가 4종 + Allocator + Validator (스키마 lock)
5. 토론 클러스터 (Bull/Bear, Risk 3인)
6. CLI 22개 명령
7. 보고서 생성기 (philosophy, monthly)
8. 3-tier 리밸런싱 + daily 트리거
9. End-to-end 통합 + 5/28 dry-run

---

## 17. 참고 자료

- 본 리포 기존 코드: `tradingagents/`
- 대회 룰: `docs/DB_GAPS_Investment_Tournament_Rules.md`
- 유니버스 원본: `docs/제12회 GAPS ETF 리스트 (2026-5-9 게시).xlsx`
- 사용자 수정 계획: `수정 계획.txt`
- HKUDS/Vibe-Trading 분석 (대화 기록 보유, repo 자체는 외부)
- Anthropic financial-services 패턴 (사용자 수정 계획 §1~5 발췌)

---

## 18. 부록: 결정 요약

### 브레인스토밍 단계 결정

| 결정 | 선택 | 근거 |
|---|---|---|
| 코드 전략 | in-place 갈아끼움 | 대회 한정 사용, 회귀 부담 낮음 |
| 유니버스 | KR 188 ETF (xlsx 고정) | 대회 §2.1 |
| Agent 산출물 형식 | CLI 22개 서브커맨드 (옵션 3) | 디버깅·반복 |
| 그래프 토폴로지 | 하이브리드 (γ) — 단계 간 summary handoff, 토론 클러스터 내부 공유 state | 비용 절감 + 토론 품질 |
| Preset YAML | 도입 (옵션 2) | 변형·실험 용이 |
| Skill base prompt | Vibe-Trading 본문 한국화 (옵션 i) | 검증된 prose, 빠른 시작 |
| Subagent 모델 | skill별 지정 (C) — 핵심 판단 deep, 보조 quick | cost vs 품질 균형 |
| 회전율 모니터링 | floor 추적만, 상한 없음 | 대회 §3는 minimum, max 없음 |
| 스펙 범위 | 풀 v1 그대로 (B, plan-eng-review D1) | 사용자 결정 |

### plan-eng-review 결정 (2026-05-10)

| ID | 영역 | 이슈 | 결정 |
|---|---|---|---|
| D2 | Architecture | Subgraph state 격리 | 별도 sub-graph + 독립 DebateState (LangGraph subgraph 패턴) |
| D3 | Architecture | Preset YAML loader | Pydantic PresetSpec + skill registry 데코레이터 패턴 |
| D4 | Architecture | Validator → Allocator cycle | Feedback injection + 2-attempt fallback + deterministic clip+normalize |
| D5 | Architecture | API fallback | 데이터별 차등 (pykrx tier1 tiered cache, FRED/ECOS tier2 재시도+D-1, narrative tier3 skip-with-note) |
| D6 | Code Quality | Subagent 추상화 | BaseSubagent 추상 클래스 + @subagent 데코레이터 |
| D7 | Code Quality | 분석가 retry 위치 | 공통 helper `invoke_with_structured_retry` |
| D8 | Code Quality | Memory log 통합 | v1 deprecate + portfolio_decisions.jsonl append-only, lap2 재설계 |
| D9 | Test | 5/28 E2E 테스트 | Mock fixture 기반 CI E2E + 5/27 수동 live dry-run |
| D10 | Performance | pykrx 188 batch fetch | 순차 fetch + Parquet cache + cron (5/27, 6/30, 7/31) |
| D11 | Process | TODOS 추가 | 5개 항목 모두 TODOS.md에 추가 |

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 2 | CLEAR (PLAN) | 1차: 11 결정 / 2차: 6 결정 (D12-D17), Critical: 1 (HRP bucket-sum, IRON RULE), TODOs: +2 |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | N/A (CLI tool, no UI) |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

- **CROSS-MODEL:** Codex review 미실행 (외부 voice skip 양 라운드).
- **UNRESOLVED:** 0
- **2차 라운드 결정 (D12-D17):**
  - D12: `_hrp_per_bucket` 반복 재분배 (단일 패스 → while-loop, IRON RULE)
  - D13: `select_etf_candidates`에 `as_of` 와이어어 (tradable_at 호출)
  - D14: `traced` 데코레이터 dead code 제거
  - D15: `daily_triggers` 컨텍스트 4개 데이터 패치 (vix_change_1d, spread, kospi, drift)
  - D16: 16개 신규 테스트 경로 + 1 eval test plan에 추가
  - D17: TODOS #8 (cache+lag), #9 (parser 괄호) 추가
- **VERDICT:** ENG CLEARED (2차) — 누적 17건 결정 모두 합의. fatal flaw 1건 (Allocator scaling collision) + 수학 버그 1건 (HRP single-pass) 모두 fix. implementation 진행 가능.

