"""F6 모멘텀 패닉 감쇠 — quadrant 전환/패닉 시 이종 버킷 선정을 AUM top-K 로 후퇴.

Daniel-Moskowitz(2016)·Barroso-Santa-Clara(2015): 모멘텀 크래시는 레짐 전환·변동성
패닉 국면에서 집중된다. 선정 자체(모멘텀 랭킹)를 후퇴시켜 크래시 위험을 낮춘다.
"""
import json
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from tradingagents.agents.trader.trader_allocator import create_trader_allocator
from tradingagents.schemas.portfolio import BucketTilt
from tradingagents.schemas.research import ResearchThesis
from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS


def test_panic_thresholds_match_trigger_yaml():
    # daily_triggers는 정규식 파서 — 상수는 YAML 문자열에만 존재(감사 MF-4).
    # 단일 소스 상수 + YAML 패리티 테스트로 드리프트 차단.
    import yaml
    from tradingagents.skills.portfolio.panic_thresholds import VIX_PANIC, VKOSPI_PANIC
    cfg = yaml.safe_load(open("presets/triggers_default.yaml", encoding="utf-8"))
    conds = " ".join(t["condition"] for t in cfg["triggers"])
    assert f"vix > {VIX_PANIC:g}" in conds and f"vkospi > {VKOSPI_PANIC:g}" in conds


# ---------------------------------------------------------------------------
# E2: 감쇠 조건 + AUM-top-K 선정 후퇴
# ---------------------------------------------------------------------------

class _FakeStep:
    """with_structured_output(schema).invoke(prompt) → 미리 정한 객체."""
    def __init__(self, obj):
        self._o = obj
    def with_structured_output(self, schema):
        return self
    def invoke(self, prompt):
        return self._o


def _scratch_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="momentum_damper_test_"))


# b3_global_tech 를 AUM 차등 5종(고유 underlying_index)으로 교체 — 감쇠(damped) 시
# _aum_top_k 가 뽑는 AUM 상위 3종(AUM_TOP3_B3)이 index-dedup 영향 없이 고정된다.
AUM_TOP3_B3 = {"B3_A1", "B3_A2", "B3_A3"}
_B3_AUM = {"B3_A1": 9e11, "B3_A2": 7e11, "B3_A3": 5e11, "B3_M1": 2e11, "B3_M2": 1e11}


def _damper_universe() -> str:
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
    for t, a in _B3_AUM.items():
        etfs.append({
            "ticker": t, "name": t, "aum_krw": a, "underlying_index": f"idx_{t}",
            "bucket": "위험", "category": "c", "gaps_bucket": "b3_global_tech",
            "sub_category": "us_tech_nasdaq",
        })
    p = _scratch_dir() / "u_damper.json"
    p.write_text(json.dumps({"version": "t", "etfs": etfs}, ensure_ascii=False))
    return str(p)


def _mk_state(*, quadrant, prev_attr_quadrant, vkospi, vix, confidence=0.8):
    macro = types.SimpleNamespace(
        regime=types.SimpleNamespace(quadrant=quadrant, confidence=confidence),
        fx=types.SimpleNamespace(regime="neutral"),
        financial_conditions=types.SimpleNamespace(regime="neutral"),
    )
    prev_portfolio = None
    if prev_attr_quadrant is not None:
        prev_portfolio = {"allocation_attribution": {"step_a": {"quadrant": prev_attr_quadrant}}}
    return {
        "research_decision": ResearchThesis(risk_tilt="neutral", thesis_md="t"),
        "universe_path": _damper_universe(),
        "macro_report": macro,
        "macro_summary": "m", "risk_summary": "r",
        "technical_summary": "t", "news_summary": "n",
        "allocation_feedback": [],
        "risk_report": types.SimpleNamespace(
            vkospi=types.SimpleNamespace(current_value=vkospi),
            vix=types.SimpleNamespace(current_value=vix),
        ),
        "previous_portfolio": prev_portfolio,
    }


def _run_allocator(state):
    node = create_trader_allocator(_FakeStep(BucketTilt()))
    return node(state)


def test_damper_on_quadrant_change():
    state = _mk_state(quadrant="recession_disinflation",
                      prev_attr_quadrant="growth_disinflation", vkospi=15.0, vix=12.0)
    out = _run_allocator(state)
    assert out["allocation_attribution"]["step_b"]["momentum_damped"] == "quadrant_transition"
    # 감쇠 시 het 버킷 선정 = _aum_top_k 결과 (모멘텀 상위와 다른 집합)
    assert set(out["candidate_set"].bucket_to_tickers["b3_global_tech"]) == AUM_TOP3_B3


def test_damper_on_panic_vkospi():
    state = _mk_state(quadrant="growth_disinflation",
                      prev_attr_quadrant="growth_disinflation", vkospi=27.0, vix=12.0)
    assert _run_allocator(state)["allocation_attribution"]["step_b"]["momentum_damped"] == "panic"


def test_no_damper_normal_and_no_prev():
    state = _mk_state(quadrant="growth_disinflation",
                      prev_attr_quadrant=None, vkospi=15.0, vix=12.0)
    assert _run_allocator(state)["allocation_attribution"]["step_b"]["momentum_damped"] is None


def _infeasible_universe() -> str:
    """b3 4종이 전부 동일 underlying_index 로 index-dedup 이 1종으로 collapse.

    강한 tilt(+0.15)로 b3 비중을 0.20 초과(need=2)시켜, dedup 된 1종만으로는
    InfeasibleBucket 이 발생하도록 강제한다 — trader_allocator.py 의
    InfeasibleBucket 재-_allocate 폴백 경로(pure AUM re-sort, no dedup)를 태운다.
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
    mono = {"B3_BIG": 6.0e11, "B3_MED": 5.0e11, "B3_SML": 1.0e10, "B3_TINY": 1.0e9}
    for t, a in mono.items():
        etfs.append({
            "ticker": t, "name": t, "aum_krw": a, "underlying_index": "SAME_IDX",
            "bucket": "위험", "category": "c", "gaps_bucket": "b3_global_tech",
            "sub_category": "us_tech_nasdaq",
        })
    p = _scratch_dir() / "u_infeasible.json"
    p.write_text(json.dumps({"version": "t", "etfs": etfs}, ensure_ascii=False))
    return str(p)


def test_damper_survives_infeasible_bucket_fallback():
    # InfeasibleBucket 재-_allocate 경로(trader_allocator.py:565)에서도 모멘텀 가중이
    # 복귀하지 않아야 함 (감사 MF-3). momentum 데이터를 안 주면(-inf 균등) 모멘텀
    # 가중 경로는 weight_proxy=1.0 균등이라 B3_BIG/B3_MED 가 50/50 이 되는데,
    # AUM 가중(정상)이면 실제 AUM 비례(6:5)라 BIG > MED 여야 한다.
    macro = types.SimpleNamespace(
        regime=types.SimpleNamespace(quadrant="growth_disinflation", confidence=0.9),
        fx=types.SimpleNamespace(regime="neutral"),
        financial_conditions=types.SimpleNamespace(regime="neutral"),
    )
    state = {
        "research_decision": ResearchThesis(risk_tilt="neutral", thesis_md="t"),
        "universe_path": _infeasible_universe(),
        "macro_report": macro,
        "macro_summary": "m", "risk_summary": "r",
        "technical_summary": "t", "news_summary": "n",
        "allocation_feedback": [],
        "cached_tilt": BucketTilt(tilts={"b3_global_tech": 0.15}),
        "risk_report": types.SimpleNamespace(
            vkospi=types.SimpleNamespace(current_value=27.0),
            vix=types.SimpleNamespace(current_value=12.0),
        ),
        "previous_portfolio": None,
    }
    out = _run_allocator(state)
    assert out["allocation_attribution"]["step_b"]["momentum_damped"] == "panic"
    wv = out["weight_vector"].weights
    assert "B3_BIG" in wv and "B3_MED" in wv
    assert wv["B3_BIG"] > wv["B3_MED"] + 1e-9
