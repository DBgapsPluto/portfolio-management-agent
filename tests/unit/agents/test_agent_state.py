from tradingagents.agents.utils.agent_states import AgentState, _create_empty_state


def test_create_empty_state_has_defaults():
    s = _create_empty_state(
        as_of_date="2026-05-25",
        universe_path="data/universe.json",
        capital_krw=1_000_000_000,
        preset_name="db_gaps",
    )
    assert s["as_of_date"] == "2026-05-25"
    assert s["allocation_attempts"] == 0
    assert s["validation_passed"] is None


def test_state_has_summary_handoff_fields():
    """D2 hybrid topology: summaries between stages."""
    s = _create_empty_state(
        as_of_date="2026-05-25", universe_path="x",
        capital_krw=100, preset_name="db_gaps",
    )
    assert "macro_summary" in s
    assert "research_debate_summary" in s


def test_d4_cycle_fields():
    """D4 fields for Validator → Allocator retry cycle."""
    s = _create_empty_state(
        as_of_date="2026-05-25", universe_path="x",
        capital_krw=100, preset_name="db_gaps",
    )
    assert s["allocation_attempts"] == 0
    assert s["allocation_feedback"] == []
