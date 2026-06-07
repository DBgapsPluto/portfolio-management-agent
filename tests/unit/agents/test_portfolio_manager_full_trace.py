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


def _build_state(universe_path):
    return {
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

    # Stage 6 정리 ① — trace 필드
    assert "research_decision" in portfolio
    assert "method_choice" in portfolio
    assert "validation_report" in portfolio
    assert "rebalance_mode" in portfolio
    assert portfolio["rebalance_mode"] == "initial"


def test_build_full_trace_handles_missing_optional_fields(tmp_path):
    universe_json = tmp_path / "universe.json"
    sync_from_xlsx(Path("tests/fixtures/universe_test.xlsx"), universe_json)
    state = _build_state(universe_json)
    # Stage 1-5 정보 모두 제거 (legacy state)
    for k in ["research_decision", "method_choice", "validation_report"]:
        state[k] = None

    portfolio = _build_full_trace_portfolio(state)
    assert portfolio["research_decision"] is None
    assert portfolio["validation_report"] is None
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
        "tradingagents.rebalance.pricing.fetch_etf_close_map",
        return_value={},
    ):
        node = create_portfolio_manager(deep_llm, artifacts_dir=str(artifacts_dir))
        result = node(state)

    # full trace 포함
    portfolio = json.loads(
        Path(result["final_portfolio_path"]).read_text(encoding="utf-8"),
    )
    assert portfolio["research_decision"]["dominant_scenario"] == "broad_recession"
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
        "tradingagents.rebalance.pricing.fetch_etf_close_map",
        return_value=fake_prices,
    ):
        node = create_portfolio_manager(deep_llm, artifacts_dir=str(artifacts_dir))
        result = node(state)

    # 모든 ticker가 price 있으므로 qty>0, warnings 없음
    qty_warnings = [w for w in result.get("warnings", []) if "qty=0" in w]
    assert qty_warnings == []
    csv_text = Path(result["trade_plan_csv_path"]).read_text(encoding="utf-8-sig")
    assert "# WARNING:" not in csv_text


# ---------- Stage 6 audit (2026-05-26) tests ----------


def test_portfolio_json_includes_stage35_attribution(tmp_path, monkeypatch):
    """Stage 6 audit Task 2: portfolio.json full_trace 에 Stage 3/5 의 attribution
    이 모두 포함된다.
    """
    from datetime import date as _date
    import json
    from unittest.mock import MagicMock
    from pathlib import Path

    from tradingagents.agents.managers.portfolio_manager import (
        create_portfolio_manager,
    )
    from tradingagents.schemas.portfolio import OptimizationMethod, WeightVector

    universe_path = Path("data/universe.json")
    if not universe_path.exists():
        pytest.skip("universe.json not present")

    wv = WeightVector(
        method=OptimizationMethod.MIN_VARIANCE,
        weights={"A114260": 0.5, "A459580": 0.5},
        rationale="test",
    )
    state = {
        "weight_vector": wv,
        "capital_krw": 10_000_000_000,
        "as_of_date": "2026-05-15",
        "universe_path": str(universe_path),
        # Stage 3/5 attribution 마킹
        "allocation_attribution": {"config": {"method": "min_variance"}},
        "mandate_validator_attribution": {
            "validation_passed": True,
            "check_counts": {"concentration": {"hard": 0, "soft": 0}},
        },
    }

    # philosophy LLM mock (deep_llm)
    deep_llm = MagicMock()
    deep_llm.invoke.return_value.content = (
        "## 1. 투자가이드 요약\n" + "본문\n" * 500
    )

    node = create_portfolio_manager(deep_llm, artifacts_dir=str(tmp_path))
    out = node(state)

    portfolio_json = json.loads(
        Path(out["final_portfolio_path"]).read_text(encoding="utf-8"),
    )
    # Stage 3/5 attribution 모두 포함 검증
    assert "allocation_attribution" in portfolio_json
    assert "mandate_validator_attribution" in portfolio_json
    # 값 정합성
    assert portfolio_json["allocation_attribution"]["config"]["method"] == "min_variance"
    assert portfolio_json["mandate_validator_attribution"]["validation_passed"] is True


def test_portfolio_manager_named_const_present():
    """Stage 6 audit Task 3: portfolio_manager 의 named const 존재."""
    from tradingagents.agents.managers import portfolio_manager as pm
    assert pm.PHILOSOPHY_MIN_CHARS == 4000
    assert pm.PHILOSOPHY_MAX_RETRIES == 1
    assert pm.WARN_REASON_PRICE_FETCH_FAILED == "PRICE_FETCH_FAILED"
    assert pm.WARN_REASON_PRICE_ZERO == "PRICE_ZERO"
