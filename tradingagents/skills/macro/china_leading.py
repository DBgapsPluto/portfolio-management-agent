from datetime import date

import pandas as pd

from tradingagents.schemas.macro import ChinaLeadingSnapshot
from tradingagents.skills.registry import register_skill


def _phase(level: float, change_3mo: float) -> str:
    """OECD CLI 표준 해석. 100 = trend, (level, 모멘텀) 4사분면."""
    above_trend = level >= 100.0
    rising = change_3mo > 0
    if above_trend and rising:
        return "expansion"
    if above_trend and not rising:
        return "peak"
    if not above_trend and not rising:
        return "contraction"
    return "trough"


def _realtime_signal(
    usdcnh: float, usdcnh_chg: float, iron_chg: float,
) -> str:
    """2026-05 추가: USDCNH + iron ore 합성 실시간 신호.

    expansion: 위안 안정 (USDCNH < 7.20 OR 변화 ≤ 0.5%) AND iron 3m +5%↑
    contraction: 위안 약세 (USDCNH > 7.30 OR 변화 > +1.5%) OR iron 3m -10%↓
    neutral: 그 외.

    ⚠️ HARDCODED CAVEAT (#4, 2026-05 audit):
      USDCNH 7.20/7.30 임계 + iron ore ±10%/±5% 임계는 **우리 자의적 선택**.
      참고:
        - USDCNH 7.30+: 2022/2023 위안 약세기 평균 부근. 정책 의사소통 임계.
        - 7.20-: 2024+ PBoC fixing 안정기 평균.
        - iron 3m ±10%: China 건설 demand 변동의 historical 1σ 근사.
      Caixin PMI free 데이터 가용 시 그것이 더 정확. 임계는 Caixin PMI 50 기준선
      대비 calibration TODO. 현재는 LLM이 daily proxy로 활용하는 trade-off 신호.
    """
    weak_yuan = usdcnh > 7.30 or usdcnh_chg > 1.5
    iron_down = iron_chg < -10.0
    iron_up = iron_chg > 5.0
    stable_yuan = usdcnh > 0 and (usdcnh < 7.20 or usdcnh_chg < 0.5)
    if weak_yuan or iron_down:
        return "contraction"
    if stable_yuan and iron_up:
        return "expansion"
    return "neutral"


def _pct_change_1m(series: pd.Series) -> float:
    if series is None or len(series) < 22:
        return 0.0
    base = float(series.iloc[-22])
    if base == 0:
        return 0.0
    return float((series.iloc[-1] / base - 1) * 100)


def _pct_change_3m(series: pd.Series) -> float:
    if series is None or len(series) < 64:
        return 0.0
    base = float(series.iloc[-64])
    if base == 0:
        return 0.0
    return float((series.iloc[-1] / base - 1) * 100)


@register_skill(name="compute_china_leading", category="macro")
def compute_china_leading(
    cli_series: pd.Series, as_of: date,
    usdcnh_series: pd.Series | None = None,
    iron_ore_series: pd.Series | None = None,
) -> ChinaLeadingSnapshot:
    """OECD China CLI + 실시간 보조 (USDCNH + iron ore).

    2026-05 보강: CLI는 2-3개월 lag으로 단독 신호 약함. USDCNH/iron ore로
    실시간 view 추가. KR 수출의 25%가 중국이라 정확성 critical.
    """
    current = float(cli_series.iloc[-1])
    change_3mo = float(cli_series.iloc[-1] - cli_series.iloc[-4]) if len(cli_series) >= 4 else 0.0

    usdcnh_now = float(usdcnh_series.iloc[-1]) if usdcnh_series is not None and len(usdcnh_series) > 0 else 0.0
    usdcnh_chg = _pct_change_1m(usdcnh_series) if usdcnh_series is not None else 0.0
    iron_now = float(iron_ore_series.iloc[-1]) if iron_ore_series is not None and len(iron_ore_series) > 0 else 0.0
    iron_chg = _pct_change_3m(iron_ore_series) if iron_ore_series is not None else 0.0

    last_cli = pd.Timestamp(cli_series.index[-1]).date()
    return ChinaLeadingSnapshot(
        cli_value=current,
        change_3mo=change_3mo,
        phase=_phase(current, change_3mo),
        usdcnh=usdcnh_now,
        usdcnh_change_1m_pct=usdcnh_chg,
        iron_ore=iron_now,
        iron_ore_change_3m_pct=iron_chg,
        realtime_signal=_realtime_signal(usdcnh_now, usdcnh_chg, iron_chg),
        source_date=as_of,
        staleness_days=max((as_of - last_cli).days, 0),
    )
