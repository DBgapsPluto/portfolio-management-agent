from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.reports.philosophy import (
    format_bucket_target_14, format_step_a_decomposition,
    format_heterogeneous_selection,
)


def test_format_lists_nonzero_14_buckets_with_kr_names():
    bt = BucketTarget(weights={"a1_cash": 0.3, "b1_kr_equity": 0.5,
                               "b3_global_tech": 0.2}, rationale="t")
    out = format_bucket_target_14(bt)
    assert "현금성" in out
    assert "한국주식" in out
    assert "30.0%" in out or "30%" in out
    # 0 비중 버킷은 생략
    assert "중국주식" not in out


def _attr_with_step_a():
    return {
        "step_a": {
            "quadrant": "growth_disinflation",
            "scenario": "kr_boom",
            "confidence": 0.7,
            "conviction": "high",
            "tilt_rationale": "AI 모멘텀 강화로 테크 비중 확대",
            "buckets": {
                "b1_kr_equity": {"baseline": 0.11, "scenario_delta": 0.05,
                                 "tilt_requested": 0.0, "tilt_applied": 0.01,
                                 "final": 0.17},
                "b3_global_tech": {"baseline": 0.14, "scenario_delta": -0.005,
                                   "tilt_requested": 0.04, "tilt_applied": 0.035,
                                   "final": 0.17},
            },
        }
    }


def test_format_step_a_decomposition_renders_buckets_and_rationale():
    out = format_step_a_decomposition(_attr_with_step_a())
    # 버킷 한글명 + 분해 단계
    assert "한국주식" in out
    assert "글로벌 테크" in out
    # 앵커/시나리오/최종이 % 로, scenario_delta 는 부호와 함께
    assert "11.0%" in out
    assert "+5.0%" in out
    assert "17.0%" in out
    # LLM 판단 근거 노출
    assert "AI 모멘텀 강화로 테크 비중 확대" in out


def test_format_step_a_decomposition_handles_missing():
    assert format_step_a_decomposition(None) == "(미산출)"
    assert format_step_a_decomposition({}) == "(미산출)"


def test_philosophy_renders_bl_native_step_a_without_crash():
    # a BL-native step_a (method='bl', view_shift/realized keys, NO scenario_delta)
    # must render, not KeyError (C3 review: renderer hard-coded old anchor schema).
    attr = {
        "step_a": {
            "method": "bl",
            "buckets": {
                "b3_global_tech": {"baseline": 0.14, "view_shift": 0.06, "final": 0.20,
                                   "realized": 0.18, "intent_vs_realized": -0.02,
                                   "status": "bl"},
                "a3_us_rates": {"baseline": 0.12, "view_shift": -0.02, "final": 0.10,
                                "realized": 0.10, "intent_vs_realized": 0.0,
                                "status": "baseline_pinned"},
            },
            "global": {"status": "bl", "n_pinned": 1},
        }
    }
    out = format_step_a_decomposition(attr)
    assert "글로벌 테크" in out          # bucket KR name rendered
    assert "0.20" in out or "20.0" in out  # final/intent rendered
    assert "baseline_pinned" in out       # per-bucket status surfaced


def test_philosophy_old_anchor_step_a_still_renders():
    attr = {"step_a": {"buckets": {
        "b1_kr_equity": {"baseline": 0.11, "scenario_delta": 0.0,
                         "tilt_requested": 0.02, "tilt_applied": 0.02, "final": 0.13},
    }}}
    out = format_step_a_decomposition(attr)
    assert "한국주식" in out
    assert "11.0%" in out
    assert "13.0%" in out


# ---- heterogeneous theme view + ETF selection traceability ----


def test_format_heterogeneous_selection_renders_view_and_picks():
    attr = {
        "step_a": {
            "sub_category_views": {
                "b3_global_tech": {"semiconductor": 0.8, "battery_ev": -0.5},
            },
            "heterogeneous_selection": {
                "b3_global_tech": {
                    "bucket": "b3_global_tech",
                    "selected": ["TIGER반도체", "KODEX반도체"],
                    "revert": None,
                    "n_floor": 1,
                },
            },
        }
    }
    out = format_heterogeneous_selection(attr)
    # 버킷 + 테마뷰 sub_category 라벨/부호 + 선정 티커가 모두 노출
    assert "b3_global_tech" in out
    assert "semiconductor" in out
    assert "battery_ev" in out
    assert "TIGER반도체" in out
    assert "KODEX반도체" in out


def test_format_heterogeneous_selection_empty_is_graceful():
    # het view/selection 이 없을 때 크래시 없이 '해당 없음'
    assert format_heterogeneous_selection(None) == "해당 없음"
    assert format_heterogeneous_selection({}) == "해당 없음"
    assert format_heterogeneous_selection(
        {"step_a": {"sub_category_views": {}, "heterogeneous_selection": {}}}
    ) == "해당 없음"


def test_format_heterogeneous_selection_reports_core_aum_revert():
    # 테마 풀이 비어 core-AUM 으로 폴백한 경우 정직하게 명시 (selected 없음).
    attr = {
        "step_a": {
            "sub_category_views": {"b3_global_tech": {"semiconductor": 0.8}},
            "heterogeneous_selection": {
                "b3_global_tech": {"bucket": "b3_global_tech", "revert": "core_aum"},
            },
        }
    }
    out = format_heterogeneous_selection(attr)
    assert "b3_global_tech" in out
    assert "core" in out.lower() or "코어" in out or "AUM" in out


def test_heterogeneous_selection_in_state_summary():
    from tradingagents.reports.philosophy import _build_state_summary
    from unittest.mock import MagicMock
    wv = MagicMock()
    wv.method = MagicMock(value="aum_weighted")
    wv.weights = {"TIGER반도체": 0.5, "KODEX반도체": 0.5}
    wv.rationale = "r"
    state = {
        "weight_vector": wv,
        "allocation_attribution": {
            "step_a": {
                "sub_category_views": {
                    "b3_global_tech": {"semiconductor": 0.8, "battery_ev": -0.5},
                },
                "heterogeneous_selection": {
                    "b3_global_tech": {
                        "bucket": "b3_global_tech",
                        "selected": ["TIGER반도체", "KODEX반도체"],
                        "revert": None,
                    },
                },
            }
        },
    }
    summary = _build_state_summary(state)
    assert "semiconductor" in summary
    assert "TIGER반도체" in summary
