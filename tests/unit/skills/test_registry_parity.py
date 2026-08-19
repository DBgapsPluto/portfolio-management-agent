"""W3-5: _registry_init must mirror registry._SKILL_MODULES exactly.

Before this test, 10 of the 38 modules in _SKILL_MODULES were missing from
_registry_init and only registered via the _reregister_all_skills() backup
path — so app code that imported _registry_init and called get_skill() could
miss them. Computed programmatically (AST of _registry_init) so any future
drift in either direction fails here.
"""
import ast
import inspect

from tradingagents.skills import _registry_init
from tradingagents.skills.registry import _SKILL_MODULES


def _modules_imported_by_registry_init() -> set[str]:
    tree = ast.parse(inspect.getsource(_registry_init))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imported.add(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
    return {m for m in imported if m.startswith("tradingagents.skills.")}


def test_registry_init_mirrors_skill_modules():
    init_imports = _modules_imported_by_registry_init()
    listed = set(_SKILL_MODULES)
    missing_from_init = sorted(listed - init_imports)
    extra_in_init = sorted(init_imports - listed)
    assert init_imports == listed, (
        f"_registry_init drifted from registry._SKILL_MODULES — "
        f"missing from _registry_init: {missing_from_init}; "
        f"imported but not listed: {extra_in_init}"
    )


def test_skill_modules_has_no_duplicates():
    assert len(_SKILL_MODULES) == len(set(_SKILL_MODULES))
