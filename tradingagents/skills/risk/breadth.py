"""Market breadth real implementation.

KOSPI200: pykrx로 200 종목 daily pct change → advancing/declining 카운트
SP500:   11 SPDR 섹터 ETF(XLF/XLK/XLE/XLV/XLI/XLY/XLP/XLU/XLB/XLRE/XLC)를 proxy로 사용
         (전체 500 종목 yfinance fetch는 비용이 크고 rate-limit 위험)

기존 stub(0.55 placeholder) 교체. 둘 다 실패 시 sentinel(staleness=99)로 graceful degrade.
"""
import logging
from datetime import date, timedelta
from typing import Literal

from tradingagents.schemas.risk import BreadthSnapshot
from tradingagents.skills.registry import register_skill

logger = logging.getLogger(__name__)


SP500_SECTOR_ETFS = [
    "XLF", "XLK", "XLE", "XLV", "XLI", "XLY",
    "XLP", "XLU", "XLB", "XLRE", "XLC",
]
KOSPI200_INDEX_CODE = "1028"


def _kospi200_breadth(as_of: date) -> BreadthSnapshot:
    """KRX KOSPI200 일별 200 종목 등락 카운트.

    pykrx `get_market_ohlcv_by_ticker(date, "KOSPI")`가 단일 일자의 모든 KOSPI
    종목 OHLCV를 반환. "등락률" 컬럼이 이미 계산돼 있어 그대로 사용.
    """
    try:
        from pykrx import stock
        constituents = set(stock.get_index_portfolio_deposit_file(
            as_of.strftime("%Y%m%d"), KOSPI200_INDEX_CODE,
        ))
        if not constituents:
            raise ValueError("empty KOSPI200 constituents")

        df = stock.get_market_ohlcv_by_ticker(
            as_of.strftime("%Y%m%d"), market="KOSPI",
        )
        if df is None or df.empty:
            raise ValueError("no KOSPI snapshot")
        # KOSPI200에 속하는 행만 선택
        df = df.loc[df.index.intersection(constituents)]
        if df.empty:
            raise ValueError("KOSPI200 constituents not in snapshot")
        if "등락률" not in df.columns:
            raise ValueError("등락률 column missing")

        change_pct = df["등락률"].dropna()
        total = max(len(change_pct), 1)
        advancing = int((change_pct > 0).sum())
        declining = int((change_pct < 0).sum())

        return BreadthSnapshot(
            market="KOSPI200",
            advancing_pct=advancing / total,
            declining_pct=declining / total,
            new_highs_minus_lows=0,  # 별도 계산 필요 (Tier 2+에서 추가 검토)
            source_date=as_of,
        )
    except Exception as e:
        logger.warning("KOSPI200 breadth failed: %s — fallback sentinel", e)
        return BreadthSnapshot(
            market="KOSPI200",
            advancing_pct=0.5, declining_pct=0.5, new_highs_minus_lows=0,
            source_date=as_of, staleness_days=99,
        )


def _sp500_sector_breadth(as_of: date) -> BreadthSnapshot:
    """SP500 11 섹터 ETF의 직전일 vs 당일 종가 변화 → 섹터 advancing 비율.

    개별 종목 500개 yfinance fetch 회피하기 위한 sector proxy.
    """
    try:
        import yfinance as yf
        end = as_of + timedelta(days=1)
        start = as_of - timedelta(days=10)  # 영업일 cushion
        symbols = " ".join(SP500_SECTOR_ETFS)
        raw = yf.download(
            symbols, start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"), auto_adjust=True, progress=False,
        )
        if raw is None or raw.empty:
            raise ValueError("empty yfinance batch")
        closes = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw
        closes = closes.dropna(how="all")
        if len(closes) < 2:
            raise ValueError("not enough data points")

        latest = closes.iloc[-1]
        prev = closes.iloc[-2]
        changes = (latest / prev - 1.0).dropna()
        total = max(len(changes), 1)
        advancing = int((changes > 0).sum())
        declining = int((changes < 0).sum())

        return BreadthSnapshot(
            market="SP500",
            advancing_pct=advancing / total,
            declining_pct=declining / total,
            new_highs_minus_lows=0,
            source_date=as_of,
        )
    except Exception as e:
        logger.warning("SP500 sector breadth failed: %s — fallback sentinel", e)
        return BreadthSnapshot(
            market="SP500",
            advancing_pct=0.5, declining_pct=0.5, new_highs_minus_lows=0,
            source_date=as_of, staleness_days=99,
        )


@register_skill(name="compute_market_breadth", category="risk")
def compute_market_breadth(
    market: Literal["KOSPI200", "SP500"], as_of: date,
) -> BreadthSnapshot:
    """실제 breadth 구현 — KOSPI200(pykrx 200종목) + SP500(11 섹터 ETF proxy)."""
    if market == "KOSPI200":
        return _kospi200_breadth(as_of)
    return _sp500_sector_breadth(as_of)
