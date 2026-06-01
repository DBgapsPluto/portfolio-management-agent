import pytest
from datetime import date
from tradingagents.schemas.macro import (
    FXSnapshot, ForeignFlowSnapshot,
    CommodityMomentumSnapshot, USEquityValuationSnapshot,
    GeopoliticalRiskSnapshot, ChinaCreditImpulseSnapshot,
    EarningsRevisionSnapshot,
)
from tradingagents.schemas.risk import ExcessBondPremiumSnapshot


def test_fxsnapshot_tier0_fields():
    snap = FXSnapshot(
        as_of=date(2026, 5, 28), staleness_days=0,
        usd_krw=1350.0, dxy=104.5,
        krw_change_1m_pct=1.2, dxy_change_1m_pct=-0.5,
        regime="krw_weak",
        krw_change_6m_pct=3.5, krw_reer=98.5,
    )
    assert snap.krw_change_6m_pct == 3.5
    assert snap.krw_reer == 98.5


def test_fxsnapshot_tier0_defaults():
    snap = FXSnapshot(
        as_of=date(2026, 5, 28), staleness_days=0,
        usd_krw=1350.0, dxy=104.5,
        krw_change_1m_pct=1.2, dxy_change_1m_pct=-0.5,
        regime="krw_weak",
    )
    assert snap.krw_change_6m_pct == 0.0
    assert snap.krw_reer is None


def test_commodity_momentum_snapshot():
    snap = CommodityMomentumSnapshot(
        as_of=date(2026, 5, 28), staleness_days=0,
        copper_3m_pct=5.2, copper_6m_pct=10.0,
        gold_3m_pct=2.0, gold_6m_pct=4.5,
        wti_3m_pct=-1.5, wti_6m_pct=3.0,
        bcom_3m_pct=2.5,
    )
    assert snap.copper_3m_pct == 5.2
    assert snap.bcom_3m_pct == 2.5


def test_us_equity_valuation():
    s = USEquityValuationSnapshot(
        as_of=date(2026, 5, 28), staleness_days=0,
        cape=32.5, cape_zscore_30y=1.2,
    )
    assert s.cape == 32.5
    assert s.cape_zscore_30y == 1.2


def test_geopolitical_risk():
    s = GeopoliticalRiskSnapshot(
        as_of=date(2026, 5, 28), staleness_days=0,
        gpr_monthly=120.0, gpr_zscore_60m=1.5, gpr_daily=130.0,
    )
    assert s.gpr_monthly == 120.0
    assert s.gpr_daily == 130.0


def test_china_credit_impulse():
    s = ChinaCreditImpulseSnapshot(
        as_of=date(2026, 5, 28), staleness_days=0,
        credit_impulse=2.5, credit_to_gdp_ratio=228.0, credit_yoy_pct=5.2,
    )
    assert s.credit_impulse == 2.5
    assert s.credit_to_gdp_ratio == 228.0


def test_earnings_revision():
    s = EarningsRevisionSnapshot(
        as_of=date(2026, 5, 28), staleness_days=0,
        sp500_net_revision=0.15, kospi200_net_revision=-0.05,
    )
    assert s.sp500_net_revision == 0.15


def test_excess_bond_premium():
    s = ExcessBondPremiumSnapshot(
        as_of=date(2026, 5, 28), staleness_days=0,
        ebp=-0.25, ebp_zscore_5y=-0.5,
    )
    assert s.ebp == -0.25


def test_foreign_flow_normalized_field():
    s = ForeignFlowSnapshot(
        as_of=date(2026, 5, 28), staleness_days=0,
        net_5d_krw=1e11, net_20d_krw=5e11,
        signal="net_buying",
        net_20d_normalized=0.0012,
    )
    assert s.net_20d_normalized == 0.0012
