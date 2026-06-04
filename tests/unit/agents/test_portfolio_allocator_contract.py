"""Stage 3 unit tests — allocation contract path (allocator internals)."""
from __future__ import annotations

import pytest

from tradingagents.agents.allocator.portfolio_allocator import (
    _build_sector_mapper_and_bounds,
)
from tradingagents.schemas.allocation_contract import BucketEnvelope
from tradingagents.schemas.portfolio import BucketTarget, CandidateSet
from tradingagents.skills.portfolio.bl_views import generate_bl_views
from tradingagents.skills.portfolio.contract_stage3 import contract_stage3_active


def _candidates() -> CandidateSet:
    return CandidateSet(
        bucket_to_tickers={
            "kr_equity": ["A0"],
            "global_equity": ["A1"],
            "precious_metals": ["A2"],
            "cyclical_commodity_fx": ["A3"],
            "kr_bond": ["A4"],
            "credit": ["A5"],
            "global_duration": ["A6"],
            "cash_mmf": ["A7"],
        },
        selection_criteria="t",
        total_candidates=8,
    )


def test_contract_stage3_active_helper():
    assert not contract_stage3_active(None, allocation_contract_enabled=True)

    class _RD:
        allocation_contract = object()

    assert contract_stage3_active(_RD(), allocation_contract_enabled=True)


def test_envelope_widens_on_retry():
    target = BucketTarget(
        weights={b: 0.125 for b in (
            "kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx",
            "kr_bond", "credit", "global_duration", "cash_mmf",
        )},
        rationale="t",
    )
    env = {
        "kr_equity": BucketEnvelope(lo=0.10, hi=0.15),
        **{
            b: BucketEnvelope(lo=0.125, hi=0.125)
            for b in target.weights if b != "kr_equity"
        },
    }
    _, lo0, hi0 = _build_sector_mapper_and_bounds(
        _candidates(), target, 0, bucket_envelope=env,
    )
    _, lo1, hi1 = _build_sector_mapper_and_bounds(
        _candidates(), target, 1, bucket_envelope=env,
    )
    assert lo1["kr_equity"] < lo0["kr_equity"]
    assert hi1["kr_equity"] > hi0["kr_equity"]


def test_bl_views_contract_override_beats_rulebook():
    views, confs, _ = generate_bl_views(
        scenario="goldilocks",
        regime_confidence=0.9,
        candidates={"kr_equity": ["A0"]},
        bucket_returns_override={"kr_equity": 0.07},
    )
    assert views["A0"] == pytest.approx(0.07)
    assert len(confs) == 1
