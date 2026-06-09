# Black-Litterman Allocator 전환 — 설계 문서

- 날짜: 2026-06-09
- 브랜치: `feat/bl-allocator` (main 기반)
- 상태: 설계 승인됨 (구현 대기)
- 범위: Stage 3(trader_allocator) Step A 비중 결정을 공분산 기반 Black-Litterman으로 전환

---

## 1. 배경 / 문제

현행 Step A는 `regime baseline → scenario/risk_tilt modifier → effective_band → LLM tilt(텍스트) → project_to_band` 구조다. adversarial 평가에서 다음 결함이 확인되었다.

- **공분산 부재**: baseline·modifier·tilt 전부 14버킷을 독립적으로 다룬다. vol_haircut만 개별 변동성을 보고 버킷 간 상관은 무시 → 상관 급등(위기) 국면을 구조적으로 못 본다.
- **기대수익 부재**: forward-looking 신호가 비중에 정량적으로 안 들어간다(LLM 텍스트로만 간접).
- **modifier 하드코딩**: RISK_TILT_AMOUNT/CREDIT/FX 델타가 검증 안 된 v1 시드. regime-invariant.
- **telephone game**: 정량 지표 → analyst summary → bull/bear → thesis → tilt 로 4중 텍스트 압축되어, BL이 요구하는 자산별 상대 크기 정보가 증발.
- **single point of failure**: baseline 56개(14×4)가 검증 안 된 손 prior인데 모든 것이 그 위에 선다.

## 2. 목표

> Stage 3 Step A를 **"prior = regime baseline + Σ(reverse-opt) / view = LLM(Idzorek) + fx·credit 결정론 view"**의 Black-Litterman으로 전환한다. 단 **검증되지 않은 prior(baseline) 위에 view를 얹기 전에, 결정론 골격을 backtest로 먼저 검증**한다.

핵심 원칙(앞선 논의 결론):
- alpha 정량 모델은 안 씀 → LLM view가 유일한 방향성 소스(정성 alpha).
- prior = regime baseline (시장 cap weight 아님 — mandate 충돌·데이터·regime 폐기 회피).
- 공분산은 LLM 뒤의 결정론 레이어 — LLM은 view만, 전파·위험조정은 BL이.
- LLM은 라벨/방향 판단만, 숫자화·캘리브레이션은 코드가(conviction 死신호 교훈).

## 3. 확정 결정사항 (16)

| # | 항목 | 결정 |
|---|---|---|
| 1 | risk_tilt redesign | **BL로 완전 피벗** — 커밋된 scenario/risk_tilt modifier 폐기 (working tree 변경은 `stash@{0}` 보존) |
| 2 | 브랜치 | `feat/bl-allocator` (main 기반, 생성 완료) |
| 3 | 문서 범위 | 전체 BL 전환 |
| 4 | fx/credit | **고확신 결정론 view로 BL 주입** |
| 5 | Σ 입력 | 버킷 내 ETF **AUM 가중 합성** 수익률 → 14×14 Σ |
| 6 | view 생성 주체 | **trader Step A** (trader_allocator 내) |
| 7 | vol_haircut | **제거** (Σ가 위험 처리) |
| 8 | MV 최적화 | **pypfopt BlackLittermanModel** |
| 9 | backtest 데이터 | **기초지수 장기 백필 15-20년** |
| 10 | 벤치마크 | 60/40 · risk parity · 단일 고정 baseline · 1/N **(4종 전부)** |
| 11 | turnover 하한 충돌 | **미달분을 고확신 view 자산에 우선 배분** |
| 12 | regime 선택 | **argmax 유지** (블렌딩은 별도 개선) |
| 13 | view 형식 | **weight tilt + confidence → Idzorek** |
| 14 | confidence | **전 view 동일 고정**(초기) → isotonic 보정(추후) |
| 15 | backtest view | **prior only (view 제외)** — 결정론 100% 재현 |
| 16 | BL fallback | **regime baseline 그대로** |

### 3.1 검토 후 추가 확정 (2026-06-09 adversarial 리뷰, 라운드 A/B)

| # | 항목 | 결정 | 근거 |
|---|---|---|---|
| 17 | **Σ·Q 시간 스케일** | **일별 Σ를 ×252 연율화, view magnitude를 연간 기대수익 delta로 통일** | 실측: 일별 Σ(분산~1e-4) + 연간 view(±0.04) → BL이 b3를 83% 폭주. 스케일 불일치는 view가 prior를 수십 배 압도 |
| 18 | **MV 목적함수** | **`max_quadratic_utility(risk_aversion=δ)`** (max_sharpe 아님) | 실측: max_sharpe는 view 없을 때 baseline 복원 실패(a1_cash 0.05→0.075). max_quadratic_utility는 정확 복원 → reverse-opt 항등(§8)·fallback(§3-16) 전제 보존 |
| 19 | **비중 제약 위치** | **EfficientFrontier `weight_bounds=(hard_min, hard_max)`로 최적화 단계 직접 부과** | 무제약 후 사후 클램프는 BL이 b3=0.83을 내도 band가 잘라 BL을 형해화. 제약을 옵티마이저에 넣어 일관되게 풀이 |
| 20 | **게이트 임계** | gate1: `regime_baseline` Sharpe가 4벤치 중 ≥3 초과 AND (paired_t p<0.10 또는 Cohen's d>0.2) AND MDD 열위 아님 / gate2: 버킷별 `max\|Δw\|>3%p`인 버킷 ≥2개면 "노이즈 초과" | "의미 있는 우위"·"노이즈 초과"의 임계 미정 시 구현자 임의 판정 → 게이트 무력화 방지 |
| 21 | **PIT(point-in-time)** | gate1 regime 분류에 **PIT 강제** — `as_of_date`별 published 데이터만, USREC(NBER 사후개정)→실시간 대용(Sahm rule / CFNAI-MA3<−0.7) | look-ahead(NBER 6~18개월 사후개정, CPI 개정)로 분류하면 baseline 우위 구조적 과대평가 → 게이트 무결성 훼손 |
| 22 | **거래비용** | gate1을 **net-of-cost** 판정, 버킷 편도 **10bps** 가정 | regime_baseline(매월 재배분, 고turnover) vs 벤치마크(정적, turnover≈0) → gross 비교는 고turnover 전략에 구조적 유리 |

### 3.2 보류 — 구현 시 결정 (장단점 §12.1·§12.2)

| 항목 | 보류 사유 |
|---|---|
| **proxy 정비** | gate1 proxy가 6버킷으로 붕괴(중복/방향오류). 신규 데이터 소스 추가 비용 vs gate1 신뢰성의 트레이드오프 → 문서의 장단점(§12.1) 검토 후 구현 시 결정 |
| **regime 분류기** | gate1 검증 대상(결정론 2×2)이 production(LLM 분류기)과 불일치. 검증 의미·중복 제거 트레이드오프 → §12.2 검토 후 구현 시 결정 |

## 4. 아키텍처 (전 → 후)

```
[현행]  regime → baseline → modifier(risk/fx/credit) → eff_band → LLM tilt(텍스트) → project_to_band → 종목 → cap
[BL후]  regime → baseline(prior) ─┐
        버킷 수익률 → Σ ──────────┼→ Π=δΣw → BL posterior → MV opt → 14버킷 비중 → project_to_band(mandate) → 종목 → cap
        Stage1지표 → 집계테이블 → LLM view(weight tilt+conf) → Idzorek(Q,Ω) ┘
        fx/credit regime → 고확신 결정론 view ┘
```

종목 선정(candidate_selector) · 종목 내 배분(within_bucket) · cap repair · 리밸런싱 엔진은 **전부 그대로 재사용**. BL은 14버킷 *목표 비중*만 새로 만든다.

## 5. 컴포넌트

### 신규 (N1–N5)

| # | 컴포넌트 | 입력 → 출력 | 재활용 |
|---|---|---|---|
| N1 | 14버킷 수익률 → Σ (`skills/portfolio/bucket_cov.py`) | 종목 returns → 버킷 AUM 가중 합성 → `compute_robust_cov` | `fetch_returns_matrix`, `compute_robust_cov` |
| N2 | 신호 집계 (`skills/portfolio/signal_aggregation.py`) | Stage1 지표 → 14버킷×카테고리 z 테이블 | Stage1 percentile/zscore 산출물 |
| N3 | LLM view agent (M1 내) | 집계 테이블 + 정성 컨텍스트 → 버킷별 (방향+크기+confidence) | trader Step A LLM |
| N4 | BL 결합 (`skills/portfolio/bl_engine.py`) | Π=δΣw + (LLM view + fx/credit view) → posterior → MV opt | `pypfopt.BlackLittermanModel`, `bl_views` Ω·τ |
| N5 | 입력 변화 트리거 (`rebalance/`) | regime/Σ/지표 유의 변화 → BL 재계산 | 기존 `rebalance/triggers.py` |
| B0 | regime baseline backtest (`scripts/backtest_baseline.py`) | 15-20년 backfill → 결정론 골격 성과 vs 벤치마크 | `fetch_asset_returns_monthly_extended`, `backtest/statistics.py`, `forward_perf` |

### 수정 (M1–M4)

| # | 파일 | 변경 |
|---|---|---|
| M1 | `agents/trader/trader_allocator.py` | Step A 코어를 `baseline+Σ→Π→BL→MV opt`로 교체. LLM view 생성·Idzorek·attribution |
| M2 | `schemas/portfolio.py` `BucketTilt` | sparse 스칼라 tilt → 버킷별 (방향+크기+confidence) 벡터 |
| M3 | `schemas/research.py` `ResearchThesis` | `risk_tilt` 폐기/강등 |
| M4 | `agents/researchers/research_cluster.py` | bull/bear/thesis → 정성 보조+리포팅 강등, 비중 critical path에서 분리 |

### 폐기

- `scenario_anchor.py`: `SCENARIO_MODIFIER`/`apply_scenario_modifier`/`apply_macro_modifiers`/`RISK_TILT_AMOUNT`/`CREDIT_MODIFIER`/`FX_MODIFIER`/`_risk_tilt_delta` (단 `hard_band`/`effective_band`/`project_to_band`/`QUADRANT_BASELINE`는 유지)
- `vol_haircut.py`: 전체 제거 (M1에서 호출 제거)
- `bl_views.py`의 `SCENARIO_BUCKET_RULEBOOK`/`SCENARIO_BL_TILT` (8버킷 legacy). ⚠️ **정정**: `generate_bl_views`는 `absolute_views`(Q)와 `view_confidences` 리스트만 만들 뿐 `BlackLittermanModel(omega="idzorek")` 호출이나 Ω 행렬 구성을 **하지 않는다**(레포 grep: `omega=`/`BlackLittermanModel(` 호출 0건). 따라서 "Ω 변환 로직 이식"은 불가 — **Task 2.2에서 omega=idzorek 배선을 신규 작성**한다. 재사용 가능한 건 `view_confidences` 산출 패턴뿐

### 유지 (재활용)

`cov_estimator.py`, `hard_band`/`project_to_band`, `candidate_selector.py`, `within_bucket.py`, `repair`(category/risk), `rebalance/`·`monitor/` 엔진 전체, `backtest/`(statistics·forward_perf·data) 인프라.

## 6. 데이터 / API 사실 (조사 확인)

### 데이터 파이프라인
```python
# 종목 일별 수익률 (date × ticker)
fetch_returns_matrix(tickers: list[str], start: date, end: date, cache_path: str|None=None) -> pd.DataFrame
# 강건 공분산 (N×N PSD)
compute_robust_cov(returns: pd.DataFrame, *, method="qis", breakdown_out=None) -> pd.DataFrame
# backtest용 장기 자산군 월간 수익률 (1970-2024)
fetch_asset_returns_monthly_extended(start: date, end: date) -> pd.DataFrame
#   columns: [gl_equity, kr_equity, bond_nominal, bond_tips, fx_commodity, cash]
fetch_macro_quarterly_extended(start, end) -> pd.DataFrame  # [cpi_yoy, recession, credit_spread_bps, ...]
# universe
load_universe(path: Path) -> Universe   # ETFEntry(ticker, aum_krw, gaps_bucket, sub_category, underlying_index, listed_since, ...)
```

### pypfopt 1.6.0 (설치 확인)
```python
from pypfopt import BlackLittermanModel, EfficientFrontier, risk_models, objective_functions

# Σ는 연율화(×252) — view delta(연간)와 스케일 통일 (결정 #17)
cov_annual = cov_daily * 252
pi = delta * cov_annual.dot(w_baseline)        # Π = δΣw, 연율 스케일 (delta=δ=2.5)

bl = BlackLittermanModel(
    cov_annual,                     # 14×14 연율 Σ (DataFrame, index=bucket)
    pi=pi,                          # 직접 계산한 prior (시장 cap 아님)
    absolute_views=abs_views,       # {bucket: pi[b] + view_delta}; Q·P 자동 도출 (Q/P 직접 전달 안 함)
    omega="idzorek", view_confidences=conf_list,   # Idzorek Ω (신규 배선, Task 2.2)
    tau=0.05, risk_aversion=2.5,
)
posterior_mu = bl.bl_returns()      # pd.Series (연율)

ef = EfficientFrontier(posterior_mu, cov_annual,
                       weight_bounds=bounds)   # bucket별 (hard_min,hard_max) 직접 부과 (결정 #19)
ef.max_quadratic_utility(risk_aversion=2.5)    # max_sharpe 아님 — baseline 복원 보장 (결정 #18)
weights = ef.clean_weights()        # dict[bucket, weight]
```
주의:
- `absolute_views`(dict)를 주면 pypfopt가 **Q·P를 자동 도출**한다. Q/P를 직접 전달하지 않는다(plan Task 2.2와 통일).
- `omega="idzorek"` + `view_confidences`로 Ω를 계산하는 배선은 bl_views에 없어 **신규 작성**(§5 정정).
- `max_quadratic_utility`는 view 없으면 prior(=baseline) 비중을 복원 → reverse-opt 항등(§8) 성립. `max_sharpe`는 복원 실패(실측).

### 그래프 / 스키마
- 노드 흐름: `research_debate → allocator → validator → portfolio_manager`. allocator 노드명 `"allocator"`, `create_trader_allocator(step_a_llm)`.
- ⚠️ **정정**: `bl_views.generate_bl_views`는 **호출처 0 (dead code)**. `force_method`는 dead code가 **아님** — `trading_graph.py`·`agent_states.py`에서 state로 실제 전파되나 `trader_allocator`가 소비하지 않을 뿐(allocator는 항상 `{"method":"aum_weighted"}` 반환). BL 분기 신규 구현 + method_choice 갱신 필요.
- `validator`는 `weight_vector`만 검증. `portfolio_manager`가 portfolio.json/trade_plan.csv/philosophy.md 생성.
- 스키마: `BucketTarget(weights, rationale)`, `WeightVector(method, weights, rationale, expected_volatility, expected_sharpe)`, `OptimizationMethod.BLACK_LITTERMAN` 존재.
- backtest 진입: `TradingAgentsGraph.run(as_of_date, capital_krw, previous_portfolio)`, `scripts/run_backtest.py` 패턴. 성과: `backtest/statistics.py`(drawdown·sharpe·paired_t), `forward_perf.score_forward_performance`.

## 7. weight tilt → BL view 변환 (N4 핵심)

LLM은 버킷별 `(direction ∈ {+,−,0}, magnitude ∈ {strong, moderate, weak}, confidence)`를 낸다. 변환:
- **Q (view return, 연간 스케일)**: magnitude → 고정 **연간** return delta. `strong=±0.04, moderate=±0.02, weak=±0.01` (v1 시드, prior 대비 절대 view). 연율 Σ·Π(결정 #17)와 스케일 일치. direction 부호 적용.
- **P (picking matrix)**: 절대 view면 각 view 1행에 해당 버킷 1. (상대 view 미사용 — 단순화)
- **Ω**: `omega="idzorek"` + `view_confidences`. confidence는 §3-14에 따라 초기 전부 동일(예 0.5).
- **fx/credit 결정론 view**: 같은 (Q, confidence) 형식으로 추가. confidence는 LLM view보다 높게(정량 신호라, 예 0.8). 예: `usd_risk_off → {a4_safe_fx: +0.03, b1_kr_equity: −0.03}`, `credit tight → {b9: −0.02, a3: +0.02}`.

## 8. Π (prior) 계산

```
Π = δ · Σ_annual · w_baseline   # δ=2.5, Σ_annual = Σ_daily×252, w_baseline = QUADRANT_BASELINE[argmax quadrant]
```
view가 없으면 BL posterior = Π → **`max_quadratic_utility(δ)`** opt → baseline **정확 복원**(reverse-opt 항등, 결정 #18). 그래서 prior weight = "view 없을 때 머무는 곳" = regime baseline. (max_sharpe는 이 항등이 깨짐 — 실측.)

## 9. STOP 게이트 (구현 순서의 핵심)

| 게이트 | 정량 조건 (결정 #20) | 통과 못 하면 |
|---|---|---|
| **게이트 1** (Phase 1 후) | `regime_baseline`의 **net-of-cost(10bps)** Sharpe가 4벤치(60/40·risk parity·단일 baseline·1/N) 중 **≥3개 초과** AND (`paired_t p<0.10` 또는 `Cohen's d>0.2`) AND **MDD가 4벤치 대비 열위 아님** | regime 골격 재고 — BL view 구현 중단 |
| **게이트 2** (Phase 2 후) | BL(고정 view) vs 현행 14버킷 비중에서 **버킷별 `\|Δw\|>3%p`인 버킷이 ≥2개** | BL 과잉설계 — view 구현 재고 |

게이트는 **LLM 없이** 측정한다(결정 #15). LLM view(Phase 3)는 두 게이트 통과 후에만. gate1은 **PIT 강제 + net-of-cost**로 측정(결정 #21·#22, §11.1·§11.2).

## 10. 리밸런싱

- BL = target 생성. 리밸런싱 엔진(`rebalance/`)은 그대로 재사용.
- **두 시간축**: BL target 재계산 = monthly(또는 입력 변화 트리거 N5), drift 감시 = daily(target 고정).
- `turnover_floor_monthly=0.10`(하한) vs BL no-trade 충돌 → 하한 미달분을 **고확신 view 자산에 우선 배분**(§3-11).
- target shift(view/Σ 변화)와 가격 drift를 섞지 말 것 — target은 한 주기 고정.

## 11. 14버킷 backtest 매핑 (B0 상세)

`fetch_asset_returns_monthly_extended`는 6자산군(gl_equity·kr_equity·bond_nominal·bond_tips·fx_commodity·cash). 14버킷 backtest는 **14버킷 → 대표 지수 proxy** 매핑으로 장기 시계열 구성(기초지수 백필, §3-9). 매핑표는 plan Task 1.1에서 확정. **proxy 품질 이슈는 §12.1 보류 결정 참조.**

### 11.1 PIT (point-in-time) 강제 (결정 #21)

gate1 regime 분류는 **각 `as_of_date`에 publish된 데이터만** 사용한다.
- `fetch_macro_quarterly_extended`에 `as_of_date` 파라미터를 추가해 내부 `fetch_fred_series(..., as_of_date=...)`로 publication lag 적용.
- **USREC(NBER 침체 더미)는 사용 금지** — 6~18개월 사후개정이라 look-ahead. 실시간 대용으로 **Sahm rule** 또는 **CFNAI-MA3 < −0.7**로 침체 판정.
- CPI는 개정되므로 published vintage 사용.
- look-ahead로 분류하면 baseline 우위가 구조적으로 과대평가되어 gate1이 부당하게 쉽게 통과한다.

### 11.2 거래비용 (결정 #22)

gate1 판정은 **net-of-cost**. `run_strategy_backtest`가 반환하는 turnover에 **버킷 편도 10bps**를 곱해 월수익에서 차감한 뒤 Sharpe/MDD 산출. regime_baseline(매월 재배분)과 정적 벤치마크(turnover≈0)를 공정 비교한다.

## 12. 보류 결정 — 장단점 분석 (구현 시 확정)

### 12.1 proxy 정비 (gate1 14버킷 proxy 붕괴)

**문제**: Task 1.1 v1 proxy가 14→6버킷으로 붕괴. a2·a3 둘 다 `us_10y`(완전상관, Σ near-singular), a4·b4 둘 다 `usdcnh`(안전통화↔중국주식 방향 반대), a5·b8 둘 다 `iron_ore`(금↔경기원자재 동인 반대), b6→Russell2000(소형주=고베타로 "방어"의 정반대).

| 옵션 | 장점 | 단점 |
|---|---|---|
| **A. 선결 교정** (a5→GLD/금선물, a4→DXY/JPY, a2→KR국채 ECOS, b6→SPLV류 저변동/배당) | Σ rank 회복, regime별 quadrant 차별화(특히 침체 방어버킷) 보존, **gate1 신뢰성 확보** | 신규 데이터 소스 4종 추가(EQUITY_INDEX_TICKERS 보강 + ECOS KR국채 백필) — 작업·일정 증가 |
| **B. 핵심만 보강** (gold·KR국채만) | 최악 왜곡(a5/b8 동인반대, a2/a3 완전상관) 완화, 작업 적음 | a4/b4(usdcnh 공유)·b6(소형주) 잔존 → 부분 왜곡 |
| **C. 현행 유지 + 격하** | 즉시 실행 | gate1이 6버킷 붕괴 상태 → STOP/GO **오판 위험, 사실상 gate1 무의미화** |

> **분석 결론(권장 A)**: gate1의 존재 이유가 "검증 안 된 baseline을 거르는 것"인데, proxy가 붕괴하면 게이트 자체가 신뢰 불가. 게이트를 둘 거라면 A가 정합적. 단 일정 압박 시 B로 최악만 막고 한계 명시도 차선. C는 게이트를 형식화하므로 비권장.

### 12.2 regime 분류기 (gate1 검증 대상 vs production 불일치)

**문제**: gate1 backtest는 결정론 2×2(`recession×cpi>3%`)를 쓰나 production live는 LLM 분류기(`classify_regime`, CFNAI multi-factor). 즉 gate1은 production이 안 쓰는 분류기를 검증. archive는 5개(2022~2026)뿐이라 전 구간 사실상 결정론. 기존 `classify.py::_cycle`/`assign_cycle`과도 중복.

| 옵션 | 장점 | 단점 |
|---|---|---|
| **A. 결정론 2×2 + 한계명시 + `classify.py::_cycle` 재사용** | 단순, **100% backtestable**, 중복 제거 | production LLM 분류기 성과 미보장(historical 분류 일치율 미검증) |
| **B. LLM 근사 + 일치율** | production에 근접, 일치율로 괴리 정량화 | 결정론 근사 작성 부담, 일치율 측정 추가 작업 |
| **C. LLM 분류기 실제 실행** | production 정확 검증 | 15-20년×월간 LLM 호출 — **비용 막대 + backtestability 파괴** |

> **분석 결론(권장 A)**: gate1의 목적은 *"regime baseline(prior)이 벤치마크를 이기는가"* 이지 *"분류기가 정확한가"* 가 아니다. baseline 골격 검증엔 결정론 분류로 충분하고 backtestable. 분류기 정확도는 별도 트랙으로 분리. 단 "live LLM 분류기와 다르다"는 한계를 게이트 통과 해석에 명시.

## 13. 비범위 / 리스크 / 마이그레이션

**비범위**: regime 확률 블렌딩(argmax 유지), confidence isotonic 보정(초기 고정), regime classifier 자체 재설계, daily 경로 category 점검.

**리스크**:
- backtestability: LLM이 critical path → 게이트는 LLM 제외 결정론 골격으로 측정(우회).
- regime 표본 부족: 4분면 × 제한 사이클 → backtest는 *검증*용, baseline *튜닝* 금지(과적합).
- LLM view 死신호: confidence/view가 한 값 쏠림 감시(conviction 전례).
- Σ 비정상성: 위기 상관 점프 → EWMA 등 반응성 확보 검토.

**마이그레이션**: 구 artifacts의 dominant_scenario/conviction/risk_tilt는 deserialize 시 무시(extra=ignore). 백테스트 산출물 재생성.
