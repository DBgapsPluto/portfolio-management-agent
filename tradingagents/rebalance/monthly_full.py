"""Monthly rebalancing — full pipeline + monthly report."""
from dataclasses import dataclass
from datetime import date

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph


@dataclass
class MonthlyResult:
    portfolio_path: str
    report_path: str | None
    summary: str

    def __str__(self):
        return self.summary


def run(month: int,
        as_of: str | None = None,
        previous_path: str | None = None) -> MonthlyResult:
    """Run full monthly pipeline. Monthly report needs MTS P&L CSV — caller
    invokes `gaps report monthly` separately once trades settle."""
    target = as_of or date.today().isoformat()

    graph = TradingAgentsGraph()
    final = graph.run(
        as_of_date=target,
        capital_krw=DEFAULT_CONFIG.get("capital_krw", 1_000_000_000),
    )

    return MonthlyResult(
        portfolio_path=final["final_portfolio_path"],
        report_path=None,
        summary=(
            f"Month {month} rebalance complete: {final['final_portfolio_path']}"
        ),
    )
