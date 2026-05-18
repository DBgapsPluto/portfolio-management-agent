"""Portfolio Manager — generates 3 artifacts (portfolio.json, philosophy.md, trade_plan.csv).

Stage 6 정리:
  ① portfolio.json full trace — Stage 1-5 산출물 통합 (research_decision,
    method_choice, risk_overlay, portfolio_numerics, validation_report,
    rebalance_mode)
  ② philosophy.md prompt 섹션별 명시 매핑 (reports/philosophy.py)
  ③ trade_plan qty=0 명시 경고 (reports/trade_plan.py + state warnings)

portfolio.json: machine-readable, LLM 0회.
trade_plan.csv: MTS-input, LLM 0회. qty=0 발생 시 CSV 마지막에 경고 라인.
philosophy.md: LLM-driven (deep, 1-2회).
"""
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

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


def _serialize_for_json(value: Any) -> Any:
    """Pydantic / dict / list → JSON-safe nested structure."""
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except TypeError:
            return value.model_dump()
    if isinstance(value, dict):
        return {str(k): _serialize_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_for_json(v) for v in value]
    return value


def _build_full_trace_portfolio(state: dict) -> dict:
    """Stage 6 정리 ①: portfolio.json에 Stage 1-5 산출물 통합 (full trace)."""
    weights = state["weight_vector"]
    bucket = state.get("bucket_target")

    return {
        "as_of_date": state["as_of_date"],
        "capital_krw": state["capital_krw"],
        "method": weights.method.value,
        "bucket_target": bucket.model_dump() if bucket else None,
        "weights": weights.weights,
        "rationale": weights.rationale,
        "expected_volatility": weights.expected_volatility,
        "expected_sharpe": weights.expected_sharpe,
        # Stage 2 — Research Decision (시나리오 확률 + dominant + conviction)
        "research_decision": _serialize_for_json(state.get("research_decision")),
        # Stage 3 — Method choice (어느 optimizer가 선택됐는지)
        "method_choice": _serialize_for_json(state.get("method_choice")),
        # Stage 4 — Risk Overlay (lens_concerns + strength + ceilings/floors)
        "risk_overlay": _serialize_for_json(state.get("risk_overlay")),
        # Stage 4 — Portfolio Numerics (HHI/CVaR/cluster_exposure)
        "portfolio_numerics": _serialize_for_json(state.get("portfolio_numerics")),
        # Stage 5 — Validation (어떤 룰 통과/위반 + rebalance_mode)
        "validation_report": _serialize_for_json(state.get("validation_report")),
        "rebalance_mode": state.get("rebalance_mode"),
    }


def create_portfolio_manager(deep_llm, artifacts_dir: str = "./artifacts"):
    def node(state):
        weights = state["weight_vector"]
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

        # 1. portfolio.json (full trace, no LLM)
        portfolio = _build_full_trace_portfolio(state)
        portfolio_path = out_dir / "portfolio.json"
        portfolio_path.write_text(
            json.dumps(portfolio, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        # 2. trade_plan.csv (MTS-input, qty=0 warning row 포함)
        trade_plan_path = out_dir / "trade_plan.csv"
        _, zero_qty_tickers = write_trade_plan(
            weights=weights.weights,
            capital_krw=capital,
            universe_lookup=universe_lookup,
            current_prices=current_prices,
            out_path=trade_plan_path,
        )

        warnings_out = list(state.get("warnings", []) or [])
        if zero_qty_tickers:
            warning_msg = (
                f"trade_plan: {len(zero_qty_tickers)} ticker(s) have qty=0 "
                f"(current_prices fetch failed): {zero_qty_tickers[:5]}"
            )
            warnings_out.append(warning_msg)
            logger.warning(warning_msg)

        # 3. philosophy.md (LLM-driven, 6 sections, Stage 1-5 명시 매핑)
        philosophy_path = out_dir / "philosophy.md"
        write_philosophy(state, deep_llm, philosophy_path)

        return {
            "final_portfolio_path": str(portfolio_path),
            "philosophy_doc_path": str(philosophy_path),
            "trade_plan_csv_path": str(trade_plan_path),
            "warnings": warnings_out,
        }

    return node
