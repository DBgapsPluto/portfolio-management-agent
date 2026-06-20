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

============================== WHAT BINDS THE LEVER ==============================
The realized concentration lever is bounded by the RELEVANT CATEGORY CAP (and, for
a single-bucket theme, by the bucket band) — NOT by the 35% correlation-cluster
cap, which never binds for a semiconductor theme in any of these measurements.

Three controlled measurements, each isolating a different layer:

  1. test_..._sector_cap_binds_at_010  (cross-bucket, ALL semis in 해외주식_섹터)
     A semiconductor ETF placed in the overseas-SECTOR category has CATEGORY_CAP
     0.10. With a maximal cross-bucket (b2+b3) melt-up the 0.10 *category* cap claws
     the cluster back.
        MEASURED: realized semi_cluster_sum == 0.1000  (binding = 해외주식_섹터 cap 0.10)
     IMPORTANT — this 0.10 figure is SPECIFIC to overseas-sector ETFs grouped into a
     single 0.10 category. It is NOT "the semiconductor lever": the real semi theme
     spans THREE categories (see measurement 3) and is not pinned at 0.10.

  2. test_..._clusterlever_under_035_in_highcap_category  (cross-bucket, 해외주식_지수)
     Same melt-up but the semis are categorized as a HIGH-cap broad-index category
     (해외주식_지수, cap 0.30). The cross-bucket cluster now concentrates ~0.30.
        MEASURED: realized semi_cluster_sum ~= 0.30  (binding = 해외주식_지수 cap 0.30)
     NOTE — the 0.35 cluster cap does NOT bind even here; the 0.30 *category* cap
     pre-empts it. This test quantifies the high-cap *category* ceiling (~0.30), not
     the cluster cap. The 0.35 cluster cap is moot in every case measured here.

  3. test_..._real_universe_category_mixed  (REAL shape — all semis in ONE bucket b3,
     spanning 해외주식_지수 0.30 / 해외주식_섹터 0.10 / 국내주식_섹터 0.15)
     The honest aggregate lever for a real category-mixed semiconductor theme.
     Per-category caps sum to 0.55, so the aggregate exceeds any single 0.10; here
     the b3 BUCKET BAND (~0.17-0.19) is the operative ceiling.
        MEASURED: realized aggregate semi_sum == 0.1669  (binding = b3 bucket band)

Honest lever summary: the realized semiconductor concentration lever is ~0.10 ONLY
for the artificial single-category overseas-sector case; for the REAL category-mixed
theme it is ~0.17 (bounded by the b3 bucket band), and it reaches ~0.30 only if the
theme is re-categorized into a 0.30-cap broad-index category. The 35% correlation-
cluster cap NEVER binds in any of these measurements — the relevant category cap or
the bucket band always pre-empts it.
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


# ======================================================================
# THIRD measurement — the REAL universe shape (data/universe.json):
# every favored semiconductor ETF sits in ONE bucket (b3_global_tech) but
# spans THREE distinct categories with THREE different caps:
#   해외주식_지수  (cap 0.30) — e.g. TIGER 미국필라델피아반도체나스닥
#   해외주식_섹터  (cap 0.10) — ACE 글로벌반도체TOP4 / TIGER AI반도체 / KODEX 미국반도체
#   국내주식_섹터  (cap 0.15) — KODEX 반도체 / KODEX AI반도체 / HANARO K-반도체 / SOL AI반도체소부장
# This is the category-mixed real semiconductor THEME. Because category caps
# are PER-category, the aggregate semi capacity is 0.30+0.10+0.15 = 0.55 — far
# above any single 0.10 — so the realized lever can (and does) exceed 0.10.
# ======================================================================
REAL_SEMI_TICKERS = (
    "R_SEMI_IDX_1",                              # 해외주식_지수 (0.30)
    "R_SEMI_OSEC_1", "R_SEMI_OSEC_2", "R_SEMI_OSEC_3",   # 해외주식_섹터 (0.10)
    "R_SEMI_KSEC_1", "R_SEMI_KSEC_2", "R_SEMI_KSEC_3", "R_SEMI_KSEC_4",  # 국내주식_섹터 (0.15)
)
KR_SECTOR_CAT = "국내주식_섹터"   # cap 0.15 — real KR semiconductor ETFs (e.g. KODEX 반도체)


def _real_semi_universe(tmp_path):
    """Mirror data/universe.json: all 8 favored semiconductor ETFs in ONE bucket
    (b3_global_tech) spanning the 3 real categories, plus a disfavored battery_ev
    sub-category in the same bucket so the selector has something to exclude.

    distinct underlying_index per ETF so index-dedup keeps them all; high AUM so
    they survive the liquidity floor. All carry sub_category 'semiconductor' so the
    LLM's {semiconductor: +0.8} view favors the whole theme at once.
    """
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
    # b3_global_tech: 8 favored semiconductor ETFs across the 3 real categories
    # + 2 disfavored battery_ev so the selector excludes something.
    semi_specs = [
        ("R_SEMI_IDX_1", INDEX_CAT, 6.0e11),
        ("R_SEMI_OSEC_1", SECTOR_CAT, 5.0e11),
        ("R_SEMI_OSEC_2", SECTOR_CAT, 4.5e11),
        ("R_SEMI_OSEC_3", SECTOR_CAT, 4.0e11),
        ("R_SEMI_KSEC_1", KR_SECTOR_CAT, 5.5e11),
        ("R_SEMI_KSEC_2", KR_SECTOR_CAT, 5.0e11),
        ("R_SEMI_KSEC_3", KR_SECTOR_CAT, 4.5e11),
        ("R_SEMI_KSEC_4", KR_SECTOR_CAT, 4.0e11),
    ]
    for ticker, cat, aum in semi_specs:
        etfs.append({
            "ticker": ticker, "name": f"{ticker}반도체", "aum_krw": aum,
            "underlying_index": f"idx_{ticker}", "bucket": "위험", "category": cat,
            "gaps_bucket": "b3_global_tech", "sub_category": "semiconductor",
        })
    etfs += [
        {"ticker": "R_BATT_1", "name": "이차전지1", "aum_krw": 3.0e11,
         "underlying_index": "idx_rbatt_1", "bucket": "위험", "category": "해외주식_섹터",
         "gaps_bucket": "b3_global_tech", "sub_category": "battery_ev"},
        {"ticker": "R_BATT_2", "name": "이차전지2", "aum_krw": 2.0e11,
         "underlying_index": "idx_rbatt_2", "bucket": "위험", "category": "해외주식_섹터",
         "gaps_bucket": "b3_global_tech", "sub_category": "battery_ev"},
    ]
    p = tmp_path / "u_real_semi.json"
    p.write_text(json.dumps({"version": "t", "etfs": etfs}, ensure_ascii=False))
    return str(p)


def _real_semi_factor_panel():
    """Favored semiconductor ETFs: strong momentum. battery_ev: negative. Rest: flat."""
    panel = {}
    for k in GAPS_BUCKET_KEYS:
        if k == "b3_global_tech":
            continue
        for i in (1, 2):
            panel[f"T_{k}_{i}"] = SimpleNamespace(
                skip1m_mom_3m=0.0, skip1m_mom_6m=0.0, skip1m_mom_12m=0.0,
                realized_vol_60d=0.12, log_aum=math.log(100.0 * i))
    for t in REAL_SEMI_TICKERS:
        panel[t] = SimpleNamespace(
            skip1m_mom_3m=0.30, skip1m_mom_6m=0.45, skip1m_mom_12m=0.60,
            realized_vol_60d=0.15, log_aum=math.log(5.0e11))
    for t in ("R_BATT_1", "R_BATT_2"):
        panel[t] = SimpleNamespace(
            skip1m_mom_3m=-0.30, skip1m_mom_6m=-0.40, skip1m_mom_12m=-0.50,
            realized_vol_60d=0.40, log_aum=math.log(2.0e11))
    return panel


def _real_semi_step_a():
    """Single-bucket melt-up: favor semiconductor in b3 only (the real shape)."""
    return _FakeStep(BucketTilt(
        tilts={"b3_global_tech": 0.06},
        sub_category_views={
            "b3_global_tech": {"semiconductor": 0.8, "battery_ev": -0.5},
        },
        rationale="AI 반도체 멜트업 — b3 단일 버킷 반도체 집중 (실제 유니버스 형상)"))


def _run_real_semi_meltup(tmp_path):
    up = _real_semi_universe(tmp_path)
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
        "technical_report": SimpleNamespace(factor_panel=_real_semi_factor_panel()),
        # One correlation cluster over ALL 8 semiconductor ETFs (real: tightly correlated).
        "correlation_clusters": [Cluster(
            cluster_id="semi_theme", members=list(REAL_SEMI_TICKERS),
            avg_internal_correlation=0.92, category_label="반도체")],
        # Raise top_k so the selector can carry the whole favored semi theme (default 3
        # would under-sample the 8-ETF theme and understate the achievable aggregate).
        "portfolio_dials": {"top_k_heterogeneous": 8},
    }
    node = create_trader_allocator(step_a_llm=_real_semi_step_a())
    result = node(state)
    weights = result["weight_vector"].weights
    semi_sum = sum(weights.get(t, 0.0) for t in REAL_SEMI_TICKERS)
    return result, weights, semi_sum


def test_realized_semi_concentration_sector_cap_binds_at_010(tmp_path):
    """OVERSEAS-SECTOR single-category case: ALL semis categorized as 해외주식_섹터
    (sector, 0.10 cap), grouped into ONE category.

    Even with a maximal cross-bucket melt-up favoring semiconductor in BOTH b2 and
    b3, the realized cluster weight is clawed back to the 0.10 *category* cap — the
    35% cluster cap never binds.

    MEASURED (recorded deliverable): semi_cluster_sum == 0.1000
        binding constraint = CATEGORY_CAPS['해외주식_섹터'] = 0.10  (NOT the 0.35 cluster cap)

    SCOPE — this 0.10 figure is SPECIFIC to overseas-sector ETFs collapsed into a
    single 0.10 category. It is NOT "the semiconductor lever": the REAL semi theme
    (data/universe.json) spans THREE categories — 지수 0.30 / 해외섹터 0.10 / 국내섹터
    0.15 — and its aggregate is NOT pinned at 0.10 (see the category-mixed test, which
    measures ~0.17). This test isolates the overseas-sector *category* cap alone.
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
    """HIGH-cap CATEGORY case: put the favored semiconductor sub-category in a
    HIGH-cap category (해외주식_지수, 0.30 cap) so the 0.10 sector cap no longer
    pre-empts it. The cross-bucket cluster now concentrates ~0.30 of the book.

    MEASURED (recorded deliverable): semi_cluster_sum ~= 0.30
        binding constraint here = the 0.30 *category* cap (해외주식_지수), NOT the cluster cap

    CORRECTION — this test does NOT isolate the 35% cluster cap. The 0.30 *category*
    cap binds first and pins the realized sum at ~0.30; the 0.35 cluster cap stays
    SLACK (0.30 < 0.35) and never engages. What this measures is the high-cap
    *category* ceiling (~0.30), i.e. how large the lever gets when semis sit in a
    0.30-cap broad-index category instead of the 0.10 sector category. The 35%
    cluster cap is moot here as in every other case in this file.
    """
    assert CATEGORY_CAPS[INDEX_CAT] == 0.30  # premise: high-cap category
    result, weights, semi_cluster_sum = _run_meltup(tmp_path, INDEX_CAT)

    assert any(t in weights for t in SEMI_CLUSTER_TICKERS), \
        f"semiconductor should be selected: {list(weights)}"

    # MEASURED ~= 0.30. Lower bound 0.20 proves the cross-bucket favored sub-cat is
    # a genuinely LARGE lever once the 0.10 sector cap is removed; the realized sum is
    # pinned by the 0.30 index *category* cap and stays UNDER the slack 0.35 cluster cap.
    assert 0.20 < semi_cluster_sum <= 0.30 + 1e-3, (
        f"realized semi cluster sum = {semi_cluster_sum:.4f} "
        f"(expected ~0.30, pinned by the 0.30 index category cap)")
    assert semi_cluster_sum < 0.35, (
        "0.35 cluster cap stays slack — the 0.30 category cap binds first")

    # integrity
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-3)
    assert all(w <= 0.20 + 1e-6 for w in weights.values())


def test_realized_semi_concentration_real_universe_category_mixed(tmp_path):
    """REAL-UNIVERSE shape: the TRUE aggregate lever for a category-mixed semi theme.

    Mirrors data/universe.json: all 8 favored semiconductor ETFs sit in ONE bucket
    (b3_global_tech) but span THREE real categories with THREE caps —
    해외주식_지수 (0.30), 해외주식_섹터 (0.10), 국내주식_섹터 (0.15) — all in one
    correlation cluster. Because category caps are PER-category, the *combined* semi
    capacity is 0.30 + 0.10 + 0.15 = 0.55, so the realized aggregate can (and does)
    EXCEED any single 0.10 sector-category figure. This is the honest aggregate lever
    for a real, category-mixed semiconductor theme — NOT the misleading single-bucket
    single-category 0.10 number.

    MEASURED (recorded deliverable): semi_sum == 0.1669
        per-category realized: 해외주식_지수 ~0.021, 해외주식_섹터 ~0.063, 국내주식_섹터 ~0.084
        all 8 favored semis selected (top_k raised to 8), equal-weighted ~0.021 each.

    Which cap binds? NONE of the three category caps (realized per-category 0.02/0.06/0.08
    are all far under 0.30/0.10/0.15) and NOT the 0.35 correlation-CLUSTER cap (0.167 «
    0.35). The binding constraint is the b3_global_tech BUCKET BAND ceiling (~0.19
    pre-haircut, ~0.167 after vol-haircut + renormalize): a single-bucket theme cannot
    exceed that bucket's own band, no matter how many sub-categories it spans. So even
    the category caps are moot here — the bucket band is the operative lever.

    Honest bottom-line: for a REAL semiconductor theme (all in b3, category-mixed) the
    realized aggregate lever is ~0.17 of the book — about 1.7x the 0.10 overseas-sector
    single-category figure (the 3 per-category caps remove the 0.10 pin), yet still
    bounded by the b3 bucket band, well short of the 0.35 cluster cap. The cluster cap
    does NOT engage for a single-bucket semi theme; it would only bite a cross-bucket
    theme whose combined bucket bands sum above 0.35.
    """
    # premises: the three real semiconductor categories and their caps.
    assert CATEGORY_CAPS[INDEX_CAT] == 0.30
    assert CATEGORY_CAPS[SECTOR_CAT] == 0.10
    assert CATEGORY_CAPS[KR_SECTOR_CAT] == 0.15

    result, weights, semi_sum = _run_real_semi_meltup(tmp_path)

    # disfavored battery_ev excluded; the whole favored semi theme is selected.
    assert not any(t.startswith("R_BATT") for t in weights), \
        f"battery_ev should be excluded: {list(weights)}"
    selected_semis = [t for t in REAL_SEMI_TICKERS if t in weights]
    assert len(selected_semis) >= 6, \
        f"most of the favored semi theme should be carried: {selected_semis}"

    # per-category realized sums — prove NO single category cap binds (the 0.10
    # pin is gone because the theme is split across 3 per-category caps).
    cat_of = {
        "R_SEMI_IDX_1": INDEX_CAT,
        "R_SEMI_OSEC_1": SECTOR_CAT, "R_SEMI_OSEC_2": SECTOR_CAT, "R_SEMI_OSEC_3": SECTOR_CAT,
        "R_SEMI_KSEC_1": KR_SECTOR_CAT, "R_SEMI_KSEC_2": KR_SECTOR_CAT,
        "R_SEMI_KSEC_3": KR_SECTOR_CAT, "R_SEMI_KSEC_4": KR_SECTOR_CAT,
    }
    by_cat: dict[str, float] = {}
    for t in REAL_SEMI_TICKERS:
        by_cat[cat_of[t]] = by_cat.get(cat_of[t], 0.0) + weights.get(t, 0.0)
    for c, tot in by_cat.items():
        assert tot <= CATEGORY_CAPS[c] + 1e-6, f"{c} {tot:.4f} > cap {CATEGORY_CAPS[c]}"

    # The documented aggregate lever: MEASURED == 0.1669. It is meaningfully ABOVE the
    # single 0.10 overseas-sector figure (category mixing removes that pin) yet bounded
    # by the b3 bucket band — NOT the 0.35 cluster cap (which stays moot).
    assert 0.14 < semi_sum < 0.22, (
        f"realized aggregate semi sum = {semi_sum:.4f} "
        f"(expected ~0.167, bounded by the b3 bucket band, above the single-cat 0.10)")
    assert semi_sum > CATEGORY_CAPS[SECTOR_CAT] + 1e-6, (
        "aggregate exceeds a single 0.10 sector cap — category mixing IS the lever")
    assert semi_sum < 0.35, (
        "0.35 cluster cap does NOT bind for a single-bucket category-mixed semi theme")

    # integrity
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-3)
    assert all(w <= 0.20 + 1e-6 for w in weights.values())
    assert result["weight_vector"].method == OptimizationMethod.AUM_WEIGHTED
