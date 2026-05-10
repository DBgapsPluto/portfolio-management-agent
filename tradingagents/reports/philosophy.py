"""Investment philosophy document generator (대회 §4.1: ≥4 워드 페이지)."""
from pathlib import Path


PHILOSOPHY_PROMPT = """\
You are writing the investment philosophy document for a Korean investment competition.

Mandatory sections (each ≥600 chars in Korean):
1. 매크로 환경 진단 (Regime, yield curve, inflation, employment)
2. 시장 리스크 평가 (VIX, credit spread, single risk via correlation)
3. 자산군 비중 결정 논리 (5-bucket target with rationale)
4. 단일 리스크 통제 전략 (correlation clusters, cluster cap)
5. 시장 충격 시나리오 (3 stress scenarios with defensive responses)
6. 매매 원칙 (turnover floor, rebalance triggers)

Inputs:
{state_summary}

CRITICAL RULES (대회 §4.2):
- Korean only
- DO NOT copy ETF prospectus text or news headlines verbatim
- All numbers MUST come from the inputs above
- Total ≥4000 chars

Output the full markdown document."""


def generate_philosophy(state: dict, deep_llm) -> str:
    wv = state["weight_vector"]
    state_summary = (
        f"### Macro\n{state.get('macro_summary', '')}\n\n"
        f"### Risk\n{state.get('risk_summary', '')}\n\n"
        f"### Technical\n{state.get('technical_summary', '')}\n\n"
        f"### News\n{state.get('news_summary', '')}\n\n"
        f"### Bucket Target\n{state.get('research_debate_summary', '')}\n\n"
        f"### Final Portfolio\n"
        f"Method: {wv.method.value}\n"
        f"Top 5 weights: {sorted(wv.weights.items(), key=lambda x: -x[1])[:5]}\n"
        f"Rationale: {wv.rationale}\n"
    )
    response = deep_llm.invoke(PHILOSOPHY_PROMPT.format(state_summary=state_summary))
    text = response.content
    if len(text) < 4000:
        retry = deep_llm.invoke(
            f"The document below is only {len(text)} chars. Expand each of 6 sections to ≥600 chars (total ≥4000):\n\n{text}"
        )
        text = retry.content
    return text


def write_philosophy(state: dict, deep_llm, out_path: Path) -> Path:
    text = generate_philosophy(state, deep_llm)
    out_path.write_text(text, encoding="utf-8")
    return out_path
