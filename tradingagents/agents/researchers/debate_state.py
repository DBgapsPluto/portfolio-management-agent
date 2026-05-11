"""Bull/Bear debate sub-graph state — independent of parent AgentState (D2)."""
from typing import Annotated, Optional

from langgraph.graph import MessagesState

from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.schemas.research import ResearcherTurn


class InvestDebateState(MessagesState):
    """Local state for the Bull/Bear sub-graph.

    Per D2 decision: raw debate messages live HERE only. The sub-graph judge
    returns just (BucketTarget, summary str) to the parent AgentState.
    """
    # Inputs from parent
    macro_summary: Annotated[str, "Handed off from MacroQuantAnalyst"]
    risk_summary: Annotated[str, "Handed off from MarketRiskAnalyst"]
    technical_summary: Annotated[str, "Handed off from TechnicalAnalyst"]
    news_summary: Annotated[str, "Handed off from MacroNewsAnalyst"]

    # Local cluster state — structured turns carry confidence + proposed_risk_tilt
    bull_arguments: Annotated[list[ResearcherTurn], "Bull researcher's turns across rounds"]
    bear_arguments: Annotated[list[ResearcherTurn], "Bear researcher's turns"]
    round_count: Annotated[int, "Completed debate rounds"]
    max_rounds_cap: Annotated[int, "Hard upper bound on rounds (adaptive may stop earlier)"]

    # Final
    bucket_target: Annotated[Optional[BucketTarget], "Research Manager's decision"]
    research_debate_summary: Annotated[str, "Summary handed back to parent"]
