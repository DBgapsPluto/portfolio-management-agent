"""Stage-isolated replay CLI — 한 stage만 단독 실행하고 결과 JSON 저장.

목적: 한 노드를 수정한 뒤 전체 E2E 재실행 없이 그 노드만 재호출 → diff 비교.

Usage:
    set -a && source .env && set +a
    python scripts/replay_stage.py --as-of 2026-05-15 --stage macro_quant
    python scripts/replay_stage.py --as-of 2026-05-15 --stage portfolio_manager \\
        --artifacts-dir artifacts/2026-05-15-replay

기본 동작:
  - baseline runs/{as_of}/*.json 파일은 덮어쓰지 않음 (archive bypass).
  - 결과는 runs/{as_of}/replay/{stage}_{ts}.json 에 저장 → diff용.
  - portfolio_manager는 파일을 직접 쓰므로 --artifacts-dir로 별도 경로 지정 권장.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--stage", required=True,
        help="stage name (e.g. macro_quant, allocator, risk_debate, portfolio_manager)",
    )
    parser.add_argument("--preset", default="db_gaps")
    parser.add_argument("--capital", type=int, default=1_000_000_000)
    parser.add_argument(
        "--artifacts-dir", default=None,
        help="portfolio_manager용 출력 디렉토리 override (기본 baseline 덮어씀)",
    )
    parser.add_argument(
        "--out", default=None,
        help="결과 JSON 저장 경로 (default: runs/{as_of}/replay/{stage}_{ts}.json)",
    )
    parser.add_argument(
        "--write-archive", action="store_true",
        help="baseline runs/{as_of}/*.json도 덮어쓰기 (default: bypass)",
    )
    args = parser.parse_args()

    try:
        datetime.strptime(args.as_of, "%Y-%m-%d")
    except ValueError:
        logger.error("Invalid --as-of: %s", args.as_of); return 1

    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.observability.replay import (
        STAGE_PREREQUISITES, restore_state, run_stage,
    )
    from tradingagents.observability.run_archive import _serializable

    if args.stage not in STAGE_PREREQUISITES:
        logger.error(
            "Unknown stage '%s'. Known: %s",
            args.stage, sorted(STAGE_PREREQUISITES),
        )
        return 1

    config = dict(DEFAULT_CONFIG)
    if args.artifacts_dir:
        config["artifacts_dir"] = args.artifacts_dir
        logger.info("artifacts_dir override: %s", args.artifacts_dir)

    logger.info("=" * 70)
    logger.info(
        "REPLAY — as_of=%s, stage=%s, preset=%s",
        args.as_of, args.stage, args.preset,
    )
    logger.info("=" * 70)

    t0 = time.time()
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    graph = TradingAgentsGraph(preset_name=args.preset, config=config)
    logger.info("Graph initialized in %.1fs", time.time() - t0)

    state, missing = restore_state(
        as_of_date=args.as_of,
        stage=args.stage,
        universe_path=config["universe_path"],
        capital_krw=args.capital,
        preset_name=args.preset,
    )
    if missing:
        logger.warning("Missing prerequisite archive keys: %s", missing)

    t1 = time.time()
    try:
        result = run_stage(
            graph, args.stage, state,
            write_to_archive=args.write_archive,
        )
    except Exception as e:
        logger.exception("Stage replay failed: %s", e)
        return 3
    elapsed = time.time() - t1
    logger.info("=" * 70)
    logger.info("STAGE %s COMPLETE in %.1fs", args.stage, elapsed)
    logger.info("=" * 70)

    if args.out:
        out_path = Path(args.out)
    else:
        cache_dir = Path(config["data_cache_dir"])
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = cache_dir.parent / "runs" / args.as_of / "replay"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{args.stage}_{ts}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(_serializable(result), default=str,
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Saved replay output → %s", out_path)
    logger.info("Result keys: %s", sorted(result.keys()) if isinstance(result, dict) else type(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
