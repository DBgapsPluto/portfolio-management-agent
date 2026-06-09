from datetime import date

import pandas as pd

from tradingagents.schemas.macro import KRSectorExportSnapshot
from tradingagents.skills.registry import register_skill

_SECTORS = ["semi", "battery", "display", "chem", "steel"]


def _yoy(s: pd.Series | None) -> float:
    if s is None or len(s) < 13:
        return 0.0
    return float(s.iloc[-1] / s.iloc[-13] - 1) * 100


@register_skill(name="compute_kr_sector_export", category="macro")
def compute_kr_sector_export(
    series: dict[str, pd.Series], as_of: date,
) -> KRSectorExportSnapshot:
    """섹터별 수출물량 YoY + leader/laggard. 키: semi/battery/display/chem/steel."""
    if not series or all(s is None or s.empty for s in series.values()):
        return KRSectorExportSnapshot(source_date=as_of, staleness_days=99)
    yoy = {k: _yoy(series.get(k)) for k in _SECTORS}
    leader = max(yoy, key=yoy.get)
    laggard = min(yoy, key=yoy.get)
    return KRSectorExportSnapshot(
        semi_yoy_pct=yoy["semi"], battery_yoy_pct=yoy["battery"],
        display_yoy_pct=yoy["display"], chem_yoy_pct=yoy["chem"],
        steel_yoy_pct=yoy["steel"], leader_sector=leader, laggard_sector=laggard,
    )
