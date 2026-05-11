"""Portfolio Manager — generates 3 artifacts (portfolio.json, philosophy.md, trade_plan.csv).

Wires Plan 4 reports module:
- philosophy.md → tradingagents.reports.philosophy.write_philosophy (LLM-driven,
  6 mandatory 한국어 sections ≥4000 chars, retry once if short)
- trade_plan.csv → tradingagents.reports.trade_plan.write_trade_plan (6-column
  MTS format with 수량(주) computed from current ETF prices)

portfolio.json stays inline — no LLM/data dependency.
"""
import json
import logging
from datetime import date
from pathlib import Path

from tradingagents.dataflows.universe import load_universe
from tradingagents.reports.philosophy import write_philosophy
from tradingagents.reports.trade_plan import write_trade_plan

logger = logging.getLogger(__name__)


def _fetch_current_prices(as_of: date) -> dict[str, float]:
    """Best-effort: pykrx snapshot → {ticker_with_A_prefix: close}. Empty on failure."""
    try:
        from tradingagents.dataflows.pykrx_data import fetch_etf_snapshot_by_date
        snap = fetch_etf_snapshot_by_date(as_of)
        if snap.empty or "ticker" not in snap.columns or "close" not in snap.columns:
            return {}
        return {f"A{row['ticker']}": float(row["close"]) for _, row in snap.iterrows()}
    except Exception as e:
        logger.warning("current_prices fetch failed: %s — qty column will be 0", e)
        return {}


def create_portfolio_manager(deep_llm, artifacts_dir: str = "./artifacts"):
    def node(state):
        weights = state["weight_vector"]
        bucket = state.get("bucket_target")
        capital = state["capital_krw"]
        as_of_str = state["as_of_date"]
        as_of = date.fromisoformat(as_of_str)

        out_dir = Path(artifacts_dir) / as_of_str
        out_dir.mkdir(parents=True, exist_ok=True)

        universe = load_universe(state["universe_path"])
        universe_lookup = {
            e.ticker: {"name": e.name, "category": e.category}
            for e in universe.etfs
        }
        current_prices = _fetch_current_prices(as_of)

        # 1. portfolio.json (machine-readable, no LLM)
        portfolio = {
            "as_of_date": as_of_str,
            "capital_krw": capital,
            "method": weights.method.value,
            "bucket_target": bucket.model_dump() if bucket else None,
            "weights": weights.weights,
            "rationale": weights.rationale,
            "expected_volatility": weights.expected_volatility,
            "expected_sharpe": weights.expected_sharpe,
        }
        portfolio_path = out_dir / "portfolio.json"
        portfolio_path.write_text(
            json.dumps(portfolio, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # 2. trade_plan.csv (MTS-input, 6 columns w/ 수량(주))
        trade_plan_path = out_dir / "trade_plan.csv"
        write_trade_plan(
            weights=weights.weights,
            capital_krw=capital,
            universe_lookup=universe_lookup,
            current_prices=current_prices,
            out_path=trade_plan_path,
        )

        # 3. philosophy.md (LLM-driven, 6 sections ≥4000 chars per 대회 §4.1)
        philosophy_path = out_dir / "philosophy.md"
        write_philosophy(state, deep_llm, philosophy_path)

        return {
            "final_portfolio_path": str(portfolio_path),
            "philosophy_doc_path": str(philosophy_path),
            "trade_plan_csv_path": str(trade_plan_path),
        }

    return node
