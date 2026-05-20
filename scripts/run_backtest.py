"""Backtest the full pipeline across multiple historical regimes.

Runs the E2E pipeline for each as_of date, saves artifacts, and emits a
side-by-side comparison summary (regime classification, bucket target, method,
expected vol/Sharpe, validation status).

Usage:
    python scripts/run_backtest.py
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import date
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s — %(message)s",
)
logger = logging.getLogger("backtest")


REGIMES = [
    ("2022-12-15", "Hawkish Fed peak (rates 4.5%, CPI 7%+, KR rate hike)"),
    ("2023-04-14", "Post-SVB credit stress (BTFP, regional bank stress)"),
    ("2024-08-14", "Sahm rule first triggered (UR rises, false alarm?)"),  # 08-15 광복절 회피
    ("2025-04-15", "Tariff shock / Trump 25% (KR exports risk, vol spike)"),
    ("2026-05-15", "Current — already run; will skip if artifacts exist"),
]


def _safe_round(val, digits: int = 2):
    """Round but tolerate None / missing fields."""
    if val is None:
        return None
    try:
        return round(float(val), digits)
    except (TypeError, ValueError):
        return None


def run_one(as_of: str) -> dict | None:
    """Run pipeline for one date. Return summary dict or None on failure."""
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    logger.info("=" * 70)
    logger.info("RUNNING as_of=%s", as_of)
    logger.info("=" * 70)

    t0 = time.time()
    try:
        graph = TradingAgentsGraph(preset_name="db_gaps")
    except Exception as e:
        logger.exception("Graph init failed: %s", e)
        return None

    try:
        result = graph.run(as_of_date=as_of, capital_krw=1_000_000_000)
    except Exception as e:
        logger.exception("Pipeline run failed for %s: %s", as_of, e)
        return None

    elapsed = time.time() - t0

    artifact_path = result.get("final_portfolio_path")
    if not artifact_path or not Path(artifact_path).exists():
        logger.warning("Missing portfolio.json for %s", as_of)
        return None

    portfolio = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
    rd = portfolio.get("research_decision", {})
    bt = portfolio.get("bucket_target", {})
    mc = portfolio.get("method_choice", {})
    vr = portfolio.get("validation_report", {})

    pn = portfolio.get("portfolio_numerics") or {}
    return {
        "as_of": as_of,
        "elapsed_sec": _safe_round(elapsed, 1),
        "dominant_cycle": rd.get("dominant_cycle"),
        "dominant_cycle_prob": _safe_round(rd.get("dominant_cycle_probability"), 3),
        "conviction": rd.get("conviction"),
        "conviction_beta": _safe_round(rd.get("conviction_beta"), 2),
        "dominant_cell": rd.get("dominant_cell"),
        "dominant_cell_prob": _safe_round(rd.get("dominant_cell_probability"), 3),
        "tail_marginals": {k: _safe_round(v, 3) for k, v in (rd.get("tail_marginals") or {}).items()},
        "kr_marginals": {k: _safe_round(v, 3) for k, v in (rd.get("kr_marginals") or {}).items()},
        "bucket_target": {
            k: _safe_round(v, 3) if isinstance(v, (int, float)) else v
            for k, v in bt.items() if k not in ("rationale",)
        },
        "method": mc.get("method"),
        "method_reasoning": (mc.get("reasoning") or "")[:120],
        "expected_volatility_pct": _safe_round(portfolio.get("expected_volatility"), 2),
        "expected_sharpe": _safe_round(portfolio.get("expected_sharpe"), 3),
        "n_assets": pn.get("n_assets"),
        "hhi": _safe_round(pn.get("hhi"), 3),
        "max_cluster_exposure": _safe_round(pn.get("max_cluster_exposure"), 3),
        "validation_passed": vr.get("passed"),
        "rebalance_mode": portfolio.get("rebalance_mode"),
    }


def format_table(rows: list[dict]) -> str:
    """ASCII summary table."""
    if not rows:
        return "(no runs completed)"

    out = []
    out.append("=" * 100)
    out.append(" BACKTEST SUMMARY")
    out.append("=" * 100)

    def _fmt(v, spec):
        return format(v, spec) if v is not None else "—"

    for r in rows:
        out.append("")
        out.append(f"## {r['as_of']}  ({r.get('elapsed_sec', '—')}s)  {r.get('regime_label','')}")
        out.append(
            f"  Cycle:    {r['dominant_cycle']!s:<4} ({_fmt(r['dominant_cycle_prob'], '.0%')}) "
            f"conviction={r['conviction']} (β={_fmt(r['conviction_beta'], '.2f')})"
        )
        out.append(
            f"  Cell:     {r['dominant_cell']} ({_fmt(r['dominant_cell_prob'], '.0%')})"
        )
        out.append(f"  Tail:     {r['tail_marginals']}")
        out.append(f"  KR:       {r['kr_marginals']}")
        out.append(f"  Buckets:  {r['bucket_target']}")
        out.append(f"  Method:   {r['method']}  — {r['method_reasoning']}")
        out.append(
            f"  Vol:      {_fmt(r['expected_volatility_pct'], '.1f')}%  "
            f"Sharpe={_fmt(r['expected_sharpe'], '.3f')}  "
            f"n_assets={r['n_assets']}  HHI={_fmt(r['hhi'], '.3f')}  "
            f"max_cluster={_fmt(r['max_cluster_exposure'], '.1%')}"
        )
        out.append(
            f"  Status:   passed={r['validation_passed']}  mode={r['rebalance_mode']}"
        )

    out.append("")
    out.append("=" * 100)
    return "\n".join(out)


def main() -> int:
    # Sys.path setup so module imports work without pip install -e .
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    rows: list[dict] = []
    for as_of, label in REGIMES:
        existing_summary = Path(f"artifacts/{as_of}/backtest_summary.json")
        if existing_summary.exists():
            logger.info("Loading cached summary for %s", as_of)
            rows.append(json.loads(existing_summary.read_text(encoding="utf-8")))
            continue

        logger.info("Regime label: %s", label)
        summary = run_one(as_of)
        if summary is None:
            logger.error("Skipping %s — failed", as_of)
            continue
        summary["regime_label"] = label
        rows.append(summary)
        out_path = Path(f"artifacts/{as_of}/backtest_summary.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Wrote %s", out_path)

    text = format_table(rows)
    print(text)

    combined = Path("artifacts/backtest_summary.json")
    combined.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    Path("artifacts/backtest_summary.txt").write_text(text, encoding="utf-8")
    logger.info("Combined summary → %s", combined)

    return 0


if __name__ == "__main__":
    sys.exit(main())
