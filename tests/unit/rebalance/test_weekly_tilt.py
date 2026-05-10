"""Unit tests for weekly_tilt — only test pure logic; LLM-dependent calls mocked."""
from unittest.mock import MagicMock, patch

import pytest


def _patch_llm_clients(monkeypatch):
    """Stub LLM client factory + analyst factories."""
    from tradingagents.rebalance import weekly_tilt as wt

    fake_llm = MagicMock()
    fake_client = MagicMock()
    fake_client.get_llm.return_value = fake_llm
    monkeypatch.setattr(wt, "create_llm_client", lambda **kw: fake_client)


def _make_macro_node(quadrant: str):
    def _node(state):
        return {"macro_report": MagicMock(regime=MagicMock(quadrant=quadrant))}
    return _node


def _make_risk_node(score: float):
    def _node(state):
        return {"risk_report": MagicMock(systemic_score=MagicMock(score=score))}
    return _node


def test_no_previous_path_no_regime_change(monkeypatch, tmp_path):
    from tradingagents.rebalance import weekly_tilt as wt

    _patch_llm_clients(monkeypatch)
    monkeypatch.setattr(
        wt, "create_macro_quant_analyst",
        lambda q, d: _make_macro_node("expansion"),
    )
    monkeypatch.setattr(
        wt, "create_market_risk_analyst",
        lambda q, d: _make_risk_node(3.5),
    )

    result = wt.run(as_of="2026-06-15")
    assert result.regime_changed is False
    assert result.tilt_proposed == {}
    assert "expansion" in result.summary


def test_regime_change_recession_tilts_to_bonds(monkeypatch, tmp_path):
    from tradingagents.rebalance import weekly_tilt as wt
    import json

    _patch_llm_clients(monkeypatch)
    monkeypatch.setattr(
        wt, "create_macro_quant_analyst",
        lambda q, d: _make_macro_node("recession"),
    )
    monkeypatch.setattr(
        wt, "create_market_risk_analyst",
        lambda q, d: _make_risk_node(7.5),
    )
    prev = tmp_path / "prev.json"
    prev.write_text(
        json.dumps({"bucket_target": {"rationale": "expansion regime"}}),
        encoding="utf-8",
    )
    result = wt.run(as_of="2026-06-15", previous_path=str(prev))
    assert result.regime_changed is True
    assert result.tilt_proposed == {
        "risk_asset_delta": -0.05, "bond_delta": +0.05,
    }


def test_regime_change_expansion_tilts_to_risk(monkeypatch, tmp_path):
    from tradingagents.rebalance import weekly_tilt as wt
    import json

    _patch_llm_clients(monkeypatch)
    monkeypatch.setattr(
        wt, "create_macro_quant_analyst",
        lambda q, d: _make_macro_node("expansion"),
    )
    monkeypatch.setattr(
        wt, "create_market_risk_analyst",
        lambda q, d: _make_risk_node(3.0),
    )
    prev = tmp_path / "prev.json"
    prev.write_text(
        json.dumps({"bucket_target": {"rationale": "recession regime"}}),
        encoding="utf-8",
    )
    result = wt.run(as_of="2026-06-15", previous_path=str(prev))
    assert result.regime_changed is True
    assert result.tilt_proposed == {
        "risk_asset_delta": +0.05, "bond_delta": -0.05,
    }
