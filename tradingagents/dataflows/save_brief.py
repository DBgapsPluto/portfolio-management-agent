"""SAVE 브리핑 텍스트 로더.

이미 LLM-vision으로 추출된 텍스트 파일을 입력으로 받음. PDF/OCR 처리 0.
파일은 GitHub repo의 `data/SAVE/` 디렉토리에서 매 호출마다 fetch한다.
GitHub Actions가 평일 22:00 KST에 새 브리핑을 자동 push하므로 항상 최신.

파일명 규칙: `YYYY-MM-DD.txt`. 파일명 stem이 `YYYY-MM-DD` 패턴이어야
as_of 기반 매칭에 잡힘.

필수 env:
  GITHUB_TOKEN        Personal Access Token (private repo 접근)

선택 env:
  SAVE_BRIEF_REPO     기본 'DBgapsPluto/pluto'
  SAVE_BRIEF_REF      기본 'main'
  SAVE_BRIEF_PATH     기본 'data/SAVE'
"""
import logging
import os
import re
import tempfile
from datetime import date, datetime
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


PAGE_SPLIT_RE = re.compile(r"---\s*Page\s+\d+\s*---", re.IGNORECASE)
DATE_RE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
FILE_STEM_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")

DEFAULT_REPO = "DBgapsPluto/pluto"
DEFAULT_REF = "main"
DEFAULT_PATH = "data/SAVE"
API_BASE = "https://api.github.com"


def _resolve_config() -> tuple[str, str, str]:
    return (
        os.environ.get("SAVE_BRIEF_REPO", DEFAULT_REPO),
        os.environ.get("SAVE_BRIEF_REF", DEFAULT_REF),
        os.environ.get("SAVE_BRIEF_PATH", DEFAULT_PATH),
    )


def _get_token() -> str:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError(
            "GITHUB_TOKEN 환경변수가 필요합니다 (private repo 접근용). "
            "export GITHUB_TOKEN=ghp_... 또는 .env로 주입하세요."
        )
    return token


def _gh_headers(extra: dict | None = None) -> dict:
    headers = {
        "Authorization": f"Bearer {_get_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if extra:
        headers.update(extra)
    return headers


def _list_remote_files() -> list[dict]:
    """data/SAVE 디렉토리의 파일 목록을 GitHub Contents API로 조회.

    Returns: [{name, path, sha, size, ...}, ...]
    """
    repo, ref, path = _resolve_config()
    url = f"{API_BASE}/repos/{repo}/contents/{path}"
    r = requests.get(url, headers=_gh_headers(), params={"ref": ref}, timeout=30)
    r.raise_for_status()
    items = r.json()
    if not isinstance(items, list):
        raise RuntimeError(f"디렉토리가 아닌 응답: {items}")
    return [i for i in items if i.get("type") == "file"]


def _download_remote_file(remote_path: str) -> str:
    """GitHub Contents API에서 raw 텍스트 다운로드."""
    repo, ref, _ = _resolve_config()
    url = f"{API_BASE}/repos/{repo}/contents/{remote_path}"
    headers = _gh_headers({"Accept": "application/vnd.github.raw"})
    r = requests.get(url, headers=headers, params={"ref": ref}, timeout=30)
    r.raise_for_status()
    return r.text


def _extract_file_date(name_or_path) -> date | None:
    """파일명/Path stem에서 YYYY-MM-DD 추출. Path와 str 둘 다 허용."""
    if isinstance(name_or_path, Path):
        stem = name_or_path.stem
    else:
        s = str(name_or_path)
        stem = s.rsplit(".", 1)[0] if "." in s else s
    m = FILE_STEM_DATE_RE.match(stem)
    if m is None:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def _find_in_local_dir(as_of: date | None, base: Path) -> Path | None:
    """로컬 디렉토리 기반 매칭 (테스트 호환성용). 기본은 GitHub fetch."""
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
        fd = _extract_file_date(p)
        if fd is None or fd > as_of:
            continue
        days_back = (as_of - fd).days
        if best is None or days_back < best[0]:
            best = (days_back, p)
    return best[1] if best else max(candidates, key=lambda p: p.stat().st_mtime)


def find_latest_save_brief(
    as_of: date | None = None, search_dir: Path | None = None,
) -> Path | None:
    """as_of 기준 가장 가까운 (과거) SAVE 브리핑을 찾는다.

    기본 동작 (search_dir=None): GitHub repo의 data/SAVE/에서 fetch.
      매 호출마다 fresh 다운로드 (캐시 X) → 항상 최신 보장.
      필수 env: GITHUB_TOKEN.

    호환 동작 (search_dir 명시): 로컬 디렉토리에서 매칭 (테스트/오프라인용).

    매칭 우선순위:
      1. 파일명 stem이 YYYY-MM-DD이고 as_of 이하 중 가장 가까운 날짜
      2. 1번 실패 시 이름순(GitHub) 또는 mtime(로컬) 최신

    Returns: 다운로드된 임시 파일 Path. 후보 없으면 None.
    """
    if search_dir is not None:
        return _find_in_local_dir(as_of, search_dir)

    try:
        files = _list_remote_files()
    except (requests.HTTPError, requests.ConnectionError, RuntimeError) as e:
        logger.error("GitHub 디렉토리 조회 실패: %s", e)
        return None
    if not files:
        return None

    chosen: dict | None = None
    if as_of is None:
        chosen = max(files, key=lambda f: f["name"])
    else:
        best: tuple[int, dict] | None = None
        for f in files:
            fd = _extract_file_date(f["name"])
            if fd is None or fd > as_of:
                continue
            days_back = (as_of - fd).days
            if best is None or days_back < best[0]:
                best = (days_back, f)
        chosen = best[1] if best else max(files, key=lambda f: f["name"])

    if chosen is None:
        return None

    logger.info("SAVE 브리핑 fetch: %s (as_of=%s)", chosen["name"], as_of)
    try:
        text = _download_remote_file(chosen["path"])
    except (requests.HTTPError, requests.ConnectionError) as e:
        logger.error("GitHub 파일 다운로드 실패 (%s): %s", chosen["path"], e)
        return None
    tmp_path = Path(tempfile.gettempdir()) / f"save_brief_{chosen['name']}"
    tmp_path.write_text(text, encoding="utf-8")
    return tmp_path


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
