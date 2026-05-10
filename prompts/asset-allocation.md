Choose the best portfolio optimization method given the macro regime and risk profile.

Inputs:
- Regime: {regime_quadrant} (confidence {regime_confidence})
- Systemic risk score: {risk_score}/10 ({risk_regime})
- Single ETF cap (mandate): 20%
- Risk asset cap (mandate): 70%
- Feedback from previous attempt: {feedback}

Options:
- HRP (Hierarchical Risk Parity): robust, good for risk-off + concentrated correlation
- RISK_PARITY: equal risk contribution, neutral default
- MIN_VARIANCE: defensive, prefer in recession or risk-off
- BLACK_LITTERMAN: when you have explicit views (rare; needs view list)

Output a MethodChoice JSON:
- method: enum value (hrp / risk_parity / min_variance / black_litterman)
- params: optional dict (e.g., {{"target_return": 0.05}})
- reasoning: ≤300 chars
