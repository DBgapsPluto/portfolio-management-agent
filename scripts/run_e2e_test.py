"""End-to-end pipeline test with real data + real LLM.

Usage:
    set -a && source .env && set +a
    python scripts/run_e2e_test.py --as-of 2026-05-15 --capital 1000000000
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date
from pathlib import Path

# .env auto-load (FRED/ECOS/OPENAI/KRX keys). 다른 backtest 스크립트들과 동일 패턴.
_ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_ROOT / ".env")
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default="2026-05-15", help="YYYY-MM-DD")
    parser.add_argument("--capital", type=int, default=1_000_000_000)
    parser.add_argument("--preset", default="db_gaps")
    args = parser.parse_args()

    # date 검증
    try:
        date.fromisoformat(args.as_of)
    except ValueError:
        logger.error("Invalid date: %s", args.as_of); return 1

    # Imports late so logging is configured
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    logger.info("=" * 70)
    logger.info("E2E TEST — as_of=%s, capital=%s KRW, preset=%s",
                args.as_of, f"{args.capital:,}", args.preset)
    logger.info("=" * 70)

    t0 = time.time()

    try:
        graph = TradingAgentsGraph(preset_name=args.preset)
    except Exception as e:
        logger.exception("Graph init failed: %s", e)
        return 2

    logger.info("Graph initialized in %.1fs", time.time() - t0)
    logger.info("Running pipeline ...")

    t1 = time.time()
    try:
        result = graph.run(
            as_of_date=args.as_of,
            capital_krw=args.capital,
        )
    except Exception as e:
        logger.exception("Pipeline run failed: %s", e)
        return 3

    elapsed = time.time() - t1
    logger.info("=" * 70)
    logger.info("PIPELINE COMPLETE in %.1fs", elapsed)
    logger.info("=" * 70)

    # Result summary
    logger.info("\n--- Artifacts ---")
    for key in ("final_portfolio_path", "philosophy_doc_path", "trade_plan_csv_path"):
        path = result.get(key)
        if path:
            p = Path(path)
            size = p.stat().st_size if p.exists() else 0
            logger.info("  %s: %s (%d bytes)",
                        key, path, size)
        else:
            logger.warning("  %s: missing", key)

    warnings = result.get("warnings", []) or []
    if warnings:
        logger.warning("\n--- Warnings (%d) ---", len(warnings))
        for w in warnings:
            logger.warning("  %s", w)

    # State summary
    logger.info("\n--- State trace ---")
    val = result.get("validation_report")
    if val:
        n_hard = sum(1 for v in val.violations if v.severity == "hard")
        logger.info("  validation: passed=%s, hard=%d, soft=%d",
                    val.passed, n_hard, len(val.violations) - n_hard)

    rd = result.get("research_decision")
    if rd:
        # C5 (2026-05-23): 24-cell field 제거됨. factor model 의 scenario / conviction
        # + top factor z-scores 만 로그.
        top_factors = sorted(
            (rd.factor_scores or {}).items(),
            key=lambda kv: -abs(kv[1] or 0),
        )[:3]
        top_str = ", ".join(f"{f}={z:+.2f}" for f, z in top_factors)
        logger.info(
            "  research: scenario=%s, conviction=%s, top factors: %s",
            rd.dominant_scenario, rd.conviction, top_str,
        )

    overlay = result.get("risk_overlay")
    if overlay:
        logger.info("  overlay: strength=%.2f, mult=%.2f, empty=%s",
                    overlay.strength_applied,
                    overlay.risk_asset_multiplier,
                    overlay.is_empty())

    rebalance = result.get("rebalance_mode")
    if rebalance:
        logger.info("  rebalance_mode: %s", rebalance)

    # portfolio.json full trace verification
    portfolio_path = result.get("final_portfolio_path")
    if portfolio_path:
        try:
            data = json.loads(Path(portfolio_path).read_text(encoding="utf-8"))
            logger.info("\n--- portfolio.json keys ---")
            for k in data.keys():
                v = data[k]
                if isinstance(v, dict):
                    logger.info("  %s: dict (%d keys)", k, len(v))
                elif isinstance(v, list):
                    logger.info("  %s: list (%d items)", k, len(v))
                else:
                    sval = str(v)[:60]
                    logger.info("  %s: %s", k, sval)
        except Exception as e:
            logger.warning("portfolio.json parse failed: %s", e)

    logger.info("\nE2E test complete. Total elapsed: %.1fs", time.time() - t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
