"""Smoke test for measure_stage2_ablation.py — module import + _apply_mode logic.

scripts/ 는 패키지가 아니라 importlib.util 로 file path 직접 load.
"""
import importlib.util
from pathlib import Path

import pytest


_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "measure_stage2_ablation.py"


def _load_mod():
    spec = importlib.util.spec_from_file_location(
        "measure_stage2_ablation", _SCRIPT_PATH,
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_module_imports():
    """script가 import 가능해야 (top-level syntax/dep error 없음)."""
    mod = _load_mod()
    assert hasattr(mod, "main")
    assert hasattr(mod, "_apply_mode")
    assert hasattr(mod, "_QUADRANT_PERTURBATION")


def test_apply_mode_baseline_passthrough():
    """baseline mode 는 state 변경 X."""
    mod = _load_mod()
    state = {"macro_summary": "hello", "other": 42}
    result = mod._apply_mode(state, "baseline")
    assert result == state


def test_apply_mode_no_macro_clears():
    mod = _load_mod()
    state = {"macro_summary": "growth_inflation regime", "other": 42}
    result = mod._apply_mode(state, "no_macro")
    assert result["macro_summary"] == ""
    assert result["other"] == 42


def test_apply_mode_no_macro_does_not_mutate_input():
    mod = _load_mod()
    state = {"macro_summary": "growth_inflation regime", "other": 42}
    _ = mod._apply_mode(state, "no_macro")
    assert state["macro_summary"] == "growth_inflation regime"


def test_apply_mode_unknown_raises():
    mod = _load_mod()
    with pytest.raises(ValueError, match="Unknown mode"):
        mod._apply_mode({}, "invalid_mode")


def test_quadrant_perturbation_swap_is_orthogonal():
    """perturbation map: growth↔recession AND inflation↔disinflation 동시 swap."""
    mod = _load_mod()
    pert = mod._QUADRANT_PERTURBATION
    assert pert["growth_inflation"] == "recession_disinflation"
    assert pert["recession_disinflation"] == "growth_inflation"
    assert pert["growth_disinflation"] == "recession_inflation"
    assert pert["recession_inflation"] == "growth_disinflation"
