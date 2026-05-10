import csv
from pathlib import Path

from tradingagents.reports.trade_plan import write_trade_plan


def test_write_trade_plan_sorts_by_weight_desc(tmp_path: Path):
    weights = {"A069500": 0.5, "A114800": 0.3, "A148070": 0.2}
    lookup = {
        "A069500": {"name": "KODEX 200", "category": "국내주식"},
        "A114800": {"name": "KODEX 인버스", "category": "국내주식"},
        "A148070": {"name": "KOSEF 국고채10년", "category": "국내채권"},
    }
    prices = {"A069500": 30000.0, "A114800": 5000.0, "A148070": 100000.0}
    out = tmp_path / "trade_plan.csv"
    write_trade_plan(weights, 1_000_000_000, lookup, prices, out)

    with open(out, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["티커", "ETF명", "자산군", "가중치", "매수금액(KRW)", "수량(주)"]
    assert rows[1][0] == "A069500"  # 0.5 first
    assert rows[1][4] == "500000000"  # 50% of 1B
    assert rows[1][5] == str(int(500_000_000 / 30000))


def test_write_trade_plan_handles_missing_price(tmp_path: Path):
    weights = {"A069500": 1.0}
    out = tmp_path / "trade_plan.csv"
    write_trade_plan(weights, 1_000_000_000, {}, {}, out)
    with open(out, encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert rows[1][5] == "0"  # qty = 0 when price unknown
