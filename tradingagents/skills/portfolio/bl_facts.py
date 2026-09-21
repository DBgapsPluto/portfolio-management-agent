"""철학 리포트용 결정론 facts (PHIL-4): prior 정당화 + 상관 분석. LLM 인용, 날조 금지."""
from __future__ import annotations

import numpy as np
import pandas as pd

from tradingagents.skills.portfolio.scenario_anchor import QUADRANT_BASELINE


def prior_justification_facts(quadrant: str) -> str:
    base = QUADRANT_BASELINE.get(quadrant, {})
    if not base:
        return ""
    top = sorted(base.items(), key=lambda kv: -kv[1])[:5]
    lines = [f"- {k}: {v:.2f}" for k, v in top]
    return (f"[Regime baseline {quadrant} 상위 5 — 실제 prior 는 신호일치도 c 로 중립 보간]\n"
            + "\n".join(lines))


def correlation_from_cov(Sigma: "pd.DataFrame") -> "pd.DataFrame":
    d = np.sqrt(np.diag(Sigma.values))
    d = np.where(d == 0, 1.0, d)
    Dinv = np.diag(1.0 / d)
    C = Dinv @ Sigma.values @ Dinv
    return pd.DataFrame(C, index=Sigma.index, columns=Sigma.columns)


def bl_correlation_facts(Corr: "pd.DataFrame", weights: dict | None = None) -> str:
    cols = list(Corr.columns)
    pairs = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            pairs.append((cols[i], cols[j], float(Corr.iloc[i, j])))
    pairs.sort(key=lambda t: -abs(t[2]))
    top = pairs[:3]
    if not top:
        return ""
    lines = [f"- {a}~{b}: corr {c:.2f}" for a, b, c in top]
    out = "[최고 상관쌍]\n" + "\n".join(lines)
    if weights and top:
        hi = {top[0][0], top[0][1]}
        s = sum(float(weights.get(k, 0.0)) for k in hi)
        out += f"\n[최고상관 클러스터 비중합 {','.join(sorted(hi))}: {s:.2f}]"
    return out
