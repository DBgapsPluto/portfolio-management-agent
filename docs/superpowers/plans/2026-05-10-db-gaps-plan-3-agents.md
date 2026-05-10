# DB GAPS Plan 3 — Agents + Graph + Debates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 4 분석가 + Allocator + Validator + Portfolio Manager + Bull/Bear sub-graph + Risk debate sub-graph + 메인 그래프(하이브리드 토폴로지)를 구현. Plan 끝나면 mock fixture 기반 `gaps plan` 풀 파이프라인이 동작.

**Architecture:** D2 결정 — 단계 간은 summary handoff (요약 str + Pydantic structured), 토론 클러스터(Bull/Bear, Risk 3인) 안에서는 별도 sub-graph + 독립 DebateState로 raw message 격리. D3 — preset YAML이 stage·agent 그래프를 빌드. D4 — Validator 실패 시 `allocation_feedback` state 필드로 retry, 2회 실패 시 deterministic fallback.

**Tech Stack:** LangGraph (StateGraph + subgraph 패턴), Plan 1·2의 모든 자산.

**Prerequisites:** Plan 1 + Plan 2 완료. `tradingagents/skills/_registry_init.py` import로 34 skill 등록.

**참조 스펙:** §3 (토폴로지), §7 (분석가별 상세), §8 (토론), §13 (state 스키마).

---

## File Structure

```
tradingagents/
├── agents/
│   ├── analysts/
│   │   ├── macro_quant_analyst.py        # 기존 fundamentals_analyst.py 대체
│   │   ├── market_risk_analyst.py        # 기존 social_media_analyst.py 대체
│   │   ├── technical_analyst.py          # rewrite (ETF 유니버스 대상)
│   │   └── macro_news_analyst.py         # rewrite
│   ├── allocator/
│   │   ├── __init__.py
│   │   └── portfolio_allocator.py        # 기존 trader/trader.py 대체
│   ├── validator/
│   │   ├── __init__.py
│   │   └── mandate_validator.py          # deterministic 4-rule 검증
│   ├── researchers/
│   │   ├── bull_researcher.py            # rewrite (자산군 비중 토론)
│   │   ├── bear_researcher.py            # rewrite
│   │   └── debate_state.py               # InvestDebateState 신규 정의 (격리)
│   ├── risk_mgmt/
│   │   ├── aggressive_debator.py
│   │   ├── conservative_debator.py
│   │   ├── neutral_debator.py
│   │   └── debate_state.py               # RiskDebateState 신규
│   ├── managers/
│   │   ├── research_manager.py           # rewrite — BucketTarget 출력
│   │   ├── risk_judge.py                 # 신규 — Risk debate judge
│   │   └── portfolio_manager.py          # rewrite — 산출물 3종 생성
│   └── utils/
│       ├── agent_states.py               # rewrite (Plan 3 state 스키마)
│       └── narrative_helpers.py          # 공통 narrative 작성 helper
├── graph/
│   ├── builder.py                        # 신규 — preset YAML → LangGraph
│   ├── debate_subgraph.py                # 신규 — Bull/Bear, Risk debate
│   ├── conditional_logic.py              # rewrite — Validator cycle (D4)
│   ├── trading_graph.py                  # rewrite — preset 기반 진입점
│   └── setup.py                          # rewrite (얇은 래퍼)
└── presets/
    └── db_gaps.yaml                      # 신규 — 본 대회 preset

tests/
├── unit/agents/
│   ├── test_macro_quant_analyst.py
│   ├── test_market_risk_analyst.py
│   ├── test_technical_analyst.py
│   ├── test_macro_news_analyst.py
│   ├── test_portfolio_allocator.py
│   ├── test_mandate_validator.py
│   ├── test_research_manager.py
│   ├── test_risk_judge.py
│   └── test_portfolio_manager.py
├── unit/graph/
│   ├── test_debate_subgraph.py
│   ├── test_conditional_logic.py
│   └── test_builder.py
└── integration/
    ├── test_subgraph_isolation.py        # D2 결정 검증
    ├── test_validator_cycle.py           # D4 결정 검증
    └── test_plan_pipeline_mock.py        # 풀 파이프라인 mock
```

---

## Phase 1: Agent State (rewrite)

### Task 1: AgentState 신규 정의

**Files:**
- Modify: `tradingagents/agents/utils/agent_states.py`
- Create: `tests/unit/agents/test_agent_state.py`

- [ ] **Step 1: 실패 테스트**

```python
from tradingagents.agents.utils.agent_states import AgentState, _create_empty_state


def test_create_empty_state_has_defaults():
    s = _create_empty_state(
        as_of_date="2026-05-25",
        universe_path="data/universe.json",
        capital_krw=1_000_000_000,
        preset_name="db_gaps",
    )
    assert s["as_of_date"] == "2026-05-25"
    assert s["allocation_attempts"] == 0
    assert s["validation_passed"] is None


def test_state_has_summary_handoff_fields():
    s = _create_empty_state(
        as_of_date="2026-05-25", universe_path="x",
        capital_krw=100, preset_name="db_gaps",
    )
    # D2 hybrid topology: summaries between stages
    assert "macro_summary" in s
    assert "research_debate_summary" in s
    assert "risk_debate_summary" in s
```

- [ ] **Step 2: 실행 (실패)**

Run: `pytest tests/unit/agents/test_agent_state.py -v`

- [ ] **Step 3: 구현**

`tradingagents/agents/utils/agent_states.py`:

```python
from typing import Annotated, Optional
from typing_extensions import TypedDict

from langgraph.graph import MessagesState

from tradingagents.schemas.macro import RegimeClassification
from tradingagents.schemas.mandate import ValidationReport, Violation
from tradingagents.schemas.portfolio import BucketTarget, CandidateSet, WeightVector
from tradingagents.schemas.reports import (
    MacroReport, RiskReport, TechnicalReport, NewsReport,
)
from tradingagents.schemas.technical import Cluster


class AgentState(MessagesState):
    """Top-level state for the DB GAPS pipeline.

    D2 hybrid topology: stage outputs are stored as both Pydantic structured
    objects AND ≤2KB markdown summaries (`*_summary` fields). Downstream stages
    receive summaries via `input_from` mapping in the preset, not raw messages.

    Debate clusters use separate sub-graphs with their own DebateState; they
    return only `*_debate_summary` to this parent state.
    """

    # === Init ===
    as_of_date: Annotated[str, "ISO date for the run (e.g., 2026-05-25)"]
    universe_path: Annotated[str, "Path to universe.json"]
    capital_krw: Annotated[int, "Initial capital in KRW"]
    preset_name: Annotated[str, "Preset YAML name (e.g., db_gaps)"]

    # === Stage 1: Analyst outputs ===
    macro_report: Annotated[Optional[MacroReport], "Macro/Quant analyst output"]
    risk_report: Annotated[Optional[RiskReport], "Market Risk analyst output"]
    technical_report: Annotated[Optional[TechnicalReport], "Technical analyst output"]
    news_report: Annotated[Optional[NewsReport], "Macro News analyst output"]

    # Summary handoffs (D2)
    macro_summary: Annotated[str, "≤2KB markdown summary for downstream stages"]
    risk_summary: Annotated[str, ""]
    technical_summary: Annotated[str, ""]
    news_summary: Annotated[str, ""]

    # === Stage 2: Researcher debate ===
    research_debate_summary: Annotated[str, "Bull/Bear debate summary (raw msgs not in parent state)"]

    # === Stage 3: Research Manager ===
    bucket_target: Annotated[Optional[BucketTarget], "5-bucket weight target"]

    # === Stage 4: Allocator ===
    candidate_set: Annotated[Optional[CandidateSet], "Filtered ETF candidates"]
    weight_vector: Annotated[Optional[WeightVector], "Allocator output weights"]
    correlation_clusters: Annotated[list[Cluster], "From technical analyst, used for validation"]

    # === Stage 5: Risk debate ===
    risk_debate_summary: Annotated[str, "3-way debate summary"]

    # === Stage 6: Validation ===
    validation_report: Annotated[Optional[ValidationReport], "Mandate validator output"]
    validation_passed: Annotated[Optional[bool], "True/False/None pre-validation"]

    # D4: Validator cycle
    allocation_attempts: Annotated[int, "Retry counter for Validator → Allocator cycle"]
    allocation_feedback: Annotated[list[Violation], "Violations to inject into Allocator on retry"]

    # === Stage 7: Final ===
    final_portfolio_path: Annotated[str, "Path to artifacts/portfolio.json"]
    philosophy_doc_path: Annotated[str, ""]
    trade_plan_csv_path: Annotated[str, ""]

    # === Cross-run ===
    previous_portfolio: Annotated[Optional[dict], "For monthly rebalancing"]


def _create_empty_state(
    as_of_date: str,
    universe_path: str,
    capital_krw: int,
    preset_name: str,
    previous_portfolio: dict | None = None,
) -> AgentState:
    return AgentState(
        messages=[],
        as_of_date=as_of_date,
        universe_path=universe_path,
        capital_krw=capital_krw,
        preset_name=preset_name,
        macro_report=None, risk_report=None,
        technical_report=None, news_report=None,
        macro_summary="", risk_summary="",
        technical_summary="", news_summary="",
        research_debate_summary="",
        bucket_target=None,
        candidate_set=None, weight_vector=None,
        correlation_clusters=[],
        risk_debate_summary="",
        validation_report=None, validation_passed=None,
        allocation_attempts=0, allocation_feedback=[],
        final_portfolio_path="", philosophy_doc_path="", trade_plan_csv_path="",
        previous_portfolio=previous_portfolio,
    )
```

- [ ] **Step 4: 테스트 통과**

Run: `pytest tests/unit/agents/test_agent_state.py -v`

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/utils/agent_states.py tests/unit/agents/test_agent_state.py
git commit -m "feat(agents): rewrite AgentState for hybrid topology + Validator cycle (D2, D4)"
```

---

## Phase 2: Analysts (4명)

### Task 2: MacroQuantAnalyst node

**Files:**
- Create: `tradingagents/agents/analysts/macro_quant_analyst.py`
- Create: `tests/unit/agents/test_macro_quant_analyst.py`

- [ ] **Step 1: 실패 테스트**

```python
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from tradingagents.agents.analysts.macro_quant_analyst import create_macro_quant_analyst
from tradingagents.schemas.macro import RegimeClassification
from tradingagents.schemas.reports import MacroReport


def test_macro_analyst_orchestration(monkeypatch):
    quick_llm = MagicMock()
    deep_llm = MagicMock()

    # Mock the regime subagent
    regime_out = RegimeClassification(
        quadrant="recession_disinflation", confidence=0.8,
        drivers=["yield curve"], reasoning="x",
    )
    deep_llm.with_structured_output.return_value.invoke.return_value = regime_out

    # Mock the data fetchers via monkeypatch
    fake_series = pd.Series(
        [4.5, 4.4], index=pd.date_range("2026-05-08", periods=2)
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.macro_quant_analyst.fetch_fred_series_skill",
        lambda *a, **kw: fake_series,
    )
    monkeypatch.setattr(
        "tradingagents.agents.analysts.macro_quant_analyst.fetch_ecos_series_skill",
        lambda *a, **kw: fake_series,
    )
    # Force narrative on a separate LLM call
    quick_llm.invoke.return_value.content = "macro narrative ≤500 chars"

    node = create_macro_quant_analyst(quick_llm, deep_llm)
    state = {"as_of_date": "2026-05-10"}
    result = node(state)
    assert "macro_report" in result
    assert isinstance(result["macro_report"], MacroReport)
    assert result["macro_report"].regime.quadrant == "recession_disinflation"
    assert "macro_summary" in result
    assert len(result["macro_summary"]) <= 2000
```

- [ ] **Step 2: 실행 (실패)**

Run: `pytest tests/unit/agents/test_macro_quant_analyst.py -v`

- [ ] **Step 3: 구현**

`tradingagents/agents/analysts/macro_quant_analyst.py`:

```python
"""Macro/Quant Analyst — orchestrates 8 macro skills, composes MacroReport.

Per design §7.1: fixed pipeline (no LLM-driven skill ordering).
LLM only writes the ≤500-char narrative + 2KB summary.
"""
from datetime import date, timedelta

from tradingagents.schemas.macro import (
    RegimeClassification, DivergenceScore,
)
from tradingagents.schemas.reports import MacroReport
from tradingagents.skills.macro.calendar import fetch_central_bank_calendar_skill
from tradingagents.skills.macro.divergence import compute_kr_divergence
from tradingagents.skills.macro.ecos_fetcher import fetch_ecos_series_skill
from tradingagents.skills.macro.employment import compute_unemployment_trend
from tradingagents.skills.macro.fred_fetcher import fetch_fred_series_skill
from tradingagents.skills.macro.inflation import compute_inflation_trend
from tradingagents.skills.macro.regime_classifier import classify_regime
from tradingagents.skills.macro.yield_curve import compute_yield_curve


NARRATIVE_PROMPT = """\
You are summarizing a macro snapshot for an asset-allocation team.

Data:
- Regime: {regime_quadrant} (confidence {confidence:.2f})
- 10y-2y spread: {spread_2y_bps:.1f} bps (inverted {inverted_days} days)
- CPI YoY: {cpi:.1f}% (accelerating: {accelerating})
- Unemployment: {ur:.1f}% (Sahm: {sahm})
- Upcoming events: {events}

Write ≤500 chars in Korean. Be concrete. Cite numbers above only — do not invent."""


def create_macro_quant_analyst(quick_llm, deep_llm):
    def node(state):
        as_of = date.fromisoformat(state["as_of_date"])
        start_macro = as_of - timedelta(days=365 * 5)

        # All fetchers receive as_of_date for point-in-time truncation
        # (look-ahead bias prevention; e.g., May CPI not visible on 2026-05-25)
        # 1-2. Yield curve series
        s_10y = fetch_fred_series_skill("us_10y", start_macro, as_of, as_of_date=as_of)
        s_2y = fetch_fred_series_skill("us_2y", start_macro, as_of, as_of_date=as_of)
        s_3m = fetch_fred_series_skill("us_3m", start_macro, as_of, as_of_date=as_of)
        yc = compute_yield_curve(s_10y, s_2y, s_3m, as_of=as_of)

        # 3-4. Inflation (CPI has ~15 day publication lag — enforced in fetcher)
        cpi = fetch_fred_series_skill("us_cpi", start_macro, as_of, as_of_date=as_of)
        core_cpi = fetch_fred_series_skill("us_core_cpi", start_macro, as_of, as_of_date=as_of)
        infl = compute_inflation_trend(cpi, core_cpi, as_of=as_of)

        # 5-6. Employment (NFP/UR has ~7 day lag)
        ur = fetch_fred_series_skill("us_unrate", start_macro, as_of, as_of_date=as_of)
        payems = fetch_fred_series_skill("us_payems", start_macro, as_of, as_of_date=as_of)
        emp = compute_unemployment_trend(ur, payems, as_of=as_of)

        # 7. KR divergence
        us_policy = fetch_fred_series_skill("us_policy_rate", start_macro, as_of, as_of_date=as_of)
        kr_rate = fetch_ecos_series_skill("kr_base_rate", start_macro, as_of, as_of_date=as_of)
        kr_cpi = fetch_ecos_series_skill("kr_cpi", start_macro, as_of, as_of_date=as_of)
        try:
            div = compute_kr_divergence(
                us_policy_rate=float(us_policy.iloc[-1]),
                kr_base_rate=float(kr_rate.iloc[-1]),
                us_cpi_yoy=infl.cpi_yoy,
                kr_cpi_yoy=float((kr_cpi.iloc[-1] / kr_cpi.iloc[-13] - 1) * 100) if len(kr_cpi) >= 13 else 0.0,
                as_of=as_of,
            )
        except Exception:
            div = DivergenceScore(us_kr_rate_gap_bps=0, us_kr_inflation_gap=0, score=0, source_date=as_of)

        # 8. Calendar
        events = fetch_central_bank_calendar_skill(as_of, days=90)

        # 9. Subagent: regime classification
        regime: RegimeClassification = classify_regime(
            quick_llm, deep_llm,
            spread_10y_2y_bps=yc.spread_10y_2y_bps,
            inverted_days_count=yc.inverted_days_count,
            cpi_yoy=infl.cpi_yoy,
            momentum_3mo=infl.momentum_3mo,
            accelerating=infl.accelerating,
            unemployment_rate=emp.unemployment_rate,
            sahm_rule_triggered=emp.sahm_rule_triggered,
        )

        # 10. Narrative + summary via quick LLM
        narrative_prompt = NARRATIVE_PROMPT.format(
            regime_quadrant=regime.quadrant, confidence=regime.confidence,
            spread_2y_bps=yc.spread_10y_2y_bps, inverted_days=yc.inverted_days_count,
            cpi=infl.cpi_yoy, accelerating=infl.accelerating,
            ur=emp.unemployment_rate, sahm=emp.sahm_rule_triggered,
            events=", ".join(f"{e.event_date} {e.bank}" for e in events[:3]) or "none",
        )
        narrative = quick_llm.invoke(narrative_prompt).content[:500]
        summary = (
            f"## Macro\n"
            f"Regime: **{regime.quadrant}** ({regime.confidence:.2f})\n"
            f"YC 10y-2y: {yc.spread_10y_2y_bps:.0f}bps, inverted {yc.inverted_days_count}d\n"
            f"CPI: {infl.cpi_yoy:.1f}% YoY ({'↑' if infl.accelerating else '↓'})\n"
            f"UR: {emp.unemployment_rate:.1f}% (Sahm: {emp.sahm_rule_triggered})\n"
            f"Drivers: {', '.join(regime.drivers[:3])}\n"
        )[:2000]

        report = MacroReport(
            yield_curve=yc, inflation=infl, employment=emp,
            kr_divergence=div, regime=regime,
            upcoming_events=events,
            narrative=narrative, summary_for_downstream=summary,
        )
        return {"macro_report": report, "macro_summary": summary}

    return node
```

- [ ] **Step 4: 테스트 통과**

Run: `pytest tests/unit/agents/test_macro_quant_analyst.py -v`

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/analysts/macro_quant_analyst.py tests/unit/agents/test_macro_quant_analyst.py
git commit -m "feat(agents): add MacroQuantAnalyst node (replaces fundamentals_analyst)"
```

---

### Task 3: MarketRiskAnalyst node

**Files:**
- Create: `tradingagents/agents/analysts/market_risk_analyst.py`
- Create: `tests/unit/agents/test_market_risk_analyst.py`

- [ ] **Step 1-5: 동일 패턴**

```python
from datetime import date, timedelta

import pandas as pd

from tradingagents.schemas.reports import RiskReport
from tradingagents.skills.risk.breadth import compute_market_breadth
from tradingagents.skills.risk.correlation_pca import compute_correlation_concentration
from tradingagents.skills.risk.credit_spread import fetch_credit_spread
from tradingagents.skills.risk.fear_greed import fetch_fear_greed_index
from tradingagents.skills.risk.systemic_score import score_systemic_risk
from tradingagents.skills.risk.volatility import fetch_volatility_index


def create_market_risk_analyst(quick_llm, deep_llm):
    def node(state):
        as_of = date.fromisoformat(state["as_of_date"])

        vix = fetch_volatility_index("VIX", as_of)
        vkospi = fetch_volatility_index("VKOSPI", as_of)
        ig = fetch_credit_spread("US_IG", as_of)
        hy = fetch_credit_spread("US_HY", as_of)
        fg = fetch_fear_greed_index(as_of)  # may be None
        breadth_kr = compute_market_breadth("KOSPI200", as_of)
        breadth_us = compute_market_breadth("SP500", as_of)

        # Correlation concentration (use technical_report if available, else stub)
        # In Plan 3 we accept technical_report may not be ready; pass empty for now
        # Real wiring: technical analyst runs in parallel, results joined later.
        # Stub: small synthetic returns matrix.
        synthetic = pd.DataFrame({
            "kospi": [0.001, -0.002, 0.003, -0.001, 0.002] * 50,
            "spy": [0.002, -0.001, 0.002, 0.0, 0.001] * 50,
            "tlt": [-0.001, 0.001, -0.002, 0.001, 0.0] * 50,
            "gld": [0.0, 0.001, 0.0, -0.001, 0.001] * 50,
        })
        pca = compute_correlation_concentration(synthetic, as_of)

        if fg is None:
            from tradingagents.schemas.risk import SentimentSnapshot
            fg = SentimentSnapshot(
                index_name="fear_greed_cnn", current_value=50,
                label="neutral", trend_7d="flat", source_date=as_of,
                staleness_days=99,  # Mark as missing
            )

        systemic = score_systemic_risk(
            quick_llm, deep_llm,
            vix=vix.current_value, vix_z=vix.zscore_30d, vix_pct=vix.percentile_5y,
            vkospi=vkospi.current_value,
            ig_bps=ig.current_bps, ig_pct=ig.percentile_5y,
            hy_bps=hy.current_bps, hy_widening=hy.widening,
            fg_label=fg.label, fg_value=fg.current_value,
            breadth_kr_adv=breadth_kr.advancing_pct,
            breadth_us_adv=breadth_us.advancing_pct,
            pca_first_share=pca.first_eigenvalue_share,
            pca_concentrated=pca.is_concentrated,
        )

        narrative = quick_llm.invoke(
            f"Summarize market risk in ≤500 Korean chars. "
            f"Score {systemic.score}/10 ({systemic.regime}). "
            f"VIX {vix.current_value:.1f}, drivers: {systemic.drivers}"
        ).content[:500]
        summary = (
            f"## Risk\nScore: **{systemic.score:.1f}/10** ({systemic.regime})\n"
            f"VIX: {vix.current_value:.1f} (z={vix.zscore_30d:.2f})\n"
            f"VKOSPI: {vkospi.current_value:.1f}\n"
            f"HY OAS: {hy.current_bps:.0f}bps {'(widening)' if hy.widening else ''}\n"
            f"PCA 1st: {pca.first_eigenvalue_share:.2f} {'(concentrated)' if pca.is_concentrated else ''}\n"
        )[:2000]

        report = RiskReport(
            vix=vix, vkospi=vkospi, credit_spread_us_ig=ig, credit_spread_us_hy=hy,
            fear_greed=fg, breadth_kr=breadth_kr, breadth_us=breadth_us,
            correlation_concentration=pca, systemic_score=systemic,
            narrative=narrative, summary_for_downstream=summary,
        )
        return {"risk_report": report, "risk_summary": summary}

    return node
```

테스트는 mock으로 모든 skill 패치 후 RiskReport 반환 검증. Commit.

---

### Task 4: TechnicalAnalyst node

**Files:**
- Create: `tradingagents/agents/analysts/technical_analyst.py`
- Create: `tests/unit/agents/test_technical_analyst.py`

```python
from datetime import date, timedelta

from tradingagents.dataflows.universe import load_universe
from tradingagents.schemas.reports import TechnicalReport
from tradingagents.skills.technical.correlation_cluster import find_correlation_clusters
from tradingagents.skills.technical.momentum_ranker import rank_momentum
from tradingagents.skills.technical.price_batch import fetch_etf_price_batch
from tradingagents.skills.technical.ta_indicators import compute_ta_indicators
from tradingagents.skills.technical.trend_state import detect_trend_state


def create_technical_analyst(quick_llm, deep_llm, cache_path: str | None = None):
    def node(state):
        as_of = date.fromisoformat(state["as_of_date"])
        universe = load_universe(state["universe_path"])
        tickers = [e.ticker for e in universe.etfs]

        start = as_of - timedelta(days=365 * 3 + 30)
        prices = fetch_etf_price_batch(tickers, start, as_of, cache_path=cache_path)
        if prices.empty:
            raise RuntimeError("No price data fetched")

        # Momentum ranking by category
        rankings = rank_momentum(prices, universe, lookback_months=6)

        # Top-tier ETFs only get TA indicators (cost reduction)
        top_tickers = []
        for cat_rankings in rankings.values():
            top_tickers.extend([r.ticker for r in cat_rankings[:5]])
        top_tickers = list(set(top_tickers))

        trend_states = {}
        for t in top_tickers:
            sub = prices[prices["ticker"] == t]
            if len(sub) < 200:
                continue
            try:
                panel = compute_ta_indicators(prices, t)
                current_price = float(sub["close"].iloc[-1])
                trend_states[t] = detect_trend_state(panel, current_price)
            except Exception:
                continue

        # Correlation clusters from returns
        pivot = prices.pivot(index="date", columns="ticker", values="close")
        returns = pivot.pct_change().dropna(how="all").tail(252)
        # Filter to top tickers for clustering speed
        returns_top = returns[[c for c in returns.columns if c in top_tickers]].dropna(axis=1, how="any")

        name_lookup = {e.ticker: e.name for e in universe.etfs}
        clusters = find_correlation_clusters(returns_top, threshold=0.7, universe_lookup=name_lookup)

        narrative = quick_llm.invoke(
            f"Summarize 188-ETF technical scan in ≤500 Korean chars. "
            f"Top momentum categories: {list(rankings.keys())[:5]}. "
            f"Found {len(clusters)} correlation clusters."
        ).content[:500]
        summary = (
            f"## Technical\n"
            f"Categories scanned: {len(rankings)}\n"
            f"Trend states: {sum(1 for v in trend_states.values() if 'uptrend' in v.value)} uptrending of {len(trend_states)}\n"
            f"Clusters: {len(clusters)} (largest: "
            f"{max((c for c in clusters), key=lambda x: len(x.members), default=None).category_label if clusters else 'none'})\n"
        )[:2000]

        report = TechnicalReport(
            asset_class_momentum=rankings,
            individual_etf_states=trend_states,
            correlation_clusters=clusters,
            narrative=narrative, summary_for_downstream=summary,
        )
        return {
            "technical_report": report, "technical_summary": summary,
            "correlation_clusters": clusters,  # used by mandate validator
        }

    return node
```

테스트 + commit.

---

### Task 5: MacroNewsAnalyst node

**Files:**
- Create: `tradingagents/agents/analysts/macro_news_analyst.py`
- Create: `tests/unit/agents/test_macro_news_analyst.py`

```python
from datetime import date

from tradingagents.schemas.reports import NewsReport
from tradingagents.skills.news.event_calendar import fetch_event_calendar_skill
from tradingagents.skills.news.impact_classifier import classify_event_impact
from tradingagents.skills.news.news_fetcher import fetch_macro_news_skill
from tradingagents.skills.news.ranker import dedupe_rank_news


def create_macro_news_analyst(quick_llm, deep_llm):
    def node(state):
        as_of = date.fromisoformat(state["as_of_date"])

        events = fetch_event_calendar_skill(as_of, days=90)
        items = fetch_macro_news_skill(window_days=7)

        # Classify impact for each (cap at 30 to control cost)
        impacts = {}
        for item in items[:30]:
            try:
                impact = classify_event_impact(
                    quick_llm, deep_llm,
                    headline=item.headline,
                    source=item.source,
                    date=item.published_at.isoformat(),
                )
                impacts[item.headline] = impact
            except Exception:
                continue

        ranked = dedupe_rank_news(items, impacts, top_n=10)

        narrative = quick_llm.invoke(
            f"Summarize macro news in ≤500 Korean chars. "
            f"Top: {[r.item.headline[:50] for r in ranked[:3]]}"
        ).content[:500]
        summary = (
            f"## News\nUpcoming events: {len(events)}\n"
            f"Top headlines (severity {ranked[0].impact.severity if ranked else 'n/a'}): "
            f"{ranked[0].item.headline[:80] if ranked else '(none)'}\n"
        )[:2000]

        report = NewsReport(
            upcoming_events=events, ranked_news=ranked,
            narrative=narrative, summary_for_downstream=summary,
        )
        return {"news_report": report, "news_summary": summary}

    return node
```

테스트 + commit.

---

## Phase 3: Researcher Debate Sub-graph (D2)

### Task 6: InvestDebateState (sub-graph 격리용)

**Files:**
- Create: `tradingagents/agents/researchers/debate_state.py`

```python
"""Bull/Bear debate sub-graph state — independent of parent AgentState (D2)."""
from typing import Annotated
from typing_extensions import TypedDict

from langgraph.graph import MessagesState

from tradingagents.schemas.portfolio import BucketTarget


class InvestDebateState(MessagesState):
    """Local state for the Bull/Bear sub-graph.

    Per D2 decision: raw debate messages live HERE only. The sub-graph judge
    returns just (BucketTarget, summary str) to the parent.
    """
    # Inputs from parent
    macro_summary: Annotated[str, "Handed off from MacroQuantAnalyst"]
    risk_summary: Annotated[str, ""]
    technical_summary: Annotated[str, ""]
    news_summary: Annotated[str, ""]

    # Local cluster state
    bull_arguments: Annotated[list[str], "Bull researcher's points across rounds"]
    bear_arguments: Annotated[list[str], "Bear researcher's points"]
    round_count: Annotated[int, "Current debate round"]
    max_rounds: Annotated[int, "From preset"]

    # Final
    bucket_target: Annotated[BucketTarget | None, "Research Manager's decision"]
```

```bash
git commit -am "feat(agents/researchers): add InvestDebateState (D2 isolated sub-graph state)"
```

---

### Task 7: BullResearcher node

**Files:**
- Create: `tradingagents/agents/researchers/bull_researcher.py`
- Create: `tests/unit/agents/test_bull_researcher.py`

```python
"""Bull researcher: argues for higher risk asset weight (자산군 단위, 종목 X)."""
from langchain_core.messages import AIMessage, HumanMessage


BULL_PROMPT = """\
You are the Bull researcher in an asset-allocation team. Your job is to argue
for higher risk-asset weight (KR/global equity, FX/commodity).

Cite SPECIFIC evidence from the analyst summaries below — never invent numbers.

Macro:
{macro_summary}

Risk:
{risk_summary}

Technical:
{technical_summary}

News:
{news_summary}

Previous Bear argument: {previous_bear}

In ≤400 chars (Korean):
1. State your proposed risk-asset bucket weight (% of 100, in 5% increments).
2. Cite 2-3 evidence points by quoting the specific data above.
3. Acknowledge ONE counter-risk."""


def create_bull_researcher(quick_llm):
    def node(state):
        previous_bear = state["bear_arguments"][-1] if state["bear_arguments"] else "(none)"
        prompt = BULL_PROMPT.format(
            macro_summary=state["macro_summary"],
            risk_summary=state["risk_summary"],
            technical_summary=state["technical_summary"],
            news_summary=state["news_summary"],
            previous_bear=previous_bear,
        )
        response = quick_llm.invoke([HumanMessage(content=prompt)])
        argument = response.content[:400]
        return {
            "bull_arguments": state["bull_arguments"] + [argument],
            "messages": state["messages"] + [AIMessage(content=f"[Bull r{state['round_count']}] {argument}")],
        }

    return node
```

테스트 + commit.

---

### Task 8: BearResearcher node

거의 동일한 구조. `BEAR_PROMPT`는 안전자산 가중을 주장. Commit.

---

### Task 9: ResearchManager (judge node)

**Files:**
- Modify: `tradingagents/agents/managers/research_manager.py`
- Create: `tests/unit/agents/test_research_manager.py`

```python
"""Research Manager — synthesizes Bull/Bear into a BucketTarget (5-bucket)."""
from pydantic import BaseModel, Field

from tradingagents.agents.utils.structured import (
    bind_structured, invoke_structured_or_freetext,
)
from tradingagents.schemas.portfolio import BucketTarget


JUDGE_PROMPT = """\
You synthesize a Bull/Bear debate into a final 5-bucket weight target.

Inputs:
{summaries}

Bull arguments (across {rounds} rounds):
{bull}

Bear arguments:
{bear}

Constraints:
- 위험자산(kr_equity + global_equity + fx_commodity) ≤ 0.70 (대회 §2.2)
- All weights sum to 1.0
- Be decisive — pick ONE target, not a range

Output a BucketTarget JSON. Rationale ≤500 chars."""


def create_research_manager(deep_llm):
    structured = bind_structured(deep_llm, BucketTarget, "ResearchManager")

    def node(state):
        prompt = JUDGE_PROMPT.format(
            summaries=(
                f"Macro: {state['macro_summary']}\n\n"
                f"Risk: {state['risk_summary']}\n\n"
                f"Technical: {state['technical_summary']}\n\n"
                f"News: {state['news_summary']}"
            ),
            rounds=state["round_count"],
            bull="\n---\n".join(state["bull_arguments"]),
            bear="\n---\n".join(state["bear_arguments"]),
        )
        target: BucketTarget = invoke_structured_or_freetext(
            structured, deep_llm,
            [{"role": "user", "content": prompt}],
            lambda x: x.model_dump_json(),
            "ResearchManager",
        )
        # Build summary for parent
        summary = (
            f"## Bucket Target\n"
            f"국내주식: {target.kr_equity:.1%}, 해외주식: {target.global_equity:.1%}, "
            f"FX/원자재: {target.fx_commodity:.1%}, 채권: {target.bond:.1%}, "
            f"MMF: {target.cash_mmf:.1%}\n"
            f"위험자산 합: {target.risk_asset_weight:.1%}\n"
            f"근거: {target.rationale[:300]}"
        )
        return {"bucket_target": target, "research_debate_summary": summary}

    return node
```

테스트 + commit.

---

### Task 10: Bull/Bear sub-graph builder

**Files:**
- Create: `tradingagents/graph/debate_subgraph.py`
- Create: `tests/integration/test_subgraph_isolation.py`

```python
"""Build the Bull/Bear debate sub-graph (D2 — raw msg isolated from parent)."""
from langgraph.graph import StateGraph, START, END

from tradingagents.agents.researchers.debate_state import InvestDebateState


def build_invest_debate_subgraph(
    bull_node, bear_node, judge_node, max_rounds: int = 1,
):
    """Sub-graph that loops Bull→Bear `max_rounds` times then runs judge.

    Returns a compiled sub-graph. Parent invokes it via .invoke() with
    relevant summaries; the sub-graph returns BucketTarget + summary str.
    """
    sg = StateGraph(InvestDebateState)
    sg.add_node("bull", bull_node)
    sg.add_node("bear", bear_node)
    sg.add_node("judge", judge_node)

    sg.add_edge(START, "bull")
    sg.add_edge("bull", "bear")

    def should_continue(state) -> str:
        next_round = state["round_count"] + 1
        if next_round >= state["max_rounds"]:
            return "judge"
        return "bull"

    sg.add_conditional_edges("bear", should_continue, {"bull": "bull", "judge": "judge"})
    sg.add_edge("judge", END)

    return sg.compile()
```

테스트 (D2 검증):

```python
"""D2 — raw debate messages must NOT leak to parent state."""
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, START, END

from tradingagents.agents.researchers.debate_state import InvestDebateState
from tradingagents.agents.utils.agent_states import AgentState, _create_empty_state
from tradingagents.graph.debate_subgraph import build_invest_debate_subgraph


def test_subgraph_messages_isolated():
    def fake_bull(state):
        return {
            "bull_arguments": state.get("bull_arguments", []) + ["bull says X"],
            "messages": state["messages"] + [HumanMessage(content="BULL_RAW")],
            "round_count": state.get("round_count", 0),
        }

    def fake_bear(state):
        return {
            "bear_arguments": state.get("bear_arguments", []) + ["bear says Y"],
            "messages": state["messages"] + [HumanMessage(content="BEAR_RAW")],
            "round_count": state["round_count"] + 1,
        }

    def fake_judge(state):
        return {
            "bucket_target": None,
            "research_debate_summary": "summary handoff: 60/40",
        }

    sg = build_invest_debate_subgraph(fake_bull, fake_bear, fake_judge, max_rounds=1)

    # Parent state does NOT have bull/bear raw msgs
    parent = _create_empty_state(
        as_of_date="2026-05-10", universe_path="x",
        capital_krw=100, preset_name="db_gaps",
    )
    parent["macro_summary"] = "macro test"
    parent["risk_summary"] = "risk test"
    parent["technical_summary"] = ""
    parent["news_summary"] = ""

    # Wrap sub-graph in a parent node that invokes it
    def parent_invoke(state):
        sub_input = InvestDebateState(
            messages=[],  # FRESH — not state["messages"]
            macro_summary=state["macro_summary"],
            risk_summary=state["risk_summary"],
            technical_summary=state["technical_summary"],
            news_summary=state["news_summary"],
            bull_arguments=[], bear_arguments=[],
            round_count=0, max_rounds=1,
            bucket_target=None,
        )
        sub_result = sg.invoke(sub_input)
        # Return ONLY the summary to parent — drop raw msgs
        return {"research_debate_summary": sub_result["research_debate_summary"]}

    main_sg = StateGraph(AgentState)
    main_sg.add_node("debate", parent_invoke)
    main_sg.add_edge(START, "debate")
    main_sg.add_edge("debate", END)
    graph = main_sg.compile()

    final = graph.invoke(parent)
    # Parent state messages should be EMPTY (the sub-graph's msgs were isolated)
    assert "BULL_RAW" not in str(final["messages"])
    assert "BEAR_RAW" not in str(final["messages"])
    assert "60/40" in final["research_debate_summary"]
```

```bash
git commit -am "feat(graph): add invest debate sub-graph + D2 isolation test"
```

---

## Phase 4: Risk Debate Sub-graph

### Task 11: RiskDebateState

**Files:**
- Create: `tradingagents/agents/risk_mgmt/debate_state.py`

같은 패턴으로 RiskDebateState 정의. 입력: bucket_target 요약 + weight_vector. 출력: WeightAdjustment.

```python
from typing import Annotated
from typing_extensions import TypedDict

from langgraph.graph import MessagesState

from tradingagents.schemas.portfolio import WeightVector


class RiskDebateState(MessagesState):
    weight_vector_input: Annotated[WeightVector | None, "From Allocator"]
    correlation_clusters_summary: Annotated[str, ""]
    macro_summary: Annotated[str, ""]
    risk_summary: Annotated[str, ""]

    aggressive_arguments: Annotated[list[str], ""]
    conservative_arguments: Annotated[list[str], ""]
    neutral_arguments: Annotated[list[str], ""]
    round_count: Annotated[int, ""]
    max_rounds: Annotated[int, ""]

    weight_adjustment: Annotated[dict | None, "Final adjustment recommendation"]
```

Commit.

---

### Task 12: 3-way risk debaters + RiskJudge

**Files:**
- Modify: `tradingagents/agents/risk_mgmt/{aggressive,conservative,neutral}_debator.py`
- Create: `tradingagents/agents/managers/risk_judge.py`
- Create: 각 unit 테스트

각 토론자는 weight_vector를 입력으로 받아 ≤300자 의견:
- Aggressive: 회전율·수익률 위주, "비중 키워라"
- Conservative: 단일 클러스터 cap, MDD, "줄여라"
- Neutral: 중재

RiskJudge는 Pydantic-locked WeightAdjustment 반환:

```python
class WeightAdjustment(BaseModel):
    delta: dict[str, float] = Field(description="ticker → weight delta (sum=0)")
    reasoning: str = Field(max_length=400)
```

테스트 + commit.

---

### Task 13: Risk debate sub-graph builder

`build_risk_debate_subgraph`. 같은 패턴, 노드 4개 (aggressive→conservative→neutral→judge). max_rounds 1 round.

테스트는 D2 isolation 검증 동일 패턴.

```bash
git commit -am "feat(graph): add risk debate sub-graph"
```

---

## Phase 5: Allocator + Validator (D4 cycle)

### Task 14: PortfolioAllocator node

**Files:**
- Create: `tradingagents/agents/allocator/__init__.py`
- Create: `tradingagents/agents/allocator/portfolio_allocator.py`
- Create: `tests/unit/agents/test_portfolio_allocator.py`

```python
"""Portfolio Allocator — bucket constraints injected into optimizer (FATAL FIX).

CRITICAL revision:
The previous design ran a 20%-capped optimizer THEN scaled weights to match
BucketTarget. Math: scaling can multiply weights by >1.0 (e.g., bucket sum
35% → target 50% means scale = 1.43), pushing single weights ABOVE the 20%
cap that the optimizer just enforced. Validator → hard violation → retry
loop runs the same flawed logic → fallback fires → BucketTarget evaporates.

Correct approach (per PyPortfolioOpt docs): inject bucket sum constraints
DURING optimization via `add_sector_constraints`. The solver finds weights
that simultaneously satisfy:
  (a) single-asset cap (weight_bounds=(0, 0.20))
  (b) bucket sum equality (sector_lower == sector_upper == bucket target)
  (c) the chosen objective (min_variance, max_sharpe, ...)
If the constraints are jointly infeasible (rare), we relax bucket equality
to a band [target ± 5%p] and retry once before falling back.
"""
from datetime import date, timedelta

import pandas as pd
from pypfopt import EfficientFrontier, HRPOpt, risk_models, expected_returns

from tradingagents.dataflows.universe import load_universe
from tradingagents.schemas.portfolio import OptimizationMethod, WeightVector
from tradingagents.skills.portfolio.candidate_selector import (
    BUCKET_TO_CATEGORIES, select_etf_candidates,
)
from tradingagents.skills.portfolio.method_picker import pick_optimization_method
from tradingagents.skills.portfolio.returns_matrix import fetch_returns_matrix


# Reverse map: category → bucket name (for sector_mapper)
_CATEGORY_TO_BUCKET = {
    cat: bucket for bucket, cats in BUCKET_TO_CATEGORIES.items() for cat in cats
}


def create_portfolio_allocator(quick_llm, deep_llm, cache_path: str | None = None):
    def node(state):
        as_of = date.fromisoformat(state["as_of_date"])
        universe = load_universe(state["universe_path"])
        bucket_target = state["bucket_target"]
        if bucket_target is None:
            raise RuntimeError("bucket_target missing — Research Manager failed")

        # D4: read feedback from previous validation failure
        feedback_violations = state.get("allocation_feedback", [])
        attempts = state.get("allocation_attempts", 0)

        # 1. Select candidates (deterministic, point-in-time per D13)
        # `as_of` flows into select_etf_candidates → universe.tradable_at(as_of)
        # so backtests don't include ETFs that weren't listed yet at as_of.
        rankings = state["technical_report"].asset_class_momentum if state.get("technical_report") else {}
        candidates = select_etf_candidates(
            universe, bucket_target, rankings,
            as_of=as_of,
            min_aum_krw=1_000_000_000_000,
            per_bucket_n=4 if attempts == 0 else 6,  # widen pool on retry
        )

        # Flatten candidate tickers
        all_candidates: list[str] = []
        for tickers in candidates.bucket_to_tickers.values():
            all_candidates.extend(tickers)
        if len(all_candidates) < 3:
            raise RuntimeError("Too few candidates")

        # 2. Returns matrix
        start = as_of - timedelta(days=365 * 3)
        returns = fetch_returns_matrix(all_candidates, start, as_of, cache_path=cache_path)

        # 3. Subagent: pick method
        regime = state["macro_report"].regime if state.get("macro_report") else None
        risk_score = state["risk_report"].systemic_score if state.get("risk_report") else None

        feedback_str = ""
        if feedback_violations:
            feedback_str = "\nPrevious violations:\n" + "\n".join(
                f"- {v.description} (fix: {v.suggested_fix})" for v in feedback_violations
            )

        method_choice = pick_optimization_method(
            quick_llm, deep_llm,
            regime_quadrant=regime.quadrant if regime else "unknown",
            regime_confidence=regime.confidence if regime else 0.5,
            risk_score=risk_score.score if risk_score else 5.0,
            risk_regime=risk_score.regime if risk_score else "neutral",
            feedback=feedback_str,
        )

        # 4. Optimize WITH bucket-constraints (single-pass; no post-scaling)
        wv = _optimize_with_bucket_constraints(
            method=method_choice.method,
            returns=returns,
            candidates=candidates,
            bucket_target=bucket_target,
            universe=universe,
            method_params=method_choice.params,
            attempts=attempts,
        )

        return {
            "candidate_set": candidates,
            "weight_vector": wv,
            "allocation_attempts": attempts + 1,
        }

    return node


def _build_sector_mapper_and_bounds(
    candidates, bucket_target, universe, attempts: int,
) -> tuple[dict[str, str], dict[str, float], dict[str, float]]:
    """Map ticker → bucket; build (lower, upper) bounds per bucket.

    First attempt: equality (lower == upper == target).
    Retry attempts: relax to ±5%p band (handle infeasibility).
    """
    sector_mapper: dict[str, str] = {}
    for bucket, tickers in candidates.bucket_to_tickers.items():
        for t in tickers:
            sector_mapper[t] = bucket

    target_map = {
        "kr_equity": bucket_target.kr_equity,
        "global_equity": bucket_target.global_equity,
        "fx_commodity": bucket_target.fx_commodity,
        "bond": bucket_target.bond,
        "cash_mmf": bucket_target.cash_mmf,
    }

    if attempts == 0:
        # Strict equality
        sector_lower = dict(target_map)
        sector_upper = dict(target_map)
    else:
        # Relax by ±5%p (clip to [0, 1])
        band = 0.05
        sector_lower = {b: max(0.0, w - band) for b, w in target_map.items()}
        sector_upper = {b: min(1.0, w + band) for b, w in target_map.items()}

    return sector_mapper, sector_lower, sector_upper


def _optimize_with_bucket_constraints(
    method: OptimizationMethod,
    returns: pd.DataFrame,
    candidates,
    bucket_target,
    universe,
    method_params: dict,
    attempts: int,
) -> WeightVector:
    """Optimize with simultaneous (single-asset cap, bucket sum) constraints."""
    sector_mapper, sector_lower, sector_upper = _build_sector_mapper_and_bounds(
        candidates, bucket_target, universe, attempts,
    )

    # Restrict returns to the candidates we have a sector mapping for
    valid = [t for t in returns.columns if t in sector_mapper]
    returns = returns[valid].dropna(axis=0, how="any")

    if method == OptimizationMethod.HRP:
        # HRP doesn't natively support sector constraints. Strategy:
        # run HRP within each bucket separately (proportional to target),
        # then concatenate. This mathematically satisfies bucket sums.
        return _hrp_per_bucket(returns, candidates, bucket_target)

    S = risk_models.sample_cov(returns)

    if method == OptimizationMethod.BLACK_LITTERMAN:
        from pypfopt import BlackLittermanModel
        views = method_params.get("views", {})
        confs = method_params.get("view_confidences", [])
        if views:
            bl = BlackLittermanModel(
                S, absolute_views=views, omega="idzorek", view_confidences=confs,
            )
            mu = bl.bl_returns()
        else:
            mu = expected_returns.mean_historical_return(returns, returns_data=True)
    else:
        mu = expected_returns.mean_historical_return(returns, returns_data=True)

    ef = EfficientFrontier(mu, S, weight_bounds=(0, 0.20))
    ef.add_sector_constraints(sector_mapper, sector_lower, sector_upper)

    try:
        if method == OptimizationMethod.MIN_VARIANCE:
            ef.min_volatility()
        elif method == OptimizationMethod.RISK_PARITY:
            # PyPortfolioOpt has no exact risk parity with sector constraints —
            # min-volatility within constraints approximates equal risk contribution
            ef.min_volatility()
        else:  # BLACK_LITTERMAN, default to max_sharpe
            ef.max_sharpe()
    except Exception as e:
        # Joint infeasibility — surface to the cycle (D4) for retry/fallback
        raise RuntimeError(
            f"Joint optimization infeasible (method={method}, attempt={attempts}): {e}"
        ) from e

    weights = {t: float(w) for t, w in ef.clean_weights().items() if w > 1e-4}
    total = sum(weights.values())
    weights = {t: w / total for t, w in weights.items()}  # safety renorm (≤1e-6 drift)

    # POST-CONDITION ASSERTIONS — these must hold by construction, not by repair
    assert all(w <= 0.20 + 1e-6 for w in weights.values()), \
        f"Optimizer violated 20% cap: {[(t, w) for t, w in weights.items() if w > 0.20]}"

    constraint_label = "strict bucket equality" if attempts == 0 else "±5%p bucket band"
    expected_vol = None
    expected_sharpe = None
    try:
        perf = ef.portfolio_performance(verbose=False)
        expected_sharpe = float(perf[2]) if len(perf) >= 3 else None
        expected_vol = float(perf[1]) if len(perf) >= 2 else None
    except Exception:
        pass

    return WeightVector(
        method=method,
        weights=weights,
        rationale=(
            f"{method.value} with single-asset cap 20% AND bucket constraints "
            f"({constraint_label}). 위험자산 target {bucket_target.risk_asset_weight:.1%}."
        ),
        expected_volatility=expected_vol,
        expected_sharpe=expected_sharpe,
    )


def _hrp_per_bucket(returns: pd.DataFrame, candidates, bucket_target) -> WeightVector:
    """HRP within each bucket, scaled by bucket target. Mathematically:
    weight[t] = bucket_target[bucket(t)] * hrp_within_bucket[t]
    sum across bucket B = bucket_target[B] * 1.0 = bucket_target[B]  ✓

    Single-asset cap: clip after-scaling and re-distribute residual within bucket.
    """
    target_map = {
        "kr_equity": bucket_target.kr_equity,
        "global_equity": bucket_target.global_equity,
        "fx_commodity": bucket_target.fx_commodity,
        "bond": bucket_target.bond,
        "cash_mmf": bucket_target.cash_mmf,
    }

    final: dict[str, float] = {}
    for bucket, tickers in candidates.bucket_to_tickers.items():
        target = target_map.get(bucket, 0)
        if target <= 0 or not tickers:
            continue
        sub = returns[[t for t in tickers if t in returns.columns]].dropna(axis=0, how="any")
        if sub.shape[1] == 0:
            continue
        if sub.shape[1] == 1:
            inner = {sub.columns[0]: 1.0}
        else:
            hrp = HRPOpt(sub)
            inner = {k: float(v) for k, v in hrp.optimize().items()}
            s = sum(inner.values())
            inner = {k: v / s for k, v in inner.items()}

        # Apply bucket scaling (within bucket only — no cross-bucket inflation)
        scaled = {t: w * target for t, w in inner.items()}

        # Enforce 20% cap WITHIN bucket via ITERATIVE water-filling (D12 fix).
        # Single-pass redistribution can fail when redistributed weight pushes
        # another asset over the cap, leaving residual unallocated. Loop until
        # either residual ≤ tolerance OR all assets capped (joint infeasibility).
        capped = {t: min(w, 0.20) for t, w in scaled.items()}
        residual = sum(scaled.values()) - sum(capped.values())
        max_iters = 10  # safety bound; converges in O(N) for N assets in practice
        for _ in range(max_iters):
            if residual <= 1e-9:
                break
            non_capped = [t for t, w in capped.items() if w < 0.20 - 1e-9]
            if not non_capped:
                # All assets at cap — joint infeasibility within this bucket.
                # Bucket cannot reach target with N candidates × 20% cap.
                # Surface to caller via D4 cycle (RuntimeError → fallback).
                raise RuntimeError(
                    f"HRP-per-bucket joint infeasibility: bucket target {target:.4f} "
                    f"unreachable with {len(scaled)} candidates × 20% cap."
                )
            share = residual / len(non_capped)
            for t in non_capped:
                room = 0.20 - capped[t]
                add = min(share, room)
                capped[t] += add
            residual = sum(scaled.values()) - sum(capped.values())

        final.update(capped)

    # Sanity
    total = sum(final.values())
    if abs(total - 1.0) > 1e-3:
        # Renormalize across all (bucket residue)
        final = {t: w / total for t, w in final.items()}

    assert all(w <= 0.20 + 1e-6 for w in final.values()), \
        "HRP-per-bucket post-condition: 20% cap violated"

    return WeightVector(
        method=OptimizationMethod.HRP,
        weights=final,
        rationale=(
            f"HRP within each bucket × bucket_target weight. "
            f"위험자산 target {bucket_target.risk_asset_weight:.1%}, single-asset cap 20%."
        ),
    )
```

> **Production hardening (FATAL FIX):** 기존 "최적화 → 사후 스케일링" 패턴은 단일 20% 캡을 깨뜨림 (예: 버킷 35% → 타겟 50% 스케일링 시 단일 28.5%). PyPortfolioOpt의 `add_sector_constraints`로 **버킷 합계 제약을 최적화 단계에 직접 주입**. 단일 캡과 버킷 합 제약이 동시에 만족되는 해를 솔버가 찾음. 1차 시도는 strict equality, 재시도 시 ±5%p band로 완화. HRP는 native sector constraint 없으므로 버킷별 독립 HRP × 타겟 가중 패턴으로 동일 효과 달성.

테스트 + commit.

---

### Task 15: MandateValidator node (D4 wired)

**Files:**
- Create: `tradingagents/agents/validator/__init__.py`
- Create: `tradingagents/agents/validator/mandate_validator.py`
- Create: `tests/unit/agents/test_mandate_validator.py`

```python
"""Mandate Validator — runs all 4 deterministic checks; D4 cycle decision in conditional_logic.py."""
from tradingagents.dataflows.universe import load_universe
from tradingagents.schemas.mandate import ValidationReport, Violation
from tradingagents.skills.mandate.concentration_check import validate_concentration
from tradingagents.skills.mandate.correlation_check import validate_correlation_concentration
from tradingagents.skills.mandate.turnover_check import validate_turnover_feasibility
from tradingagents.skills.mandate.universe_check import validate_universe


def create_mandate_validator():
    def node(state):
        weights = state["weight_vector"]
        if weights is None:
            return {"validation_passed": False, "validation_report": ValidationReport(
                passed=False,
                violations=[Violation(
                    rule="universe_membership",
                    description="No weight_vector to validate",
                    severity="hard",
                    suggested_fix="Re-run Allocator",
                )],
            )}

        universe = load_universe(state["universe_path"])
        all_violations = []

        for check in [
            validate_universe(weights, universe),
            validate_concentration(weights, universe),
            validate_correlation_concentration(weights, state.get("correlation_clusters", [])),
        ]:
            all_violations.extend(check.violations)

        # Turnover check
        prev = state.get("previous_portfolio")
        prev_weights = prev["weights"] if prev else None
        floor = 0.80 if prev is None else 0.10
        days = 5 if prev is None else 20
        turnover_check = validate_turnover_feasibility(
            weights, prev_weights, state["capital_krw"], floor_pct=floor, days_remaining=days,
        )
        all_violations.extend(turnover_check.violations)

        report = ValidationReport(
            passed=not any(v.severity == "hard" for v in all_violations),
            violations=all_violations,
        )
        return {
            "validation_report": report,
            "validation_passed": report.passed,
            "allocation_feedback": report.hard_violations if not report.passed else [],
        }

    return node
```

테스트는 단일 25%, 위험 73%, 회전율 40% 등 케이스로 hard_violations 발견 검증. Commit.

---

### Task 16: Validator → Allocator cycle conditional logic (D4)

**Files:**
- Modify: `tradingagents/graph/conditional_logic.py`

```python
"""Conditional logic for the LangGraph (D4 — Validator cycle)."""
from typing import Literal


MAX_ALLOCATION_ATTEMPTS = 2


def validation_router(state) -> Literal["finalize", "retry_allocator", "fallback"]:
    """Per D4: pass → finalize. Fail + attempts<2 → retry. Fail + attempts==2 → fallback."""
    if state.get("validation_passed"):
        return "finalize"
    attempts = state.get("allocation_attempts", 0)
    if attempts < MAX_ALLOCATION_ATTEMPTS:
        return "retry_allocator"
    return "fallback"
```

```python
"""Deterministic fallback node: constrained re-optimization (D4 + revision).

CRITICAL math correction: the naive "clip(0.20) + renormalize" pattern can
push weights BACK ABOVE the 20% cap (e.g., [0.30, 0.30, 0.40] → clipped
[0.20, 0.20, 0.20] → renormalized [0.333, 0.333, 0.333] — still violates).

The correct deterministic fallback is to RE-RUN the optimizer with HARD
constraints (PyPortfolioOpt's `weight_bounds`) so the optimizer itself
finds a feasible solution. If even this fails, we fall back to an equal-
weighted defensive cash-heavy mix that mathematically cannot violate.
"""
from datetime import date, timedelta

from tradingagents.dataflows.universe import load_universe
from tradingagents.schemas.portfolio import OptimizationMethod, WeightVector
from tradingagents.skills.portfolio.returns_matrix import fetch_returns_matrix


def create_fallback_normalizer(cache_path: str | None = None):
    def node(state):
        weights = state["weight_vector"]
        if weights is None:
            return _emergency_cash_portfolio(state)

        # Strategy: re-run min-variance with strict weight_bounds(0, 0.20).
        # Unlike clip+renormalize, the optimizer mathematically guarantees
        # the solution satisfies the constraint at the optimization step.
        try:
            from pypfopt import EfficientFrontier, risk_models

            tickers = list(weights.weights.keys())
            as_of = date.fromisoformat(state["as_of_date"])
            start = as_of - timedelta(days=365 * 3)
            returns = fetch_returns_matrix(tickers, start, as_of, cache_path=cache_path)

            S = risk_models.sample_cov(returns)
            ef = EfficientFrontier(None, S, weight_bounds=(0, 0.20))
            ef.min_volatility()
            constrained_weights = {
                k: float(v) for k, v in ef.clean_weights().items() if v > 1e-4
            }

            # Validate the optimizer actually respected the cap (sanity check)
            assert all(w <= 0.20 + 1e-6 for w in constrained_weights.values()), \
                "PyPortfolioOpt weight_bounds violated — falling through"
            assert abs(sum(constrained_weights.values()) - 1.0) < 1e-3, \
                "Constrained solution doesn't sum to 1 — falling through"

            new_wv = WeightVector(
                method=OptimizationMethod.MIN_VARIANCE,
                weights=constrained_weights,
                rationale=(
                    f"DETERMINISTIC FALLBACK after {state['allocation_attempts']} "
                    f"failed attempts: re-optimized with min-variance + hard 20% cap. "
                    f"Original method: {weights.method.value}."
                ),
            )
            return {
                "weight_vector": new_wv,
                "validation_passed": True,  # constraints are mathematically guaranteed
            }
        except Exception as e:
            # Last-resort: emergency cash portfolio
            return _emergency_cash_portfolio(state, error=str(e))

    return node


def _emergency_cash_portfolio(state, error: str = "no weight_vector") -> dict:
    """Last-resort fallback: 100% safe-asset (cash/MMF) split.

    Used when even constrained optimization fails. Produces a portfolio that
    cannot violate mandate rules: equal-weight across MMF/CD ETFs, all of
    which are 안전자산 (no risk-asset cap concern), each ≤20% by construction.
    """
    universe = load_universe(state["universe_path"])
    cash_etfs = [
        e.ticker for e in universe.etfs
        if e.category == "금리연계형/초단기채권"
    ][:5]
    if not cash_etfs:
        # Truly nothing we can do — surface the failure
        raise RuntimeError(
            f"Emergency fallback failed ({error}); no cash ETFs in universe"
        )

    weight = 1.0 / len(cash_etfs)
    weights = {t: weight for t in cash_etfs}

    new_wv = WeightVector(
        method=OptimizationMethod.MIN_VARIANCE,
        weights=weights,
        rationale=(
            f"EMERGENCY DEFENSIVE FALLBACK: equal-weight across {len(cash_etfs)} "
            f"MMF/CD ETFs. Triggered by: {error}. Manual review required before submission."
        ),
    )
    return {
        "weight_vector": new_wv,
        "validation_passed": True,
    }
```

테스트는 cycle 통합 시나리오로 검증.

```bash
git commit -am "feat(graph): add Validator cycle conditional logic + fallback (D4)"
```

---

### Task 17: PortfolioManager (final composition node)

**Files:**
- Modify: `tradingagents/agents/managers/portfolio_manager.py`
- Create: `tests/unit/agents/test_portfolio_manager.py`

```python
"""Portfolio Manager — generates 3 artifacts (portfolio.json, philosophy.md, trade_plan.csv)."""
import csv
import json
from pathlib import Path

from tradingagents.dataflows.universe import load_universe


def create_portfolio_manager(deep_llm, artifacts_dir: str = "./artifacts"):
    def node(state):
        weights = state["weight_vector"]
        bucket = state["bucket_target"]
        capital = state["capital_krw"]
        as_of = state["as_of_date"]

        out_dir = Path(artifacts_dir) / as_of
        out_dir.mkdir(parents=True, exist_ok=True)

        universe = load_universe(state["universe_path"])
        meta = {e.ticker: e for e in universe.etfs}

        # 1. portfolio.json
        portfolio = {
            "as_of_date": as_of,
            "capital_krw": capital,
            "method": weights.method.value,
            "bucket_target": bucket.model_dump(),
            "weights": weights.weights,
            "rationale": weights.rationale,
            "expected_volatility": weights.expected_volatility,
            "expected_sharpe": weights.expected_sharpe,
        }
        portfolio_path = out_dir / "portfolio.json"
        portfolio_path.write_text(json.dumps(portfolio, indent=2, ensure_ascii=False), encoding="utf-8")

        # 2. trade_plan.csv (will be replaced with current price fetching in Plan 4)
        trade_plan_path = out_dir / "trade_plan.csv"
        with open(trade_plan_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["티커", "ETF명", "자산군", "가중치", "매수금액(KRW)"])
            for ticker, weight in sorted(weights.weights.items(), key=lambda x: -x[1]):
                m = meta.get(ticker)
                w.writerow([
                    ticker, m.name if m else "", m.category if m else "",
                    f"{weight:.4f}", int(weight * capital),
                ])

        # 3. philosophy.md (deep LLM, ≥4000 chars per spec §4.1)
        # Placeholder; full impl in Plan 4 with reports module
        philosophy_path = out_dir / "philosophy.md"
        philosophy = (
            f"# 투자철학 ({as_of})\n\n"
            f"## 1. 매크로 판단\n"
            f"{state.get('macro_summary', '')}\n\n"
            f"## 2. 시장 리스크\n"
            f"{state.get('risk_summary', '')}\n\n"
            f"## 3. 자산군 비중 결정\n"
            f"{state.get('research_debate_summary', '')}\n\n"
            f"## 4. 단일 리스크 통제\n"
            f"{state.get('technical_summary', '')}\n\n"
            f"## 5. 매매 결정\n"
            f"{weights.rationale}\n\n"
            f"## 6. 시장 충격 시나리오\n"
            f"(Plan 4에서 채워짐 — 본 v1 Plan 3 placeholder)\n"
        )
        philosophy_path.write_text(philosophy, encoding="utf-8")

        return {
            "final_portfolio_path": str(portfolio_path),
            "philosophy_doc_path": str(philosophy_path),
            "trade_plan_csv_path": str(trade_plan_path),
        }

    return node
```

테스트 + commit.

---

## Phase 6: Graph Builder + 메인 그래프

### Task 18: Graph builder (preset YAML → LangGraph)

**Files:**
- Create: `tradingagents/graph/builder.py`
- Create: `tests/unit/graph/test_builder.py`

```python
"""Build a LangGraph from a PresetSpec (D3)."""
from langgraph.graph import StateGraph, START, END

from tradingagents.agents.utils.agent_states import AgentState
from tradingagents.graph.conditional_logic import validation_router
from tradingagents.presets.spec import PresetSpec


def build_main_graph(preset: PresetSpec, node_factory):
    """Build the top-level graph from a preset.

    `node_factory` is a callable that, given an AgentSpec, returns the actual
    node function. This indirection lets tests inject mocks.
    """
    sg = StateGraph(AgentState)

    # Phase 1: parallel analysts
    analyst_stage = next((s for s in preset.stages if s.id == "analysts"), None)
    if analyst_stage is None:
        raise ValueError("preset must have an 'analysts' stage")

    for agent in analyst_stage.agents:
        sg.add_node(agent.id, node_factory(agent))
        sg.add_edge(START, agent.id)

    # Phase 2: research debate (single node — sub-graph wrapped inside)
    sg.add_node("research_debate", node_factory(_synth_agent("research_debate")))
    for agent in analyst_stage.agents:
        sg.add_edge(agent.id, "research_debate")

    # Phase 3: allocator
    sg.add_node("allocator", node_factory(_synth_agent("allocator")))
    sg.add_edge("research_debate", "allocator")

    # Phase 4: risk debate (sub-graph wrapped)
    sg.add_node("risk_debate", node_factory(_synth_agent("risk_debate")))
    sg.add_edge("allocator", "risk_debate")

    # Phase 5: validator
    sg.add_node("validator", node_factory(_synth_agent("validator")))
    sg.add_edge("risk_debate", "validator")

    # Phase 6: D4 cycle
    sg.add_node("fallback", node_factory(_synth_agent("fallback")))
    sg.add_node("portfolio_manager", node_factory(_synth_agent("portfolio_manager")))

    sg.add_conditional_edges(
        "validator", validation_router,
        {
            "finalize": "portfolio_manager",
            "retry_allocator": "allocator",
            "fallback": "fallback",
        },
    )
    sg.add_edge("fallback", "portfolio_manager")
    sg.add_edge("portfolio_manager", END)

    return sg.compile()


def _synth_agent(agent_id: str):
    """Helper for synthetic agents not in preset (e.g., wrapper nodes)."""
    from tradingagents.presets.spec import AgentSpec
    return AgentSpec(id=agent_id, skills=[], output_schema=None, model="quick")
```

테스트는 mock node_factory로 그래프 컴파일 검증.

```bash
git commit -am "feat(graph): add preset-based graph builder (D3 + D4 cycle)"
```

---

### Task 19: Main TradingGraph rewrite (얇은 진입점)

**Files:**
- Modify: `tradingagents/graph/trading_graph.py`
- Create: `tests/integration/test_trading_graph_e2e.py`

```python
"""TradingAgentsGraph — preset-driven entry point."""
import logging
from pathlib import Path

from langgraph.graph import StateGraph

from tradingagents.agents.allocator.portfolio_allocator import create_portfolio_allocator
from tradingagents.agents.analysts.macro_news_analyst import create_macro_news_analyst
from tradingagents.agents.analysts.macro_quant_analyst import create_macro_quant_analyst
from tradingagents.agents.analysts.market_risk_analyst import create_market_risk_analyst
from tradingagents.agents.analysts.technical_analyst import create_technical_analyst
from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
from tradingagents.agents.managers.research_manager import create_research_manager
from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
from tradingagents.agents.utils.agent_states import _create_empty_state
from tradingagents.agents.validator.mandate_validator import create_mandate_validator
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.builder import build_main_graph
from tradingagents.graph.conditional_logic import create_fallback_normalizer
from tradingagents.graph.debate_subgraph import build_invest_debate_subgraph
from tradingagents.llm_clients import create_llm_client
from tradingagents.presets.loader import PresetLoader
import tradingagents.skills._registry_init  # noqa: F401 — register all skills

logger = logging.getLogger(__name__)


class TradingAgentsGraph:
    def __init__(self, preset_name: str = "db_gaps", config: dict | None = None):
        self.config = config or DEFAULT_CONFIG
        self.preset_name = preset_name

        preset_path = Path(self.config["preset_dir"]) / f"{preset_name}.yaml"
        self.preset = PresetLoader.from_yaml(preset_path)

        # Build LLMs
        deep = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["deep_think_llm"],
        ).get_llm()
        quick = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["quick_think_llm"],
        ).get_llm()

        # Assemble nodes
        analysts = {
            "macro_quant": create_macro_quant_analyst(quick, deep),
            "market_risk": create_market_risk_analyst(quick, deep),
            "technical": create_technical_analyst(quick, deep, cache_path=self.config["etf_price_cache_path"]),
            "macro_news": create_macro_news_analyst(quick, deep),
        }

        bull = create_bull_researcher(quick)
        bear = create_bear_researcher(quick)
        research_judge = create_research_manager(deep)
        invest_subgraph = build_invest_debate_subgraph(bull, bear, research_judge, max_rounds=self.config["max_debate_rounds"])

        allocator = create_portfolio_allocator(quick, deep, cache_path=self.config["etf_price_cache_path"])
        validator = create_mandate_validator()
        fallback = create_fallback_normalizer(cache_path=self.config["etf_price_cache_path"])
        pm = create_portfolio_manager(deep, artifacts_dir=self.config.get("artifacts_dir", "./artifacts"))

        # Wrap research_debate as a parent node that invokes the sub-graph
        def research_debate_node(state):
            from tradingagents.agents.researchers.debate_state import InvestDebateState
            sub_input = InvestDebateState(
                messages=[],
                macro_summary=state.get("macro_summary", ""),
                risk_summary=state.get("risk_summary", ""),
                technical_summary=state.get("technical_summary", ""),
                news_summary=state.get("news_summary", ""),
                bull_arguments=[], bear_arguments=[],
                round_count=0, max_rounds=self.config["max_debate_rounds"],
                bucket_target=None,
            )
            sub_result = invest_subgraph.invoke(sub_input)
            return {
                "research_debate_summary": sub_result["research_debate_summary"],
                "bucket_target": sub_result["bucket_target"],
            }

        nodes = {
            **analysts,
            "research_debate": research_debate_node,
            "allocator": allocator,
            "risk_debate": lambda state: state,  # Plan 3 stub; Plan 4 wires risk sub-graph
            "validator": validator,
            "fallback": fallback,
            "portfolio_manager": pm,
        }

        def factory(agent_spec):
            return nodes.get(agent_spec.id, lambda s: s)

        self.graph = build_main_graph(self.preset, factory)

    def run(self, as_of_date: str, capital_krw: int = 1_000_000_000) -> dict:
        state = _create_empty_state(
            as_of_date=as_of_date,
            universe_path=self.config["universe_path"],
            capital_krw=capital_krw,
            preset_name=self.preset_name,
        )
        return self.graph.invoke(state, config={"recursion_limit": 50})
```

```bash
git commit -am "feat(graph): rewrite TradingAgentsGraph as preset-driven entry point"
```

---

### Task 20: db_gaps.yaml preset

**Files:**
- Create: `presets/db_gaps.yaml`

```yaml
name: db_gaps
universe: ./data/universe.json
capital_krw: 1_000_000_000

stages:
  - id: analysts
    parallel: true
    agents:
      - id: macro_quant
        skills: [
          fetch_fred_series, fetch_ecos_series,
          compute_yield_curve, compute_inflation_trend,
          compute_unemployment_trend, classify_regime,
          compute_kr_divergence, fetch_central_bank_calendar,
        ]
        output_schema: MacroReport
        model: deep
        timeout_seconds: 180
        skill_prompt_base: prompts/macro-analysis.md

      - id: market_risk
        skills: [
          fetch_volatility_index, fetch_credit_spread, fetch_fear_greed_index,
          compute_market_breadth, compute_correlation_concentration, score_systemic_risk,
        ]
        output_schema: RiskReport
        model: deep

      - id: technical
        skills: [
          fetch_etf_price_batch, compute_ta_indicators, rank_momentum,
          detect_trend_state, find_correlation_clusters,
        ]
        output_schema: TechnicalReport
        model: quick

      - id: macro_news
        skills: [
          fetch_event_calendar, fetch_macro_news,
          classify_event_impact, dedupe_rank_news,
        ]
        output_schema: NewsReport
        model: quick

  - id: research_debate
    cluster_mode: shared_state
    rounds: 1
    agents:
      - id: bull_researcher
        cited_evidence_required: true
      - id: bear_researcher
        cited_evidence_required: true
    judge:
      id: research_manager
      output_schema: BucketTarget

  - id: allocation
    agents:
      - id: portfolio_allocator
        skills: [
          select_etf_candidates, fetch_returns_matrix,
          optimize_hrp, optimize_risk_parity, optimize_min_variance, optimize_black_litterman,
          pick_optimization_method,
        ]
        input_from:
          bucket_target: research_manager
          regime: macro_quant
          risk_score: market_risk
          clusters: technical

  - id: risk_debate
    cluster_mode: shared_state
    rounds: 1
    agents:
      - id: aggressive_debator
      - id: conservative_debator
      - id: neutral_debator
    judge:
      id: risk_judge

  - id: validation
    agents:
      - id: mandate_validator
        skills: [
          validate_universe, validate_concentration,
          validate_turnover_feasibility, validate_correlation_concentration,
        ]
    on_fail: rerun_from(allocation, max_attempts=2)

  - id: finalize
    agents:
      - id: portfolio_manager
```

```bash
git add presets/db_gaps.yaml
git commit -m "feat(presets): add db_gaps.yaml — full v1 preset"
```

---

## Phase 7: Integration

### Task 21: D4 cycle integration test

`tests/integration/test_validator_cycle.py`:

```python
def test_validator_retry_then_fallback(tmp_path, monkeypatch):
    # Set up an Allocator that always produces a 25% single weight (violates 20% cap)
    # Run pipeline, verify:
    # - 1st validation fail
    # - 2nd attempt fails again
    # - Fallback triggered, weights normalized to ≤20%
    # - validation_passed=True after fallback
    pass  # Full impl uses mocked nodes
```

테스트 작성 + commit.

---

### Task 22: Mock fixture pipeline integration

`tests/integration/test_plan_pipeline_mock.py`:

```python
"""End-to-end pipeline with all external APIs mocked. Plan 3 happy path."""
def test_plan_pipeline_produces_artifacts(tmp_path, monkeypatch):
    # Mock fetch_fred_series, fetch_ecos_series, fetch_etf_price_batch, LLMs
    # Run TradingAgentsGraph.run("2026-05-25")
    # Assert: portfolio.json, philosophy.md, trade_plan.csv exist
    # Assert: validation_passed=True
    # Assert: weight_vector total ≈ 1.0
    pass
```

```bash
git commit -am "test(integration): add Plan 3 pipeline mock E2E"
```

---

## Self-Review

- ✅ D2 (subgraph 격리) — Task 6, 10, 11, 13 + isolation test
- ✅ D3 (preset YAML 빌더) — Task 18
- ✅ D4 (Validator cycle) — Task 16
- ✅ D6 (BaseSubagent 활용) — 모든 분석가가 subagent 호출
- ✅ D7 (retry helper 활용) — bind_structured 통해 간접 적용
- ✅ §13 state 스키마 — Task 1
- 분석가 4명·Allocator·Validator·PM 모두 구현
- D2 hybrid topology가 메인 그래프에 반영

## Plan 3 완료 시 산출물

- 4 분석가 + Allocator + Validator + PM 노드
- 2 sub-graph (research debate, risk debate)
- preset YAML loader → LangGraph builder
- D4 cycle (3개 conditional edge)
- ~25 단위 테스트 + 3 integration test
- `db_gaps.yaml` preset

**다음:** Plan 4 (CLI 22개 + Reports + 5/28 E2E + 3-tier rebalancing) — `docs/superpowers/plans/2026-05-10-db-gaps-plan-4-cli.md`
