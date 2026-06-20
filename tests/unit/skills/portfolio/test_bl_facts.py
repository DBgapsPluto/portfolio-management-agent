import numpy as np
import pandas as pd

from tradingagents.skills.portfolio.bl_facts import (
    prior_justification_facts,
    correlation_from_cov,
    bl_correlation_facts,
)


def test_prior_justification_lists_baseline():
    txt = prior_justification_facts("recession_inflation")
    assert "a5_gold_infl" in txt and "0.17" in txt   # 인플레헤지 금 (recession_inflation a5=0.17)


def test_prior_justification_unknown_quadrant_empty():
    assert prior_justification_facts("nonsense") == ""


def test_correlation_from_cov_is_unit_diagonal():
    Sigma = pd.DataFrame([[0.04, 0.02], [0.02, 0.09]], index=["x", "y"], columns=["x", "y"])
    C = correlation_from_cov(Sigma)
    assert abs(C.loc["x", "x"] - 1.0) < 1e-9 and abs(C.loc["y", "y"] - 1.0) < 1e-9
    assert abs(C.loc["x", "y"] - (0.02 / np.sqrt(0.04 * 0.09))) < 1e-9


def test_correlation_facts_top_pair_and_cluster_weight():
    keys = ["b1_kr_equity", "b3_global_tech", "a1_cash"]
    Corr = pd.DataFrame(
        [[1.0, 0.85, 0.1], [0.85, 1.0, 0.05], [0.1, 0.05, 1.0]],
        index=keys, columns=keys,
    )
    txt = bl_correlation_facts(
        Corr, weights={"b1_kr_equity": 0.2, "b3_global_tech": 0.18, "a1_cash": 0.1}
    )
    assert "b1_kr_equity" in txt and "b3_global_tech" in txt and "0.85" in txt
    assert "0.38" in txt   # cluster weight sum 0.2+0.18


def test_correlation_facts_no_weights_omits_cluster_line():
    keys = ["b1_kr_equity", "b3_global_tech"]
    Corr = pd.DataFrame([[1.0, 0.7], [0.7, 1.0]], index=keys, columns=keys)
    txt = bl_correlation_facts(Corr)
    assert "최고 상관쌍" in txt
    assert "클러스터 비중합" not in txt


def test_correlation_facts_empty_corr_empty_string():
    Corr = pd.DataFrame(index=[], columns=[])
    assert bl_correlation_facts(Corr) == ""
