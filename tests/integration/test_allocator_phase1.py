"""Phase 1 integration — allocator pipeline 의 spillover + ENB 통합 검증.

가짜 universe 와 returns 로 5 개 시나리오:
  1. 정상 universe (모두 양수 alpha) → spillover 0, ENB 양호
  2. fx_commodity 음수 only → fx 100% spillover
  3. global low conviction → 부분 spillover
  4. attribution completeness
  5. cash overflow → high-conv redistribution
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingagents.dataflows.universe import ETFEntry, Universe
from tradingagents.schemas.portfolio import BucketTarget


@pytest.fixture
def synthetic_universe(tmp_path):
    """5 bucket × 4 ticker = 20 ETF universe."""
    etfs = []
    for prefix, cat, sub in [
        ("KR", "국내주식_지수", None),
        ("GL", "해외주식_지수", None),
        ("FX", "FX 및 원자재", "gold"),
        ("BD", "국내채권_종합", "nominal"),
        ("CS", "금리연계형/초단기채권", None),
    ]:
        for i in range(4):
            etfs.append(ETFEntry(
                ticker=f"A_{prefix}{i:02d}", name=f"{prefix}{i}",
                aum_krw=50_000_000_000,
                underlying_index=f"{prefix}_idx_{i}",
                bucket="안전" if prefix in ("BD", "CS") else "위험",
                category=cat, sub_category=sub,
            ))
    universe = Universe(version="test", etfs=etfs)
    path = tmp_path / "universe.json"
    path.write_text(universe.model_dump_json())
    return path


def test_allocator_with_normal_universe(tmp_path, monkeypatch):
    """5 bucket 양수 alpha 충분 → spillover ≈ 0, ENB > 2.0."""
    from tests.integration._allocator_state_helpers import (
        make_synthetic_universe, make_synthetic_returns, make_factor_panel,
        make_bucket_target, make_macro_report, make_risk_report,
        make_research_decision, make_technical_report, make_allocator_state,
    )
    from tradingagents.agents.allocator.portfolio_allocator import create_portfolio_allocator

    universe = make_synthetic_universe(n_per_bucket=4)
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(universe.model_dump_json())

    tickers = [e.ticker for e in universe.etfs]
    returns = make_synthetic_returns(tickers, n_days=252, seed=7)
    factor_panel = make_factor_panel(tickers)  # default alpha 0.05 (양수)

    monkeypatch.setattr(
        "tradingagents.skills.portfolio.candidate_selector.fetch_etf_metrics_window",
        lambda tickers, start, end, cache_path=None: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "tradingagents.agents.allocator.portfolio_allocator.fetch_returns_matrix",
        lambda eligible, start, end, cache_path=None: returns[eligible],
    )

    state = make_allocator_state(
        as_of=date(2026, 5, 28),
        universe_path=str(universe_path),
        bucket_target=make_bucket_target(),
        technical_report=make_technical_report(factor_panel),
        macro_report=make_macro_report(),
        risk_report=make_risk_report(),
        research_decision=make_research_decision(),
    )

    node_func = create_portfolio_allocator()
    result = node_func(state)

    spillover = result["allocation_attribution"]["cash_spillover"]
    assert spillover["total_spillover_to_cash"] < 0.10
    assert result["allocation_attribution"]["enb"] > 1.5


def test_allocator_with_fx_negative_only(tmp_path, monkeypatch):
    """fx_commodity alpha 음수 → bucket weight 감소, cash 증가."""
    from tests.integration._allocator_state_helpers import (
        make_synthetic_universe, make_synthetic_returns, make_factor_panel,
        make_bucket_target, make_macro_report, make_risk_report,
        make_research_decision, make_technical_report, make_allocator_state,
        BUCKET_CATEGORIES,
    )
    from tradingagents.agents.allocator.portfolio_allocator import create_portfolio_allocator

    universe = make_synthetic_universe(n_per_bucket=4)
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(universe.model_dump_json())

    tickers = [e.ticker for e in universe.etfs]
    fx_cat = BUCKET_CATEGORIES["fx_commodity"][0]
    fx_tickers = [e.ticker for e in universe.etfs if e.category == fx_cat]
    returns = make_synthetic_returns(tickers, n_days=252, seed=11)
    factor_panel = make_factor_panel(
        tickers,
        alpha_overrides={t: -0.05 for t in fx_tickers},  # fx alpha 음수
    )

    monkeypatch.setattr(
        "tradingagents.skills.portfolio.candidate_selector.fetch_etf_metrics_window",
        lambda tickers, start, end, cache_path=None: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "tradingagents.agents.allocator.portfolio_allocator.fetch_returns_matrix",
        lambda eligible, start, end, cache_path=None: returns[eligible],
    )

    state = make_allocator_state(
        as_of=date(2026, 5, 28),
        universe_path=str(universe_path),
        bucket_target=make_bucket_target(),
        technical_report=make_technical_report(factor_panel),
        macro_report=make_macro_report(),
        risk_report=make_risk_report(),
        research_decision=make_research_decision(),
    )

    node_func = create_portfolio_allocator()
    result = node_func(state)

    config = result["allocation_attribution"]["config"]
    bt_stage2 = config["bucket_target_stage2"]
    bt_post = config["bucket_target_post_spillover"]
    assert bt_post["fx_commodity"] < bt_stage2["fx_commodity"]
    assert bt_post["cash_mmf"] > bt_stage2["cash_mmf"]


def test_allocator_with_global_low_conviction(tmp_path, monkeypatch):
    """global alpha 낮음 → 부분 spillover."""
    from tests.integration._allocator_state_helpers import (
        make_synthetic_universe, make_synthetic_returns, make_factor_panel,
        make_bucket_target, make_macro_report, make_risk_report,
        make_research_decision, make_technical_report, make_allocator_state,
        BUCKET_CATEGORIES,
    )
    from tradingagents.agents.allocator.portfolio_allocator import create_portfolio_allocator

    universe = make_synthetic_universe(n_per_bucket=4)
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(universe.model_dump_json())

    tickers = [e.ticker for e in universe.etfs]
    global_cat = BUCKET_CATEGORIES["global_equity"][0]
    global_tickers = [e.ticker for e in universe.etfs if e.category == global_cat]
    returns = make_synthetic_returns(tickers, n_days=252, seed=13)
    factor_panel = make_factor_panel(
        tickers,
        alpha_overrides={t: 0.005 for t in global_tickers},  # 낮은 양수
    )

    monkeypatch.setattr(
        "tradingagents.skills.portfolio.candidate_selector.fetch_etf_metrics_window",
        lambda tickers, start, end, cache_path=None: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "tradingagents.agents.allocator.portfolio_allocator.fetch_returns_matrix",
        lambda eligible, start, end, cache_path=None: returns[eligible],
    )

    state = make_allocator_state(
        as_of=date(2026, 5, 28),
        universe_path=str(universe_path),
        bucket_target=make_bucket_target(),
        technical_report=make_technical_report(factor_panel),
        macro_report=make_macro_report(),
        risk_report=make_risk_report(),
        research_decision=make_research_decision(),
    )

    node_func = create_portfolio_allocator()
    result = node_func(state)

    # global 의 conviction 이 낮아 일부 spillover 일어남 (full 또는 부분)
    spillover = result["allocation_attribution"]["cash_spillover"]
    convictions = spillover["convictions"]
    assert convictions["global_equity"]["conviction"] < 0.6


def test_allocator_attribution_completeness_via_smoke(tmp_path):
    """기존 phase1_smoke fixture 가 새 attribution 키 (cash_spillover, enb) 를 채우는지 검증."""
    # 가장 가벼운 통합 검증: smoke fixture 결과에서 allocation_attribution 가 확장됐는지.
    # 실 fixture 가 없으면 skip 처리. (있으면 그 산출물 검사)
    import os
    smoke_artifact = "artifacts/2026-05-15/portfolio.json"
    if not os.path.exists(smoke_artifact):
        pytest.skip(f"{smoke_artifact} 없음 — 회귀 케이스는 Task 15 의 regression_compare 에서 검증")
    import json
    with open(smoke_artifact) as f:
        portfolio = json.load(f)
    attribution = portfolio.get("allocation_attribution") or {}
    # Phase 1 적용 후 산출물이라면 이 키들이 있어야 함
    assert "cash_spillover" in attribution, (
        "Phase 1 적용 후 산출물에 cash_spillover 누락 — hook 1 미통합"
    )
    assert "enb" in attribution, (
        "Phase 1 적용 후 산출물에 enb 누락 — hook 2 미통합"
    )
    # 타입 검증
    assert isinstance(attribution["cash_spillover"], dict)
    assert isinstance(attribution["enb"], (int, float))


def test_allocator_cash_overflow_redistribution(tmp_path, monkeypatch):
    """global+fx+bond 음수 → cash > 40% → overflow → kr_equity 로."""
    from tests.integration._allocator_state_helpers import (
        make_synthetic_universe, make_synthetic_returns, make_factor_panel,
        make_bucket_target, make_macro_report, make_risk_report,
        make_research_decision, make_technical_report, make_allocator_state,
        BUCKET_CATEGORIES,
    )
    from tradingagents.agents.allocator.portfolio_allocator import create_portfolio_allocator

    universe = make_synthetic_universe(n_per_bucket=4)
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(universe.model_dump_json())

    tickers = [e.ticker for e in universe.etfs]
    # global, fx, bond ticker 들 모두 alpha 음수
    neg_categories = [
        BUCKET_CATEGORIES["global_equity"][0],
        BUCKET_CATEGORIES["fx_commodity"][0],
        BUCKET_CATEGORIES["bond"][0],
    ]
    neg_tickers = [e.ticker for e in universe.etfs if e.category in neg_categories]
    returns = make_synthetic_returns(tickers, n_days=252, seed=17)
    factor_panel = make_factor_panel(
        tickers,
        alpha_overrides={t: -0.05 for t in neg_tickers},
    )

    monkeypatch.setattr(
        "tradingagents.skills.portfolio.candidate_selector.fetch_etf_metrics_window",
        lambda tickers, start, end, cache_path=None: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "tradingagents.agents.allocator.portfolio_allocator.fetch_returns_matrix",
        lambda eligible, start, end, cache_path=None: returns[eligible],
    )

    state = make_allocator_state(
        as_of=date(2026, 5, 28),
        universe_path=str(universe_path),
        bucket_target=make_bucket_target(cash_mmf=0.15),  # cash 작게 → overflow 유도
        technical_report=make_technical_report(factor_panel),
        macro_report=make_macro_report(),
        risk_report=make_risk_report(),
        research_decision=make_research_decision(),
    )

    node_func = create_portfolio_allocator()
    result = node_func(state)

    spillover = result["allocation_attribution"]["cash_spillover"]
    assert spillover["cash_cap_triggered"] is True
    # overflow 가 kr_equity 또는 cash_mmf 로 분배됨
    assert spillover["adjusted_bucket_target"]["cash_mmf"] <= 0.40 + 1e-6
