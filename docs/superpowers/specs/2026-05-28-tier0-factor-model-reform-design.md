# Tier 0 — Factor Model Reform + Stage 1 Data Extension

- **작성일:** 2026-05-28
- **대상:** Stage 1/Stage 2 구현자 (PR2a friend 포함)
- **선행 의존:** 없음 (가장 foundational tier)
- **후속 의존:** Tier 1 (bucket taxonomy)는 본 spec의 factor 구조 위에서 bucket 변경, Tier 2 (calibration)는 본 spec의 β prior matrix 위에서 fit
- **외부 참조:** [Factor_Model_Gemini_DeepResearch](../../Factor_Model_Gemini_DeepResearch), [2026-05-28-pr2a-factor-taxonomy-redesign-idea.md](../../2026-05-28-pr2a-factor-taxonomy-redesign-idea.md)

---

## 0. TL;DR

10 factor → **12 factor** 재설계. 학술 인용 기반 (Gemini deep research validated). 외부 source 모두 실측 검증 완료. Per-factor window calibration framework로 sample efficiency 최대화.

**구조 변경:**
1. **F1 reform**: NFCI/curve 제거 (F10/F4와 중복) + INDPRO/Real PCE 추가
2. **F4 reform**: ACM term premium (NY Fed THREEFYTP10) 추가
3. **F5 reform**: GZ EBP (Fed Board) + KR corp spread (KRCorpSpreadSnapshot 활성화) 추가
4. **F6 reform**: krw_level → `krw_pct_change_6m` (Engel-West 2005 random walk) + BIS REER (RBKRBIS)
5. **F7 reform**: `geopolitical_surge` news count → Caldara-Iacoviello GPR Index
6. **F8 reform**: KOSPI PER/DivYield 활성화 + US Shiller CAPE 추가 (US:KR 50:50). KOSPI CAPE는 v2 deferral
7. **F9 rename**: `liquidity_regime` → `market_dispersion` (실제 내용에 맞춤)
8. **F10 reform**: SOFR → TEDRATE proxy stitching (pre-2018)
9. **F11 신규**: earnings revision net ratio (yfinance, 2010+, staggered calibration)
10. **F12 신규**: China Credit Impulse (BIS Total Credit, Biggs-Mayer-Pick 2010 정의 2차 미분)

**Sign restriction 변경:** F5×precious(+), F7×gl_dur(+), F7×precious(+) 3개 entry 제거.

**Z-baseline:** static `LONG_RUN_BASELINE` 위에 expanding window 모듈 신설 (`factor_baselines_dynamic.py`). Pesaran-Timmermann 1995.

**News-derived components 유지:** PR2a의 graceful degradation pattern 유지. Tier 3 LLM overlay는 *additive* (factor model 대체 X).

---

## 1. 현재 결함 (Gemini deep research validated)

### 1.1. 다중공선성 (Multicollinearity)
- **F1 × F10 NFCI 중복**: F1의 `nfci` (inverted, weight 0.12) + F10의 `nfci` (weight 0.30). 같은 raw source 이중 산정 → VIF 폭증. 근거: Gilchrist-Zakrajsek 2012, Stock-Watson 2002.
- **F1 × F4 curve 중복**: F1의 `curve` (weight 0.10) + F4의 `slope_2_10y` (weight 0.25). 동일 raw.

### 1.2. 시계열 비정상성 (Spurious Regression)
- **F6 `krw_level` raw level z-score**: Engel-West 2005 *JPE* 환율 random walk + Dornbusch 1976 overshooting. **수학적 필수 사항.** Meese-Rogoff 1983 puzzle, Granger-Newbold 1974 spurious regression (Monte Carlo 76-96%).

### 1.3. 지역 편향 (Regional Bias)
- **F8 US:KR = 75:25**: KR-원화 펀드인데 US valuation dominant. Baxter-Jermann 1997, Heathcote-Perri 2013 home bias 정당화.
- **F5 KR coverage 0%**: HY OAS/IG quality 모두 US. KR 부동산 PF 위기 등 *국지적* 신용 경색 감지 불가. Bekaert-Hodrick-Zhang 2009.

### 1.4. 핵심 선행 지표 누락 (Missing Leading Indicators)
- **GZ EBP 부재** (Gilchrist-Zakrajsek 2012 *AER*): Fed Board publishes monthly. credit spread를 default risk vs risk-bearing capacity로 분해. 표준 macro forecaster.
- **China Credit Impulse 부재** (Biggs-Mayer-Pick 2010 *JMCB*): KR 수출 25%+ China. 6-9개월 leading global PMI/copper/iron ore/KR exports.
- **Earnings revision 부재** (Chan-Jegadeesh-Lakonishok 1996, Asness-Frazzini-Pedersen 2019): top-down macro의 sluggishness 보완.

### 1.5. 명칭 혼선
- **F9 `liquidity_regime`** 이름이 실제 내용 (cross-sectional dispersion)과 분리. F10이 진짜 systemic liquidity. → rename `F9_market_dispersion`.

### 1.6. 과도한 Sign Restriction (Dash-for-cash 모순)
- **F5 → precious(+)**: 신용 경색 시 margin call로 금 매도. 2008-09 LTCM, 2020-03 COVID 사례. Brunnermeier-Pedersen 2009.
- **F7 → gl_dur/precious(+)**: 2022 stock/bond/gold 동반 폭락 (correlation breakdown).

---

## 2. 새 Stage 1 데이터 source

### 2.1. FRED 추가 series (`tradingagents/dataflows/fred.py:FRED_SERIES` dict 확장)

| Friendly key | Series ID | 시작일 (실측) | Frequency | 용도 |
|---|---|---|---|---|
| `us_indpro` | `INDPRO` | 1919-01 | monthly | F1 component (real activity) |
| `us_real_pce` | `PCECC96` | 1947-01 | quarterly | F1 component (real consumption) |
| `us_acm_term_premium_10y` | `THREEFYTP10` | 1990-01 | daily | F4 component (term premium decomposition) |
| `kr_reer` | `RBKRBIS` | 1994-01 | monthly | F6 component (REER, Engel-West) |
| `ted_spread` | `TEDRATE` | 1986-01 ~ 2022-01 | daily | F10 SOFR pre-2018 proxy |

**Publication lag** (`DEFAULT_CONFIG['publication_lag_days']`에 추가):
- `us_indpro`: ~15일 (mid-month release for prior month)
- `us_real_pce`: ~30일 (BEA quarterly, 1-month lag)
- `us_acm_term_premium_10y`: ~5일 (NY Fed weekly update)
- `kr_reer`: ~15일 (BIS monthly)
- `ted_spread`: ~1일 (daily)

**확인된 점:** 모든 series는 FRED API로 fetch 가능. 검증 완료 (2026-05-28).

### 2.2. SOFR-TED stitching (Option A) — **regime-aware**

**파일:** `tradingagents/dataflows/fred.py`에 stitching logic 추가.

```python
def fetch_funding_stress_stitched(
    start: date, end: date, as_of_date: date | None = None,
) -> pd.Series:
    """SOFR-Tbill (2018+) + TED (1986-2018) stitched series.

    F10 systemic_liquidity의 sofr_tbill_spread component. 
    Brunnermeier-Pedersen 2009: funding stress는 동일 economic concept이라 
    두 series stitching valid. PR2a의 BAA10Y fallback pattern과 동일.

    Pre 2018-04-03: TEDRATE (3M LIBOR - 3M Tbill, bps)
    2018-04-03+: SOFR - DTB3 (bps, scaled ×100 from percent)
    
    Stitch boundary: 2018-04-03 (SOFR 도입일, hard switch).
    Overlap (2018-04~2022-01)에서 SOFR-Tbill 우선 (TED는 2022-01 단종).
    
    Level mismatch (TED mean ~30bps, SOFR-Tbill mean ~5bps)는 **regime-aware z-baseline**으로 처리:
    pre-2018 sample → TED moments로 z, post-2018 sample → SOFR-Tbill moments로 z.
    Expanding window 통합 사용 X (regime mismatch로 biased mean/sd).
    """
    if start < date(2018, 4, 3):
        ted_end = min(end, date(2018, 4, 2))
        ted = fetch_fred_series("ted_spread", start, ted_end, as_of_date=as_of_date)
        # Remove TED rows after stitch boundary (overlap에서 SOFR-Tbill 우선)
        ted = ted[ted.index < pd.Timestamp("2018-04-03")]
        if end >= date(2018, 4, 3):
            sofr_start = max(start, date(2018, 4, 3))
            sofr_series = fetch_fred_series("us_sofr", sofr_start, end, as_of_date=as_of_date)
            tbill = fetch_fred_series("us_3m_tbill", sofr_start, end, as_of_date=as_of_date)
            sofr_tbill = (sofr_series - tbill) * 100  # percent → bps
            return pd.concat([ted, sofr_tbill]).sort_index()
        return ted
    # 전부 SOFR 시기
    sofr_series = fetch_fred_series("us_sofr", start, end, as_of_date=as_of_date)
    tbill = fetch_fred_series("us_3m_tbill", start, end, as_of_date=as_of_date)
    return (sofr_series - tbill) * 100
```

**FundingStressSnapshot 변경:** `spread_bps`는 stitched series 사용. schema 변경 없음 (interface 유지).

**Regime-aware z-baseline (factor_baselines_dynamic 호환):**

```python
# factor_baselines_dynamic.py에 special-case
def compute_expanding_baseline_funding_stress(as_of_date: date) -> tuple[float, float]:
    """Regime-aware: pre/post 2018-04-03 분리 mean/sd.
    
    sample t < 2018-04-03  →  TED 1986-2018 moments 사용
    sample t >= 2018-04-03 →  SOFR-Tbill 2018+ moments 사용 (까지의 expanding)
    """
    if as_of_date < date(2018, 4, 3):
        ted_series = fetch_fred_series("ted_spread", date(1986, 1, 1), as_of_date)
        return float(ted_series.mean()), float(ted_series.std(ddof=1))
    else:
        # SOFR-Tbill from 2018-04-03 to as_of
        ss = fetch_funding_stress_stitched(date(2018, 4, 3), as_of_date)
        return float(ss.mean()), float(ss.std(ddof=1))
```

### 2.3. 신규 fetcher 모듈 (free external CSV)

#### 2.3.1. Shiller US CAPE (`tradingagents/dataflows/shiller_cape.py` 신규)

**URL:** `http://www.econ.yale.edu/~shiller/data/ie_data.xls`
**검증 (2026-05-28 실측):** 1.6 MB Excel, accessible. xls format (xlrd 필요).

**Schema 실측:**
- Sheets: `['Disclaimer', 'Data']`
- Sheet `'Data'` row 0-7: 설명 (multi-line header)
- `skiprows=7` 후 첫 row가 column names: `['Date', 'P', 'D', 'E', 'CPI', 'Fraction', 'Rate GS10', 'Price', 'Dividend', 'Price.1', 'Earnings', 'Earnings.1', 'CAPE', ...]`
- Target column: **`'CAPE'`** (Cyclically Adjusted P/E ratio)
- Date format: **decimal year** (`1871.01` = 1871-01, `2026.04` = 2026-04). NOT timestamp.
- NaN values exist for first 10 years (CAPE = trailing 10y avg, requires history)

```python
import pandas as pd
import urllib.request
from datetime import date

SHILLER_URL = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"

def fetch_shiller_cape(as_of: date | None = None) -> pd.Series:
    """Monthly Shiller CAPE (PE10) from Yale.
    
    Series: 1881-01 ~ current (CAPE valid from 1881 after 10y rolling).
    Returns pd.Series indexed by month-end date, name='cape'.
    
    Caching: TTL 24h. File: data/cache/shiller_cape.parquet
    """
    data = urllib.request.urlopen(SHILLER_URL, timeout=30).read()
    df = pd.read_excel(io.BytesIO(data), sheet_name="Data", skiprows=7)
    # Date column: decimal year format
    df["date"] = df["Date"].apply(_decimal_year_to_date)
    df = df.dropna(subset=["CAPE"]).set_index("date")
    if as_of:
        df = df[df.index <= pd.Timestamp(as_of)]
    return df["CAPE"].astype(float).rename("cape")

def _decimal_year_to_date(dy: float) -> pd.Timestamp:
    """Convert Shiller decimal year (e.g., 2026.04) → 2026-04-01 timestamp."""
    if pd.isna(dy):
        return pd.NaT
    year = int(dy)
    # Shiller convention: 0.01 = January, 0.12 = December
    month = round((dy - year) * 100)
    month = max(1, min(12, month))
    return pd.Timestamp(year=year, month=month, day=1)
```

**검증 fallback:** column 'CAPE' 없으면 'TR CAPE' (Total Return CAPE) 시도. 둘 다 없으면 raise.

#### 2.3.2. Caldara-Iacoviello GPR Index (`tradingagents/dataflows/gpr_index.py` 신규)

**URL (월간):** `https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls`
**URL (일간):** `https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls`
**검증 (2026-05-28 실측):** 2.7 MB / 3.2 MB Excel, accessible.

**Schema 실측 (Monthly):**
- Single sheet `'Sheet1'`
- 115 columns total. Key columns:
  - `'month'` — pandas Timestamp (1900-01-01 first row)
  - `'GPR'` — main Geopolitical Risk Index
  - `'GPRT'` — threats sub-component
  - `'GPRA'` — acts sub-component
  - `'GPRH'` — historical extended (1900+ even more rigorous)
  - `'GPRC_<COUNTRY>'` — country-specific (KOR, CHN, USA, etc.) — KR-specific bonus signal
- Use: `df['GPR']` for main. For KR portfolio, also extract `df['GPRC_KOR']`.

**Schema 실측 (Daily):**
- Sheet `'Sheet1'`, columns `'date'`, `'GPRD'` (daily index, 1985-01+)

```python
import io, urllib.request
import pandas as pd

GPR_MONTHLY_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls"
GPR_DAILY_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls"

def fetch_gpr_index(
    frequency: str = "monthly",
    series: str = "GPR",   # "GPR" (global) | "GPRC_KOR" (KR-specific)
    as_of: date | None = None,
) -> pd.Series:
    """Caldara-Iacoviello Geopolitical Risk Index.
    
    Reference: Caldara-Iacoviello 2018 (updated 2022) AER "Measuring Geopolitical Risk".
    
    Caching: TTL 24h. File: data/cache/gpr_{frequency}.parquet
    """
    if frequency == "monthly":
        url, date_col, default_series = GPR_MONTHLY_URL, "month", "GPR"
    else:
        url, date_col, default_series = GPR_DAILY_URL, "date", "GPRD"
    
    data = urllib.request.urlopen(url, timeout=30).read()
    df = pd.read_excel(io.BytesIO(data), sheet_name="Sheet1")
    df = df.set_index(pd.to_datetime(df[date_col]))
    target = series if series in df.columns else default_series
    s = df[target].astype(float).rename(target.lower())
    if as_of:
        s = s[s.index <= pd.Timestamp(as_of)]
    return s.dropna()
```

#### 2.3.3. Fed Board GZ EBP (`tradingagents/dataflows/gz_ebp.py` 신규)

**URL:** `https://www.federalreserve.gov/econres/notes/feds-notes/ebp_csv.csv`
**검증 (2026-05-28 실측):** 44 KB CSV, accessible.

**Schema 실측:**
- CSV columns: `'date', 'gz_spread', 'ebp', 'est_prob'`
- Date format: `YYYY-MM-DD` (first-of-month, 1973-01-01 first row, 2026-04-01 last row)
- Use: `df['ebp']` (Excess Bond Premium, pure risk premium component)

```python
import pandas as pd
import urllib.request

FED_EBP_URL = "https://www.federalreserve.gov/econres/notes/feds-notes/ebp_csv.csv"

def fetch_gz_ebp(as_of: date | None = None) -> pd.Series:
    """Gilchrist-Zakrajsek Excess Bond Premium (Federal Reserve Board).
    
    Reference: Gilchrist-Zakrajsek 2012 AER "Credit Spreads and Business Cycle Fluctuations".
    
    EBP = corporate bond spread - expected default loss (Merton 1974 distance-to-default).
    Pure risk-bearing capacity proxy. NBER recession 4-12m lead.
    
    Caching: TTL 24h. File: data/cache/gz_ebp.parquet
    """
    df = pd.read_csv(FED_EBP_URL)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    if as_of:
        df = df[df.index <= pd.Timestamp(as_of)]
    return df["ebp"].astype(float)
```

#### 2.3.4. BIS China Total Credit (`tradingagents/dataflows/bis_credit.py` 신규)

**URL:** `https://www.bis.org/statistics/totcredit/totcredit.xlsx`
**검증 (2026-05-28 실측):** 1.7 MB Excel, accessible. CSV는 **404** — xlsx만 사용.

**Schema 실측:**
- Sheets: `['Content', 'Summary Documentation', 'Quarterly Series']`
- `'Summary Documentation'` (1133 rows): 각 series의 metadata. 컬럼 `['Data set', 'Code', 'Frequency', "Borrowers' country", 'Borrowing sector', 'Lending sector', 'Valuation method', 'Unit type', 'Adjustment', 'Unit', ...]`
- `'Quarterly Series'`: 1134 columns × 333 rows. Header가 *multi-row* (제목, country, sector, ..., **code in row 3**)
- **Target code: `Q:CN:P:A:M:770:A`** — Quarterly, China, Private non-financial sector, All sectors lending, Market value, Percent of GDP (770), Adjusted for breaks
- 현재 vintage에서 code 위치: row 3, column index **269** — **vintage마다 shift 가능, dynamic discovery 필수**
- 데이터: 1940-Q2 ~ 2023-Q2 (NaN until ~1985)

```python
import io, urllib.request
import pandas as pd

BIS_TOTCREDIT_URL = "https://www.bis.org/statistics/totcredit/totcredit.xlsx"
BIS_CN_CREDIT_CODE = "Q:CN:P:A:M:770:A"  # China Private Non-Fin / All sectors / Market value / % GDP / Adjusted

def fetch_bis_china_credit(as_of: date | None = None) -> pd.Series:
    """BIS Total Credit to Non-Financial Sector, China — credit/GDP ratio (%).
    
    Source: bis.org/statistics/totcredit.xlsx (Total Credit Statistics dataset BIS_TC2).
    Used by compute_china_credit_impulse() for F12 (Biggs-Mayer-Pick 2010).
    
    Vintage-aware column discovery: code 'Q:CN:P:A:M:770:A' position varies between
    BIS vintages → search row 0-15 to find the code, then use that column index.
    
    Returns: pd.Series indexed by quarter_end, credit-to-GDP %, dropna.
    Caching: TTL 7d (BIS quarterly publication).
    """
    data = urllib.request.urlopen(BIS_TOTCREDIT_URL, timeout=60).read()
    # Step 1: find code row + column index
    header_df = pd.read_excel(io.BytesIO(data), sheet_name="Quarterly Series",
                              header=None, nrows=15)
    code_row, code_col = _find_bis_code_position(header_df, BIS_CN_CREDIT_CODE)
    if code_row is None:
        raise ValueError(f"BIS code {BIS_CN_CREDIT_CODE} not found in xlsx — vintage schema changed")
    # Step 2: read data using found column
    df = pd.read_excel(io.BytesIO(data), sheet_name="Quarterly Series",
                       skiprows=code_row + 1, usecols=[0, code_col],
                       header=None, names=["date", "cn_credit_gdp_pct"])
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna().set_index("date")
    if as_of:
        df = df[df.index <= pd.Timestamp(as_of)]
    return df["cn_credit_gdp_pct"].astype(float)

def _find_bis_code_position(df: pd.DataFrame, code: str) -> tuple[int | None, int | None]:
    """Search first 15 rows for the BIS series code, return (row, col)."""
    for i in range(len(df)):
        row_str = df.iloc[i].astype(str)
        matches = row_str[row_str == code]
        if len(matches) > 0:
            return i, matches.index[0]
    return None, None
```

### 2.4. Stage 1 schema 확장

#### 2.4.1. `FXSnapshot` (macro.py)
```python
class FXSnapshot(StalenessAware):
    # 기존 fields 유지
    usd_krw: float
    dxy: float
    krw_change_1m_pct: float
    dxy_change_1m_pct: float
    regime: Literal["krw_strong", "krw_weak", "usd_risk_off", "neutral"]
    
    # NEW (Tier 0): F6 reform — Engel-West 2005 random walk fix
    krw_change_6m_pct: float = Field(
        default=0.0,
        description="USD/KRW 6-month % change. F6 component (replaces krw_level raw). "
                    "Engel-West 2005 JPE: exchange rate ≈ random walk, level은 non-stationary, "
                    "변화율만 stationary I(0). 표준 macro empirics.",
    )
    
    # NEW (Tier 0): F6 component — BIS REER (RBKRBIS)
    krw_reer: float | None = Field(
        default=None,
        description="BIS Real Effective Exchange Rate for KRW (1994+). "
                    "None=fetch 실패 또는 1994 이전. Engel-West 2005 호환.",
    )
```

#### 2.4.2. `CommodityMomentumSnapshot` (NEW, macro.py)
```python
class CommodityMomentumSnapshot(StalenessAware):
    """Commodity price momentum — F2/F13 components.

    Daily price series (commodities.py) 위에서 1m/3m/6m % change 계산.
    Erb-Harvey 2006, Asness-Moskowitz-Pedersen 2013 commodity momentum factor.
    """
    copper_3m_pct: float = Field(description="Copper (HG=F) 3-month % change")
    copper_6m_pct: float = Field(description="Copper 6-month % change")
    gold_3m_pct: float = Field(description="Gold (GC=F) 3-month % change")
    gold_6m_pct: float = Field(description="Gold 6-month % change")
    wti_3m_pct: float = Field(description="WTI (CL=F) 3-month % change")
    wti_6m_pct: float = Field(description="WTI 6-month % change")
    bcom_3m_pct: float | None = Field(
        default=None,
        description="Bloomberg Commodity Index (^BCOM or DJP ETF) 3m % change. "
                    "None=fetch 실패.",
    )
```

#### 2.4.3. `ForeignFlowSnapshot` (확장, macro.py)
```python
class ForeignFlowSnapshot(StalenessAware):
    net_5d_krw: float
    net_20d_krw: float
    signal: Literal["net_buying", "net_selling", "neutral"]
    
    # NEW (Tier 0): non-stationarity fix — pykrx market cap normalization
    net_20d_normalized: float = Field(
        default=0.0,
        description="net_20d_krw / KOSPI market_cap. Period-stationary ratio "
                    "(1991-2024 sample composition fix). Stambaugh 1986 bias 우회.",
    )
```

#### 2.4.4. `USEquityValuationSnapshot` (NEW, macro.py)
```python
class USEquityValuationSnapshot(StalenessAware):
    """Shiller US CAPE — F8 component (Asness 2003 standard).

    Trailing PE는 ex-post, CAPE는 10년 cyclically-adjusted PE로 long-run 
    mean reversion 강함.
    """
    cape: float = Field(description="Shiller CAPE (PE10), monthly")
    cape_zscore_30y: float = Field(description="30-year z-score of CAPE")
```

#### 2.4.5. `KRValuationSnapshot` (확장, 기존 macro.py)
```python
class KRValuationSnapshot(StalenessAware):
    kospi_pbr: float
    kospi_per: float  # 이미 schema에 있음, factor model 이 활성화 안 함
    kospi_div_yield: float
    # KOSPI CAPE는 v2 deferral — 10y rolling EPS 누적 필요 (pykrx 2003+ → effective 2013+)
```

#### 2.4.6. `GeopoliticalRiskSnapshot` (NEW, macro.py 또는 risk.py)
```python
class GeopoliticalRiskSnapshot(StalenessAware):
    """Caldara-Iacoviello Geopolitical Risk Index — F7 component.

    Replaces F7's `geopolitical_surge` (news count delta) — academic-standard.
    """
    gpr_monthly: float = Field(description="GPR Index (monthly, 1900+)")
    gpr_zscore_60m: float = Field(description="60-month z-score")
    gpr_daily: float | None = Field(
        default=None,
        description="GPR Daily Index (1985+). None=fetch 실패.",
    )
```

#### 2.4.7. `ExcessBondPremiumSnapshot` (NEW, risk.py)
```python
class ExcessBondPremiumSnapshot(StalenessAware):
    """Gilchrist-Zakrajsek Excess Bond Premium — F5 component."""
    ebp: float = Field(description="Monthly EBP (1973+)")
    ebp_zscore_5y: float = Field(description="5-year rolling z-score")
```

#### 2.4.8. `ChinaCreditImpulseSnapshot` (NEW, macro.py)
```python
class ChinaCreditImpulseSnapshot(StalenessAware):
    """China Credit Impulse — F12 신규 factor.

    Biggs-Mayer-Pick 2010 JMCB 정의:
        CI(t) = Δ(Δ Credit_t / GDP_t)  /  (Δ Credit_{t-4} / GDP_{t-4})
    
    즉 신용 흐름의 *2차 미분* (가속도). 6-9개월 leading global PMI/commodity.
    Source: BIS Total Credit Q.CN.P.B.M.770.A (1989+).
    """
    credit_impulse: float = Field(description="Biggs-Mayer-Pick credit impulse (%)")
    credit_to_gdp_ratio: float = Field(description="Raw credit/GDP ratio (%)")
    credit_yoy_pct: float = Field(description="Credit YoY % growth (1차 미분)")
```

#### 2.4.9. `EarningsRevisionSnapshot` (NEW, macro.py 또는 별도)
```python
class EarningsRevisionSnapshot(StalenessAware):
    """Earnings Revision Net Ratio — F11 신규 factor (staggered).

    Source: yfinance ticker.earnings_history + recommendations_summary,
    aggregated over SP500 + KOSPI200 constituents (2010+).
    
    Net Ratio = (count of upward revisions - count of downward) / total revisions.
    """
    sp500_net_revision: float | None = Field(
        default=None,
        description="SP500 aggregated EPS revision net ratio (1m), [-1, +1]. "
                    "None=fetch 실패 또는 2010 이전.",
    )
    kospi200_net_revision: float | None = Field(
        default=None,
        description="KOSPI200 aggregated EPS revision net ratio (1m). None=fetch 실패.",
    )
```

---

## 3. Factor 구조 명세 (12 factor)

### 3.1. 전역 변경

`tradingagents/skills/research/factor_estimators.py`:

```python
FACTORS: Final[tuple[str, ...]] = (
    "F1_growth",
    "F2_inflation",
    "F3_real_rate",
    "F4_term_premium",
    "F5_credit_cycle",
    "F6_krw_regime",
    "F7_equity_vol_regime",
    "F8_valuation",
    "F9_market_dispersion",        # renamed from F9_liquidity_regime
    "F10_systemic_liquidity",
    "F11_earnings_revision",       # NEW
    "F12_china_credit_impulse",    # NEW
)
```

`FactorScores` dataclass:
```python
@dataclass
class FactorScores:
    growth_surprise: FactorScore
    inflation_surprise: FactorScore
    real_rate: FactorScore
    term_premium: FactorScore
    credit_cycle: FactorScore
    krw_regime: FactorScore
    equity_vol_regime: FactorScore
    valuation: FactorScore
    market_dispersion: FactorScore        # renamed
    systemic_liquidity: FactorScore | None = None
    earnings_revision: FactorScore | None = None    # NEW (staggered)
    china_credit_impulse: FactorScore | None = None # NEW

    def to_dict(self) -> dict[str, float]:
        ...
        if self.earnings_revision is not None:
            out["F11_earnings_revision"] = self.earnings_revision.z_score
        if self.china_credit_impulse is not None:
            out["F12_china_credit_impulse"] = self.china_credit_impulse.z_score
        return out
```

### 3.2. F1_growth (reform)

**Sign convention:** +z = stronger growth.

**제거:**
- `nfci` (NFCI inverted, weight 0.12) — F10 중복
- `curve` (10y-2y spread, weight 0.10) — F4 중복
- `gdpnow` weight 0.18 — **backtest mode에서 drop** (Option C, live mode에서 graceful add)

**추가:**
- `indpro_yoy` weight 0.15 — INDPRO YoY %, Industrial Production (1919+). Cooper-Mitrache-Priestley 2017.
- `real_pce_yoy` weight 0.10 — PCECC96 YoY %, Real PCE (1947+). Cieslak-Pflueger 2023 *JF*.

**최종 component table:**

| Component | Source | Weight | Mode | Reliability |
|---|---|---|---|---|
| cfnai | macro_report.financial_conditions.cfnai | 0.12 | both | high |
| cfnai_3m | macro_report.financial_conditions.cfnai_3m_avg | 0.10 | both | high |
| sahm | macro_report.employment.sahm_rule_triggered | 0.08 | both | medium-low |
| indpro_yoy | macro_report.us_indpro YoY | 0.15 | both | high |
| real_pce_yoy | macro_report.us_real_pce YoY | 0.10 | both | high |
| gdpnow | macro_report.gdp_nowcast.nowcast_pct | 0.10 | **live only** | high |
| release_surprise (news) | news_report.release_surprise.surprise_index_30d | 0.15 | live | high |
| hawkish_bias (news) | news_report.release_surprise.bias_30d | 0.05 | live | high |
| macro_sent (news) | news_report.news_sentiment.avg_sentiment.macro | 0.05 | live | medium |
| risk_regime_overnight (news) | news_report.global_overnight.risk_regime_overnight | 0.10 | live | high |

**Quant weight (backtest mode, news/gdpnow drop) renormalized to 1.0**:
- cfnai: 0.12 / 0.55 = 0.218
- cfnai_3m: 0.10 / 0.55 = 0.182
- sahm: 0.08 / 0.55 = 0.145
- indpro_yoy: 0.15 / 0.55 = 0.273
- real_pce_yoy: 0.10 / 0.55 = 0.182

**Backtest start:** 1971+ (INDPRO YoY 계산 1년 lag 후).

### 3.3. F2_inflation (변경 없음)

기존 component 유지. PCEPI/Core PCE는 이미 schema 보유.

**Backtest start:** 2003+ (TIPS-based real_yield_inv, T5YIFR breakeven binding).

### 3.4. F3_real_rate (변경 없음)

기존 component 유지.

**Backtest start:** 2003+ (DFII10 binding).

### 3.5. F4_term_premium (reform)

**Sign convention:** +z = steeper / higher term premium.

**기존 component:**
- `slope_2_10y` weight 0.25
- `slope_5_30y` weight 0.20
- `fed_tone_balance` (news) weight 0.30
- `fed_voting_balance` (news) weight 0.25

**추가:**
- `acm_term_premium_10y` weight 0.30 — Adrian-Crump-Moench 2013 *RFS* 표준 분해. NY Fed publishes monthly via THREEFYTP10.

**Weight 재조정:**
- `slope_2_10y`: 0.15 (raw slope, conf. expected rates + term premium)
- `slope_5_30y`: 0.10
- `acm_term_premium_10y`: 0.30 (pure term premium)
- `fed_tone_balance` (news): 0.25
- `fed_voting_balance` (news): 0.20

**Quant weight (renormalized)**:
- slope_2_10y: 0.15 / 0.55 = 0.273
- slope_5_30y: 0.10 / 0.55 = 0.182
- acm_term_premium_10y: 0.30 / 0.55 = 0.545

**Backtest start:** 1990+ (THREEFYTP10 binding).

### 3.6. F5_credit_cycle (reform)

**Sign convention:** +z = credit stress.

**추가:**
- `gz_ebp` weight 0.20 — Gilchrist-Zakrajsek 2012 EBP. Fed Board publishes.
- `kr_corp_spread_bps` weight 0.10 — KRCorpSpreadSnapshot.spread_bps (AA- 3y 회사채 vs 국고채 3y), pykrx (2003+).

**Weight 재조정:**
- `hy_oas_bps`: 0.20 (was 0.30)
- `hy_oas_momentum`: 0.15 (was 0.25)
- `credit_quality_bps`: 0.10 (was 0.15)
- `funding_bps`: 0.10 (unchanged)
- `gz_ebp`: 0.20 (NEW)
- `kr_corp_spread_bps`: 0.10 (NEW)
- `corporate_distress` (news): 0.10 (was 0.15)
- `dovish_bias` (news): 0.05 (unchanged)

**Quant weight (renormalized)**:
- hy_oas_bps: 0.20 / 0.85 = 0.235
- hy_oas_momentum: 0.15 / 0.85 = 0.176
- credit_quality_bps: 0.10 / 0.85 = 0.118
- funding_bps: 0.10 / 0.85 = 0.118
- gz_ebp: 0.20 / 0.85 = 0.235
- kr_corp_spread_bps: 0.10 / 0.85 = 0.118

**Backtest start:** 2003+ (KR corp spread pykrx binding). GZ EBP는 1973+이지만 KR corp spread가 binding.

### 3.7. F6_krw_regime (reform)

**Sign convention:** +z = weaker KRW.

**제거:**
- `krw_level` weight 0.20 — Engel-West 2005, Meese-Rogoff 1983 random walk violation. **수학적 필수 사항.**

**추가:**
- `krw_change_6m_pct` weight 0.20 — FXSnapshot 6m change. I(0) stationary.
- `krw_reer` weight 0.10 — BIS REER (RBKRBIS, 1994+). Pflueger-Viceira 2011 valuation control.

**기존 component:**
- `krw_overnight_pct` weight 0.20 (unchanged)
- `kr_us_rate_diff` weight 0.15 (was 0.15)
- `foreign_flow_z` weight 0.20 → **normalized**: `net_20d_normalized` (KOSPI mcap normalization)
- `kr_exports_yoy` weight 0.10 (unchanged)
- `bok_tone_balance` (news) weight 0.15 (unchanged)

**Quant weight (renormalized)**:
- krw_overnight_pct: 0.20 / 0.85 = 0.235
- krw_change_6m_pct: 0.20 / 0.85 = 0.235
- krw_reer: 0.10 / 0.85 = 0.118
- kr_us_rate_diff: 0.15 / 0.85 = 0.176
- foreign_flow_normalized: 0.20 / 0.85 = 0.235

**Backtest start:** 
- 1994+ if REER required → 2003+ if foreign_flow required → 2003+ (KR pykrx binding)
- Without REER (None drop): 2003+ via foreign_flow_normalized
- Without foreign_flow_normalized: 1994+ via REER

### 3.8. F7_equity_vol_regime (reform)

**Sign convention:** +z = high vol.

**제거:**
- `geopolitical_surge` (news count delta, weight 0.15) — Caldara-Iacoviello GPR로 대체

**추가:**
- `gpr_index_zscore` weight 0.10 — Caldara-Iacoviello 2018 *AER* GPR Index 60m z-score.

**기존 component (VXVCLS 유지 — Option D skip):**
- `vix_level` weight 0.20
- `vix_z_score` weight 0.10
- `vix_term_ratio` weight 0.10 (VXVCLS, 2007+ binding)
- `move` weight 0.15
- `realized_vol_60d` weight 0.13
- `skew_change` weight 0.07
- `sentiment_dispersion` (news) weight 0.10 (renamed/유지)
- `gpr_index_zscore` weight 0.15 (NEW, replaces geopolitical_surge)

**Quant weight (renormalized)**:
- vix_level: 0.20 / 0.75 = 0.267
- vix_z_score: 0.10 / 0.75 = 0.133
- vix_term_ratio: 0.10 / 0.75 = 0.133
- move: 0.15 / 0.75 = 0.200
- realized_vol_60d: 0.13 / 0.75 = 0.173
- skew_change: 0.07 / 0.75 = 0.093
- gpr_index_zscore: (treated as quant — GPR is structured FRED-style series, 1900+ available) 0.15 / 0.75 → adjustment

**Re-decision:** GPR Index는 *quant series* (Caldara-Iacoviello가 매월 publish) → quant 분류.

**Final quant weight (with GPR)**:
- vix_level: 0.20 / 0.90 = 0.222
- vix_z_score: 0.10 / 0.90 = 0.111
- vix_term_ratio: 0.10 / 0.90 = 0.111
- move: 0.15 / 0.90 = 0.167
- realized_vol_60d: 0.13 / 0.90 = 0.144
- skew_change: 0.07 / 0.90 = 0.078
- gpr_index_zscore: 0.15 / 0.90 = 0.167

**Backtest start:** 2007+ (VXVCLS binding).

### 3.9. F8_valuation (reform — US:KR 50:50 balance)

**Sign convention:** +z = expensive.

**제거:**
- KOSPI CAPE — v2 deferral (effective 2013+ too short, KOSPI 10y EPS history needed)

**추가:**
- `us_cape` weight 0.20 — Shiller CAPE (PE10). Asness 2003 *FAJ*.
- `kospi_per` weight 0.15 — 이미 KRValuationSnapshot에 있음, factor model이 *활성화 안 함*
- `kospi_div_yield` weight 0.10 — 이미 schema, 활성화

**기존 component:**
- `sp_pe` weight 0.10 (was 0.20)
- `earnings_yield` weight 0.10 (was 0.25)
- `erp` weight 0.15 (was 0.30)
- `kospi_pbr` weight 0.20 (was 0.25)

**Final weight (sum=1.0)**:
- US: sp_pe 0.10 + earnings_yield 0.10 + erp 0.15 + us_cape 0.20 = **0.55**
- KR: kospi_pbr 0.20 + kospi_per 0.15 + kospi_div_yield 0.10 = **0.45**

Note: 정확한 50:50은 어렵지만 55:45는 Gemini 권고 50:50에 근접하며 US CAPE의 1871+ deep history 가치 반영.

**Backtest start:** 2003+ (KOSPI pykrx fundamental binding). US CAPE는 1871+로 매우 길지만 KR 측이 binding.

### 3.10. F9_market_dispersion (rename only)

`F9_liquidity_regime` → `F9_market_dispersion`. 모든 reference 갱신.

- `factor_estimators.py`: 함수 이름 `compute_liquidity_regime` → `compute_market_dispersion`
- `factor_to_bucket.py`: `FACTORS` tuple + `INITIAL_BETA` 키 + `SIGN_RESTRICTION` 키
- `factor_baselines.py`: `LONG_RUN_BASELINE` 키
- `factor_reliability_audit.py`: tier 유지
- Test files: assertion 갱신

Component 변경 없음. 의미 일관.

**Backtest start:** 1993+ (SPY realized_vol_60d binding for VRP).

### 3.11. F10_systemic_liquidity (SOFR-TED stitching)

**Sign convention:** +z = systemic stress.

**Component 변경:**
- `sofr_tbill_spread` → **stitched** (TEDRATE 1986-2018 + SOFR-Tbill 2018+). 변경: data source만, schema/factor structure 동일.

**나머지 component 유지:**
- nfci weight 0.30
- anfci weight 0.20
- fed_bs_signal weight 0.15
- sofr_tbill_spread (stitched) weight 0.20
- aaa_oas weight 0.15

**Baseline 통일** (`factor_baselines.py`):
- `F10_systemic_liquidity, nfci`: **(0, 1)** — Chicago Fed construction 표준 (mean=0, sd=1)
- F1의 nfci는 *제거됨* → F10이 단일 진실
- `F10_systemic_liquidity, sofr_tbill_spread`: stitched series의 통합 (mean, sd). TED (mean ~30bps, sd ~30bps) + SOFR-Tbill (mean ~5bps, sd ~10bps). 통합 baseline은 *expanding window*에서 계산 (factor_baselines_dynamic.py).

**Backtest start:** 1971+ (NFCI binding). TED stitching으로 sofr_tbill_spread도 1986+에서 가용.

### 3.12. F11_earnings_revision (NEW, staggered)

**Sign convention:** +z = positive earnings revision (more upgrades than downgrades).

**Source (실측 검증 후 결정):**
- yfinance `ticker.earnings_history` 는 **4 quarters만** 반환 — backtest 불가.
- yfinance `ticker.upgrades_downgrades` 는 **장기 history** 보유 (AAPL 968행, JPM 426행).
- → **F11은 `upgrades_downgrades` 기반 net revision proxy 사용.** EPS revision의 직접 측정이 아니라 *analyst rating action count* 사용 (correlated proxy).

**SP500 constituents:** hardcoded snapshot file `data/universe/sp500_constituents.json` (수동 refresh monthly, Wikipedia/yfinance에서 추출).

**KOSPI200 측:** pykrx의 `get_market_fundamental_by_date`에서 *forward EPS implied = price / PER* 1-month % change. 양수 = 상향 revision.

**Aggregation logic** (`tradingagents/skills/research/earnings_revision.py` 신규):

```python
def compute_sp500_net_revision(month_end: date, lookback_days: int = 30) -> float | None:
    """SP500 net revision proxy from yfinance upgrades_downgrades.
    
    For each SP500 constituent:
        1. fetch ticker.upgrades_downgrades (analyst rating actions)
        2. Filter to last `lookback_days`
        3. Count Action='upgrade' vs 'downgrade'
    
    Aggregated net ratio = (Σ upgrades - Σ downgrades) / Σ total
    
    Returns: float ∈ [-1, +1] (clipped to ±1), or None if coverage < 50%.
    Caching: ticker-level call results cached daily.
    """
    constituents = load_sp500_constituents()  # data/universe/sp500_constituents.json
    cutoff = month_end - timedelta(days=lookback_days)
    total_up, total_down, n_valid = 0, 0, 0
    for ticker in constituents:
        try:
            ud = yf.Ticker(ticker).upgrades_downgrades
            if ud is None or ud.empty:
                continue
            recent = ud[ud.index >= pd.Timestamp(cutoff)]
            ups = (recent["Action"].str.lower() == "upgrade").sum()
            downs = (recent["Action"].str.lower() == "downgrade").sum()
            if ups + downs > 0:
                total_up += ups
                total_down += downs
                n_valid += 1
        except Exception:
            continue
    if n_valid < len(constituents) * 0.5:
        return None
    total = total_up + total_down
    return (total_up - total_down) / total if total > 0 else 0.0


def compute_kospi200_net_revision(month_end: date) -> float | None:
    """KOSPI200 forward EPS revision via pykrx PER 1m change.
    
    EPS_forward = price / PER (implied). +1m change → upward revision.
    Aggregated as cap-weighted average of constituent EPS % change > 0 - < 0.
    
    Returns: float ∈ [-1, +1], or None if pykrx fetch fails / coverage < 50%.
    """
    from pykrx import stock as pkstock
    kospi200 = pkstock.get_index_portfolio_deposit_file("1028")  # KOSPI200
    n_up, n_down, n_valid = 0, 0, 0
    today_pers = pkstock.get_market_fundamental_by_date(month_end, market="KOSPI")
    month_ago = month_end - timedelta(days=30)
    prior_pers = pkstock.get_market_fundamental_by_date(month_ago, market="KOSPI")
    for ticker in kospi200:
        if ticker not in today_pers.index or ticker not in prior_pers.index:
            continue
        # Implied EPS from price / PER
        today_eps_idx = today_pers.loc[ticker, "PER"]
        prior_eps_idx = prior_pers.loc[ticker, "PER"]
        if today_eps_idx <= 0 or prior_eps_idx <= 0:
            continue
        # Lower PER (same price) = higher EPS = upward revision
        eps_change = (1/today_eps_idx - 1/prior_eps_idx) / (1/prior_eps_idx)
        if eps_change > 0.01:    n_up += 1
        elif eps_change < -0.01: n_down += 1
        n_valid += 1
    if n_valid < 100:  # < 50% of 200
        return None
    total = n_up + n_down
    return (n_up - n_down) / total if total > 0 else 0.0
```

**Component table:**

| Component | Source | Weight | Mode | Reliability |
|---|---|---|---|---|
| sp500_net_revision | yfinance upgrades_downgrades aggregation | 0.50 | both | medium |
| kospi200_net_revision | pykrx PER 1m change aggregation | 0.50 | both | medium |

**Backtest start:** 2010+ (yfinance coverage limit for KOSPI tickers + pykrx fundamental history). **Staggered calibration** in Tier 2 spec.

**알려진 제약:**
- yfinance `upgrades_downgrades`는 *analyst rating action* (upgrade/downgrade/maintain). EPS revision의 *correlated proxy*이나 직접 측정 아님.
- API rate limit: ticker-level call → 500 SP500 × monthly = 6000 call/month. yfinance soft limit (~2000/hour) 안 가까움.
- 캐싱: `data/cache/earnings_revision/{ticker}_ud.parquet`, daily TTL.
- KOSPI200 implied EPS는 forward 12m가 아닌 *trailing 12m* PER 기반 (pykrx 데이터) — 진정한 forward revision 아님 (proxy).

### 3.13. F12_china_credit_impulse (NEW)

**Sign convention:** +z = positive credit impulse (accelerating credit supply).

**Source:** BIS Total Credit (totcredit.xlsx), Q.CN.P.B.M.770.A.

**Calculation logic** (`tradingagents/skills/research/china_credit_impulse.py` 신규):

```python
def compute_china_credit_impulse(quarter_end: date) -> float | None:
    """Biggs-Mayer-Pick 2010 JMCB credit impulse.
    
    Steps:
    1. Fetch BIS quarterly credit-to-GDP ratio for China.
    2. First diff: Δ_t = ratio_t - ratio_{t-1}
    3. Year-over-year change in flow: Δ_t - Δ_{t-4}
    4. Normalize by lagged credit: (Δ_t - Δ_{t-4}) / credit_{t-4}
    
    Returns impulse value (typical range: -5% to +5%).
    None if insufficient lag history (< 5 quarters).
    """
    credit_to_gdp = fetch_bis_china_credit(as_of=quarter_end)
    if len(credit_to_gdp) < 5:
        return None
    diff_t = credit_to_gdp.iloc[-1] - credit_to_gdp.iloc[-2]
    diff_t4 = credit_to_gdp.iloc[-5] - credit_to_gdp.iloc[-6] if len(credit_to_gdp) >= 6 else 0.0
    credit_t4 = credit_to_gdp.iloc[-5]
    if credit_t4 == 0:
        return None
    return (diff_t - diff_t4) / credit_t4 * 100  # percent
```

**Component table:**

| Component | Source | Weight | Reliability |
|---|---|---|---|
| credit_impulse | ChinaCreditImpulseSnapshot.credit_impulse | 0.60 | high |
| credit_yoy_pct | ChinaCreditImpulseSnapshot.credit_yoy_pct | 0.30 | high |
| iron_ore_3m_pct | ChinaLeadingSnapshot.iron_ore_change_3m_pct | 0.10 | medium |

**Backtest start:** 1990+ (BIS 1989+ + 5-lag).

---

## 4. Sign Restriction 변경

`tradingagents/skills/research/factor_to_bucket.py:SIGN_RESTRICTION`

**제거 (Gemini deep research Section 7.2):**
- `("F5_credit_cycle", "precious_metals"): "positive"` — Brunnermeier-Pedersen 2009 dash-for-cash 모순
- `("F7_equity_vol_regime", "global_duration"): "positive"` — 2022 correlation breakdown 사례
- `("F7_equity_vol_regime", "precious_metals"): "positive"` — 동일

**유지:** 나머지 sign restriction (F1 growth → kr_eq+, F2 inflation → bond-, F3 real_rate → cash+ 등).

**Tier 1 spec과의 연계:** 8-bucket 새 schema에 맞춰 sign restriction 재배치 (Tier 1 §3 참조).

---

## 5. Z-baseline expanding window

### 5.1. 신규 모듈 `factor_baselines_dynamic.py`

```python
"""Expanding window z-score normalization.

Pesaran-Timmermann 1995 JF 'Predictability of Stock Returns: Robustness 
and Economic Significance' — static baseline의 look-ahead bias 제거.

기존 LONG_RUN_BASELINE static dict는 fallback (live mode 또는 historical 
series가 부족한 component용).
"""

from typing import Callable
from tradingagents.dataflows import fred, ecos, pykrx_data
from tradingagents.dataflows import shiller_cape, gpr_index, gz_ebp, bis_credit


# Component → (source_type, fetcher_callable) dispatch
COMPONENT_HISTORY_SOURCES: Final[dict[str, tuple[str, Callable]]] = {
    # ----- FRED direct -----
    "cfnai":             ("fred", lambda s, e: fred.fetch_fred_series("us_cfnai", s, e)),
    "cfnai_3m":          ("fred", lambda s, e: fred.fetch_fred_series("us_cfnai_ma3", s, e)),
    "vix_level":         ("fred", lambda s, e: fred.fetch_fred_series("vix_close", s, e)),
    "vix_z_score":       ("fred_derived", lambda s, e: _zscore_30d(fred.fetch_fred_series("vix_close", s, e))),
    "vix_term_ratio":    ("fred_derived", lambda s, e: fred.fetch_fred_series("vix_3m", s, e) / fred.fetch_fred_series("vix_close", s, e)),
    "move":              ("fred", lambda s, e: fred.fetch_fred_series("move", s, e)),
    "tips_yield":        ("fred", lambda s, e: fred.fetch_fred_series("us_tips_10y", s, e)),
    "hy_oas_bps":        ("fred", lambda s, e: fred.fetch_fred_series("us_hy_oas", s, e) * 100),
    "credit_quality_bps":("fred_derived", lambda s, e: (fred.fetch_fred_series("us_bbb_oas", s, e) - fred.fetch_fred_series("us_aaa_oas", s, e)) * 100),
    "funding_bps":       ("fred_derived", lambda s, e: fetch_funding_stress_stitched(s, e)),  # regime-aware
    "slope_2_10y":       ("fred_derived", lambda s, e: (fred.fetch_fred_series("us_10y", s, e) - fred.fetch_fred_series("us_2y", s, e)) * 100),
    "slope_5_30y":       ("fred_derived", lambda s, e: (fred.fetch_fred_series("us_30y", s, e) - fred.fetch_fred_series("us_5y", s, e)) * 100),
    "acm_term_premium_10y": ("fred", lambda s, e: fred.fetch_fred_series("us_acm_term_premium_10y", s, e)),
    "cpi_yoy":           ("fred_derived", lambda s, e: _yoy_pct(fred.fetch_fred_series("us_cpi", s, e))),
    "core_pce":          ("fred_derived", lambda s, e: _yoy_pct(fred.fetch_fred_series("us_core_pce", s, e))),
    "five_y_five_y":     ("fred", lambda s, e: fred.fetch_fred_series("us_5y5y_breakeven", s, e)),
    "michigan_1y":       ("fred", lambda s, e: fred.fetch_fred_series("us_michigan_1y", s, e)),
    "real_yield_inv":    ("fred_derived", lambda s, e: -fred.fetch_fred_series("us_tips_10y", s, e)),
    "fed_path_bps":      ("fred_derived", lambda s, e: (fred.fetch_fred_series("us_2y", s, e) - fred.fetch_fred_series("us_policy_rate", s, e)) * 100),
    "indpro_yoy":        ("fred_derived", lambda s, e: _yoy_pct(fred.fetch_fred_series("us_indpro", s, e))),
    "real_pce_yoy":      ("fred_derived", lambda s, e: _yoy_pct(fred.fetch_fred_series("us_real_pce", s, e))),
    "krw_change_6m_pct": ("fred_derived", lambda s, e: _pct_change_n(fred.fetch_fred_series("usd_krw", s, e), 126)),  # ~6mo trading days
    "krw_reer":          ("fred", lambda s, e: fred.fetch_fred_series("kr_reer", s, e)),
    
    # ----- ECOS (KR) -----
    "kr_corp_spread_bps":("ecos_derived", lambda s, e: (ecos.fetch_ecos_series("kr_corp_aa_3y", s, e, freq="D") - ecos.fetch_ecos_series("kr_treasury_3y", s, e, freq="D")) * 100),
    
    # ----- pykrx (KR fundamental) -----
    "kospi_pbr":         ("pykrx", lambda s, e: pykrx_data.fetch_kospi200_pbr_series(s, e)),
    "kospi_per":         ("pykrx", lambda s, e: pykrx_data.fetch_kospi200_per_series(s, e)),
    "kospi_div_yield":   ("pykrx", lambda s, e: pykrx_data.fetch_kospi200_div_series(s, e)),
    
    # ----- External CSV scrapers (TTL cached) -----
    "us_cape":           ("shiller", lambda s, e: shiller_cape.fetch_shiller_cape(as_of=e)[s:]),
    "gpr_index_zscore":  ("iacoviello_derived", lambda s, e: _zscore_60m(gpr_index.fetch_gpr_index("monthly", as_of=e)[s:])),
    "gz_ebp":            ("fed_board", lambda s, e: gz_ebp.fetch_gz_ebp(as_of=e)[s:]),
    "credit_impulse":    ("bis_derived", lambda s, e: _biggs_mayer_pick(bis_credit.fetch_bis_china_credit(as_of=e)[s:])),
    "credit_yoy_pct":    ("bis_derived", lambda s, e: _yoy_pct(bis_credit.fetch_bis_china_credit(as_of=e)[s:])),
    
    # ----- F11 (staggered, limited history) -----
    "sp500_net_revision":("yfinance_aggregate", lambda s, e: _yfinance_sp500_revision_history(s, e)),
    "kospi200_net_revision": ("pykrx_aggregate", lambda s, e: _pykrx_kospi_revision_history(s, e)),
    
    # 위 dispatch table 외 component (예: sentiment, news-derived)는 expanding window 
    # 부재 → static LONG_RUN_BASELINE fallback.
}


def compute_expanding_baseline(
    component: str,
    factor: str,
    as_of_date: date,
    history_start: date = date(1971, 1, 1),
) -> tuple[float, float] | None:
    """Returns (mean, sd) computed from history_start to as_of_date - lag.
    
    Caching: per-component parquet at data/cache/factor_history/{component}.parquet
    weekly refresh.
    
    Returns None if:
    - component not in COMPONENT_HISTORY_SOURCES (news-derived 등) → static fallback
    - history series fetch 실패 → static fallback
    - n < 60 (5 years minimum for stable estimate) → static fallback
    """
    # Regime-aware special case for funding_bps (SOFR-TED stitching)
    if component == "funding_bps":
        return compute_expanding_baseline_funding_stress(as_of_date)
    
    if component not in COMPONENT_HISTORY_SOURCES:
        return get_baseline(factor, component)  # static fallback
    
    series = _get_cached_or_fetch(component, history_start, as_of_date)
    if series is None or len(series) < 60:
        return get_baseline(factor, component)
    return float(series.mean()), float(series.std(ddof=1))


def _get_cached_or_fetch(component: str, start: date, end: date) -> pd.Series | None:
    """Disk cache wrapper around dispatch table fetchers."""
    cache_path = Path(f"data/cache/factor_history/{component}.parquet")
    # Check cache freshness (weekly TTL)
    if cache_path.exists():
        mtime = datetime.fromtimestamp(cache_path.stat().st_mtime)
        if (datetime.now() - mtime).days < 7:
            cached = pd.read_parquet(cache_path)
            return cached["value"].loc[str(start):str(end)]
    # Cache miss or stale — refetch
    _, fetcher = COMPONENT_HISTORY_SOURCES[component]
    try:
        series = fetcher(start, end)
        if series is not None and len(series) > 0:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            series.to_frame(name="value").to_parquet(cache_path)
        return series
    except Exception as ex:
        logger.warning("factor_baselines_dynamic: fetch %s failed: %s", component, ex)
        return None
```

### 5.2. `_aggregate` 함수 수정

```python
def _aggregate(
    factor_name: str,
    components_raw: dict[str, float | None],
    weights: dict[str, float],
    mode: FactorMode = "production",
    use_dynamic_baseline: bool = True,    # NEW
    as_of_date: date | None = None,        # NEW
) -> FactorScore:
    ...
    for name, raw in components_raw.items():
        if raw is None:
            continue
        if use_dynamic_baseline and as_of_date is not None:
            baseline = compute_expanding_baseline(name, factor_name, as_of_date)
            if baseline is None:
                z = z_score(float(raw), factor_name, name)  # static fallback
            else:
                mean, sd = baseline
                z = (float(raw) - mean) / sd if sd > 0 else None
        else:
            z = z_score(float(raw), factor_name, name)  # static
        if z is None:
            continue
        ...
```

### 5.3. Acceptance criteria

- Backtest (use_dynamic_baseline=True) mode에서 모든 factor z-score는 *as-of date까지의 데이터만* 사용
- Live mode (as_of_date=None)는 static baseline 사용
- Unit test: `as_of_date=2000-01-01`에서 factor z 계산 시 2000-01 이후 데이터 *접근 안 됨* 검증

---

## 6. Reliability tier (hybrid)

### 6.1. Hand-coded baseline (`factor_reliability_audit.py` 확장)

Tier 0 새 component 추가:

```python
COMPONENT_RELIABILITY: Final[dict[str, Reliability]] = {
    # ... 기존 ...
    
    # NEW (Tier 0)
    "indpro_yoy":           "high",
    "real_pce_yoy":         "high",
    "acm_term_premium_10y": "high",
    "gz_ebp":               "high",
    "kr_corp_spread_bps":   "high",
    "krw_change_6m_pct":    "high",
    "krw_reer":             "high",
    "us_cape":              "medium-high",  # 정의/방법론 debated post-2010
    "kospi_per":            "high",
    "kospi_div_yield":      "high",
    "gpr_index_zscore":     "high",
    "sp500_net_revision":   "medium",       # yfinance coverage partial
    "kospi200_net_revision":"medium",       # pykrx implied
    "credit_impulse":       "high",
    "credit_yoy_pct":       "high",
}
```

### 6.2. Empirical posterior precision (Tier 2 dependency)

`tradingagents/skills/research/factor_reliability_empirical.py` 신규 (Tier 2에서 학습):

```python
def estimate_component_reliability_empirical(
    component: str,
    factor: str,
    history_window: tuple[date, date],
) -> Reliability:
    """Walk-forward에서 각 component의 univariate predictive power 평가.
    
    1/Var(prediction error) 가중. Granger-Newbold 1986 Forecasting Economic Time Series §5.
    
    Hand-coded baseline + empirical override (Bayesian update).
    """
    ...
```

`get_weight_cap(component)`을 hybrid로 변경:
```python
def get_weight_cap(component: str, mode: str = "static") -> float:
    if mode == "empirical":
        tier = COMPONENT_RELIABILITY_EMPIRICAL.get(component, get_reliability(component))
    else:
        tier = get_reliability(component)
    return WEIGHT_CAP_BY_RELIABILITY[tier]
```

---

## 7. News-derived components 처리

**결정: PR2a graceful degradation pattern 유지.**

- Backtest mode (`mode="historical"`): NEWS_DERIVED_COMPONENTS frozenset drop + quant weight 재정규화 (PR2a 기존)
- Live mode (`mode="production"`): news + quant 둘 다 사용
- Tier 3 LLM overlay는 *factor model 위에 additive* — factor를 대체 X

**NEWS_DERIVED_COMPONENTS 변경:**

```python
NEWS_DERIVED_COMPONENTS: Final[frozenset[str]] = frozenset({
    # F1 (제거 component 제외)
    "release_surprise", "hawkish_bias", "macro_sent", "risk_regime_overnight",
    # F2
    "release_hawkish",
    # F3
    "fed_voting_balance",
    # F4
    "fed_tone_balance",
    # F5
    "corporate_distress", "dovish_bias",
    # F6
    "krw_overnight_pct", "bok_tone_balance",
    # F7 (geopolitical_surge 제거 — GPR Index가 quant)
    "sentiment_dispersion",
    # F9 (기존 — F9 rename에도 동일)
    "event_cluster", "rising_signal",
})
```

**Live-only quant components (Option C):**
- `gdpnow`: backtest mode에서 drop, live mode에서 사용

```python
LIVE_ONLY_QUANT_COMPONENTS: Final[frozenset[str]] = frozenset({
    "gdpnow",  # 2011+ short backtest history, live에서만 real-time advantage
})

def _aggregate(...):
    if mode == "historical":
        components_raw = {
            k: v for k, v in components_raw.items()
            if k not in NEWS_DERIVED_COMPONENTS
            and k not in LIVE_ONLY_QUANT_COMPONENTS
        }
    ...
```

---

## 8. F11 Staggered Calibration handling

**Stage 1/Stage 2 측면:**
- F11 factor z-score는 2010+에서만 계산 (yfinance coverage limit)
- `compute_earnings_revision()`은 2010 이전 quarter에 대해 `FactorScore(z_score=0, confidence=0)` 반환
- `to_dict()`에서 F11이 confidence=0 이면 *factor에서 제외* (None 반환)

**Tier 2 dependency:** β의 F11 column (8 entries)은 *별도 staggered fit*. T2 spec §5 참조.

---

## 9. 영향받는 파일 목록

| File | 변경 |
|---|---|
| `tradingagents/schemas/macro.py` | FXSnapshot.krw_change_6m_pct/krw_reer 추가, CommodityMomentumSnapshot/USEquityValuationSnapshot/GeopoliticalRiskSnapshot/ChinaCreditImpulseSnapshot/EarningsRevisionSnapshot 신규, ForeignFlowSnapshot.net_20d_normalized 추가 |
| `tradingagents/schemas/risk.py` | ExcessBondPremiumSnapshot 신규 |
| `tradingagents/schemas/reports.py` | MacroReport에 new Optional fields 추가 |
| `tradingagents/dataflows/fred.py` | FRED_SERIES dict 5개 추가 (us_indpro, us_real_pce 등), fetch_funding_stress_stitched 신규 |
| `tradingagents/dataflows/shiller_cape.py` | 신규 |
| `tradingagents/dataflows/gpr_index.py` | 신규 |
| `tradingagents/dataflows/gz_ebp.py` | 신규 |
| `tradingagents/dataflows/bis_credit.py` | 신규 |
| `tradingagents/agents/analysts/macro_quant_analyst.py` | 새 snapshot 채우는 logic 추가 |
| `tradingagents/agents/analysts/macro_news_analyst.py` | (변경 없음 — news component 그대로) |
| `tradingagents/agents/analysts/market_risk_analyst.py` | ExcessBondPremium/USEquityValuation 채움 |
| `tradingagents/skills/research/factor_estimators.py` | FACTORS tuple, FactorScores dataclass, compute_* 함수 12개, NEWS_DERIVED_COMPONENTS/LIVE_ONLY_QUANT_COMPONENTS, F9 rename |
| `tradingagents/skills/research/factor_baselines.py` | LONG_RUN_BASELINE 새 component baseline 추가 |
| `tradingagents/skills/research/factor_baselines_dynamic.py` | 신규 (expanding window) |
| `tradingagents/skills/research/factor_reliability_audit.py` | new component reliability tier 추가, hybrid mode |
| `tradingagents/skills/research/factor_reliability_empirical.py` | 신규 (Tier 2 dependency) |
| `tradingagents/skills/research/earnings_revision.py` | 신규 (F11 aggregation) |
| `tradingagents/skills/research/china_credit_impulse.py` | 신규 (F12 Biggs-Mayer-Pick) |
| `tradingagents/skills/research/factor_to_bucket.py` | FACTORS tuple, INITIAL_BETA prior 12×8 (Tier 1 dependency), SIGN_RESTRICTION update, INITIAL_TIPS_BETA 12 entries 확장 |
| `backtest/historical/stage1_builder.py` | 새 component historical fetch logic, expanding window 호환 |
| `backtest/historical/fetcher_yfinance.py` | F11 earnings revision history fetch (2010+) |
| `backtest/historical/fetcher_pykrx.py` | kospi_per/kospi_div_yield 활성화 |
| `tests/unit/schemas/test_macro.py` | new snapshot tests |
| `tests/unit/skills/research/test_factor_estimators.py` | 12 factor tests, GDPNow live-only, news drop, expanding window |
| `tests/unit/dataflows/test_shiller_cape.py`, etc. | 신규 fetcher tests with mock |

**총 영향:** ~25 file 신규/수정. PR 단위로 분할 권고 (T0 단일 PR이면 review 어려움 — sub-PR 분리: data sources / factor reform / news handling / staggered F11).

---

## 10. Acceptance Criteria

### 10.1. Data layer
- [ ] 모든 신규 FRED series (THREEFYTP10, INDPRO, PCECC96, RBKRBIS, TEDRATE) fetch 성공 + publication lag 정확
- [ ] Shiller CAPE Excel parser 작동 (Yale column schema 변경 시 fallback)
- [ ] Caldara-Iacoviello GPR Excel parser (monthly + daily)
- [ ] Fed Board GZ EBP CSV parser
- [ ] BIS Total Credit (totcredit.xlsx) parser + Q.CN.P.B.M.770.A series 추출
- [ ] SOFR-TED stitching 검증: 2018-04-03 boundary 정확, scale 통합 z-score 검증

### 10.2. Factor estimators
- [ ] 12 factor 모두 `compute_<factor>(stage1, mode='historical')` 작동 (synthetic test fixture)
- [ ] F1 backtest mode에서 gdpnow + news drop, quant weight (cfnai/cfnai_3m/sahm/indpro_yoy/real_pce_yoy) renormalized to 1.0
- [ ] F4 backtest mode에서 ACM term premium (THREEFYTP10) 사용 검증
- [ ] F6에서 krw_level component 제거 확인, krw_change_6m_pct + krw_reer 활용 검증
- [ ] F7에서 geopolitical_surge → gpr_index_zscore 전환 검증
- [ ] F8 weight 분포: US 0.55, KR 0.45 (sum 1.0)
- [ ] F9 rename: `F9_market_dispersion` 키 사용 (모든 reference 검증)
- [ ] F10 sofr_tbill_spread는 stitched series 사용
- [ ] F11 staggered: 2010 이전 quarter에서 confidence=0 반환, `to_dict()`에서 제외
- [ ] F12 Biggs-Mayer-Pick 정확도: known case (e.g., 2009 Q1 China stimulus) 검증

### 10.3. Sign restriction
- [ ] `SIGN_RESTRICTION` dict에서 F5×precious, F7×gl_dur, F7×precious 3개 entry 제거 확인
- [ ] 새 sign restriction은 8-bucket schema (Tier 1)에 맞춰 정의

### 10.4. Expanding window z-baseline
- [ ] `factor_baselines_dynamic.compute_expanding_baseline()`이 as_of_date 까지의 데이터만 사용
- [ ] Look-ahead bias 검증: `as_of=2000-01-01` 호출 시 2000-01-02 이후 데이터 접근 시도 없음
- [ ] Fallback chain: expanding 실패 → static LONG_RUN_BASELINE → None drop

### 10.5. Reliability tier
- [ ] 새 15 component 모두 reliability tier 할당 (`COMPONENT_RELIABILITY` dict)
- [ ] Empirical override mode 작동 (`get_weight_cap(name, mode='empirical')`)

### 10.6. Integration
- [ ] `research_manager.py:334`의 `apply_factor_model_with_safety(z)` 호출이 12 factor 처리
- [ ] Production live trading에서 GDPNow + news components 정상 작동 (graceful degradation 호환)
- [ ] Backtest mode에서 news + gdpnow drop, factor z magnitudes는 production과 유사 scale 유지

### 10.7. Test plan
- [ ] Unit tests: 각 fetcher module + each compute_<factor> function
- [ ] Integration test: stage1_builder.py가 모든 신규 snapshot 채움 (mock fixtures)
- [ ] Regression test: 5-bucket 시절 PR2a/2b validation 결과는 reference로 보존 (8-bucket Tier 1+2 결과와 비교)
- [ ] Look-ahead bias test: 2000-01-01 시점 simulation 에서 신규 component history (1971-1999) 만 사용 확인

---

## 11. Out of Scope

다음은 Tier 0에서 처리하지 않음:

- **β prior 12×8 numeric matrix**: Tier 1 spec (bucket taxonomy)에서 정의
- **Bucket family grouping** (hierarchical prior): Tier 2 spec
- **Hard zero cells** (~25 cells): Tier 2 spec
- **Component weight PCA / walk-forward derivation**: hand-coded 유지, v2 deferral
- **KOSPI CAPE 계산 logic** (10y rolling KOSPI EPS): v2 deferral (Tier 0에서는 KOSPI CAPE 제외)
- **F11 paid IBES 통합**: yfinance partial coverage 유지, paid는 v2
- **VIF/Effective df check**: Tier 2 spec acceptance criteria
- **LLM overlay**: Tier 3 spec

---

## 12. 참고문헌 (학술 검증)

- Adrian-Crump-Moench 2013 *RFS* "Pricing the Term Structure with Linear Regressions" (F4 ACM)
- Asness 2003 *FAJ* "Speculative Bubbles, Excess Volatility, and Mean Reversion" (F8 CAPE)
- Asness-Frazzini-Pedersen 2019 (F11 earnings revision)
- Baxter-Jermann 1997 (F8 home bias 정당화)
- Biggs-Mayer-Pick 2010 *JMCB* "Credit and Economic Recovery" (F12 credit impulse)
- Bekaert-Hodrick-Zhang 2009 *JFE* (F5 KR credit)
- Brunnermeier-Pedersen 2009 *RFS* "Market Liquidity and Funding Liquidity" (Sign restriction relaxation)
- Caldara-Iacoviello 2018/2022 *AER* "Measuring Geopolitical Risk" (F7 GPR)
- Chan-Jegadeesh-Lakonishok 1996 *JF* (F11 earnings momentum)
- Cooper-Mitrache-Priestley 2017 *JFE* (F1 global growth factor)
- Engel-West 2005 *JPE* "Exchange Rates and Fundamentals" (F6 random walk)
- Erb-Harvey 2006 *FAJ* (Commodity momentum)
- Gemini Deep Research 2026-05-28 "다중 자산 포트폴리오 운용 거시경제 팩터 모델" (entire reform validated)
- Gilchrist-Zakrajsek 2012 *AER* "Credit Spreads and Business Cycle Fluctuations" (F5 GZ EBP)
- Granger-Newbold 1974 (Spurious regression)
- Heathcote-Perri 2013 (Home bias)
- Meese-Rogoff 1983 "The Out-of-Sample Failure of Empirical Exchange Rate Models" (F6 random walk)
- Pesaran-Timmermann 1995 *JF* "Predictability of Stock Returns" (Expanding window)
- Pflueger-Viceira 2011 *RFS* (TIPS liquidity premium)
- Rey 2013 Jackson Hole "Dilemma not Trilemma" (Global financial cycle)
- Stock-Watson 2002 *JBES* "Forecasting Using Principal Components" (Component aggregation)

---

**Next:** Tier 1 spec (bucket taxonomy) + Tier 2 spec (calibration) + Tier 3 spec (LLM overlay).
