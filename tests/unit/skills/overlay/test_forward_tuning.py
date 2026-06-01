from datetime import date
from tradingagents.schemas.llm_overlay import CredibilityState
from tradingagents.skills.overlay.forward_tuning import auto_tune_band


_BUCKETS = ["kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx",
            "kr_bond", "credit", "global_duration", "cash_mmf"]


def test_auto_tune_band_tightens_when_low_cred():
    cs = CredibilityState(bucket_cred={b: 0.30 for b in _BUCKETS},
                          history_count=8 * 6, last_updated=date(2026, 7, 15))
    assert auto_tune_band(cs, current_band=0.05) == 0.04


def test_auto_tune_band_loosens_when_high_cred():
    cs = CredibilityState(bucket_cred={b: 0.70 for b in _BUCKETS},
                          history_count=8 * 6, last_updated=date(2026, 7, 15))
    assert auto_tune_band(cs, current_band=0.05) == 0.06


def test_auto_tune_band_neutral_cred_unchanged():
    cs = CredibilityState(bucket_cred={b: 0.50 for b in _BUCKETS},
                          history_count=8 * 6, last_updated=date(2026, 7, 15))
    assert auto_tune_band(cs, current_band=0.05) == 0.05


def test_auto_tune_band_insufficient_history_unchanged():
    cs = CredibilityState(bucket_cred={"kr_equity": 0.7}, history_count=5,
                          last_updated=date(2026, 6, 15))
    assert auto_tune_band(cs, current_band=0.05) == 0.05


def test_auto_tune_band_respects_min_max():
    cs_low = CredibilityState(bucket_cred={b: 0.1 for b in _BUCKETS},
                              history_count=8 * 6, last_updated=date(2026, 7, 15))
    assert auto_tune_band(cs_low, current_band=0.03) == 0.03  # already at min
    cs_high = CredibilityState(bucket_cred={b: 0.9 for b in _BUCKETS},
                               history_count=8 * 6, last_updated=date(2026, 7, 15))
    assert auto_tune_band(cs_high, current_band=0.07) == 0.07  # already at max
