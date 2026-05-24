# Stage 2a — Factor Model β Calibration (Historical Walk-forward)

- **작성일:** 2026-05-23
- **선행:** PR1 Stage 1 enhance (`feat/stage1-enhance-for-factor-model`, commit e52e2dc, C11 완료)
- **Branch base:** PR1 branch (또는 merge 후 main 등가)
- **Scope:** Historical Stage 1 reconstruction (1991-2024) + walk-forward β calibration + INITIAL_BETA 교체 (acceptance gate PASS 시)
- **Out of scope:** Benchmark 비교 + empirical superiority 통계 검증 → PR2b
- **Delivery:** Single PR (PR2a) with clear commit 분리 (C0-C10)
- **Effort:** ~38-48h (PR1 의 40-55h 와 비슷 magnitude)
- **Quality gates:** 매 commit regression test + selective grill-me 3 회
- **Followup:** PR2b benchmark 비교 + 통계 검증 (별도 spec)

---

## 0. 결정 요약

### 0.1 Brainstorming Q1-Q9 결정

| Decision | Choice | 출처 |
|---|---|---|
| Q1 Scope | 2-PR decompose — PR2a = data + calibration, PR2b = benchmarks + analysis | brainstorm Q1 |
| Q2 Window | 1991-2024 (135Q) with graceful per-factor degradation | brainstorm Q2 |
| Q3 Calib target | β only (45 params) with shrinkage + sign penalty (PR1 C6 `hybrid_calibration` 재사용) | brainstorm Q3 |
| Q4 Calib protocol | Shrinkage grid {0.1, 0.3, 0.5, 1.0, 2.0} × walk-forward (initial_train=80, **test=7** → 7 folds) | brainstorm Q4 |
| Q5 Acceptance | Default 5-condition **+ statistical rigor 강화** (Critical 3) | brainstorm Q5 + Critical 3 |
| Q6 Reconstruction | C — production reuse with date-parameterized minimal-proxy Stage 1 builder | brainstorm Q6 |
| Q7 Linux/cache | Linux-first + multi-tier cache (raw gitignored, quarterly indicators + factor z + bucket returns committed) | brainstorm Q7 |
| Q8 Execution | PR1 방식 — commit 순차 + grill-me 3회 + per-commit regression test | brainstorm Q8 |
| Q9 Issue scope | 최소 범위 — Linux 우회로 Issue #20/#21, 영구 fix 는 별도 PR | brainstorm Q9 |

### 0.2 Critical issue 처리

| # | Issue | 처리 |
|---|---|---|
| C1 | Point-in-time data / look-ahead bias | ALFRED vintage fetch for 7 revising series (CFNAI, NFCI, ANFCI, GDPNOW, UNRATE, CPIAUCSL, PCEPILFE) |
| C2 | News-sentinel 의 production-historical model 불일치 | `factor_estimators.py` 에 `mode="historical"` flag 추가 (backward-compat default `"production"`) — news weight 0 + quant weight renormalize |
| C3 | Acceptance gate 의 statistical rigor 부족 | improvement: paired-t-test p<0.20 추가; overfit guard: \|mean(IS)-mean(OOS)\|<0.30 (lenient 0.50 에서 강화); fold positive: ≥6 of 7 (5/7 에서 강화) |
| C4 | Bucket return 의 currency basis 미명시 | **KRW basis** (KR investor mandate), USD 자산 의 USDKRW translation, pre-1996 kr_equity = None (KOSPI 부재) |

### 0.3 Minor (informational diagnostic only, gate 아님)

| # | 항목 | 처리 |
|---|---|---|
| M1 | Sign penalty 100x 가 사실상 hard constraint — calibrated β 가 prior 근처 stuck 가능 | `\|β_calibrated - β_prior\|<0.001` 비율 > 80% 시 informational warning |
| M2 | Shrinkage grid 모두에서 OOS 비슷 → best 선택 noise | `\|β_0.1 - β_2.0\|_avg < 0.01` 시 "calibration is non-informative" warning |
| M3 | Prior INITIAL_BETA 가 hand-coded — improvement baseline 신뢰성 | equi-weight β=0 의 OOS Sharpe 도 reporting (informational) |
| M4 | sample_quality 미사용 (era 별 confidence 차이) | 기록 only, PR2b 의 era-stratified sensitivity 로 후속 |
| M5 | Robustness penalty 계수 0.25 임의 | spec 안에 documentation 고정, alternative 는 PR2b sensitivity |

---

## 1. 배경 + 동기

### 1.1 PR1 후 현재 state

PR1 완료 (C11 e52e2dc) 로:
- Factor estimator field path 100% 정확 (~17 fix + 5 신규 component 활성화)
- 9 factor 의 진짜 component coverage ≥ 90%
- C2/C9 real schema integration test 으로 silent-broken 재발 차단
- 2026-05-15 산출물의 factor z 값이 실제 9 factor signal 의 결과

→ **PR2a 의 모든 input 이 production grade**.

### 1.2 PR2a 의 단일 목적

`tradingagents/skills/research/factor_to_bucket.py` 의 `INITIAL_BETA` (factor → bucket mapping 의 hand-coded 45 weight) 를 **historical walk-forward Sharpe optimization 으로 data-driven 으로 교체** — acceptance gate PASS 시.

### 1.3 PR2a 의 non-goal

- Benchmark 비교 (24-cell / 60-40 / 1-N / risk parity) → **PR2b**
- Empirical superiority 통계 검증 (t-test, regime decomposition, drawdown analysis) → **PR2b**
- `INITIAL_BASELINE` calibration (현재 hand-coded 유지) → 별도 PR
- Per-contribution cap / factor weights fit → 별도 PR
- Issue #20/#21 (Windows curl_cffi / pykrx API) 의 영구 fix → 별도 PR
- News component 의 historical LLM replay → 영구 sentinel 유지
- ALFRED vintage 확장 (7 series 외 다른 revising series) → 별도 PR
- `mode="historical"` 의 production sensitivity sweep → PR2b
- era-specific calibration (era 별 separate β) → PR2b sensitivity
- 2026-05-15 산출물 regen with new INITIAL_BETA → 별도 follow-up commit 또는 PR2b
- Acceptance gate FAIL 시 "design 재검토" → PR2a 안에서 처리 X (Issue 작성 후 follow-up)

---

## 2. Architecture Overview

### 2.1 전체 pipeline

```
[Linux CI 또는 Linux 환경의 PR2a fetch — Issues #20/#21 우회]
  │
  ├─ FRED fetcher (fredapi) — latest-vintage daily/monthly
  │    → 1991-2024: CPI, GDP, DGS{2,5,10,30}, BAA, AAA, BAA10Y, TB3MS,
  │                   T10YIE, T5YIFR, DFII10, DEXKOUS, DTWEXM, MICH, USREC, UNRATE
  ├─ ALFRED fetcher (Critical 1) — vintage-aware
  │    → 7 revising series: CFNAI, NFCI, ANFCI, GDPNOW, UNRATE,
  │                          CPIAUCSL, PCEPILFE
  ├─ yfinance fetcher (Linux 에서만 SSL 정상)
  │    → 1991-2024 daily Close: ^GSPC, ^KS11, ^VIX, ^SKEW, IEF, TIP, DJP,
  │                              GC=F, 9 sector ETF, ^IRX
  └─ pykrx fetcher (Linux 에서만 API 정상)
       → 2001-2024 monthly: KOSPI200 PBR/PER/DivYield
       → 2003-2024 monthly: 외국인 순매수 net flow
  │
  ▼
[backtest/historical/raw/*.parquet] — gitignored, ~5-10MB total
  │
  ▼
[Quarterly aggregation (aggregate.py)]
  → quarterly indicator panel: 135 row × ~40 col
  ▼
[backtest/historical/quarterly_indicators.parquet] — committed (~500KB)
  │
  ▼
[_build_historical_stage1(date, indicators_q)] — date-parameterized builder
  → 매 quarter t 에서 MacroReport/RiskReport/TechnicalReport/NewsReport instance
  → news_report 의 LLM-derived field = sentinel (z=0)
  → pre-availability era field = sentinel (None 또는 0.0)
  │
  ▼
[compute_all_factors(state, mode="historical")] — Critical 2
  → 9 factor z + 9 factor confidence per quarter
  → news weight 0 + quant weight renormalize → factor z 가 production scale 과 매치
  ▼
[backtest/historical/factor_z.parquet] — committed (~50KB)
  │
  ▼
[Quarterly bucket returns (bucket_returns.py)] — Critical 4
  → 5 bucket × 135 quarter, KRW basis
  → USD 자산 = USDKRW translation
  → pre-1996 kr_equity = None (KOSPI 부재)
  ▼
[backtest/historical/bucket_returns.parquet] — committed (~30KB)
  │
  ▼
[backtest/historical/samples.parquet] — joined HistoricalSample list, committed (~100KB)
  │
  ▼
[scripts/calibrate_factor_model.py]
  → 5 shrinkage × 7 fold × L-BFGS-B optim = 35 calibration runs
  → prior_baseline OOS Sharpe (no-fit walk-forward)
  → equi-weight baseline OOS Sharpe (informational M3)
  → vintage sanity check (latest vs vintage β 비교)
  ▼
[artifacts/2026-05-XX/calibration_runs/*] — committed
  │
  ▼
[Acceptance gate evaluation (acceptance.py)]
  → 5 strict-default condition + paired-t-test + diagnostic
  ▼
[artifacts/2026-05-XX/validation_report.json] — committed
  │
  ▼ (PASS 시)
[INITIAL_BETA 교체] in tradingagents/skills/research/factor_to_bucket.py
  + production unit test 의 INITIAL_BETA 의존 assertion update
  │
  ▼ (FAIL 시)
[docs/followup_issues.md 의 신규 Issue 작성]
  → PR2a status = "FAIL", design 재검토 follow-up
```

### 2.2 신규 file / 변경 file

#### Created (production)
- `tradingagents/backtest/historical/__init__.py`
- `tradingagents/backtest/historical/fetcher_fred.py` — FRED latest-vintage fetch + parquet cache
- `tradingagents/backtest/historical/fetcher_alfred.py` — ALFRED vintage-aware fetch (Critical 1)
- `tradingagents/backtest/historical/fetcher_yfinance.py` — yfinance daily fetch + parquet
- `tradingagents/backtest/historical/fetcher_pykrx.py` — pykrx KR fetch + parquet
- `tradingagents/backtest/historical/aggregate.py` — daily/monthly → quarterly indicator panel + derived
- `tradingagents/backtest/historical/stage1_builder.py` — `build_historical_stage1(date, indicators_q)`
- `tradingagents/backtest/historical/bucket_returns.py` — 5-bucket quarterly return (KRW basis)
- `tradingagents/backtest/historical/shiller_cape_static.csv` — Shiller CAPE 정적 commit (~50KB)
- `tradingagents/backtest/acceptance.py` — acceptance gate evaluation (5 condition + paired-t + diagnostic)
- `scripts/generate_historical_factor_z.py` — end-to-end fetch → aggregate → build → compute → parquet
- `scripts/calibrate_factor_model.py` — walk-forward + shrinkage grid + acceptance evaluation runner

#### Created (tests)
- `tests/unit/backtest/historical/test_fetcher_fred.py`
- `tests/unit/backtest/historical/test_fetcher_alfred.py`
- `tests/unit/backtest/historical/test_fetcher_yfinance.py`
- `tests/unit/backtest/historical/test_fetcher_pykrx.py`
- `tests/unit/backtest/historical/test_aggregate.py`
- `tests/unit/backtest/historical/test_stage1_builder.py`
- `tests/unit/backtest/historical/test_bucket_returns.py`
- `tests/unit/skills/research/test_factor_estimators_historical_mode.py` — Critical 2 의 backward-compat 보장 + historical mode 의 quant-only renorm 검증
- `tests/integration/test_calibration_pipeline_synthetic.py` — walk-forward + acceptance gate synthetic smoke
- `tests/integration/test_historical_factor_z_end_to_end.py` — opt-in (env var) Linux-only end-to-end

#### Created (artifacts)
- `artifacts/2026-05-XX/decisions.md` — C0
- `artifacts/2026-05-XX/regression_log.md` — C0 + 매 commit entry
- `artifacts/2026-05-XX/job_status.json` — long fetch + calibration 작업 상태
- `artifacts/2026-05-XX/calibration_runs/per_fold/shrinkage_{s}_fold_{i}.json` (35 files)
- `artifacts/2026-05-XX/calibration_runs/per_shrinkage_summary.json`
- `artifacts/2026-05-XX/calibration_runs/best_shrinkage.json`
- `artifacts/2026-05-XX/calibration_runs/vintage_sanity.json`
- `artifacts/2026-05-XX/calibration_runs/equi_weight_baseline.json` (M3)
- `artifacts/2026-05-XX/calibration_runs/learning_sensitivity.json` (M2)
- `artifacts/2026-05-XX/calibration_runs/validation_report.json`

#### Modified
- `tradingagents/skills/research/factor_estimators.py` — `mode` parameter 추가 (Critical 2)
- `tradingagents/skills/research/factor_to_bucket.py` — `INITIAL_BETA` 교체 (C9, PASS 시)
- `tests/unit/skills/research/test_factor_to_bucket.py` — INITIAL_BETA 의존 assertion update (C9, PASS 시)
- `.gitignore` — `backtest/historical/raw/` 추가
- `docs/followup_issues.md` — Issue #18 status update (C10)
- `docs/superpowers/specs/2026-05-23-stage2a-calibration-design.md` — 본 spec, C10 의 status checkmark

### 2.3 기존 module 와의 관계

- `tradingagents/skills/research/factor_calibration.py` (PR1 C6) — **그대로 사용**: `walk_forward`, `hybrid_calibration`, `aggregate_median_beta`, `compute_sharpe` 재사용.
- `tradingagents/skills/research/factor_estimators.py` (PR1 C1+C8) — **`mode` parameter 1 개 추가** (backward-compat).
- `tradingagents/backtest/data.py` (24-cell legacy) — **참조 only**: 일부 yfinance fetch 로직을 `fetcher_yfinance.py` 로 이전 가능.
- `tradingagents/backtest/optimize.py` (24-cell legacy) — **변경 0**: PR2b 의 24-cell benchmark 가 참조.

### 2.4 Downstream interface 변화

- `compute_all_factors` 시그니처: `(state) → (state, mode="production")`. default 적용 → 기존 호출 100% 영향 0.
- `INITIAL_BETA` 값 변화 (PASS 시) → `apply_factor_model` output (bucket weight) 변화 → allocator / risk_judge / portfolio_manager 의 *input* 만 변화 (interface 변경 0).
- `BucketTarget` schema 변경 0.

---

## 3. Historical Stage 1 Reconstruction

### 3.1 핵심 아이디어

PR1 C2 의 `_build_real_stage1_baseline()` (모든 schema instance baseline values) 패턴을 **date-parameterized 로 확장**. `compute_all_factors(state, mode="historical")` 는 변경 없이 호출.

### 3.2 Fetch 대상 indicator 명세

| Factor | Component | Source | 가용 시기 | Fetch | Vintage-aware? |
|---|---|---|---|---|---|
| F1 | GDP nowcast | GDPNOW (FRED) | 2011+ | FRED + ALFRED | ✓ |
| F1 | NFCI / ANFCI | NFCI, ANFCI (FRED) | 1971+ weekly | FRED + ALFRED | ✓ |
| F1 | CFNAI / CFNAI 3m | CFNAI (FRED) | 1967+ monthly | FRED + ALFRED | ✓ |
| F1 | Sahm rule | derived from UNRATE (FRED) | 1948+ | FRED + ALFRED | ✓ |
| F1 | Yield curve 2-10y | DGS10 - DGS2 (FRED) | 1976+ daily | FRED | — (daily, no revise) |
| F2 | CPI YoY / 3mo mom | CPIAUCSL (FRED) | 1948+ monthly | FRED + ALFRED | ✓ |
| F2 | Core CPI YoY | CPILFESL (FRED) | 1957+ monthly | FRED | — |
| F2 | PCE / Core PCE YoY | PCEPI, PCEPILFE (FRED) | 1959+ monthly | FRED + ALFRED | ✓ (Core PCE) |
| F2 | Breakeven 5y5y | T5YIFR (FRED) | 2003+ daily | FRED | — |
| F2 | Michigan 1y | MICH (FRED) | 1978+ monthly | FRED | — |
| F3 | Real yield 10y | DFII10 (FRED) | 2003+ daily | FRED | — |
| F4 | Spread 30y-5y | DGS30 - DGS5 (FRED) | 1977+ daily, **gap 2002-2006** | FRED | — |
| F4 | Inverted days / percentile | derived from spread_10y_2y | 1976+ | derived | — |
| F5 | BAA-AAA spread | BAA - AAA (FRED) | 1919+ monthly | FRED | — |
| F5 | BAA-10y spread | BAA10Y (FRED) | 1986+ daily | FRED | — |
| F6 | USD/KRW | DEXKOUS (FRED) | 1981+ daily | FRED | — |
| F6 | DXY broad | **DTWEXM** (FRED, major currencies) | 1973+ daily | FRED | — |
| F6 | KR base rate / gap | BOK base rate | 1999+ | static csv / FRED | — |
| F6 | Foreign flow net z | pykrx 외국인 순매수 | 2003+ | pykrx (Linux) | — |
| F7 | VIX | ^VIX (yfinance) | 1990+ daily | yfinance | — |
| F7 | MOVE | **derived** from DGS10 60d realized vol × 100 | 1976+ | derived fallback | — |
| F7 | VIX term ratio | ^VIX9D / ^VIX (yfinance) | 2011+ | yfinance, pre-2011 = None | — |
| F7 | Skew | ^SKEW (yfinance) | 1990+ daily | yfinance | — |
| F7 | Realized vol 60d (SPX) | ^GSPC 60d log-return std × √252 | 1957+ | derived from yfinance | — |
| F8 | S&P Shiller CAPE | static csv from Shiller | 1881+ monthly | static commit | — |
| F8 | KOSPI 200 PBR | pykrx market.get_market_fundamental | ~2001+ monthly | pykrx (Linux) | — |
| F8 | KOSPI 200 forward P/E | pykrx | ~2001+ | pykrx (Linux) | — |
| F8 | Dividend yield | Shiller + pykrx | 1881+ / 2001+ | both | — |
| F9 | Sector return dispersion | XLF, XLE, XLI, XLK, XLP, XLU, XLV, XLY, XLB 60d returns std | 1998-12+ daily | yfinance | — |
| F9 | VRP 60d | VIX² - realized_60d² | 1990+ | derived | — |
| F9 | KR/global breadth dispersion | pykrx KOSPI sector indices | 2003+ | pykrx (Linux) | — |

**~30 raw series + ~10 derived = ~40 indicator per quarter**.

### 3.3 ALFRED vintage 사용 detail (Critical 1)

```python
# fetcher_alfred.py
def fetch_alfred_vintage_quarterly(
    series_id: str, start: date, end: date,
) -> pd.DataFrame:
    """각 quarter end 시점에 *알려져 있던* 값 (real-time vintage).

    API: https://api.stlouisfed.org/fred/series/observations
         ?series_id=...&realtime_start=<quarter_end>&realtime_end=<quarter_end>

    Publish lag 가 큰 quarter (예: CFNAI 1991-Q1 의 first publish 가 1991-04-15) 의 경우:
    quarter_end (1991-03-31) 시점에 알 수 있는 *이전* publish 값을 사용 (1991-02-15 의 1990-12 data).
    """
```

ALFRED 의 vintage-aware 7 series:
1. `CFNAI` — CFNAI
2. `NFCI` — Chicago Fed National Financial Conditions Index
3. `ANFCI` — Adjusted NFCI
4. `GDPNOW` — Atlanta Fed GDPNow (2011+)
5. `UNRATE` — Unemployment rate (Sahm rule input)
6. `CPIAUCSL` — CPI All Items (small revisions but for consistency)
7. `PCEPILFE` — Core PCE

Rate limit: FRED 120/min. 7 × 135 quarter × 1 call ≈ 945 → ~8 min total fetch with retry.

### 3.4 Stage 1 builder — sentinel handling

```python
def build_historical_stage1(as_of: date, indicators_q: pd.DataFrame) -> dict:
    row = indicators_q.loc[as_of]

    fci = FinancialConditionsSnapshot(
        nfci=row.get("nfci", 0.0),  # 1971+ vintage value
        anfci=row.get("anfci", 0.0),
        regime="neutral",
        tightening=row.get("nfci", 0.0) > 0.3,
        cfnai=row.get("cfnai", 0.0),  # 1967+ vintage value
        cfnai_3m_avg=row.get("cfnai_3m_avg", 0.0),
    )
    gdp = GDPNowSnapshot(
        nowcast_pct=row.get("gdp_nowcast", 0.0),  # 2011+ only; pre-2011 = 0 sentinel
        change_from_prior=0.0,
    )
    # ... 모든 schema field 채움 (가용 시기에 따라 sentinel) ...

    # News-derived field: historical reconstruction 불가 — 영구 sentinel
    news_report = NewsReport(
        sentiment_dispersion_z=0.0,
        release_surprise=SurpriseSnapshot(surprise_index_30d=0.0),
        geopolitical_surge=0,
        macro_event_pulse=0.0,
        # ... 나머지 sentinel ...
    )
    # Technical report: KR market metric 만 pykrx, 나머지 sentinel
    ...

    return {"macro_report": macro, "risk_report": risk,
            "technical_report": tech, "news_report": news_report}
```

**핵심**: pre-availability era field 는 sentinel (None 또는 0.0) — `_safe_get` 이 None handling, 0.0 은 z=0 (factor 영향 0). Sentinel 사용은 confidence 감소로 reflect 됨.

### 3.5 News-derived field 의 영구 sentinel

| Field | 처리 | 이유 |
|---|---|---|
| `news_report.sentiment_dispersion_z` | 0 sentinel (모든 quarter) | LLM-derived, 1991-2024 historical reconstruction 불가 |
| `news_report.release_surprise` | 0 sentinel | API 의존 + historical surprise sign 추출 어려움 |
| `news_report.geopolitical_surge` | 0 sentinel | LLM-derived |
| `news_report.macro_event_pulse` | 0 sentinel | LLM-derived |

→ `mode="historical"` 가 news weight 를 자동 0 + quant weight renormalize → factor z magnitude 가 production scale 과 일치 (Critical 2 해결).

### 3.6 factor_estimators 의 mode parameter (Critical 2)

```python
# factor_estimators.py — PR2a 변경 (단일 parameter 추가)
def compute_all_factors(
    state: dict,
    mode: Literal["production", "historical"] = "production",
) -> FactorScores:
    """
    production: news + quant component 모두 합산 (PR1 의 기존 behavior).
    historical: news component weight 를 0 으로 + quant weight 만으로 renormalize.
    """
    for factor_name, factor_def in FACTOR_DEFINITIONS.items():
        weights = factor_def.weights
        if mode == "historical":
            quant_only = {k: v for k, v in weights.items()
                         if k not in NEWS_DERIVED_COMPONENTS}
            total = sum(quant_only.values())
            weights = ({k: v / total for k, v in quant_only.items()}
                       if total > 0 else weights)
        # 나머지 aggregation 동일
        ...
```

**Backward compat 보장**: default `mode="production"` → 100% identical to PR1 behavior. Unit test (`test_production_mode_unchanged`) 가 강제.

`NEWS_DERIVED_COMPONENTS: set[str]` 가 factor_estimators 안에 정의 — F1 release_surprise, F2 release_surprise_inflation, F7 sentiment_dispersion_z, F9 sentiment_dispersion_z 등.

### 3.7 sample_quality (M4)

```python
@dataclass
class HistoricalSample:
    date: str
    factor_z: dict[str, float]
    factor_confidence: dict[str, float]
    bucket_returns_next: dict[str, float]
    sample_quality: float  # mean(factor_confidence), 기록 only
```

PR2a 에서 sample_quality 는 *기록만* — calibration 의 sample weighting 적용 안 함 (Q3 의 "β only with shrinkage" scope 유지). PR2b 의 era-stratified sensitivity 에서 활용.

### 3.8 Bucket return — KRW basis (Critical 4)

| Bucket | Source | KRW translation | Pre-1996 handling |
|---|---|---|---|
| kr_equity | ^KS11 (KOSPI, 1996+) | native KRW | **None** (KOSPI 부재) |
| global_equity | ^GSPC (S&P 500, 1957+) | × USDKRW change | ✓ (USDKRW DEXKOUS 1981+) |
| fx_commodity | DJP (2006+) + gold (^XAU / GC=F, 1971+) | × USDKRW change | ✓ |
| bond | IEF (2002+) + DGS10 yield-derived TR (pre-2002) | × USDKRW change | ✓ |
| cash_mmf | ^IRX or TB3MS yield → monthly carry | × USDKRW change | ✓ |

Pre-1996 quarter (1991-Q1 ~ 1995-Q4 = 20 quarter) 의 kr_equity bucket return = None → calibration sample 의 partial bucket. factor_calibration 의 `simulate_portfolio_returns` 가 None bucket 를 graceful skip (해당 bucket weight × None = ignored).

---

## 4. Walk-forward Calibration

### 4.1 HistoricalSample 생성

`scripts/generate_historical_factor_z.py` 가 `quarterly_indicators.parquet` + `bucket_returns.parquet` 를 join 하여 135 `HistoricalSample` 출력 → `backtest/historical/samples.parquet` commit.

### 4.2 Walk-forward fold 구조

`n=135, initial_train=80, test=7` → `range(80, 135-7+1, 7) = [80, 87, 94, 101, 108, 115, 122]` → **7 folds**.

| Fold | Train idx | Test idx | Train 기간 | Test 기간 |
|---|---|---|---|---|
| 0 | 0:80 | 80:87 | 1991Q1-2010Q4 | 2011Q1-2012Q3 |
| 1 | 0:87 | 87:94 | 1991Q1-2012Q3 | 2012Q4-2014Q2 |
| 2 | 0:94 | 94:101 | 1991Q1-2014Q2 | 2014Q3-2016Q1 |
| 3 | 0:101 | 101:108 | 1991Q1-2016Q1 | 2016Q2-2017Q4 |
| 4 | 0:108 | 108:115 | 1991Q1-2017Q4 | 2018Q1-2019Q3 |
| 5 | 0:115 | 115:122 | 1991Q1-2019Q3 | 2019Q4-2021Q2 |
| 6 | 0:122 | 122:129 | 1991Q1-2021Q2 | 2021Q3-2023Q1 |

129 = 122+7 → fold 6 test 2023Q1 종료. **2023Q2-2024Q3 (6Q) held-out** (PR2b 의 future fold 후보) — `n=135` 는 1991Q1 (idx 0) 부터 2024Q3 (idx 134) 까지, 각 sample 의 `bucket_returns_next` 가 다음 분기 까지 require 하므로 마지막 sample 은 2024Q3 (next=Q4 with full close data).

각 fold: expanding window train + fixed 7Q non-overlapping test.

### 4.3 Per-fold calibration

PR1 C6 의 `hybrid_calibration` 그대로 호출:

```python
def hybrid_calibration(train, prior_beta=INITIAL_BETA, shrinkage=s):
    """
    L(β) = -Sharpe(β; train) + shrinkage × ||β - prior||² + sign_penalty(β)
    bounds: |β| ≤ 0.20 per (factor, bucket)
    optimizer: scipy.optimize.minimize(L-BFGS-B, x0=prior)
    """
```

### 4.4 Shrinkage grid loop

5 shrinkage × 7 fold = **35 calibration runs**. 각 run ~5-30 sec → 전체 ~3-15 min.

각 shrinkage 값 별 산출:
- Per-fold β list (7)
- Per-fold IS Sharpe, OOS Sharpe
- median β across 7 folds (PR1 의 `aggregate_median_beta`)
- mean IS, mean OOS, std OOS

### 4.5 Best shrinkage 선택

```python
def select_best_shrinkage(per_shrinkage_results):
    """Best by: mean_oos - 0.25 × std_oos (robustness penalty, M5).

    Tie-break: smaller |mean_is - mean_oos| (less overfit).
    """
    scores = {s: r["mean_oos"] - 0.25 * r["std_oos"]
              for s, r in per_shrinkage_results.items()}
    return max(scores, key=scores.get)
```

### 4.6 Prior baseline OOS Sharpe (M3 의 base reporting)

```python
def compute_prior_baseline_oos(samples, folds):
    """Hand-coded INITIAL_BETA 의 walk-forward OOS Sharpe (no fitting).

    각 test window 에서 INITIAL_BETA 그대로 적용 → OOS Sharpe.
    Mean across 7 folds = prior_oos_sharpe.
    """
```

→ Acceptance gate condition 1 의 baseline.

### 4.7 Equi-weight baseline (M3, informational)

```python
def compute_equi_weight_baseline_oos(samples, folds):
    """β=0 (모든 β=0, factor model 가 baseline 만 반환) 의 OOS Sharpe.

    Calibration 의 added value sanity check.
    """
```

→ Informational only, validation_report 에 reporting.

### 4.8 Acceptance gate evaluation (Critical 3 strict default)

```python
def evaluate_acceptance(
    calibrated_beta, calibrated_folds,
    prior_oos_sharpe, equi_weight_oos_sharpe,
    vintage_sanity, sensitivity_diagnostic,
) -> dict:
    mean_is = np.mean([f.in_sample_sharpe for f in calibrated_folds])
    mean_oos = np.mean([f.oos_sharpe for f in calibrated_folds])

    # Paired-t-test: calibrated vs prior on same fold's test window
    prior_per_fold_oos = [...]  # prior_baseline OOS per fold
    calibrated_per_fold_oos = [f.oos_sharpe for f in calibrated_folds]
    paired_t_stat, paired_p = scipy.stats.ttest_rel(
        calibrated_per_fold_oos, prior_per_fold_oos,
    )

    conditions = {
        "improvement": (
            mean_oos > prior_oos_sharpe + 0.05
            and paired_p < 0.20  # Critical 3 강화
        ),
        "overfit_guard": abs(mean_is - mean_oos) < 0.30,  # Critical 3 강화 (was 0.50)
        "sign_respect": all(check_sign(k, v) for k, v in calibrated_beta.items()),
        "saturation": (
            sum(abs(v) > 0.195 for v in calibrated_beta.values())
            / len(calibrated_beta) < 0.30
        ),
        "fold_positive": (
            sum(f.oos_sharpe > 0 for f in calibrated_folds) >= 6  # Critical 3 강화 (was 5)
        ),
    }
    overall_pass = all(conditions.values())

    return {
        "pass": overall_pass,
        "conditions": conditions,
        "mean_is_sharpe": mean_is,
        "mean_oos_sharpe": mean_oos,
        "prior_oos_sharpe": prior_oos_sharpe,
        "equi_weight_oos_sharpe": equi_weight_oos_sharpe,  # M3 informational
        "improvement_delta": mean_oos - prior_oos_sharpe,
        "paired_t_p": float(paired_p),
        "diagnostic": {
            "vintage_sanity": vintage_sanity,  # |β_vintage - β_latest|_avg
            "learning_sensitivity": sensitivity_diagnostic,  # |β_0.1 - β_2.0|_avg, M2
            "saturated_fraction": ...,
            "prior_stuck_fraction": ...,  # |β - prior| < 0.001 비율, M1
        },
    }
```

### 4.9 산출물 구조

```
artifacts/2026-05-XX/calibration_runs/
  per_fold/
    shrinkage_0.1_fold_0.json    # {beta, is_sharpe, oos_sharpe, optimizer_status}
    ...
    shrinkage_2.0_fold_6.json    # 35 files total
  per_shrinkage_summary.json     # 5 shrinkage 의 mean/std OOS + median β
  best_shrinkage.json            # 선정된 shrinkage + median β
  vintage_sanity.json            # |β_vintage - β_latest|_avg
  equi_weight_baseline.json      # informational (M3)
  learning_sensitivity.json      # informational (M2)
  validation_report.json         # acceptance gate verdict
```

### 4.10 INITIAL_BETA 교체 (PASS 시)

```python
# tradingagents/skills/research/factor_to_bucket.py
# Auto-generated from artifacts/2026-05-XX/calibration_runs/best_shrinkage.json
# Calibration date: 2026-05-XX
# Best shrinkage: 0.5
# Mean OOS Sharpe: 0.42, prior OOS Sharpe: 0.31, improvement Δ: +0.11
# Paired-t p-value: 0.08
INITIAL_BETA: Final[dict[tuple[str, str], float]] = {
    ("growth_surprise", "kr_equity"): 0.094,  # calibrated 2026-05-XX
    ...
}
```

Source-of-truth comment block 으로 calibration metadata 명시.

---

## 5. Cache + Git Layout

```
tradingagents/backtest/historical/
  __init__.py
  fetcher_fred.py
  fetcher_alfred.py
  fetcher_yfinance.py
  fetcher_pykrx.py
  aggregate.py
  stage1_builder.py
  bucket_returns.py
  shiller_cape_static.csv      # committed (~50KB)

backtest/historical/                  # working data dir
  raw/                                # gitignored
    fred/{series_id}.parquet
    fred_alfred/{series_id}.parquet
    yfinance/{ticker}.parquet
    pykrx/{series_id}.parquet
  quarterly_indicators.parquet        # committed (~500KB)
  factor_z.parquet                    # committed (~50KB)
  bucket_returns.parquet              # committed (~30KB)
  samples.parquet                     # committed (~100KB)

artifacts/2026-05-XX/
  decisions.md, regression_log.md, job_status.json
  calibration_runs/{...}              # all committed (~50KB)
```

`.gitignore` 추가: `backtest/historical/raw/`

Git commit 총 size: ~1MB (Shiller csv 50KB + indicators 500KB + factor_z 50KB + bucket_returns 30KB + samples 100KB + artifacts 50KB + 기타 docs).

---

## 6. Commit Structure + Quality Gates

### 6.1 Commit list (C0-C10, 11 commits)

| Commit | Type | 주요 file | 무엇 |
|---|---|---|---|
| **C0** | chore | `artifacts/2026-05-XX/` | safeguards (decisions, regression_log, job_status) |
| **C1** | feat(backtest) | `historical/fetcher_*.py` | FRED + ALFRED + yfinance + pykrx fetchers + parquet cache + unit test (mock API) |
| **C2** | feat(backtest) | `historical/aggregate.py` | quarterly aggregation + 40 indicator panel + derived (rolling vol, spreads, momentum) + unit test |
| **C3** | feat(backtest) | `historical/stage1_builder.py` + `historical/bucket_returns.py` | date-parameterized builder + KRW-basis 5-bucket return + unit test |
| | | **[grill-me #1]** | fetcher API + ALFRED vintage timing + stage1_builder sentinel + bucket KRW basis |
| **C4** | feat(stage2) | `skills/research/factor_estimators.py` | `mode="historical"` flag (backward-compat) + unit test (production unchanged 보장) |
| **C5** | data | `scripts/generate_historical_factor_z.py` + `backtest/historical/*.parquet` | end-to-end script run + samples.parquet (135Q) commit |
| | | **[grill-me #2]** | factor z coverage by era + sample sanity + mode flag 효과 verify |
| **C6** | feat(backtest) | `scripts/calibrate_factor_model.py` | walk-forward (7 folds) + shrinkage grid (5 values) + prior_baseline + equi-weight (M3) + sensitivity diagnostic (M2) |
| **C7** | feat(backtest) | `backtest/acceptance.py` | 5 strict-default condition + paired-t + diagnostic |
| **C8** | data | `artifacts/2026-05-XX/calibration_runs/` | 35 calibration runs + best_shrinkage + validation_report commit |
| | | **[grill-me #3]** | best β 해석 + acceptance gate verdict + INITIAL_BETA 교체 권한 confirm |
| **C9** | feat(stage2) **if PASS** | `skills/research/factor_to_bucket.py` | INITIAL_BETA 교체 + production unit test update |
| **C9-alt** | docs **if FAIL** | `docs/followup_issues.md` | 신규 Issue 작성 (PR2a calibration FAIL — design 재검토) |
| **C10** | docs | spec + decisions + backlog | PR2a spec checkmark + decisions.md final + Issue #18 status update |

### 6.2 Per-commit quality gate (PR1 그대로)

```bash
# 매 commit 직전
git status --short
uv run pytest tests/unit/ -q 2>&1 | tail -3
uv run pytest tests/integration/ -q 2>&1 | tail -3
# artifacts/2026-05-XX/regression_log.md 의 Post-Cx section 작성
#   - raw pytest output paste
#   - Δ from previous commit
#   - 0 new failure 확인
```

### 6.3 grill-me 시점 + 무엇 grill 받을지 (3 회)

| # | 시점 | 주된 grill 대상 |
|---|---|---|
| 1 | After C3 / before C4 | (a) FRED+ALFRED+yfinance+pykrx fetcher API + retry/timeout — production 의존도; (b) stage1_builder 의 sentinel policy — pre-2003 era 의 None vs 0.0 결정 일관성; (c) bucket_returns 의 KRW basis + pre-1996 kr_equity 처리 |
| 2 | After C5 / before C6 | (a) factor z coverage by era — pre-2003 의 confidence 가 expected 인지; (b) `mode="historical"` 의 effect verify — news weight 0 후 magnitude 가 production scale 과 동일한지; (c) sample 별 distribution — 극단값 outlier sanity |
| 3 | After C8 / before C9 | (a) best β 의 magnitude — hand-coded INITIAL_BETA 와의 \|Δβ\|_avg; (b) sign 일관성 — sign flip 한 β 가 SIGN_RESTRICTION 의 "either" 영역인지; (c) acceptance gate 결과 review — 5 condition + paired-t + diagnostic 분석; (d) INITIAL_BETA 교체 권한 user final approval |

### 6.4 Acceptance gate FAIL handling

C7 의 `validation_report.json` 의 `pass: false` 시:
- C9 의 INITIAL_BETA 교체 **skip**
- C9-alt 로 `docs/followup_issues.md` 에 신규 Issue 작성:
  ```
  Issue #25 — PR2a calibration acceptance FAIL: design 재검토 필요

  Failed conditions: [...]
  Diagnostic: mean OOS Sharpe = X.XX, prior = Y.YY, Δ = -0.0Z
  Suggested 재검토: ...
  ```
- C10: spec status = "FAIL — design 재검토 필요" 명시.

→ PR2a 의 *deliverable* 은 acceptance verdict (PASS 또는 FAIL) 까지. INITIAL_BETA 교체 자체는 PASS 일 때만.

### 6.5 Long-session protocol 적용

PR2a 도 11 commit + 다수 외부 API fetch + 35 calibration run + multiple grill-me → 환각 risk 다수.

`memory/feedback_long_session_protocol.md` 의 8 원칙 strict 적용:
- `artifacts/2026-05-XX/decisions.md` 외부화 — Section 1-8 의 모든 결정 + Critical 1-4 처리 명시
- `artifacts/2026-05-XX/regression_log.md` 매 commit 별 entry
- `artifacts/2026-05-XX/job_status.json` — 장시간 fetch (ALFRED ~1000 call) + calibration runs 의 진행 상태
- 매 commit 직전 grep + verify

### 6.6 Production limitation 처리 (Q9 minimal scope)

- 모든 fetch (C1) 는 **Linux 환경** 에서 실행 (Issues #20, #21 우회)
- Windows 의 경우: `backtest/historical/*.parquet` cache 가 commit 되어 있으므로 calibration (C6-C8) 만 실행 가능 (no fetch)
- Issue #22 (F6 baseline sd) 영향은 C5 의 factor z generation 후 sanity check → grill-me #2 에서 영향 quantify → fix 필요시 PR2a 안 (C5.5 즉시 commit) 또는 별도 PR 결정
- Issue #20, #21 영구 fix 는 PR2a 후속 별도 PR

---

## 7. Test Strategy

### 7.1 Layer 별 신규 test

| Layer | 신규 test 수 | 핵심 의도 |
|---|---|---|
| Fetcher unit (mocked API) | 12-15 | FRED/ALFRED/yfinance/pykrx 의 정상 + edge (empty response, rate limit, network error, vintage publish lag) |
| Aggregate unit | 5-8 | quarterly aggregation 의 NaN handling, derived computation |
| stage1_builder unit | 8-10 | date-parameterized builder — multiple era, pre-availability sentinel, schema validation |
| bucket_returns unit | 6-8 | KRW basis translation, pre-1996 kr_equity None, quarter-end alignment |
| factor_estimators mode unit (Critical 2) | 4-6 | `mode="historical"` quant-only renorm; `mode="production"` regression |
| calibrate runner integration | 8-12 | synthetic data smoke, fold count, shrinkage grid, prior + equi-weight baseline, acceptance gate |
| End-to-end regression (opt-in) | 2 | 1991-2024 real data run on Linux — env var opt-in |
| **Total 신규** | **~45-60** | |

### 7.2 핵심 test (반드시)

1. **test_factor_estimators_historical_mode.py**:
   - `test_production_mode_unchanged()` — PR1 의 모든 production behavior 100% identical (Critical 2 regression)
   - `test_historical_mode_quant_only()` — news perturbation 이 historical mode 에 영향 없음
   - `test_historical_mode_renormalization()` — quant weight sum after renorm = 1.0
2. **test_alfred_vintage_fetch.py**:
   - `test_alfred_vintage_differs_from_latest()` — CFNAI 1991-Q1 vintage value ≠ revised value
   - `test_alfred_publish_lag_handling()` — publish lag 가 큰 quarter 의 fallback
3. **test_walk_forward_acceptance_synthetic.py**:
   - `test_acceptance_gate_5_conditions_pass()` — known good calibration 의 5 condition PASS
   - `test_acceptance_gate_paired_t_test()` — paired-t logic 검증
   - `test_acceptance_gate_overfit_guard()` — overfit case FAIL
4. **test_bucket_returns_krw_basis.py**:
   - `test_global_equity_krw_translation()` — SPX × USDKRW translation correctness
   - `test_pre_1996_kr_equity_none()` — pre-1996 KOSPI 부재 → None 처리

### 7.3 Pre-existing fail set

PR1 baseline: 3 unit + 18 integration fail. PR2a 추가 후 **증가 0** 보장 — regression_log.md 매 commit 검증.

### 7.4 CI environment

| Environment | 실행 | 비고 |
|---|---|---|
| Linux CI (full) | unit + integration + opt-in end-to-end | PR2a 의 primary CI |
| Windows local | unit + cache 기반 integration | fetch 의존 test 는 `pytest.mark.skipif` |

---

## 8. Backward Compatibility

### 8.1 Concern + Mitigation

| Concern | Impact | Mitigation |
|---|---|---|
| `compute_all_factors()` 시그니처 변경 (mode 추가) | 모든 기존 호출자 | default `mode="production"` → 영향 0; `test_production_mode_unchanged` regression |
| INITIAL_BETA 교체 (C9, PASS 시) | bucket weight production output 변화 | C9 안에서 production unit test 의 INITIAL_BETA 의존 assertion update |
| 2026-05-15 산출물 의 bucket weight 변화 | calibration 반영 시 다른 결과 | **별도 follow-up commit 또는 PR2b** — PR2a scope 외 |
| Archive deserialize | 영향 0 (schema 변경 0) | — |

---

## 9. Risks + Mitigation

| Risk | Mitigation |
|---|---|
| ALFRED API rate limit (120/min) — 7 series × 135Q ≈ 1000 call → ~8 분 | per-series per-vintage parquet cache + retry with backoff |
| yfinance Linux rare fetch fail | per-ticker retry + None sentinel + cache 우선 |
| pykrx 일부 historical quarter 누락 (KRX 시스템) | None sentinel + F6/F8 confidence 감소 acceptable |
| ALFRED vintage publish lag 큰 quarter | publish lag 처리 — 해당 시리즈 lagged value |
| Critical 3 의 stricter acceptance gate → FAIL 가능성 ↑ | 예상 outcome — C9-alt path 명확. PR2a deliverable 은 verdict 까지. |
| Calibrated β 가 deploy 후 bucket weight 큰 변화 | 2026-05-15 regen 별도 follow-up — 변화량 명시 + sanity |
| Long-session 환각 | feedback_long_session_protocol.md 8 원칙 strict 적용 |
| Shiller CAPE CSV freshness | static commit + Issue #19 의 6m 재검증 cycle 에 포함 |
| Critical 4 KRW basis pre-1996 kr_equity None → 1996+ 데이터로만 kr-related β 학습 | Acceptable — pre-1996 KOSPI 데이터 부재는 fundamental limitation |

---

## 10. Non-goals (1.3 + 추가 명시)

- Benchmark 비교 (24-cell / 60-40 / 1-N / risk parity) → **PR2b**
- Empirical superiority 통계 검증 → **PR2b**
- `INITIAL_BASELINE` calibration → 별도 PR
- Per-contribution cap / factor weights fit → 별도 PR
- Issue #20 (Windows curl_cffi) + #21 (pykrx API) 영구 fix → 별도 PR
- News component 의 historical LLM replay → 영구 sentinel 유지
- ALFRED vintage 확장 (7 series 외) → 별도 PR
- `mode="historical"` 의 production sensitivity sweep → PR2b
- era-specific calibration (era 별 separate β) → PR2b sensitivity
- 2026-05-15 산출물 regen with new INITIAL_BETA → PR2b 또는 별도 follow-up
- Acceptance gate FAIL 시 "design 재검토" → PR2a 안에서 처리 X (Issue 작성 후 follow-up)

---

## 11. Sign-off Checklist

본 PR2a merge 의 조건 (2026-05-24 실행 완료, status = **PASS**):

- [x] 모든 unit + integration test pass (2 unit + 18 integ pre-existing 외 0 new failure; baseline 이 plan 의 3 unit 예상치와 다른 이유는 PR1 merge 가 unit fail 1개 fix)
- [x] C1-C5 의 fetcher + aggregate + builder + bucket_returns + factor z generation 모든 unit test pass (11 fetcher + 9 aggregate + 5 builder + 3 bucket_returns + 1 ALFRED 400 = 29 new)
- [x] C4 의 `mode="production"` regression test PASS — 4 historical_mode tests + PR1 의 모든 production test 100% unchanged
- [x] C5 의 factor z coverage by era 검증 — pre-2010 ALFRED 부재 → baseline-fallback, post-2010 real data. grill-me #2 에서 확인
- [x] C8 의 35 calibration runs 모두 완료 + validation_report.json 작성 (best_shrinkage=2.0)
- [x] Acceptance gate verdict **PASS** (with sign tolerance 1e-3) — validation_report.json + decisions.md final section
- [x] **PASS 시**: C9 의 INITIAL_BETA 교체 + 6 test update (test_factor_to_bucket — row-sum invariant 제거)
- [x] 3 grill-me 세션 의 decision 기록 (decisions.md) — #1/#2/#3 all DECIDED
- [x] regression_log.md 매 commit 별 entry — Post-C0 ~ Post-C9, 0 new failure 검증
- [x] backlog (docs/followup_issues.md) Issue #18 status **RESOLVED**
- [x] Critical 1-4 + plan errata (6건) 처리 결과 documentation (decisions.md Final Status)

---

## 12. PR2a 종착점 (PR2b 의 입력)

PR2a merge 후 state:
- Production `INITIAL_BETA` = data-driven (PASS) 또는 hand-coded 유지 (FAIL)
- `tradingagents/backtest/historical/` fetcher + builder + cache 완비
- `factor_estimators.py mode="historical"` 가 PR2b benchmark 비교에서 재사용
- 135 quarterly samples (factor z + bucket returns, KRW basis) 가 PR2b input

**PR2b 가 즉시 활용 가능한 PR2a deliverable**:
- `backtest/historical/samples.parquet` — PR2b calibration sample 재사용
- `factor_estimators.py mode="historical"` — PR2b era-specific sensitivity + benchmark factor model evaluation
- `INITIAL_BETA` (calibrated 또는 hand-coded) — PR2b benchmark 비교 baseline

---

## 13. 참조

- 선행 spec: `docs/superpowers/specs/2026-05-23-stage1-enhance-for-factor-model-design.md` (PR1)
- 선행 plan: `docs/superpowers/plans/2026-05-23-stage1-enhance-for-factor-model.md` (PR1)
- Audit motivation: `docs/superpowers/specs/2026-05-22-stage2-pipeline-audit.md`
- Mega-PR execution protocol: `docs/superpowers/plans/2026-05-20-stage2-execution-protocol.md`
- Followup issue (resolution target): `docs/followup_issues.md` Issue #18
- Memory: `feedback_regression_tests.md`, `feedback_long_session_protocol.md`
- PR1 의 `factor_calibration.py` (재사용): `tradingagents/skills/research/factor_calibration.py`
- PR1 의 `factor_estimators.py` (mode parameter 확장): `tradingagents/skills/research/factor_estimators.py`
- PR1 의 `factor_to_bucket.py` (INITIAL_BETA 교체 target): `tradingagents/skills/research/factor_to_bucket.py`
- 24-cell legacy 참조: `tradingagents/backtest/data.py`, `tradingagents/backtest/optimize.py`
