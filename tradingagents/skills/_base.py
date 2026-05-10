import logging
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel

from tradingagents.skills._helpers import invoke_with_structured_retry

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
ModelTier = Literal["deep", "quick"]


class BaseSubagent:
    """Abstract subagent: small LLM + Pydantic-locked output.

    Per D6 decision: every subagent inherits this contract.
    Per D7: retry/validation handled by invoke_with_structured_retry helper.
    """

    def __init__(
        self,
        name: str,
        tier: ModelTier,
        schema: type[T],
        prompt_path: Path | str,
        llm_quick,
        llm_deep,
        max_retries: int = 1,
    ):
        self.name = name
        self.tier: ModelTier = tier
        self.schema = schema
        self.prompt_template = Path(prompt_path).read_text(encoding="utf-8")
        self.llm = llm_deep if tier == "deep" else llm_quick
        self.max_retries = max_retries

    def _build_messages(self, **inputs) -> list[dict]:
        """Render the prompt template with inputs."""
        try:
            user_content = self.prompt_template.format(**inputs)
        except KeyError as e:
            raise KeyError(f"Subagent {self.name!r} prompt missing variable: {e}")
        return [{"role": "user", "content": user_content}]

    def invoke(self, **inputs) -> T:
        messages = self._build_messages(**inputs)
        logger.debug("Subagent %s invoking with tier=%s", self.name, self.tier)
        return invoke_with_structured_retry(
            self.llm, self.schema, messages, max_retries=self.max_retries
        )
