from datetime import date
import pandas as pd
from tradingagents.skills.macro.employment import compute_unemployment_trend


def test_sahm_rule_not_triggered():
    months = pd.date_range("2025-05-01", periods=15, freq="MS")
    ur_values = [3.5] * 12 + [3.6, 3.9, 4.1]  # 3-mo avg = 3.87 vs min 3.5 = +0.37
    ur = pd.Series(ur_values, index=months)
    payems = pd.Series([150_000] * 15, index=months)
    snap = compute_unemployment_trend(ur, payems, as_of=date(2026, 7, 1))
    assert snap.sahm_rule_triggered is False


def test_sahm_rule_clear_trigger():
    months = pd.date_range("2025-05-01", periods=15, freq="MS")
    ur_values = [3.5] * 12 + [4.0, 4.2, 4.5]  # 3-mo avg = 4.23 vs min 3.5 = +0.73
    ur = pd.Series(ur_values, index=months)
    payems = pd.Series([150_000] * 15, index=months)
    snap = compute_unemployment_trend(ur, payems, as_of=date(2026, 7, 1))
    assert snap.sahm_rule_triggered is True
