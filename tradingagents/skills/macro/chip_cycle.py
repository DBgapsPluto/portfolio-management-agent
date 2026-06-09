from datetime import date

import pandas as pd

from tradingagents.schemas.macro import ChipCycleSnapshot
from tradingagents.skills.registry import register_skill


@register_skill(name="compute_chip_cycle", category="macro")
def compute_chip_cycle(chip_ppi: pd.Series, as_of: date) -> ChipCycleSnapshot:
    """칩 PPI YoY + 3개월 모멘텀."""
    if chip_ppi is None or chip_ppi.empty:
        return ChipCycleSnapshot(
            chip_ppi=0.0, chip_ppi_yoy_pct=0.0,
            source_date=as_of, staleness_days=99,
        )
    level = float(chip_ppi.iloc[-1])
    yoy = float(chip_ppi.iloc[-1] / chip_ppi.iloc[-13] - 1) * 100 if len(chip_ppi) >= 13 else 0.0
    mom_3 = float(chip_ppi.iloc[-1] / chip_ppi.iloc[-4] - 1) * 100 if len(chip_ppi) >= 4 else 0.0
    return ChipCycleSnapshot(
        chip_ppi=level, chip_ppi_yoy_pct=yoy, momentum_3mo_pct=mom_3,
        accelerating=(mom_3 > 0 and yoy > 0),
    )
