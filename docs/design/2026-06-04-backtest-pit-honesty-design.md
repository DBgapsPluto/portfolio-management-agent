# 백테스트 Point-in-Time 정직성 설계 ((1)+(2))

**작성일:** 2026-06-04
**상태:** 설계 확정 (구현 대기)
**관련:** 데이터 품질 audit (2026-06-04) — 백테스트가 라이브-온리 소스로 미래를 엿보는 lookahead. rulebook/threshold 튜닝의 선결 조건.

---

## 1. 배경 — 문제

백테스트(`run_backtest.py`)는 과거 `as_of`로 E2E를 돌리지만, 일부 fetcher가 `as_of`를 무시하고 **오늘 데이터**를 가져온다(lookahead):

- **뉴스** (`news_macro.py:53` `datetime.utcnow()`): as_of 무시, 오늘 헤드라인. "2025-04 tariff 미반영"의 원인.
- **CNN Fear&Greed**: 라이브 스크레이프, 과거값 API 없음 → 항상 오늘 값.
- **market_risk 3종** (섹터분산·메가캡·SPY실현변동성, `yf...history(period="65d"/"400d"/"120d")`): `period=`는 "오늘 기준 N일" → 미래 포함.

이게 잡히지 않으면 백테스트 결과를 신뢰할 수 없어 threshold/baseline 튜닝이 무의미하다.

## 2. 범위 + 비범위

**In scope:**
- (1) 라이브-온리 소스(뉴스·F&G)를 **as_of가 과거면 중립화**.
- (2) market_risk의 `period=` 4곳을 `start/end`(as_of 종료)로 교체.

**Out of scope (구조적/후순위):**
- FRED/ECOS revision(vintage/ALFRED) lookahead — 보통 영향 작음.
- S&P500 earnings revision(yfinance 과거 부재) — 옛 날짜는 이미 None 방어.
- 과거 뉴스 아카이브 도입(유료 API) — 중립화로 대체.
- 사전 스냅샷 저장 방식.

**핵심 불변식: 라이브(as_of=오늘) 실행 산출물은 변하지 않는다.** 가드는 as_of가 과거일 때만 발동, market_risk start/end는 as_of=오늘이면 period=와 동일 창.

## 3. 컴포넌트

### 3.1 신규 `tradingagents/dataflows/pit_guard.py`
```python
from datetime import date

PIT_STALENESS_DAYS: int = 7   # as_of가 이보다 과거면 라이브-온리 데이터는 그 시점 대표 불가


def is_pit_stale(as_of: date, today: date | None = None,
                 max_days: int = PIT_STALENESS_DAYS) -> bool:
    """as_of가 today 로부터 max_days 초과 과거면 True (라이브 데이터 point-in-time 불가).

    today 주입 가능 — 테스트 결정론. None이면 date.today().
    """
    today = today or date.today()
    return (today - as_of).days > max_days
```
근거: 라이브 RSS는 최근 7일치 → as_of가 7일 넘게 과거면 겹침 0 → 무효. 7일 이내면 유지(잔여 lookahead 소폭, 개발 E2E 편의).

### 3.2 (1) 뉴스 중립화
- `tradingagents/dataflows/news_macro.py` `fetch_macro_news(rss_urls, window_days=7, as_of=None)` — 인자 추가, 함수 맨 위:
  ```python
  if as_of is not None and is_pit_stale(as_of):
      return []
  ```
- `tradingagents/skills/news/news_fetcher.py` `fetch_macro_news_skill(rss_urls=None, window_days=7, as_of=None)` — 인자 추가 + `_fetch(..., as_of=as_of)` 전달.
- `tradingagents/agents/analysts/macro_news_analyst.py:135` — `fetch_macro_news_skill(window_days=NEWS_WINDOW_DAYS, as_of=as_of)` (as_of는 :131에서 이미 파싱됨).
- 빈 뉴스 → 하류(categorize/sentiment/speaker_events)가 이미 graceful → 중립 news_summary. (이벤트 캘린더·SAVE brief·overnight는 PIT 정확 → 유지.)

### 3.3 (1) Fear&Greed 중립화
- `tradingagents/skills/risk/fear_greed.py` `fetch_fear_greed_index(as_of, ...)` 함수 **맨 위**(cache 읽기 전):
  ```python
  if is_pit_stale(as_of):
      return None
  ```
- 맨 위에 두는 이유: stale 값이 cache에 기록되는 것 방지 + 기존 poisoned cache 무시. 하류는 None을 이미 graceful 처리(market_risk `fg = ... # may be None`).

### 3.4 (2) market_risk `period=` → `start/end`
`tradingagents/agents/analysts/market_risk_analyst.py` (노드에 `as_of`·`timedelta` 이미 in scope). 상수(168-170)를 일수 int로:
```python
REALIZED_VOL_LOOKBACK_DAYS = 120
SECTOR_DISP_LOOKBACK_DAYS = 65
MEGA_CAP_LOOKBACK_DAYS = 400
```
호출 교체 (창 길이 N 동일, 끝점만 today→as_of):
- 203: `yf.Ticker(ticker).history(start=as_of - timedelta(days=SECTOR_DISP_LOOKBACK_DAYS), end=as_of + timedelta(days=1), interval="1d")`
- 229: `yf.Ticker("RSP").history(start=as_of - timedelta(days=MEGA_CAP_LOOKBACK_DAYS), end=as_of + timedelta(days=1), interval="1d")`
- 230: `yf.Ticker("SPY").history(start=as_of - timedelta(days=MEGA_CAP_LOOKBACK_DAYS), end=as_of + timedelta(days=1), interval="1d")`
- 454: `spy.history(start=as_of - timedelta(days=REALIZED_VOL_LOOKBACK_DAYS), end=as_of + timedelta(days=1), interval="1d")`

(yfinance `.history`는 date 객체 start/end 허용. `end`는 exclusive라 `as_of+1`로 as_of 포함.) `.iloc[-1]`/`.iloc[-60]` 등 후속 로직 무변경.

## 4. 데이터 흐름 / 라이브 불변식
- 라이브(as_of=오늘): `is_pit_stale`=False → 뉴스·F&G 라이브 그대로. market_risk `start=오늘-N, end=오늘+1` ≈ `period="Nd"` → 동일 창. **산출물 불변.**
- 백테스트(as_of 과거): 뉴스 [], F&G None, market_risk가 as_of 시점 데이터. → 백테스트만 변함.
- as_of=None(레거시 직접 호출): 뉴스 가드 skip(라이브 동작) — backward-compat.

## 5. 에러 처리
순수 가드, 예외 없음. 빈 뉴스/None F&G는 기존 하류 처리 존재. market_risk start/end가 빈 df면 기존 `if h.empty or len(h)<60: continue`·try/except가 처리.

## 6. 테스트

**단위:**
- `tests/unit/dataflows/test_pit_guard.py`: `is_pit_stale(as_of, today=고정)` 경계 — 8일 전→True, 7일 전→False, 0일→False.
- 뉴스: `fetch_macro_news(urls, as_of=<먼 과거>)` → `[]` (feedparser 미호출 — 네트워크 없이 통과). `as_of=None` → 가드 skip(기존 경로).
- F&G: `fetch_fear_greed_index(<먼 과거 as_of>)` → `None` (scrape/cache 미접근).

**통합/E2E (라이브 불변 + 백테스트 억제 둘 다 확인):**
- E2E `--as-of 2026-05-29` (오늘 -6일, ≤7 → **not stale**): news_summary 비어있지 않음(라이브 경로 유지, 회귀 없음), validation 통과.
- E2E `--as-of 2026-05-15` (오늘 -20일, >7 → **stale**): news 항목 0 / F&G None, crash 없음, validation 통과.

## 7. 확장 항목 (v1 제외)
1. FRED/ECOS ALFRED vintage.
2. 과거 뉴스 아카이브 API(유료) — 중립화 대신 실제 과거 뉴스.
3. F&G 사전 스냅샷 시계열 적재.
4. `PIT_STALENESS_DAYS` 값 재검토(뉴스 window와 분리 튜닝).
