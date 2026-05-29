import sys
from pathlib import Path

import numpy as np
import pytest

# scripts/ is not on sys.path by default — add it explicitly (same pattern as other script tests)
_SCRIPTS_DIR = Path(__file__).parents[3] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import calibrate_factor_model_8b as cal  # noqa: E402
import validate_factor_model_8b as val   # noqa: E402


def test_calibrate_script_imports():
    assert hasattr(cal, "load_samples_8b")
    assert hasattr(cal, "grid_search_shrinkage")
    assert hasattr(cal, "main")


def test_validate_script_imports():
    assert hasattr(val, "validate")


def test_load_samples_missing_raises_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="Issue #18|not found"):
        cal.load_samples_8b(tmp_path / "nonexistent.parquet")


def test_validate_on_synthetic_samples(tmp_path):
    """validate() runs end-to-end on synthetic samples (no real parquet)."""
    from tradingagents.skills.research.factor_calibration import HistoricalSample
    from tradingagents.skills.research.factor_to_bucket import FACTORS, BUCKETS

    rng = np.random.default_rng(0)
    samples = [
        HistoricalSample(
            date=f"{2000+i//4}-03-31",
            factor_z={f: float(rng.normal(0, 1)) for f in FACTORS},
            bucket_returns_next={b: float(rng.normal(0, 0.05)) for b in BUCKETS},
        )
        for i in range(100)
    ]
    report = val.validate(samples, lambda_global=2.0, out_dir=tmp_path)
    assert "vif_max" in report and "effective_df" in report and "median_oos_sharpe" in report
    assert (tmp_path / "validation_report.json").exists()
    assert (tmp_path / "validation_report.md").exists()
