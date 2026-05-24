"""KOSPI valuation — PBR/PER/DivYield via pykrx.

Factor model F8 valuation 의 KR equity valuation component (C8 활성화 예정).
KOSPI 200 underlying. as_of 가 KR holiday 시 pykrx 내부에서 prior trading
day 데이터 사용.

C5 patterns (5 indicator pattern 의 첫 *신규 class indicator* 사례):
- D7 (신규 class): full Snapshot 반환 — analyst 가 MacroReport 의 Optional
  field 에 직접 채움 (model_copy 아님). 기존 cfnai / slope_5_30y 는 scalar
  return + model_copy 였으나, KRValuationSnapshot 은 별개 schema instance.
- D8: empty / exception → None + logger.warning (no default fill, no raise)
- D9: no retry, no skill-internal cache (fetcher cache 와 분리)
"""
import logging
from datetime import date

from pykrx import stock

from tradingagents.schemas.macro import KRValuationSnapshot
from tradingagents.skills.registry import register_skill

logger = logging.getLogger(__name__)


@register_skill(name="compute_kospi_valuation", category="macro")
def compute_kospi_valuation(as_of: date) -> KRValuationSnapshot | None:
    """KOSPI 200 valuation snapshot (PBR/PER/DivYield 평균).

    Args:
        as_of: report as-of date. KR holiday 시 pykrx 내부에서 prior trading day 사용.

    Returns:
        KRValuationSnapshot 성공 시. None on empty / missing column / exception (D8).

    Notes:
        - pykrx 의 KOSPI200 fundamental 은 BPS/PER/PBR/EPS/DIV/DPS 컬럼.
          본 skill 은 PBR/PER/DIV (dividend yield %) 의 평균을 사용.
        - 단일 row 면 .mean() == 그 값 (pandas semantics).
    """
    try:
        date_str = as_of.strftime("%Y%m%d")
        df = stock.get_market_fundamental(date_str, market="KOSPI200")
        if df is None or df.empty:
            logger.warning(
                "KOSPI valuation: pykrx returned empty for %s — F8 valuation component skipped",
                date_str,
            )
            return None

        # 필수 컬럼 존재 확인 (D8 — silent default 채움 금지).
        for col in ("PBR", "PER", "DIV"):
            if col not in df.columns:
                logger.warning(
                    "KOSPI valuation: missing column %s in pykrx response (as_of=%s)",
                    col, as_of,
                )
                return None

        kospi_pbr = float(df["PBR"].mean())
        kospi_per = float(df["PER"].mean())
        kospi_div = float(df["DIV"].mean())

        return KRValuationSnapshot(
            kospi_pbr=kospi_pbr,
            kospi_per=kospi_per,
            kospi_div_yield=kospi_div,
            source_date=as_of,
        )
    except Exception as e:
        logger.warning(
            "KOSPI valuation fetch failed (as_of=%s): %s", as_of, e,
        )
        return None
