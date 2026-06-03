"""Step A 입력 민감도 측정 — thesis 를 동일 substance 의 N개 paraphrase 로 바꿔
allocator 를 replay, 변형 간 bucket_target 분산(cross-variant dispersion) 측정.

L2(measure_stepA_variance: 고정입력 run-to-run stdev)와 달리, 여기서는
'입력(thesis)이 바뀔 때 출력이 얼마나 흔들리는지'를 잰다 — 사용자의 핵심 우려
(결과가 입력 값에 따라 달라지고 기준이 흔들림)에 직접 대응하는 지표.

앵커는 baseline 을 macro_report.regime.quadrant 로만 선택하고 thesis 는 bounded
tilt 에만 영향을 주므로, thesis 문구 변화에 둔감할 것으로 기대(낮은 x-var stdev).
free-LLM(앵커 이전)은 thesis 가 주 동력이라 더 크게 흔들릴 것으로 예상.

각 변형을 --repeat 회 반복해 고정입력 노이즈를 평균화한 뒤, 변형-평균들의 분산을
계산해 입력-주도 변동만 분리한다.

Usage:
    set -a && source .env && set +a
    python scripts/measure_stepA_input_sensitivity.py --as-of 2026-05-15 --repeat 3
"""
from __future__ import annotations

import argparse
import logging
import statistics
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=_ROOT / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

# 동일 substance(인플레 지속 + 성장 견조 → 실물·주식 선호, 듀레이션 경계)의 4개 표현 변형.
# 같은 판단을 서로 다른 어휘·강조·순서로 서술 — 출력이 substance 가 같은데도 흔들리면
# 그게 입력 민감도(기준 드리프트)다.
THESIS_VARIANTS = [
    "물가가 예상보다 끈적하게 유지되는 가운데 성장은 견조하다. 인플레 수혜 자산(금·원자재)과 "
    "주식 비중을 유지하되, 장기 국채 듀레이션은 경계한다.",
    "성장세는 양호하나 인플레이션이 재가속 조짐을 보인다. 실물자산과 위험자산을 선호하고, "
    "금리 민감한 장기채는 비중을 낮게 가져간다.",
    "경기는 확장 국면이고 물가 압력이 지속된다. 인플레 헤지(금)와 경기민감 원자재, 성장주를 "
    "선호한다. 듀레이션 노출은 제한적으로 유지.",
    "디스인플레가 지연되고 성장은 유지되는 환경. 주식과 인플레 연동 자산에 무게를 두고, "
    "미국 장기 금리 자산은 신중하게 접근한다.",
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--as-of", required=True, help="YYYY-MM-DD (archived run 존재해야 함)")
    ap.add_argument("--repeat", type=int, default=3, help="변형당 반복(고정입력 노이즈 평균화)")
    ap.add_argument("--preset", default="db_gaps")
    ap.add_argument("--capital", type=int, default=1_000_000_000)
    args = ap.parse_args()

    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.observability.replay import restore_state, run_stage

    config = dict(DEFAULT_CONFIG)
    graph = TradingAgentsGraph(preset_name=args.preset, config=config)
    state, missing = restore_state(
        as_of_date=args.as_of, stage="allocator",
        universe_path=config["universe_path"], capital_krw=args.capital,
        preset_name=args.preset,
    )
    if missing:
        logger.warning("missing prereq keys: %s", missing)

    rd = state["research_decision"]
    if not hasattr(rd, "model_copy"):
        logger.error("research_decision 가 Pydantic 객체가 아님(%s) — thesis 교체 불가", type(rd))
        return 2

    variant_means: list[dict[str, float]] = []
    for vi, thesis in enumerate(THESIS_VARIANTS):
        new_rd = rd.model_copy(update={"thesis_md": thesis})
        per_run: dict[str, list[float]] = {}
        for _ in range(args.repeat):
            s = dict(state)
            s["research_decision"] = new_rd
            result = run_stage(graph, "allocator", s, write_to_archive=False)
            for b, w in result["bucket_target"].weights.items():
                per_run.setdefault(b, []).append(w)
        variant_means.append({b: statistics.fmean(xs) for b, xs in per_run.items()})
        logger.info("variant %d/%d done", vi + 1, len(THESIS_VARIANTS))

    buckets = sorted({b for m in variant_means for b in m})
    print(f"\n=== Step A 입력 민감도 (thesis {len(THESIS_VARIANTS)} 변형 × {args.repeat} repeat, "
          f"as_of={args.as_of}) ===")
    print(f"{'bucket':<22}{'mean':>8}{'x-var sd':>10}{'min':>8}{'max':>8}")
    total = 0.0
    for b in buckets:
        vals = [m.get(b, 0.0) for m in variant_means]
        sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
        total += sd
        print(f"{b:<22}{statistics.fmean(vals):>8.3f}{sd:>10.3f}{min(vals):>8.3f}{max(vals):>8.3f}")
    print(f"\nΣ cross-variant stdev = {total:.4f}  (낮을수록 입력 문구에 둔감 = 기준 안정)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
