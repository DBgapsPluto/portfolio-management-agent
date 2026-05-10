"""Risk Judge — synthesizes 3-way debate into a WeightAdjustment dict."""
from pydantic import BaseModel, Field

from tradingagents.skills._helpers import invoke_with_structured_retry


class WeightAdjustment(BaseModel):
    """Pydantic-locked output from RiskJudge."""
    delta: dict[str, float] = Field(
        default_factory=dict,
        description="Per-ticker weight delta (sum should be ≈0; positive = increase)",
    )
    reasoning: str = Field(max_length=400)


JUDGE_PROMPT = """\
You synthesize a 3-way risk debate (Aggressive/Conservative/Neutral) into
a final WeightAdjustment recommendation for the Allocator.

Macro: {macro_summary}
Risk: {risk_summary}
Clusters: {clusters_summary}

Aggressive: {agg}
Conservative: {cons}
Neutral: {neut}

Output a WeightAdjustment JSON with:
- delta: dict of ticker → small adjustment (-0.05 to +0.05). Empty if no change needed.
- reasoning: ≤400 chars."""


def create_risk_judge(deep_llm):
    def node(state):
        prompt = JUDGE_PROMPT.format(
            macro_summary=state["macro_summary"],
            risk_summary=state["risk_summary"],
            clusters_summary=state["correlation_clusters_summary"],
            agg="\n".join(state["aggressive_arguments"]) or "(none)",
            cons="\n".join(state["conservative_arguments"]) or "(none)",
            neut="\n".join(state["neutral_arguments"]) or "(none)",
        )
        adjustment: WeightAdjustment = invoke_with_structured_retry(
            deep_llm, WeightAdjustment,
            [{"role": "user", "content": prompt}],
            max_retries=1,
        )
        summary = (
            f"## Risk Debate Outcome\n"
            f"Adjustment: {len(adjustment.delta)} tickers modified\n"
            f"Reasoning: {adjustment.reasoning[:200]}"
        )
        return {
            "weight_adjustment": adjustment.model_dump(),
            "risk_debate_summary": summary,
        }

    return node
