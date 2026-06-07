import csv
import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import tradingagents.rebalance.pricing as pricing
from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
from tradingagents.dataflows.universe import sync_from_xlsx
from tradingagents.schemas.portfolio import (
    BucketTarget, OptimizationMethod, WeightVector,
)


def test_current_prices_falls_back_to_prior_available_day(monkeypatch):
    """KRX OpenAPI T+1~T+2 지연으로 as_of 종가가 비면 직전 영업일로 fallback."""
    tried: list[date] = []

    def fake_close_map(d: date) -> dict[str, float]:
        tried.append(d)
        if d == date(2026, 6, 2):  # 6/4·6/3은 아직 미제공, 6/2에 데이터
            return {"A069500": 12345.0}
        return {}

    monkeypatch.setattr(pricing, "fetch_etf_close_map", fake_close_map, raising=False)

    result = pricing.fetch_current_prices(date(2026, 6, 4))

    assert result == {"A069500": 12345.0}
    assert date(2026, 6, 2) in tried  # 거슬러 올라가 6/2까지 시도


def test_current_prices_empty_when_no_recent_data(monkeypatch):
    """전 구간 미제공이면 빈 dict (qty=0 graceful) — 무한 루프 없이 종료."""
    monkeypatch.setattr(pricing, "fetch_etf_close_map", lambda d: {}, raising=False)

    result = pricing.fetch_current_prices(date(2026, 6, 4))

    assert result == {}


def test_portfolio_manager_writes_3_artifacts(tmp_path):
    universe_json = tmp_path / "universe.json"
    sync_from_xlsx(Path("tests/fixtures/universe_test.xlsx"), universe_json)

    artifacts_dir = tmp_path / "artifacts"
    deep_llm = MagicMock()
    # write_philosophy expects len(content) >= 4000 to skip the expansion retry
    deep_llm.invoke.return_value.content = "투자철학 문서 본문입니다. " * 200

    state = {
        "weight_vector": WeightVector(
            method=OptimizationMethod.HRP,
            weights={"A069500": 0.20, "A360750": 0.20, "A114260": 0.30, "A459580": 0.30},
            rationale="balanced defensive tilt",
            expected_volatility=0.12, expected_sharpe=0.85,
        ),
        "bucket_target": BucketTarget(
            weights={
                "kr_equity": 0.20, "global_equity": 0.20, "precious_metals": 0.0,
                "cyclical_commodity_fx": 0.0, "kr_bond": 0.20,
                "credit": 0.10, "global_duration": 0.0, "cash_mmf": 0.30,
            },
            rationale="x",
        ),
        "capital_krw": 1_000_000_000,
        "as_of_date": "2026-05-25",
        "universe_path": str(universe_json),
        "macro_summary": "regime: recession",
        "risk_summary": "VIX 28",
        "research_debate_summary": "60/40",
        "technical_summary": "clusters: 3",
    }

    node = create_portfolio_manager(deep_llm, artifacts_dir=str(artifacts_dir))
    result = node(state)

    # 3 paths returned
    assert "final_portfolio_path" in result
    assert "philosophy_doc_path" in result
    assert "trade_plan_csv_path" in result

    # All 3 files written
    assert Path(result["final_portfolio_path"]).exists()
    assert Path(result["philosophy_doc_path"]).exists()
    assert Path(result["trade_plan_csv_path"]).exists()

    # portfolio.json schema
    portfolio = json.loads(Path(result["final_portfolio_path"]).read_text(encoding="utf-8"))
    assert portfolio["method"] == "hrp"
    assert abs(sum(portfolio["weights"].values()) - 1.0) < 1e-6

    # trade_plan.csv columns (# 주석 라인은 qty=0 경고용, 데이터 행만 카운트)
    with open(result["trade_plan_csv_path"], encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        assert header == ["티커", "ETF명", "자산군", "가중치", "매수금액(KRW)", "수량(주)"]
        data_rows = [
            r for r in reader
            if r and not r[0].startswith("#") and r[0].strip()
        ]
        assert len(data_rows) == 4
