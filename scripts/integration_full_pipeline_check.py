"""Full-pipeline integration check: Stage 1 → Stage 3 factor_panel handoff.

Validates the architectural refactor:
1. Runs the real Technical Analyst node (mocked LLM only — narrative is irrelevant)
2. Extracts factor_panel from the resulting TechnicalReport
3. Runs select_etf_candidates TWICE:
   - With factor_panel from Stage 1 (intended new path)
   - Without factor_panel (selector falls back to local computation)
4. Asserts both paths produce identical candidates
   → confirms Stage 1's panel is consumable by Stage 3 with no information loss

Uses cached pykrx prices (no network needed).
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from tradingagents.agents.analysts.technical_analyst import create_technical_analyst
from tradingagents.dataflows.universe import load_universe
from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills.portfolio.candidate_selector import select_etf_candidates


CACHE_PATH = Path("data/.cache/pykrx_universe.parquet")
UNIVERSE_PATH = Path("data/universe.json")


def _build_state(as_of: date) -> dict:
    return {
        "as_of_date": as_of.isoformat(),
        "universe_path": str(UNIVERSE_PATH),
    }


def _make_mock_llm() -> MagicMock:
    """Stub quick LLM — narrative summary doesn't affect factor_panel."""
    fake = MagicMock()
    fake.invoke.return_value = MagicMock(content="(mocked technical narrative)")
    return fake


def run_pipeline_check(as_of: date) -> dict:
    print(f"\n=== Full-pipeline check for as_of={as_of} ===")

    # Patch fetch_etf_price_batch to source from cache only
    cache = pd.read_parquet(CACHE_PATH)
    cache["date"] = pd.to_datetime(cache["date"])

    def _patched_price_batch(tickers, start, end, cache_path=None):
        end_ts = pd.Timestamp(end)
        start_ts = pd.Timestamp(start)
        sub = cache[
            (cache["ticker"].isin(tickers))
            & (cache["date"] >= start_ts)
            & (cache["date"] <= end_ts)
        ].copy()
        return sub

    quick = _make_mock_llm()
    deep = _make_mock_llm()
    node = create_technical_analyst(quick, deep)

    with patch(
        "tradingagents.agents.analysts.technical_analyst.fetch_etf_price_batch",
        side_effect=_patched_price_batch,
    ):
        state = _build_state(as_of)
        delta = node(state)

    report = delta["technical_report"]
    panel = report.factor_panel
    print(f"[stage1] factor_panel built: {len(panel)} tickers")
    if not panel:
        raise RuntimeError("factor_panel empty — Stage 1 didn't populate it")

    # Inspect a sample panel
    sample_t = next(iter(panel.keys()))
    p = panel[sample_t]
    print(f"[stage1] sample panel for {sample_t}:")
    print(f"   skip1m_mom_3m  = {p.skip1m_mom_3m}")
    print(f"   skip1m_mom_6m  = {p.skip1m_mom_6m}")
    print(f"   skip1m_mom_12m = {p.skip1m_mom_12m}")
    print(f"   realized_vol_60d = {p.realized_vol_60d}")
    print(f"   sharpe_60d     = {p.sharpe_60d}")
    print(f"   log_aum        = {p.log_aum:.2f}")

    # Now compare selector with panel vs selector recomputing
    universe = load_universe(UNIVERSE_PATH)
    target = BucketTarget(
        kr_equity=0.25, global_equity=0.20, fx_commodity=0.05,
        bond=0.40, cash_mmf=0.10,
        rationale="integration check",
    )

    # Returns matrix (needed for correlation de-dup in both paths)
    sub_pivot = cache.pivot_table(
        index="date", columns="ticker", values="close", aggfunc="last",
    )
    returns = sub_pivot.pct_change().dropna(how="all")
    returns = returns[returns.index <= pd.Timestamp(as_of)]

    # Path A: factor_panel from Stage 1 (intended new path)
    pick_A = select_etf_candidates(
        universe, target, momentum_rankings={},
        as_of=as_of, per_bucket_n=4,
        returns=returns,
        factor_panel=panel,
        regime_quadrant="unknown", regime_confidence=0.5,
        correlation_threshold=0.85,
    )

    # Path B: no factor_panel — selector recomputes internally
    pick_B = select_etf_candidates(
        universe, target, momentum_rankings={},
        as_of=as_of, per_bucket_n=4,
        returns=returns,
        factor_panel=None,
        regime_quadrant="unknown", regime_confidence=0.5,
        correlation_threshold=0.85,
    )

    print(f"\n[stage3] Path A (Stage1 panel):  "
          f"{sum(len(t) for t in pick_A.bucket_to_tickers.values())} tickers")
    print(f"[stage3] Path B (re-compute):     "
          f"{sum(len(t) for t in pick_B.bucket_to_tickers.values())} tickers")

    mismatches: list[tuple[str, list[str], list[str]]] = []
    for bucket in pick_A.bucket_to_tickers:
        a = pick_A.bucket_to_tickers[bucket]
        b = pick_B.bucket_to_tickers[bucket]
        if a != b:
            mismatches.append((bucket, a, b))

    if mismatches:
        print("\n⚠️  Mismatch — Path A vs Path B picks differ:")
        for bucket, a, b in mismatches:
            print(f"   [{bucket}]")
            print(f"     A: {a}")
            print(f"     B: {b}")
    else:
        print("\n✅ Path A == Path B — factor_panel hand-off is lossless.")

    return {
        "as_of": as_of.isoformat(),
        "panel_size": len(panel),
        "path_A": pick_A.bucket_to_tickers,
        "path_B": pick_B.bucket_to_tickers,
        "mismatches": mismatches,
    }


def main():
    dates = [date(2024, 7, 1), date(2025, 1, 2)]
    results = [run_pipeline_check(d) for d in dates]
    total_mismatches = sum(len(r["mismatches"]) for r in results)
    print(f"\n{'=' * 60}")
    print(f"SUMMARY: {len(results)} dates tested, "
          f"{total_mismatches} bucket-level mismatches")
    if total_mismatches > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
