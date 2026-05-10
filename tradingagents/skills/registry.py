from collections.abc import Callable
from typing import Any

_REGISTRY: dict[str, dict[str, Any]] = {}


def register_skill(name: str, category: str) -> Callable:
    """Decorator to register a deterministic skill function.

    Usage:
        @register_skill(name="fetch_fred_series", category="macro")
        def fetch_fred_series(series_id: str, ...) -> TimeSeries:
            ...
    """
    def decorator(fn: Callable) -> Callable:
        if name in _REGISTRY:
            raise ValueError(f"Skill '{name}' already registered")
        _REGISTRY[name] = {"fn": fn, "category": category, "kind": "deterministic"}
        return fn
    return decorator


def register_subagent(name: str, category: str) -> Callable:
    """Decorator to register a subagent (small LLM + schema-locked output)."""
    def decorator(fn: Callable) -> Callable:
        if name in _REGISTRY:
            raise ValueError(f"Skill '{name}' already registered")
        _REGISTRY[name] = {"fn": fn, "category": category, "kind": "subagent"}
        return fn
    return decorator


def get_skill(name: str) -> Callable:
    if name not in _REGISTRY:
        raise KeyError(f"unknown_skill: {name!r} not in registry")
    return _REGISTRY[name]["fn"]


def list_skills(category: str | None = None) -> list[str]:
    if category is None:
        return list(_REGISTRY.keys())
    return [n for n, meta in _REGISTRY.items() if meta["category"] == category]


def clear_registry() -> None:
    """Test-only: clear the global registry."""
    _REGISTRY.clear()
