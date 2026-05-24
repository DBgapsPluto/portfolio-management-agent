"""Mega-cap concentration — RSP (equal-weight) vs SPY (cap-weight) ratio percentile.

S&P 500 11 sector ETF advancing_pct 만 보면 narrow rally (mega-cap 7개가 IT/Comm/
Disc 섹터에 분산 매수돼 11 섹터 모두 녹색이지만 종목 breadth 는 낮음) blindspot.
RSP/SPY ratio 는 equal-weight 가 cap-weight 보다 underperform 하면 하락 = mega-cap
만 가는 narrow market 의 직접 측정.

Factor model 의 F9 liquidity_regime 보완 component (C8 활성화 예정).

D7 (scalar return) + D8 (insufficient data → None + warning) + D9 (no cache) —
sector_dispersion / cfnai 와 동일 fold-in 패턴.
"""
import logging
from datetime import date

import pandas as pd

from tradingagents.skills.registry import register_skill

logger = logging.getLogger(__name__)


@register_skill(name="compute_mega_cap_concentration", category="risk")
def compute_mega_cap_concentration(
    rsp_close: pd.Series | None,
    spy_close: pd.Series | None,
    as_of: date,
) -> float | None:
    """Returns 1y percentile of (RSP/SPY) ratio. None on insufficient data.

    Args:
        rsp_close: RSP (equal-weight S&P 500) daily close prices.
        spy_close: SPY (cap-weight S&P 500) daily close prices.
        as_of: report date (advisory — series itself point-in-time).

    Returns:
        Percentile in [0, 1]. <0.20 = mega-cap heavy narrow market,
        ~0.50 = balanced, >0.80 = equal-weight 우위 (broad rally).
        None if either input empty or < 30 overlapping obs.

    Notes:
        - 1y window = 252 거래일. 5y로 가면 RSP 출시 (2003-04) 직후 데이터로
          왜곡 가능하니 1y로 충분.
        - Analyst 가 breadth_us.model_copy(update={"mega_cap_concentration_pct": ...})
          로 BreadthSnapshot 에 fold-in.
    """
    try:
        if rsp_close is None or spy_close is None or rsp_close.empty or spy_close.empty:
            logger.warning(
                "Mega-cap concentration: empty input (rsp=%s, spy=%s, as_of=%s) — "
                "narrow rally signal skipped",
                rsp_close is None or rsp_close.empty,
                spy_close is None or spy_close.empty,
                as_of,
            )
            return None

        aligned = pd.concat([rsp_close, spy_close], axis=1, join="inner").dropna()
        if len(aligned) < 30:
            logger.warning(
                "Mega-cap concentration: only %d overlapping obs (need 30+) — skipped",
                len(aligned),
            )
            return None

        aligned.columns = ["rsp", "spy"]
        ratio = aligned["rsp"] / aligned["spy"]
        current = float(ratio.iloc[-1])

        last_1y = ratio.tail(252)
        percentile = float((last_1y < current).sum() / len(last_1y))
        return percentile
    except Exception as e:
        logger.warning("Mega-cap concentration compute failed (as_of=%s): %s", as_of, e)
        return None
