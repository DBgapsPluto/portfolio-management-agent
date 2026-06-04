from tradingagents.skills.portfolio.vol_haircut import (
    bucket_volatility, apply_vol_haircut,
)


def test_bucket_volatility_aum_weighted():
    pool = {"b8": ["OIL", "GAS"], "a1": ["CASH"]}
    vol_of = {"OIL": 0.40, "GAS": 0.30, "CASH": 0.01}
    aum = {"OIL": 300.0, "GAS": 100.0, "CASH": 50.0}
    out = bucket_volatility(pool, vol_of, aum)
    assert abs(out["b8"] - 0.375) < 1e-9   # (0.40*300+0.30*100)/400
    assert abs(out["a1"] - 0.01) < 1e-9


def test_bucket_volatility_skips_none_and_zero():
    pool = {"b": ["X", "Y", "Z"]}
    vol_of = {"X": 0.20, "Y": None, "Z": 0.0}
    aum = {"X": 100.0, "Y": 100.0, "Z": 100.0}
    out = bucket_volatility(pool, vol_of, aum)
    assert abs(out["b"] - 0.20) < 1e-9     # only X counts


def test_bucket_volatility_omits_bucket_with_no_vol():
    out = bucket_volatility({"b": ["X"]}, {"X": None}, {"X": 100.0})
    assert "b" not in out


def test_haircut_trims_high_vol_bucket():
    bw = {"b8": 0.5, "a1": 0.5}
    bv = {"b8": 0.40, "a1": 0.10}      # ref=0.25, thr=0.30; b8 factor=max(0.6,0.75)=0.75
    out = apply_vol_haircut(bw, bv)
    assert abs(out["b8"] - 0.375) < 1e-9   # 0.5*0.75
    assert abs(out["a1"] - 0.625) < 1e-9   # freed 0.125 → a1
    assert abs(sum(out.values()) - 1.0) < 1e-9


def test_haircut_floor_caps_trim():
    bw = {"hi": 0.1, "lo": 0.9}
    bv = {"hi": 1.0, "lo": 0.10}       # ref=0.19, thr=0.228; factor=max(0.6,0.228)=0.6
    out = apply_vol_haircut(bw, bv)
    assert abs(out["hi"] - 0.06) < 1e-9    # 0.1*0.6 (floored)
    assert abs(sum(out.values()) - 1.0) < 1e-9


def test_haircut_noop_when_uniform_vol():
    bw = {"a": 0.5, "b": 0.5}
    out = apply_vol_haircut(bw, {"a": 0.20, "b": 0.20})
    assert out == bw


def test_haircut_noop_when_no_vol_data():
    bw = {"a": 0.5, "b": 0.5}
    assert apply_vol_haircut(bw, {}) == bw
