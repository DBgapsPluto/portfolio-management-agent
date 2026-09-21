from datetime import date
from types import SimpleNamespace as NS

import pandas as pd
import pytest

from tradingagents.skills.macro import regime_confidence as rc
from tradingagents.skills.macro.inflation import compute_inflation_trend
from tradingagents.skills.macro.employment import compute_unemployment_trend
from tradingagents.skills.macro.yield_curve import compute_yield_curve


def test_laplace_agreement_n1():
    assert rc._agreement([1], +1) == pytest.approx(2/3)      # n=1 일치
    assert rc._agreement([-1], +1) == pytest.approx(1/3)     # n=1 불일치
    assert rc._agreement([], +1) == 0.0                       # n=0 → 0


def test_laplace_agreement_smoothing_decays():
    assert rc._agreement([1]*10, +1) == pytest.approx(11/12)  # n=10 → 0.917


def test_fresh_gate_stale_and_none_abstain():
    assert rc._fresh(None) is False
    assert rc._fresh(NS(staleness_days=99)) is False
    assert rc._fresh(NS(staleness_days=0)) is True


def test_growth_votes_sign_rules():
    snaps = {
        "us_leading": NS(recession_signal=False, cfnai_ma3=0.5, staleness_days=0),
        "yield_curve": NS(spread_10y_2y_bps=-30.0, staleness_days=0),   # 역전 → −1
        "gdp_nowcast": NS(nowcast_pct=3.5, staleness_days=0),           # >2.0 → +1
        "risk_appetite": NS(signal="neutral", staleness_days=0),        # neutral → 기권
    }
    votes = rc._growth_votes(snaps)
    assert sorted(votes) == [-1, 1, 1]   # cfnai+1, yc−1, gdp+1; risk_appetite 기권


def test_compute_confidence_all_agree_high():
    snaps = {
        "us_leading": NS(recession_signal=False, cfnai_ma3=0.5, staleness_days=0),
        "gdp_nowcast": NS(nowcast_pct=3.5, staleness_days=0),
        "inflation": NS(momentum_3mo=4.0, core_pce_yoy=3.0, staleness_days=0),  # >3, >2 → +1,+1
    }
    c = rc.compute_regime_confidence(snaps, "growth_inflation")
    assert c > 0.5


def test_compute_confidence_cross_check_lowers_c():
    snaps = {
        "us_leading": NS(recession_signal=False, cfnai_ma3=0.5, staleness_days=0),
        "gdp_nowcast": NS(nowcast_pct=3.5, staleness_days=0),
        "inflation": NS(momentum_3mo=1.0, core_pce_yoy=1.5, staleness_days=0),  # <3,<2 → −1,−1
    }
    c = rc.compute_regime_confidence(snaps, "growth_inflation")
    assert c < 0.5


def test_compute_confidence_none_snapshot_no_crash():
    snaps = {"commodity_momentum": None, "chip_cycle": None,
             "gdp_nowcast": NS(nowcast_pct=3.0, staleness_days=0)}
    c = rc.compute_regime_confidence(snaps, "growth_inflation")
    assert 0.0 <= c <= 1.0


def test_compute_confidence_output_bounded_and_bad_quadrant():
    assert rc.compute_regime_confidence({}, "growth_inflation") == 0.0
    assert rc.compute_regime_confidence({}, "nonsense") == 0.0


def test_infl_yc_emp_sentinels_abstain_from_regime_confidence():
    empty = pd.Series([], dtype=float)
    infl = compute_inflation_trend(empty, empty, as_of=date(2026, 8, 14))
    emp = compute_unemployment_trend(empty, empty, as_of=date(2026, 8, 14))
    yc = compute_yield_curve(empty, empty, empty, as_of=date(2026, 8, 14))
    snaps = {
        "inflation": infl, "employment": emp, "yield_curve": yc,
        "us_leading": NS(recession_signal=False, cfnai_ma3=0.5, staleness_days=0),
        "risk_appetite": NS(signal="risk_on", staleness_days=0),
        "commodity_momentum": NS(wti_3m_pct=5.0, staleness_days=0),
    }
    c = rc.compute_regime_confidence(snaps, "growth_inflation")
    assert c == pytest.approx(0.5)
    assert infl.staleness_days == 99 and emp.staleness_days == 99 and yc.staleness_days == 99
