from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class StalenessAware(BaseModel):
    """모든 외부 데이터 기반 스냅샷의 베이스. staleness 추적."""

    staleness_days: int = Field(
        default=0,
        ge=0,
        description="Days since the source data was current. 0 = live, >7 = stale.",
    )
    source_date: Optional[date] = Field(
        default=None,
        description="The 'as-of' date of the underlying data (not fetch time).",
    )

    @property
    def is_stale(self) -> bool:
        """True if data is more than 1 day old."""
        return self.staleness_days > 1

    @property
    def is_severely_stale(self) -> bool:
        """True if data is more than 7 days old."""
        return self.staleness_days > 7
