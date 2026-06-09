"""Stage 2 research 클러스터 — bull → bear → manager 종합 (단일 패스)."""
from __future__ import annotations
import logging

from tradingagents.agents.researchers.bull_researcher import create_bull_researcher
from tradingagents.agents.researchers.bear_researcher import create_bear_researcher
from tradingagents.agents.utils.structured import bind_structured, invoke_structured_obj
from tradingagents.schemas.research import InvestmentThesis, ResearchThesis

logger = logging.getLogger(__name__)

_MANAGER_SYSTEM = (
    "당신은 자산배분 팀의 리서치 매니저다. 강세(bull) 리서처와 약세(bear) 리서처의 "
    "주장, 그리고 Stage 1 매크로/리스크/기술적/뉴스 분석을 모두 검토해 균형 잡힌 "
    "투자 판단을 종합한다. 한쪽으로 치우치지 말고 양측 논거의 강도를 평가해 결론을 "
    "내려라. 결과는 thesis_md(한국어 종합 판단), risk_tilt, key_risks 로 구조화하라.\n"
    "risk_tilt: regime baseline 이 정한 위험수준 '대비' 위험자산을 어느 방향·강도로 조정할지.\n"
    "  - strong_offensive: 위험자산 대폭 확대 (강세 논거 압도)\n"
    "  - offensive: 위험자산 소폭 확대\n"
    "  - neutral: regime baseline 유지 (대부분의 경우)\n"
    "  - defensive: 위험자산 소폭 축소\n"
    "  - strong_defensive: 위험자산 대폭 축소 (약세·위험 논거 압도)\n"
    "  ※ 환율·신용 등 정량 신호는 Stage 1 이 별도 처리하므로 여기서 판단하지 말 것."
)


def _manager_prompt(state, bull_view: str, bear_view: str) -> list[dict]:
    g = state.get
    body = (
        f"## Stage 1 요약\n매크로: {g('macro_summary','(없음)')}\n"
        f"리스크: {g('risk_summary','(없음)')}\n"
        f"기술적: {g('technical_summary','(없음)')}\n"
        f"뉴스: {g('news_summary','(없음)')}\n\n"
        f"## 강세(bull) 주장\n{bull_view}\n\n"
        f"## 약세(bear) 주장\n{bear_view}\n"
    )
    return [
        {"role": "system", "content": _MANAGER_SYSTEM},
        {"role": "user", "content": body},
    ]


def create_research_cluster(bull_llm, bear_llm, manager_llm):
    bull_node = create_bull_researcher(bull_llm)
    bear_node = create_bear_researcher(bear_llm)
    structured_mgr = bind_structured(manager_llm, InvestmentThesis, "ResearchManager")

    def node(state):
        # 방어적 절단 — LLM markdown thesis가 ResearchThesis 필드 한도(20000)를
        # 넘어 검증 크래시 나는 것을 방지 (실 E2E 발견).
        _MAX = 20000
        bull_view = bull_node(state).get("bull_view", "(없음)")[:_MAX]
        bear_view = bear_node(state).get("bear_view", "(없음)")[:_MAX]

        fallback = InvestmentThesis(
            thesis_md="(manager 종합 실패 — 중립 유지)", risk_tilt="neutral", key_risks=[],
        )
        thesis = invoke_structured_obj(
            structured_mgr, _manager_prompt(state, bull_view, bear_view),
            fallback, "ResearchManager",
        )

        decision = ResearchThesis(
            risk_tilt=thesis.risk_tilt,
            thesis_md=thesis.thesis_md,
            bull_view=bull_view,
            bear_view=bear_view,
            key_risks=thesis.key_risks,
        )
        summary = (
            f"## Research Thesis\n"
            f"risk_tilt: {decision.risk_tilt}\n"
            f"{decision.thesis_md[:1200]}\n"
            f"key risks: {', '.join(decision.key_risks) or '(none)'}\n"
        )[:2000]
        return {
            "research_decision": decision,
            "research_debate_summary": summary,
        }

    return node
