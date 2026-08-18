"""WP-F F-4 — calibration re-run on the new Σ with the plan's sweep values.

Thin wrapper over backtest_bl_calibration.main(): overrides TURNOVER_SWEEP to
the plan-specified {0.35, 0.50, 0.65} (module default sweeps 0.15..1.00) and
runs at a recent as_of so Σ v2 (KRW + weekly) governs. Dial changes remain
user-approval only — this script only measures.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

import backtest_bl_calibration as cal  # noqa: E402

cal.TURNOVER_SWEEP = [0.35, 0.50, 0.65]

if __name__ == "__main__":
    raise SystemExit(cal.main(["--as-of", "2026-08-14", "--window-days", "1825"]))
