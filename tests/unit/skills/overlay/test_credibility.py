from datetime import date
from tradingagents.schemas.llm_overlay import CredibilityState
from tradingagents.skills.overlay.credibility import (
    update_credibility, get_credibility, load_credibility, save_credibility,
    COLD_START_PRIOR,
)


def test_cold_start_prior_0_3():
    cs = CredibilityState(bucket_cred={}, history_count=0, last_updated=date(2026, 6, 1))
    assert get_credibility(cs, "kr_equity") == COLD_START_PRIOR == 0.3


def test_load_credibility_bootstraps_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr("tradingagents.skills.overlay.credibility.CRED_PATH", tmp_path / "cred.json")
    loaded = load_credibility()

    assert loaded.history_count == 8
    assert loaded.bucket_cred["kr_equity"] == 0.45
    assert loaded.bucket_cred["global_equity"] == 0.45
    assert get_credibility(loaded, "kr_equity") > COLD_START_PRIOR


def test_update_hit_increases_cred(tmp_path, monkeypatch):
    monkeypatch.setattr("tradingagents.skills.overlay.credibility.CRED_PATH", tmp_path / "cred.json")
    cs = CredibilityState(bucket_cred={"kr_equity": 0.3}, history_count=0, last_updated=date(2026, 6, 1))
    update_credibility(cs, "kr_equity", predicted_delta=0.02, realized_return=0.05)
    assert abs(cs.bucket_cred["kr_equity"] - 0.37) < 1e-9


def test_update_miss_decreases_cred(tmp_path, monkeypatch):
    monkeypatch.setattr("tradingagents.skills.overlay.credibility.CRED_PATH", tmp_path / "cred.json")
    cs = CredibilityState(bucket_cred={"kr_equity": 0.5}, history_count=0, last_updated=date(2026, 6, 1))
    update_credibility(cs, "kr_equity", predicted_delta=0.03, realized_return=-0.05)
    assert abs(cs.bucket_cred["kr_equity"] - 0.45) < 1e-9


def test_update_subthreshold_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr("tradingagents.skills.overlay.credibility.CRED_PATH", tmp_path / "cred.json")
    cs = CredibilityState(bucket_cred={"kr_equity": 0.5}, history_count=0, last_updated=date(2026, 6, 1))
    update_credibility(cs, "kr_equity", predicted_delta=0.001, realized_return=0.05)  # below 0.005
    assert cs.bucket_cred["kr_equity"] == 0.5  # unchanged
    assert cs.history_count == 0


def test_persistence_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("tradingagents.skills.overlay.credibility.CRED_PATH", tmp_path / "cred.json")
    cs = CredibilityState(bucket_cred={"kr_equity": 0.4}, history_count=5, last_updated=date(2026, 6, 15))
    save_credibility(cs)
    loaded = load_credibility()
    assert loaded.bucket_cred["kr_equity"] == 0.4
    assert loaded.history_count == 5
