"""Conditional stress surprise — D2 axis cycle-decontamination.

문제: HY OAS, VIX 등 절대값 threshold (예: "HY OAS > 600bp = tail")는 D1 cycle과
mechanical correlation 큼 (recession이면 자동으로 widening). 이걸 그대로 LLM에
주면 D1 신호를 D2로 이중 가산.

해결: 각 D1 regime quadrant가 normally produce하는 baseline stress level을 두고,
실측 값과의 *surprise*만 D2 신호로 사용. surprise > +1σ가 진짜 systemic tail의
독립 신호.

baseline 표는 macro consensus + 1970-2024 분기 평균 기반으로 hand-code.
P1: historical regression으로 baseline 자동 추정 + σ 추정 교체 예정.
"""
from __future__ import annotations

from dataclasses import dataclass

from tradingagents.schemas.macro import RegimeQuadrant


# Cycle-conditional baseline (regime이 normally produce하는 stress level).
# (mean, typical_1σ) per metric per quadrant. 1σ는 historical std 근사.
#
# 본 값은 macro consensus + 1970-2024 근사 hand-coded. Issue #6 (전체 회귀) 의
# scope 가 본 PR 초과 — decisions.md D7 참조.
# Data gap (2026-05-21 확인):
#   - HY OAS (BAMLH0A0HYM2): 2023 vintage 변경 후 historical 가용 불가
#   - BAA10Y (IG proxy): 1990+ 가용 — partial regression 가능
#   - VIXCLS, funding, equity_bond_corr: 1990+ FRED 가용
#   - KR corp/equity_bond: ECOS data 별도 fetcher 필요 (~2003+)
# 후속 PR: 1990-2024 partial regression (US 부분) + KR 별도 cycle.
_BASELINE: dict[RegimeQuadrant, dict[str, tuple[float, float]]] = {
    "growth_disinflation": {
        "hy_oas_bps":          (350,  120),
        "vix":                 (15,   4),
        "funding_spread_bps":  (5,    15),
        "credit_quality_bps":  (75,   25),
        "equity_bond_corr":    (-0.30, 0.20),
    },
    "growth_inflation": {
        "hy_oas_bps":          (400,  140),
        "vix":                 (19,   5),
        "funding_spread_bps":  (15,   20),
        "credit_quality_bps":  (90,   30),
        "equity_bond_corr":    (0.20, 0.25),
    },
    "recession_disinflation": {
        "hy_oas_bps":          (600,  250),
        "vix":                 (26,   8),
        "funding_spread_bps":  (20,   30),
        "credit_quality_bps":  (130,  60),
        "equity_bond_corr":    (-0.10, 0.30),
    },
    "recession_inflation": {
        "hy_oas_bps":          (650,  220),
        "vix":                 (28,   8),
        "funding_spread_bps":  (25,   30),
        "credit_quality_bps":  (140,  50),
        "equity_bond_corr":    (0.30, 0.30),
    },
}


@dataclass
class ConditionalStressSurprise:
    """D1 baseline 대비 surprise z-score. 양수 = 평소보다 더 stressed."""
    quadrant: RegimeQuadrant
    hy_oas_z: float
    vix_z: float
    funding_z: float
    credit_quality_z: float
    equity_bond_corr_z: float
    # 단순 평균 합성 score — tail trigger 판정용 (참고치).
    aggregate_z: float
    tail_trigger: bool      # aggregate_z ≥ +1.0
    note: str               # 사람이 읽는 요약 라인

    def to_prompt_block(self) -> str:
        """LLM prompt 주입용 텍스트."""
        return (
            f"=== Conditional Stress Surprise (D2, regime={self.quadrant} 기준) ===\n"
            f"HY OAS surprise:           z = {self.hy_oas_z:+.2f}\n"
            f"VIX surprise:              z = {self.vix_z:+.2f}\n"
            f"Funding spread surprise:   z = {self.funding_z:+.2f}\n"
            f"Credit quality surprise:   z = {self.credit_quality_z:+.2f}\n"
            f"Equity-bond corr surprise: z = {self.equity_bond_corr_z:+.2f}\n"
            f"Aggregate D2 surprise:     z = {self.aggregate_z:+.2f}"
            f"{'  ← tail trigger' if self.tail_trigger else ''}\n"
            f"해석: D1={self.quadrant}에서 normally expected되는 baseline 대비\n"
            f"surprise 분만 D2(systemic tail) 신호로 취급. z<+0.5 = no surprise,\n"
            f"z 0.5-1.0 = mild, z>1.0 = 진짜 tail event 확률 높음.\n"
        )


def _z(value: float, baseline: tuple[float, float]) -> float:
    mean, sigma = baseline
    if sigma <= 0:
        return 0.0
    return (value - mean) / sigma


def compute_conditional_stress(
    quadrant: RegimeQuadrant,
    *,
    hy_oas_bps: float,
    vix: float,
    funding_spread_bps: float,
    credit_quality_bps: float,
    equity_bond_corr: float,
) -> ConditionalStressSurprise:
    """Cycle-conditional surprise z-score 5종 + aggregate."""
    base = _BASELINE[quadrant]
    hy_z   = _z(hy_oas_bps, base["hy_oas_bps"])
    vix_z  = _z(vix, base["vix"])
    fund_z = _z(funding_spread_bps, base["funding_spread_bps"])
    cq_z   = _z(credit_quality_bps, base["credit_quality_bps"])
    ebc_z  = _z(equity_bond_corr, base["equity_bond_corr"])

    # Aggregate: 단순 평균 (P1: PCA 또는 가중치 학습 예정).
    agg = (hy_z + vix_z + fund_z + cq_z + ebc_z) / 5.0
    tail = agg >= 1.0

    note = (
        f"D1={quadrant} baseline 대비 aggregate surprise z={agg:+.2f}"
        f" {'(tail event 가능)' if tail else '(평소 수준)'}"
    )
    return ConditionalStressSurprise(
        quadrant=quadrant,
        hy_oas_z=hy_z, vix_z=vix_z, funding_z=fund_z,
        credit_quality_z=cq_z, equity_bond_corr_z=ebc_z,
        aggregate_z=agg, tail_trigger=tail, note=note,
    )
