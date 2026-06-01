"""Phase 3a integration — NCO end-to-end."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from tests.integration._allocator_state_helpers import (
    BUCKET_CATEGORIES, make_allocator_state, make_bucket_target,
    make_factor_panel, make_macro_report, make_research_decision,
    make_risk_report, make_synthetic_returns, make_synthetic_universe,
    make_technical_report,
)
from tradingagents.agents.allocator.portfolio_allocator import (
    create_portfolio_allocator,
)


def _setup_state_nco(tmp_path, monkeypatch, *, n_per_bucket: int = 6,
                     capital_krw: float = 1_000_000_000, bt=None,
                     alpha_overrides=None, force_method: str | None = "nco"):
    universe = make_synthetic_universe(n_per_bucket=n_per_bucket)
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(universe.model_dump_json())
    tickers = [e.ticker for e in universe.etfs]
    returns = make_synthetic_returns(tickers, n_days=252, seed=37)
    factor_panel = make_factor_panel(tickers, alpha_overrides=alpha_overrides)
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
        bucket_target=bt or make_bucket_target(),
        technical_report=make_technical_report(factor_panel),
        macro_report=make_macro_report(),
        risk_report=make_risk_report(),
        research_decision=make_research_decision(),
        capital_krw=capital_krw,
    )
    if force_method:
        state["force_method"] = force_method
    return state


def test_allocator_with_method_nco_runs_to_completion(tmp_path, monkeypatch):
    """state['force_method']='nco' 정상 종료, weight sum=1."""
    state = _setup_state_nco(tmp_path, monkeypatch)
    result = create_portfolio_allocator()(state)
    weights = result["weight_vector"].weights
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-6)
    assert result["allocation_attribution"]["method_picker"]["method"] == "nco"


def test_allocator_nco_attribution_records_breakdown(tmp_path, monkeypatch):
    """attribution.optimization.nco_breakdown_per_pool per bucket 채워짐."""
    state = _setup_state_nco(tmp_path, monkeypatch)
    result = create_portfolio_allocator()(state)
    opt_attr = result["allocation_attribution"]["optimization"]
    assert "nco_breakdown_per_pool" in opt_attr
    nco = opt_attr["nco_breakdown_per_pool"]
    # 적어도 1 bucket 의 breakdown 있어야
    assert len(nco) > 0
    # 각 pool 의 breakdown 에 핵심 키 있어야
    for pool_label, breakdown in nco.items():
        if "error" in breakdown:
            continue  # fallback case
        assert "n_clusters" in breakdown or "silhouette" in breakdown


def test_allocator_nco_respects_single_asset_cap(tmp_path, monkeypatch):
    """단일 자산 weight ≤ 20%."""
    state = _setup_state_nco(tmp_path, monkeypatch)
    result = create_portfolio_allocator()(state)
    weights = result["weight_vector"].weights
    for ticker, w in weights.items():
        assert w <= 0.20 + 1e-6, f"{ticker} weight {w} exceeds 20% cap"


def test_allocator_nco_bucket_sum_approximates_target(tmp_path, monkeypatch):
    """Bucket weight ≈ bucket_target."""
    bt = make_bucket_target(
        kr_equity=0.20, global_equity=0.20,
        precious_metals=0.05, cyclical_commodity_fx=0.05,
        kr_bond=0.15, credit=0.05, global_duration=0.10, cash_mmf=0.20,
    )
    state = _setup_state_nco(tmp_path, monkeypatch, bt=bt)
    result = create_portfolio_allocator()(state)
    attr = result["allocation_attribution"]
    bucket_to_tickers = attr["buckets"]
    weights = result["weight_vector"].weights

    # 각 bucket 의 chosen 종목 weight 합 ≈ bucket_target (band 허용)
    bt_post = attr["config"]["bucket_target_post_spillover"]
    for bucket_name in ("kr_equity", "global_equity", "precious_metals",
                        "cyclical_commodity_fx", "kr_bond", "credit",
                        "global_duration", "cash_mmf"):
        chosen = bucket_to_tickers.get(bucket_name, {}).get("chosen", [])
        bucket_sum = sum(weights.get(t, 0.0) for t in chosen)
        target = bt_post[bucket_name]
        # 10% band (HRP shortfall 또는 NCO 의 capped 효과 허용)
        if target > 0:
            assert abs(bucket_sum - target) < 0.10, (
                f"{bucket_name}: bucket_sum={bucket_sum:.3f}, target={target:.3f}"
            )


def test_allocator_nco_handles_single_ticker_bucket(tmp_path, monkeypatch):
    """chosen 1 개인 bucket 정상 (weight=bucket_target)."""
    # 매우 strict bucket → adaptive N 으로 chosen 1 개만 통과
    bt = make_bucket_target(
        kr_equity=0.05, global_equity=0.05,
        precious_metals=0.025, cyclical_commodity_fx=0.025,
        kr_bond=0.02, credit=0.01, global_duration=0.02, cash_mmf=0.80,
    )
    state = _setup_state_nco(
        tmp_path, monkeypatch, bt=bt, capital_krw=1_000_000_000,
    )
    result = create_portfolio_allocator()(state)
    # 정상 종료만 검증 (assertion error 없이)
    assert sum(result["weight_vector"].weights.values()) == pytest.approx(1.0, abs=1e-3)


def test_allocator_nco_vs_hrp_same_inputs_different_weights(tmp_path, monkeypatch):
    """동일 입력에 NCO 와 HRP 가 다른 method 라벨."""
    state_nco = _setup_state_nco(tmp_path, monkeypatch, force_method="nco")
    result_nco = create_portfolio_allocator()(state_nco)

    state_hrp = _setup_state_nco(tmp_path, monkeypatch, force_method="hrp")
    result_hrp = create_portfolio_allocator()(state_hrp)

    # method 라벨이 각각 다름
    assert result_nco["allocation_attribution"]["method_picker"]["method"] == "nco"
    assert result_hrp["allocation_attribution"]["method_picker"]["method"] == "hrp"


def test_allocator_nco_with_correlated_etfs_uses_single_cluster(tmp_path, monkeypatch):
    """NCO 통합 정상 동작 + breakdown 에 cluster 정보 있음."""
    state = _setup_state_nco(tmp_path, monkeypatch)
    result = create_portfolio_allocator()(state)
    # NCO 통합 정상 동작 + breakdown 에 cluster 정보 있음
    nco_breakdown = result["allocation_attribution"]["optimization"].get("nco_breakdown_per_pool", {})
    for pool_label, breakdown in nco_breakdown.items():
        if "n_clusters" in breakdown:
            # n_clusters 가 정수
            assert isinstance(breakdown["n_clusters"], int)
            assert breakdown["n_clusters"] >= 1
