# FX 노출 리포팅 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 최종 포트폴리오의 통화별 FX 노출(USD/JPY/CNY/INR/EUR/KRW/기타)을 결정론적으로 계산해 `portfolio.json`과 `philosophy.md` 리포트에 명시한다. 선정·비중은 무변경(informational only).

**Architecture:** 순수 skill `fx_exposure.py`(`exposure_currency` + `compute_fx_exposure`)를 신설하고, Stage 6 `portfolio_manager`가 universe·weights로 한 번 계산해 portfolio.json 최상위 키 + philosophy state로 주입한다. validator 경로는 미사용(`mandate_validator_attribution`이 state 스키마 누락으로 최종 출력까지 전파되지 않음).

**Tech Stack:** Python 3.13, pytest. 신규 데이터 fetch 없음(전부 universe.json `name`/`category` 파싱).

**Spec:** `docs/superpowers/specs/2026-06-04-fx-exposure-reporting-design.md`

---

## File Structure

- **Create** `tradingagents/skills/mandate/fx_exposure.py` — `exposure_currency(etf)` + `compute_fx_exposure(weights, universe)`.
- **Modify** `tradingagents/reports/philosophy.py` — `_build_state_summary`에 FX 블록 + `PHILOSOPHY_PROMPT` section 3 한 줄.
- **Modify** `tradingagents/agents/managers/portfolio_manager.py` — fx_exposure 계산 + portfolio.json 키 + state 주입.
- **Test** `tests/unit/skills/mandate/test_fx_exposure.py` (신규), `tests/unit/reports/test_philosophy.py` (추가), `tests/integration/test_plan_pipeline_mock.py` (추가).

---

## Task 1: `fx_exposure.py` 순수 함수

**Files:**
- Create: `tradingagents/skills/mandate/fx_exposure.py`
- Test: `tests/unit/skills/mandate/test_fx_exposure.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/skills/mandate/test_fx_exposure.py`:

```python
from types import SimpleNamespace

from tradingagents.dataflows.universe import Universe, ETFEntry
from tradingagents.skills.mandate.fx_exposure import (
    exposure_currency, compute_fx_exposure,
)


def _etf(name, category):
    return SimpleNamespace(name=name, category=category)


def test_exposure_currency_domestic_and_hedged():
    assert exposure_currency(_etf("KODEX 200", "국내주식_지수")) == "KRW"
    assert exposure_currency(_etf("KODEX WTI원유선물(H)", "FX 및 원자재")) == "KRW"
    assert exposure_currency(_etf("TIGER 미국MSCI리츠(합성 H)", "해외주식_섹터")) == "KRW"


def test_exposure_currency_foreign():
    assert exposure_currency(_etf("TIGER 미국S&P500", "해외주식_지수")) == "USD"
    assert exposure_currency(_etf("ACE KRX금현물", "FX 및 원자재")) == "USD"
    assert exposure_currency(_etf("TIGER 일본니케이225", "해외주식_지수")) == "JPY"
    assert exposure_currency(_etf("TIGER 차이나항셍테크", "해외주식_지수")) == "CNY"
    assert exposure_currency(_etf("KODEX 인도Nifty50", "해외주식_지수")) == "INR"
    assert exposure_currency(_etf("ACE 베트남VN30(합성)", "해외주식_지수")) == "기타"


def test_exposure_currency_mmf_split():
    assert exposure_currency(_etf("KODEX CD금리액티브(합성)", "금리연계형/초단기채권")) == "KRW"
    assert exposure_currency(
        _etf("TIGER 미국달러SOFR금리액티브(합성)", "금리연계형/초단기채권")) == "USD"


def _uni():
    rows = [
        ("A069500", "KODEX 200", "국내주식_지수"),
        ("A360750", "TIGER 미국S&P500", "해외주식_지수"),
        ("A241180", "TIGER 일본니케이225", "해외주식_지수"),
        ("A261220", "KODEX WTI원유선물(H)", "FX 및 원자재"),
    ]
    etfs = [ETFEntry(ticker=t, name=n, aum_krw=1.0,
                     underlying_index="i", bucket="위험", category=c)
            for t, n, c in rows]
    return Universe(version="t", etfs=etfs)


def test_compute_fx_exposure_aggregates_by_currency():
    weights = {"A069500": 0.25, "A360750": 0.40, "A241180": 0.10, "A261220": 0.25}
    out = compute_fx_exposure(weights, _uni())
    assert out["USD"] == 0.40
    assert out["JPY"] == 0.10
    assert out["KRW"] == 0.50          # 국내 0.25 + 헤지된 WTI 0.25
    assert abs(sum(out.values()) - 1.0) < 1e-9


def test_compute_fx_exposure_skips_unknown_ticker():
    out = compute_fx_exposure({"A069500": 0.5, "A999999": 0.5}, _uni())
    assert out == {"KRW": 0.5}        # A999999 universe 부재 → 제외
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/skills/mandate/test_fx_exposure.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tradingagents.skills.mandate.fx_exposure'`

- [ ] **Step 3: Implement the module**

Create `tradingagents/skills/mandate/fx_exposure.py`:

```python
"""포트폴리오 통화별 FX 노출 분해 (리포팅 — spec 2026-06-04).

최종 weight를 노출 통화로 집계. 헤지(H)·국내 → KRW, 해외 UH → 본국 통화.
informational only(하드 게이트 아님). Stage 6 portfolio_manager + philosophy 가 사용.
"""
from __future__ import annotations

from tradingagents.skills.portfolio.candidate_selector import is_hedged

_JPY = ("일본", "니케이", "TOPIX", "엔")
_CNY = ("차이나", "중국", "CSI", "항셍", "HSCEI", "과창판", "홍콩")
_INR = ("인도", "Nifty", "니프티")
_EUR = ("유로", "유럽", "스탁스", "Europe")
_OTHER = ("베트남", "신흥국", "이머징", "emerging")


def exposure_currency(etf) -> str:
    """ETF 한 종목의 노출 통화. 헤지·국내 → KRW, 해외 UH → 본국 통화."""
    name = etf.name or ""
    cat = etf.category or ""
    if is_hedged(name):              # 헤지 = 환노출 제거
        return "KRW"
    if cat.startswith("국내"):        # 국내주식/국내채권
        return "KRW"
    if cat == "금리연계형/초단기채권":
        return "USD" if any(k in name for k in ("달러", "USD", "SOFR")) else "KRW"
    if any(k in name for k in _JPY):
        return "JPY"
    if any(k in name for k in _CNY):
        return "CNY"
    if any(k in name for k in _INR):
        return "INR"
    if any(k in name for k in _EUR):
        return "EUR"
    if any(k in name for k in _OTHER):
        return "기타"
    return "USD"   # 해외 default (미국·금·은·원유·원자재·달러)


def compute_fx_exposure(weights: dict[str, float], universe) -> dict[str, float]:
    """최종 weight를 통화별 노출 %로 분해. 합 ≈ Σ(알려진 ticker weight).

    universe 에 없는 ticker 는 건너뜀(합에서 제외).
    """
    meta = {e.ticker: e for e in universe.etfs}
    out: dict[str, float] = {}
    for t, w in weights.items():
        e = meta.get(t)
        if e is None:
            continue
        cur = exposure_currency(e)
        out[cur] = out.get(cur, 0.0) + w
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/skills/mandate/test_fx_exposure.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/mandate/fx_exposure.py tests/unit/skills/mandate/test_fx_exposure.py
git commit -m "feat(fx): 통화별 FX 노출 분해 순수 함수 (exposure_currency/compute_fx_exposure)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: philosophy 리포트에 FX 블록 주입

**Files:**
- Modify: `tradingagents/reports/philosophy.py` (`_build_state_summary` + `PHILOSOPHY_PROMPT`)
- Test: `tests/unit/reports/test_philosophy.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/reports/test_philosophy.py`:

```python
from tradingagents.reports.philosophy import _build_state_summary


def test_build_state_summary_includes_fx_block():
    state = dict(_make_state())
    state["fx_exposure"] = {"USD": 0.55, "KRW": 0.35, "CNY": 0.10}
    summary = _build_state_summary(state)
    assert "FX(환) 노출" in summary
    assert "USD 55.0%" in summary


def test_build_state_summary_fx_absent_graceful():
    summary = _build_state_summary(_make_state())   # fx_exposure 없음
    assert "FX(환) 노출" in summary
    assert "(미산출)" in summary
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/reports/test_philosophy.py -k "fx" -v`
Expected: FAIL — `AssertionError: assert 'FX(환) 노출' in summary`

- [ ] **Step 3: Implement**

In `tradingagents/reports/philosophy.py`, in `_build_state_summary`, locate the final return f-string ending with the Final Portfolio block (`...Rationale: {rationale}\n"`). Just BEFORE the `return (` statement, add:

```python
    fx = state.get("fx_exposure") or {}
    fx_str = (
        ", ".join(f"{c} {v*100:.1f}%"
                  for c, v in sorted(fx.items(), key=lambda kv: -kv[1]))
        if fx else "(미산출)"
    )
```

Then in the returned f-string, append a FX block at the end (after the `Rationale: {rationale}\n` line). Change the tail of the return from:

```python
        "### Final Portfolio\n"
        f"Method: {_resolve_method(state)}\n"
        f"Top 5 weights: "
        f"{sorted(weights.items(), key=lambda x: -x[1])[:5]}\n"
        f"Rationale: {rationale}\n"
    )
```

to:

```python
        "### Final Portfolio\n"
        f"Method: {_resolve_method(state)}\n"
        f"Top 5 weights: "
        f"{sorted(weights.items(), key=lambda x: -x[1])[:5]}\n"
        f"Rationale: {rationale}\n\n"
        "### FX(환) 노출 (통화별)\n"
        f"{fx_str}\n"
    )
```

Then in `PHILOSOPHY_PROMPT`, change the section 3 line from:

```
## 3. 자산군 비중 결정 논리
(≥600 chars — Stage 2 scenario/factor view + 5-bucket target rationale)
```

to:

```
## 3. 자산군 비중 결정 논리
(≥600 chars — Stage 2 scenario/factor view + 5-bucket target rationale + FX(환) 노출 포지션과 그 의도(원화 약세 수혜 / 위기 시 달러 강세 방어) 설명)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/reports/test_philosophy.py -v`
Expected: PASS — 신규 2 + 기존 전부 (FX 블록은 fx_exposure 없을 때 "(미산출)"로 graceful).

- [ ] **Step 5: Commit**

```bash
git add tradingagents/reports/philosophy.py tests/unit/reports/test_philosophy.py
git commit -m "feat(fx): philosophy 리포트에 통화별 FX 노출 블록 + section3 의도 서술

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: portfolio_manager가 FX 노출 계산·주입

**Files:**
- Modify: `tradingagents/agents/managers/portfolio_manager.py`
- Test: `tests/integration/test_plan_pipeline_mock.py`

- [ ] **Step 1: Write the failing test**

In `tests/integration/test_plan_pipeline_mock.py`, in `test_plan_pipeline_produces_artifacts`, after the existing single-cap assertion (the block ending `f"Single ETF cap violated: {portfolio['weights']}"`), add:

```python
    # FX 노출 리포팅 (통화별 분해)
    assert "fx_exposure" in portfolio, "portfolio.json missing fx_exposure"
    assert isinstance(portfolio["fx_exposure"], dict)
    assert sum(portfolio["fx_exposure"].values()) <= 1.0 + 1e-6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts -v`
Expected: FAIL — `AssertionError: portfolio.json missing fx_exposure`

- [ ] **Step 3: Implement**

In `tradingagents/agents/managers/portfolio_manager.py`:

(a) Add the import near the other `tradingagents` imports (after line 21 `from tradingagents.reports.trade_plan import write_trade_plan`):

```python
from tradingagents.skills.mandate.fx_exposure import compute_fx_exposure
```

(b) In `node`, AFTER `universe = load_universe(state["universe_path"])` (currently line 115), add:

```python
        fx_exposure = compute_fx_exposure(weights.weights, universe)
```

(c) AFTER `portfolio = _build_full_trace_portfolio(state)` (currently line 124) and BEFORE `portfolio_path = out_dir / "portfolio.json"`, add:

```python
        portfolio["fx_exposure"] = fx_exposure
```

(d) Just BEFORE `write_philosophy(state, deep_llm, philosophy_path)` (currently line 170), add:

```python
        state["fx_exposure"] = fx_exposure
```

- [ ] **Step 4: Run test + full reports/integration suite (regression)**

Run: `.venv/bin/python -m pytest tests/integration/test_plan_pipeline_mock.py tests/unit/reports/test_philosophy.py tests/unit/skills/mandate/test_fx_exposure.py -v`
Expected: PASS — 신규 + 기존 전부.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/managers/portfolio_manager.py tests/integration/test_plan_pipeline_mock.py
git commit -m "feat(fx): portfolio_manager가 통화별 FX 노출 계산 → portfolio.json + 리포트 주입

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: E2E 검증 (2026-05-29 실데이터)

**Files:** 코드 변경 없음 — 실행 검증만.

- [ ] **Step 1: 전체 관련 스위트 회귀**

Run: `.venv/bin/python -m pytest tests/unit/skills/mandate/test_fx_exposure.py tests/unit/reports/ tests/integration/test_plan_pipeline_mock.py -q`
Expected: PASS.

- [ ] **Step 2: E2E 재실행**

Run: `.venv/bin/python scripts/run_e2e_test.py --as-of 2026-05-29 --capital 1000000000`
Expected: EXIT 0, validation 통과. (실패 시 traceback/사유 그대로 보고하고 중단.)

- [ ] **Step 3: portfolio.json에 fx_exposure 확인**

Run: `.venv/bin/python -c "import json; p=json.load(open('artifacts/2026-05-29/portfolio.json')); fx=p['fx_exposure']; print(sorted(fx.items(), key=lambda x:-x[1])); print('sum=', round(sum(fx.values()),4))"`
Expected: 통화별 dict 출력(USD 최대), sum ≈ 1.0.

- [ ] **Step 4: philosophy.md에 FX 서술 확인**

Run: `grep -nE "FX|환노출|환\(|USD|달러" artifacts/2026-05-29/philosophy.md | head`
Expected: FX/환 노출 포지션 서술 라인 존재.

- [ ] **Step 5: 결과 보고 (코드 변경 없으니 commit 생략)**

통화별 FX 노출 값 + 리포트 서술 포함 여부를 사용자에게 요약 보고.

---

## Self-Review

**1. Spec coverage:**
- §3.1 `exposure_currency`(우선순위 + 통화집합) → Task 1 ✅ / §3.2 `compute_fx_exposure` → Task 1 ✅
- §4 wiring(portfolio_manager 계산, portfolio.json 키, state 주입, philosophy 블록 + prompt) → Task 2(philosophy)·Task 3(portfolio_manager) ✅
- §4 "validator 미사용" 근거 → Task 3가 portfolio_manager에서만 계산(validator 무수정) ✅
- §5 에러 처리(unknown ticker 제외, fx 부재 graceful) → `test_compute_fx_exposure_skips_unknown_ticker`·`test_build_state_summary_fx_absent_graceful` ✅
- §6 테스트(단위·통합·E2E) → Task 1/2/3/4 ✅
- §7 nuances → v1 의도(주석/spec 기록), 구현 불필요 ✅

**2. Placeholder scan:** TBD/TODO 없음. 모든 step에 실제 코드·명령·기대 출력.

**3. Type consistency:** `compute_fx_exposure(weights: dict, universe)` 정의(Task 1) ↔ 호출 `compute_fx_exposure(weights.weights, universe)`(Task 3) 일치. `exposure_currency(etf)` 정의 ↔ 내부 사용 일치. `state["fx_exposure"]` 키(Task 3 주입) ↔ `_build_state_summary` 읽기(Task 2) 일치. portfolio.json `fx_exposure` 키(Task 3) ↔ integration assert(Task 3) 일치.
