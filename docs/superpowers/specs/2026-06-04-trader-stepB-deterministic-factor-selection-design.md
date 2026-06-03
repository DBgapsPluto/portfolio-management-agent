# Trader Step B — Deterministic Quant Factor Selection

- **작성일:** 2026-06-04
- **대상:** Stage 3 trader/allocator 구현자
- **선행 의존:** [Step A Phase 1 — quadrant anchor](./2026-06-03-trader-stepA-quadrant-anchor-design.md), [Step A Phase 2 — scenario modifier](./2026-06-03-trader-stepA-scenario-modifier-design.md) (둘 다 구현·검증 완료)
- **대상 파일:** `tradingagents/skills/portfolio/factor_scorer.py`, `tradingagents/agents/trader/trader_allocator.py`

---

## 0. TL;DR

Step A(버킷 비중)는 결정론적 앵커로 안정화됐다. 그러나 **Step B(버킷 내 종목 선정)는 아직 LLM**(`structured_b`/`_step_b_prompt`)이라 입력 문구에 흔들리고 기준이 불안정하다. 본 spec은 Step B를 **결정론적 퀀트 팩터 선정**으로 교체한다.

핵심 통찰: Step A가 이미 *자산군 베팅(버킷 비중)*을 정했으므로, Step B의 일은 **그 노출을 실현할 최적 ETF(운반체) 선택** — 새 알파 베팅이 아니다. 따라서 **구현품질(impl) 우선 + 레짐조건부 가격팩터(alpha) 틸트**로 점수화한다.

**사용자 확정 결정:**
1. **방식:** 결정론적 팩터 스코어링 (LLM Step B 제거). 기존 검증된 `factor_scorer.py` 엔진 재활용.
2. **팩터:** **가격/유동성 팩터**(모멘텀·저변동성·Sharpe·log AUM)만. PER/PBR/ROE 등 **펀더멘털 제외** — 같은 버킷 ETF는 동일 지수를 추종해 펀더멘털이 거의 동일 → 종목 구분 불가, 게다가 ETF 펀더멘털 데이터 부재.
3. **합성:** `composite = 0.6·rank(impl) + 0.4·rank(alpha)` — 구현품질 우선(옛 0.85 알파-과중을 뒤집음).
4. **impl 입력:** **log(AUM)만** (신규 fetch 0; factor_panel에 이미 존재). 거래량·괴리율·추적오차는 향후 옵션.
5. **선정:** composite ↓ → underlying_index dedup → adaptive N. **ENB-greedy 미사용**(옛 ENB minimum_torsion 버그가 포트폴리오 파괴 — 메모리 기록).

**검증:** 단위(점수·dedup·N·결정성·fallback) PASS, 입력 민감도 재측정(Step A 게이트 유지/개선 — Step B 결정론화로 종목선정 변동 제거), regime×scenario E2E spot-check.

---

## 1. 현재 상태 (ground-truth)

`trader_allocator.py:199-228` Step B:
```python
ss = invoke_structured_obj(structured_b, _step_b_prompt(state, bucket_weights, pool),
                           StockSelection(selections={}), "TraderStepB")
# LLM 선정 → need=ceil(w/0.20) 미달 시 AUM top-N 보충 → InfeasibleBucket fallback
```
→ LLM이 버킷별 ticker 선정. 입력(thesis 등)에 따라 변동 + 기준 불투명.

**이미 존재하나 고아 상태인 자산** (`skills/portfolio/factor_scorer.py`):
- `score_candidates(panels, quadrant, confidence, *, risk_adjusted, trend_quant, extended, etf_states)` — 레짐조건부 mom/lowvol/qual/size 합성 + timing overlay. **rank_percentile 정규화.**
- `compute_impl_score(panels, *, volume_per_aum, premium_discount, tracking_error)` — 입력 None 시 `0.33·z(log_aum)`로 graceful.
- `compute_adaptive_n_max(*, n_positive_alpha, bucket_weight, capital_krw)` — `min(n_positive_alpha, ⌊w/0.025⌋, ⌊w·capital/5e7⌋, 8)`.
- `REGIME_FACTOR_WEIGHTS` (quadrant별), `blend_regime_weights`, `_rank_normalize`.
- *(미사용 예정: `select_by_enb_greedy` — ENB 버그 이력. `select_diverse` — returns 필요.)*

이 중 `compute_factor_panel`만 Stage 1 technical_analyst가 호출, 나머지 스코어링부는 **candidate_selector(삭제됨) 제거 후 고아**.

**가용 데이터** (`technical_report`, allocator stage prerequisite — 이미 state에 흐름):
- `factor_panel: dict[str, FactorPanel]` (skip-1m mom 3/6/12m, realized_vol_60d, sharpe_60d, log_aum)
- `risk_adjusted: dict[str, RiskAdjustedMetrics]` (sortino/calmar/max_drawdown/skew)
- `trend_quantification: dict[str, TrendQuantification]` (trend_strength_score, momentum_acceleration)
- `extended_indicators: dict[str, ExtendedIndicatorPanel]` (RSI/MACD divergence, bb_percent_b, mfi, stoch)
- `individual_etf_states: dict[str, TrendState]`

→ **alpha_score 입력 전부 technical_report에 존재. 신규 fetch 0.**

**버킷 풀 크기** (의미: 큰 버킷은 스코어링 signal↑): b1_kr_equity 34, b2_dm_core 24, b3_global_tech 24, b5 18, a2 17, b6 17, a1 14, a3 13, b4 10 / 작은: a4 3, b9 3, b8 4, a5 5, b7 2. 레버리지·인버스 0개(universe 정제됨).

---

## 2. 설계

### 2.1. 신규 함수 `select_bucket_candidates` (`factor_scorer.py`)

버킷 하나의 후보 풀을 받아 선정 ticker 리스트를 반환. 순수 함수.

```python
STEP_B_IMPL_WEIGHT: float = 0.6
STEP_B_ALPHA_WEIGHT: float = 0.4


def select_bucket_candidates(
    *,
    eligible: list[str],                       # 이 버킷 풀의 ticker (universe gaps_bucket 기준)
    panels: dict[str, FactorPanel],            # technical_report.factor_panel (subset 가능)
    quadrant: str | None,
    confidence: float,
    bucket_weight: float,
    capital_krw: float,
    index_of: dict[str, str],                  # ticker → underlying_index (dedup용)
    risk_adjusted: dict | None = None,
    trend_quant: dict | None = None,
    extended: dict | None = None,
    etf_states: dict | None = None,
    trace: dict | None = None,
) -> list[str]:
    """버킷 내 결정론 선정. composite = 0.6·rank(impl) + 0.4·rank(alpha)
    → underlying_index dedup → adaptive N (ceil(w/0.20) 하한).

    panels 없는 ticker(가격이력 부족 등)는 alpha 중립; impl은 log_aum 필요 →
    panel 없으면 eligible 에서 제외하되, 전부 없으면 AUM top-N fallback(호출부).
    """
```

**알고리즘:**
1. **scored 풀** = `[t for t in eligible if t in panels]` (impl은 log_aum 필수). 비어있으면 `[]` 반환 → 호출부가 AUM top-N fallback.
2. **alpha** = `score_candidates(panels_scored, quadrant, confidence, risk_adjusted=…, trend_quant=…, extended=…, etf_states=…)` → ticker→score.
3. **impl** = `compute_impl_score(panels_scored)` (volume/premium/te=None → `0.33·z(log_aum)`).
4. **composite** = `0.6·_rank_normalize(impl) + 0.4·_rank_normalize(alpha)` (둘 다 [-0.5,0.5]로 정규화 후 가중).
5. **index dedup**: composite 내림차순 walk, 각 `underlying_index`의 **최고 composite 1개만** 채택(나머지 동일 인덱스는 제외).
6. **N**: `N_floor = ceil(bucket_weight / SINGLE_CAP)`; `N_cap = compute_adaptive_n_max(n_positive_alpha=len(dedup_pool), bucket_weight=bucket_weight, capital_krw=capital_krw)`; `N = min(len(dedup_pool), max(N_floor, N_cap))`. (n_positive_alpha 자리에 dedup 풀 크기를 넣어 alpha 부호로 게이팅하지 않음 — impl 우선 선정.)
7. dedup된 composite 상위 N 반환. `trace` 제공 시 composite/contribution 기록.

### 2.2. node 배선 (`trader_allocator.py`)

`bucket_weights` 확정(Step A) 직후 LLM Step B 블록(199-228)을 교체:
```python
        tech = state.get("technical_report")
        fp = getattr(tech, "factor_panel", None) or {}
        ra = getattr(tech, "risk_adjusted", None)
        tq = getattr(tech, "trend_quantification", None)
        ext = getattr(tech, "extended_indicators", None)
        states = getattr(tech, "individual_etf_states", None)
        index_of = {e.ticker: e.underlying_index for e in uni.etfs}
        capital = float(state.get("capital_krw") or 0.0)

        selections: dict[str, list[str]] = {}
        for bkey, w in bucket_weights.items():
            if w <= 0:
                continue
            eligible = [e.ticker for e in pool[bkey]]
            picked = select_bucket_candidates(
                eligible=eligible,
                panels={t: fp[t] for t in eligible if t in fp},
                quadrant=quadrant, confidence=confidence,
                bucket_weight=w, capital_krw=capital, index_of=index_of,
                risk_adjusted=ra, trend_quant=tq, extended=ext, etf_states=states,
            )
            need = max(1, math.ceil(w / SINGLE_CAP - 1e-9))
            if len(picked) < need:                       # panel 부족/빈 풀 → AUM top-N fallback
                extra = [e.ticker for e in sorted(pool[bkey], key=lambda e: -e.aum_krw)
                         if e.ticker not in picked]
                picked = (picked + extra)[:max(need, len(picked))]
            selections[bkey] = picked
```
- `quadrant`/`confidence`는 Step A에서 이미 계산됨(재사용).
- 이후 `aum_weighted_allocation` + `InfeasibleBucket` fallback + risk/출력은 **불변**.
- `structured_b`, `_step_b_prompt`, `StockSelection` import는 **제거**(다른 호출지 grep 확인 후).
- `candidate_set.selection_criteria` 문자열을 `"deterministic factor: 0.6 impl(logAUM) + 0.4 regime-alpha, index-dedup"`로 갱신.

### 2.3. 왜 이 형태인가 (설계 근거)
- **impl 우선(0.6)**: 버킷 내 ETF는 비슷한 노출이므로 모멘텀 차이는 주로 노이즈. 큰 AUM = 대표·유동적 운반체 → log_aum이 대표성까지 대리. 옛 0.85 알파-과중(고점추격)을 교정.
- **alpha 틸트(0.4)**: 동급 운반체 중 레짐에 맞는 리스크조정 우위로 미세 차등(growth_disinflation=모멘텀, recession=저변동성).
- **ENB-greedy 배제**: 옛 minimum_torsion 버그가 ENB 붕괴→포트폴리오 파괴 이력. 대신 underlying_index dedup(견고, returns 불필요).
- **펀더멘털 제외**: §0.2 — 같은 버킷 ETF는 underlying 공유라 PER/PBR이 종목을 못 가름.

---

## 3. 에러 처리 / fallback
- `technical_report` 없음 / `factor_panel` 비어있음 / 버킷에 panel 가진 ticker 0개 → `select_bucket_candidates`가 `[]` → 호출부 **AUM top-N fallback**(현행과 동일, 굶지 않음).
- 가격이력 부족 신규 ETF: panel 부재 → scored 풀에서 제외되나, need 미달 시 AUM 보충으로 포함 가능.
- `aum_weighted_allocation` InfeasibleBucket fallback: 불변(2차 안전망).
- Stage 5 validator(risk≤70%·단일20%): 불변.

---

## 4. 영향 받는 파일

| 파일 | 변경 |
|---|---|
| `tradingagents/skills/portfolio/factor_scorer.py` | **추가** `STEP_B_IMPL_WEIGHT/ALPHA_WEIGHT` + `select_bucket_candidates` (기존 score_candidates/compute_impl_score/compute_adaptive_n_max/_rank_normalize 재활용) |
| `tradingagents/agents/trader/trader_allocator.py` | LLM Step B 블록 → 결정론 선정 루프; `technical_report` 읽기; `structured_b`/`_step_b_prompt`/`StockSelection` import 제거; `candidate_set` 기준 문자열 갱신 |
| `tests/unit/skills/test_portfolio_factor_scorer.py` | `select_bucket_candidates` 단위 테스트 추가 |
| `tests/unit/agents/trader/test_trader_allocator.py` | Step B LLM mock 제거 → 결정론 선정 통합 테스트로 갱신 |

---

## 5. 검증

| 단계 | 검증 | 통과 기준 |
|---|---|---|
| **L0 단위(선정)** | `select_bucket_candidates` | 동일 입력→동일 출력(결정성); composite=0.6·rank(impl)+0.4·rank(alpha); 같은 underlying_index 1개만; N≥ceil(w/0.20) 이고 ≤풀크기; panel 0개→`[]` |
| **L0 단위(틸트 방향)** | alpha 효과 | 두 후보 AUM 동일 시 모멘텀 높은 쪽이 우선; growth_disinflation에서 모멘텀 가중↑ |
| **fallback** | panel 부재 | technical_report 없음 → AUM top-N 동일 결과(굶지 않음) |
| **L0 단위(node)** | 통합 | LLM 없이 node가 14버킷 selection 생성; weight_vector sum=1·단일≤20%; bucket당 ≥ceil(w/0.20)종목 |
| **입력 민감도(재측정)** | Step B 결정론화 효과 | `measure_stepA_input_sensitivity.py` — bucket_target은 Step A라 동일하나, **종목 selection이 thesis 변형에 완전 불변**(Step B가 결정론) 확인 |
| **E2E spot-check** | 실데이터 | E2E 정상·validation pass; 선정 종목이 합리적(대형·유동 대표 ETF + 레짐 틸트) |

---

## 6. 범위 밖 / 향후 옵션 (튜닝)
- **impl 강화**: 거래량/AUM·|괴리율|·tracking_error (etf_metrics fetch) → `compute_impl_score`에 주입. 현재 logAUM-only.
- **sub_category / scenario fit**: dominant_scenario(ai_concentration 등)에 따라 버킷 내 sub_category 가점 — 현재는 logAUM이 대표성 대리하므로 제외, 향후 오버레이.
- **ENB / correlation 다양화**: ENB 버그 수정 후 또는 `select_diverse`(returns 필요)로 상관-aware 선정.
- **펀더멘털 오버레이**: KR 주식 버킷 한정 index PER/PBR/배당 (pykrx) — 인덱스 단위라 버킷 내 차등 약함, 낮은 우선순위.
- `STEP_B_IMPL_WEIGHT/ALPHA_WEIGHT`, `REGIME_FACTOR_WEIGHTS` backtest 튜닝.
