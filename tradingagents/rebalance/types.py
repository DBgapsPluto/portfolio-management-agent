"""리밸런싱 엔진 데이터 구조 (스펙 §4.1)."""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TradeLine:
    ticker: str
    action: str                 # "BUY" | "SELL" | "HOLD"
    current_qty: int
    target_qty: int
    delta_qty: int              # +매수 / -매도
    delta_amount_krw: int


@dataclass
class RebalanceResult:
    as_of: str
    tier: str                   # "daily" | "reassess" | "monthly" | "none"
    current_weights: dict[str, float] = field(default_factory=dict)   # 현금 포함("CASH")
    target_weights: dict[str, float] = field(default_factory=dict)
    realized_weights: dict[str, float] = field(default_factory=dict)
    plan: list[TradeLine] = field(default_factory=list)
    turnover: float = 0.0
    buy_krw: float = 0.0                # F3/C2: 월누적(MTD) 집계용 체결 명목
    sell_krw: float = 0.0
    begin_value: float = 0.0            # 리밸런싱 전 평가액 (= build_rebalance_plan의 current_value)
    end_value: float = 0.0              # 리밸런싱 후 평가액 (invested+cash_residual; MF-6: begin_value와 항등)
    cash_residual_krw: int = 0
    cash_weight: float = 0.0
    skipped_no_trade: list[str] = field(default_factory=list)
    trigger: dict[str, Any] = field(default_factory=dict)
    validation: Any = None      # ValidationReport
    rationale_md: str = ""
    paths: dict[str, str] = field(default_factory=dict)
