"""DB GAPS AgentState — hybrid topology (D2) + Validator cycle (D4)."""
from typing import Annotated, Optional

from langgraph.graph import MessagesState

from tradingagents.schemas.mandate import ValidationReport, Violation
from tradingagents.schemas.portfolio import BucketTarget, CandidateSet, WeightVector
from tradingagents.schemas.reports import (
    MacroReport, RiskReport, TechnicalReport, NewsReport,
)
from tradingagents.schemas.research import ResearchDecision
from tradingagents.schemas.technical import Cluster


class AgentState(MessagesState):
    """Top-level state for the DB GAPS pipeline.

    D2 hybrid topology: stage outputs are stored as both Pydantic structured
    objects AND ≤2KB markdown summaries (`*_summary` fields). Downstream stages
    receive summaries via `input_from` mapping in the preset, not raw messages.

    Debate clusters use separate sub-graphs with their own DebateState; they
    return only `*_debate_summary` to this parent state.
    """

    # === Init ===
    as_of_date: Annotated[str, "ISO date for the run (e.g., 2026-05-25)"]
    universe_path: Annotated[str, "Path to universe.json"]
    capital_krw: Annotated[int, "Initial capital in KRW"]
    preset_name: Annotated[str, "Preset YAML name (e.g., db_gaps)"]

    # === Stage 1: Analyst outputs ===
    macro_report: Annotated[Optional[MacroReport], "Macro/Quant analyst output"]
    risk_report: Annotated[Optional[RiskReport], "Market Risk analyst output"]
    technical_report: Annotated[Optional[TechnicalReport], "Technical analyst output"]
    news_report: Annotated[Optional[NewsReport], "Macro News analyst output"]

    # Summary handoffs (D2)
    macro_summary: Annotated[str, "≤2KB markdown summary for downstream stages"]
    risk_summary: Annotated[str, ""]
    technical_summary: Annotated[str, ""]
    news_summary: Annotated[str, ""]

    # === Stage 2: Research (시나리오 estimator + 결정적 매핑) ===
    research_debate_summary: Annotated[str, "Stage 2 estimator summary (D2 isolation 유지)"]
    research_decision: Annotated[
        Optional[ResearchDecision],
        "Stage 2 풀 출력 — scenario probabilities + dominant + conviction + bucket_target",
    ]

    # === Stage 3: Research Manager (legacy 키, BucketTarget만 노출) ===
    bucket_target: Annotated[Optional[BucketTarget], "5-bucket weight target"]

    # === Stage 4: Allocator ===
    candidate_set: Annotated[Optional[CandidateSet], "Filtered ETF candidates"]
    weight_vector: Annotated[Optional[WeightVector], "Allocator output weights"]
    correlation_clusters: Annotated[list[Cluster], "From technical analyst, used for validation"]

    # === Stage 5: Risk debate ===
    risk_debate_summary: Annotated[str, "3-way debate summary"]

    # === Stage 6: Validation ===
    validation_report: Annotated[Optional[ValidationReport], "Mandate validator output"]
    validation_passed: Annotated[Optional[bool], "True/False/None pre-validation"]

    # D4: Validator cycle
    allocation_attempts: Annotated[int, "Retry counter for Validator → Allocator cycle"]
    allocation_feedback: Annotated[list[Violation], "Violations to inject into Allocator on retry"]

    # === Stage 7: Final ===
    final_portfolio_path: Annotated[str, "Path to artifacts/portfolio.json"]
    philosophy_doc_path: Annotated[str, ""]
    trade_plan_csv_path: Annotated[str, ""]

    # === Cross-run ===
    previous_portfolio: Annotated[Optional[dict], "For monthly rebalancing"]


def _create_empty_state(
    as_of_date: str,
    universe_path: str,
    capital_krw: int,
    preset_name: str,
    previous_portfolio: dict | None = None,
) -> AgentState:
    return AgentState(
        messages=[],
        as_of_date=as_of_date,
        universe_path=universe_path,
        capital_krw=capital_krw,
        preset_name=preset_name,
        macro_report=None, risk_report=None,
        technical_report=None, news_report=None,
        macro_summary="", risk_summary="",
        technical_summary="", news_summary="",
        research_debate_summary="",
        research_decision=None,
        bucket_target=None,
        candidate_set=None, weight_vector=None,
        correlation_clusters=[],
        risk_debate_summary="",
        validation_report=None, validation_passed=None,
        allocation_attempts=0, allocation_feedback=[],
        final_portfolio_path="", philosophy_doc_path="", trade_plan_csv_path="",
        previous_portfolio=previous_portfolio,
    )


# === LEGACY STATE CLASSES (D8 deprecate — Plan 3 Task 19) ===
# These are kept for backward compatibility with trading_graph.py
# They will be removed when the graph is rewritten per D8.
from typing_extensions import TypedDict


class InvestDebateState(TypedDict):
    """DEPRECATED: Legacy state for researcher debate. Kept for trading_graph compatibility."""
    bull_history: Annotated[
        str, "Bullish Conversation history"
    ]
    bear_history: Annotated[
        str, "Bearish Conversation history"
    ]
    history: Annotated[str, "Conversation history"]
    current_response: Annotated[str, "Latest response"]
    judge_decision: Annotated[str, "Final judge decision"]
    count: Annotated[int, "Length of the current conversation"]


class RiskDebateState(TypedDict):
    """DEPRECATED: Legacy state for risk management debate. Kept for trading_graph compatibility."""
    aggressive_history: Annotated[
        str, "Aggressive Agent's Conversation history"
    ]
    conservative_history: Annotated[
        str, "Conservative Agent's Conversation history"
    ]
    neutral_history: Annotated[
        str, "Neutral Agent's Conversation history"
    ]
    history: Annotated[str, "Conversation history"]
    latest_speaker: Annotated[str, "Analyst that spoke last"]
    current_aggressive_response: Annotated[
        str, "Latest response by the aggressive analyst"
    ]
    current_conservative_response: Annotated[
        str, "Latest response by the conservative analyst"
    ]
    current_neutral_response: Annotated[
        str, "Latest response by the neutral analyst"
    ]
    judge_decision: Annotated[str, "Judge's decision"]
    count: Annotated[int, "Length of the current conversation"]
