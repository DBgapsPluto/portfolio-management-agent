import numpy as np
from tradingagents.skills.portfolio import bl_engine as be

def test_tier_score_and_mean_removal():
    buckets = ["b1", "b2", "b3", "b4"]
    ranking = {"b1": ("strong_OW", 1.0), "b2": ("OW", 1.0), "b3": ("UW", 1.0), "b4": ("strong_UW", 1.0)}
    s = be.tier_scores(buckets, ranking)
    assert abs(s.sum()) < 1e-12          # mean-removed → zero-sum
    assert s[0] > s[1] > s[2] > s[3]

def test_all_same_tier_gives_empty_views():
    buckets = ["b1", "b2", "b3"]
    ranking = {b: ("strong_OW", 0.9) for b in buckets}
    P, Q, conf = be.build_relative_views(buckets, ranking, base_spread=0.04)
    assert P.shape[0] == 0               # mean-removed → all zero → view=∅

def test_relative_view_zero_sum_and_magnitude():
    buckets = ["b1", "b2", "b3"]
    ranking = {"b1": ("strong_OW", 1.0), "b2": ("neutral", 0.0), "b3": ("strong_UW", 1.0)}
    P, Q, conf = be.build_relative_views(buckets, ranking, base_spread=0.04)
    assert P.shape == (2, 3)
    assert np.allclose(P.sum(axis=1), 0.0)
    assert np.all(np.abs(Q) <= 0.04 + 1e-9)

def test_conviction_capped_at_095():
    buckets = ["b1", "b2"]
    ranking = {"b1": ("strong_OW", 5.0), "b2": ("strong_UW", 5.0)}   # >0.95 input
    P, Q, conf = be.build_relative_views(buckets, ranking, base_spread=0.04)
    assert np.all(conf <= 0.95 + 1e-9)
