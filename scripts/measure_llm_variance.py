"""LLM stochasticity 측정 — OBSOLETE (C5 2026-05-23).

원래 목적: research_debate 의 LLM call (ScenarioProbabilities24) 반복 호출하여
dominant_cycle / cell / cycle_marginal 분산 측정.

C5 (2026-05-23) 에서 Stage 2 가 factor model (deterministic, LLM 호출 0회) 으로
전환되어 본 script 의 측정 대상 (LLM stochasticity) 이 사라짐. ScenarioProbabilities24
schema + dominant_cell/cycle field 모두 제거됨.

향후 factor variance 가 필요하면 별도 script 작성 권장.
"""
import sys


def main() -> int:
    print(
        "[OBSOLETE] measure_llm_variance.py 는 24-cell LLM stochasticity 측정용. "
        "C5 (2026-05-23) 에서 Stage 2 가 deterministic factor model 로 전환되어 "
        "본 측정 대상이 사라짐. "
        "Factor variance 가 필요하면 별도 script 작성 권장."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
