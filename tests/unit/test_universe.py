import json
from datetime import date
from pathlib import Path

import pytest

from tradingagents.dataflows.universe import sync_from_xlsx, load_universe, Universe, ETFEntry


FIX = Path("tests/fixtures/universe_test.xlsx")


def test_sync_extracts_5_etfs(tmp_path):
    out = tmp_path / "universe.json"
    sync_from_xlsx(FIX, out)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert len(payload["etfs"]) == 5


def test_sync_normalizes_ticker(tmp_path):
    out_path = tmp_path / "u.json"
    sync_from_xlsx(FIX, out_path)
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    tickers = [e["ticker"] for e in payload["etfs"]]
    assert "A069500" in tickers
    assert all(t.startswith("A") for t in tickers)


def test_load_returns_typed(tmp_path):
    out_path = tmp_path / "u2.json"
    sync_from_xlsx(FIX, out_path)
    universe = load_universe(out_path)
    kodex_200 = next(e for e in universe.etfs if e.ticker == "A069500")
    assert kodex_200.bucket == "위험"
    assert kodex_200.aum_krw > 1_000_000_000_000  # 16조+


def test_sync_rejects_bad_ticker(tmp_path):
    bad = tmp_path / "bad.xlsx"
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([None, None, None, None, None, None, None])
    ws.append([None] * 7)
    ws.append([None] * 7)
    ws.append([None] * 7)
    ws.append([None, "티커", "ETF명", "AUM(억원)", "기초지수", "구분1", "구분2"])
    ws.append([None, "BAD", "Bad", 100.0, "x", "위험", "국내주식_지수"])
    wb.save(bad)
    out = tmp_path / "u.json"
    with pytest.raises(ValueError, match="invalid ticker"):
        sync_from_xlsx(bad, out)


def test_tradable_at_filters_unlisted():
    u = Universe(version="2026-05-10", etfs=[
        ETFEntry(ticker="A111111", name="x", aum_krw=1e12, underlying_index="x", bucket="위험", category="국내주식_지수",
                 listed_since=date(2025, 1, 1)),
        ETFEntry(ticker="A222222", name="y", aum_krw=1e12, underlying_index="y", bucket="위험", category="국내주식_지수",
                 listed_since=date(2027, 1, 1)),
    ])
    sub = u.tradable_at(date(2026, 5, 10))
    assert len(sub.etfs) == 1
    assert sub.etfs[0].ticker == "A111111"
