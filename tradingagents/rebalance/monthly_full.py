"""Monthly rebalancing — full pipeline + 델타 거래계획 (스펙 §6.3, §9)."""
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.dataflows.universe import load_universe
from tradingagents.rebalance.pricing import fetch_current_prices
from tradingagents.rebalance.holdings import load_prev_holdings
from tradingagents.rebalance.engine import run_rebalance


@dataclass
class MonthlyResult:
    portfolio_path: str
    rebalance_paths: dict
    summary: str

    def __str__(self):
        return self.summary


def _build_deep_llm():
    """deep LLM for monthly rationale (LLM 서술). 테스트에서 monkeypatch 가능."""
    from tradingagents.llm_clients import create_llm_client
    return create_llm_client(
        provider=DEFAULT_CONFIG["llm_provider"],
        model=DEFAULT_CONFIG["deep_think_llm"],
    ).get_llm()


def run(month: int, as_of: str | None = None,
        previous_path: str | None = None) -> MonthlyResult:
    target = as_of or date.today().isoformat()
    capital = DEFAULT_CONFIG.get("capital_krw", 1_000_000_000)

    prev_portfolio = None
    prev_weights = None
    if previous_path:
        pj = Path(previous_path) / "portfolio.json"
        if pj.exists():
            prev_portfolio = json.loads(pj.read_text(encoding="utf-8"))
            prev_weights = prev_portfolio.get("weights")

    # 1) full pipeline — 새 목표 (gap #1: previous 전달)
    graph = TradingAgentsGraph()
    final = graph.run(as_of_date=target, capital_krw=capital,
                      previous_portfolio=prev_portfolio)
    target_weights = final["weight_vector"].weights
    universe = load_universe(Path(final["universe_path"]))
    clusters = final.get("correlation_clusters", [])   # 이번 run 의 Cluster 객체

    # 2) 직전 보유 재평가 → 델타 거래계획
    prev_qty, prev_cash = ({}, 0)
    if previous_path:
        prev_qty, prev_cash = load_prev_holdings(Path(previous_path))
    prices = fetch_current_prices(date.fromisoformat(target))

    dials = DEFAULT_CONFIG.get("rebalance", {})
    out_dir = Path(DEFAULT_CONFIG.get("artifacts_dir", "./artifacts")) / target
    out_dir.mkdir(parents=True, exist_ok=True)

    res = run_rebalance(
        as_of=target, tier="monthly", capital=capital,
        prev_qty=prev_qty, prev_cash=prev_cash, target_weights=target_weights,
        prices=prices, universe=universe, clusters=clusters,
        previous_weights=prev_weights, dials=dials, out_dir=out_dir,
        previous_path=previous_path or "", deep_llm=_build_deep_llm(),
    )
    return MonthlyResult(
        portfolio_path=final["final_portfolio_path"],
        rebalance_paths=res.paths,
        summary=(f"Month {month} rebalance: tier=monthly, turnover={res.turnover:.2%}, "
                 f"passed={res.validation.passed} → {res.paths['plan_csv']}"),
    )
