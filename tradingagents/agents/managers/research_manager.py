"""Research Manager — synthesizes Bull/Bear into a BucketTarget (5-bucket)."""
from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills._helpers import invoke_with_structured_retry


JUDGE_PROMPT = """\
You synthesize a Bull/Bear debate into a final 5-bucket weight target.

Inputs:
{summaries}

Bull arguments (across {rounds} rounds):
{bull}

Bear arguments:
{bear}

Constraints:
- 위험자산(kr_equity + global_equity + fx_commodity) ≤ 0.70 (대회 §2.2)
- All weights sum to 1.0
- Be decisive — pick ONE target, not a range

Output a BucketTarget JSON. Rationale ≤500 chars."""


def create_research_manager(deep_llm):
    def node(state):
        summaries = (
            f"Macro: {state['macro_summary']}\n\n"
            f"Risk: {state['risk_summary']}\n\n"
            f"Technical: {state['technical_summary']}\n\n"
            f"News: {state['news_summary']}"
        )
        prompt = JUDGE_PROMPT.format(
            summaries=summaries,
            rounds=state["round_count"],
            bull="\n---\n".join(state["bull_arguments"]),
            bear="\n---\n".join(state["bear_arguments"]),
        )
        target: BucketTarget = invoke_with_structured_retry(
            deep_llm, BucketTarget,
            [{"role": "user", "content": prompt}],
            max_retries=1,
        )
        summary = (
            f"## Bucket Target\n"
            f"국내주식: {target.kr_equity:.1%}, 해외주식: {target.global_equity:.1%}, "
            f"FX/원자재: {target.fx_commodity:.1%}, 채권: {target.bond:.1%}, "
            f"MMF: {target.cash_mmf:.1%}\n"
            f"위험자산 합: {target.risk_asset_weight:.1%}\n"
            f"근거: {target.rationale[:300]}"
        )
        return {"bucket_target": target, "research_debate_summary": summary}

    return node
