"""Tail-risk lens — CVaR/VaR + macro stress 기반 level + overlay.

LLM-free deterministic (Stage 1·2·3 정신 일관). 향후 LLM-augmented evidence
narrative는 옵션. 현재는 정량 evidence string으로 충분.

Threshold (보수적 초기값, Phase 3 calibration):
  critical: CVaR ≥ 4% OR systemic_score ≥ 9 OR VIX backwardation+funding_stress
  high:     CVaR ≥ 3% OR systemic ≥ 8 OR (VIX backwardation OR funding stress)
  medium:   CVaR ≥ 2.5% OR systemic ≥ 7
  low:      CVaR ≥ 2.0% OR systemic ≥ 6
  none:     else

Overlay template per level (preset, deterministic):
  critical: multiplier=0.6, tail_hedge_floor cash_mmf=0.05
  high:     multiplier=0.75
  medium:   multiplier=0.9
  low/none: empty
"""
from tradingagents.skills.risk.portfolio_metrics import PortfolioNumerics
from tradingagents.schemas.risk_overlay import LensConcern, RiskOverlayDelta


_CRITICAL_CVAR = 0.04
_HIGH_CVAR = 0.03
_MEDIUM_CVAR = 0.025
_LOW_CVAR = 0.02

_CRITICAL_SYSTEMIC = 9.0
_HIGH_SYSTEMIC = 8.0
_MEDIUM_SYSTEMIC = 7.0
_LOW_SYSTEMIC = 6.0


def _level_from_inputs(
    cvar: float, systemic: float, vix_backwardation: bool, funding_stress: bool,
) -> str:
    if (
        cvar >= _CRITICAL_CVAR
        or systemic >= _CRITICAL_SYSTEMIC
        or (vix_backwardation and funding_stress)
    ):
        return "critical"
    if (
        cvar >= _HIGH_CVAR
        or systemic >= _HIGH_SYSTEMIC
        or vix_backwardation
        or funding_stress
    ):
        return "high"
    if cvar >= _MEDIUM_CVAR or systemic >= _MEDIUM_SYSTEMIC:
        return "medium"
    if cvar >= _LOW_CVAR or systemic >= _LOW_SYSTEMIC:
        return "low"
    return "none"


def _overlay_for_level(level: str) -> RiskOverlayDelta:
    """Level별 preset overlay template. cash_mmf ticker는 외부에서 주입 필요 →
    여기서는 multiplier만, floor는 risk_judge가 cash_mmf 후보 ticker로 채움.
    """
    if level == "critical":
        return RiskOverlayDelta(risk_asset_multiplier=0.6)
    if level == "high":
        return RiskOverlayDelta(risk_asset_multiplier=0.75)
    if level == "medium":
        return RiskOverlayDelta(risk_asset_multiplier=0.9)
    return RiskOverlayDelta()


def run_tail_risk_lens(
    numerics: PortfolioNumerics,
    systemic_score: float = 5.0,
    vix_term_regime: str = "contango",
    funding_regime: str = "calm",
) -> LensConcern:
    """Tail-risk lens — portfolio CVaR + market stress 기반.

    inputs:
      numerics: Stage 3.5 PortfolioNumerics
      systemic_score: market_risk SystemicRiskScore.score (0~10)
      vix_term_regime: market_risk vix_term.regime (contango/flat/backwardation)
      funding_regime: market_risk funding_stress.regime (calm/elevated/stress)
    """
    cvar = numerics.cvar_95_1d
    vix_bw = vix_term_regime == "backwardation"
    funding_s = funding_regime == "stress"

    level = _level_from_inputs(cvar, systemic_score, vix_bw, funding_s)
    overlay = _overlay_for_level(level)

    evidence = (
        f"CVaR_95_1d={cvar*100:.2f}%, systemic_score={systemic_score:.1f}, "
        f"vix_term={vix_term_regime}, funding={funding_regime}"
    )[:300]

    return LensConcern(
        lens="tail_risk", level=level,  # type: ignore[arg-type]
        proposed_overlay=overlay, evidence=evidence,
    )
