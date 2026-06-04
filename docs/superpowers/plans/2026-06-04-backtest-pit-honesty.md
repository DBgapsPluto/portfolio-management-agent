# 백테스트 Point-in-Time 정직성 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 백테스트(과거 as_of) 실행에서 라이브-온리 소스(뉴스·Fear&Greed)를 중립화하고 market_risk의 today-anchored `period=` 호출을 as_of-anchored `start/end`로 바꿔, 미래 데이터 누출(lookahead)을 제거한다. **라이브(as_of=오늘) 실행 산출물은 불변.**

**Architecture:** 신규 `pit_guard.is_pit_stale(as_of)` 가드 하나로 as_of가 7일 넘게 과거면 라이브-온리 소스가 빈/None 반환. market_risk는 `period="Nd"`→`start=as_of-N, end=as_of+1`(라이브에선 동일 창). 명시 플래그·별도 분기 없음.

**Tech Stack:** Python 3.13, pytest. 신규 의존성 없음.

**Spec:** `docs/superpowers/specs/2026-06-04-backtest-pit-honesty-design.md`

---

## File Structure

- **Create** `tradingagents/dataflows/pit_guard.py` — `PIT_STALENESS_DAYS` + `is_pit_stale`.
- **Modify** `tradingagents/dataflows/news_macro.py` — `fetch_macro_news` as_of 인자 + 가드.
- **Modify** `tradingagents/skills/news/news_fetcher.py` — `fetch_macro_news_skill` as_of 전달.
- **Modify** `tradingagents/agents/analysts/macro_news_analyst.py` — 호출에 as_of.
- **Modify** `tradingagents/skills/risk/fear_greed.py` — `fetch_fear_greed_index` 가드.
- **Modify** `tradingagents/agents/analysts/market_risk_analyst.py` — `period=`→`start/end` 4곳.
- **Test** `tests/unit/dataflows/test_pit_guard.py` (신규), 뉴스/F&G 가드 테스트.

---

## Task 1: `pit_guard.py` + 테스트

**Files:**
- Create: `tradingagents/dataflows/pit_guard.py`
- Test: `tests/unit/dataflows/test_pit_guard.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/dataflows/test_pit_guard.py`:

```python
from datetime import date

from tradingagents.dataflows.pit_guard import is_pit_stale, PIT_STALENESS_DAYS


def test_pit_staleness_threshold():
    today = date(2026, 6, 4)
    assert is_pit_stale(date(2026, 5, 15), today=today) is True    # 20일 전
    assert is_pit_stale(date(2026, 5, 27), today=today) is True    # 8일 전 (>7)
    assert is_pit_stale(date(2026, 5, 28), today=today) is False   # 7일 전 (==7, not >)
    assert is_pit_stale(date(2026, 5, 29), today=today) is False   # 6일 전
    assert is_pit_stale(today, today=today) is False               # 오늘


def test_pit_staleness_default_today():
    # today 미주입 시 date.today() 사용 — 먼 과거는 항상 stale
    assert is_pit_stale(date(2000, 1, 1)) is True


def test_pit_staleness_constant():
    assert PIT_STALENESS_DAYS == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/dataflows/test_pit_guard.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tradingagents.dataflows.pit_guard'`

- [ ] **Step 3: Implement**

Create `tradingagents/dataflows/pit_guard.py`:

```python
"""Point-in-time 가드 — 백테스트에서 라이브-온리 소스의 lookahead 차단 (spec 2026-06-04).

as_of가 오늘로부터 충분히 과거면 라이브 데이터(RSS 뉴스·CNN F&G)가 그 시점을 대표하지
못하므로 호출부가 중립값(빈/None)을 반환한다. 라이브(as_of≈오늘)는 발동하지 않는다.
"""
from datetime import date

PIT_STALENESS_DAYS: int = 7   # as_of가 이보다 과거면 라이브-온리 데이터는 point-in-time 불가


def is_pit_stale(as_of: date, today: date | None = None,
                 max_days: int = PIT_STALENESS_DAYS) -> bool:
    """as_of가 today 로부터 max_days 초과 과거면 True. today 미주입 시 date.today()."""
    today = today or date.today()
    return (today - as_of).days > max_days
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/dataflows/test_pit_guard.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/pit_guard.py tests/unit/dataflows/test_pit_guard.py
git commit -m "feat(backtest): point-in-time staleness 가드 (is_pit_stale)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: (1) 뉴스 + Fear&Greed 중립화

**Files:**
- Modify: `tradingagents/dataflows/news_macro.py`, `tradingagents/skills/news/news_fetcher.py`, `tradingagents/agents/analysts/macro_news_analyst.py`, `tradingagents/skills/risk/fear_greed.py`
- Test: `tests/unit/dataflows/test_pit_guard.py` (추가)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/dataflows/test_pit_guard.py`:

```python
from tradingagents.dataflows.news_macro import fetch_macro_news
from tradingagents.skills.news.news_fetcher import fetch_macro_news_skill
from tradingagents.skills.risk.fear_greed import fetch_fear_greed_index


def test_news_suppressed_when_stale():
    # 먼 과거 as_of → 빈 리스트 (네트워크/feedparser 미호출)
    assert fetch_macro_news(["http://example.com/rss"], as_of=date(2000, 1, 1)) == []
    assert fetch_macro_news_skill(as_of=date(2000, 1, 1)) == []


def test_fear_greed_suppressed_when_stale():
    # 먼 과거 as_of → None (scrape/cache 미접근)
    assert fetch_fear_greed_index(date(2000, 1, 1)) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/dataflows/test_pit_guard.py -k "suppressed" -v`
Expected: FAIL — `TypeError: fetch_macro_news() got an unexpected keyword argument 'as_of'` (and F&G still tries to scrape / returns non-None).

- [ ] **Step 3: Implement**

(a) `tradingagents/dataflows/news_macro.py` — add import at top and `as_of` param + guard:
```python
from tradingagents.dataflows.pit_guard import is_pit_stale
```
Change the signature of `fetch_macro_news`:
```python
def fetch_macro_news(rss_urls: list[str], window_days: int = 7,
                     as_of: "date | None" = None) -> list[NewsItem]:
```
(`date` is already imported in this module — it uses `datetime`; if only `datetime` is imported, add `from datetime import date` to the existing datetime import line.) As the FIRST statement in the function body:
```python
    if as_of is not None and is_pit_stale(as_of):
        return []
```

(b) `tradingagents/skills/news/news_fetcher.py` — thread `as_of`:
```python
def fetch_macro_news_skill(rss_urls: list[str] | None = None, window_days: int = 7,
                           as_of: "date | None" = None) -> list[NewsItem]:
    return _fetch(rss_urls or DEFAULT_RSS, window_days=window_days, as_of=as_of)
```
Add `from datetime import date` at top if not present.

(c) `tradingagents/agents/analysts/macro_news_analyst.py:135` — pass as_of (already parsed at line 131 `as_of = date.fromisoformat(...)`):
```python
        items = fetch_macro_news_skill(window_days=NEWS_WINDOW_DAYS, as_of=as_of)
```

(d) `tradingagents/skills/risk/fear_greed.py` — add import + guard as the FIRST statement of `fetch_fear_greed_index` (before `if not use_cache`):
```python
from tradingagents.dataflows.pit_guard import is_pit_stale
```
```python
def fetch_fear_greed_index(
    as_of: date, use_cache: bool = True, max_staleness: int = 3,
) -> SentimentSnapshot | None:
    """..."""
    if is_pit_stale(as_of):
        return None
    if not use_cache:
        ...
```

- [ ] **Step 4: Run the new tests + macro_news/fear_greed touch points (regression)**

Run: `.venv/bin/python -m pytest tests/unit/dataflows/test_pit_guard.py -v`
Expected: PASS (new suppression tests + Task 1 tests).

Also run any existing news/risk unit tests to confirm no breakage:
Run: `.venv/bin/python -m pytest tests/unit -k "news or fear_greed" -v`
Expected: PASS (no signature breakage; as_of defaults keep backward-compat).

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/news_macro.py tradingagents/skills/news/news_fetcher.py tradingagents/agents/analysts/macro_news_analyst.py tradingagents/skills/risk/fear_greed.py tests/unit/dataflows/test_pit_guard.py
git commit -m "feat(backtest): 뉴스·Fear&Greed를 stale as_of일 때 중립화 (lookahead 차단)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: (2) market_risk `period=` → `start/end`

**Files:**
- Modify: `tradingagents/agents/analysts/market_risk_analyst.py`

- [ ] **Step 1: Implement (mechanical — 동작 검증은 기존 테스트 + E2E)**

In `tradingagents/agents/analysts/market_risk_analyst.py`, inside `node` (`as_of`·`timedelta` already in scope):

(a) Replace the three period constants (currently lines ~168-170):
```python
        REALIZED_VOL_LOOKBACK_PERIOD = "120d"
        SECTOR_DISP_HIST_PERIOD = "65d"
        MEGA_CAP_HIST_PERIOD = "400d"
```
with day-int constants:
```python
        REALIZED_VOL_LOOKBACK_DAYS = 120
        SECTOR_DISP_LOOKBACK_DAYS = 65
        MEGA_CAP_LOOKBACK_DAYS = 400
```

(b) Sector dispersion call (currently line ~203):
```python
                    h = yf.Ticker(ticker).history(period=SECTOR_DISP_HIST_PERIOD, interval="1d")
```
→
```python
                    h = yf.Ticker(ticker).history(
                        start=as_of - timedelta(days=SECTOR_DISP_LOOKBACK_DAYS),
                        end=as_of + timedelta(days=1), interval="1d")
```

(c) Mega-cap calls (currently lines ~229-230):
```python
            rsp_hist = yf.Ticker("RSP").history(period=MEGA_CAP_HIST_PERIOD, interval="1d")
            spy_hist = yf.Ticker("SPY").history(period=MEGA_CAP_HIST_PERIOD, interval="1d")
```
→
```python
            rsp_hist = yf.Ticker("RSP").history(
                start=as_of - timedelta(days=MEGA_CAP_LOOKBACK_DAYS),
                end=as_of + timedelta(days=1), interval="1d")
            spy_hist = yf.Ticker("SPY").history(
                start=as_of - timedelta(days=MEGA_CAP_LOOKBACK_DAYS),
                end=as_of + timedelta(days=1), interval="1d")
```

(d) SPY realized vol call (currently line ~454):
```python
            hist = spy.history(period=REALIZED_VOL_LOOKBACK_PERIOD, interval="1d")
```
→
```python
            hist = spy.history(
                start=as_of - timedelta(days=REALIZED_VOL_LOOKBACK_DAYS),
                end=as_of + timedelta(days=1), interval="1d")
```

No other logic changes (`.iloc[-1]`/`.iloc[-60]`/`pct_change` 등 그대로).

- [ ] **Step 2: Run existing market_risk tests (regression)**

Run: `.venv/bin/python -m pytest tests/unit/agents/test_market_risk_analyst.py tests/unit/agents/test_market_risk_tier0.py -v`
Expected: PASS (분석가 노드가 여전히 동작 — start/end로 바뀌어도 스키마/흐름 동일).
(이 변경의 lookahead 제거 효과는 Task 4 E2E backtest로 검증.)

- [ ] **Step 3: Commit**

```bash
git add tradingagents/agents/analysts/market_risk_analyst.py
git commit -m "feat(backtest): market_risk period= → as_of-anchored start/end (lookahead 제거)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: E2E 검증 (라이브 불변 + 백테스트 억제)

**Files:** 코드 변경 없음 — 실행 검증.

- [ ] **Step 1: 전체 관련 스위트 회귀**

Run: `.venv/bin/python -m pytest tests/unit/dataflows/test_pit_guard.py tests/unit/agents/test_market_risk_analyst.py tests/unit/agents/test_market_risk_tier0.py tests/integration/test_plan_pipeline_mock.py -q`
Expected: PASS.

- [ ] **Step 2: 라이브 경로 불변 확인 (not-stale)**

Run: `.venv/bin/python scripts/run_e2e_test.py --as-of 2026-05-29 --capital 1000000000`
Expected: EXIT 0, validation 통과. 2026-05-29는 오늘(-6일) ≤ 7 → not stale → 뉴스 유지(회귀 없음).
검증: `.venv/bin/python -c "import json,glob; print(len(open('artifacts/2026-05-29/philosophy.md').read()))"` 가 정상(뉴스 섹션 포함).

- [ ] **Step 3: 백테스트 억제 확인 (stale)**

Run: `.venv/bin/python scripts/run_e2e_test.py --as-of 2026-05-15 --capital 1000000000`
Expected: EXIT 0, validation 통과, crash 없음. 2026-05-15는 오늘(-20일) > 7 → stale → 뉴스 항목 0 / F&G None.
검증(로그): 실행 로그에서 `macro_news` 가 뉴스 0건으로 진행되고 파이프라인이 끝까지 완주하는지 확인.

- [ ] **Step 4: 결과 보고 (코드 변경 없으니 commit 생략)**

2026-05-29(뉴스 유지=라이브 불변) vs 2026-05-15(뉴스 off=백테스트 정직) 대비 + 둘 다 validation 통과를 사용자에게 요약 보고.

---

## Self-Review

**1. Spec coverage:**
- §3.1 `pit_guard` → Task 1 ✅
- §3.2 뉴스 (3파일 threading + 가드) → Task 2(a,b,c) ✅ / §3.3 F&G 가드 → Task 2(d) ✅
- §3.4 market_risk 4곳 → Task 3 ✅
- §4 라이브 불변식 → Task 4 Step 2(2026-05-29 not-stale 회귀) ✅
- §6 테스트(단위 가드·억제 + E2E 2종) → Task 1/2/4 ✅
- §7 확장 → 제외(의도) ✅

**2. Placeholder scan:** TBD/TODO 없음. 모든 step 실제 코드·명령·기대 출력.

**3. Type consistency:** `is_pit_stale(as_of, today=None, max_days=...)` 정의(Task 1) ↔ 호출(news_macro·fear_greed, Task 2) 일치. `fetch_macro_news(..., as_of=None)`·`fetch_macro_news_skill(..., as_of=None)` 신규 인자(Task 2) ↔ analyst 호출 `as_of=as_of`(Task 2c) 일치. market_risk 상수명 변경(REALIZED_VOL_LOOKBACK_DAYS 등) ↔ 4 호출지 사용(Task 3) 일치.
