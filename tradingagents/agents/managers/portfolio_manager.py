"""Portfolio Manager — generates 3 artifacts (portfolio.json, philosophy.md, trade_plan.csv).

Plan 3 Phase 5: this is the structural skeleton.
philosophy.md content fully implemented in Plan 4 with reports module.
"""
import csv
import json
from pathlib import Path

from tradingagents.dataflows.universe import load_universe


def create_portfolio_manager(deep_llm, artifacts_dir: str = "./artifacts"):
    def node(state):
        weights = state["weight_vector"]
        bucket = state.get("bucket_target")
        capital = state["capital_krw"]
        as_of = state["as_of_date"]

        out_dir = Path(artifacts_dir) / as_of
        out_dir.mkdir(parents=True, exist_ok=True)

        universe = load_universe(state["universe_path"])
        meta = {e.ticker: e for e in universe.etfs}

        # 1. portfolio.json
        portfolio = {
            "as_of_date": as_of,
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

        # 2. trade_plan.csv (current price column populated in Plan 4)
        trade_plan_path = out_dir / "trade_plan.csv"
        with open(trade_plan_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["티커", "ETF명", "자산군", "가중치", "매수금액(KRW)"])
            for ticker, weight in sorted(weights.weights.items(), key=lambda x: -x[1]):
                m = meta.get(ticker)
                w.writerow([
                    ticker,
                    m.name if m else "",
                    m.category if m else "",
                    f"{weight:.4f}",
                    int(weight * capital),
                ])

        # 3. philosophy.md (Plan 3 placeholder; Plan 4 reports module replaces)
        philosophy_path = out_dir / "philosophy.md"
        philosophy = (
            f"# 투자철학 ({as_of})\n\n"
            f"## 1. 매크로 판단\n"
            f"{state.get('macro_summary', '(missing)')}\n\n"
            f"## 2. 시장 리스크\n"
            f"{state.get('risk_summary', '(missing)')}\n\n"
            f"## 3. 자산군 비중 결정\n"
            f"{state.get('research_debate_summary', '(missing)')}\n\n"
            f"## 4. 단일 리스크 통제\n"
            f"{state.get('technical_summary', '(missing)')}\n\n"
            f"## 5. 매매 결정\n"
            f"{weights.rationale}\n\n"
            f"## 6. 시장 충격 시나리오\n"
            f"(Plan 4 reports module에서 채워짐 — 본 v1 Plan 3 placeholder)\n"
        )
        philosophy_path.write_text(philosophy, encoding="utf-8")

        return {
            "final_portfolio_path": str(portfolio_path),
            "philosophy_doc_path": str(philosophy_path),
            "trade_plan_csv_path": str(trade_plan_path),
        }

    return node
