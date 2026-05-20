from datetime import date

import pandas as pd

from tradingagents.schemas.macro import EmploymentSnapshot
from tradingagents.skills.registry import register_skill


@register_skill(name="compute_unemployment_trend", category="macro")
def compute_unemployment_trend(
    unemployment_rate: pd.Series,
    non_farm_payrolls: pd.Series,
    as_of: date,
    labor_participation: pd.Series | None = None,
    job_openings: pd.Series | None = None,
    quits_rate: pd.Series | None = None,
) -> EmploymentSnapshot:
    """Sahm rule + 노동참여율 cross-check (2026-05 fix).

    Original Sahm: 3-month avg UR rises 0.5pp+ above the 12-month min.

    2024년 7월 첫 발동 후 미국 침체 없음 — Claudia Sahm 본인이 "팬데믹 후 노동
    참여율 정상화로 false-positive 가능"이라 언급. 따라서 trigger 조건에
    'UR 상승이 노동공급(LFPR) 증가가 아닌 수요 감소로 인한 것인지' 보강:

        sahm_rule_triggered = (recent_3mo_avg - prior_12mo_min) >= 0.5
                              AND (labor_participation 6개월 변화 ≤ +0.2pp)

    LFPR이 빠르게 오르고 있으면 UR 상승은 노동공급 증가로 흡수 가능 — false alert.
    labor_participation 미제공 시 기존 Sahm rule만 (downstream LLM이 해석).
    """
    if len(unemployment_rate) < 12:
        sahm = False
    else:
        recent_3mo_avg = float(unemployment_rate.tail(3).mean())
        prior_12mo_min = float(unemployment_rate.tail(15).head(12).min())
        sahm_raw = (recent_3mo_avg - prior_12mo_min) >= 0.5

        # Cross-check: LFPR 6개월 변화가 +0.2pp 이상이면 노동공급 증가
        # → Sahm 신호 false-positive 가능성. trigger 격하.
        if sahm_raw and labor_participation is not None and len(labor_participation) >= 7:
            lfpr_change_6mo = float(
                labor_participation.iloc[-1] - labor_participation.iloc[-7]
            )
            if lfpr_change_6mo > 0.2:
                sahm = False  # 노동공급 증가가 UR 상승 흡수 — 침체 신호 아님
            else:
                sahm = True
        else:
            sahm = sahm_raw

    rate_change_3mo = float(unemployment_rate.iloc[-1] - unemployment_rate.iloc[-4]) if len(unemployment_rate) > 3 else 0.0
    payrolls_3mo_avg = float(non_farm_payrolls.tail(3).mean()) if len(non_farm_payrolls) >= 3 else 0.0

    # JOLTS labor market tightness (2026-05). Sahm rule보다 leading.
    if job_openings is not None and len(job_openings) >= 3:
        openings_3mo_avg = float(job_openings.tail(3).mean())
    else:
        openings_3mo_avg = 0.0

    if quits_rate is not None and len(quits_rate) >= 7:
        quits_now = float(quits_rate.iloc[-1])
        quits_6mo_ago = float(quits_rate.iloc[-7])
        quits_change_6mo = quits_now - quits_6mo_ago
    elif quits_rate is not None and len(quits_rate) >= 1:
        quits_now = float(quits_rate.iloc[-1])
        quits_change_6mo = 0.0
    else:
        quits_now = 0.0
        quits_change_6mo = 0.0

    return EmploymentSnapshot(
        unemployment_rate=float(unemployment_rate.iloc[-1]),
        rate_change_3mo=rate_change_3mo,
        sahm_rule_triggered=sahm,
        non_farm_payrolls_3mo_avg=payrolls_3mo_avg,
        job_openings_3mo_avg=openings_3mo_avg,
        quits_rate=quits_now,
        quits_rate_change_6mo=quits_change_6mo,
        source_date=as_of,
    )
