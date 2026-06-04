import json
import pytest
from tradingagents.schemas.research import ResearchThesis
from tradingagents.schemas.portfolio import (
    BucketTarget, CandidateSet,
    WeightVector, OptimizationMethod, BucketTilt,
)
from tradingagents.agents.trader.trader_allocator import create_trader_allocator
from tradingagents.agents.trader.trader_allocator import (
    _resolve_quadrant, _resolve_confidence, _step_a_prompt,
)
from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS
from tradingagents.skills.portfolio.scenario_anchor import (
    QUADRANT_BASELINE, hard_band, effective_band,
)


class _FakeStep:
    """with_structured_output(schema).invoke(prompt) → 미리 정한 객체."""
    def __init__(self, obj):
        self._o = obj
    def with_structured_output(self, schema):
        return self
    def invoke(self, prompt):
        return self._o


def _universe_14(tmp_path):
    """14버킷 각 2 ETF (anchor 비중이 풀 부족으로 cash 로 쏠리지 않게)."""
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


def _state_14(universe_path, macro=None):
    return {
        "research_decision": ResearchThesis(conviction="medium",
                                            dominant_scenario="neutral", thesis_md="t"),
        "universe_path": universe_path, "macro_report": macro,
        "macro_summary": "m", "risk_summary": "r",
        "technical_summary": "t", "news_summary": "n",
        "allocation_feedback": [],
    }


def test_step_a_prompt_includes_quadrant_anchor_and_signals():
    q = "growth_disinflation"
    anchor = QUADRANT_BASELINE[q]
    eff = {b: effective_band(anchor[b], *hard_band(q, b, anchor[b]), 0.7, "high") for b in anchor}
    state = {
        "research_decision": ResearchThesis(
            conviction="high", dominant_scenario="x", thesis_md="강세 논거",
            key_risks=["중국 둔화"]),
        "macro_summary": "MACRO_X", "risk_summary": "r",
        "technical_summary": "t", "news_summary": "n",
        "allocation_feedback": [],
    }
    msgs = _step_a_prompt(state, q, "kr_stress", 0.7, "high", anchor, eff)
    text = msgs[0]["content"] + msgs[1]["content"]
    assert q in text
    assert "kr_stress" in text
    assert "b3_global_tech" in text
    assert "중국 둔화" in text
    assert "MACRO_X" in text
    assert "tilt" in text.lower()


def test_zero_tilt_bucket_target_equals_baseline(tmp_path):
    up = _universe_14(tmp_path)
    step_a = _FakeStep(BucketTilt())
    node = create_trader_allocator(step_a_llm=step_a)
    out = node(_state_14(up))  # macro_report=None → _resolve_quadrant 가 growth_disinflation 로 fallback
    base = QUADRANT_BASELINE["growth_disinflation"]  # 따라서 이것이 기대 앵커
    for b, w in base.items():
        assert out["bucket_target"].weights.get(b, 0.0) == pytest.approx(w, abs=1e-6)


def test_positive_tilt_increases_bucket_weight(tmp_path):
    up = _universe_14(tmp_path)
    base_node = create_trader_allocator(_FakeStep(BucketTilt()))
    tilt_node = create_trader_allocator(
        _FakeStep(BucketTilt(tilts={"b3_global_tech": 0.06, "b2_dm_core": -0.06})))
    w0 = base_node(_state_14(up))["bucket_target"].weights["b3_global_tech"]
    w1 = tilt_node(_state_14(up))["bucket_target"].weights["b3_global_tech"]
    assert w1 > w0


def test_node_outputs_valid_weight_vector(tmp_path):
    up = _universe_14(tmp_path)
    node = create_trader_allocator(_FakeStep(BucketTilt()))
    out = node(_state_14(up))
    wv = out["weight_vector"]
    assert wv.method == OptimizationMethod.AUM_WEIGHTED
    assert sum(wv.weights.values()) == pytest.approx(1.0, abs=1e-3)
    assert all(w <= 0.20 + 1e-6 for w in wv.weights.values())
    assert sum(out["bucket_target"].weights.values()) == pytest.approx(1.0, abs=1e-6)


def test_node_smoke_thin_pool_does_not_crash(tmp_path):
    etfs = [
        {"ticker": "R1", "name": "리츠1", "aum_krw": 100.0, "underlying_index": "i1",
         "bucket": "위험", "category": "c", "gaps_bucket": "b7_reits"},
        {"ticker": "R2", "name": "리츠2", "aum_krw": 100.0, "underlying_index": "i2",
         "bucket": "위험", "category": "c", "gaps_bucket": "b7_reits"},
        {"ticker": "C1", "name": "현금1", "aum_krw": 100.0, "underlying_index": "i3",
         "bucket": "안전", "category": "c", "gaps_bucket": "a1_cash"},
        {"ticker": "C2", "name": "현금2", "aum_krw": 100.0, "underlying_index": "i4",
         "bucket": "안전", "category": "c", "gaps_bucket": "a1_cash"},
        {"ticker": "C3", "name": "현금3", "aum_krw": 100.0, "underlying_index": "i5",
         "bucket": "안전", "category": "c", "gaps_bucket": "a1_cash"},
    ]
    p = tmp_path / "u.json"
    p.write_text(json.dumps({"version": "t", "etfs": etfs}, ensure_ascii=False))
    node = create_trader_allocator(_FakeStep(BucketTilt()))
    out = node(_state_14(str(p)))
    wv = out["weight_vector"]
    assert sum(wv.weights.values()) == pytest.approx(1.0, abs=1e-3)
    assert all(w <= 0.20 + 1e-6 for w in wv.weights.values())


class _FakeRegime:
    def __init__(self, quadrant, confidence):
        self.quadrant = quadrant
        self.confidence = confidence


class _FakeMacro:
    def __init__(self, regime):
        self.regime = regime


def test_resolve_quadrant_reads_macro_report():
    state = {"macro_report": _FakeMacro(_FakeRegime("recession_inflation", 0.7))}
    assert _resolve_quadrant(state) == "recession_inflation"
    assert _resolve_confidence(state) == pytest.approx(0.7)


def test_resolve_quadrant_falls_back_when_missing():
    assert _resolve_quadrant({}) == "growth_disinflation"
    assert _resolve_confidence({}) == pytest.approx(0.1)


def test_resolve_quadrant_rejects_unknown_label():
    state = {"macro_report": _FakeMacro(_FakeRegime("nonsense", 0.5))}
    assert _resolve_quadrant(state) == "growth_disinflation"


def test_kr_stress_modifier_shifts_kr_equity_down(tmp_path):
    up = _universe_14(tmp_path)
    macro = _FakeMacro(_FakeRegime("growth_disinflation", 0.5))

    def run(scenario):
        st = _state_14(up, macro)
        st["research_decision"] = ResearchThesis(
            conviction="medium", dominant_scenario=scenario, thesis_md="t")
        node = create_trader_allocator(_FakeStep(BucketTilt()))
        return node(st)["bucket_target"].weights["b1_kr_equity"]

    assert run("kr_stress") < run("neutral")   # kr_stress 가 한국주식을 낮춤


def test_node_deterministic_selection_no_llm(tmp_path):
    up = _universe_14(tmp_path)
    node = create_trader_allocator(_FakeStep(BucketTilt()))
    out1 = node(_state_14(up))
    out2 = node(_state_14(up))
    assert out1["candidate_set"].bucket_to_tickers == out2["candidate_set"].bucket_to_tickers
    wv = out1["weight_vector"]
    assert sum(wv.weights.values()) == pytest.approx(1.0, abs=1e-3)
    assert all(w <= 0.20 + 1e-6 for w in wv.weights.values())
    assert out1["candidate_set"].selection_criteria.startswith("deterministic carrier")


def test_node_a3_inflation_selects_short_unhedged(tmp_path):
    """노드가 quadrant·ETF명을 selector로 전달 → a3에서 10년(UH) 선택."""
    etfs = []
    for k in GAPS_BUCKET_KEYS:
        if k == "a3_us_rates":
            continue
        risk = "안전" if k[0] == "a" else "위험"
        for i in (1, 2):
            etfs.append({
                "ticker": f"T_{k}_{i}", "name": f"{k}{i}", "aum_krw": 100.0 * i,
                "underlying_index": f"idx_{k}_{i}", "bucket": risk,
                "category": "c", "gaps_bucket": k,
            })
    etfs += [
        {"ticker": "A453850", "name": "ACE 미국30년국채액티브(H)", "aum_krw": 1.82e12,
         "underlying_index": "미국30년국채", "bucket": "안전", "category": "c",
         "gaps_bucket": "a3_us_rates", "sub_category": "us_treasury"},
        {"ticker": "A305080", "name": "TIGER 미국채10년선물", "aum_krw": 2.446e11,
         "underlying_index": "미국채10년", "bucket": "안전", "category": "c",
         "gaps_bucket": "a3_us_rates", "sub_category": "us_treasury"},
    ]
    p = tmp_path / "u.json"
    p.write_text(json.dumps({"version": "t", "etfs": etfs}, ensure_ascii=False))
    macro = _FakeMacro(_FakeRegime("growth_inflation", 0.7))
    node = create_trader_allocator(_FakeStep(BucketTilt()))
    out = node(_state_14(str(p), macro))
    assert out["candidate_set"].bucket_to_tickers.get("a3_us_rates") == ["A305080"]
