"""End-to-end property test for the confidence-scaled BL prior (Task 5 / MATH-1).

Drives the REAL trader_allocator node twice with identical inputs except
`macro_report.regime.signal_confidence` = 0.0 vs 1.0, with NO views
(`bl_fixed_ranking={}`). With no views the BL posterior recovers the prior
exactly (MATH-1), so the realized `bucket_target` ≈ prior_w =
(1−c)·W_NEUTRAL + c·QUADRANT_BASELINE[quadrant]. Hence c genuinely moves the
bucket allocation: risk-proxy sum 0.50 (neutral, c=0) ↔ baseline risk (c=1).

Harness REUSED from tests/unit/agents/trader/test_trader_allocator.py
(_universe_14 / _state_14 / _FakeStep) and the Σ monkeypatch from
test_trader_allocator_bl_branch.py (ta.fetch_bucket_proxy_returns).

Placed under tests/integration/ because the repo already keeps end-to-end
node-driving tests here (test_allocator_phase2a.py etc.) and conftest.py here
pre-mocks pypfopt/cvxpy that the BL import chain needs.
"""
from __future__ import annotations

import json
import types
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingagents.agents.trader import trader_allocator as ta
from tradingagents.agents.trader.trader_allocator import create_trader_allocator
from tradingagents.schemas.portfolio import BucketTilt
from tradingagents.schemas.research import ResearchThesis
from tradingagents.skills.portfolio.gaps_buckets import (
    GAPS_BUCKET_KEYS, GROWTH_KEYS,
)
from tradingagents.skills.portfolio.scenario_anchor import QUADRANT_BASELINE

# risk-proxy = mandate RISK_PROXY (a5 ∪ 성장버킷) — same set the node uses for
# W_NEUTRAL's 0.50 normalization (_MANDATE_RISK_BUCKETS / _RISK_PROXY_KEYS).
_RISK = {"a5_gold_infl"} | set(GROWTH_KEYS)
_QUADRANT = "growth_disinflation"   # fixture regime; base risk ≈ 0.68 ≠ 0.50 (clear gap)


def _risk_of(weights: dict) -> float:
    return sum(v for k, v in weights.items() if k in _RISK)


class _FakeStep:
    """with_structured_output(schema).invoke(prompt) → 미리 정한 객체 (never used:
    bl_fixed_ranking={} short-circuits the LLM)."""
    def __init__(self, obj):
        self._o = obj

    def with_structured_output(self, schema):
        return self

    def invoke(self, prompt):
        return self._o


def _universe_14(tmp_path):
    """14버킷 각 2 ETF — anchor 비중이 풀 부족으로 cash 로 쏠리지 않게 (reused harness)."""
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


def _macro_with_conf(c):
    """macro_report carrying regime.quadrant + regime.signal_confidence=c (+ neutral
    fx/credit). signal_confidence is the lever build_bl_bucket_weights reads."""
    return types.SimpleNamespace(
        regime=types.SimpleNamespace(
            quadrant=_QUADRANT, confidence=0.8, signal_confidence=c,
        ),
        fx=types.SimpleNamespace(regime="neutral"),
        financial_conditions=types.SimpleNamespace(regime="neutral"),
    )


def _state_bl(universe_path, c):
    """BL-branch state: use_bl=True, NO views (bl_fixed_ranking={} ⇒ MATH-1),
    signal_confidence=c on the macro_report regime."""
    return {
        "research_decision": ResearchThesis(risk_tilt="neutral", thesis_md="t"),
        "universe_path": universe_path,
        "macro_report": _macro_with_conf(c),
        "macro_summary": "m", "risk_summary": "r",
        "technical_summary": "t", "news_summary": "n",
        "allocation_feedback": [],
        "as_of_date": "2026-05-10",
        "capital_krw": 100_000_000,
        "portfolio_dials": {"use_bl": True},
        "bl_fixed_ranking": {},   # no-view lever → BL posterior == prior (MATH-1)
    }


@pytest.fixture
def patch_proxies(monkeypatch):
    """Offline synthetic 14-bucket Σ returns (reused from test_trader_allocator_bl_branch)."""
    def fake_proxies(as_of, window_days=730):
        idx = pd.bdate_range(end=pd.Timestamp(as_of), periods=400)
        rng = np.random.default_rng(0)
        return pd.DataFrame(
            rng.normal(0, 0.01, (400, 14)), index=idx, columns=list(GAPS_BUCKET_KEYS)
        )
    monkeypatch.setattr(ta, "fetch_bucket_proxy_returns", fake_proxies)
    return fake_proxies


def _run_node_with_conf(c, universe_path) -> dict:
    """Drive the real node with signal_confidence=c, return bucket_target.weights."""
    node = create_trader_allocator(step_a_llm=_FakeStep(BucketTilt()))
    out = node(_state_bl(universe_path, c))
    return dict(out["bucket_target"].weights)


def test_signal_confidence_moves_bucket_target(tmp_path, patch_proxies):
    up = _universe_14(tmp_path)
    bt0 = _run_node_with_conf(0.0, up)   # neutral prior
    bt1 = _run_node_with_conf(1.0, up)   # baseline prior

    base_risk = _risk_of(QUADRANT_BASELINE[_QUADRANT])   # ≈ 0.68
    r0 = _risk_of(bt0)
    r1 = _risk_of(bt1)

    # Tight invariant (abs 0.02): with no views (MATH-1), ample pool capacity and
    # no clusters, the realized bucket_target ≈ prior_w, so risk-proxy lands at the
    # neutral 0.50 (c=0) / baseline (c=1) endpoints.
    assert r0 == pytest.approx(0.50, abs=0.02), f"c=0 risk {r0} ≠ 0.50"
    assert r1 == pytest.approx(base_risk, abs=0.02), f"c=1 risk {r1} ≠ base {base_risk}"

    # c genuinely MOVES the allocation (direction + meaningful L1 magnitude).
    assert r1 > r0, f"baseline risk {r1} should exceed neutral {r0}"
    l1 = sum(abs(bt0.get(b, 0.0) - bt1.get(b, 0.0)) for b in set(bt0) | set(bt1))
    assert l1 > 0.05, f"L1 between c=0/c=1 bucket_target too small: {l1}"

    # Guards: both targets are valid simplex points.
    assert sum(bt0.values()) == pytest.approx(1.0, abs=1e-6)
    assert sum(bt1.values()) == pytest.approx(1.0, abs=1e-6)
    assert all(v >= -1e-9 for v in bt0.values())
    assert all(v >= -1e-9 for v in bt1.values())
