"""Unit tests for monitor functions."""
from pathlib import Path

import pandas as pd
import pytest

from tradingagents.monitor.cost import compute_cost
from tradingagents.monitor.drift import compute_drift
from tradingagents.monitor.exposure import compute_exposure
from tradingagents.monitor.turnover import compute_turnover


@pytest.fixture
def transactions_csv(tmp_path: Path) -> Path:
    df = pd.DataFrame({
        "거래일자": ["2026-06-02", "2026-06-15", "2026-07-10", "2026-08-05"],
        "거래금액": [800_000_000, 50_000_000, 120_000_000, 90_000_000],
        "수수료": [10_000, 1_000, 2_000, 1_500],
        "슬리피지": [50_000, 5_000, 8_000, 6_000],
    })
    p = tmp_path / "tx.csv"
    df.to_csv(p, index=False)
    return p


def test_turnover_initial_below_floor():
    """Initial < 80% should fire CUTOFF warning."""
    df = pd.DataFrame({
        "거래일자": ["2026-06-02"],
        "거래금액": [500_000_000],  # 50%
    })
    p = Path("/tmp/_t.csv")
    df.to_csv(p, index=False)
    status = compute_turnover(p, 1_000_000_000, pd.Timestamp("2026-06-09").date())
    assert status.initial_pct == pytest.approx(0.50)
    assert any("CUTOFF" in w for w in status.warnings)


def test_turnover_initial_meets_floor(transactions_csv: Path):
    status = compute_turnover(
        transactions_csv, 1_000_000_000, pd.Timestamp("2026-06-09").date()
    )
    assert status.initial_pct == pytest.approx(0.80)


def test_exposure_risk_safe_split():
    weights = {"A1": 0.5, "A2": 0.3, "A3": 0.2}
    lookup = {
        "A1": {"category": "국내주식", "bucket": "위험"},
        "A2": {"category": "국내채권", "bucket": "안전"},
        "A3": {"category": "원자재", "bucket": "원자재"},
    }
    out = compute_exposure(weights, lookup)
    assert out.risk_asset_pct == pytest.approx(0.5)
    assert out.safe_asset_pct == pytest.approx(0.5)


def test_drift_no_movement():
    """Equal entry/current prices -> drift ~0."""
    weights = {"A": 0.6, "B": 0.4}
    prices = {"A": 100.0, "B": 50.0}
    rep = compute_drift(weights, prices, prices)
    assert rep.max_drift < 1e-9


def test_drift_one_winner():
    weights = {"A": 0.5, "B": 0.5}
    entry = {"A": 100.0, "B": 100.0}
    current = {"A": 200.0, "B": 100.0}  # A doubled
    rep = compute_drift(weights, current, entry)
    assert rep.max_drift_ticker in {"A", "B"}
    assert rep.max_drift > 0.1


def test_cost_summary(transactions_csv: Path):
    s = compute_cost(transactions_csv, 1_000_000_000)
    assert s.total_commission == 14_500
    assert s.total_slippage == 69_000
    assert s.cost_bps_of_capital > 0
