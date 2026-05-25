"""Concentration mandate checks — 단일 ETF cap 20% + 위험자산 cap 70%.

위험자산 정의: candidate_selector의 BUCKET_TO_CATEGORIES을 single truth
source로 사용 (kr_equity + global_equity + fx_commodity). universe.json의
`bucket` 필드와 정합성은 보장돼 있지만 (현재 138 "위험" = kr/gl/fx 합치),
silent drift를 막기 위해 5-bucket 매핑을 명시.
"""
from tradingagents.dataflows.universe import Universe
from tradingagents.schemas.mandate import Violation, ValidationReport
from tradingagents.schemas.portfolio import WeightVector
from tradingagents.skills.portfolio.candidate_selector import (
    BUCKET_TO_CATEGORIES,
)
from tradingagents.skills.registry import register_skill


# Stage 5 audit (2026-05-26, Task 1): named hard mandate const.
# DB GAPS §2.2 — 대회 룰북. 변경 시 룰북 동기화 필요.
HARD_SINGLE_CAP: float = 0.20      # 단일 ETF cap (대회 §2.2)
HARD_RISK_ASSET_CAP: float = 0.70  # 위험자산 합 cap (대회 §2.2)
FLOAT_TOLERANCE: float = 1e-6      # floating-point comparison tolerance

# 5-bucket 중 "위험자산"으로 간주하는 bucket 집합 (대회 §2.2 70% cap 대상).
RISK_BUCKET_NAMES = {"kr_equity", "global_equity", "fx_commodity"}

# RISK_BUCKET_NAMES → 해당 universe categories. (silent miss 방지용 명시 매핑)
RISK_CATEGORIES = frozenset(
    cat
    for bucket in RISK_BUCKET_NAMES
    for cat in BUCKET_TO_CATEGORIES[bucket]
)


@register_skill(name="validate_concentration", category="mandate")
def validate_concentration(weights: WeightVector, universe: Universe) -> ValidationReport:
    """Per DB GAPS §2.2: single ETF ≤ HARD_SINGLE_CAP, risk asset ≤ HARD_RISK_ASSET_CAP."""
    violations = []
    # 5-bucket 매핑 기준 truth source — universe.bucket 필드와는 독립.
    category_lookup = {e.ticker: e.category for e in universe.etfs}

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
        if category_lookup.get(t) in RISK_CATEGORIES
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
