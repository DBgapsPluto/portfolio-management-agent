"""Stage 2 sub-graph state (D2 isolated topology, Phase 1).

Bull/Bear 토론 폐기. 단일 estimator 노드만 운영하지만, D2 isolation
(parent state에 raw 산출물이 안 새도록) 원칙은 유지한다.
"""
from typing import Annotated, Optional

from langgraph.graph import MessagesState

from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.schemas.research import ResearchDecision


class InvestDebateState(MessagesState):
    """Local state for the Stage 2 sub-graph.

    Phase 1: 단일 estimator 노드 → ResearchDecision 산출. parent로 넘어가는
    것은 (BucketTarget, ResearchDecision, summary str)뿐.
    """
    # Inputs from parent
    macro_summary: Annotated[str, "Handed off from MacroQuantAnalyst"]
    risk_summary: Annotated[str, "Handed off from MarketRiskAnalyst"]
    technical_summary: Annotated[str, "Handed off from TechnicalAnalyst"]
    news_summary: Annotated[str, "Handed off from MacroNewsAnalyst"]

    # Final outputs
    bucket_target: Annotated[Optional[BucketTarget], "결정적 매핑 산출"]
    research_decision: Annotated[
        Optional[ResearchDecision],
        "scenario probabilities + dominant + conviction + bucket_target",
    ]
    research_debate_summary: Annotated[str, "Summary handed back to parent"]
