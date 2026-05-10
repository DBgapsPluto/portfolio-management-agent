"""Risk debate sub-graph state — independent of parent AgentState (D2)."""
from typing import Annotated, Optional

from langgraph.graph import MessagesState

from tradingagents.schemas.portfolio import WeightVector


class RiskDebateState(MessagesState):
    """Local state for the 3-way risk debate sub-graph.

    Per D2: raw debate messages live HERE only. Judge returns
    (WeightAdjustment dict, summary str) to parent.
    """
    weight_vector_input: Annotated[Optional[WeightVector], "Allocator's proposed weights"]
    correlation_clusters_summary: Annotated[str, "From technical analyst"]
    macro_summary: Annotated[str, ""]
    risk_summary: Annotated[str, ""]

    aggressive_arguments: Annotated[list[str], ""]
    conservative_arguments: Annotated[list[str], ""]
    neutral_arguments: Annotated[list[str], ""]
    round_count: Annotated[int, ""]
    max_rounds: Annotated[int, ""]

    weight_adjustment: Annotated[Optional[dict], "Final adjustment recommendation"]
    risk_debate_summary: Annotated[str, "Summary handed back to parent"]
