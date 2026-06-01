# Tier 0 — Factor Model Reform + Stage 1 Data Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend Stage 1 with 4 new external data fetchers + 5 FRED series + 8 schema fields, and reform factor model from 10 → 12 factors with redesigned F1/F4/F5/F6/F7/F8/F9/F10 + new F11/F12, while preserving PR2a graceful degradation pattern.

**Architecture:** Stage 1 fetches new economic indicators (ACM term premium, GZ EBP, Shiller CAPE, Caldara-Iacoviello GPR, BIS China credit) and exposes them via new pydantic snapshots. Factor estimators (`factor_estimators.py`) aggregate these into 12 z-scores with NaN-skip pattern. Expanding-window z-baseline module (`factor_baselines_dynamic.py`) replaces static (mean, sd) with time-honest rolling moments, falling back to static `LONG_RUN_BASELINE` for short-history components. News-derived components retain PR2a's historical-mode drop-and-renormalize behavior.

**Tech Stack:** Python 3.11+, pandas, pydantic v2, scipy, yfinance, pykrx, fredapi, xlrd (for Yale .xls), openpyxl (for BIS .xlsx), urllib.request (CSV scrapers), pytest.

**Spec:** [`docs/superpowers/specs/2026-05-28-tier0-factor-model-reform-design.md`](../specs/2026-05-28-tier0-factor-model-reform-design.md)

**Out of scope (other tiers):** β prior matrix numeric values (T1), β calibration (T2), LLM overlay (T3).

---

## File Structure

**Created:**
- `tradingagents/dataflows/shiller_cape.py` — Shiller CAPE Excel scraper
- `tradingagents/dataflows/gpr_index.py` — Caldara-Iacoviello GPR scraper
- `tradingagents/dataflows/gz_ebp.py` — Fed Board GZ EBP CSV scraper
- `tradingagents/dataflows/bis_credit.py` — BIS Total Credit xlsx scraper (dynamic code discovery)
- `tradingagents/skills/research/factor_baselines_dynamic.py` — expanding window z-baseline + dispatch table
- `tradingagents/skills/research/factor_reliability_empirical.py` — walk-forward posterior precision (Tier 2 dependency)
- `tradingagents/skills/research/earnings_revision.py` — F11 yfinance aggregation
- `tradingagents/skills/research/china_credit_impulse.py` — F12 Biggs-Mayer-Pick calculation
- `data/cache/factor_history/` — expanding baseline parquet cache directory
- `data/universe/sp500_constituents.json` — SP500 ticker snapshot for F11
- `tests/unit/dataflows/test_shiller_cape.py`
- `tests/unit/dataflows/test_gpr_index.py`
- `tests/unit/dataflows/test_gz_ebp.py`
- `tests/unit/dataflows/test_bis_credit.py`
- `tests/unit/skills/research/test_factor_baselines_dynamic.py`
- `tests/unit/skills/research/test_earnings_revision.py`
- `tests/unit/skills/research/test_china_credit_impulse.py`

**Modified:**
- `tradingagents/dataflows/fred.py` — add 5 FRED series + SOFR-TED stitched fetcher
- `tradingagents/schemas/macro.py` — extend FXSnapshot, add 5 new snapshots
- `tradingagents/schemas/risk.py` — add ExcessBondPremiumSnapshot
- `tradingagents/schemas/reports.py` — MacroReport new Optional fields
- `tradingagents/agents/analysts/macro_quant_analyst.py` — fill new snapshots
- `tradingagents/agents/analysts/market_risk_analyst.py` — fill ExcessBondPremium + USEquityValuation
- `tradingagents/skills/research/factor_baselines.py` — add baselines for new components
- `tradingagents/skills/research/factor_reliability_audit.py` — add reliability for new components
- `tradingagents/skills/research/factor_estimators.py` — 12-factor reform (largest change)
- `tradingagents/default_config.py` — add publication_lag_days for new series
- `tests/unit/skills/research/test_factor_estimators.py` — 12-factor test fixtures

---

## Task 0: Setup + Cache Directory

**Files:**
- Create: `data/cache/factor_history/.gitkeep`
- Create: `data/cache/external/.gitkeep`

- [ ] **Step 1: Create cache directories**

```bash
mkdir -p data/cache/factor_history data/cache/external
touch data/cache/factor_history/.gitkeep data/cache/external/.gitkeep
```

- [ ] **Step 2: Add xlrd to requirements**

Modify: `requirements.txt` or `pyproject.toml`
```
xlrd>=2.0.1     # for Shiller/Iacoviello .xls
openpyxl>=3.1.0 # for BIS .xlsx (likely already present)
```

- [ ] **Step 3: Install + verify**

```bash
pip install -r requirements.txt
python -c "import xlrd, openpyxl; print('OK')"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add data/cache/factor_history/.gitkeep data/cache/external/.gitkeep requirements.txt
git commit -m "chore(tier0): cache dirs + xlrd/openpyxl deps"
```

---

## Phase 1: New External Data Fetchers

### Task 1.1: Shiller US CAPE fetcher

**Files:**
- Create: `tradingagents/dataflows/shiller_cape.py`
- Create: `tests/unit/dataflows/test_shiller_cape.py`

- [ ] **Step 1: Write failing test**

`tests/unit/dataflows/test_shiller_cape.py`:
```python
import io, pytest
from unittest.mock import patch
from datetime import date
import pandas as pd
from tradingagents.dataflows.shiller_cape import (
    fetch_shiller_cape, _decimal_year_to_date,
)


def test_decimal_year_conversion():
    assert _decimal_year_to_date(1871.01) == pd.Timestamp(1871, 1, 1)
    assert _decimal_year_to_date(2026.04) == pd.Timestamp(2026, 4, 1)
    assert _decimal_year_to_date(2026.12) == pd.Timestamp(2026, 12, 1)


def test_fetch_shiller_cape_parses_excel(monkeypatch):
    """Mock urllib + verify CAPE column extracted, decimal year converted."""
    # Synthesize minimal Shiller-like xls content via fixture if present;
    # for unit, mock pd.read_excel directly.
    fake_df = pd.DataFrame({
        "Date": [2020.01, 2020.02, 2020.03],
        "CAPE": [30.5, 31.2, 28.7],
    })
    with patch("tradingagents.dataflows.shiller_cape.urllib.request.urlopen"), \
         patch("tradingagents.dataflows.shiller_cape.pd.read_excel", return_value=fake_df):
        result = fetch_shiller_cape(as_of=date(2020, 3, 31))
    assert len(result) == 3
    assert result.iloc[0] == 30.5
    assert isinstance(result.index[0], pd.Timestamp)
    assert result.index[0].year == 2020


def test_fetch_shiller_cape_as_of_truncates(monkeypatch):
    fake_df = pd.DataFrame({
        "Date": [2020.01, 2020.02, 2020.03],
        "CAPE": [30.5, 31.2, 28.7],
    })
    with patch("tradingagents.dataflows.shiller_cape.urllib.request.urlopen"), \
         patch("tradingagents.dataflows.shiller_cape.pd.read_excel", return_value=fake_df):
        result = fetch_shiller_cape(as_of=date(2020, 2, 15))
    assert len(result) <= 2  # Jan + Feb only
```

- [ ] **Step 2: Run test (expect FAIL — module not exist)**

```bash
pytest tests/unit/dataflows/test_shiller_cape.py -v
```
Expected: `ModuleNotFoundError: No module named 'tradingagents.dataflows.shiller_cape'`

- [ ] **Step 3: Implement module**

`tradingagents/dataflows/shiller_cape.py`:
```python
"""Shiller US CAPE (PE10) fetcher.

Source: Yale econ.yale.edu/~shiller/data/ie_data.xls (1871+).
Reference: Asness 2003 FAJ, Campbell-Shiller 1988 RFS.
"""
from __future__ import annotations

import io
import logging
import urllib.request
from datetime import date
from typing import Final

import pandas as pd

logger = logging.getLogger(__name__)

SHILLER_URL: Final[str] = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"


def _decimal_year_to_date(dy: float) -> pd.Timestamp:
    """Shiller decimal year (1871.01 = Jan 1871) → first-of-month Timestamp."""
    if pd.isna(dy):
        return pd.NaT
    year = int(dy)
    month = round((dy - year) * 100)
    month = max(1, min(12, month))
    return pd.Timestamp(year=year, month=month, day=1)


def fetch_shiller_cape(as_of: date | None = None) -> pd.Series:
    """Monthly Shiller CAPE (cyclically adjusted P/E10).

    Returns pd.Series indexed by month-start Timestamp, dtype float, name='cape'.
    Drops NaN (early years before 10y rolling enough).
    """
    req = urllib.request.Request(SHILLER_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    df = pd.read_excel(io.BytesIO(data), sheet_name="Data", skiprows=7)
    cape_col = "CAPE" if "CAPE" in df.columns else "TR CAPE"
    df["_date"] = df["Date"].apply(_decimal_year_to_date)
    df = df.dropna(subset=[cape_col, "_date"]).set_index("_date")
    s = df[cape_col].astype(float).rename("cape")
    if as_of is not None:
        s = s[s.index <= pd.Timestamp(as_of)]
    return s


__all__ = ["fetch_shiller_cape", "_decimal_year_to_date", "SHILLER_URL"]
```

- [ ] **Step 4: Run test (expect PASS)**

```bash
pytest tests/unit/dataflows/test_shiller_cape.py -v
```
Expected: 3 passed

- [ ] **Step 5: Live network integration smoke test**

Add to test file:
```python
@pytest.mark.network
def test_fetch_shiller_cape_live():
    """Hits actual Yale URL — gated by @pytest.mark.network."""
    s = fetch_shiller_cape(as_of=date(2025, 1, 1))
    assert len(s) > 100
    assert s.index[0].year == 1881  # CAPE valid from 1881 (after 10y rolling)
    assert all(s > 0)
```
Run: `pytest tests/unit/dataflows/test_shiller_cape.py -v -m network` (manually, when online)

- [ ] **Step 6: Commit**

```bash
git add tradingagents/dataflows/shiller_cape.py tests/unit/dataflows/test_shiller_cape.py
git commit -m "feat(tier0): Shiller CAPE fetcher (Yale ie_data.xls)"
```

---

### Task 1.2: Caldara-Iacoviello GPR fetcher

**Files:**
- Create: `tradingagents/dataflows/gpr_index.py`
- Create: `tests/unit/dataflows/test_gpr_index.py`

- [ ] **Step 1: Write failing test**

`tests/unit/dataflows/test_gpr_index.py`:
```python
import pytest
from unittest.mock import patch
from datetime import date
import pandas as pd
from tradingagents.dataflows.gpr_index import fetch_gpr_index


def test_fetch_gpr_monthly(monkeypatch):
    fake_df = pd.DataFrame({
        "month": pd.to_datetime(["2020-01-01", "2020-02-01"]),
        "GPR": [85.0, 92.5],
        "GPRC_KOR": [40.0, 45.0],
    })
    with patch("tradingagents.dataflows.gpr_index.urllib.request.urlopen"), \
         patch("tradingagents.dataflows.gpr_index.pd.read_excel", return_value=fake_df):
        s = fetch_gpr_index(frequency="monthly", series="GPR",
                            as_of=date(2020, 2, 28))
    assert len(s) == 2
    assert s.iloc[0] == 85.0
    assert s.name == "gpr"


def test_fetch_gpr_country_specific_kor(monkeypatch):
    fake_df = pd.DataFrame({
        "month": pd.to_datetime(["2020-01-01"]),
        "GPR": [85.0],
        "GPRC_KOR": [40.0],
    })
    with patch("tradingagents.dataflows.gpr_index.urllib.request.urlopen"), \
         patch("tradingagents.dataflows.gpr_index.pd.read_excel", return_value=fake_df):
        s = fetch_gpr_index(series="GPRC_KOR")
    assert s.iloc[0] == 40.0


def test_fetch_gpr_unknown_series_fallback(monkeypatch):
    """Unknown series name falls back to default 'GPR'."""
    fake_df = pd.DataFrame({
        "month": pd.to_datetime(["2020-01-01"]),
        "GPR": [85.0],
    })
    with patch("tradingagents.dataflows.gpr_index.urllib.request.urlopen"), \
         patch("tradingagents.dataflows.gpr_index.pd.read_excel", return_value=fake_df):
        s = fetch_gpr_index(series="GPR_NONEXISTENT")
    assert s.iloc[0] == 85.0  # falls back to GPR
```

- [ ] **Step 2: Run test (expect FAIL)**

```bash
pytest tests/unit/dataflows/test_gpr_index.py -v
```
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement module**

`tradingagents/dataflows/gpr_index.py`:
```python
"""Caldara-Iacoviello Geopolitical Risk Index fetcher.

Reference: Caldara-Iacoviello 2022 AER "Measuring Geopolitical Risk".
Source: matteoiacoviello.com/gpr_files/ (Excel, monthly 1900+ / daily 1985+).
"""
from __future__ import annotations

import io
import logging
import urllib.request
from datetime import date
from typing import Final

import pandas as pd

logger = logging.getLogger(__name__)

GPR_MONTHLY_URL: Final[str] = (
    "https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls"
)
GPR_DAILY_URL: Final[str] = (
    "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls"
)


def fetch_gpr_index(
    frequency: str = "monthly",
    series: str = "GPR",
    as_of: date | None = None,
) -> pd.Series:
    """Caldara-Iacoviello GPR Index, monthly or daily.

    frequency: 'monthly' (GPR 1900+) | 'daily' (GPRD 1985+)
    series: 'GPR' (global), 'GPRC_KOR'/'GPRC_CHN'/etc. (country-specific).
            Falls back to default if not found in columns.
    """
    if frequency == "monthly":
        url, date_col, default_series = GPR_MONTHLY_URL, "month", "GPR"
    else:
        url, date_col, default_series = GPR_DAILY_URL, "date", "GPRD"

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    df = pd.read_excel(io.BytesIO(data), sheet_name="Sheet1")
    df["_date"] = pd.to_datetime(df[date_col])
    df = df.set_index("_date")

    target_series = series if series in df.columns else default_series
    if target_series not in df.columns:
        raise ValueError(f"GPR series {target_series!r} not in columns {list(df.columns)[:10]}...")

    s = df[target_series].astype(float).rename(target_series.lower())
    if as_of is not None:
        s = s[s.index <= pd.Timestamp(as_of)]
    return s.dropna()


__all__ = ["fetch_gpr_index", "GPR_MONTHLY_URL", "GPR_DAILY_URL"]
```

- [ ] **Step 4: Run test (expect PASS)**

```bash
pytest tests/unit/dataflows/test_gpr_index.py -v
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/gpr_index.py tests/unit/dataflows/test_gpr_index.py
git commit -m "feat(tier0): Caldara-Iacoviello GPR Index fetcher"
```

---

### Task 1.3: Fed Board GZ EBP fetcher

**Files:**
- Create: `tradingagents/dataflows/gz_ebp.py`
- Create: `tests/unit/dataflows/test_gz_ebp.py`

- [ ] **Step 1: Write failing test**

`tests/unit/dataflows/test_gz_ebp.py`:
```python
import pytest
from unittest.mock import patch
from datetime import date
from io import StringIO
import pandas as pd
from tradingagents.dataflows.gz_ebp import fetch_gz_ebp


def test_fetch_gz_ebp_parses_csv(monkeypatch):
    csv_content = (
        "date,gz_spread,ebp,est_prob\n"
        "2020-01-01,1.5,-0.04,0.18\n"
        "2020-02-01,2.1,0.45,0.32\n"
        "2020-03-01,5.5,3.20,0.85\n"
    )
    with patch("tradingagents.dataflows.gz_ebp.pd.read_csv",
               return_value=pd.read_csv(StringIO(csv_content), parse_dates=["date"])):
        s = fetch_gz_ebp(as_of=date(2020, 3, 31))
    assert len(s) == 3
    assert s.iloc[2] == 3.20
    assert s.name == "ebp"


def test_fetch_gz_ebp_as_of(monkeypatch):
    csv_content = (
        "date,gz_spread,ebp,est_prob\n"
        "2020-01-01,1.5,-0.04,0.18\n"
        "2020-02-01,2.1,0.45,0.32\n"
    )
    with patch("tradingagents.dataflows.gz_ebp.pd.read_csv",
               return_value=pd.read_csv(StringIO(csv_content), parse_dates=["date"])):
        s = fetch_gz_ebp(as_of=date(2020, 1, 15))
    assert len(s) == 1
```

- [ ] **Step 2: Run test (expect FAIL)**

```bash
pytest tests/unit/dataflows/test_gz_ebp.py -v
```

- [ ] **Step 3: Implement**

`tradingagents/dataflows/gz_ebp.py`:
```python
"""Gilchrist-Zakrajsek Excess Bond Premium fetcher.

Reference: Gilchrist-Zakrajsek 2012 AER "Credit Spreads and Business Cycle".
Source: federalreserve.gov/econres/notes/feds-notes/ebp_csv.csv (monthly 1973+).
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Final

import pandas as pd

logger = logging.getLogger(__name__)

FED_EBP_URL: Final[str] = (
    "https://www.federalreserve.gov/econres/notes/feds-notes/ebp_csv.csv"
)


def fetch_gz_ebp(as_of: date | None = None) -> pd.Series:
    """Monthly Excess Bond Premium (Federal Reserve Board).

    Returns pd.Series indexed by month-start, dtype float, name='ebp'.
    """
    df = pd.read_csv(FED_EBP_URL, parse_dates=["date"])
    df = df.set_index("date")
    s = df["ebp"].astype(float).rename("ebp")
    if as_of is not None:
        s = s[s.index <= pd.Timestamp(as_of)]
    return s.dropna()


__all__ = ["fetch_gz_ebp", "FED_EBP_URL"]
```

- [ ] **Step 4: Run test (expect PASS)**

```bash
pytest tests/unit/dataflows/test_gz_ebp.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/gz_ebp.py tests/unit/dataflows/test_gz_ebp.py
git commit -m "feat(tier0): Fed Board GZ EBP fetcher"
```

---

### Task 1.4: BIS China Total Credit fetcher (dynamic discovery)

**Files:**
- Create: `tradingagents/dataflows/bis_credit.py`
- Create: `tests/unit/dataflows/test_bis_credit.py`

- [ ] **Step 1: Write failing test**

`tests/unit/dataflows/test_bis_credit.py`:
```python
import pytest
from unittest.mock import patch
from datetime import date
import pandas as pd
from tradingagents.dataflows.bis_credit import (
    fetch_bis_china_credit, _find_bis_code_position,
    BIS_CN_CREDIT_CODE,
)


def test_find_bis_code_position_locates_code():
    df = pd.DataFrame({
        0: ["", "", "", "Q:CN:P:A:M:770:A", ""],
        1: ["", "", "", "OtherCode", ""],
    })
    row, col = _find_bis_code_position(df, "Q:CN:P:A:M:770:A")
    assert row == 3
    assert col == 0


def test_find_bis_code_not_found():
    df = pd.DataFrame({0: ["", "", "Code1"]})
    row, col = _find_bis_code_position(df, "NotPresent")
    assert row is None and col is None


def test_fetch_bis_china_credit_raises_on_missing_code(monkeypatch):
    fake_header_df = pd.DataFrame({0: ["title", "other_code", "more"]})
    with patch("tradingagents.dataflows.bis_credit.urllib.request.urlopen"), \
         patch("tradingagents.dataflows.bis_credit.pd.read_excel",
               return_value=fake_header_df):
        with pytest.raises(ValueError, match="not found"):
            fetch_bis_china_credit()


def test_bis_constant_matches_spec():
    assert BIS_CN_CREDIT_CODE == "Q:CN:P:A:M:770:A"
```

- [ ] **Step 2: Run test (expect FAIL)**

```bash
pytest tests/unit/dataflows/test_bis_credit.py -v
```

- [ ] **Step 3: Implement**

`tradingagents/dataflows/bis_credit.py`:
```python
"""BIS Total Credit to Non-Financial Sector fetcher (China-focused).

Reference: BIS Total Credit Statistics (BIS_TC2), Biggs-Mayer-Pick 2010 JMCB.
Source: bis.org/statistics/totcredit/totcredit.xlsx (Quarterly Series sheet).

Vintage-aware: column position of code 'Q:CN:P:A:M:770:A' varies between BIS
xlsx vintages → dynamic discovery via _find_bis_code_position.
"""
from __future__ import annotations

import io
import logging
import urllib.request
from datetime import date
from typing import Final

import pandas as pd

logger = logging.getLogger(__name__)

BIS_TOTCREDIT_URL: Final[str] = (
    "https://www.bis.org/statistics/totcredit/totcredit.xlsx"
)
# Target: Quarterly, China, Private non-fin, All sectors lending,
# Market value, Percent of GDP (770), Adjusted for breaks (A).
BIS_CN_CREDIT_CODE: Final[str] = "Q:CN:P:A:M:770:A"


def _find_bis_code_position(
    header_df: pd.DataFrame, code: str, max_rows: int = 15,
) -> tuple[int | None, int | None]:
    """Search first max_rows for the BIS series code, return (row_idx, col_idx)."""
    for i in range(min(max_rows, len(header_df))):
        row_str = header_df.iloc[i].astype(str)
        matches = row_str[row_str == code]
        if len(matches) > 0:
            return i, matches.index[0]
    return None, None


def fetch_bis_china_credit(as_of: date | None = None) -> pd.Series:
    """BIS Quarterly: China Private Non-Financial Credit / GDP (%).

    Used by F12 china_credit_impulse (Biggs-Mayer-Pick 2010).
    Returns pd.Series indexed by quarter_end, dtype float, name='cn_credit_gdp_pct'.

    Vintage-aware: dynamically finds column for code 'Q:CN:P:A:M:770:A'.
    Raises ValueError if code not found (vintage schema may have changed).
    """
    req = urllib.request.Request(BIS_TOTCREDIT_URL,
                                  headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()

    header_df = pd.read_excel(
        io.BytesIO(data), sheet_name="Quarterly Series",
        header=None, nrows=15,
    )
    code_row, code_col = _find_bis_code_position(header_df, BIS_CN_CREDIT_CODE)
    if code_row is None:
        raise ValueError(
            f"BIS code {BIS_CN_CREDIT_CODE} not found in xlsx — "
            f"vintage schema changed, update BIS_CN_CREDIT_CODE or discovery logic"
        )

    df = pd.read_excel(
        io.BytesIO(data), sheet_name="Quarterly Series",
        skiprows=code_row + 1, usecols=[0, code_col],
        header=None, names=["date", "cn_credit_gdp_pct"],
    )
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna().set_index("date")
    s = df["cn_credit_gdp_pct"].astype(float)
    if as_of is not None:
        s = s[s.index <= pd.Timestamp(as_of)]
    return s


__all__ = [
    "fetch_bis_china_credit",
    "_find_bis_code_position",
    "BIS_TOTCREDIT_URL",
    "BIS_CN_CREDIT_CODE",
]
```

- [ ] **Step 4: Run test (expect PASS)**

```bash
pytest tests/unit/dataflows/test_bis_credit.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/bis_credit.py tests/unit/dataflows/test_bis_credit.py
git commit -m "feat(tier0): BIS Total Credit fetcher with vintage-aware code discovery"
```

---

## Phase 2: FRED Extensions

### Task 2.1: Add 5 new FRED series

**Files:**
- Modify: `tradingagents/dataflows/fred.py` (FRED_SERIES dict)
- Modify: `tradingagents/default_config.py` (publication_lag_days)

- [ ] **Step 1: Write failing test (regression — new series present)**

Add to `tests/unit/dataflows/test_fred.py` (create if absent):
```python
import pytest
from tradingagents.dataflows.fred import FRED_SERIES

NEW_TIER0_SERIES = {
    "us_indpro": "INDPRO",
    "us_real_pce": "PCECC96",  # Real PCE chained 2017 dollars (1947+)
    "us_acm_term_premium_10y": "THREEFYTP10",
    "kr_reer": "RBKRBIS",
    "ted_spread": "TEDRATE",
}

@pytest.mark.parametrize("key,series_id", NEW_TIER0_SERIES.items())
def test_tier0_fred_series_registered(key, series_id):
    assert key in FRED_SERIES
    assert FRED_SERIES[key] == series_id
```

- [ ] **Step 2: Run test (expect FAIL — keys missing)**

```bash
pytest tests/unit/dataflows/test_fred.py::test_tier0_fred_series_registered -v
```

- [ ] **Step 3: Add to FRED_SERIES dict**

In `tradingagents/dataflows/fred.py`, add at end of FRED_SERIES dict (before closing `}`):
```python
    # === Tier 0 additions (2026-05-28) ===
    # F1 reform — INDPRO + Real PCE replace nfci/curve removal
    "us_indpro": "INDPRO",                # Industrial Production Index (1919+)
    "us_real_pce": "PCECC96",             # Real PCE Chained 2017 Dollars (1947+, quarterly)
    # F4 reform — ACM term premium decomposition
    "us_acm_term_premium_10y": "THREEFYTP10",  # NY Fed 10y ACM (1990+, daily)
    # F6 reform — BIS REER (Engel-West random walk fix companion)
    "kr_reer": "RBKRBIS",                 # BIS Real Effective Exchange Rate KR (1994+, monthly)
    # F10 SOFR-TED stitching (pre-2018 proxy)
    "ted_spread": "TEDRATE",              # TED Spread (1986-2022, discontinued)
```

- [ ] **Step 4: Add publication lag**

In `tradingagents/default_config.py`, add to `publication_lag_days` dict:
```python
    "us_indpro": 17,                # IP released ~17th of month for prior month
    "us_real_pce": 30,              # BEA quarterly + 1 month lag
    "us_acm_term_premium_10y": 5,   # NY Fed weekly update
    "kr_reer": 17,                  # BIS monthly
    "ted_spread": 1,                # daily
```

- [ ] **Step 5: Run test (expect PASS)**

```bash
pytest tests/unit/dataflows/test_fred.py::test_tier0_fred_series_registered -v
```

- [ ] **Step 6: Commit**

```bash
git add tradingagents/dataflows/fred.py tradingagents/default_config.py tests/unit/dataflows/test_fred.py
git commit -m "feat(tier0): FRED — INDPRO, PCECC96, THREEFYTP10, RBKRBIS, TEDRATE"
```

---

### Task 2.2: SOFR-TED stitched fetcher

**Files:**
- Modify: `tradingagents/dataflows/fred.py` (add function)
- Modify: `tests/unit/dataflows/test_fred.py`

- [ ] **Step 1: Write failing test**

Add to `tests/unit/dataflows/test_fred.py`:
```python
from datetime import date
from unittest.mock import patch
import pandas as pd
from tradingagents.dataflows.fred import fetch_funding_stress_stitched


def test_stitch_uses_ted_pre_2018(monkeypatch):
    ted = pd.Series(
        [25.0, 30.0, 28.0],
        index=pd.to_datetime(["2010-01-01", "2010-02-01", "2010-03-01"]),
    )
    def mock_fred(key, *args, **kwargs):
        if key == "ted_spread":
            return ted
        return pd.Series(dtype=float)
    with patch("tradingagents.dataflows.fred.fetch_fred_series", side_effect=mock_fred):
        s = fetch_funding_stress_stitched(date(2010, 1, 1), date(2010, 3, 31))
    assert len(s) == 3
    assert s.iloc[0] == 25.0


def test_stitch_uses_sofr_post_2018(monkeypatch):
    sofr = pd.Series([2.0, 2.1], index=pd.to_datetime(["2020-01-01", "2020-02-01"]))
    tbill = pd.Series([1.9, 1.95], index=pd.to_datetime(["2020-01-01", "2020-02-01"]))
    def mock_fred(key, *args, **kwargs):
        if key == "us_sofr":
            return sofr
        if key == "us_3m_tbill":
            return tbill
        return pd.Series(dtype=float)
    with patch("tradingagents.dataflows.fred.fetch_fred_series", side_effect=mock_fred):
        s = fetch_funding_stress_stitched(date(2020, 1, 1), date(2020, 2, 28))
    assert len(s) == 2
    # (SOFR - tbill) * 100 = (2.0-1.9)*100 = 10 bps
    assert abs(s.iloc[0] - 10.0) < 0.01


def test_stitch_overlap_period_excludes_ted_after_2018_04_03(monkeypatch):
    ted = pd.Series(
        [25.0, 26.0, 27.0],
        index=pd.to_datetime(["2018-03-01", "2018-04-01", "2018-04-15"]),
    )
    sofr = pd.Series([2.0], index=pd.to_datetime(["2018-04-15"]))
    tbill = pd.Series([1.9], index=pd.to_datetime(["2018-04-15"]))
    def mock_fred(key, *args, **kwargs):
        if key == "ted_spread":
            return ted
        if key == "us_sofr":
            return sofr
        if key == "us_3m_tbill":
            return tbill
        return pd.Series(dtype=float)
    with patch("tradingagents.dataflows.fred.fetch_fred_series", side_effect=mock_fred):
        s = fetch_funding_stress_stitched(date(2018, 3, 1), date(2018, 4, 30))
    # TED 2018-03-01 (kept), 2018-04-01 (before boundary), 2018-04-15 should be SOFR
    assert pd.Timestamp("2018-03-01") in s.index
    # 2018-04-15 should be from SOFR, not TED
    assert s.loc[pd.Timestamp("2018-04-15")] == 10.0  # SOFR-Tbill
```

- [ ] **Step 2: Run test (expect FAIL — function not exist)**

```bash
pytest tests/unit/dataflows/test_fred.py::test_stitch_uses_ted_pre_2018 -v
```

- [ ] **Step 3: Implement function**

Add to `tradingagents/dataflows/fred.py` after `fetch_fred_series`:
```python
from datetime import date


def fetch_funding_stress_stitched(
    start: date, end: date, as_of_date: date | None = None,
) -> pd.Series:
    """SOFR-Tbill (2018+) + TED (1986-2018-04-03) stitched series, in bps.

    F10 systemic_liquidity's sofr_tbill_spread component.
    Stitch boundary: 2018-04-03 (SOFR introduction, hard switch).
    Overlap (2018-04 ~ 2022-01) uses SOFR-Tbill (TED discontinued 2022).

    Note: regime-aware z-baseline handled separately in
    factor_baselines_dynamic.compute_expanding_baseline_funding_stress.
    """
    boundary = date(2018, 4, 3)
    pieces: list[pd.Series] = []

    if start < boundary:
        ted_end = min(end, date(2018, 4, 2))
        ted = fetch_fred_series("ted_spread", start, ted_end, as_of_date=as_of_date)
        # Defensive: remove anything at/after boundary
        if not ted.empty:
            ted = ted[ted.index < pd.Timestamp(boundary)]
        pieces.append(ted)

    if end >= boundary:
        sofr_start = max(start, boundary)
        sofr = fetch_fred_series("us_sofr", sofr_start, end, as_of_date=as_of_date)
        tbill = fetch_fred_series("us_3m_tbill", sofr_start, end, as_of_date=as_of_date)
        # Align indexes (both daily). Convert percent → bps.
        common = sofr.index.intersection(tbill.index)
        sofr_tbill = (sofr.loc[common] - tbill.loc[common]) * 100
        pieces.append(sofr_tbill)

    if not pieces:
        return pd.Series(dtype=float, name="funding_stress_bps")
    result = pd.concat(pieces).sort_index()
    result.name = "funding_stress_bps"
    return result
```

Add `fetch_funding_stress_stitched` to module `__all__` if present.

- [ ] **Step 4: Run test (expect PASS)**

```bash
pytest tests/unit/dataflows/test_fred.py::test_stitch_uses_ted_pre_2018 tests/unit/dataflows/test_fred.py::test_stitch_uses_sofr_post_2018 tests/unit/dataflows/test_fred.py::test_stitch_overlap_period_excludes_ted_after_2018_04_03 -v
```

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/fred.py tests/unit/dataflows/test_fred.py
git commit -m "feat(tier0): SOFR-TED stitched funding stress (F10 pre-2018 proxy)"
```

---

## Phase 3: Schema Extensions

### Task 3.1: FXSnapshot extensions (krw_change_6m, krw_reer)

**Files:**
- Modify: `tradingagents/schemas/macro.py` (FXSnapshot class)
- Create: `tests/unit/schemas/test_macro_tier0.py`

- [ ] **Step 1: Write failing test**

`tests/unit/schemas/test_macro_tier0.py`:
```python
import pytest
from datetime import date
from tradingagents.schemas.macro import FXSnapshot


def test_fxsnapshot_has_tier0_fields():
    snap = FXSnapshot(
        as_of=date(2026, 5, 28), staleness_days=0,
        usd_krw=1350.0, dxy=104.5,
        krw_change_1m_pct=1.2, dxy_change_1m_pct=-0.5,
        regime="krw_weak",
        krw_change_6m_pct=3.5,
        krw_reer=98.5,
    )
    assert snap.krw_change_6m_pct == 3.5
    assert snap.krw_reer == 98.5


def test_fxsnapshot_krw_reer_defaults_to_none():
    snap = FXSnapshot(
        as_of=date(2026, 5, 28), staleness_days=0,
        usd_krw=1350.0, dxy=104.5,
        krw_change_1m_pct=1.2, dxy_change_1m_pct=-0.5,
        regime="krw_weak",
    )
    assert snap.krw_change_6m_pct == 0.0
    assert snap.krw_reer is None
```

- [ ] **Step 2: Run test (expect FAIL)**

```bash
pytest tests/unit/schemas/test_macro_tier0.py::test_fxsnapshot_has_tier0_fields -v
```

- [ ] **Step 3: Add fields to FXSnapshot**

In `tradingagents/schemas/macro.py`, modify `class FXSnapshot`:
```python
class FXSnapshot(StalenessAware):
    """USD/KRW + DXY. KRW 약세 + DXY 강세 동시 발생 = 외국인 매도 압력."""
    usd_krw: float = Field(description="KRW per 1 USD")
    dxy: float = Field(description="Broad trade-weighted dollar index")
    krw_change_1m_pct: float = Field(description="USD/KRW 1-month % change (+ = KRW weakening)")
    dxy_change_1m_pct: float = Field(description="DXY 1-month % change (+ = USD strengthening)")
    regime: Literal["krw_strong", "krw_weak", "usd_risk_off", "neutral"] = Field(
        description="krw_weak if KRW>+2% in 1m, usd_risk_off if both KRW and DXY rising together"
    )

    # === Tier 0 (2026-05-28) — F6 reform ===
    # Engel-West 2005 random walk fix: replace level z-score with %-change.
    krw_change_6m_pct: float = Field(
        default=0.0,
        description="USD/KRW 6-month % change. F6 component (replaces raw krw_level).",
    )
    krw_reer: float | None = Field(
        default=None,
        description="BIS Real Effective Exchange Rate KR (1994+). None=fetch fail or pre-1994.",
    )
```

- [ ] **Step 4: Run test (expect PASS)**

```bash
pytest tests/unit/schemas/test_macro_tier0.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tradingagents/schemas/macro.py tests/unit/schemas/test_macro_tier0.py
git commit -m "feat(tier0): FXSnapshot — krw_change_6m_pct, krw_reer"
```

---

### Task 3.2: CommodityMomentumSnapshot (new)

**Files:**
- Modify: `tradingagents/schemas/macro.py` (add class)
- Modify: `tests/unit/schemas/test_macro_tier0.py`

- [ ] **Step 1: Write failing test**

Append to `tests/unit/schemas/test_macro_tier0.py`:
```python
from tradingagents.schemas.macro import CommodityMomentumSnapshot


def test_commodity_momentum_snapshot():
    snap = CommodityMomentumSnapshot(
        as_of=date(2026, 5, 28), staleness_days=0,
        copper_3m_pct=5.2, copper_6m_pct=10.0,
        gold_3m_pct=2.0, gold_6m_pct=4.5,
        wti_3m_pct=-1.5, wti_6m_pct=3.0,
        bcom_3m_pct=2.5,
    )
    assert snap.copper_3m_pct == 5.2
    assert snap.bcom_3m_pct == 2.5
```

- [ ] **Step 2: Run test (expect FAIL — class not exist)**

```bash
pytest tests/unit/schemas/test_macro_tier0.py::test_commodity_momentum_snapshot -v
```

- [ ] **Step 3: Add class**

Append to `tradingagents/schemas/macro.py`:
```python
class CommodityMomentumSnapshot(StalenessAware):
    """Commodity price momentum — F2/F12 components, F13 directly.

    Daily price series (commodities.py) → 3m/6m % change.
    Reference: Erb-Harvey 2006 FAJ, Asness-Moskowitz-Pedersen 2013 JF.
    """
    copper_3m_pct: float = Field(description="Copper (HG=F) 3-month % change")
    copper_6m_pct: float = Field(description="Copper 6-month % change")
    gold_3m_pct: float = Field(description="Gold (GC=F) 3-month % change")
    gold_6m_pct: float = Field(description="Gold 6-month % change")
    wti_3m_pct: float = Field(description="WTI (CL=F) 3-month % change")
    wti_6m_pct: float = Field(description="WTI 6-month % change")
    bcom_3m_pct: float | None = Field(
        default=None,
        description="Bloomberg Commodity Index (^BCOM or DJP ETF proxy) 3m %. None=fetch fail.",
    )
```

- [ ] **Step 4: Run test (expect PASS)**

```bash
pytest tests/unit/schemas/test_macro_tier0.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tradingagents/schemas/macro.py tests/unit/schemas/test_macro_tier0.py
git commit -m "feat(tier0): CommodityMomentumSnapshot schema"
```

---

### Task 3.3: USEquityValuationSnapshot + GeopoliticalRiskSnapshot + ChinaCreditImpulseSnapshot + EarningsRevisionSnapshot

**Files:**
- Modify: `tradingagents/schemas/macro.py` (add 4 classes)
- Modify: `tests/unit/schemas/test_macro_tier0.py`

- [ ] **Step 1: Write failing test**

Append to test file:
```python
from tradingagents.schemas.macro import (
    USEquityValuationSnapshot, GeopoliticalRiskSnapshot,
    ChinaCreditImpulseSnapshot, EarningsRevisionSnapshot,
)


def test_us_equity_valuation():
    s = USEquityValuationSnapshot(
        as_of=date(2026, 5, 28), staleness_days=0,
        cape=32.5, cape_zscore_30y=1.2,
    )
    assert s.cape == 32.5

def test_geopolitical_risk():
    s = GeopoliticalRiskSnapshot(
        as_of=date(2026, 5, 28), staleness_days=0,
        gpr_monthly=120.0, gpr_zscore_60m=1.5,
        gpr_daily=130.0,
    )
    assert s.gpr_monthly == 120.0
    assert s.gpr_daily == 130.0

def test_china_credit_impulse():
    s = ChinaCreditImpulseSnapshot(
        as_of=date(2026, 5, 28), staleness_days=0,
        credit_impulse=2.5, credit_to_gdp_ratio=228.0,
        credit_yoy_pct=5.2,
    )
    assert s.credit_impulse == 2.5

def test_earnings_revision():
    s = EarningsRevisionSnapshot(
        as_of=date(2026, 5, 28), staleness_days=0,
        sp500_net_revision=0.15, kospi200_net_revision=-0.05,
    )
    assert s.sp500_net_revision == 0.15
```

- [ ] **Step 2: Run test (expect FAIL)**

```bash
pytest tests/unit/schemas/test_macro_tier0.py -v
```

- [ ] **Step 3: Add 4 classes to macro.py**

Append to `tradingagents/schemas/macro.py`:
```python
class USEquityValuationSnapshot(StalenessAware):
    """Shiller US CAPE — F8 component (Asness 2003 standard).

    Trailing PE는 ex-post, CAPE (PE10)는 10년 cyclically-adjusted PE.
    Source: Yale econ.yale.edu/~shiller/data/ie_data.xls.
    """
    cape: float = Field(description="Shiller CAPE (PE10), monthly")
    cape_zscore_30y: float = Field(default=0.0, description="30-year z-score of CAPE")


class GeopoliticalRiskSnapshot(StalenessAware):
    """Caldara-Iacoviello GPR Index — F7 component.

    Source: matteoiacoviello.com/gpr_files/.
    Replaces F7's `geopolitical_surge` (news count delta).
    """
    gpr_monthly: float = Field(description="GPR Index (monthly, 1900+)")
    gpr_zscore_60m: float = Field(default=0.0, description="60-month z-score")
    gpr_daily: float | None = Field(
        default=None,
        description="GPR Daily Index (1985+). None=fetch fail.",
    )


class ChinaCreditImpulseSnapshot(StalenessAware):
    """China Credit Impulse — F12 new factor.

    Biggs-Mayer-Pick 2010 JMCB: CI = Δ(Δ Credit/GDP) / (Δ Credit_{t-4}/GDP_{t-4}).
    Source: BIS Total Credit Q:CN:P:A:M:770:A (1985+ effective).
    """
    credit_impulse: float = Field(description="Biggs-Mayer-Pick credit impulse (%)")
    credit_to_gdp_ratio: float = Field(description="Raw credit/GDP ratio (%)")
    credit_yoy_pct: float = Field(description="Credit-to-GDP YoY % change (1st diff)")


class EarningsRevisionSnapshot(StalenessAware):
    """Earnings Revision Net Ratio — F11 new factor (staggered, 2010+).

    Source: yfinance upgrades_downgrades (SP500) + pykrx PER 1m change (KOSPI200).
    Net Ratio = (upgrades - downgrades) / total ∈ [-1, +1].
    """
    sp500_net_revision: float | None = Field(
        default=None,
        description="SP500 aggregated net revision ratio (1m). None=fetch fail or pre-2010.",
    )
    kospi200_net_revision: float | None = Field(
        default=None,
        description="KOSPI200 forward EPS implied 1m net change. None=fetch fail.",
    )
```

- [ ] **Step 4: Run test (expect PASS)**

```bash
pytest tests/unit/schemas/test_macro_tier0.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tradingagents/schemas/macro.py tests/unit/schemas/test_macro_tier0.py
git commit -m "feat(tier0): 4 new snapshots — USCape, GPR, ChinaCredit, EarningsRevision"
```

---

### Task 3.4: ExcessBondPremiumSnapshot + ForeignFlowSnapshot extension

**Files:**
- Modify: `tradingagents/schemas/risk.py` (add ExcessBondPremiumSnapshot)
- Modify: `tradingagents/schemas/macro.py` (extend ForeignFlowSnapshot)
- Modify: `tests/unit/schemas/test_macro_tier0.py`

- [ ] **Step 1: Write failing test**

Append:
```python
from tradingagents.schemas.risk import ExcessBondPremiumSnapshot
from tradingagents.schemas.macro import ForeignFlowSnapshot


def test_excess_bond_premium():
    s = ExcessBondPremiumSnapshot(
        as_of=date(2026, 5, 28), staleness_days=0,
        ebp=-0.25, ebp_zscore_5y=-0.5,
    )
    assert s.ebp == -0.25

def test_foreign_flow_normalized_field():
    s = ForeignFlowSnapshot(
        as_of=date(2026, 5, 28), staleness_days=0,
        net_5d_krw=1e11, net_20d_krw=5e11,
        signal="net_buying",
        net_20d_normalized=0.0012,
    )
    assert s.net_20d_normalized == 0.0012
```

- [ ] **Step 2: Run test (expect FAIL)**

```bash
pytest tests/unit/schemas/test_macro_tier0.py::test_excess_bond_premium tests/unit/schemas/test_macro_tier0.py::test_foreign_flow_normalized_field -v
```

- [ ] **Step 3: Add ExcessBondPremiumSnapshot to risk.py**

Append to `tradingagents/schemas/risk.py`:
```python
class ExcessBondPremiumSnapshot(StalenessAware):
    """Gilchrist-Zakrajsek 2012 Excess Bond Premium — F5 component.

    EBP = corporate spread - default risk component (Merton 1974 distance-to-default).
    Pure risk-bearing capacity proxy. NBER recession 4-12m lead.
    Source: federalreserve.gov/econres/notes/feds-notes/ebp_csv.csv.
    """
    ebp: float = Field(description="Monthly EBP (1973+)")
    ebp_zscore_5y: float = Field(default=0.0, description="5-year rolling z-score")
```

- [ ] **Step 4: Extend ForeignFlowSnapshot in macro.py**

In `tradingagents/schemas/macro.py`, modify `class ForeignFlowSnapshot`:
```python
class ForeignFlowSnapshot(StalenessAware):
    """KRX 외국인 KOSPI 순매수. 단기 KOSPI 방향성과 매우 높은 상관."""
    net_5d_krw: float = Field(description="외국인 5거래일 누적 순매수 (KRW)")
    net_20d_krw: float = Field(description="외국인 20거래일 누적 순매수 (KRW)")
    signal: Literal["net_buying", "net_selling", "neutral"] = Field(
        description="net_buying if 20d>+1조, net_selling if <-1조"
    )

    # === Tier 0 — Stambaugh 1986 period non-stationarity fix ===
    net_20d_normalized: float = Field(
        default=0.0,
        description="net_20d_krw / KOSPI market_cap (ratio). Period-stationary "
                    "(1991-2024 sample composition fix).",
    )
```

- [ ] **Step 5: Run test (expect PASS)**

```bash
pytest tests/unit/schemas/test_macro_tier0.py -v
```

- [ ] **Step 6: Commit**

```bash
git add tradingagents/schemas/risk.py tradingagents/schemas/macro.py tests/unit/schemas/test_macro_tier0.py
git commit -m "feat(tier0): ExcessBondPremium snapshot + ForeignFlow.net_20d_normalized"
```

---

### Task 3.5: MacroReport schema integration

**Files:**
- Modify: `tradingagents/schemas/reports.py` (MacroReport adds Optional fields)

- [ ] **Step 1: Add Optional fields to MacroReport**

In `tradingagents/schemas/reports.py`, modify `class MacroReport`:
```python
class MacroReport(_AnalystReport):
    yield_curve: YieldCurveSnapshot
    inflation: InflationSnapshot
    # ... (existing fields)

    # === Tier 0 (2026-05-28) — Optional new snapshots ===
    commodity_momentum: CommodityMomentumSnapshot | None = None
    us_equity_valuation: USEquityValuationSnapshot | None = None
    geopolitical_risk: GeopoliticalRiskSnapshot | None = None
    china_credit_impulse: ChinaCreditImpulseSnapshot | None = None
    earnings_revision: EarningsRevisionSnapshot | None = None
```

Add corresponding imports at top of reports.py:
```python
from tradingagents.schemas.macro import (
    CommodityMomentumSnapshot, USEquityValuationSnapshot,
    GeopoliticalRiskSnapshot, ChinaCreditImpulseSnapshot,
    EarningsRevisionSnapshot,
)
```

- [ ] **Step 2: Write integration test**

`tests/unit/schemas/test_macro_tier0.py` append:
```python
def test_macroreport_accepts_tier0_optional_fields(minimal_macro_report_kwargs):
    """Minimal MacroReport works without new Optional fields, and accepts them."""
    from tradingagents.schemas.reports import MacroReport
    # Build with only required fields → new fields default None
    r1 = MacroReport(**minimal_macro_report_kwargs)
    assert r1.commodity_momentum is None

    # Build with new field
    r2 = MacroReport(
        **minimal_macro_report_kwargs,
        commodity_momentum=CommodityMomentumSnapshot(
            as_of=date(2026, 5, 28), staleness_days=0,
            copper_3m_pct=5.0, copper_6m_pct=10.0,
            gold_3m_pct=2.0, gold_6m_pct=4.0,
            wti_3m_pct=-1.0, wti_6m_pct=2.0,
        ),
    )
    assert r2.commodity_momentum.copper_3m_pct == 5.0
```

Add fixture in same file (or `conftest.py`):
```python
@pytest.fixture
def minimal_macro_report_kwargs():
    """Minimal kwargs for MacroReport — populate per actual MacroReport required fields."""
    # NOTE: Replace placeholders with actual minimal valid kwargs per current schema.
    # The exact structure depends on what's required vs Optional in MacroReport.
    # Use schema's required-field discovery: MacroReport.model_fields with no default.
    return {
        "as_of": date(2026, 5, 28), "staleness_days": 0,
        "narrative": "test", "summary_for_downstream": "test summary",
        # ... fill required fields per current MacroReport schema
    }
```

> Note: Adjust `minimal_macro_report_kwargs` to match current required-field set. Discover via `MacroReport.model_fields`.

- [ ] **Step 3: Run test (expect PASS once fixture is filled in)**

```bash
pytest tests/unit/schemas/test_macro_tier0.py::test_macroreport_accepts_tier0_optional_fields -v
```

- [ ] **Step 4: Commit**

```bash
git add tradingagents/schemas/reports.py tests/unit/schemas/test_macro_tier0.py
git commit -m "feat(tier0): MacroReport Optional fields for new snapshots"
```

---

## Phase 4: Stage 1 Analyst Updates

### Task 4.1: macro_quant_analyst fills new snapshots

**Files:**
- Modify: `tradingagents/agents/analysts/macro_quant_analyst.py`
- Create: `tests/unit/agents/test_macro_quant_tier0.py`

- [ ] **Step 1: Write failing test**

`tests/unit/agents/test_macro_quant_tier0.py`:
```python
import pytest
from unittest.mock import patch, MagicMock
from datetime import date
import pandas as pd
from tradingagents.agents.analysts.macro_quant_analyst import build_macro_report


def _stub_external_fetches():
    """Common patches to bypass external IO."""
    return {
        "fetch_shiller_cape": lambda as_of=None: pd.Series(
            [30.0, 31.0], index=pd.to_datetime(["2026-04-01", "2026-05-01"]),
        ),
        "fetch_gpr_index": lambda **kw: pd.Series(
            [120.0, 130.0], index=pd.to_datetime(["2026-04-01", "2026-05-01"]),
        ),
        "fetch_bis_china_credit": lambda as_of=None: pd.Series(
            [220.0, 225.0, 228.0, 230.0, 232.0, 235.0],
            index=pd.to_datetime(["2024-09-30","2024-12-31","2025-03-31",
                                   "2025-06-30","2025-09-30","2025-12-31"]),
        ),
    }


def test_macro_quant_fills_commodity_momentum(monkeypatch):
    """macro_quant_analyst populates CommodityMomentumSnapshot from yfinance."""
    # Mock minimal Stage 1 data + verify CommodityMomentum populated
    # ... pattern: patch fetchers, call build_macro_report, assert .commodity_momentum is not None
    # Skipping concrete implementation — depends on current build_macro_report signature.
    pass  # Placeholder — IMPLEMENT against current analyst signature
```

- [ ] **Step 2: Inspect current analyst structure**

Run:
```bash
grep -n "def build_macro_report\|MacroReport(" tradingagents/agents/analysts/macro_quant_analyst.py | head -20
```

Note the analyst's report-building entry point and adjust test stub.

- [ ] **Step 3: Add fillers to analyst**

In `tradingagents/agents/analysts/macro_quant_analyst.py`, locate the MacroReport instantiation. Add Tier 0 fillers before instantiation:

```python
# === Tier 0 (2026-05-28): populate new snapshots ===
from tradingagents.dataflows.shiller_cape import fetch_shiller_cape
from tradingagents.dataflows.gpr_index import fetch_gpr_index
from tradingagents.dataflows.bis_credit import fetch_bis_china_credit
from tradingagents.skills.research.china_credit_impulse import compute_china_credit_impulse
from tradingagents.skills.research.earnings_revision import (
    compute_sp500_net_revision, compute_kospi200_net_revision,
)

def _build_us_equity_valuation(as_of: date) -> USEquityValuationSnapshot | None:
    try:
        cape_series = fetch_shiller_cape(as_of=as_of)
        if cape_series.empty:
            return None
        cape = float(cape_series.iloc[-1])
        # 30y z-score
        cutoff = pd.Timestamp(as_of) - pd.DateOffset(years=30)
        recent = cape_series[cape_series.index >= cutoff]
        mu, sd = float(recent.mean()), float(recent.std(ddof=1)) or 1e-9
        z = (cape - mu) / sd
        return USEquityValuationSnapshot(
            as_of=as_of, staleness_days=1,
            cape=cape, cape_zscore_30y=z,
        )
    except Exception as e:
        logger.warning("US CAPE fetch failed: %s", e)
        return None


def _build_geopolitical_risk(as_of: date) -> GeopoliticalRiskSnapshot | None:
    try:
        gpr = fetch_gpr_index(frequency="monthly", series="GPR", as_of=as_of)
        if gpr.empty:
            return None
        gpr_now = float(gpr.iloc[-1])
        cutoff = pd.Timestamp(as_of) - pd.DateOffset(months=60)
        recent = gpr[gpr.index >= cutoff]
        mu, sd = float(recent.mean()), float(recent.std(ddof=1)) or 1e-9
        z = (gpr_now - mu) / sd
        gpr_daily_val = None
        try:
            gd = fetch_gpr_index(frequency="daily", series="GPRD", as_of=as_of)
            if not gd.empty:
                gpr_daily_val = float(gd.iloc[-1])
        except Exception:
            pass
        return GeopoliticalRiskSnapshot(
            as_of=as_of, staleness_days=1,
            gpr_monthly=gpr_now, gpr_zscore_60m=z, gpr_daily=gpr_daily_val,
        )
    except Exception as e:
        logger.warning("GPR fetch failed: %s", e)
        return None


def _build_china_credit_impulse(as_of: date) -> ChinaCreditImpulseSnapshot | None:
    try:
        ci_data = compute_china_credit_impulse(as_of)
        if ci_data is None:
            return None
        return ChinaCreditImpulseSnapshot(
            as_of=as_of, staleness_days=60,  # BIS quarterly lag
            credit_impulse=ci_data["impulse"],
            credit_to_gdp_ratio=ci_data["ratio"],
            credit_yoy_pct=ci_data["yoy"],
        )
    except Exception as e:
        logger.warning("China credit impulse failed: %s", e)
        return None


def _build_earnings_revision(as_of: date) -> EarningsRevisionSnapshot | None:
    if as_of < date(2010, 1, 1):
        return None  # F11 staggered: pre-2010 unavailable
    sp = compute_sp500_net_revision(as_of)
    ks = compute_kospi200_net_revision(as_of)
    if sp is None and ks is None:
        return None
    return EarningsRevisionSnapshot(
        as_of=as_of, staleness_days=1,
        sp500_net_revision=sp, kospi200_net_revision=ks,
    )


def _build_commodity_momentum(as_of: date) -> CommodityMomentumSnapshot | None:
    """Read commodities.py daily price series, compute 3m/6m % changes."""
    from tradingagents.dataflows.commodities import fetch_commodity_close
    from datetime import timedelta
    start_6m = as_of - timedelta(days=200)
    try:
        copper = fetch_commodity_close("copper", start_6m, as_of)
        gold = fetch_commodity_close("gold", start_6m, as_of)
        wti = fetch_commodity_close("wti_oil", start_6m, as_of)
        def _pct(s, days):
            if s.empty or len(s) < days:
                return 0.0
            return float((s.iloc[-1] / s.iloc[-days] - 1) * 100)
        return CommodityMomentumSnapshot(
            as_of=as_of, staleness_days=1,
            copper_3m_pct=_pct(copper, 63), copper_6m_pct=_pct(copper, 126),
            gold_3m_pct=_pct(gold, 63), gold_6m_pct=_pct(gold, 126),
            wti_3m_pct=_pct(wti, 63), wti_6m_pct=_pct(wti, 126),
            bcom_3m_pct=None,  # BCOM via DJP — implement separately if needed
        )
    except Exception as e:
        logger.warning("commodity_momentum failed: %s", e)
        return None
```

Then in MacroReport instantiation, pass these fillers:
```python
report = MacroReport(
    # ... existing fields ...
    commodity_momentum=_build_commodity_momentum(as_of),
    us_equity_valuation=_build_us_equity_valuation(as_of),
    geopolitical_risk=_build_geopolitical_risk(as_of),
    china_credit_impulse=_build_china_credit_impulse(as_of),
    earnings_revision=_build_earnings_revision(as_of),
)
```

- [ ] **Step 4: Smoke test (manual or scripted)**

```bash
python -c "
from datetime import date
from tradingagents.agents.analysts.macro_quant_analyst import build_macro_report
# Or whatever the actual entry point is. Verify no exception when running with mocks/fixtures.
"
```

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/analysts/macro_quant_analyst.py tests/unit/agents/test_macro_quant_tier0.py
git commit -m "feat(tier0): macro_quant_analyst fills 5 new snapshots (CAPE/GPR/China/Earnings/Commodity)"
```

---

### Task 4.2: market_risk_analyst fills ExcessBondPremiumSnapshot

**Files:**
- Modify: `tradingagents/agents/analysts/market_risk_analyst.py`

- [ ] **Step 1: Locate where RiskReport is built**

```bash
grep -n "RiskReport(\|def build_risk_report" tradingagents/agents/analysts/market_risk_analyst.py | head -10
```

- [ ] **Step 2: Add EBP filler**

Add helper function:
```python
from tradingagents.dataflows.gz_ebp import fetch_gz_ebp
import pandas as pd
from datetime import date


def _build_excess_bond_premium(as_of: date) -> ExcessBondPremiumSnapshot | None:
    try:
        ebp_series = fetch_gz_ebp(as_of=as_of)
        if ebp_series.empty:
            return None
        ebp_now = float(ebp_series.iloc[-1])
        cutoff = pd.Timestamp(as_of) - pd.DateOffset(years=5)
        recent = ebp_series[ebp_series.index >= cutoff]
        mu, sd = float(recent.mean()), float(recent.std(ddof=1)) or 1e-9
        z = (ebp_now - mu) / sd
        return ExcessBondPremiumSnapshot(
            as_of=as_of, staleness_days=15,  # monthly publication lag
            ebp=ebp_now, ebp_zscore_5y=z,
        )
    except Exception as e:
        logger.warning("GZ EBP fetch failed: %s", e)
        return None
```

Add to RiskReport instantiation:
```python
report = RiskReport(
    # ... existing fields ...
    excess_bond_premium=_build_excess_bond_premium(as_of),
)
```

> Note: `RiskReport` must accept the new Optional field. Modify `tradingagents/schemas/reports.py` `RiskReport` to add:
> ```python
> excess_bond_premium: ExcessBondPremiumSnapshot | None = None
> ```
> (Plus import.)

- [ ] **Step 3: Commit**

```bash
git add tradingagents/agents/analysts/market_risk_analyst.py tradingagents/schemas/reports.py
git commit -m "feat(tier0): market_risk_analyst fills ExcessBondPremiumSnapshot"
```

---

## Phase 5: Factor Model Reform (factor_estimators.py)

> **Big task ahead.** Splitting into per-factor tasks for review granularity.

### Task 5.1: Update FACTORS tuple + FactorScores dataclass

**Files:**
- Modify: `tradingagents/skills/research/factor_estimators.py`
- Modify: `tests/unit/skills/research/test_factor_estimators.py`

- [ ] **Step 1: Write failing test**

Add to `tests/unit/skills/research/test_factor_estimators.py`:
```python
from tradingagents.skills.research.factor_estimators import FACTORS, FactorScores


def test_factors_tuple_has_12_entries_with_renamed_f9():
    assert len(FACTORS) == 12
    assert "F9_market_dispersion" in FACTORS
    assert "F9_liquidity_regime" not in FACTORS
    assert "F11_earnings_revision" in FACTORS
    assert "F12_china_credit_impulse" in FACTORS


def test_factor_scores_to_dict_includes_new_factors():
    from tradingagents.skills.research.factor_estimators import FactorScore
    # Build minimal FactorScores
    def _s(name, z=0.0): return FactorScore(name=name, z_score=z)
    fs = FactorScores(
        growth_surprise=_s("F1_growth", 1.0),
        inflation_surprise=_s("F2_inflation"),
        real_rate=_s("F3_real_rate"),
        term_premium=_s("F4_term_premium"),
        credit_cycle=_s("F5_credit_cycle"),
        krw_regime=_s("F6_krw_regime"),
        equity_vol_regime=_s("F7_equity_vol"),
        valuation=_s("F8_valuation"),
        market_dispersion=_s("F9_market_dispersion"),  # renamed
        systemic_liquidity=_s("F10_systemic_liquidity", 0.5),
        earnings_revision=_s("F11_earnings_revision", 0.3),
        china_credit_impulse=_s("F12_china_credit_impulse", -0.2),
    )
    d = fs.to_dict()
    assert d["F1_growth"] == 1.0
    assert d["F9_market_dispersion"] == 0.0
    assert d["F11_earnings_revision"] == 0.3
    assert d["F12_china_credit_impulse"] == -0.2


def test_factor_scores_to_dict_drops_none_f11():
    """F11 staggered: when None, not in dict."""
    from tradingagents.skills.research.factor_estimators import FactorScore
    fs = FactorScores(
        growth_surprise=FactorScore(name="F1_growth", z_score=0.0),
        inflation_surprise=FactorScore(name="F2_inflation", z_score=0.0),
        real_rate=FactorScore(name="F3_real_rate", z_score=0.0),
        term_premium=FactorScore(name="F4_term_premium", z_score=0.0),
        credit_cycle=FactorScore(name="F5_credit_cycle", z_score=0.0),
        krw_regime=FactorScore(name="F6_krw_regime", z_score=0.0),
        equity_vol_regime=FactorScore(name="F7_equity_vol", z_score=0.0),
        valuation=FactorScore(name="F8_valuation", z_score=0.0),
        market_dispersion=FactorScore(name="F9_market_dispersion", z_score=0.0),
        systemic_liquidity=None,
        earnings_revision=None,  # pre-2010 backtest
        china_credit_impulse=None,
    )
    d = fs.to_dict()
    assert "F11_earnings_revision" not in d
    assert "F12_china_credit_impulse" not in d
    assert "F10_systemic_liquidity" not in d
```

- [ ] **Step 2: Run test (expect FAIL)**

```bash
pytest tests/unit/skills/research/test_factor_estimators.py::test_factors_tuple_has_12_entries_with_renamed_f9 -v
```

- [ ] **Step 3: Update FACTORS tuple + FactorScores**

In `tradingagents/skills/research/factor_estimators.py`:

Replace `FACTORS`:
```python
FACTORS: Final[tuple[str, ...]] = (
    "F1_growth",
    "F2_inflation",
    "F3_real_rate",
    "F4_term_premium",
    "F5_credit_cycle",
    "F6_krw_regime",
    "F7_equity_vol_regime",
    "F8_valuation",
    "F9_market_dispersion",        # renamed from F9_liquidity_regime
    "F10_systemic_liquidity",
    "F11_earnings_revision",       # NEW (staggered, 2010+)
    "F12_china_credit_impulse",    # NEW
)
```

Replace `FactorScores`:
```python
@dataclass
class FactorScores:
    growth_surprise: FactorScore
    inflation_surprise: FactorScore
    real_rate: FactorScore
    term_premium: FactorScore
    credit_cycle: FactorScore
    krw_regime: FactorScore
    equity_vol_regime: FactorScore
    valuation: FactorScore
    market_dispersion: FactorScore     # renamed
    systemic_liquidity: FactorScore | None = None
    earnings_revision: FactorScore | None = None     # NEW (staggered)
    china_credit_impulse: FactorScore | None = None  # NEW

    def to_dict(self) -> dict[str, float]:
        out = {
            "F1_growth":              self.growth_surprise.z_score,
            "F2_inflation":           self.inflation_surprise.z_score,
            "F3_real_rate":           self.real_rate.z_score,
            "F4_term_premium":        self.term_premium.z_score,
            "F5_credit_cycle":        self.credit_cycle.z_score,
            "F6_krw_regime":          self.krw_regime.z_score,
            "F7_equity_vol_regime":   self.equity_vol_regime.z_score,
            "F8_valuation":           self.valuation.z_score,
            "F9_market_dispersion":   self.market_dispersion.z_score,
        }
        if self.systemic_liquidity is not None:
            out["F10_systemic_liquidity"] = self.systemic_liquidity.z_score
        if self.earnings_revision is not None:
            out["F11_earnings_revision"] = self.earnings_revision.z_score
        if self.china_credit_impulse is not None:
            out["F12_china_credit_impulse"] = self.china_credit_impulse.z_score
        return out
```

- [ ] **Step 4: Run test (expect PASS)**

```bash
pytest tests/unit/skills/research/test_factor_estimators.py::test_factors_tuple_has_12_entries_with_renamed_f9 tests/unit/skills/research/test_factor_estimators.py::test_factor_scores_to_dict_includes_new_factors tests/unit/skills/research/test_factor_estimators.py::test_factor_scores_to_dict_drops_none_f11 -v
```

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/research/factor_estimators.py tests/unit/skills/research/test_factor_estimators.py
git commit -m "feat(tier0): FACTORS tuple + FactorScores → 12-factor schema"
```

---

### Task 5.2: NEWS_DERIVED_COMPONENTS + LIVE_ONLY_QUANT_COMPONENTS

**Files:**
- Modify: `tradingagents/skills/research/factor_estimators.py`
- Modify: `tests/unit/skills/research/test_factor_estimators.py`

- [ ] **Step 1: Write failing test**

```python
from tradingagents.skills.research.factor_estimators import (
    NEWS_DERIVED_COMPONENTS, LIVE_ONLY_QUANT_COMPONENTS,
)


def test_geopolitical_surge_removed_from_news_set():
    """Tier 0: geopolitical_surge replaced by GPR Index (quant) → not news."""
    assert "geopolitical_surge" not in NEWS_DERIVED_COMPONENTS


def test_gdpnow_in_live_only_quant():
    """Tier 0: GDPNow backtest history starts 2011 (too short) → live only."""
    assert "gdpnow" in LIVE_ONLY_QUANT_COMPONENTS
```

- [ ] **Step 2: Run test (expect FAIL)**

```bash
pytest tests/unit/skills/research/test_factor_estimators.py::test_geopolitical_surge_removed_from_news_set -v
```

- [ ] **Step 3: Update sets + _aggregate**

In `factor_estimators.py`:

Modify `NEWS_DERIVED_COMPONENTS`:
```python
NEWS_DERIVED_COMPONENTS: Final[frozenset[str]] = frozenset({
    # F1 (제거 component 제외)
    "release_surprise", "hawkish_bias", "macro_sent", "risk_regime_overnight",
    # F2
    "release_hawkish",
    # F3
    "fed_voting_balance",
    # F4
    "fed_tone_balance",
    # F5
    "corporate_distress", "dovish_bias",
    # F6
    "krw_overnight_pct", "bok_tone_balance",
    # F7 (geopolitical_surge 제거 — Tier 0: GPR Index가 quant)
    "sentiment_dispersion",
    # F9 (unchanged)
    "event_cluster", "rising_signal",
})
```

Add new frozenset:
```python
# Tier 0 (2026-05-28): quant components with short backtest history → live-only.
LIVE_ONLY_QUANT_COMPONENTS: Final[frozenset[str]] = frozenset({
    "gdpnow",  # Atlanta Fed GDPNOW (2011+) — too short for backtest, live add only
})
```

Update `_aggregate` to drop both sets in historical mode:
```python
def _aggregate(
    factor_name: str,
    components_raw: dict[str, float | None],
    weights: dict[str, float],
    mode: FactorMode = "production",
) -> FactorScore:
    if mode == "historical":
        components_raw = {
            k: v for k, v in components_raw.items()
            if k not in NEWS_DERIVED_COMPONENTS
            and k not in LIVE_ONLY_QUANT_COMPONENTS
        }
    # ... rest unchanged
```

- [ ] **Step 4: Run test (expect PASS)**

```bash
pytest tests/unit/skills/research/test_factor_estimators.py::test_geopolitical_surge_removed_from_news_set tests/unit/skills/research/test_factor_estimators.py::test_gdpnow_in_live_only_quant -v
```

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/research/factor_estimators.py tests/unit/skills/research/test_factor_estimators.py
git commit -m "feat(tier0): NEWS_DERIVED set (geopolitical_surge 제거) + LIVE_ONLY_QUANT (gdpnow)"
```

---

### Task 5.3: F1 reform (compute_growth_surprise)

**Files:**
- Modify: `tradingagents/skills/research/factor_estimators.py`
- Modify: `tradingagents/skills/research/factor_baselines.py` (add new component baselines)
- Modify: `tests/unit/skills/research/test_factor_estimators.py`

- [ ] **Step 1: Add baselines for new F1 components**

In `factor_baselines.py`, modify `LONG_RUN_BASELINE` dict — under `=== F1 growth_surprise ===`, **remove** nfci entry and **add**:
```python
    # Tier 0: F1 reform
    ("F1_growth", "indpro_yoy"):     (2.0, 3.0),    # INDPRO YoY long-run mean ~2%, sd ~3%
    ("F1_growth", "real_pce_yoy"):   (2.5, 2.0),    # Real PCE YoY long-run mean ~2.5%, sd ~2%
    # ("F1_growth", "nfci") removed — F10에 양보
    # ("F1_growth", "curve") removed — F4에 양보
```

> Note: also delete `("F1_growth", "nfci")` and `("F1_growth", "curve")` entries from the dict.

- [ ] **Step 2: Write failing test**

```python
def test_f1_no_longer_uses_nfci_or_curve():
    """Tier 0: F1 removed nfci (F10 dup) + curve (F4 dup)."""
    from tradingagents.agents.utils.agent_states import _create_empty_state
    from tradingagents.skills.research.factor_estimators import compute_growth_surprise
    # Build stage1 with strong nfci tightening (+1.0) — F1 should NOT respond strongly
    # because nfci is removed from F1.
    state = _make_mock_stage1(nfci=1.0, indpro_yoy=2.0, real_pce_yoy=2.5, gdpnow=2.0,
                              cfnai=0.0, cfnai_3m=0.0)
    score = compute_growth_surprise(state, mode="historical")  # drops news+gdpnow
    # F1 z should be ~0 (indpro/pce/cfnai/cfnai_3m/sahm all at baseline)
    assert abs(score.z_score) < 0.5  # confirm nfci doesn't drive F1


def _make_mock_stage1(**kwargs):
    """Helper: build minimal stage1-like object with nested attribute access."""
    class Obj:
        def __init__(self, **d):
            for k, v in d.items(): setattr(self, k, v)
    # ... build nested macro_report.financial_conditions.nfci etc.
    # Implementation depends on real schema. Use Mock or actual schema fixtures.
    return Obj(...)
```

> Note: For real test, build a `MockStage1` fixture that mirrors current `AgentState` paths. See existing test fixtures in `tests/unit/skills/research/test_factor_estimators.py` for the pattern.

- [ ] **Step 3: Run test (expect FAIL — F1 still uses nfci)**

```bash
pytest tests/unit/skills/research/test_factor_estimators.py::test_f1_no_longer_uses_nfci_or_curve -v
```

- [ ] **Step 4: Modify compute_growth_surprise**

In `factor_estimators.py`, replace `compute_growth_surprise`:
```python
def compute_growth_surprise(stage1: Any, mode: FactorMode = "production") -> FactorScore:
    """F1 growth_surprise — +z = stronger growth.

    Tier 0 reform:
    - REMOVED: nfci (F10 dup), curve (F4 dup)
    - ADDED:   indpro_yoy (INDPRO YoY), real_pce_yoy (Real PCE YoY)
    - gdpnow: live only (LIVE_ONLY_QUANT_COMPONENTS drops in historical)
    """
    gdpnow = _safe_get(stage1, "macro_report", "gdp_nowcast", "nowcast_pct")

    # New: INDPRO YoY, Real PCE YoY — to be filled by macro_quant_analyst from FRED
    indpro_yoy = _safe_get(stage1, "macro_report", "us_indpro_yoy_pct")
    real_pce_yoy = _safe_get(stage1, "macro_report", "us_real_pce_yoy_pct")

    sahm_trigger = _safe_get(stage1, "macro_report", "employment", "sahm_rule_triggered")
    sahm_signal = None if sahm_trigger is None else (-1.0 if sahm_trigger else 0.5)

    cfnai = _safe_get(stage1, "macro_report", "financial_conditions", "cfnai")
    cfnai_3m = _safe_get(stage1, "macro_report", "financial_conditions", "cfnai_3m_avg")

    components_raw: dict[str, float | None] = {
        "gdpnow":         gdpnow,
        "cfnai":          cfnai,
        "cfnai_3m":       cfnai_3m,
        "sahm":           sahm_signal,
        "indpro_yoy":     indpro_yoy,
        "real_pce_yoy":   real_pce_yoy,
        # News-derived (drop in historical mode)
        "release_surprise":      _safe_get(stage1, "news_report", "release_surprise", "surprise_index_30d"),
        "hawkish_bias":          _BIAS_MAP.get(
            _safe_get(stage1, "news_report", "release_surprise", "bias_30d") or ""
        ),
        "macro_sent":            _safe_get(stage1, "news_report", "news_sentiment", "avg_sentiment", "macro"),
        "risk_regime_overnight": _RISK_REGIME_MAP.get(
            _safe_get(stage1, "news_report", "global_overnight", "risk_regime_overnight") or ""
        ),
    }

    # Production-mode weights (sum=1.00); historical mode drops gdpnow + news, renormalizes.
    weights: dict[str, float] = {
        "gdpnow":      0.10,   # LIVE only
        "cfnai":       0.12,
        "cfnai_3m":    0.10,
        "sahm":        0.08,
        "indpro_yoy":  0.15,   # NEW
        "real_pce_yoy":0.10,   # NEW
        "release_surprise":      0.15,
        "hawkish_bias":          0.05,
        "macro_sent":            0.05,
        "risk_regime_overnight": 0.10,
    }
    return _aggregate("F1_growth", components_raw, weights, mode=mode)
```

> Also: macro_quant_analyst must compute `us_indpro_yoy_pct` and `us_real_pce_yoy_pct` and stash them on `macro_report`. Add fields to MacroReport in `reports.py`:
> ```python
> us_indpro_yoy_pct: float | None = None
> us_real_pce_yoy_pct: float | None = None
> ```
> And populate in macro_quant_analyst from FRED INDPRO / PCECC96 with %-YoY.

- [ ] **Step 5: Run test (expect PASS)**

```bash
pytest tests/unit/skills/research/test_factor_estimators.py::test_f1_no_longer_uses_nfci_or_curve -v
```

- [ ] **Step 6: Commit**

```bash
git add tradingagents/skills/research/factor_estimators.py tradingagents/skills/research/factor_baselines.py tradingagents/schemas/reports.py tradingagents/agents/analysts/macro_quant_analyst.py tests/unit/skills/research/test_factor_estimators.py
git commit -m "feat(tier0): F1 reform — drop nfci/curve, add INDPRO + Real PCE"
```

---

### Task 5.4: F4 reform (ACM term premium)

**Files:**
- Modify: `tradingagents/skills/research/factor_estimators.py` (compute_term_premium)
- Modify: `tradingagents/schemas/macro.py` (YieldCurveSnapshot adds field)
- Modify: `tradingagents/agents/analysts/macro_quant_analyst.py` (fill new field)
- Modify: `tradingagents/skills/research/factor_baselines.py`

- [ ] **Step 1: Add field + baseline + analyst filler**

In `tradingagents/schemas/macro.py`, modify `class YieldCurveSnapshot`:
```python
class YieldCurveSnapshot(StalenessAware):
    spread_10y_2y_bps: float
    spread_10y_3m_bps: float
    inverted_days_count: int = Field(ge=0)
    percentile_5y: float = Field(ge=0, le=1)
    spread_30y_5y_bps: float = Field(default=0.0)
    # === Tier 0: F4 reform — ACM term premium ===
    acm_term_premium_10y_pct: float | None = Field(
        default=None,
        description="NY Fed ACM 10y term premium (THREEFYTP10, %). None=fetch fail.",
    )
```

In `factor_baselines.py` `LONG_RUN_BASELINE`, add:
```python
    ("F4_term_premium", "acm_term_premium_10y"): (0.5, 1.0),  # ACM 10y mean ~0.5%, sd ~1%
```

In `macro_quant_analyst.py`, ensure YieldCurveSnapshot is populated with ACM:
```python
# Inside the YieldCurveSnapshot build:
acm_tp = fetch_fred_series("us_acm_term_premium_10y", start, as_of, as_of_date=as_of).iloc[-1] \
         if not <fetched series>.empty else None
yield_curve = YieldCurveSnapshot(
    # ... existing ...
    acm_term_premium_10y_pct=acm_tp,
)
```

- [ ] **Step 2: Write failing test**

```python
def test_f4_uses_acm_term_premium():
    state = _make_mock_stage1(
        slope_2_10y=80.0, slope_5_30y=80.0,
        acm_term_premium=2.0,
    )
    score = compute_term_premium(state, mode="historical")
    # Strong positive ACM (+1.5σ) → F4 positive
    assert score.z_score > 0.3
```

- [ ] **Step 3: Modify compute_term_premium**

```python
def compute_term_premium(stage1: Any, mode: FactorMode = "production") -> FactorScore:
    """F4 term_premium — +z = steeper / higher term premium.

    Tier 0 reform: ACM term premium added (NY Fed THREEFYTP10).
    Reference: Adrian-Crump-Moench 2013 RFS.
    """
    slope_2_10 = _safe_get(stage1, "macro_report", "yield_curve", "spread_10y_2y_bps")
    slope_5_30 = _safe_get(stage1, "macro_report", "yield_curve", "spread_30y_5y_bps")
    acm_tp = _safe_get(stage1, "macro_report", "yield_curve", "acm_term_premium_10y_pct")

    components_raw: dict[str, float | None] = {
        "slope_2_10y":      slope_2_10,
        "slope_5_30y":      slope_5_30,
        "acm_term_premium_10y": acm_tp,
        "fed_tone_balance":   _safe_get(stage1, "news_report", "cb_speakers", "fed_tone_balance"),
        "fed_voting_balance": _safe_get(stage1, "news_report", "cb_speakers", "fed_voting_balance"),
    }
    weights: dict[str, float] = {
        "slope_2_10y":      0.15,
        "slope_5_30y":      0.10,
        "acm_term_premium_10y": 0.30,   # NEW: pure term premium (Adrian-Crump-Moench)
        "fed_tone_balance":     0.25,
        "fed_voting_balance":   0.20,
    }
    return _aggregate("F4_term_premium", components_raw, weights, mode=mode)
```

- [ ] **Step 4: Run tests; commit**

```bash
pytest tests/unit/skills/research/test_factor_estimators.py::test_f4_uses_acm_term_premium -v
git add tradingagents/skills/research/factor_estimators.py tradingagents/skills/research/factor_baselines.py tradingagents/schemas/macro.py tradingagents/agents/analysts/macro_quant_analyst.py
git commit -m "feat(tier0): F4 reform — ACM term premium (THREEFYTP10)"
```

---

### Task 5.5: F5 reform (GZ EBP + KR corp spread)

**Files:**
- Modify: `tradingagents/skills/research/factor_estimators.py` (compute_credit_cycle)
- Modify: `tradingagents/skills/research/factor_baselines.py`

- [ ] **Step 1: Add baselines**

```python
    ("F5_credit_cycle", "gz_ebp"):              (0.0, 0.5),   # EBP mean ~0%, sd ~0.5%
    ("F5_credit_cycle", "kr_corp_spread_bps"):  (60.0, 40.0), # KR corp 3y spread mean ~60bps
```

- [ ] **Step 2: Update compute_credit_cycle**

```python
def compute_credit_cycle(stage1: Any, mode: FactorMode = "production") -> FactorScore:
    """F5 credit_cycle — +z = credit stress.

    Tier 0 reform: GZ EBP (Gilchrist-Zakrajsek 2012) + KR corp spread.
    """
    # ... existing component computations: corporate_distress, dovish_bias ...
    gz_ebp = _safe_get(stage1, "risk_report", "excess_bond_premium", "ebp")
    kr_corp_spread = _safe_get(stage1, "risk_report", "kr_corp_spread", "spread_bps")

    components_raw: dict[str, float | None] = {
        "hy_oas_bps":           _safe_get(stage1, "risk_report", "credit_spread_us_hy", "current_bps"),
        "hy_oas_momentum":      _safe_get(stage1, "risk_report", "credit_spread_us_hy", "momentum_zscore"),
        "credit_quality_bps":   _safe_get(stage1, "risk_report", "credit_quality", "quality_spread_bps"),
        "funding_bps":          _safe_get(stage1, "risk_report", "funding_stress", "spread_bps"),
        "gz_ebp":               gz_ebp,
        "kr_corp_spread_bps":   kr_corp_spread,
        "corporate_distress":   corporate_distress,
        "dovish_bias":          dovish_bias,
    }
    weights: dict[str, float] = {
        "hy_oas_bps":         0.20,
        "hy_oas_momentum":    0.15,
        "credit_quality_bps": 0.10,
        "funding_bps":        0.10,
        "gz_ebp":             0.20,   # NEW
        "kr_corp_spread_bps": 0.10,   # NEW (KR coverage)
        "corporate_distress": 0.10,
        "dovish_bias":        0.05,
    }
    return _aggregate("F5_credit_cycle", components_raw, weights, mode=mode)
```

- [ ] **Step 3: Test + commit**

Add minimal test verifying GZ EBP shift → F5 positive. Commit:
```bash
git commit -m "feat(tier0): F5 reform — GZ EBP + KR corp spread"
```

---

### Task 5.6: F6 reform (krw_6m_pct + REER + normalized foreign_flow)

**Files:** factor_estimators.py, factor_baselines.py

- [ ] **Step 1: Baselines**

```python
# remove ("F6_krw_regime", "krw_level") line
("F6_krw_regime", "krw_change_6m_pct"): (0.0, 5.0),    # 6m change mean ~0%, sd ~5%
("F6_krw_regime", "krw_reer"):           (100.0, 5.0), # BIS REER mean 100, sd 5
# update foreign_flow_z → use normalized
("F6_krw_regime", "foreign_flow_normalized"): (0.0, 0.005),  # mean ~0, sd ~0.5%
```

- [ ] **Step 2: Update compute_krw_regime**

```python
def compute_krw_regime(stage1: Any, mode: FactorMode = "production") -> FactorScore:
    """F6 krw_regime — +z = weaker KRW.

    Tier 0 reform (Engel-West 2005 random walk fix):
    - REMOVED: krw_level (raw I(1) → spurious regression risk)
    - ADDED:   krw_change_6m_pct, krw_reer
    - foreign_flow: normalized by KOSPI mcap (Stambaugh 1986 fix)
    """
    krw_6m = _safe_get(stage1, "macro_report", "fx", "krw_change_6m_pct")
    krw_reer = _safe_get(stage1, "macro_report", "fx", "krw_reer")
    foreign_flow_norm = _safe_get(stage1, "macro_report", "foreign_flow", "net_20d_normalized")

    components_raw: dict[str, float | None] = {
        "krw_overnight_pct":        _safe_get(stage1, "news_report", "global_overnight", "krw", "change_pct"),
        "krw_change_6m_pct":        krw_6m,
        "krw_reer":                 krw_reer,
        "kr_us_rate_diff":          _safe_get(stage1, "macro_report", "kr_divergence", "us_kr_rate_gap_bps"),
        "foreign_flow_normalized":  foreign_flow_norm,
        "kr_exports_yoy":           _safe_get(stage1, "macro_report", "kr_export", "yoy_pct"),
        "bok_tone_balance":         _safe_get(stage1, "news_report", "cb_speakers", "bok_tone_balance"),
    }
    weights: dict[str, float] = {
        "krw_overnight_pct":       0.20,
        "krw_change_6m_pct":       0.20,   # NEW
        "krw_reer":                0.10,   # NEW
        "kr_us_rate_diff":         0.15,
        "foreign_flow_normalized": 0.20,   # was foreign_flow_z (KRW units, broken)
        "kr_exports_yoy":          0.05,
        "bok_tone_balance":        0.10,
    }
    return _aggregate("F6_krw_regime", components_raw, weights, mode=mode)
```

- [ ] **Step 3: Test + commit**

Verify F6 doesn't use krw_level. Commit:
```bash
git commit -m "feat(tier0): F6 reform — Engel-West fix (krw 6m %change, REER, foreign_flow_normalized)"
```

---

### Task 5.7: F7 reform (GPR Index)

- [ ] **Step 1: Update baseline + compute_equity_vol_regime**

In `factor_baselines.py`:
```python
# remove ("F7_equity_vol", "geopolitical_surge")
("F7_equity_vol", "gpr_index_zscore"): (0.0, 1.0),   # already z-scored externally
```

In `factor_estimators.py`:
```python
def compute_equity_vol_regime(stage1: Any, mode: FactorMode = "production") -> FactorScore:
    """F7 equity_vol_regime — +z = high vol.

    Tier 0 reform: geopolitical_surge (news count) → Caldara-Iacoviello GPR (quant).
    """
    gpr_z = _safe_get(stage1, "macro_report", "geopolitical_risk", "gpr_zscore_60m")
    # ... existing components: vix_level, vix_z_score, vix_term_ratio, move,
    # realized_vol_60d, skew_change, sentiment_dispersion ...

    components_raw: dict[str, float | None] = {
        "vix_level":            _safe_get(stage1, "risk_report", "vix", "current_value"),
        "vix_z_score":          _safe_get(stage1, "risk_report", "vix", "zscore_30d"),
        "vix_term_ratio":       _safe_get(stage1, "risk_report", "vix_term", "ratio"),
        "move":                 _safe_get(stage1, "macro_report", "tail_risk", "move"),
        "realized_vol_60d":     _safe_get(stage1, "risk_report", "real_vol", "realized_vol_60d"),
        "skew_change":          _safe_get(stage1, "risk_report", "skew", "change_1m_z"),
        "gpr_index_zscore":     gpr_z,
        "sentiment_dispersion": _safe_get(stage1, "news_report", "news_sentiment", "sentiment_dispersion"),
    }
    weights: dict[str, float] = {
        "vix_level":           0.20,
        "vix_z_score":         0.10,
        "vix_term_ratio":      0.10,
        "move":                0.15,
        "realized_vol_60d":    0.13,
        "skew_change":         0.07,
        "gpr_index_zscore":    0.15,   # NEW (replaces geopolitical_surge)
        "sentiment_dispersion":0.10,
    }
    return _aggregate("F7_equity_vol", components_raw, weights, mode=mode)
```

- [ ] **Step 2: Test + commit**

```bash
git commit -m "feat(tier0): F7 reform — Caldara-Iacoviello GPR replaces geopolitical_surge"
```

---

### Task 5.8: F8 reform (US:KR 50:50, CAPE, KOSPI fundamentals)

- [ ] **Step 1: Baselines**

```python
("F8_valuation", "us_cape"):           (20.0, 8.0),     # Shiller CAPE 1881+ mean ~20, sd ~8
("F8_valuation", "kospi_per"):         (13.0, 4.0),     # KOSPI200 PER mean ~13, sd ~4
("F8_valuation", "kospi_div_yield"):   (2.0, 0.8),      # KOSPI div yield mean ~2%, sd ~0.8%
```

- [ ] **Step 2: Update compute_valuation**

```python
def compute_valuation(stage1: Any, mode: FactorMode = "production") -> FactorScore:
    """F8 valuation — +z = expensive.

    Tier 0 reform: US:KR 50:50 balance. KOSPI CAPE → v2 deferral.
    Adds: US Shiller CAPE, KOSPI PER, KOSPI Div Yield.
    """
    sp_pe = fetch_sp_trailing_pe()
    earnings_yield = (100.0 / sp_pe) if (sp_pe and sp_pe > 0) else None

    tips_yield = _safe_get(stage1, "risk_report", "real_yields", "tips_10y")
    erp = (earnings_yield - float(tips_yield)) if (earnings_yield is not None and tips_yield is not None) else None

    us_cape = _safe_get(stage1, "macro_report", "us_equity_valuation", "cape")
    kospi_pbr = _safe_get(stage1, "macro_report", "kr_valuation", "kospi_pbr")
    kospi_per = _safe_get(stage1, "macro_report", "kr_valuation", "kospi_per")
    kospi_div = _safe_get(stage1, "macro_report", "kr_valuation", "kospi_div_yield")
    # Note: kospi_div_yield interpreted *inversely* — high yield = cheap → invert sign
    kospi_div_inv = -float(kospi_div) if kospi_div is not None else None

    components_raw: dict[str, float | None] = {
        "sp_pe":           sp_pe,
        "earnings_yield":  earnings_yield,
        "erp":             erp,
        "us_cape":         us_cape,
        "kospi_pbr":       kospi_pbr,
        "kospi_per":       kospi_per,
        "kospi_div_yield": kospi_div_inv,   # inverted: high yield = cheap
    }
    weights: dict[str, float] = {
        "sp_pe":           0.10,
        "earnings_yield":  0.10,
        "erp":             0.15,
        "us_cape":         0.20,   # NEW (Shiller)
        "kospi_pbr":       0.20,
        "kospi_per":       0.15,   # NEW (was unused)
        "kospi_div_yield": 0.10,   # NEW (was unused)
    }
    return _aggregate("F8_valuation", components_raw, weights, mode=mode)
```

- [ ] **Step 3: Test + commit**

```bash
git commit -m "feat(tier0): F8 reform — US:KR 50:50 (CAPE, KOSPI PER+DivYield activated)"
```

---

### Task 5.9: F9 rename (market_dispersion)

- [ ] **Step 1: Search/replace `F9_liquidity` → `F9_market_dispersion`**

```bash
# Search all references
grep -rn "F9_liquidity" tradingagents/ tests/ docs/ scripts/
```

For each occurrence, rename to `F9_market_dispersion`. Specifically:
- `factor_estimators.py`: rename function `compute_liquidity_regime` → `compute_market_dispersion`; update `_aggregate("F9_liquidity", ...)` call to `_aggregate("F9_market_dispersion", ...)`
- `factor_baselines.py`: rename keys `("F9_liquidity", ...)` → `("F9_market_dispersion", ...)`
- `factor_to_bucket.py`: rename keys in `INITIAL_BETA`, `SIGN_RESTRICTION`
- `compute_all_factors`: update field name to `market_dispersion=...`

- [ ] **Step 2: Test + commit**

```bash
pytest tests/unit/skills/research/test_factor_estimators.py -v
git add -u
git commit -m "feat(tier0): F9 rename liquidity_regime → market_dispersion (Goyal-Santa-Clara 2003 alignment)"
```

---

### Task 5.10: F10 SOFR-TED stitching integration

**Note: F10 stays same in factor terms — only the underlying *funding_stress* component data source changes via stitched fetcher.**

- [ ] **Step 1: Modify market_risk_analyst to use stitched fetcher**

In `market_risk_analyst.py`, where `FundingStressSnapshot` is built:
```python
from tradingagents.dataflows.fred import fetch_funding_stress_stitched

# Replace direct SOFR fetch with stitched (handles pre-2018 via TED proxy)
spread_bps_series = fetch_funding_stress_stitched(start, as_of, as_of_date=as_of)
spread_bps = float(spread_bps_series.iloc[-1]) if not spread_bps_series.empty else 0.0
```

- [ ] **Step 2: Commit**

```bash
git commit -m "feat(tier0): F10 funding_stress uses SOFR-TED stitched series (pre-2018 backtest coverage)"
```

---

### Task 5.11: F11_earnings_revision aggregation module

**Files:**
- Create: `tradingagents/skills/research/earnings_revision.py`
- Create: `data/universe/sp500_constituents.json` (snapshot)
- Create: `tests/unit/skills/research/test_earnings_revision.py`
- Modify: `factor_estimators.py` (add `compute_earnings_revision`)
- Modify: `factor_baselines.py`

- [ ] **Step 1: Create SP500 constituents snapshot**

Save current SP500 ticker list to `data/universe/sp500_constituents.json`:
```bash
python -c "
import yfinance as yf, json
# Use yfinance Tickers (or manually maintain). For initial snapshot:
sp500 = ['AAPL', 'MSFT', 'JPM', 'XOM', 'JNJ', 'AMZN', 'GOOGL', 'META']  # MINIMAL — expand to full 500
with open('data/universe/sp500_constituents.json', 'w') as f:
    json.dump(sp500, f, indent=2)
"
```

> For production: scrape Wikipedia SP500 page or use a maintained source. Document refresh cadence (monthly).

- [ ] **Step 2: Write failing test**

`tests/unit/skills/research/test_earnings_revision.py`:
```python
import pytest
from unittest.mock import patch, MagicMock
from datetime import date
import pandas as pd
from tradingagents.skills.research.earnings_revision import (
    compute_sp500_net_revision, compute_kospi200_net_revision,
)


def test_compute_sp500_net_ratio(monkeypatch):
    """Mock yfinance — 60% upgrades, 40% downgrades over 30d → net = +0.2."""
    def mock_yf_ticker(symbol):
        m = MagicMock()
        m.upgrades_downgrades = pd.DataFrame({
            "Firm": ["A", "B", "C", "D", "E"],
            "Action": ["upgrade", "upgrade", "upgrade", "downgrade", "downgrade"],
        }, index=pd.to_datetime(["2026-05-01"] * 5))
        return m
    with patch("tradingagents.skills.research.earnings_revision.yf.Ticker",
               side_effect=mock_yf_ticker), \
         patch("tradingagents.skills.research.earnings_revision.load_sp500_constituents",
               return_value=["A", "B", "C", "D", "E"]):
        ratio = compute_sp500_net_revision(date(2026, 5, 28))
    assert ratio is not None
    # 5 upgrades-1 downgrades = wait, we have 3 up, 2 down → (3-2)/5 = 0.2
    assert abs(ratio - 0.2) < 0.05


def test_returns_none_when_coverage_low(monkeypatch):
    """Coverage < 50% → return None."""
    def mock_yf_ticker(symbol):
        raise Exception("yfinance fail")
    with patch("tradingagents.skills.research.earnings_revision.yf.Ticker",
               side_effect=mock_yf_ticker), \
         patch("tradingagents.skills.research.earnings_revision.load_sp500_constituents",
               return_value=["A", "B", "C"]):
        result = compute_sp500_net_revision(date(2026, 5, 28))
    assert result is None
```

- [ ] **Step 3: Run test (expect FAIL)**

```bash
pytest tests/unit/skills/research/test_earnings_revision.py -v
```

- [ ] **Step 4: Implement module**

`tradingagents/skills/research/earnings_revision.py`:
```python
"""F11 Earnings Revision Net Ratio aggregation.

Source: yfinance ticker.upgrades_downgrades (SP500) + pykrx PER 1m change (KOSPI200).
Reference: Chan-Jegadeesh-Lakonishok 1996 JF, Asness-Frazzini-Pedersen 2019.
Backtest coverage: 2010+ (yfinance API limit) — staggered calibration in Tier 2.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Final

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

SP500_CONSTITUENTS_PATH: Final[Path] = Path("data/universe/sp500_constituents.json")


def load_sp500_constituents() -> list[str]:
    """Load SP500 ticker list from snapshot file."""
    if not SP500_CONSTITUENTS_PATH.exists():
        logger.warning("SP500 constituents file missing: %s", SP500_CONSTITUENTS_PATH)
        return []
    with open(SP500_CONSTITUENTS_PATH) as f:
        return json.load(f)


def compute_sp500_net_revision(
    as_of: date, lookback_days: int = 30, coverage_threshold: float = 0.5,
) -> float | None:
    """SP500 net revision proxy via yfinance upgrades_downgrades.

    For each constituent: count upgrade vs downgrade actions in last `lookback_days`.
    Aggregated net_ratio = (Σ up - Σ down) / Σ total, clipped to [-1, +1].
    Returns None if coverage (valid tickers / total) < `coverage_threshold`.
    """
    constituents = load_sp500_constituents()
    if not constituents:
        return None
    cutoff = pd.Timestamp(as_of) - pd.Timedelta(days=lookback_days)
    total_up, total_down, n_valid = 0, 0, 0
    for ticker in constituents:
        try:
            ud = yf.Ticker(ticker).upgrades_downgrades
            if ud is None or ud.empty:
                continue
            ud_idx = ud.index if isinstance(ud.index, pd.DatetimeIndex) else pd.to_datetime(ud.index)
            recent = ud[ud_idx >= cutoff]
            ups = (recent["Action"].astype(str).str.lower() == "upgrade").sum()
            downs = (recent["Action"].astype(str).str.lower() == "downgrade").sum()
            if ups + downs > 0:
                total_up += int(ups)
                total_down += int(downs)
                n_valid += 1
        except Exception as e:
            logger.debug("yfinance %s skip: %s", ticker, e)
            continue
    if n_valid < len(constituents) * coverage_threshold:
        return None
    total = total_up + total_down
    return (total_up - total_down) / total if total > 0 else 0.0


def compute_kospi200_net_revision(as_of: date) -> float | None:
    """KOSPI200 forward EPS implied 1m change via pykrx fundamentals.

    EPS_forward = price / PER (implied trailing). +1m change > 0 = upward revision.
    Aggregated as ratio of (n_up - n_down) / total over KOSPI200.
    """
    try:
        from pykrx import stock as pkstock
    except ImportError:
        logger.warning("pykrx not available — KOSPI net_revision returns None")
        return None
    month_ago = as_of - timedelta(days=30)
    try:
        today_fund = pkstock.get_market_fundamental_by_date(
            as_of.strftime("%Y%m%d"), as_of.strftime("%Y%m%d"), market="KOSPI"
        )
        prior_fund = pkstock.get_market_fundamental_by_date(
            month_ago.strftime("%Y%m%d"), month_ago.strftime("%Y%m%d"), market="KOSPI"
        )
        kospi200 = pkstock.get_index_portfolio_deposit_file("1028")
    except Exception as e:
        logger.warning("pykrx fetch failed: %s", e)
        return None

    n_up, n_down, n_valid = 0, 0, 0
    for ticker in kospi200:
        if ticker not in today_fund.index or ticker not in prior_fund.index:
            continue
        t_per = today_fund.loc[ticker, "PER"]
        p_per = prior_fund.loc[ticker, "PER"]
        if not (t_per > 0 and p_per > 0):
            continue
        # Forward EPS = 1/PER. Lower PER (same price) = higher EPS = upward revision.
        eps_pct_change = (1.0 / t_per - 1.0 / p_per) / (1.0 / p_per)
        if eps_pct_change > 0.01:
            n_up += 1
        elif eps_pct_change < -0.01:
            n_down += 1
        n_valid += 1
    if n_valid < 100:  # < 50% of 200
        return None
    total = n_up + n_down
    return (n_up - n_down) / total if total > 0 else 0.0
```

Add `compute_earnings_revision` to `factor_estimators.py`:
```python
def compute_earnings_revision(stage1: Any, mode: FactorMode = "production") -> FactorScore:
    """F11 earnings_revision — +z = upward revisions dominate.

    Tier 0 NEW factor (staggered, 2010+).
    """
    sp = _safe_get(stage1, "macro_report", "earnings_revision", "sp500_net_revision")
    ks = _safe_get(stage1, "macro_report", "earnings_revision", "kospi200_net_revision")
    components_raw: dict[str, float | None] = {
        "sp500_net_revision":    sp,
        "kospi200_net_revision": ks,
    }
    weights: dict[str, float] = {
        "sp500_net_revision":    0.50,
        "kospi200_net_revision": 0.50,
    }
    return _aggregate("F11_earnings_revision", components_raw, weights, mode=mode)
```

Add baselines:
```python
("F11_earnings_revision", "sp500_net_revision"):    (0.0, 0.3),  # net ratio mean 0, sd ~0.3
("F11_earnings_revision", "kospi200_net_revision"): (0.0, 0.3),
```

- [ ] **Step 5: Run tests; commit**

```bash
pytest tests/unit/skills/research/test_earnings_revision.py -v
git add tradingagents/skills/research/earnings_revision.py tradingagents/skills/research/factor_estimators.py tradingagents/skills/research/factor_baselines.py data/universe/sp500_constituents.json tests/unit/skills/research/test_earnings_revision.py
git commit -m "feat(tier0): F11 earnings_revision via yfinance upgrades_downgrades + pykrx KOSPI PER"
```

---

### Task 5.12: F12_china_credit_impulse calculation module

**Files:**
- Create: `tradingagents/skills/research/china_credit_impulse.py`
- Create: `tests/unit/skills/research/test_china_credit_impulse.py`
- Modify: `factor_estimators.py` (add `compute_china_credit_impulse_factor`)
- Modify: `factor_baselines.py`

- [ ] **Step 1: Write failing test**

`tests/unit/skills/research/test_china_credit_impulse.py`:
```python
import pytest
from unittest.mock import patch
from datetime import date
import pandas as pd
from tradingagents.skills.research.china_credit_impulse import (
    compute_china_credit_impulse,
)


def test_biggs_mayer_pick_formula(monkeypatch):
    # ratio_t = 230, ratio_{t-1} = 228, ratio_{t-4} = 220, ratio_{t-5} = 218
    # Δ_t = 230 - 228 = 2
    # Δ_{t-4} = 220 - 218 = 2
    # impulse = (Δ_t - Δ_{t-4}) / ratio_{t-4} × 100 = (2-2)/220 × 100 = 0
    series = pd.Series(
        [218.0, 220.0, 222.0, 224.0, 228.0, 230.0],
        index=pd.to_datetime([
            "2025-09-30", "2025-12-31", "2026-03-31",
            "2026-06-30", "2026-09-30", "2026-12-31"
        ]),
    )
    with patch("tradingagents.skills.research.china_credit_impulse.fetch_bis_china_credit",
               return_value=series):
        result = compute_china_credit_impulse(date(2026, 12, 31))
    assert result is not None
    assert abs(result["impulse"]) < 0.5
    assert result["ratio"] == 230.0


def test_insufficient_history_returns_none(monkeypatch):
    series = pd.Series([220.0], index=pd.to_datetime(["2026-12-31"]))
    with patch("tradingagents.skills.research.china_credit_impulse.fetch_bis_china_credit",
               return_value=series):
        result = compute_china_credit_impulse(date(2026, 12, 31))
    assert result is None
```

- [ ] **Step 2: Run test (expect FAIL)**

```bash
pytest tests/unit/skills/research/test_china_credit_impulse.py -v
```

- [ ] **Step 3: Implement**

`tradingagents/skills/research/china_credit_impulse.py`:
```python
"""F12 China Credit Impulse calculation.

Reference: Biggs-Mayer-Pick 2010 JMCB "Credit and Economic Recovery".
Formula: CI(t) = (Δ_t - Δ_{t-4}) / credit_{t-4} × 100
         where Δ_t = credit_to_gdp_t - credit_to_gdp_{t-1}

Source: BIS Total Credit Q:CN:P:A:M:770:A (quarterly, % of GDP).
"""
from __future__ import annotations

import logging
from datetime import date

from tradingagents.dataflows.bis_credit import fetch_bis_china_credit

logger = logging.getLogger(__name__)


def compute_china_credit_impulse(as_of: date) -> dict[str, float] | None:
    """Compute Biggs-Mayer-Pick credit impulse for China.

    Returns dict with keys:
      - 'impulse': credit impulse (%)
      - 'ratio':   raw credit/GDP ratio (%)
      - 'yoy':     credit-to-GDP YoY % change (1st diff helper)

    None if insufficient history (< 6 quarters for 4-lag + diff).
    """
    try:
        series = fetch_bis_china_credit(as_of=as_of)
    except Exception as e:
        logger.warning("BIS fetch failed: %s", e)
        return None
    if series is None or len(series) < 6:
        return None

    # Most recent 6 observations
    s = series.tail(6).values
    # s = [ratio_{t-5}, ratio_{t-4}, ratio_{t-3}, ratio_{t-2}, ratio_{t-1}, ratio_{t}]
    delta_t = s[-1] - s[-2]
    delta_t_minus_4 = s[-5] - s[-6]
    credit_t_minus_4 = s[-5]
    if credit_t_minus_4 == 0:
        return None
    impulse = (delta_t - delta_t_minus_4) / credit_t_minus_4 * 100.0
    # YoY %
    yoy = (s[-1] / s[-5] - 1.0) * 100.0 if s[-5] != 0 else 0.0
    return {
        "impulse": float(impulse),
        "ratio":   float(s[-1]),
        "yoy":     float(yoy),
    }
```

Add `compute_china_credit_impulse_factor` to `factor_estimators.py`:
```python
def compute_china_credit_impulse_factor(
    stage1: Any, mode: FactorMode = "production",
) -> FactorScore:
    """F12 china_credit_impulse — +z = accelerating credit (Biggs-Mayer-Pick).

    Tier 0 NEW factor.
    """
    impulse = _safe_get(stage1, "macro_report", "china_credit_impulse", "credit_impulse")
    yoy = _safe_get(stage1, "macro_report", "china_credit_impulse", "credit_yoy_pct")
    iron_ore_3m = _safe_get(stage1, "macro_report", "china_leading", "iron_ore_change_3m_pct")
    components_raw: dict[str, float | None] = {
        "credit_impulse":   impulse,
        "credit_yoy_pct":   yoy,
        "iron_ore_3m_pct":  iron_ore_3m,
    }
    weights: dict[str, float] = {
        "credit_impulse":   0.60,
        "credit_yoy_pct":   0.30,
        "iron_ore_3m_pct":  0.10,
    }
    return _aggregate("F12_china_credit_impulse", components_raw, weights, mode=mode)
```

Add baselines:
```python
("F12_china_credit_impulse", "credit_impulse"):  (0.0, 2.0),
("F12_china_credit_impulse", "credit_yoy_pct"):  (5.0, 5.0),
("F12_china_credit_impulse", "iron_ore_3m_pct"): (0.0, 15.0),
```

- [ ] **Step 4: Run tests; commit**

```bash
pytest tests/unit/skills/research/test_china_credit_impulse.py -v
git add tradingagents/skills/research/china_credit_impulse.py tradingagents/skills/research/factor_estimators.py tradingagents/skills/research/factor_baselines.py tests/unit/skills/research/test_china_credit_impulse.py
git commit -m "feat(tier0): F12 china_credit_impulse — Biggs-Mayer-Pick 2010 (BIS data)"
```

---

### Task 5.13: compute_all_factors integration

- [ ] **Step 1: Update compute_all_factors**

```python
def compute_all_factors(stage1: Any, mode: FactorMode = "production") -> FactorScores:
    """Compute all 12 factors. Returns FactorScores with None for unavailable (e.g. F11 pre-2010)."""
    return FactorScores(
        growth_surprise=compute_growth_surprise(stage1, mode=mode),
        inflation_surprise=compute_inflation_surprise(stage1, mode=mode),
        real_rate=compute_real_rate(stage1, mode=mode),
        term_premium=compute_term_premium(stage1, mode=mode),
        credit_cycle=compute_credit_cycle(stage1, mode=mode),
        krw_regime=compute_krw_regime(stage1, mode=mode),
        equity_vol_regime=compute_equity_vol_regime(stage1, mode=mode),
        valuation=compute_valuation(stage1, mode=mode),
        market_dispersion=compute_market_dispersion(stage1, mode=mode),
        systemic_liquidity=compute_systemic_liquidity(stage1, mode=mode),
        earnings_revision=_safely(compute_earnings_revision, stage1, mode),
        china_credit_impulse=_safely(compute_china_credit_impulse_factor, stage1, mode),
    )


def _safely(fn, stage1, mode):
    """Run factor compute; None on hard failure (snapshot absent etc.)."""
    try:
        score = fn(stage1, mode=mode)
        # If confidence=0 (all components missing), treat as None for to_dict skip
        return score if score.confidence > 0 else None
    except Exception as e:
        logger.warning("%s failed: %s", fn.__name__, e)
        return None
```

- [ ] **Step 2: Run all factor tests; commit**

```bash
pytest tests/unit/skills/research/test_factor_estimators.py -v
git add tradingagents/skills/research/factor_estimators.py
git commit -m "feat(tier0): compute_all_factors → 12 factors with safe-None for F11/F12"
```

---

## Phase 6: Sign Restriction (SIGN_RESTRICTION dict update)

### Task 6.1: Remove 3 sign restrictions

**Files:**
- Modify: `tradingagents/skills/research/factor_to_bucket.py`
- Modify: `tests/unit/skills/research/test_factor_to_bucket.py`

> Note: This SIGN_RESTRICTION update for 8-bucket schema is **Tier 1's responsibility**. Tier 0 only handles the 5-bucket → still-5-bucket cleanup (since Tier 0 keeps current buckets). The 3 removals (F5×precious, F7×gl_dur, F7×precious) make sense in **8-bucket context** (Tier 1) — for now in Tier 0, just remove F5×precious_metals if it exists in current 5-bucket schema, otherwise this task is **deferred to Tier 1**.

- [ ] **Step 1: Check current SIGN_RESTRICTION dict**

```bash
grep -A 40 "SIGN_RESTRICTION" tradingagents/skills/research/factor_to_bucket.py | head -50
```

- [ ] **Step 2: If precious_metals not in current 5-bucket sign restrictions, defer to Tier 1**

If current dict has no `precious_metals` entries (5-bucket has fx_commodity instead), commit a no-op marker:

```bash
# No code change needed in Tier 0; Tier 1 handles sign restrictions for 8-bucket schema.
echo "Tier 0 sign restriction changes deferred to Tier 1 (depends on 8-bucket schema)" >> docs/superpowers/plans/tier0-notes.md
```

> If current 5-bucket dict happens to have any F5/F7 entries that contradict dash-for-cash logic, remove them now.

- [ ] **Step 3: Commit notes**

```bash
git add docs/superpowers/plans/tier0-notes.md
git commit -m "chore(tier0): defer SIGN_RESTRICTION reform to Tier 1 (8-bucket schema)"
```

---

## Phase 7: Reliability Tier Update

### Task 7.1: Add reliability tier for 14 new components

**Files:**
- Modify: `tradingagents/skills/research/factor_reliability_audit.py`

- [ ] **Step 1: Add entries**

In `COMPONENT_RELIABILITY` dict, add:
```python
    # === Tier 0 (2026-05-28) new components ===
    "indpro_yoy":           "high",
    "real_pce_yoy":         "high",
    "acm_term_premium_10y": "high",
    "gz_ebp":               "high",
    "kr_corp_spread_bps":   "high",
    "krw_change_6m_pct":    "high",
    "krw_reer":             "high",
    "foreign_flow_normalized": "high",
    "us_cape":              "medium-high",
    "kospi_per":            "high",
    "kospi_div_yield":      "high",
    "gpr_index_zscore":     "high",
    "sp500_net_revision":   "medium",       # yfinance partial
    "kospi200_net_revision":"medium",       # pykrx PER implied (not true forward)
    "credit_impulse":       "high",
    "credit_yoy_pct":       "high",
    "iron_ore_3m_pct":      "medium",
```

Update AUDIT_DATE: `AUDIT_DATE: Final[str] = "2026-05-28"`.

- [ ] **Step 2: Commit**

```bash
git add tradingagents/skills/research/factor_reliability_audit.py
git commit -m "feat(tier0): reliability tier — 14 new component entries + audit date refresh"
```

---

## Phase 8: Expanding Window Z-Baseline

### Task 8.1: factor_baselines_dynamic module skeleton + dispatch table

**Files:**
- Create: `tradingagents/skills/research/factor_baselines_dynamic.py`
- Create: `tests/unit/skills/research/test_factor_baselines_dynamic.py`

- [ ] **Step 1: Write failing test**

```python
import pytest
from datetime import date
from unittest.mock import patch
import pandas as pd
from tradingagents.skills.research.factor_baselines_dynamic import (
    compute_expanding_baseline, COMPONENT_HISTORY_SOURCES,
)


def test_dispatch_table_has_known_components():
    assert "cfnai" in COMPONENT_HISTORY_SOURCES
    assert "us_cape" in COMPONENT_HISTORY_SOURCES
    assert "credit_impulse" in COMPONENT_HISTORY_SOURCES


def test_compute_expanding_baseline_unknown_falls_back_to_static(monkeypatch):
    """Unknown component → static LONG_RUN_BASELINE fallback."""
    result = compute_expanding_baseline("nonexistent_component", "F1_growth", date(2020, 1, 1))
    # Static fallback may also return None if no static entry, but should not raise.
    assert result is None or isinstance(result, tuple)


def test_compute_expanding_baseline_short_history_falls_back(monkeypatch):
    """n < 60 → static fallback."""
    short_series = pd.Series(
        [0.5, 0.6], index=pd.to_datetime(["2025-01-01", "2025-02-01"]),
    )
    def mock_fetcher(start, end):
        return short_series
    monkeypatch.setitem(COMPONENT_HISTORY_SOURCES, "test_comp",
                         ("test", mock_fetcher))
    # Static baseline lookup for unknown ('test_comp', 'F1_growth') → None
    result = compute_expanding_baseline("test_comp", "F1_growth", date(2025, 3, 1))
    # Short history → fallback. (No static entry → None.)
    assert result is None
```

- [ ] **Step 2: Run test (expect FAIL)**

```bash
pytest tests/unit/skills/research/test_factor_baselines_dynamic.py -v
```

- [ ] **Step 3: Implement skeleton**

`tradingagents/skills/research/factor_baselines_dynamic.py`:
```python
"""Expanding window z-score normalization (Pesaran-Timmermann 1995 JF).

Replaces static LONG_RUN_BASELINE with time-honest expanding mean/sd.
Per-component dispatch table maps component → (source_type, fetcher_callable).

Cache: data/cache/factor_history/{component}.parquet, weekly TTL.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Final

import pandas as pd

from tradingagents.skills.research.factor_baselines import get_baseline

logger = logging.getLogger(__name__)

CACHE_DIR: Final[Path] = Path("data/cache/factor_history")
CACHE_TTL_DAYS: Final[int] = 7
MIN_HISTORY_POINTS: Final[int] = 60


def _yoy_pct(series: pd.Series) -> pd.Series:
    return (series / series.shift(12) - 1.0) * 100


def _pct_change_n(series: pd.Series, n: int) -> pd.Series:
    return (series / series.shift(n) - 1.0) * 100


def _zscore_30d(series: pd.Series) -> pd.Series:
    return (series - series.rolling(30).mean()) / series.rolling(30).std()


def _zscore_60m(series: pd.Series) -> pd.Series:
    return (series - series.rolling(60).mean()) / series.rolling(60).std()


# --- Dispatch table (component → fetcher) ---
# Populated lazily to avoid circular imports.
COMPONENT_HISTORY_SOURCES: dict[str, tuple[str, Callable]] = {}


def _register_default_sources() -> None:
    """Populate dispatch table with known component fetchers.

    Called on first compute_expanding_baseline call to defer imports.
    """
    if COMPONENT_HISTORY_SOURCES:
        return  # already registered
    from tradingagents.dataflows import fred
    from tradingagents.dataflows import shiller_cape, gpr_index, gz_ebp, bis_credit

    COMPONENT_HISTORY_SOURCES.update({
        # FRED direct
        "cfnai":    ("fred", lambda s, e: fred.fetch_fred_series("us_cfnai", s, e)),
        "cfnai_3m": ("fred", lambda s, e: fred.fetch_fred_series("us_cfnai_ma3", s, e)),
        "vix_level":("fred", lambda s, e: fred.fetch_fred_series("vix_close", s, e)),
        "move":     ("fred", lambda s, e: fred.fetch_fred_series("move", s, e)),
        "tips_yield": ("fred", lambda s, e: fred.fetch_fred_series("us_tips_10y", s, e)),
        "acm_term_premium_10y": ("fred", lambda s, e: fred.fetch_fred_series("us_acm_term_premium_10y", s, e)),
        "five_y_five_y":  ("fred", lambda s, e: fred.fetch_fred_series("us_5y5y_breakeven", s, e)),
        "michigan_1y":    ("fred", lambda s, e: fred.fetch_fred_series("us_michigan_1y", s, e)),
        "gz_ebp":         ("fed_board", lambda s, e: gz_ebp.fetch_gz_ebp(as_of=e)[s:e]),
        "us_cape":        ("shiller", lambda s, e: shiller_cape.fetch_shiller_cape(as_of=e)[s:e]),
        "gpr_index_zscore": ("iacoviello_derived",
                              lambda s, e: _zscore_60m(gpr_index.fetch_gpr_index("monthly", as_of=e)[s:e])),
        # FRED derived
        "indpro_yoy":     ("fred_derived", lambda s, e: _yoy_pct(fred.fetch_fred_series("us_indpro", s, e))),
        "real_pce_yoy":   ("fred_derived", lambda s, e: _yoy_pct(fred.fetch_fred_series("us_real_pce", s, e))),
        "krw_change_6m_pct": ("fred_derived",
                               lambda s, e: _pct_change_n(fred.fetch_fred_series("usd_krw", s, e), 126)),
        "krw_reer":       ("fred", lambda s, e: fred.fetch_fred_series("kr_reer", s, e)),
        # BIS derived
        "credit_impulse": ("bis_derived",
                            lambda s, e: bis_credit.fetch_bis_china_credit(as_of=e)[s:e]),
        # Add others as needed during implementation. Unknown components → static fallback.
    })


def _cache_path(component: str) -> Path:
    return CACHE_DIR / f"{component}.parquet"


def _read_cache(component: str, start: date, end: date) -> pd.Series | None:
    path = _cache_path(component)
    if not path.exists():
        return None
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    if (datetime.now() - mtime).days >= CACHE_TTL_DAYS:
        return None
    df = pd.read_parquet(path)
    if "value" not in df.columns:
        return None
    s = df.set_index(df.columns[0])["value"]
    s.index = pd.to_datetime(s.index)
    return s[(s.index >= pd.Timestamp(start)) & (s.index <= pd.Timestamp(end))]


def _write_cache(component: str, series: pd.Series) -> None:
    path = _cache_path(component)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = series.rename("value").reset_index()
    df.columns = ["date", "value"]
    df.to_parquet(path, index=False)


def _fetch_with_cache(component: str, start: date, end: date) -> pd.Series | None:
    cached = _read_cache(component, start, end)
    if cached is not None and len(cached) > 0:
        return cached
    if component not in COMPONENT_HISTORY_SOURCES:
        return None
    _, fetcher = COMPONENT_HISTORY_SOURCES[component]
    try:
        series = fetcher(start, end)
        if series is not None and len(series) > 0:
            _write_cache(component, series)
        return series
    except Exception as e:
        logger.warning("factor_baselines_dynamic fetch %s: %s", component, e)
        return None


def compute_expanding_baseline(
    component: str,
    factor: str,
    as_of_date: date,
    history_start: date = date(1971, 1, 1),
) -> tuple[float, float] | None:
    """Expanding-window (mean, sd) for a (factor, component) as of date.

    Returns None if:
      - component not in dispatch table → static fallback
      - fetch fails → static fallback
      - n < 60 → static fallback
    Static fallback via get_baseline(factor, component) in factor_baselines.py.
    """
    _register_default_sources()
    if component not in COMPONENT_HISTORY_SOURCES:
        return get_baseline(factor, component)
    series = _fetch_with_cache(component, history_start, as_of_date)
    if series is None or len(series) < MIN_HISTORY_POINTS:
        return get_baseline(factor, component)
    s_clean = series.dropna()
    return float(s_clean.mean()), float(s_clean.std(ddof=1))


__all__ = [
    "compute_expanding_baseline",
    "COMPONENT_HISTORY_SOURCES",
    "CACHE_DIR",
    "MIN_HISTORY_POINTS",
]
```

- [ ] **Step 4: Run tests; commit**

```bash
pytest tests/unit/skills/research/test_factor_baselines_dynamic.py -v
git add tradingagents/skills/research/factor_baselines_dynamic.py tests/unit/skills/research/test_factor_baselines_dynamic.py
git commit -m "feat(tier0): factor_baselines_dynamic — expanding window + dispatch table + parquet cache"
```

---

### Task 8.2: Regime-aware funding stress baseline (SOFR-TED)

- [ ] **Step 1: Add helper to factor_baselines_dynamic**

```python
def compute_expanding_baseline_funding_stress(as_of_date: date) -> tuple[float, float]:
    """Regime-aware: pre-2018-04-03 uses TED moments, post uses SOFR-Tbill moments.

    Reason: TED (~30bps mean) and SOFR-Tbill (~5bps mean) have different scales —
    unified mean/sd would bias z-scores in either regime.
    """
    from tradingagents.dataflows import fred
    if as_of_date < date(2018, 4, 3):
        ted = fred.fetch_fred_series("ted_spread", date(1986, 1, 1), as_of_date)
        if len(ted) < MIN_HISTORY_POINTS:
            return (30.0, 30.0)  # static prior
        return float(ted.mean()), float(ted.std(ddof=1))
    else:
        from tradingagents.dataflows.fred import fetch_funding_stress_stitched
        s = fetch_funding_stress_stitched(date(2018, 4, 3), as_of_date)
        if len(s) < MIN_HISTORY_POINTS:
            return (5.0, 10.0)
        return float(s.mean()), float(s.std(ddof=1))
```

In `compute_expanding_baseline`, route `funding_bps` to this special case:
```python
def compute_expanding_baseline(component, factor, as_of_date, history_start=date(1971,1,1)):
    if component == "funding_bps":
        return compute_expanding_baseline_funding_stress(as_of_date)
    # ... rest unchanged
```

- [ ] **Step 2: Add test**

```python
def test_funding_stress_uses_ted_baseline_pre_2018(monkeypatch):
    ted = pd.Series([28.0, 32.0, 30.0] * 30, 
                     index=pd.date_range("2010-01-01", periods=90, freq="D"))
    with patch("tradingagents.dataflows.fred.fetch_fred_series", return_value=ted):
        mean, sd = compute_expanding_baseline("funding_bps", "F10_systemic_liquidity",
                                                date(2015, 1, 1))
    assert abs(mean - 30.0) < 2.0
```

- [ ] **Step 3: Run; commit**

```bash
pytest tests/unit/skills/research/test_factor_baselines_dynamic.py::test_funding_stress_uses_ted_baseline_pre_2018 -v
git commit -am "feat(tier0): regime-aware funding stress baseline (SOFR-TED split)"
```

---

### Task 8.3: Wire expanding baseline into _aggregate

**Files:**
- Modify: `tradingagents/skills/research/factor_estimators.py`

- [ ] **Step 1: Add as_of_date parameter to _aggregate**

```python
def _aggregate(
    factor_name: str,
    components_raw: dict[str, float | None],
    weights: dict[str, float],
    mode: FactorMode = "production",
    as_of_date: date | None = None,         # NEW
    use_dynamic_baseline: bool = False,     # NEW
) -> FactorScore:
    """... existing docstring + Tier 0 note ...

    Tier 0: when use_dynamic_baseline=True + as_of_date given, expanding-window
    z-baseline from factor_baselines_dynamic.compute_expanding_baseline replaces
    static LONG_RUN_BASELINE.
    """
    if mode == "historical":
        components_raw = {
            k: v for k, v in components_raw.items()
            if k not in NEWS_DERIVED_COMPONENTS
            and k not in LIVE_ONLY_QUANT_COMPONENTS
        }

    component_z: dict[str, float] = {}
    used_original_weights: dict[str, float] = {}
    for name, raw in components_raw.items():
        if raw is None:
            continue
        w = weights.get(name, 0.0)
        if w <= 0.0:
            continue
        if use_dynamic_baseline and as_of_date is not None:
            from tradingagents.skills.research.factor_baselines_dynamic import compute_expanding_baseline
            baseline = compute_expanding_baseline(name, factor_name, as_of_date)
            if baseline is not None:
                mean, sd = baseline
                if sd <= 0:
                    z = None
                else:
                    z = (float(raw) - mean) / sd
            else:
                z = z_score(float(raw), factor_name, name)  # static fallback
        else:
            z = z_score(float(raw), factor_name, name)
        if z is None:
            continue
        z = max(-_COMPONENT_Z_CLIP, min(_COMPONENT_Z_CLIP, z))
        component_z[name] = z
        used_original_weights[name] = w

    # ... rest unchanged (weight cap, renormalize, aggregate, _Z_CAP) ...
```

- [ ] **Step 2: Propagate parameters through compute_*factor functions and compute_all_factors**

Add `as_of_date` parameter (Optional) + `use_dynamic_baseline` to each `compute_*` function and propagate to `_aggregate`.

```python
def compute_all_factors(
    stage1: Any, mode: FactorMode = "production",
    as_of_date: date | None = None,
    use_dynamic_baseline: bool = False,
) -> FactorScores:
    kwargs = {"mode": mode, "as_of_date": as_of_date, "use_dynamic_baseline": use_dynamic_baseline}
    return FactorScores(
        growth_surprise=compute_growth_surprise(stage1, **kwargs),
        # ... all other factors with **kwargs ...
    )
```

> Apply same pattern to each `compute_*` function — accept and propagate to `_aggregate`.

- [ ] **Step 3: Test**

```python
def test_aggregate_uses_dynamic_baseline_when_enabled(monkeypatch):
    from tradingagents.skills.research.factor_estimators import _aggregate
    # Force dynamic baseline mock to return (5.0, 2.0) for cfnai
    def mock_dynamic(name, factor, as_of):
        if name == "cfnai":
            return (5.0, 2.0)
        return None
    with patch("tradingagents.skills.research.factor_baselines_dynamic.compute_expanding_baseline",
               side_effect=mock_dynamic):
        result = _aggregate(
            "F1_growth",
            components_raw={"cfnai": 7.0},
            weights={"cfnai": 1.0},
            mode="historical",
            as_of_date=date(2020, 1, 1),
            use_dynamic_baseline=True,
        )
    # z = (7 - 5) / 2 = 1.0
    assert abs(result.z_score - 1.0) < 0.1
```

- [ ] **Step 4: Run + commit**

```bash
pytest tests/unit/skills/research/test_factor_estimators.py::test_aggregate_uses_dynamic_baseline_when_enabled -v
git add tradingagents/skills/research/factor_estimators.py tests/unit/skills/research/test_factor_estimators.py
git commit -m "feat(tier0): _aggregate + compute_* accept use_dynamic_baseline + as_of_date"
```

---

## Phase 9: Integration

### Task 9.1: research_manager wiring (live mode)

**Files:**
- Modify: `tradingagents/agents/managers/research_manager.py`

- [ ] **Step 1: Update factor model call**

Locate `compute_all_factors` call in `research_manager.py`. Update:
```python
# Live mode: dynamic baseline can be enabled via config
use_dynamic = state.get("use_dynamic_baseline", False)
as_of = state.get("as_of_date")
as_of_date = datetime.strptime(as_of, "%Y-%m-%d").date() if as_of else None

factor_scores = compute_all_factors(
    stage1=state, mode="production",
    as_of_date=as_of_date, use_dynamic_baseline=use_dynamic,
)
factor_z = factor_scores.to_dict()
bucket, tips_share, contributions, safety_diag = apply_factor_model_with_safety(factor_z)
```

- [ ] **Step 2: Add config flag**

In `tradingagents/default_config.py`:
```python
DEFAULT_CONFIG = {
    # ... existing ...
    "use_dynamic_baseline": False,  # Tier 0: opt-in expanding window z
}
```

- [ ] **Step 3: Run E2E smoke test**

```bash
python scripts/run_e2e_test.py --as-of 2026-05-28 2>&1 | tail -20
```

Expected: No exceptions. Factor model runs with 12 factors. F11/F12 may be None.

- [ ] **Step 4: Commit**

```bash
git add tradingagents/agents/managers/research_manager.py tradingagents/default_config.py
git commit -m "feat(tier0): research_manager wires 12-factor + dynamic baseline opt-in"
```

---

### Task 9.2: Final integration test

**Files:**
- Create: `tests/integration/test_tier0_pipeline.py`

- [ ] **Step 1: Write integration test**

```python
"""Tier 0 end-to-end smoke test: build minimal stage1 → 12-factor scores."""
import pytest
from datetime import date
from tradingagents.skills.research.factor_estimators import compute_all_factors


@pytest.fixture
def stage1_minimal():
    """Build minimal mock stage1 with all required + Tier 0 new snapshots."""
    # Reuse existing fixture builder. Pattern: build MacroReport + RiskReport + etc.
    # with default-valued required fields and None for Tier 0 Optional fields.
    pass  # IMPLEMENT against current fixture builder utilities


def test_compute_all_factors_returns_12_or_fewer(stage1_minimal):
    fs = compute_all_factors(stage1_minimal, mode="production")
    d = fs.to_dict()
    assert "F1_growth" in d
    assert "F9_market_dispersion" in d
    # F10/F11/F12 may be None if snapshots absent — both behaviors OK
    assert len(d) >= 9 and len(d) <= 12


def test_historical_mode_drops_news_and_gdpnow(stage1_minimal):
    fs = compute_all_factors(stage1_minimal, mode="historical")
    # F1 component_weights should not include news_* keys or gdpnow
    f1_keys = set(fs.growth_surprise.component_weights.keys())
    assert "gdpnow" not in f1_keys
    assert not any(k in f1_keys for k in ["release_surprise", "hawkish_bias"])
```

- [ ] **Step 2: Run + commit**

```bash
pytest tests/integration/test_tier0_pipeline.py -v
git add tests/integration/test_tier0_pipeline.py
git commit -m "test(tier0): integration — 12-factor compute + mode behavior"
```

---

## Acceptance Checklist

- [ ] All 4 new external fetcher modules tested + parsing accurate against live URLs
- [ ] FRED 5 new series present in `FRED_SERIES` dict with publication_lag_days
- [ ] SOFR-TED stitched fetcher correct boundary (2018-04-03)
- [ ] 8 new schemas (CommodityMomentum, USEquityValuation, GPR, ChinaCreditImpulse, EarningsRevision, ExcessBondPremium, FXSnapshot extensions, ForeignFlowSnapshot extension) accept fields + Optional default None
- [ ] MacroReport + RiskReport accept new Optional fields
- [ ] macro_quant_analyst fills 5 new MacroReport snapshots
- [ ] market_risk_analyst fills ExcessBondPremium
- [ ] FACTORS tuple = 12 entries with `F9_market_dispersion`
- [ ] FactorScores.to_dict drops None F10/F11/F12
- [ ] NEWS_DERIVED_COMPONENTS removes `geopolitical_surge`
- [ ] LIVE_ONLY_QUANT_COMPONENTS = `{"gdpnow"}`
- [ ] F1 reform: no nfci/curve, indpro/real_pce added
- [ ] F4: ACM term premium component
- [ ] F5: GZ EBP + kr_corp_spread components
- [ ] F6: krw_change_6m + krw_reer + foreign_flow_normalized
- [ ] F7: gpr_index_zscore replaces geopolitical_surge
- [ ] F8: us_cape + kospi_per + kospi_div_yield activated; US:KR ≈ 50:50
- [ ] F10: funding_bps via stitched fetcher
- [ ] F11/F12 new compute functions with `_safely` wrapper for None on failure
- [ ] Reliability tier: 17 new entries + audit date 2026-05-28
- [ ] factor_baselines_dynamic module + dispatch table + parquet cache
- [ ] _aggregate accepts use_dynamic_baseline + as_of_date
- [ ] research_manager passes as_of_date + use_dynamic_baseline
- [ ] Integration test passes

---

**Plan saved to `docs/superpowers/plans/2026-05-28-tier0-factor-model-reform.md`.**
