import tradingagents.rebalance.daily_triggers as dt


def test_evaluate_reassess_fires_on_yield_curve():
    # yield_curve_regime_shift: spread_10y_2y_bps < -50
    assert dt.evaluate_reassess({"spread_10y_2y_bps": -60, "vix": 20,
                                 "vix_change_5d": 0.0}) is True


def test_evaluate_reassess_fires_on_vol_shift():
    # vol_regime_shift: vix_change_5d > 0.30 OR (vix<18 AND vix_change_5d<-0.30)
    assert dt.evaluate_reassess({"spread_10y_2y_bps": 50, "vix": 15,
                                 "vix_change_5d": -0.35}) is True
    assert dt.evaluate_reassess({"spread_10y_2y_bps": 50, "vix": 25,
                                 "vix_change_5d": 0.40}) is True


def test_evaluate_reassess_quiet_market_false():
    assert dt.evaluate_reassess({"spread_10y_2y_bps": 50, "vix": 20,
                                 "vix_change_5d": 0.05}) is False


def test_evaluate_reassess_missing_var_skips_not_crash():
    # ctx 에 변수 누락 → 해당 트리거 skip, crash 안 함
    assert dt.evaluate_reassess({"vix": 20}) is False
