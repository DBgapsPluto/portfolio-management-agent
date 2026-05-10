"""Asset-class exposure breakdown."""
from dataclasses import dataclass


@dataclass
class ExposureBreakdown:
    by_category: dict[str, float]
    risk_asset_pct: float
    safe_asset_pct: float


SAFE_BUCKETS = {"안전", "원자재"}  # 안전자산 + 원자재(금)


def compute_exposure(
    weights: dict[str, float], universe_lookup: dict
) -> ExposureBreakdown:
    by_category: dict[str, float] = {}
    risk_asset_pct = 0.0
    safe_asset_pct = 0.0
    for ticker, w in weights.items():
        meta = universe_lookup.get(ticker, {})
        cat = meta.get("category", "unknown")
        bucket = meta.get("bucket", "위험")
        by_category[cat] = by_category.get(cat, 0.0) + w
        if bucket in SAFE_BUCKETS or bucket == "안전":
            safe_asset_pct += w
        else:
            risk_asset_pct += w
    return ExposureBreakdown(
        by_category=by_category,
        risk_asset_pct=risk_asset_pct,
        safe_asset_pct=safe_asset_pct,
    )
