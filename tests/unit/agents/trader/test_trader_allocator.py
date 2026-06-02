import json
import pytest
from tradingagents.schemas.research import ResearchThesis
from tradingagents.schemas.portfolio import (
    BucketAllocation, StockSelection, BucketTarget, CandidateSet,
    WeightVector, OptimizationMethod,
)
from tradingagents.agents.trader.trader_allocator import create_trader_allocator


class _FakeStep:
    """with_structured_output(schema).invoke(prompt) → 미리 정한 객체."""
    def __init__(self, obj):
        self._o = obj
    def with_structured_output(self, schema):
        return self
    def invoke(self, prompt):
        return self._o


def _universe(tmp_path):
    etfs = [
        {"ticker": "C1", "name": "현금1", "aum_krw": 100.0, "underlying_index": "i",
         "bucket": "안전", "category": "c", "gaps_bucket": "a1_cash"},
        {"ticker": "C2", "name": "현금2", "aum_krw": 100.0, "underlying_index": "i",
         "bucket": "안전", "category": "c", "gaps_bucket": "a1_cash"},
        {"ticker": "E1", "name": "코스피1", "aum_krw": 300.0, "underlying_index": "i",
         "bucket": "위험", "category": "c", "gaps_bucket": "b1_kr_equity"},
        {"ticker": "E2", "name": "코스피2", "aum_krw": 100.0, "underlying_index": "i",
         "bucket": "위험", "category": "c", "gaps_bucket": "b1_kr_equity"},
        {"ticker": "E3", "name": "코스피3", "aum_krw": 100.0, "underlying_index": "i",
         "bucket": "위험", "category": "c", "gaps_bucket": "b1_kr_equity"},
    ]
    p = tmp_path / "u.json"
    p.write_text(json.dumps({"version": "t", "etfs": etfs}, ensure_ascii=False))
    return str(p)


def _state(universe_path):
    return {
        "research_decision": ResearchThesis(conviction="medium",
                                            dominant_scenario="neutral", thesis_md="t"),
        "universe_path": universe_path,
        "macro_summary": "m", "risk_summary": "r",
        "technical_summary": "t", "news_summary": "n",
        "allocation_feedback": [],
    }


def test_trader_produces_weight_vector_and_bucket_target(tmp_path):
    up = _universe(tmp_path)
    step_a = _FakeStep(BucketAllocation(weights={"a1_cash": 0.4, "b1_kr_equity": 0.6}))
    step_b = _FakeStep(StockSelection(selections={
        "a1_cash": ["C1", "C2"], "b1_kr_equity": ["E1", "E2", "E3"]}))
    node = create_trader_allocator(step_a_llm=step_a, step_b_llm=step_b)
    out = node(_state(up))

    bt = out["bucket_target"]
    assert isinstance(bt, BucketTarget)
    assert bt.weights["b1_kr_equity"] == pytest.approx(0.6)
    assert isinstance(out["candidate_set"], CandidateSet)
    wv = out["weight_vector"]
    assert isinstance(wv, WeightVector)
    assert wv.method == OptimizationMethod.AUM_WEIGHTED
    assert sum(wv.weights.values()) == pytest.approx(1.0, abs=1e-3)
    assert all(w <= 0.20 + 1e-6 for w in wv.weights.values())   # 단일 ETF ≤20%
    assert out["allocation_attribution"]["realized_risk_pct"] == pytest.approx(0.60, abs=1e-3)
    assert "C1" in wv.weights


def test_trader_normalizes_offsum_bucket_weights(tmp_path):
    up = _universe(tmp_path)
    step_a = _FakeStep(BucketAllocation(weights={"a1_cash": 0.8, "b1_kr_equity": 1.2}))
    step_b = _FakeStep(StockSelection(selections={
        "a1_cash": ["C1", "C2"], "b1_kr_equity": ["E1", "E2", "E3"]}))
    node = create_trader_allocator(step_a_llm=step_a, step_b_llm=step_b)
    out = node(_state(up))
    assert sum(out["bucket_target"].weights.values()) == pytest.approx(1.0)
    assert out["bucket_target"].weights["b1_kr_equity"] == pytest.approx(0.6)


def test_trader_drops_unknown_bucket_keys(tmp_path):
    up = _universe(tmp_path)
    step_a = _FakeStep(BucketAllocation(weights={
        "a1_cash": 0.4, "b1_kr_equity": 0.6, "garbage_key": 0.5}))
    step_b = _FakeStep(StockSelection(selections={
        "a1_cash": ["C1", "C2"], "b1_kr_equity": ["E1", "E2", "E3"]}))
    node = create_trader_allocator(step_a_llm=step_a, step_b_llm=step_b)
    out = node(_state(up))
    assert "garbage_key" not in out["bucket_target"].weights
