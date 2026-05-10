import pytest
from pydantic import ValidationError

from tradingagents.presets.spec import (
    PresetSpec, AgentSpec, StageSpec, ClusterMode,
)


def test_minimal_preset():
    p = PresetSpec(
        name="test",
        universe="data/u.json",
        capital_krw=1_000_000_000,
        stages=[
            StageSpec(
                id="analysts", parallel=True,
                agents=[
                    AgentSpec(
                        id="macro", skills=["fred_series"],
                        output_schema="MacroReport", model="deep",
                    )
                ],
            ),
        ],
    )
    assert p.name == "test"
    assert p.stages[0].parallel is True


def test_cluster_mode_enum():
    s = StageSpec(
        id="debate", cluster_mode=ClusterMode.SHARED_STATE,
        agents=[AgentSpec(id="bull", skills=[], output_schema="DebateMessage")],
    )
    assert s.cluster_mode == "shared_state"


def test_invalid_yaml_rejected():
    with pytest.raises(ValidationError):
        PresetSpec(
            name="bad",
            universe="x",
            capital_krw=-1,
            stages=[],
        )
