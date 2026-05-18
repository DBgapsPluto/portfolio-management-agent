"""Phase 4 — CNN Fear & Greed cache."""
from datetime import date

from tradingagents.skills.risk.fear_greed import fetch_fear_greed_index


def _patch_cache_dir(monkeypatch, tmp_path):
    import tradingagents.default_config as cfg
    monkeypatch.setitem(cfg.DEFAULT_CONFIG, "data_cache_dir", str(tmp_path))


def test_fear_greed_cache_hit_skips_scrape(tmp_path, monkeypatch):
    _patch_cache_dir(monkeypatch, tmp_path)
    calls = {"n": 0}

    def fake_scrape():
        calls["n"] += 1
        return {"score": 67, "previous_close": 60}

    monkeypatch.setattr(
        "tradingagents.skills.risk.fear_greed._scrape_cnn_fg", fake_scrape,
    )

    s1 = fetch_fear_greed_index(date(2026, 5, 18))
    s2 = fetch_fear_greed_index(date(2026, 5, 18))
    assert calls["n"] == 1
    assert s1.current_value == 67
    assert s1.label == "greed"


def test_fear_greed_scrape_failure_returns_none(tmp_path, monkeypatch):
    _patch_cache_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "tradingagents.skills.risk.fear_greed._scrape_cnn_fg", lambda: None,
    )

    s = fetch_fear_greed_index(date(2026, 5, 18))
    assert s is None


def test_fear_greed_stale_fallback(tmp_path, monkeypatch):
    """Day 1: scrape OK + cache 적재. Day 2: scrape 실패 → stale fallback."""
    _patch_cache_dir(monkeypatch, tmp_path)
    calls = {"n": 0}

    def fake_scrape_success():
        calls["n"] += 1
        return {"score": 50, "previous_close": 50}

    monkeypatch.setattr(
        "tradingagents.skills.risk.fear_greed._scrape_cnn_fg",
        fake_scrape_success,
    )
    s1 = fetch_fear_greed_index(date(2026, 5, 15))
    assert s1 is not None
    assert s1.current_value == 50

    # Day 2: live 실패
    monkeypatch.setattr(
        "tradingagents.skills.risk.fear_greed._scrape_cnn_fg", lambda: None,
    )
    s2 = fetch_fear_greed_index(date(2026, 5, 16), max_staleness=3)
    assert s2 is not None
    assert s2.current_value == 50  # stale fallback
