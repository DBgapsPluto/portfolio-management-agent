"""Stale 데이터의 staleness_days 정직 stamp 회귀.

china_cli(OECD 2024-01 동결) / Shiller CAPE(2023-09 종료) / BIS China credit(2023-06)
이 상류 소스에서 stale인데도 builder가 staleness_days를 0/1/60 으로 하드코딩 →
regime LLM 이 2~3년 묵은 데이터를 'live'로 소비. 실제 last-date 기반으로 stamp 한다.
"""
from datetime import date

import numpy as np
import pandas as pd

from tradingagents.agents.analysts import macro_quant_analyst as mq
from tradingagents.skills.macro.china_leading import compute_china_leading


def test_cape_stamps_real_staleness(monkeypatch):
    """Shiller CAPE 가 2023-09 종료면 staleness_days 가 실제 ~1000일 이어야 (1 아님)."""
    idx = pd.date_range("2023-01-01", "2023-09-01", freq="MS")
    monkeypatch.setattr(
        mq, "fetch_shiller_cape", lambda as_of: pd.Series([30.0] * len(idx), index=idx),
    )
    snap = mq._build_us_equity_valuation(date(2026, 6, 2))
    assert snap is not None
    assert snap.staleness_days > 900  # 2023-09 → 2026-06 ≈ 1005일


def test_china_cli_stamps_real_staleness():
    """china_cli 가 2024-01 동결이면 staleness_days 가 실제 ~880일 이어야 (0 아님)."""
    idx = pd.date_range("2023-05-01", "2024-01-01", freq="MS")
    cli = pd.Series([101.0] * len(idx), index=idx)
    snap = compute_china_leading(cli, date(2026, 6, 2))
    assert snap.staleness_days > 800  # 2024-01 → 2026-06 ≈ 883일


def test_china_credit_impulse_stamps_real_staleness(monkeypatch):
    """BIS China credit 가 2023-06 종료면 staleness_days 가 실제 ~1000일 이어야 (60 아님)."""
    from tradingagents.skills.research import china_credit_impulse as cci

    idx = pd.period_range("2021Q1", "2023Q2", freq="Q").to_timestamp()
    s = pd.Series(np.linspace(220.0, 228.0, len(idx)), index=idx)
    monkeypatch.setattr(cci, "fetch_bis_china_credit", lambda as_of: s)
    snap = mq._build_china_credit_impulse_snapshot(date(2026, 6, 2))
    assert snap is not None
    assert snap.staleness_days > 1000  # 2023-06 → 2026-06 ≈ 1068일
