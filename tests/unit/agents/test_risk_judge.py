"""risk_judge 가 apply_risk_overlay outcome 을 RiskOverlay 에 기록."""
from unittest.mock import patch

import numpy as np
import pandas as pd

from tradingagents.agents.managers.risk_judge import create_risk_judge
from tradingagents.schemas.portfolio import (
    BucketTarget, CandidateSet, OptimizationMethod, WeightVector,
)
from tradingagents.schemas.risk_overlay import RiskOverlay


def _state():
    tickers = [f"A{i:03d}" for i in range(1, 11)]
    rng = np.random.default_rng(7)
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    returns = pd.DataFrame(
        {t: rng.normal(0.0005, 0.005, 300) for t in tickers}, index=idx,
    )

    wv = WeightVector(
        method=OptimizationMethod.MIN_VARIANCE,
        weights={t: 0.10 for t in tickers}, rationale="1st",
    )
    cs = CandidateSet(
        bucket_to_tickers={
            "kr_equity":     tickers[0:2],
            "global_equity": tickers[2:4],
            "fx_commodity":  tickers[4:6],
            "bond":          tickers[6:8],
            "cash_mmf":      tickers[8:10],
        },
        selection_criteria="test", total_candidates=10,
    )
    bt = BucketTarget(
        kr_equity=0.20, global_equity=0.20, fx_commodity=0.20,
        bond=0.20, cash_mmf=0.20, rationale="test",
    )
    return {
        "as_of_date": "2024-06-15",
        "weight_vector":     wv,
        "candidate_set":     cs,
        "bucket_target":     bt,
        "risk_report":       None,
        "macro_report":      None,
        "research_decision": None,
        "technical_report":  None,
    }, returns


def test_risk_judge_records_overlay_outcome_in_overlay_schema():
    """risk_judge 노드가 apply_risk_overlay 의 outcome 을 RiskOverlay 에 기록."""
    state, returns = _state()
    node = create_risk_judge()

    with patch(
        "tradingagents.agents.managers.risk_judge.fetch_returns_matrix",
        return_value=returns,
    ):
        # apply_risk_overlay 를 mock 해서 "relax_band" 반환하게 강제
        with patch(
            "tradingagents.agents.managers.risk_judge.apply_risk_overlay",
            return_value=(state["weight_vector"], "relax_band"),
        ):
            out = node(state)

    overlay = out["risk_overlay"]
    assert isinstance(overlay, RiskOverlay)
    assert overlay.overlay_apply_outcome == "relax_band", (
        f"expected relax_band, got {overlay.overlay_apply_outcome}"
    )


def test_risk_judge_skip_when_inputs_missing_sets_primary_success():
    """input 누락 시 RiskOverlay.no_concerns() → outcome=primary_success default."""
    node = create_risk_judge()
    out = node({"as_of_date": "2024-06-15"})  # weight_vector etc. 없음
    assert out["risk_overlay"].overlay_apply_outcome == "primary_success"
