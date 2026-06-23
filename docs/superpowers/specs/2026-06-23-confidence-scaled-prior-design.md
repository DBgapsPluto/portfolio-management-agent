# Confidence-Scaled BL Prior — 설계 (rev0)

> **상태:** 설계 승인 → 적대적 감사 대기.
> **맥락:** BL allocator의 *regime-as-prior-swap 취약성* 교정. 외부 비판: 정통 BL(Goldman 1992)은 regime으로 prior를 통째로 스왑하지 않는다 — 안정적 중립 prior에 닻을 내리고, regime은 *confidence 붙은 view*로 섞는다. 현 시스템은 `prior = QUADRANT_BASELINE[quadrant]`를 regime argmax로 하드 선택 → regime 오분류/지연 시 포트폴리오 전체가 점프(binary·fragile). 본 설계는 대안 ②(confidence-scaled prior)로 이를 graceful하게 만든다.
> **선행:** BL allocator(`2026-06-20-bl-allocator-design.md`)가 라이브 기본(use_bl=True). 본 설계는 그 prior 선택만 보간으로 교체.
> **브랜치:** `rework/pipeline-methodology`. 테스트: repo `.venv` py3.13, `PYTHONUTF8=1`.

---

## 1. 목적 · 비목적

**목적.** BL prior를 regime argmax 하드선택에서 **confidence 보간**으로:
```
prior_w = (1 − c)·w_neutral + c·QUADRANT_BASELINE[quadrant]
```
- `c` = regime에 대한 **결정론 신호-일치도 confidence** (LLM 자가보고 아님).
- regime 확신이 약하거나(경계) 데이터가 결측이면 `c→0` → prior가 중립으로 수렴(graceful). 명확하면 `c→1` → regime baseline 앵커.

**비목적.**
- BL 엔진(`bl_engine`: Π 역산·view·Idzorek·MQU·soft-clip·turnover)은 불변 — prior 선택만 교체.
- LLM `RegimeClassification.confidence`(자가보고)는 *건드리지 않음* — 휴면 옛경로·philosophy가 쓰던 값 유지. BL prior만 신규 결정론 `signal_confidence` 소비.
- regime을 prior에서 완전히 빼 view로 강등하는 정통 BL 전면 전환(대안 ④)은 범위 밖 — 본 설계는 *최소·가역* 보간.

---

## 2. 핵심 결정 (5)

| # | 결정 | 선택 | 근거 |
|---|---|---|---|
| D1 | `w_neutral` | **4 baseline 평균** | derived(파라미터 0)·정당화 자명("regime 불확실→시나리오 평균")·convex라 보간 항상 sane. |
| D2 | `c` 계산 | **신호 일치도** `growth_agreement × inflation_agreement` | 등가투표(가중치 0)·squash 0 → near-parameter-free. 개별신호 노이즈에 robust. LLM regime 오판 교차검증 보너스. |
| D3 | 데이터품질 | **stale 신호 기권**(일치도에 내재) | 별도 인자 불필요. 유일 dial = staleness 임계. |
| D4 | 지속성(hysteresis) | **없음(무상태)** | confidence-scaling이 prior 레벨 whipsaw를 이미 중화(경계 flip→c≈0→두 달 다 중립). 상태비용 대비 한계효용 낮음(YAGNI). |
| D5 | c 상한 | **무클램프 [0,1]** | baseline은 *앵커*(view가 tilt)라 명확국면 100% 앵커는 "예보에 다 거는" 게 아님. 보호는 경계(c→0)에서. 파라미터 −1. |
| D6 | 배선 | **매크로 레이어 skill + 추가 필드** | skill이 입력(스냅샷) 옆에 살아 경계 깨끗·순수함수 테스트 쉬움. LLM confidence 불변→위험 최소·가역. `signal_confidence` 재사용 자산(향후 문제4 확장 여지). |

**파라미터 예산:** 새 자유 파라미터 ≈ **1개**(staleness 임계). `w_neutral`·신호배정·경제상수(~2% 잠재성장·2% Fed타겟)는 튜닝값 아님. ~88 월간 backtest 점으로 robust 보정 가능 범위 내(≤2 dial).

---

## 3. 아키텍처 & 데이터 흐름

```
macro_quant_analyst (스냅샷 빌드)
   ├─ classify_regime(LLM) → quadrant + confidence(LLM, 그대로)
   └─ compute_regime_confidence(스냅샷, quadrant) → signal_confidence c   ← 신규 결정론 skill
        │ (RegimeClassification 에 둘 다 저장)
        ▼
   macro_report.regime.{quadrant, confidence(LLM), signal_confidence(결정론)}
        ▼
trader_allocator.node → build_bl_bucket_weights(as_of, quadrant, ranking,
                          signal_confidence=c, ...):
   prior_w = (1−c)·W_NEUTRAL + c·QUADRANT_BASELINE[quadrant]
   → bl_allocate(Sigma, prior_w, ranking, ...)   # 이하 BL 불변
```

**컴포넌트 경계:**
| 유닛 | 입력 | 출력 | 의존 |
|---|---|---|---|
| `compute_regime_confidence` (신규 skill) | 스냅샷, quadrant | float∈[0,1] | 없음(순수) |
| `W_NEUTRAL` (상수) | QUADRANT_BASELINE | dict(14) | scenario_anchor |
| prior 보간 (build_bl_bucket_weights 내) | quadrant, c | prior_w dict | W_NEUTRAL |

**파일(3곳):**
| 파일 | 변경 |
|---|---|
| `tradingagents/skills/macro/regime_confidence.py` (신규) | `compute_regime_confidence(snapshots, quadrant)→float` 순수 skill |
| `tradingagents/schemas/macro.py` + `agents/analysts/macro_quant_analyst.py` | `RegimeClassification.signal_confidence` 필드 + 호출·저장 |
| `tradingagents/agents/trader/trader_allocator.py` | `W_NEUTRAL` 상수 + `build_bl_bucket_weights`에 `signal_confidence` 파라미터 + 보간; node가 `macro_report.regime.signal_confidence` 추출·전달 |

---

## 4. `compute_regime_confidence` skill (핵심)

**계약:** `compute_regime_confidence(snapshots, quadrant) -> float ∈ [0,1]`. 순수함수.

**공식:**
```
c = growth_agreement × inflation_agreement
growth_agreement    = (분면 성장방향과 부호 일치하는 *신선* 성장신호 수) / (신선 성장신호 수)
inflation_agreement = (분면 인플레방향과 부호 일치하는 *신선* 인플레신호 수) / (신선 인플레신호 수)
```
quadrant → 방향: `growth_inflation=(+,+)` · `growth_disinflation=(+,−)` · `recession_inflation=(−,+)` · `recession_disinflation=(−,−)` (성장+ = 확장, 인플레+ = 인플레).

**신호 그룹 & 부호 추출** (기존 boolean/categorical 재사용 우선):

*성장 신호 (+ = 확장):*
| 신호 | snapshot 필드 | 부호 규칙 |
|---|---|---|
| CFNAI | `USLeadingIndexSnapshot.cfnai_ma3` / `recession_signal` | recession_signal=True→−1; else sign(cfnai_ma3) |
| KR 선행지수 | `KRLeadingIndexSnapshot.phase` | expansion/peak→+1; contraction/trough→−1 |
| KR 수출 | `KRExportSnapshot.yoy_pct` | sign(yoy_pct) |
| KR BSI | `KRBusinessSurveySnapshot.mfg_bsi` / `contraction_signal` | contraction_signal=True→−1; else sign(mfg_bsi−100) |
| 고용 | `EmploymentSnapshot.sahm_rule_triggered` | True→−1; else sign(−rate_change_3mo) |
| Copper/Gold | `RiskAppetiteSnapshot.signal` | risk_on→+1; risk_off→−1; neutral→기권 |
| 수익률곡선 | `YieldCurveSnapshot.spread_10y_2y_bps` | <0(역전)→−1; else +1 |
| 중국 선행 | `ChinaLeadingSnapshot.realtime_signal` | expansion→+1; contraction→−1; neutral→기권 |
| GDPNow | `GDPNowSnapshot.nowcast_pct` | sign(nowcast_pct − 2.0) *(2.0=잠재성장, 경제상수)* |

*인플레 신호 (+ = 인플레):*
| 신호 | snapshot 필드 | 부호 규칙 |
|---|---|---|
| CPI | `InflationSnapshot.accelerating` / `momentum_3mo` | accelerating=True→+1; else sign(momentum_3mo − 2.0) |
| Core PCE | `InflationSnapshot.core_pce_yoy` | None→기권; else sign(core_pce_yoy − 2.0) *(2.0=Fed타겟)* |
| 인플레 기대 | `InflationExpectationsSnapshot.unanchored_direction` | upside→+1; downside→−1; none→기권 |
| 원자재 momentum | `CommodityMomentumSnapshot.copper_3m_pct`, `wti_3m_pct` | 각 sign; 둘을 별도 투표 |
| 반도체 PPI | `ChipCycleSnapshot.accelerating` / `chip_ppi_yoy_pct` | accelerating=True→+1; else sign(chip_ppi_yoy_pct) |

**규칙:**
- **기권(투표 제외):** ① `staleness_days ≥ STALENESS_ABSTAIN`(기본 **99** — sentinel==99 + 3개월+ 묵은 real 데이터 포착), ② 부호가 neutral/모호(예 copper/gold "neutral", phase 모호, None 필드).
- **분모 0(전 신호 stale)** → 해당 axis agreement = 0 → `c = 0` → prior = 중립. (데이터 없으면 regime 안 믿음. 기존 sentinel-게이트 50% 규칙과 일관.)
- **LLM 오판 교차검증:** classifier가 데이터 미지지 분면을 찍으면 일치도<0.5 → c↓ → prior 중립. (결정론 신호가 LLM regime을 sanity-check.)
- **유일 자유 dial:** `STALENESS_ABSTAIN`(기본 99). 경제상수(2.0×2)·신호배정은 구조적.

---

## 5. prior 보간 (`build_bl_bucket_weights`)

```python
# 모듈 상수 (derived)
W_NEUTRAL = {b: sum(QUADRANT_BASELINE[q][b] for q in QUADRANT_BASELINE) / len(QUADRANT_BASELINE)
             for b in next(iter(QUADRANT_BASELINE.values()))}
# 각 분면 합=1 → 평균도 합=1.

def build_bl_bucket_weights(as_of, quadrant, ranking, *, signal_confidence=1.0, ...):
    c = max(0.0, min(1.0, float(signal_confidence)))
    base_q = QUADRANT_BASELINE[quadrant]
    prior_w = pd.Series({b: (1-c)*W_NEUTRAL[b] + c*base_q[b] for b in base_q})  # convex → 합=1
    # ... 이하 기존: Sigma fetch, extra_views, bl_allocate(Sigma, prior_w, ranking, ...)
```
- node가 `signal_confidence = getattr(macro_report.regime, "signal_confidence", 1.0)` 추출·전달.
- **기본값 1.0** = 현 거동(prior=baseline) → `signal_confidence` 미전달 호출자(기존 BL 테스트·게이트2 고정view) 무변경 → 회귀 0. 라이브 node만 실제 c 전달.
- **w 레벨 보간**(Π 아님) → prior_w 항상 유효 배분(합=1, ≥0). pin·view·MQU·soft-clip 전부 prior_w를 baseline으로 받아 불변.

---

## 6. 불변식 · 테스트 · 검증

**불변식 (테스트 잠금):**
- `compute_regime_confidence`: 전 신호 일치→c 높음 · 분열→c 낮음 · LLM 미지지 분면→c<0.5 · 전 신호 stale→c=0 · neutral/None 부호 기권 · 출력 ∈[0,1].
- 보간: prior_w 합=1 · c=0→W_NEUTRAL · c=1→base_q · c∈[0,1] 클램프 · prior_w≥0.
- **MATH-1 무영향:** 보간은 build층, `bl_allocate`는 주어진 baseline으로 복원 → bl_engine no-view 복원 테스트 불변. build층은 "no-view→prior_w 복원" 신규 테스트.

**회귀:** 기존 BL/게이트2 테스트는 `signal_confidence` 미전달(기본 1.0) → prior=baseline → 전부 green.

**검증 (②의 값어치 실증):**
- 라이브 스모크: 데모 run에서 산출 c + prior가 baseline 대비 중립으로 당겨진 정도 확인.
- **backtest A/B:** `scripts/backtest_bl_calibration.py`에 `regime-swap(c=1 고정) vs confidence-scaled(실제 c)` 비교 추가 — graceful 버전이 수익/낙폭/regime-오분류 구간에서 나은지 실증.
- **적대적 감사** 코드변경마다(사용자 정책).

---

## 7. 미해결 / 위험

- **신호 부호 추출의 경계값:** sign(x − 상수)에서 x가 상수에 매우 가까우면 부호가 흔들림 → 사실상 "약한 신호"인데 +1/−1 투표. 완화: 작은 dead-zone(|x−상수|<ε→기권) 고려 가능하나 파라미터 추가 — backtest로 필요시.
- **신호 그룹 불균형:** 성장 9 vs 인플레 ~6 — 축별 분모가 달라도 *각 축 내 비율*이라 무방(곱). 단 인플레 신호가 적어 결측 시 분모 작아짐 → c 변동성↑. 모니터.
- **STALENESS_ABSTAIN=99 충돌:** 실제 분기 데이터가 99일째면 오기권 가능(minor). sentinel 마커(99)와 real-stale를 한 임계로 합친 단순화의 비용.
- **w_neutral 평균의 의미:** 4 baseline 평균이 어느 실제 국면과도 안 맞는 "어중간" 배분일 수 있음 — 단 c→0은 *불확실*할 때만 발동하므로 어중간이 오히려 적절(특정 국면 베팅 회피).
