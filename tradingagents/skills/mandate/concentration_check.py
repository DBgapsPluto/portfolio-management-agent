"""Concentration mandate checks — 단일 ETF cap 20% + 위험자산 cap 70%.

위험자산 정의: 8-bucket schema (Tier 1).
  위험자산 buckets: kr_equity, global_equity, precious_metals, cyclical_commodity_fx.
ETF 분류는 bucket_for_etf()를 사용해 sub_category-aware하게 처리.
"""
from tradingagents.dataflows.universe import Universe
from tradingagents.schemas.mandate import Violation, ValidationReport
from tradingagents.schemas.portfolio import WeightVector
from tradingagents.skills.portfolio.sub_category import bucket_for_etf
from tradingagents.skills.registry import register_skill


# Stage 5 audit (2026-05-26, Task 1): named hard mandate const.
# DB GAPS §2.2 — 대회 룰북. 변경 시 룰북 동기화 필요.
HARD_SINGLE_CAP: float = 0.20      # 단일 ETF cap (대회 §2.2)
HARD_RISK_ASSET_CAP: float = 0.70  # 위험자산 합 cap (대회 §2.2)
FLOAT_TOLERANCE: float = 1e-6      # floating-point comparison tolerance

# 8-bucket 중 "위험자산"으로 간주하는 bucket 집합 (대회 §2.2 70% cap 대상).
RISK_BUCKET_NAMES = frozenset({
    "kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx",
})


@register_skill(name="validate_concentration", category="mandate")
def validate_concentration(weights: WeightVector, universe: Universe) -> ValidationReport:
    """Per DB GAPS §2.2: single ETF ≤ HARD_SINGLE_CAP, risk asset ≤ HARD_RISK_ASSET_CAP."""
    violations = []
    # 8-bucket 분류 (sub_category-aware).
    bucket_lookup = {e.ticker: bucket_for_etf(e) for e in universe.etfs}

    for ticker, w in weights.weights.items():
        if w > HARD_SINGLE_CAP + FLOAT_TOLERANCE:
            violations.append(Violation(
                rule="single_etf_cap",
                description=f"{ticker} weight {w:.4f} > {HARD_SINGLE_CAP}",
                severity="hard",
                suggested_fix=f"Reduce {ticker} to ≤{HARD_SINGLE_CAP}",
            ))

    risk_total = sum(
        w for t, w in weights.weights.items()
        if bucket_lookup.get(t) in RISK_BUCKET_NAMES
    )
    if risk_total > HARD_RISK_ASSET_CAP + FLOAT_TOLERANCE:
        violations.append(Violation(
            rule="risk_asset_cap",
            description=f"Risk weight {risk_total:.4f} > {HARD_RISK_ASSET_CAP}",
            severity="hard",
            suggested_fix=(
                f"Reduce risk exposure by {(risk_total - HARD_RISK_ASSET_CAP):.4f}"
            ),
        ))

    return ValidationReport(passed=not violations, violations=violations)
