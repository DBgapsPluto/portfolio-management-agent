from datetime import date

import pandas as pd

from tradingagents.schemas.macro import FedPathSnapshot
from tradingagents.skills.registry import register_skill


# Adaptive band based on (DGS2 - DFF) 5y rolling std (2026-05 fix).
# 이전: 절대 ±50bps band — 2022-2024 같은 빠른 정책 사이클엔 path_bps가 ±200bps+
# 까지 가서 단순 ±50은 너무 좁고 거의 항상 hike/cut. band를 historical
# volatility에 맞춰 동적으로 조정.
#
# ⚠️ HARDCODED CAVEAT (#5, 2026-05 audit):
#   floor 25 / ceil 150 (`max(25, min(150, std_bps))`)은 우리 임의 선택.
#   - 25 미만이면 hold 의미 잃음 (모든 작은 변동에 hike/cut 신호)
#   - 150 초과면 hike/cut 의미 잃음 (거의 항상 hold)
#   2022-2024 quick-cycle era에서는 1σ가 한때 200bps+ 갔으니 150 ceil이 보수적.
#   CME FedWatch (CME에서 직접 fetch 가능, 무료) 사용이 더 정확. 추후 통합 권장.
DEFAULT_BAND_BPS = 50.0  # 5y 데이터 부족 시 fallback


def _classify_view(path_bps: float, band_bps: float) -> str:
    if path_bps > band_bps:
        return "hike"
    if path_bps < -band_bps:
        return "cut"
    return "hold"


@register_skill(name="compute_fed_path", category="macro")
def compute_fed_path(
    fed_funds: pd.Series, dgs2: pd.Series, as_of: date,
) -> FedPathSnapshot:
    """Fed funds futures 묵시금리를 (DGS2 - DFF) 스프레드로 proxy.

    2y Treasury는 향후 ~24개월 정책 기대를 가격에 반영하므로 futures와
    corr > 0.9. CME FedWatch 의존 없이 FRED만으로 single-API 구현.

    market_view band는 (DGS2-DFF) 5년 rolling std × 1.0 (즉, ~1σ 밖이면 directional).
    이전 절대 ±50bps는 정책 변동기엔 너무 좁아 거의 항상 hike/cut로 떨어졌음.
    """
    current = float(fed_funds.iloc[-1])
    implied_2y = float(dgs2.iloc[-1])
    path_bps = (implied_2y - current) * 100.0

    # 5y rolling band — daily 시리즈 가정 (252×5 ≈ 1260일)
    aligned = pd.concat([fed_funds, dgs2], axis=1, join="inner").dropna()
    if len(aligned) >= 252:
        spread_history = (aligned.iloc[:, 1] - aligned.iloc[:, 0]) * 100.0
        last_5y = spread_history.tail(252 * 5)
        std_bps = float(last_5y.std())
        # Band: 1σ. floor 25bps (지나치게 좁아지면 hold 의미 잃음),
        # cap 150bps (지나치게 넓어지면 hike/cut 의미 잃음).
        band_bps = max(25.0, min(150.0, std_bps))
    else:
        band_bps = DEFAULT_BAND_BPS

    return FedPathSnapshot(
        current_rate_pct=current,
        implied_2y_rate_pct=implied_2y,
        path_bps=path_bps,
        market_view=_classify_view(path_bps, band_bps),
        source_date=as_of,
    )
