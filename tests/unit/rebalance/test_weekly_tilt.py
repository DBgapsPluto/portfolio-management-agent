"""Unit tests for weekly_tilt — only test pure logic; LLM-dependent calls mocked."""
import logging
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


# ---- C3: structured quadrant compare (rationale substring never matches BL rationale) ----


def test_regime_unchanged_structured_quadrant_same_despite_bl_rationale(monkeypatch, tmp_path):
    # C3: the real BL bucket_target.rationale never contains the quadrant string
    # (it's "risk_tilt=... fx=... credit=... / risk=NN.N%"), so the old substring
    # check always tripped regime_changed=True on BL artifacts. Structured
    # allocation_attribution.step_a.quadrant compare must correctly see "unchanged".
    from tradingagents.rebalance import weekly_tilt as wt
    import json

    _patch_llm_clients(monkeypatch)
    monkeypatch.setattr(
        wt, "create_macro_quant_analyst",
        lambda q, d: _make_macro_node("growth_disinflation"),
    )
    monkeypatch.setattr(
        wt, "create_market_risk_analyst",
        lambda q, d: _make_risk_node(4.0),
    )
    prev = tmp_path / "prev.json"
    prev.write_text(
        json.dumps({
            "bucket_target": {"rationale": "risk_tilt=neutral fx=neutral credit=neutral / risk=55.0%"},
            "allocation_attribution": {"step_a": {"quadrant": "growth_disinflation"}},
        }),
        encoding="utf-8",
    )
    result = wt.run(as_of="2026-06-15", previous_path=str(prev))
    assert result.regime_changed is False


def test_regime_changed_structured_quadrant_differs(monkeypatch, tmp_path):
    from tradingagents.rebalance import weekly_tilt as wt
    import json

    _patch_llm_clients(monkeypatch)
    monkeypatch.setattr(
        wt, "create_macro_quant_analyst",
        lambda q, d: _make_macro_node("recession_inflation"),
    )
    monkeypatch.setattr(
        wt, "create_market_risk_analyst",
        lambda q, d: _make_risk_node(8.0),
    )
    prev = tmp_path / "prev.json"
    prev.write_text(
        json.dumps({
            "bucket_target": {"rationale": "risk_tilt=neutral fx=neutral credit=neutral / risk=55.0%"},
            "allocation_attribution": {"step_a": {"quadrant": "growth_disinflation"}},
        }),
        encoding="utf-8",
    )
    result = wt.run(as_of="2026-06-15", previous_path=str(prev))
    assert result.regime_changed is True
    assert result.tilt_proposed == {
        "risk_asset_delta": -0.05, "bond_delta": +0.05,
    }


def test_regime_change_fallback_substring_when_quadrant_missing_logs_warning(
    monkeypatch, tmp_path, caplog,
):
    # Pre-C3 artifact (no allocation_attribution.step_a.quadrant) — fall back to
    # the substring heuristic unchanged, but warn so the fallback is observable.
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
    with caplog.at_level(logging.WARNING):
        result = wt.run(as_of="2026-06-15", previous_path=str(prev))
    assert result.regime_changed is True
    assert any("structured quadrant" in r.message for r in caplog.records)
