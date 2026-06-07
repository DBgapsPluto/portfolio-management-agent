from pathlib import Path
from tradingagents.rebalance.holdings import load_prev_holdings


def _write(tmp_path, name, rows):
    p = tmp_path / name
    p.write_text(rows, encoding="utf-8-sig")
    return p


def test_loads_qty_from_trade_plan(tmp_path):
    _write(tmp_path, "trade_plan.csv",
           "티커,ETF명,자산군,가중치,매수금액(KRW),수량(주)\n"
           "A069500,KODEX200,국내주식,0.5,500000,50\n"
           "A229200,KODEX코스닥,국내주식,0.5,500000,25\n")
    qty, cash = load_prev_holdings(tmp_path)
    assert qty == {"A069500": 50, "A229200": 25}
    assert cash == 0


def test_prefers_rebalancing_plan_and_reads_cash(tmp_path):
    _write(tmp_path, "trade_plan.csv", "티커,수량(주)\nA069500,1\n")
    _write(tmp_path, "2026-06-07(rebalancing)_plan.csv",
           "티커,ETF명,자산군,현재수량,목표수량,매매구분,거래수량,거래금액(KRW)\n"
           "A069500,KODEX200,국내주식,0,50,BUY,50,500000\n"
           "# CASH_RESIDUAL_KRW: 12345\n")
    qty, cash = load_prev_holdings(tmp_path)
    assert qty == {"A069500": 50}     # 목표수량 = 리밸 후 보유
    assert cash == 12345
