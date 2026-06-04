"""P1-1 B: Stage 3 reuses Stage 2 alpha scores when provided."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills.portfolio.candidate_selector import select_etf_candidates
from tradingagents.skills.research.factor_to_bucket import BUCKETS
from tests.integration._allocator_state_helpers import (
    make_factor_panel,
    make_synthetic_returns,
    make_synthetic_universe,
)


def test_select_skips_compute_alpha_when_precomputed():
    universe = make_synthetic_universe(n_per_bucket=2)
    tickers = [e.ticker for e in universe.etfs]
    weights = {b: 0.0 for b in BUCKETS}
    weights["kr_equity"] = 1.0
    target = BucketTarget(weights=weights, bond_tips_share=0.0, rationale="t")
    kr_ticker = [t for t in tickers if t.startswith("A_0")][0]
    precomputed = {"kr_equity": {kr_ticker: 0.42}}

    with patch(
        "tradingagents.skills.portfolio.candidate_selector._compute_alpha_scores",
    ) as mock_compute:
        with patch(
            "tradingagents.skills.portfolio.candidate_selector.fetch_etf_metrics_window",
            return_value=pd.DataFrame(),
        ):
            with patch(
                "tradingagents.skills.portfolio.candidate_selector.select_by_enb_greedy",
                return_value=[kr_ticker],
            ):
                attr: dict = {}
                select_etf_candidates(
                    universe,
                    target,
                    as_of=date(2026, 5, 28),
                    returns=make_synthetic_returns(tickers, n_days=60),
                    factor_panel=make_factor_panel(tickers),
                    sigma=pd.DataFrame(0.01, index=tickers, columns=tickers),
                    capital_krw=1_000_000_000,
                    attribution=attr,
                    precomputed_alpha_scores_by_bucket=precomputed,
                )
    mock_compute.assert_not_called()
    assert attr["config"]["alpha_source"] == "stage2_precomputed"
    assert attr["buckets"]["kr_equity"]["alpha_source"] == "stage2_precomputed"
    assert attr["buckets"]["kr_equity"]["alpha_scores"][kr_ticker] == pytest.approx(
        0.42,
    )
