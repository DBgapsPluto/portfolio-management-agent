"""Historical quarter → (cycle, tail, kr) cell 분류.

D1 cycle: NBER recession × CPI YoY threshold (3%)
D2 tail:  credit_spread conditional surprise (D1-conditioned baseline)
D3 kr:    KOSPI - SPX residual z-score (60d momentum 차이의 1y rolling z)
"""
from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


_CPI_INFLATION_THRESHOLD = 3.0  # YoY %


def _cycle(recession: float, cpi_yoy: float) -> str:
    is_rec = bool(recession >= 0.5)
    is_infl = cpi_yoy >= _CPI_INFLATION_THRESHOLD
    if is_rec and is_infl: return "D"
    if is_rec:             return "C"
    if is_infl:            return "B"
    return "A"


def assign_cycle(macro_q: pd.DataFrame) -> pd.Series:
    return pd.Series(
        [_cycle(r, c) for r, c in zip(macro_q["recession"], macro_q["cpi_yoy"])],
        index=macro_q.index, name="cycle",
    )


def conditional_credit_baseline(
    macro_q: pd.DataFrame, cycle_series: pd.Series,
) -> pd.DataFrame:
    """각 cycle별 credit_spread mean + std → baseline 표.

    Returns DataFrame indexed by cycle ('A','B','C','D'), columns: mean_bps, std_bps.
    """
    df = macro_q.join(cycle_series)
    out = df.groupby("cycle")["credit_spread_bps"].agg(["mean", "std"]).fillna(50.0)
    out.columns = ["mean_bps", "std_bps"]
    return out


def assign_tail(
    macro_q: pd.DataFrame, cycle_series: pd.Series, threshold_z: float = 1.0,
) -> pd.Series:
    """D2: 같은 cycle 안에서 credit_spread surprise z ≥ +1.0 → T."""
    baseline = conditional_credit_baseline(macro_q, cycle_series)
    z = []
    for ts, c in zip(macro_q.index, cycle_series):
        cs = macro_q.loc[ts, "credit_spread_bps"]
        mu = baseline.loc[c, "mean_bps"]
        sigma = max(baseline.loc[c, "std_bps"], 10.0)
        z.append((cs - mu) / sigma)
    z_series = pd.Series(z, index=macro_q.index, name="credit_z")
    return (z_series >= threshold_z).map({True: "T", False: "N"}).rename("tail")


def assign_kr(
    macro_q: pd.DataFrame, window: int = 4, threshold_z: float = 1.0,
) -> pd.Series:
    """D3: KR-SPX residual z. KOSPI return - SPX return의 rolling z-score.

    Simple: KOSPI 분기 return - SPX 분기 return = 'kr_minus_spx'.
    이걸 4-quarter rolling mean / std로 z-score. > +1 → boom, < -1 → stress, 그 외 F.
    KOSPI/SPX 둘 다 있는 시기만 분류. 누락 시 F.
    """
    diff = macro_q["kr_eq_return_q"] - macro_q["gl_eq_return_q"]
    z = (diff - diff.rolling(window, min_periods=2).mean()) / diff.rolling(
        window, min_periods=2,
    ).std().replace(0, 1.0)

    def _cls(v: float) -> str:
        if pd.isna(v):
            return "F"
        if v >= threshold_z:
            return "boom"
        if v <= -threshold_z:
            return "stress"
        return "F"

    return z.map(_cls).rename("kr").fillna("F")


def assign_cells(macro_q: pd.DataFrame) -> pd.DataFrame:
    """Returns macro_q with added cycle/tail/kr/cell columns."""
    cyc = assign_cycle(macro_q)
    tl = assign_tail(macro_q, cyc)
    kr = assign_kr(macro_q)
    out = macro_q.assign(cycle=cyc, tail=tl, kr=kr)
    out["cell"] = out["cycle"] + "_" + out["tail"] + "_" + out["kr"]
    return out


def cell_frequency_table(cells: pd.DataFrame) -> pd.DataFrame:
    """Cell별 sample count + start/end quarter."""
    g = cells.groupby("cell")
    return pd.DataFrame({
        "n": g.size(),
        "first": g.apply(lambda x: x.index.min()),
        "last":  g.apply(lambda x: x.index.max()),
    }).sort_values("n", ascending=False)
