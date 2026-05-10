import json
import re
from datetime import date
from pathlib import Path
from typing import Literal, Optional

import openpyxl
from pydantic import BaseModel, Field

TICKER_RE = re.compile(r"^A\d{6}[A-Z0-9]?$")


class ETFEntry(BaseModel):
    ticker: str
    name: str
    aum_krw: float = Field(ge=0)
    underlying_index: str
    bucket: Literal["위험", "안전"]
    category: str
    listed_since: Optional[date] = Field(
        default=None,
        description="Listing date — used to filter for backtests with as_of < listed_since",
    )
    delisted_at: Optional[date] = Field(
        default=None,
        description="Delisting date — for survivorship-bias-aware backtests",
    )


class Universe(BaseModel):
    version: str
    etfs: list[ETFEntry]

    def tradable_at(self, as_of: date) -> "Universe":
        """Return a sub-universe of ETFs that were tradable at as_of."""
        tradable: list[ETFEntry] = []
        for e in self.etfs:
            if e.listed_since is not None and e.listed_since > as_of:
                continue
            if e.delisted_at is not None and e.delisted_at <= as_of:
                continue
            tradable.append(e)
        return Universe(version=self.version, etfs=tradable)


def _fetch_listed_since(ticker: str) -> Optional[date]:
    """Best-effort listing date lookup via pykrx. Returns None on failure."""
    try:
        from pykrx import stock
        info = stock.get_etf_isin(ticker)
        if hasattr(info, "상장일"):
            raw = info.상장일
            return date.fromisoformat(str(raw)[:10])
        return None
    except Exception:
        return None


def sync_from_xlsx(
    xlsx_path: Path, out_path: Path,
    fetch_listing_dates: bool = False,
) -> Universe:
    """Parse the GAPS xlsx and write a normalized JSON.

    Args:
        fetch_listing_dates: If True, call pykrx for each ticker to populate
            listed_since. Adds ~60s. Default False (skip for fast iteration).
    """
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.active

    etfs: list[ETFEntry] = []
    rows = list(ws.iter_rows(values_only=True))

    header_idx = None
    for i, row in enumerate(rows):
        if row and "티커" in row:
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("xlsx missing '티커' header row")

    for row in rows[header_idx + 1:]:
        if not row or row[1] is None:
            continue
        ticker = str(row[1]).strip()
        if not TICKER_RE.match(ticker):
            raise ValueError(f"invalid ticker: {ticker!r}")
        aum_krw = float(row[3] or 0) * 1e8
        listed_since = _fetch_listed_since(ticker) if fetch_listing_dates else None
        etfs.append(ETFEntry(
            ticker=ticker,
            name=str(row[2] or "").strip(),
            aum_krw=aum_krw,
            underlying_index=str(row[4] or "").strip(),
            bucket=str(row[5] or "").strip(),  # type: ignore
            category=str(row[6] or "").strip(),
            listed_since=listed_since,
            delisted_at=None,
        ))

    universe = Universe(version=date.today().isoformat(), etfs=etfs)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(universe.model_dump_json(indent=2), encoding="utf-8")
    return universe


def load_universe(path: Path) -> Universe:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return Universe.model_validate(payload)
