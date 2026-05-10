from pathlib import Path

import yaml
from pydantic import ValidationError

from tradingagents.presets.spec import PresetSpec
from tradingagents.skills.registry import list_skills


class PresetLoadError(Exception):
    """Preset YAML failed to load or validate."""


class PresetLoader:
    """Load and validate a preset YAML file (D3)."""

    @staticmethod
    def from_yaml(path: Path | str) -> PresetSpec:
        path = Path(path)
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise PresetLoadError(f"YAML parse error in {path}: {e}") from e

        try:
            spec = PresetSpec.model_validate(raw)
        except ValidationError as e:
            raise PresetLoadError(f"Schema error in {path}: {e}") from e

        # Validate skill names against registry
        known = set(list_skills())
        for stage in spec.stages:
            for agent in stage.agents:
                for skill_name in agent.skills:
                    if skill_name not in known:
                        raise PresetLoadError(
                            f"unknown skill {skill_name!r} in agent {agent.id!r} "
                            f"(stage {stage.id!r}). Known: {sorted(known)[:5]}..."
                        )
        return spec
