import json
import logging
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FetchFailure(Exception):
    """Upstream API failure."""


class CacheMiss(Exception):
    """Live failed and cache lookup also failed within staleness budget."""


class TieredCache:
    """File-backed JSON cache with date-keyed entries (D5)."""

    def __init__(self, cache_dir: Path | str, name: str):
        self.cache_dir = Path(cache_dir) / name
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.name = name

    def _path(self, d: date) -> Path:
        return self.cache_dir / f"{d.isoformat()}.json"

    def write(self, d: date, payload: Any) -> None:
        self._path(d).write_text(json.dumps(payload, default=str), encoding="utf-8")

    def read(self, d: date) -> Any | None:
        p = self._path(d)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def fetch_with_fallback(
        self,
        fetcher: Callable[[], Any],
        as_of: date,
        max_staleness: int = 7,
    ) -> tuple[Any, int]:
        """Try live fetcher; on failure, walk back through cache.

        Returns (payload, staleness_days). 0 = live.
        Raises CacheMiss if live fails and no cache within max_staleness.
        """
        try:
            payload = fetcher()
            self.write(as_of, payload)
            return payload, 0
        except Exception as e:
            logger.warning("Cache %s: live fetch failed: %s — trying fallback", self.name, e)

        for delta in range(1, max_staleness + 1):
            d = as_of - timedelta(days=delta)
            cached = self.read(d)
            if cached is not None:
                logger.warning(
                    "Cache %s: serving stale data from %s (staleness=%d)",
                    self.name, d.isoformat(), delta,
                )
                return cached, delta

        raise CacheMiss(
            f"Cache {self.name}: live failed and no cache within {max_staleness} days of {as_of.isoformat()}"
        )
