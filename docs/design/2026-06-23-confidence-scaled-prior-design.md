# Confidence-Scaled BL Prior — 설계 (rev1)

> **상태:** 적대적 감사(5렌즈·41제기·32확정·9반박) 반영 완료 → 사용자 검토 대기.
> **rev1 변경:** must-fix(staleness 이진·W_NEUTRAL 위험편향) + 핵심 should-fix(Laplace 평활·CPI 레벨투표·cross-check 약화·스키마 fold-in·검증 A/B·정직 param 예산)를 전 섹션 반영. 변경점 `[감사]` 표기.
> **맥락:** BL allocator의 *regime-as-prior-swap 취약성* 교정. 외부 비판: 정통 BL(Goldman 1992)은 regime으로 prior를 통째로 스왑하지 않는다 — 안정적 중립 prior에 닻을 내리고 regime은 *confidence 붙은 view*로 섞는다. 현 시스템은 `prior = QUADRANT_BASELINE[quadrant]`를 regime argmax로 하드선택 → regime 오분류/지연 시 포트폴리오 전체가 점프(binary·fragile). 본 설계는 대안 ②(confidence-scaled prior)로 이를 graceful하게.
> **선행:** BL allocator(`2026-06-20-bl-allocator-design.md`)가 라이브 기본(use_bl=True). 본 설계는 prior 선택만 보간으로 교체.
> **브랜치:** `rework/pipeline-methodology`. 테스트: repo `.venv` py3.13, `PYTHONUTF8=1`.

---

## 1. 목적 · 비목적

**목적.** BL prior를 regime argmax 하드선택에서 **confidence 보간**으로:
```
prior_w = (1 − c)·w_neutral + c·QUADRANT_BASELINE[quadrant]
```
`c` = regime에 대한 **결정론 신호-일치도 confidence**(LLM 자가보고 아님). 확신 약하거나 데이터 결측이면 `c→0` → prior가 *진짜 중립*으로 수렴(graceful). 명확하면 `c→1` → regime baseline 앵커.

**비목적.**
- BL 엔진(Π 역산·view·Idzorek·MQU·soft-clip·turnover) 불변 — prior 선택만 교체.
- LLM `RegimeClassification.confidence`(자가보고) 불변 — 휴면 옛경로·philosophy 유지. BL prior만 신규 `signal_confidence` 소비.
- regime을 prior에서 완전히 빼 view로 강등하는 정통 BL 전면전환(대안 ④)은 범위 밖. **[감사 F5]** ④는 더 *복잡*함이 검증됨(각 baseline이 w_neutral과 14차원 중 12-14개 상이, L1 0.20-0.42; regime을 weight-space 타깃으로 재현하려면 rank-13 view 세트 + turnover_cap=0.35가 L1 0.42를 막음). 본 설계는 *최소·가역* 보간.
- **[감사 F3] 기존 confidence 채널과의 관계:** 비-BL 경로의 `effective_band(0.4+0.6c)`는 quadrant baseline *주위 tilt 폭*을 좁힐 뿐 prior를 중립으로 보간하지 않음 → 본 보간은 *기존에 없던 능력*을 채움. 세 채널은 **병렬**(곱 아님): LLM `confidence`→effective_band(비-BL만), sentinel-게이트 0.1→LLM-skip 마커, 신규 `signal_confidence`→BL prior 보간 전용.

---

## 2. 핵심 결정

| # | 결정 | 선택 | 근거 |
|---|---|---|---|
| D1 | `w_neutral` | **4 baseline 평균 → 위험 0.50으로 재정규화** | **[감사 F1-STRAT]** 단순 평균은 위험합 0.6025(위험편향) → 침체서 c→0이 위험을 *올림*(역효과). 위험-proxy(={a5}∪GROWTH_KEYS) 합을 *중립 0.50*으로 rescale해 "불확실→진짜 균형"을 보장. derived(자유 파라미터 0; 0.50은 균형 상수). |
| D2 | `c` 계산 | **신호 일치도** `g_agree × i_agree` (Laplace 평활) | 등가투표·squash 0 → 저파라미터. 단일신호 노이즈에 등가투표가 ±1/n 캡(magnitude 대비 우위). **[감사 D2 약화]** LLM과 입력 공유 → "독립 교차검증"이 아니라 *동일 데이터의 룰기반 재현*. |
| D3 | 데이터품질 | **fetch-fail(sentinel)·None·neutral 기권** | **[감사 must]** staleness_days는 성공 시 0·실패 시 99(이진)라 *real-stale 포착 불가*. 따라서 기권의 실체는 *fetch-실패 게이트* + neutral/None 부호 기권 + 분모0→c=0. *staleness 임계는 tunable dial 아닌 sentinel 상수(99)*. |
| D4 | 지속성 | **없음(무상태)** | confidence-scaling이 prior whipsaw를 중화 + Laplace 평활이 단일신호 진폭 제한(아래 §4). |
| D5 | c 상한 | **무클램프 [0,1]** | baseline은 앵커(view가 tilt). 보호는 경계(c→0). **[감사 ROBUST-3]** 단 c→1 confident-misclassification 잔여위험은 §7에 명시(클램프 추가 대신 문서화 + backtest 진단). |
| D6 | 배선 | **매크로 레이어 skill + Optional 필드(fold-in)** | 경계 깨끗·순수함수. **[감사 F4-IMPL]** 필드는 *Optional+default*(LLM structured-output이 강요 안 되게), 코드가 *양 분기 model_copy로 사후 주입*. |

**[감사 PARSIM-2] 정직한 파라미터 예산.** "≈1개"는 과소계상이었음. *데이터로 보정하는 자유 dial은 사실상 0개*(staleness=sentinel 상수). 단 **사전등록(pre-registered) 이산 선택**이 존재: ① 신호의 성장/인플레 그룹 *배정*, ② 곱 결합(vs min/평균), ③ 경제 상수 3개(잠재성장 2.0·Fed타겟 2.0·CPI 레짐경계 3.0), ④ 15개 신호 *선택*, ⑤ 부호임계. 이들은 *튜닝값이 아니라 경제적 정당화를 가진 구조 선택*이며 spec에 명문화(아래 §4)해 사후 자유도를 막는다. ~88 월간 backtest 점은 *공격성 dial*(turnover/δ) 보정용이지 이 confidence 구조 보정용이 아님.

---

## 3. 아키텍처 & 데이터 흐름

```
macro_quant_analyst (스냅샷 빌드)
   ├─ [정상] classify_regime(LLM) → quadrant + confidence(LLM, 그대로)
   │     → c = compute_regime_confidence(snapshots, quadrant)
   │     → regime = regime.model_copy(update={"signal_confidence": c})   # D7 fold-in
   └─ [degraded, sentinel≥50%] LLM skip → quadrant=placeholder
         → regime = regime.model_copy(update={"signal_confidence": 0.0})  # [감사 F5-IMPL] 강제 0
        ▼
   macro_report.regime.{quadrant, confidence(LLM), signal_confidence(결정론)}
        ▼
trader_allocator.node:
   c = getattr(getattr(macro_report,"regime",None), "signal_confidence", 1.0)  # None-guard
   build_bl_bucket_weights(as_of, quadrant, ranking, signal_confidence=c, ...):
      prior_w = (1−c)·W_NEUTRAL + c·QUADRANT_BASELINE[quadrant]
      → bl_allocate(Sigma, prior_w, ranking, ...)   # BL 불변
```
**[감사 F5/F4-IMPL]** degraded 분기는 `compute_regime_confidence`에 의존하지 않고 `signal_confidence=0.0` *무조건 설정* — sentinel≥50%가 §4 신호가 stale함을 *보장하지 않으며*(일부 신선할 수 있음) 분면이 고정 placeholder라, 잘못된 분면에 spurious c를 붙이면 안 됨. → prior 강제 중립.

**파일(3곳):**
| 파일 | 변경 |
|---|---|
| `tradingagents/skills/macro/regime_confidence.py` (신규) | `compute_regime_confidence(snapshots, quadrant)→float` 순수 skill |
| `tradingagents/schemas/macro.py` + `agents/analysts/macro_quant_analyst.py` | `RegimeClassification.signal_confidence: float|None = None` 필드 + *양 분기* fold-in |
| `tradingagents/agents/trader/trader_allocator.py` | `W_NEUTRAL` 상수 + `build_bl_bucket_weights` `signal_confidence` kwarg + 보간; node 추출(None-guard) |

---

## 4. `compute_regime_confidence` skill (핵심)

**계약:** `compute_regime_confidence(snapshots, quadrant) -> float ∈ [0,1]`. 순수함수. snapshots는 dict(일부 값 None 가능).

**공식 (Laplace 평활):**
```
c = growth_agreement × inflation_agreement
각 축: n = 신선 신호 수, k = 분면방향과 부호 일치하는 신선 신호 수
  n == 0  →  agreement = 0      # [감사 CONF-3] 한 축 정보 전무 → 분면 확인 불가 → c=0(중립)
  n >= 1  →  agreement = (k + 1) / (n + 2)   # Laplace: n=1 일치→2/3, 불일치→1/3 (이진붕괴 제거)
```
quadrant→방향: `growth_inflation=(+,+)` · `growth_disinflation=(+,−)` · `recession_inflation=(−,+)` · `recession_disinflation=(−,−)`.

**[감사 CONF-3] Laplace 효과:** n=1 단일신호 축이 경계 flip해도 c가 0↔타축이 아니라 (1/3·a)↔(2/3·a)로만 이동(진폭 절반↓) → 작은 분모(인플레 ~6, 결측 시 더 작음) 민감도·whipsaw 동시 완화(ROBUST-2 흡수). n↑면 평활 감쇠(n=10,k=10→11/12).

**신호 그룹 & 부호 추출** (기존 boolean/categorical 재사용; 부호 규칙은 *사전등록 구조선택*):

*성장 (+ = 확장):*
| 신호 | 필드 | 부호 |
|---|---|---|
| CFNAI | `USLeadingIndexSnapshot.cfnai_ma3`/`recession_signal` | recession_signal→−1; else sign(cfnai_ma3) |
| KR 선행 | `KRLeadingIndexSnapshot.phase` | expansion/peak→+1; contraction/trough→−1 *([감사 CONF-9 확인] phase=(level,momentum) — peak=추세위·trough=추세아래, 동시점 일치도엔 레벨부호가 옳음)* |
| KR 수출 | `KRExportSnapshot.yoy_pct` | sign(yoy_pct) |
| KR BSI | `KRBusinessSurveySnapshot.mfg_bsi`/`contraction_signal` | contraction_signal→−1; else sign(mfg_bsi−100) |
| 고용 | `EmploymentSnapshot.sahm_rule_triggered` | True→−1; else sign(−rate_change_3mo) |
| Copper/Gold | `RiskAppetiteSnapshot.signal` | risk_on→+1; risk_off→−1; neutral→기권 |
| 수익률곡선 | `YieldCurveSnapshot.spread_10y_2y_bps` | <0→−1; else +1 |
| 중국 선행 | `ChinaLeadingSnapshot.realtime_signal` | expansion→+1; contraction→−1; neutral→기권 |
| GDPNow | `GDPNowSnapshot.nowcast_pct` | sign(nowcast_pct − 2.0) *(잠재성장 상수)* |

*인플레 (+ = 인플레):*
| 신호 | 필드 | 부호 |
|---|---|---|
| CPI | `InflationSnapshot.momentum_3mo`/`accelerating` | **[감사 CONF-6] 레벨 우선:** `sign(momentum_3mo − 3.0)` *(레짐경계 3%, classifier 프롬프트 정합)*; `|momentum_3mo−3.0|<ε`일 때만 accelerating 방향 보조 |
| Core PCE | `InflationSnapshot.core_pce_yoy` | None→기권; else sign(core_pce_yoy − 2.0) *(Fed타겟)* |
| 인플레 기대 | `InflationExpectationsSnapshot.unanchored_direction` | upside→+1; downside→−1; none→기권 |
| WTI momentum | `CommodityMomentumSnapshot.wti_3m_pct` | sign(wti_3m_pct) *([감사 F2-STRAT] copper는 성장축 Cu/Au 1회만 — 인플레축서 제외해 cross-axis 중복 회피)* |
| 반도체 PPI | `ChipCycleSnapshot.accelerating`/`chip_ppi_yoy_pct` | accelerating→+1; else sign(chip_ppi_yoy_pct) |

**기권 규칙 (3가지, 균일 게이트):**
1. **fetch-fail:** `snap.staleness_days ≥ STALENESS_ABSTAIN(=99 sentinel 상수)`. **[감사 must]** 정상 데이터는 staleness=0이라 *real-stale 포착 안 됨* — 이 게이트의 실체는 *fetch 실패(sentinel) 기권*. (china_leading만 연속 staleness — 월간 OECD CLI라 보통 <99, 별도 처리 불필요.)
2. **None 스냅샷:** **[감사 F2/F3-IMPL]** `snap is None`(CommodityMomentum·ChipCycle 등 Optional이 None 반환 가능) → 그 신호 기권. 균일 가드: `snap is None or getattr(snap,"staleness_days",99) >= STALENESS_ABSTAIN`.
3. **neutral/None 부호:** copper/gold "neutral", phase 모호, None 필드 → 기권.

**[감사 CONF-1] LLM 오판 sanity-check (정확 진술):** `c < 0.5 ⟺ g_agree·i_agree < 0.5`. 한 축이 완전지지(=1)면 c는 타축으로 환원 → 그 타축이 strict-minority(<0.5)일 때만 발동. 경계(한 축 1.0, 타축 정확히 0.5)는 c=0.5로 *비발동*. **이건 독립 교차검증이 아니라 동일 데이터의 룰기반 재현**(LLM과 입력 공유) — confident-misclassification은 못 막음(§7).

---

## 5. prior 보간 (`build_bl_bucket_weights`)

```python
# 모듈 상수 (derived) — [감사 D1] 위험 0.50 재정규화
_RAW_NEUTRAL = {b: mean(QUADRANT_BASELINE[q][b] for q in QUADRANT_BASELINE) for b in 14버킷}
# 위험-proxy(={a5_gold_infl}∪GROWTH_KEYS) 합을 0.50으로: 위험버킷 ×(0.50/risk_sum), 방어버킷 ×((0.50)/(1−risk_sum)) 후 합=1
W_NEUTRAL = _rescale_risk_to(_RAW_NEUTRAL, target_risk=0.50)

def build_bl_bucket_weights(as_of, quadrant, ranking, *, signal_confidence=1.0, ...):
    c = max(0.0, min(1.0, float(signal_confidence)))
    base_q = QUADRANT_BASELINE[quadrant]
    prior_w = pd.Series({b: (1-c)*W_NEUTRAL[b] + c*base_q[b] for b in base_q})  # convex → 합=1, ≥0
    # ... 기존: bl_allocate(Sigma, prior_w, ranking, ...)
```
- node가 `signal_confidence` 추출·전달. **기본값 1.0** = 현 거동(prior=baseline) → 미전달 호출자(기존 BL/게이트2 테스트) 무변경 → 회귀 0. 라이브만 실제 c.
- **[감사 F7-INTEG 확인]** prior_w가 `bl_allocate`의 baseline으로 들어가 pin·budget-aware cap·turnover·soft-clip이 *모두 같은 prior_w 기준*으로 일관 작동. MATH-1 "no-view→prior_w 정확복원"은 *모든 c*에서 성립(turnover=0 feasible). "엔진 불변"은 *알고리즘 불변*을 뜻하며 최종 배분은 c에 따라 의도적으로 변함(graceful).

---

## 6. 불변식 · 테스트 · 검증

**불변식 (테스트 잠금):**
- `compute_regime_confidence`: Laplace n=1 일치→2/3·불일치→1/3(둘 다 {0,1} 아님) · n=0→agreement 0 · 한 축 1.0+타축<0.5→c<0.5 · 양축 약(각≤0.6)→c≤0.36 · **None 스냅샷→해당신호 기권·예외 없음** · 출력∈[0,1] · LLM이 채운 signal_confidence를 코드 fold-in이 *항상 덮어씀*.
- W_NEUTRAL: 위험-proxy 합≈0.50 · 합=1 · ≥0.
- 보간: prior_w 합=1·≥0 · c=0→W_NEUTRAL · c=1→base_q. **[감사 F1] 위험 단조성 테스트:** *모든 quadrant*에서 c↓ 시 prior_w 위험-proxy가 0.50으로 수렴(침체서 0.40→0.50 상승은 "불확실→균형"이라 의도적이나, 0.60으로 *과상승하지 않음*을 잠금).
- 회귀: 기존 BL/게이트2(기본 1.0) → prior=baseline → green. RegimeClassification 기존 생성처(default=None) → green.

**[감사 F4-STRAT/F4-IMPL] 검증 — A/B는 신규 하네스 필요:**
- 기존 `backtest_bl_calibration.py`는 *quadrant 고정*이라 regime-오분류 구간이 없어 ② A/B 불가. → **regime-PATH 변형 추가**: 매월말 `tradingagents/backtest/classify.py::assign_cycle`로 PIT 매크로 패널(`backtest/data.py::fetch_macro_quarterly_extended`)에서 quadrant 결정론 산출 → `regime-swap(c=1) vs confidence-scaled(실제 c)`를 2020-03·2022 전환 포함 윈도우로 비교, **전환구간 슬라이스**로 (F1 침체위험상승)·(F2 전환점 과신)을 직접 검정.
- 대안(저비용): unit/property 검증 — synthetic 스냅샷으로 c→0(경계)·c→1(일치)·단조성, 보간 end-to-end는 §6 불변식. *기존 calibration 스크립트가 c를 검증한다고 주장하지 않음.*
- **적대적 감사** 코드변경마다(사용자 정책).

---

## 7. 미해결 / 위험

- **[감사 must] staleness=fetch-fail 게이트:** real-stale(묵었지만 fetch 성공) 데이터는 staleness=0이라 *기권 안 됨* — data-quality는 *결측 신호*만 잡고 *늙은 신호*는 못 잡음. 진짜 real-stale 기권을 원하면 각 skill이 source_date 기반 실 staleness를 emit하도록 producer 수정 필요(범위 밖).
- **[감사 ROBUST-3/F2-STRAT] confident-misclassification(질문2 SPOF 실재):** 신호 공선성(CFNAI↔고용↔생산; copper 양축은 dedup으로 1회) 및 *후행지표*(Sahm·realized CPI·employment)로 전환점에서 일치도가 *옛 regime을 과신*해 c→1로 잘못 앵커 가능. LLM도 같은 스냅샷을 봐 D2 교차검증이 *공모*로 퇴화. → c_max<1 약클램프는 backtest 전환구간 진단에서 c가 유의하게 1 근방에 몰릴 때만 조건부 도입(파라미터 1 정직 계상).
- **[감사 CONF-6] 저베이스 reflation:** sub-target이지만 가속하는 CPI가 inflation_agreement를 spurious하게 올릴 수 있음(레벨투표로 완화하나 경계 ε 잔존).
- **[감사 PARSIM] dead-zone ε:** sign(x−상수) 경계 흔들림 — `|x−상수|<ε→기권`은 파라미터 1 추가라 backtest 도입가치 확인 후.
- **w_neutral 의미:** 위험 0.50 재정규화 후에도 자산회전 shape는 4-baseline 평균 — 특정 국면엔 어중간하나 c→0(불확실)에서만 발동하므로 적절(특정 국면 베팅 회피).
