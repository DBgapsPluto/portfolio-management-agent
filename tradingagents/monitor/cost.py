"""Trading cost tracker — sums slippage + commission from transactions CSV."""
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass
class CostSummary:
    total_commission: float
    total_slippage: float
    cost_bps_of_capital: float


def compute_cost(transactions_csv: Path, capital_krw: int) -> CostSummary:
    df = pd.read_csv(transactions_csv)
    commission = float(df.get("수수료", pd.Series([0])).sum())
    slippage = float(df.get("슬리피지", pd.Series([0])).sum())
    total = commission + slippage
    bps = (total / capital_krw * 10000) if capital_krw else 0.0
    return CostSummary(
        total_commission=commission,
        total_slippage=slippage,
        cost_bps_of_capital=bps,
    )
