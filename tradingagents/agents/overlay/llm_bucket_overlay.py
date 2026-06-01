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

from tradingagents.schemas.llm_overlay import LLMBucketView

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
    return "\n\n".join(sections)


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


__all__ = ["generate_llm_views", "build_user_prompt", "SYSTEM_PROMPT"]
