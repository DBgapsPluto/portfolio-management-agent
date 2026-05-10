from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ClusterMode(str, Enum):
    SHARED_STATE = "shared_state"      # debate cluster (D2)
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


ModelTier = Literal["deep", "quick"]


class AgentSpec(BaseModel):
    id: str
    skills: list[str] = Field(default_factory=list, description="Whitelisted skill names")
    output_schema: Optional[str] = Field(default=None, description="Pydantic class name")
    model: ModelTier = "deep"
    timeout_seconds: int = Field(default=180, ge=10)
    max_iterations: int = Field(default=25, ge=1)
    skill_prompt_base: Optional[str] = Field(default=None, description="Path to base prompt MD")
    cited_evidence_required: bool = False
    input_from: dict[str, str] = Field(
        default_factory=dict,
        description="Map of {context_key: source_agent_id} for handoff",
    )


class StageSpec(BaseModel):
    id: str
    parallel: bool = False
    cluster_mode: Optional[ClusterMode] = None
    rounds: int = Field(default=1, ge=1)
    agents: list[AgentSpec] = Field(min_length=1)
    judge: Optional[AgentSpec] = None
    on_fail: Optional[str] = Field(default=None, description="e.g., 'rerun_from(allocation, max_attempts=2)'")


class PresetSpec(BaseModel):
    name: str = Field(min_length=1)
    universe: str = Field(description="Path to universe.json")
    capital_krw: int = Field(ge=1)
    stages: list[StageSpec]
