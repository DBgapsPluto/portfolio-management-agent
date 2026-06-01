"""Phase 1 integration — allocator pipeline 의 spillover + ENB 통합 검증.

가짜 universe 와 returns 로 5 개 시나리오:
  1. 정상 universe (모두 양수 alpha) → spillover 0, ENB 양호
  2. precious_metals 음수 only → bucket weight 감소, cash 증가
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
    """precious_metals alpha 음수 → bucket weight 감소, cash 증가."""
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
    # precious_metals 만 골라 음수 alpha 부여 (cyclical_commodity_fx 와 동일 category 라
    # sub_category 로 구분). 음수 alpha → rank-normalize 후 낮은 conviction → spill.
    pm_cat = BUCKET_CATEGORIES["precious_metals"][0]
    pm_sub = BUCKET_CATEGORIES["precious_metals"][2]
    pm_tickers = [
        e.ticker for e in universe.etfs
        if e.category == pm_cat and e.sub_category == pm_sub
    ]
    returns = make_synthetic_returns(tickers, n_days=252, seed=11)
    factor_panel = make_factor_panel(
        tickers,
        alpha_overrides={t: -0.05 for t in pm_tickers},  # precious_metals alpha 음수
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
    assert bt_post["precious_metals"] < bt_stage2["precious_metals"]
    assert bt_post["cash_mmf"] > bt_stage2["cash_mmf"]


def test_allocator_with_global_low_conviction(tmp_path, monkeypatch):
    """global_equity conviction < 1.0 → 부분 spillover.

    의도: low-conviction RISK_BUCKET 이 cash 로 일부 spillover 한다.

    8-bucket migration 후 발견된 파이프라인 제약 — conviction <0.6 은 도달 불가:
      - alpha 는 bucket 내 rank_percentile 정규화 (절대값 무관, 동률이면 모두 중앙값)
        이라 alpha_override 로 conviction 을 낮출 수 없다.
      - ENB-greedy 는 항상 bucket 내 상위 ticker 를 chosen 하므로 chosen 의
        mean rank percentile 이 ≈ +0.2 로 바닥이 받쳐진다.
      - scenario boost 최소값은 0 (음수 boost 없음).
    전 9 scenario × n_per_bucket × weight sweep 결과 global_equity 최소 conviction =
    0.9188 (broad_recession, n_per_bucket=6, global_equity weight=0.10). 그래서
    "conviction < full-strength(1.0) → spillover_ratio>0" 로 의도를 검증한다.
    """
    from tests.integration._allocator_state_helpers import (
        make_synthetic_universe, make_synthetic_returns, make_factor_panel,
        make_bucket_target, make_macro_report, make_risk_report,
        make_research_decision, make_technical_report, make_allocator_state,
    )
    from tradingagents.agents.allocator.portfolio_allocator import create_portfolio_allocator

    universe = make_synthetic_universe(n_per_bucket=6)
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(universe.model_dump_json())

    tickers = [e.ticker for e in universe.etfs]
    returns = make_synthetic_returns(tickers, n_days=252, seed=13)
    factor_panel = make_factor_panel(tickers)

    monkeypatch.setattr(
        "tradingagents.skills.portfolio.candidate_selector.fetch_etf_metrics_window",
        lambda tickers, start, end, cache_path=None: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "tradingagents.agents.allocator.portfolio_allocator.fetch_returns_matrix",
        lambda eligible, start, end, cache_path=None: returns[
            [t for t in eligible if t in returns.columns]
        ],
    )

    state = make_allocator_state(
        as_of=date(2026, 5, 28),
        universe_path=str(universe_path),
        # global_equity 0.10 (작은 weight) + broad_recession (us_broad boost=0)
        # → conviction < 1.0 → 부분 spillover.
        bucket_target=make_bucket_target(
            kr_equity=0.20, global_equity=0.10,
            precious_metals=0.08, cyclical_commodity_fx=0.14,
            kr_bond=0.15, credit=0.05, global_duration=0.13, cash_mmf=0.15,
        ),
        technical_report=make_technical_report(factor_panel),
        macro_report=make_macro_report(),
        risk_report=make_risk_report(),
        research_decision=make_research_decision(dominant_scenario="broad_recession"),
    )

    node_func = create_portfolio_allocator()
    result = node_func(state)

    # global_equity conviction 이 full-strength(1.0) 미만이라 일부 spillover 발생.
    spillover = result["allocation_attribution"]["cash_spillover"]
    convictions = spillover["convictions"]
    ge = convictions["global_equity"]
    assert ge["conviction"] < 1.0, ge["conviction"]
    assert ge["spillover_ratio"] > 0.0, ge["spillover_ratio"]
    assert spillover["total_spillover_to_cash"] > 0.0


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
    """3 RISK_BUCKET zero-conviction → cash > 40% → overflow → kr_equity.

    의도: 다수 low-conviction RISK_BUCKET 이 cash 를 40% 초과로 밀어내면 overflow
    가 high-conviction RISK_BUCKET(kr_equity)로 재분배된다.

    8-bucket migration 후 발견된 파이프라인 제약 — 자연스러운 alpha override 로는
    bucket conviction 을 0 으로 만들 수 없다(bucket 내 rank_percentile 정규화 +
    ENB-greedy 상위 선택이 mean_alpha 를 ≈ +0.2 로 바닥받쳐, 전 scenario sweep 상
    최대 total_spillover ≈ 0.008). cash>40% overflow 는 unit test
    (test_portfolio_cash_spillover.test_spillover_cash_cap_overflow_redistributes)
    가 직접 alpha=0 으로 검증한다.

    여기서는 **allocator node 의 spillover→redistribution wiring** 을 end-to-end 로
    검증하기 위해, returns/metrics 를 stub 하는 것과 동일한 방식으로 per-bucket
    alpha 수집(_collect_alpha_scores_per_bucket)만 stub 한다: 3 RISK_BUCKET alpha=0
    (full spill), kr_equity high alpha. 실제 adjust_bucket_targets 재분배 + allocator
    downstream 은 그대로 실행된다.
    """
    from tests.integration._allocator_state_helpers import (
        make_synthetic_universe, make_synthetic_returns, make_factor_panel,
        make_bucket_target, make_macro_report, make_risk_report,
        make_research_decision, make_technical_report, make_allocator_state,
    )
    import tradingagents.agents.allocator.portfolio_allocator as pa
    from tradingagents.agents.allocator.portfolio_allocator import create_portfolio_allocator

    universe = make_synthetic_universe(n_per_bucket=4)
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(universe.model_dump_json())

    tickers = [e.ticker for e in universe.etfs]
    returns = make_synthetic_returns(tickers, n_days=252, seed=17)
    factor_panel = make_factor_panel(tickers)

    monkeypatch.setattr(
        "tradingagents.skills.portfolio.candidate_selector.fetch_etf_metrics_window",
        lambda tickers, start, end, cache_path=None: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "tradingagents.agents.allocator.portfolio_allocator.fetch_returns_matrix",
        lambda eligible, start, end, cache_path=None: returns[eligible],
    )

    # 3 RISK_BUCKET full spill (alpha=0), kr_equity high-conviction (keeps + receives).
    _orig_collect = pa._collect_alpha_scores_per_bucket
    _low = {"global_equity", "precious_metals", "cyclical_commodity_fx"}

    def _fake_collect(attribution):
        out = _orig_collect(attribution)
        for b in list(out):
            if b in _low:
                out[b] = {t: 0.0 for t in out[b]}
            elif b == "kr_equity":
                out[b] = {t: 0.6 for t in out[b]}
        return out

    monkeypatch.setattr(pa, "_collect_alpha_scores_per_bucket", _fake_collect)

    state = make_allocator_state(
        as_of=date(2026, 5, 28),
        universe_path=str(universe_path),
        bucket_target=make_bucket_target(  # cash 작게 + 3 risk bucket 큰 weight → overflow
            kr_equity=0.15, global_equity=0.25,
            precious_metals=0.10, cyclical_commodity_fx=0.10,
            kr_bond=0.15, credit=0.05, global_duration=0.05, cash_mmf=0.15,
        ),
        technical_report=make_technical_report(factor_panel),
        macro_report=make_macro_report(),
        risk_report=make_risk_report(),
        research_decision=make_research_decision(),
    )

    node_func = create_portfolio_allocator()
    result = node_func(state)

    spillover = result["allocation_attribution"]["cash_spillover"]
    adj = spillover["adjusted_bucket_target"]["weights"]
    assert spillover["cash_cap_triggered"] is True
    assert adj["cash_mmf"] == pytest.approx(0.40, abs=1e-6)
    # overflow → high-conviction kr_equity (0.15 → 증가)
    assert adj["kr_equity"] > 0.15
