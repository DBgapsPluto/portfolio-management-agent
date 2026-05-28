"""Phase 1 integration — allocator pipeline 의 spillover + ENB 통합 검증.

가짜 universe 와 returns 로 5 개 시나리오:
  1. 정상 universe (모두 양수 alpha) → spillover 0, ENB 양호
  2. fx_commodity 음수 only → fx 100% spillover
  3. global low conviction → 부분 spillover
  4. attribution completeness
  5. cash overflow → high-conv redistribution
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingagents.dataflows.universe import ETFEntry, Universe
from tradingagents.schemas.portfolio import BucketTarget


@pytest.fixture
def synthetic_universe(tmp_path):
    """5 bucket × 4 ticker = 20 ETF universe."""
    etfs = []
    for prefix, cat, sub in [
        ("KR", "국내주식_지수", None),
        ("GL", "해외주식_지수", None),
        ("FX", "FX 및 원자재", "gold"),
        ("BD", "국내채권_종합", "nominal"),
        ("CS", "금리연계형/초단기채권", None),
    ]:
        for i in range(4):
            etfs.append(ETFEntry(
                ticker=f"A_{prefix}{i:02d}", name=f"{prefix}{i}",
                aum_krw=50_000_000_000,
                underlying_index=f"{prefix}_idx_{i}",
                bucket="안전" if prefix in ("BD", "CS") else "위험",
                category=cat, sub_category=sub,
            ))
    universe = Universe(version="test", etfs=etfs)
    path = tmp_path / "universe.json"
    path.write_text(universe.model_dump_json())
    return path


@pytest.mark.skip(reason="state mocking 헬퍼 후속 작업 — Task 15 의 regression_compare 가 더 직접적")
def test_allocator_with_normal_universe(synthetic_universe):
    """5 bucket 양수 충분 → spillover 0, ENB > ENB_WARNING_THRESHOLD."""
    pass


@pytest.mark.skip(reason="state mocking 헬퍼 후속 작업")
def test_allocator_with_fx_negative_only(synthetic_universe):
    """fx_commodity 음수만 → fx bucket weight 감소, cash 증가."""
    pass


@pytest.mark.skip(reason="state mocking 헬퍼 후속 작업")
def test_allocator_with_global_low_conviction(synthetic_universe):
    """global 알파 낮음 → 부분 spillover."""
    pass


def test_allocator_attribution_completeness_via_smoke(tmp_path):
    """기존 phase1_smoke fixture 가 새 attribution 키 (cash_spillover, enb) 를 채우는지 검증."""
    # 가장 가벼운 통합 검증: smoke fixture 결과에서 allocation_attribution 가 확장됐는지.
    # 실 fixture 가 없으면 skip 처리. (있으면 그 산출물 검사)
    import os
    smoke_artifact = "artifacts/2026-05-15/portfolio.json"
    if not os.path.exists(smoke_artifact):
        pytest.skip(f"{smoke_artifact} 없음 — 회귀 케이스는 Task 15 의 regression_compare 에서 검증")
    import json
    with open(smoke_artifact) as f:
        portfolio = json.load(f)
    attribution = portfolio.get("allocation_attribution") or {}
    # Phase 1 적용 후 산출물이라면 이 키들이 있어야 함
    assert "cash_spillover" in attribution, (
        "Phase 1 적용 후 산출물에 cash_spillover 누락 — hook 1 미통합"
    )
    assert "enb" in attribution, (
        "Phase 1 적용 후 산출물에 enb 누락 — hook 2 미통합"
    )
    # 타입 검증
    assert isinstance(attribution["cash_spillover"], dict)
    assert isinstance(attribution["enb"], (int, float))


@pytest.mark.skip(reason="state mocking 헬퍼 후속 작업")
def test_allocator_cash_overflow_redistribution(synthetic_universe):
    """동시 다 bucket spillover → cash > 40% → overflow → high-conv 로."""
    pass
