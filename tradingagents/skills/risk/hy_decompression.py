from datetime import date

from tradingagents.schemas.risk import HYDecompressionSnapshot
from tradingagents.skills.registry import register_skill


def _classify(diff_bps: float) -> str:
    if diff_bps > 500:
        return "stress"
    if diff_bps >= 300:   # 300 포함 (schema: "300~500 widening")
        return "widening"
    return "calm"


@register_skill(name="compute_hy_decompression", category="risk")
def compute_hy_decompression(
    hy_oas_bps: float, ig_oas_bps: float, as_of: date,
) -> HYDecompressionSnapshot:
    """HY − IG OAS 디컴프레션. HY==IG면 backtest fallback 붕괴로 표시."""
    diff = hy_oas_bps - ig_oas_bps
    collapsed = abs(diff) < 1e-9
    return HYDecompressionSnapshot(
        hy_oas_bps=hy_oas_bps, ig_oas_bps=ig_oas_bps,
        hy_minus_ig_bps=diff, collapsed=collapsed,
        regime=_classify(diff), source_date=as_of,
    )
