"""Unit tests — contract_stage3 helpers."""
from __future__ import annotations

import pytest

from tradingagents.schemas.allocation_contract import ThemeLimit
from tradingagents.skills.portfolio.contract_stage3 import (
    apply_theme_portfolio_limits,
    build_implementation_alignment,
    contract_stage3_active,
    enforce_stage3_mandate_qp,
    realized_bucket_weights,
    redistribute_subcategory_excess_to_cash,
)
from tradingagents.skills.research.factor_to_bucket import RISK_BUCKETS
from tradingagents.skills.research.allocation_contract import build_allocation_contract
from tradingagents.skills.research.factor_to_bucket import BUCKETS, INITIAL_BASELINE


def _contract():
    prior = dict(INITIAL_BASELINE)
    return build_allocation_contract(
        prior_weights=prior,
        bond_tips_share=0.0,
        universe=None,
        as_of=None,
        factor_contributions={"F1_growth": {b: 0.01 for b in BUCKETS}},
    )


def test_contract_stage3_active():
    class _RD:
        allocation_contract = _contract()

    assert contract_stage3_active(_RD(), allocation_contract_enabled=True)
    assert not contract_stage3_active(None, allocation_contract_enabled=True)
    assert not contract_stage3_active(_RD(), allocation_contract_enabled=False)


def test_realized_bucket_weights():
    w = {"A1": 0.12, "A2": 0.08, "B1": 0.30}
    buckets = {"kr_equity": ["A1", "A2"], "global_equity": ["B1"]}
    realized = realized_bucket_weights(w, buckets)
    assert realized["kr_equity"] == pytest.approx(0.20)
    assert realized["global_equity"] == pytest.approx(0.30)


def test_build_implementation_alignment_envelope_flags():
    contract = _contract()
    realized = {
        b: (env.lo + env.hi) / 2.0
        for b, env in contract.envelope.items()
    }
    align = build_implementation_alignment(contract, realized)
    assert align["all_buckets_within_envelope"] is True
    assert "drift_prior_to_feasible_pp" in align


def test_apply_theme_portfolio_limits_to_cash():
    weights = {"G1": 0.40, "C1": 0.10}
    capped, events = apply_theme_portfolio_limits(
        weights,
        [ThemeLimit(sub_category="gold", max_portfolio_share=0.25)],
        {"G1": "gold", "C1": "mmf"},
        cash_tickers=["C1"],
    )
    assert sum(capped.values()) == pytest.approx(0.50, abs=1e-6)
    assert events[0]["routed_to_cash"] is True


def test_enforce_stage3_mandate_qp_triggers_on_high_risk():
    w_ref = dict(INITIAL_BASELINE)
    b2t = {b: [f"T_{b}"] for b in BUCKETS}
    weights = {f"T_{b}": (0.25 if b in RISK_BUCKETS else 0.0) for b in BUCKETS}
    weights["T_cash_mmf"] = 0.25
    out, audit = enforce_stage3_mandate_qp(weights, b2t, w_ref, unallocated_mass=0.0)
    assert audit["triggered"] is True
    post_risk = sum(
        realized_bucket_weights(out, b2t).get(b, 0) for b in RISK_BUCKETS
    )
    assert post_risk <= 0.70 + 0.02


def test_redistribute_subcategory_excess_to_cash():
    weights = {"G1": 0.15, "C1": 0.05}
    out = redistribute_subcategory_excess_to_cash(
        weights, ["G1"], excess=0.05, cash_tickers=["C1"],
    )
    assert out["C1"] == pytest.approx(0.10, abs=1e-6)
    assert out["G1"] == pytest.approx(0.15, abs=1e-6)
