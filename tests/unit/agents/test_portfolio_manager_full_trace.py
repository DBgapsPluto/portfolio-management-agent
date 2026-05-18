"""Stage 6 정리 ①②③ — portfolio.json full trace + trade_plan qty=0 warning."""
import csv
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tradingagents.agents.managers.portfolio_manager import (
    _build_full_trace_portfolio, _serialize_for_json, create_portfolio_manager,
)
from tradingagents.dataflows.universe import sync_from_xlsx
from tradingagents.schemas.portfolio import (
    BucketTarget, OptimizationMethod, WeightVector,
)
from tradingagents.schemas.risk_overlay import (
    LensConcern, RiskOverlay, RiskOverlayDelta,
)


def _build_state(universe_path):
    return {
        "weight_vector": WeightVector(
            method=OptimizationMethod.HRP,
            weights={"A069500": 0.20, "A360750": 0.20, "A114260": 0.30, "A459580": 0.30},
            rationale="balanced defensive tilt",
            expected_volatility=0.12, expected_sharpe=0.85,
        ),
        "bucket_target": BucketTarget(
            kr_equity=0.20, global_equity=0.20, fx_commodity=0.0,
            bond=0.30, cash_mmf=0.30,
            rationale="defensive",
        ),
        "capital_krw": 1_000_000_000,
        "as_of_date": "2026-05-25",
        "universe_path": str(universe_path),
        "macro_summary": "regime: recession",
        "risk_summary": "VIX 28",
        "research_debate_summary": "60/40",
        "technical_summary": "clusters: 3",
        "news_summary": "calm",
        "research_decision": SimpleNamespace(
            dominant_scenario="broad_recession",
            dominant_probability=0.42,
            conviction="medium",
            model_dump=lambda **kw: {
                "dominant_scenario": "broad_recession",
                "dominant_probability": 0.42,
                "conviction": "medium",
            },
        ),
        "method_choice": {"method": "hrp", "reasoning": "recession defensive"},
        # Real RiskOverlay (philosophy._format_overlay가 is_empty() 호출)
        "risk_overlay": RiskOverlay(
            risk_asset_multiplier=0.85,
            severity_decision="high consensus",
            strength_applied=0.5,
            lens_concerns=[
                LensConcern(
                    lens="tail_risk", level="high",
                    proposed_overlay=RiskOverlayDelta(risk_asset_multiplier=0.75),
                    evidence="CVaR_95=3.2%, systemic=7.5",
                ),
                LensConcern(
                    lens="concentration", level="medium",
                    proposed_overlay=RiskOverlayDelta(),
                    evidence="HHI=0.14",
                ),
                LensConcern(
                    lens="macro_conditional", level="medium",
                    proposed_overlay=RiskOverlayDelta(risk_asset_multiplier=0.92),
                    evidence="risk_weight=55%, scenario=broad_recession",
                ),
            ],
        ),
        "portfolio_numerics": SimpleNamespace(
            hhi=0.14, top1_weight=0.30, top3_weight_sum=0.80,
            max_cluster_exposure=0.40,
            cvar_95_1d=0.025, var_95_1d=0.020, realized_vol_60d=0.012,
            cluster_exposure={"c1": 0.40},
            n_assets=4, source_date=None, staleness_days=0,
            model_dump=lambda **kw: {
                "hhi": 0.14, "top1_weight": 0.30, "cvar_95_1d": 0.025,
            },
        ),
        "validation_report": SimpleNamespace(
            passed=True, violations=[],
            model_dump=lambda **kw: {"passed": True, "violations": []},
        ),
        "rebalance_mode": "initial",
    }


def test_serialize_for_json_handles_pydantic_dict_list():
    class FakeModel:
        def model_dump(self, **kwargs):
            return {"k": "v"}
    out = _serialize_for_json([FakeModel(), {"a": 1}, "s"])
    assert out == [{"k": "v"}, {"a": 1}, "s"]


def test_serialize_for_json_passes_primitives():
    assert _serialize_for_json(42) == 42
    assert _serialize_for_json("text") == "text"
    assert _serialize_for_json(None) is None


def test_build_full_trace_portfolio_has_all_keys(tmp_path):
    universe_json = tmp_path / "universe.json"
    sync_from_xlsx(Path("tests/fixtures/universe_test.xlsx"), universe_json)
    state = _build_state(universe_json)

    portfolio = _build_full_trace_portfolio(state)

    # Stage 6 정리 ① — 5개 신규 trace 필드
    assert "research_decision" in portfolio
    assert "method_choice" in portfolio
    assert "risk_overlay" in portfolio
    assert "portfolio_numerics" in portfolio
    assert "validation_report" in portfolio
    assert "rebalance_mode" in portfolio
    assert portfolio["rebalance_mode"] == "initial"


def test_build_full_trace_handles_missing_optional_fields(tmp_path):
    universe_json = tmp_path / "universe.json"
    sync_from_xlsx(Path("tests/fixtures/universe_test.xlsx"), universe_json)
    state = _build_state(universe_json)
    # Stage 1-5 정보 모두 제거 (legacy state)
    for k in ["research_decision", "method_choice", "risk_overlay",
              "portfolio_numerics", "validation_report"]:
        state[k] = None

    portfolio = _build_full_trace_portfolio(state)
    assert portfolio["research_decision"] is None
    assert portfolio["risk_overlay"] is None
    # 기존 필드는 정상
    assert portfolio["method"] == "hrp"
    assert "weights" in portfolio


def test_portfolio_manager_writes_full_trace_and_warnings(tmp_path):
    universe_json = tmp_path / "universe.json"
    sync_from_xlsx(Path("tests/fixtures/universe_test.xlsx"), universe_json)
    artifacts_dir = tmp_path / "artifacts"

    deep_llm = MagicMock()
    deep_llm.invoke.return_value.content = "투자철학 본문입니다. " * 200

    state = _build_state(universe_json)

    # current_prices fetch 실패 시나리오 (qty=0 warning 트리거)
    with patch(
        "tradingagents.agents.managers.portfolio_manager._fetch_current_prices",
        return_value={},
    ):
        node = create_portfolio_manager(deep_llm, artifacts_dir=str(artifacts_dir))
        result = node(state)

    # full trace 포함
    portfolio = json.loads(
        Path(result["final_portfolio_path"]).read_text(encoding="utf-8"),
    )
    assert portfolio["research_decision"]["dominant_scenario"] == "broad_recession"
    assert portfolio["risk_overlay"]["strength_applied"] == 0.5
    assert portfolio["portfolio_numerics"]["hhi"] == 0.14
    assert portfolio["validation_report"]["passed"] is True
    assert portfolio["rebalance_mode"] == "initial"

    # warnings 채워짐 (모든 ticker qty=0)
    assert "warnings" in result
    assert any("qty=0" in w for w in result["warnings"])

    # CSV에 # WARNING 라인 포함
    csv_text = Path(result["trade_plan_csv_path"]).read_text(encoding="utf-8-sig")
    assert "# WARNING:" in csv_text
    assert "qty=0" in csv_text


def test_portfolio_manager_no_warnings_when_prices_available(tmp_path):
    universe_json = tmp_path / "universe.json"
    sync_from_xlsx(Path("tests/fixtures/universe_test.xlsx"), universe_json)
    artifacts_dir = tmp_path / "artifacts"

    deep_llm = MagicMock()
    deep_llm.invoke.return_value.content = "투자철학 본문입니다. " * 200

    state = _build_state(universe_json)

    fake_prices = {
        "A069500": 50000.0, "A360750": 35000.0,
        "A114260": 100000.0, "A459580": 1000000.0,
    }
    with patch(
        "tradingagents.agents.managers.portfolio_manager._fetch_current_prices",
        return_value=fake_prices,
    ):
        node = create_portfolio_manager(deep_llm, artifacts_dir=str(artifacts_dir))
        result = node(state)

    # 모든 ticker가 price 있으므로 qty>0, warnings 없음
    qty_warnings = [w for w in result.get("warnings", []) if "qty=0" in w]
    assert qty_warnings == []
    csv_text = Path(result["trade_plan_csv_path"]).read_text(encoding="utf-8-sig")
    assert "# WARNING:" not in csv_text
