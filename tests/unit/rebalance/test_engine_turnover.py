"""F3 회전율 측정 충실화 — 체결 기반 메트릭 + CASH phantom 배제 (C1, MF-5/MF-6)."""
from tradingagents.dataflows.universe import Universe, ETFEntry
from tradingagents.rebalance.engine import build_rebalance_plan, validate_rebalance


def _uni():
    # 6종, 서로 다른 category — single/category cap 충돌 없이 드리프트만 관찰 가능하게.
    cats = ["국내주식_지수", "해외주식_지수", "FX 및 원자재",
            "국내채권_회사채", "해외채권_회사채", "금리연계형/초단기채권"]
    etfs = [ETFEntry(ticker=t, name=t, aum_krw=1e12, underlying_index="x",
                     bucket="안전", category=c)
            for t, c in zip("ABCDEF", cats)]
    return Universe(version="t", etfs=etfs)


def _run_monthly_engine(trades, drift_pct, floor):
    # 지난 리밸런싱 이후 거래 없음(trades=[]) — 보유수량 불변, 가격만 드리프트.
    tickers = "ABCDEF"
    prev_qty = {t: 100 for t in tickers}
    price_before = {t: 10000.0 for t in tickers}
    prev_value = sum(prev_qty[t] * price_before[t] for t in tickers)
    previous_weights = {t: prev_qty[t] * price_before[t] / prev_value for t in tickers}

    prices = dict(price_before)
    prices["A"] = price_before["A"] * (1 + drift_pct)   # A 만 드리프트
    current_value = sum(prev_qty[t] * prices[t] for t in tickers)
    current = {t: prev_qty[t] * prices[t] / current_value for t in tickers}
    target = dict(current)   # trades=[] → 이번 달 목표 = 현재(재조정 없음)
    assert trades == []

    dials = dict(no_trade_band=0.005)
    plan_out = build_rebalance_plan(current, target, prev_qty, int(current_value),
                                    prices, is_risk=lambda t: False, dials=dials)
    return validate_rebalance(
        plan_out["realized_weights"], universe=_uni(), clusters=[],
        previous_weights=previous_weights, current_value=int(current_value),
        floor_pct=floor, trade_turnover=plan_out["turnover"])


def test_monthly_floor_authority_is_engine_trade_notional():
    # 거래 0 + 가격 드리프트 12% → floor 미충족이어야 함 (드리프트 착시 제거).
    validation = _run_monthly_engine(trades=[], drift_pct=0.12, floor=0.10)
    assert any(v.rule == "turnover_floor" for v in validation.violations)


def _run_validate_rebalance(realized, previous, floor):
    etfs = [ETFEntry(ticker="A", name="A", aum_krw=1e12, underlying_index="x",
                     bucket="위험", category="국내주식_지수")]
    return validate_rebalance(realized, universe=Universe(version="t", etfs=etfs),
                              clusters=[], previous_weights=previous,
                              current_value=1_000_000, floor_pct=floor)


def test_cash_phantom_excluded_in_validate_rebalance():
    # 실제 팬텀 지점(감사 MF-6): full_wv는 CASH 포함, previous_weights는 미포함
    # → validate 경로에서 CASH 를 delta 집계에서 제외해야 함
    v = _run_validate_rebalance(realized={"A": 0.5, "CASH": 0.5},
                                previous={"A": 0.5}, floor=0.10)
    assert not any(x.rule == "turnover_floor" and "phantom" not in x.description
                   for x in v.violations if x.severity == "hard")
