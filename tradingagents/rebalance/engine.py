"""리밸런싱 공통 엔진 — 보유 재평가·델타 거래계획·재검증 (스펙 §7).

전부 LLM 0 — 순수 결정론. 현금 포지션은 키 "CASH"로 표현.
"""
import logging
from collections.abc import Callable
from pathlib import Path

from tradingagents.dataflows.universe import Universe
from tradingagents.skills.portfolio.sub_category import bucket_for_etf
from tradingagents.skills.mandate.concentration_check import (
    RISK_BUCKET_NAMES, HARD_SINGLE_CAP, HARD_RISK_ASSET_CAP, FLOAT_TOLERANCE,
)
from tradingagents.rebalance.types import TradeLine, RebalanceResult
from tradingagents.schemas.portfolio import WeightVector, OptimizationMethod
from tradingagents.schemas.mandate import ValidationReport, Violation
from tradingagents.skills.mandate.universe_check import validate_universe
from tradingagents.skills.mandate.concentration_check import validate_concentration
from tradingagents.skills.mandate.correlation_check import validate_correlation_concentration
from tradingagents.skills.mandate.turnover_check import validate_turnover_feasibility

logger = logging.getLogger(__name__)

CASH_KEY = "CASH"


def reprice_holdings(
    qty: dict[str, int], cash_krw: int, prices: dict[str, float],
) -> dict[str, float]:
    """보유 수량 × 오늘 종가 + 현금 → 비중(합 1.0). 현금은 CASH_KEY.

    가격 없는 종목은 평가액 0(비중 0) + 경고.
    """
    value: dict[str, float] = {}
    for t, q in qty.items():
        p = prices.get(t, 0.0)
        if p <= 0:
            logger.warning("reprice: %s 가격 없음 → 평가액 0", t)
        value[t] = q * p
    total = sum(value.values()) + max(cash_krw, 0)
    if total <= 0:
        return {}
    weights = {t: v / total for t, v in value.items()}
    if cash_krw > 0:
        weights[CASH_KEY] = cash_krw / total
    return weights


def make_is_risk(universe: Universe) -> Callable[[str], bool]:
    """ticker → 위험자산 여부. CASH·미분류·universe 외 ticker는 False."""
    meta = {e.ticker: e for e in universe.etfs}
    def is_risk(ticker: str) -> bool:
        if ticker == CASH_KEY:
            return False
        e = meta.get(ticker)
        return bool(e) and bucket_for_etf(e) in RISK_BUCKET_NAMES
    return is_risk


def risk_total(weights: dict[str, float], is_risk: Callable[[str], bool]) -> float:
    return sum(w for t, w in weights.items() if is_risk(t))


def compute_deltas(
    current: dict[str, float], target: dict[str, float],
    dials: dict, is_risk: Callable[[str], bool],
) -> tuple[dict[str, float], list[str]]:
    """목표−현재 델타. no-trade band 적용, 단 hard cap-방향 위반 해소 델타는 예외 실행.

    band 예외는 hard mandate cap(단일 0.20 / 위험 0.70) 기준 — finding #2.
    Returns (delta(실행할 것만), skipped_tickers). CASH_KEY 는 제외.
    """
    band = dials["no_trade_band"]
    cur_risk = risk_total(current, is_risk)

    tickers = (set(current) | set(target)) - {CASH_KEY}
    delta: dict[str, float] = {}
    skipped: list[str] = []
    for t in tickers:
        d = target.get(t, 0.0) - current.get(t, 0.0)
        if abs(d) >= band:
            delta[t] = d
            continue
        over_single = (current.get(t, 0.0) > HARD_SINGLE_CAP
                       and d < 0
                       and current.get(t, 0.0) + d <= HARD_SINGLE_CAP + FLOAT_TOLERANCE)
        over_risk = (cur_risk > HARD_RISK_ASSET_CAP and is_risk(t) and d < 0)
        if over_single or over_risk:
            delta[t] = d
        elif d != 0.0:
            skipped.append(t)
    return delta, skipped


def build_rebalance_plan(
    current: dict[str, float], target: dict[str, float], capital: int,
    prices: dict[str, float], is_risk: Callable[[str], bool], dials: dict,
) -> dict:
    """현재→목표 거래계획. 잔여는 현금 보유(sweep 안 함). 실현 비중·turnover 산출.

    Returns dict: plan·skipped_no_trade·cash_residual_krw·realized_weights·turnover.
    """
    delta, skipped = compute_deltas(current, target, dials, is_risk)

    plan: list[TradeLine] = []
    invested = 0
    buy_krw = 0
    sell_krw = 0
    target_value: dict[str, float] = {}
    for t in (set(current) | set(target)) - {CASH_KEY}:
        p = prices.get(t, 0.0)
        cur_qty = int(round(current.get(t, 0.0) * capital / p)) if p > 0 else 0
        # band 로 생략된 종목은 현재 유지 → 실행 delta 만 목표에 반영
        eff_target_w = current.get(t, 0.0) + delta.get(t, 0.0)
        tgt_qty = int(round(eff_target_w * capital / p)) if p > 0 else cur_qty
        dq = tgt_qty - cur_qty
        if dq == 0:
            action = "HOLD"
        elif dq > 0:
            action = "BUY"; buy_krw += dq * p
        else:
            action = "SELL"; sell_krw += (-dq) * p
        if p > 0:
            target_value[t] = tgt_qty * p
            invested += tgt_qty * p
        plan.append(TradeLine(
            ticker=t, action=action, current_qty=cur_qty, target_qty=tgt_qty,
            delta_qty=dq, delta_amount_krw=int(dq * p),
        ))

    cash_residual = max(capital - invested, 0)
    realized = {t: v / capital for t, v in target_value.items()}
    if cash_residual > 0:
        realized[CASH_KEY] = cash_residual / capital
    turnover = (buy_krw + sell_krw) / capital if capital else 0.0

    return {
        "plan": sorted(plan, key=lambda tl: -abs(tl.delta_amount_krw)),
        "skipped_no_trade": skipped,
        "cash_residual_krw": int(cash_residual),
        "realized_weights": realized,
        "turnover": turnover,
    }


def validate_rebalance(
    realized: dict[str, float], universe, clusters, previous_weights,
    capital: int, floor_pct: float,
) -> ValidationReport:
    """realized 비중(종목)에 전체 mandate 재검증. CASH 는 제외 후 종목만 재정규화."""
    stock = {t: w for t, w in realized.items() if t != CASH_KEY}
    s = sum(stock.values())
    if s <= 0:
        return ValidationReport(passed=False, violations=[Violation(
            rule="weight_validity", description="no stock weight", severity="hard",
            suggested_fix="check reprice")])
    norm = {t: w / s for t, w in stock.items()}
    wv = WeightVector(method=OptimizationMethod.AUM_WEIGHTED, weights=norm,
                      rationale="rebalance realized")

    violations: list[Violation] = []
    violations += validate_universe(wv, universe).violations
    violations += validate_concentration(wv, universe).violations
    violations += validate_correlation_concentration(wv, clusters).violations
    violations += validate_turnover_feasibility(
        wv, previous_weights, capital, floor_pct=floor_pct).violations
    return ValidationReport(
        passed=not any(v.severity == "hard" for v in violations),
        violations=violations,
    )


def run_rebalance(
    *, as_of: str, tier: str, capital: int,
    prev_qty: dict[str, int], prev_cash: int,
    target_weights: dict[str, float], prices: dict[str, float],
    universe, clusters, previous_weights, dials: dict,
    out_dir: Path, previous_path: str, deep_llm=None,
) -> RebalanceResult:
    """리밸런싱 1회: 재평가 → 거래계획 → 재검증 → 산출물 3종."""
    from tradingagents.reports.rebalance_plan import write_rebalance_plan, write_rebalance_json
    from tradingagents.reports.rebalance_rationale import write_rebalance_rationale

    is_risk = make_is_risk(universe)
    current = reprice_holdings(prev_qty, prev_cash, prices)

    plan_out = build_rebalance_plan(current, target_weights, capital, prices, is_risk, dials)

    floor = dials.get("turnover_floor_monthly", 0.0) if tier == "monthly" else 0.0
    validation = validate_rebalance(
        plan_out["realized_weights"], universe=universe, clusters=clusters,
        previous_weights=previous_weights, capital=capital, floor_pct=floor)

    res = RebalanceResult(
        as_of=as_of, tier=tier,
        current_weights=current, target_weights=target_weights,
        realized_weights=plan_out["realized_weights"], plan=plan_out["plan"],
        turnover=plan_out["turnover"], cash_residual_krw=plan_out["cash_residual_krw"],
        cash_weight=plan_out["realized_weights"].get(CASH_KEY, 0.0),
        skipped_no_trade=plan_out["skipped_no_trade"],
        trigger={"tier": tier}, validation=validation,
    )

    lookup = {e.ticker: {"name": e.name, "category": e.category} for e in universe.etfs}
    out_dir = Path(out_dir)
    csv_path = out_dir / f"{as_of}(rebalancing)_plan.csv"
    json_path = out_dir / f"{as_of}(rebalancing).json"
    md_path = out_dir / f"{as_of}(rebalancing)_rationale.md"
    write_rebalance_plan(res, lookup, csv_path)
    write_rebalance_json(res, json_path, previous_path)
    write_rebalance_rationale(res, md_path, deep_llm=deep_llm)
    res.paths = {"json": str(json_path), "plan_csv": str(csv_path),
                 "rationale_md": str(md_path)}
    return res
