"""Generate monthly operations report (대회 §4.2: ≥A4 2 pages).

매월 1회 수동 호출. portfolio_manager는 매일 portfolio.json/trade_plan/philosophy
를 자동 생성하지만 monthly report는 *전월 PnL 데이터 + 상태 trace* 필요.

Usage:
    python scripts/generate_monthly_report.py \\
        --month 6 \\
        --pnl-csv data/pnl/2026-06.csv \\
        --as-of-date 2026-06-30 \\
        --out artifacts/2026-06/monthly.md

상태 복원:
    runs/{as_of_date}/macro_summary.json
    runs/{as_of_date}/risk_summary.json
    (Stage 1·2·3·4 archive에서 자동 복원)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client
from tradingagents.observability.run_archive import resolve_run_dir
from tradingagents.reports.monthly import write_monthly

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _restore_state_from_archive(as_of_date: str, run_dir: Path) -> dict:
    """runs/{as_of_date}/*.json archive에서 state 복원.

    monthly prompt가 사용하는 키만 추출 (macro_summary / risk_summary).
    파일 없으면 빈 문자열로 fallback (graceful).
    """
    state: dict = {"as_of_date": as_of_date}
    keys_to_restore = ["macro_summary", "risk_summary"]
    for key in keys_to_restore:
        path = run_dir / f"{key}.json"
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                # archive_report가 str을 json.dumps하면 quoted string 보존
                state[key] = (
                    payload if isinstance(payload, str)
                    else json.dumps(payload, ensure_ascii=False)
                )
            except Exception as e:
                logger.warning("Failed to restore %s: %s", key, e)
                state[key] = ""
        else:
            state[key] = ""
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--month", type=int, required=True,
        help="month number (1-12) — 리포트 대상 월",
    )
    parser.add_argument(
        "--pnl-csv", type=Path, required=True,
        help="PnL CSV (columns: equity 필수). 일별 equity 시계열",
    )
    parser.add_argument(
        "--as-of-date", type=str, required=True,
        help="YYYY-MM-DD — runs/{date}/ archive 위치 + monthly.md 위치 결정",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="output path (default: runs/{as_of_date}/monthly.md)",
    )
    parser.add_argument("--provider", default=None,
                        help="LLM provider (default: DEFAULT_CONFIG)")
    parser.add_argument("--model", default=None,
                        help="LLM model (default: DEFAULT_CONFIG deep_think_llm)")
    args = parser.parse_args()

    # as_of_date 검증
    try:
        datetime.strptime(args.as_of_date, "%Y-%m-%d")
    except ValueError:
        logger.error("as-of-date must be YYYY-MM-DD, got %r", args.as_of_date)
        return 1

    if not args.pnl_csv.exists():
        logger.error("pnl-csv not found: %s", args.pnl_csv)
        return 1

    # State 복원
    run_dir = resolve_run_dir(args.as_of_date)
    state = _restore_state_from_archive(args.as_of_date, run_dir)
    logger.info(
        "Restored state from %s: macro=%d chars, risk=%d chars",
        run_dir, len(state.get("macro_summary", "")), len(state.get("risk_summary", "")),
    )

    # LLM client
    provider = args.provider or DEFAULT_CONFIG.get("llm_provider", "openai")
    model = args.model or DEFAULT_CONFIG.get("deep_think_llm", "gpt-4o-mini")
    logger.info("LLM: %s/%s", provider, model)
    llm = create_llm_client(provider=provider, model=model).get_llm()

    # 출력 경로
    out_path = args.out or (run_dir / "monthly.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 생성
    write_monthly(state, args.pnl_csv, args.month, llm, out_path)
    logger.info("Written: %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
