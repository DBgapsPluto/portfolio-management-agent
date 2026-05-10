"""Multi-agent tracing via LangSmith.

When LANGSMITH_TRACING=true, every analyst node, subagent skill, and LLM call
is captured as a span. View the run tree at https://smith.langchain.com/.

Usage:
    from tradingagents.observability.tracing import setup_tracing, traced
    setup_tracing()  # call once at app start

    @traced(name="my_skill")
    def my_skill(x):
        return x * 2
"""
import logging
import os
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def setup_tracing() -> None:
    """Enable LangSmith tracing if LANGSMITH_TRACING=true and key present.

    Must be called once at application start. LangChain auto-detects the
    environment variables; we just verify and log.
    """
    if os.getenv("LANGSMITH_TRACING", "false").lower() != "true":
        logger.info("LangSmith tracing disabled (set LANGSMITH_TRACING=true to enable)")
        return
    if not os.getenv("LANGSMITH_API_KEY"):
        logger.warning("LANGSMITH_TRACING=true but LANGSMITH_API_KEY missing; disabling")
        os.environ["LANGSMITH_TRACING"] = "false"
        return
    project = os.getenv("LANGSMITH_PROJECT", "db-gaps-agent")
    logger.info("LangSmith tracing enabled, project=%s", project)


def traced(name: str | None = None) -> Callable:
    """Decorator: wrap a callable as a LangSmith span.

    No-op when langsmith is not installed. Use on analyst nodes, skills, and
    any function whose I/O is worth inspecting in the run tree.
    """
    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        try:
            from langsmith import traceable
        except ImportError:
            return fn  # langsmith not installed — pass-through
        return traceable(name=name or fn.__name__)(fn)

    return decorator
