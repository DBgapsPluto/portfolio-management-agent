"""Integration test — PR2a calibrate pipeline on synthetic data."""
import importlib.util
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# scripts/ is not a pip-installed package — load via importlib for test import.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CALIBRATE_PATH = _PROJECT_ROOT / "scripts" / "calibrate_factor_model.py"
_spec = importlib.util.spec_from_file_location(
    "_pr2a_calibrate", _CALIBRATE_PATH,
)
_calibrate_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_calibrate_mod)
load_samples_from_parquet = _calibrate_mod.load_samples_from_parquet

from tradingagents.skills.research.factor_to_bucket import (
    BUCKETS, FACTORS, INITIAL_BETA,
)


_DATACLASS_FACTOR_NAMES = (
    "growth_surprise", "inflation_surprise", "real_rate",
    "term_premium", "credit_cycle", "krw_regime",
    "equity_vol_regime", "valuation", "market_dispersion",
    "systemic_liquidity", "earnings_revision", "china_credit_impulse",
)


def _build_synthetic_samples(n: int = 135, seed: int = 42) -> pd.DataFrame:
    """Synthetic factor z + bucket returns with known underlying β.

    Uses dataclass field names ("growth_surprise" 등) to match real
    samples.parquet format (generate_historical_factor_z.py 출력).
    """
    rng = np.random.default_rng(seed)
    factor_z = rng.standard_normal((n, len(_DATACLASS_FACTOR_NAMES)))
    fz_df = pd.DataFrame(factor_z, columns=list(_DATACLASS_FACTOR_NAMES))
    conf_df = pd.DataFrame(
        np.full((n, len(_DATACLASS_FACTOR_NAMES)), 0.85),
        columns=[f"{f}_conf" for f in _DATACLASS_FACTOR_NAMES],
    )

    bucket_returns = np.zeros((n, len(BUCKETS)))
    for i in range(n):
        for j, b in enumerate(BUCKETS):
            for k, f in enumerate(FACTORS):
                # factor_z columns are dataclass-named (k-indexed = aligned with FACTORS)
                bucket_returns[i, j] += INITIAL_BETA.get((f, b), 0.0) * factor_z[i, k]
            if b in ("kr_equity", "global_equity"):
                bucket_returns[i, j] += 0.015
            elif b == "bond":
                bucket_returns[i, j] += 0.008
            elif b == "cash_mmf":
                bucket_returns[i, j] += 0.005
            bucket_returns[i, j] += rng.normal(0, 0.04)
    br_df = pd.DataFrame(bucket_returns,
                          columns=[f"next_{b}" for b in BUCKETS])

    index = pd.date_range("1991-03-31", periods=n, freq="QE")
    combined = pd.concat([fz_df, conf_df, br_df], axis=1)
    combined.index = index
    combined.index.name = "quarter_end"
    return combined


def test_load_samples_from_parquet(tmp_path: Path) -> None:
    """Load samples → HistoricalSample list."""
    samples_df = _build_synthetic_samples(n=10)
    p = tmp_path / "samples.parquet"
    samples_df.to_parquet(p)

    samples = load_samples_from_parquet(p)
    assert len(samples) == 10
    s0 = samples[0]
    # Legacy 9-factor loader (calibrate_factor_model.py, superseded by _8b for the
    # full 12-factor path) maps exactly the keys it declares in _PARQUET_TO_FACTOR_KEY.
    assert set(s0.factor_z.keys()) == set(_calibrate_mod._PARQUET_TO_FACTOR_KEY.values())
    assert set(s0.bucket_returns_next.keys()) == set(BUCKETS)


def test_walk_forward_synthetic_produces_7_folds(tmp_path: Path) -> None:
    """135 sample → walk_forward(initial_train=80, test=7) → 7 folds."""
    from tradingagents.skills.research.factor_calibration import walk_forward

    samples_df = _build_synthetic_samples(n=135)
    p = tmp_path / "samples.parquet"
    samples_df.to_parquet(p)

    samples = load_samples_from_parquet(p)
    folds = walk_forward(
        samples, initial_train_size=80, test_window=7,
        shrinkage=0.5, prior_beta=INITIAL_BETA,
    )
    assert len(folds) == 7
    assert folds[0].train_end_idx == 80
    assert folds[6].test_end_idx == 129
