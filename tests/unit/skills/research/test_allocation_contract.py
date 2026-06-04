"""allocation_contract investability projection."""
import pytest

from tradingagents.schemas.allocation_contract import InvestabilitySnapshot
from tradingagents.skills.portfolio.bucket_sync import ContractInfeasibleError
from tradingagents.skills.research.allocation_contract import (
    build_allocation_contract,
    build_envelope_around_center,
    compute_implied_bucket_returns,
    compute_investability,
    project_investability_risk_overflow,
)
from tradingagents.skills.research.factor_to_bucket import BUCKETS, INITIAL_BASELINE


def _uniform_prior() -> dict[str, float]:
    w = 1.0 / len(BUCKETS)
    return {b: w for b in BUCKETS}


def test_thin_universe_zeros_bucket_and_adds_cash():
    prior = dict(INITIAL_BASELINE)
    prior["cyclical_commodity_fx"] = 0.12
    inv = {
        b: InvestabilitySnapshot(
            n_eligible=0 if b == "cyclical_commodity_fx" else 3,
            n_selectable=0 if b == "cyclical_commodity_fx" else 3,
            max_realizable_weight=prior.get(b, 0.0),
        )
        for b in BUCKETS
    }
    feasible, binding, _audit = project_investability_risk_overflow(prior, inv)
    assert binding["cyclical_commodity_fx"] == "thin_universe"
    assert feasible["cyclical_commodity_fx"] == pytest.approx(0.0, abs=1e-9)
    assert sum(feasible.values()) == pytest.approx(1.0, abs=1e-6)


def test_single_etf_cap():
    prior = _uniform_prior()
    prior["precious_metals"] = 0.15
    eligible = {b: ["A", "B", "C"] for b in BUCKETS}
    eligible["precious_metals"] = ["GOLD"]
    inv = compute_investability(prior, eligible, single_etf_cap=0.05)
    assert inv["precious_metals"].max_realizable_weight == pytest.approx(0.05)


def test_build_contract_without_universe_matches_prior():
    prior = dict(INITIAL_BASELINE)
    contribs = {"F1_growth": {b: 0.01 for b in BUCKETS}}
    contract = build_allocation_contract(
        prior_weights=prior,
        bond_tips_share=0.2,
        universe=None,
        as_of=None,
        factor_contributions=contribs,
    )
    assert contract.prior_weights == pytest.approx(prior, abs=1e-6)
    assert contract.feasible_weights == pytest.approx(prior, abs=1e-6)
    assert sum(contract.implied_bucket_returns.values()) != 0.0


def test_envelope_lo_le_hi_when_max_realizable_below_center_minus_band():
    prior = dict(INITIAL_BASELINE)
    prior["precious_metals"] = 0.25
    inv = {
        b: InvestabilitySnapshot(n_eligible=3, max_realizable_weight=prior.get(b, 0.0))
        for b in BUCKETS
    }
    inv["precious_metals"] = InvestabilitySnapshot(
        n_eligible=1, n_selectable=1, max_realizable_weight=0.05,
    )
    feasible, _, _ = project_investability_risk_overflow(prior, inv)
    envelope = build_envelope_around_center(
        feasible, band=0.02, investability=inv,
    )
    env = envelope["precious_metals"]
    assert env.lo <= env.hi + 1e-12


def test_implied_returns_clipped():
    contribs = {"F1_growth": {"kr_equity": 2.0}}
    implied = compute_implied_bucket_returns(contribs, scale=0.10, clip=0.15)
    assert implied["kr_equity"] == pytest.approx(0.15)


def test_no_positive_alpha_zeros_bucket():
    prior = dict(INITIAL_BASELINE)
    prior["cash_mmf"] = 0.12
    eligible = {b: ["X"] for b in BUCKETS}
    inv = compute_investability(
        prior,
        eligible,
        single_etf_cap=0.05,
        alpha_scores_by_bucket={"cash_mmf": {"X": 0.0}},
    )
    assert inv["cash_mmf"].n_selectable == 0
    assert inv["cash_mmf"].max_realizable_weight == pytest.approx(0.0)


def test_cash_not_selectable_routes_lost_to_other_buckets():
    prior = _uniform_prior()
    prior["cash_mmf"] = 0.12
    prior["kr_equity"] = 0.15
    inv = {
        b: InvestabilitySnapshot(
            n_eligible=1,
            n_selectable=0 if b == "cash_mmf" else 1,
            max_realizable_weight=0.0 if b == "cash_mmf" else prior.get(b, 0.0),
        )
        for b in BUCKETS
    }
    feasible, binding, audit = project_investability_risk_overflow(prior, inv)
    assert binding["cash_mmf"] == "no_positive_alpha"
    assert feasible["cash_mmf"] == pytest.approx(0.0, abs=1e-9)
    assert audit.get("lost_routed_skip_cash")
    assert sum(feasible.values()) == pytest.approx(1.0, abs=1e-6)


def test_contract_infeasible_when_no_selectable_recipient():
    prior = _uniform_prior()
    prior["cash_mmf"] = 0.20
    inv = {
        b: InvestabilitySnapshot(
            n_eligible=1,
            n_selectable=0,
            max_realizable_weight=0.0,
        )
        for b in BUCKETS
    }
    with pytest.raises(ContractInfeasibleError):
        project_investability_risk_overflow(prior, inv)
