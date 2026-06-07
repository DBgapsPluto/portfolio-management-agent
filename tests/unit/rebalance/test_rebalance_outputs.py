import csv, json
from tradingagents.rebalance.types import TradeLine, RebalanceResult
from tradingagents.reports.rebalance_plan import write_rebalance_plan, write_rebalance_json


def _res():
    r = RebalanceResult(as_of="2026-06-07", tier="monthly")
    r.plan = [TradeLine("A069500", "BUY", 0, 33, 33, 990000)]
    r.cash_residual_krw = 10000
    r.realized_weights = {"A069500": 0.99, "CASH": 0.01}
    r.turnover = 0.5
    return r


def test_csv_has_cash_residual_line(tmp_path):
    out = tmp_path / "2026-06-07(rebalancing)_plan.csv"
    write_rebalance_plan(_res(), {"A069500": {"name": "KODEX200", "category": "국내주식"}}, out)
    text = out.read_text(encoding="utf-8-sig")
    assert "매매구분" in text
    assert "# CASH_RESIDUAL_KRW: 10000" in text
    rows = [r for r in csv.reader(text.splitlines()) if r and not r[0].startswith("#")]
    assert rows[1][5] == "BUY"        # 매매구분 컬럼 (index 5)


def test_json_full_trace(tmp_path):
    out = tmp_path / "2026-06-07(rebalancing).json"
    write_rebalance_json(_res(), out, previous_path="artifacts/2026-06-05")
    d = json.loads(out.read_text(encoding="utf-8"))
    assert d["tier"] == "monthly"
    assert d["cash_residual_krw"] == 10000
    assert d["realized_weights"]["CASH"] == 0.01
    assert d["previous_portfolio_path"] == "artifacts/2026-06-05"
