from datetime import date
from types import SimpleNamespace as NS
from tradingagents.agents.analysts import macro_quant_analyst as mqa
from tradingagents.schemas.macro import RegimeClassification


def test_foldin_overwrites_llm_value():
    # 결정론 fold-in이 (LLM이 채웠을) signal_confidence를 덮어쓴다
    regime = RegimeClassification(quadrant="growth_inflation", confidence=0.9, drivers=["x"],
                                  reasoning="y", source_date=date(2026, 5, 10),
                                  signal_confidence=0.99)   # 오염값
    snaps = {"gdp_nowcast": NS(nowcast_pct=3.0, staleness_days=0),
             "inflation": NS(momentum_3mo=4.0, core_pce_yoy=3.0, staleness_days=0)}
    out = mqa._fold_in_signal_confidence(regime, snaps)
    assert out.signal_confidence != 0.99
    assert out.signal_confidence > 0.0


def test_regime_snap_keys_present():
    keys = set(mqa._REGIME_SNAP_KEYS)
    for k in ("gdp_nowcast", "inflation", "commodity_momentum", "us_leading",
              "kr_leading", "kr_export", "kr_bsi", "employment", "risk_appetite",
              "yield_curve", "china_leading", "inflation_exp", "chip_cycle"):
        assert k in keys
