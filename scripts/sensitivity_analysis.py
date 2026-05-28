"""CLI for Stage 3 weight/boost sensitivity analysis.

Usage:
    python scripts/sensitivity_analysis.py [--delta 20] [--out artifacts/sensitivity.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(dotenv_path=_ROOT / ".env")

from tradingagents.observability.sensitivity import (
    run_sensitivity, format_report,
)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--catalog", default=str(_ROOT / "data" / "historical_anchors"))
    p.add_argument("--universe", default=str(_ROOT / "data" / "universe.json"))
    p.add_argument(
        "--cache",
        default=str(Path.home() / ".tradingagents" / "cache" / "etf_prices.parquet"),
    )
    p.add_argument("--delta", type=float, default=20.0,
                   help="perturbation %% (default 20)")
    p.add_argument("--no-regime", action="store_true",
                   help="regime_weight perturbation 건너뛰기")
    p.add_argument("--no-boost", action="store_true",
                   help="boost dict perturbation 건너뛰기")
    p.add_argument("--out", default=None)
    args = p.parse_args()

    print(f"\n=== Stage 3 Sensitivity Analysis (Δ=±{args.delta:.0f}%) ===\n")
    rows = run_sensitivity(
        args.catalog,
        universe_path=args.universe, cache_path=args.cache,
        delta_pct=args.delta,
        include_regime=not args.no_regime,
        include_boost=not args.no_boost,
    )
    print(format_report(rows))

    out_path = args.out or str(_ROOT / "artifacts" / "sensitivity.json")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps([r.to_dict() for r in rows], indent=2,
                   ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(f"\n  → JSON saved: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
