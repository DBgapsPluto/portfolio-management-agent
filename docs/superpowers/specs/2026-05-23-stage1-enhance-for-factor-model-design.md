# Stage 1 Enhancement for Factor Model — Design

- **작성일:** 2026-05-23
- **선행:** PR1 factor model (`feat/stage2-factor-model`, commits f95b485→a93616d)
- **Scope:** PR0 hotfix (factor_estimators field path 수정) + PR1 Stage 1 enhance (5 신규 indicator 추가)
- **Delivery:** Single PR with clear commit 분리 (C0-C11)
- **Coverage target:** Definition 1 — *current factor model design 의 100% component*
- **Quality gates:** 매 commit regression test + selective grill-me (4 회)
- **다음:** PR2 backtest + production calibration (별도 spec)

---

## 0. 결정 요약

| Decision | Choice | 출처 |
|---|---|---|
| Q1 Scope | Decomposed — PR0/PR1/PR2 별도 spec | brainstorm Q1 |
| Q2 Order | PR1 (Stage 1 enhance) + PR0 sub-task 로 포함 | brainstorm Q2 |
| Q3 Coverage | Definition 1 (current design 100%, ~40-55h) | brainstorm Q3 |
| Q4 Schema | A2 hybrid (3 신규 class + 2 field 확장) | brainstorm Q4 |
| Approach | Approach 3 — single PR, commit 분리 (C0=safe + C1-C2=PR0 + C3-C7=enhance + C8-C11=integrate/regen/docs) | brainstorm |
| Commit grouping | X1 per-indicator (5 commit for enhancements) | brainstorm Q3 detail |
| Sub-skill pattern | A (각 indicator 별 신규 skill module, 5 files) | brainstorm Q4 detail |
| Quality gates | per-commit regression test + selective grill-me 4 시점 | brainstorm 추가 |

---

## 1. 배경 + 동기

### 1.1 현재 broken state

PR1 (factor model) 완료 후 audit (`feat/stage2-factor-model` 의 a93616d 시점) 에서 *critical bug* 발견:

`tradingagents/skills/research/factor_estimators.py` 가 *대부분 잘못된 attribute path* 참조 (예: `macro_report.growth.gdp_nowcast` 가 schema 에 없음 — 실제는 `macro_report.gdp_nowcast.nowcast_pct`).

**근본 원인**:
1. Field path 가 *spec 의 가정* 따라 작성 — 실제 schema (`MacroReport`, `RiskReport`) 와 mismatch.
2. `_safe_get` 의 *silent None handling* 으로 production "run" 하나 *대부분 component skip*.
3. Unit test 가 `MagicMock` 사용 — *어떤 path 든 number 반환* 으로 silent fail 미검출.

**영향 추정**:
- 각 factor 의 *실제 작동 component coverage ~40%*.
- C7 의 2026-05-15 산출물 의 factor z 값 (예: F7=+2.32) 가 *대부분 news_report 의 sentiment_dispersion + geopolitical_surge* 으로만 산출 — VIX/MOVE 등 *진짜 vol signal* 누락.
- bucket weight (위험자산 0.32) 가 *silent-broken state* 의 출력.

### 1.2 진짜 Stage 1 data 부재 — 5 개

Path 수정 후에도 *진짜 schema 부재* 5 개:

| Indicator | Factor 사용 | Source |
|---|---|---|
| CFNAI (Chicago Fed National Activity Index) | F1 growth | FRED CFNAINMNI |
| Yield curve 5-30y slope | F4 term_premium | FRED DGS5 + DGS30 |
| Realized vol 60d (SPY) | F7 + F9 (VRP) | yfinance SPY daily aggregate |
| Sector return dispersion | F9 liquidity | 11 sector ETF returns |
| KOSPI PBR | F8 valuation | pykrx market.get_market_fundamental |

### 1.3 본 PR 의 의도

1. **PR0 hotfix (C1-C2)**: factor_estimators field path 수정 + *real schema integration test* (MagicMock 우회 차단).
2. **PR1 Stage 1 enhance (C3-C7)**: 5 신규 indicator 의 *real fetch + schema + skill module + analyst integration*.
3. **Factor model update (C8-C9)**: 5 신규 component 활성화 + audit table 확장 + test.
4. **Production verify (C10-C11)**: 2026-05-15 산출물 regen + diff + docs.

→ **본 PR 후 factor model 의 *진짜 signal coverage* ≥ 90%**. PR2 backtest 의 prerequisite *완성*.

---

## 2. Architecture Overview

### 2.1 현재 → 목표 pipeline

```
[현재 — silent broken]
  Stage 1 (real data)
    ↓ factor_estimator (wrong paths)
    → 대부분 _safe_get → None → component skip
    → factor z = 1-3 component 만 (~40% signal)
    ↓ apply_factor_model
    → bucket weight 가 *대부분 baseline 근처*

[본 PR 후 — full signal]
  Stage 1 (real data + 5 신규 indicator)
    ↓ factor_estimator (correct paths + 5 신규 path)
    → 9 factor 모두 designed components 활용
    → factor z = full signal
    ↓ apply_factor_model
    → bucket weight 가 *진짜 factor model output*
```

### 2.2 Sub-system 변화 mapping

| Layer | 변화 | 책임 commit |
|---|---|---|
| factor_estimators.py path | ~17 path 수정 (5 placeholder TODO for PR1 의존) | C1 |
| Real schema integration test (신규) | MagicMock 우회 — real Snapshot instance 사용 | C2 |
| MacroReport schema | FinancialConditionsSnapshot 확장 (CFNAI) | C3 |
| | YieldCurveSnapshot 확장 (slope_5_30y) | C4 |
| | KRValuationSnapshot 신설 + MacroReport.kr_valuation field | C5 |
| RiskReport schema | RealVolSnapshot 신설 + RiskReport.real_vol field | C6 |
| | BreadthSnapshot 확장 (sector_return_dispersion) | C7 |
| macro_quant_analyst | CFNAI + slope_5_30y + KOSPI PBR fetch + integrate | C3-C5 |
| market_risk_analyst | realized_vol + sector_dispersion fetch + integrate | C6-C7 |
| Sub-skill module 신설 | real_activity.py, yield_curve.py, kr_valuation.py, realized_volatility.py, sector_dispersion.py | C3-C7 |
| factor_estimators.py 활성화 | 5 신규 component placeholder → 실제 path | C8 |
| factor_reliability_audit | 5 신규 component reliability + EXPECTED_COMPONENTS set | C8 |
| 2026-05-15 산출물 | Stage 2-6 sequential replay regen | C10 |

### 2.3 Downstream interface

- `BucketTarget` schema — 변경 0
- `ResearchDecision` schema — 변경 0 (factor_scores/contributions/safety_diagnostics 그대로)
- Allocator / risk_judge / portfolio_manager — 변경 0

→ **본 PR 의 *output 값 변화* (signal 의 정확도 향상) but pipeline 형식 동일**.

### 2.4 신규 dependency

- `pykrx` (이미 있음 — KOSPI PBR fetch 위해 추가 사용)
- `yfinance` (이미 있음 — realized_vol 의 SPY daily fetch)
- 외부 신규 dependency 0.

---

## 3. PR0 Hotfix Detail (C1-C2)

### 3.1 Path mapping table

```
[Wrong]                                              [Correct]
macro_report.growth.gdp_nowcast                  →  macro_report.gdp_nowcast.nowcast_pct
macro_report.growth.nfci                         →  macro_report.financial_conditions.nfci
macro_report.growth.cfnai                        →  macro_report.financial_conditions.cfnai          (PR1 후)
macro_report.employment.sahm_trigger             →  macro_report.employment.sahm_rule_triggered
macro_report.yield_curve.slope_2_10y_bps         →  macro_report.yield_curve.spread_10y_2y_bps
macro_report.yield_curve.slope_5_30y_bps         →  macro_report.yield_curve.spread_30y_5y_bps      (PR1 후)
macro_report.cpi.yoy_pct                         →  macro_report.inflation.cpi_yoy
macro_report.cpi.three_month_annualized_pct      →  macro_report.inflation.momentum_3mo
macro_report.cpi.core_pce_yoy                    →  macro_report.inflation.core_pce_yoy
macro_report.inflation_exp.five_y_five_y_pct     →  macro_report.inflation_expectations.breakeven_5y5y
macro_report.inflation_exp.michigan_1y_pct       →  macro_report.inflation_expectations.michigan_1y
macro_report.real_yields.ten_y_pct               →  risk_report.real_yields.ten_y_yield_pct          ★ report 이동
macro_report.fed_path.implied_change_6m_bps      →  macro_report.fed_path.path_bps
macro_report.kr_macro.bok_us_rate_diff_bps       →  macro_report.kr_divergence.us_kr_rate_gap_bps
macro_report.kr_macro.exports_yoy_pct            →  macro_report.kr_export.<field — implementer verify>
macro_report.foreign_flow.net_flow_z             →  macro_report.foreign_flow.<field — implementer verify>
risk_report.vix.term_ratio                       →  risk_report.vix_term.<field — implementer verify>
risk_report.skew.change_1m                       →  risk_report.skew.<field — implementer verify>
risk_report.move.current_value                   →  risk_report.<MOVE 위치 — implementer verify>
risk_report.realized_vol.sixty_d                 →  risk_report.real_vol.realized_vol_60d            (PR1 후)
technical_report.kospi_pbr                       →  macro_report.kr_valuation.kospi_pbr              (PR1 후)
technical_report.sector_dispersion               →  risk_report.breadth_kr.sector_return_dispersion (PR1 후)
technical_report.breadth                         →  risk_report.breadth_kr (또는 breadth_us — F9 design 결정)
```

Total **~22 path 수정**, 그 중 **5 placeholder TODO** (PR1 C3-C7 후 활성화).

### 3.2 C1 implementation pattern

```python
# F1 예시 — placeholder + path-fixed components

def compute_growth_surprise(stage1) -> FactorScore:
    # Path-fixed (실제 schema 매칭)
    gdpnow = _safe_get(stage1, "macro_report", "gdp_nowcast", "nowcast_pct")
    nfci_raw = _safe_get(stage1, "macro_report", "financial_conditions", "nfci")
    nfci = -nfci_raw if nfci_raw is not None else None
    sahm_trigger = _safe_get(stage1, "macro_report", "employment", "sahm_rule_triggered")
    sahm_z = (-1.0 if sahm_trigger else +0.5) if sahm_trigger is not None else None
    curve = _safe_get(stage1, "macro_report", "yield_curve", "spread_10y_2y_bps")

    # TODO (C8 activation — PR1 의 CFNAI 추가 후)
    # cfnai = _safe_get(stage1, "macro_report", "financial_conditions", "cfnai")
    cfnai = None  # placeholder until C8

    # News-derived (이미 작동 — 변경 0)
    release_surprise = _safe_get(stage1, "news_report", "release_surprise", "surprise_index_30d")
    # ...

    components_raw = {
        "gdpnow": gdpnow,
        "nfci": nfci,
        "sahm": sahm_z,
        "curve": curve,
        "cfnai": cfnai,  # placeholder
        "release_surprise": release_surprise,
        # ...
    }
    return _aggregate("F1_growth", components_raw, weights)
```

### 3.3 C2 real schema integration test

`tests/integration/test_factor_estimators_real_schema.py` 신설:

```python
"""Real Stage 1 schema instance (no MagicMock) 으로 factor estimator 검증."""
from datetime import date
from tradingagents.schemas.reports import MacroReport, RiskReport, TechnicalReport, NewsReport
from tradingagents.schemas.macro import (
    YieldCurveSnapshot, InflationSnapshot, EmploymentSnapshot,
    FinancialConditionsSnapshot, GDPNowSnapshot, InflationExpectationsSnapshot,
    FedPathSnapshot, FXSnapshot, ForeignFlowSnapshot, KRExportSnapshot,
    DivergenceScore, RegimeClassification, ...
)
from tradingagents.schemas.risk import (
    VolatilitySnapshot, SpreadSnapshot, RealYieldsSnapshot, ...
)
from tradingagents.skills.research.factor_estimators import compute_all_factors


def _build_real_stage1_baseline() -> dict:
    """모든 schema 의 real instance — baseline values (mostly 0/평균)."""
    return {
        "macro_report": MacroReport(
            yield_curve=YieldCurveSnapshot(
                spread_10y_2y_bps=80.0,
                spread_10y_3m_bps=120.0,
                inverted_days_count=0,
                percentile_5y=0.5,
            ),
            inflation=InflationSnapshot(
                cpi_yoy=2.5, core_cpi_yoy=2.0,
                momentum_3mo=2.5, momentum_6mo=2.5,
                accelerating=False,
                pce_yoy=2.0, core_pce_yoy=2.0, pce_momentum_3mo=2.0,
            ),
            employment=EmploymentSnapshot(
                unemployment_rate=4.0, rate_change_3mo=0.0,
                sahm_rule_triggered=False,
                non_farm_payrolls_3mo_avg=200,
            ),
            financial_conditions=FinancialConditionsSnapshot(
                nfci=0.0, anfci=0.0, regime="neutral", tightening=False,
            ),
            gdp_nowcast=GDPNowSnapshot(nowcast_pct=2.0, change_from_prior=0.0),
            inflation_expectations=InflationExpectationsSnapshot(
                breakeven_5y5y=2.3, michigan_1y=3.0, anchored=True,
                unanchored_direction="none",
            ),
            fed_path=FedPathSnapshot(
                current_rate_pct=5.0, implied_2y_rate_pct=5.0, path_bps=0.0,
                market_view="hold",
            ),
            fx=FXSnapshot(
                usd_krw=1250.0, dxy=100.0, krw_change_1m_pct=0.0,
                dxy_change_1m_pct=0.0, regime="neutral",
            ),
            foreign_flow=ForeignFlowSnapshot(...),  # implementer 가 정확한 field 채움
            kr_divergence=DivergenceScore(
                us_kr_rate_gap_bps=-100, us_kr_inflation_gap=0.5, score=-2.0,
            ),
            kr_export=KRExportSnapshot(...),
            regime=RegimeClassification(...),
            upcoming_events=[],
            # ... 모든 required field ...
        ),
        "risk_report": RiskReport(
            vix=VolatilitySnapshot(...),
            real_yields=RealYieldsSnapshot(ten_y_yield_pct=0.5, ...),
            credit_spread_us_hy=SpreadSnapshot(...),
            # ... 모든 required field ...
        ),
        "technical_report": TechnicalReport(...),
        "news_report": NewsReport(...),
    }


def test_compute_all_factors_with_real_schema_after_c1():
    """C1 (path fix only) 후 — 5 placeholder 외 모든 component 작동."""
    state = _build_real_stage1_baseline()
    scores = compute_all_factors(state)

    # 각 factor 의 expected coverage (C1 path fix 만 후)
    expected_min_coverage = {
        "growth_surprise": 0.60,    # CFNAI (PR1 후) 제외
        "inflation_surprise": 0.90,  # 모든 component path fix 만으로
        "real_rate": 0.85,
        "term_premium": 0.60,        # slope_5_30y (PR1 후) 제외
        "credit_cycle": 0.85,
        "krw_regime": 0.80,
        "equity_vol_regime": 0.70,   # realized_vol (PR1 후) 제외
        "valuation": 0.45,            # KOSPI PBR (PR1 후) 제외, P/E external fetch only
        "liquidity_regime": 0.55,     # realized_vol + sector_dispersion (PR1 후) 제외
    }

    for factor_name, min_cov in expected_min_coverage.items():
        score = getattr(scores, factor_name)
        assert score.confidence >= min_cov, (
            f"{factor_name} coverage {score.confidence:.2f} < expected {min_cov:.2f}"
        )


def test_no_silent_path_mismatch():
    """모든 factor 가 *적어도 1 component* 작동 (즉 confidence > 0)."""
    state = _build_real_stage1_baseline()
    scores = compute_all_factors(state)
    for factor_name in (
        "growth_surprise", "inflation_surprise", "real_rate", "term_premium",
        "credit_cycle", "krw_regime", "equity_vol_regime", "valuation", "liquidity_regime",
    ):
        score = getattr(scores, factor_name)
        assert score.confidence > 0, f"{factor_name}: silent broken — 0 components"


def test_extreme_perturbation_propagates():
    """High inflation perturbation → F2 z 크게 positive."""
    state = _build_real_stage1_baseline()
    # Perturb CPI
    state["macro_report"].inflation.cpi_yoy = 8.0  # 매우 high
    state["macro_report"].inflation.momentum_3mo = 10.0
    scores = compute_all_factors(state)
    assert scores.inflation_surprise.z_score > 1.0, (
        f"F2 should respond strongly to inflation, got {scores.inflation_surprise.z_score:.2f}"
    )
```

---

## 4. PR1 Stage 1 Enhancement Detail (C3-C7)

### 4.1 5 신규 indicator 변경 summary

| Commit | Indicator | Schema 변경 | Sub-skill (신설) | Analyst integration |
|---|---|---|---|---|
| C3 | CFNAI | `FinancialConditionsSnapshot.cfnai + cfnai_3m_avg` 확장 | `skills/macro/real_activity.py` | `macro_quant_analyst.py` |
| C4 | slope_5_30y | `YieldCurveSnapshot.spread_30y_5y_bps` 확장 | `skills/macro/yield_curve.py` (신설) | `macro_quant_analyst.py` |
| C5 | KOSPI PBR | `KRValuationSnapshot` 신설 + `MacroReport.kr_valuation` | `skills/macro/kr_valuation.py` | `macro_quant_analyst.py` |
| C6 | realized_vol_60d | `RealVolSnapshot` 신설 + `RiskReport.real_vol` | `skills/risk/realized_volatility.py` | `market_risk_analyst.py` |
| C7 | sector_dispersion | `BreadthSnapshot.sector_return_dispersion` 확장 | `skills/risk/sector_dispersion.py` | `market_risk_analyst.py` |

### 4.2 Schema 추가 — concrete code

```python
# tradingagents/schemas/macro.py

class FinancialConditionsSnapshot(StalenessAware):
    # ... 기존 4 field ...
    cfnai: float = 0.0  # ★ C3 — Chicago Fed National Activity Index (monthly)
    cfnai_3m_avg: float = 0.0  # ★ C3


class YieldCurveSnapshot(StalenessAware):
    # ... 기존 4 field ...
    spread_30y_5y_bps: float = 0.0  # ★ C4 — long-end curve


class KRValuationSnapshot(StalenessAware):  # ★ C5
    kospi_pbr: float = Field(description="KOSPI 200 PBR")
    kospi_per: float = Field(description="KOSPI 200 forward PER")
    kospi_div_yield: float = Field(description="KOSPI 200 dividend yield %")


class MacroReport(_AnalystReport):
    # ... 기존 18 field ...
    kr_valuation: KRValuationSnapshot | None = None  # ★ C5


# tradingagents/schemas/risk.py

class RealVolSnapshot(StalenessAware):  # ★ C6
    realized_vol_60d: float = Field(description="SPY 60-day stddev (annualized)")
    realized_vol_20d: float = Field(description="SPY 20-day stddev (annualized)")
    vrp_60d: float = Field(default=0.0, description="VIX² - realized_60d² (bps²-like)")


class BreadthSnapshot(StalenessAware):
    # ... 기존 field ...
    sector_return_dispersion: float = 0.0  # ★ C7


class RiskReport(_AnalystReport):
    # ... 기존 18 field ...
    real_vol: RealVolSnapshot | None = None  # ★ C6
```

모든 신규 field 가 `default` 또는 `Optional = None` → 기존 archive backward compat.

### 4.3 Sub-skill pattern — concrete code (CFNAI 예시)

`tradingagents/skills/macro/real_activity.py`:

```python
"""CFNAI (Chicago Fed National Activity Index) — 85 real economy series composite.

CFNAI: 0=neutral (trend growth), +1=well above trend, -1=well below.
3-month MA (CFNAI-MA3) 가 NBER recession signal.
"""
from datetime import date
import pandas as pd
from tradingagents.skills.registry import register_skill


@register_skill(name="compute_cfnai_metrics", category="macro")
def compute_cfnai_metrics(
    cfnai_series: pd.Series, as_of: date,
) -> tuple[float, float]:
    """Returns (cfnai_latest, cfnai_3m_avg).

    Args:
        cfnai_series: FRED CFNAINMNI (monthly index value).
        as_of: report date.

    Returns:
        (latest, 3m_average) — 3m MA 가 standard 분석 signal.
    """
    if cfnai_series.empty:
        return 0.0, 0.0
    cfnai_latest = float(cfnai_series.iloc[-1])
    cfnai_3m_avg = (
        float(cfnai_series.tail(3).mean())
        if len(cfnai_series) >= 3
        else cfnai_latest
    )
    return cfnai_latest, cfnai_3m_avg
```

Analyst integration:

```python
# macro_quant_analyst.py 의 추가 부분

from tradingagents.skills.macro.real_activity import compute_cfnai_metrics

# FRED fetch (기존 fred_fetcher 활용)
cfnai_series = fred.get_series("CFNAINMNI", start_date=as_of - relativedelta(years=5))
cfnai_latest, cfnai_3m_avg = compute_cfnai_metrics(cfnai_series, as_of)

# FinancialConditionsSnapshot 에 populate
fci = compute_financial_conditions(nfci, anfci, as_of=as_of)
fci = fci.model_copy(update={
    "cfnai": cfnai_latest,
    "cfnai_3m_avg": cfnai_3m_avg,
})
```

(model_copy 사용으로 *기존 skill 의 시그니처 변경 없음* — backward compat)

### 4.4 5 indicator 별 source + 비고

| Indicator | Source | 주의사항 |
|---|---|---|
| CFNAI | FRED CFNAINMNI (monthly) | Lag 1-2 months 정상 — analyst 의 staleness handle |
| slope_5_30y | FRED DGS5 (5y) + DGS30 (30y) | 동일 publish date — derive |
| KOSPI PBR | pykrx `market.get_market_fundamental(date, market="KOSPI200")` | KR business day 만 — as_of 가 holiday 시 prior trading day |
| realized_vol_60d | yfinance SPY 1d interval | annualized = std × sqrt(252) |
| sector_dispersion | 11 sector ETF (XLF, XLY, XLE, etc.) 60d returns | 1 sector 실패 시 graceful — n_sectors 기록 |

각 fetch 의 *retry + cache + graceful failure* (`return None` on failure → analyst 가 sentinel 채움) — 기존 pattern 따름.

---

## 5. Factor Estimator Update (C8-C9)

### 5.1 C8 — 5 신규 component 활성화

C1 에서 placeholder 였던 5 component 의 *실제 path* 활성화:

```python
# F1 growth — CFNAI 활성화
cfnai = _safe_get(stage1, "macro_report", "financial_conditions", "cfnai")  # ★ C8
cfnai_3m = _safe_get(stage1, "macro_report", "financial_conditions", "cfnai_3m_avg")  # ★ C8 new

# F4 term_premium — slope_5_30y 활성화
slope_5_30 = _safe_get(stage1, "macro_report", "yield_curve", "spread_30y_5y_bps")  # ★ C8

# F7 equity_vol_regime — realized_vol 활성화
realized_vol = _safe_get(stage1, "risk_report", "real_vol", "realized_vol_60d")  # ★ C8

# F8 valuation — KOSPI PBR 활성화 (macro_report 로 이동, technical_report 아님)
kospi_pbr = _safe_get(stage1, "macro_report", "kr_valuation", "kospi_pbr")  # ★ C8

# F9 liquidity_regime — realized_vol + sector_dispersion + VRP 활성화
realized_vol = _safe_get(stage1, "risk_report", "real_vol", "realized_vol_60d")  # ★ C8
vrp = _safe_get(stage1, "risk_report", "real_vol", "vrp_60d")  # ★ C8 pre-computed
sector_dispersion = _safe_get(stage1, "risk_report", "breadth_kr", "sector_return_dispersion")  # ★ C8
```

### 5.2 Weight 재조정

기존 weight 가 *placeholder* 가정. 5 신규 활성화 후 *각 factor 의 weight sum* 재정규화:

| Factor | 기존 active sum | 신규 추가 weight | 재정규화 weight |
|---|---|---|---|
| F1 growth | ~0.62 (news+일부 quant) | cfnai 0.10 + cfnai_3m 0.08 | 모두 ~1.0 으로 |
| F4 term_premium | ~0.65 | slope_5_30y 0.20 | ~0.85 → 재정규화 |
| F7 equity_vol_regime | ~0.65 | realized_vol_60d 0.13 | ~0.78 → 재정규화 |
| F8 valuation | ~0.40 | kospi_pbr 0.20 | ~0.60 → 재정규화 |
| F9 liquidity_regime | ~0.50 | realized_vol 의 vrp + sector_dispersion 0.18 | ~0.68 → 재정규화 |

*정확한 weight 는 grill-me #3 (before C8) 에서 결정 후 명시*.

### 5.3 audit table 확장

`factor_reliability_audit.py`:

```python
COMPONENT_RELIABILITY: Final[dict[str, Reliability]] = {
    # ... 기존 ...
    "cfnai": "high",           # ★ C8
    "cfnai_3m_avg": "high",
    "spread_30y_5y_bps": "high", # ★ C8
    "kospi_pbr": "high",       # ★ C8
    "realized_vol_60d": "high",
    "vrp_60d": "high",
    "sector_return_dispersion": "medium",  # narrow rally 환경 reliability ↓
}
```

`test_factor_indicator_validity.py` 의 `EXPECTED_COMPONENTS` 5 신규 추가.

### 5.4 C9 — real schema integration test 확장

C2 의 test 가 *PR1 활성화 후 expected coverage* 검증:

```python
def test_compute_all_factors_with_real_schema_after_c8():
    """C8 후 — 모든 5 신규 component 활성화. 각 factor coverage ≥ 90%."""
    state = _build_real_stage1_baseline_with_pr1()  # 5 신규 schema 포함
    scores = compute_all_factors(state)

    expected_min_coverage = {
        "growth_surprise": 0.95,
        "inflation_surprise": 0.95,
        "real_rate": 0.95,
        "term_premium": 0.90,
        "credit_cycle": 0.90,
        "krw_regime": 0.85,
        "equity_vol_regime": 0.95,
        "valuation": 0.90,
        "liquidity_regime": 0.90,
    }
    for f, min_c in expected_min_coverage.items():
        assert getattr(scores, f).confidence >= min_c
```

---

## 6. Backward Compatibility

### 6.1 Archive deserialize

기존 archive (`runs/{date}/*.json`):
- `macro_report.json`: 새 field (cfnai, spread_30y_5y_bps, kr_valuation) 부재 → default 적용 (0.0 / None) → deserialize OK
- `risk_report.json`: 새 field (real_vol) 부재 → None → OK
- `research_decision.json`: 변경 0

### 6.2 Existing analyst prompt

`macro_quant_analyst` / `market_risk_analyst` 의 *기존 prompt template* — 새 field 가 *prompt 에 등장 안 함* (existing template 가 reference 안 함). LLM narrative 변화 0.

→ Prompt update 는 *별도 PR* (optional).

### 6.3 Existing test

- 기존 factor estimator test (MagicMock 기반): 그대로 작동 (mock 이 어떤 path 든 response).
- C2 / C9 의 real schema integration test 신규.
- `test_factor_indicator_validity.py` 의 EXPECTED_COMPONENTS 갱신 (C8).

---

## 7. Test Strategy

### 7.1 Test layer + 본 PR 추가

| Layer | 기존 | 본 PR 추가 |
|---|---|---|
| Schema unit (3 신규 class) | — | +9-15 |
| Sub-skill unit (5 신규 module) | — | +20-30 |
| Factor estimator unit (MagicMock) | ~40 | (default value update) |
| **Real schema integration (C2, C9)** | — | **+~30** |
| Analyst integration (mock fetch + schema verify) | — | +15 |
| End-to-end (replay 2026-05-15) | (C10) | regen 검증 |
| **Total 신규** | | **+~75-90** |

### 7.2 Critical tests

**Real schema integration test (`tests/integration/test_factor_estimators_real_schema.py`)**: PR0 의 가장 중요한 산출물. MagicMock 우회 차단 — 향후 같은 silent-broken 재발 방지.

**Audit table 강제 test**: 5 신규 component 가 audit table 에 *명시적 등록* — 누락 시 test fail.

**Backward compat test**: 기존 archive (예: Mega-PR 의 47b5590 archive) load → pydantic validation pass → factor estimator 작동.

---

## 8. Commit Structure (C0-C11) + Quality Gates

```
C0  chore: execution safeguards (artifacts/2026-05-23/{decisions, regression_log, job_status})

[PR0 hotfix — factor_estimators path fix]
C1  fix(stage2): factor_estimators field path 수정 (~17 fix + 5 placeholder TODO)
C2  test(stage2): real schema integration test — MagicMock 우회 차단

[grill-me #1: pattern decisions before C3 series — sub-skill API shape, error handling, fetch retry, schema default]

[PR1 Stage 1 enhance — 5 신규 indicator]
C3  feat(stage1): CFNAI fetcher + FinancialConditionsSnapshot 확장
[grill-me #2: C3 의 결과 review + C4-C7 pattern validation]
C4  feat(stage1): yield curve 5-30y slope + YieldCurveSnapshot 확장
C5  feat(stage1): KOSPI PBR + KRValuationSnapshot 신설
C6  feat(stage1): realized vol + RealVolSnapshot 신설
C7  feat(stage1): sector dispersion + BreadthSnapshot 확장

[grill-me #3: weight rebalance decisions before C8]
[factor model update]
C8  feat(stage2): factor_estimators 의 5 신규 component 활성화 + audit table update
C9  test(stage2): 신규 component 의 real schema integration test 확장

[final]
C10 data(2026-05-15): 산출물 regen + stage2_diff_post_stage1.md
[grill-me #4: bucket weight 변화 interpretation]
C11 docs: backlog update + audit status (Issue #12-#19)
```

### 8.1 매 commit quality gate

```bash
# Step 1: 변경 파일 review
git status --short

# Step 2: Unit + integration regression
uv run pytest tests/unit/ -q 2>&1 | tail -3
uv run pytest tests/integration/ -q 2>&1 | tail -3

# Step 3: regression_log.md 의 Post-Cx section 채움
# - raw output paste
# - Δ from previous commit
# - 0 new failure 확인

# Step 4: commit (per-commit message format 따라)
```

### 8.2 grill-me 적용 시점 (총 4 회)

| # | 시점 | 무엇 grill |
|---|---|---|
| 1 | Before C3 | 5-indicator pattern 의 *skill API shape, error handling, fetch retry, schema default* |
| 2 | After C3 / before C4 | C3 의 *실측 결과* 보고 — pattern 의 *문제점* (C4-C7 적용 전) |
| 3 | Before C8 | 5 신규 component 의 *weight magnitude* + reliability tier + cap |
| 4 | After C10 / before C11 | regen 결과 의 *bucket weight 변화* interpretation |

각 grill ~10 min. 총 ~40 min interview overhead.

---

## 9. Acceptance Criteria

### 9.1 본 PR 의 acceptance

| Test | Threshold | Action if fail |
|---|---|---|
| C2 real schema integration (after C1) | 각 factor coverage ≥ expected_min (Section 3.3) | path 재검토 |
| C9 real schema integration (after C8) | 각 factor coverage ≥ 0.85 (모두) | schema/skill 재검토 |
| Sign restriction violation in 2026-05-15 산출물 | 0 | factor estimator 재검토 |
| Mandate violation (2026-05-15 산출물) | 0 | projection 재확인 |
| Pre-existing fail set (3 unit + 18 integ) | 증가 0 | 새 fail origin 추적 |
| Audit table EXPECTED_COMPONENTS | 5 신규 추가 + 모두 present | audit update 누락 |

### 9.2 *Empirical superiority* 는 본 PR acceptance 아님

본 PR = *infrastructure + coverage*. *Backtest 검증* 은 PR2 의 책임.

---

## 10. Non-goals

- **Backtest (PR2)**: walk-forward calibration, regime analysis, vs 24-cell/60-40 비교
- **β recalibration** (PR2): INITIAL_BETA update 는 real historical fetch + production backtest 후
- **Stage 1 의 advanced indicator** (Tier 2-3): r-star, ACM/Kim-Wright, REER, ISM sub, cross-currency basis
- **macro_news_analyst 의 LLM prompt update**: 신규 factor signal 의 narrative 활용 — optional, 별도 PR
- **Stage 1 의 analyst prompt template update**: analyst 가 신규 field 활용 narrative — optional, 별도 PR
- **24-cell framework 의 partial restoration**: hybrid model — 별도 결정
- **External fetchers.py cleanup**: Issue #17 — *PR1 후* (KOSPI PBR + S&P P/E migrate)

---

## 11. Risks + Mitigations

| Risk | Mitigation |
|---|---|
| C1 path fix 시 다른 path mismatch 발견 | C2 real schema test 가 모든 path validation — 발견 시 *그 commit 안* fix |
| C3-C7 의 fetcher 외부 API rate limit (FRED, yfinance, pykrx) | retry + lru_cache + skill graceful degradation (`return None` on failure) |
| 신규 schema field 가 analyst prompt template 와 mismatch | prompt template update *별도 PR* (본 PR scope 외). 신규 field 는 struct 에만, prompt 에 표시 안 함 |
| C8 weight 재조정 후 factor signal magnitude 변화 — 2026-05-15 bucket weight 대규모 변경 | C10 의 stage2_diff 가 변화 명시 — acceptable (mandate pass) 검증 |
| Archive deserialize forbid extra 가 기존 archive 의 추가 field fail | C5 의 `extra="ignore"` 가 처리. 신규 field 는 default 적용 |
| pykrx KOSPI PBR fetch 의 historical 범위 제한 | pykrx 가 ~2000+ historical OK. 1991-2000 missing — PR2 backtest sample window 결정 영향 |
| realized_vol_60d 의 SPY daily fetch 대용량 | yfinance 1d interval 1991-2024 ≈ 8500 day. 1회 fetch + parquet cache → 재fetch 불필요 |
| C8 factor signal 변화 → downstream allocator method choice 영향 (HRP → mean-variance 등) | expected 변화. C10 diff 에 method choice 변화 명시 |
| grill-me 시점 의 *over-engineering* 유도 | grill 의 *목적* (pattern + weight decision 만) 명시. C3 의 pattern 결정 후 *재오픈 안 함* |

---

## 12. Sign-off Checklist

본 PR merge 의 조건:
- [ ] 모든 unit + integration test pass (3 unit + 18 integ pre-existing 외 0 new failure)
- [ ] C2 real schema test: 각 factor 의 expected_min coverage (after C1) 충족
- [ ] C9 real schema test: 각 factor coverage ≥ 0.85 (after C8)
- [ ] Sign restriction violation = 0 (2026-05-15 산출물)
- [ ] Mandate violation = 0 (2026-05-15 산출물)
- [ ] 5 신규 audit components 의 reliability + EXPECTED_COMPONENTS 갱신
- [ ] 4 grill-me 세션 의 decision 기록 (decisions.md)
- [ ] stage2_diff_post_stage1.md 작성
- [ ] backlog (docs/followup_issues.md) 의 Issue #13, #15, #16 partial 또는 resolved 마크

---

## 13. 참조

- Spec (선행): `docs/superpowers/specs/2026-05-22-stage2-factor-model-design.md`
- Audit (motivation): `docs/superpowers/specs/2026-05-22-stage2-pipeline-audit.md`
- Mega-PR execution protocol: `docs/superpowers/plans/2026-05-20-stage2-execution-protocol.md`
- Followup issues: `docs/followup_issues.md`
- Memory: `feedback_regression_tests.md`, `feedback_long_session_protocol.md`
- PR1 implementation plan: `docs/superpowers/plans/2026-05-22-stage2-factor-model.md`
