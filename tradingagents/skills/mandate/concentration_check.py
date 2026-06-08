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

# 세부자산(category)별 비중 상한 (대회 §2.2). universe.json ETFEntry.category 와 1:1.
# 단일 ETF/위험자산 cap 과 직교하는 제3 제약층. 변경 시 룰북 동기화 필요.
CATEGORY_CAPS: dict[str, float] = {
    "국내주식_지수": 0.30,
    "국내주식_섹터": 0.15,
    "해외주식_지수": 0.30,
    "해외주식_섹터": 0.10,
    "FX 및 원자재": 0.20,
    "국내채권_종합": 0.50,
    "국내채권_회사채": 0.30,
    "해외채권_종합": 0.50,
    "해외채권_회사채": 0.30,
    "금리연계형/초단기채권": 0.50,
}


@register_skill(name="validate_concentration", category="mandate")
def validate_concentration(weights: WeightVector, universe: Universe) -> ValidationReport:
    """Per DB GAPS §2.2: single ETF ≤ HARD_SINGLE_CAP, risk asset ≤ HARD_RISK_ASSET_CAP."""
    violations = []
    # 8-bucket 분류 (sub_category-aware).
    bucket_lookup = {e.ticker: bucket_for_etf(e) for e in universe.etfs}

    for ticker, w in weights.weights.items():
        if ticker == "CASH":   # 현금은 단일 ETF cap 대상 아님 (실제 ETF 아님)
            continue
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

    # 세부자산(category)별 상한 — e.category 로 합산해 CATEGORY_CAPS 와 대조.
    cat_lookup = {e.ticker: e.category for e in universe.etfs}
    cat_totals: dict[str, float] = {}
    for t, w in weights.weights.items():
        if t == "CASH":
            continue
        c = cat_lookup.get(t)
        if c is not None:
            cat_totals[c] = cat_totals.get(c, 0.0) + w
    for c, cap in CATEGORY_CAPS.items():
        tot = cat_totals.get(c, 0.0)
        if tot > cap + FLOAT_TOLERANCE:
            violations.append(Violation(
                rule="category_cap",
                description=f"category {c} weight {tot:.4f} > {cap}",
                severity="hard",
                suggested_fix=f"Reduce {c} exposure to ≤{cap}",
            ))

    return ValidationReport(passed=not violations, violations=violations)
