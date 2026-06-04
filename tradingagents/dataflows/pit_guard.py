"""Point-in-time 가드 — 백테스트에서 라이브-온리 소스의 lookahead 차단 (spec 2026-06-04).

as_of가 오늘로부터 충분히 과거면 라이브 데이터(RSS 뉴스·CNN F&G)가 그 시점을 대표하지
못하므로 호출부가 중립값(빈/None)을 반환한다. 라이브(as_of≈오늘)는 발동하지 않는다.
"""
from datetime import date

PIT_STALENESS_DAYS: int = 7   # as_of가 이보다 과거면 라이브-온리 데이터는 point-in-time 불가


def is_pit_stale(as_of: date, today: date | None = None,
                 max_days: int = PIT_STALENESS_DAYS) -> bool:
    """as_of가 today 로부터 max_days 초과 과거면 True. today 미주입 시 date.today()."""
    today = today or date.today()
    return (today - as_of).days > max_days
