from datetime import date
from tradingagents.skills.macro.divergence import compute_kr_divergence


def test_divergence_us_higher():
    snap = compute_kr_divergence(
        us_policy_rate=5.5, kr_base_rate=3.5,
        us_cpi_yoy=3.0, kr_cpi_yoy=2.5,
        as_of=date(2026, 5, 10),
    )
    assert snap.us_kr_rate_gap_bps == 200.0
    assert snap.us_kr_inflation_gap == 0.5
