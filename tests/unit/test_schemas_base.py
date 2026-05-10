from datetime import date
from tradingagents.schemas._base import StalenessAware


def test_staleness_aware_default_zero():
    class Snap(StalenessAware):
        value: float = 0.0
    s = Snap()
    assert s.staleness_days == 0
    assert s.is_stale is False


def test_staleness_aware_d7_marks_stale():
    class Snap(StalenessAware):
        value: float = 0.0
    s = Snap(staleness_days=7)
    assert s.is_stale is True


def test_staleness_aware_serializes_json():
    class Snap(StalenessAware):
        value: float = 1.5
    s = Snap(value=1.5, staleness_days=2, source_date=date(2026, 5, 10))
    payload = s.model_dump_json()
    assert "staleness_days" in payload
    assert "1.5" in payload
