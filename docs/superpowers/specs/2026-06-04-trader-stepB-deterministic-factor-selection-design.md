# Trader Step B — Deterministic Representative-Carrier Selection

- **작성일:** 2026-06-04 (rev2 — 적대 리뷰 반영 전면 개정)
- **대상:** Stage 3 trader/allocator 구현자
- **선행 의존:** [Step A Phase 1 — quadrant anchor](./2026-06-03-trader-stepA-quadrant-anchor-design.md), [Step A Phase 2 — scenario modifier](./2026-06-03-trader-stepA-scenario-modifier-design.md) (구현·검증 완료)
- **대상 파일:** `tradingagents/skills/portfolio/candidate_selector.py` (신규), `tradingagents/agents/trader/trader_allocator.py`

---

## 0. TL;DR

Step A(버킷 비중)는 결정론적 앵커로 안정화됐다. Step B(버킷 내 종목 선정)는 아직 **LLM**(`structured_b`)이라 thesis 문구에 흔들린다. 본 spec은 Step B를 **결정론적 "대표 운반체(carrier) 선정"** 으로 교체한다.

> **rev2 변경 (적대 리뷰 결과):** 초안(rev1)은 `regime-conditional 팩터 alpha 틸트(0.6 impl + 0.4 alpha)`를 썼으나, 6각도 적대 리뷰에서 **MAJOR 3건이 수렴**해 기각됨 — (1) 버킷이 동질적 운반체가 아니라 *이질적 노출 묶음*(b1=KOSPI broad 15 + 방산/조선 테마 19)이라 버킷 내 모멘텀은 진짜 sub-theme alpha다, (2) `_rank_normalize`가 AUM 크기를 버려 0.4 alpha가 실제로 픽을 50~70% 좌우(명시한 "impl 우선"과 정반대), (3) 결국 **Step A가 승인 안 한 unsized sub-theme 베팅을 선정 게이트로** 하게 됨 + AUM-baseline 대비 우월성 증거 0. → **alpha 틸트 제거, 순수 대표성/구현품질 선정으로 단순화.** (alpha 는 backtest A/B 게이트 또는 Step A 로 연기 — §6.)

핵심 통찰: Step A가 *자산군 베팅(버킷 비중)* 을 정했으므로, Step B의 일은 **그 노출을 가장 정확·대표적·유동적으로 실현할 ETF 선택** — 새 알파 베팅이 아니다.

**사용자 확정 결정:**
1. **방식:** 결정론적 **대표 운반체 선정** (LLM Step B 제거). 수익-알파 미주장 → 미검증 베팅 없음.
2. **평가 기준 (우선순위):** ① 대표성(broad/core sub_category) → ② 규모·유동성(AUM) → ③ 중복제거(underlying_index dedup). **모멘텀/퀄리티/펀더멘털 미사용.**
3. **펀더멘털 제외:** 같은 버킷 ETF는 동일 지수 추종 → PER/PBR이 종목을 못 가름. (게다가 ETF 펀더멘털 데이터 부재.)
4. **alpha 연기:** regime-conditional 팩터는 backtest A/B 우월성 입증 후, 또는 Step A sub-theme 틸트로 (이번 범위 밖).

**검증:** 결정론(동일입력→동일선정), 대표성(broad 우선·thematic hijack 차단), **thesis 변형에 선정 완전 불변**, AUM-baseline 대비 대표성 개선 spot-check.

---

## 1. 현재 상태 & 동기

### 1.1. 현 Step B는 LLM
`trader_allocator.py:199-228`: `structured_b`(LLM)가 버킷별 ticker 선정 → AUM top-N 보충/fallback. thesis 문구에 따라 변동, 기준 불투명.

### 1.2. 버킷은 이질적 노출 묶음 (적대 리뷰 핵심 근거)
universe.json (188 ETF) 측정 — 큰 버킷일수록 broad + thematic 혼합:

| 버킷 | #ETF | broad(core) sub_category | thematic sub_category |
|---|---|---|---|
| b1_kr_equity | 34 | index_broad **15** | thematic_other 9, 방산 5, 소비 2, 금융 2, … (19) |
| b2_dm_core | 24 | us_broad 11, us_tech_nasdaq 5 | thematic_other 7, us_sector 1 |
| b3_global_tech | 24 | us_tech_nasdaq 5, ai_theme_global 2 | 반도체 2, ai_robotics 4, 배터리 2, it_software 2, thematic_other 6 |
| b5_other_intl | 18 | japan 4, india 4, europe 2, emerging 2 | thematic_other 6 |
| b6_defensive_equity | 17 | factor_value_dividend 4 | thematic_other 6, us_sector 5, … |
| (동질) b4_china 10, a2 17, a3 13 | | 단일 core sub_category | — |
| (소형) a4 3, a5 5, b7 2, b8 4, b9 3 | | — | tiering 무의미(N≈전량) |

→ 버킷 내 "가장 오른 ETF"를 고르면 **방산 테마가 광범위 KOSPI 운반체를 hijack**하는 식의 *숨은 sub-theme 베팅*이 됨. 그래서 **대표성(broad 우선)** 이 평가의 1차 기준이어야 한다.

### 1.3. factor_scorer 자산 — 전부 미사용
- `score_candidates` / `compute_impl_score` / `REGIME_FACTOR_WEIGHTS` — alpha 연기로 미사용. 고아 유지.
- `compute_adaptive_n_max` — **미사용**(최소-N 채택, §2.1). 같은 버킷 broad ETF는 고상관이라 자본 기반 다양화 이득이 미미 → adaptive-N은 §6로 연기. candidate_selector 는 factor_scorer 에 의존하지 않음.

---

## 2. 설계

### 2.1. 신규 모듈 `candidate_selector.py`

**`CORE_SUBCATEGORIES` (v1 시드, 튜닝 대상)** — 각 버킷의 *대표 노출* sub_category. (`sub_category.py`의 `VALID_SUB_CATEGORIES`와 정합; 그중 broad/core 만 지정.)
```python
CORE_SUBCATEGORIES: dict[str, set[str]] = {
    "a1_cash":              {"mmf_kr"},
    "a2_kr_rates":          {"kr_treasury", "kr_corporate"},
    "a3_us_rates":          {"us_treasury"},
    "a4_safe_fx":           {"usd_fx", "jpy_fx"},
    "a5_gold_infl":         {"gold", "inflation_linked"},
    "b1_kr_equity":         {"index_broad"},
    "b2_dm_core":           {"us_broad", "us_tech_nasdaq"},
    "b3_global_tech":       {"us_tech_nasdaq", "ai_theme_global"},
    "b4_china":             {"china"},
    "b5_other_intl":        {"japan", "india", "europe", "emerging_other"},
    "b6_defensive_equity":  {"factor_value_dividend"},
    "b7_reits":             {"thematic_other"},   # 풀 자체가 thematic_other 2개 → 전부 core
    "b8_cyclical_commodity":{"oil_energy", "agricultural", "materials_energy"},
    "b9_risk_credit":       {"us_high_yield"},
}
```

**유지보수 불변식 (적대 리뷰 #2 — silent failure 방지):** universe에 등장하는 모든 `(bucket, sub_category)` 가 *의도적으로 분류*됐는지 검증하는 테스트를 둔다 — `CORE_SUBCATEGORIES[bucket]` 또는 명시적 `KNOWN_THEMATIC[bucket]` 중 하나에 반드시 속해야 하며, **둘 다에 없는 신규 sub_category가 나타나면 테스트 실패**(새 broad ETF가 thematic으로 조용히 강등되는 것 차단). universe sync 시 사람이 분류를 갱신하도록 강제. (CI 게이트, §5 L0.)

**선정 함수** (순수 함수, 결정론):
```python
def select_representative_candidates(
    *,
    bucket_key: str,
    eligible: list[str],                  # 버킷 풀 ticker (gaps_bucket 매칭)
    aum: dict[str, float],                # ticker → aum_krw
    sub_category: dict[str, str | None],  # ticker → sub_category
    underlying_index: dict[str, str],     # ticker → underlying_index
    bucket_weight: float,
    capital_krw: float,
    trace: dict | None = None,
) -> list[str]:
    """버킷 내 대표 운반체 선정. core 우선 → AUM 내림차순 → underlying_index dedup → top-N.
    core 풀이 N 미달이면 thematic 으로 AUM 순 보충(dedup 유지). 결정성: 동일 입력 → 동일 출력
    (AUM 동률은 ticker 사전순 tie-break).
    """
```

**`_normalize_index(s)` — dedup 키 정규화 (적대 리뷰 #4):** *수익률 계산 변종 접미사만* 제거해 동일 노출을 합친다 — `"코스피 200 TR지수"→"코스피 200"`, `"S&P 500 Total Return Index"→"S&P 500"`, `"NASDAQ-100 Total Return Index"→"NASDAQ-100"`. 제거 토큰: `TR지수/TR/Total Return/Net Total Return/NTR/(TR)/ER/Excess Return` + 공백·대소문자 정규화. **sub-index 명(`"코스피 200 정보기술"`)은 보존** — 다른 노출이라 합치면 안 됨. (실데이터에 `"코스피 200"` vs `"코스피 200 TR지수"`가 분리 존재해 미정규화 시 동일 노출 중복 선정됨.)

**알고리즘:**
1. **tiering**: `core = [t for t in eligible if sub_category[t] in CORE_SUBCATEGORIES[bucket_key]]`. core 비어있으면 `core = eligible`(fallback).
2. **rank**: `core` 를 `(-aum[t], t)` 로 정렬 (AUM 내림차순, 동률은 ticker 오름차순 — 결정성).
3. **dedup**: 위 순서로 walk, `_normalize_index(underlying_index[t])` **첫 등장만** 채택 → `deduped_core`.
4. **N (최소-N)**: `N_floor = ceil(bucket_weight / SINGLE_CAP)`(단일-20% feasibility); **`N = min(N_floor, len(deduped_core))`**. 즉 버킷당 **대표 최소 개수**(보통 1, 비중>20%면 2~3)만 선택 — 자본 기반 적응형 다양화는 안 함(같은 버킷 broad ETF 고상관 → 분산효과 미미, §6 연기). thematic 확장은 아래 forced-fill(feasibility)뿐. `capital_krw` 인자는 §6(hysteresis/adaptive-N) 예약, v1 미사용.
5. **select**: `deduped_core[:N]`.
6. **forced fill — feasibility 한정 (적대 리뷰 #1 "테마 역류" 차단)**: `len(selected) < N_floor` (core distinct 인덱스가 단일-20% 충족에 부족 — 현 universe엔 없으나 방어) 일 때만 thematic 보충. 이때 단순 AUM 순이 아니라 **sub_category 다양성 강제** — thematic을 sub_category별로 묶어 AUM순 round-robin(한 테마 몰림 방지) + `_normalize_index` dedup 유지. (선택적 다양화로는 thematic 진입 불가 — §4에서 N이 core로 상한됨.)
7. `trace` 제공 시 core/thematic·dedup·N 근거 기록.

> AUM = 대표성+유동성 대리(거래량/괴리율은 §6 향후). 모멘텀/퀄리티/regime 가중 **없음**.

### 2.2. node 배선 (`trader_allocator.py`)

`bucket_weights` 확정(Step A) 직후 LLM Step B 블록(199-228)을 교체:
```python
        from tradingagents.skills.portfolio.candidate_selector import (
            select_representative_candidates,
        )
        sub_cat = {e.ticker: e.sub_category for e in uni.etfs}
        idx_of = {e.ticker: e.underlying_index for e in uni.etfs}
        capital = float(state.get("capital_krw") or 0.0)

        selections: dict[str, list[str]] = {}
        for bkey, w in bucket_weights.items():
            if w <= 0:
                continue
            eligible = [e.ticker for e in pool[bkey]]
            selections[bkey] = select_representative_candidates(
                bucket_key=bkey, eligible=eligible,
                aum=aum, sub_category=sub_cat, underlying_index=idx_of,
                bucket_weight=w, capital_krw=capital,
            )
```
- 이후 `aum_weighted_allocation` + `InfeasibleBucket` fallback + risk/출력: **불변.**
- `structured_b`, `_step_b_prompt`, `StockSelection` import: **제거**(grep 확인 후).
- `step_b_llm` 파라미터: `create_trader_allocator(step_a_llm, step_b_llm)` 시그니처에서 제거 (호출부 [trading_graph.py] 갱신).
- `candidate_set.selection_criteria` → `"deterministic carrier: core sub_category + AUM + index-dedup"`.

### 2.3. 설계 근거 (왜 이 형태)
- **대표성 1차**: 버킷=노출 결정. 그 노출의 *broad 대표* 펀드가 운반체. thematic hijack 차단(§1.2).
- **AUM 2차**: 큰 AUM = 유동·대표·추종 양호·상폐 위험 낮음. log 불요(직접 정렬).
- **index-dedup**: 동일 지수(코스피200/TR) 중복 회피.
- **alpha 없음**: 미검증·레이어-오류 sub-theme 베팅 배제(적대 리뷰). 결정론·무손실만.
- **펀더멘털 없음**: §0.3.

---

## 3. 에러 처리 / fallback
- core 풀 비어있음(매칭 sub_category 없음) → `eligible` 전체를 core로 취급.
- core+thematic 합쳐도 N 미달 → 가능한 전부 선정(이후 `aum_weighted_allocation` InfeasibleBucket fallback이 2차 안전망 — 불변).
- `sub_category`/`underlying_index` None/누락 → 해당 ticker는 thematic 취급 / dedup 키 없음(고유 취급). 굶지 않음.
- Stage 5 validator(risk≤70%·단일20%): 불변.

---

## 4. 영향 받는 파일

| 파일 | 변경 |
|---|---|
| `tradingagents/skills/portfolio/candidate_selector.py` | **신규** — `CORE_SUBCATEGORIES`/`KNOWN_THEMATIC` + `_normalize_index` + `select_representative_candidates` (factor_scorer 의존 없음) |
| `tradingagents/agents/trader/trader_allocator.py` | LLM Step B → 결정론 선정 루프; `structured_b`/`_step_b_prompt`/`StockSelection` 제거; `step_b_llm` 파라미터 제거; criteria 문자열 갱신 |
| `tradingagents/graph/trading_graph.py` | `create_trader_allocator` 호출에서 `step_b_llm` 인자 제거 |
| `tests/unit/skills/portfolio/test_candidate_selector.py` | **신규** — 선정 단위 테스트 |
| `tests/unit/agents/trader/test_trader_allocator.py` | Step B LLM mock 제거 → 결정론 선정 통합 테스트 |

---

## 5. 검증

| 단계 | 검증 | 통과 기준 |
|---|---|---|
| **L0 결정성** | `select_representative_candidates` | 동일 입력 → 동일 출력; AUM 동률 ticker 사전순 tie-break |
| **L0 대표성** | core 우선·hijack 차단 | 거대 thematic ETF(높은 AUM)가 있어도 core(broad)가 N 안에서 우선 선정; core가 N 채우면 thematic 미선정 |
| **L0 dedup (#4)** | TR/비-TR 정규화 | `_normalize_index`로 `"코스피 200"`/`"코스피 200 TR지수"`(및 S&P500/NASDAQ TR쌍)가 1개로 dedup; **`"코스피 200 정보기술"`은 별도 유지**(sub-index 보존) |
| **L0 N-cap (#1)** | 다양화는 core 안에서만 | 선택적(자본기반) N이 `len(deduped_core)` 초과 안 함; thematic은 `N_floor>core` 강제 시에만 진입 |
| **L0 forced-fill 다양성 (#1)** | 테마 역류 차단 | core<N_floor 강제보충 시 thematic이 한 sub_category에 몰리지 않고 round-robin |
| **L0 coverage 불변식 (#2)** | silent failure 방지 | universe의 모든 (bucket, sub_category)가 CORE∪KNOWN_THEMATIC에 분류됨; 미분류 신규 sub_category → 테스트 실패 |
| **fallback** | core 부재/풀 부족 | core 매칭 0 → eligible 전체; N_floor 미달 → thematic 보충, 굶지 않음 |
| **node 통합** | 결정론 종목 | LLM 없이 14버킷 selection; weight_vector sum=1·단일≤20%; bucket당 ≥ceil(w/0.20)종목 |
| **thesis 불변** | 입력 민감도 | `measure_stepA_input_sensitivity.py` — thesis 4변형에서 **선정 종목 100% 동일**(Step B가 thesis 무관) |
| **E2E spot-check** | 실데이터 | E2E 정상·validation pass; 선정이 대표 운반체(broad·대형)인지 육안 확인 |

---

## 6. 범위 밖 / 향후 (게이트·튜닝)
- **regime-alpha 틸트 (보류)**: momentum/lowvol/quality 를 다시 넣으려면 **반드시** `run_backtest.py` A/B(factor-composite vs 대표성-only)로 Sharpe/변동성/MDD 우월성을 입증한 뒤에만 — 미검증 default 출시 금지(적대 리뷰 결론). 또는 sized·risk-budget 형태로 **Step A** sub-theme 틸트에 편입.
- **유동성 가드 / impl 강화**: `etf_metrics` fetch(거래량/AUM, |괴리율|, 추적오차)로 대표성 점수 보강 — 특히 stale 저거래 ETF 차단. 현재 AUM 단독.
- **`CORE_SUBCATEGORIES` 튜닝**: v1 시드 → 운영 데이터로 broad/thematic 경계 보정.
- **다양화**: N>1 시 core 내 sub_category 다양화(중복 테마 회피) — 현재 index-dedup만(forced-fill만 다양성 강제).
- **adaptive-N (보류)**: 자본 크기에 따라 버킷당 대표 broad ETF 수를 늘리는 정책(`compute_adaptive_n_max`). v1은 최소-N 채택 — 같은 버킷 broad ETF가 고상관(KOSPI200≈KRX300 ~95%)이라 분산효과가 미미하고 holdings·턴오버만 늘기 때문. 저상관 운반체가 있는 버킷에 한해 backtest로 이득 입증 시 재도입.
- **턴오버 hysteresis (적대 리뷰 #3)**: AUM 2·3위가 근소차(예: ≤5%)면 날마다 픽이 엎치락뒤치락 → 불필요한 교체매매. 향후 `previous_portfolio`(rebalance state) 연동해 **기보유 ETF가 AUM 근소차면 유지**(hysteresis threshold)로 턴오버 억제. v1은 순수 `(-aum,t)` 결정론(턴오버 미고려).
- **underlying_index 전처리 정규화 (적대 리뷰 #4)**: dedup이 `_normalize_index`로 TR/비-TR 1차 방어하나, 데이터 공급자 표기 변동(언어·약어·신규 TR 변종)에 의존. universe sync 파이프라인에서 `underlying_index` 표준화(또는 정규화 토큰 목록 갱신) 보장 권장.
