"""Stage 4 Phase 2 — risk_judge 통합 검증.

3 lens (tail/concentration/macro_conditional) 모두 deterministic.
인프라 wiring + lens 합의 + apply_risk_overlay 흐름 검증.
"""
from types import SimpleNamespace

import numpy as np
import pandas as pd

from tradingagents.agents.managers.risk_judge import create_risk_judge
from tradingagents.schemas.portfolio import (
    BucketTarget, CandidateSet, OptimizationMethod, WeightVector,
)


_TICKERS = [f"A{i:03d}" for i in range(1, 11)]


def _bucket():
    return BucketTarget(
        kr_equity=0.20, global_equity=0.20, fx_commodity=0.20,
        bond=0.20, cash_mmf=0.20, rationale="test",
    )


def _wv():
    return WeightVector(
        method=OptimizationMethod.MIN_VARIANCE,
        weights={t: 0.10 for t in _TICKERS},
        rationale="1st result",
    )


def _candidates():
    return CandidateSet(
        bucket_to_tickers={
            "kr_equity": _TICKERS[0:2], "global_equity": _TICKERS[2:4],
            "fx_commodity": _TICKERS[4:6], "bond": _TICKERS[6:8],
            "cash_mmf": _TICKERS[8:10],
        },
        selection_criteria="t", total_candidates=10,
    )


def _state_calm():
    return {
        "as_of_date": "2026-05-18",
        "weight_vector": _wv(),
        "candidate_set": _candidates(),
        "bucket_target": _bucket(),
        "risk_report": SimpleNamespace(
            systemic_score=SimpleNamespace(score=4.0, regime="risk_on"),
            vix_term=SimpleNamespace(regime="contango"),
            funding_stress=SimpleNamespace(regime="calm"),
        ),
        "macro_report": SimpleNamespace(
            regime=SimpleNamespace(quadrant="growth_disinflation", confidence=0.8),
        ),
        "research_decision": SimpleNamespace(
            dominant_scenario="goldilocks", conviction="high",
        ),
        "technical_report": SimpleNamespace(correlation_clusters=[]),
    }


def _state_critical():
    state = _state_calm()
    state["risk_report"] = SimpleNamespace(
        systemic_score=SimpleNamespace(score=9.5, regime="risk_off"),
        vix_term=SimpleNamespace(regime="backwardation"),
        funding_stress=SimpleNamespace(regime="stress"),
    )
    state["research_decision"] = SimpleNamespace(
        dominant_scenario="global_credit", conviction="high",
    )
    return state


def test_calm_market_yields_empty_overlay(monkeypatch):
    rng = np.random.default_rng(0)
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    fake_returns = pd.DataFrame(
        {t: rng.normal(0.0005, 0.005, 300) for t in _TICKERS}, index=idx,
    )
    monkeypatch.setattr(
        "tradingagents.agents.managers.risk_judge.fetch_returns_matrix",
        lambda *a, **kw: fake_returns,
    )

    node = create_risk_judge()
    out = node(_state_calm())

    overlay = out["risk_overlay"]
    assert overlay.strength_applied == 0.0 or overlay.is_empty()
    assert out["weight_vector"].weights == _wv().weights


def test_critical_state_triggers_overlay(monkeypatch):
    rng = np.random.default_rng(42)
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    fake_returns = pd.DataFrame(
        {t: rng.normal(0.0, 0.025, 300) for t in _TICKERS}, index=idx,
    )
    monkeypatch.setattr(
        "tradingagents.agents.managers.risk_judge.fetch_returns_matrix",
        lambda *a, **kw: fake_returns,
    )

    node = create_risk_judge()
    out = node(_state_critical())

    overlay = out["risk_overlay"]
    assert overlay.strength_applied > 0
    assert len(overlay.lens_concerns) == 3
    assert overlay.risk_asset_multiplier < 1.0


def test_missing_stage3_input_returns_empty():
    """Stage 3 입력 부재 시 empty overlay + weight_vector 변경 없음."""
    node = create_risk_judge()
    out = node({"as_of_date": "2026-05-18"})
    assert out["risk_overlay"].is_empty()
    assert "weight_vector" not in out
