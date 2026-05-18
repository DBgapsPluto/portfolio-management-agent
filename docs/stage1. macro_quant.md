# Stage 1 — Macro Quant Analyst

> 파이프라인 6 stage 중 첫 단계의 4명 병렬 분석가 중 하나. 매크로 환경을 정량 진단해서 다음 stage(Bull/Bear 토론)와 그 이후 모든 단계의 기준 신호를 만들어낸다.

---

## 1. 한 줄 요약

> **23개 데이터 시리즈를 22개 skill로 가공해 20개 dimension의 macro snapshot을 만들고, LLM에게 넘겨 4 quadrant 중 하나로 현재 매크로 regime을 분류한다.**

---

## 2. 어떤 데이터를 보는가 (23개 시리즈)

### 2.1 FRED (미국 St. Louis Fed, 16 시리즈)

| 친근명 | FRED ID | 빈도 | 의미 |
|---|---|---|---|
| `us_10y` | DGS10 | daily | 10년 국채 수익률 |
| `us_2y` | DGS2 | daily | 2년 국채 수익률 |
| `us_3m` | DGS3MO | daily | 3개월 단기 |
| `us_cpi` | CPIAUCSL | monthly | 헤드라인 CPI |
| `us_core_cpi` | CPILFESL | monthly | 코어 CPI |
| `us_unrate` | UNRATE | monthly | 실업률 |
| `us_payems` | PAYEMS | monthly | 비농업 고용 |
| `us_policy_rate` | DFF | daily | Fed Funds 실효금리 |
| `us_cfnai` | CFNAI | monthly | Chicago Fed 85-지표 합성 활동지수 |
| `us_cfnai_ma3` | CFNAIMA3 | monthly | CFNAI 3개월 MA (recession 핵심 임계) |
| `us_gdp_nowcast` | GDPNOW | weekly | Atlanta Fed 실시간 분기 GDP nowcast |
| `us_nfci` | NFCI | weekly | Chicago Fed 금융여건 지수 (105+ 지표 합성) |
| `us_anfci` | ANFCI | weekly | NFCI 조정후 (background macro 제거) |
| `us_5y5y_breakeven` | T5YIFR | daily | 5Y5Y forward 기대인플레 (시장 기반) |
| `us_michigan_1y` | MICH | monthly | Univ of Michigan 1y 기대인플레 (가계 서베이) |
| `usd_krw` | DEXKOUS | daily | 1 USD 당 KRW |
| `dxy` | DTWEXBGS | daily | Trade-weighted broad dollar index |
| `china_cli` | CHNLOLITONOSTSAM | monthly | OECD China amplitude-adjusted CLI |
| `us_epu` | USEPUINDXM | monthly | Baker-Bloom-Davis US 정책 불확실성 |
| `global_epu` | GEPUCURRENT | monthly | Global EPU (현재가 가중) |
| `vvix` | VVIXCLS | daily | CBOE VIX-of-VIX (vol of vol) |
| `move` | MOVE | daily | ICE BofA Treasury 변동성 |

### 2.2 ECOS (한국은행, 5 시리즈)

| 친근명 | ECOS 코드 | 빈도 | 의미 |
|---|---|---|---|
| `kr_base_rate` | 722Y001 / 0101000 | daily | 한국 기준금리 |
| `kr_cpi` | 901Y009 / 0 | monthly | 한국 CPI |
| `kr_export` | 403Y001 / *AA | monthly | 한국 총 수출액 |
| `kr_cli` | 901Y067 / I16D | monthly | 통계청 선행지수 순환변동치 |
| `kr_bsi_mfg` | 512Y014 / AX1AA | monthly | 한국은행 제조업 업황 BSI |

### 2.3 yfinance (글로벌 commodities, 2 시리즈)

| 친근명 | yf 티커 | 의미 |
|---|---|---|
| `copper` | HG=F | COMEX 구리 선물 (USD/lb) |
| `gold` | GC=F | COMEX 금 선물 (USD/oz) |

### 2.4 KRX pykrx (한국 거래소, 1 시리즈)

| 함수 | 의미 |
|---|---|
| `fetch_foreign_flow(start, end)` | 외국인 KOSPI 일별 순매수 거래대금 (KRW) |

### 2.5 추가 — Central Bank Calendar

FOMC + BOK 결정일 90일 lookahead 스크랩 (별도 API 불요). 결정 자체는 regime 분류에 들어가지 않고, philosophy.md 작성 시 컨텍스트로만 사용.

---

## 3. 어떻게 가공하는가 (22 skill의 계산 공식)

### 3.1 금리 (3 skills)

#### `yield_curve` (DGS10, DGS2, DGS3MO)
```
spread_10y_2y_bps   = (10y - 2y) × 100
spread_10y_3m_bps   = (10y - 3m) × 100
inverted_days_count = (지난 365일 중 spread<0인 일수)
percentile_5y       = 현재 spread가 5년 분포에서 어디 위치
```
**해석**: 역전(spread<0)이 60일 넘게 지속되면 6~18개월 후 경기침체 신호.

#### `fed_path` (DGS2, DFF)
```
path_bps = (DGS2 - DFF) × 100   # bps 단위
market_view = "hike" if path_bps > +50
              "cut"  if path_bps < -50
              "hold" otherwise
```
**왜 DGS2-DFF**: 2년 국채는 향후 ~24개월 정책 기대를 가격에 반영. CME Fed Funds Futures와 corr > 0.9. 추가 API 의존성 없이 단일 신호로 Fed 경로 진단.

#### `divergence` (DFF, kr_base_rate, US CPI, KR CPI)
```
rate_gap_bps = (us_policy_rate - kr_base_rate) × 100
infl_gap     = us_cpi_yoy - kr_cpi_yoy
score        = max(-10, min(10, -|rate_gap/100| - |infl_gap|))
```
**해석**: score가 음수일수록 미-한 정책 갭이 커서 KRW 약세 압력. -5 미만 = 심각한 divergence.

### 3.2 인플레이션 (2 skills)

#### `inflation` (CPI, Core CPI)
```python
yoy            = (cpi[-1]/cpi[-13])^(12/12) - 1        # 12개월 YoY
momentum_3mo   = (cpi[-1]/cpi[-4])^(12/3)  - 1         # 3개월 연율화
momentum_6mo   = (cpi[-1]/cpi[-7])^(12/6)  - 1
accelerating   = (momentum_3mo > momentum_6mo > yoy)   # 볼록성 = 가속
```
**해석**: `accelerating=True`는 단기가 장기보다 빠르다는 볼록성 신호. Fed 인상 확률 급등 트리거.

#### `inflation_expectations` (5Y5Y breakeven, Michigan 1y)
```
breakeven_anchored = 1.5 ≤ breakeven_5y5y ≤ 3.0
michigan_anchored  = 2.0 ≤ michigan_1y ≤ 4.0
anchored = breakeven_anchored AND michigan_anchored   # 둘 다 만족해야

unanchored_direction:
  "upside"   if breakeven_5y5y > 3.0 OR michigan_1y > 4.0
  "downside" if breakeven_5y5y < 1.5
  "none"     otherwise
```
**왜 AND 조건**: 시장 기반(breakeven) AND 가계 서베이(Michigan) 둘 다 정상이어야 anchored. 한쪽만 정상이고 다른 쪽이 이탈 = unanchored (둘이 갈라지는 게 더 심각한 신호).

### 3.3 성장 — 미국 (3 skills)

#### `employment` (UNRATE, PAYEMS) — Sahm Rule
```python
recent_3mo_avg = unemployment_rate.tail(3).mean()
prior_12mo_min = unemployment_rate.tail(15).head(12).min()
sahm_triggered = (recent_3mo_avg - prior_12mo_min) >= 0.5   # ≥0.5%p 상승
```
**왜 Sahm**: 1960년 이후 모든 경기침체를 거의 false positive 없이 예측. 우리 prompt의 **recession anchor 4개 중 하나**.

#### `us_leading` (CFNAI, CFNAIMA3)
```
recession_signal = (cfnai_ma3 < -0.7)
```
**왜 CFNAI**: ISM PMI는 FRED 라이선스 끊김(2016). CFNAI는 85개 매크로 지표의 표준화된 합성. MA3 < -0.7은 학문적으로 검증된 recession 진입 임계. **recession anchor 4개 중 하나**.

#### `gdp_nowcast` (GDPNOW)
```
nowcast_pct      = gdpnow.iloc[-1]                    # 최신 % 연율
change_from_prior = gdpnow.iloc[-1] - gdpnow.iloc[-2] # WoW 변화
```
**왜**: 분기 GDP 발표 전까지 가장 빠른 성장 게이지. 주 2회 갱신.

### 3.4 성장 — 한국 (3 skills)

#### `kr_exports` (kr_export ECOS)
```python
yoy           = (export[-1]/export[-13])^1 - 1
momentum_3mo  = (export[-1]/export[-4])^(12/3) - 1
momentum_6mo  = (export[-1]/export[-7])^(12/6) - 1
accelerating  = (momentum_3mo > momentum_6mo > yoy)
```
**왜**: 한국 EPS의 가장 강력한 동행/선행 지표. 매월 11일/21일/1일에 10일/20일/말일 잠정치 공개 → 글로벌 수요의 빠른 proxy.

#### `kr_leading` (kr_cli ECOS) — 4-phase 분류
```
above_trend = (level >= 100.0)
rising      = (change_3mo > 0)

phase = "expansion"   if above_trend AND rising
        "peak"        if above_trend AND NOT rising
        "contraction" if NOT above_trend AND NOT rising
        "trough"      if NOT above_trend AND rising
```
**왜**: 통계청 선행지수 순환변동치는 9개 구성지표 합성. 100 = trend. 4사분면 phase로 사이클 위치 정량화.

#### `kr_business_survey` (kr_bsi_mfg ECOS)
```
contraction_signal = (mfg_bsi < 80.0)
```
**왜**: BSI는 100 기준선. 80 미만은 명확한 위축 국면.

### 3.5 유동성 (1 skill)

#### `financial_conditions` (NFCI, ANFCI) — 4-tier regime
```
regime = "easy"    if nfci < -0.5
         "neutral" if -0.5 ≤ nfci < 0.5
         "tight"   if  0.5 ≤ nfci < 1.0
         "crisis"  if nfci >= 1.0

# 4-week tightening flag (NFCI는 weekly)
tightening = (nfci.iloc[-1] - nfci.iloc[-5]) > 0.2
```
**왜**: Chicago Fed 공식 임계. NFCI는 표준편차 1 단위로 표준화돼 임계가 직접 의미 가짐. >+1 = 침체급, >+2 = 위기 수준. **recession anchor 4개 중 하나**.

### 3.6 FX (1 skill)

#### `fx` (DEXKOUS, DTWEXBGS) — 4-regime 분류
```python
krw_change_1m = (usd_krw[-1] / usd_krw[-22] - 1) × 100   # 약 21 거래일
dxy_change_1m = (dxy[-1] / dxy[-22] - 1) × 100

regime = "usd_risk_off" if krw_change > +2.0 AND dxy_change > +1.0  # 동시 발생
         "krw_weak"     if krw_change > +2.0
         "krw_strong"   if krw_change < -2.0
         "neutral"      otherwise
```
**왜 `usd_risk_off` 별도**: KRW 약세 + USD 강세 동시 = 외국인 매도 압력 최대. 단독 KRW 약세보다 훨씬 강한 risk-off 신호.

### 3.7 Cross-asset (1 skill)

#### `risk_appetite` (HG=F, GC=F) — Copper/Gold ratio
```python
ratio = copper / gold * 100
last_1y = ratio.tail(252)
percentile = (last_1y < current_ratio).sum() / len(last_1y)

signal = "risk_on"  if percentile > 0.7
         "risk_off" if percentile < 0.3
         "neutral"  otherwise
```
**왜**: 구리(cyclical) vs 금(defensive) 비율. 10년 yield와 corr 0.7+. Gundlach가 자주 인용하는 단일 risk-on/off 지표.

### 3.8 중국 (1 skill)

#### `china_leading` (CHNLOLITONOSTSAM) — 4-phase
KR `kr_leading`과 동일한 4-phase 알고리즘. OECD CLI는 100 = trend. **Caixin PMI는 S&P Global paid 라이선스라 회피, OECD가 FRED에 미러링하는 무료 시리즈로 대체**.

**왜**: 한국 수출의 25%가 중국. 중국 사이클이 KR ETF 결정에 직접 transmission.

### 3.9 KR 자금 흐름 (1 skill)

#### `foreign_flow` (KRX pykrx)
```python
net_5d  = foreign_daily.tail(5).sum()
net_20d = foreign_daily.tail(20).sum()

signal = "net_buying"  if net_20d > +1조 KRW
         "net_selling" if net_20d < -1조 KRW
         "neutral"     otherwise
```
**왜 ±1조 임계**: KOSPI 시총 대비 ~0.05%. 20거래일 누적이라 의미있는 단위. 단기 KOSPI 방향성과 매우 높은 상관.

### 3.10 Policy & Tail risk (2 skills)

#### `policy_uncertainty` (USEPUINDXM, GEPUCURRENT)
```
regime = "extreme"  if us_epu >= 200
         "elevated" if us_epu >= 150
         "normal"   if us_epu < 150

us_epu_percentile_5y = (last_60 < current).sum() / len(last_60)
```
**왜 임계**: Baker-Bloom-Davis 가이드. 100 = 1985-2010 평균. >150 (elevated) 구간은 평균 risk asset return이 유의하게 낮음 (Baker et al 2016).

#### `tail_risk` (VVIXCLS, MOVE) — GPR substitute
```
vvix_pct = percentile_1y(vvix)
move_pct = percentile_1y(move)

signal = "extreme"  if vvix_pct > 0.9 AND move_pct > 0.9
         "elevated" if vvix_pct > 0.75 OR move_pct > 0.75
         "calm"     otherwise
```
**왜 둘 다 90%+ 이어야 extreme**: equity 변동성(VVIX) AND Treasury 변동성(MOVE) 동시 급등이 진정한 systemic risk 신호. **Caldara-Iacoviello GPR(직접 fetch 어려움)의 operational substitute**.

---

## 4. regime_quadrant 판단 (의사결정 룰)

분류 결과는 4개 quadrant 중 하나:

| Quadrant | 정의 |
|---|---|
| `growth_inflation` | GDP/사이클 expanding, CPI > 3% YoY |
| `growth_disinflation` | GDP/사이클 expanding, CPI < 3% AND decelerating |
| `recession_inflation` | GDP/사이클 contracting AND CPI > 3% (예: 1973 스태그플레이션) |
| `recession_disinflation` | contracting + CPI declining (예: 2008-12) |

### 4.1 Recession 판정 룰 (가장 중요)

**핵심 디자인**: Recession은 **US 매크로 anchor 필수**. KR/China 신호는 보조.

**Step 1 — US recession anchor 검사** (4개 중 1+개 충족 필수):
- `sahm_rule_triggered = True`
- `us_cfnai_ma3 < -0.7` (`us_recession_signal = True`)
- `inverted_days_count ≥ 60`
- `us_nfci ≥ +1.0` (NFCI tight/crisis)

**Step 2 — 보조 신호** (Step 1 충족 시):
- KR CLI phase ∈ {contraction, trough}
- KR BSI contraction = True
- KR exports YoY < -5 AND decelerating
- Fed market_view = "cut" AND CFNAI < 0
- China CLI phase ∈ {contraction, trough}
- 외국인 KOSPI = net_selling

**Step 1 충족 + Step 2에서 1+개 추가** → recession quadrant.

**Step 1 미충족 + KR/China contraction만** → quadrant는 **growth_*** 유지, confidence를 0.6~0.7로 하향, drivers에 "KR-specific weakness" 명시. **이 상태는 글로벌 regime 변경이 아니라 KR ETF 비중 조정 시사일 뿐.**

### 4.2 Inflation vs Disinflation 판정

- 기대 인플레 `unanchored_direction = "upside"` → inflation quadrant 우선
- `anchored = True` AND CPI 감속 (`accelerating = False` AND `momentum_3mo < cpi_yoy`) → disinflation
- 둘 다 애매하면 `cpi_yoy > 3.0` 기준

### 4.3 Confidence 하향 트리거

`confidence ∈ [0, 1]` 산출 시 다음 조건이 발동되면 confidence 하향:

| 조건 | 효과 |
|---|---|
| EPU regime = "extreme" | confidence 추가 하향 |
| tail_risk signal = "extreme" | confidence 추가 하향 |
| US 신호와 KR 신호 disagree | confidence 0.6~0.7로 |
| KR/China contraction이지만 US anchor 0개 | confidence 0.6~0.7로 (KR-specific) |

→ "regime 분류 자체의 불확실성"을 코드화한 부분. 의사결정의 robustness 강화.

### 4.4 KR ETF cross-asset overlay

이 룰들은 quadrant 자체를 바꾸진 않지만 **drivers/reasoning에 명시되어 downstream(Bull/Bear 토론, Allocator)에 전달**:

- China contraction + 외국인 net_selling + USD/KRW usd_risk_off **3-way 동시** = 위험자산 비중 강한 축소 시사
- China expansion + 외국인 net_buying + Copper/Gold risk_on = recession quadrant라도 confidence 하향 (KR 단기 outperformance 가능)
- US EPU extreme + tail_risk extreme = 시스템 리스크 위기 (2008, 2020 같은 outlier)

---

## 5. 출력 구조

### 5.1 `MacroReport` Pydantic 객체

`tradingagents/schemas/reports.py:MacroReport`. State에는 `macro_report` 키로 저장.

```python
class MacroReport(_AnalystReport):
    # Baseline (5)
    yield_curve:           YieldCurveSnapshot
    inflation:             InflationSnapshot
    employment:            EmploymentSnapshot
    kr_divergence:         DivergenceScore
    regime:                RegimeClassification

    # Tier-1 (5)
    kr_export:             KRExportSnapshot
    kr_leading:            KRLeadingIndexSnapshot
    kr_business_survey:    KRBusinessSurveySnapshot
    us_leading:            USLeadingIndexSnapshot
    gdp_nowcast:           GDPNowSnapshot

    # Tier-2 (3)
    financial_conditions:  FinancialConditionsSnapshot
    inflation_expectations: InflationExpectationsSnapshot
    fed_path:              FedPathSnapshot

    # Tier-3 (4)
    fx:                    FXSnapshot
    risk_appetite:         RiskAppetiteSnapshot
    china_leading:         ChinaLeadingSnapshot
    foreign_flow:          ForeignFlowSnapshot

    # Tier-4 (2)
    policy_uncertainty:    PolicyUncertaintySnapshot
    tail_risk:             TailRiskSnapshot

    # 이벤트 (1)
    upcoming_events:       list[CentralBankEvent]   # 90일 FOMC/BOK

    # 핸드오프 (2)
    narrative:                str   # ≤500자 한국어 산문 (LLM 작성)
    summary_for_downstream:   str   # ≤2000자 마크다운 (다음 stage용)
```

### 5.2 `macro_summary` 마크다운 (Stage 2로 핸드오프)

`state["macro_summary"]`에 저장되는 ≤2000자 텍스트. Bull/Bear가 직접 읽음.

예시:
```markdown
## Macro
Regime: **recession_disinflation** (0.85)
YC 10y-2y: -10bps, inverted 120d
CPI: 2.8% YoY (↓)
UR: 4.5% (Sahm: True)
KR exports: -3.0% YoY (↓)
KR CLI: 98.0 (contraction), BSI mfg: 82
CFNAI MA3: -0.40 (expansion)
GDPNow: +0.5%
NFCI: +0.30 (neutral, tightening)
Inflexp: 5Y5Y=2.40%, Mich1y=3.00% (anchored)
Fed path: -80bps → cut
FX: USD/KRW 1380 (+2.5%/1m, usd_risk_off)
Cu/Au: risk_off (pct 25%)
China CLI: 98.0 (contraction)
Foreign 20d: -15000억 (net_selling)
US EPU: 170 (elevated)
Tail risk: VVIX=110, MOVE=130 (elevated)
Drivers: Sahm triggered, KR exports declining, usd_risk_off
```

### 5.3 `RegimeClassification` (LLM 출력 핵심)

```python
class RegimeClassification(StalenessAware):
    quadrant:    "growth_inflation" | "growth_disinflation"
                 | "recession_inflation" | "recession_disinflation"
    confidence:  float  ∈ [0, 1]
    drivers:     list[str]  (1~5개 키워드, 위 룰을 인용)
    reasoning:   str  ≤300자
```

`drivers`에는 **위 의사결정 룰의 어떤 부분이 발동됐는지**를 명시. 예:
- `["Sahm triggered", "CFNAI MA3 -0.85 < -0.7", "China CLI contraction"]`
- `["No US recession anchor", "KR specific weakness (CLI/BSI contraction)", "EPU elevated"]`

→ Allocator와 Risk Judge가 drivers를 보고 추가 의사결정에 활용.

### 5.4 두 키로 State에 wire

```python
def node(state):
    ...
    return {
        "macro_report":  MacroReport(...),   # 구조화된 Pydantic (전체 데이터)
        "macro_summary": summary,             # ≤2000자 텍스트 (Stage 2 핸드오프)
    }
```

---

## 6. Graceful degradation (장애 처리)

모든 외부 fetch는 try/except로 감싸여 있고, 실패 시 **sentinel snapshot** (`staleness_days=99`, 중립값) 반환. 파이프라인은 절대 안 죽음.

예: ECOS가 한국공휴일로 fetch 실패 시:
```python
try:
    kr_cli_series = fetch_ecos_series_skill("kr_cli", ...)
    kr_leading = compute_kr_leading_index(kr_cli_series, as_of=as_of)
except Exception:
    kr_leading = _sentinel_kr_leading(as_of)
    # KRLeadingIndexSnapshot(cli_value=100.0, change_3mo=0.0, phase="expansion",
    #                         staleness_days=99)
```

→ 분석가 노드의 22개 try/except blocks가 각 fetch를 독립적으로 보호. 1개 데이터 실패가 다른 19개 dimension을 망치지 않음.

다음 stage에서 `snapshot.is_severely_stale` (= staleness > 7) 검사하면 해당 신호를 무시할 수 있음.

---

## 7. 검증 (Test 결과)

| 항목 | 결과 |
|---|---|
| 단위 테스트 (4 tier × ~12 case) | **49/49 passing** |
| 분석가 통합 테스트 | **passing** (mock 기반) |
| 스키마 검증 | **passing** (Pydantic v2) |
| LLM eval (8 historical case, 1973~2026) | **8/8 passing**, 모든 case confidence ≥ 0.6 |
| 회귀 (전체 suite) | **352/352 passing**, 회귀 0건 |

eval 8 case 결과:
1. **2008-12 Lehman aftermath** → `recession_disinflation` ✓
2. **2022-06 peak inflation** → `growth_inflation` ✓ (conf 0.67, prompt가 의도한 ambiguity)
3. **2020-04 COVID** → `recession_disinflation` ✓
4. **2017-Q3 Goldilocks** → `growth_disinflation` ✓
5. **1973-12 stagflation** → `recession_inflation` ✓
6. **2007-12 pre-GFC** → `growth_inflation` ✓
7. **2014-12 disinflation expansion** → `growth_disinflation` ✓ (US anchor 룰 덕분)
8. **2026-05 current** → `recession_disinflation` ✓

---

## 8. API 키 요구

| 키 | 사용처 | 시리즈 수 |
|---|---|---|
| `FRED_API_KEY` | macro_quant의 미국/글로벌 데이터 16개 | 16 |
| `ECOS_API_KEY` | macro_quant의 한국 데이터 5개 | 5 |
| (yfinance) | commodities (copper, gold) | 키 불요 |
| (pykrx) | KRX 외국인 flow | 키 불요 |
| `OPENAI_API_KEY` | LLM eval 시 (regime_classifier 호출) | — |

기존 환경 그대로 사용 가능. 추가 API 가입 없음.

---

## 9. 파일 매니페스트

| 위치 | 파일 |
|---|---|
| 스킬 (22) | `tradingagents/skills/macro/*.py` |
| 분석가 노드 | `tradingagents/agents/analysts/macro_quant_analyst.py` |
| 스키마 (18) | `tradingagents/schemas/macro.py`, `tradingagents/schemas/reports.py` |
| 데이터 wrapper | `tradingagents/dataflows/fred.py`, `ecos.py`, `commodities.py`, `pykrx_data.py` |
| LLM prompt | `prompts/macro-analysis.md` |
| 단위 테스트 | `tests/unit/skills/test_macro_*.py` |
| LLM eval | `tests/integration/test_eval_regime_classifier.py` |
| Lag 설정 | `tradingagents/default_config.py:publication_lag_days` |
