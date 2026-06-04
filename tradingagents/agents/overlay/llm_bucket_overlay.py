"""Tier 3 LLM bucket overlay: prompt assembly + K-sample LLM forward.

The live LLM client is reached via `_get_llm_client()` — a seam that tests
mock. Production wiring (when tier3_llm_overlay_enabled=True) should return an
object exposing an async `complete(system, user, response_schema, temperature)`
returning an LLMBucketView. Currently a thin adapter over the project's
llm_clients is provided; wire to the actual provider when enabling Tier 3.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from tradingagents.agents.overlay.prompt_helpers import (
    DEFAULT_OVERLAY_TEMPERATURE,
    EVIDENCE_FORMAT_HINT,
    OVERLAY_DECISION_RUBRIC,
    format_top_factor_z,
    stage2_schema_enum_block,
    wrap_untrusted_reports,
)
from tradingagents.schemas.llm_overlay import LLMBucketView, Stage2NarrativeView

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a senior macroeconomic strategist for a KRW-denominated
multi-asset portfolio. Output a directional view on 8 bucket allocations.

Output STRICT JSON conforming to LLMBucketView schema. Per-bucket delta in [-1, +1].
- +1 = strongly increase from quant baseline
- 0  = no view (neutral)
- -1 = strongly decrease

Rules:
1. NO arithmetic — output directional view only, not specific weights
2. CITE sources from provided analyst narratives (cited_events field)
3. Confidence reflects YOUR uncertainty, not market volatility
4. Reasoning must be 500 chars max, KR or EN
5. Your view should ADD value beyond quant — focus on what quant z-scores might miss:
   - Breaking events / policy surprises (recent news)
   - Regime shifts (correlation breakdown, structural shifts)
   - Qualitative signals (central bank tone, geopolitical narrative)

Buckets: kr_equity, global_equity, precious_metals, cyclical_commodity_fx,
kr_bond, credit, global_duration, cash_mmf.
"""

STAGE2_NARRATIVE_SYSTEM_PROMPT = f"""You are a senior macro strategist for a
KRW-denominated multi-asset ETF portfolio. Output a Stage2NarrativeView.

Rules:
1. NO arithmetic — output directional tilts only, not target weights
2. Do not invent buckets, tickers, factors, or data not present in the prompt
3. Use evidence from Stage 1 summaries and cite the exact events concisely
4. Confidence is your uncertainty about the narrative edge, not market volatility
5. If narrative adds no edge beyond quant, use neutral bucket_deltas and low confidence
6. Mark conflict_with_quant=True when the narrative intentionally disagrees with factor_z
7. {EVIDENCE_FORMAT_HINT}

{OVERLAY_DECISION_RUBRIC}
"""


def _build_analyst_context(state: Any) -> str:
    """Extract Stage 1 *_summary fields from AgentState (dict-like or attr)."""
    sections = []
    for key, title in [
        ("macro_summary", "Macro (macro_quant_analyst)"),
        ("risk_summary", "Market Risk (market_risk_analyst)"),
        ("technical_summary", "Technical (technical_analyst)"),
        ("news_summary", "News (macro_news_analyst)"),
    ]:
        text = state.get(key) if isinstance(state, dict) else getattr(state, key, "")
        if text:
            sections.append(f"## {title}\n{text}")
    return wrap_untrusted_reports("\n\n".join(sections))


def _build_factor_context(factor_z: dict[str, float]) -> str:
    lines = ["Factor z-scores (Stage 2 factor model):"]
    for f, z in sorted(factor_z.items()):
        if abs(z) < 0.25:
            interp = "neutral"
        elif abs(z) < 1.0:
            interp = "modest"
        elif abs(z) < 2.0:
            interp = "strong"
        else:
            interp = "extreme"
        sign = "+" if z >= 0 else "-"
        lines.append(f"  {f}: z={sign}{abs(z):.2f} ({interp})")
    return "\n".join(lines)


def _build_audit_context(safety_diag: dict | None) -> str:
    if not safety_diag:
        return ""
    notes = []
    if safety_diag.get("cap_hits", 0) > 0:
        notes.append(f"WARNING: {safety_diag['cap_hits']} factor x bucket cells saturated at cap")
    if safety_diag.get("projection_intervened"):
        notes.append("WARNING: Mandate constraint actively binding")
    if safety_diag.get("extreme_factor_active"):
        notes.append("WARNING: Extreme factor z (|z|>=2.5) detected")
    return "Quant model limits:\n" + "\n".join(notes) if notes else ""


def build_user_prompt(state: Any, factor_z: dict[str, float],
                      quant_target: dict[str, float], safety_diag: dict | None = None) -> str:
    return f"""=== Stage 1 Analyst Reports ===

{_build_analyst_context(state)}

=== Stage 2 Factor Model Signals ===

{_build_factor_context(factor_z)}

{_build_audit_context(safety_diag)}

=== Stage 2 Quant Bucket Target ===

{json.dumps(quant_target, indent=2)}

=== Task ===

Review the analyst narratives and factor signals above. Identify:
1. Macro/news signals that quant z-scores might be UNDER-weighting
2. Regime characteristics that the linear factor model might miss
3. Tail risks or asymmetric scenarios not captured by mean-variance logic

Then output your directional view as LLMBucketView JSON.
"""


def build_stage2_narrative_prompt(
    state: Any,
    factor_z: dict[str, float],
    quant_target: dict[str, float],
    safety_diag: dict | None = None,
) -> str:
    """Build the Stage 2 narrative policy prompt.

    This supersedes the old bucket-only prompt for live Stage 2 blending while
    keeping the legacy LLMBucketView path available for backwards-compatible
    tests and archives.
    """
    return f"""=== Stage 1 Analyst Reports ===

{_build_analyst_context(state)}

=== Quant Anchor ===

{_build_factor_context(factor_z)}

{_build_audit_context(safety_diag)}

Quant bucket target:
{json.dumps(quant_target, indent=2)}

=== Schema enums ===

{stage2_schema_enum_block()}

=== Task ===

Return STRICT JSON conforming to Stage2NarrativeView.

Schema intent:
- base_scenario: one allowed value from Schema enums
- overlays: only allowed narrative modifiers from Schema enums
- bucket_deltas: bucket → directional tilt in [-1, +1], NOT target weights
- risk_budget_delta: total risk-asset tilt in [-1, +1], NOT a target risk weight
- confidence: your uncertainty about the incremental narrative edge
- evidence: {EVIDENCE_FORMAT_HINT}
- expiry_days: 1-10 day validity window
- conflict_with_quant: true only when intentionally disagreeing with the quant anchor

NO arithmetic. Do not produce final weights.
"""


def _structured_llm(llm: Any, schema: type, temperature: float):
    try:
        bound = llm.bind(temperature=temperature)
    except (AttributeError, NotImplementedError, TypeError):
        bound = llm
    return bound.with_structured_output(schema)


def _get_llm_client():
    """Return an object with async `complete(system, user, response_schema, temperature)`.

    SEAM: tests monkeypatch this. Production wiring for Tier 3 (when enabled)
    should adapt the project's llm_clients (e.g. OpenAIClient.get_llm() +
    langchain with_structured_output(LLMBucketView)). Not exercised while
    tier3_llm_overlay_enabled is False (default).
    """
    raise NotImplementedError(
        "Tier 3 LLM client not wired. Set up an async complete() adapter over "
        "tradingagents.llm_clients before enabling tier3_llm_overlay_enabled."
    )


async def generate_llm_views(state: Any, factor_z: dict[str, float],
                             quant_target: dict[str, float], safety_diag: dict | None = None,
                             k: int = 5, temperature: float = 0.7) -> list[LLMBucketView]:
    """K independent stochastic samples (consensus estimation). Failures skipped."""
    user_prompt = build_user_prompt(state, factor_z, quant_target, safety_diag)
    client = _get_llm_client()
    views: list[LLMBucketView] = []
    for i in range(k):
        try:
            v = await client.complete(
                system=SYSTEM_PROMPT, user=user_prompt,
                response_schema=LLMBucketView, temperature=temperature,
            )
            views.append(v)
        except Exception as e:
            logger.warning("LLM sample %d failed: %s", i, e)
    return views


def generate_stage2_narrative_views(
    *,
    llm: Any,
    state: Any,
    factor_z: dict[str, float],
    quant_target: dict[str, float],
    safety_diag: dict | None = None,
    k: int = 3,
    temperature: float = DEFAULT_OVERLAY_TEMPERATURE,
) -> list[Stage2NarrativeView]:
    """Generate K structured Stage 2 narrative views.

    Failures are skipped so the quant path remains the fail-safe. The caller
    decides whether these views are shadow-only or live low-impact input.
    """
    if llm is None or k <= 0:
        return []
    prompt = [
        {"role": "system", "content": STAGE2_NARRATIVE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": build_stage2_narrative_prompt(
                state=state,
                factor_z=factor_z,
                quant_target=quant_target,
                safety_diag=safety_diag,
            ),
        },
    ]
    try:
        structured = _structured_llm(llm, Stage2NarrativeView, temperature)
    except (NotImplementedError, AttributeError) as exc:
        logger.warning("Stage 2 narrative overlay unavailable: %s", exc)
        return []

    views: list[Stage2NarrativeView] = []
    for i in range(k):
        try:
            views.append(structured.invoke(prompt))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Stage 2 narrative sample %d failed: %s", i, exc)
    return views


__all__ = [
    "generate_llm_views", "build_user_prompt", "SYSTEM_PROMPT",
    "generate_stage2_narrative_views", "build_stage2_narrative_prompt",
    "STAGE2_NARRATIVE_SYSTEM_PROMPT", "DEFAULT_OVERLAY_TEMPERATURE",
]
