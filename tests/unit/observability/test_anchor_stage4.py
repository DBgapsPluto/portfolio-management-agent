"""evaluate_anchor(--with_stage4=True) 채점."""
from pathlib import Path

import pytest

from tradingagents.observability.anchor_evaluator import evaluate_anchor


_REPO = Path(__file__).resolve().parents[3]


def test_with_stage4_false_returns_only_stage3_checks():
    """default (with_stage4=False) → 기존 동작 그대로."""
    anchor = _REPO / "data" / "historical_anchors" / "2024-08_yen_carry.json"
    universe = _REPO / "data" / "universe.json"
    if not anchor.exists() or not universe.exists():
        pytest.skip("anchor/universe fixture missing")
    cache = Path.home() / ".tradingagents" / "cache" / "etf_prices.parquet"

    result = evaluate_anchor(anchor, universe_path=str(universe), cache_path=str(cache))
    # 기존 시그니처: checks 1 set
    assert isinstance(result.checks, list)
    assert len(result.checks) == 8
    # stage4 결과 없음
    assert getattr(result, "stage4_checks", None) is None


def test_with_stage4_true_returns_both_sets():
    """with_stage4=True → checks (stage3) + stage4_checks (stage3+4) 둘 다."""
    anchor = _REPO / "data" / "historical_anchors" / "2024-08_yen_carry.json"
    universe = _REPO / "data" / "universe.json"
    if not anchor.exists() or not universe.exists():
        pytest.skip("anchor/universe fixture missing")
    cache = Path.home() / ".tradingagents" / "cache" / "etf_prices.parquet"

    result = evaluate_anchor(
        anchor, universe_path=str(universe), cache_path=str(cache),
        with_stage4=True,
    )
    assert len(result.checks) == 8
    assert result.stage4_checks is not None
    assert len(result.stage4_checks) == 8
    assert result.stage4_outcome in {
        "primary_success", "relax_cluster", "relax_ceiling",
        "relax_band", "fallback_to_1st",
    }
    # Stage 3 + 4 weights 도 보존
    assert result.stage4_weights is not None


def test_stage4_weights_differ_only_when_overlay_active():
    """overlay 가 empty 면 stage4_weights == weights."""
    anchor = _REPO / "data" / "historical_anchors" / "2024-08_yen_carry.json"
    universe = _REPO / "data" / "universe.json"
    if not anchor.exists() or not universe.exists():
        pytest.skip("anchor/universe fixture missing")
    cache = Path.home() / ".tradingagents" / "cache" / "etf_prices.parquet"

    result = evaluate_anchor(
        anchor, universe_path=str(universe), cache_path=str(cache),
        with_stage4=True,
    )
    if result.stage4_outcome == "primary_success" and \
       not result.stage4_overlay_was_active:
        assert result.stage4_weights == result.weights


def test_weight_diff_summary_present_when_active():
    """overlay active 시 stage4_weight_diff 가 bucket-단위 변화 dict 반환."""
    # 이 테스트는 실측 케이스에서 검증. yen_carry 가 multiplier=0.80 → bucket 변화.
    anchor = _REPO / "data" / "historical_anchors" / "2024-08_yen_carry.json"
    universe = _REPO / "data" / "universe.json"
    if not anchor.exists() or not universe.exists():
        pytest.skip("anchor/universe fixture missing")
    cache = Path.home() / ".tradingagents" / "cache" / "etf_prices.parquet"

    result = evaluate_anchor(
        anchor, universe_path=str(universe), cache_path=str(cache),
        with_stage4=True,
    )
    if result.stage4_overlay_was_active:
        assert isinstance(result.stage4_bucket_diff, dict)
        # 변화량 합 ≈ 0 (재정규화) — 0.01 이내 tolerance
        assert abs(sum(result.stage4_bucket_diff.values())) < 0.01


def test_live_evaluate_with_stage4_optional_kwarg_exists():
    """signature 확인 — LIVE 실제 호출은 LLM 비용으로 skip."""
    import inspect
    from tradingagents.observability.anchor_live import evaluate_anchor_live
    sig = inspect.signature(evaluate_anchor_live)
    assert "with_stage4" in sig.parameters
    assert sig.parameters["with_stage4"].default is False
