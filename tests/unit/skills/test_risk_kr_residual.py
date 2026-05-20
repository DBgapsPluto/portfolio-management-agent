"""KR residual signals tests — D3 cycle-decontamination."""
import pytest

from tradingagents.skills.risk.kr_residual_signals import compute_kr_residual_signals


def test_zero_residual_when_kr_corp_matches_global_baseline():
    """KR corp spread = α + β × HY → residual ≈ 0."""
    # _ALPHA=50, _BETA=0.50
    hy = 400
    kr_corp = 50 + 0.5 * hy  # 250
    r = compute_kr_residual_signals(
        kr_corp_spread_bps=kr_corp, hy_oas_bps=hy,
        kr_margin_change_20d_pct=0.0,
        kr_tier_relative_pct=0.0,
    )
    assert r.kr_corp_spread_residual_bps == pytest.approx(0.0, abs=1e-6)
    assert r.kr_stress_score == pytest.approx(0.0, abs=0.01)
    assert r.kr_boom_score == pytest.approx(0.0, abs=0.01)


def test_global_widening_does_not_widen_kr_residual():
    """글로벌 HY 확대만으로는 KR residual stress가 잡히지 않아야 함 (cycle 빼고 남는 KR-only)."""
    # HY는 normal 400, kr_corp도 그에 맞게 250. residual 0.
    r_normal = compute_kr_residual_signals(
        kr_corp_spread_bps=250, hy_oas_bps=400,
        kr_margin_change_20d_pct=0.0, kr_tier_relative_pct=0.0,
    )

    # 글로벌 cycle 악화 — HY 600, kr_corp 350 (= 50 + 0.5×600). 둘 다 비례 widening.
    # KR-specific stress는 없으므로 residual 여전히 ~0이어야.
    r_widen = compute_kr_residual_signals(
        kr_corp_spread_bps=350, hy_oas_bps=600,
        kr_margin_change_20d_pct=0.0, kr_tier_relative_pct=0.0,
    )
    assert r_widen.kr_corp_spread_residual_bps == pytest.approx(0.0, abs=1e-6)
    assert r_widen.kr_stress_score == pytest.approx(r_normal.kr_stress_score, abs=1e-6)


def test_kr_specific_stress_widens_residual_when_global_calm():
    """글로벌은 calm인데 KR corp만 widening → kr_stress_score 양수."""
    # HY 350 (calm), kr_corp 350 → expected = 50+175 = 225. residual = +125.
    r = compute_kr_residual_signals(
        kr_corp_spread_bps=350, hy_oas_bps=350,
        kr_margin_change_20d_pct=-15.0,  # 신용잔고 deleveraging
        kr_tier_relative_pct=-3.0,
        foreign_flow_z=-1.5,  # 외국인 매도
    )
    assert r.kr_corp_spread_residual_bps > 100
    assert r.kr_stress_score > 1.5  # 합성 신호 명확


def test_kr_boom_score_when_kr_credit_tight_and_inflows():
    """KR 신용 tight + 외국인 매수 + KOSDAQ 강세 → kr_boom_score 양수."""
    # HY 400, kr_corp 200 → expected = 250. residual = -50 (KR 양호).
    r = compute_kr_residual_signals(
        kr_corp_spread_bps=200, hy_oas_bps=400,
        kr_margin_change_20d_pct=5.0,
        kr_tier_relative_pct=+8.0,  # KOSDAQ outperform
        foreign_flow_z=+2.0,
    )
    assert r.kr_corp_spread_residual_bps < -30
    assert r.kr_boom_score > 1.0


def test_prompt_block_contains_residual_and_score_labels():
    r = compute_kr_residual_signals(
        kr_corp_spread_bps=300, hy_oas_bps=400,
        kr_margin_change_20d_pct=0.0, kr_tier_relative_pct=0.0,
    )
    block = r.to_prompt_block()
    assert "KR corp spread residual" in block
    assert "KR stress score" in block
    assert "KR boom score" in block
    assert "global HY-OAS 설명분 제거 후" in block
