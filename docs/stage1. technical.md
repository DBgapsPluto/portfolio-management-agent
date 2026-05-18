# Stage 1 — Technical Analyst

> 파이프라인 6 stage 중 첫 단계의 4명 병렬 분석가 중 하나. 188개 KRX 상장 ETF universe에 대해 가격 기반 technical 신호를 *전수 스캔*하고, 카테고리/universe 집계 + per-ETF 정량 지표를 만들어 Stage 2 Bull/Bear 토론 + Stage 3 candidate selector / allocator에 전달한다.

> **macro_quant·market_risk와의 역할 분담**: macro_quant는 매크로 regime(분기 단위), market_risk는 실시간 시장 stress(일간 vol/credit), **technical은 universe 188 ETF의 가격 행동을 ETF별·카테고리별·universe-wide로 정량화**. 셋이 어디서 어떤 정보를 잡는지 차원이 다르다.

---

## 1. 한 줄 요약

> **OHLCV 5컬럼 + 벤치마크 2개로 10개 skill을 가공해 188 ETF 각 +28 dim의 정량 지표 + universe-level 5 snapshot을 만들고, LLM에는 압축된 집계·outlier만 전달한다.**

---

## 2. 어떤 데이터를 보는가

### 2.1 분석 대상 (단일 고정)

| 항목 | 값 |
|---|---|
| **Universe 파일** | `data/universe.json` (v2026-05-11) |
| **ETF 개수** | **188개** (전부 KRX 상장) |
| **카테고리** | 10개 — 국내주식_지수/섹터, 해외주식_지수/섹터, 국내채권_종합/회사채, 해외채권_종합/회사채, FX/원자재, 금리연계형/초단기채권 |
| **메타데이터** | ticker, name, AUM(KRW), underlying_index, bucket(위험/안전), category, listed_since, delisted_at |

### 2.2 가격 데이터 (yfinance)

| 함수 | 데이터 | 사용처 |
|---|---|---|
| `fetch_etf_price_batch(tickers, start, end)` | 188 ETF × 3년 OHLCV | 모든 Tier 계산의 input |
| `fetch_equity_index_close("kospi200", ...)` | KODEX 200 ETF (069500.KS) close | Tier-2 dual momentum (국내 ETF 벤치마크) |
| `fetch_equity_index_close("spy", ...)` | SPY close | Tier-2 dual momentum (해외/원자재/채권 ETF 벤치마크) |

→ **외부 API 키 0개** (yfinance는 무료). market_risk가 받는 SKEW/SPY와 채널 공유.

---

## 3. 어떻게 가공하는가 (10 skill의 계산 공식)

### 3.0 Baseline (5 skill)

| Skill | 계산 |
|---|---|
| `fetch_etf_price_batch` | yfinance OHLCV batch |
| `rank_momentum` | 카테고리 내 3m/6m/12m 모멘텀 *raw* return rank의 합산 (composite rank) |
| `compute_ta_indicators` | MA200, MA50, RSI(14), MACD(12,26,9), ATR(14) — top-5 per category에만 |
| `detect_trend_state` | MA + RSI 5-state enum (STRONG_UPTREND ~ BREAKDOWN) |
| `find_correlation_clusters` | hierarchical clustering, 60d corr, threshold 0.7 |

(추가 `factor_panel` portfolio skill로 skip-1m mom + 60d vol + Sharpe + log AUM)

---

### 3.1 Tier-1 — Indicator 깊이 (`compute_extended_indicators`)

**입력**: 단일 ETF의 OHLCV, ≥200일 history.

**출력**: `ExtendedIndicatorPanel` (12 dim).

```python
# Bollinger (length=20, std=2)
bb_percent_b  = (price - lower) / (upper - lower)   # <0 oversold, >1 overbought
bb_bandwidth  = (upper - lower) / middle             # squeeze ≈ <5%

# ADX (length=14) — 추세 강도 (방향 무관)
# <20 무추세 / 20~40 추세 / >40 강한 추세

# Stochastic (k=14, d=3) — 단기 oscillator (RSI 보완)
stoch_k, stoch_d

# Volume confirmation
obv             = 누적 OBV
obv_slope_20d   = OBV 최근 20일 linear-fit slope sign (+1/0/-1)
mfi             = Money Flow Index (volume-weighted RSI)

# Divergence (60d 윈도우)
rsi_divergence  ∈ {"none", "bullish", "bearish"}
macd_divergence ∈ {"none", "bullish", "bearish"}
# bearish: 가격 신고가 + 지표 신고가 못 만듦 (추세 약화 조기 경보)
# bullish: 가격 신저가 + 지표 신저가 못 만듦 (반등 가능성)

# Multi-timeframe (주봉 — W-FRI resample)
weekly_ma50, weekly_rsi
weekly_trend ∈ {"up", "down", "neutral"}
```

**왜**: 기존 5 지표(MA/RSI/MACD/ATR)는 *추세 방향*만 봤다. ADX로 *강도*, Bollinger로 *변동성 밴드 & 반전*, OBV/MFI로 *거래량 확인*, divergence로 *반전 조기 경보*, 주봉으로 *큰 추세 정렬* 확인. 모든 188 ETF에 계산 (기존 top-5 제한 해제).

---

### 3.2 Tier-2 — Trend 정량화 (`quantify_trend`)

**입력**: 단일 ETF OHLCV ≥252일 + 벤치마크 close series.

**출력**: `TrendQuantification` (10 dim).

```python
trend_strength_score  ∈ [-1, +1]
  = 0.40·clip(distance_ma200_pct/10, -1, 1)
  + 0.30·clip(adx/50, 0, 1)·sign(ma50 > ma200)
  + 0.20·sign(ma50 > ma200)
  + 0.10·clip((rsi - 50)/50, -1, 1)

time_in_state_days     = MA200를 마지막으로 cross한 후 경과 일수
distance_ma200_pct     = (price - MA200) / MA200 × 100
distance_ma50_pct      = (price - MA50)  / MA50  × 100

# Dual momentum
momentum_3m_abs   = close[-1]/close[-64] - 1
momentum_3m_rel   = m3 - benchmark_3m
momentum_12m_abs  = close[-1]/close[-253] - 1
momentum_12m_rel  = m12 - benchmark_12m
benchmark         ∈ {"KOSPI200", "SPY", "none"}

# Acceleration
momentum_acceleration = (1 + m3)^4 - 1  -  m12   # 연환산 3m vs 12m
```

**벤치마크 매핑**: `category.startswith("국내")` → KOSPI200, 그 외 → SPY. fetch 실패 시 `benchmark="none"`, m_rel = 0.

**왜**:
- **거리 정량화**: trend_state ENUM("UPTREND") 한 가지로 MA200 위 +2%와 +30%가 같았던 문제 해결.
- **time_in_state**: 추세 초반(추격 가능)과 후반(과열) 구분.
- **dual momentum** (Antonacci 1990s): 절대 모멘텀만 보면 강세장에선 다 1등. 진짜 leader는 벤치마크보다 더 오르는 자산.
- **acceleration**: 12m 1등이라도 최근 3m 감속 중이면 late-stage 신호.

---

### 3.3 Tier-3 — Universe Breadth (`compute_universe_breadth`)

**입력**: 188 ETF의 OHLC 전체 pivot.

**출력**: `UniverseBreadthSnapshot` (10 dim, *집계 1개*).

```python
n_total                    = 188
n_eligible                 = MA200 계산 가능한 ETF 수

pct_above_ma50, pct_above_ma200    # universe 내 비율

new_52w_highs              = 오늘 close가 252d max인 ETF 수
new_52w_lows               = 오늘 close가 252d min인 ETF 수

advance_decline_5d_ratio   = advancing_5d / declining_5d (cap 10.0)
ad_line_5d_slope           = cumulative AD line의 5일 sign (+1/0/-1)

universe_vol_median        = 188 ETF의 60d annualized vol median
universe_vol_z             = 위 값의 252d 자체 historical z-score

regime ∈ {
    "broad_risk_on"   if pct_above_ma200 > 0.6 AND ad_ratio > 1 AND ad_slope ≥ 0
    "broad_risk_off"  if pct_above_ma200 < 0.3
    "narrow"          else
}
```

**왜**: market_risk의 KOSPI200/SP500 11섹터 breadth와는 *독립* 차원. 우리 *선정 대상* universe 자체의 health. 예: 거시 환경은 risk-on이지만 한국 ETF universe만 narrow면 KR ETF 선정 가치 낮음. 후보 풀이 좁아진 신호로 Stage 4 Risk debate에 직접 입력.

---

### 3.4 Tier-4 — Sector Rotation + Correlation regime (`compute_sector_rotation`)

**입력**: 188 ETF pivot + Universe 객체 (카테고리 매핑).

**출력**: `SectorRotationSnapshot`.

```python
# 카테고리 단위 집계 모멘텀
for cat in 10개 카테고리:
    mean_mom_3m   = mean(ETF별 3m 수익률)
    mean_mom_12m  = mean(ETF별 12m 수익률)
    rank          = mean_mom_3m DESC 순위

leader_category   = rank=1
laggard_category  = rank=10

# Universe-wide dispersion
momentum_spread_3m = (mom_3m 상위 10% mean) - (하위 10% mean)
                   # 넓을수록 selective alpha 가치 ↑, 좁으면 베타 시장

# Correlation regime change
corr_median_60d   = 모든 ETF 쌍 60d corr의 median (upper triangle)
corr_median_252d  = 동일, 252d
correlation_change = med_60 - med_252

correlation_regime ∈ {
    "expansion"   if change > +0.10   # 위기 시 correlation → 1 패턴
    "compression" if change < -0.10   # 분산 가능성 증가
    "stable"      else
}
```

**왜**:
- **leadership matrix**: 자금이 어디로 회전 중인지 자동 추출 ("IT 섹터 leadership, 채권 laggard").
- **momentum_spread**: ETF 선정의 신뢰도 → 좁으면 모멘텀 신호 가치 ↓.
- **correlation regime**: 1987/2008/2020 모두 correlation 폭증으로 시작. 분산 효과 소실 측정. market_risk Tier-4 (equity-bond corr)와 보완.

---

### 3.5 Tier-5 — Risk-Adjusted Metrics (`compute_risk_adjusted`)

**입력**: 단일 ETF OHLCV + (선택) Tier-1 ExtendedIndicatorPanel.

**출력**: `RiskAdjustedMetrics` (7 dim).

```python
# Downside-aware Sharpe
sortino_60d  = (mean_60 × 252) / (downside_std_60 × √252)
             # 상승 변동성 페널티 없음

# Drawdown awareness
max_drawdown_12m  = min(cummax-relative drawdown) over 252d  ∈ [-1, 0]
calmar_12m        = annualized_return_12m / |max_drawdown_12m|

# Tail risk shape
skewness_60d         = scipy.stats.skew (음수 = 좌측 꼬리)
excess_kurtosis_60d  = Fisher kurtosis (>3 = fat tail)

# Mean reversion candidate
return_z_30d  = 자체 30d 누적 수익률의 252d historical z-score
is_mean_reversion_candidate = (bb_percent_b < 0
                              AND rsi < 35
                              AND return_z_30d < -1.5)
```

**왜**:
- 기존 factor_panel은 Sharpe만. **Sortino**는 하방 위험만 페널티 — 폭등하는 자산이 부당하게 손해 안 봄.
- **Calmar/max_DD**: 12m 30% 수익률도 max_DD -40%면 보유 어려움. "수익 대비 견뎌야 했던 고통".
- **skew/kurt**: 음의 skew + 높은 kurt = 드물지만 큰 손실 (black swan). 평균만 보면 안 보임.
- **mean reversion candidate**: 시스템 전체가 추세 추종이라 평균 회귀 setup은 빈 영역이었음. Contrarian 후보.

---

## 4. 188 ETF → LLM 핸드오프 압축 룰

핵심 디자인: **두 갈래 핸드오프**.

```
TechnicalAnalyst
  ├─→ technical_report (Pydantic, full 188 ETF dict)  →  portfolio_allocator (code, LLM 아님)
  └─→ technical_summary (str ≤2KB markdown)           →  bull/bear/manager/리포트 (LLM)
```

### 4.1 Tier별 압축 전략

| Tier | report에 저장 | summary에 노출 |
|---|---|---|
| **Tier-1** (~12 dim × 188 = 2,256 cell) | `extended_indicators: dict[ticker, ExtendedIndicatorPanel]` | 집계만 (ADX>25 개수, 압축 개수, divergence count + top-3 ticker) |
| **Tier-2** (~10 dim × 188) | `trend_quantification: dict[ticker, TrendQuantification]` | 분포 (strength>+0.5 개수, 가속 비율, outperformer 카운트) + top-3/bot-3 ETF |
| **Tier-3** (10 scalar) | `universe_breadth: UniverseBreadthSnapshot` | **전부 노출** (이미 집계) |
| **Tier-4** | `sector_rotation: SectorRotationSnapshot` (10 카테고리 풀) | top-3 + bot-3 카테고리만, spread + corr regime |
| **Tier-5** (7 dim × 188) | `risk_adjusted: dict[ticker, RiskAdjustedMetrics]` | tail-risk top-3, best Calmar top-3, worst DD top-3, reversion 후보 카운트 |

### 4.2 압축 후 summary 실제 예시 (~1.8KB)

```markdown
## Technical
Categories scanned: 10
Trend states: 23 uptrending of 50
Clusters: 6 (largest: 미국S&P500 외)
Tier-1 (188 ETF aggregate):
  ADX>25 (강한 추세): 42/188
  Bollinger 압축 (bw<5%): 7/188
  %B>1 과매수: 8, %B<0 과매도: 3
  MFI>80: 12, MFI<20: 4
  Bearish divergence: 9 (예: ['A069500', ...])
  Bullish divergence: 5 (예: ['A153130', ...])
  Weekly trend up/down: 86/22
Tier-2 (trend quant, n=185):
  strength>+0.5: 31, <-0.5: 11
  Accelerating (mom_3m_ann > 12m): 92/185
  벤치마크 outperform 12m: 78/185
  Top: A069500(+0.78, rel_12m +5.2%), ...
  Bot: A153130(-0.71), ...
Tier-3 (universe breadth, n=185):
  %above MA50: 58.4%, MA200: 62.7%
  52w highs/lows: 7/2
  A/D 5d ratio: 1.47 (AD line 5d slope +1)
  Universe vol: median 17.8% (z +0.42)
  Regime: broad_risk_on
Tier-4 (sector rotation):
  Leader: 해외주식_섹터 (3m +12.3%)
  Top-3: 해외주식_섹터(+12.3%), 국내주식_지수(+8.1%), 해외주식_지수(+7.4%)
  Bot-3: 국내채권_회사채(-1.2%), 금리연계형/초단기채권(-0.3%), FX 및 원자재(-3.0%)
  Mom spread (top-bot decile): +18.5%
  Corr 60d/252d: +0.52/+0.41 (Δ +0.11, expansion)
Tier-5 (risk-adjusted, n=185):
  Mean-reversion 후보: 3 (예: ['A364980', ...])
  Tail-risk top-3: A285690(skew -2.1, ek +5.3), ...
  Best Calmar 12m: A091160(Calmar +2.34), ...
  Worst max_DD 12m: A453850(-32%), ...
```

→ Bull/Bear가 이 한 덩어리만 읽고 토론 가능. raw 188 dict는 LLM 컨텍스트에 절대 안 들어감.

---

## 5. 출력 구조

### 5.1 `TechnicalReport` Pydantic 객체

`tradingagents/schemas/reports.py:TechnicalReport`. State에 `technical_report` 키로 저장.

```python
class TechnicalReport(_AnalystReport):
    # Baseline (4)
    asset_class_momentum:     dict[str, list[ETFRanking]]
    individual_etf_states:    dict[str, TrendState]
    correlation_clusters:     list[Cluster]
    factor_panel:             dict[str, FactorPanel]

    # Tier-1 — 188 ETF Indicator 깊이
    extended_indicators:      dict[str, ExtendedIndicatorPanel]

    # Tier-2 — Trend 정량화
    trend_quantification:     dict[str, TrendQuantification]

    # Tier-3 — Universe breadth (단일 snapshot)
    universe_breadth:         UniverseBreadthSnapshot | None

    # Tier-4 — Sector rotation
    sector_rotation:          SectorRotationSnapshot | None

    # Tier-5 — Risk-adjusted (188 ETF dict)
    risk_adjusted:            dict[str, RiskAdjustedMetrics]

    # 핸드오프 (2)
    narrative:                str   # ≤500자 한국어 산문
    summary_for_downstream:   str   # ≤2000자 마크다운
```

### 5.2 State wire (두 키)

```python
return {
    "technical_report":   TechnicalReport(...),   # 풀 객체 (allocator)
    "technical_summary":  summary,                 # 압축 (Bull/Bear)
    "correlation_clusters": clusters,              # 별도 키 (allocator diversification)
}
```

---

## 6. Graceful degradation (장애 처리)

모든 외부 fetch + skill 호출은 try/except로 감싸여 있다.

| 실패 | Fallback |
|---|---|
| yfinance ETF batch | `RuntimeError` (다음 stage 못 감) — 가장 critical |
| KOSPI200/SPY 벤치마크 | `benchmark="none"`, `momentum_*_rel = 0.0` |
| 개별 ETF history < 200/252일 | 해당 ETF는 dict에서 누락 (skip), 나머지는 계속 |
| `compute_extended_indicators` 실패 | 해당 ticker skip, Tier-5 자체 BB 재계산으로 대응 |
| `compute_universe_breadth` 예외 | `universe_breadth = None`, summary 빈 줄 |
| `compute_sector_rotation` 예외 | `sector_rotation = None`, summary 빈 줄 |
| Correlation matrix NaN | `fillna(0.0)` + `np.clip(-1, 1)` |

→ 188 ETF 중 일부 fetch 실패해도 나머지는 정상 분석. 카테고리 1개 누락도 leadership matrix가 9개로 계속 동작.

---

## 7. 검증 결과

| 항목 | 결과 |
|---|---|
| 단위 테스트 (Tier 1-5 × ~6-9 case) | **214 passing** (회귀 0건) |
| 신규 unit test (Tier 1~5) | **+27 신규** (Tier-1: 9, Tier-2: 8, Tier-3: 6, Tier-4: 5, Tier-5: 6) |
| 분석가 통합 테스트 | **passing** (`test_phase1_smoke.py`, `test_subgraph_isolation.py`) |
| 스키마 검증 | **passing** (Pydantic v2) |

Tier-4 correlation 계산에서 NaN을 fillna+clip으로 robust 처리. 그 외 단발 오류는 처음 통과.

---

## 8. API 키 요구

| 키 | 사용처 | 비고 |
|---|---|---|
| (yfinance) | 188 ETF OHLCV, KOSPI200, SPY | **키 불요** |
| `OPENAI_API_KEY` | quick_llm narrative 생성 (≤500자) | 기존 환경 |

→ 신규 가입/키 0개. macro_quant·market_risk와 동일 자원 풀.

---

## 9. macro_quant / market_risk와의 차이 요약

| 항목 | macro_quant | market_risk | **technical** |
|---|---|---|---|
| 역할 | 매크로 regime 분류 (top-down) | 실시간 시장 stress (bottom-up) | universe 가격 행동 정량화 |
| 출력 | 4 quadrant + confidence | 0-10 score + 3 regime | per-ETF dict + universe snapshot |
| Skill | 22 | 17 | **10** (Baseline 5 + Tier 1~5 신규 5) |
| Dim | 20 | 33 | 188 ETF × ~28 + 25 universe-level |
| 시간 단위 | 월간 (CPI, UR, CLI) | 일간 (VIX, spreads) | 일간 (가격) + 주간 (multi-TF) |
| LLM 사용 | regime_classifier subagent | systemic_score subagent | narrative 1번만 (≤500자) |
| 분석 대상 | 거시 시계열 | 시장 stress 시계열 | **188 ETF universe 고정** |
| 다음 stage 입력 | Stage 2 (Bull/Bear), Stage 3 (Allocator) | Stage 4 (Risk debate), Allocator | Stage 2 (Bull/Bear), Stage 3 (Selector + Allocator) |

세 분석가 모두 다른 차원을 잡는다:
- **macro_quant**: "어떤 매크로 환경인가" (성장+물가)
- **market_risk**: "지금 시장이 얼마나 stressed 인가" (VIX/credit/breadth)
- **technical**: "188 ETF에서 어떤 게 사고 어떤 게 팔 만한가" (가격 신호)

→ 셋의 출력은 Stage 2 Bull/Bear가 종합해서 토론한다.

---

## 10. 5 Tier 누적 결과

| Tier | Skills 추가 | 추가 정보 | 누적 Skill | Commit |
|---|---|---|---|---|
| Baseline | 5 | 카테고리 모멘텀 + top-5 TA + 추세 enum + 60d corr cluster | 5 | (pre-existing) |
| **Tier-1** (Indicator 깊이) | 1 신규 (`compute_extended_indicators`) | 188 ETF × +12 dim (Bollinger/ADX/Stoch/OBV/MFI/Divergence/Weekly) | 6 | `2a8b070` |
| **Tier-2** (Trend 정량화) | 1 신규 (`quantify_trend`) | 188 ETF × +10 dim (strength/time/distance/dual mom/accel) + KOSPI200·SPY 벤치마크 | 7 | `3e9c6a7` |
| **Tier-3** (Universe breadth) | 1 신규 (`compute_universe_breadth`) | universe 집계 +10 dim (pct_above_MA / 52w hi-lo / A/D / vol regime) | 8 | `1a10b26` |
| **Tier-4** (Sector rotation + RS) | 1 신규 (`compute_sector_rotation`) | 카테고리 leadership matrix + spread + corr regime change | 9 | `c15aea7` |
| **Tier-5** (Risk-adjusted) | 1 신규 (`compute_risk_adjusted`) | 188 ETF × +7 dim (Sortino/Calmar/skew/kurt/reversion) | **10** | `08b2927` |

**5 skill → 10 skill (2배 확장)**, 회귀 0건, 신규 27 단위 테스트 전부 pass.
**LLM 핸드오프 크기**: 5KB 이상 폭주 없이 ≤2KB 유지 (압축 룰 자동 적용).

---

## 11. 파일 매니페스트

| 위치 | 파일 |
|---|---|
| Baseline 스킬 (5) | `tradingagents/skills/technical/{price_batch,momentum_ranker,ta_indicators,trend_state,correlation_cluster}.py` |
| Tier-1 스킬 | `tradingagents/skills/technical/extended_indicators.py` |
| Tier-2 스킬 | `tradingagents/skills/technical/trend_quantification.py` |
| Tier-3 스킬 | `tradingagents/skills/technical/universe_breadth.py` |
| Tier-4 스킬 | `tradingagents/skills/technical/sector_rotation.py` |
| Tier-5 스킬 | `tradingagents/skills/technical/risk_adjusted.py` |
| 분석가 노드 | `tradingagents/agents/analysts/technical_analyst.py` |
| 스키마 | `tradingagents/schemas/technical.py`, `reports.py` |
| 데이터 wrapper | `tradingagents/dataflows/{universe,equity_indices}.py` |
| 단위 테스트 | `tests/unit/skills/test_technical_*.py` (10 파일) |
| Universe 데이터 | `data/universe.json` |
