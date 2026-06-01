"""Pre-mock pypfopt/cvxpy so tradingagents.agents.__init__.py can be imported.

Python 3.11 + numpy 1.26 environment has a broken cvxpy that fails at import
time (numpy.lib.array_utils missing). pypfopt imports cvxpy at module load,
which poisons sys.modules['tradingagents.agents'] and prevents any agent test
from running. This conftest pre-injects a MagicMock shim before collection so
the import chain succeeds.
"""
import sys
from unittest.mock import MagicMock

# Only inject if not already importable (avoids masking real installs).
_needs_mock = False
try:
    import pypfopt as _pypfopt  # noqa: F401
except Exception:
    _needs_mock = True

if _needs_mock:
    for _mod in [
        "pypfopt",
        "pypfopt.black_litterman",
        "pypfopt.base_optimizer",
        "pypfopt.efficient_frontier",
        "pypfopt.expected_returns",
        "pypfopt.risk_models",
        "cvxpy",
    ]:
        if _mod not in sys.modules:
            sys.modules[_mod] = MagicMock()
