# Stage 1 — Macro Quant Analyst

> 파이프라인 6 stage 중 첫 단계의 4명 병렬 분석가 중 하나. 매크로 환경을 정량 진단해서 다음 stage(Bull/Bear 토론)와 그 이후 모든 단계의 기준 신호를 만들어낸다.

---

## 1. 한 줄 요약

> **27개 데이터 시리즈를 21개 skill로 가공해 21개 dimension의 macro snapshot을 만들고, LLM에게 넘겨 4 quadrant 중 하나로 현재 매크로 regime을 분류한다.** (2026-05 indicator 정비: PCE/JOLTS/LFPR/USDCNH/iron ore 추가, EPU deprecated.)

---

## 2. 어떤 데이터를 보는가 (27개 시리즈)

### 2.1 FRED (미국 St. Louis Fed, 21 시리즈)

| 친근명 | FRED ID | 빈도 | 의미 |
|---|---|---|---|
| `us_10y` | DGS10 | daily | 10년 국채 수익률 |
| `us_2y` | DGS2 | daily | 2년 국채 수익률 |
| `us_3m` | DGS3MO | daily | 3개월 단기 |
| `us_cpi` | CPIAUCSL | monthly | 헤드라인 CPI |
| `us_core_cpi` | CPILFESL | monthly | 코어 CPI |
| **`us_pce`** | **PCEPI** | monthly | **PCE deflator — Fed 공식 inflation 타겟 (2026-05 추가)** |
| **`us_core_pce`** | **PCEPILFE** | monthly | **Core PCE — Powell이 자주 인용하는 핵심 지표** |
| `us_unrate` | UNRATE | monthly | 실업률 |
| `us_payems` | PAYEMS | monthly | 비농업 고용 |
| **`us_lfpr`** | **CIVPART** | monthly | **노동참여율 (Sahm rule cross-check, 2026-05)** |
| **`us_jolts_openings`** | **JTSJOL** | monthly | **JOLTS Job Openings — labor 수요 leading (2026-05)** |
| **`us_jolts_quits`** | **JTSQUR** | monthly | **JOLTS Quits Rate — labor tightness 핵심 (2026-05)** |
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
| ~~`us_epu`~~ | ~~USEPUINDXM~~ | monthly | **DEPRECATED 2026-05 — 학술 지표, 실무 약함. VIX/credit이 우월** |
| ~~`global_epu`~~ | ~~GEPUCURRENT~~ | monthly | **DEPRECATED — 동일 이유** |

### 2.2 ECOS (한국은행, 5 시리즈)

| 친근명 | ECOS 코드 | 빈도 | 의미 |
|---|---|---|---|
| `kr_base_rate` | 722Y001 / 0101000 | daily | 한국 기준금리 |
| `kr_cpi` | 901Y009 / 0 | monthly | 한국 CPI |
| `kr_export` | 403Y001 / *AA | monthly | 한국 총 수출액 |
| `kr_cli` | 901Y067 / I16D | monthly | 통계청 선행지수 순환변동치 |
| `kr_bsi_mfg` | 512Y014 / X8000/BA | monthly | 한국은행 제조업 업황 BSI (multi-dim) |

### 2.3 yfinance (글로벌 markets, 6 시리즈)

| 친근명 | yf 티커 | 의미 |
|---|---|---|
| `copper` | HG=F | COMEX 구리 선물 (USD/lb) — Cu/Au ratio |
| `gold` | GC=F | COMEX 금 선물 (USD/oz) — Cu/Au ratio |
| `vvix` | ^VVIX | CBOE VIX-of-VIX (tail risk, 2026-05 FRED VVIXCLS 폐지 후 이전) |
| `move` | ^MOVE | ICE BofA Treasury volatility (tail risk, 동일 사유) |
| **`usdcnh`** | **CNH=X** | **USD/CNH offshore — China 정책/경제 실시간 신호 (2026-05)** |
| **`iron_ore`** | **TIO=F** | **SGX iron ore futures — China 건설 수요 proxy (2026-05)** |

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

#### `inflation` (CPI, Core CPI, PCE, Core PCE)
```python
# CPI 기반 (시장이 보는 헤드라인)
yoy            = (cpi[-1]/cpi[-13])^(12/12) - 1        # 12개월 YoY
momentum_3mo   = (cpi[-1]/cpi[-4])^(12/3)  - 1         # 3개월 연율화
momentum_6mo   = (cpi[-1]/cpi[-7])^(12/6)  - 1
accelerating   = (momentum_3mo > momentum_6mo > yoy)   # 볼록성 = 가속

# PCE 기반 (Fed 정책 anchor, 2026-05 추가)
pce_yoy            = (pce[-1]/pce[-13])^1 - 1
core_pce_yoy       = (core_pce[-1]/core_pce[-13])^1 - 1
pce_momentum_3mo   = (core_pce[-1]/core_pce[-4])^(12/3) - 1   # Powell 자주 인용
```
**해석**: `accelerating=True`는 단기가 장기보다 빠르다는 볼록성 신호. Fed 인상 확률 급등 트리거.
**왜 PCE 추가**: **Fed 공식 inflation 타겟은 CPI가 아니라 Core PCE**. CPI는 housing weight가 높아 lagging, PCE는 service consumption 가중이 더 균형. 두 지표가 갈라지면(예: CPI 가속 + Core PCE 감속) Fed는 PCE 우선. 정책 결정 anchor.

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

#### `employment` (UNRATE, PAYEMS, LFPR, JOLTS) — Sahm Rule + LFPR cross-check + JOLTS
```python
# Sahm rule (1960~ 검증)
recent_3mo_avg = unemployment_rate.tail(3).mean()
prior_12mo_min = unemployment_rate.tail(15).head(12).min()
sahm_raw       = (recent_3mo_avg - prior_12mo_min) >= 0.5

# 2026-05 추가 — LFPR cross-check (false-positive 방지).
# Sahm 발동인데 LFPR이 +0.2pp 이상 상승 = 노동공급 증가로 UR 상승 흡수.
# → 침체 신호 아님 (2024년 7월 false alarm 패턴).
if sahm_raw AND (lfpr 6개월 변화) > +0.2:
    sahm_triggered = False  # downgrade
else:
    sahm_triggered = sahm_raw

# 2026-05 추가 — JOLTS labor tightness (leading indicators)
job_openings_3mo_avg = jolts_openings.tail(3).mean()    # 천 명 단위
quits_rate            = jolts_quits.iloc[-1]              # % of employment
quits_rate_change_6mo = quits_rate - jolts_quits.iloc[-7]
```
**왜 Sahm**: 1960년 이후 모든 경기침체를 거의 false positive 없이 예측. 우리 prompt의 **recession anchor 4개 중 하나**. 단 2024년 first false alarm 이후 LFPR cross-check 필수.
**왜 JOLTS**: Sahm/UR은 lagging. **JOLTS Job Openings + Quits Rate는 노동시장 cooling을 6-12개월 leading**. Powell이 2022-2024년 wage-price spiral 진단 시 가장 강조한 series.

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

### 3.8 중국 (1 skill, 2026-05 보강)

#### `china_leading` (OECD CLI + USDCNH + iron ore)
```python
# 1) OECD CLI 4-phase (lag 2-3개월)
above_trend = (cli >= 100.0)
rising      = (change_3mo > 0)
phase = "expansion" / "peak" / "contraction" / "trough"

# 2) 2026-05 보강 — USDCNH 1m change + iron ore 3m change
usdcnh_chg_1m  = (usdcnh[-1]/usdcnh[-22] - 1) × 100
iron_chg_3m    = (iron[-1]/iron[-64] - 1) × 100

# 3) 실시간 합성 신호 (CLI lag 보정)
weak_yuan   = (usdcnh > 7.30) OR (usdcnh_chg_1m > +1.5)
iron_down   = (iron_chg_3m < -10)
iron_up     = (iron_chg_3m > +5)
stable_yuan = (usdcnh < 7.20) OR (usdcnh_chg_1m < +0.5)

realtime_signal = "contraction" if weak_yuan OR iron_down
                  "expansion"   if stable_yuan AND iron_up
                  "neutral"     otherwise
```
**왜 보강 필요**: OECD CLI는 **2-3개월 publication lag**. 단독으로는 너무 느림. **실무 표준은 Caixin Manufacturing PMI**지만 free institutional API가 부족 — daily 시장 proxies (위안화 + iron ore)로 lag 보정.
**왜 USDCNH**: 위안 약세 = PBoC fixing 완화 = 정책/경제 우려 신호. PBoC가 fixing rate로 미세 정책 발신.
**왜 iron ore**: 중국이 글로벌 iron ore 수요의 ~70%. 가격 하락 = 건설/제조 demand 약화 직접 proxy.
**왜 한국에 중요**: 한국 수출의 25%가 중국. 중국 사이클이 KR ETF 결정에 직접 transmission.

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

### 3.10 Tail risk (1 skill, EPU 2026-05 deprecated)

> ~~`policy_uncertainty` (EPU)~~ **DEPRECATED 2026-05**. Baker-Bloom-Davis EPU는 학술 지표로 institutional 실무에서 거의 안 쓰임. (1) 2020+ 평균이 이미 ~180으로 "elevated" 임계가 무의미해졌고, (2) 시장 기반 uncertainty proxies(VIX/MOVE/credit spread/SKEW)가 더 빠르고 정확. Schema에는 호환성을 위해 남겨두지만 sentinel만 채워지고 regime_classifier prompt에 전달되지 않음.

#### `tail_risk` (^VVIX, ^MOVE — yfinance) — GPR substitute
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
| tail_risk signal = "extreme" (VVIX + MOVE 동시 90th+) | confidence 추가 하향 |
| US 신호와 KR 신호 disagree | confidence 0.6~0.7로 |
| KR/China contraction이지만 US anchor 0개 | confidence 0.6~0.7로 (KR-specific) |
| CPI accelerating ↑ but Core PCE decelerating ↓ (2026-05) | confidence 하향 (Fed 타겟 vs 헤드라인 분기) |
| Sahm raw triggered but LFPR rising > +0.2pp/6m (2026-05) | sahm flag downgrade, confidence 0.6~0.7 (labor supply 회복) |

→ "regime 분류 자체의 불확실성"을 코드화한 부분. 의사결정의 robustness 강화.

### 4.4 KR ETF cross-asset overlay

이 룰들은 quadrant 자체를 바꾸진 않지만 **drivers/reasoning에 명시되어 downstream(Bull/Bear 토론, Allocator)에 전달**:

- China contraction (CLI **OR** USDCNH > 7.30 **OR** iron ore 3m < -10%) + 외국인 net_selling + USD/KRW usd_risk_off **3-way 동시** = 위험자산 비중 강한 축소 시사
- China expansion (CLI + realtime 동조) + 외국인 net_buying + Copper/Gold risk_on = recession quadrant라도 confidence 하향 (KR 단기 outperformance 가능)
- tail_risk extreme (VVIX + MOVE 동시 90th+) = 시스템 리스크 위기 (2008, 2020, 2022 같은 outlier)

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
Core PCE: 2.5% YoY (3m ann 2.1%) — Fed 타겟
UR: 4.5% (Sahm: True) JOLTS: openings 7.2M, quits 1.8% (-0.20/6m)
KR exports: -3.0% YoY (↓)
KR CLI: 98.0 (contraction), BSI mfg: 82
CFNAI MA3: -0.40 (recession)
GDPNow: +0.5%
NFCI: +0.30 (neutral, tightening)
Inflexp: 5Y5Y=2.40%, Mich1y=3.00% (anchored)
Fed path: -80bps → cut
FX: USD/KRW 1380 (+2.5%/1m, usd_risk_off)
Cu/Au: risk_off (pct 25%)
China CLI: 98.0 (contraction) | USDCNH 7.35 (+1.8%/1m), iron 95 (-15.0%/3m) → realtime contraction
Foreign 20d: -15000억 (net_selling)
Tail risk: VVIX=110, MOVE=130 (elevated)
Drivers: Sahm triggered (LFPR confirmed), Core PCE decel, KR exports declining, China realtime contraction, usd_risk_off
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

## 6.5 Hardcoded 임계값 caveat (2026-05 audit)

Stage 1 코드에는 **공식 학술 임계**(Sahm 0.5pp, CFNAI -0.7) 외에 **우리 자의적 임계**도 일부 포함. 분류와 update 정책:

### 🔴 자동 갱신 메커니즘 적용됨 (#1 fix)

| 위치 | 임계 | 갱신 방식 |
|---|---|---|
| `cb_speaker_tracker.py::FED_VOTING_BY_YEAR` | Fed regional president voting 회전 | 연도별 set 별도 보유 + `as_of.year` lookup. 매년 1월 manual update |

### 🟡 임의 임계 (calibration TODO — 주석에 명시됨)

| 위치 | 임계 | 비고 |
|---|---|---|
| `trend_quantification.py::_trend_strength` | 가중치 (0.40/0.30/0.20/0.10) + 정규화 분모(/10, /50) | 합 1.0이 되도록 임의 선택. Stage 3 backtest로 calibrate TODO. |
| `us_leading.py::MODERATE/SEVERE_THRESHOLD` | -1.5 / -2.5 (CFNAI 강도) | -0.7만 Chicago Fed 공식. 나머지는 우리 추가. |
| `china_leading.py::_realtime_signal` | USDCNH 7.20/7.30, iron ±5%/±10% | Caixin PMI free 가용 시 PMI 50 기준선으로 calibrate 권장. |
| `fed_path.py::DEFAULT_BAND_BPS + floor/ceil` | 25 / 150 bps clamp | CME FedWatch 직접 fetch가 더 정확. 통합 TODO. |
| `kr_margin_debt.py::EUPHORIA_*/DELEVERAGING_*` | 0.85 pct + 10% / -15% | 2021 single observation calibration. 다른 시기 사례 부족. |
| `inflation_expectations.py::*_ANCHOR_*` | breakeven 1.5~3.0, michigan 2.0~4.0 | Fed 2% 타겟 기반. 타겟 변경 시 update 필요. |

### 🟢 OK (공식/표준)

- Sahm rule 0.5pp (Claudia Sahm), CFNAI -0.7 (Chicago Fed)
- 모든 percentile cutoffs (0.20/0.70/0.80/0.85/0.90) — 통계 컨벤션
- NFCI 임계 (Chicago Fed 공식)
- Indicator 표준 파라미터 (RSI 14, MACD 12/26/9, Bollinger 20/2σ)

→ 모든 🟡 항목은 소스 파일에 `⚠️ HARDCODED CAVEAT` 주석으로 위치 표기. LLM이 raw 임계 의존하지 않고 percentile 보조 + cross-check 신호로 흡수.

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
| `FRED_API_KEY` | macro_quant의 미국/글로벌 데이터 21개 | 21 |
| `ECOS_API_KEY` | macro_quant의 한국 데이터 5개 | 5 |
| (yfinance) | commodities + tail risk + China (Cu/Au/VVIX/MOVE/USDCNH/iron) | 키 불요 |
| (pykrx) | KRX 외국인 flow | 키 불요 |
| `KRX_ID` / `KRX_PW` | KRX 일부 endpoint (foreign flow 등 더 안정적 fetch) | — |
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
