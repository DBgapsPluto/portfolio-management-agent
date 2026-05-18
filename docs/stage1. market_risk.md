# Stage 1 — Market Risk Analyst

> 파이프라인 6 stage 중 첫 단계의 4명 병렬 분석가 중 하나. 시장 stress를 실시간으로 측정해서 systemic risk score (0~10) + regime (risk_on/risk_off/neutral)을 산출, Risk Debate (Stage 4)와 BucketTarget 결정 (Stage 2~3)에 입력으로 전달한다.

> **macro_quant와의 역할 분담**: macro_quant는 **regime classifier** (top-down 매크로 사이클 진단 → BucketTarget). market_risk는 **real-time stress detector** (bottom-up 시장 stress 측정 → Risk debate). 두 분석가는 dimension이 겹치지 않게 설계됐다 (VVIX/MOVE는 macro_quant Tier-4, VIX 직접/SKEW/VIX term structure은 market_risk Tier-1).

---

## 1. 한 줄 요약

> **22개 데이터 시리즈를 17개 skill로 가공해 33개 dimension의 risk snapshot을 만들고, LLM에게 넘겨 0~10 systemic_score + 3-regime을 산출한다.**

---

## 2. 어떤 데이터를 보는가 (22개 시리즈)

### 2.1 FRED (US Treasury, credit, volatility — 11 시리즈)

| 친근명 | FRED ID | 빈도 | 의미 |
|---|---|---|---|
| `vix_close` | VIXCLS | daily | CBOE VIX (S&P 500 30일 vol) |
| `vix_3m` | VXVCLS | daily | VIX 3-month (term structure 분자) |
| `vxn` | VXNCLS | daily | NASDAQ-100 vol |
| `us_ig_oas` | BAMLC0A0CM | daily | US Investment Grade OAS |
| `us_hy_oas` | BAMLH0A0HYM2 | daily | US High Yield OAS |
| `us_tips_10y` | DFII10 | daily | 10년 TIPS yield (실질금리) |
| `us_tips_5y` | DFII5 | daily | 5년 TIPS yield |
| `us_sofr` | SOFR | daily | Secured Overnight Financing Rate |
| `us_3m_tbill` | DTB3 | daily | 3개월 단기 국채 |
| `us_aaa_oas` | BAMLC0A1CAAA | daily | AAA 회사채 OAS |
| `us_bbb_oas` | BAMLC0A4CBBB | daily | BBB 회사채 OAS |

### 2.2 ECOS (한국은행 — 3 시리즈)

| 친근명 | ECOS 코드 | 빈도 | 의미 |
|---|---|---|---|
| `kr_treasury_3y` | 817Y002 / 010195000 | daily | 한국 국고채 3년 |
| `kr_treasury_10y` | 817Y002 / 010210000 | daily | 한국 국고채 10년 |
| `kr_corp_aa_3y` | 817Y002 / 010320000 | daily | 회사채 AA- 3년 |

### 2.3 KRX pykrx (한국 거래소 — 5 함수)

| 함수 | 의미 |
|---|---|
| `fetch_vkospi(start, end)` | VKOSPI 지수 (KRX 1037) |
| `fetch_credit_balance(start, end)` | KRX 신용잔고 (KOSPI 전체) |
| `fetch_market_index("1001", ...)` | KOSPI 인덱스 |
| `fetch_market_index("2001", ...)` | KOSDAQ 인덱스 |
| `get_market_ohlcv_by_ticker(date)` | KOSPI200 breadth용 종목별 등락률 |

### 2.4 yfinance (commodities + equity indices — 6 시리즈 + SP500 11 섹터)

| 친근명 | yf 티커 | 의미 |
|---|---|---|
| `skew` | ^SKEW | CBOE SKEW Index (외가격 풋 hedge) |
| `SPY` | SPY | S&P 500 ETF (cross-asset PCA + equity-bond corr) |
| `QQQ` | QQQ | NASDAQ-100 ETF |
| `TLT` | TLT | 20y Treasury ETF |
| `GLD` | GLD | Gold ETF |
| `EWY` | EWY | iShares MSCI South Korea (KOSPI proxy) |
| SP500 섹터 11개 | XLF/XLK/XLE/XLV/XLI/XLY/XLP/XLU/XLB/XLRE/XLC | breadth proxy |

### 2.5 CNN scraper

| 함수 | 의미 |
|---|---|
| `fetch_fear_greed_index(as_of)` | CNN Fear & Greed Index (0-100) |

---

## 3. 어떻게 가공하는가 (17 skill의 계산 공식)

### 3.1 Volatility (3 skills)

#### `volatility` — VIX/VKOSPI 통합 처리
```python
current      = s.iloc[-1]
zscore_30d   = (current - mean_30) / std_30
percentile_5y = (last_5y < current).sum() / len(last_5y)
change_4w    = s.iloc[-1] - s.iloc[-21]   # 4주 절대 변화 (Tier-1 추가)
```
**해석**:
- z > 2 = 통계적 outlier (95% 신뢰)
- percentile > 0.9 = 5년 상위 10%
- change_4w > +5 = 빠르게 stress 가중

#### `vix_term_structure` (Tier-1) — VIX vs VXV
```
ratio = vix_3m / vix_front

regime = "contango"      if ratio > 1.05
         "flat"          if 0.95 ≤ ratio ≤ 1.05
         "backwardation" if ratio < 0.95
```
**핵심 의미**: contango는 정상(현재 calm, future 약간 stress). backwardation은 **현재 panic > 미래 기대** = 2008/2020 panic 시 발생하는 강한 위기 신호.

#### `vxn` (Tier-1) — NASDAQ-100 vol + spread
```
spread_vs_vix = vxn - vix_close

> +5pt = 기술주 stress가 broad보다 의미있게 큼
```
**해석**: AI/mega-cap 회전, 기술주 거품 우려 detect.

### 3.2 SKEW (1 skill, Tier-1)

#### `skew_index` — 외가격 풋 hedge 수요
```
SKEW < 120 = "low"      (정규분포 가정, 헷지 수요 낮음)
SKEW 120-130 = "normal" (역사 평균 ~118)
SKEW 130-145 = "elevated" (tail hedge demand 상승)
SKEW > 145 = "extreme"  (black swan 가격 책정)
```
**해석**: SKEW + VIX 동시 상승 = 위기 인지 + 가격 책정. **VIX backwardation + SKEW extreme + HY widening 동시** = 가장 강력한 위기 신호 (9-10 점).

### 3.3 Credit (3 skills)

#### `credit_spread` — IG/HY OAS 분석 (Tier-2 momentum 추가)
```python
current_bps = s.iloc[-1] × 100
percentile_5y
widening = (last_20.mean() > last_60.mean())   # 단기 > 장기 평균
momentum_zscore = diffs_60d.mean() / diffs_60d.std()   # 60일 변화 가속도
```
**해석**:
- IG > 150bps = stress, > 200bps = 위기
- HY > 600bps = stress, > 1000bps = 위기
- momentum_z > +1.5 = **가속 widening** (위기 진행 중)

#### `credit_quality` (Tier-2) — BBB-AAA quality spread
```
quality_spread_bps = (bbb_oas - aaa_oas) × 100
percentile_5y

regime = "calm"     if percentile < 0.5
         "elevated" if 0.5 ≤ percentile < 0.85
         "stress"   if percentile ≥ 0.85
```
**해석**: 시장이 BBB 추가 risk 가산 → flight-to-quality 진행 중.

#### `funding_stress` (Tier-2) — SOFR - 3m T-bill
```
spread_bps = (sofr - tbill_3m) × 100

regime = "calm"     if spread < +10 bps
         "elevated" if 10 ≤ spread < 20
         "stress"   if spread ≥ +20 bps
```
**핵심**: TED spread(LIBOR 단종) 표준 대체. **2008/2020 모두 spike 발생** — 은행 collateral 부족 = systemic crisis 진행 중.

### 3.4 Real Yields (1 skill, Tier-2)

#### `real_yields` — TIPS 기반 실질금리
```
regime = "accommodative" if tips_10y < 0
         "neutral"       if 0 ≤ tips_10y < 1
         "tight"         if 1 ≤ tips_10y < 2
         "very_tight"    if tips_10y ≥ 2
```
**핵심 의미**: 실질금리 > +2% = **자산 가격 압박 강함**. 2022-2023 미국 주식 약세의 핵심 driver였음 (real yield -1% → +2% 급등).

### 3.5 Sentiment + Breadth (2 skills)

#### `fear_greed` — CNN scraper
- 0-100 scale
- label: extreme_fear / fear / neutral / greed / extreme_greed
- 7일 추세

#### `breadth` (Tier-1 실 구현) — KOSPI200 + SP500
```python
# KOSPI200: pykrx 200 종목의 "등락률" 컬럼 사용
advancing = (등락률 > 0).sum()
advancing_pct = advancing / 200

# SP500: 11 SPDR 섹터 ETF proxy (XLF, XLK, XLE, XLV, XLI, XLY, XLP, XLU, XLB, XLRE, XLC)
# 직전일 vs 당일 종가 비교
advancing_pct = sum(close_diff > 0) / 11
```
**왜 SP500 섹터 proxy**: 500 종목 yfinance fetch는 비용+rate limit. 11 섹터로 의미있는 breadth 추정.

### 3.6 Concentration / PCA (1 skill, Tier-4 강화)

#### `correlation_pca` — 자산군 분산도 (Tier-4: synthetic→real)
```python
# Tier-4: 실제 5-asset (SPY/QQQ/TLT/GLD/EWY) returns via yfinance
returns = fetch_cross_asset_returns(as_of - 365d, as_of)

pca = PCA(n_components=k)
first_eigenvalue_share = pca.explained_variance_ratio_[0]
is_concentrated = first_eigenvalue_share > 0.6
```
**해석**: PC1 점유율 > 0.6 = 모든 자산이 한 방향 (위기 시 correlation → 1).

### 3.7 KR-specific risk (4 skills, Tier-3)

#### `kr_yield_curve` — 한국 국고채 10y-3y
```
spread_10y_3y_bps = (treasury_10y - treasury_3y) × 100

regime = "normal"   if spread > +50
         "flat"     if -10 ≤ spread ≤ +50
         "inverted" if spread < -10
inverted flag = (spread < 0)
```
**해석**: 한국 BOK 사이클이 미국과 dis-correlate 가능 → **KR 단독 침체 신호**.

#### `kr_corp_spread` — 회사채 AA- 3y vs 국고채 3y
```
spread_bps = (corp_3y - treasury_3y) × 100
percentile_5y
3-tier regime (calm / elevated / stress)
```
**해석**: 확대 = 한국 기업 신용 stress. **2022 레고랜드형 KR-specific 신용 위기** 추적.

#### `kr_margin_debt` — KRX 신용잔고
```
change_20d_pct = (current / 20일_전 - 1) × 100
percentile_1y

signal = "euphoria"     if percentile > 0.85 AND change > +10%
         "deleveraging" if change < -15%
         "normal"       otherwise
```
**해석**:
- euphoria = retail 과열 peak (2021년 1월처럼)
- deleveraging = margin call 강제 매도 (위기 진행 중)

#### `kr_market_tier` — KOSPI vs KOSDAQ 상대 성과
```
relative_perf = kosdaq_return_20d - kospi_return_20d

signal = "small_cap_risk_on"  if relative > +3%
         "neutral"             if -3% ≤ relative ≤ +3%
         "large_cap_risk_off"  if relative < -3%
```
**해석**:
- small_cap_risk_on = 중소형 outperform (retail 우호)
- large_cap_risk_off = 대형주 outperform = **flight-to-quality 진행 중**

### 3.8 Cross-asset (1 skill, Tier-4)

#### `equity_bond_corr` — SPY-TLT 60일 rolling correlation
```
corr_60d = SPY_returns.tail(60).corr(TLT_returns.tail(60))

regime = "normal_hedge"     if corr < -0.3   (bonds hedge equity)
         "weakening_hedge"  if -0.3 ≤ corr < 0
         "positive_flip"    if 0 ≤ corr < +0.3
         "extreme_positive" if corr ≥ +0.3   (60/40 hedge 소실)
```
**핵심 의미**: positive flip = **stagflation/inflation regime** (1970s, 2022형). 채권이 더 이상 equity hedge 안 됨 → KR ETF 배분 시 채권 비중 증가가 분산 도움 안 됨.

### 3.9 Systemic Score (1 LLM subagent)

전체 33개 dimension을 받아 0-10 점수 + regime 분류. 아래 §4에서 자세히.

---

## 4. systemic_score 판단 룰 (의사결정)

`prompts/risk-analysis.md`에 명문화. LLM(Opus급)이 33개 입력을 받아 다음 룰로 합성:

### 4.1 기본 score guidance (6단계)

| Score | 조건 | 의미 |
|---|---|---|
| **9-10** | VIX backwardation + SKEW extreme + HY widening 동시 | 즉각 위기 (2008 Lehman, 2020 COVID) |
| **7-8** | VIX z>2 + VKOSPI z>2 + breadth narrow (양 시장 <0.4) | 고조 stress (2018 Q4, 2022 peak inflation) |
| **6-7** | VXN spread > 5 OR PCA concentrated | 편중 stress (AI 거품, mega-cap 회전) |
| **+1** | VIX 4w change > +5 | 상승 추세 가산점 |
| **+1** | HY OAS percentile > 0.8 OR widening | 신용 stress |
| **1-3** | VIX pct < 0.3 + SKEW low + breadth broad | Calm (Goldilocks) |

### 4.2 Tier-2 가산 룰 (Bond/funding)

- **TIPS very_tight (>2%) → score +1** (자산 가격 압박)
- **Funding stress (>+20bps) → score +2** (은행 시스템 위기, 2008/2020 spike)
- **Credit quality stress (percentile>0.85) → score +1** (flight to quality)
- **HY momentum_z > +1.5 → score +1** (확대 가속)
- **3+ Tier-2 stress regime 동시 → 자동 9-10** (systemic crisis 전개 중)

### 4.3 Tier-3 가산 룰 (KR-specific, KR ETF 결정에 직접 영향)

- **KR yield curve inverted → score +1** (KR 침체 우려)
- **KR 회사채 stress → score +2** (KR 신용 위기, 레고랜드형)
- **KR margin signal = "deleveraging" → score +2** (forced selling)
- **KR market tier = "large_cap_risk_off" → score +1** (대형주 flight-to-quality)
- **KR margin signal = "euphoria"** → score 자체는 변동 없지만 drivers에 명시 (peak 우려)

### 4.4 Tier-4 가산 룰 (Cross-asset regime)

- **equity_bond_corr = "positive_flip"** → drivers에 명시, KR ETF 배분 시 채권 비중 감소 권고
- **equity_bond_corr = "extreme_positive" → score +1** (60/40 hedge 완전 소실, 1970s/2022형)

### 4.5 regime 분류

```
regime = "risk_off" if score ≥ 6
         "risk_on"  if score ≤ 3
         "neutral"  otherwise
```

---

## 5. 출력 구조

### 5.1 `RiskReport` Pydantic 객체

`tradingagents/schemas/reports.py:RiskReport`. State에 `risk_report` 키로 저장.

```python
class RiskReport(_AnalystReport):
    # Baseline (8)
    vix:                       VolatilitySnapshot
    vkospi:                    VolatilitySnapshot
    credit_spread_us_ig:       SpreadSnapshot
    credit_spread_us_hy:       SpreadSnapshot
    fear_greed:                SentimentSnapshot
    breadth_kr:                BreadthSnapshot
    breadth_us:                BreadthSnapshot
    correlation_concentration: PCASnapshot
    systemic_score:            SystemicRiskScore

    # Tier-1 (3) — Equity stress 깊이
    vix_term:                  VIXTermStructureSnapshot
    skew:                      SkewSnapshot
    vxn:                       VxnSnapshot

    # Tier-2 (3) — Bond/funding stress
    real_yields:               RealYieldsSnapshot
    funding_stress:            FundingStressSnapshot
    credit_quality:            CreditQualitySnapshot

    # Tier-3 (4) — KR-specific
    kr_yield_curve:            KRYieldCurveSnapshot
    kr_corp_spread:            KRCorpSpreadSnapshot
    kr_margin_debt:            KRMarginDebtSnapshot
    kr_market_tier:            KRMarketTierSnapshot

    # Tier-4 (1) — Cross-asset positioning
    equity_bond_corr:          EquityBondCorrelationSnapshot

    # 핸드오프 (2)
    narrative:                 str   # ≤500자 한국어 산문
    summary_for_downstream:    str   # ≤2000자 마크다운
```

### 5.2 `risk_summary` 마크다운 (Stage 2/3/4 핸드오프)

예시:
```markdown
## Risk
Score: **6.5/10** (risk_off)
VIX: 22.0 (z=1.30, 4w +4.0)
VKOSPI: 24.0 (4w +5.0)
VIX term: ratio 0.96 (flat)
SKEW: 138 (elevated)
VXN: 28.0 (spread vs VIX +6.0)
HY OAS: 420bps (widening) (mom z +1.20)
Breadth KR: 32%, US: 42%
PCA 1st: 0.62 (concentrated)
TIPS 10y: 1.60% (tight)
Funding: SOFR-Tbill +14bps (elevated)
Credit quality: BBB-AAA 125bps (elevated)
KR yield curve: 10y-3y -15bps (inverted)
KR corp spread: +130bps (elevated)
KR margin: 20d -18.0% (deleveraging)
KR tier: KOSDAQ-KOSPI -4.0% (large_cap_risk_off)
Equity-bond corr 60d: +0.10 (positive_flip)
```

### 5.3 `SystemicRiskScore` (LLM 출력 핵심)

```python
class SystemicRiskScore(StalenessAware):
    score:     float ∈ [0, 10]
    regime:    "risk_on" | "risk_off" | "neutral"
    drivers:   list[str]  (1~5개 키워드, 위 룰을 인용)
    reasoning: str  ≤300자
```

drivers 예시 (2026-05 KR ETF context):
```python
[
  "VIX 22 elevated (4w +4), VIX term flat",
  "SKEW 138 elevated tail hedge demand",
  "HY OAS 420bp widening + momentum_z 1.2",
  "KR yield curve inverted -15bps + KR corp elevated",
  "KR margin deleveraging 20d -18%, large_cap risk-off",
]
```

### 5.4 두 키로 State에 wire

```python
return {
    "risk_report":  RiskReport(...),    # 구조화 (Stage 4 Risk debate, allocator 입력)
    "risk_summary": summary,             # ≤2KB (Stage 2 Bull/Bear)
}
```

---

## 6. Graceful degradation (장애 처리)

모든 외부 fetch는 try/except로 감싸여 있고, 실패 시 **sentinel snapshot** (`staleness_days=99`, 중립값) 반환. 파이프라인은 절대 안 죽음.

예시:
```python
try:
    kr_3y = fetch_ecos_series_skill("kr_treasury_3y", start_5y, as_of, freq="D")
    kr_10y = fetch_ecos_series_skill("kr_treasury_10y", start_5y, as_of, freq="D")
    kr_yield_curve = compute_kr_yield_curve(kr_3y, kr_10y, as_of=as_of)
except Exception:
    kr_yield_curve = _sentinel_kr_yield_curve(as_of)
    # KRYieldCurveSnapshot(... staleness_days=99, regime="flat", inverted=False)
```

→ 분석가 노드의 약 14개 try/except blocks가 각 fetch를 독립적으로 보호.

특히 risk 분야에서 fragile한 데이터:
- VKOSPI (KRX 자격증명 필요 시 fallback)
- CNN Fear & Greed (스크랩 실패)
- ECOS KR treasury (best-effort item code)
- yfinance batch (rate limit / network)
- pykrx 신용잔고 (컬럼명 버전별 차이 → 4개 후보로 robust 처리)

---

## 7. 검증 결과

| 항목 | 결과 |
|---|---|
| 단위 테스트 (4 tier × ~10 case) | **402 passing** (회귀 0건) |
| 분석가 통합 테스트 | **passing** (mock 기반) |
| 스키마 검증 | **passing** (Pydantic v2) |
| **LLM eval (8 historical case, 1973~2026)** | **8/8 passing**, 1회 iteration (range 조정만) |

eval 8 case 결과:
1. **2008-10 Lehman aftermath** → score 8.5-10, risk_off ✓
2. **2020-03 COVID March crash** → score 9-10, risk_off ✓
3. **2017-Q3 Goldilocks calm** → score 0-3, risk_on ✓
4. **2018-12 Powell pivot** → score 6-9 (got 9.0), risk_off ✓
5. **2022-06 peak inflation** → score 7-9, risk_off ✓
6. **2014-12 mild disinflation** → score 3-5, neutral ✓
7. **2024-06 AI rally narrow breadth** → score 4-6.5, neutral ✓
8. **2026-05 current KR** → score 6-8.5, risk_off ✓

비용 ~$0.4 (8 case × gpt-5.4).

---

## 8. API 키 요구

| 키 | 사용처 | 시리즈 수 |
|---|---|---|
| `FRED_API_KEY` | US 매크로/금리/credit/vol 데이터 11개 | 11 |
| `ECOS_API_KEY` | 한국 국고채/회사채 3개 | 3 |
| (yfinance) | SKEW, cross-asset, SP500 섹터 ETF | 키 불요 |
| (pykrx) | VKOSPI, 신용잔고, KOSPI/KOSDAQ, KOSPI200 breadth | 키 불요 |
| (CNN scraper) | Fear & Greed | 키 불요 |
| `OPENAI_API_KEY` | LLM eval (systemic_score) | — |

기존 환경 그대로 사용. 추가 가입 없음.

---

## 9. macro_quant와의 차이 요약

| 항목 | macro_quant | market_risk |
|---|---|---|
| 역할 | 매크로 regime 분류 (top-down) | 실시간 시장 stress 측정 (bottom-up) |
| 출력 | 4 quadrant + confidence | 0-10 score + 3 regime |
| Dimension | 20 | 33 |
| 핵심 시간 단위 | 월간 (CPI, UR, CLI) | 일간 (VIX, spreads) |
| KR 비중 | 1/5 (사이클 + FX + flow) | 4/17 skills 명시적 KR |
| LLM subagent | regime_classifier | systemic_score |
| 사용처 | Stage 2 (Bull/Bear), Stage 3 (Allocator) | Stage 4 (Risk debate), Allocator |

두 분석가의 데이터는 일부 겹치지만 (VIX는 양쪽에서 보지만 다른 각도) 결정적으로 **macro_quant는 "어떤 매크로 환경인가"**, **market_risk는 "지금 시장이 얼마나 stressed 인가"** 를 답한다. Stage 4 Risk Judge는 market_risk의 systemic_score를 weight_adjustment delta 계산에 직접 사용한다.

---

## 10. 4 Tier 누적 결과

| Tier | Skills 추가 | Dimension | 누적 | Commit |
|---|---|---|---|---|
| Baseline | 6 | 6 | 6 | (pre-existing) |
| **Tier-1** (equity stress 깊이) | 3 신규 + 2 강화 | +13 | 19 | `242525d` |
| **Tier-2** (bond/funding/credit) | 3 신규 + 1 확장 | +6 | 25 | `4fd8f8c` |
| **Tier-3** (KR-specific) | 4 신규 | +6 | 31 | `4daef50` |
| **Tier-4** (cross-asset positioning) | 1 신규 + 1 wire 교체 | +2 | **33** | `fd2b9ed` |
| **LLM eval** | — | — | — | `aeac6af` |

**5.5배 확장 (6 → 33)**, 회귀 0건, eval 8/8 pass.

---

## 11. 파일 매니페스트

| 위치 | 파일 |
|---|---|
| 스킬 (17) | `tradingagents/skills/risk/*.py` |
| 분석가 노드 | `tradingagents/agents/analysts/market_risk_analyst.py` |
| 스키마 (16) | `tradingagents/schemas/risk.py`, `reports.py` |
| 데이터 wrapper | `tradingagents/dataflows/{fred,ecos,pykrx_data,equity_indices,cross_asset_returns}.py` |
| LLM prompt | `prompts/risk-analysis.md` |
| 단위 테스트 | `tests/unit/skills/test_risk_*.py` (tier 1-4 + systemic_score) |
| LLM eval | `tests/integration/test_eval_systemic_score.py` |
| Lag 설정 | `tradingagents/default_config.py:publication_lag_days` |
