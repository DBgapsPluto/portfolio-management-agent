"""Phase 2a integration — allocator pipeline 의 etf_metrics 통합 검증."""
from __future__ import annotations

import os
import json

import pytest


def test_attribution_records_etf_metrics_summary_via_smoke():
    """기존 phase1_smoke fixture 가 Phase 2a 새 attribution 키 (etf_metrics_summary,
    bucket_target_stage2) 를 채우는지 검증."""
    smoke_artifact = "artifacts/2026-05-15/portfolio.json"
    if not os.path.exists(smoke_artifact):
        pytest.skip(
            f"{smoke_artifact} 없음 — Phase 2a regression 실행 후 검증"
        )
    with open(smoke_artifact) as f:
        portfolio = json.load(f)
    attribution = portfolio.get("allocation_attribution") or {}

    # Phase 2a 적용 후 산출물이라면 이 키들이 있어야 함
    assert "etf_metrics_summary" in attribution, (
        "Phase 2a 적용 후 산출물에 etf_metrics_summary 누락"
    )

    summary = attribution["etf_metrics_summary"]
    assert "fetch_attempted" in summary
    assert "fetch_succeeded" in summary
    assert isinstance(summary["fetch_succeeded"], bool)
    assert "n_tickers_with_te" in summary
    assert "fetch_duration_seconds" in summary

    # config snapshot 도 확인 (Task 9)
    config = attribution.get("config", {})
    assert "bucket_target_stage2" in config, (
        "Phase 2a Task 9: bucket_target_stage2 누락"
    )
