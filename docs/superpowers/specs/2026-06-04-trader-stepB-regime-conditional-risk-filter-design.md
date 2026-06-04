# Step B 레짐 조건부 risk-filter 선정 설계

**작성일:** 2026-06-04
**상태:** 설계 확정 (구현 대기)
**관련:** `2026-06-04-trader-stepB-deterministic-factor-selection-design.md` (Step B v1 — 대표성/AUM 선정)

---

## 1. 배경 — 문제

2026-05-29 E2E 결과물(`artifacts/2026-05-29/trade_plan.csv`)에 대한 리뷰에서, **AUM 단일 기준의 기계적 선정**이 만든 리스크-비일관성 3가지가 드러났다:

1. **듀레이션 역행 (가장 큰 문제):** `a3_us_rates` 버킷에 30년·10년·단기 채권이 한 풀에 섞여 있고, 선정은 AUM 1등을 뽑는다. growth_inflation(금리 상승 위험) 레짐인데 AUM 1등이 `ACE 미국30년국채(H)`(18,200억) — **구조적으로 가장 긴 듀레이션**이 뽑혀, "듀레이션을 제한한다"는 thesis와 정면충돌.
2. **환헤지 전략 부재 / 비효율:** USD/KRW 약세(원화 약세, 달러 강세) 국면에서 안전자산은 UH(환노출)여야 위기 시 USD 강세의 방어 효과를 유지한다. 그러나 선정은 헤지(H)/비헤지(UH)를 구분하지 않아 `30년국채(H)`처럼 헤지물이 뽑혔다.

> **유가 비중 과대(별건):** WTI 9.09%는 선정이 아니라 **Step A 앵커 baseline**(growth_inflation의 b8=0.09) + LLM이 전쟁 뉴스에도 하향 tilt를 안 한 결과다. 본 설계 범위 밖(Step A). 또한 universe에 UH 원유가 없어 선정으로는 손댈 수 없다.

### 근본 원인
Step B는 변동성 제거를 위해 **의도적으로 뉴스/레짐에 무감각**(대표성·AUM만)하게 설계되었다. 이는 "어느 브로드 국내주식 ETF냐"처럼 **대체 가능한** 선택엔 옳지만, 버킷 내 운반체가 **리스크 특성(듀레이션·환헤지)이 다른** 경우엔 AUM이 잘못된 타이브레이크가 된다 — AUM 1등이 곧 최장 듀레이션·임의 헤지로 귀결.

### 설계 철학 (재확인)
듀레이션·환헤지는 **수익 베팅(alpha)이 아니라 리스크 특성**이다. 레짐에 따라 이를 조건화하는 것은 *리스크 일관성 강제*("인플레인데 30년 들지 마라")이지 수익 추종이 아니다. **이산 레짐 → 이산 페널티**이므로, 이전에 적대 리뷰로 폐기한 연속 alpha-score의 변동성 문제를 재유입하지 않는다.

---

## 2. 범위

**In scope (Step B 선정 로직만):**
- `a2_kr_rates`, `a3_us_rates` 채권 버킷의 **듀레이션 인지 선정** (인플레 레짐 → 단기 선호).
- `a3_us_rates`, `a5_gold_infl` 안전 헤지자산의 **환헤지 인지 선정** (USD 강세 신호 → UH 선호).

**Out of scope:**
- 유가/commodity 비중(Step A 앵커·LLM tilt).
- 해외주식(b2/b3/b5)·크레딧(b9)의 환헤지 — 주식 FX는 수익 베팅에 가까워 Step A 영역으로 남김(확장 항목).
- 버킷 구조 재설계.

---

## 3. 컴포넌트 — 순수 함수 (신규, `candidate_selector.py`)

### 3.1 `duration_tier(name: str) -> int`
ETF `name`에서 듀레이션 tier를 파싱한다. `0`=초단기 … `3`=장기. (값이 클수록 인플레 레짐에서 페널티가 크다.)

```python
def duration_tier(name: str) -> int:
    m = re.search(r"(\d+)\s*년", name)
    if m:
        y = int(m.group(1))
        return 3 if y >= 20 else 2 if y >= 7 else 1   # ≥20y 장기 / 7~19y 중기 / 1~6y 단기
    n = name
    if any(k in n for k in ("CD", "KOFR", "머니마켓", "MMF", "SOFR", "초단기", "통안")):
        return 0
    if "중장기" in n or "중기" in n or "종합" in n:   # 중장기/종합은 장기 토큰보다 먼저
        return 2
    if any(k in n for k in ("장기", "스트립", "초장기")):
        return 3
    if "단기" in n:
        return 1
    return 2   # 기본 중기
```

검증 케이스:
| name | tier |
|---|---|
| 미국30년국채액티브(H) | 3 |
| 미국채10년선물 | 2 |
| 국고채3년 | 1 |
| CD금리액티브(합성) | 0 |
| 종합채권(AA-이상)액티브 | 2 |
| 미국장기우량회사채 | 3 |
| 미국단기회사채(AAA~A) | 1 |
| 중장기국채 | 2 |

### 3.2 `is_hedged(name: str) -> bool`
KR ETF 명명 관례: 환헤지물은 `(H)`/`(합성 H)`로 끝나고, UH(환노출)는 무표기·`(합성)`·`(UH)`로 끝난다.

```python
def is_hedged(name: str) -> bool:
    n = name.strip()
    if n.endswith("(UH)"):       # 환노출 명시 표기 — 먼저 배제 ("H)"로 끝나 오탐되지 않게)
        return False
    return n.endswith("H)")      # (H) / (합성 H) / 엔화노출(H) → 헤지
```

**검증(현 universe.json 실측):** `(UH)` 표기 종목 **0건**, `endswith("H)")` 매칭 **33건 전부 진짜 헤지물**(오탐 0). UH 종목은 무표기("ACE 미국30년국채액티브", "TIGER 미국채10년선물")·`(합성)`("…산업재(합성)")로 끝나 정확히 False. → 현 데이터에선 `(UH)` 가드가 발동하지 않는다.

> **`(UH)` 가드 근거(방어적):** `(UH)`는 한국 ETF 시장의 실재 표기다. 향후 universe refresh가 `(UH)` 종목을 들이면 `endswith("H)")` 단독은 그걸 *silent*하게 헤지로 오분류 → 필터가 정반대로 작동. 1줄 가드로 방어.
> **Known nuance:** `엔화노출(H)`(엔 헤지) 변종은 USD-UH도 plain-H도 아니지만 v1은 "기준통화 노출 제거됨"으로 보아 헤지(True). 빈도 낮음. 확장 시 세분화.

### 3.3 `regime_selection_prefs(quadrant, scenario) -> tuple[bool, bool]`
```python
def regime_selection_prefs(quadrant: str | None, scenario: str | None) -> tuple[bool, bool]:
    prefer_short    = quadrant in {"growth_inflation", "recession_inflation"}
    prefer_unhedged = prefer_short or scenario in {"kr_stress", "global_credit"}
    return prefer_short, prefer_unhedged
```
근거: 인플레 quadrant → Fed 매파 → USD 강세 → 단기·UH 선호. stress/credit 시나리오 → dollar smile → UH 선호.

> `quadrant in {...}`로 명시 집합 비교 — `"inflation" in quadrant`는 `"disinflation"`도 매칭하는 substring 버그라 금지.

---

## 4. 정렬 키 (핵심 변경)

```python
_DURATION_BUCKETS = {"a2_kr_rates", "a3_us_rates"}
_HEDGE_BUCKETS    = {"a3_us_rates", "a5_gold_infl"}
```

`select_representative_candidates` 내부 `_rank`의 정렬 키를 교체:

```python
prefer_short, prefer_unhedged = regime_selection_prefs(quadrant, dominant_scenario)

def _dur_pen(t: str) -> int:
    if bucket_key not in _DURATION_BUCKETS or not prefer_short:
        return 0
    return duration_tier(name.get(t, ""))           # 0..3

def _hedge_pen(t: str) -> int:
    if bucket_key not in _HEDGE_BUCKETS or not prefer_unhedged:
        return 0
    return 1 if is_hedged(name.get(t, "")) else 0    # 0/1

def _rank(ts: list[str]) -> list[str]:
    return sorted(ts, key=lambda t: (_dur_pen(t), _hedge_pen(t), -aum.get(t, 0.0), t))
```

- **듀레이션 1차 / 헤지 2차** — 인플레에서 듀레이션이 더 큰 리스크.
- 그 외 로직(core 우선 → index-dedup → `N = min(n_floor, distinct)`)은 **무변경**. forced-fill 분기도 AUM 순 그대로(feasibility 전용).
- **순수 재정렬** — 풀을 절대 비우지 않음, infeasible 경로 없음. 대안 없는 버킷(유가: H뿐)은 자동 no-op.

### 실효과 (a3_us_rates, growth_inflation — 실 universe 종목명)
| ticker | name (실제) | dur_pen | hedge_pen | AUM(억) | 결과 |
|---|---|---|---|---|---|
| A453850 | ACE 미국30년국채액티브(H) | 3 | 1 | 18200 | 후순위로 밀림 |
| A476760 | ACE 미국30년국채액티브 | 3 | 0 | 3171 | 후순위 |
| A305080 | TIGER 미국채10년선물 | 2 | 0 | 2446 | **1등 → 선정** |

n_floor=1(비중 ~8%)이므로 단일 픽이 `30년국채(H)` → `미국채10년`(UH, 무표기)로 전환. 듀레이션·헤지 동시 해결.

> **Lexicographic 속성(인지·수용):** 듀레이션 tier 차이는 아무리 작아도(예: 2 vs 1) 헤지 페널티를 전부 덮는다 — "단기-헤지물"이 "중기-환노출물"을 항상 이긴다. 가중합(`2·dur + 1·hedge`)으로 바꾸면 조절 가능하나 연속 점수의 변동성 문제를 재유입하므로, lexicographic을 의도적으로 유지하고 이 트레이드오프를 수용한다.

---

## 5. 데이터 흐름 — 시그니처 변경

`select_representative_candidates`에 3개 인자 추가 — **전부 안전한 기본값**으로 backward-compat 유지(기존 테스트·호출 무수정 통과, regime 필터는 no-op):
```python
def select_representative_candidates(
    *, bucket_key, eligible, aum, sub_category, underlying_index,
    bucket_weight, capital_krw,
    name: dict[str, str] | None = None,        # 신규 — ticker→ETF명 (None→{}, 듀레이션·헤지 파싱)
    quadrant: str | None = None,               # 신규 — macro_report.regime.quadrant (None→prefs=(F,F))
    dominant_scenario: str | None = None,      # 신규 — research_decision.dominant_scenario
    trace=None,
) -> list[str]:
    name = name or {}
    ...
```
> 기본값이 곧 graceful path: `name`/`quadrant` 미전달 시 `_dur_pen`/`_hedge_pen`이 모두 0 → 기존 AUM 정렬과 동일. 따라서 기존 `tests/unit/skills/portfolio/test_candidate_selector.py`는 **무수정 통과**(회귀 보장).

`trader_allocator.py` 노드: 이미 가진 `quadrant`·`scenario` 변수에 더해
```python
name_of = {e.ticker: e.name for e in uni.etfs}
```
를 만들어 호출 시 `name=name_of, quadrant=quadrant, dominant_scenario=scenario` 전달. **신규 데이터 fetch 없음** (전부 universe.json `name` 파싱).

---

## 6. 에러 처리

| 상황 | 동작 |
|---|---|
| `name` 누락 | `""` → tier=2(중기)/UH 취급. graceful. |
| unknown quadrant | 노드가 이미 `growth_disinflation`로 기본 → prefs=(False,False) → no-op. |
| 대안 없는 버킷(유가 H뿐) | 재정렬해도 동일 → no-op. |
| 풀 부족 | 순수 재정렬이라 infeasible 유발 안 함. 기존 forced-fill/InfeasibleBucket 경로 무변경. |

---

## 7. 테스트

**단위 (`tests/skills/portfolio/`):**
- `duration_tier` — §3.1 표 8케이스.
- `is_hedged` — `(H)`/`(합성 H)`/`(합성)`/무표기/금현물.
- `regime_selection_prefs` — growth_inflation→(T,T); growth_disinflation→(F,F); recession_disinflation→(F,F); (growth_disinflation, kr_stress)→(F,T); (growth_disinflation, global_credit)→(F,T).

**통합 (`select_representative_candidates`):**
- **a3 + growth_inflation:** 픽이 `30년(H)`→`10년(UH)`로 전환 (헤드라인).
- **a3 + growth_disinflation:** prefs=(F,F) → AUM 기본 → `30년(H)` 유지 (**회귀 보장 — 레짐이 요구 안 하면 무변경**).
- **a2 + growth_inflation:** 단기 국고채가 종합채권보다 우선.
- **b8(유가 H뿐):** WTI(H) 그대로 (no-op).
- **b1_kr_equity(국내, 헤지 버킷 아님):** 무영향.
- **a5 + growth_inflation:** 금현물(UH)이 골드선물(H)보다 우선.

**E2E:** 2026-05-29 재실행 → a3 픽=10년 UH 확인, validation 통과·risk≤70% 유지.

**회귀:** 기존 `tests/unit/skills/portfolio/test_candidate_selector.py`는 신규 인자 기본값(no-op)으로 **무수정 통과**해야 한다. 신규 단위·통합 테스트는 같은 파일에 추가하거나 `test_candidate_selector_regime.py`로 분리한다(구현 계획에서 확정).

---

## 8. 확장 항목 (v1 제외, 백테스트/후속 검토)
1. **disinflation 장기 선호:** recession_disinflation에서 장기 듀레이션을 *능동적으로* 선호(침체 헤지). v1은 중립.
2. **해외주식 환헤지(b2/b3/b5):** 주식 FX는 수익 베팅 성격 → Step A 또는 별도 확장.
3. **유가 비중 뉴스 반응성:** Step A 앵커/LLM tilt 영역 (별건).
4. **엔화노출(H) 세분화:** v1은 헤지 취급.
5. **TIPS/inflation_linked 듀레이션:** a5 듀레이션 필터 미적용(v1).
