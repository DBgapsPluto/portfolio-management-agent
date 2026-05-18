from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tradingagents.dataflows.save_brief import (
    parse_brief_date, split_save_brief_pages,
)
from tradingagents.skills.news.save_ingestor import (
    _parse_value, _to_region,
    ingest_save_brief, parse_economic_releases,
    parse_news_cards_heuristic, parse_weekly_schedule,
)


FIXTURE = Path(__file__).parents[2] / "fixtures" / "save" / "extracted_result_2026-05-15.txt"


def test_parse_brief_date_from_fixture():
    if not FIXTURE.exists():
        pytest.skip("fixture not available")
    text = FIXTURE.read_text(encoding="utf-8")
    d = parse_brief_date(text)
    assert d == date(2026, 5, 15)


def test_split_pages_yields_nonempty():
    text = (
        "--- Page 1 ---\nA\n\n--- Page 2 ---\nB\nstuff\n--- Page 3 ---\n   \n"
    )
    pages = split_save_brief_pages(text)
    assert "A" in pages[0]
    assert "B" in pages[1]
    # 3페이지는 빈 페이지 (whitespace only) → skip
    assert len(pages) == 2


def test_parse_value_pct():
    val, unit = _parse_value("1.9%")
    assert val == pytest.approx(1.9)
    assert unit == "pct"


def test_parse_value_k():
    val, unit = _parse_value("211K")
    assert val == 211.0
    assert unit == "k"


def test_parse_value_plus_sign():
    val, _ = _parse_value("+0.5%")
    assert val == pytest.approx(0.5)


def test_parse_value_none():
    val, unit = _parse_value(None)
    assert val is None
    assert unit == "level"


def test_to_region_mapping():
    assert _to_region("미국") == "US"
    assert _to_region("한국") == "KR"
    assert _to_region("연준") == "US"
    assert _to_region("랜덤") == "GLOBAL"


def test_parse_economic_releases_from_fixture():
    if not FIXTURE.exists():
        pytest.skip("fixture not available")
    text = FIXTURE.read_text(encoding="utf-8")
    pages = split_save_brief_pages(text)
    releases = parse_economic_releases(pages, date(2026, 5, 15))
    # 샘플에 미국 수입물가, 신규실업수당, 4월 소매판매, 3월 기업재고가 있음
    assert len(releases) >= 2
    indicators = [r.indicator for r in releases]
    assert any("수입물가" in ind or "import" in ind.lower() for ind in indicators)
    # importance ★★★ 가 1개는 있어야 (실업수당청구건수)
    assert any(r.importance == 3 for r in releases)


def test_parse_economic_releases_inline_synthetic():
    page = (
        "[경제 지표]\n"
        "21:30 - 미국 - 4월 수입물가지수 ★★ 1.9% (예상: 1.0% 이전: 0.8%)\n"
        "21:30 - 미국 - 신규실업수당청구건수 ★★★ 211K (예상: 205K 이전: 200K)\n"
    )
    releases = parse_economic_releases([page], date(2026, 5, 15))
    assert len(releases) == 2
    assert releases[0].importance == 2
    assert releases[0].actual == pytest.approx(1.9)
    assert releases[0].forecast == pytest.approx(1.0)
    assert releases[1].importance == 3
    assert releases[1].actual == 211.0


def test_parse_news_cards_heuristic_picks_kr_en_pair():
    page = (
        "## 1. 페이지 내 텍스트 추출\n\n"
        "오늘의 소식\n\n"
        "RBC, 10년물 5%이면 미 주식 도전\n"
        "RBC's Calvasina Says 5% Yield Would Challenge US Stock Bulls\n"
        "- 본문 bullet\n"
    )
    out = parse_news_cards_heuristic([page])
    assert len(out) == 1
    assert "RBC" in out[0].headline


def test_parse_weekly_schedule_extracts_treasury_auctions():
    page = (
        "이번 주 일정\n"
        "국채 경매: 3·10·30년 물\n"
        "FOMC 회의록 공개 예정\n"
        "관련 없는 내용 한 줄\n"
    )
    events = parse_weekly_schedule([page, page], date(2026, 5, 15))
    assert len(events) >= 1
    descriptions = [e.description for e in events]
    assert any("국채" in d or "auction" in d.lower() for d in descriptions)


def test_ingest_save_brief_with_fixture():
    if not FIXTURE.exists():
        pytest.skip("fixture not available")
    snap = ingest_save_brief(
        as_of=date(2026, 5, 15), quick_llm=None,
        explicit_path=FIXTURE,
    )
    assert snap is not None
    assert snap.brief_date == date(2026, 5, 15)
    assert snap.pages_parsed >= 1
    # 경제지표는 fixture에 들어있음
    assert len(snap.economic_releases) >= 1


def test_ingest_returns_none_when_file_missing():
    snap = ingest_save_brief(
        as_of=date(2026, 5, 15), quick_llm=None,
        explicit_path="/nonexistent/path/save.txt",
    )
    assert snap is None


def test_ingest_uses_llm_when_provided():
    fake = MagicMock()
    fake.invoke.return_value.content = (
        '[{"title_kr":"테스트 헤드라인","title_en":"Test","bullet":"x"}]'
    )
    if not FIXTURE.exists():
        pytest.skip("fixture not available")
    snap = ingest_save_brief(
        as_of=date(2026, 5, 15), quick_llm=fake,
        explicit_path=FIXTURE,
    )
    assert snap is not None
    # LLM 결과가 잡혔거나, 휴리스틱으로 채워졌거나
    assert len(snap.news_cards) >= 1
