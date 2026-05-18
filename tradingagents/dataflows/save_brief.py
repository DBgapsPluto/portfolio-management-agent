"""SAVE 브리핑 텍스트 파일 로더.

이미 LLM-vision으로 추출된 텍스트 파일을 입력으로 받음. PDF/OCR 처리 0.

기본 경로: `<project_root>/data/SAVE/` (환경변수 SAVE_BRIEF_DIR로 override).
파일명 규칙: `YYYY-MM-DD.txt` (또는 `YYYY-MM-DD`, `YYYY-MM-DD.md` 등 확장자 무관).
파일명 stem이 `YYYY-MM-DD` 패턴이어야 as_of 기반 매칭에 잡힘.
"""
import logging
import os
import re
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


SAVE_BRIEF_DIR_ENV = "SAVE_BRIEF_DIR"
# 기본 경로: 프로젝트 루트의 data/SAVE/. 이 모듈이
# tradingagents/dataflows/save_brief.py 위치이므로 parents[2]가 project root.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SAVE_BRIEF_DIR = str(_PROJECT_ROOT / "data" / "SAVE")

PAGE_SPLIT_RE = re.compile(r"---\s*Page\s+\d+\s*---", re.IGNORECASE)
DATE_RE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
# 파일명 stem이 YYYY-MM-DD로 시작 (`2026-05-15`, `2026-05-15.txt` 모두 OK)
FILE_STEM_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def resolve_save_brief_dir() -> Path:
    base = os.environ.get(SAVE_BRIEF_DIR_ENV, DEFAULT_SAVE_BRIEF_DIR)
    return Path(base).expanduser()


def _extract_file_date(p: Path) -> date | None:
    """파일명 stem에서 YYYY-MM-DD 추출. 매칭 실패면 None."""
    m = FILE_STEM_DATE_RE.match(p.stem)
    if m is None:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def find_latest_save_brief(
    as_of: date | None = None, search_dir: Path | None = None,
) -> Path | None:
    """as_of 기준 가장 가까운 (과거) SAVE 브리핑 파일을 찾는다.

    매칭 우선순위:
      1. 파일명 stem이 YYYY-MM-DD이고 as_of 이하인 것 중 가장 가까운 날짜
      2. 1번 실패 시 mtime 가장 최근 파일

    검색 대상: search_dir 안의 모든 파일 (확장자 무관). hidden/dir 제외.
    """
    base = search_dir or resolve_save_brief_dir()
    if not base.exists():
        return None
    candidates = [
        p for p in base.iterdir()
        if p.is_file() and not p.name.startswith(".")
    ]
    if not candidates:
        return None

    if as_of is None:
        return max(candidates, key=lambda p: p.stat().st_mtime)

    best: tuple[int, Path] | None = None
    for p in candidates:
        file_date = _extract_file_date(p)
        if file_date is None:
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
