"""Stage 3 LLM candidate boost overlay.

The LLM can only re-rank candidates already surfaced by quant. It cannot add
tickers, produce expected returns, covariance, or final portfolio weights.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any

import numpy as np

from tradingagents.agents.overlay.prompt_helpers import (
    DEFAULT_OVERLAY_TEMPERATURE,
    EVIDENCE_FORMAT_HINT,
    OVERLAY_DECISION_RUBRIC,
    format_top_factor_z,
    wrap_untrusted_reports,
)
from tradingagents.schemas.llm_overlay import Stage3CandidateBoostView

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = f"""You are a macro narrative reviewer for a KRW ETF portfolio.
Output a Stage3CandidateBoostView.

Rules:
1. Do not add tickers. Only use tickers present in the provided longlists.
2. Do not output weights, expected returns, volatility, covariance, or trades.
3. Use ticker_boosts/subcategory_boosts only as directional re-rank signals in [-1,+1].
4. If the narrative has no edge beyond quant alpha, return empty boosts and confidence <= 0.25.
5. {EVIDENCE_FORMAT_HINT}

{OVERLAY_DECISION_RUBRIC}
"""


def _summary_context(state: Any) -> str:
    sections = []
    for key, title in [
        ("macro_summary", "Macro"),
        ("risk_summary", "Risk"),
        ("technical_summary", "Technical"),
        ("news_summary", "News"),
    ]:
        text = state.get(key) if isinstance(state, dict) else getattr(state, key, "")
        if text:
            sections.append(f"## {title}\n{text}")
    return wrap_untrusted_reports("\n\n".join(sections))


def build_stage3_candidate_prompt(
    *,
    state: Any,
    bucket_longlists: dict[str, list[dict[str, Any]]],
    factor_z: dict[str, float] | None = None,
    dominant_scenario: str | None = None,
) -> str:
    quant_lines = []
    if dominant_scenario:
        quant_lines.append(f"Dominant macro scenario (Stage 2): {dominant_scenario}")
    if factor_z:
        quant_lines.append(format_top_factor_z(factor_z))
    quant_block = "\n".join(quant_lines) if quant_lines else "(not provided)"

    return f"""=== Stage 1 Summaries ===

{_summary_context(state)}

=== Quant context (anchor; do not override with narrative alone) ===

{quant_block}

=== Quant Candidate Longlists ===

{json.dumps(bucket_longlists, ensure_ascii=False, indent=2, default=str)}

=== Task ===

Return STRICT JSON conforming to Stage3CandidateBoostView.

Do not add tickers outside the longlists. Only express small directional
re-rank preferences for tickers or subcategories when the narrative evidence
adds information beyond the quant alpha/implementation scores already in the longlists.
"""


def _structured_llm(llm: Any, temperature: float):
    try:
        bound = llm.bind(temperature=temperature)
    except (AttributeError, NotImplementedError, TypeError):
        bound = llm
    return bound.with_structured_output(Stage3CandidateBoostView)


def aggregate_stage3_candidate_views(
    views: list[Stage3CandidateBoostView],
) -> Stage3CandidateBoostView | None:
    """Mean ticker/subcategory boosts and confidence across K samples."""
    if not views:
        return None
    if len(views) == 1:
        return views[0]

    ticker_vals: dict[str, list[float]] = defaultdict(list)
    sub_vals: dict[str, list[float]] = defaultdict(list)
    for view in views:
        for ticker, boost in view.ticker_boosts.items():
            ticker_vals[ticker].append(float(boost))
        for sub, boost in view.subcategory_boosts.items():
            sub_vals[sub].append(float(boost))

    ticker_boosts = {t: float(np.mean(vals)) for t, vals in ticker_vals.items()}
    subcategory_boosts = {s: float(np.mean(vals)) for s, vals in sub_vals.items()}
    confidence = float(np.mean([v.confidence for v in views]))

    evidence: list[str] = []
    for v in views:
        for item in v.evidence:
            if item and item not in evidence:
                evidence.append(item)
            if len(evidence) >= 6:
                break
        if len(evidence) >= 6:
            break

    reasoning = " | ".join(v.reasoning[:180] for v in views if v.reasoning)[:700]
    return Stage3CandidateBoostView(
        ticker_boosts=ticker_boosts,
        subcategory_boosts=subcategory_boosts,
        confidence=confidence,
        evidence=evidence,
        reasoning=reasoning or "K-sample aggregate",
    )


def generate_stage3_candidate_boost_view(
    *,
    llm: Any,
    state: Any,
    bucket_longlists: dict[str, list[dict[str, Any]]],
    factor_z: dict[str, float] | None = None,
    dominant_scenario: str | None = None,
    k: int = 2,
    temperature: float = DEFAULT_OVERLAY_TEMPERATURE,
) -> Stage3CandidateBoostView | None:
    if llm is None or k <= 0:
        return None
    user_content = build_stage3_candidate_prompt(
        state=state,
        bucket_longlists=bucket_longlists,
        factor_z=factor_z,
        dominant_scenario=dominant_scenario,
    )
    prompt = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    try:
        structured = _structured_llm(llm, temperature)
    except (NotImplementedError, AttributeError) as exc:
        logger.warning("Stage 3 candidate overlay unavailable: %s", exc)
        return None

    views: list[Stage3CandidateBoostView] = []
    for i in range(k):
        try:
            views.append(structured.invoke(prompt))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Stage 3 candidate sample %d failed: %s", i, exc)
    return aggregate_stage3_candidate_views(views)


__all__ = [
    "SYSTEM_PROMPT",
    "build_stage3_candidate_prompt",
    "generate_stage3_candidate_boost_view",
    "aggregate_stage3_candidate_views",
    "DEFAULT_OVERLAY_TEMPERATURE",
]
