# Tier 2 — β Calibration Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build 8-bucket historical return time series (1991-2024 quarterly), implement joint hierarchical optimization with NaN-skip + hard zero cells + 5-family group prior for 96-entry β matrix, F11 staggered protocol (Phase A 1991-2024 / Phase B 2010+ sub-fit), TIPS scalar regression (12 entries), and acceptance gates (VIF ≤ 5, effective df ≤ 44, OOS Sharpe > 1.171).

**Architecture:** PR2a's existing `hybrid_calibration` extended with hierarchical μ joint variable + hard zero cell clamping + per-factor NaN-skip in `simulate_portfolio_returns_per_factor_aware`. PR2a's `walk_forward` and `aggregate_median_beta` reused. New 8-bucket `bucket_returns.parquet` replaces 5-bucket. F11 column fits separately after main β converges (Phase B).

**Tech Stack:** Python 3.11+, scipy.optimize.L-BFGS-B, numpy, pandas (rolling, resample), yfinance + pykrx + ECOS + FRED stitching, pytest.

**Spec:** [`docs/superpowers/specs/2026-05-28-tier2-calibration-design.md`](../specs/2026-05-28-tier2-calibration-design.md)

**Dependency:** Tier 0 (12 factors + new fetchers) + Tier 1 (8 buckets + INITIAL_BETA prior) merged.

---

## File Structure

**Created:**
- `backtest/historical/bucket_returns_8b.py` — 8-bucket TR construction
- `tradingagents/skills/research/factor_calibration_hierarchical.py` — hierarchical objective + L-BFGS-B
- `tradingagents/skills/research/factor_calibration_tips.py` — TIPS scalar regression
- `scripts/calibrate_factor_model_8b.py` — entry CLI
- `scripts/validate_factor_model_8b.py` — VIF + df + OOS Sharpe acceptance
- `tests/unit/backtest/test_bucket_returns_8b.py`
- `tests/unit/skills/research/test_factor_calibration_hierarchical.py`
- `tests/unit/skills/research/test_factor_calibration_tips.py`
- `tests/integration/test_tier2_calibration_pipeline.py`

**Modified:**
- `tradingagents/skills/research/factor_calibration.py` — add `simulate_portfolio_returns_per_factor_aware`, `HARD_ZERO_CELLS`, `BUCKET_FAMILIES`, `compute_effective_df`, `compute_vif_matrix`
- `tradingagents/skills/research/factor_to_bucket.py` — runtime uses calibrated β (constant replace or coefficient_table.json load)

---

## Task 1: 8-bucket bucket_returns — kr_equity (KOSPI 200 TR)

**Files:**
- Create: `backtest/historical/bucket_returns_8b.py`
- Create: `tests/unit/backtest/test_bucket_returns_8b.py`

- [ ] **Step 1: Write failing test**

```python
import pytest
from unittest.mock import patch
from datetime import date
import pandas as pd
from backtest.historical.bucket_returns_8b import _build_kr_equity_tr


def test_kr_equity_tr_from_kospi200(monkeypatch):
    """KOSPI 200 daily price + monthly dividend yield → daily TR."""
    fake_prices = pd.DataFrame({
        "종가": [380, 385, 388, 390],
    }, index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]))
    # Mock pykrx
    with patch("backtest.historical.bucket_returns_8b.pkstock.get_index_ohlcv_by_date",
               return_value=fake_prices):
        s = _build_kr_equity_tr(date(2024, 1, 1), date(2024, 1, 31))
    assert not s.empty
    # First-day NaN expected after .pct_change()
    assert pd.isna(s.iloc[0]) or len(s) == 3
```

- [ ] **Step 2: Run (expect FAIL)**

```bash
pytest tests/unit/backtest/test_bucket_returns_8b.py::test_kr_equity_tr_from_kospi200 -v
```

- [ ] **Step 3: Implement skeleton + kr_equity**

`backtest/historical/bucket_returns_8b.py`:
```python
"""8-bucket historical return time series construction (Tier 2).

Replaces 5-bucket bucket_returns.parquet with 8-bucket schema:
  kr_equity, global_equity, precious_metals, cyclical_commodity_fx,
  kr_bond, credit, global_duration, cash_mmf.

All returns are KRW basis (USD → KRW via DEXKOUS).

Source per bucket (실측 검증 후 확정 in spec §7.2):
  kr_equity:               pykrx KOSPI 200 (1028) daily close + dividend RI
  global_equity:           VEU 2007+ / ^GSPC 1991-2007 (USD → KRW)
  precious_metals:         GLD 2004+ + SLV 2006+ (50:50 KRW basis)
                           / FRED GOLDAMGBD228NLBM pre-2004 fallback
  cyclical_commodity_fx:   DJP 2006+ + DXY 70:30 / WTI+DXY pre-2006
  kr_bond:                 KOSEF 148070.KS 2011+ / ECOS kr_treasury_10y duration pre-2011
  credit:                  HYG 2007+ / BAA10Y returns proxy pre-2007
  global_duration:         TLT 2002+ / DGS10 duration pre-2002
  cash_mmf:                ECOS kr_treasury_3y 단기금리 TR
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _build_kr_equity_tr(start: date, end: date) -> pd.Series:
    """KOSPI 200 Total Return = price-change + dividend-reinvestment.

    Source: pykrx get_index_ohlcv_by_date(1028) daily close (no dividends).
    Dividend approximation: + KOSPI200 div yield / 252 per day (~2%/yr).
    """
    from pykrx import stock as pkstock
    df = pkstock.get_index_ohlcv_by_date(
        start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), "1028"
    )
    if df is None or df.empty:
        return pd.Series(dtype=float, name="kr_equity_tr")
    price_ret = df["종가"].pct_change()
    # Approximate dividend reinvestment (2% annual / 252 trading days)
    div_daily = 0.02 / 252
    return (price_ret + div_daily).rename("kr_equity_tr")


__all__ = ["_build_kr_equity_tr"]
```

- [ ] **Step 4: Run + commit**

```bash
pytest tests/unit/backtest/test_bucket_returns_8b.py::test_kr_equity_tr_from_kospi200 -v
git add backtest/historical/bucket_returns_8b.py tests/unit/backtest/test_bucket_returns_8b.py
git commit -m "feat(tier2): bucket_returns_8b — kr_equity (KOSPI200 TR via pykrx)"
```

---

## Task 2: global_equity (VEU/^GSPC stitching)

- [ ] **Step 1: Test**

```python
def test_global_equity_stitching(monkeypatch):
    """Use VEU post-2007, ^GSPC pre-2007."""
    from backtest.historical.bucket_returns_8b import _build_global_equity_tr
    # Mock yfinance — VEU has data from 2007+, GSPC from 1991+
    # ... (test scaffolding for stitch boundary)
    pass  # Implement once skeleton is in place
```

- [ ] **Step 2: Implement**

Add to `bucket_returns_8b.py`:
```python
def _build_global_equity_tr(start: date, end: date) -> pd.Series:
    """VEU 2007+, ^GSPC 1991-2007 (KRW basis via DEXKOUS).

    VEU includes KR ~1-2% (minor contamination, acceptable per spec).
    Pre-2007: S&P 500 only (US dominant, acceptable for KR fund global exposure).
    """
    import yfinance as yf
    from tradingagents.dataflows import fred
    boundary = date(2007, 3, 8)  # VEU IPO

    def _yf_returns_krw(symbol: str, s: date, e: date) -> pd.Series:
        df = yf.Ticker(symbol).history(start=s, end=e + timedelta(days=1), auto_adjust=True)
        if df.empty:
            return pd.Series(dtype=float)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        price_ret = df["Close"].pct_change()
        # KRW basis conversion: r_KRW = (1+r_USD) × (1+r_KRWUSD) - 1
        krw_series = fred.fetch_fred_series("usd_krw", s, e)
        krw_aligned = krw_series.reindex(price_ret.index).ffill()
        krw_ret = krw_aligned.pct_change()
        return ((1 + price_ret) * (1 + krw_ret) - 1).dropna()

    pieces: list[pd.Series] = []
    if start < boundary:
        gspc = _yf_returns_krw("^GSPC", start, min(end, boundary - timedelta(days=1)))
        pieces.append(gspc)
    if end >= boundary:
        veu = _yf_returns_krw("VEU", max(start, boundary), end)
        pieces.append(veu)
    if not pieces:
        return pd.Series(dtype=float, name="global_equity_tr")
    return pd.concat(pieces).sort_index().rename("global_equity_tr")
```

- [ ] **Step 3: Test + commit**

```bash
git commit -am "feat(tier2): bucket_returns_8b — global_equity stitching (VEU+^GSPC KRW basis)"
```

---

## Task 3: precious_metals (GLD+SLV 50:50)

- [ ] **Step 1: Implement**

```python
def _build_precious_metals_tr(start: date, end: date) -> pd.Series:
    """50:50 GLD/SLV 2006+, fallback to FRED gold spot pre-2004.

    GLD: 2004-11+, SLV: 2006-04+. Pre-2004: London gold AM (GOLDAMGBD228NLBM).
    """
    import yfinance as yf
    from tradingagents.dataflows import fred
    gld_start = date(2004, 11, 18)
    slv_start = date(2006, 4, 28)

    def _yf_ret(sym, s, e):
        df = yf.Ticker(sym).history(start=s, end=e + timedelta(days=1), auto_adjust=True)
        if df.empty: return pd.Series(dtype=float)
        if df.index.tz is not None: df.index = df.index.tz_localize(None)
        return df["Close"].pct_change()

    # USD → KRW conversion
    krw = fred.fetch_fred_series("usd_krw", start, end)
    krw_ret = krw.pct_change()

    pieces = []
    if start < gld_start:
        # Pre-2004 fallback: FRED gold spot only
        gold = fred.fetch_fred_series("GOLDAMGBD228NLBM", start, min(end, gld_start - timedelta(days=1)))
        if not gold.empty:
            gold_ret = gold.pct_change()
            aligned_krw = krw_ret.reindex(gold_ret.index).ffill()
            pre = ((1 + gold_ret) * (1 + aligned_krw) - 1).dropna()
            pieces.append(pre)
    if end >= gld_start:
        gld = _yf_ret("GLD", max(start, gld_start), end)
        if end >= slv_start:
            slv = _yf_ret("SLV", max(start, slv_start), end)
            common = gld.index.intersection(slv.index)
            avg = 0.5 * gld.loc[common] + 0.5 * slv.loc[common]
        else:
            avg = gld
        aligned_krw = krw_ret.reindex(avg.index).ffill()
        post = ((1 + avg) * (1 + aligned_krw) - 1).dropna()
        pieces.append(post)
    if not pieces:
        return pd.Series(dtype=float, name="precious_metals_tr")
    return pd.concat(pieces).sort_index().rename("precious_metals_tr")
```

- [ ] **Step 2: Test + commit**

```bash
git commit -am "feat(tier2): bucket_returns_8b — precious_metals (GLD+SLV / gold spot fallback)"
```

---

## Task 4: cyclical_commodity_fx, kr_bond (duration), credit, global_duration, cash_mmf

> **Convention:** Each helper follows similar pattern (yfinance/FRED/ECOS source + KRW conversion + stitching). Implementation per spec §7.2.

- [ ] **Step 1: Implement `_build_cyclical_commodity_fx_tr`**

```python
def _build_cyclical_commodity_fx_tr(start: date, end: date) -> pd.Series:
    """DJP 2006+ (Bloomberg Commodity Index) + DXY 70:30 weighted.
    Pre-2006: WTI (CL=F) + DXY weighted.
    """
    import yfinance as yf
    from tradingagents.dataflows import fred
    djp_start = date(2006, 10, 30)
    def _yf_ret(sym, s, e):
        df = yf.Ticker(sym).history(start=s, end=e + timedelta(days=1), auto_adjust=True)
        if df.empty: return pd.Series(dtype=float)
        if df.index.tz is not None: df.index = df.index.tz_localize(None)
        return df["Close"].pct_change()
    krw_ret = fred.fetch_fred_series("usd_krw", start, end).pct_change()
    dxy = fred.fetch_fred_series("dxy", start, end).pct_change()
    pieces = []
    if start < djp_start:
        wti = _yf_ret("CL=F", start, min(end, djp_start - timedelta(days=1)))
        dxy_pre = dxy.reindex(wti.index).ffill()
        krw_pre = krw_ret.reindex(wti.index).ffill()
        commodity = 0.70 * wti + 0.30 * dxy_pre
        pieces.append(((1 + commodity) * (1 + krw_pre) - 1).dropna())
    if end >= djp_start:
        djp = _yf_ret("DJP", max(start, djp_start), end)
        dxy_post = dxy.reindex(djp.index).ffill()
        krw_post = krw_ret.reindex(djp.index).ffill()
        commodity = 0.70 * djp + 0.30 * dxy_post
        pieces.append(((1 + commodity) * (1 + krw_post) - 1).dropna())
    if not pieces:
        return pd.Series(dtype=float, name="cyclical_commodity_fx_tr")
    return pd.concat(pieces).sort_index().rename("cyclical_commodity_fx_tr")
```

- [ ] **Step 2: Implement `_build_kr_bond_tr`**

```python
def _build_kr_bond_tr(start: date, end: date) -> pd.Series:
    """KOSEF 148070.KS 2011-10+, ECOS kr_treasury_10y duration approximation pre-2011.

    Duration approximation: r_t ≈ -D × Δy_t + y_{t-1}/360 (D = 8.5y for KTB 10y).
    """
    import yfinance as yf
    from tradingagents.dataflows import ecos
    kosef_start = date(2011, 10, 20)
    pieces = []
    if start < kosef_start:
        # Duration approximation from ECOS yields
        y = ecos.fetch_ecos_series("kr_treasury_10y", start, min(end, kosef_start - timedelta(days=1)),
                                    freq="D")
        if not y.empty:
            d_y = y.diff()
            r = (-8.5 * d_y / 100 + y.shift(1) / 36000).dropna()  # bps → decimal
            pieces.append(r.rename("kr_bond_tr"))
    if end >= kosef_start:
        df = yf.Ticker("148070.KS").history(start=max(start, kosef_start), end=end + timedelta(days=1), auto_adjust=True)
        if not df.empty:
            if df.index.tz is not None: df.index = df.index.tz_localize(None)
            pieces.append(df["Close"].pct_change().dropna().rename("kr_bond_tr"))
    if not pieces:
        return pd.Series(dtype=float, name="kr_bond_tr")
    return pd.concat(pieces).sort_index().rename("kr_bond_tr")
```

- [ ] **Step 3: Implement `_build_credit_tr` (HYG + BAA10Y), `_build_global_duration_tr` (TLT + DGS10 duration), `_build_cash_mmf_tr` (ECOS short rate)**

```python
def _build_credit_tr(start: date, end: date) -> pd.Series:
    """HYG 2007+, BAA10Y proxy pre-2007.
    BAA10Y is a *spread* — convert to *return proxy* via -duration × Δspread + carry.
    """
    import yfinance as yf
    from tradingagents.dataflows import fred
    hyg_start = date(2007, 4, 11)
    krw_ret = fred.fetch_fred_series("usd_krw", start, end).pct_change()
    pieces = []
    if start < hyg_start:
        baa = fred.fetch_fred_series("us_credit_proxy", start, min(end, hyg_start - timedelta(days=1)))
        if not baa.empty:
            d_spread = baa.diff()
            r = (-5.0 * d_spread / 100 + baa.shift(1) / 36000).dropna()  # 5y duration approx
            pieces.append(r.rename("credit_tr"))
    if end >= hyg_start:
        df = yf.Ticker("HYG").history(start=max(start, hyg_start), end=end + timedelta(days=1), auto_adjust=True)
        if not df.empty:
            if df.index.tz is not None: df.index = df.index.tz_localize(None)
            ret_usd = df["Close"].pct_change()
            krw_a = krw_ret.reindex(ret_usd.index).ffill()
            ret_krw = ((1 + ret_usd) * (1 + krw_a) - 1).dropna()
            pieces.append(ret_krw.rename("credit_tr"))
    if not pieces:
        return pd.Series(dtype=float, name="credit_tr")
    return pd.concat(pieces).sort_index().rename("credit_tr")


def _build_global_duration_tr(start: date, end: date) -> pd.Series:
    """TLT 2002+, DGS10 duration approx pre-2002 (D=18y for 20+ Treasury)."""
    import yfinance as yf
    from tradingagents.dataflows import fred
    tlt_start = date(2002, 7, 30)
    krw_ret = fred.fetch_fred_series("usd_krw", start, end).pct_change()
    pieces = []
    if start < tlt_start:
        y = fred.fetch_fred_series("us_10y", start, min(end, tlt_start - timedelta(days=1)))
        if not y.empty:
            d_y = y.diff()
            r_usd = (-9.0 * d_y / 100 + y.shift(1) / 36000).dropna()  # 10y has D~9
            krw_a = krw_ret.reindex(r_usd.index).ffill()
            r_krw = ((1 + r_usd) * (1 + krw_a) - 1).dropna()
            pieces.append(r_krw.rename("global_duration_tr"))
    if end >= tlt_start:
        df = yf.Ticker("TLT").history(start=max(start, tlt_start), end=end + timedelta(days=1), auto_adjust=True)
        if not df.empty:
            if df.index.tz is not None: df.index = df.index.tz_localize(None)
            ret_usd = df["Close"].pct_change()
            krw_a = krw_ret.reindex(ret_usd.index).ffill()
            ret_krw = ((1 + ret_usd) * (1 + krw_a) - 1).dropna()
            pieces.append(ret_krw.rename("global_duration_tr"))
    if not pieces:
        return pd.Series(dtype=float, name="global_duration_tr")
    return pd.concat(pieces).sort_index().rename("global_duration_tr")


def _build_cash_mmf_tr(start: date, end: date) -> pd.Series:
    """ECOS kr_treasury_3y short-rate TR (annualized → daily)."""
    from tradingagents.dataflows import ecos
    y = ecos.fetch_ecos_series("kr_treasury_3y", start, end, freq="D")
    if y.empty:
        return pd.Series(dtype=float, name="cash_mmf_tr")
    daily = (y / 36000).shift(1).rename("cash_mmf_tr")  # bps annual → daily decimal
    return daily.dropna()
```

- [ ] **Step 4: Test all helpers (smoke) + commit**

```bash
pytest tests/unit/backtest/test_bucket_returns_8b.py -v
git commit -am "feat(tier2): bucket_returns_8b — 7 remaining bucket TR builders"
```

---

## Task 5: build_bucket_returns_8b orchestrator + quarterly aggregation

- [ ] **Step 1: Implement**

```python
def build_bucket_returns_8b(
    start: date = date(1991, 1, 1),
    end: date = date(2024, 12, 31),
) -> pd.DataFrame:
    """Quarterly returns for 8-bucket schema. KRW basis.

    Output: DataFrame indexed by quarter_end, 8 columns (one per bucket).
    """
    builders = [
        ("kr_equity",             _build_kr_equity_tr),
        ("global_equity",         _build_global_equity_tr),
        ("precious_metals",       _build_precious_metals_tr),
        ("cyclical_commodity_fx", _build_cyclical_commodity_fx_tr),
        ("kr_bond",               _build_kr_bond_tr),
        ("credit",                _build_credit_tr),
        ("global_duration",       _build_global_duration_tr),
        ("cash_mmf",              _build_cash_mmf_tr),
    ]
    cols = []
    for name, fn in builders:
        try:
            s = fn(start, end)
            cols.append(s.rename(name))
        except Exception as e:
            logger.warning("bucket %s build failed: %s", name, e)
            cols.append(pd.Series(dtype=float, name=name))
    df = pd.concat(cols, axis=1)
    # Quarterly aggregate: compound daily returns
    return df.resample("Q").apply(lambda x: (1 + x.fillna(0)).prod() - 1)


def save_bucket_returns_8b(
    out_path: Path = Path("backtest/historical/bucket_returns_8b.parquet"),
    start: date = date(1991, 1, 1),
    end: date = date(2024, 12, 31),
) -> pd.DataFrame:
    df = build_bucket_returns_8b(start, end)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path)
    return df
```

- [ ] **Step 2: Run, save, sanity-check**

```bash
python -c "
from datetime import date
from backtest.historical.bucket_returns_8b import save_bucket_returns_8b
df = save_bucket_returns_8b()
print('shape:', df.shape)
print('cols:', list(df.columns))
print(df.tail(4))
print('correlation matrix:')
print(df.corr().round(2))
"
```
Expected: shape ~(134, 8), correlations sensible (kr_eq vs gl_eq ρ > 0.3, kr_bond vs cash ρ > 0.5).

- [ ] **Step 3: Commit**

```bash
git add backtest/historical/bucket_returns_8b.py backtest/historical/bucket_returns_8b.parquet
git commit -m "feat(tier2): bucket_returns_8b orchestrator + 1991-2024 quarterly snapshot"
```

---

## Task 6: HARD_ZERO_CELLS + BUCKET_FAMILIES constants

**Files:**
- Modify: `tradingagents/skills/research/factor_calibration.py`
- Modify: `tests/unit/skills/research/test_factor_calibration.py`

- [ ] **Step 1: Test**

```python
def test_hard_zero_cells_28_entries():
    from tradingagents.skills.research.factor_calibration import HARD_ZERO_CELLS
    assert len(HARD_ZERO_CELLS) == 28
    assert ("F1_growth", "precious_metals") in HARD_ZERO_CELLS
    assert ("F8_valuation", "precious_metals") in HARD_ZERO_CELLS
    assert ("F11_earnings_revision", "precious_metals") in HARD_ZERO_CELLS


def test_bucket_families_5_families():
    from tradingagents.skills.research.factor_calibration import BUCKET_FAMILIES
    assert set(BUCKET_FAMILIES.keys()) == {"equity", "commodity", "duration", "credit", "cash"}
    assert "kr_equity" in BUCKET_FAMILIES["equity"]
    assert "global_equity" in BUCKET_FAMILIES["equity"]
    assert "precious_metals" in BUCKET_FAMILIES["commodity"]
    assert "kr_bond" in BUCKET_FAMILIES["duration"]
    assert BUCKET_FAMILIES["credit"] == ["credit"]
    assert BUCKET_FAMILIES["cash"] == ["cash_mmf"]
```

- [ ] **Step 2: Implement constants**

Add to `tradingagents/skills/research/factor_calibration.py`:
```python
# Tier 2: Hard zero cells (theoretical exclusion). 28 entries per spec §3.
HARD_ZERO_CELLS: Final[frozenset[tuple[str, str]]] = frozenset({
    ("F1_growth", "precious_metals"),
    ("F2_inflation", "global_equity"),
    ("F3_real_rate", "kr_equity"),
    ("F3_real_rate", "cyclical_commodity_fx"),
    ("F4_term_premium", "precious_metals"),
    ("F4_term_premium", "cyclical_commodity_fx"),
    ("F4_term_premium", "credit"),
    ("F5_credit_cycle", "precious_metals"),
    ("F5_credit_cycle", "cyclical_commodity_fx"),
    ("F5_credit_cycle", "global_duration"),
    ("F6_krw_regime", "credit"),
    ("F6_krw_regime", "global_duration"),
    ("F7_equity_vol_regime", "cyclical_commodity_fx"),
    ("F7_equity_vol_regime", "precious_metals"),
    ("F7_equity_vol_regime", "global_duration"),
    ("F8_valuation", "precious_metals"),
    ("F8_valuation", "cyclical_commodity_fx"),
    ("F8_valuation", "kr_bond"),
    ("F8_valuation", "credit"),
    ("F8_valuation", "global_duration"),
    ("F8_valuation", "cash_mmf"),
    ("F9_market_dispersion", "precious_metals"),
    ("F9_market_dispersion", "cyclical_commodity_fx"),
    ("F10_systemic_liquidity", "precious_metals"),
    ("F11_earnings_revision", "precious_metals"),
    ("F11_earnings_revision", "cyclical_commodity_fx"),
    ("F12_china_credit_impulse", "global_duration"),
    ("F12_china_credit_impulse", "precious_metals"),
})

# Tier 2: Bucket family groups for hierarchical prior.
BUCKET_FAMILIES: Final[dict[str, list[str]]] = {
    "equity":    ["kr_equity", "global_equity"],
    "commodity": ["precious_metals", "cyclical_commodity_fx"],
    "duration":  ["kr_bond", "global_duration"],
    "credit":    ["credit"],
    "cash":      ["cash_mmf"],
}


def bucket_family(bucket: str) -> str:
    for fam, members in BUCKET_FAMILIES.items():
        if bucket in members:
            return fam
    raise ValueError(f"Unknown bucket {bucket}")
```

- [ ] **Step 3: Test + commit**

```bash
pytest tests/unit/skills/research/test_factor_calibration.py::test_hard_zero_cells_28_entries tests/unit/skills/research/test_factor_calibration.py::test_bucket_families_5_families -v
git commit -am "feat(tier2): HARD_ZERO_CELLS (28) + BUCKET_FAMILIES (5)"
```

---

## Task 7: simulate_portfolio_returns_per_factor_aware (NaN-skip)

- [ ] **Step 1: Test**

```python
def test_simulate_skips_nan_factor():
    """If factor_z is NaN, factor contribution = 0."""
    from tradingagents.skills.research.factor_calibration import (
        simulate_portfolio_returns_per_factor_aware, HistoricalSample,
    )
    from tradingagents.skills.research.factor_to_bucket import INITIAL_BASELINE
    samples = [
        HistoricalSample(
            date="2020-Q1",
            factor_z={"F1_growth": float("nan"), "F2_inflation": 1.0,
                      **{f: 0.0 for f in ["F3_real_rate","F4_term_premium",
                          "F5_credit_cycle","F6_krw_regime","F7_equity_vol_regime",
                          "F8_valuation","F9_market_dispersion","F10_systemic_liquidity",
                          "F11_earnings_revision","F12_china_credit_impulse"]}},
            bucket_returns_next={b: 0.0 for b in INITIAL_BASELINE},
        ),
    ]
    beta = {(f, b): 0.05 for f in [
        "F1_growth","F2_inflation","F3_real_rate","F4_term_premium",
        "F5_credit_cycle","F6_krw_regime","F7_equity_vol_regime",
        "F8_valuation","F9_market_dispersion","F10_systemic_liquidity",
        "F11_earnings_revision","F12_china_credit_impulse",
    ] for b in INITIAL_BASELINE}
    returns = simulate_portfolio_returns_per_factor_aware(samples, beta)
    # F1 NaN → contributes 0. F2=+1 → bucket shifted by β·1=0.05 per bucket (but row sum=0 from prior).
    # Returns array exists.
    assert len(returns) == 1
```

- [ ] **Step 2: Implement**

```python
def simulate_portfolio_returns_per_factor_aware(
    samples: list[HistoricalSample],
    beta: dict[tuple[str, str], float],
    baseline: dict[str, float] | None = None,
) -> np.ndarray:
    """Apply factor model per-sample with NaN-skip.

    Each factor's contribution skipped when factor_z is None/NaN.
    Per-factor window emerges naturally: factor f's β only updates via
    samples where factor_z[f] is valid.
    """
    from tradingagents.skills.research.factor_to_bucket import (
        BUCKETS, FACTORS, PER_FACTOR_BUCKET_CONTRIB_CAP, INITIAL_BASELINE,
    )
    baseline = baseline or INITIAL_BASELINE
    returns = []
    for s in samples:
        bucket = dict(baseline)
        for f in FACTORS:
            z = s.factor_z.get(f)
            if z is None or (isinstance(z, float) and np.isnan(z)):
                continue
            for b in BUCKETS:
                contrib = beta.get((f, b), 0.0) * z
                contrib = max(-PER_FACTOR_BUCKET_CONTRIB_CAP,
                              min(PER_FACTOR_BUCKET_CONTRIB_CAP, contrib))
                bucket[b] = bucket.get(b, 0.0) + contrib
        projected = _project_simple(bucket)
        ret = sum(projected[b] * s.bucket_returns_next.get(b, 0.0) for b in BUCKETS)
        returns.append(ret)
    return np.array(returns)
```

- [ ] **Step 3: Test + commit**

```bash
pytest tests/unit/skills/research/test_factor_calibration.py::test_simulate_skips_nan_factor -v
git commit -am "feat(tier2): simulate_portfolio_returns_per_factor_aware (NaN-skip)"
```

---

## Task 8: hybrid_calibration_hierarchical (joint optimization)

**Files:**
- Create: `tradingagents/skills/research/factor_calibration_hierarchical.py`
- Create: `tests/unit/skills/research/test_factor_calibration_hierarchical.py`

- [ ] **Step 1: Test**

```python
def test_hierarchical_fit_with_hard_zeros():
    """Hard zero cells are clamped to 0 in final β."""
    from tradingagents.skills.research.factor_calibration_hierarchical import (
        hybrid_calibration_hierarchical,
    )
    # ... build synthetic samples (50+ quarters with random factor_z + bucket_returns)
    # Verify HARD_ZERO_CELLS all zero in calibrated_beta
    # Verify μ_{f, family} per family populated
    pass  # IMPLEMENT against actual fixtures
```

- [ ] **Step 2: Implement**

`tradingagents/skills/research/factor_calibration_hierarchical.py`:
```python
"""Joint hierarchical β + μ optimization (Tier 2).

L(β, μ) = -Sharpe(β; train)
        + λ_global · ||β - prior||²
        + λ_family · Σ_(f,b) ||β_{f,b} - μ_{f, family(b)}||²
        + sign_penalty(β)
        + hard_zero_penalty(β)   # clamps hard-zero cells

L-BFGS-B over (free β entries + μ entries) decision vector.
"""
from __future__ import annotations

import logging
from typing import Final

import numpy as np
from scipy.optimize import minimize

from tradingagents.skills.research.factor_calibration import (
    BUCKET_FAMILIES, HARD_ZERO_CELLS, HistoricalSample,
    bucket_family, compute_sharpe,
    simulate_portfolio_returns_per_factor_aware,
)
from tradingagents.skills.research.factor_to_bucket import (
    BUCKETS, FACTORS, INITIAL_BETA, SIGN_RESTRICTION,
)

logger = logging.getLogger(__name__)

HARD_ZERO_PENALTY_WEIGHT: Final[float] = 1000.0


def _sign_penalty(beta: dict[tuple[str, str], float]) -> float:
    pen = 0.0
    for key, expected in SIGN_RESTRICTION.items():
        val = beta.get(key, 0.0)
        if expected == "positive" and val < 0:
            pen += val**2 * 100
        elif expected == "negative" and val > 0:
            pen += val**2 * 100
    return pen


def hybrid_calibration_hierarchical(
    train: list[HistoricalSample],
    prior_beta: dict[tuple[str, str], float] | None = None,
    lambda_global: float = 2.0,
    lambda_family: float = 0.5,
    max_iter: int = 100,
) -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], float], float]:
    """Returns (calibrated_beta, calibrated_mu, in_sample_sharpe).

    decision vars: free β entries (96 - len(HARD_ZERO_CELLS) ≈ 68) + μ entries
    (12 factors × 5 families = 60). Total ~128 dim.
    """
    prior = prior_beta or INITIAL_BETA
    free_beta_keys = sorted(set(prior.keys()) - HARD_ZERO_CELLS)
    mu_keys = sorted([(f, fam) for f in FACTORS for fam in BUCKET_FAMILIES])
    n_beta = len(free_beta_keys)
    n_mu = len(mu_keys)

    # Initial: prior β for free, family-mean of prior for μ
    x0 = np.concatenate([
        np.array([prior[k] for k in free_beta_keys]),
        np.array([
            np.mean([prior[(f, b)] for b in BUCKET_FAMILIES[fam]])
            for (f, fam) in mu_keys
        ]),
    ])
    bounds = [(-0.20, 0.20)] * n_beta + [(-0.15, 0.15)] * n_mu

    def _unpack(x: np.ndarray) -> tuple[dict, dict]:
        beta_free = {k: float(x[i]) for i, k in enumerate(free_beta_keys)}
        beta = {**beta_free, **{k: 0.0 for k in HARD_ZERO_CELLS}}
        mu = {k: float(x[n_beta + i]) for i, k in enumerate(mu_keys)}
        return beta, mu

    def objective(x: np.ndarray) -> float:
        beta, mu = _unpack(x)
        returns = simulate_portfolio_returns_per_factor_aware(train, beta)
        sharpe = compute_sharpe(returns)
        # Prior penalty: ||β - prior||²
        prior_pen = lambda_global * sum(
            (beta[k] - prior[k])**2 for k in beta
        )
        # Family penalty: Σ_(f,b) (β_{f,b} - μ_{f, family(b)})²
        fam_pen = 0.0
        for (f, b), v in beta.items():
            mu_val = mu[(f, bucket_family(b))]
            fam_pen += lambda_family * (v - mu_val) ** 2
        sign_pen = _sign_penalty(beta)
        return -sharpe + prior_pen + fam_pen + sign_pen

    result = minimize(objective, x0, method="L-BFGS-B", bounds=bounds,
                      options={"maxiter": max_iter})
    beta, mu = _unpack(result.x)
    returns = simulate_portfolio_returns_per_factor_aware(train, beta)
    final_sharpe = compute_sharpe(returns)
    return beta, mu, final_sharpe
```

- [ ] **Step 3: Test + commit**

```bash
pytest tests/unit/skills/research/test_factor_calibration_hierarchical.py -v
git add tradingagents/skills/research/factor_calibration_hierarchical.py tests/unit/skills/research/test_factor_calibration_hierarchical.py
git commit -m "feat(tier2): hybrid_calibration_hierarchical (joint β+μ, L-BFGS-B)"
```

---

## Task 9: Effective df + VIF compute

- [ ] **Step 1: Test + implement**

Add to `factor_calibration.py`:
```python
def compute_effective_df(design_matrix: np.ndarray, lambda_global: float) -> float:
    """Effective degrees of freedom (Hastie-Tibshirani-Friedman ESL §3.4.1).
    df = Σ d_j² / (d_j² + λ) where d_j = singular values of X.
    """
    _, sv, _ = np.linalg.svd(design_matrix, full_matrices=False)
    return float(np.sum(sv**2 / (sv**2 + lambda_global)))


def compute_vif_matrix(
    samples: list[HistoricalSample], factors: list[str]
) -> pd.DataFrame:
    """Pairwise VIF for factor z-scores. VIF_j = 1 / (1 - R²_j).
    R²_j = R² of regressing factor j on remaining factors.
    """
    import pandas as pd
    from sklearn.linear_model import LinearRegression
    Z = pd.DataFrame({
        f: [s.factor_z.get(f, np.nan) for s in samples]
        for f in factors
    }).dropna()
    vif = pd.Series(index=factors, dtype=float)
    for f in factors:
        y = Z[f].values
        X = Z.drop(columns=[f]).values
        try:
            r2 = LinearRegression().fit(X, y).score(X, y)
            vif[f] = 1.0 / max(1e-9, 1.0 - r2)
        except Exception:
            vif[f] = float("nan")
    return vif
```

- [ ] **Step 2: Test**

```python
def test_compute_effective_df_monotone_in_lambda():
    np.random.seed(42)
    X = np.random.randn(100, 50)
    df_small = compute_effective_df(X, 0.01)
    df_large = compute_effective_df(X, 100.0)
    assert df_small > df_large
    assert df_large < 5  # heavy shrinkage
```

- [ ] **Step 3: Commit**

```bash
git commit -am "feat(tier2): compute_effective_df + compute_vif_matrix"
```

---

## Task 10: F11 staggered protocol

- [ ] **Step 1: Implement `staggered_calibration` in factor_calibration_hierarchical.py**

```python
from datetime import date


def staggered_calibration(
    train_pre_2010: list[HistoricalSample],
    train_2010_plus: list[HistoricalSample],
    prior_beta: dict[tuple[str, str], float] | None = None,
    lambda_global: float = 2.0,
    lambda_family: float = 0.5,
    lambda_f11_multiplier: float = 2.0,
) -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], float]]:
    """Two-stage staggered calibration for F11 (short-history factor).

    Phase A: Main fit on 1991-2024 with F11 column held at INITIAL_BETA prior.
    Phase B: Sub-fit F11 column only on 2010+ window with strong shrinkage.
    """
    prior = prior_beta or INITIAL_BETA
    
    # Phase A: full train, but force F11 column to prior
    f11_keys = frozenset((f, b) for f, b in prior if f == "F11_earnings_revision")
    # Effectively add F11 cells to HARD_ZERO_CELLS for Phase A → use modified hard-zero set
    # Or alternative: use 1e6 penalty on (β_F11 - prior_F11)
    
    train_all = train_pre_2010 + train_2010_plus
    beta_main, mu_main, _ = hybrid_calibration_hierarchical(
        train_all,
        prior_beta=prior,
        lambda_global=lambda_global,
        lambda_family=lambda_family,
    )
    # Force F11 column back to prior (Phase A treats it as fixed)
    for k in f11_keys:
        if k not in HARD_ZERO_CELLS:
            beta_main[k] = prior[k]
    
    # Phase B: F11 column sub-fit
    lambda_f11 = max(lambda_f11_multiplier * lambda_global, 5.0)
    f11_free_keys = [k for k in f11_keys if k not in HARD_ZERO_CELLS]
    
    def _f11_objective(x: np.ndarray) -> float:
        beta_combined = dict(beta_main)
        for i, k in enumerate(f11_free_keys):
            beta_combined[k] = float(x[i])
        returns = simulate_portfolio_returns_per_factor_aware(train_2010_plus, beta_combined)
        sharpe = compute_sharpe(returns)
        # Strong shrinkage to prior
        pen = lambda_f11 * sum(
            (beta_combined[k] - prior[k])**2 for k in f11_free_keys
        )
        return -sharpe + pen
    
    x0_f11 = np.array([prior[k] for k in f11_free_keys])
    bounds_f11 = [(-0.10, 0.10)] * len(f11_free_keys)  # tighter for F11
    result = minimize(_f11_objective, x0_f11, method="L-BFGS-B", bounds=bounds_f11)
    
    for i, k in enumerate(f11_free_keys):
        beta_main[k] = float(result.x[i])
    return beta_main, mu_main
```

- [ ] **Step 2: Test + commit**

```bash
git commit -am "feat(tier2): staggered_calibration (Phase A 1991+ / Phase B F11 2010+)"
```

---

## Task 11: TIPS scalar regression

**Files:**
- Create: `tradingagents/skills/research/factor_calibration_tips.py`
- Create: `tests/unit/skills/research/test_factor_calibration_tips.py`

- [ ] **Step 1: Test**

```python
def test_tips_calibration_clamps_hard_zeros():
    from tradingagents.skills.research.factor_calibration_tips import hybrid_calibration_tips
    # Build minimal HistoricalSample with tips_share_realized
    # Verify F11/F12 entries in calibrated_tips_beta = 0
    pass  # implement
```

- [ ] **Step 2: Implement**

```python
"""TIPS share scalar regression (Tier 2).

Smaller-dimensional regression for INITIAL_TIPS_BETA (12 entries).
Hierarchical/family X (single output). Hard zero: F11/F12 × TIPS.
"""
from __future__ import annotations
from typing import Final
import numpy as np
from scipy.optimize import minimize

from tradingagents.skills.research.factor_calibration import HistoricalSample
from tradingagents.skills.research.factor_to_bucket import (
    FACTORS, INITIAL_TIPS_BASELINE, INITIAL_TIPS_BETA,
)

HARD_ZERO_TIPS: Final[frozenset[str]] = frozenset({
    "F11_earnings_revision",
    "F12_china_credit_impulse",
})


def hybrid_calibration_tips(
    train: list[HistoricalSample],
    prior_tips_beta: dict[str, float] | None = None,
    lambda_global: float = 2.0,
    max_iter: int = 50,
) -> tuple[dict[str, float], float]:
    """Returns (calibrated_tips_beta, in_sample_mse).

    Predicts tips share within bond bucket from factor z-scores.
    Sample/param ratio: 133 / 10 = 13.3 (acceptable).
    """
    prior = prior_tips_beta or INITIAL_TIPS_BETA
    free_keys = sorted(set(prior.keys()) - HARD_ZERO_TIPS)
    
    def _unpack(x: np.ndarray) -> dict[str, float]:
        return {
            **{k: float(x[i]) for i, k in enumerate(free_keys)},
            **{k: 0.0 for k in HARD_ZERO_TIPS},
        }
    
    def objective(x: np.ndarray) -> float:
        beta = _unpack(x)
        # MSE between predicted tips_share and realized
        pred, real = [], []
        for s in train:
            tips_realized = getattr(s, "tips_share_realized", None)
            if tips_realized is None:
                continue
            share = INITIAL_TIPS_BASELINE
            for f, b in beta.items():
                z = s.factor_z.get(f)
                if z is not None and not (isinstance(z, float) and np.isnan(z)):
                    share += b * z
            share = max(0.0, min(1.0, share))
            pred.append(share)
            real.append(tips_realized)
        if not pred:
            return 1e6
        mse = float(np.mean((np.array(pred) - np.array(real))**2))
        prior_pen = lambda_global * sum(
            (x[i] - prior[k])**2 for i, k in enumerate(free_keys)
        )
        return mse + prior_pen
    
    x0 = np.array([prior[k] for k in free_keys])
    bounds = [(-0.30, 0.30)] * len(free_keys)
    result = minimize(objective, x0, method="L-BFGS-B", bounds=bounds,
                      options={"maxiter": max_iter})
    final = _unpack(result.x)
    return final, float(result.fun)
```

- [ ] **Step 3: Test + commit**

```bash
pytest tests/unit/skills/research/test_factor_calibration_tips.py -v
git add tradingagents/skills/research/factor_calibration_tips.py tests/unit/skills/research/test_factor_calibration_tips.py
git commit -m "feat(tier2): TIPS scalar regression (12 entries, F11/F12 hard zero)"
```

---

## Task 12: Calibration entry script

**Files:**
- Create: `scripts/calibrate_factor_model_8b.py`

- [ ] **Step 1: Implement**

```python
"""Tier 2 calibration entry: 8-bucket × 12-factor hierarchical fit.

Run:
  python scripts/calibrate_factor_model_8b.py --grid

Outputs:
  artifacts/<DATE>/tier2_calibration/
    - calibrated_beta.json
    - calibrated_mu.json
    - calibrated_tips_beta.json
    - shrinkage_grid_summary.json
    - validation_report.md
"""
import argparse, json, logging
from datetime import date
from pathlib import Path
import numpy as np
import pandas as pd

from tradingagents.skills.research.factor_calibration import (
    HARD_ZERO_CELLS, BUCKET_FAMILIES, HistoricalSample,
    compute_effective_df, compute_vif_matrix, walk_forward, aggregate_median_beta,
)
from tradingagents.skills.research.factor_calibration_hierarchical import (
    hybrid_calibration_hierarchical, staggered_calibration,
)
from tradingagents.skills.research.factor_calibration_tips import (
    hybrid_calibration_tips,
)
from tradingagents.skills.research.factor_to_bucket import (
    FACTORS, BUCKETS, INITIAL_BETA, INITIAL_TIPS_BETA,
)


def load_samples_8b(samples_parquet: Path = Path("backtest/historical/samples_8b.parquet")) -> list[HistoricalSample]:
    """Load 8-bucket samples. samples_8b is generated by extending samples.parquet
    with bucket_returns_8b.parquet."""
    df = pd.read_parquet(samples_parquet)
    return [
        HistoricalSample(
            date=str(row.name),
            factor_z={f: row[f] if f in df.columns else float("nan") for f in FACTORS},
            bucket_returns_next={b: row[f"ret_next_{b}"] for b in BUCKETS if f"ret_next_{b}" in df.columns},
        )
        for _, row in df.iterrows()
    ]


def grid_search_shrinkage(samples, prior_beta):
    lambda_global_grid = [0.5, 1.0, 2.0, 3.0, 5.0, 10.0]
    lambda_family_grid = [0.1, 0.3, 1.0]
    results = []
    for lg in lambda_global_grid:
        for lf in lambda_family_grid:
            folds = walk_forward(samples, initial_train_size=80, test_window=8,
                                  shrinkage=lg, prior_beta=prior_beta)
            median_oos = float(np.median([f.oos_sharpe for f in folds])) if folds else float("nan")
            results.append({
                "lambda_global": lg, "lambda_family": lf,
                "median_oos_sharpe": median_oos,
                "n_folds": len(folds),
            })
    return pd.DataFrame(results)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--grid", action="store_true", help="Run shrinkage grid")
    parser.add_argument("--out-dir", type=str, default=None)
    args = parser.parse_args()
    out_dir = Path(args.out_dir or f"artifacts/{date.today().isoformat()}/tier2_calibration")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    samples = load_samples_8b()
    if args.grid:
        grid = grid_search_shrinkage(samples, INITIAL_BETA)
        grid.to_json(out_dir / "shrinkage_grid_summary.json", orient="records", indent=2)
        best = grid.loc[grid["median_oos_sharpe"].idxmax()]
        lg, lf = float(best["lambda_global"]), float(best["lambda_family"])
    else:
        lg, lf = 2.0, 0.5  # spec default

    # Phase A + B staggered
    pre_2010 = [s for s in samples if s.date < "2010-01-01"]
    post_2010 = [s for s in samples if s.date >= "2010-01-01"]
    beta, mu = staggered_calibration(pre_2010, post_2010, lambda_global=lg, lambda_family=lf)
    
    # TIPS
    tips_beta, tips_mse = hybrid_calibration_tips(samples, lambda_global=lg)
    
    # Save
    with open(out_dir / "calibrated_beta.json", "w") as f:
        json.dump({f"{k[0]}|{k[1]}": v for k, v in beta.items()}, f, indent=2)
    with open(out_dir / "calibrated_mu.json", "w") as f:
        json.dump({f"{k[0]}|{k[1]}": v for k, v in mu.items()}, f, indent=2)
    with open(out_dir / "calibrated_tips_beta.json", "w") as f:
        json.dump(tips_beta, f, indent=2)
    
    print(f"✅ Calibration complete. Output: {out_dir}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
```

- [ ] **Step 2: Run**

```bash
python scripts/calibrate_factor_model_8b.py --grid 2>&1 | tail -20
```

- [ ] **Step 3: Commit**

```bash
git add scripts/calibrate_factor_model_8b.py artifacts/$(date +%Y-%m-%d)/tier2_calibration/
git commit -m "feat(tier2): calibrate_factor_model_8b — grid search + staggered + TIPS"
```

---

## Task 13: Validation script (VIF + df + OOS Sharpe)

**Files:**
- Create: `scripts/validate_factor_model_8b.py`

- [ ] **Step 1: Implement**

```python
"""Tier 2 validation: VIF check + effective df + walk-forward OOS Sharpe.

Acceptance:
- VIF ≤ 5 for spurious pairs (multicollinearity 결함 fix verification)
- Effective df ≤ 44 (Gelman N/3, N=133)
- Walk-forward OOS Sharpe > 1.171 (PR2a baseline)
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd

from tradingagents.skills.research.factor_calibration import (
    compute_effective_df, compute_vif_matrix, walk_forward,
)
from tradingagents.skills.research.factor_to_bucket import FACTORS


def validate(samples, beta, lambda_global, out_dir: Path):
    # VIF
    vif = compute_vif_matrix(samples, list(FACTORS))
    spurious_pairs = [
        ("F1_growth", "F10_systemic_liquidity"),  # NFCI dup (Tier 0 fixed)
        ("F1_growth", "F4_term_premium"),         # curve dup (Tier 0 fixed)
    ]
    vif_max = float(vif.max())
    vif_pass = vif_max <= 5.0
    
    # Design matrix for df
    X = np.array([
        [s.factor_z.get(f, 0.0) for f in FACTORS]
        for s in samples
    ])
    df = compute_effective_df(X, lambda_global)
    n = len(samples)
    df_pass = df <= n / 3
    
    # Walk-forward OOS Sharpe
    folds = walk_forward(samples, initial_train_size=80, test_window=8,
                          shrinkage=lambda_global)
    median_oos = float(np.median([f.oos_sharpe for f in folds]))
    sharpe_pass = median_oos > 1.171
    
    report = {
        "vif_max":          vif_max,
        "vif_pass":         vif_pass,
        "effective_df":     df,
        "n_samples":        n,
        "df_threshold":     n / 3,
        "df_pass":          df_pass,
        "median_oos_sharpe":median_oos,
        "sharpe_pass":      sharpe_pass,
        "overall_pass":     vif_pass and df_pass and sharpe_pass,
    }
    (out_dir / "validation_report.json").write_text(json.dumps(report, indent=2))
    (out_dir / "validation_report.md").write_text(_format_md(report))
    return report


def _format_md(r):
    return f"""# Tier 2 Calibration Validation

| Metric | Value | Threshold | Pass |
|---|---|---|---|
| VIF max | {r['vif_max']:.2f} | ≤ 5.0 | {'✓' if r['vif_pass'] else '✗'} |
| Effective df | {r['effective_df']:.1f} | ≤ {r['df_threshold']:.1f} | {'✓' if r['df_pass'] else '✗'} |
| Median OOS Sharpe | {r['median_oos_sharpe']:.3f} | > 1.171 | {'✓' if r['sharpe_pass'] else '✗'} |

**Overall**: {'PASS' if r['overall_pass'] else 'FAIL'}
"""


if __name__ == "__main__":
    from scripts.calibrate_factor_model_8b import load_samples_8b
    out_dir = Path("artifacts/" + pd.Timestamp.today().strftime("%Y-%m-%d") + "/tier2_calibration")
    samples = load_samples_8b()
    beta_path = out_dir / "calibrated_beta.json"
    if not beta_path.exists():
        raise SystemExit("Run calibrate_factor_model_8b.py first")
    beta = json.loads(beta_path.read_text())
    report = validate(samples, beta, 2.0, out_dir)
    print(json.dumps(report, indent=2))
```

- [ ] **Step 2: Run + commit**

```bash
python scripts/validate_factor_model_8b.py 2>&1 | tail -10
git add scripts/validate_factor_model_8b.py
git commit -m "feat(tier2): validate_factor_model_8b — VIF + df + OOS Sharpe acceptance"
```

---

## Task 14: Runtime wiring (calibrated β → production)

**Files:**
- Modify: `tradingagents/skills/research/factor_to_bucket.py`

- [ ] **Step 1: Load calibrated β at module init**

```python
def _load_calibrated_beta() -> dict[tuple[str, str], float] | None:
    """Load latest calibrated β if available; else use hand-coded INITIAL_BETA."""
    import json
    from pathlib import Path
    # Find latest calibration artifact
    base = Path("artifacts")
    if not base.exists():
        return None
    candidates = sorted(base.glob("*/tier2_calibration/calibrated_beta.json"))
    if not candidates:
        return None
    latest = candidates[-1]
    raw = json.loads(latest.read_text())
    return {tuple(k.split("|")): v for k, v in raw.items()}


_CALIBRATED_BETA = _load_calibrated_beta()
if _CALIBRATED_BETA is not None:
    logger.info("Loaded calibrated β from %s", "tier2_calibration latest")
    # Override INITIAL_BETA at runtime (preserve hand-coded as fallback)
    INITIAL_BETA = _CALIBRATED_BETA  # type: ignore
```

> Alternative: hand-edit INITIAL_BETA dict in factor_to_bucket.py per spec C3 single-source.

- [ ] **Step 2: Test wiring**

```python
def test_calibrated_beta_loaded_when_available(tmp_path, monkeypatch):
    # mock artifacts dir with calibrated_beta.json
    pass  # implement
```

- [ ] **Step 3: Commit**

```bash
git commit -am "feat(tier2): runtime loads calibrated β from latest artifact (fallback INITIAL_BETA)"
```

---

## Task 15: Integration test (end-to-end Tier 2)

**Files:**
- Create: `tests/integration/test_tier2_calibration_pipeline.py`

- [ ] **Step 1: Test**

```python
def test_full_pipeline_smoke():
    """Build samples → hierarchical fit → validate → β passes acceptance."""
    pass  # implement: synthetic 100-quarter samples, run hybrid_calibration_hierarchical, assert sharpe positive
```

- [ ] **Step 2: Run + commit**

```bash
pytest tests/integration/test_tier2_calibration_pipeline.py -v
git commit -m "test(tier2): integration — synthetic 100q → hierarchical fit → validate"
```

---

## Acceptance Checklist

- [ ] 8 bucket builders implemented + parquet snapshot generated (~134 quarters × 8 cols)
- [ ] HARD_ZERO_CELLS = 28 entries (frozenset)
- [ ] BUCKET_FAMILIES = 5 family dict
- [ ] simulate_portfolio_returns_per_factor_aware skips NaN factor contribution
- [ ] hybrid_calibration_hierarchical: free β + μ joint optimization
- [ ] staggered_calibration: F11 Phase A prior-fixed + Phase B 2010+ sub-fit
- [ ] hybrid_calibration_tips: 12 entries, F11/F12 hard zero
- [ ] compute_effective_df monotone in λ
- [ ] compute_vif_matrix per-factor
- [ ] Calibration script + validation script run end-to-end
- [ ] Runtime loads calibrated β (or falls back to INITIAL_BETA)
- [ ] Walk-forward OOS Sharpe ≥ 1.171 acceptance threshold
- [ ] Effective df ≤ 44 (Gelman N/3)
- [ ] VIF max ≤ 5.0 after Tier 0 multicollinearity fixes

---

**Plan saved to `docs/superpowers/plans/2026-05-28-tier2-calibration.md`.**
