from collections.abc import Callable
from typing import Any

_REGISTRY: dict[str, dict[str, Any]] = {}
# Permanent record of every skill registered this process. Survives
# clear_registry() so _reregister_all_skills() can restore the original
# function objects WITHOUT importlib.reload — reloading a skill module would
# replace the classes it defines (e.g. method_picker.MethodChoice), breaking
# isinstance() in any test that imported those classes at collection time.
_REGISTRY_BACKUP: dict[str, dict[str, Any]] = {}
_SKILL_MODULES: list[str] = [
    "tradingagents.skills.macro.yield_curve",
    "tradingagents.skills.macro.inflation",
    "tradingagents.skills.macro.employment",
    "tradingagents.skills.macro.fred_fetcher",
    "tradingagents.skills.macro.ecos_fetcher",
    "tradingagents.skills.macro.real_activity",
    "tradingagents.skills.macro.kr_valuation",
    "tradingagents.skills.macro.divergence",
    "tradingagents.skills.macro.calendar",
    "tradingagents.skills.macro.regime_classifier",
    "tradingagents.skills.risk.volatility",
    "tradingagents.skills.risk.realized_volatility",
    "tradingagents.skills.risk.credit_spread",
    "tradingagents.skills.risk.fear_greed",
    "tradingagents.skills.risk.breadth",
    "tradingagents.skills.risk.sector_dispersion",
    "tradingagents.skills.risk.correlation_pca",
    "tradingagents.skills.risk.systemic_score",
    "tradingagents.skills.technical.price_batch",
    "tradingagents.skills.technical.ta_indicators",
    "tradingagents.skills.technical.momentum_ranker",
    "tradingagents.skills.technical.trend_state",
    "tradingagents.skills.technical.correlation_cluster",
    "tradingagents.skills.technical.semi_momentum",
    "tradingagents.skills.macro.chip_cycle",
    "tradingagents.skills.macro.emerging_market",
    "tradingagents.skills.macro.kr_sector_export",
    "tradingagents.skills.news.event_calendar",
    "tradingagents.skills.news.news_fetcher",
    "tradingagents.skills.news.impact_classifier",
    "tradingagents.skills.news.ranker",
    "tradingagents.skills.portfolio.returns_matrix",
    "tradingagents.skills.mandate.universe_check",
    "tradingagents.skills.mandate.concentration_check",
    "tradingagents.skills.mandate.turnover_check",
    "tradingagents.skills.mandate.correlation_check",
    "tradingagents.skills.risk.reit_driver",
    "tradingagents.skills.risk.hy_decompression",
]


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
        entry = {"fn": fn, "category": category, "kind": "deterministic"}
        _REGISTRY[name] = entry
        _REGISTRY_BACKUP[name] = entry
        return fn
    return decorator


def register_subagent(name: str, category: str) -> Callable:
    """Decorator to register a subagent (small LLM + schema-locked output)."""
    def decorator(fn: Callable) -> Callable:
        if name in _REGISTRY:
            raise ValueError(f"Skill '{name}' already registered")
        entry = {"fn": fn, "category": category, "kind": "subagent"}
        _REGISTRY[name] = entry
        _REGISTRY_BACKUP[name] = entry
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


def _reregister_all_skills() -> None:
    """Test-only: re-register all built-in skills after clear_registry.

    This is needed because skill modules are cached in sys.modules, so importing
    them again won't trigger the @register_skill decorator. We clear the registry
    first, then reload all modules to re-trigger their @register_skill decorators.

    2026-05: per-module try/except so that optional skills with heavy deps
    (e.g. portfolio.optimizers → pypfopt → cvxpy → numpy 2.x) failing to import
    in a degraded test env doesn't abort the entire chain. Production envs that
    install the full lockfile import everything fine so this silent skip never
    affects them. Test-only function — no behavioral impact on production code.
    """
    import importlib

    _REGISTRY.clear()

    # Import (never reload) every skill module so first-time imports run their
    # @register_skill decorators into the backup. import_module is a no-op for
    # already-cached modules — their entries are restored from the backup below.
    # Avoiding reload keeps class identities stable (no broken isinstance()).
    for module_name in _SKILL_MODULES:
        try:
            importlib.import_module(module_name)
        except Exception:
            # Per-module isolation: degraded test envs may not have heavy deps.
            continue

    _REGISTRY.update(_REGISTRY_BACKUP)
