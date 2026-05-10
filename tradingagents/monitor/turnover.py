"""Turnover floor tracking — D11 (floor-only, no cap)."""
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd


@dataclass
class TurnoverStatus:
    initial_pct: float
    monthly_pcts: dict[int, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def compute_turnover(
    transactions_csv: Path,
    capital_krw: int,
    as_of: date,
) -> TurnoverStatus:
    """Compute initial-window + per-month turnover from MTS export.

    Formula (대회 §3): 거래금액 합계 / 평균자산 (capital_krw 근사).
    Initial window = 6/1 - 6/8 (5 business days).
    Per-month = June, July, August.
    """
    df = pd.read_csv(transactions_csv)
    df["거래일자"] = pd.to_datetime(df["거래일자"])

    initial_window = df[
        (df["거래일자"] >= "2026-06-01") & (df["거래일자"] <= "2026-06-08")
    ]
    initial = float(initial_window["거래금액"].sum() / capital_krw) if capital_krw else 0.0

    monthly: dict[int, float] = {}
    for m in [6, 7, 8]:
        m_data = df[df["거래일자"].dt.month == m]
        monthly[m] = float(m_data["거래금액"].sum() / capital_krw) if capital_krw else 0.0

    warnings: list[str] = []
    if initial < 0.80:
        warnings.append(
            f"⚠ Initial turnover {initial:.2%} < 80% floor (CUTOFF RISK)"
        )
    for m, pct in monthly.items():
        if pct < 0.10:
            warnings.append(
                f"⚠ Month {m} turnover {pct:.2%} < 10% floor (CUTOFF RISK)"
            )

    return TurnoverStatus(
        initial_pct=initial, monthly_pcts=monthly, warnings=warnings,
    )
