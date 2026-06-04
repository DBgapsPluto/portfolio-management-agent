from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.reports.philosophy import (
    format_bucket_target_14, format_step_a_decomposition,
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
