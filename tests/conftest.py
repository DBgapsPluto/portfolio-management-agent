"""Shared pytest fixtures that prevent CI hangs when API keys are absent."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# PR2a: scripts/ is not a pip-installed package — add project root to sys.path
# so tests can `from scripts.calibrate_factor_model import ...`.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# pandas_ta shim — PyPI no longer ships pandas-ta for Python 3.11. Tests use
# `pandas_ta_classic` (drop-in fork) under the original module name.
if "pandas_ta" not in sys.modules:
    try:
        import pandas_ta_classic as _ta_classic  # type: ignore
        sys.modules["pandas_ta"] = _ta_classic
    except ImportError:
        pass  # let the test fail with the original ImportError


def pytest_configure(config):
    for marker in ("unit", "integration", "smoke"):
        config.addinivalue_line("markers", f"{marker}: {marker}-level tests")


_API_KEY_ENV_VARS = (
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "ZHIPU_API_KEY",
    "OPENROUTER_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
)


@pytest.fixture(autouse=True)
def _dummy_api_keys(monkeypatch):
    for env_var in _API_KEY_ENV_VARS:
        monkeypatch.setenv(env_var, os.environ.get(env_var, "placeholder"))


@pytest.fixture(autouse=True)
def _stable_pandas_copy_on_write():
    """Pin pandas Copy-on-Write to the project baseline (pandas 2.x default: off).

    `pandas_ta` (classic) enables CoW globally as an import side effect. Once any
    test importing it is collected, CoW stays on for the rest of the process,
    making `DataFrame.values` read-only and breaking `np.fill_diagonal(df.values)`
    in unrelated tests — purely as a function of collection order. Resetting before
    each test removes that ordering dependency. Production code is CoW-safe either
    way (it builds writable arrays via to_numpy(copy=True)/np.full/arithmetic).
    """
    import pandas as pd

    pd.set_option("mode.copy_on_write", False)
    yield


@pytest.fixture()
def mock_llm_client():
    client = MagicMock()
    client.get_llm.return_value = MagicMock()
    with patch(
        "tradingagents.llm_clients.factory.create_llm_client",
        return_value=client,
    ):
        yield client
