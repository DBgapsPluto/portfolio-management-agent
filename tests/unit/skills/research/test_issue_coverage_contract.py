"""Map design issues I1–I8 to implemented mechanisms (contract path)."""
from __future__ import annotations

import inspect

import pytest

from tradingagents.agents.allocator import portfolio_allocator as pa
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.schemas.allocation_contract import (
    AllocationContract,
    BucketEnvelope,
    ThemeLimit,
)
from tradingagents.skills.portfolio import bl_views
from tradingagents.skills.portfolio.contract_stage3 import (
    apply_theme_portfolio_limits,
    build_implementation_alignment,
    contract_stage3_active,
)
from tradingagents.skills.research.allocation_contract import DEFAULT_THEME_LIMITS
from tradingagents.skills.research.factor_to_bucket import BUCKETS, INITIAL_BASELINE


def _minimal_contract() -> AllocationContract:
    w = dict(INITIAL_BASELINE)
    env = {b: BucketEnvelope(lo=max(0.0, w[b] - 0.02), hi=min(1.0, w[b] + 0.02)) for b in BUCKETS}
    return AllocationContract(
        prior_weights=dict(w),
        feasible_weights=dict(w),
        envelope=env,
        theme_limits=list(DEFAULT_THEME_LIMITS),
        implied_bucket_returns={"kr_equity": 0.08, "cash_mmf": 0.025},
        bond_tips_share=0.2,
    )


class TestIssueCoverage:
    """Each test names the issue ID and asserts the mitigation exists in code."""

    def test_i1_theme_limit_gold_cap(self):
        """I1: theme collapse (gold 100% in precious) → portfolio theme cap."""
        assert any(t.sub_category == "gold" for t in DEFAULT_THEME_LIMITS)
        weights = {"G1": 0.60, "G2": 0.10, "C1": 0.30}
        lookup = {"G1": "gold", "G2": "gold", "C1": "equity"}
        capped, events = apply_theme_portfolio_limits(
            weights,
            [ThemeLimit(sub_category="gold", max_portfolio_share=0.50)],
            lookup,
            cash_tickers=["C1"],
        )
        gold_sum = sum(capped[t] for t in ("G1", "G2"))
        assert gold_sum <= 0.50 * sum(weights.values()) + 1e-6
        assert events

    def test_i2_prior_vs_feasible_alignment(self):
        """I2: bucket L1 drift → prior/feasible/realized alignment block."""
        contract = _minimal_contract()
        contract.prior_weights["precious_metals"] = 0.20
        contract.feasible_weights["precious_metals"] = 0.05
        align = build_implementation_alignment(
            contract,
            realized={"precious_metals": 0.06, **{b: contract.feasible_weights[b] for b in BUCKETS if b != "precious_metals"}},
        )
        assert "drift_prior_to_feasible_pp" in align
        assert align["drift_prior_to_feasible_pp"]["precious_metals"] == pytest.approx(-15.0, abs=0.1)

    def test_i3_bl_uses_contract_returns(self):
        """I3: BL dual story → contract implied_bucket_returns override rulebook."""
        sig = inspect.signature(bl_views.generate_bl_views)
        assert "bucket_returns_override" in sig.parameters
        views, confs, _ = bl_views.generate_bl_views(
            scenario="goldilocks",
            regime_confidence=0.8,
            candidates={"kr_equity": ["A1"]},
            bucket_returns_override={"kr_equity": 0.11},
        )
        assert views["A1"] == pytest.approx(0.11)
        assert confs

    def test_i4_unified_cov_path(self):
        """I4: selection σ vs optimization Σ → shared factor-proxy blend helpers."""
        from tradingagents.skills.portfolio import cov_estimator

        assert hasattr(cov_estimator, "compute_pairwise_selection_cov")
        assert hasattr(cov_estimator, "blend_cov_with_factor_proxy")
        src = inspect.getsource(pa.create_portfolio_allocator)
        assert "blend_cov_with_factor_proxy" in src
        assert "compute_pairwise_selection_cov" in src

    def test_i5_spillover_disabled_in_contract_mode(self):
        """I5: spill vs rebalance → spill skipped when contract active."""
        assert DEFAULT_CONFIG["allocation_contract_enabled"] is True
        assert "stage3_cash_spillover_enabled" not in DEFAULT_CONFIG
        src = inspect.getsource(pa.create_portfolio_allocator)
        assert "stage3_cash_spillover_enabled" in src
        assert '"skipped": True' in src or "'skipped': True" in src

    def test_i6_investability_in_contract_schema(self):
        """I6: thin buckets → investability projection in AllocationContract."""
        contract = _minimal_contract()
        assert contract.binding_stage2 is not None
        assert contract.investability is not None
        assert "envelope" in AllocationContract.model_fields

    def test_i7_contract_simplifies_stage3(self):
        """I7: complexity → fixed HRP, no scenario boost, envelope bounds."""
        assert DEFAULT_CONFIG["contract_optimizer_method"] == "hrp"
        assert "stage3_scenario_boost_enabled" not in DEFAULT_CONFIG
        sig = inspect.signature(pa._build_sector_mapper_and_bounds)
        assert "bucket_envelope" in sig.parameters
        src = inspect.getsource(pa.create_portfolio_allocator)
        assert "contract_fixed_method" in src
        assert "boost_scale" in src

    def test_i8_stage3_llm_shadow_default(self):
        """I8: LLM overlay gate → Stage 3 shadow by default."""
        assert DEFAULT_CONFIG["stage3_llm_overlay_mode"] == "shadow"

    def test_contract_stage3_active_requires_contract(self):
        class _RD:
            allocation_contract = _minimal_contract()

        assert contract_stage3_active(_RD(), allocation_contract_enabled=True)
        assert not contract_stage3_active(None, allocation_contract_enabled=True)
