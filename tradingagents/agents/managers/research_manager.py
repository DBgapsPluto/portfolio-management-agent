"""Research Manager (Stage 2 Phase 1).

Bull/Bear 토론 폐기 → 단일 estimator + 7개 직교 시나리오 확률 + 결정적 매핑.

흐름:
  Stage 1 summaries (macro/risk/technical/news)
    → estimator (deep_llm 1회 호출, ScenarioProbabilities 산출)
    → map_probs_to_bucket (결정적 함수, BucketTarget 산출)
    → ResearchDecision (bucket_target + scenario_probs + conviction)

mandate (위험자산 ≤ 0.70) 안전성은 SCENARIO_BUCKETS의 invariant로 자동 보장.
"""
from tradingagents.schemas.research import ResearchDecision, ScenarioProbabilities
from tradingagents.skills._helpers import invoke_with_structured_retry
from tradingagents.skills.research.scenario_definitions import SCENARIO_DEFINITIONS
from tradingagents.skills.research.scenario_mapper import map_probs_to_bucket


_SCENARIO_BLOCK = "\n".join(
    f"- {name}: {defn}" for name, defn in SCENARIO_DEFINITIONS.items()
)


ESTIMATOR_PROMPT = f"""\
당신은 자산배분 시나리오 분석가입니다. Stage 1의 4명 분석가 (macro_quant,
market_risk, technical, macro_news)가 만든 요약 4개를 받습니다.

당신의 임무는 다음 7개 직교 시나리오의 확률을 추정하는 것입니다.
어느 한 입장을 옹호하지 말고, 데이터가 가리키는 대로 추정하세요.

[Scenario 정의]
{_SCENARIO_BLOCK}

[Stage 1 요약]
=== Macro Quant ===
{{macro_summary}}

=== Market Risk ===
{{risk_summary}}

=== Technical ===
{{technical_summary}}

=== Macro News ===
{{news_summary}}

[추정 규칙]
1. 각 시나리오 확률 ∈ [0, 1], 모두 합 = 1.0 (엄격).
2. 각 확률 결정은 위 요약의 *구체 수치/regime*을 인용. 직관·내러티브만으로 X.
3. 7개 모두 0.05 이상으로 가정하지 마세요 — 일부는 0.01도 합리적.
4. reasoning (≤800자): 각 시나리오를 *지지/반대*하는 evidence 2-3개씩.
   주로 dominant 시나리오와 가장 의외인 시나리오를 자세히.

ScenarioProbabilities JSON으로 출력. 합 검증은 자동 적용됨.
"""


def create_research_manager(deep_llm):
    def node(state):
        prompt = ESTIMATOR_PROMPT.format(
            macro_summary=state.get("macro_summary", ""),
            risk_summary=state.get("risk_summary", ""),
            technical_summary=state.get("technical_summary", ""),
            news_summary=state.get("news_summary", ""),
        )
        probs: ScenarioProbabilities = invoke_with_structured_retry(
            deep_llm, ScenarioProbabilities,
            [{"role": "user", "content": prompt}],
            max_retries=1,
        )

        decision: ResearchDecision = map_probs_to_bucket(
            probs, rationale_seed=probs.reasoning[:200],
        )

        target = decision.bucket_target
        prob_lines = "\n".join(
            f"  {name:<18} {p*100:>5.1f}%"
            for name, p in sorted(
                decision.scenario_probabilities.as_dict().items(),
                key=lambda kv: -kv[1],
            )
        )
        summary = (
            f"## Research Decision\n"
            f"Dominant: {decision.dominant_scenario} "
            f"({decision.dominant_probability*100:.1f}%, "
            f"{decision.conviction} conviction)\n"
            f"Scenario probabilities:\n{prob_lines}\n"
            f"\n## Bucket Target\n"
            f"국내주식: {target.kr_equity*100:.1f}%, "
            f"해외주식: {target.global_equity*100:.1f}%, "
            f"FX/원자재: {target.fx_commodity*100:.1f}%, "
            f"채권: {target.bond*100:.1f}%, "
            f"MMF: {target.cash_mmf*100:.1f}%\n"
            f"위험자산 합: {target.risk_asset_weight*100:.1f}%\n"
            f"근거: {target.rationale[:300]}"
        )

        return {
            "bucket_target": target,
            "research_decision": decision,
            "research_debate_summary": summary,
        }

    return node
