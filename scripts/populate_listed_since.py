"""One-shot: data/universe.json 의 listed_since 를 채움.

배경:
  pykrx 1.2.8 의 get_etf_isin 이 KRX schema 변경으로 'isin' KeyError → 기존
  universe.py 의 _fetch_listed_since 가 작동 안 함. 결과: universe.json 의
  188/188 ETF 가 listed_since=None → tradable_at(as_of) 가 모든 ETF 통과 →
  historical 시점 backtest 시 신규 ETF (예: 2024 상장) 가 2022 시점 후보로
  들어가는 silent bug.

방식 (2026-05-26):
  pykrx 의 작동하는 endpoint `get_market_ohlcv(start, end, ticker)` 사용 —
  ETF 의 OHLCV df 의 첫 인덱스 일자 = 실제 첫 거래일 ≈ 상장일 (0~1일 차이).

Effect:
  - candidate_selector 가 historical 시점에 미상장 ETF 자동 제외
  - returns matrix dropna 로 인한 bucket ticker 누락 해소
  - Stage 4 overlay all-infeasible 의 root cause 제거 (2022-12-15 cash_mmf
    1/4 ticker only 사례)

실행: uv run python scripts/populate_listed_since.py
소요: ~3-5분 (188 × 0.5s sleep + ohlcv fetch).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s — %(message)s",
)
logger = logging.getLogger(__name__)

# pykrx 의 단축코드는 'A' prefix 없음 (universe.json 의 'A157450' → '157450').
_OHLCV_START = "20100101"
_OHLCV_END = date.today().strftime("%Y%m%d")
_SLEEP_SEC = 0.4  # pykrx rate limit safety


def fetch_first_trade_date(ticker: str) -> str | None:
    """pykrx 의 작동하는 endpoint 로 ETF 첫 거래일 (= 상장일 ± 0~1일) 반환.

    universe.json 의 'A157450' 형식 → pykrx 는 '157450' 사용.
    Returns ISO format date string or None on failure.
    """
    try:
        from pykrx import stock
        bare = ticker[1:] if ticker.startswith("A") else ticker
        df = stock.get_market_ohlcv(_OHLCV_START, _OHLCV_END, bare)
        if df is None or df.empty:
            return None
        return df.index.min().date().isoformat()
    except Exception as e:
        logger.warning("fetch_first_trade_date(%s) failed: %s", ticker, e)
        return None


def main():
    path = _ROOT / "data" / "universe.json"
    universe = json.loads(path.read_text())

    etfs = universe["etfs"]
    total = len(etfs)
    already = sum(1 for e in etfs if e.get("listed_since"))
    logger.info(
        "universe loaded: %d ETFs, %d already have listed_since", total, already,
    )

    updated = 0
    failed = 0
    for i, e in enumerate(etfs):
        if e.get("listed_since"):
            continue
        ticker = e["ticker"]
        listed = fetch_first_trade_date(ticker)
        if listed:
            e["listed_since"] = listed
            updated += 1
        else:
            failed += 1
        time.sleep(_SLEEP_SEC)
        if (i + 1) % 20 == 0:
            logger.info(
                "progress: %d/%d (updated=%d, failed=%d)",
                i + 1, total, updated, failed,
            )

    logger.info("DONE: updated=%d, failed=%d, total=%d", updated, failed, total)

    # version 갱신.
    universe["version"] = date.today().isoformat()

    path.write_text(json.dumps(universe, ensure_ascii=False, indent=2) + "\n")
    logger.info("written: %s", path)


if __name__ == "__main__":
    main()
