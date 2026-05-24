#!/usr/bin/env python3
"""SAVE 브리핑 자동 페치 → data/SAVE/YYYY-MM-DD.txt 저장.

흐름:
  1. Playwright(Chromium)로 saveticker.com 로그인
  2. /report 페이지에서 타겟 이하 가장 가까운 카드의 'PDF 다운로드' 클릭
  3. PDF를 OpenAI Files API에 업로드 → Responses API로 1회 텍스트 추출
  4. macro_news 애널리스트가 읽는 포맷으로 data/SAVE/{리포트날짜}.txt 저장
  5. (선택) git commit + push

Routine 권장 일정: 평일 22:00 KST.

필수 env:
  SAVE_EMAIL          saveticker.com 로그인 이메일
  SAVE_PASSWORD       로그인 비밀번호
  OPENAI_API_KEY      OpenAI API 키 (openai SDK가 자동 사용)

선택 env:
  SAVE_BRIEF_DIR      출력 디렉토리 (기본: <repo>/data/SAVE)
  SAVE_OCR_MODEL      OpenAI 모델 (기본: gpt-5)
  SAVE_DATE           YYYY-MM-DD 강제 지정 (기본: 오늘 KST)
  SAVE_DEBUG          1이면 단계별 스크린샷 /tmp 저장
  SAVE_HEADLESS       0이면 GUI로 브라우저 표시 (디버그 용도, 기본 1)
  SAVE_GIT_PUSH       1이면 저장 후 git add/commit/push (클라우드 routine용)
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import fitz  # PyMuPDF
from openai import OpenAI
from playwright.sync_api import Page, sync_playwright

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("save_brief")

KST = ZoneInfo("Asia/Seoul")
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAVE_DIR = REPO_ROOT / "data" / "SAVE"

LOGIN_URL = "https://saveticker.com/login"
REPORT_URL = "https://saveticker.com/report"

def env_or_die(key: str) -> str:
    v = os.environ.get(key)
    if not v:
        log.error("필수 환경변수 %s 가 설정되지 않았습니다.", key)
        sys.exit(2)
    return v


def login(page: Page, email: str, password: str) -> None:
    log.info("로그인 페이지 진입: %s", LOGIN_URL)
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass  # networkidle 못 잡아도 진행

    # saveticker.com 로그인 페이지는 소셜 로그인 + "이메일로 로그인" 진입 버튼
    # 구조. 이메일 form이 바로 보이지 않으면 진입 버튼을 먼저 클릭.
    email_entry = page.locator(
        'button:has-text("이메일로 로그인"), '
        'a:has-text("이메일로 로그인"), '
        '[role="button"]:has-text("이메일로 로그인"), '
        'button:has-text("이메일"), a:has-text("이메일")'
    ).first
    if email_entry.count() > 0 and email_entry.is_visible():
        log.info("'이메일로 로그인' 진입 버튼 클릭")
        email_entry.click()
        page.wait_for_timeout(800)  # form 펼침/네비게이션 대기

    email_input = page.locator(
        'input[type="email"], input[name*="email" i], input[id*="email" i], '
        'input[placeholder*="이메일"], input[placeholder*="email" i], '
        'input[autocomplete="username"], input[autocomplete="email"]'
    ).first
    try:
        email_input.wait_for(timeout=15000)
    except Exception:
        dump_html = Path("/tmp/save_login_dump.html")
        dump_png = Path("/tmp/save_login_fail.png")
        dump_html.write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(dump_png), full_page=True)
        log.error("이메일 input을 찾지 못함. 디버그: %s, %s", dump_html, dump_png)
        raise

    email_input.fill(email)
    pw_input = page.locator('input[type="password"]').first
    pw_input.fill(password)

    submit_selectors = [
        'button[type="submit"]:visible',
        'input[type="submit"]:visible',
        'button:has-text("로그인"):visible',
        'button:has-text("Login"):visible',
        'button:has-text("Sign in"):visible',
        '[role="button"]:has-text("로그인"):visible',
        'a:has-text("로그인"):visible',
        'div:has-text("로그인"):visible',
    ]
    clicked = False
    for sel in submit_selectors:
        cand = page.locator(sel).first
        try:
            if cand.count() > 0:
                log.info("로그인 버튼 매칭: %s", sel)
                cand.click(timeout=3000)
                clicked = True
                break
        except Exception as e:
            log.debug("selector %s 클릭 실패: %s", sel, e)
            continue
    if not clicked:
        log.warning("로그인 버튼 selector 모두 실패 — 비밀번호 input에 Enter 폴백")
        pw_input.press("Enter")

    try:
        page.wait_for_url(lambda url: "/login" not in url, timeout=20000)
    except Exception:
        Path("/tmp/save_after_submit.html").write_text(
            page.content(), encoding="utf-8"
        )
        page.screenshot(path="/tmp/save_after_submit.png", full_page=True)
        log.error(
            "로그인 후 URL 전환이 안 됨. 디버그: /tmp/save_after_submit.html, .png"
        )
        raise
    log.info("로그인 성공: %s", page.url)


def _collect_pdf_cards(page: Page) -> list[dict]:
    """각 'PDF 다운로드' 버튼에서 카드 컨테이너로 거슬러 올라가 날짜 매칭.

    Returns: [{date: 'YYYY-MM-DD', index: int}, ...]  index는 PDF 버튼 순서.
    saveticker.com /report 페이지는 각 카드가 독립된 'PDF 다운로드' 버튼을
    가지므로 카드 진입 없이 목록에서 바로 클릭 가능.
    """
    return page.evaluate(
        """() => {
            const re = /(\\d{4})\\s*년\\s*(\\d{1,2})\\s*월\\s*(\\d{1,2})\\s*일/;
            const buttons = Array.from(document.querySelectorAll('button'))
                .filter(b => (b.innerText || b.textContent || '').trim() === 'PDF 다운로드');
            const out = [];
            for (let i = 0; i < buttons.length; i++) {
                let cur = buttons[i];
                for (let depth = 0; depth < 12 && cur; depth++) {
                    const txt = cur.textContent || '';
                    const m = txt.match(re);
                    if (m) {
                        const y = +m[1], mo = +m[2], d = +m[3];
                        const ds = `${y}-${String(mo).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
                        out.push({date: ds, index: i});
                        break;
                    }
                    cur = cur.parentElement;
                }
            }
            return out;
        }"""
    )


def download_pdf_for_date(page: Page, out_path: Path, target_date: date) -> str:
    """target_date 이하 가장 가까운 카드의 PDF를 다운로드. 선택된 카드의
    실제 날짜 문자열(YYYY-MM-DD)을 반환."""
    log.info("리포트 페이지 진입: %s", REPORT_URL)
    page.goto(REPORT_URL, wait_until="domcontentloaded", timeout=30000)

    # 'PDF 다운로드' 버튼이 렌더링될 때까지 대기 — 카드의 핵심 element
    try:
        page.wait_for_selector(
            'button:has-text("PDF 다운로드")', timeout=30000
        )
        log.info("PDF 다운로드 버튼 렌더링 감지됨")
    except Exception:
        Path("/tmp/save_report_list.html").write_text(
            page.content(), encoding="utf-8"
        )
        page.screenshot(path="/tmp/save_report_list.png", full_page=True)
        raise RuntimeError(
            "'PDF 다운로드' 버튼이 30초 내 안 나타남. "
            "/tmp/save_report_list.{html,png} 확인."
        )

    cards = _collect_pdf_cards(page)
    log.info("PDF 카드 후보 %d개", len(cards))
    for c in cards[:5]:
        log.info("  - %s (idx=%d)", c["date"], c["index"])
    if not cards:
        raise RuntimeError(
            "PDF 다운로드 버튼은 있지만 인접한 날짜 텍스트를 찾지 못함."
        )

    target_str = target_date.strftime("%Y-%m-%d")
    eligible = [c for c in cards if c["date"] <= target_str]
    if not eligible:
        log.warning("target=%s 이하 카드 없음 — 전체 중 최신 사용", target_str)
        eligible = cards
    chosen = max(eligible, key=lambda x: x["date"])
    log.info("선택: %s (target=%s, idx=%d)", chosen["date"], target_str, chosen["index"])

    pdf_buttons = page.locator('button:has-text("PDF 다운로드")')
    btn = pdf_buttons.nth(chosen["index"])
    btn.scroll_into_view_if_needed()

    with page.expect_download(timeout=20000) as dl_info:
        btn.click()
    dl_info.value.save_as(str(out_path))
    log.info("PDF 다운로드 완료: %s", out_path)
    return chosen["date"]


def _count_pdf_pages(pdf_path: Path) -> int:
    doc = fitz.open(pdf_path)
    try:
        return len(doc)
    finally:
        doc.close()


def ocr_pdf_whole(client: OpenAI, pdf_path: Path, model: str) -> str:
    """PDF 한 개를 통째로 GPT에 보내 텍스트 추출. 페이지 마커는 모델이 삽입.

    OpenAI Files API에 업로드 → Responses API의 input_file로 참조. 한 번의
    호출로 전체 PDF가 처리되므로 페이지별 vision OCR보다 훨씬 빠름.
    """
    n_pages = _count_pdf_pages(pdf_path)
    log.info("PDF 페이지 수: %d → 통합 OCR 1회 호출", n_pages)

    with pdf_path.open("rb") as f:
        file_obj = client.files.create(file=f, purpose="user_data")
    log.info("PDF 업로드 완료: file_id=%s", file_obj.id)

    prompt = (
        f"이 PDF는 총 {n_pages} 페이지입니다. 모든 페이지의 텍스트를 빠짐없이 추출해 주세요. "
        f"한글/영문/숫자/기호 모두 포함합니다. "
        f"각 페이지의 시작에 정확히 `----- Page N -----` 마커를 넣어 주세요 "
        f"(N은 1부터 {n_pages}까지 순서대로). "
        f"원본 레이아웃과 읽기 순서를 가능한 보존하고, 표/리스트 항목 구분은 줄바꿈으로 유지합니다. "
        f"추가 설명이나 markdown 코드블록 없이 추출 텍스트와 페이지 마커만 반환하세요."
    )

    try:
        resp = client.responses.create(
            model=model,
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_file", "file_id": file_obj.id},
                    {"type": "input_text", "text": prompt},
                ],
            }],
        )
        return (resp.output_text or "").strip()
    finally:
        try:
            client.files.delete(file_obj.id)
        except Exception as e:
            log.warning("임시 파일 정리 실패 (무시): %s", e)


def write_brief_text(date_str: str, text: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date_str}.txt"
    out_path.write_text(text, encoding="utf-8")
    log.info("저장 완료: %s (%d chars)", out_path, len(text))
    return out_path


def git_commit_push(file_path: Path) -> None:
    """저장된 브리핑 파일을 git에 add/commit/push. 변경 없으면 skip."""
    try:
        rel = file_path.relative_to(REPO_ROOT)
    except ValueError:
        log.warning("출력 파일이 repo 밖이라 git push skip: %s", file_path)
        return
    subprocess.run(["git", "add", str(rel)], cwd=REPO_ROOT, check=True)
    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=REPO_ROOT
    )
    if diff.returncode == 0:
        log.info("staged 변경 없음 — commit/push skip")
        return
    msg = f"chore(save): brief {rel.name}"
    subprocess.run(
        ["git", "commit", "-m", msg, "--no-verify"], cwd=REPO_ROOT, check=True
    )
    subprocess.run(["git", "push"], cwd=REPO_ROOT, check=True)
    log.info("git commit + push 완료: %s", rel)


def main() -> int:
    email = env_or_die("SAVE_EMAIL")
    password = env_or_die("SAVE_PASSWORD")
    env_or_die("OPENAI_API_KEY")

    date_str = os.environ.get(
        "SAVE_DATE", datetime.now(KST).strftime("%Y-%m-%d")
    )
    out_dir = Path(os.environ.get("SAVE_BRIEF_DIR", str(DEFAULT_SAVE_DIR)))
    model = os.environ.get("SAVE_OCR_MODEL", "gpt-5")
    headless = os.environ.get("SAVE_HEADLESS", "1") != "0"
    debug = os.environ.get("SAVE_DEBUG", "0") == "1"

    log.info("타겟 날짜=%s 출력=%s 모델=%s headless=%s",
             date_str, out_dir, model, headless)

    pdf_path = Path(f"/tmp/save_brief_{date_str}.pdf")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(accept_downloads=True)
        page = ctx.new_page()
        try:
            login(page, email, password)
            if debug:
                page.screenshot(path=f"/tmp/save_after_login_{date_str}.png",
                                full_page=True)
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            chosen_date = download_pdf_for_date(page, pdf_path, target_date)
            if debug:
                page.screenshot(path=f"/tmp/save_after_download_{date_str}.png",
                                full_page=True)
        finally:
            ctx.close()
            browser.close()

    client = OpenAI()
    text = ocr_pdf_whole(client, pdf_path, model)
    out_file = write_brief_text(chosen_date, text, out_dir)
    if os.environ.get("SAVE_GIT_PUSH", "0") == "1":
        git_commit_push(out_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
