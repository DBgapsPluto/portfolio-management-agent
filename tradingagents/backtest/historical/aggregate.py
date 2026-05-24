"""Quarterly aggregation + derived computations.

Input: raw daily/monthly fetched series from fetcher_{fred,yfinance,pykrx,alfred}.
Output: quarterly indicator panel (135 rows × ~40 columns) indexed by quarter end.

Derived computations:
- YoY % (12-month difference / 12-month prior, × 100)
- 3-mo annualized % ((Pt/Pt-3)^4 - 1) × 100
- 60d realized vol % (annualized std × √252 × 100)
- Yield spread bps ((s_long - s_short) × 100, NaN if either NaN)
- 3-mo MA
- Sector dispersion (std of 60d returns across N sector ETFs)
- VRP % ((VIX/100)^2 - rv60^2, in % squared units)
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Mapping

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def daily_to_quarter_end_last(daily: pd.Series) -> pd.Series:
    """Daily → quarter end last value (last trading day in quarter)."""
    if daily.empty:
        return daily
    return daily.resample("QE").last()


def monthly_to_quarter_end_last(monthly: pd.Series) -> pd.Series:
    """Monthly → quarter end last value."""
    if monthly.empty:
        return monthly
    return monthly.resample("QE").last()


def derive_yoy_pct(monthly_or_quarterly: pd.Series, lag: int = 12) -> pd.Series:
    """YoY %: (Pt - Pt-lag) / Pt-lag × 100. lag=12 for monthly YoY."""
    if monthly_or_quarterly.empty:
        return monthly_or_quarterly
    return monthly_or_quarterly.pct_change(periods=lag) * 100


def derive_3mo_annualized(monthly: pd.Series) -> pd.Series:
    """3-month annualized %: ((Pt/Pt-3)^4 - 1) × 100."""
    if monthly.empty:
        return monthly
    ratio = monthly / monthly.shift(3)
    return (ratio ** 4 - 1) * 100


def derive_rolling_vol_pct(daily_close: pd.Series, window: int = 60) -> pd.Series:
    """Daily close → 60d rolling std of daily returns × √252 × 100 (% annualized)."""
    if daily_close.empty:
        return daily_close
    returns = daily_close.pct_change()
    return returns.rolling(window=window).std() * np.sqrt(252) * 100


def derive_yield_spread_bps(series_long: pd.Series, series_short: pd.Series) -> pd.Series:
    """(s_long - s_short) × 100. NaN propagates."""
    if series_long.empty or series_short.empty:
        return pd.Series(dtype=float)
    aligned = pd.concat([series_long, series_short], axis=1, keys=["long", "short"])
    return (aligned["long"] - aligned["short"]) * 100


def derive_3mo_avg(monthly: pd.Series, window: int = 3) -> pd.Series:
    """Rolling 3-month mean. NaN-aware."""
    if monthly.empty:
        return monthly
    return monthly.rolling(window=window, min_periods=1).mean()


def derive_sector_dispersion(
    sector_daily_closes: Mapping[str, pd.Series],
    window: int = 60,
) -> pd.Series:
    """Across N sector ETFs, std of trailing 60d return distribution.

    Returns quarterly series of dispersion (std of {60d return per sector}).
    """
    if not sector_daily_closes:
        return pd.Series(dtype=float)
    # 60d returns per sector
    returns_60d = {
        name: close.pct_change(window) for name, close in sector_daily_closes.items()
        if not close.empty
    }
    if not returns_60d:
        return pd.Series(dtype=float)
    df = pd.DataFrame(returns_60d)
    dispersion_daily = df.std(axis=1)
    return dispersion_daily.resample("QE").last()


def derive_vrp_pct(vix_qe: pd.Series, realized_vol_60d_qe: pd.Series) -> pd.Series:
    """VRP = (VIX/100)^2 - (rv60d/100)^2 (in fraction squared, % units)."""
    if vix_qe.empty or realized_vol_60d_qe.empty:
        return pd.Series(dtype=float)
    df = pd.concat([vix_qe, realized_vol_60d_qe], axis=1, keys=["vix", "rv"])
    return (df["vix"] / 100) ** 2 - (df["rv"] / 100) ** 2


def derive_move_proxy_pct(dgs10_daily: pd.Series, window: int = 60) -> pd.Series:
    """MOVE proxy: 10y yield 의 60d realized vol of *daily changes* × √252 × 100.

    Pure proxy — actual MOVE (Treasury option vol) 와 ~70% correlation.
    """
    if dgs10_daily.empty:
        return dgs10_daily
    daily_changes = dgs10_daily.diff()
    return daily_changes.rolling(window=window).std() * np.sqrt(252) * 100


def assemble_quarterly_panel(
    start: date, end: date, raw_dir: Path | str,
) -> pd.DataFrame:
    """End-to-end: raw fetch directories → quarterly indicator panel.

    Reads pre-fetched parquet from `raw_dir/{fred,fred_alfred,yfinance,pykrx}/`.
    Returns DataFrame indexed by quarter_end with ~40 columns.

    Missing series (e.g., pre-availability era) → NaN column / partial coverage.
    """
    raw_dir = Path(raw_dir)
    cols: dict[str, pd.Series] = {}

    def _load_fred(name: str) -> pd.Series:
        path = raw_dir / "fred" / f"{name}.parquet"
        if not path.exists():
            return pd.Series(dtype=float)
        df = pd.read_parquet(path)
        return df["value"]

    def _load_alfred(name: str) -> pd.DataFrame:
        path = raw_dir / "fred_alfred" / f"{name}.parquet"
        if not path.exists():
            return pd.DataFrame()
        return pd.read_parquet(path)

    def _load_yfinance(name: str) -> pd.Series:
        path = raw_dir / "yfinance" / f"{name.replace('^', '').replace('=', '_')}.parquet"
        if not path.exists():
            return pd.Series(dtype=float)
        df = pd.read_parquet(path)
        return df["close"]

    # Yield curve daily → quarter end last
    dgs2 = daily_to_quarter_end_last(_load_fred("DGS2"))
    dgs5 = daily_to_quarter_end_last(_load_fred("DGS5"))
    dgs10 = daily_to_quarter_end_last(_load_fred("DGS10"))
    dgs30 = daily_to_quarter_end_last(_load_fred("DGS30"))
    cols["dgs2_pct"] = dgs2
    cols["dgs5_pct"] = dgs5
    cols["dgs10_pct"] = dgs10
    cols["dgs30_pct"] = dgs30
    cols["spread_10y_2y_bps"] = derive_yield_spread_bps(dgs10, dgs2)
    cols["spread_30y_5y_bps"] = derive_yield_spread_bps(dgs30, dgs5)

    # Inflation
    cpi_monthly = _load_fred("CPIAUCSL")
    core_cpi_monthly = _load_fred("CPILFESL")
    pce_monthly = _load_fred("PCEPI")
    core_pce_monthly = _load_fred("PCEPILFE")
    cols["cpi_yoy"] = monthly_to_quarter_end_last(derive_yoy_pct(cpi_monthly))
    cols["core_cpi_yoy"] = monthly_to_quarter_end_last(derive_yoy_pct(core_cpi_monthly))
    cols["pce_yoy"] = monthly_to_quarter_end_last(derive_yoy_pct(pce_monthly))
    cols["core_pce_yoy"] = monthly_to_quarter_end_last(derive_yoy_pct(core_pce_monthly))
    cols["cpi_3mo_ann"] = monthly_to_quarter_end_last(derive_3mo_annualized(cpi_monthly))

    # Inflation expectations
    cols["breakeven_5y5y"] = daily_to_quarter_end_last(_load_fred("T5YIFR"))
    cols["michigan_1y"] = monthly_to_quarter_end_last(_load_fred("MICH"))

    # Real yield
    cols["real_yield_10y_pct"] = daily_to_quarter_end_last(_load_fred("DFII10"))

    # ALFRED vintage — CFNAI / NFCI / ANFCI / GDPNOW / UNRATE
    cfnai_df = _load_alfred("CFNAI")
    cols["cfnai"] = cfnai_df["vintage_value"] if not cfnai_df.empty else pd.Series(dtype=float)
    if not cfnai_df.empty:
        cols["cfnai_3m_avg"] = cfnai_df["vintage_value"].rolling(window=3, min_periods=1).mean()
    else:
        cols["cfnai_3m_avg"] = pd.Series(dtype=float)
    nfci_df = _load_alfred("NFCI")
    cols["nfci"] = nfci_df["vintage_value"] if not nfci_df.empty else pd.Series(dtype=float)
    anfci_df = _load_alfred("ANFCI")
    cols["anfci"] = anfci_df["vintage_value"] if not anfci_df.empty else pd.Series(dtype=float)
    gdpnow_df = _load_alfred("GDPNOW")
    cols["gdp_nowcast"] = gdpnow_df["vintage_value"] if not gdpnow_df.empty else pd.Series(dtype=float)
    unrate_df = _load_alfred("UNRATE")
    cols["unrate"] = unrate_df["vintage_value"] if not unrate_df.empty else pd.Series(dtype=float)
    if not unrate_df.empty:
        u = unrate_df["vintage_value"]
        u_3m = u.rolling(window=3, min_periods=1).mean()
        u_12m_min = u.rolling(window=12, min_periods=1).min()
        cols["sahm_rule_triggered"] = (u_3m >= u_12m_min + 0.5).astype(float)

    # Credit
    baa = _load_fred("BAA")
    aaa = _load_fred("AAA")
    if not baa.empty and not aaa.empty:
        cols["baa_aaa_bps"] = monthly_to_quarter_end_last((baa - aaa) * 100)
    cols["baa_10y_bps"] = daily_to_quarter_end_last(_load_fred("BAA10Y")) * 100

    # FX
    cols["usdkrw"] = daily_to_quarter_end_last(_load_fred("DEXKOUS"))
    cols["dxy_dtwexm"] = daily_to_quarter_end_last(_load_fred("DTWEXM"))

    # Vol indicators
    vix_daily = _load_fred("VIXCLS")
    cols["vix"] = daily_to_quarter_end_last(vix_daily)
    cols["skew"] = daily_to_quarter_end_last(_load_yfinance("^SKEW"))
    # Realized vol from ^GSPC
    spx_daily = _load_yfinance("^GSPC")
    if not spx_daily.empty:
        cols["realized_vol_60d_spx_pct"] = daily_to_quarter_end_last(
            derive_rolling_vol_pct(spx_daily, window=60),
        )
    # MOVE proxy
    dgs10_daily = _load_fred("DGS10")
    if not dgs10_daily.empty:
        cols["move_proxy_pct"] = daily_to_quarter_end_last(derive_move_proxy_pct(dgs10_daily))
    # VRP
    if not vix_daily.empty and not spx_daily.empty:
        vix_qe = daily_to_quarter_end_last(vix_daily)
        rv60_qe = cols.get("realized_vol_60d_spx_pct", pd.Series(dtype=float))
        cols["vrp_pct"] = derive_vrp_pct(vix_qe, rv60_qe)

    # Sector dispersion
    sector_tickers = ["XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "XLB"]
    sector_closes = {t: _load_yfinance(t) for t in sector_tickers}
    sector_closes = {t: s for t, s in sector_closes.items() if not s.empty}
    if sector_closes:
        cols["sector_dispersion"] = derive_sector_dispersion(sector_closes, window=60)

    # KOSPI200 valuation (monthly → quarter end)
    pykrx_val_path = raw_dir / "pykrx" / "kospi200_valuation.parquet"
    if pykrx_val_path.exists():
        val_df = pd.read_parquet(pykrx_val_path)
        cols["kospi200_pbr"] = val_df["PBR"].resample("QE").last()
        cols["kospi200_per"] = val_df["PER"].resample("QE").last()
        cols["kospi200_div_yield"] = val_df["DIV_YIELD"].resample("QE").last()

    # Foreign flow monthly → quarterly z-score (60-quarter rolling)
    ff_path = raw_dir / "pykrx" / "foreign_flow.parquet"
    if ff_path.exists():
        ff_df = pd.read_parquet(ff_path)
        ff_quarterly = ff_df["net_buy_krw"].resample("QE").sum()
        rolling_mean = ff_quarterly.rolling(window=60, min_periods=8).mean()
        rolling_std = ff_quarterly.rolling(window=60, min_periods=8).std()
        # Floor std to 1e-6 to avoid huge z (Issue #22 — F6 baseline sd)
        rolling_std_clamped = rolling_std.where(rolling_std > 1e-6, 1e-6)
        cols["foreign_flow_z"] = (ff_quarterly - rolling_mean) / rolling_std_clamped

    # Shiller CAPE (static csv) — graceful absence
    cape_path = Path(__file__).parent / "shiller_cape_static.csv"
    if cape_path.exists():
        cape_df = pd.read_csv(cape_path, parse_dates=["date"]).set_index("date")
        cols["shiller_cape"] = cape_df["cape"].resample("QE").last()

    # Recession dummy
    cols["usrec"] = monthly_to_quarter_end_last(_load_fred("USREC"))

    # Cash (3m T-bill yield, quarterly avg in %)
    tb3 = _load_fred("TB3MS")
    cols["tb3ms_pct"] = monthly_to_quarter_end_last(tb3)

    # Construct DataFrame on union index, filter to [start, end]
    panel = pd.DataFrame(cols)
    panel.index = pd.to_datetime(panel.index)
    panel = panel[(panel.index >= pd.Timestamp(start)) & (panel.index <= pd.Timestamp(end))]
    panel.index.name = "quarter_end"
    logger.info("assemble_quarterly_panel: %s rows × %s columns", *panel.shape)
    return panel
