# 리밸런싱 엔진 Plan A — 거래계획 엔진 + monthly 리밸런싱 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 직전 산출물을 현재가로 재평가해 현재 보유를 구하고, 목표와의 델타로 매수/매도 거래계획(현금 잔여 포함)을 만들어 mandate 재검증까지 거치는 공통 엔진을 만들고, `gaps rebalance monthly`가 이 엔진으로 완전 동작하게 한다.

**Architecture:** 순수 결정론 엔진(`tradingagents/rebalance/engine.py`)이 `reprice_holdings`(보유 재평가) → `build_rebalance_plan`(델타·no-trade band·정수 qty·현금·turnover·실현비중) → `validate_rebalance`(realized 비중에 검증 skill 4종 직접 조합)을 담당. 산출물 3종은 `reports/`에. monthly는 기존 full 파이프라인(`graph.run`)으로 목표를 얻고 엔진을 호출. LLM은 monthly 사유서에서만 사용.

**Tech Stack:** Python 3.12+, pytest, pydantic v2, 기존 tradingagents 모듈(schemas/portfolio, schemas/mandate, skills/mandate, skills/portfolio, dataflows/universe).

**스펙:** [docs/superpowers/specs/2026-06-07-rebalancing-engine-design.md](../specs/2026-06-07-rebalancing-engine-design.md) (§4 데이터구조, §6.3 monthly, §6.4 클러스터, §7 엔진, §8 산출물, §9 수정점)

**범위 경계:** 이 Plan은 **monthly 경로와 공통 엔진**만 다룬다. daily 트리거 라우터·방어 오버레이·reassess는 Plan B, GitHub Actions·알림은 Plan C. 본 Plan 완료 시 `gaps rebalance monthly --from <직전 portfolio.json 디렉토리>`가 현재 보유 재평가 → 새 목표 → 델타 거래계획 → mandate 재검증 → 산출물 3종을 산출한다.

---

## File Structure

| 파일 | 책임 | 신규/수정 |
|---|---|---|
| `tradingagents/rebalance/types.py` | `TradeLine`, `RebalanceResult` dataclass | 신규 |
| `tradingagents/rebalance/pricing.py` | 현재가 fetch 공용 함수(portfolio_manager에서 추출) | 신규 |
| `tradingagents/rebalance/holdings.py` | 직전 trade_plan.csv → 보유 수량/현금 로딩 | 신규 |
| `tradingagents/rebalance/engine.py` | `reprice_holdings`·`build_rebalance_plan`·`validate_rebalance`·위험분류 | 신규 |
| `tradingagents/reports/rebalance_plan.py` | `write_rebalance_plan`(csv)·`write_rebalance_json` | 신규 |
| `tradingagents/reports/rebalance_rationale.py` | `write_rebalance_rationale`(monthly LLM) | 신규 |
| `tradingagents/agents/managers/portfolio_manager.py` | `correlation_clusters` portfolio.json 영속화; `_fetch_current_prices`→pricing import | 수정 |
| `tradingagents/rebalance/monthly_full.py` | previous 전달 + engine 호출 | 수정 |
| `cli/commands/portfolio.py` | `rebalance monthly` 엔진 결과 출력 | 수정 |
| `tests/unit/rebalance/` | 단위 테스트 | 신규 |

---

## Task 1: rebalance 데이터 구조

**Files:**
- Create: `tradingagents/rebalance/types.py`
- Test: `tests/unit/rebalance/test_types.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/unit/rebalance/test_types.py
from tradingagents.rebalance.types import TradeLine, RebalanceResult


def test_trade_line_fields():
    t = TradeLine(ticker="A069500", action="BUY", current_qty=0,
                  target_qty=10, delta_qty=10, delta_amount_krw=100000)
    assert t.action == "BUY"
    assert t.delta_qty == 10


def test_rebalance_result_defaults():
    r = RebalanceResult(as_of="2026-06-07", tier="monthly")
    assert r.plan == []
    assert r.cash_residual_krw == 0
    assert r.tier == "monthly"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/unit/rebalance/test_types.py -v`
Expected: FAIL — `ModuleNotFoundError: tradingagents.rebalance.types`

- [ ] **Step 3: 구현**

```python
# tradingagents/rebalance/types.py
"""리밸런싱 엔진 데이터 구조 (스펙 §4.1)."""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TradeLine:
    ticker: str
    action: str                 # "BUY" | "SELL" | "HOLD"
    current_qty: int
    target_qty: int
    delta_qty: int              # +매수 / -매도
    delta_amount_krw: int


@dataclass
class RebalanceResult:
    as_of: str
    tier: str                   # "daily" | "reassess" | "monthly" | "none"
    current_weights: dict[str, float] = field(default_factory=dict)   # 현금 포함("CASH")
    target_weights: dict[str, float] = field(default_factory=dict)
    realized_weights: dict[str, float] = field(default_factory=dict)
    plan: list[TradeLine] = field(default_factory=list)
    turnover: float = 0.0
    cash_residual_krw: int = 0
    cash_weight: float = 0.0
    skipped_no_trade: list[str] = field(default_factory=list)
    trigger: dict[str, Any] = field(default_factory=dict)
    validation: Any = None      # ValidationReport
    rationale_md: str = ""
    paths: dict[str, str] = field(default_factory=dict)
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/unit/rebalance/test_types.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/rebalance/types.py tests/unit/rebalance/test_types.py
git commit -m "feat(rebalance): TradeLine·RebalanceResult 데이터 구조"
```

---

## Task 2: 현재가 fetch 공용 추출

기존 [`portfolio_manager._fetch_current_prices`](../../../tradingagents/agents/managers/portfolio_manager.py)를 엔진과 공유하도록 모듈로 추출(스펙 §7.1). 동작 동일, 위치만 이동.

**Files:**
- Create: `tradingagents/rebalance/pricing.py`
- Modify: `tradingagents/agents/managers/portfolio_manager.py:36-69` (함수 본문 → import로 교체)
- Test: `tests/unit/rebalance/test_pricing.py`

- [ ] **Step 1: 테스트 작성** (walk-back 동작 — KRX fetch를 monkeypatch)

```python
# tests/unit/rebalance/test_pricing.py
from datetime import date
import tradingagents.rebalance.pricing as pricing


def test_walks_back_when_today_empty(monkeypatch):
    calls = []
    def fake_close_map(d):
        calls.append(d)
        return {"A069500": 10000.0} if d == date(2026, 6, 5) else {}
    monkeypatch.setattr(pricing, "fetch_etf_close_map", fake_close_map, raising=False)
    out = pricing.fetch_current_prices(date(2026, 6, 7))
    assert out == {"A069500": 10000.0}
    assert calls[0] == date(2026, 6, 7)   # 오늘부터 시작
    assert date(2026, 6, 5) in calls       # walk-back 도달


def test_empty_on_total_failure(monkeypatch):
    monkeypatch.setattr(pricing, "fetch_etf_close_map", lambda d: {}, raising=False)
    assert pricing.fetch_current_prices(date(2026, 6, 7)) == {}
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/unit/rebalance/test_pricing.py -v`
Expected: FAIL — `ModuleNotFoundError: tradingagents.rebalance.pricing`

- [ ] **Step 3: 구현** — `_fetch_current_prices` 본문을 그대로 옮기고 모듈-레벨 import로 monkeypatch 가능하게.

```python
# tradingagents/rebalance/pricing.py
"""현재가 fetch 공용 함수 — portfolio_manager·rebalance engine 공유 (스펙 §7.1).

KRX OpenAPI 는 T+1~T+2 지연 — as_of 당일 데이터가 없으면 직전 영업일로
최대 7일 walk-back. 빈 dict = 휴장/실패(qty=0 graceful).
"""
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

try:
    from tradingagents.dataflows.krx_openapi import fetch_etf_close_map
except Exception:  # import 실패도 graceful — 호출 시 빈 dict
    fetch_etf_close_map = None


def fetch_current_prices(as_of: date) -> dict[str, float]:
    if fetch_etf_close_map is None:
        logger.warning("krx_openapi import 불가 — qty=0")
        return {}
    d = as_of
    for _ in range(8):  # as_of 포함 최대 8일 (주말+연휴 방어)
        try:
            prices = fetch_etf_close_map(d)
        except Exception as e:
            logger.warning("current_prices fetch 실패 (%s): %s — qty=0", d, e)
            return {}
        if prices:
            if d != as_of:
                logger.info("current_prices: %s 미제공 → 직전 %s 종가 사용", as_of, d)
            return prices
        d -= timedelta(days=1)
    logger.warning("current_prices: %s~%s 전 구간 빈 응답 — qty=0", d, as_of)
    return {}
```

- [ ] **Step 4: portfolio_manager가 공용 함수 사용하도록 교체**

`tradingagents/agents/managers/portfolio_manager.py`에서 `_fetch_current_prices` 함수 정의(36-69행)를 삭제하고, 상단 import 추가 + 호출부(144행 `current_prices = _fetch_current_prices(as_of)`) 교체:

```python
# import 섹션에 추가:
from tradingagents.rebalance.pricing import fetch_current_prices
# 144행:
current_prices = fetch_current_prices(as_of)
```

- [ ] **Step 5: 테스트 + 회귀 확인**

Run: `pytest tests/unit/rebalance/test_pricing.py tests/ -k portfolio_manager -v`
Expected: PASS (pricing 2 passed; portfolio_manager 관련 테스트 회귀 없음)

- [ ] **Step 6: 커밋**

```bash
git add tradingagents/rebalance/pricing.py tradingagents/agents/managers/portfolio_manager.py tests/unit/rebalance/test_pricing.py
git commit -m "refactor(rebalance): 현재가 fetch 공용 모듈로 추출"
```

---

## Task 3: 직전 보유 로딩 (trade_plan.csv → 수량·현금)

직전 산출 디렉토리에서 보유 수량과 현금을 읽는다(스펙 §7.1). 직전 `(rebalancing)_plan.csv`(있으면) 또는 `trade_plan.csv`의 `수량(주)` 컬럼을 파싱.

**Files:**
- Create: `tradingagents/rebalance/holdings.py`
- Test: `tests/unit/rebalance/test_holdings.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/unit/rebalance/test_holdings.py
from pathlib import Path
from tradingagents.rebalance.holdings import load_prev_holdings


def _write(tmp_path, name, rows):
    p = tmp_path / name
    p.write_text(rows, encoding="utf-8-sig")
    return p


def test_loads_qty_from_trade_plan(tmp_path):
    _write(tmp_path, "trade_plan.csv",
           "티커,ETF명,자산군,가중치,매수금액(KRW),수량(주)\n"
           "A069500,KODEX200,국내주식,0.5,500000,50\n"
           "A229200,KODEX코스닥,국내주식,0.5,500000,25\n")
    qty, cash = load_prev_holdings(tmp_path)
    assert qty == {"A069500": 50, "A229200": 25}
    assert cash == 0


def test_prefers_rebalancing_plan_and_reads_cash(tmp_path):
    _write(tmp_path, "trade_plan.csv", "티커,수량(주)\nA069500,1\n")
    _write(tmp_path, "2026-06-07(rebalancing)_plan.csv",
           "티커,ETF명,자산군,현재수량,목표수량,매매구분,거래수량,거래금액(KRW)\n"
           "A069500,KODEX200,국내주식,0,50,BUY,50,500000\n"
           "# CASH_RESIDUAL_KRW: 12345\n")
    qty, cash = load_prev_holdings(tmp_path)
    assert qty == {"A069500": 50}     # 목표수량 = 리밸 후 보유
    assert cash == 12345
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/unit/rebalance/test_holdings.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

```python
# tradingagents/rebalance/holdings.py
"""직전 산출물에서 현재 보유 수량·현금 로딩 (스펙 §7.1).

우선순위: 직전 (rebalancing)_plan.csv 의 '목표수량'(리밸 후 보유) > trade_plan.csv 의 '수량(주)'.
현금은 (rebalancing)_plan.csv 의 '# CASH_RESIDUAL_KRW:' 주석 라인에서.
"""
import csv
import glob
from pathlib import Path


def _read_cash(path: Path) -> int:
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("# CASH_RESIDUAL_KRW:"):
            return int(line.split(":", 1)[1].strip())
    return 0


def load_prev_holdings(prev_dir: Path) -> tuple[dict[str, int], int]:
    """Return (ticker→qty, cash_krw). 빈 dict 가능(파일 없음)."""
    rebal = sorted(glob.glob(str(prev_dir / "*(rebalancing)_plan.csv")))
    if rebal:
        path = Path(rebal[-1])
        qty: dict[str, int] = {}
        with path.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                t = (row.get("티커") or "").strip()
                if not t or t.startswith("#"):
                    continue
                qty[t] = int(float(row.get("목표수량") or 0))
        return {t: q for t, q in qty.items() if q > 0}, _read_cash(path)

    tp = prev_dir / "trade_plan.csv"
    if tp.exists():
        qty = {}
        with tp.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                t = (row.get("티커") or "").strip()
                if not t or t.startswith("#"):
                    continue
                qty[t] = int(float(row.get("수량(주)") or 0))
        return {t: q for t, q in qty.items() if q > 0}, 0

    return {}, 0
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/unit/rebalance/test_holdings.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/rebalance/holdings.py tests/unit/rebalance/test_holdings.py
git commit -m "feat(rebalance): 직전 산출물 보유 수량·현금 로딩"
```

---

## Task 4: reprice_holdings — 보유 재평가 (현금 포함)

수량 × 오늘 종가 → 현재 비중. 현금 포지션 포함, 합 1.0. 가격 실패 종목은 제외하지 않고 0 평가(보수적으로 직전 비중을 유지하려면 가격이 필요하므로, 가격 없으면 그 종목은 평가액 0 → 비중 0, 경고). (스펙 §7.1)

**Files:**
- Create: `tradingagents/rebalance/engine.py`
- Test: `tests/unit/rebalance/test_reprice.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/unit/rebalance/test_reprice.py
from tradingagents.rebalance.engine import reprice_holdings


def test_reprice_includes_cash_and_sums_to_one():
    qty = {"A069500": 50, "A229200": 25}
    prices = {"A069500": 10000.0, "A229200": 20000.0}
    # 평가액: 500000 + 500000 = 1,000,000, 현금 0
    w = reprice_holdings(qty, cash_krw=0, prices=prices)
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert abs(w["A069500"] - 0.5) < 1e-9
    assert abs(w["A229200"] - 0.5) < 1e-9
    assert "CASH" not in w or w.get("CASH", 0) == 0


def test_reprice_cash_weight():
    qty = {"A069500": 50}
    prices = {"A069500": 10000.0}  # 평가액 500,000 + 현금 500,000 = 1,000,000
    w = reprice_holdings(qty, cash_krw=500000, prices=prices)
    assert abs(w["A069500"] - 0.5) < 1e-9
    assert abs(w["CASH"] - 0.5) < 1e-9


def test_reprice_missing_price_zero_weight():
    qty = {"A069500": 50, "AMISSING": 10}
    prices = {"A069500": 10000.0}  # AMISSING 가격 없음
    w = reprice_holdings(qty, cash_krw=0, prices=prices)
    assert w["A069500"] == 1.0          # 전체가 A069500
    assert w.get("AMISSING", 0.0) == 0.0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/unit/rebalance/test_reprice.py -v`
Expected: FAIL — `ImportError: cannot import name 'reprice_holdings'`

- [ ] **Step 3: 구현** (engine.py 시작)

```python
# tradingagents/rebalance/engine.py
"""리밸런싱 공통 엔진 — 보유 재평가·델타 거래계획·재검증 (스펙 §7).

전부 LLM 0 — 순수 결정론. 현금 포지션은 키 "CASH"로 표현.
"""
import logging

logger = logging.getLogger(__name__)

CASH_KEY = "CASH"


def reprice_holdings(
    qty: dict[str, int], cash_krw: int, prices: dict[str, float],
) -> dict[str, float]:
    """보유 수량 × 오늘 종가 + 현금 → 비중(합 1.0). 현금은 CASH_KEY.

    가격 없는 종목은 평가액 0(비중 0) + 경고.
    """
    value: dict[str, float] = {}
    for t, q in qty.items():
        p = prices.get(t, 0.0)
        if p <= 0:
            logger.warning("reprice: %s 가격 없음 → 평가액 0", t)
        value[t] = q * p
    total = sum(value.values()) + max(cash_krw, 0)
    if total <= 0:
        return {}
    weights = {t: v / total for t, v in value.items()}
    if cash_krw > 0:
        weights[CASH_KEY] = cash_krw / total
    return weights
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/unit/rebalance/test_reprice.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/rebalance/engine.py tests/unit/rebalance/test_reprice.py
git commit -m "feat(rebalance): reprice_holdings 보유 재평가(현금 포함)"
```

---

## Task 5: 위험자산 분류 헬퍼

universe로 `ticker→ETF` 맵을 만들고 위험자산 여부·합계를 계산(스펙 §5.2, [trader_allocator.py:230-234](../../../tradingagents/agents/trader/trader_allocator.py) 패턴). 현금(CASH_KEY)은 위험자산 아님.

**Files:**
- Modify: `tradingagents/rebalance/engine.py` (함수 추가)
- Test: `tests/unit/rebalance/test_risk_classify.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/unit/rebalance/test_risk_classify.py
from tradingagents.dataflows.universe import Universe, ETFEntry
from tradingagents.rebalance.engine import make_is_risk, risk_total


def _uni():
    return Universe(version="t", etfs=[
        ETFEntry(ticker="A069500", name="KODEX200", aum_krw=1e12,
                 underlying_index="KOSPI200", bucket="위험",
                 category="국내주식_지수"),
        ETFEntry(ticker="A114260", name="KODEX국고채", aum_krw=1e11,
                 underlying_index="KTB", bucket="안전",
                 category="국내채권_지수"),
    ])


def test_is_risk():
    is_risk = make_is_risk(_uni())
    assert is_risk("A069500") is True      # kr_equity → 위험
    assert is_risk("A114260") is False     # kr_bond → 안전
    assert is_risk("CASH") is False        # 현금 → 안전


def test_risk_total_excludes_cash():
    is_risk = make_is_risk(_uni())
    w = {"A069500": 0.6, "A114260": 0.3, "CASH": 0.1}
    assert abs(risk_total(w, is_risk) - 0.6) < 1e-9
```

> ⚠️ ETFEntry 필수 필드(ticker/name/aum_krw/underlying_index/bucket/category)를 확인하고 카테고리 문자열이 `bucket_for_etf`의 8-bucket 매핑에서 `kr_equity`/`kr_bond`로 해석되는지 [sub_category.py](../../../tradingagents/skills/portfolio/sub_category.py)의 `_CATEGORY_TO_BUCKET`로 검증할 것. 매핑이 다르면 위 카테고리 문자열을 실제 universe.json 값으로 교체.

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/unit/rebalance/test_risk_classify.py -v`
Expected: FAIL — `ImportError: make_is_risk`

- [ ] **Step 3: 구현** (engine.py에 추가)

```python
# engine.py 상단 import 추가
from collections.abc import Callable
from tradingagents.dataflows.universe import Universe
from tradingagents.skills.portfolio.sub_category import bucket_for_etf
from tradingagents.skills.mandate.concentration_check import RISK_BUCKET_NAMES


def make_is_risk(universe: Universe) -> Callable[[str], bool]:
    """ticker → 위험자산 여부. CASH·미분류·universe 외 ticker는 False."""
    meta = {e.ticker: e for e in universe.etfs}
    def is_risk(ticker: str) -> bool:
        if ticker == CASH_KEY:
            return False
        e = meta.get(ticker)
        return bool(e) and bucket_for_etf(e) in RISK_BUCKET_NAMES
    return is_risk


def risk_total(weights: dict[str, float], is_risk: Callable[[str], bool]) -> float:
    return sum(w for t, w in weights.items() if is_risk(t))
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/unit/rebalance/test_risk_classify.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/rebalance/engine.py tests/unit/rebalance/test_risk_classify.py
git commit -m "feat(rebalance): 위험자산 분류 헬퍼(make_is_risk·risk_total)"
```

---

## Task 6: build_rebalance_plan — 델타 + no-trade band + cap 예외

목표−현재 델타에서 작은 델타는 생략하되, **cap 버퍼 초과 종목의 cap-방향 델타는 항상 실행**(finding #2, 스펙 §7.2 step 2). 현금(CASH_KEY)은 거래 대상 아님 — 종목만.

**Files:**
- Modify: `tradingagents/rebalance/engine.py`
- Test: `tests/unit/rebalance/test_build_plan_delta.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/unit/rebalance/test_build_plan_delta.py
from tradingagents.rebalance.engine import compute_deltas


def _dials(**kw):
    base = dict(no_trade_band=0.005, single_etf_abs_cap=0.19,
               risk_asset_abs_cap=0.68)
    base.update(kw); return base


def test_small_delta_skipped():
    cur = {"A": 0.50, "B": 0.50}
    tgt = {"A": 0.502, "B": 0.498}     # |Δ|=0.002 < 0.005
    delta, skipped = compute_deltas(cur, tgt, _dials(), is_risk=lambda t: False)
    assert delta == {}                  # 전부 생략
    assert set(skipped) == {"A", "B"}


def test_large_delta_kept():
    cur = {"A": 0.50, "B": 0.50}
    tgt = {"A": 0.40, "B": 0.60}        # |Δ|=0.10
    delta, skipped = compute_deltas(cur, tgt, _dials(), is_risk=lambda t: False)
    assert abs(delta["A"] + 0.10) < 1e-9
    assert abs(delta["B"] - 0.10) < 1e-9
    assert skipped == []


def test_cap_buffer_exempt_forces_small_sell():
    # A가 0.203(cap 0.20 초과)인데 목표 0.200 → Δ=-0.003 (band 미만)이지만
    # cap-방향 축소라 band 예외로 실행해야 (finding #2).
    cur = {"A": 0.203, "B": 0.797}
    tgt = {"A": 0.200, "B": 0.800}
    delta, skipped = compute_deltas(cur, tgt, _dials(), is_risk=lambda t: False)
    assert "A" in delta and delta["A"] < 0     # 강제 실행
    assert "A" not in skipped


def test_risk_cap_exempt_forces_risk_reduction():
    # 위험자산 합 0.69 > 0.68 → 위험 종목 축소 델타는 작아도 실행.
    cur = {"R": 0.69, "S": 0.31}
    tgt = {"R": 0.688, "S": 0.312}     # Δ_R=-0.002 (band 미만)
    is_risk = lambda t: t == "R"
    delta, skipped = compute_deltas(cur, tgt, _dials(), is_risk=is_risk)
    assert "R" in delta and delta["R"] < 0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/unit/rebalance/test_build_plan_delta.py -v`
Expected: FAIL — `ImportError: compute_deltas`

- [ ] **Step 3: 구현** (engine.py에 추가)

```python
def compute_deltas(
    current: dict[str, float], target: dict[str, float],
    dials: dict, is_risk: Callable[[str], bool],
) -> tuple[dict[str, float], list[str]]:
    """목표−현재 델타. no-trade band 적용, 단 cap-방향 버퍼초과 델타는 예외 실행.

    Returns (delta(실행할 것만), skipped_tickers). CASH_KEY 는 제외(현금은 거래 안 함).
    """
    band = dials["no_trade_band"]
    single_cap = dials["single_etf_abs_cap"]
    risk_cap = dials["risk_asset_abs_cap"]
    cur_risk = risk_total(current, is_risk)

    tickers = (set(current) | set(target)) - {CASH_KEY}
    delta: dict[str, float] = {}
    skipped: list[str] = []
    for t in tickers:
        d = target.get(t, 0.0) - current.get(t, 0.0)
        if abs(d) >= band:
            delta[t] = d
            continue
        # band 미만 — cap-방향 예외 검사
        over_single = current.get(t, 0.0) > single_cap and d < 0
        over_risk = cur_risk > risk_cap and is_risk(t) and d < 0
        if over_single or over_risk:
            delta[t] = d          # 강제 실행
        elif d != 0.0:
            skipped.append(t)
    return delta, skipped
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/unit/rebalance/test_build_plan_delta.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/rebalance/engine.py tests/unit/rebalance/test_build_plan_delta.py
git commit -m "feat(rebalance): 델타 계산 + no-trade band(cap 버퍼 예외)"
```

---

## Task 7: build_rebalance_plan — 정수 qty + 잔여현금(현금 보유) + turnover + 실현비중

델타를 정수 수량으로, 잔여는 현금 보유, turnover는 실현 거래액 기준, realized_post 비중 산출(스펙 §7.2 step 3·4·6). **현금성 ETF로 sweep하지 않음**(사용자 지시).

**Files:**
- Modify: `tradingagents/rebalance/engine.py`
- Test: `tests/unit/rebalance/test_build_plan_qty.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/unit/rebalance/test_build_plan_qty.py
from tradingagents.rebalance.engine import build_rebalance_plan


def _dials():
    return dict(no_trade_band=0.005, single_etf_abs_cap=0.19,
                risk_asset_abs_cap=0.68)


def test_buy_sell_hold_classification():
    current = {"A": 0.50, "B": 0.50}
    target = {"A": 0.30, "B": 0.70}
    prices = {"A": 10000.0, "B": 10000.0}
    res = build_rebalance_plan(current, target, capital=1_000_000,
                               prices=prices, is_risk=lambda t: False, dials=_dials())
    by = {tl.ticker: tl for tl in res["plan"]}
    assert by["A"].action == "SELL" and by["A"].delta_qty < 0
    assert by["B"].action == "BUY" and by["B"].delta_qty > 0


def test_cash_residual_held_not_swept():
    # 목표 100% A지만 정수 qty 반올림으로 잔여 발생 → 현금 보유.
    current = {"A": 0.0}
    target = {"A": 1.0}
    prices = {"A": 30000.0}          # 1,000,000 / 30,000 = 33.33 → 33주 = 990,000
    res = build_rebalance_plan(current, target, capital=1_000_000,
                               prices=prices, is_risk=lambda t: False, dials=_dials())
    assert res["cash_residual_krw"] == 10000     # 1,000,000 - 33*30,000
    assert res["realized_weights"]["CASH"] == 0.01
    # 현금성 ETF 추가 매수 라인이 없어야(sweep 안 함)
    assert all(tl.ticker == "A" for tl in res["plan"])


def test_turnover_realized():
    current = {"A": 0.50, "B": 0.50}
    target = {"A": 0.30, "B": 0.70}
    prices = {"A": 10000.0, "B": 10000.0}
    res = build_rebalance_plan(current, target, capital=1_000_000,
                               prices=prices, is_risk=lambda t: False, dials=_dials())
    # 매도 A ~0.20, 매수 B ~0.20 → turnover ≈ (0.20+0.20) = 0.40 (정수 반올림 오차 허용)
    assert abs(res["turnover"] - 0.40) < 0.02
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/unit/rebalance/test_build_plan_qty.py -v`
Expected: FAIL — `ImportError: build_rebalance_plan`

- [ ] **Step 3: 구현** (engine.py에 추가)

```python
from tradingagents.rebalance.types import TradeLine


def build_rebalance_plan(
    current: dict[str, float], target: dict[str, float], capital: int,
    prices: dict[str, float], is_risk: Callable[[str], bool], dials: dict,
) -> dict:
    """현재→목표 거래계획. 잔여는 현금 보유(sweep 안 함). 실현 비중·turnover 산출.

    Returns dict: plan·skipped_no_trade·cash_residual_krw·realized_weights·turnover.
    """
    delta, skipped = compute_deltas(current, target, dials, is_risk)

    # 현재 보유 금액 추정 (현재 비중 × capital). 정수 qty 는 현재 qty 와 목표 qty 차.
    plan: list[TradeLine] = []
    invested = 0
    buy_krw = 0
    sell_krw = 0
    target_value: dict[str, float] = {}
    for t in (set(current) | set(target)) - {CASH_KEY}:
        p = prices.get(t, 0.0)
        cur_qty = int(round(current.get(t, 0.0) * capital / p)) if p > 0 else 0
        # 목표 비중: 델타 실행분만 반영 (band 로 생략된 종목은 현재 유지)
        eff_target_w = current.get(t, 0.0) + delta.get(t, 0.0)
        tgt_qty = int(round(eff_target_w * capital / p)) if p > 0 else cur_qty
        dq = tgt_qty - cur_qty
        if dq == 0:
            action = "HOLD"
        elif dq > 0:
            action = "BUY"; buy_krw += dq * p
        else:
            action = "SELL"; sell_krw += (-dq) * p
        if p > 0:
            target_value[t] = tgt_qty * p
            invested += tgt_qty * p
        plan.append(TradeLine(
            ticker=t, action=action, current_qty=cur_qty, target_qty=tgt_qty,
            delta_qty=dq, delta_amount_krw=int(dq * p),
        ))

    cash_residual = max(capital - invested, 0)
    realized = {t: v / capital for t, v in target_value.items()}
    if cash_residual > 0:
        realized[CASH_KEY] = cash_residual / capital
    turnover = (buy_krw + sell_krw) / capital if capital else 0.0

    return {
        "plan": sorted(plan, key=lambda tl: -abs(tl.delta_amount_krw)),
        "skipped_no_trade": skipped,
        "cash_residual_krw": int(cash_residual),
        "realized_weights": realized,
        "turnover": turnover,
    }
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/unit/rebalance/test_build_plan_qty.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/rebalance/engine.py tests/unit/rebalance/test_build_plan_qty.py
git commit -m "feat(rebalance): 정수 qty·잔여현금 보유·turnover·실현비중"
```

---

## Task 8: validate_rebalance — 실현 비중에 전체 mandate 재검증

realized_weights(WeightVector로 wrap)에 검증 skill 4종을 직접 조합(스펙 §7.2 step 5, finding #2·#6·#7). 클러스터 입력원은 인자로 받음(Task 9에서 영속화한 것 또는 재계산 — monthly는 graph가 이미 검증하나 엔진 일관성을 위해 realized에 재검증). 현금(CASH_KEY)은 검증 전 제외하고 종목 비중을 재정규화하여 WeightVector(합≈1) 제약을 만족시킨다.

**Files:**
- Modify: `tradingagents/rebalance/engine.py`
- Test: `tests/unit/rebalance/test_validate_rebalance.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/unit/rebalance/test_validate_rebalance.py
from tradingagents.dataflows.universe import Universe, ETFEntry
from tradingagents.rebalance.engine import validate_rebalance


def _uni():
    return Universe(version="t", etfs=[
        ETFEntry(ticker="A069500", name="KODEX200", aum_krw=1e12,
                 underlying_index="KOSPI200", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A114260", name="KODEX국고채", aum_krw=1e11,
                 underlying_index="KTB", bucket="안전", category="국내채권_지수"),
    ])


def test_single_cap_breach_on_realized_is_caught():
    # 0.203 잔존이 단일 cap(0.20) 위반으로 잡혀야 (finding #2).
    realized = {"A069500": 0.203, "A114260": 0.797}
    report = validate_rebalance(realized, universe=_uni(), clusters=[],
                                previous_weights=None, capital=1_000_000,
                                floor_pct=0.0)
    assert not report.passed
    assert any(v.rule == "single_etf_cap" for v in report.hard_violations)


def test_clean_realized_passes():
    realized = {"A069500": 0.15, "A114260": 0.85}
    report = validate_rebalance(realized, universe=_uni(), clusters=[],
                                previous_weights=None, capital=1_000_000,
                                floor_pct=0.0)
    assert report.passed


def test_cash_excluded_from_validation():
    realized = {"A069500": 0.15, "A114260": 0.80, "CASH": 0.05}
    report = validate_rebalance(realized, universe=_uni(), clusters=[],
                                previous_weights=None, capital=1_000_000,
                                floor_pct=0.0)
    assert report.passed     # 현금 제외 후 종목 재정규화 → 위반 없음
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/unit/rebalance/test_validate_rebalance.py -v`
Expected: FAIL — `ImportError: validate_rebalance`

- [ ] **Step 3: 구현** (engine.py에 추가)

> 검증 skill 시그니처는 [mandate_validator.py:185-220](../../../tradingagents/agents/validator/mandate_validator.py)의 호출부와 동일: `validate_universe(wv, universe)`, `validate_concentration(wv, universe)`, `validate_correlation_concentration(wv, clusters)`, `validate_turnover_feasibility(wv, prev_weights, capital, floor_pct)`. 구현 전 각 함수의 정확한 import 경로를 grep으로 확인할 것.

```python
from tradingagents.schemas.portfolio import WeightVector, OptimizationMethod
from tradingagents.schemas.mandate import ValidationReport, Violation
from tradingagents.skills.mandate.universe_check import validate_universe
from tradingagents.skills.mandate.concentration_check import validate_concentration
from tradingagents.skills.mandate.correlation_check import validate_correlation_concentration
from tradingagents.skills.mandate.turnover_check import validate_turnover_feasibility


def validate_rebalance(
    realized: dict[str, float], universe, clusters, previous_weights,
    capital: int, floor_pct: float,
) -> ValidationReport:
    """realized 비중(종목)에 전체 mandate 재검증. CASH 는 제외 후 종목만 재정규화."""
    stock = {t: w for t, w in realized.items() if t != CASH_KEY}
    s = sum(stock.values())
    if s <= 0:
        return ValidationReport(passed=False, violations=[Violation(
            rule="weight_validity", description="no stock weight", severity="hard",
            suggested_fix="check reprice")])
    norm = {t: w / s for t, w in stock.items()}
    wv = WeightVector(method=OptimizationMethod.AUM_WEIGHTED, weights=norm,
                      rationale="rebalance realized")

    violations: list[Violation] = []
    violations += validate_universe(wv, universe).violations
    violations += validate_concentration(wv, universe).violations
    violations += validate_correlation_concentration(wv, clusters).violations
    violations += validate_turnover_feasibility(
        wv, previous_weights, capital, floor_pct=floor_pct).violations
    return ValidationReport(
        passed=not any(v.severity == "hard" for v in violations),
        violations=violations,
    )
```

> ⚠️ 주의: 위 재정규화는 단일 cap 검사를 종목-only 분모로 만든다. **현금이 크면 종목 분모가 작아져 단일 cap 위반이 과장될 수 있다.** monthly 목표는 보통 현금이 작아(잔여만) 문제없지만, 검사 의미를 "MTS 집행 후 실제 ETF 슬리브 내 비중"으로 명시. 위험자산 cap도 동일 분모 — 현금 포함 분모로 보고 싶으면 별도 함수가 필요하나, 본 Plan에서는 종목-only(보수적, 위반 과장 방향)로 통일하고 §12 nuance에 기록.

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/unit/rebalance/test_validate_rebalance.py -v`
Expected: PASS (3 passed). `validate_universe` import 경로가 다르면 grep `def validate_universe`로 교정.

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/rebalance/engine.py tests/unit/rebalance/test_validate_rebalance.py
git commit -m "feat(rebalance): 실현 비중에 전체 mandate 재검증"
```

---

## Task 9: 클러스터 영속화 (portfolio.json)

monthly full run의 `correlation_clusters`를 portfolio.json에 저장해 이후 tier가 재사용(스펙 §6.4, finding #1·#6). [portfolio_manager._build_full_trace_portfolio](../../../tradingagents/agents/managers/portfolio_manager.py:86-121)에 키 추가.

**Files:**
- Modify: `tradingagents/agents/managers/portfolio_manager.py:86-121`
- Test: `tests/unit/rebalance/test_clusters_persist.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/unit/rebalance/test_clusters_persist.py
from tradingagents.agents.managers.portfolio_manager import _build_full_trace_portfolio
from tradingagents.schemas.portfolio import WeightVector, OptimizationMethod


def test_clusters_persisted():
    state = {
        "as_of_date": "2026-06-07", "capital_krw": 1_000_000_000,
        "weight_vector": WeightVector(method=OptimizationMethod.AUM_WEIGHTED,
                                      weights={"A069500": 1.0}, rationale="t"),
        "correlation_clusters": [{"members": ["A069500", "A229200"], "avg_corr": 0.8}],
    }
    out = _build_full_trace_portfolio(state)
    assert out["correlation_clusters"] == [
        {"members": ["A069500", "A229200"], "avg_corr": 0.8}]


def test_clusters_default_empty():
    state = {
        "as_of_date": "2026-06-07", "capital_krw": 1_000_000_000,
        "weight_vector": WeightVector(method=OptimizationMethod.AUM_WEIGHTED,
                                      weights={"A069500": 1.0}, rationale="t"),
    }
    out = _build_full_trace_portfolio(state)
    assert out["correlation_clusters"] == []
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/unit/rebalance/test_clusters_persist.py -v`
Expected: FAIL — KeyError `correlation_clusters`

- [ ] **Step 3: 구현** — `_build_full_trace_portfolio` 반환 dict에 한 줄 추가 (기존 `_serialize_for_json` 재사용):

```python
        # (기존 return dict 안에 추가)
        "correlation_clusters": _serialize_for_json(
            state.get("correlation_clusters", [])
        ),
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/unit/rebalance/test_clusters_persist.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/agents/managers/portfolio_manager.py tests/unit/rebalance/test_clusters_persist.py
git commit -m "feat(rebalance): correlation_clusters portfolio.json 영속화"
```

---

## Task 10: 산출물 — rebalance_plan.csv + rebalance.json

거래계획 CSV(현금 라인 포함)와 full trace JSON(스펙 §8).

**Files:**
- Create: `tradingagents/reports/rebalance_plan.py`
- Test: `tests/unit/rebalance/test_rebalance_outputs.py`

- [ ] **Step 1: 테스트 작성**

```python
# tests/unit/rebalance/test_rebalance_outputs.py
import csv, json
from tradingagents.rebalance.types import TradeLine, RebalanceResult
from tradingagents.reports.rebalance_plan import write_rebalance_plan, write_rebalance_json


def _res():
    r = RebalanceResult(as_of="2026-06-07", tier="monthly")
    r.plan = [TradeLine("A069500", "BUY", 0, 33, 33, 990000)]
    r.cash_residual_krw = 10000
    r.realized_weights = {"A069500": 0.99, "CASH": 0.01}
    r.turnover = 0.5
    return r


def test_csv_has_cash_residual_line(tmp_path):
    out = tmp_path / "2026-06-07(rebalancing)_plan.csv"
    write_rebalance_plan(_res(), {"A069500": {"name": "KODEX200", "category": "국내주식"}}, out)
    text = out.read_text(encoding="utf-8-sig")
    assert "매매구분" in text
    assert "# CASH_RESIDUAL_KRW: 10000" in text
    rows = [r for r in csv.reader(text.splitlines()) if r and not r[0].startswith("#")]
    assert rows[1][5] == "BUY"        # 매매구분 컬럼


def test_json_full_trace(tmp_path):
    out = tmp_path / "2026-06-07(rebalancing).json"
    write_rebalance_json(_res(), out, previous_path="artifacts/2026-06-05")
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["tier"] == "monthly"
    assert d["cash_residual_krw"] == 10000
    assert d["realized_weights"]["CASH"] == 0.01
    assert d["previous_portfolio_path"] == "artifacts/2026-06-05"
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/unit/rebalance/test_rebalance_outputs.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

```python
# tradingagents/reports/rebalance_plan.py
"""리밸런싱 산출물 — (rebalancing)_plan.csv + (rebalancing).json (스펙 §8)."""
import csv
import json
from dataclasses import asdict
from pathlib import Path

from tradingagents.rebalance.types import RebalanceResult


def write_rebalance_plan(result: RebalanceResult, universe_lookup: dict, out_path: Path) -> Path:
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["티커", "ETF명", "자산군", "현재수량", "목표수량",
                    "매매구분", "거래수량", "거래금액(KRW)"])
        for tl in result.plan:
            meta = universe_lookup.get(tl.ticker, {})
            w.writerow([tl.ticker, meta.get("name", ""), meta.get("category", ""),
                        tl.current_qty, tl.target_qty, tl.action,
                        tl.delta_qty, tl.delta_amount_krw])
        f.write(f"# CASH_RESIDUAL_KRW: {result.cash_residual_krw}\n")
        f.write(f"# CASH_WEIGHT: {result.realized_weights.get('CASH', 0.0):.6f}\n")
    return out_path


def write_rebalance_json(result: RebalanceResult, out_path: Path, previous_path: str) -> Path:
    validation = result.validation
    payload = {
        "as_of_date": result.as_of,
        "tier": result.tier,
        "trigger": result.trigger,
        "current_weights": result.current_weights,
        "target_weights": result.target_weights,
        "realized_weights": result.realized_weights,
        "plan": [asdict(tl) for tl in result.plan],
        "turnover": result.turnover,
        "cash_residual_krw": result.cash_residual_krw,
        "skipped_no_trade": result.skipped_no_trade,
        "validation": (validation.model_dump() if hasattr(validation, "model_dump")
                       else validation),
        "previous_portfolio_path": previous_path,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8")
    return out_path
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/unit/rebalance/test_rebalance_outputs.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/reports/rebalance_plan.py tests/unit/rebalance/test_rebalance_outputs.py
git commit -m "feat(rebalance): rebalance_plan.csv·rebalance.json 산출물"
```

---

## Task 11: 사유서 — rebalance_rationale.md (monthly = LLM)

monthly 사유서(스펙 §8.1). monthly는 philosophy 패턴의 LLM 서술. daily/reassess 템플릿은 Plan B에서 추가하므로, 본 Task는 **monthly LLM 경로 + 결정론 fallback**만.

**Files:**
- Create: `tradingagents/reports/rebalance_rationale.py`
- Test: `tests/unit/rebalance/test_rebalance_rationale.py`

- [ ] **Step 1: 테스트 작성** (LLM은 mock)

```python
# tests/unit/rebalance/test_rebalance_rationale.py
from tradingagents.rebalance.types import TradeLine, RebalanceResult
from tradingagents.reports.rebalance_rationale import write_rebalance_rationale


class _FakeLLM:
    def invoke(self, prompt):
        class R: content = "## 리밸런싱 사유\n충분히 긴 monthly 서술 " + "x" * 200
        return R()


def _res(tier):
    r = RebalanceResult(as_of="2026-06-07", tier=tier)
    r.plan = [TradeLine("A069500", "BUY", 0, 33, 33, 990000)]
    r.trigger = {"tier": tier, "fired": ["monthly"]}
    return r


def test_monthly_uses_llm(tmp_path):
    out = tmp_path / "r.md"
    write_rebalance_rationale(_res("monthly"), out, deep_llm=_FakeLLM())
    text = out.read_text(encoding="utf-8")
    assert "리밸런싱 사유" in text
    assert len(text) > 100


def test_no_llm_falls_back_to_template(tmp_path):
    out = tmp_path / "r.md"
    write_rebalance_rationale(_res("monthly"), out, deep_llm=None)
    text = out.read_text(encoding="utf-8")
    assert "A069500" in text          # 결정론 템플릿에 매매 포함
    assert "BUY" in text
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/unit/rebalance/test_rebalance_rationale.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

```python
# tradingagents/reports/rebalance_rationale.py
"""리밸런싱 사유서 (스펙 §8.1). monthly=LLM 서술, fallback=결정론 템플릿."""
from pathlib import Path

from tradingagents.rebalance.types import RebalanceResult

_PROMPT = """당신은 자산배분 매니저입니다. 아래 리밸런싱 결과로 사유서를 한국어로 작성하세요.
포함: ① 왜 지금 리밸런싱했는가(트리거) ② 무엇을 바꿨는가(주요 매매) ③ 왜 그렇게(regime/risk 근거) ④ mandate 준수.
트리거: {trigger}
주요 매매: {trades}
turnover: {turnover:.2%}
실현 비중: {realized}
"""


def _template(result: RebalanceResult) -> str:
    lines = [f"# 리밸런싱 사유서 — {result.as_of} ({result.tier})", "",
             f"**트리거:** {result.trigger}", "",
             f"**turnover:** {result.turnover:.2%}", "",
             "## 매매 내역", "", "| 티커 | 구분 | 거래수량 | 금액 |", "|---|---|---|---|"]
    for tl in result.plan:
        lines.append(f"| {tl.ticker} | {tl.action} | {tl.delta_qty} | {tl.delta_amount_krw:,} |")
    return "\n".join(lines) + "\n"


def write_rebalance_rationale(result: RebalanceResult, out_path: Path, deep_llm=None) -> Path:
    if result.tier == "monthly" and deep_llm is not None:
        trades = "; ".join(f"{tl.ticker} {tl.action} {tl.delta_qty}" for tl in result.plan[:10])
        prompt = _PROMPT.format(trigger=result.trigger, trades=trades,
                                turnover=result.turnover, realized=result.realized_weights)
        try:
            md = deep_llm.invoke(prompt).content
        except Exception:
            md = _template(result)
    else:
        md = _template(result)
    out_path.write_text(md, encoding="utf-8")
    return out_path
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/unit/rebalance/test_rebalance_rationale.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/reports/rebalance_rationale.py tests/unit/rebalance/test_rebalance_rationale.py
git commit -m "feat(rebalance): 사유서(monthly LLM + 결정론 fallback)"
```

---

## Task 12: run_monthly_rebalance — 엔진 오케스트레이션

엔진 + 산출물을 묶어 monthly 리밸런싱 1회를 실행하는 함수. graph.run으로 목표를 얻고(별도 호출자), 직전 보유를 재평가해 거래계획·산출물 생성(스펙 §6.3, §9).

**Files:**
- Modify: `tradingagents/rebalance/engine.py` (오케스트레이터 추가)
- Test: `tests/unit/rebalance/test_run_monthly.py`

- [ ] **Step 1: 테스트 작성** (graph·LLM·가격은 인자/mock 주입으로 격리)

```python
# tests/unit/rebalance/test_run_monthly.py
from pathlib import Path
from datetime import date
from tradingagents.dataflows.universe import Universe, ETFEntry
from tradingagents.rebalance.engine import run_rebalance


def _uni():
    return Universe(version="t", etfs=[
        ETFEntry(ticker="A069500", name="KODEX200", aum_krw=1e12,
                 underlying_index="KOSPI200", bucket="위험", category="국내주식_지수"),
        ETFEntry(ticker="A114260", name="KODEX국고채", aum_krw=1e11,
                 underlying_index="KTB", bucket="안전", category="국내채권_지수"),
    ])


def test_run_rebalance_end_to_end(tmp_path):
    out_dir = tmp_path / "2026-06-07"; out_dir.mkdir()
    res = run_rebalance(
        as_of="2026-06-07", tier="monthly", capital=1_000_000,
        prev_qty={"A069500": 50, "A114260": 0}, prev_cash=0,
        target_weights={"A069500": 0.3, "A114260": 0.7},
        prices={"A069500": 10000.0, "A114260": 10000.0},
        universe=_uni(), clusters=[], previous_weights={"A069500": 1.0},
        dials=dict(no_trade_band=0.005, single_etf_abs_cap=0.19,
                   risk_asset_abs_cap=0.68, turnover_floor_monthly=0.10),
        out_dir=out_dir, previous_path="artifacts/2026-06-05", deep_llm=None,
    )
    assert res.tier == "monthly"
    assert res.validation.passed
    assert (out_dir / "2026-06-07(rebalancing).json").exists()
    assert (out_dir / "2026-06-07(rebalancing)_plan.csv").exists()
    assert (out_dir / "2026-06-07(rebalancing)_rationale.md").exists()
    # 현재 A069500 100% → 목표 30% → SELL 발생
    assert any(tl.ticker == "A069500" and tl.action == "SELL" for tl in res.plan)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/unit/rebalance/test_run_monthly.py -v`
Expected: FAIL — `ImportError: run_rebalance`

- [ ] **Step 3: 구현** (engine.py에 추가)

```python
from pathlib import Path
from tradingagents.rebalance.types import RebalanceResult
from tradingagents.reports.rebalance_plan import write_rebalance_plan, write_rebalance_json
from tradingagents.reports.rebalance_rationale import write_rebalance_rationale


def run_rebalance(
    *, as_of: str, tier: str, capital: int,
    prev_qty: dict[str, int], prev_cash: int,
    target_weights: dict[str, float], prices: dict[str, float],
    universe, clusters, previous_weights, dials: dict,
    out_dir: Path, previous_path: str, deep_llm=None,
) -> RebalanceResult:
    """리밸런싱 1회: 재평가 → 거래계획 → 재검증 → 산출물 3종."""
    is_risk = make_is_risk(universe)
    current = reprice_holdings(prev_qty, prev_cash, prices)

    plan_out = build_rebalance_plan(current, target_weights, capital, prices, is_risk, dials)

    floor = dials.get("turnover_floor_monthly", 0.0) if tier == "monthly" else 0.0
    validation = validate_rebalance(
        plan_out["realized_weights"], universe=universe, clusters=clusters,
        previous_weights=previous_weights, capital=capital, floor_pct=floor)

    res = RebalanceResult(
        as_of=as_of, tier=tier,
        current_weights=current, target_weights=target_weights,
        realized_weights=plan_out["realized_weights"], plan=plan_out["plan"],
        turnover=plan_out["turnover"], cash_residual_krw=plan_out["cash_residual_krw"],
        cash_weight=plan_out["realized_weights"].get(CASH_KEY, 0.0),
        skipped_no_trade=plan_out["skipped_no_trade"],
        trigger={"tier": tier}, validation=validation,
    )

    lookup = {e.ticker: {"name": e.name, "category": e.category} for e in universe.etfs}
    out_dir = Path(out_dir)
    csv_path = out_dir / f"{as_of}(rebalancing)_plan.csv"
    json_path = out_dir / f"{as_of}(rebalancing).json"
    md_path = out_dir / f"{as_of}(rebalancing)_rationale.md"
    write_rebalance_plan(res, lookup, csv_path)
    write_rebalance_json(res, json_path, previous_path)
    write_rebalance_rationale(res, md_path, deep_llm=deep_llm)
    res.paths = {"json": str(json_path), "plan_csv": str(csv_path),
                 "rationale_md": str(md_path)}
    return res
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/unit/rebalance/test_run_monthly.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/rebalance/engine.py tests/unit/rebalance/test_run_monthly.py
git commit -m "feat(rebalance): run_rebalance 오케스트레이터(엔진+산출물)"
```

---

## Task 13: monthly_full 통합 + CLI

`monthly_full.run`이 직전 보유를 로딩하고 graph로 목표를 얻어 `run_rebalance` 호출. graph에 previous 전달(gap #1). CLI는 결과 출력(스펙 §9).

**Files:**
- Modify: `tradingagents/rebalance/monthly_full.py`
- Modify: `cli/commands/portfolio.py:56-62` (monthly 분기)
- Test: `tests/integration/test_monthly_rebalance.py`

- [ ] **Step 1: 통합 테스트 작성** (graph.run·가격·universe를 monkeypatch)

```python
# tests/integration/test_monthly_rebalance.py
from pathlib import Path
import tradingagents.rebalance.monthly_full as mf


def test_monthly_full_produces_rebalance_artifacts(tmp_path, monkeypatch):
    # 직전 산출물 디렉토리
    prev = tmp_path / "2026-05-29"; prev.mkdir()
    (prev / "trade_plan.csv").write_text(
        "티커,수량(주)\nA069500,100\n", encoding="utf-8-sig")
    (prev / "portfolio.json").write_text(
        '{"as_of_date":"2026-05-29","weights":{"A069500":1.0},'
        '"correlation_clusters":[]}', encoding="utf-8")

    out = tmp_path / "2026-06-30"; out.mkdir()

    # graph.run mock — 목표·universe_path·산출 경로 반환
    class _Graph:
        def run(self, as_of_date, capital_krw, previous_portfolio=None):
            assert previous_portfolio is not None     # gap #1: 전달 확인
            return {"final_portfolio_path": str(out / "portfolio.json"),
                    "weight_vector": _WV(), "universe_path": "data/universe.json"}
    monkeypatch.setattr(mf, "TradingAgentsGraph", lambda *a, **k: _Graph())
    monkeypatch.setattr(mf, "fetch_current_prices", lambda d: {"A069500": 10000.0})
    # universe·clusters 로딩 stub은 monthly_full 내부 helper를 patch (구현에 맞춰 조정)

    res = mf.run(month=7, as_of="2026-06-30", previous_path=str(prev))
    assert Path(res.rebalance_paths["plan_csv"]).exists()
```

> ⚠️ 이 통합 테스트는 monthly_full의 내부 의존(universe 로딩·clusters 추출 위치)에 맞춰 monkeypatch 대상을 조정해야 한다. 구현(Step 3) 후 실제 심볼명으로 맞출 것.

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/integration/test_monthly_rebalance.py -v`
Expected: FAIL

- [ ] **Step 3: monthly_full.py 구현**

```python
# tradingagents/rebalance/monthly_full.py
"""Monthly rebalancing — full pipeline + 델타 거래계획 (스펙 §6.3, §9)."""
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.dataflows.universe import load_universe
from tradingagents.rebalance.pricing import fetch_current_prices
from tradingagents.rebalance.holdings import load_prev_holdings
from tradingagents.rebalance.engine import run_rebalance


@dataclass
class MonthlyResult:
    portfolio_path: str
    rebalance_paths: dict
    summary: str
    def __str__(self): return self.summary


def run(month: int, as_of: str | None = None,
        previous_path: str | None = None) -> MonthlyResult:
    target = as_of or date.today().isoformat()
    capital = DEFAULT_CONFIG.get("capital_krw", 1_000_000_000)

    prev_portfolio = None
    prev_weights = None
    if previous_path:
        pj = Path(previous_path) / "portfolio.json"
        if pj.exists():
            prev_portfolio = json.loads(pj.read_text(encoding="utf-8"))
            prev_weights = prev_portfolio.get("weights")

    # 1) full pipeline — 새 목표 (gap #1: previous 전달)
    graph = TradingAgentsGraph()
    final = graph.run(as_of_date=target, capital_krw=capital,
                      previous_portfolio=prev_portfolio)
    target_weights = final["weight_vector"].weights
    universe = load_universe(Path(final["universe_path"]))
    clusters = (prev_portfolio or {}).get("correlation_clusters", [])

    # 2) 직전 보유 재평가 → 델타 거래계획
    prev_qty, prev_cash = ({}, 0)
    if previous_path:
        prev_qty, prev_cash = load_prev_holdings(Path(previous_path))
    prices = fetch_current_prices(date.fromisoformat(target))

    dials = DEFAULT_CONFIG.get("rebalance", {})
    out_dir = Path(DEFAULT_CONFIG.get("artifacts_dir", "./artifacts")) / target
    out_dir.mkdir(parents=True, exist_ok=True)

    res = run_rebalance(
        as_of=target, tier="monthly", capital=capital,
        prev_qty=prev_qty, prev_cash=prev_cash, target_weights=target_weights,
        prices=prices, universe=universe, clusters=clusters,
        previous_weights=prev_weights, dials=dials, out_dir=out_dir,
        previous_path=previous_path or "", deep_llm=None,
    )
    return MonthlyResult(
        portfolio_path=final["final_portfolio_path"],
        rebalance_paths=res.paths,
        summary=(f"Month {month} rebalance: tier=monthly, turnover={res.turnover:.2%}, "
                 f"passed={res.validation.passed} → {res.paths['plan_csv']}"),
    )
```

> `DEFAULT_CONFIG["rebalance"]` dials는 스펙 §5.6 yaml 값을 default_config에 등록해야 한다. 미등록 시 `dials.get(...)`가 KeyError → 이 Task의 사전작업으로 `default_config.py`에 `"rebalance": {"no_trade_band":0.005,"single_etf_abs_cap":0.19,"risk_asset_abs_cap":0.68,"turnover_floor_monthly":0.10}` 추가하고 별도 커밋.

- [ ] **Step 4: CLI 수정** ([cli/commands/portfolio.py:56-62](../../../cli/commands/portfolio.py))

```python
    elif tier == "monthly":
        from tradingagents.rebalance import monthly_full
        if month is None:
            raise click.UsageError("--month required for monthly")
        result = monthly_full.run(month=month, as_of=target, previous_path=previous_path)
        click.echo(result.summary)
        for label, p in result.rebalance_paths.items():
            click.echo(f"  {label}: {p}")
```

- [ ] **Step 5: 테스트 + 회귀 확인**

Run: `pytest tests/integration/test_monthly_rebalance.py tests/unit/rebalance/ -v`
Expected: PASS (전체)

- [ ] **Step 6: 커밋**

```bash
git add tradingagents/rebalance/monthly_full.py cli/commands/portfolio.py tradingagents/default_config.py tests/integration/test_monthly_rebalance.py
git commit -m "feat(rebalance): monthly_full 엔진 통합 + previous 전달(gap#1) + CLI"
```

---

## 최종 검증

- [ ] **전체 단위 테스트**

Run: `pytest tests/unit/rebalance/ -v`
Expected: 전부 PASS

- [ ] **회귀 — 기존 파이프라인 미손상**

Run: `pytest tests/ -m 'not slow and not eval' -q`
Expected: 기존 테스트 통과(특히 portfolio_manager·mandate 관련)

- [ ] **수동 스모크 (선택, 실 API 필요)**

Run: `gaps rebalance monthly --month 7 --date 2026-06-30 --from artifacts/2026-05-29`
Expected: `artifacts/2026-06-30/2026-06-30(rebalancing){.json,_plan.csv,_rationale.md}` 생성, summary에 turnover·passed 출력

---

## Plan A 자체 검토 노트

- **스펙 커버리지**: §4.1(types)=T1 · §7.1(reprice/pricing)=T2,T4 · §5.2 위험분류=T5 · §7.2 델타/band/qty/현금/turnover=T6,T7 · §7.2 step5 재검증=T8 · §6.4 클러스터 영속화=T9 · §8 산출물=T10,T11 · §6.3·§9 monthly/CLI/gap#1=T12,T13. **Plan B/C 범위**(daily 라우터·reassess·GitHub Actions·알림)는 본 Plan 제외 — 명시됨.
- **미해결 의존(구현 중 확인)**: ① `validate_universe` import 경로(T8) ② universe.json 카테고리 문자열이 `kr_equity`/`kr_bond`로 매핑되는지(T5) ③ `default_config`에 `rebalance` dials 등록(T13) ④ T13 통합테스트 monkeypatch 심볼.
- **알려진 nuance**: T8 재검증이 현금 제외 후 종목-only 분모 → 현금 클 때 단일/위험 cap 위반이 과장 방향(보수적). monthly는 현금 작아 무방. 현금 포함 분모 검사가 필요하면 후속.
