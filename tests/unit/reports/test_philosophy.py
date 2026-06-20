from pathlib import Path
from unittest.mock import MagicMock

from tradingagents.reports.philosophy import (
    generate_philosophy,
    write_philosophy,
    _build_state_summary,
    _audit_philosophy_numbers,
    format_step_a_decomposition,
    _format_scenario_probs,
)
from tradingagents.schemas.research import ResearchThesis


def _make_state():
    wv = MagicMock()
    wv.method = MagicMock(value="hrp")
    wv.weights = {"A069500": 0.5, "A114800": 0.3, "A148070": 0.2}
    wv.rationale = "5-bucket target met"
    return {
        "macro_summary": "regime: recession",
        "risk_summary": "VIX 25",
        "technical_summary": "clusters",
        "news_summary": "events",
        "research_debate_summary": "60/40 풍선",
        "weight_vector": wv,
    }


def test_philosophy_min_length():
    deep_llm = MagicMock()
    deep_llm.invoke.return_value.content = "x" * 4500
    text = generate_philosophy(_make_state(), deep_llm)
    assert len(text) >= 4000


def test_philosophy_retries_when_short():
    """If first response < 4000 chars, generator retries once."""
    deep_llm = MagicMock()
    short = MagicMock(content="too short")
    long = MagicMock(content="y" * 4500)
    deep_llm.invoke.side_effect = [short, long]
    text = generate_philosophy(_make_state(), deep_llm)
    assert len(text) >= 4000
    assert deep_llm.invoke.call_count == 2


def test_write_philosophy_creates_file(tmp_path: Path):
    deep_llm = MagicMock()
    deep_llm.invoke.return_value.content = "z" * 4200
    out = tmp_path / "philosophy.md"
    result = write_philosophy(_make_state(), deep_llm, out)
    assert result == out
    assert out.read_text(encoding="utf-8").startswith("z")
    assert len(out.read_text(encoding="utf-8")) >= 4000


def test_build_state_summary_includes_fx_block():
    state = dict(_make_state())
    state["fx_exposure"] = {"USD": 0.55, "KRW": 0.35, "CNY": 0.10}
    summary = _build_state_summary(state)
    assert "FX(환) 노출" in summary
    assert "USD 55.0%" in summary


def test_build_state_summary_fx_absent_graceful():
    summary = _build_state_summary(_make_state())   # fx_exposure 없음
    assert "FX(환) 노출" in summary
    assert "(미산출)" in summary


def test_step_a_decomp_shows_risk_tilt():
    attribution = {"step_a": {
        "quadrant": "growth_disinflation", "risk_tilt": "defensive",
        "fx_regime": "usd_risk_off", "credit_regime": "tight", "confidence": 0.8,
        "tilt_rationale": "r",
        "buckets": {"a1_cash": {"baseline": 0.08, "scenario_delta": 0.0,
                                "tilt_applied": 0.0, "final": 0.08}},
    }}
    out = format_step_a_decomposition(attribution)
    assert "risk_tilt defensive" in out
    assert "fx usd_risk_off" in out


def test_format_scenario_probs_risk_tilt():
    assert "risk_tilt=offensive" in _format_scenario_probs(ResearchThesis(risk_tilt="offensive"))


# ---- B8: mandate facts block + number grounding audit ----


def test_facts_block_in_state_summary():
    state = dict(_make_state())
    state["allocation_attribution"] = {"realized_risk_pct": 0.62}
    val = MagicMock()
    val.passed = True
    val.violations = []
    state["validation_report"] = val
    summary = _build_state_summary(state)
    assert "Mandate Facts" in summary
    assert "보유 종목 수: 3" in summary
    assert "위험자산 비중: 62.0% (mandate cap 70%)" in summary
    assert "최대 단일 비중: A069500 = 50.0%" in summary
    assert "의무사항 검증: 통과" in summary


def test_audit_flags_fabricated_number():
    inputs = "위험자산 비중: 62.0%, VIX 25.0, regime recession"
    doc = "포트폴리오 위험자산은 62.0%이며 VIX 25.0. 그러나 88.5% 수익을 기대한다."
    flagged = _audit_philosophy_numbers(doc, inputs)
    assert 88.5 in flagged          # fabricated — not in inputs
    assert 62.0 not in flagged      # present in inputs
    assert 25.0 not in flagged      # present in inputs


def test_audit_ignores_years_and_small_ints():
    inputs = "위험자산 62.0%"
    doc = "2026년 6월, 14개 종목 보유, 위험자산 62.0%."
    flagged = _audit_philosophy_numbers(doc, inputs)
    assert flagged == []            # 2026=year, 6/14=small ints, 62.0 in input


def test_audit_flags_bare_integer_percentage():
    # B8 (adversarial-audit fix): a fabricated 2-digit percentage written without
    # a decimal (Korean prose '45%') must still be flagged, not exempted as a
    # 'small int'. Days/months/counts (<=31) and years stay exempt.
    inputs = "위험자산 62.0%, 보유 14개 종목"
    doc = "예상 수익률 45%를 자신합니다. 위험자산 62.0%, 14개 종목."
    flagged = _audit_philosophy_numbers(doc, inputs)
    assert 45 in flagged            # fabricated 2-digit % — now caught
    assert 62.0 not in flagged      # in inputs
    assert 14 not in flagged        # <=31 count, and in inputs


def test_facts_block_excludes_cash_from_single_cap():
    # B8 (adversarial-audit fix): CASH is not an ETF; it must not be the
    # '최대 단일 비중' nor counted as a holding (mirrors concentration_check).
    wv = MagicMock()
    wv.method = MagicMock(value="aum_weighted")
    wv.weights = {"A069500": 0.18, "CASH": 0.30}
    wv.rationale = "r"
    summary = _build_state_summary({"weight_vector": wv})
    facts = summary.split("Stage 1")[0]
    assert "최대 단일 비중: A069500 = 18.0%" in facts
    assert "보유 종목 수: 1" in facts
    assert "CASH" not in facts


def test_facts_block_cluster_dual_mode():
    wv = MagicMock()
    wv.method = MagicMock(value="x")
    wv.weights = {"A": 0.4, "B": 0.3, "C": 0.3}
    wv.rationale = "r"
    # list-of-dict clusters
    s1 = _build_state_summary({"weight_vector": wv, "correlation_clusters": [{"members": ["A", "B"]}]})
    assert "최대 상관클러스터 비중 합: 70.0%" in s1
    # object-with-.members clusters (pydantic Cluster shape)
    c = MagicMock()
    c.members = ["A", "C"]
    s2 = _build_state_summary({"weight_vector": wv, "correlation_clusters": [c]})
    assert "최대 상관클러스터 비중 합: 70.0%" in s2


# ---- PHIL-4: philosophy deterministic facts (prior + correlation) ----


def test_philosophy_facts_prior_appears_when_quadrant_known():
    # quadrant from step_a attribution → prior(baseline) facts surface in the summary.
    state = dict(_make_state())
    state["allocation_attribution"] = {"step_a": {"quadrant": "recession_inflation"}}
    summary = _build_state_summary(state)
    assert "PHIL-4" in summary
    assert "Prior(baseline) recession_inflation" in summary
    assert "a5_gold_infl" in summary   # recession_inflation 최상위(0.17)


def test_philosophy_facts_quadrant_from_macro_report_fallback():
    from unittest.mock import MagicMock as MM
    state = dict(_make_state())
    mr = MM()
    mr.regime = MM()
    mr.regime.quadrant = "growth_inflation"
    state["macro_report"] = mr
    summary = _build_state_summary(state)
    assert "Prior(baseline) growth_inflation" in summary


def test_philosophy_facts_correlation_graceful_without_sigma():
    # No Σ available → prior fact only, correlation skipped, no crash.
    state = dict(_make_state())
    state["allocation_attribution"] = {"step_a": {"quadrant": "growth_disinflation"}}
    summary = _build_state_summary(state)
    assert "Prior(baseline) growth_disinflation" in summary
    assert "최고 상관쌍" not in summary   # gracefully skipped without Σ


def test_philosophy_facts_correlation_appears_with_sigma():
    import pandas as pd
    keys = ["b1_kr_equity", "b3_global_tech", "a1_cash"]
    cov = pd.DataFrame(
        [[0.04, 0.018, 0.001], [0.018, 0.05, 0.0005], [0.001, 0.0005, 0.0001]],
        index=keys, columns=keys,
    )
    bt = MagicMock()
    bt.weights = {"b1_kr_equity": 0.2, "b3_global_tech": 0.18, "a1_cash": 0.1}
    state = dict(_make_state())
    state["allocation_attribution"] = {"step_a": {"quadrant": "growth_inflation"}}
    state["bl_cov"] = cov
    state["bucket_target"] = bt
    summary = _build_state_summary(state)
    assert "최고 상관쌍" in summary
    assert "b1_kr_equity" in summary and "b3_global_tech" in summary


def test_philosophy_facts_absent_quadrant_graceful():
    # No quadrant anywhere → facts block is '(미산출)', no crash.
    summary = _build_state_summary(_make_state())
    assert "PHIL-4" in summary
    assert "(미산출)" in summary


def test_generate_philosophy_warns_on_fabricated_number(caplog):
    import logging
    deep_llm = MagicMock()
    # LLM fabricates 137.7% — not present anywhere in the inputs.
    deep_llm.invoke.return_value.content = (
        "전략 보고서. 위험자산 비중은 적정합니다. " + "상세 분석 " * 800
        + " 우리는 137.7% 초과수익을 확신합니다."
    )
    with caplog.at_level(logging.WARNING):
        generate_philosophy(_make_state(), deep_llm)
    assert any("not found in inputs" in r.message for r in caplog.records)
