# 리밸런싱 엔진 설계 (Daily 감시 + Monthly full + 조건부 재진단)

**작성일:** 2026-06-07
**상태:** 설계 확정 (구현 대기)
**버전:** v3 — 주기 구조 재평가 반영. **정기 weekly 제거**(실측: regime quadrant 3주+ 불변 → 주간 tilt 대부분 no-op), daily 감시가 regime 프록시 급변을 감지하면 그때만 **조건부 재진단(reassess)**. (v2의 14-finding 적대적 리뷰 수정 + 잔여현금=현금보유 모두 보존)
**맥락:** 실전 운용 — 대회 기간(2026-06-01 ~ 2026-08-31) 실제 10억 KRW 운용 중, 주기적으로 *현재 보유 → 목표*를 재산출하고 종목별 매수/매도 거래계획을 산출한다.
**선행/관련:** [`tradingagents/rebalance/`](../../../tradingagents/rebalance/), [`turnover_check.py`](../../../tradingagents/skills/mandate/turnover_check.py), [`risk_repair.py`](../../../tradingagents/skills/mandate/risk_repair.py), [`correlation_check.py`](../../../tradingagents/skills/mandate/correlation_check.py), [`sub_category.py`](../../../tradingagents/skills/portfolio/sub_category.py)

> **v3 변경(주기 구조):** ① 정기 weekly tier 제거 — 실측상 regime quadrant가 3주+ 고정([artifacts](../../../artifacts/) 2026-05-15~06-05 전 구간 `growth_inflation`)이라 매주 macro+risk를 돌려도 대부분 no-op이고, binary quadrant 비교 한계 + LLM sampling variance로 불필요 회전 위험. ② 대신 **조건부 재진단(reassess)** — daily 감시가 regime 프록시 급변(수익률곡선 전환·vol regime 전환 등)을 감지할 때만 macro+risk 재실행. ③ monthly full 유지(매크로 발표 월간 주기·회전율 규칙과 일치, 대회 중 3회뿐). ④ 잔여 현금은 현금성 ETF로 sweep하지 않고 **현금 보유**.
>
> **v2 변경(결함 수정, 유지):** gap #1 정정(graph.run previous_portfolio·turnover 이미 구현) · 클러스터 cap 공허통과 차단 · no-trade band cap-위반 잔존 방지 + post-trade 실현비중 전체 validator 재검증 · `bucket_for_etf`/`repair_risk_cap` 정정 · turnover 실현거래액 통일 · 종목교체최소화 · tier ladder · auto-discovery 날짜 등.

---

## 1. 배경 — 문제

이미 [`tradingagents/rebalance/`](../../../tradingagents/rebalance/)에 3-tier 재배분 스캐폴드(daily_triggers / weekly_tilt / monthly_full)와 `gaps rebalance` CLI가 있다. 그러나 **"리밸런싱의 알맹이"인 공통 거래계획 레이어가 비어 있다.** 코드 확인으로 확정된 gap:

| # | gap | 근거 |
|---|---|---|
| 1 | **(정정)** `TradingAgentsGraph.run()`은 **이미 `previous_portfolio`를 받고**, state 주입·`mandate_validator`의 turnover 검증까지 end-to-end 구현돼 있다(2026-05-10). **진짜 남은 gap은 [`monthly_full.run`](../../../tradingagents/rebalance/monthly_full.py)이 받은 `previous_path`를 `graph.run(previous_portfolio=…)`로 전달하지 않는 것 하나뿐.** | [`trading_graph.py`](../../../tradingagents/graph/trading_graph.py), [`agent_states.py`](../../../tradingagents/agents/utils/agent_states.py), [`mandate_validator.py`](../../../tradingagents/agents/validator/mandate_validator.py) |
| 2 | `write_trade_plan`은 **"전량 신규 매수" 가정** — 현재 보유 델타(매도/매수) 계산이 없다. | [`reports/trade_plan.py`](../../../tradingagents/reports/trade_plan.py) |
| 3 | 거래계획 미생성: daily=신호만, weekly=추상 tilt, monthly=새 목표만. | [`daily_triggers.py:165`](../../../tradingagents/rebalance/daily_triggers.py), [`weekly_tilt.py:53-58`](../../../tradingagents/rebalance/weekly_tilt.py) |
| 4 | drift 트리거 `any_etf_weight > 0.18`이 **실보유 아닌 종가 스냅샷** 기반(placeholder). 또 `kospi_return_1d = 0.0`으로 하드코딩돼 **KOSPI 급락 트리거 미작동**. | [`daily_triggers.py:108,111-116`](../../../tradingagents/rebalance/daily_triggers.py) |
| 5 | ✅ `turnover_check`는 **previous_weights 인터페이스가 이미 있다** → 재사용. | [`turnover_check.py:27`](../../../tradingagents/skills/mandate/turnover_check.py) |
| 6 | **(신규)** 상관 클러스터 cap(hard mandate, 0.25)은 `state["correlation_clusters"]`로만 검증되는데 **`technical_analyst`만 생성**한다. 분석가를 안 돌리는 tier(daily/reassess)에서는 빈 리스트 → **공허 통과**. | [`technical_analyst.py:209,383`](../../../tradingagents/agents/analysts/technical_analyst.py), [`correlation_check.py:25`](../../../tradingagents/skills/mandate/correlation_check.py) |

진짜로 없는 것: **(A) 현재 보유 재평가 + 목표 델타 거래계획 공통 엔진**, **(B) 분석가-미실행 tier의 클러스터 cap 검증 입력원**, **(C) monthly_full의 previous 전달**.

---

## 2. 범위

**In scope:**
- 신규 공통 엔진 [`tradingagents/rebalance/engine.py`](../../../tradingagents/rebalance/engine.py) — `reprice_holdings` + `build_rebalance_plan`.
- 트리거 라우터 — **드리프트 + 이벤트 + regime 프록시**를 daily에서 평가, monthly는 캘린더.
- tier별 목표 재산출 (daily/event = 결정론 방어 오버레이, **reassess = 조건부 macro+risk 재진단 tilt**, monthly = full 파이프라인).
- 산출물 3종 — `(rebalancing).json` + `(rebalancing)_plan.csv` + `(rebalancing)_rationale.md`.
- **post-trade 실현 비중**에 대한 **전체 `mandate_validator` 재검증**(integrity + universe + concentration[20%/70%] + **correlation[0.25]** + turnover). 분석가-미실행 tier의 클러스터 입력원 확보.
- 잔여 현금은 **현금 보유**(미투자) — 현금성 ETF sweep 안 함.
- 임계값 전부 yaml 설정화.
- **자동 실행 + 알림**: GitHub Actions cron으로 매 영업일 daily 감시 자동 실행(내 컴퓨터 무관 24/7) + 트리거 발화 시 알림(슬랙) — §13.

**Out of scope:**
- **자동 주문 집행** — 거래계획(CSV)까지. MTS 입력은 운영자 수동(알림 ≠ 집행).
- **백테스트 시뮬레이션** — 실전 운용 전용(후속 스펙).
- **정밀 거래비용 모델** — no-trade band(50bp)로 잡소음만 제거.
- **현금흐름·실체결 오차 반영** — 현재 보유는 직전 산출물 수량 × 현재가 재평가(이상적 보유 가정). 실계좌 CSV override는 후속.

---

## 3. 설계 결정 요약 (brainstorm 확정)

| 항목 | 결정 | 근거 |
|---|---|---|
| 맥락 | 실전 운용 | 현재→목표 거래계획이 핵심 산출물 |
| 주기 구조 | **Daily 감시 + Monthly full + 조건부 재진단** | 실측: regime 주간 불변 → 정기 weekly는 대부분 no-op. 상태 변화 기반이 더 원리적 |
| 트리거 | 드리프트 + 이벤트 + regime 프록시(daily) / 캘린더(monthly) | 충격·이탈·국면변화에 반응, 월간 회전율 규칙 충족 |
| 현재 보유 입력 | 직전 산출물 → 현재가 재평가 | 추가 입력 0, 가격 drift 자동 반영 |
| 거래계획 방식 | tier 차등 재산출 + no-trade band | 비용·turnover 인식, 결정론 중심 재현성 |
| 안전 버퍼 | 단일 0.19 / 위험 0.68 (cap 역산, 고정) | 위반 = 즉시 탈락 → cap 닿기 전 발화 |
| 드리프트 밴드 | 목표 대비 ±0.05 (single_etf_rel_band) | 국내 ETF 저비용 → 중간값, 운영 튜닝 |
| 잔여 현금 | **현금 보유**(미투자) | 사용자 지시 — 현금성 ETF 강제 매수 안 함 |
| mandate 재검증 | **post-trade 실현 비중**에 **전체 validator**(클러스터 포함) | band·rounding 후 실제 보유가 검증 대상 |
| 임계값 관리 | 전부 yaml | 코드 수정 없이 조정 |
| 사유서 깊이 | tier 차등 | monthly 상세 LLM, daily/reassess 간결 |
| 파일명 | `{date}(rebalancing)` 표식 | plan 산출물과 식별 구분 |

---

## 4. 아키텍처 — 공통 엔진 + 데이터 흐름

```
gaps rebalance {daily|monthly} [--date D] [--from 직전 portfolio.json]
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  rebalance/engine.py  (신규 — 공통 레이어)                    │
│                                                               │
│  [1] reprice_holdings(previous_portfolio, as_of)              │
│      직전 보유 수량 × 오늘 종가 → current_weights (+현금)     │
│                                                               │
│  [2] evaluate_triggers(current_weights, target_prev, as_of)   │
│      드리프트 + 이벤트 + regime 프록시(daily) / 캘린더(monthly)│
│         tier == none → 모니터링 리포트만, 거래 0, 종료         │
│                                                               │
│  [3] 목표 재산출 target_weights  (tier별 — §6)                │
│         daily/event : 직전목표 + 결정론 방어 오버레이 (LLM 0)  │
│         reassess    : (프록시 발화 시) macro+risk 재실행 →     │
│                       regime 변화 시 bucket tilt, 아니면 종료  │
│         monthly     : graph.run(previous 주입) full 재최적화   │
│                                                               │
│  [4] build_rebalance_plan(current, target, capital, prices)   │
│         delta = target − current                              │
│         no-trade band (단, cap-방향 버퍼초과 델타는 예외 실행) │
│         정수 qty + 잔여 현금은 현금 보유                       │
│         turnover(실현 거래액) 하한 검사 (monthly ≥10%)        │
│         realized_post 비중에 전체 mandate_validator 재검증     │
│           (클러스터 입력원 확보 — §6.4)                       │
│                                                               │
│  [5] 산출물 3종 (§8)                                          │
└─────────────────────────────────────────────────────────────┘
```

**핵심 원칙:**
- 엔진의 [1][2][4]는 **LLM 0 — 순수 결정론**. LLM은 [3]의 reassess(경량)·monthly(full)에서만.
- 기존 `mandate_validator`·`turnover_check`·`risk_repair`·`sub_category.bucket_for_etf`·`find_correlation_clusters`·옛 `weekly_tilt` 로직(reassess로 재사용)을 **재사용**.
- 직전 산출물은 `--from` 미지정 시 **as_of_date보다 엄격히 이전인** 가장 최근 `portfolio.json` 자동 탐색(같은 날 plan 제외 — §10).

### 4.1 데이터 구조 (신규)
```python
@dataclass
class RebalanceResult:
    as_of: str
    tier: str                       # "daily" | "reassess" | "monthly" | "none"
    trigger: TriggerResult          # 기존 daily_triggers.TriggerResult 확장
    current_weights: dict[str, float]    # 현금 포지션 포함
    target_weights: dict[str, float]
    realized_weights: dict[str, float]   # current + 실행 delta (검증 대상)
    plan: list[TradeLine]
    turnover: float                 # 실현 거래액 기반
    cash_residual_krw: int          # 정수 qty 반올림 잔여 → 현금 보유
    cash_weight: float
    skipped_no_trade: list[str]
    validation: ValidationReport    # 전체 validator (클러스터 포함)
    rationale_md: str
    paths: dict[str, str]

@dataclass
class TradeLine:
    ticker: str
    action: str                     # "BUY" | "SELL" | "HOLD"
    current_qty: int
    target_qty: int
    delta_qty: int
    delta_amount_krw: int
```

---

## 5. 트리거 레이어

### 5.1 캘린더 (monthly만)
| tier | 주기 | 목적 |
|---|---|---|
| monthly | 매월 1회 | full 재최적화 + **월간 회전율 ≥10% 보장**(7월부터 강제) + philosophy |

> 정기 weekly는 제거됐다. 매크로 입력(CPI·CFNAI·KR수출)이 월간 발표 주기이고, regime quadrant가 실측상 주 단위로 안 바뀌므로 월 1회 재진단이 정보 주기와 일치한다. full 1회 ≈ LLM 51회·5~7분이지만 대회 중 3회뿐이라 부담이 작다.

### 5.2 드리프트 (daily — gap #4 수정 포함)
`reprice_holdings()`로 산출한 **실제 current_weights** 기준:

| 조건 | 기본 임계값(yaml) | 발화 tier |
|---|---|---|
| 단일 ETF 절대 비중 | `current > single_etf_abs_cap` (0.19) | drift:rebalance |
| 단일 ETF 목표 대비 이탈 | `\|current − target\| > single_etf_rel_band` (0.05) | drift:rebalance |
| 위험자산 합계 | `current_risk > risk_asset_abs_cap` (0.68) | drift:defensive |

**위험자산 분류(finding #4):** [`skills/portfolio/sub_category.bucket_for_etf(etf)`](../../../tradingagents/skills/portfolio/sub_category.py)는 **ETF 객체**(ticker 아님)를 받는다. 엔진은 universe로 `ticker→ETF` 맵을 만들고 [`concentration_check.RISK_BUCKET_NAMES`](../../../tradingagents/skills/mandate/concentration_check.py) 멤버십으로 집계 — [`trader_allocator.py:230-234`](../../../tradingagents/agents/trader/trader_allocator.py) 패턴.

### 5.3 이벤트 (daily — 기존 [triggers_default.yaml](../../../presets/triggers_default.yaml) 재사용)
VIX>30 / VKOSPI>25 / 수익률곡선 역전 / KOSPI 급락 / vol 정상화. 데이터 소스를 실보유 `current_weights`로 교체하고, **`kospi_return_1d` placeholder(0.0)를 실제 KOSPI 일간수익률 fetch로 교체**(현재 미작동, gap #4).
- 즉각 충격 대응(`emergency_defensive`)은 daily에서 결정론 방어 오버레이로 처리(§6.1).
- **중복 정리(finding #13):** 레거시 `any_etf_weight > 0.18`은 §5.2 `single_etf_abs_cap`(0.19)과 중복 → 제거 또는 `alert`로 강등(§5.5 yaml에 명시).

### 5.4 조건부 재진단 (reassess) — 옛 weekly를 정기→조건부로
정기 주간 실행 대신, **regime 프록시 급변**을 daily가 감지할 때만 macro+risk를 재실행해 국면 변화를 확인한다. 값싼 프록시(daily가 이미 fetch하는 지표)로 "재진단 필요"만 판단 → 발화 시에만 LLM(경량) 사용.

regime 프록시 트리거(yaml `reassess_triggers`):
| 신호 | 조건(예시) | 의미 |
|---|---|---|
| 수익률곡선 국면 전환 | `spread_10y_2y_bps < -50` | 침체 신호 |
| vol regime 전환 | `vix_change_5d > 0.30` 또는 `(vix < 18 AND vix_change_5d < -0.30)` | 위험선호 급변 |
| (확장) 외국인/환율 급변 | USDKRW·외국인 순매도 임계 | KR 국면 변화 |

발화 시 reassess 동작: `macro_quant + market_risk` 재실행 → 직전 regime/systemic과 비교 → **변화 있으면** bucket tilt 목표 재산출(§6.2) → 거래계획. **변화 없으면** no-op(모니터링 기록만, 거래 0).

### 5.5 tier 우선순위 — canonical ladder (finding #10)
같은 날 다중 발화 시 단일 사다리:
```
event:emergency_defensive  >  monthly  >  reassess  >  drift:defensive  >  drift:rebalance  >  event:risk_on  >  alert  >  none
```
- 위험 축소(defensive)는 위험 확대(risk_on)보다 항상 우선.
- 기존 [`daily_triggers.py`](../../../tradingagents/rebalance/daily_triggers.py) 액션 우선순위 dict(`emergency_defensive=2, rebalance=1, risk_on=1, alert=0`)는 이 ladder에 맞춰 `risk_on`을 `rebalance`보다 낮게 재매핑.
- `none`이면 거래 없이 **모니터링 리포트만**.

### 5.6 설정 (신규 yaml 섹션)
```yaml
rebalance:
  drift:
    single_etf_abs_cap: 0.19        # cap 0.20 버퍼 (고정 권장)
    single_etf_rel_band: 0.05       # 목표 대비 ±5%p (drift 발화 — 튜닝 대상)
    risk_asset_abs_cap: 0.68        # cap 0.70 버퍼 (고정 권장)
  no_trade_band: 0.005              # 50bp 미만 델타 거래 생략
  cap_buffer_band_exempt: true      # 버퍼 초과 cap-방향 델타는 band 무시(§7.2)
  turnover_floor_monthly: 0.10      # 월간 회전율 하한 (실현 거래액 기준)
  defensive_target: 0.55            # emergency_defensive 시 위험자산 목표치 (§6.1)
  reassess_tilt_step: 0.05          # reassess bucket tilt 크기 (≠ single_etf_rel_band — finding #14)
  reassess_incumbent_band: 0.10     # 종목 유지: challenger AUM 우위 < 10%면 교체 안 함
  reassess_triggers:                # regime 프록시 (§5.4)
    - name: yield_curve_regime_shift
      condition: "spread_10y_2y_bps < -50"
    - name: vol_regime_shift
      condition: "vix_change_5d > 0.30 OR (vix < 18 AND vix_change_5d < -0.30)"
  legacy_018_trigger: alert         # any_etf_weight>0.18 처리: "remove" | "alert" (finding #13)
```
> **명칭 주의(finding #14):** `single_etf_rel_band`(드리프트 *발화*, per-ETF) ≠ `reassess_tilt_step`(reassess *조정* 크기, per-bucket). 둘 다 0.05지만 의미가 다르고 독립 튜닝.

---

## 6. tier별 목표 재산출 (target_weights 생성)

| tier | 목표 생성 | LLM | 재사용/신규 |
|---|---|---|---|
| **daily/event** | 직전 목표 + **결정론 방어 오버레이** (§6.1) | 0 | `repair_risk_cap`(cap 파라미터화) + 신규 de-risk |
| **reassess** | (프록시 발화 시) macro+risk 재실행 → regime 변화 시 직전 `bucket_target`에서 `reassess_tilt_step` tilt → ETF 변환(**보유 우선** §6.2); 변화 없으면 no-op | 경량 (≈4회) | 옛 `weekly_tilt` 로직 + `within_bucket` + 신규 incumbent-bias |
| **monthly** | `graph.run(previous_portfolio=…)` full 재실행 → 새 목표 | 전체 (≈51회) | 전체 파이프라인 |

### 6.1 daily/event 방어 오버레이 (finding #5 정정)
`repair_risk_cap`은 **risk_sum > cap일 때만** 작동(cap 이하면 no-op, [`risk_repair.py:34-36`](../../../tradingagents/skills/mandate/risk_repair.py)). emergency_defensive는 cap *이하*에서도 위험을 더 낮춰야 하므로:
- `emergency_defensive`: `repair_risk_cap(weights, is_risk, cap=defensive_target(0.55))`로 호출 → 위험자산을 목표치까지 비례 축소 + 안전자산 water-fill.
- `risk_on`: 위험자산 소폭 확대(cap 0.70 내). **확대 경로도** §7.2 [5] 검증→수선 사이클 통과.
- `drift:rebalance`: 직전 목표 복원. `drift:defensive`: 위험자산 cap 안으로 축소.

### 6.2 종목 교체 최소화 (finding #9 — reassess/monthly tilt 시)
[`select_representative_candidates`](../../../tradingagents/skills/portfolio/candidate_selector.py)는 `(duration, hedge, -AUM, ticker)`로만 정렬하고 **incumbent 인자가 없어** AUM drift로 near-tie가 run마다 뒤집혀 churn한다. 따라서:
- 엔진이 **현재 보유 종목 집합**을 bucket→ETF 변환에 전달.
- challenger AUM 우위(또는 rank-score delta) < `reassess_incumbent_band`(0.10)면 **보유 유지**, 명확히 우월할 때만 교체.
- 구현: `select_representative_candidates`에 `incumbents` 인자 또는 swap-suppression wrapper.

### 6.3 monthly
`graph.run(previous_portfolio=…)` — full validator(클러스터 포함)가 파이프라인 내부에서 이미 돈다. 엔진은 결과 weights를 target으로 받아 §7로.

### 6.4 클러스터 입력원 확보 (finding #1·#6 — hard mandate 구멍 차단)
daily/reassess에서 `correlation_clusters`가 비면 클러스터 cap이 공허 통과한다:
- **1차(권장)**: monthly full run이 `correlation_clusters`를 **portfolio.json에 영속화**(현재 미저장 — §9). daily/reassess는 직전 산출물 clusters 재사용.
- **2차(정확)**: 엔진이 [`find_correlation_clusters(returns, threshold=0.7)`](../../../tradingagents/skills/technical/correlation_cluster.py)를 가격 수익률로 **경량 재계산**(결정론, LLM 0).
- **안전장치**: 두 경로 모두 실패 시 **비중 변경 오버레이/tilt 금지**(거래 차단) + 경고 — 검증 불가 상태로 클러스터 cap 우회 금지.

---

## 7. 거래계획 엔진 `engine.py`

### 7.1 `reprice_holdings(previous_portfolio, as_of) -> dict[str, float]`
```python
def reprice_holdings(previous_portfolio: dict, as_of: date) -> dict[str, float]:
    """직전 보유 수량 × 오늘 종가 → 현재 비중 (현금 포지션 포함).

    수량: 직전 trade_plan.csv 수량(우선) 또는 weights×capital÷직전종가.
    오늘 종가: _fetch_current_prices(공용 추출) — KRX T+1~2 지연 시 7일 walk-back.
    현금: 직전 cash_residual을 현금 포지션으로 포함 → 종목+현금 합 ≈ 1.0.
    가격 fetch 실패 종목은 직전 비중 유지(보수적).
    """
```
- [`portfolio_manager._fetch_current_prices`](../../../tradingagents/agents/managers/portfolio_manager.py)를 공용 모듈로 추출 재사용.
- **현금은 위험자산 아님** → cap(위험 70%) 계산 시 분모에만 기여, 분자 제외.

### 7.2 `build_rebalance_plan(current, target, capital, prices, tier, dials)`
```
1. delta[t] = target[t] − current[t]   (합집합, 미보유=0)

2. no-trade band: |delta[t]| < dials.no_trade_band → delta[t]=0 (보유 유지)
   ★ 예외(finding #2): cap-방향 버퍼 초과 종목은 band 무시하고 항상 실행 —
     current[t] > single_etf_abs_cap(0.19)의 축소(SELL) 델타,
     또는 위험자산 합 > risk_asset_abs_cap(0.68) 해소용 위험 ETF 축소 델타.
     → cap 미세 초과가 band에 먹혀 잔존하는 위반 방지.

3. realized_post[t] = current[t] + 실행된 delta[t]   (band/예외 반영)
     = 실제 보유될 비중. 이후 검증·turnover의 기준.

4. 정수 qty: delta_qty = round(delta * capital / price)   (price=0 → 0 + 경고)
   잔여 현금(finding #12): cash_residual = capital − Σ(target_qty × price)
     → **현금으로 보유**(미투자). 현금성 ETF로 sweep하지 않음.
     → portfolio.json/rebalance.json에 cash line(cash_residual_krw·cash_weight) 기록
       → 다음 reprice가 현금 포함해 비중 산출(§7.1), 100% 투자 오인 방지.

5. mandate 재검증(finding #2·#6·#7): realized_post 비중에 **전체 mandate_validator**
   재실행 — integrity + universe + concentration(20%/70%) + correlation(0.25) + turnover.
     · 클러스터 입력원은 §6.4로 확보.
     · 위반 시 수선 1회: 위험 cap→repair_risk_cap, 클러스터 cap→비례 축소,
       그래도 실패면 validation에 hard 위반 기록 + 경고 (passed=True 오보고 금지).

6. turnover(finding #8): 실현 거래액 기반 단일 정의 —
     turnover = (Σ BUY krw + Σ SELL krw) / capital
   monthly: turnover < turnover_floor_monthly(0.10) → band 완화 재계산 → 미달 시 경고.
     turnover_check 재검증도 동일 실현 값 사용.
```

**핵심 경계:** 우선순위는 **cap 위반 방지 > turnover 하한 > no-trade band**. monthly에서만 동시 발생, 보통 full 재최적화로 자연 충족.

---

## 8. 산출물 (`artifacts/{date}/`)

| 파일 | 내용 | LLM |
|---|---|---|
| `{date}(rebalancing).json` | full trace: tier · trigger · current_weights · target_weights · **realized_weights** · plan · turnover(실현) · **cash_residual·cash_weight** · skipped_no_trade · **validation(클러스터 포함)** · previous_portfolio_path | 0 |
| `{date}(rebalancing)_plan.csv` | `티커, ETF명, 자산군, 현재수량, 목표수량, 매매구분, 거래수량, 거래금액(KRW)` (+ 잔여 현금 라인) | 0 |
| `{date}(rebalancing)_rationale.md` | 사유서 — **왜 지금(트리거) · 무엇을 바꿨나 · 왜 그렇게(regime/risk/시나리오·클러스터) · mandate 준수** | tier 차등 |

### 8.1 사유서 깊이 (tier 차등) — 신규 [`reports/rebalance_rationale.py`](../../../tradingagents/reports/rebalance_rationale.py)
| tier | 형식 | 내용 |
|---|---|---|
| monthly | 상세 LLM (philosophy 패턴) | regime/risk/시나리오 변화 → 목표 변경 논리 + 주요 매매 근거 + mandate 준수 |
| reassess | 간결 LLM | 발화 프록시 · regime 변화 · tilt 근거 · 주요 매매 3~5줄 |
| daily/event | **결정론 템플릿** (LLM 0) | 발화 트리거 · 방어 액션 · 매매 요약 표 |

> 파일명 주의: `(rebalancing)`의 괄호는 shell glob 특수문자 → 자동화 시 `"…"` 따옴표 필요.

---

## 9. 기존 코드 수정점 (surgical)

| 파일 | 변경 | finding |
|---|---|---|
| [`monthly_full.py`](../../../tradingagents/rebalance/monthly_full.py) | `previous_path`를 `graph.run(previous_portfolio=…)`로 전달 + engine 호출로 거래계획 | #1, #3 |
| [`portfolio_manager.py`](../../../tradingagents/agents/managers/portfolio_manager.py) | `correlation_clusters` portfolio.json 영속화; `_fetch_current_prices` 공용 추출 | #1/#6 |
| [`weekly_tilt.py`](../../../tradingagents/rebalance/weekly_tilt.py) | **정기 호출 제거** → reassess(조건부)로 재사용: 프록시 발화 시 macro+risk 재실행 → tilt → ETF 변환(incumbent-bias) → engine | 구조변경, #9 |
| [`daily_triggers.py`](../../../tradingagents/rebalance/daily_triggers.py) | 실제 `current_weights` 주입(`any_etf_weight`·드리프트); `kospi_return_1d` 실제 fetch; `reassess_triggers` 평가; 레거시 0.18 정리 | #4, #13, 구조변경 |
| [`candidate_selector.py`](../../../tradingagents/skills/portfolio/candidate_selector.py) | `select_representative_candidates`에 `incumbents` 인자(또는 wrapper) | #9 |
| [`reports/trade_plan.py`](../../../tradingagents/reports/trade_plan.py) | 현재 보유 델타 모드(또는 신규 `write_rebalance_plan`) + 잔여 현금 라인 | #2, #12 |
| [`presets/triggers_default.yaml`](../../../presets/triggers_default.yaml) | `rebalance:` 섹션(§5.6) 추가; `reassess_triggers`; 0.18 결정 반영 | #10, #13, 구조변경 |
| [`cli/commands/portfolio.py`](../../../cli/commands/portfolio.py) `rebalance` | **tier choice를 `{daily, monthly}`로** (weekly 제거; reassess는 daily 내부 자동); engine 결과·산출물 출력; `--from` 미지정 시 as_of 이전 날짜 auto-discovery | #3, #11, 구조변경 |
| **(신규)** [`tradingagents/monitor/notify.py`](../../../tradingagents/monitor/) + [`.github/workflows/rebalance-daily.yml`](../../../.github/workflows/) | 트리거 발화 시 알림 어댑터(슬랙 webhook, env); GitHub Actions cron 워크플로(상태 commit·동시성 직렬화) (§13) | 자동화 |

> **gap #1 주의:** `trading_graph.run()`·`agent_states`·`mandate_validator`의 previous_portfolio/turnover wiring은 **이미 구현돼 있다**(2026-05-10). 새로 추가 금지 — 수정은 `monthly_full` 전달 한 줄.

---

## 10. 에러 처리

| 상황 | 동작 |
|---|---|
| 직전 portfolio.json 없음 (첫 실행) | 리밸런싱 불가 → 명시 에러, `gaps plan` 먼저 안내 |
| **같은 날 plan + rebalance** (finding #11) | auto-discovery는 **as_of_date보다 엄격히 이전인** 가장 최근 portfolio.json만 previous로 채택 |
| 가격 fetch 실패 (휴장/지연) | 해당 종목 qty=0 + 경고; current 재평가는 직전 비중 유지 |
| tier == none (트리거 미발화) | 거래 0, 모니터링 리포트만, 정상 종료 |
| reassess 발화했으나 regime 변화 없음 | tilt 0, 모니터링 기록만 (거래 없음) |
| mandate 위반 (realized_post) | 수선 1회 → 실패 시 hard 위반 기록 + 경고 (passed 오보고 금지) |
| 클러스터 입력원 확보 실패 | 비중 변경 오버레이/tilt 금지(거래 차단) + 경고 (§6.4) |
| turnover 하한 미달 (monthly) | band 완화 재계산 → 그래도 미달이면 경고 |
| universe에 없는 ticker | 건너뜀, 예외 없음 |

---

## 11. 테스트 전략

**단위 ([`tests/unit/rebalance/`](../../../tests/unit/)):**
- `reprice_holdings` — 직전 수량 × 현재가 → 비중(현금 포함), 합 ≈ 1.0, 가격 실패 시 직전 유지.
- `build_rebalance_plan` — delta / no-trade band / **band 예외(버퍼 초과 cap-방향 강제 실행)** / 잔여 현금 = 현금 보유(cash_weight 기록, 종목 합 + 현금 = 1.0) / turnover(실현 거래액) 하한 충돌.
- 엣지: 신규 편입(current=0→BUY), 완전 청산(target=0→SELL), 가격=0(경고), HOLD.
- **mandate 재검증 — realized_post 기준**: 0.203 잔존이 단일 cap 위반으로 잡히는지(finding #2), daily/reassess에서 클러스터 cap이 실제 평가되는지(공허 통과 회귀 방지, finding #1/#6).
- 트리거 라우터 — 드리프트 임계 발화, **reassess 프록시 발화→regime 변화 유무 분기**, canonical ladder 우선순위, none 분기.

**통합 ([`tests/integration/`](../../../tests/integration/)):**
- 직전 portfolio.json fixture → `gaps rebalance daily/monthly` → 산출물 3종 + 파일명(`{date}(rebalancing)*`).
- 생성 plan이 **전체 mandate**(단일 20% / 위험 70% / **클러스터 0.25** / turnover) 만족, monthly turnover ≥10%.
- 같은 날 plan→rebalance 시 previous가 이전 날짜인지(finding #11).
- reassess: 프록시 발화 + regime 변화 → tilt 거래계획 / 프록시 발화 + regime 불변 → no-op.

**기존 재사용:** mandate 테스트, trade_plan qty=0 경고.

---

## 12. Known nuances / 튜닝 항목

1. **주기 구조 근거**: regime quadrant 실측 3주+ 불변(growth_inflation). 정기 weekly 제거 — daily 감시 + 조건부 reassess가 국면 변화를 더 정확히 포착. 단 quadrant 불변이면서 confidence/scenario가 천천히 drift하는 경우는 monthly까지 대기(대회 단기라 영향 작음).
2. **임계값 운영 튜닝**: 안전 버퍼(0.19/0.68) 고정, 드리프트 밴드·`defensive_target`·`reassess_triggers`·`reassess_incumbent_band`는 발화 빈도 로그로 조정. 전부 yaml.
3. **현재 보유 = 이상적 보유 가정 + 현금 포지션**: 실체결 오차·현금흐름 미반영. 잔여는 현금 보유로 추적. 실계좌 CSV override는 후속.
4. **turnover 정의 통일(finding #8)**: floor 검사·mandate 재검증 모두 실현 거래액 `(buy+sell)/capital`. 기존 `turnover_check` floor(0.10/0.80) calibration 유지.
5. **±5%p 두 의미 분리(finding #14)**: `single_etf_rel_band`(드리프트 발화) ≠ `reassess_tilt_step`(조정). 둘 다 yaml.
6. **클러스터 영속화(finding #1/#6)**: portfolio.json에 `correlation_clusters` 저장은 신규. 미저장 구버전 산출물 사용 시 2차(재계산) 또는 거래 차단 안전장치.
7. **reassess 프록시 정밀화**: 현재 yaml 프록시는 수익률곡선·vol 중심. 외국인 흐름·USDKRW 추가는 확장(daily fetch 확대 필요).
8. **백테스트 재사용**: 동일 엔진을 과거 구간에 쓰려면 가격 소스를 PIT-guard 경유 주입 — 별도 스펙.

---

## 13. 운영 모델 — 자동 실행 + 알림

현재 시스템은 **100% 수동(on-demand)** — CLI를 직접 실행할 때만 데이터를 fetch하고 트리거를 평가한다. 자동 스케줄러·데몬·cron이 전혀 없다(검증 완료). daily 감시가 의미를 가지려면 매일 돌아야 하므로 자동 실행을 도입한다.

### 13.1 자동 실행 (GitHub Actions cron)
- 신규 워크플로 `.github/workflows/rebalance-daily.yml`. **매 한국 영업일(월~금) 아침 — 미국장 마감 후, 한국장 개장 전** — cron `0 22 * * 0-4`(UTC 전날 22:00 = **KST 07:00**). 근거: ① 직전 미국장 마감(여름 EDT 05:00 KST·겨울 EST 06:00 KST) 이후라 밤사이 미국 시장(VIX·S&P·overnight) 영향 반영 — daily 이벤트 트리거가 보는 VIX·미국 금리가 최신값이 됨, ② 한국장 개장(09:00 KST) 2시간 전이라 당일 거래계획을 개장 전에 준비, ③ 아침이라 운영자가 확인 후 개장 시 집행. KST 07:00은 EDT/EST 전환과 무관하게 항상 미국 마감 후 — 서머타임 안전. GitHub 고부하 시 수 분 지연 가능하나 개장까지 2시간 여유.
- **내 컴퓨터와 완전 무관·24/7** — GitHub 인프라에서 실행. 노트북을 꺼도 돈다.
- **API 키**: GitHub Secrets (`FRED_API_KEY`·`ECOS_API_KEY`·`OPENAI_API_KEY`·KRX 키·`SLACK_WEBHOOK_URL`).
- **상태 보존(핵심)**: 매 실행은 ephemeral 환경 → 워크플로가 ① repo를 checkout해 직전 `artifacts/.../portfolio.json`을 읽고(§10 auto-discovery), ② 새 산출물 `artifacts/{date}/{date}(rebalancing)*`을 생성한 뒤 ③ **git commit & push**로 보존 → 다음 실행이 previous로 사용. (artifacts를 git에 남기는 기존 흐름과 일치)
- **동시성**: 워크플로 `concurrency` 그룹으로 직렬화 — 운영자 수동 실행/커밋과의 push 충돌 방지.
- **휴장일**: cron은 월~금만. 한국 공휴일/임시휴장은 daily 내부에서 가격 fetch 빈 응답 감지 시 트리거 평가 skip(§10 재사용) → 무거래.
- **monthly는 자동화 제외**: full은 philosophy 검토가 필요하므로 운영자가 의도적으로 실행(원하면 별도 월간 워크플로로 확장 가능하나 검토 게이트 권장).

### 13.2 발화 알림 (신규 [`tradingagents/monitor/notify.py`](../../../tradingagents/monitor/))
- **발송 조건**: `tier != none`(거래계획 발생) 또는 `emergency_defensive`/`reassess`(regime 변화) 발화 시.
- **채널**: env로 선택 — `SLACK_WEBHOOK_URL`(슬랙 webhook, 설정 간단·권장) 또는 SMTP(이메일). 미설정 시 로그만(graceful).
- **내용**: tier · 발화 트리거 · 주요 매매 요약(상위 N) · mandate 통과 여부 · 산출물 3종 경로.
- **데이터 소스 알림 아님**: 알림은 *트리거 발화*에만. 평시 no-op은 무알림(소음 방지).

### 13.3 안전 경계
- cron·알림은 **감시 + 거래계획 산출까지만** 자동화. **실제 주문은 사람이 산출물(`(rebalancing)_plan.csv`)을 확인한 뒤 MTS 수동 입력** — 자동 집행 없음(§2 out of scope 유지).
- 즉 "기계가 매일 살펴보고 이상 시 사람을 부른다. 거래 결정·집행은 사람이 한다."
