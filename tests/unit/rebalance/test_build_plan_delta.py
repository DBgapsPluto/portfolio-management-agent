from tradingagents.rebalance.engine import compute_deltas


def _dials(**kw):
    base = dict(no_trade_band=0.005, single_etf_abs_cap=0.19,
               risk_asset_abs_cap=0.68)
    base.update(kw); return base


def test_small_delta_skipped():
    cur = {"A": 0.50, "B": 0.50}
    tgt = {"A": 0.502, "B": 0.498}     # |Δ|=0.002 < 0.005
    delta, skipped = compute_deltas(cur, tgt, _dials(), is_risk=lambda t: False)
    assert delta == {}                  # 전부 생략
    assert set(skipped) == {"A", "B"}


def test_large_delta_kept():
    cur = {"A": 0.50, "B": 0.50}
    tgt = {"A": 0.40, "B": 0.60}        # |Δ|=0.10
    delta, skipped = compute_deltas(cur, tgt, _dials(), is_risk=lambda t: False)
    assert abs(delta["A"] + 0.10) < 1e-9
    assert abs(delta["B"] - 0.10) < 1e-9
    assert skipped == []


def test_cap_buffer_exempt_forces_small_sell():
    # A가 0.203(cap 0.20 hard 초과)인데 목표 0.200 → Δ=-0.003 (band 미만)이지만
    # cap-방향 축소라 band 예외로 실행해야 (finding #2). 예외는 HARD_SINGLE_CAP(0.20) 기준.
    cur = {"A": 0.203, "B": 0.797}
    tgt = {"A": 0.200, "B": 0.800}
    delta, skipped = compute_deltas(cur, tgt, _dials(), is_risk=lambda t: False)
    assert "A" in delta and delta["A"] < 0     # 강제 실행
    assert "A" not in skipped


def test_risk_cap_exempt_forces_risk_reduction():
    # 위험자산 합 0.71 > hard cap 0.70 → 위험 종목 축소 델타는 작아도 실행.
    cur = {"R": 0.71, "S": 0.29}
    tgt = {"R": 0.708, "S": 0.292}     # Δ_R=-0.002 (band 미만), cur_risk 0.71 > 0.70
    is_risk = lambda t: t == "R"
    delta, skipped = compute_deltas(cur, tgt, _dials(), is_risk=is_risk)
    assert "R" in delta and delta["R"] < 0


def test_way_over_cap_small_sell_not_exempt():
    # 0.25(cap 0.20 크게 초과)에서 작은 셀(→0.248)은 cap 복귀 불가 → band 예외 X, skip.
    # current+d <= HARD_SINGLE_CAP 가드가 "barely over(복귀 가능)"만 예외함을 lock-in.
    cur = {"A": 0.25, "B": 0.75}
    tgt = {"A": 0.248, "B": 0.752}     # Δ_A=-0.002 (band 미만), 0.248 여전히 cap 초과
    delta, skipped = compute_deltas(cur, tgt, _dials(), is_risk=lambda t: False)
    assert "A" not in delta            # 예외 발동 안 함
    assert "A" in skipped
