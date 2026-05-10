from datetime import date

import pandas as pd

from tradingagents.schemas.macro import EmploymentSnapshot
from tradingagents.skills.registry import register_skill


@register_skill(name="compute_unemployment_trend", category="macro")
def compute_unemployment_trend(
    unemployment_rate: pd.Series,
    non_farm_payrolls: pd.Series,
    as_of: date,
) -> EmploymentSnapshot:
    """Sahm rule: 3-month avg UR rises 0.5pp+ above the 12-month min."""
    if len(unemployment_rate) < 12:
        sahm = False
    else:
        recent_3mo_avg = float(unemployment_rate.tail(3).mean())
        prior_12mo_min = float(unemployment_rate.tail(15).head(12).min())
        sahm = (recent_3mo_avg - prior_12mo_min) >= 0.5

    rate_change_3mo = float(unemployment_rate.iloc[-1] - unemployment_rate.iloc[-4]) if len(unemployment_rate) > 3 else 0.0
    payrolls_3mo_avg = float(non_farm_payrolls.tail(3).mean()) if len(non_farm_payrolls) >= 3 else 0.0

    return EmploymentSnapshot(
        unemployment_rate=float(unemployment_rate.iloc[-1]),
        rate_change_3mo=rate_change_3mo,
        sahm_rule_triggered=sahm,
        non_farm_payrolls_3mo_avg=payrolls_3mo_avg,
        source_date=as_of,
    )
