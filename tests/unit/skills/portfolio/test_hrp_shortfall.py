"""R1–R3 HRP shortfall: no risk spill; non-risk absorb; unallocated mass."""
from tradingagents.skills.portfolio.hrp_shortfall import finalize_per_bucket_mass
from tradingagents.skills.research.factor_to_bucket import BUCKETS, RISK_BUCKETS


def _b2t() -> dict[str, list[str]]:
    return {b: [f"T_{b}"] for b in BUCKETS}


def test_risk_bucket_not_scaled_up_when_shortfall():
    """Global shortfall must not inflate risk buckets above target."""
    target = {b: 1.0 / len(BUCKETS) for b in BUCKETS}
    for b in RISK_BUCKETS:
        target[b] = 0.10
    target["cash_mmf"] = 1.0 - sum(target[b] for b in BUCKETS if b != "cash_mmf")

    weights = {}
    for b in BUCKETS:
        t = f"T_{b}"
        weights[t] = target[b] * 0.5  # 50% fill everywhere → total 0.5

    out, audit = finalize_per_bucket_mass(weights, _b2t(), target, label="hrp")
    risk_sum = sum(
        out.get(f"T_{b}", 0) for b in RISK_BUCKETS
    )
    assert risk_sum <= 0.10 * len(RISK_BUCKETS) + 0.02
    assert audit["hrp_unallocated_mass"] >= 0.0


def test_r1_trims_risk_above_target():
    target = {b: 0.0 for b in BUCKETS}
    target["kr_equity"] = 0.15
    target["cash_mmf"] = 0.85
    weights = {"T_kr_equity": 0.25, "T_cash_mmf": 0.75}
    out, _ = finalize_per_bucket_mass(
        weights,
        {"kr_equity": ["T_kr_equity"], "cash_mmf": ["T_cash_mmf"]},
        target,
        label="hrp",
    )
    assert out["T_kr_equity"] <= 0.15 + 1e-6


def test_shortfall_spills_to_non_risk_headroom():
    target = {b: 0.0 for b in BUCKETS}
    target["kr_equity"] = 0.20
    target["kr_bond"] = 0.50
    target["cash_mmf"] = 0.30
    weights = {"T_kr_equity": 0.20, "T_kr_bond": 0.10, "T_cash_mmf": 0.10}
    b2t = {
        "kr_equity": ["T_kr_equity"],
        "kr_bond": ["T_kr_bond"],
        "cash_mmf": ["T_cash_mmf"],
    }
    out, audit = finalize_per_bucket_mass(weights, b2t, target, label="hrp")
    assert out["T_kr_bond"] > 0.10
    assert audit["hrp_shortfall_to_non_risk_pp"] > 0
