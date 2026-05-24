"""KRW basis 5-bucket quarterly returns (Critical 4).

5 buckets: kr_equity, global_equity, fx_commodity, bond, cash_mmf.

KRW basis translation: USD 자산 의 return = (1 + USD_return)(1 + USDKRW_change) - 1.

Pre-1996 kr_equity = NaN (KOSPI 부재).
Pre-2002 bond = yield-derived TR (duration × yield change + carry).
Pre-1981 USDKRW = NaN (DEXKOUS 1981+).
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


BUCKETS_5: tuple[str, ...] = (
    "kr_equity", "global_equity", "fx_commodity", "bond", "cash_mmf",
)


def _load_yf_close(raw_dir: Path, ticker: str) -> pd.Series:
    fname = ticker.replace("^", "").replace("=", "_") + ".parquet"
    path = raw_dir / "yfinance" / fname
    if not path.exists():
        return pd.Series(dtype=float)
    return pd.read_parquet(path)["close"]


def _load_fred(raw_dir: Path, series_id: str) -> pd.Series:
    path = raw_dir / "fred" / f"{series_id}.parquet"
    if not path.exists():
        return pd.Series(dtype=float)
    return pd.read_parquet(path)["value"]


def _yield_based_bond_quarterly_tr(yields_pct: pd.Series, duration: float = 7.5) -> pd.Series:
    """yield daily → quarterly TR ≈ -duration × Δy + y × dt (annualized carry)."""
    if yields_pct.empty:
        return pd.Series(dtype=float)
    y_dec = yields_pct / 100.0
    monthly_y = y_dec.resample("ME").last()
    delta_y = monthly_y.diff()
    coupon_carry = monthly_y.shift(1) / 12.0
    monthly_tr = -duration * delta_y + coupon_carry
    # Quarterly compound (3-month product)
    quarterly_tr = (1 + monthly_tr).resample("QE").apply(lambda x: x.prod() - 1)
    return quarterly_tr


def compute_bucket_returns_quarterly(
    start: date,
    end: date,
    raw_dir: Path | str,
    basis: Literal["KRW", "USD"] = "KRW",
) -> pd.DataFrame:
    """5-bucket quarterly return matrix, indexed by quarter end.

    KRW basis: USD 자산 의 return × USDKRW change.
    Pre-1996 kr_equity = NaN.
    Pre-2002 bond = yield-derived from DGS10 (duration=7.5).
    """
    raw_dir = Path(raw_dir)

    # Daily Close → quarterly Close → quarterly return
    spx = _load_yf_close(raw_dir, "^GSPC")
    kospi = _load_yf_close(raw_dir, "^KS11")
    ief = _load_yf_close(raw_dir, "IEF")
    djp = _load_yf_close(raw_dir, "DJP")
    gold = _load_yf_close(raw_dir, "GC=F")
    irx = _load_yf_close(raw_dir, "^IRX")  # 3m T-bill yield %

    spx_q = spx.resample("QE").last().pct_change() if not spx.empty else pd.Series(dtype=float)
    kospi_q = kospi.resample("QE").last().pct_change() if not kospi.empty else pd.Series(dtype=float)

    # Bond: IEF ETF (2002+) + yield-derived (pre-2002)
    ief_q = ief.resample("QE").last().pct_change() if not ief.empty else pd.Series(dtype=float)
    dgs10 = _load_fred(raw_dir, "DGS10")
    bond_q_yld = _yield_based_bond_quarterly_tr(dgs10)
    if not ief_q.empty and not bond_q_yld.empty:
        bond_q = ief_q.combine_first(bond_q_yld)
    elif not ief_q.empty:
        bond_q = ief_q
    else:
        bond_q = bond_q_yld

    # fx_commodity: DJP (2006+) ∪ gold
    djp_q = djp.resample("QE").last().pct_change() if not djp.empty else pd.Series(dtype=float)
    gold_q = gold.resample("QE").last().pct_change() if not gold.empty else pd.Series(dtype=float)
    if not djp_q.empty and not gold_q.empty:
        fx_q = djp_q.combine_first(gold_q)
    elif not djp_q.empty:
        fx_q = djp_q
    else:
        fx_q = gold_q

    # cash_mmf: ^IRX daily yield % → quarterly carry approx = mean(yield)/4
    if not irx.empty:
        irx_q_mean = (irx / 100.0).resample("QE").mean()
        cash_q = irx_q_mean / 4.0  # quarterly carry (approximation)
    else:
        # Fallback: TB3MS monthly
        tb3 = _load_fred(raw_dir, "TB3MS")
        if not tb3.empty:
            tb3_q = (tb3 / 100.0).resample("QE").mean()
            cash_q = tb3_q / 4.0
        else:
            cash_q = pd.Series(dtype=float)

    # KRW basis translation: USDKRW change
    if basis == "KRW":
        usdkrw = _load_fred(raw_dir, "DEXKOUS")
        usdkrw_q = usdkrw.resample("QE").last() if not usdkrw.empty else pd.Series(dtype=float)
        usdkrw_chg = usdkrw_q.pct_change()

        def _krw_translate(usd_q: pd.Series) -> pd.Series:
            if usd_q.empty or usdkrw_chg.empty:
                return usd_q
            aligned = pd.concat([usd_q, usdkrw_chg], axis=1, keys=["r", "fx"]).dropna()
            return (1 + aligned["r"]) * (1 + aligned["fx"]) - 1

        spx_q = _krw_translate(spx_q)
        bond_q = _krw_translate(bond_q)
        fx_q = _krw_translate(fx_q)
        cash_q = _krw_translate(cash_q)
        # kr_equity (KOSPI) is already KRW — no translation

    # Construct DataFrame
    df = pd.DataFrame({
        "kr_equity": kospi_q,
        "global_equity": spx_q,
        "fx_commodity": fx_q,
        "bond": bond_q,
        "cash_mmf": cash_q,
    })
    df.index = pd.to_datetime(df.index)
    df = df[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
    df.index.name = "quarter_end"
    logger.info("compute_bucket_returns_quarterly: %s rows", len(df))
    return df
