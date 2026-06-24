import json

import numpy as np
import pandas as pd
import pytest

from tradingagents.agents.trader import trader_allocator as ta
from tradingagents.agents.trader.trader_allocator import create_trader_allocator
from tradingagents.schemas.portfolio import BucketTilt, BucketRanking
from tradingagents.schemas.research import ResearchThesis
from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS


# ---------------------------------------------------------------------------
# Pure helper: _bl_step_a_attribution
# ---------------------------------------------------------------------------
def test_bl_step_a_attribution_decomposition():
    regime_baseline = {"b3_global_tech": 0.20, "a3_us_rates": 0.12, "a2_kr_bond": 0.10}
    prior           = {"b3_global_tech": 0.14, "a3_us_rates": 0.12, "a2_kr_bond": 0.14}  # c<1 pulled b3 down, a2 up
    final           = {"b3_global_tech": 0.20, "a3_us_rates": 0.10, "a2_kr_bond": 0.13}  # BL views
    realized        = {"b3_global_tech": 0.18, "a3_us_rates": 0.10, "a2_kr_bond": 0.13}
    bl_meta = {"b3_global_tech": {"status": "bl"}, "a3_us_rates": {"status": "baseline_pinned"},
               "__global__": {"status": "bl", "n_pinned": 1}}
    attr = ta._bl_step_a_attribution(regime_baseline, prior, final, realized, bl_meta, signal_confidence=0.4)
    assert attr["method"] == "bl"
    b3 = attr["buckets"]["b3_global_tech"]
    assert b3["regime_baseline"] == 0.20 and b3["prior"] == 0.14
    assert b3["confidence_shift"] == pytest.approx(-0.06)      # prior − regime_baseline
    assert b3["view_shift"] == pytest.approx(0.06)             # final − prior
    assert b3["final"] == 0.20 and b3["realized"] == 0.18
    assert b3["intent_vs_realized"] == pytest.approx(-0.02)
    # honest identities hold per bucket:
    for d in attr["buckets"].values():
        assert d["regime_baseline"] + d["confidence_shift"] == pytest.approx(d["prior"])
        assert d["prior"] + d["view_shift"] == pytest.approx(d["final"])
    assert attr["buckets"]["a3_us_rates"]["status"] == "baseline_pinned"
    assert attr["global"]["n_pinned"] == 1
    assert attr["global"]["signal_confidence"] == pytest.approx(0.4)


def test_c_equals_one_prior_equals_regime_baseline():
    # c=1: prior == regime_baseline ⇒ confidence_shift == 0 everywhere (report unchanged vs pre-feature)
    rb = {"b1_kr_equity": 0.16, "a2_kr_bond": 0.12}
    attr = ta._bl_step_a_attribution(rb, dict(rb), {"b1_kr_equity": 0.18, "a2_kr_bond": 0.10},
                                     {"b1_kr_equity": 0.18, "a2_kr_bond": 0.10}, {}, signal_confidence=1.0)
    for d in attr["buckets"].values():
        assert d["confidence_shift"] == 0.0
        assert d["regime_baseline"] == d["prior"]


def test_bl_step_a_attribution_skips_all_zero():
    attr = ta._bl_step_a_attribution({"x": 0.0}, {"x": 0.0}, {"x": 0.0}, {"x": 0.0}, {},
                                     signal_confidence=1.0)
    assert "x" not in attr["buckets"]


def test_bl_step_a_attribution_default_status_bl():
    # bl_meta missing the bucket → status falls back to "bl"
    attr = ta._bl_step_a_attribution({"b1_kr_equity": 0.1}, {"b1_kr_equity": 0.1},
                                     {"b1_kr_equity": 0.12}, {"b1_kr_equity": 0.12}, {},
                                     signal_confidence=1.0)
    assert attr["buckets"]["b1_kr_equity"]["status"] == "bl"


# ---------------------------------------------------------------------------
# Node-level: use_bl=True produces BL-native step_a attribution
# ---------------------------------------------------------------------------
class _FakeStep:
    def __init__(self, obj):
        self._o = obj

    def with_structured_output(self, schema):
        return self

    def invoke(self, prompt):
        return self._o


def _universe_14(tmp_path):
    etfs = []
    for k in GAPS_BUCKET_KEYS:
        risk = "안전" if k[0] == "a" else "위험"
        for i in (1, 2):
            etfs.append({
                "ticker": f"T_{k}_{i}", "name": f"{k}{i}", "aum_krw": 100.0 * i,
                "underlying_index": f"idx_{k}_{i}", "bucket": risk,
                "category": "c", "gaps_bucket": k,
            })
    p = tmp_path / "u14.json"
    p.write_text(json.dumps({"version": "t", "etfs": etfs}, ensure_ascii=False))
    return str(p)


def _state_bl(universe_path):
    return {
        "research_decision": ResearchThesis(thesis_md="t"),
        "universe_path": universe_path, "macro_report": None,
        "macro_summary": "m", "risk_summary": "r",
        "technical_summary": "t", "news_summary": "n",
        "allocation_feedback": [], "as_of_date": "2026-05-10",
        "portfolio_dials": {"use_bl": True},
    }


def _state_non_bl(universe_path):
    st = _state_bl(universe_path)
    st["portfolio_dials"] = {}   # use_bl absent → old project_to_band path
    return st


def _fake_proxies(as_of, window_days=730):
    idx = pd.bdate_range(end=pd.Timestamp(as_of), periods=400)
    rng = np.random.default_rng(0)
    return pd.DataFrame(rng.normal(0, 0.01, (400, 14)), index=idx,
                        columns=list(GAPS_BUCKET_KEYS))


def test_bl_node_step_a_is_bl_native(tmp_path, monkeypatch):
    monkeypatch.setattr(ta, "fetch_bucket_proxy_returns", _fake_proxies)
    up = _universe_14(tmp_path)
    node = create_trader_allocator(_FakeStep(BucketTilt(bucket_ranking={
        "b3_global_tech": BucketRanking(tier="strong_OW", conviction=0.9, rationale="x"),
        "b2_dm_core": BucketRanking(tier="strong_UW", conviction=0.9, rationale="y"),
    })))
    out = node(_state_bl(up))
    sa = out["allocation_attribution"]["step_a"]
    assert sa["method"] == "bl"
    assert sa["buckets"], "BL step_a must decompose at least one bucket"
    for b, row in sa["buckets"].items():
        for key in ("regime_baseline", "confidence_shift", "prior", "view_shift",
                    "final", "realized", "intent_vs_realized", "status"):
            assert key in row
    # BL meta still attached (B6)
    assert out["allocation_attribution"]["bl"]


def test_non_bl_node_step_a_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(ta, "fetch_bucket_proxy_returns", _fake_proxies)
    up = _universe_14(tmp_path)
    node = create_trader_allocator(_FakeStep(BucketTilt()))
    out = node(_state_non_bl(up))
    sa = out["allocation_attribution"]["step_a"]
    # old-style step_a has no "method" key and uses scenario_delta/tilt decomposition
    assert "method" not in sa
    assert "bl" not in out["allocation_attribution"]
    for b, row in sa["buckets"].items():
        assert "scenario_delta" in row and "tilt_applied" in row
        assert "view_shift" not in row
