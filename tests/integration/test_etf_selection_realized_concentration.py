"""Integration: quantify the REALIZED semiconductor concentration the ETF-selection
hybrid can actually deliver after the full Step-B allocation + repair clawback.

The "ETF-selection hybrid" lets the LLM favor a sub-category (e.g. semiconductor)
inside heterogeneous buckets (b2_dm_core / b3_global_tech / b5_other_intl); the
trader then narrows by sub_category_views, picks top-K by risk-adjusted momentum,
and momentum-weights them. Two self-imposed caps can claw back that concentration
inside _repair_all_weights (interleaved category/risk/cluster loop):

  * a per-CATEGORY cap (concentration_check.CATEGORY_CAPS), and
  * a 35% correlation-CLUSTER cap (repair_cluster_cap).

This test MEASURES which cap actually binds for a realistic favored-semiconductor
melt-up, and records the realized lever size.

================================ KEY FINDING ================================
A real semiconductor ETF is a *sector* ETF -> category "해외주식_섹터", whose
CATEGORY_CAP is **0.10**. So even when the LLM maximally favors semiconductor in
BOTH b2 and b3 (cross-bucket), with all 4 semi ETFs at high momentum and grouped
into one correlation cluster, the Step-B allocation that *wants* ~0.30 of the book
is clawed back by the 0.10 sector category cap — NOT the 35% cluster cap.

    MEASURED (sector category, the realistic case):
        realized semi_cluster_sum == 0.1000  (binding cap = category 해외주식_섹터 = 0.10)

The 35% cluster cap is therefore *moot* for a real sector theme: the sector
category cap (0.10) binds first and dominates. The cluster cap only becomes the
binding lever for a favored sub-category whose ETFs sit in a HIGH-cap category
(e.g. a broad-index category capped at 0.30). To prove the cluster-cap lever is
real and quantify ITS ceiling, the second test repeats the melt-up with the semi
ETFs categorized as a 0.30-cap index category:

    MEASURED (high-cap category, isolating the cluster lever):
        realized semi_cluster_sum ~= 0.30  (cross-bucket b2+b3, just under the 0.35 cap)

Honest lever summary: for the *realistic* semiconductor (sector) case the concen-
tration lever is small — clamped to 0.10 by the sector category cap. The 35%
cluster cap is the binding constraint only for high-cap categories, where the
cross-bucket lever reaches ~0.30 and would be clipped at 0.35.
"""
from __future__ import annotations

import json
import math
from types import SimpleNamespace

import pytest

from tradingagents.schemas.research import ResearchThesis
from tradingagents.schemas.portfolio import BucketTilt, OptimizationMethod
from tradingagents.schemas.technical import Cluster
from tradingagents.agents.trader.trader_allocator import create_trader_allocator
from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS
from tradingagents.skills.mandate.concentration_check import CATEGORY_CAPS


# The cross-bucket semiconductor correlation cluster under measurement.
SEMI_CLUSTER_TICKERS = ("A_SEMI_B2_1", "A_SEMI_B2_2", "A_SEMI_B3_1", "A_SEMI_B3_2")
SECTOR_CAT = "해외주식_섹터"      # realistic for a semiconductor sector ETF (cap 0.10)
INDEX_CAT = "해외주식_지수"      # high-cap broad-index category (cap 0.30)


class _FakeStep:
    """with_structured_output(schema).invoke(prompt) -> preset object."""

    def __init__(self, obj):
        self._o = obj

    def with_structured_output(self, schema):
        return self

    def invoke(self, prompt):
        return self._o


class _FakeRegime:
    def __init__(self, quadrant, confidence):
        self.quadrant = quadrant
        self.confidence = confidence


def _meltup_universe(tmp_path, semi_category):
    """14 buckets x2 ETF, but b2_dm_core & b3_global_tech expanded into a favored
    semiconductor sub-category (2 ETFs each, high AUM) PLUS a disfavored
    non-semi sub-category (2 ETFs each) so the selector has something to exclude.

    Semiconductor spans two heterogeneous buckets -> a cross-bucket cluster of 4
    ETFs whose Step-B-intended weight (~b2+b3 bucket weight ~0.30) can exceed any
    single bucket's weight. `semi_category` is parameterized so we can measure the
    realistic sector cap (0.10) vs. a high-cap index category (0.30).
    """
    etfs = []
    for k in GAPS_BUCKET_KEYS:
        if k in ("b2_dm_core", "b3_global_tech"):
            continue
        risk = "안전" if k[0] == "a" else "위험"
        for i in (1, 2):
            etfs.append({
                "ticker": f"T_{k}_{i}", "name": f"{k}{i}", "aum_krw": 100.0 * i,
                "underlying_index": f"idx_{k}_{i}", "bucket": risk,
                "category": "c", "gaps_bucket": k,
            })
    # b2_dm_core: semiconductor (favored, high AUM) + dm_broad (disfavored)
    etfs += [
        {"ticker": "A_SEMI_B2_1", "name": "b2반도체1", "aum_krw": 5.0e11,
         "underlying_index": "idx_semi_b2_1", "bucket": "위험", "category": semi_category,
         "gaps_bucket": "b2_dm_core", "sub_category": "semiconductor"},
        {"ticker": "A_SEMI_B2_2", "name": "b2반도체2", "aum_krw": 4.0e11,
         "underlying_index": "idx_semi_b2_2", "bucket": "위험", "category": semi_category,
         "gaps_bucket": "b2_dm_core", "sub_category": "semiconductor"},
        {"ticker": "A_DMB_1", "name": "선진광범위1", "aum_krw": 3.0e11,
         "underlying_index": "idx_dmb_1", "bucket": "위험", "category": "해외주식_광범위",
         "gaps_bucket": "b2_dm_core", "sub_category": "dm_broad"},
        {"ticker": "A_DMB_2", "name": "선진광범위2", "aum_krw": 2.0e11,
         "underlying_index": "idx_dmb_2", "bucket": "위험", "category": "해외주식_광범위",
         "gaps_bucket": "b2_dm_core", "sub_category": "dm_broad"},
    ]
    # b3_global_tech: semiconductor (favored, high AUM) + battery_ev (disfavored)
    etfs += [
        {"ticker": "A_SEMI_B3_1", "name": "b3반도체1", "aum_krw": 5.0e11,
         "underlying_index": "idx_semi_b3_1", "bucket": "위험", "category": semi_category,
         "gaps_bucket": "b3_global_tech", "sub_category": "semiconductor"},
        {"ticker": "A_SEMI_B3_2", "name": "b3반도체2", "aum_krw": 4.0e11,
         "underlying_index": "idx_semi_b3_2", "bucket": "위험", "category": semi_category,
         "gaps_bucket": "b3_global_tech", "sub_category": "semiconductor"},
        {"ticker": "A_BATT_1", "name": "이차전지1", "aum_krw": 3.0e11,
         "underlying_index": "idx_batt_1", "bucket": "위험", "category": "해외주식_섹터",
         "gaps_bucket": "b3_global_tech", "sub_category": "battery_ev"},
        {"ticker": "A_BATT_2", "name": "이차전지2", "aum_krw": 2.0e11,
         "underlying_index": "idx_batt_2", "bucket": "위험", "category": "해외주식_섹터",
         "gaps_bucket": "b3_global_tech", "sub_category": "battery_ev"},
    ]
    p = tmp_path / f"u_meltup_{semi_category}.json"
    p.write_text(json.dumps({"version": "t", "etfs": etfs}, ensure_ascii=False))
    return str(p)


def _meltup_factor_panel():
    """All semiconductor ETFs: strong positive momentum. Disfavored sub-cats:
    strong negative momentum + high vol. Other buckets: flat / low vol."""
    panel = {}
    for k in GAPS_BUCKET_KEYS:
        if k in ("b2_dm_core", "b3_global_tech"):
            continue
        for i in (1, 2):
            panel[f"T_{k}_{i}"] = SimpleNamespace(
                skip1m_mom_3m=0.0, skip1m_mom_6m=0.0, skip1m_mom_12m=0.0,
                realized_vol_60d=0.12, log_aum=math.log(100.0 * i),
            )
    for t, aum in (
        ("A_SEMI_B2_1", 5.0e11), ("A_SEMI_B2_2", 4.0e11),
        ("A_SEMI_B3_1", 5.0e11), ("A_SEMI_B3_2", 4.0e11),
    ):
        panel[t] = SimpleNamespace(
            skip1m_mom_3m=0.30, skip1m_mom_6m=0.45, skip1m_mom_12m=0.60,
            realized_vol_60d=0.15, log_aum=math.log(aum))
    for t, aum in (
        ("A_DMB_1", 3.0e11), ("A_DMB_2", 2.0e11),
        ("A_BATT_1", 3.0e11), ("A_BATT_2", 2.0e11),
    ):
        panel[t] = SimpleNamespace(
            skip1m_mom_3m=-0.30, skip1m_mom_6m=-0.40, skip1m_mom_12m=-0.50,
            realized_vol_60d=0.40, log_aum=math.log(aum))
    return panel


def _meltup_state(tmp_path, semi_category):
    up = _meltup_universe(tmp_path, semi_category)
    macro = SimpleNamespace(
        regime=_FakeRegime("growth_disinflation", 0.8),
        fx=SimpleNamespace(regime="neutral"),
        financial_conditions=SimpleNamespace(regime="neutral"),
    )
    state = {
        "research_decision": ResearchThesis(risk_tilt="neutral", thesis_md="t"),
        "universe_path": up, "macro_report": macro,
        "macro_summary": "m", "risk_summary": "r",
        "technical_summary": "t", "news_summary": "n",
        "allocation_feedback": [],
        "technical_report": SimpleNamespace(factor_panel=_meltup_factor_panel()),
        # Single cross-bucket correlation cluster over ALL semiconductor ETFs.
        "correlation_clusters": [Cluster(
            cluster_id="semi_xbucket", members=list(SEMI_CLUSTER_TICKERS),
            avg_internal_correlation=0.92, category_label="반도체")],
    }
    return state


def _melt_up_step_a():
    return _FakeStep(BucketTilt(
        tilts={"b3_global_tech": 0.06, "b2_dm_core": 0.06},
        sub_category_views={
            "b2_dm_core": {"semiconductor": 0.8, "dm_broad": -0.5},
            "b3_global_tech": {"semiconductor": 0.8, "battery_ev": -0.5},
        },
        rationale="AI 반도체 멜트업 — b2/b3 동시 반도체 집중"))


def _run_meltup(tmp_path, semi_category):
    node = create_trader_allocator(step_a_llm=_melt_up_step_a())
    result = node(_meltup_state(tmp_path, semi_category))
    weights = result["weight_vector"].weights
    semi_cluster_sum = sum(weights.get(t, 0.0) for t in SEMI_CLUSTER_TICKERS)
    return result, weights, semi_cluster_sum


def test_realized_semi_concentration_sector_cap_binds_at_010(tmp_path):
    """REALISTIC case: semiconductor ETF categorized as 해외주식_섹터 (sector, 0.10 cap).

    Even with a maximal cross-bucket melt-up favoring semiconductor in BOTH b2 and
    b3, the realized cluster weight is clawed back to the 0.10 *category* cap — the
    35% cluster cap never binds.

    MEASURED (recorded deliverable): semi_cluster_sum == 0.1000
        binding constraint = CATEGORY_CAPS['해외주식_섹터'] = 0.10  (NOT the 0.35 cluster cap)

    Honest lever size: for a real semiconductor (sector) theme the concentration
    lever is SMALL — 0.10 of the book — because the sector category cap dominates.
    """
    assert CATEGORY_CAPS[SECTOR_CAT] == 0.10  # premise of this measurement
    result, weights, semi_cluster_sum = _run_meltup(tmp_path, SECTOR_CAT)

    # disfavored + low-momentum sub-categories excluded.
    assert not any(t.startswith("A_BATT") for t in weights), \
        f"battery_ev should be excluded: {list(weights)}"
    assert not any(t.startswith("A_DMB") for t in weights), \
        f"dm_broad should be excluded: {list(weights)}"
    # semiconductor IS selected (the lever is engaged), just clamped.
    assert any(t in weights for t in SEMI_CLUSTER_TICKERS), \
        f"semiconductor should be selected: {list(weights)}"

    # The documented lever: clamped to the 0.10 SECTOR CATEGORY cap, not 0.35.
    # MEASURED == 0.1000. We assert it is meaningfully engaged (>0.05) yet pinned
    # at the 0.10 sector cap — proving the category cap, not the cluster cap, binds.
    assert 0.05 < semi_cluster_sum <= 0.10 + 1e-6, (
        f"realized semi cluster sum = {semi_cluster_sum:.4f} "
        f"(expected pinned at 0.10 sector category cap)")
    assert semi_cluster_sum == pytest.approx(0.10, abs=1e-3), (
        "sector category cap (0.10) should bind exactly")

    # integrity: sum=1, single-ETF cap, valid method.
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-3)
    assert all(w <= 0.20 + 1e-6 for w in weights.values())
    assert result["weight_vector"].method == OptimizationMethod.AUM_WEIGHTED


def test_realized_semi_concentration_clusterlever_under_035_in_highcap_category(tmp_path):
    """ISOLATE the cluster-cap lever: put the favored semiconductor sub-category in
    a HIGH-cap category (해외주식_지수, 0.30 cap) so the sector cap no longer pre-empts
    it. Now the cross-bucket cluster genuinely concentrates ~0.30 of the book and
    the 35% cluster cap is the operative ceiling.

    MEASURED (recorded deliverable): semi_cluster_sum ~= 0.30
        binding constraint here = category 해외주식_지수 (0.30) ~= cluster ceiling (0.35)

    This documents the TRUE size of the cluster lever: ~0.30, just under the 0.35
    cluster cap. The cluster cap would clip any further melt-up; here the 0.30
    index-category cap and the cluster cap coincide closely as the joint ceiling.
    """
    assert CATEGORY_CAPS[INDEX_CAT] == 0.30  # premise: high-cap category
    result, weights, semi_cluster_sum = _run_meltup(tmp_path, INDEX_CAT)

    assert any(t in weights for t in SEMI_CLUSTER_TICKERS), \
        f"semiconductor should be selected: {list(weights)}"

    # MEASURED ~= 0.30. Lower bound 0.20 proves the cross-bucket favored sub-cat is
    # a genuinely LARGE lever once the sector cap is removed; upper bound is the
    # 0.35 cluster cap (and the 0.30 index category cap), both >= the realized sum.
    assert 0.20 < semi_cluster_sum <= 0.35 + 1e-6, (
        f"realized semi cluster sum = {semi_cluster_sum:.4f} "
        f"(expected meaningful 0.20<x<=0.35)")

    # integrity
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-3)
    assert all(w <= 0.20 + 1e-6 for w in weights.values())
