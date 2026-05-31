import pytest
from datetime import date
from unittest.mock import MagicMock
import pandas as pd
from tradingagents.skills.overlay.novelty import (
    compute_novelty, append_daily_salience, load_salience_history,
)


def test_compute_novelty_returns_zero_when_no_history(tmp_path, monkeypatch):
    monkeypatch.setattr("tradingagents.skills.overlay.novelty.SALIENCE_HISTORY_PATH",
                        tmp_path / "salience.parquet")
    nr = MagicMock()
    nr.release_surprise.high_importance_today = 0
    nr.news_sentiment.avg_sentiment.macro = 0.0
    assert compute_novelty(nr, date(2026, 6, 1)) == 0.0


def test_compute_novelty_none_report_zero():
    assert compute_novelty(None, date(2026, 6, 1)) == 0.0


def test_compute_novelty_extreme_z_capped(tmp_path, monkeypatch):
    salience_file = tmp_path / "salience.parquet"
    monkeypatch.setattr("tradingagents.skills.overlay.novelty.SALIENCE_HISTORY_PATH", salience_file)
    hist = pd.DataFrame({
        "date": pd.date_range("2026-05-01", periods=30, freq="D").date,
        "salience": [0.5 + 0.05 * (i % 5) for i in range(30)],
    })
    salience_file.parent.mkdir(parents=True, exist_ok=True)
    hist.to_parquet(salience_file, index=False)
    nr = MagicMock()
    nr.release_surprise.high_importance_today = 100
    nr.news_sentiment.avg_sentiment.macro = 1.0
    n = compute_novelty(nr, date(2026, 6, 1))
    assert 0.0 <= n <= 1.0
    assert n > 0.5


def test_append_idempotent(tmp_path, monkeypatch):
    salience_file = tmp_path / "salience.parquet"
    monkeypatch.setattr("tradingagents.skills.overlay.novelty.SALIENCE_HISTORY_PATH", salience_file)
    nr = MagicMock()
    nr.release_surprise.high_importance_today = 2
    nr.news_sentiment.avg_sentiment.macro = 0.3
    append_daily_salience(nr, date(2026, 6, 1))
    append_daily_salience(nr, date(2026, 6, 1))
    df = pd.read_parquet(salience_file)
    assert len(df) == 1


def test_append_two_distinct_dates(tmp_path, monkeypatch):
    salience_file = tmp_path / "salience.parquet"
    monkeypatch.setattr("tradingagents.skills.overlay.novelty.SALIENCE_HISTORY_PATH", salience_file)
    nr = MagicMock()
    nr.release_surprise.high_importance_today = 2
    nr.news_sentiment.avg_sentiment.macro = 0.3
    append_daily_salience(nr, date(2026, 6, 1))
    append_daily_salience(nr, date(2026, 6, 2))
    df = pd.read_parquet(salience_file)
    assert len(df) == 2
