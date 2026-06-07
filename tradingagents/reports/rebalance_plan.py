"""리밸런싱 산출물 — (rebalancing)_plan.csv + (rebalancing).json (스펙 §8)."""
import csv
import json
from dataclasses import asdict
from pathlib import Path

from tradingagents.rebalance.types import RebalanceResult


def write_rebalance_plan(result: RebalanceResult, universe_lookup: dict, out_path: Path) -> Path:
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["티커", "ETF명", "자산군", "현재수량", "목표수량",
                    "매매구분", "거래수량", "거래금액(KRW)"])
        for tl in result.plan:
            meta = universe_lookup.get(tl.ticker, {})
            w.writerow([tl.ticker, meta.get("name", ""), meta.get("category", ""),
                        tl.current_qty, tl.target_qty, tl.action,
                        tl.delta_qty, tl.delta_amount_krw])
        f.write(f"# CASH_RESIDUAL_KRW: {result.cash_residual_krw}\n")
        f.write(f"# CASH_WEIGHT: {result.realized_weights.get('CASH', 0.0):.6f}\n")
    return out_path


def write_rebalance_json(result: RebalanceResult, out_path: Path, previous_path: str) -> Path:
    validation = result.validation
    payload = {
        "as_of_date": result.as_of,
        "tier": result.tier,
        "trigger": result.trigger,
        "current_weights": result.current_weights,
        "target_weights": result.target_weights,
        "realized_weights": result.realized_weights,
        "plan": [asdict(tl) for tl in result.plan],
        "turnover": result.turnover,
        "cash_residual_krw": result.cash_residual_krw,
        "skipped_no_trade": result.skipped_no_trade,
        "validation": (validation.model_dump() if hasattr(validation, "model_dump")
                       else validation),
        "previous_portfolio_path": previous_path,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8")
    return out_path
