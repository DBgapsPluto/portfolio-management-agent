"""End-to-end smoke for Phase 1 — wire everything together with mocks."""
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from tradingagents.dataflows.universe import sync_from_xlsx, load_universe
from tradingagents.dataflows.cache import TieredCache
from tradingagents.dataflows.pykrx_data import fetch_etf_ohlcv_batch, ParquetCache
from tradingagents.skills.registry import (
    register_skill, list_skills, clear_registry, _reregister_all_skills,
)


def test_phase1_wiring(tmp_path):
    """Universe + cache + skill registry all instantiate without errors."""
    try:
        # 1. Universe
        universe_json = tmp_path / "universe.json"
        sync_from_xlsx(Path("tests/fixtures/universe_test.xlsx"), universe_json)
        universe = load_universe(universe_json)
        assert len(universe.etfs) == 5

        # 2. Cache
        cache = TieredCache(cache_dir=tmp_path / "cache", name="smoke")
        val, staleness = cache.fetch_with_fallback(
            lambda: {"hello": "world"}, as_of=date(2026, 5, 10)
        )
        assert staleness == 0

        # 3. ParquetCache + pykrx
        parq = ParquetCache(tmp_path / "etf.parquet")
        fake_df = pd.DataFrame({
            "시가": [100], "고가": [110], "저가": [99], "종가": [105], "거래량": [1000]
        }, index=pd.to_datetime(["2026-05-10"]))
        with patch("tradingagents.dataflows.pykrx_data._raw_pykrx_call", return_value=fake_df):
            df = fetch_etf_ohlcv_batch(["A069500"], date(2026, 5, 10), date(2026, 5, 10), cache=parq)
        assert len(df) == 1

        # 4. Registry
        clear_registry()

        @register_skill(name="dummy", category="macro")
        def dummy(): pass

        assert "dummy" in list_skills()
    finally:
        # Re-register all skills after the test
        _reregister_all_skills()
