"""compute_cfnai_metrics tests (C3 — factor model F1 growth_surprise component).

D7 pattern: scalar tuple return (analyst applies model_copy).
D8 pattern: empty / exception → None (graceful skip, no default fill).
D9 pattern: no retry, no cache in skill — fresh compute each call.
"""
from datetime import date

import pandas as pd
import pytest

from tradingagents.skills.macro.real_activity import compute_cfnai_metrics


def test_cfnai_latest_returned():
    series = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5])
    result = compute_cfnai_metrics(series, as_of=date.today())
    assert result is not None
    latest, avg = result
    assert latest == pytest.approx(0.5)


def test_cfnai_3m_average():
    series = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5])
    result = compute_cfnai_metrics(series, as_of=date.today())
    assert result is not None
    latest, avg = result
    assert avg == pytest.approx((0.3 + 0.4 + 0.5) / 3)


def test_cfnai_short_series_returns_best_effort():
    """2-obs series — avg = mean of 2 (best-effort)."""
    series = pd.Series([0.2, 0.4])
    result = compute_cfnai_metrics(series, as_of=date.today())
    assert result is not None
    latest, avg = result
    assert latest == pytest.approx(0.4)
    assert avg == pytest.approx(0.3)


def test_cfnai_empty_series_returns_none():
    """Empty → None (data 부재 signal, D8 — no default fill)."""
    series = pd.Series([], dtype=float)
    result = compute_cfnai_metrics(series, as_of=date.today())
    assert result is None


def test_cfnai_none_series_returns_none():
    """None series → None (D8 — graceful)."""
    result = compute_cfnai_metrics(None, as_of=date.today())
    assert result is None
