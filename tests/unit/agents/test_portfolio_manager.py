import csv
import json
from pathlib import Path
from unittest.mock import MagicMock

from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
from tradingagents.dataflows.universe import sync_from_xlsx
from tradingagents.schemas.portfolio import (
    BucketTarget, OptimizationMethod, WeightVector,
)


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
            kr_equity=0.20, global_equity=0.20, fx_commodity=0.0,
            bond=0.30, cash_mmf=0.30,
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
