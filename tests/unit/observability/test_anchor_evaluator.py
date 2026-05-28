"""Historical anchor evaluator — sanity & check logic."""
import json
from pathlib import Path

import pytest

from tradingagents.observability.anchor_evaluator import (
    CheckResult, AnchorEvalResult, _sub_category_totals, _bucket_of_ticker,
)
from tradingagents.dataflows.universe import Universe, ETFEntry


def _mini_universe():
    return Universe(version="t", etfs=[
        ETFEntry(ticker="A1", name="KODEX 200", aum_krw=10e12,
                 underlying_index="x", bucket="위험", category="국내주식_지수",
                 sub_category="index_broad"),
        ETFEntry(ticker="A2", name="KODEX 반도체", aum_krw=5e12,
                 underlying_index="x", bucket="위험", category="국내주식_섹터",
                 sub_category="semiconductor"),
        ETFEntry(ticker="A3", name="KODEX 골드", aum_krw=2e12,
                 underlying_index="x", bucket="위험", category="FX 및 원자재",
                 sub_category="gold"),
        ETFEntry(ticker="A4", name="KODEX MMF", aum_krw=3e12,
                 underlying_index="x", bucket="안전", category="금리연계형/초단기채권",
                 sub_category="mmf_kr"),
    ])


def test_sub_category_totals_aggregation():
    u = _mini_universe()
    weights = {"A1": 0.30, "A2": 0.10, "A3": 0.05, "A4": 0.55}
    totals = _sub_category_totals(weights, u)
    assert totals["index_broad"] == pytest.approx(0.30)
    assert totals["semiconductor"] == pytest.approx(0.10)
    assert totals["gold"] == pytest.approx(0.05)
    assert totals["mmf_kr"] == pytest.approx(0.55)


def test_bucket_of_ticker():
    u = _mini_universe()
    m = _bucket_of_ticker(u)
    assert m["A1"] == "kr_equity"
    assert m["A2"] == "kr_equity"
    assert m["A3"] == "fx_commodity"
    assert m["A4"] == "cash_mmf"


def test_eval_result_pass_count():
    r = AnchorEvalResult(
        anchor_id="t", as_of_date="2024-01-01", title="t",
        checks=[
            CheckResult(name="a", passed=True),
            CheckResult(name="b", passed=False),
            CheckResult(name="c", passed=True),
        ],
        chosen_method="hrp", weights={}, sub_category_totals={},
        n_unique_sub_categories=0, risk_asset_total=0.0,
    )
    assert r.pass_count == 2
    assert r.fail_count == 1


def test_substitute_group_satisfied_by_any_label():
    """KR boom 시 KOSPI200(index_broad) 비중만 있어도 kr_growth_theme 충족."""
    weights = {"A1": 0.15, "A4": 0.85}    # index_broad 15%, mmf_kr 85%
    u = _mini_universe()
    totals = _sub_category_totals(weights, u)
    # 직접 group check 로직 검증
    group = {"name": "kr_growth", "any_of": ["semiconductor", "index_broad"], "min_total_weight": 0.10}
    g_total = sum(totals.get(sc, 0) for sc in group["any_of"])
    assert g_total >= group["min_total_weight"]   # index_broad 0.15 ≥ 0.10


def test_substitute_group_failed_when_none_of_any_of_present():
    weights = {"A4": 1.0}    # mmf_kr only
    u = _mini_universe()
    totals = _sub_category_totals(weights, u)
    group = {"name": "kr_growth", "any_of": ["semiconductor", "index_broad"], "min_total_weight": 0.10}
    g_total = sum(totals.get(sc, 0) for sc in group["any_of"])
    assert g_total == 0.0
    assert g_total < group["min_total_weight"]


def test_substitute_group_summed_across_labels():
    """여러 라벨 비중 합산도 인정."""
    weights = {"A1": 0.05, "A2": 0.04, "A3": 0.91}    # index_broad 5%, semiconductor 4%, gold 91%
    u = _mini_universe()
    totals = _sub_category_totals(weights, u)
    group = {"name": "kr_growth", "any_of": ["semiconductor", "index_broad"], "min_total_weight": 0.08}
    g_total = sum(totals.get(sc, 0) for sc in group["any_of"])
    assert g_total == pytest.approx(0.09)  # 5% + 4%
    assert g_total >= group["min_total_weight"]


def test_catalog_files_load_against_schema():
    """모든 anchor JSON이 필수 필드 갖춤."""
    catalog = Path(__file__).resolve().parents[3] / "data" / "historical_anchors"
    if not catalog.exists():
        pytest.skip("catalog not present")
    required_top = {"anchor_id", "as_of_date", "title", "description",
                    "consensus_reasoning", "stage1", "stage2", "expected_stage3"}
    for p in catalog.glob("*.json"):
        if p.name.startswith("_"):
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        missing = required_top - set(data)
        assert not missing, f"{p.name} missing keys: {missing}"
        # stage2 cell key 형식 확인
        cell = data["stage2"]["dominant_cell"]
        parts = cell.split("_")
        assert len(parts) == 3, f"{p.name} invalid cell {cell}"
        assert parts[0] in {"A", "B", "C", "D"}
        assert parts[1] in {"N", "T"}
        assert parts[2] in {"F", "boom", "stress"}
        # bucket_target 합 ≈ 1
        bt = data["stage2"]["bucket_target"]
        s = sum(bt[k] for k in ("kr_equity", "global_equity", "fx_commodity",
                                  "bond", "cash_mmf"))
        assert abs(s - 1.0) < 0.01, f"{p.name} bucket_target sum={s:.3f}"
