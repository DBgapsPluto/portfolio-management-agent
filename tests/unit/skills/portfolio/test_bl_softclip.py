import pytest
import pandas as pd
from tradingagents.skills.portfolio import bl_engine as be

def test_growth_bucket_soft_clipped_not_fallback():
    w = pd.Series({"b3_global_tech": 0.45, "a1_cash": 0.30, "a3_us_rates": 0.25})
    out = be.soft_clip(w, growth_keys={"b3_global_tech"}, growth_cap=0.30, defensive_cap=0.50)
    assert out["b3_global_tech"] <= 0.30 + 1e-9      # growth ceiling
    assert abs(out.sum() - 1.0) < 1e-9               # water-fill preserves sum

def test_defensive_bucket_higher_ceiling_no_false_trip():
    # recession a3 OW 0.40 — defensive ceiling 0.50 → NOT clipped (no false trip)
    w = pd.Series({"a3_us_rates": 0.40, "b1_kr_equity": 0.35, "a1_cash": 0.25})
    out = be.soft_clip(w, growth_keys={"b1_kr_equity"}, growth_cap=0.30, defensive_cap=0.50)
    # FALSE-1 invariant: a3 not CLIPPED (stays ≥ its 0.40 input), but may legitimately
    # receive water-fill up to its 0.50 ceiling. The real test is "not clipped", not "untouched".
    assert 0.40 <= out["a3_us_rates"] <= 0.50 + 1e-9            # defensive → not clipped
    assert out["b1_kr_equity"] <= 0.30 + 1e-9                    # growth → clipped
    assert abs(out.sum() - 1.0) < 1e-9


def test_soft_clip_preserves_relative_order():
    # one growth bucket over cap; recipients keep their relative ordering and ratios
    w = pd.Series({"b3_global_tech": 0.35, "a1_cash": 0.05, "a2_kr_rates": 0.12,
                   "a3_us_rates": 0.20, "b1_kr_equity": 0.28})
    out = be.soft_clip(w, growth_keys={"b3_global_tech", "b1_kr_equity"},
                       growth_cap=0.30, defensive_cap=0.50)
    assert out["b3_global_tech"] <= 0.30 + 1e-9
    # a2 stays strictly above a1 (ratio preserved, not equalized)
    assert out["a2_kr_rates"] > out["a1_cash"]
    assert out["a2_kr_rates"] / out["a1_cash"] == pytest.approx(0.12 / 0.05, rel=1e-6)
    assert abs(out.sum() - 1.0) < 1e-9
