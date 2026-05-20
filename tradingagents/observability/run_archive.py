"""Stage 1-2 산출물 archive — 매 실행 결과를 JSON으로 영구 저장.

목적:
  1. 사후 분석 (backtest, 모델 변화 추적)
  2. 매 실행 재현 가능 (캐시된 raw input + 저장된 산출물로 정확 복원)
  3. 모델 행동 모니터링 ("어제는 risk_off였는데 오늘은 왜 risk_on?")

위치: ~/.tradingagents/runs/{as_of_date}/{key}.json (기본).
DEFAULT_CONFIG["data_cache_dir"] 부모 디렉토리를 공유.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from tradingagents.default_config import DEFAULT_CONFIG

logger = logging.getLogger(__name__)


def resolve_run_dir(as_of_date: str, base: Path | None = None) -> Path:
    if base is None:
        cache_dir = Path(DEFAULT_CONFIG["data_cache_dir"])
        base = cache_dir.parent / "runs"
    out = Path(base) / as_of_date
    out.mkdir(parents=True, exist_ok=True)
    return out


def _serializable(payload: Any) -> Any:
    """Pydantic → dict, dict/list → recursive."""
    if isinstance(payload, BaseModel):
        return payload.model_dump(mode="json")
    if isinstance(payload, dict):
        return {str(k): _serializable(v) for k, v in payload.items()}
    if isinstance(payload, (list, tuple)):
        return [_serializable(v) for v in payload]
    return payload


def archive_report(
    as_of_date: str, key: str, payload: Any,
    base: Path | None = None,
) -> Path | None:
    """Save one report under runs/{as_of_date}/{key}.json. Returns saved path."""
    if payload is None:
        return None
    run_dir = resolve_run_dir(as_of_date, base=base)
    path = run_dir / f"{key}.json"
    try:
        path.write_text(
            json.dumps(
                _serializable(payload), default=str, ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning("run_archive %s/%s failed: %s", as_of_date, key, e)
        return None
    return path


def archive_metadata(as_of_date: str, metadata: dict, base: Path | None = None) -> None:
    """Write metadata.json — preset/cap/run timestamp 등 부수 정보."""
    run_dir = resolve_run_dir(as_of_date, base=base)
    md = {
        "as_of_date": as_of_date,
        "archived_at": datetime.now().isoformat(),
        **metadata,
    }
    (run_dir / "metadata.json").write_text(
        json.dumps(md, default=str, ensure_ascii=False, indent=2), encoding="utf-8",
    )


# === Wrapping helpers — 분석가 노드 변경 없이 archive 적용 ===

def archive_wrap_node(node: Callable[[dict], dict], report_keys: list[str]):
    """Wrap a LangGraph node so its `state[key]` outputs are auto-archived.

    노드가 반환한 dict에서 지정된 키들을 골라 archive. 노드 자체 동작은 변경 X.
    """
    def wrapped(state: dict) -> dict:
        result = node(state)
        as_of_date = state.get("as_of_date", "unknown")
        for key in report_keys:
            if key in result and result[key] is not None:
                archive_report(as_of_date, key, result[key])
        return result
    # Expose raw node so replay tooling can re-run a stage without overwriting
    # the baseline archive (replay calls wrapped.__wrapped__(state)).
    wrapped.__wrapped__ = node
    return wrapped
