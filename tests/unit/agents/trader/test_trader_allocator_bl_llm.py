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
# Pure helpers
# ---------------------------------------------------------------------------
def test_ranking_from_tilt():
    bt = BucketTilt(bucket_ranking={
        "b3_global_tech": BucketRanking(tier="strong_OW", conviction=0.8, rationale="x"),
        "a3_us_rates": BucketRanking(tier="UW", conviction=0.5, rationale="y"),
    })
    rk = ta._ranking_from_tilt(bt)
    assert rk["b3_global_tech"] == ("strong_OW", 0.8)
    assert rk["a3_us_rates"] == ("UW", 0.5)


def test_ranking_from_tilt_empty():
    assert ta._ranking_from_tilt(BucketTilt()) == {}


def test_step_a_prompt_bl_asks_for_ranking():
    msgs = ta._step_a_prompt_bl({"as_of_date": "2026-05-10"}, "growth_disinflation",
                                "neutral", "neutral")
    sys = msgs[0]["content"]
    body = msgs[1]["content"]
    assert "tier" in sys and "상대순위" in sys
    assert "bucket_ranking" in body


# ---------------------------------------------------------------------------
# Node-level: use_bl=True + LLM ranking drives BL allocation
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


def _fake_proxies(as_of, window_days=730):
    idx = pd.bdate_range(end=pd.Timestamp(as_of), periods=400)
    rng = np.random.default_rng(0)
    return pd.DataFrame(rng.normal(0, 0.01, (400, 14)), index=idx,
                        columns=list(GAPS_BUCKET_KEYS))


def test_bl_branch_llm_ranking_drives_allocation(tmp_path, monkeypatch):
    """use_bl=True, NO bl_fixed_ranking → LLM BucketTilt.bucket_ranking drives BL:
    b3 strong_OW pushes b3 weight above its no-view (neutral-ranking) weight."""
    monkeypatch.setattr(ta, "fetch_bucket_proxy_returns", _fake_proxies)
    up = _universe_14(tmp_path)

    # neutral ranking baseline
    base_node = create_trader_allocator(_FakeStep(BucketTilt()))
    w0 = base_node(_state_bl(up))["bucket_target"].weights.get("b3_global_tech", 0.0)

    # strong overweight on b3 funded by underweight on b2
    ow = _FakeStep(BucketTilt(bucket_ranking={
        "b3_global_tech": BucketRanking(tier="strong_OW", conviction=0.9, rationale="x"),
        "b2_dm_core": BucketRanking(tier="strong_UW", conviction=0.9, rationale="y"),
    }))
    w1 = create_trader_allocator(ow)(_state_bl(up))["bucket_target"].weights.get(
        "b3_global_tech", 0.0)
    assert w1 > w0, f"strong_OW should raise b3 weight: base={w0}, ow={w1}"


def test_bl_fixed_ranking_override_still_works(tmp_path, monkeypatch):
    """bl_fixed_ranking present → LLM is NOT consulted (raising step proves it)."""
    monkeypatch.setattr(ta, "fetch_bucket_proxy_returns", _fake_proxies)
    up = _universe_14(tmp_path)

    class _Raising:
        def with_structured_output(self, schema):
            return self

        def invoke(self, prompt):
            raise AssertionError("bl_fixed_ranking present — LLM must not be called")

    st = _state_bl(up)
    st["bl_fixed_ranking"] = {"b3_global_tech": ("strong_OW", 0.9)}
    out = create_trader_allocator(_Raising())(st)
    assert sum(out["weight_vector"].weights.values()) == pytest.approx(1.0, abs=1e-3)


def test_bl_branch_sub_category_views_flow_to_step_b(tmp_path, monkeypatch):
    """In the BL branch with LLM ranking, tilt.sub_category_views must still drive
    Step B heterogeneous selection (favored semiconductor selected, battery excluded)."""
    monkeypatch.setattr(ta, "fetch_bucket_proxy_returns", _fake_proxies)
    # build a het universe (b3 split into semiconductor / battery_ev)
    etfs = []
    for k in GAPS_BUCKET_KEYS:
        if k == "b3_global_tech":
            continue
        risk = "안전" if k[0] == "a" else "위험"
        for i in (1, 2):
            etfs.append({
                "ticker": f"T_{k}_{i}", "name": f"{k}{i}", "aum_krw": 100.0 * i,
                "underlying_index": f"idx_{k}_{i}", "bucket": risk,
                "category": "c", "gaps_bucket": k,
            })
    etfs += [
        {"ticker": "A_SEMI_1", "name": "반도체1", "aum_krw": 5.0e11,
         "underlying_index": "idx_semi_1", "bucket": "위험", "category": "c",
         "gaps_bucket": "b3_global_tech", "sub_category": "semiconductor"},
        {"ticker": "A_BATT_1", "name": "이차전지1", "aum_krw": 3.0e11,
         "underlying_index": "idx_batt_1", "bucket": "위험", "category": "c",
         "gaps_bucket": "b3_global_tech", "sub_category": "battery_ev"},
    ]
    p = tmp_path / "u_het.json"
    p.write_text(json.dumps({"version": "t", "etfs": etfs}, ensure_ascii=False))

    step_a = _FakeStep(BucketTilt(
        bucket_ranking={
            "b3_global_tech": BucketRanking(tier="OW", conviction=0.7, rationale="x")},
        sub_category_views={"b3_global_tech": {"semiconductor": 0.9, "battery_ev": -0.9}},
        rationale="반도체 선호"))
    out = create_trader_allocator(step_a)(_state_bl(str(p)))
    wv = out["weight_vector"]
    assert any(t.startswith("A_SEMI") for t in wv.weights), \
        f"favored semiconductor must be selected: {list(wv.weights)}"
    assert not any(t.startswith("A_BATT") for t in wv.weights), \
        f"excluded battery must not appear: {list(wv.weights)}"
    sa = out["allocation_attribution"]["step_a"]
    assert sa["sub_category_views"]["b3_global_tech"]["semiconductor"] == 0.9
