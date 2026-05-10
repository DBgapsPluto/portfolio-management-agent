import logging
from typing import TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def invoke_with_structured_retry(
    llm,
    schema: type[T],
    messages: list[dict],
    max_retries: int = 1,
) -> T:
    """Invoke an LLM with a Pydantic-locked schema, retrying on validation failure.

    Used by both BaseSubagent and analyst nodes per D7 decision.

    Args:
        llm: A LangChain LLM client (must support .with_structured_output).
        schema: Pydantic class for output schema.
        messages: List of {"role": ..., "content": ...} dicts.
        max_retries: Number of retries on ValidationError (default 1).

    Returns:
        Validated schema instance.

    Raises:
        ValidationError: If retries exhausted.
    """
    structured = llm.with_structured_output(schema)
    last_err: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return structured.invoke(messages)
        except ValidationError as e:
            last_err = e
            logger.warning(
                "Schema validation failed on attempt %d/%d for %s: %s",
                attempt + 1, max_retries + 1, schema.__name__, e,
            )
            if attempt < max_retries:
                # Inject the error into the conversation so the model can self-correct.
                messages = list(messages) + [
                    {
                        "role": "system",
                        "content": (
                            f"Your previous response failed schema validation: {e}. "
                            f"Output ONLY a valid {schema.__name__} JSON object."
                        ),
                    }
                ]
    assert last_err is not None
    raise last_err
