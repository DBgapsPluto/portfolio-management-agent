"""Enrich universe.json with `sub_category` field via LLM (1회 실행 도구).

Usage:
    python scripts/enrich_universe_subcategory.py \
        --universe data/universe.json \
        --provider openai \
        --model gpt-4o-mini

이미 sub_category가 채워진 ETF는 skip (idempotent). force=True면 전부 재분류.

LLM 호출 비용 추정: 188 ETF × 10/batch = 약 19 호출. gpt-4o-mini 기준 < $0.05.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from tradingagents.dataflows.universe import load_universe
from tradingagents.llm_clients import create_llm_client
from tradingagents.skills.portfolio.sub_category import (
    bucket_for_category, classify_batch_via_llm,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--universe", type=Path, default=Path("data/universe.json"),
        help="universe.json 경로",
    )
    parser.add_argument("--provider", default="openai", help="LLM provider")
    parser.add_argument("--model", default="gpt-4o-mini", help="LLM model name")
    parser.add_argument(
        "--force", action="store_true",
        help="이미 sub_category 있는 ETF도 재분류",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="결과만 출력, 파일 저장 X",
    )
    parser.add_argument("--batch-size", type=int, default=10)
    args = parser.parse_args()

    if not args.universe.exists():
        logger.error("universe file not found: %s", args.universe)
        return 1

    universe = load_universe(args.universe)
    logger.info("Loaded %d ETFs from %s", len(universe.etfs), args.universe)

    # 대상 추출 (이미 있는 건 skip 옵션)
    pending = []
    for etf in universe.etfs:
        if etf.sub_category and not args.force:
            continue
        bucket = bucket_for_category(etf.category)
        if bucket is None:
            logger.warning("Unknown category %r for ticker %s — skipping", etf.category, etf.ticker)
            continue
        pending.append({
            "ticker": etf.ticker,
            "name": etf.name,
            "underlying_index": etf.underlying_index,
            "bucket": bucket,
        })

    if not pending:
        logger.info("Nothing to classify (all ETFs already have sub_category). Use --force to redo.")
        return 0

    logger.info("Classifying %d ETFs via %s/%s ...", len(pending), args.provider, args.model)
    llm = create_llm_client(provider=args.provider, model=args.model).get_llm()
    classifications = classify_batch_via_llm(pending, llm, batch_size=args.batch_size)
    logger.info("Got %d classifications", len(classifications))

    # 분포 출력
    from collections import Counter
    counter: Counter[str] = Counter(classifications.values())
    logger.info("Distribution:")
    for label, count in counter.most_common():
        logger.info("  %s: %d", label, count)

    # 적용
    updated = 0
    for etf in universe.etfs:
        label = classifications.get(etf.ticker)
        if label and (args.force or not etf.sub_category):
            etf.sub_category = label
            updated += 1

    if args.dry_run:
        logger.info("[dry-run] Would update %d ETFs. Skipping file write.", updated)
        return 0

    # 백업
    backup = args.universe.with_suffix(args.universe.suffix + ".bak")
    backup.write_text(args.universe.read_text(encoding="utf-8"), encoding="utf-8")
    logger.info("Backup written: %s", backup)

    args.universe.write_text(
        universe.model_dump_json(indent=2), encoding="utf-8",
    )
    logger.info("Updated %d ETFs in %s", updated, args.universe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
