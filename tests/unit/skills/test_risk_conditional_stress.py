"""Conditional stress surprise tests — D2 cycle-decontamination."""
import pytest

from tradingagents.skills.risk.conditional_stress import (
    compute_conditional_stress, _BASELINE,
)


def _baseline_inputs(quadrant):
    """Return inputs that match the baseline exactly (surprise should be ~0)."""
    b = _BASELINE[quadrant]
    return dict(
        hy_oas_bps=b["hy_oas_bps"][0],
        vix=b["vix"][0],
        funding_spread_bps=b["funding_spread_bps"][0],
        credit_quality_bps=b["credit_quality_bps"][0],
        equity_bond_corr=b["equity_bond_corr"][0],
    )


def test_baseline_inputs_yield_zero_surprise():
    """각 regime의 baseline 값을 입력하면 surprise z ≈ 0, tail_trigger=False."""
    for q in _BASELINE:
        result = compute_conditional_stress(q, **_baseline_inputs(q))
        assert abs(result.aggregate_z) < 1e-6
        assert not result.tail_trigger


def test_recession_baseline_hy_does_not_trigger_tail():
    """recession_disinflation에서 HY OAS = 600bps (baseline)이면 D2 trigger 아님.

    이게 사용자의 (a) 지적 핵심: 'HY OAS > 600bps = tail'은 D1과 mechanical.
    conditional surprise로 정의하면 같은 600bps도 recession_disinflation에서는
    baseline = 0σ = 평소 수준이고, growth_disinflation에서는 +2σ가 됨.
    """
    # 600bps HY OAS = recession_disinflation의 baseline 그대로
    r_rec = compute_conditional_stress(
        "recession_disinflation",
        hy_oas_bps=600, vix=26, funding_spread_bps=20,
        credit_quality_bps=130, equity_bond_corr=-0.10,
    )
    assert not r_rec.tail_trigger
    assert r_rec.hy_oas_z == pytest.approx(0.0, abs=1e-6)

    # 같은 600bps이지만 growth_disinflation에서는 +2σ surprise (350+200×1.25=600)
    r_grw = compute_conditional_stress(
        "growth_disinflation",
        hy_oas_bps=600, vix=15, funding_spread_bps=5,
        credit_quality_bps=75, equity_bond_corr=-0.30,
    )
    assert r_grw.hy_oas_z > 2.0  # (600-350)/120 ≈ 2.08
    # vix/funding 등 다른 신호는 baseline이지만 hy alone으로 aggregate가 충분히 큰가는
    # 평균이므로 ~0.4. tail trigger 안 됨. 이게 의도된 동작 — 한 신호만으로는 tail X.
    assert not r_grw.tail_trigger


def test_compound_surprise_triggers_tail():
    """여러 D2 신호가 동시에 baseline 초과 → tail_trigger."""
    # growth_disinflation에서 모든 stress 신호가 1.5σ씩 surprise
    b = _BASELINE["growth_disinflation"]
    inputs = dict(
        hy_oas_bps=b["hy_oas_bps"][0] + 1.5 * b["hy_oas_bps"][1],
        vix=b["vix"][0] + 1.5 * b["vix"][1],
        funding_spread_bps=b["funding_spread_bps"][0] + 1.5 * b["funding_spread_bps"][1],
        credit_quality_bps=b["credit_quality_bps"][0] + 1.5 * b["credit_quality_bps"][1],
        equity_bond_corr=b["equity_bond_corr"][0] + 1.5 * b["equity_bond_corr"][1],
    )
    result = compute_conditional_stress("growth_disinflation", **inputs)
    assert result.aggregate_z == pytest.approx(1.5, abs=1e-6)
    assert result.tail_trigger


def test_prompt_block_includes_z_and_trigger_flag():
    r = compute_conditional_stress(
        "recession_disinflation",
        hy_oas_bps=1200, vix=40, funding_spread_bps=80,
        credit_quality_bps=250, equity_bond_corr=0.50,
    )
    block = r.to_prompt_block()
    assert "Conditional Stress Surprise" in block
    assert "z = +" in block  # 양수 surprise
    assert "tail trigger" in block  # aggregate ≥ +1
