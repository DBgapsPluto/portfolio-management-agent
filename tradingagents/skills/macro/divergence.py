from datetime import date

from tradingagents.schemas.macro import DivergenceScore
from tradingagents.skills.registry import register_skill


@register_skill(name="compute_kr_divergence", category="macro")
def compute_kr_divergence(
    us_policy_rate: float, kr_base_rate: float,
    us_cpi_yoy: float, kr_cpi_yoy: float,
    as_of: date,
) -> DivergenceScore:
    rate_gap_bps = (us_policy_rate - kr_base_rate) * 100
    infl_gap = us_cpi_yoy - kr_cpi_yoy
    score = -abs(rate_gap_bps / 100) - abs(infl_gap)  # closer to 0 = aligned
    score = max(-10.0, min(10.0, score))

    return DivergenceScore(
        us_kr_rate_gap_bps=rate_gap_bps,
        us_kr_inflation_gap=infl_gap,
        score=score,
        source_date=as_of,
    )
