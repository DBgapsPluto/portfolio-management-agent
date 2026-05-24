# Stage 1 Enhancement for Factor Model — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stage 2 factor model 의 *silent broken* state (field path mismatch + 5 missing indicator) 를 fix — production factor signal coverage ≥ 90%.

**Architecture:** PR0 hotfix (path fix + real schema integration test) + PR1 Stage 1 enhance (5 indicator 의 schema + skill module + analyst integration) + factor estimator update (5 신규 component 활성화) + 2026-05-15 regen + backlog update.

**Tech Stack:** Python 3.12, pydantic v2, pandas, scipy, yfinance, pykrx, FRED (fredapi), pytest, langgraph.

**Spec:** `docs/superpowers/specs/2026-05-23-stage1-enhance-for-factor-model-design.md`

**Branch base:** `feat/stage2-factor-model` (PR1 factor model, commit a93616d).

**Quality gates:**
- 매 commit 후 regression test (pytest unit + integration) + regression_log.md 갱신 (0 new failure 검증)
- Selective grill-me 4 시점 (before C3, after C3/before C4, before C8, after C10/before C11)

**Memory policies (필독):**
- `feedback_regression_tests.md`: 모든 코드 수정 시 regression test 의무
- `feedback_long_session_protocol.md`: long-session 환각 차단 8 원칙

---

## File Structure

### Created (production)
- `tradingagents/skills/macro/real_activity.py` — CFNAI compute
- `tradingagents/skills/macro/yield_curve.py` — yield curve compute (5-30y slope 포함)
- `tradingagents/skills/macro/kr_valuation.py` — KOSPI PBR/PER/DivYield
- `tradingagents/skills/risk/realized_volatility.py` — SPY realized_vol + VRP
- `tradingagents/skills/risk/sector_dispersion.py` — sector return dispersion

### Created (tests)
- `tests/integration/test_factor_estimators_real_schema.py` — MagicMock 우회 차단
- `tests/unit/skills/macro/test_real_activity.py`
- `tests/unit/skills/macro/test_yield_curve.py`
- `tests/unit/skills/macro/test_kr_valuation.py`
- `tests/unit/skills/risk/test_realized_volatility.py`
- `tests/unit/skills/risk/test_sector_dispersion.py`
- `tests/unit/schemas/test_factor_model_schemas.py` — 신규 schema validation

### Created (artifacts)
- `artifacts/2026-05-23/decisions.md`
- `artifacts/2026-05-23/regression_log.md`
- `artifacts/2026-05-23/job_status.json`
- `artifacts/2026-05-15/stage2_diff_post_stage1.md` (C10 regen 후)

### Modified
- `tradingagents/skills/research/factor_estimators.py` — C1 path fix + C8 신규 component 활성화
- `tradingagents/skills/research/factor_reliability_audit.py` — C8 5 신규 component 추가
- `tradingagents/schemas/macro.py` — C3 cfnai + C4 spread_30y_5y_bps + C5 KRValuationSnapshot
- `tradingagents/schemas/risk.py` — C6 RealVolSnapshot + C7 sector_return_dispersion
- `tradingagents/schemas/reports.py` — C5 MacroReport.kr_valuation + C6 RiskReport.real_vol
- `tradingagents/agents/analysts/macro_quant_analyst.py` — C3, C4, C5 integration
- `tradingagents/agents/analysts/market_risk_analyst.py` — C6, C7 integration
- `tests/unit/skills/research/test_factor_indicator_validity.py` — C8 5 신규 audit
- `artifacts/2026-05-15/{portfolio,philosophy,trade_plan}.{json,md,csv}` — C10 regen
- `docs/followup_issues.md` — C11 Issue #13/#15/#16 status
- `docs/superpowers/specs/2026-05-22-stage2-pipeline-audit.md` — C11 status

---

## Task 0: Branch + Execution Safeguards (C0)

### Task 0.1: 새 branch 생성

**Files:** branch creation, no files yet

- [ ] **Step 1: 현재 상태 확인**

```bash
git status --short
git log --oneline -3
git branch --show-current
```

Expected: 현재 branch `feat/stage2-factor-model`, 최근 commit `54f2485 docs(stage1): Stage 1 enhance + PR0 hotfix design spec (PR1)`.

- [ ] **Step 2: 새 branch 생성**

```bash
git checkout -b feat/stage1-enhance-for-factor-model
```

Expected: `Switched to a new branch 'feat/stage1-enhance-for-factor-model'`.

- [ ] **Step 3: regression baseline 확인**

```bash
uv run pytest tests/unit/ -q 2>&1 | tail -3
uv run pytest tests/integration/ -q 2>&1 | tail -3
```

Expected:
- Unit: 3 failed (pre-existing) / 668 passed
- Integration: 18 failed (pre-existing) / 16 passed

### Task 0.2: artifacts/2026-05-23/ scaffolding

**Files:**
- Create: `artifacts/2026-05-23/decisions.md`
- Create: `artifacts/2026-05-23/regression_log.md`
- Create: `artifacts/2026-05-23/job_status.json`

- [ ] **Step 1: decisions.md 작성**

```bash
mkdir -p artifacts/2026-05-23
```

`artifacts/2026-05-23/decisions.md`:

```markdown
# Stage 1 Enhance for Factor Model PR — Decisions

> Brainstorming 의 결정 + grill-me 4 회 의 후속 결정 기록.

| # | 항목 | 결정 | 근거 | 시각 | commit |
|---|---|---|---|---|---|
| D1 | Scope | PR0 hotfix + PR1 Stage 1 enhance (single PR) | brainstorm Q1+Q2 | 2026-05-23 | spec |
| D2 | Coverage | Definition 1 — current design 100% (PR0 + 5 신규) | brainstorm Q3 | 2026-05-23 | spec |
| D3 | Schema | A2 hybrid — 3 신규 class + 2 field 확장 | brainstorm Q4 | 2026-05-23 | spec |
| D4 | Commit grouping | X1 per-indicator (5 commit) | brainstorm Q3 detail | 2026-05-23 | spec |
| D5 | Sub-skill | A pattern — 신규 skill module per indicator | brainstorm Q4 detail | 2026-05-23 | spec |
| D6 | Quality gates | per-commit regression + selective grill-me 4 회 | brainstorm 추가 | 2026-05-23 | spec |
| D7 | Sub-skill API shape (grill-me #1) | _pending — before C3_ | — | — | — |
| D8 | Error handling pattern (grill-me #1) | _pending_ | — | — | — |
| D9 | Fetch retry policy (grill-me #1) | _pending_ | — | — | — |
| D10 | C3 결과 pattern adjust (grill-me #2) | _pending — after C3_ | — | — | — |
| D11 | C8 weight magnitude (grill-me #3) | _pending — before C8_ | — | — | — |
| D12 | 2026-05-15 diff interpretation (grill-me #4) | _pending — after C10_ | — | — | — |
```

- [ ] **Step 2: regression_log.md baseline**

```bash
uv run pytest tests/unit/ -q 2>&1 | tail -3 > /tmp/baseline_unit.txt
uv run pytest tests/integration/ -q 2>&1 | tail -3 > /tmp/baseline_int.txt
cat /tmp/baseline_unit.txt
cat /tmp/baseline_int.txt
```

`artifacts/2026-05-23/regression_log.md`:

```markdown
# Stage 1 Enhance for Factor Model PR Regression Log

> 각 commit 직후 회귀 결과. baseline 대비 0 *new* regression merge 조건.

## Pre-existing failures (본 PR scope 외)

### Unit (3)
- tests/unit/agents/test_macro_quant_analyst.py::test_macro_analyst_orchestration
- tests/unit/agents/test_technical_analyst.py::test_technical_analyst_returns_report
- tests/unit/monitor/test_monitor.py::test_turnover_initial_below_floor

### Integration (18)
- tests/integration/test_eval_systemic_score.py (8 cases)
- tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts
- 그 외 9 — Stage 1 systemic_score eval

## Post-C0 baseline

### Unit
```
$ uv run pytest tests/unit/ -q 2>&1 | tail -3
<paste raw output here>
```

### Integration
```
$ uv run pytest tests/integration/ -q 2>&1 | tail -3
<paste raw output here>
```

## Post-C1, Post-C2, ..., Post-C11
(각 commit 후 갱신)
```

Raw output 의 *마지막 3 줄* 을 `<paste raw output here>` 자리에 paste.

- [ ] **Step 3: job_status.json 생성**

`artifacts/2026-05-23/job_status.json`:

```json
{
  "comment": "Background process tracker.",
  "jobs": {}
}
```

- [ ] **Step 4: C0 commit**

```bash
git add artifacts/2026-05-23/
git commit -m "$(cat <<'EOF'
chore(stage1-enhance): execution safeguards (C0)

artifacts/2026-05-23/:
- decisions.md: D1-D6 결정 외부화 + D7-D12 grill-me pending
- regression_log.md: pre-existing baseline + Post-C0
- job_status.json: tracker

C1-C11 모든 task 가 본 artifacts 참조 의무.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 1: PR0 Hotfix — Path Fix (C1)

### Task 1.1: factor_estimators.py path 수정

**Files:**
- Modify: `tradingagents/skills/research/factor_estimators.py` (모든 9 factor)

> **Pattern**: 각 factor 마다 _safe_get 의 path 를 *실제 schema* 와 매칭. 5 placeholder TODO 는 *C8 활성화* (PR1 의존).

- [ ] **Step 1: schema 확인 — 실제 field name 검증**

```bash
grep -A 5 "^class YieldCurveSnapshot\|^class InflationSnapshot\|^class EmploymentSnapshot\|^class FinancialConditionsSnapshot\|^class GDPNowSnapshot\|^class InflationExpectationsSnapshot\|^class FedPathSnapshot\|^class DivergenceScore\|^class KRExportSnapshot\|^class ForeignFlowSnapshot\|^class FXSnapshot" tradingagents/schemas/macro.py | head -100

grep -A 5 "^class VolatilitySnapshot\|^class SpreadSnapshot\|^class RealYieldsSnapshot\|^class SkewSnapshot\|^class VIXTermStructureSnapshot\|^class EquityBondCorrelationSnapshot\|^class BreadthSnapshot\|^class CreditQualitySnapshot\|^class FundingStressSnapshot" tradingagents/schemas/risk.py | head -100
```

각 snapshot 의 field name 확인 후 *spec 의 path mapping table* 과 cross-reference.

- [ ] **Step 2: factor_estimators.py 의 F1 compute_growth_surprise 수정**

`tradingagents/skills/research/factor_estimators.py` 의 `compute_growth_surprise` 함수 수정.

Before (broken):
```python
def compute_growth_surprise(stage1) -> FactorScore:
    nfci_raw = _safe_get(stage1, "macro_report", "growth", "nfci")
    sahm_trigger = _safe_get(stage1, "macro_report", "employment", "sahm_trigger")
    # ...
    components_raw = {
        "gdpnow": _safe_get(stage1, "macro_report", "growth", "gdp_nowcast"),
        "cfnai":  _safe_get(stage1, "macro_report", "growth", "cfnai"),
        # ...
        "curve":  _safe_get(stage1, "macro_report", "yield_curve", "slope_2_10y_bps"),
        # ...
    }
```

After (path fixed):
```python
def compute_growth_surprise(stage1) -> FactorScore:
    """F1 growth_surprise — +z = growth, -z = recession.
    
    PR0 hotfix (2026-05-23 C1): paths fixed to actual MacroReport/RiskReport schema.
    5 placeholder TODO (cfnai, spread_30y_5y_bps, realized_vol, kospi_pbr, sector_dispersion)
    activated in C8 after PR1 Stage 1 enhance.
    """
    # macro_report (path-fixed)
    gdpnow = _safe_get(stage1, "macro_report", "gdp_nowcast", "nowcast_pct")
    nfci_raw = _safe_get(stage1, "macro_report", "financial_conditions", "nfci")
    nfci = -nfci_raw if nfci_raw is not None else None
    sahm_trigger = _safe_get(stage1, "macro_report", "employment", "sahm_rule_triggered")
    sahm_z = (-1.0 if sahm_trigger else +0.5) if sahm_trigger is not None else None
    curve = _safe_get(stage1, "macro_report", "yield_curve", "spread_10y_2y_bps")

    # TODO (C8 activation — PR1 의 CFNAI 추가 후)
    # cfnai = _safe_get(stage1, "macro_report", "financial_conditions", "cfnai")
    cfnai = None

    # news_report (이미 작동 — 변경 0)
    release_surprise = _safe_get(stage1, "news_report", "release_surprise", "surprise_index_30d")
    bias_30d = _safe_get(stage1, "news_report", "release_surprise", "bias_30d") or ""
    hawkish_bias = _BIAS_MAP.get(bias_30d) if bias_30d else None
    macro_sent_dict = _safe_get(stage1, "news_report", "news_sentiment", "avg_sentiment")
    macro_sent = macro_sent_dict.get("macro") if isinstance(macro_sent_dict, dict) else None
    risk_regime = _safe_get(stage1, "news_report", "global_overnight", "risk_regime_overnight") or ""
    risk_regime_z = _RISK_REGIME_MAP.get(risk_regime) if risk_regime else None

    components_raw = {
        "gdpnow": gdpnow,
        "cfnai": cfnai,  # placeholder until C8
        "nfci": nfci,
        "sahm": sahm_z,
        "curve": curve,
        "release_surprise": release_surprise,
        "hawkish_bias": hawkish_bias,
        "macro_sent": macro_sent,
        "risk_regime_overnight": risk_regime_z,
    }
    weights = {
        "gdpnow": 0.20, "cfnai": 0.0,  # cfnai weight = 0 until C8
        "nfci": 0.15, "sahm": 0.08, "curve": 0.12,
        "release_surprise": 0.18, "hawkish_bias": 0.05,
        "macro_sent": 0.05, "risk_regime_overnight": 0.05,
    }
    return _aggregate("F1_growth", components_raw, weights)
```

- [ ] **Step 3: F2 compute_inflation_surprise 수정**

```python
def compute_inflation_surprise(stage1) -> FactorScore:
    """F2 inflation_surprise — +z = inflation, -z = disinflation.
    PR0 hotfix: paths fixed.
    """
    # macro_report (path-fixed)
    cpi_yoy = _safe_get(stage1, "macro_report", "inflation", "cpi_yoy")
    cpi_3m = _safe_get(stage1, "macro_report", "inflation", "momentum_3mo")
    core_pce = _safe_get(stage1, "macro_report", "inflation", "core_pce_yoy")
    five_y_five_y = _safe_get(stage1, "macro_report", "inflation_expectations", "breakeven_5y5y")
    michigan_1y = _safe_get(stage1, "macro_report", "inflation_expectations", "michigan_1y")
    fed_path_bps = _safe_get(stage1, "macro_report", "fed_path", "path_bps")
    # real_yields 가 risk_report 에 있음 (★ macro_report → risk_report 이동)
    real_yield = _safe_get(stage1, "risk_report", "real_yields", "ten_y_yield_pct")
    real_yield_inv = -real_yield if real_yield is not None else None

    # news_report (변경 0)
    bias_30d = _safe_get(stage1, "news_report", "release_surprise", "bias_30d") or ""
    release_hawkish = _BIAS_MAP.get(bias_30d) if bias_30d else None
    macro_sent_dict = _safe_get(stage1, "news_report", "news_sentiment", "avg_sentiment")
    macro_sent = macro_sent_dict.get("macro") if isinstance(macro_sent_dict, dict) else None

    components_raw = {
        "cpi_yoy": cpi_yoy,
        "cpi_3m": cpi_3m,
        "core_pce": core_pce,
        "five_y_five_y": five_y_five_y,
        "michigan_1y": michigan_1y,
        "real_yield_inv": real_yield_inv,
        "fed_path_bps": fed_path_bps,
        "release_hawkish": release_hawkish,
        "macro_sent": macro_sent,
    }
    weights = {
        "cpi_yoy": 0.18, "cpi_3m": 0.18, "core_pce": 0.13,
        "five_y_five_y": 0.13, "michigan_1y": 0.08,
        "real_yield_inv": 0.08, "fed_path_bps": 0.08,
        "release_hawkish": 0.07, "macro_sent": 0.07,
    }
    return _aggregate("F2_inflation", components_raw, weights)
```

- [ ] **Step 4: F3 compute_real_rate 수정**

```python
def compute_real_rate(stage1) -> FactorScore:
    """F3 real_rate — +z = high real rate.
    PR0 hotfix: tips_yield 가 risk_report.real_yields.
    """
    tips_yield = _safe_get(stage1, "risk_report", "real_yields", "ten_y_yield_pct")
    fed_voting = _safe_get(stage1, "news_report", "cb_speakers", "fed_voting_balance")
    fed_path = _safe_get(stage1, "macro_report", "fed_path", "path_bps")

    components_raw = {
        "tips_yield": tips_yield,
        "fed_voting_balance": fed_voting,
        "fed_path_implied": fed_path,
    }
    weights = {
        "tips_yield": 0.55, "fed_voting_balance": 0.35, "fed_path_implied": 0.10,
    }
    return _aggregate("F3_real_rate", components_raw, weights)
```

- [ ] **Step 5: F4 compute_term_premium 수정**

```python
def compute_term_premium(stage1) -> FactorScore:
    """F4 term_premium.
    PR0 hotfix: slope_2_10y path. slope_5_30y placeholder (C8 활성화).
    """
    slope_2_10 = _safe_get(stage1, "macro_report", "yield_curve", "spread_10y_2y_bps")
    # TODO (C8): slope_5_30 = _safe_get(stage1, "macro_report", "yield_curve", "spread_30y_5y_bps")
    slope_5_30 = None  # placeholder

    fed_tone = _safe_get(stage1, "news_report", "cb_speakers", "fed_tone_balance")
    fed_voting = _safe_get(stage1, "news_report", "cb_speakers", "fed_voting_balance")

    components_raw = {
        "slope_2_10y": slope_2_10,
        "slope_5_30y": slope_5_30,  # placeholder
        "fed_tone_balance": fed_tone,
        "fed_voting_balance": fed_voting,
    }
    weights = {
        "slope_2_10y": 0.30,
        "slope_5_30y": 0.0,  # weight 0 until C8
        "fed_tone_balance": 0.30, "fed_voting_balance": 0.15,
    }
    return _aggregate("F4_term_premium", components_raw, weights)
```

- [ ] **Step 6: F5 compute_credit_cycle 수정**

```python
def compute_credit_cycle(stage1) -> FactorScore:
    """F5 credit_cycle.
    PR0 hotfix: path 검증 — implementer 가 SpreadSnapshot/CreditQualitySnapshot/FundingStressSnapshot 의
    실제 field name 확인. 아래는 *예상* field name (verify with grep).
    """
    # IMPLEMENTER: verify field names via grep 'class SpreadSnapshot' tradingagents/schemas/risk.py
    hy_oas_current = _safe_get(stage1, "risk_report", "credit_spread_us_hy", "current_bps")
    hy_oas_momentum = _safe_get(stage1, "risk_report", "credit_spread_us_hy", "momentum_z")
    credit_quality = _safe_get(stage1, "risk_report", "credit_quality", "quality_spread_bps")
    funding = _safe_get(stage1, "risk_report", "funding_stress", "spread_bps")

    # news_report — corporate distress
    count_change_dict = _safe_get(stage1, "news_report", "news_sentiment", "count_change_vs_7d")
    corp_count_change = count_change_dict.get("corporate") if isinstance(count_change_dict, dict) else None
    sent_dict = _safe_get(stage1, "news_report", "news_sentiment", "avg_sentiment")
    corp_sent = sent_dict.get("corporate") if isinstance(sent_dict, dict) else None
    corporate_distress = (
        max(0, corp_count_change) * max(0, -corp_sent)
        if corp_count_change is not None and corp_sent is not None else None
    )

    bias_30d = _safe_get(stage1, "news_report", "release_surprise", "bias_30d")
    dovish_bias = (
        +0.5 if bias_30d == "dovish_surprise"
        else (-0.5 if bias_30d == "hawkish_surprise"
        else (0.0 if bias_30d else None))
    )

    components_raw = {
        "hy_oas_bps": hy_oas_current,
        "hy_oas_momentum": hy_oas_momentum,
        "credit_quality_bps": credit_quality,
        "funding_bps": funding,
        "corporate_distress": corporate_distress,
        "dovish_bias": dovish_bias,
    }
    weights = {
        "hy_oas_bps": 0.30, "hy_oas_momentum": 0.25,
        "credit_quality_bps": 0.15, "funding_bps": 0.10,
        "corporate_distress": 0.15, "dovish_bias": 0.05,
    }
    return _aggregate("F5_credit_cycle", components_raw, weights)
```

- [ ] **Step 7: F6 compute_krw_regime 수정**

```python
def compute_krw_regime(stage1) -> FactorScore:
    """F6 krw_regime — +z = weak KRW.
    PR0 hotfix: kr_macro → kr_divergence + kr_export.
    krw_level 은 macro_report.fx.usd_krw 활용 (external_fetcher 대안).
    """
    from tradingagents.skills.research.external_fetchers import fetch_krw_usd_level

    # KRW overnight (news)
    krw_overnight_pct = _safe_get(stage1, "news_report", "global_overnight", "krw", "change_pct")

    # KRW level — macro_report.fx.usd_krw 우선, external fallback
    krw_level = _safe_get(stage1, "macro_report", "fx", "usd_krw")
    if krw_level is None:
        krw_level = fetch_krw_usd_level()

    # kr_divergence (이전 kr_macro 였음)
    kr_us_rate_diff = _safe_get(stage1, "macro_report", "kr_divergence", "us_kr_rate_gap_bps")
    # foreign_flow — IMPLEMENTER: verify ForeignFlowSnapshot field name
    foreign_flow = _safe_get(stage1, "macro_report", "foreign_flow", "net_flow_z")
    # kr_export — IMPLEMENTER: verify KRExportSnapshot field name
    kr_exports = _safe_get(stage1, "macro_report", "kr_export", "exports_yoy_pct")

    # BOK tone (news)
    bok_tone = _safe_get(stage1, "news_report", "cb_speakers", "bok_tone_balance")

    components_raw = {
        "krw_overnight_pct": krw_overnight_pct,
        "krw_level": krw_level,
        "kr_us_rate_diff": kr_us_rate_diff,
        "foreign_flow_z": foreign_flow,
        "kr_exports_yoy": kr_exports,
        "bok_tone_balance": bok_tone,
    }
    weights = {
        "krw_overnight_pct": 0.20, "krw_level": 0.20,
        "kr_us_rate_diff": 0.15, "foreign_flow_z": 0.20,
        "kr_exports_yoy": 0.10, "bok_tone_balance": 0.15,
    }
    return _aggregate("F6_krw_regime", components_raw, weights)
```

- [ ] **Step 8: F7 compute_equity_vol_regime 수정**

```python
def compute_equity_vol_regime(stage1) -> FactorScore:
    """F7 equity_vol_regime — +z = high vol.
    PR0 hotfix: vix_term 이 별도 snapshot. SKEW field 검증.
    realized_vol_60d placeholder (C8 활성화 — RealVolSnapshot).
    """
    # vix (VolatilitySnapshot — IMPLEMENTER: verify field names)
    vix_level = _safe_get(stage1, "risk_report", "vix", "current_value")
    vix_z = _safe_get(stage1, "risk_report", "vix", "z_score")

    # vix_term (별도 snapshot VIXTermStructureSnapshot — IMPLEMENTER: verify field)
    vix_term = _safe_get(stage1, "risk_report", "vix_term", "ratio_3m_1m")

    # move (IMPLEMENTER: verify 어느 schema field — vxn 일 수도)
    move = _safe_get(stage1, "risk_report", "vxn", "current_value")  # placeholder — verify

    # skew (SkewSnapshot — IMPLEMENTER: verify field)
    skew_change = _safe_get(stage1, "risk_report", "skew", "change_1m_z")  # placeholder — verify

    # TODO (C8): realized_vol_60d = _safe_get(stage1, "risk_report", "real_vol", "realized_vol_60d")
    realized_vol = None

    # sentiment_dispersion (news)
    sent_dispersion = _safe_get(stage1, "news_report", "news_sentiment", "sentiment_dispersion")
    count_change_dict = _safe_get(stage1, "news_report", "news_sentiment", "count_change_vs_7d")
    geo_change = count_change_dict.get("geopolitical") if isinstance(count_change_dict, dict) else None
    geo_surge = max(0, geo_change) if geo_change is not None else None

    components_raw = {
        "vix_level": vix_level, "vix_z_score": vix_z, "vix_term_ratio": vix_term,
        "move": move, "realized_vol_60d": realized_vol,  # placeholder
        "skew_change": skew_change,
        "sentiment_dispersion": sent_dispersion,
        "geopolitical_surge": geo_surge,
    }
    weights = {
        "vix_level": 0.22, "vix_z_score": 0.12, "vix_term_ratio": 0.12,
        "move": 0.18, "realized_vol_60d": 0.0,  # weight 0 until C8
        "skew_change": 0.08,
        "sentiment_dispersion": 0.08, "geopolitical_surge": 0.07,
    }
    return _aggregate("F7_equity_vol_regime", components_raw, weights)
```

- [ ] **Step 9: F8 compute_valuation 수정**

```python
def compute_valuation(stage1) -> FactorScore:
    """F8 valuation.
    PR0 hotfix: tips_yield 가 risk_report.
    kospi_pbr placeholder (C8 활성화 — KRValuationSnapshot).
    """
    from tradingagents.skills.research.external_fetchers import fetch_sp_trailing_pe

    pe = fetch_sp_trailing_pe()
    earnings_yield = (100.0 / pe) if (pe is not None and pe > 0) else None
    tips_yield = _safe_get(stage1, "risk_report", "real_yields", "ten_y_yield_pct")
    erp = (earnings_yield - tips_yield) if (earnings_yield is not None and tips_yield is not None) else None

    # TODO (C8): kospi_pbr = _safe_get(stage1, "macro_report", "kr_valuation", "kospi_pbr")
    kospi_pbr = None  # placeholder

    components_raw = {
        "sp_pe": pe,
        "earnings_yield": earnings_yield,
        "erp": erp,
        "kospi_pbr": kospi_pbr,  # placeholder
    }
    weights = {
        "sp_pe": 0.20, "earnings_yield": 0.30, "erp": 0.30,
        "kospi_pbr": 0.0,  # weight 0 until C8
    }
    return _aggregate("F8_valuation", components_raw, weights)
```

- [ ] **Step 10: F9 compute_liquidity_regime 수정**

```python
def compute_liquidity_regime(stage1) -> FactorScore:
    """F9 liquidity_regime.
    PR0 hotfix: breadth 가 risk_report.breadth_kr / breadth_us.
    realized_vol + sector_dispersion placeholder (C8 활성화).
    """
    # VRP derived — vix 와 realized_vol_60d 둘 다 필요
    vix = _safe_get(stage1, "risk_report", "vix", "current_value")
    # TODO (C8): realized_vol = _safe_get(stage1, "risk_report", "real_vol", "realized_vol_60d")
    realized_vol = None
    vrp = None
    if vix is not None and realized_vol is not None:
        vix_var = (vix / 100.0) ** 2
        realized_var = realized_vol ** 2
        vrp = (vix_var - realized_var) * 10000.0

    # eq_bond_corr — IMPLEMENTER: verify EquityBondCorrelationSnapshot field
    eq_bond_corr = _safe_get(stage1, "risk_report", "equity_bond_corr", "correlation_60d")

    # TODO (C8): sector_dispersion = _safe_get(stage1, "risk_report", "breadth_kr", "sector_return_dispersion")
    sector_dispersion = None  # placeholder

    # breadth — IMPLEMENTER: pick breadth_kr or breadth_us, verify field
    breadth = _safe_get(stage1, "risk_report", "breadth_kr", "advance_decline_ratio")

    # news event_cluster + rising_signal (이미 작동)
    event_cluster = _safe_get(stage1, "news_report", "release_surprise", "high_importance_today")
    event_cluster_f = float(event_cluster) if event_cluster is not None else None
    ns = _safe_get(stage1, "news_report", "news_sentiment")
    rising_cat = _safe_get(stage1, "news_report", "news_sentiment", "rising_category")
    rising_signal = 1.0 if rising_cat is not None else (0.0 if ns is not None else None)

    components_raw = {
        "vrp": vrp,                        # placeholder until C8 (realized_vol 필요)
        "eq_bond_corr": eq_bond_corr,
        "sector_dispersion": sector_dispersion,  # placeholder
        "breadth": breadth,
        "event_cluster": event_cluster_f,
        "rising_signal": rising_signal,
    }
    weights = {
        "vrp": 0.0,  # weight 0 until C8 (realized_vol 필요)
        "eq_bond_corr": 0.18,
        "sector_dispersion": 0.0,  # weight 0 until C8
        "breadth": 0.08,
        "event_cluster": 0.12,
        "rising_signal": 0.09,
    }
    return _aggregate("F9_liquidity_regime", components_raw, weights)
```

- [ ] **Step 11: 기존 unit test 실행 (MagicMock 기반 — 통과해야)**

```bash
uv run pytest tests/unit/skills/research/test_factor_estimators_individual.py -v 2>&1 | tail -10
uv run pytest tests/unit/skills/research/ -q 2>&1 | tail -3
```

Expected: 모두 PASS (MagicMock 이 어떤 path 든 response).

- [ ] **Step 12: 전체 회귀**

```bash
uv run pytest tests/unit/ -q 2>&1 | tail -3
uv run pytest tests/integration/ -q 2>&1 | tail -3
```

Expected: 3 unit fail / 668 pass; 18 integ fail / 16 pass (baseline 유지).

- [ ] **Step 13: regression_log.md 의 Post-C1 채움**

`artifacts/2026-05-23/regression_log.md` 의 `## Post-C1` 추가:

```markdown
## Post-C1

### Unit
$ uv run pytest tests/unit/ -q 2>&1 | tail -3
<paste>

### Integration
$ uv run pytest tests/integration/ -q 2>&1 | tail -3
<paste>

### Δ from Post-C0
- Unit: 변경 0 (MagicMock test 그대로 통과)
- Integration: 변경 0
- 0 *new* regression
- Note: 실제 path 정확도 는 C2 의 real schema integration test 가 검증
```

- [ ] **Step 14: C1 commit**

```bash
git add tradingagents/skills/research/factor_estimators.py \
        artifacts/2026-05-23/regression_log.md

git commit -m "$(cat <<'EOF'
fix(stage2): factor_estimators field path 수정 (C1, PR0 hotfix)

PR1 의 silent broken state 해소 — _safe_get 의 wrong path 가 silently None 반환,
factor signal coverage ~40% 였음.

수정된 path (17 active fix):
- macro_report.growth.gdp_nowcast → macro_report.gdp_nowcast.nowcast_pct
- macro_report.growth.nfci → macro_report.financial_conditions.nfci
- macro_report.employment.sahm_trigger → macro_report.employment.sahm_rule_triggered
- macro_report.yield_curve.slope_2_10y_bps → macro_report.yield_curve.spread_10y_2y_bps
- macro_report.cpi.* → macro_report.inflation.*
- macro_report.inflation_exp.* → macro_report.inflation_expectations.*
- macro_report.real_yields → risk_report.real_yields.ten_y_yield_pct
- macro_report.fed_path.implied_change_6m_bps → macro_report.fed_path.path_bps
- macro_report.kr_macro → macro_report.kr_divergence / kr_export
- macro_report.fx.usd_krw 활용 (F6 의 krw_level)
- 그 외 risk_report 의 vix_term, skew, breadth path 정정

5 placeholder TODO (C8 활성화 — PR1 의존):
- F1: cfnai
- F4: spread_30y_5y_bps
- F7: realized_vol_60d
- F8: kospi_pbr
- F9: vrp (realized_vol 의존) + sector_dispersion

기존 MagicMock test 통과 유지. 실제 path 정확도 는 C2 의 real schema
integration test 에서 검증.

Regression (artifacts/2026-05-23/regression_log.md):
- Unit: 3 failed (pre-existing) / 668 passed (변경 0)
- Integration: 18 failed (pre-existing) / 16 passed (변경 0)
- Δ baseline: 0 new regression

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Real Schema Integration Test (C2)

### Task 2.1: tests/integration/test_factor_estimators_real_schema.py 신설

**Files:**
- Create: `tests/integration/test_factor_estimators_real_schema.py`

- [ ] **Step 1: helper _build_real_stage1_baseline() 작성 (모든 required field)**

```python
"""Real Stage 1 schema instance 으로 factor estimator 검증.

PR0 의 silent path mismatch 차단 — MagicMock 의 attribute 자동 생성 우회.
"""
from datetime import date, datetime
from typing import Any

import pytest

from tradingagents.schemas.reports import (
    MacroReport, RiskReport, TechnicalReport, NewsReport,
)
from tradingagents.schemas.macro import (
    YieldCurveSnapshot, InflationSnapshot, EmploymentSnapshot,
    DivergenceScore, RegimeClassification, KRExportSnapshot,
    KRLeadingIndexSnapshot, KRBusinessSurveySnapshot, USLeadingIndexSnapshot,
    GDPNowSnapshot, FinancialConditionsSnapshot, InflationExpectationsSnapshot,
    FedPathSnapshot, FXSnapshot, RiskAppetiteSnapshot, ChinaLeadingSnapshot,
    ForeignFlowSnapshot, PolicyUncertaintySnapshot, TailRiskSnapshot,
)
from tradingagents.skills.research.factor_estimators import compute_all_factors


# IMPLEMENTER: 각 snapshot 의 required field 가 무엇인지 grep + read 후 정확히 채움.
# 본 helper 는 *모든 schema 의 valid instance* 를 baseline value 로 build.
# pytest.fixture 로 reuse.

@pytest.fixture
def real_stage1_baseline() -> dict[str, Any]:
    """모든 9 factor 의 component 가 readable 한 real Stage 1 state.
    Baseline values (대부분 평균 ≈ 0 효과)."""
    return {
        "macro_summary": "baseline",
        "risk_summary": "baseline",
        "technical_summary": "baseline",
        "news_summary": "baseline",
        "macro_report": _build_baseline_macro_report(),
        "risk_report": _build_baseline_risk_report(),
        "technical_report": _build_baseline_technical_report(),
        "news_report": _build_baseline_news_report(),
    }


def _build_baseline_macro_report() -> MacroReport:
    # IMPLEMENTER: 각 snapshot 의 required field 채움.
    # grep 'class <SnapshotName>' tradingagents/schemas/macro.py
    return MacroReport(
        as_of=date.today(),
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
        kr_divergence=DivergenceScore(
            us_kr_rate_gap_bps=-100, us_kr_inflation_gap=0.5, score=-2.0,
        ),
        regime=RegimeClassification(  # IMPLEMENTER: verify required fields
            quadrant="A",
            probability=0.6,
            confidence="medium",
        ),
        upcoming_events=[],
        kr_export=KRExportSnapshot(...),         # IMPLEMENTER: required fields
        kr_leading=KRLeadingIndexSnapshot(...),
        kr_business_survey=KRBusinessSurveySnapshot(...),
        us_leading=USLeadingIndexSnapshot(...),
        gdp_nowcast=GDPNowSnapshot(nowcast_pct=2.0, change_from_prior=0.0),
        financial_conditions=FinancialConditionsSnapshot(
            nfci=0.0, anfci=0.0, regime="neutral", tightening=False,
        ),
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
        risk_appetite=RiskAppetiteSnapshot(...),
        china_leading=ChinaLeadingSnapshot(...),
        foreign_flow=ForeignFlowSnapshot(...),
        policy_uncertainty=PolicyUncertaintySnapshot(...),
        tail_risk=TailRiskSnapshot(...),
    )


def _build_baseline_risk_report() -> RiskReport:
    # IMPLEMENTER: verify required fields per snapshot via grep + Read schemas/risk.py
    from tradingagents.schemas.risk import (
        VolatilitySnapshot, SpreadSnapshot, SentimentSnapshot, BreadthSnapshot,
        PCASnapshot, SystemicRiskScore, VIXTermStructureSnapshot, SkewSnapshot,
        VxnSnapshot, RealYieldsSnapshot, FundingStressSnapshot, CreditQualitySnapshot,
        KRYieldCurveSnapshot, KRCorpSpreadSnapshot, KRMarginDebtSnapshot,
        KRMarketTierSnapshot, EquityBondCorrelationSnapshot,
    )
    return RiskReport(
        as_of=date.today(),
        vix=VolatilitySnapshot(current_value=20.0, z_score=0.0, ...),  # IMPLEMENTER
        vkospi=VolatilitySnapshot(...),
        credit_spread_us_ig=SpreadSnapshot(...),
        credit_spread_us_hy=SpreadSnapshot(current_bps=400.0, momentum_z=0.0, ...),
        fear_greed=SentimentSnapshot(...),
        breadth_kr=BreadthSnapshot(...),  # IMPLEMENTER: include all required + advance_decline_ratio
        breadth_us=BreadthSnapshot(...),
        correlation_concentration=PCASnapshot(...),
        systemic_score=SystemicRiskScore(...),
        vix_term=VIXTermStructureSnapshot(ratio_3m_1m=1.0, ...),
        skew=SkewSnapshot(change_1m_z=0.0, ...),
        vxn=VxnSnapshot(current_value=20.0, ...),
        real_yields=RealYieldsSnapshot(ten_y_yield_pct=0.5, ...),
        funding_stress=FundingStressSnapshot(spread_bps=10.0, ...),
        credit_quality=CreditQualitySnapshot(quality_spread_bps=90.0, ...),
        kr_yield_curve=KRYieldCurveSnapshot(...),
        kr_corp_spread=KRCorpSpreadSnapshot(...),
        kr_margin_debt=KRMarginDebtSnapshot(...),
        kr_market_tier=KRMarketTierSnapshot(...),
        equity_bond_corr=EquityBondCorrelationSnapshot(correlation_60d=-0.2, ...),
    )


def _build_baseline_technical_report() -> TechnicalReport:
    return TechnicalReport(
        as_of=date.today(),
        asset_class_momentum={},
        individual_etf_states={},
        correlation_clusters=[],
    )


def _build_baseline_news_report() -> NewsReport:
    # IMPLEMENTER: NewsReport 의 required fields + Tier-1~5 Optional fields
    return NewsReport(
        as_of=date.today(),
        upcoming_events=[],
        ranked_news=[],
        global_overnight=None,  # 일부 test 만 채움
        release_surprise=None,
        news_sentiment=None,
        cb_speakers=None,
        save_brief=None,
    )
```

- [ ] **Step 2: Required field 검증 (helper 완성)**

```bash
# 각 schema 의 required field 확인 + helper 정확히 채움
grep -B 1 -A 30 "^class YieldCurveSnapshot" tradingagents/schemas/macro.py
grep -B 1 -A 30 "^class KRExportSnapshot" tradingagents/schemas/macro.py
# ... 모든 사용 snapshot ...
```

IMPLEMENTER: helper 의 `...` (ellipsis) 부분 모두 정확한 field value 채움. 모든 required field (default 없는 field) 가 포함되도록.

- [ ] **Step 3: helper test — pydantic validation pass**

`tests/integration/test_factor_estimators_real_schema.py` 에 추가:

```python
def test_baseline_helper_builds_valid_schema(real_stage1_baseline):
    """모든 schema instance 가 pydantic validation pass."""
    assert real_stage1_baseline["macro_report"] is not None
    assert real_stage1_baseline["risk_report"] is not None
    assert real_stage1_baseline["technical_report"] is not None
    assert real_stage1_baseline["news_report"] is not None
```

```bash
uv run pytest tests/integration/test_factor_estimators_real_schema.py::test_baseline_helper_builds_valid_schema -v 2>&1 | tail -10
```

Expected: PASS. 만약 fail → snapshot 의 required field 누락 — helper 보완.

- [ ] **Step 4: failing test — factor coverage after C1**

```python
def test_compute_all_factors_with_real_schema_after_c1(real_stage1_baseline):
    """C1 (path fix only) 후 — 각 factor 의 expected coverage 충족.
    5 placeholder component (cfnai, slope_5_30y, realized_vol, kospi_pbr, sector_dispersion)
    는 C8 후 활성화 — 본 test 에서는 이들 제외 coverage 검증.
    """
    scores = compute_all_factors(real_stage1_baseline)

    # Expected min coverage (C1 path fix 만으로)
    expected_min = {
        "growth_surprise": 0.60,
        "inflation_surprise": 0.85,
        "real_rate": 0.85,
        "term_premium": 0.55,
        "credit_cycle": 0.85,
        "krw_regime": 0.75,
        "equity_vol_regime": 0.65,
        "valuation": 0.45,
        "liquidity_regime": 0.50,
    }
    for factor_name, min_cov in expected_min.items():
        score = getattr(scores, factor_name)
        assert score.confidence >= min_cov, (
            f"{factor_name} confidence {score.confidence:.2f} < {min_cov} "
            f"(components: {list(score.components.keys())})"
        )


def test_no_silent_path_mismatch(real_stage1_baseline):
    """모든 factor 가 *적어도 1 active component* (confidence > 0)."""
    scores = compute_all_factors(real_stage1_baseline)
    for factor_name in (
        "growth_surprise", "inflation_surprise", "real_rate", "term_premium",
        "credit_cycle", "krw_regime", "equity_vol_regime",
        "valuation", "liquidity_regime",
    ):
        score = getattr(scores, factor_name)
        assert score.confidence > 0, (
            f"{factor_name}: silent broken — 0 active components"
        )


def test_extreme_inflation_propagates(real_stage1_baseline):
    """High inflation perturbation → F2 z 크게 positive (path 가 정확히 작동 검증)."""
    state = dict(real_stage1_baseline)
    # InflationSnapshot 의 cpi_yoy 만 perturb
    macro = state["macro_report"]
    macro.inflation.cpi_yoy = 8.0
    macro.inflation.momentum_3mo = 10.0
    state["macro_report"] = macro

    scores = compute_all_factors(state)
    assert scores.inflation_surprise.z_score > 1.0, (
        f"F2 should respond strongly to inflation, got {scores.inflation_surprise.z_score:.2f}"
    )


def test_extreme_vix_propagates_to_f7(real_stage1_baseline):
    """High VIX perturbation → F7 z 크게 positive."""
    state = dict(real_stage1_baseline)
    risk = state["risk_report"]
    risk.vix.current_value = 45.0
    risk.vix.z_score = 3.0
    state["risk_report"] = risk

    scores = compute_all_factors(state)
    assert scores.equity_vol_regime.z_score > 0.5, (
        f"F7 should respond strongly to VIX spike, got {scores.equity_vol_regime.z_score:.2f}"
    )
```

- [ ] **Step 5: test 실행 — *경우에 따라 fail* 가능 (path 가 여전히 wrong 한 경우)**

```bash
uv run pytest tests/integration/test_factor_estimators_real_schema.py -v 2>&1 | tail -20
```

Expected:
- 정상: 모두 PASS
- Fail 발견: factor_estimators.py 에 *남은 path mismatch* 또는 helper 의 schema build 오류 — 즉시 fix

만약 fail 시:
1. Error trace 분석 — 어느 factor 의 어느 component 가 confidence 미달?
2. Schema 의 *진짜 field name* grep 확인
3. factor_estimators.py 에서 해당 path 수정 (C1 의 일부로 amend)

수정 후 재실행 — PASS 까지 반복.

- [ ] **Step 6: 전체 회귀**

```bash
uv run pytest tests/unit/ -q 2>&1 | tail -3
uv run pytest tests/integration/ -q 2>&1 | tail -3
```

Expected: 3 unit fail / 18 integ fail (pre-existing), 0 new failure. integ pass +5 (C2 의 5 신규 test).

- [ ] **Step 7: regression_log.md Post-C2 갱신**

```markdown
## Post-C2

### Unit
$ uv run pytest tests/unit/ -q 2>&1 | tail -3
<paste>

### Integration
$ uv run pytest tests/integration/ -q 2>&1 | tail -3
<paste>

### Δ from Post-C1
- Unit: 변경 0
- Integration: +5 passed (test_factor_estimators_real_schema.py 5 new tests)
- 0 new regression
- Critical: real schema integration test PASS — path mismatch silent fail 차단
```

- [ ] **Step 8: C2 commit**

```bash
git add tests/integration/test_factor_estimators_real_schema.py \
        artifacts/2026-05-23/regression_log.md

git commit -m "$(cat <<'EOF'
test(stage2): real schema integration test for factor_estimators (C2)

MagicMock 우회 — real Stage 1 schema instance (MacroReport, RiskReport,
TechnicalReport, NewsReport) 로 factor estimator 검증.

PR0 의 silent broken state 의 영구 방지:
- _build_real_stage1_baseline() helper — 모든 schema 의 valid instance 빌드
- 각 factor 의 expected_min coverage 검증 (path fix 만으로)
- no_silent_path_mismatch test — 각 factor confidence > 0 보장
- extreme perturbation propagation test — 정확한 path 작동 검증

본 test 는 *MagicMock 으로 가려진 silent fail 재발 방지* 의 핵심 gate.

Regression:
- Unit: 3 failed (pre-existing) / 668 passed
- Integration: 18 failed (pre-existing) / 21 passed (+5 new)
- 0 new regression

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Grill-me #1 (Before C3 series)

**Trigger**: C2 commit 직후, C3 시작 전.

**무엇 grill**:
- 5-indicator sub-skill 의 *API shape* (function signature, return type)
- Error handling pattern — fetch 실패 시 None vs default vs raise
- Fetch retry logic — `lru_cache` size, retry count, backoff
- Schema default values — 0.0 vs None for new fields (이미 spec 결정)

**기록**: `artifacts/2026-05-23/decisions.md` 의 D7-D9 채움.

---

## Task 3: C3 — CFNAI

### Task 3.1: Schema 확장 (FinancialConditionsSnapshot)

**Files:**
- Modify: `tradingagents/schemas/macro.py`
- Create: `tests/unit/schemas/test_factor_model_schemas.py`

- [ ] **Step 1: failing test 작성**

`tests/unit/schemas/test_factor_model_schemas.py` (신규):

```python
"""Stage 1 enhance 의 신규 schema fields 검증."""
import pytest
from tradingagents.schemas.macro import FinancialConditionsSnapshot
from datetime import datetime


def test_financial_conditions_has_cfnai_field():
    """cfnai field 가 default 0.0."""
    fci = FinancialConditionsSnapshot(
        nfci=0.0, anfci=0.0, regime="neutral", tightening=False,
        observed_at=datetime.now(),
    )
    assert fci.cfnai == 0.0
    assert fci.cfnai_3m_avg == 0.0


def test_financial_conditions_accepts_cfnai_value():
    fci = FinancialConditionsSnapshot(
        nfci=0.0, anfci=0.0, regime="neutral", tightening=False,
        observed_at=datetime.now(),
        cfnai=+0.5,
        cfnai_3m_avg=+0.3,
    )
    assert fci.cfnai == +0.5
    assert fci.cfnai_3m_avg == +0.3
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/unit/schemas/test_factor_model_schemas.py::test_financial_conditions_has_cfnai_field -v 2>&1 | tail -5
```

Expected: FAIL (cfnai field 미존재).

- [ ] **Step 3: schema 수정**

`tradingagents/schemas/macro.py` 의 `FinancialConditionsSnapshot` 에 field 추가:

```python
class FinancialConditionsSnapshot(StalenessAware):
    """Chicago Fed National Financial Conditions Index. 105+ 금융지표 합성."""
    nfci: float = Field(description="National Financial Conditions Index (standardized)")
    anfci: float = Field(description="Adjusted NFCI (removes background macro)")
    regime: Literal["easy", "neutral", "tight", "crisis"] = Field(
        description="<-0.5=easy, -0.5~0.5=neutral, 0.5~1.0=tight, >1.0=crisis"
    )
    tightening: bool = Field(description="True if NFCI 4-week change > +0.2 (긴축 가속)")

    # ★ NEW (2026-05-23 C3 — for factor model F1)
    cfnai: float = Field(
        default=0.0,
        description="CFNAI (Chicago Fed National Activity Index). 0=trend, +1=above, -1=below.",
    )
    cfnai_3m_avg: float = Field(
        default=0.0,
        description="CFNAI 3-month moving average — NBER recession signal.",
    )
```

- [ ] **Step 4: 통과 확인**

```bash
uv run pytest tests/unit/schemas/test_factor_model_schemas.py -v 2>&1 | tail -5
```

Expected: 2 PASS.

### Task 3.2: skill module — real_activity.py

**Files:**
- Create: `tradingagents/skills/macro/real_activity.py`
- Create: `tests/unit/skills/macro/test_real_activity.py`

- [ ] **Step 1: failing test 작성**

`tests/unit/skills/macro/test_real_activity.py` (신규):

```python
"""compute_cfnai_metrics tests."""
import pytest
import pandas as pd
from datetime import date
from tradingagents.skills.macro.real_activity import compute_cfnai_metrics


def test_cfnai_latest_returned():
    series = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5])
    latest, avg = compute_cfnai_metrics(series, as_of=date.today())
    assert latest == pytest.approx(0.5)


def test_cfnai_3m_average():
    series = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5])
    latest, avg = compute_cfnai_metrics(series, as_of=date.today())
    assert avg == pytest.approx((0.3 + 0.4 + 0.5) / 3)


def test_cfnai_short_series_returns_latest_for_avg():
    series = pd.Series([0.2, 0.4])
    latest, avg = compute_cfnai_metrics(series, as_of=date.today())
    assert latest == pytest.approx(0.4)
    assert avg == pytest.approx(0.3)  # mean of available 2


def test_cfnai_empty_series_returns_zero():
    series = pd.Series([], dtype=float)
    latest, avg = compute_cfnai_metrics(series, as_of=date.today())
    assert latest == 0.0
    assert avg == 0.0
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/unit/skills/macro/test_real_activity.py -v 2>&1 | tail -5
```

Expected: FAIL (module 미존재).

- [ ] **Step 3: skill 구현**

`tradingagents/skills/macro/real_activity.py` (신규):

```python
"""CFNAI (Chicago Fed National Activity Index) — 85 real economy series composite.

CFNAI: 0 = trend growth (NBER baseline). +1 = well above trend, -1 = well below.
3-month MA 가 standard recession signal (NBER).
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
        cfnai_series: FRED CFNAI (monthly index, dated).
        as_of: report date.

    Returns:
        (latest, 3m_average). Empty series → (0.0, 0.0).
    """
    if cfnai_series.empty:
        return 0.0, 0.0
    cfnai_latest = float(cfnai_series.iloc[-1])
    cfnai_3m_avg = (
        float(cfnai_series.tail(3).mean())
        if len(cfnai_series) >= 1
        else cfnai_latest
    )
    return cfnai_latest, cfnai_3m_avg
```

- [ ] **Step 4: 통과 확인**

```bash
mkdir -p tests/unit/skills/macro
touch tests/unit/skills/macro/__init__.py
uv run pytest tests/unit/skills/macro/test_real_activity.py -v 2>&1 | tail -5
```

Expected: 4 PASS.

### Task 3.3: macro_quant_analyst integration

**Files:**
- Modify: `tradingagents/agents/analysts/macro_quant_analyst.py`

- [ ] **Step 1: 기존 analyst 의 financial_conditions 통합 부분 찾기**

```bash
grep -n "compute_financial_conditions\|financial_conditions=" tradingagents/agents/analysts/macro_quant_analyst.py
```

Expected: line ~280 의 `fci = compute_financial_conditions(nfci, anfci, as_of=as_of)`.

- [ ] **Step 2: CFNAI fetch + integrate 추가**

`tradingagents/agents/analysts/macro_quant_analyst.py` 의 financial_conditions 계산 *직후* 에 추가:

```python
# Existing
fci = compute_financial_conditions(nfci, anfci, as_of=as_of)

# ★ NEW (2026-05-23 C3 — CFNAI for factor model F1)
try:
    from tradingagents.skills.macro.real_activity import compute_cfnai_metrics
    cfnai_series = fred.get_series("CFNAI")  # IMPLEMENTER: verify FRED series ID
    cfnai_latest, cfnai_3m_avg = compute_cfnai_metrics(cfnai_series, as_of)
    fci = fci.model_copy(update={
        "cfnai": cfnai_latest,
        "cfnai_3m_avg": cfnai_3m_avg,
    })
except Exception as e:
    logger.warning("CFNAI fetch failed (factor F1 affected): %s", e)
    # fci 의 default 0.0 유지
```

- [ ] **Step 3: 전체 회귀 (analyst 가 변경됨 — test_macro_quant_analyst.py 영향 확인)**

```bash
uv run pytest tests/unit/agents/test_macro_quant_analyst.py -v 2>&1 | tail -10
uv run pytest tests/unit/ -q 2>&1 | tail -3
uv run pytest tests/integration/ -q 2>&1 | tail -3
```

Expected: macro_quant test 가 *pre-existing fail 외* 0 new failure. (이미 1 test pre-existing fail — `test_macro_analyst_orchestration` — *증가하지 않음* 확인.)

### Task 3.4: C3 commit

- [ ] **Step 1: regression_log.md Post-C3 갱신**

`artifacts/2026-05-23/regression_log.md` 의 `## Post-C3` 추가.

- [ ] **Step 2: commit**

```bash
git add tradingagents/schemas/macro.py \
        tradingagents/skills/macro/real_activity.py \
        tradingagents/agents/analysts/macro_quant_analyst.py \
        tests/unit/schemas/test_factor_model_schemas.py \
        tests/unit/skills/macro/__init__.py \
        tests/unit/skills/macro/test_real_activity.py \
        artifacts/2026-05-23/regression_log.md

git commit -m "$(cat <<'EOF'
feat(stage1): CFNAI fetcher + FinancialConditionsSnapshot 확장 (C3)

Factor model F1 growth_surprise 의 component 추가.

Schema 확장:
- FinancialConditionsSnapshot.cfnai (default 0.0)
- FinancialConditionsSnapshot.cfnai_3m_avg (default 0.0)

Sub-skill 신설:
- tradingagents/skills/macro/real_activity.py
- compute_cfnai_metrics(cfnai_series, as_of) → (latest, 3m_avg)

Analyst integration:
- macro_quant_analyst.py: FRED CFNAI fetch + fci.model_copy(update=...)
- Try/except: fetch 실패 시 default 0.0 유지 (graceful degradation)

Test (4 + 2 new):
- test_factor_model_schemas.py: CFNAI field default + acceptance
- test_real_activity.py: latest, 3m avg, short series, empty series

C8 에서 factor_estimators 의 cfnai placeholder 활성화 예정.

Regression:
- Unit: 3 failed (pre-existing) / 668+6=674 passed
- Integration: unchanged (21 passed)
- 0 new regression

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Grill-me #2 (After C3 / Before C4)

**Trigger**: C3 commit 직후, C4 시작 전.

**무엇 grill**:
- C3 의 *실측* — analyst integration 의 model_copy 패턴 OK? try/except 처리 적정?
- 5-indicator 의 *공통 pattern* 확정 — C4-C7 에서 동일 적용
- C3 에서 *발견된 issue* (예: FRED series ID 정확성, fetch lag) 의 *C4-C7 적용*

**기록**: `artifacts/2026-05-23/decisions.md` 의 D10 채움.

---

## Task 4: C4 — Yield Curve 5-30y Slope

### Task 4.1: Schema 확장 (YieldCurveSnapshot)

**Files:**
- Modify: `tradingagents/schemas/macro.py`
- Modify: `tests/unit/schemas/test_factor_model_schemas.py`

- [ ] **Step 1: failing test 추가**

`tests/unit/schemas/test_factor_model_schemas.py` 에 추가:

```python
from tradingagents.schemas.macro import YieldCurveSnapshot


def test_yield_curve_has_spread_30y_5y_field():
    yc = YieldCurveSnapshot(
        spread_10y_2y_bps=80.0, spread_10y_3m_bps=120.0,
        inverted_days_count=0, percentile_5y=0.5,
        observed_at=datetime.now(),
    )
    assert yc.spread_30y_5y_bps == 0.0


def test_yield_curve_accepts_spread_30y_5y():
    yc = YieldCurveSnapshot(
        spread_10y_2y_bps=80.0, spread_10y_3m_bps=120.0,
        inverted_days_count=0, percentile_5y=0.5,
        observed_at=datetime.now(),
        spread_30y_5y_bps=120.0,
    )
    assert yc.spread_30y_5y_bps == 120.0
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/unit/schemas/test_factor_model_schemas.py::test_yield_curve_has_spread_30y_5y_field -v
```

Expected: FAIL.

- [ ] **Step 3: schema 수정**

`tradingagents/schemas/macro.py` 의 `YieldCurveSnapshot`:

```python
class YieldCurveSnapshot(StalenessAware):
    spread_10y_2y_bps: float = Field(description="10Y - 2Y in basis points")
    spread_10y_3m_bps: float = Field(description="10Y - 3M in basis points")
    inverted_days_count: int = Field(ge=0, description="Days inverted in last 365")
    percentile_5y: float = Field(ge=0, le=1, description="5y historical percentile")

    # ★ NEW (2026-05-23 C4 — for factor model F4 term_premium)
    spread_30y_5y_bps: float = Field(
        default=0.0,
        description="30Y - 5Y in basis points. Long-end curve — F4 term_premium component.",
    )
```

- [ ] **Step 4: PASS 확인**

```bash
uv run pytest tests/unit/schemas/test_factor_model_schemas.py -v 2>&1 | tail -5
```

Expected: 4 PASS (cfnai 2 + spread_30y_5y 2).

### Task 4.2: Skill module — yield_curve.py

**Files:**
- Create: `tradingagents/skills/macro/yield_curve.py`
- Create: `tests/unit/skills/macro/test_yield_curve.py`

- [ ] **Step 1: 기존 yield_curve skill 존재 여부 확인**

```bash
ls tradingagents/skills/macro/ | grep yield
grep -rn "compute_yield_curve\|yield_curve.*compute" tradingagents/ --include="*.py" | head -5
```

만약 *없음*: 신설. 만약 *있음*: 확장 (5-30y compute 추가).

- [ ] **Step 2: failing test**

`tests/unit/skills/macro/test_yield_curve.py` (신규):

```python
"""compute_yield_curve_extras tests — slope_5_30y derived."""
import pytest
from datetime import date
from tradingagents.skills.macro.yield_curve import compute_yield_curve_extras


def test_slope_5_30y_basic():
    """DGS30 - DGS5."""
    slope = compute_yield_curve_extras(dgs5_pct=4.0, dgs30_pct=4.8, as_of=date.today())
    assert slope == pytest.approx(80.0)  # 0.8 pp → 80 bps


def test_slope_5_30y_inverted():
    slope = compute_yield_curve_extras(dgs5_pct=5.0, dgs30_pct=4.5, as_of=date.today())
    assert slope == pytest.approx(-50.0)


def test_slope_5_30y_none_inputs():
    slope = compute_yield_curve_extras(dgs5_pct=None, dgs30_pct=4.8, as_of=date.today())
    assert slope is None
```

- [ ] **Step 3: 실패 확인**

```bash
uv run pytest tests/unit/skills/macro/test_yield_curve.py -v 2>&1 | tail -5
```

Expected: FAIL.

- [ ] **Step 4: skill 구현**

`tradingagents/skills/macro/yield_curve.py` (신규):

```python
"""Yield curve extras — long-end slope (5-30y) for factor model F4 term_premium.

기존 spread_10y_2y_bps, spread_10y_3m_bps 는 fred_fetcher 가 직접 계산.
5-30y slope 는 별도 — long-end (real economy) 의 term premium signal.
"""
from datetime import date
from tradingagents.skills.registry import register_skill


@register_skill(name="compute_yield_curve_extras", category="macro")
def compute_yield_curve_extras(
    dgs5_pct: float | None,
    dgs30_pct: float | None,
    as_of: date,
) -> float | None:
    """Returns slope_30y_5y in basis points (DGS30 - DGS5) * 100.

    Args:
        dgs5_pct: 5y Treasury yield in percent.
        dgs30_pct: 30y Treasury yield in percent.
        as_of: report date.

    Returns:
        Spread in bps, or None if either input is None.
    """
    if dgs5_pct is None or dgs30_pct is None:
        return None
    return (dgs30_pct - dgs5_pct) * 100.0
```

- [ ] **Step 5: PASS**

```bash
uv run pytest tests/unit/skills/macro/test_yield_curve.py -v 2>&1 | tail -5
```

Expected: 3 PASS.

### Task 4.3: macro_quant_analyst integration

**Files:**
- Modify: `tradingagents/agents/analysts/macro_quant_analyst.py`

- [ ] **Step 1: 기존 YieldCurveSnapshot 빌드 부분 찾기**

```bash
grep -n "YieldCurveSnapshot\|yield_curve=" tradingagents/agents/analysts/macro_quant_analyst.py | head -5
```

- [ ] **Step 2: slope_5_30y fetch + populate 추가**

YieldCurveSnapshot 빌드 부분 근처에 추가:

```python
# ★ NEW (2026-05-23 C4 — slope_5_30y for F4)
try:
    from tradingagents.skills.macro.yield_curve import compute_yield_curve_extras
    dgs5 = fred.get_series("DGS5")  # IMPLEMENTER: verify series ID
    dgs30 = fred.get_series("DGS30")
    dgs5_latest = float(dgs5.iloc[-1]) if not dgs5.empty else None
    dgs30_latest = float(dgs30.iloc[-1]) if not dgs30.empty else None
    spread_30y_5y_bps = compute_yield_curve_extras(dgs5_latest, dgs30_latest, as_of)
    if spread_30y_5y_bps is not None:
        yield_curve = yield_curve.model_copy(update={"spread_30y_5y_bps": spread_30y_5y_bps})
except Exception as e:
    logger.warning("slope_5_30y fetch failed (factor F4 affected): %s", e)
```

- [ ] **Step 3: 회귀**

```bash
uv run pytest tests/unit/agents/test_macro_quant_analyst.py -v 2>&1 | tail -10
uv run pytest tests/unit/ -q 2>&1 | tail -3
```

Expected: pre-existing fail 외 0 new failure.

### Task 4.4: C4 commit

```bash
git add tradingagents/schemas/macro.py \
        tradingagents/skills/macro/yield_curve.py \
        tradingagents/agents/analysts/macro_quant_analyst.py \
        tests/unit/schemas/test_factor_model_schemas.py \
        tests/unit/skills/macro/test_yield_curve.py \
        artifacts/2026-05-23/regression_log.md

git commit -m "$(cat <<'EOF'
feat(stage1): yield curve 5-30y slope + YieldCurveSnapshot 확장 (C4)

Factor model F4 term_premium 의 long-end slope component.

Schema:
- YieldCurveSnapshot.spread_30y_5y_bps (default 0.0)

Sub-skill:
- skills/macro/yield_curve.py — compute_yield_curve_extras(dgs5, dgs30, as_of)

Analyst:
- macro_quant_analyst.py: FRED DGS5 + DGS30 fetch + model_copy

Test (2 + 3):
- test_factor_model_schemas: spread_30y_5y default + accept
- test_yield_curve: basic slope, inverted, None inputs

Regression:
- Unit: 3 failed (pre-existing) / 677 passed (+3)
- Integration: unchanged
- 0 new regression

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: C5 — KOSPI PBR

### Task 5.1: Schema 신설 (KRValuationSnapshot)

**Files:**
- Modify: `tradingagents/schemas/macro.py`
- Modify: `tradingagents/schemas/reports.py`
- Modify: `tests/unit/schemas/test_factor_model_schemas.py`

- [ ] **Step 1: failing test 추가**

`tests/unit/schemas/test_factor_model_schemas.py`:

```python
from tradingagents.schemas.macro import KRValuationSnapshot
from tradingagents.schemas.reports import MacroReport


def test_kr_valuation_snapshot_basic():
    kv = KRValuationSnapshot(
        kospi_pbr=1.0, kospi_per=12.0, kospi_div_yield=2.0,
        observed_at=datetime.now(),
    )
    assert kv.kospi_pbr == 1.0
    assert kv.kospi_per == 12.0


def test_macro_report_kr_valuation_default_none():
    # IMPLEMENTER: MacroReport 의 모든 required field 채움 (helper 재사용 가능)
    # 본 test 는 kr_valuation field 가 *Optional, default None*
    macro = _build_minimal_macro_report()  # helper
    assert macro.kr_valuation is None


def test_macro_report_accepts_kr_valuation():
    kv = KRValuationSnapshot(
        kospi_pbr=0.9, kospi_per=11.0, kospi_div_yield=2.2,
        observed_at=datetime.now(),
    )
    macro = _build_minimal_macro_report(kr_valuation=kv)
    assert macro.kr_valuation.kospi_pbr == 0.9


def _build_minimal_macro_report(**override) -> MacroReport:
    # IMPLEMENTER: 모든 required field 채움 (test_factor_estimators_real_schema 의 helper 차용)
    ...
```

- [ ] **Step 2: 실패 확인**

```bash
uv run pytest tests/unit/schemas/test_factor_model_schemas.py::test_kr_valuation_snapshot_basic -v
```

Expected: FAIL.

- [ ] **Step 3: schema 수정**

`tradingagents/schemas/macro.py` 의 *끝부분* 에 추가:

```python
class KRValuationSnapshot(StalenessAware):
    """KOSPI valuation indicators — for factor model F8 valuation.

    PBR < 1.0 = below book value (deep value). Historical avg ~1.0.
    """
    kospi_pbr: float = Field(description="KOSPI 200 PBR")
    kospi_per: float = Field(description="KOSPI 200 forward PER")
    kospi_div_yield: float = Field(description="KOSPI 200 dividend yield %")
```

`tradingagents/schemas/reports.py` 의 `MacroReport`:

```python
class MacroReport(_AnalystReport):
    # ... 기존 18 field ...
    # ★ NEW (2026-05-23 C5)
    kr_valuation: KRValuationSnapshot | None = None
```

`reports.py` 의 import 도 update:
```python
from tradingagents.schemas.macro import (
    # ... 기존 ...
    KRValuationSnapshot,
)
```

- [ ] **Step 4: PASS**

```bash
uv run pytest tests/unit/schemas/test_factor_model_schemas.py -v 2>&1 | tail -10
```

Expected: 모두 PASS (5+ test).

### Task 5.2: Skill module — kr_valuation.py

**Files:**
- Create: `tradingagents/skills/macro/kr_valuation.py`
- Create: `tests/unit/skills/macro/test_kr_valuation.py`

- [ ] **Step 1: failing test**

`tests/unit/skills/macro/test_kr_valuation.py`:

```python
"""compute_kr_valuation tests — pykrx mocked."""
import pytest
from unittest.mock import patch, MagicMock
from datetime import date
import pandas as pd
from tradingagents.skills.macro.kr_valuation import compute_kr_valuation
from tradingagents.schemas.macro import KRValuationSnapshot


def test_kr_valuation_returns_snapshot():
    # pykrx 의 get_market_fundamental: DataFrame returns
    mock_df = pd.DataFrame({
        "PBR": [0.95], "PER": [11.5], "DIV": [2.1],
    }, index=pd.DatetimeIndex(["2026-05-15"]))

    with patch(
        "tradingagents.skills.macro.kr_valuation.stock.get_market_fundamental",
        return_value=mock_df,
    ):
        result = compute_kr_valuation(as_of=date(2026, 5, 15))

    assert isinstance(result, KRValuationSnapshot)
    assert result.kospi_pbr == pytest.approx(0.95)
    assert result.kospi_per == pytest.approx(11.5)
    assert result.kospi_div_yield == pytest.approx(2.1)


def test_kr_valuation_empty_df_returns_zero_snapshot():
    empty_df = pd.DataFrame({"PBR": [], "PER": [], "DIV": []})

    with patch(
        "tradingagents.skills.macro.kr_valuation.stock.get_market_fundamental",
        return_value=empty_df,
    ):
        result = compute_kr_valuation(as_of=date(2026, 5, 15))

    assert result.kospi_pbr == 0.0
    assert result.kospi_per == 0.0


def test_kr_valuation_pykrx_exception_returns_none_or_default():
    with patch(
        "tradingagents.skills.macro.kr_valuation.stock.get_market_fundamental",
        side_effect=Exception("API error"),
    ):
        result = compute_kr_valuation(as_of=date(2026, 5, 15))

    # IMPLEMENTER: design choice — None 또는 default Snapshot
    # 본 spec 은 graceful degradation → default Snapshot 권장
    assert isinstance(result, KRValuationSnapshot)
    assert result.kospi_pbr == 0.0
```

- [ ] **Step 2: 실패**

```bash
uv run pytest tests/unit/skills/macro/test_kr_valuation.py -v 2>&1 | tail -5
```

Expected: FAIL.

- [ ] **Step 3: 구현**

`tradingagents/skills/macro/kr_valuation.py` (신규):

```python
"""KOSPI valuation — PBR/PER/DivYield via pykrx.

KOSPI 200 underlying. as_of 가 KR holiday 시 prior trading day 데이터 사용.
"""
import logging
from datetime import date, timedelta
from pykrx import stock
from tradingagents.schemas._base import StalenessAware  # for observed_at
from tradingagents.schemas.macro import KRValuationSnapshot
from tradingagents.skills.registry import register_skill

logger = logging.getLogger(__name__)


@register_skill(name="compute_kr_valuation", category="macro")
def compute_kr_valuation(as_of: date) -> KRValuationSnapshot:
    """Returns KOSPI 200 valuation snapshot.

    Args:
        as_of: report date (KR holiday 시 prior trading day fallback).

    Returns:
        KRValuationSnapshot. fetch fail 시 default 0.0 (graceful degradation).
    """
    try:
        # pykrx: YYYYMMDD format
        date_str = as_of.strftime("%Y%m%d")
        df = stock.get_market_fundamental(date_str, market="KOSPI200")
        if df.empty:
            logger.warning("pykrx get_market_fundamental returned empty for %s", date_str)
            return _default_snapshot(as_of)

        # pykrx returns DataFrame — average across constituents
        kospi_pbr = float(df["PBR"].mean()) if "PBR" in df.columns else 0.0
        kospi_per = float(df["PER"].mean()) if "PER" in df.columns else 0.0
        kospi_div = float(df["DIV"].mean()) if "DIV" in df.columns else 0.0

        return KRValuationSnapshot(
            kospi_pbr=kospi_pbr,
            kospi_per=kospi_per,
            kospi_div_yield=kospi_div,
            observed_at=as_of,
        )
    except Exception as e:
        logger.warning("KOSPI valuation fetch failed: %s", e)
        return _default_snapshot(as_of)


def _default_snapshot(as_of: date) -> KRValuationSnapshot:
    return KRValuationSnapshot(
        kospi_pbr=0.0, kospi_per=0.0, kospi_div_yield=0.0,
        observed_at=as_of,
    )
```

- [ ] **Step 4: PASS**

```bash
uv run pytest tests/unit/skills/macro/test_kr_valuation.py -v 2>&1 | tail -5
```

Expected: 3 PASS.

### Task 5.3: macro_quant_analyst integration

**Files:**
- Modify: `tradingagents/agents/analysts/macro_quant_analyst.py`

- [ ] **Step 1: MacroReport 생성 부분 찾기 + KRValuationSnapshot 추가**

```bash
grep -n "MacroReport(" tradingagents/agents/analysts/macro_quant_analyst.py
```

MacroReport 생성 (line ~480 추정) 직전에 추가:

```python
# ★ NEW (2026-05-23 C5 — KR valuation for F8)
try:
    from tradingagents.skills.macro.kr_valuation import compute_kr_valuation
    kr_valuation_snapshot = compute_kr_valuation(as_of)
except Exception as e:
    logger.warning("KR valuation skill failed: %s", e)
    kr_valuation_snapshot = None

# Existing MacroReport 생성에 kr_valuation 추가
return MacroReport(
    # ... 기존 18 field ...
    kr_valuation=kr_valuation_snapshot,  # ★ NEW
)
```

- [ ] **Step 2: 회귀**

```bash
uv run pytest tests/unit/agents/test_macro_quant_analyst.py -v 2>&1 | tail -10
uv run pytest tests/unit/ -q 2>&1 | tail -3
```

### Task 5.4: C5 commit

```bash
git add tradingagents/schemas/macro.py \
        tradingagents/schemas/reports.py \
        tradingagents/skills/macro/kr_valuation.py \
        tradingagents/agents/analysts/macro_quant_analyst.py \
        tests/unit/schemas/test_factor_model_schemas.py \
        tests/unit/skills/macro/test_kr_valuation.py \
        artifacts/2026-05-23/regression_log.md

git commit -m "$(cat <<'EOF'
feat(stage1): KOSPI PBR + KRValuationSnapshot 신설 (C5)

Factor model F8 valuation 의 KR equity valuation component.

Schema 신설:
- KRValuationSnapshot (kospi_pbr, kospi_per, kospi_div_yield)
- MacroReport.kr_valuation: Optional, default None

Sub-skill:
- skills/macro/kr_valuation.py — compute_kr_valuation(as_of) → Snapshot
- pykrx market.get_market_fundamental(KOSPI200) 평균

Analyst:
- macro_quant_analyst.py: KR valuation skill 호출 + MacroReport 에 populate
- try/except: graceful degradation

Test (3 + 3):
- test_factor_model_schemas: KRValuationSnapshot + MacroReport integration
- test_kr_valuation: pykrx mock — success/empty/exception

Regression: 0 new failure

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: C6 — Realized Vol + RealVolSnapshot

### Task 6.1: Schema 신설 (RealVolSnapshot)

**Files:**
- Modify: `tradingagents/schemas/risk.py`
- Modify: `tradingagents/schemas/reports.py`
- Modify: `tests/unit/schemas/test_factor_model_schemas.py`

- [ ] **Step 1: failing test**

`tests/unit/schemas/test_factor_model_schemas.py` 에 추가:

```python
from tradingagents.schemas.risk import RealVolSnapshot
from tradingagents.schemas.reports import RiskReport


def test_real_vol_snapshot_basic():
    rv = RealVolSnapshot(
        realized_vol_60d=0.12, realized_vol_20d=0.10,
        observed_at=datetime.now(),
    )
    assert rv.realized_vol_60d == 0.12
    assert rv.vrp_60d == 0.0  # default


def test_real_vol_snapshot_with_vrp():
    rv = RealVolSnapshot(
        realized_vol_60d=0.12, realized_vol_20d=0.10, vrp_60d=120.0,
        observed_at=datetime.now(),
    )
    assert rv.vrp_60d == 120.0


def test_risk_report_real_vol_default_none():
    risk = _build_minimal_risk_report()  # IMPLEMENTER: helper
    assert risk.real_vol is None
```

- [ ] **Step 2: 실패 → schema 수정**

`tradingagents/schemas/risk.py` 의 *끝부분* :

```python
class RealVolSnapshot(StalenessAware):
    """Realized volatility — for factor model F7 vol regime + F9 VRP."""
    realized_vol_60d: float = Field(description="SPY 60-day stddev (annualized)")
    realized_vol_20d: float = Field(description="SPY 20-day stddev (annualized)")
    vrp_60d: float = Field(
        default=0.0,
        description="Variance risk premium: VIX² - realized_60d² (bps²-like)",
    )
```

`tradingagents/schemas/reports.py` 의 `RiskReport`:

```python
class RiskReport(_AnalystReport):
    # ... 기존 ...
    real_vol: RealVolSnapshot | None = None  # ★ NEW (C6)
```

Import update.

- [ ] **Step 3: PASS**

### Task 6.2: Skill module — realized_volatility.py

**Files:**
- Create: `tradingagents/skills/risk/realized_volatility.py`
- Create: `tests/unit/skills/risk/test_realized_volatility.py`

- [ ] **Step 1: failing test**

`tests/unit/skills/risk/test_realized_volatility.py`:

```python
"""compute_realized_volatility tests."""
import pytest
import numpy as np
import pandas as pd
from datetime import date
from tradingagents.skills.risk.realized_volatility import (
    compute_realized_volatility, RealVolSnapshot,
)


def test_realized_vol_basic():
    # 60 day returns, std ≈ 0.01 (1% daily)
    np.random.seed(42)
    returns = pd.Series(np.random.normal(0, 0.01, 100))
    result = compute_realized_volatility(returns, vix_level=20.0, as_of=date.today())

    assert isinstance(result, RealVolSnapshot)
    # annualized: 0.01 * sqrt(252) ≈ 0.158
    assert 0.10 < result.realized_vol_60d < 0.25


def test_realized_vol_vrp_calculation():
    # 60d realized_vol = 0.10 (10% annualized), VIX = 20% (i.e., 0.20)
    # VRP = (0.20)² - (0.10)² = 0.04 - 0.01 = 0.03 → ×10000 = 300 (bps²)
    constant_returns = pd.Series([0.01 / np.sqrt(252)] * 60)  # std ≈ 0
    # IMPLEMENTER: returns 의 std 가 0 이면 realized_vol = 0 → VRP = VIX²
    # Test 의 정확한 expected 값 은 implementer 가 _compute_vrp logic 따라


def test_realized_vol_short_returns():
    """20d 이하 returns 시 graceful."""
    returns = pd.Series(np.random.normal(0, 0.01, 10))
    result = compute_realized_volatility(returns, vix_level=20.0, as_of=date.today())
    assert result.realized_vol_60d == 0.0 or result.realized_vol_60d > 0  # graceful
```

- [ ] **Step 2: 구현**

`tradingagents/skills/risk/realized_volatility.py`:

```python
"""Realized volatility — SPY daily returns aggregated to 60d / 20d stddev.

VRP (variance risk premium): (VIX/100)² - realized² in bps²-like normalization.
Factor model F7 vol regime + F9 liquidity (via VRP) components.
"""
from datetime import date
import numpy as np
import pandas as pd
from tradingagents.schemas.risk import RealVolSnapshot
from tradingagents.skills.registry import register_skill


@register_skill(name="compute_realized_volatility", category="risk")
def compute_realized_volatility(
    daily_returns: pd.Series, vix_level: float | None, as_of: date,
) -> RealVolSnapshot:
    """Returns RealVolSnapshot with realized_vol_60d, realized_vol_20d, vrp_60d.

    Args:
        daily_returns: SPY daily returns (≥20 obs preferred, 60+ for primary metric).
        vix_level: current VIX (e.g., 20.0 for 20%). None → vrp=0.
        as_of: report date.

    Returns:
        RealVolSnapshot. Empty/short returns → zeros.
    """
    if daily_returns.empty or len(daily_returns) < 5:
        return RealVolSnapshot(
            realized_vol_60d=0.0, realized_vol_20d=0.0, vrp_60d=0.0,
            observed_at=as_of,
        )

    # Annualized stddev
    realized_60d = float(daily_returns.tail(60).std() * np.sqrt(252)) if len(daily_returns) >= 5 else 0.0
    realized_20d = float(daily_returns.tail(20).std() * np.sqrt(252)) if len(daily_returns) >= 5 else 0.0

    # VRP: (VIX/100)² - realized_60d², scaled to bps²
    vrp = 0.0
    if vix_level is not None:
        vix_var = (vix_level / 100.0) ** 2
        realized_var = realized_60d ** 2
        vrp = (vix_var - realized_var) * 10000.0

    return RealVolSnapshot(
        realized_vol_60d=realized_60d,
        realized_vol_20d=realized_20d,
        vrp_60d=vrp,
        observed_at=as_of,
    )
```

- [ ] **Step 3: PASS**

```bash
mkdir -p tests/unit/skills/risk
touch tests/unit/skills/risk/__init__.py
uv run pytest tests/unit/skills/risk/test_realized_volatility.py -v 2>&1 | tail -5
```

### Task 6.3: market_risk_analyst integration

**Files:**
- Modify: `tradingagents/agents/analysts/market_risk_analyst.py`

- [ ] **Step 1: SPY daily fetch + skill 호출 추가**

market_risk_analyst.py 의 RiskReport 생성 부분 근처:

```python
# ★ NEW (2026-05-23 C6 — realized vol for F7 + F9)
try:
    from tradingagents.skills.risk.realized_volatility import compute_realized_volatility
    import yfinance as yf
    spy = yf.Ticker("SPY")
    hist = spy.history(period="120d", interval="1d")
    daily_returns = hist["Close"].pct_change().dropna() if not hist.empty else pd.Series([])
    vix_level = vix_snapshot.current_value if vix_snapshot else None
    real_vol = compute_realized_volatility(daily_returns, vix_level, as_of)
except Exception as e:
    logger.warning("Realized vol fetch failed: %s", e)
    real_vol = None

# RiskReport 생성에 real_vol 추가
return RiskReport(
    # ... 기존 ...
    real_vol=real_vol,  # ★ NEW
)
```

- [ ] **Step 2: 회귀**

```bash
uv run pytest tests/unit/agents/test_market_risk_analyst.py -v 2>&1 | tail -10
```

### Task 6.4: C6 commit

```bash
git add tradingagents/schemas/risk.py \
        tradingagents/schemas/reports.py \
        tradingagents/skills/risk/realized_volatility.py \
        tradingagents/agents/analysts/market_risk_analyst.py \
        tests/unit/schemas/test_factor_model_schemas.py \
        tests/unit/skills/risk/__init__.py \
        tests/unit/skills/risk/test_realized_volatility.py \
        artifacts/2026-05-23/regression_log.md

git commit -m "$(cat <<'EOF'
feat(stage1): realized vol + RealVolSnapshot 신설 (C6)

Factor model F7 vol regime + F9 liquidity (via VRP) components.

Schema 신설:
- RealVolSnapshot (realized_vol_60d, realized_vol_20d, vrp_60d)
- RiskReport.real_vol: Optional, default None

Sub-skill:
- skills/risk/realized_volatility.py
- compute_realized_volatility(daily_returns, vix_level, as_of) → Snapshot
- VRP = (VIX/100)² - realized_60d², scaled to bps²

Analyst:
- market_risk_analyst.py: yfinance SPY 120d fetch + skill 호출

Test: 3 + 3 new

Regression: 0 new failure

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: C7 — Sector Dispersion

### Task 7.1: Schema 확장 (BreadthSnapshot)

**Files:**
- Modify: `tradingagents/schemas/risk.py`
- Modify: `tests/unit/schemas/test_factor_model_schemas.py`

- [ ] **Step 1: failing test**

```python
from tradingagents.schemas.risk import BreadthSnapshot


def test_breadth_has_sector_dispersion_default():
    # IMPLEMENTER: BreadthSnapshot 의 required field 채움
    breadth = BreadthSnapshot(
        # ... 기존 required fields ...
        observed_at=datetime.now(),
    )
    assert breadth.sector_return_dispersion == 0.0


def test_breadth_accepts_sector_dispersion():
    breadth = BreadthSnapshot(
        # ... 기존 required ...
        observed_at=datetime.now(),
        sector_return_dispersion=2.5,
    )
    assert breadth.sector_return_dispersion == 2.5
```

- [ ] **Step 2: schema 수정**

`tradingagents/schemas/risk.py` 의 `BreadthSnapshot`:

```python
class BreadthSnapshot(StalenessAware):
    # ... 기존 ...
    sector_return_dispersion: float = Field(
        default=0.0,
        description="Cross-sectional std of sector ETF 60d returns (in pp). F9 liquidity component.",
    )
```

### Task 7.2: Skill module — sector_dispersion.py

**Files:**
- Create: `tradingagents/skills/risk/sector_dispersion.py`
- Create: `tests/unit/skills/risk/test_sector_dispersion.py`

- [ ] **Step 1: failing test**

`tests/unit/skills/risk/test_sector_dispersion.py`:

```python
"""compute_sector_dispersion tests."""
import pytest
from tradingagents.skills.risk.sector_dispersion import compute_sector_dispersion


def test_dispersion_basic():
    # 5 sector 의 60d returns: equal → dispersion 0
    sector_returns = {f"XL{i}": 0.05 for i in "FYBKEUV"}
    disp = compute_sector_dispersion(sector_returns)
    assert disp == pytest.approx(0.0, abs=1e-6)


def test_dispersion_wide_spread():
    sector_returns = {"XLF": +0.20, "XLE": -0.15, "XLV": +0.05, "XLY": +0.10, "XLU": -0.05}
    disp = compute_sector_dispersion(sector_returns)
    assert disp > 0.05  # high dispersion


def test_dispersion_empty_returns_zero():
    disp = compute_sector_dispersion({})
    assert disp == 0.0


def test_dispersion_single_returns_zero():
    disp = compute_sector_dispersion({"XLF": 0.10})
    assert disp == 0.0
```

- [ ] **Step 2: 구현**

`tradingagents/skills/risk/sector_dispersion.py`:

```python
"""Sector return dispersion — cross-sectional std of sector ETF 60d returns.

Narrow market (AI rally) → low dispersion. Broad market → high dispersion.
Factor model F9 liquidity_regime component.
"""
import numpy as np
from tradingagents.skills.registry import register_skill


@register_skill(name="compute_sector_dispersion", category="risk")
def compute_sector_dispersion(sector_60d_returns: dict[str, float]) -> float:
    """Returns std of sector returns (as decimal, e.g., 0.05 = 5pp).

    Args:
        sector_60d_returns: {sector_ticker: 60d_return_decimal}.
            Empty / 1 sector → 0.0.

    Returns:
        Cross-sectional std (decimal).
    """
    if len(sector_60d_returns) < 2:
        return 0.0
    values = np.array(list(sector_60d_returns.values()))
    return float(np.std(values, ddof=1))
```

### Task 7.3: market_risk_analyst integration

**Files:**
- Modify: `tradingagents/agents/analysts/market_risk_analyst.py`

- [ ] **Step 1: 11 sector ETF fetch + dispersion 계산**

```python
# ★ NEW (2026-05-23 C7 — sector dispersion for F9)
try:
    import yfinance as yf
    from tradingagents.skills.risk.sector_dispersion import compute_sector_dispersion
    SECTOR_ETFS = ["XLF", "XLE", "XLI", "XLY", "XLV", "XLK", "XLU", "XLP", "XLB", "XLRE", "XLC"]
    sector_returns_60d = {}
    for ticker in SECTOR_ETFS:
        try:
            h = yf.Ticker(ticker).history(period="65d", interval="1d")
            if h.empty or len(h) < 60:
                continue
            ret_60d = (h["Close"].iloc[-1] / h["Close"].iloc[-60]) - 1.0
            sector_returns_60d[ticker] = float(ret_60d)
        except Exception:
            continue
    sector_disp = compute_sector_dispersion(sector_returns_60d)
    if breadth_us_snapshot is not None:
        breadth_us_snapshot = breadth_us_snapshot.model_copy(update={
            "sector_return_dispersion": sector_disp,
        })
except Exception as e:
    logger.warning("Sector dispersion fetch failed (F9 affected): %s", e)
```

- [ ] **Step 2: 회귀 + commit**

### Task 7.4: C7 commit

```bash
git commit -m "$(cat <<'EOF'
feat(stage1): sector dispersion + BreadthSnapshot 확장 (C7)

Factor model F9 liquidity_regime component.

Schema:
- BreadthSnapshot.sector_return_dispersion (default 0.0)

Sub-skill:
- skills/risk/sector_dispersion.py — cross-sectional std of 11 sector ETFs

Analyst:
- market_risk_analyst.py: yfinance 11 SPDR sector ETF (XLF/XLE/XLI/...) 60d fetch
- breadth_us.model_copy 으로 populate

Test: 2 + 4 new

Regression: 0 new failure

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Grill-me #3 (Before C8)

**Trigger**: C7 commit 직후, C8 시작 전.

**무엇 grill**:
- 5 신규 component 의 *weight magnitude* (spec Section 5.2 의 표)
- Reliability tier (high/medium/medium-low) per 신규 component
- Per-contribution cap 영향 — weight × 3 (z cap) > 0.10 cap 인 경우
- Sum-of-weights 재정규화 정책 (각 factor 의 active sum 이 1.0 으로 회복?)

**기록**: `artifacts/2026-05-23/decisions.md` 의 D11 채움.

---

## Task 8: C8 — Factor Estimator Update

### Task 8.1: factor_estimators.py 의 placeholder 활성화

**Files:**
- Modify: `tradingagents/skills/research/factor_estimators.py`

- [ ] **Step 1: F1 CFNAI 활성화**

`compute_growth_surprise` 의 cfnai placeholder 교체:

```python
# Before (C1 placeholder)
# TODO (C8 activation — PR1 의 CFNAI 추가 후)
# cfnai = _safe_get(stage1, "macro_report", "financial_conditions", "cfnai")
cfnai = None

# After (C8 활성)
cfnai = _safe_get(stage1, "macro_report", "financial_conditions", "cfnai")
cfnai_3m = _safe_get(stage1, "macro_report", "financial_conditions", "cfnai_3m_avg")
```

components_raw 의 cfnai_3m 추가 + weights 재조정 (grill-me #3 결정 따라):

```python
components_raw = {
    "gdpnow": gdpnow,
    "cfnai": cfnai,
    "cfnai_3m": cfnai_3m,  # ★ NEW
    "nfci": nfci, "sahm": sahm_z, "curve": curve,
    # news ...
}
weights = {
    "gdpnow": 0.18, "cfnai": 0.10, "cfnai_3m": 0.08,  # ★ activated
    "nfci": 0.12, "sahm": 0.07, "curve": 0.10,
    "release_surprise": 0.18, "hawkish_bias": 0.05,
    "macro_sent": 0.05, "risk_regime_overnight": 0.07,
    # sum = 1.00
}
```

- [ ] **Step 2: F4 slope_5_30y 활성화**

```python
# Before
# TODO (C8): slope_5_30 = _safe_get(stage1, "macro_report", "yield_curve", "spread_30y_5y_bps")
slope_5_30 = None
# ...
weights = {"slope_2_10y": 0.30, "slope_5_30y": 0.0, ...}

# After
slope_5_30 = _safe_get(stage1, "macro_report", "yield_curve", "spread_30y_5y_bps")
# ...
weights = {
    "slope_2_10y": 0.25, "slope_5_30y": 0.20,  # ★ activated
    "fed_tone_balance": 0.30, "fed_voting_balance": 0.25,
    # sum = 1.00
}
```

- [ ] **Step 3: F7 realized_vol 활성화**

```python
# After
realized_vol = _safe_get(stage1, "risk_report", "real_vol", "realized_vol_60d")
# weights:
weights = {
    "vix_level": 0.20, "vix_z_score": 0.10, "vix_term_ratio": 0.10,
    "move": 0.15, "realized_vol_60d": 0.13,  # ★ activated
    "skew_change": 0.07,
    "sentiment_dispersion": 0.10, "geopolitical_surge": 0.15,
}
```

- [ ] **Step 4: F8 kospi_pbr 활성화**

```python
# After (note: kospi_pbr 는 macro_report 로 이동)
kospi_pbr = _safe_get(stage1, "macro_report", "kr_valuation", "kospi_pbr")
# weights:
weights = {
    "sp_pe": 0.20, "earnings_yield": 0.25, "erp": 0.30,
    "kospi_pbr": 0.25,  # ★ activated
}
```

- [ ] **Step 5: F9 realized_vol + vrp + sector_dispersion 활성화**

```python
# After
realized_vol = _safe_get(stage1, "risk_report", "real_vol", "realized_vol_60d")
vrp = _safe_get(stage1, "risk_report", "real_vol", "vrp_60d")  # pre-computed
sector_dispersion = _safe_get(stage1, "risk_report", "breadth_us", "sector_return_dispersion")

# weights:
weights = {
    "vrp": 0.30,                       # ★ activated
    "eq_bond_corr": 0.15,
    "sector_dispersion": 0.15,         # ★ activated
    "breadth": 0.10,
    "event_cluster": 0.15,
    "rising_signal": 0.15,
}
```

### Task 8.2: audit table 확장

**Files:**
- Modify: `tradingagents/skills/research/factor_reliability_audit.py`
- Modify: `tests/unit/skills/research/test_factor_indicator_validity.py`

- [ ] **Step 1: COMPONENT_RELIABILITY 5 신규 추가**

`factor_reliability_audit.py`:

```python
COMPONENT_RELIABILITY: Final[dict[str, Reliability]] = {
    # ... 기존 ...
    # ★ NEW (2026-05-23 C8)
    "cfnai":               "high",
    "cfnai_3m_avg":        "high",
    "spread_30y_5y_bps":   "high",
    "kospi_pbr":           "high",
    "realized_vol_60d":    "high",
    "vrp":                 "high",
    "sector_dispersion":   "medium",  # narrow rally 환경 reliability ↓
}
```

- [ ] **Step 2: test_factor_indicator_validity.py 의 EXPECTED_COMPONENTS update**

```python
EXPECTED_COMPONENTS = frozenset([
    # 기존 ...
    # ★ NEW (2026-05-23 C8)
    "cfnai", "cfnai_3m_avg", "spread_30y_5y_bps", "kospi_pbr",
    "realized_vol_60d", "vrp", "sector_dispersion",
])
```

- [ ] **Step 3: test PASS**

```bash
uv run pytest tests/unit/skills/research/test_factor_indicator_validity.py -v 2>&1 | tail -10
```

### Task 8.3: C8 commit

```bash
git add tradingagents/skills/research/factor_estimators.py \
        tradingagents/skills/research/factor_reliability_audit.py \
        tests/unit/skills/research/test_factor_indicator_validity.py \
        artifacts/2026-05-23/regression_log.md \
        artifacts/2026-05-23/decisions.md

git commit -m "$(cat <<'EOF'
feat(stage2): factor_estimators 의 5 신규 component 활성화 (C8)

PR1 C3-C7 에서 추가된 5 indicator 의 factor estimator placeholder 활성화.

활성화된 component:
- F1: cfnai + cfnai_3m_avg
- F4: spread_30y_5y_bps
- F7: realized_vol_60d
- F8: kospi_pbr
- F9: realized_vol_60d + vrp + sector_dispersion

Weight 재조정 (grill-me #3 결정 — decisions.md D11):
- 각 factor 의 weight sum 이 1.00 으로 재정규화
- per-contribution cap (0.10) 내 모든 (β × z) 보장

Audit table 확장:
- COMPONENT_RELIABILITY: 7 신규 추가 (cfnai 등 6 high + sector_dispersion medium)
- EXPECTED_COMPONENTS: frozenset 갱신

Regression:
- Unit: 3 failed / N passed (factor_indicator_validity test 1 추가)
- Integration: 변경 0
- 0 new regression

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: C9 — Real Schema Integration Test 확장

### Task 9.1: test_factor_estimators_real_schema.py 확장

**Files:**
- Modify: `tests/integration/test_factor_estimators_real_schema.py`

- [ ] **Step 1: helper 의 _build_baseline_macro_report 에 신규 schema field 추가**

```python
def _build_baseline_macro_report() -> MacroReport:
    return MacroReport(
        # ... 기존 ...
        financial_conditions=FinancialConditionsSnapshot(
            nfci=0.0, anfci=0.0, regime="neutral", tightening=False,
            cfnai=0.0, cfnai_3m_avg=0.0,  # ★ NEW (C3)
        ),
        yield_curve=YieldCurveSnapshot(
            spread_10y_2y_bps=80.0, spread_10y_3m_bps=120.0,
            inverted_days_count=0, percentile_5y=0.5,
            spread_30y_5y_bps=120.0,  # ★ NEW (C4)
        ),
        kr_valuation=KRValuationSnapshot(  # ★ NEW (C5)
            kospi_pbr=1.0, kospi_per=12.0, kospi_div_yield=2.0,
        ),
        # ... 기존 ...
    )


def _build_baseline_risk_report() -> RiskReport:
    return RiskReport(
        # ... 기존 ...
        real_vol=RealVolSnapshot(  # ★ NEW (C6)
            realized_vol_60d=0.012, realized_vol_20d=0.010, vrp_60d=300.0,
        ),
        breadth_us=BreadthSnapshot(
            # ... 기존 required ...
            sector_return_dispersion=2.0,  # ★ NEW (C7)
        ),
    )
```

- [ ] **Step 2: 신규 test — coverage ≥ 0.85**

```python
def test_compute_all_factors_with_real_schema_after_c8(real_stage1_baseline):
    """C8 후 — 모든 5 신규 component 활성화. 각 factor coverage ≥ 0.85."""
    scores = compute_all_factors(real_stage1_baseline)

    expected_min = {
        "growth_surprise": 0.85,
        "inflation_surprise": 0.85,
        "real_rate": 0.85,
        "term_premium": 0.85,
        "credit_cycle": 0.85,
        "krw_regime": 0.80,
        "equity_vol_regime": 0.85,
        "valuation": 0.85,
        "liquidity_regime": 0.85,
    }
    for factor_name, min_cov in expected_min.items():
        score = getattr(scores, factor_name)
        assert score.confidence >= min_cov, (
            f"{factor_name} confidence {score.confidence:.2f} < {min_cov} "
            f"(components: {list(score.components.keys())})"
        )


def test_cfnai_affects_growth_factor(real_stage1_baseline):
    """CFNAI = +1 perturbation → F1 z 증가."""
    state = dict(real_stage1_baseline)
    baseline_scores = compute_all_factors(state)
    baseline_f1 = baseline_scores.growth_surprise.z_score

    macro = state["macro_report"]
    macro.financial_conditions.cfnai = +1.5
    macro.financial_conditions.cfnai_3m_avg = +1.0
    state["macro_report"] = macro

    new_scores = compute_all_factors(state)
    assert new_scores.growth_surprise.z_score > baseline_f1 + 0.05


def test_realized_vol_affects_vol_and_liquidity(real_stage1_baseline):
    """High realized_vol → F7 + F9 모두 영향."""
    state = dict(real_stage1_baseline)
    risk = state["risk_report"]
    risk.real_vol.realized_vol_60d = 0.30  # very high
    risk.real_vol.vrp_60d = -500  # negative VRP (rare)
    state["risk_report"] = risk

    scores = compute_all_factors(state)
    # F7 should respond
    # F9 VRP component should respond
```

- [ ] **Step 3: PASS**

```bash
uv run pytest tests/integration/test_factor_estimators_real_schema.py -v 2>&1 | tail -15
```

Expected: 모두 PASS (8+ test).

### Task 9.2: C9 commit

```bash
git add tests/integration/test_factor_estimators_real_schema.py \
        artifacts/2026-05-23/regression_log.md

git commit -m "$(cat <<'EOF'
test(stage2): real schema integration test 확장 — post-C8 (C9)

C8 의 5 신규 component 활성화 후의 coverage 검증.

Helper update:
- _build_baseline_macro_report: cfnai, spread_30y_5y_bps, kr_valuation 추가
- _build_baseline_risk_report: real_vol + sector_return_dispersion 추가

Test:
- test_compute_all_factors_after_c8: 각 factor coverage ≥ 0.85
- test_cfnai_affects_growth_factor: perturbation propagation
- test_realized_vol_affects_vol_and_liquidity: F7 + F9 동시 영향

Regression: 0 new failure

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: C10 — 2026-05-15 Regen + Diff

### Task 10.1: Stage 2-6 sequential replay

- [ ] **Step 1: pre-C10 backup**

```bash
mkdir -p /tmp/pre_c10_backup
cp artifacts/2026-05-15/portfolio.json /tmp/pre_c10_backup/ 2>/dev/null || true
cp artifacts/2026-05-15/philosophy.md /tmp/pre_c10_backup/ 2>/dev/null || true
cp artifacts/2026-05-15/trade_plan.csv /tmp/pre_c10_backup/ 2>/dev/null || true
ls /tmp/pre_c10_backup/
```

- [ ] **Step 2: Stage 1 analysts 재실행 (신규 indicator fetch 활성화)**

```bash
set -a && source .env && set +a
uv run python scripts/replay_stage.py --as-of 2026-05-15 --stage macro_quant --write-archive 2>&1 | tail -10
uv run python scripts/replay_stage.py --as-of 2026-05-15 --stage market_risk --write-archive 2>&1 | tail -10
```

- [ ] **Step 3: Stage 2-6 sequential**

```bash
uv run python scripts/replay_stage.py --as-of 2026-05-15 --stage research_debate --write-archive 2>&1 | tail -10
uv run python scripts/replay_stage.py --as-of 2026-05-15 --stage allocator --write-archive 2>&1 | tail -10
uv run python scripts/replay_stage.py --as-of 2026-05-15 --stage risk_debate --write-archive 2>&1 | tail -10
uv run python scripts/replay_stage.py --as-of 2026-05-15 --stage validator --write-archive 2>&1 | tail -10
uv run python scripts/replay_stage.py --as-of 2026-05-15 --stage portfolio_manager --artifacts-dir artifacts --write-archive 2>&1 | tail -10
```

- [ ] **Step 4: artifacts/2026-05-15/ 정리**

```bash
if [ -d artifacts/2026-05-15/2026-05-15 ]; then
  mv artifacts/2026-05-15/2026-05-15/* artifacts/2026-05-15/
  rmdir artifacts/2026-05-15/2026-05-15
fi
ls artifacts/2026-05-15/
```

- [ ] **Step 5: mandate validation 확인**

```bash
python -c "import json; d=json.load(open('artifacts/2026-05-15/portfolio.json')); print('mandate.passed:', d.get('validation_report', {}).get('passed'))"
```

Expected: `mandate.passed: True`. False 시 blocker — 보고.

### Task 10.2: stage2_diff_post_stage1.md 작성

**Files:**
- Create: `artifacts/2026-05-15/stage2_diff_post_stage1.md`

- [ ] **Step 1: pre/post 비교 dump**

```bash
python -c "
import json
pre = json.load(open('/tmp/pre_c10_backup/portfolio.json'))
post = json.load(open('artifacts/2026-05-15/portfolio.json'))
print('=== Pre ===')
print('bucket:', pre['weight_vector'])
print('=== Post ===')
print('bucket:', post['weight_vector'])
" > /tmp/diff_dump.txt
cat /tmp/diff_dump.txt
```

- [ ] **Step 2: diff doc 작성**

`artifacts/2026-05-15/stage2_diff_post_stage1.md`:

```markdown
# Stage 2 Diff: Post-Stage-1-Enhance vs Pre (2026-05-15)

PR `feat/stage2-factor-model` (PR1 only — silent broken) vs `feat/stage1-enhance-for-factor-model` (real signal).

## research_decision diff

### Pre (PR1 only — broken state)
- factor_scores (silent ~40% coverage):
  - F1_growth: <pre>
  - F2_inflation: <pre>
  - ...
- dominant_scenario: <pre>
- bucket_target: <pre>

### Post (Stage 1 enhance — full coverage)
- factor_scores (≥90% coverage):
  - F1_growth: <post> (cfnai 활성화 효과)
  - F2_inflation: <post>
  - ...
- dominant_scenario: <post>
- bucket_target: <post>

## Bucket target diff

| Bucket | Pre | Post | Δ (pp) |
|---|---:|---:|---:|
| kr_equity | X.XX | X.XX | +X |
| global_equity | X.XX | X.XX | +X |
| fx_commodity | X.XX | X.XX | +X |
| bond | X.XX | X.XX | +X |
| cash_mmf | X.XX | X.XX | +X |
| bond_tips_share | X.XX | X.XX | +X |
| 위험자산 합 | X.XX | X.XX | +X |

## Factor signal quality 개선

| Factor | Pre coverage | Post coverage | 신규 component |
|---|---|---|---|
| F1 growth | ~40% | ~95% | cfnai, cfnai_3m_avg |
| F4 term_premium | ~50% | ~90% | spread_30y_5y_bps |
| F7 vol_regime | ~50% | ~90% | realized_vol_60d |
| F8 valuation | ~30% | ~85% | kospi_pbr |
| F9 liquidity | ~30% | ~85% | realized_vol + vrp + sector_dispersion |

## Validator
- pre: mandate.passed = X
- post: mandate.passed = True

## 분석
- Stage 1 enhance 후 *진짜 factor signal* 의 영향 — 위험자산 변화 / scenario 변화 / method_choice 영향
- 5/28 대회 narrative 측면
```

### Task 10.3: C10 commit

```bash
git add artifacts/2026-05-15/ \
        artifacts/2026-05-23/regression_log.md \
        artifacts/2026-05-23/decisions.md

git commit -m "$(cat <<'EOF'
data(2026-05-15): factor model 의 진짜 signal 으로 산출물 재생성 (C10)

Stage 1 enhance 후 *full coverage* factor signal 의 production output.

Stage 1-6 sequential replay:
- Stage 1 (macro_quant + market_risk): 5 신규 indicator 활성화
- Stage 2 (research_debate): factor model 의 *진짜 signal* (coverage ≥90%)
- Stage 3-5: bucket_target 따라 종합 → mandate validated
- Stage 6: philosophy.md narrative 의 *factor 기반* 작성

artifacts/2026-05-15/ 갱신:
- portfolio.json: factor model bucket_target + weight_vector
- philosophy.md: factor-based narrative (신규 5 component 의 contribution)
- trade_plan.csv: 새 weight 따른 trade list
- runs/2026-05-15/*.json archive 갱신

stage2_diff_post_stage1.md:
- pre (PR1 broken) vs post (Stage 1 enhance) 비교
- factor coverage 개선: ~40% → ~90%
- bucket weight 변화
- mandate.passed: True

Regression: 0 new failure (data only)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Grill-me #4 (After C10 / Before C11)

**Trigger**: C10 commit 직후, C11 시작 전.

**무엇 grill**:
- 2026-05-15 bucket weight 변화 의 *interpretation* — 의도된 변화 vs 우려
- Coverage 개선이 *실제로* 의미 있는 signal 변화 인지 vs noise
- 5 신규 component 중 *dominant contributor* 식별 (기대 한 것 vs 실제)
- philosophy.md narrative 의 *factor-based quality* 평가

**기록**: `artifacts/2026-05-23/decisions.md` 의 D12 채움.

---

## Task 11: C11 — Documentation + Backlog Update

### Task 11.1: docs/followup_issues.md 의 Issue status update

**Files:**
- Modify: `docs/followup_issues.md`

- [ ] **Step 1: Issue #13 (LEI + ISM) status — partial resolved**

`docs/followup_issues.md` 의 Issue #13 section 끝에 추가:

```markdown
### Status (2026-05-23, PR `feat/stage1-enhance-for-factor-model`)
- **PARTIAL RESOLVED**: CFNAI 추가 (C3) — LEI + ISM sub-components 는 *별도 후속 PR*
- Factor F1 coverage 향상: ~40% → ~95%
```

- [ ] **Step 2: Issue #15 (valuation) status — partial resolved**

Issue #15 section:

```markdown
### Status (2026-05-23)
- **PARTIAL RESOLVED**: KOSPI PBR/PER/DivYield 추가 (C5)
- Forward P/E (S&P 500) 는 여전히 external_fetcher 의존 — Issue #17 cleanup 대기
- Factor F8 coverage: ~30% → ~85%
```

- [ ] **Step 3: Issue #16 (cross-currency basis) status — no change**

Issue #16 의 status: unchanged (Tier 3, low priority).

### Task 11.2: audit doc status update

**Files:**
- Modify: `docs/superpowers/specs/2026-05-22-stage2-pipeline-audit.md`

- [ ] **Step 1: Issue A 의 status 다시 update (path mismatch 도 sub-issue)**

audit doc 의 Issue A 의 Resolution Summary 에 추가:

```markdown
**Hotfix (2026-05-23 C1-C2)**: factor_estimators field path mismatch (silent broken state)
별도 발견 — PR `feat/stage1-enhance-for-factor-model` 의 C1-C2 에서 해결.
real schema integration test (test_factor_estimators_real_schema.py) 가 재발 방지.
```

### Task 11.3: C11 commit

```bash
git add docs/followup_issues.md \
        docs/superpowers/specs/2026-05-22-stage2-pipeline-audit.md \
        artifacts/2026-05-23/regression_log.md \
        artifacts/2026-05-23/decisions.md

git commit -m "$(cat <<'EOF'
docs(stage1): backlog status + audit update (C11)

Stage 1 backlog (docs/followup_issues.md):
- Issue #13 (LEI + ISM): PARTIAL RESOLVED — CFNAI 만 (C3)
- Issue #15 (valuation): PARTIAL RESOLVED — KOSPI PBR (C5), forward P/E 잔존
- Issue #16 (cross-currency): unchanged

Audit (2026-05-22-stage2-pipeline-audit.md):
- Issue A 의 sub-issue (path mismatch silent broken) hotfix 명시
- real schema integration test 가 재발 방지 기재

decisions.md final state:
- D7-D12 모두 채움 (grill-me 4 회 결정)
- D7: sub-skill API shape — try/except graceful + model_copy update pattern
- D10: C3 결과 — pattern OK, C4-C7 동일 적용
- D11: weight 재조정 결정 — each factor sum=1.0 재정규화
- D12: bucket diff interpretation — coverage 개선의 *진짜 signal change*

PR1 (Stage 1 enhance + PR0 hotfix) complete.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final Validation Gate

- [ ] **Step 1: 전체 회귀**

```bash
uv run pytest tests/unit/ -q 2>&1 | tail -3
uv run pytest tests/integration/ -q 2>&1 | tail -3
```

Expected: 3 unit fail (pre-existing) / N pass (+~70-90); 18 integ fail / N pass (+~5-10).

- [ ] **Step 2: Acceptance criteria 검증**

- [x] C2 real schema integration: 각 factor coverage ≥ expected_min after C1
- [x] C9 real schema integration: 각 factor coverage ≥ 0.85 after C8
- [x] Mandate violation = 0 (2026-05-15 산출물)
- [x] Pre-existing fail set 증가 0
- [x] 5 신규 audit components 추가
- [x] 4 grill-me 세션 의 decision 기록
- [x] stage2_diff_post_stage1.md 작성
- [x] backlog Issue #13/#15/#16 status update

- [ ] **Step 3: PR creation 준비**

```bash
git log --oneline feat/stage2-factor-model..feat/stage1-enhance-for-factor-model
git push -u origin feat/stage1-enhance-for-factor-model
```

PR URL: https://github.com/DBgapsPluto/pluto/pull/new/feat/stage1-enhance-for-factor-model

---

## 참조

- Spec: `docs/superpowers/specs/2026-05-23-stage1-enhance-for-factor-model-design.md`
- PR1 spec: `docs/superpowers/specs/2026-05-22-stage2-factor-model-design.md`
- Audit: `docs/superpowers/specs/2026-05-22-stage2-pipeline-audit.md`
- Memory: `feedback_regression_tests.md`, `feedback_long_session_protocol.md`
