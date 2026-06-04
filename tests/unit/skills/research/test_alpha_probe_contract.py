"""P1-1 B: Stage 2 alpha probe kwargs align with Stage 3 allocator."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pandas as pd

from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills.portfolio.alpha_probe import compute_alpha_scores_for_eligible
from tradingagents.skills.research.factor_to_bucket import BUCKETS
from tests.integration._allocator_state_helpers import make_synthetic_universe


def test_probe_passes_boost_scale_and_technical_fields():
    universe = make_synthetic_universe(n_per_bucket=1)
    weights = {b: 1.0 / len(BUCKETS) for b in BUCKETS}
    target = BucketTarget(weights=weights, bond_tips_share=0.2, rationale="t")
    tech = {
        "risk_adjusted": {"T_kr_equity": 0.1},
        "trend_quant": {"T_kr_equity": 0.2},
        "extended": {"T_kr_equity": 0.3},
        "etf_states": {"T_kr_equity": "uptrend"},
    }

    tickers = [e.ticker for e in universe.etfs]
    with patch(
        "tradingagents.skills.portfolio.alpha_probe._compute_alpha_scores",
        return_value=({tickers[0]: 0.5}, {}),
    ) as mock_compute:
        with patch(
            "tradingagents.skills.portfolio.alpha_probe.fetch_returns_matrix",
            return_value=pd.DataFrame({t: [0.001] * 30 for t in tickers}),
        ):
            compute_alpha_scores_for_eligible(
                universe,
                target,
                date(2026, 5, 28),
                dominant_scenario="goldilocks",
                factor_scores={"F1_growth": 0.1},
                risk_adjusted=tech["risk_adjusted"],
                trend_quant=tech["trend_quant"],
                extended=tech["extended"],
                etf_states=tech["etf_states"],
                boost_scale=0.0,
            )
    _args, kwargs = mock_compute.call_args
    assert kwargs["boost_scale"] == 0.0
    assert kwargs["risk_adjusted"] == tech["risk_adjusted"]
    assert kwargs["trend_quant"] == tech["trend_quant"]
    assert kwargs["extended"] == tech["extended"]
    assert kwargs["etf_states"] == tech["etf_states"]
