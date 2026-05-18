"""SAVE 브리핑 텍스트 파일 로더.

이미 LLM-vision으로 추출된 텍스트 파일 (extracted_result_*.txt)을 입력으로 받음.
PDF/OCR 처리 0.
"""
import logging
import os
import re
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


SAVE_BRIEF_DIR_ENV = "SAVE_BRIEF_DIR"
DEFAULT_SAVE_BRIEF_DIR = "~/Downloads/SAVE"
PAGE_SPLIT_RE = re.compile(r"---\s*Page\s+\d+\s*---", re.IGNORECASE)
DATE_RE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
FILE_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def resolve_save_brief_dir() -> Path:
    base = os.environ.get(SAVE_BRIEF_DIR_ENV, DEFAULT_SAVE_BRIEF_DIR)
    return Path(base).expanduser()


def find_latest_save_brief(
    as_of: date | None = None, search_dir: Path | None = None,
) -> Path | None:
    """as_of 기준 가장 가까운 SAVE 브리핑 파일을 찾는다.

    파일명에 YYYY-MM-DD가 들어있으면 그걸 기준, 아니면 mtime.
    """
    base = search_dir or resolve_save_brief_dir()
    if not base.exists():
        return None
    candidates = sorted(base.glob("extracted_result_*.txt"))
    if not candidates:
        return None
    if as_of is None:
        # mtime 가장 최근
        return max(candidates, key=lambda p: p.stat().st_mtime)
    # as_of 기준 매칭 (파일명에서 날짜 추출 시도)
    best: tuple[int, Path] | None = None
    for p in candidates:
        m = FILE_DATE_RE.search(p.name)
        if m is None:
            continue
        try:
            file_date = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
        if file_date > as_of:
            continue
        days_back = (as_of - file_date).days
        if best is None or days_back < best[0]:
            best = (days_back, p)
    if best is not None:
        return best[1]
    return max(candidates, key=lambda p: p.stat().st_mtime)


def load_save_brief_text(path: Path | str) -> str:
    return Path(path).read_text(encoding="utf-8")


def split_save_brief_pages(text: str) -> list[str]:
    """Page 경계로 split. 빈 페이지는 제거."""
    parts = PAGE_SPLIT_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


def parse_brief_date(text: str) -> date | None:
    """첫 페이지 상단에 표시된 '2026년 05월 15일 (금)' 패턴."""
    m = DATE_RE.search(text)
    if m is None:
        return None
    try:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return date(y, mo, d)
    except ValueError:
        return None
