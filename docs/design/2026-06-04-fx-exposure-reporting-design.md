# FX 노출 리포팅 설계 (#2)

**작성일:** 2026-06-04
**상태:** 설계 확정 (구현 대기)
**관련 비판:** 심사평 #1 — "USD/KRW 약세를 우려하면서 포트폴리오의 환노출(UH)/환헤지(H) 포지션을 어떻게 통제하는지 리포트에 직접 논리가 없다."
**선행:** `2026-06-04-trader-stepB-regime-conditional-risk-filter-design.md` (Step B 헤지 필터 — 안전자산만)

---

## 1. 배경 — 문제

2026-05-29 결과물 리뷰에서 드러난 사실: 해외 자산 sleeve가 **구조적으로 ~전부 UH(환노출)** 였다.
- 주식 버킷은 AUM가 이미 압도적으로 UH를 선택(b3_global_tech는 헤지 옵션 0개).
- 유일한 헤지 해외 보유분(미국리츠)은 UH 대안이 universe에 없음.

즉 포트폴리오는 **이미 달러(USD)에 크게 롱**이다 — 원화 약세 수혜 + 위기 시 달러 강세 방어를 노린 포지션. 그러나 **이게 의도된 것인지, 그 규모가 얼마인지 리포트에 드러나지 않았다.** 심사평 #1의 본질은 이 *FX 포지션의 가시화·의도 명시*이다.

### 결정 (이전 brainstorm)
- 선정 로직으로는 FX를 통제할 레버가 거의 없다(이미 ~전부 UH, 리츠는 UH 부재). → **선정은 무변경.**
- 대신 **포트폴리오의 통화별 FX 노출을 결정론적으로 계산해 machine-readable 산출물(portfolio.json)과 리포트(philosophy.md)에 명시**한다. 입도: **통화별 전체 분해**.

---

## 2. 범위

**In scope:**
- 순수 함수: 최종 weight를 **통화별 노출 %**로 분해 (USD/JPY/CNY/INR/EUR/KRW/기타).
- `portfolio.json`에 최상위 `fx_exposure` 키로 정확값 기록.
- `philosophy.md` 리포트에 FX 포지션 수치 + 의도 서술 주입.

**Out of scope:**
- 종목 선정·비중 변경 (없음).
- 하드 게이트(FX 한도 검증) — 대회 룰에 FX mandate 없음. **informational only.**
- 정밀 환헤지 비율 계산(통화 peg, 부분헤지 등) — 경제블록 기준 근사.
- validator(mandate_validator) 경로 — 아래 §4 참조(attribution 전파 부재로 미사용).

---

## 3. 컴포넌트 — 순수 함수 (신규 `tradingagents/skills/mandate/fx_exposure.py`)

### 3.1 `exposure_currency(etf) -> str`
ETF 한 종목의 노출 통화. 우선순위:
```python
from tradingagents.skills.portfolio.candidate_selector import is_hedged

_JPY = ("일본", "니케이", "TOPIX", "엔")
_CNY = ("차이나", "중국", "CSI", "항셍", "HSCEI", "과창판", "홍콩")
_INR = ("인도", "Nifty", "니프티")
_EUR = ("유로", "유럽", "스탁스", "Europe")
_OTHER = ("베트남", "신흥국", "이머징", "emerging")


def exposure_currency(etf) -> str:
    name = etf.name or ""
    cat = etf.category or ""
    if is_hedged(name):           # 헤지 = 환노출 제거 → 원화
        return "KRW"
    if cat.startswith("국내"):     # 국내주식/국내채권
        return "KRW"
    if cat == "금리연계형/초단기채권":
        return "USD" if any(k in name for k in ("달러", "USD", "SOFR")) else "KRW"
    # 해외주식/해외채권/FX 및 원자재 — name 지역 키워드
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
```

검증 케이스:
| name | category | 통화 |
|---|---|---|
| KODEX 200 | 국내주식_지수 | KRW |
| TIGER 미국S&P500 | 해외주식_지수 | USD |
| KODEX WTI원유선물(H) | FX 및 원자재 | **KRW** (헤지) |
| ACE KRX금현물 | FX 및 원자재 | USD |
| TIGER 일본니케이225 | 해외주식_지수 | JPY |
| TIGER 차이나항셍테크 | 해외주식_지수 | CNY |
| KODEX 인도Nifty50 | 해외주식_지수 | INR |
| KODEX CD금리액티브(합성) | 금리연계형/초단기채권 | KRW |
| TIGER 미국달러SOFR금리액티브(합성) | 금리연계형/초단기채권 | USD |
| TIGER 미국MSCI리츠(합성 H) | 해외주식_섹터 | **KRW** (헤지) |

### 3.2 `compute_fx_exposure(weights, universe) -> dict[str, float]`
```python
def compute_fx_exposure(weights: dict[str, float], universe) -> dict[str, float]:
    """최종 weight를 통화별 노출 %로 분해. 합 ≈ Σ(알려진 ticker weight) ≈ 1.0.

    universe 에 없는 ticker 는 건너뜀(합에서 제외). 헤지·국내는 KRW 로 집계.
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
출력 예(2026-05-29 근사): `{"USD": ~0.55, "KRW": ~0.35, "CNY": ~0.03, "JPY": ~0.02, ...}`.

---

## 4. 데이터 흐름 — wiring

**계산 위치: Stage 6 `portfolio_manager.node`** (`universe`·`weights`를 이미 보유; line 115/103). validator(mandate_validator)에 넣지 않는 이유: 현재 그래프 state 스키마에 `mandate_validator_attribution` 키가 없어 **Stage 6까지 전파되지 않고 portfolio.json에서 `None`으로 관측됨**(allocation_attribution은 전파됨). 따라서 portfolio_manager에서 직접 계산하는 것이 유일하게 신뢰 가능한 surfacing 경로이며, "machine-readable + 리포트" 의도를 확실히 만족한다.

`tradingagents/agents/managers/portfolio_manager.py` `node`:
```python
from tradingagents.skills.mandate.fx_exposure import compute_fx_exposure
# universe = load_universe(...) 직후:
fx_exposure = compute_fx_exposure(weights.weights, universe)

# (1) portfolio.json — 최상위 키
portfolio = _build_full_trace_portfolio(state)
portfolio["fx_exposure"] = fx_exposure   # ← 신규
portfolio_path.write_text(...)

# (2) philosophy 로 전달
state["fx_exposure"] = fx_exposure        # ← 신규 (write_philosophy 전)
write_philosophy(state, deep_llm, philosophy_path)
```

`tradingagents/reports/philosophy.py`:
- `_build_state_summary(state)`에 FX 블록 추가:
```python
fx = state.get("fx_exposure") or {}
fx_str = (", ".join(f"{c} {v*100:.1f}%"
          for c, v in sorted(fx.items(), key=lambda kv: -kv[1]))
          if fx else "(미산출)")
# 반환 문자열에 삽입:
#   "### FX(환) 노출\n" f"{fx_str}\n\n"
```
- `PHILOSOPHY_PROMPT` section 3(자산군 비중 결정 논리) 설명에 한 줄 추가: `+ FX(환) 노출 포지션과 그 의도(원화 약세 수혜 / 위기 시 달러 강세 방어) 설명`.

> 결과: 리포트가 "USD 노출 ~55%는 원화 약세 수혜와 위기 헤지를 노린 의도적 포지션" 식으로 서술하고, portfolio.json에 정확값이 남는다.

---

## 5. 에러 처리
| 상황 | 동작 |
|---|---|
| name/category 누락(None) | `""` → 국내/헤지 아님 → 해외 default USD. (단 헤지 표기 없으면) — 보수적이지 않으나 빈도 0. |
| weights에 있지만 universe에 없는 ticker | 건너뜀(합에서 제외), 예외 없음. |
| `state["fx_exposure"]` 부재(philosophy 단독 호출) | `(미산출)`로 graceful, 블록은 출력. |
| 순수 함수 | 예외 없음. |

---

## 6. 테스트

**단위 (`tests/unit/skills/mandate/test_fx_exposure.py`):**
- `exposure_currency` — §3.1 표 10케이스.
- `compute_fx_exposure` — 혼합 미니 Universe(국내·미국UH·니케이·항셍·WTI(H)·CD금리) → 통화별 합 + 총합 ≈ Σweight.
- universe에 없는 ticker → 제외 확인.

**통합:**
- `tests/unit/reports/` (또는 기존 philosophy 테스트) — `_build_state_summary`가 `state["fx_exposure"]` 주입 시 `### FX(환) 노출` + 통화 수치 포함.
- `tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts` 확장 — 생성된 `portfolio.json`에 `fx_exposure` 키 존재 + 합 ≈ 1.0.

**E2E:** 2026-05-29 재실행 → portfolio.json에 `fx_exposure` 기록(USD 최대), philosophy.md에 FX 포지션 서술 포함.

---

## 7. Known nuances / 확장 항목
1. **HKD peg:** 항셍/HSCEI(홍콩 상장 중국주식)는 통화가 엄밀히 HKD(USD에 peg)지만, 사용자 가독성 위해 경제블록 기준 **CNY로 라벨**. 정밀 통화로 분리는 확장.
2. **기타 bucket:** 베트남(VND)·신흥국 혼합은 `기타`로 집계.
3. **name 키워드 분류 한계:** "인도네시아" 같은 부분일치 오분류 가능(현 universe 미존재). sub_category 기반 정밀화는 확장.
4. **엔화노출(H):** 헤지로 KRW 집계(USD 기준통화 제거 관점). UH 엔화노출은 `엔` 키워드로 JPY.
5. **validator 하드 게이트:** FX 한도 검증은 대회 룰에 없어 미도입. 룰 신설 시 concentration_check 패턴으로 추가 가능.
