# Stage 1 — Macro News Analyst

> 파이프라인 6 stage 중 첫 단계의 4명 병렬 분석가 중 하나. **다른 3명(macro_quant·market_risk·technical)이 안 보는 차원만 잡는다**는 디자인 원칙 — 정성적 정보의 정량화 + 발표 surprise + 시점성 신호 + 큐레이션 데이터 통합.

> **macro_quant와 market_risk와의 역할 분담**: macro_quant는 거시 시계열 (월간 FRED/ECOS), market_risk는 시장 stress (일간 vol/credit), technical은 188 ETF 가격 행동. **macro_news는 정량 시계열이 못 잡는 모든 영역** — 뉴스 sentiment, 경제지표 forecast 대비 surprise, 중앙은행 인사 발언 톤, 글로벌 overnight (US 제외).

---

## 1. 한 줄 요약

> **10개 skill로 글로벌 overnight + 경제지표 surprise + 5분류 뉴스 sentiment + CB speaker 매파-비둘기 + SAVE 큐레이션 통합 → ≤2KB summary + 풍부한 NewsReport 객체 산출. 다른 분석가와 dimension 중복 0건.**

---

## 2. 어떤 데이터를 보는가 (이전 분석가가 안 보는 것만)

### 2.1 중복 매트릭스 — 진짜 NEW만 잡는다

| 데이터 | macro_quant | market_risk | technical | **macro_news** |
|---|:---:|:---:|:---:|:---:|
| US Treasury (DGS10/2/3MO) | ✅ FRED | — | — | — (참조만) |
| VIX/SKEW/VXN | — | ✅ | — | — (참조만) |
| US IG/HY OAS, TIPS, SOFR | — | ✅ | — | — |
| Gold/Copper (GC/HG) | ✅ | ✅ | — | — |
| 달러 (DTWEXBGS) | ✅ FRED (월간) | — | — | — |
| SPY/QQQ/TLT/EWY | — | ✅ | technical은 벤치 | — |
| KR 국고채/회사채 | — | ✅ ECOS | — | — |
| VKOSPI/KRX 신용잔고 | — | ✅ pykrx | — | — |
| CNN Fear & Greed | — | ✅ scraper | — | — |
| 188 ETF OHLCV | — | — | ✅ | — |
| **글로벌 overnight (STOXX/N225/HSI/SSE/FTSE/TWII)** | — | — | — | **✅ Tier-1** |
| **WTI / 천연가스** | — | — | — | **✅ Tier-1** |
| **USDKRW intraday** | — | — | — | **✅ Tier-1** |
| **경제지표 forecast vs actual surprise** | — | — | — | **✅ Tier-2** |
| **뉴스 카테고리 + sentiment + momentum** | — | — | — | **✅ Tier-3** |
| **CB speaker 매파/비둘기 tone** | — | — | — | **✅ Tier-4** |
| **SAVE 평일 브리핑 (큐레이션)** | — | — | — | **✅ Tier-5** |

→ 모든 NEW 차원은 macro_news 전용. 단 한 차원도 다른 분석가와 겹치지 않는다.

### 2.2 데이터 소스 명세

| 소스 | 데이터 | 사용처 |
|---|---|---|
| yfinance | 9개 글로벌 자산 daily close | Tier-1 overnight |
| event_calendar (기존) | 향후 90일 매크로 이벤트 | upcoming_events |
| news_fetcher (기존) | 최근 7일 매크로 뉴스 RSS | Tier-3 input |
| SAVE 브리핑 (`extracted_result_*.txt`) | 큐레이션된 경제지표/뉴스카드/주간일정 | Tier-2/3/event_calendar 보강 |
| state["release_surprises_30d"] | 외부 주입 발표 데이터 | Tier-2 input |
| `quick_llm` (OpenAI/Anthropic) | batch sentiment/categorization/tone 분류 | Tier-3/4/5 |

→ 신규 API 키 0개. yfinance + 기존 LLM 인프라 재사용.

---

## 3. 어떻게 가공하는가 (10 skill)

### 3.0 Baseline (5 skill)

| Skill | 기능 |
|---|---|
| `fetch_event_calendar_skill(as_of, days)` | 향후 90일 매크로 이벤트 |
| `fetch_macro_news_skill(window_days)` | 최근 7일 뉴스 RSS |
| `classify_event_impact(quick_llm, deep_llm, ...)` | LLM 임팩트 분류 (asset_classes/direction/severity 1-5) |
| `dedupe_rank_news(items, impacts, top_n)` | 중복 제거 + recency × severity ranking |
| `quick_llm` narrative 합성 | ≤500자 한글 산문 |

---

### 3.1 Tier-1 — Global Overnight (`compute_global_overnight_snapshot`)

**측정 대상** (9개 자산, 미국 제외):

| Group | Ticker | 의미 | 왜 NEW |
|---|---|---|---|
| 유럽 | `^STOXX50E`, `^FTSE` | STOXX50, FTSE100 | 다른 분석가 0 |
| 아시아 | `^N225`, `^HSI`, `000001.SS`, `^TWII` | 닛케이/항셍/상하이/대만 | 한국 개장 전 마지막 시그널 |
| 원자재 | `CL=F`, `NG=F` | WTI, 천연가스 | macro_quant는 copper/gold만 |
| FX | `KRW=X` | USD/KRW | FRED DEXKOUS는 lag → overnight NEW |

**알고리즘**:
```python
for ticker in 9개:
    series = closes[ticker].dropna()
    value = series.iloc[-1], prior = series.iloc[-2]
    change_pct = (value - prior) / prior * 100
    direction = "up" if pct > 0.05 else "down" if < -0.05 else "flat"

# Regime 분류
equity_avg = mean(europe + asia change_pct)
risk_on:  equity_avg > +0.3 AND krw_pct < +0.3
risk_off: equity_avg < -0.3 OR  krw_pct > +0.5
mixed:    else

# narrative_seed (≤300자) — SAVE 스타일 한 줄
"STOXX50 +0.42% / N225 -0.31% / WTI +1.18% / USDKRW 1493.3 (-0.21%)"
```

**의미**: 한국 개장 *전* 마지막 글로벌 시그널. Bull/Bear가 그대로 인용 가능.

---

### 3.2 Tier-2 — Release Surprise (`compute_release_surprise_snapshot` + `normalize_release`)

**개념**: macro_quant FRED는 actual 시리즈만 받는다. **예상 vs 실제 차이**는 어디에도 없다.

**`normalize_release`** — 단일 발표를 정규화:
```python
surprise = actual - forecast
zscore   = surprise / historical_std  (없으면 None)

direction = "inline"   if |surprise| < 0.05
            "positive" if surprise > 0
            "negative" if surprise < 0
```

**`compute_release_surprise_snapshot`** — 30d aggregate:
```python
today_releases       = filter(release_date == as_of)
last_5d_releases     = filter(release_date >= as_of - 5d)
surprise_index_30d   = mean(zscore for zscore in releases)   # Citi ESI 스타일
high_importance_today= count(importance == 3)

# Bias 분류 (Hawkish vs Dovish)
bias_score = Σ _bias_score_one(release)
  - CPI/PPI/GDP/고용 surprise + → +zscore (hawkish)
  - 실업률 surprise + → -zscore (dovish, inverted)

bias_30d = "hawkish_surprise" if bias_score > +1.0
           "dovish_surprise"  if bias_score < -1.0
           "balanced"         else
```

**의미**: macro_quant가 "CPI 4.2%"라고 보고할 때 macro_news는 "예상 4.0% 대비 +0.2 surprise → hawkish 명분"으로 보완.

데이터는 `state["release_surprises_30d"]` 또는 Tier-5 SAVE에서 채움. 비어있어도 `bias_30d = "balanced"`로 graceful.

---

### 3.3 Tier-3 — News Categorizer + Sentiment + Momentum (3 skill)

**5 카테고리**: `policy`, `macro`, `corporate`, `geopolitical`, `market_commentary`

#### `categorize_news` — 2단계 분류 (비용 최소화)

```python
1차: 한/영 키워드 매칭 (KEYWORD_MAP, lookup table, 비용 0)
     예) "Fed", "Powell", "연준", "기준금리" → policy
         "CPI", "고용", "GDP", "물가"       → macro
         ...

2차: 1차에서 hits==0인 뉴스만 → quick_llm batch (10개씩) JSON 분류
     prompt: "Return JSON: [{idx, category}, ...]"
     실패 시 default "macro"
```

→ 일반적으로 키워드만으로 80%+ 처리. LLM 호출 최소화.

#### `score_sentiment` — LLM batch
```python
score ∈ [-1, +1]
prompt = "Score sentiment for each headline (-1 to +1, JSON)"
batch_size = 10
실패 시 fallback 0.0
```

→ FinBERT 의존성 추가 0 (transformers + torch 2GB 회피). 한/영 모두 처리.

#### `compute_news_sentiment_snapshot` — Aggregate + Momentum
```python
# 카테고리별 집계
counts[cat]              = count(items.category == cat)
avg_sentiment[cat]       = mean(sentiment_score)
dominant_category        = argmax(counts)
sentiment_dispersion     = std(avg_sentiment values)   # 분열도
top_headline_per_category[cat] = argmax(|score|)

# Momentum (24h vs 7d daily avg)
counts_24h[cat]          = filter(published_at >= now - 24h)
counts_prev7d[cat]       = filter(now - 7d <= published_at < now - 24h)
count_change_vs_7d[cat]  = counts_24h - counts_prev7d / 7
rising_category          = cat (counts_24h ≥ 2× prev_daily_avg AND ≥ 2건)
```

**의미**: "정책 카테고리 8건 (-0.3 sentiment), 지정학 4건 (-0.6)" 같은 분포 + "지정학 카테고리 24h 카운트 5건 vs 7일 평균 0.5건 → rising" 같은 momentum.

---

### 3.4 Tier-4 — CB Speaker Tracker (`extract_speaker_events` + `compute_speaker_aggregate`)

#### `extract_speaker_events`
```python
# 정적 directory (30+ 인사 매핑)
SPEAKER_DIRECTORY = {
    "powell": ("Fed", True),   # voting
    "goolsbee": ("Fed", False),
    "이창용": ("BOK", True),
    "lagarde": ("ECB", True),
    "ueda": ("BOJ", True),
    ...
}

1차: headline.lower() 안에서 키워드 매칭 → speaker, cb, voting 식별
2차: 매칭된 헤드라인만 batch LLM → tone ∈ {hawkish, neutral, dovish}
```

#### `compute_speaker_aggregate` — 7d aggregate
```python
TONE_SCORE = {"hawkish": +1.0, "neutral": 0.0, "dovish": -1.0}

fed_tone_balance     = mean(score for Fed speakers in last 7d)
bok_tone_balance     = mean(score for BOK speakers)
fed_voting_balance   = mean(score for Fed speakers WHERE voting=True)
                       # 시장 영향 핵심 — voting만 가중
```

**의미**: "Fed 7d balance +0.5 (5명 중 4명 매파), voting only +1.0 (Powell/Williams 매파)" → 매파 회의록 가능성 ↑.

macro_quant fed_path subagent (월간 forecast)와 보완 — speaker tracker는 7일 sliding window로 실시간성.

---

### 3.5 Tier-5 — SAVE Brief Ingestor (`ingest_save_brief`)

**역할 한정**: 가격 수치 skip (Tier-1 + macro_quant + market_risk 중복), 추출은 NEW 정보만.

**3 가지 추출**:

#### (a) 경제지표 발표 (`parse_economic_releases`)
```regex
RELEASE_LINE_RE = r"""
    (?P<time>\d{2}:\d{2}) \s* [-–] \s*
    (?P<region>[가-힣A-Za-z]+) \s* [-–] \s*
    (?P<indicator>[^★]+) \s*
    (?P<stars>★+) \s*
    (?P<actual>[\+\-\d.,KMB%]+)?
    [▲▼=]?
    \(예상[:：]? (?P<forecast>...)? \s* 이전[:：]? (?P<previous>...)? \)
"""
```

추출 예시 (SAVE 샘플 fixture):
```
21:30 - 미국 - 4월 수입물가지수 ★★ 1.9% (예상: 1.0% 이전: 0.8%)
  → ReleaseSurprise(region="US", indicator="4월 수입물가지수", importance=2,
                    actual=1.9, forecast=1.0, surprise=+0.9, direction="positive")

21:30 - 미국 - 신규실업수당청구건수 ★★★ 211K (예상: 205K 이전: 200K)
  → ReleaseSurprise(... importance=3, actual=211.0, unit="k", ...)
```

→ Tier-2 input으로 직접 주입.

#### (b) 뉴스 카드 (`parse_news_cards_with_llm` + heuristic fallback)
```python
# LLM 우선 (페이지 텍스트 통째로 batch JSON 추출):
prompt = "Extract news headlines as JSON [{title_kr, title_en, bullet}]"

# 휴리스틱 fallback:
영문 원제 1줄 + 직전 한글 줄 매칭 → "{kr} — {en}"
```

→ NewsItem list로 변환 후 Tier-3 input items에 append. categorize/sentiment가 자연스럽게 처리.

#### (c) 주간 일정 (`parse_weekly_schedule`)
```python
"이번 주" 또는 "주간 일정" 헤더 있는 페이지에서
WEEKLY_EVENT_RE = r"국채\s*경매|FOMC|BOK|연준|금통위|ECB|BOJ|CPI|GDP"

event_type 자동 매핑:
  "FOMC" → "fomc"
  "BOK"  → "bok"
  "CPI"  → "cpi"
  "GDP"  → "gdp"
```

→ upcoming_events list에 dedupe append. event_calendar 보강.

**파일 탐색**:
```python
SAVE_BRIEF_DIR_ENV = "SAVE_BRIEF_DIR"
default = "~/Downloads/SAVE/"

find_latest_save_brief(as_of):
    1순위: 파일명 YYYY-MM-DD ≤ as_of 중 가장 가까운 것
    2순위: mtime 가장 최근
    없으면 None
```

→ 없어도 graceful (`save_brief = None`).

---

## 4. macro_news → 다음 stage 핸드오프

### 4.1 출력 채널 두 개

```
MacroNewsAnalyst
  ├─→ news_report (Pydantic, full Tier 1~5 dict + snapshot)  →  (allocator 직접 사용 X, 현재 LLM-facing 위주)
  └─→ news_summary (str ≤2KB markdown)                        →  bull/bear/manager/리포트 (LLM)
```

### 4.2 압축된 summary 실제 예시 (~1.8KB)

```markdown
## News
Upcoming events: 12
Top headlines (severity 4): Fed Chair Powell hints at later rate cuts
Tier-1 (global overnight, n=9/9):
  Regime: mixed
  STOXX50 +0.42% / FTSE -0.18% / N225 -0.31% / HSI -0.14% / SSE +0.08%
  / TWII +0.61% / WTI +1.18% / NG -0.42% / USDKRW 1493.3 (-0.21%)
Tier-2 (release surprise):
  Today high-importance: 2
  Today releases: US Initial Jobless Claims(211 vs 205, positive);
                  US Retail Sales(0.5 vs 0.5, inline)
  30d ESI: +0.34, bias: hawkish_surprise
Tier-3 (news sentiment, n=23):
  Counts: policy 7, macro 5, corporate 6, geopolitical 3, commentary 2
  Avg sentiment: policy -0.21, macro +0.04, corporate +0.38,
                 geopolitical -0.51, commentary +0.18
  Dominant: policy, Rising: geopolitical
  Dispersion: 0.32
  Top per category:
    policy: Fed Schmid hints rate cuts later in year
    macro:  US Q1 GDP revised up to 2.7%
    ...
Tier-4 (CB speakers 7d, n=6):
  Fed balance: +0.50 (voting only: +1.00, n=4)
  BOK balance: -0.50 (n=2)
  Fed recent: Powell(hawkish); Williams(hawkish); Goolsbee(dovish)
  BOK recent: 이창용(dovish); Rhee(neutral)
Tier-5 (SAVE brief 2026-05-15, pages 11):
  Releases extracted: 4 (→ Tier-2)
  News cards extracted: 6 (→ Tier-3 input)
  Weekly schedule: 3 (→ event_calendar 보강)
```

→ Bull/Bear는 이 1.8KB만 받음. 풀데이터는 NewsReport에 보존.

---

## 5. 출력 구조 — `NewsReport` Pydantic 객체

```python
class NewsReport(_AnalystReport):
    # Baseline
    upcoming_events:    list[CalendarEvent]
    ranked_news:        list[RankedNews]

    # Tier-1 (글로벌 overnight)
    global_overnight:   GlobalOvernightSnapshot | None

    # Tier-2 (Release surprise)
    release_surprise:   ReleaseSurpriseSnapshot | None

    # Tier-3 (News sentiment)
    news_sentiment:     NewsSentimentSnapshot | None

    # Tier-4 (CB speaker)
    cb_speakers:        SpeakerToneAggregate | None

    # Tier-5 (SAVE ingestor)
    save_brief:         SaveBriefSnapshot | None

    # 핸드오프
    narrative:                  str   # ≤500자
    summary_for_downstream:     str   # ≤2000자
```

각 snapshot은 sub-field들 (예: `GlobalOvernightSnapshot.europe`, `.asia`, `.commodities`, `.krw`, `.risk_regime_overnight`, `.narrative_seed`, `.fetched_count`) 풀데이터 보존.

---

## 6. Graceful Degradation

| 실패 | Fallback |
|---|---|
| yfinance global overnight batch | `global_overnight = None`, summary 빈 줄 |
| 일부 ticker만 fetch 실패 | `fetched_count`로 표시, 나머지는 계속 |
| SAVE 파일 없음 | `save_brief = None`, Tier-2/3 자체 fallback |
| SAVE 파싱 부분 실패 | 해당 섹션만 빈 list, 나머지는 계속 |
| LLM categorizer 호출 실패 | 키워드 매칭만, 안 잡힌 건 default "macro" |
| LLM sentiment 호출 실패 | 0.0 fallback |
| LLM CB tone 호출 실패 | "neutral" fallback |
| 모든 LLM 호출 실패 | snapshot은 빈 값이지만 NewsReport 자체는 생성 |

→ 외부 의존성 (yfinance, LLM API, SAVE 파일) 어느 것이 끊겨도 파이프라인은 안 죽음.

---

## 7. 검증 결과

| 항목 | 결과 |
|---|---|
| 단위 테스트 (Tier 1-5 × 각 7-14 case) | **273 passing** (회귀 0건) |
| 신규 unit test (Tier 1~5 합) | **+59 신규** (Tier-1: 9, Tier-2: 7, Tier-3: 18, Tier-4: 11, Tier-5: 14) |
| 분석가 통합 테스트 | **passing** (`test_phase1_smoke.py`, `test_subgraph_isolation.py`) |
| 스키마 검증 | **passing** (Pydantic v2) |
| 중복 매트릭스 검증 | **dimension 중복 0건** (§2.1 매트릭스) |

---

## 8. API 키 요구

| 키 | 사용처 | 비고 |
|---|---|---|
| (yfinance) | 9 글로벌 overnight ticker | **키 불요** |
| `OPENAI_API_KEY` | quick_llm batch — categorize/sentiment/CB tone/SAVE 카드 추출 | 기존 환경 그대로 |
| `SAVE_BRIEF_DIR` (env) | SAVE `extracted_result_*.txt` 경로 (기본 `~/Downloads/SAVE/`) | optional |

→ 신규 가입/키 0개. FinBERT 등 무거운 의존성 추가 0.

**일일 LLM 비용 추정**: 약 $0.005~$0.01 (뉴스 30개 × categorize/sentiment + speaker tone + SAVE 카드).

---

## 9. macro_quant / market_risk / technical과의 역할 차이

| 항목 | macro_quant | market_risk | technical | **macro_news** |
|---|---|---|---|---|
| 역할 | 거시 regime 분류 (top-down) | 실시간 시장 stress (bottom-up) | universe 가격 행동 정량화 | **정성→정량 변환 + surprise + 시점성** |
| 시간 단위 | 월간/분기 | 일간 | 일간 + 주간 multi-TF | **일간 + 24h vs 7d momentum + 7d aggregate** |
| 데이터 성격 | 정량 시계열 (FRED/ECOS) | 정량 시계열 (vol/credit) | 정량 시계열 (OHLCV) | **정성 (뉴스/발언) + 큐레이션 (SAVE) + 일부 정량 (overnight/surprise)** |
| 출력 핵심 | 4 quadrant regime | 0-10 systemic_score + 3 regime | 188 ETF dict + universe snapshot | **5 snapshot (각 Tier) + 카테고리·tone aggregate** |
| LLM 활용 | regime_classifier subagent | systemic_score subagent | narrative만 | **categorize/sentiment/tone/SAVE 카드 batch 분류** |
| 사용처 | Stage 2 Bull/Bear, Stage 3 Allocator | Stage 4 Risk debate, Allocator | Stage 2 Bull/Bear, Stage 3 Selector | **Stage 2 Bull/Bear, Stage 4 Risk debate** |

→ 4명 분석가는 **dimension이 겹치지 않게** 설계됨. macro_news는 셋이 못 잡는 영역의 *완성판* 역할.

---

## 10. 5 Tier 누적 결과

| Tier | Skills 추가 | NEW 정보 | 누적 Skill | Commit |
|---|---|---|---|---|
| Baseline | 5 | event calendar + news fetch + impact classify + rank + narrative | 5 | (pre-existing) |
| **Tier-1** Global Overnight | 1 신규 | 9 글로벌 자산 (US 제외) overnight + risk regime + SAVE 스타일 narrative_seed | 6 | `aa35d46` |
| **Tier-2** Release Surprise | 2 신규 (`normalize_release` + `compute_snapshot`) | 경제지표 forecast 대비 surprise + 30d ESI + hawkish/dovish bias | 8 | `1b4ac58` |
| **Tier-3** News Categorizer + Sentiment + Momentum | 3 신규 (`categorize_news` + `score_sentiment` + `compute_snapshot`) | 5분류 × count/sentiment/top + 24h vs 7d momentum + rising category | 11 | `bbc40e0` |
| **Tier-4** CB Speaker Tracker | 2 신규 (`extract_speaker_events` + `compute_aggregate`) | Fed/BOK/ECB/BOJ 매파-비둘기 + voting 가중 | 13 | `f51d400` |
| **Tier-5** SAVE Brief Ingestor | 1 신규 (`ingest_save_brief`) | SAVE 평일 브리핑 → 발표/뉴스카드/주간일정 추출 (Tier 2/3/event 보강) | **14** | `2fb793c` |

**5 skill → 14 skill (≈3배 확장)**, 회귀 0건, 신규 59 단위 테스트 전부 pass.
**LLM 핸드오프 크기**: 5KB 초과 없이 ≤2KB 유지 (Tier별 압축 룰).
**중복 매트릭스**: 다른 3 분석가와 **dimension 중복 0건** (§2.1 매트릭스 검증).

---

## 11. 파일 매니페스트

| 위치 | 파일 |
|---|---|
| Baseline 스킬 (5) | `tradingagents/skills/news/{event_calendar, news_fetcher, impact_classifier, ranker}.py` |
| Tier-1 스킬 | `tradingagents/skills/news/global_overnight.py` |
| Tier-2 스킬 | `tradingagents/skills/news/release_surprise.py` |
| Tier-3 스킬 (2) | `tradingagents/skills/news/{categorizer, news_sentiment}.py` |
| Tier-4 스킬 | `tradingagents/skills/news/cb_speaker_tracker.py` |
| Tier-5 스킬 | `tradingagents/skills/news/save_ingestor.py` |
| 분석가 노드 | `tradingagents/agents/analysts/macro_news_analyst.py` |
| 스키마 | `tradingagents/schemas/news.py`, `reports.py` |
| 데이터 wrapper (신규 2) | `tradingagents/dataflows/{global_overnight, save_brief}.py` |
| 단위 테스트 (신규 6) | `tests/unit/skills/test_news_{global_overnight, release_surprise, categorizer, sentiment, cb_speaker, save_ingestor}.py` |
| Fixture | `tests/fixtures/save/extracted_result_2026-05-15.txt` |
