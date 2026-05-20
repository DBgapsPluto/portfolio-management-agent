"""KR residual signals — D3 axis cycle-decontamination.

문제: 기존 D3 (KR 신호)는 cycle leading indicator를 포함했음 (특히
kr_yield_curve inversion은 본질적으로 cycle proxy). 글로벌 cycle과 강한
correlation이 있으니 그대로 D3 신호로 쓰면 D1을 reflagging.

해결: KR 신호에서 *global cycle로 설명되는 분*을 빼고 KR-specific residual만 D3로.
   kr_corp_spread_residual = kr_corp_spread - β × hy_oas
   kr_margin_z = standardized z (KR 자체 deleveraging은 cycle과 비교적 독립)
   kr_tier_relative_perf = KOSPI vs KOSDAQ 자체로 KR 내부 risk preference (이미 residual성)

β는 1990-2024 분기 데이터로 산출한 회귀계수 근사치 (P1 TODO: 실제 regression으로 교체).
"""
from __future__ import annotations

from dataclasses import dataclass


# Hand-coded β: kr_corp_spread = α + β × hy_oas + ε
# 대략 KR AA-3y corp spread vs US HY OAS 회귀 — KR이 US 신용 cycle을 약 50%
# 만큼 흡수한다고 보는 보수적 추정. P1 TODO: pandas OLS로 실측.
_BETA_KR_CORP_VS_HY = 0.50
_ALPHA_KR_CORP = 50.0  # bps, KR baseline corp premium

# kr_margin_debt change_20d_pct의 1σ (rough). normalized z = pct / sigma.
_KR_MARGIN_SIGMA_PCT = 8.0


@dataclass
class KRResidualSignals:
    """글로벌 cycle 영향 제거한 KR-specific 신호."""
    kr_corp_spread_residual_bps: float    # 음수 = KR 신용 양호, 양수 = KR-specific 압력
    kr_margin_z: float                    # 양수 = 평소보다 leveraging, 음수 = deleveraging
    kr_tier_relative_pct: float           # KOSPI vs KOSDAQ 상대 — KR 내부 risk-on/off
    foreign_flow_z: float                 # 외국인 KR equity flow z-score
    # 합성 신호 — D3 trigger 후보
    kr_stress_score: float                # 양수 클수록 kr_stress 가능성 ↑
    kr_boom_score: float                  # 양수 클수록 kr_boom 가능성 ↑

    def to_prompt_block(self) -> str:
        return (
            f"=== KR Residual Signals (D3, global cycle 영향 제거) ===\n"
            f"KR corp spread residual:   {self.kr_corp_spread_residual_bps:+.0f} bps "
            f"(global HY-OAS 설명분 제거 후)\n"
            f"KR margin debt z-score:    {self.kr_margin_z:+.2f}\n"
            f"KOSDAQ-KOSPI relative:     {self.kr_tier_relative_pct:+.2f}% "
            f"(KR 내부 risk preference)\n"
            f"Foreign flow z-score:      {self.foreign_flow_z:+.2f}\n"
            f"-- KR-specific signals --\n"
            f"KR stress score:           {self.kr_stress_score:+.2f}\n"
            f"KR boom score:             {self.kr_boom_score:+.2f}\n"
            f"해석: residual 신호만 D3 (KR 방향) 판단에 사용. 글로벌 cycle\n"
            f"파동이 KR에 미친 영향분은 이미 D1으로 반영되었으니 중복 계산 금지.\n"
        )


def _z_score(value: float, sigma: float) -> float:
    if sigma <= 0:
        return 0.0
    return value / sigma


def compute_kr_residual_signals(
    *,
    kr_corp_spread_bps: float,
    hy_oas_bps: float,
    kr_margin_change_20d_pct: float,
    kr_tier_relative_pct: float,
    foreign_flow_z: float = 0.0,
) -> KRResidualSignals:
    """KR-specific residual 신호 산출.

    Args:
        kr_corp_spread_bps: KR AA-3y - 국고채3y spread (bps)
        hy_oas_bps: US HY OAS (bps) — global cycle proxy
        kr_margin_change_20d_pct: 신용잔고 20일 변화율 (%)
        kr_tier_relative_pct: KOSPI vs KOSDAQ 상대 수익률 (%)
        foreign_flow_z: 외국인 KR 주식 순매수 flow z-score (이미 정규화된 값)
    """
    # Cycle-decontaminated KR corp spread
    kr_corp_expected = _ALPHA_KR_CORP + _BETA_KR_CORP_VS_HY * hy_oas_bps
    kr_corp_residual = kr_corp_spread_bps - kr_corp_expected

    margin_z = _z_score(kr_margin_change_20d_pct, _KR_MARGIN_SIGMA_PCT)

    # 합성 — kr_stress: corp spread 양수 + margin deleveraging + foreign 매도
    kr_stress_score = (
        max(0, kr_corp_residual) / 50.0      # 50bps 이상 residual widening → +1
        - min(0, margin_z) * 0.7              # margin deleveraging (z<0) → +
        - min(0, foreign_flow_z) * 0.5        # 외국인 매도 → +
    )
    # 합성 — kr_boom: corp spread 음수 (KR 신용 양호) + 외국인 순매수 + KOSDAQ 강세
    kr_boom_score = (
        max(0, -kr_corp_residual) / 50.0      # KR 신용 tightening → +
        + max(0, foreign_flow_z) * 0.5
        + max(0, kr_tier_relative_pct) / 5.0  # KOSDAQ 강세 = 소형주 risk-on
    )

    return KRResidualSignals(
        kr_corp_spread_residual_bps=kr_corp_residual,
        kr_margin_z=margin_z,
        kr_tier_relative_pct=kr_tier_relative_pct,
        foreign_flow_z=foreign_flow_z,
        kr_stress_score=kr_stress_score,
        kr_boom_score=kr_boom_score,
    )
