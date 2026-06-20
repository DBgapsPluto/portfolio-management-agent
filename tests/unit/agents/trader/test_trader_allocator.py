import json
import pytest
from types import SimpleNamespace
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
        "research_decision": ResearchThesis(thesis_md="t"),
        "universe_path": universe_path, "macro_report": macro,
        "macro_summary": "m", "risk_summary": "r",
        "technical_summary": "t", "news_summary": "n",
        "allocation_feedback": [],
    }


def test_step_a_prompt_includes_quadrant_anchor_and_signals():
    q = "growth_disinflation"
    anchor = QUADRANT_BASELINE[q]
    eff = {b: effective_band(anchor[b], *hard_band(q, b, anchor[b]), 0.7) for b in anchor}
    state = {
        "research_decision": ResearchThesis(
            risk_tilt="defensive", thesis_md="강세 논거",
            key_risks=["중국 둔화"]),
        "macro_summary": "MACRO_X", "risk_summary": "r",
        "technical_summary": "t", "news_summary": "n",
        "allocation_feedback": [],
    }
    msgs = _step_a_prompt(state, q, "defensive", "usd_risk_off", "neutral", 0.7, anchor, eff)
    text = msgs[0]["content"] + msgs[1]["content"]
    assert q in text
    assert "usd_risk_off" in text
    assert "defensive" in text
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


def test_fx_modifier_shifts_kr_equity_down(tmp_path):
    import types
    up = _universe_14(tmp_path)

    def run(fx_regime):
        macro = types.SimpleNamespace(
            regime=_FakeRegime("growth_disinflation", 0.5),
            fx=types.SimpleNamespace(regime=fx_regime),
            financial_conditions=types.SimpleNamespace(regime="neutral"),
        )
        st = _state_14(up, macro)
        st["research_decision"] = ResearchThesis(risk_tilt="neutral", thesis_md="t")
        node = create_trader_allocator(_FakeStep(BucketTilt()))
        return node(st)["bucket_target"].weights["b1_kr_equity"]

    assert run("usd_risk_off") < run("neutral")   # usd_risk_off 가 한국주식을 낮춤


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


def test_attribution_records_step_a_decomposition(tmp_path):
    import types
    up = _universe_14(tmp_path)
    step_a = _FakeStep(BucketTilt(
        tilts={"b3_global_tech": 0.04, "b2_dm_core": -0.04},
        rationale="AI 모멘텀 강화로 테크 비중 확대"))
    node = create_trader_allocator(step_a_llm=step_a)
    macro = types.SimpleNamespace(
        regime=_FakeRegime("growth_disinflation", 0.8),
        fx=types.SimpleNamespace(regime="usd_risk_off"),
        financial_conditions=types.SimpleNamespace(regime="neutral"),
    )
    st = _state_14(up, macro)
    st["research_decision"] = ResearchThesis(risk_tilt="neutral", thesis_md="t")
    sa = node(st)["allocation_attribution"]["step_a"]

    # regime/macro 맥락 + LLM 근거 보존
    assert sa["quadrant"] == "growth_disinflation"
    assert sa["risk_tilt"] == "neutral"
    assert sa["fx_regime"] == "usd_risk_off"
    assert sa["credit_regime"] == "neutral"
    assert sa["tilt_rationale"] == "AI 모멘텀 강화로 테크 비중 확대"

    # usd_risk_off 는 b1_kr_equity 를 끌어내림 (scenario_delta < 0)
    assert sa["buckets"]["b1_kr_equity"]["scenario_delta"] < 0
    # LLM 이 요청한 raw tilt 가 기록됨
    assert sa["buckets"]["b3_global_tech"]["tilt_requested"] == 0.04

    # 분해 항등식: baseline + scenario_delta + tilt_applied == final
    for d in sa["buckets"].values():
        assert abs(d["baseline"] + d["scenario_delta"]
                   + d["tilt_applied"] - d["final"]) < 1e-6


def test_node_vol_haircut_reduces_high_vol_bucket(tmp_path):
    """technical_report에 b8 고vol 주입 → b8 비중이 haircut 없을 때보다 감소."""
    up = _universe_14(tmp_path)
    panel = {}
    for k in GAPS_BUCKET_KEYS:
        for i in (1, 2):
            v = 0.45 if k == "b8_cyclical_commodity" else 0.12
            panel[f"T_{k}_{i}"] = SimpleNamespace(realized_vol_60d=v)
    tr = SimpleNamespace(factor_panel=panel)

    base = create_trader_allocator(_FakeStep(BucketTilt()))(_state_14(up))
    st = _state_14(up)
    st["technical_report"] = tr
    hc = create_trader_allocator(_FakeStep(BucketTilt()))(st)

    b8_base = base["bucket_target"].weights.get("b8_cyclical_commodity", 0.0)
    b8_hc = hc["bucket_target"].weights.get("b8_cyclical_commodity", 0.0)
    assert b8_hc < b8_base, f"haircut이 b8을 줄여야 함: base={b8_base}, hc={b8_hc}"


def test_node_vol_haircut_noop_without_technical_report(tmp_path):
    """technical_report 없으면 무변경(회귀 보장)."""
    up = _universe_14(tmp_path)
    out1 = create_trader_allocator(_FakeStep(BucketTilt()))(_state_14(up))
    out2 = create_trader_allocator(_FakeStep(BucketTilt()))(_state_14(up))
    assert out1["bucket_target"].weights == out2["bucket_target"].weights


class _RaisingStep:
    """cached_tilt 있으면 LLM은 호출되면 안 됨 — 호출 시 실패."""
    def with_structured_output(self, schema):
        return self
    def invoke(self, prompt):
        raise AssertionError("cached_tilt 있는데 LLM이 호출됨")


def test_node_uses_cached_tilt_skips_llm(tmp_path):
    up = _universe_14(tmp_path)
    node = create_trader_allocator(_RaisingStep())
    st = _state_14(up)
    st["cached_tilt"] = BucketTilt(tilts={"b3_global_tech": 0.05})
    out = node(st)   # LLM 미호출이라 raise 안 함
    assert out["weight_vector"] is not None
    assert out["allocation_attribution"]["step_a"]["tilt"] == {"b3_global_tech": 0.05}


def test_allocator_reads_fx_and_credit_and_risk_tilt():
    """mr.fx.regime=usd_risk_off → a4 상승, rd.risk_tilt=defensive → 성장 축소."""
    import types
    from tradingagents.schemas.research import ResearchThesis
    from tradingagents.schemas.portfolio import BucketTilt
    mr = types.SimpleNamespace(
        regime=types.SimpleNamespace(quadrant="growth_disinflation", confidence=0.8),
        fx=types.SimpleNamespace(regime="usd_risk_off"),
        financial_conditions=types.SimpleNamespace(regime="neutral"),
    )
    state = {
        "macro_report": mr,
        "research_decision": ResearchThesis(risk_tilt="defensive", thesis_md="t"),
        "universe_path": "data/universe.json",
        "capital_krw": 100_000_000,
        "cached_tilt": BucketTilt(),     # LLM 우회 (tilt=0)
    }
    node = create_trader_allocator(object())
    out = node(state)
    sa = out["allocation_attribution"]["step_a"]
    assert sa["risk_tilt"] == "defensive"
    assert sa["fx_regime"] == "usd_risk_off"
    assert sa["credit_regime"] == "neutral"


def test_node_portfolio_dials_override_haircut(tmp_path):
    up = _universe_14(tmp_path)
    panel = {}
    for k in GAPS_BUCKET_KEYS:
        for i in (1, 2):
            v = 0.45 if k == "b8_cyclical_commodity" else 0.12
            panel[f"T_{k}_{i}"] = SimpleNamespace(realized_vol_60d=v)
    tr = SimpleNamespace(factor_panel=panel)

    def run(floor):
        st = _state_14(up)
        st["technical_report"] = tr
        st["portfolio_dials"] = {"vol_haircut_floor": floor, "vol_haircut_margin": 0.2}
        out = create_trader_allocator(_FakeStep(BucketTilt()))(st)
        return out["bucket_target"].weights.get("b8_cyclical_commodity", 0.0)

    # floor 낮을수록 haircut 더 큼 → b8 더 작아짐
    assert run(0.5) < run(0.9)


def _universe_het_b3(tmp_path):
    """14버킷 + b3_global_tech 를 이종(semiconductor/battery_ev) 종목으로 확장.

    각 버킷 2 ETF (anchor 가 풀 부족으로 cash 쏠리지 않게) — b3 만 4 ETF:
    semiconductor 2 (고AUM·고모멘텀), battery_ev 2 (저AUM·저모멘텀).
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
    # b3 이종 종목: 충분히 큰 AUM (min_etf_aum_krw=10e9 floor 통과)
    etfs += [
        {"ticker": "A_SEMI_1", "name": "반도체1", "aum_krw": 5.0e11,
         "underlying_index": "idx_semi_1", "bucket": "위험", "category": "c",
         "gaps_bucket": "b3_global_tech", "sub_category": "semiconductor"},
        {"ticker": "A_SEMI_2", "name": "반도체2", "aum_krw": 4.0e11,
         "underlying_index": "idx_semi_2", "bucket": "위험", "category": "c",
         "gaps_bucket": "b3_global_tech", "sub_category": "semiconductor"},
        {"ticker": "A_BATT_1", "name": "이차전지1", "aum_krw": 3.0e11,
         "underlying_index": "idx_batt_1", "bucket": "위험", "category": "c",
         "gaps_bucket": "b3_global_tech", "sub_category": "battery_ev"},
        {"ticker": "A_BATT_2", "name": "이차전지2", "aum_krw": 2.0e11,
         "underlying_index": "idx_batt_2", "bucket": "위험", "category": "c",
         "gaps_bucket": "b3_global_tech", "sub_category": "battery_ev"},
    ]
    p = tmp_path / "u_het.json"
    p.write_text(json.dumps({"version": "t", "etfs": etfs}, ensure_ascii=False))
    return str(p)


def _het_factor_panel(up):
    """semiconductor 고모멘텀 / battery_ev 저모멘텀 factor_panel (+ 다른 버킷 저vol)."""
    import math
    panel = {}
    for k in GAPS_BUCKET_KEYS:
        if k == "b3_global_tech":
            continue
        for i in (1, 2):
            panel[f"T_{k}_{i}"] = SimpleNamespace(
                skip1m_mom_3m=0.0, skip1m_mom_6m=0.0, skip1m_mom_12m=0.0,
                realized_vol_60d=0.12, log_aum=math.log(100.0 * i),
            )
    # 반도체: 강한 양 모멘텀 / 이차전지: 강한 음 모멘텀
    panel["A_SEMI_1"] = SimpleNamespace(
        skip1m_mom_3m=0.30, skip1m_mom_6m=0.45, skip1m_mom_12m=0.60,
        realized_vol_60d=0.15, log_aum=math.log(5.0e11))
    panel["A_SEMI_2"] = SimpleNamespace(
        skip1m_mom_3m=0.25, skip1m_mom_6m=0.40, skip1m_mom_12m=0.55,
        realized_vol_60d=0.15, log_aum=math.log(4.0e11))
    panel["A_BATT_1"] = SimpleNamespace(
        skip1m_mom_3m=-0.30, skip1m_mom_6m=-0.40, skip1m_mom_12m=-0.50,
        realized_vol_60d=0.40, log_aum=math.log(3.0e11))
    panel["A_BATT_2"] = SimpleNamespace(
        skip1m_mom_3m=-0.25, skip1m_mom_6m=-0.35, skip1m_mom_12m=-0.45,
        realized_vol_60d=0.40, log_aum=math.log(2.0e11))
    return panel


def test_het_bucket_selects_high_momentum_semi(tmp_path):
    """이종 b3: sub_category_views(semiconductor 선호) + 반도체 고모멘텀 →
    결과 weight_vector 에 반도체 ETF 포함, 이차전지 배제, attribution 에 view 기록.
    correlation cluster(반도체 2종) 합 ≤ 0.35."""
    import types
    up = _universe_het_b3(tmp_path)
    step_a = _FakeStep(BucketTilt(
        tilts={"b3_global_tech": 0.06, "b2_dm_core": -0.06},
        sub_category_views={"b3_global_tech": {"semiconductor": 0.8, "battery_ev": -0.5}},
        rationale="AI 반도체 사이클 강세"))
    macro = types.SimpleNamespace(
        regime=_FakeRegime("growth_disinflation", 0.8),
        fx=types.SimpleNamespace(regime="neutral"),
        financial_conditions=types.SimpleNamespace(regime="neutral"),
    )
    st = _state_14(up, macro)
    st["research_decision"] = ResearchThesis(risk_tilt="neutral", thesis_md="t")
    st["technical_report"] = SimpleNamespace(factor_panel=_het_factor_panel(up))
    # 반도체 2종을 한 상관군집으로 — cluster cap(0.35) 가 강제되는지 확인
    from tradingagents.schemas.technical import Cluster
    st["correlation_clusters"] = [Cluster(
        cluster_id="semi", members=["A_SEMI_1", "A_SEMI_2"],
        avg_internal_correlation=0.9, category_label="반도체")]

    out = create_trader_allocator(step_a_llm=step_a)(st)
    wv = out["weight_vector"]

    # (1) 반도체 선택 (favored + 고모멘텀), 이차전지 배제
    semi_held = [t for t in wv.weights if t.startswith("A_SEMI")]
    assert semi_held, f"반도체 ETF 가 선택돼야 함: {list(wv.weights)}"
    assert not any(t.startswith("A_BATT") for t in wv.weights), \
        f"비선호+저모멘텀 이차전지는 배제돼야 함: {list(wv.weights)}"

    # (2) attribution 에 sub_category_views 기록
    sa = out["allocation_attribution"]["step_a"]
    assert sa.get("sub_category_views", {}).get("b3_global_tech", {}).get("semiconductor") == 0.8

    # (3) 상관군집(반도체) 합 ≤ 0.35
    cluster_sum = sum(wv.weights.get(t, 0.0) for t in ("A_SEMI_1", "A_SEMI_2"))
    assert cluster_sum <= 0.35 + 1e-6, f"cluster sum {cluster_sum} > 0.35"

    # 무결성: 합=1, 단일 cap
    assert sum(wv.weights.values()) == pytest.approx(1.0, abs=1e-3)
    assert all(w <= 0.20 + 1e-6 for w in wv.weights.values())


# ---------------------------------------------------------------------------
# Regression: cluster_repair must run INSIDE the category/risk loop, not once
# after it. The old order (3× category+risk, THEN cluster once, THEN renorm)
# let cluster_repair water-fill freed cluster mass onto a category-capped ETF,
# re-violating that category cap with no later category pass to clean it.
# Proven scenario (reviewer): a feasible sum=1 input yields 해외주식_섹터=0.1083
# (>0.10) under the old order; the interleaved order converges to 0.10.
# ---------------------------------------------------------------------------

def _cap_interaction_scenario():
    """Feasible (sum=1) weights where freed cluster mass lands on a .10 category.

    cluster {CL1,CL2}=0.40 sits in a slack category (국내채권_종합, cap .50) so only
    the 0.35 cluster cap binds; the 해외주식_섹터 pair {SEC1,SEC2}=0.10 is exactly
    at its 0.10 category cap; the remaining 0.50 is slack recipients with ample
    category + single-cap headroom (so the problem is genuinely feasible).
    """
    from tradingagents.schemas.technical import Cluster
    from tradingagents.skills.mandate.concentration_check import CATEGORY_CAPS
    weights = {
        "CL1": 0.20, "CL2": 0.20,                       # 국내채권_종합 (.50 cap) — cluster .40>.35
        "SEC1": 0.05, "SEC2": 0.05,                     # 해외주식_섹터 (.10 cap) — exactly at cap
        "B1": 0.075, "B2": 0.075, "B3": 0.075, "B4": 0.075,  # 해외채권_종합 (.50 cap)
        "C1": 0.10, "C2": 0.10,                         # 국내채권_회사채 (.30 cap)
    }
    cat = {
        "CL1": "국내채권_종합", "CL2": "국내채권_종합",
        "SEC1": "해외주식_섹터", "SEC2": "해외주식_섹터",
        "B1": "해외채권_종합", "B2": "해외채권_종합",
        "B3": "해외채권_종합", "B4": "해외채권_종합",
        "C1": "국내채권_회사채", "C2": "국내채권_회사채",
    }
    clusters = [Cluster(
        cluster_id="cl", members=["CL1", "CL2"],
        avg_internal_correlation=0.9, category_label="dup")]
    return weights, cat, CATEGORY_CAPS, clusters


def _cat_sums(weights, cat):
    sums: dict[str, float] = {}
    for t, w in weights.items():
        c = cat.get(t)
        if c is not None:
            sums[c] = sums.get(c, 0.0) + w
    return sums


def test_old_cluster_after_loop_order_violates_category_cap():
    """Pin the BUG: cluster_repair ONCE after the category/risk loop overflows a
    category cap. This replicates the *broken* ordering to prove it is wrong —
    the production code must NOT use it (see the interleaved helper test below).
    """
    from tradingagents.skills.mandate.category_repair import repair_category_caps
    from tradingagents.skills.mandate.risk_repair import repair_risk_cap
    from tradingagents.skills.mandate.cluster_repair import repair_cluster_cap
    weights, cat, caps, clusters = _cap_interaction_scenario()
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-9)

    def is_risk(_t):
        return False

    # The pre-fix ordering: 3× (category, risk), THEN cluster once, THEN renorm.
    w = dict(weights)
    for _ in range(3):
        w = repair_category_caps(w, cat, caps)
        w = repair_risk_cap(w, is_risk)
    w = repair_cluster_cap(w, clusters, cap=0.35)
    s = sum(w.values())
    w = {t: x / s for t, x in w.items()} if s > 0 else w

    sec = _cat_sums(w, cat)["해외주식_섹터"]
    # BUG manifests: the .10-capped category is pushed strictly over 0.10.
    assert sec > 0.10 + 1e-6, (
        f"expected old order to violate 해외주식_섹터 cap, got {sec}")


def test_repair_all_weights_satisfies_all_caps_on_cluster_interaction():
    """The shipped helper interleaves cluster_repair INSIDE the loop and must
    satisfy ALL caps (category, risk, single, cluster) with sum==1 on the exact
    scenario that breaks the old order. This FAILS on pre-fix code, PASSES now.
    """
    from tradingagents.agents.trader.trader_allocator import _repair_all_weights
    weights, cat, caps, clusters = _cap_interaction_scenario()

    def is_risk(_t):
        return False

    out = _repair_all_weights(dict(weights), cat, caps, is_risk, clusters)

    # sum preserved
    assert sum(out.values()) == pytest.approx(1.0, abs=1e-6)
    # single-ETF cap
    assert all(w <= 0.20 + 1e-6 for w in out.values()), out
    # risk cap (no risk assets here, but assert the path)
    assert sum(w for t, w in out.items() if is_risk(t)) <= 0.70 + 1e-6
    # cluster cap
    cluster_sum = out["CL1"] + out["CL2"]
    assert cluster_sum <= 0.35 + 1e-6, f"cluster {cluster_sum} > 0.35"
    # EVERY category cap holds — the bug's exact failure point.
    sums = _cat_sums(out, cat)
    for c, cap in caps.items():
        assert sums.get(c, 0.0) <= cap + 1e-6, (
            f"category {c} = {sums.get(c, 0.0)} > {cap}")
    # And the specific reviewer assertion: SEC is at 0.10, NOT 0.108.
    assert sums["해외주식_섹터"] == pytest.approx(0.10, abs=1e-6)


def test_node_respects_all_caps_with_correlation_clusters(tmp_path):
    """End-to-end: drive the real node with state['correlation_clusters'] and a
    category-distinct universe; the final weight_vector must satisfy every cap
    family (single, risk, category via real CATEGORY_CAPS + e.category, cluster,
    sum=1). Guards that the helper is wired into the node, not just unit-pure.
    """
    import types
    from tradingagents.schemas.technical import Cluster
    from tradingagents.skills.mandate.concentration_check import (
        CATEGORY_CAPS, RISK_BUCKET_NAMES,
    )
    from tradingagents.skills.portfolio.sub_category import bucket_for_etf

    up = _universe_het_b3(tmp_path)
    step_a = _FakeStep(BucketTilt(
        tilts={"b3_global_tech": 0.06, "b2_dm_core": -0.06},
        sub_category_views={"b3_global_tech": {"semiconductor": 0.8, "battery_ev": -0.5}},
        rationale="반도체 집중 → cluster cap 강제"))
    macro = types.SimpleNamespace(
        regime=_FakeRegime("growth_disinflation", 0.8),
        fx=types.SimpleNamespace(regime="neutral"),
        financial_conditions=types.SimpleNamespace(regime="neutral"),
    )
    st = _state_14(up, macro)
    st["research_decision"] = ResearchThesis(risk_tilt="neutral", thesis_md="t")
    st["technical_report"] = SimpleNamespace(factor_panel=_het_factor_panel(up))
    st["correlation_clusters"] = [Cluster(
        cluster_id="semi", members=["A_SEMI_1", "A_SEMI_2"],
        avg_internal_correlation=0.95, category_label="반도체")]

    out = create_trader_allocator(step_a_llm=step_a)(st)
    wv = out["weight_vector"]
    uni = json.loads(__import__("pathlib").Path(up).read_text())
    cat_of = {e["ticker"]: e.get("category") for e in uni["etfs"]}

    # sum + single cap
    assert sum(wv.weights.values()) == pytest.approx(1.0, abs=1e-3)
    assert all(w <= 0.20 + 1e-6 for w in wv.weights.values())
    # cluster cap
    assert wv.weights.get("A_SEMI_1", 0.0) + wv.weights.get("A_SEMI_2", 0.0) \
        <= 0.35 + 1e-6
    # category caps (real CATEGORY_CAPS + e.category)
    cat_sums: dict[str, float] = {}
    for t, w in wv.weights.items():
        c = cat_of.get(t)
        if c is not None:
            cat_sums[c] = cat_sums.get(c, 0.0) + w
    for c, cap in CATEGORY_CAPS.items():
        assert cat_sums.get(c, 0.0) <= cap + 1e-6, f"category {c} over cap"
    # risk cap (validator's definition)
    from tradingagents.dataflows.universe import Universe
    universe = Universe(**uni)
    bl = {e.ticker: bucket_for_etf(e) for e in universe.etfs}
    risk = sum(w for t, w in wv.weights.items() if bl.get(t) in RISK_BUCKET_NAMES)
    assert risk <= 0.70 + 1e-6, f"risk {risk} > 0.70"
