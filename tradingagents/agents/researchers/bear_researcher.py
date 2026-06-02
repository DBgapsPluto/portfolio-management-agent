"""Bear researcher (Stage 2) — Stage 1 분석을 약세 관점으로 해석."""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

_SYSTEM = (
    "당신은 자산배분 팀의 약세(bear) 리서처다. 주어진 매크로/리스크/기술적/뉴스 "
    "분석을 '위험자산을 줄이고 방어자산을 늘려야 하는 근거' 관점에서 해석한다. "
    "비관을 위한 비관이 아니라, 데이터에서 하방·꼬리 위험 시나리오를 뒷받침하는 "
    "신호를 찾아 논리적으로 제시한다. 상대를 반박하지 말고 너의 논거만 한국어 "
    "markdown 으로 써라."
)


def _build_prompt(state) -> list[dict]:
    g = state.get
    body = (
        f"## 매크로\n{g('macro_summary', '(없음)')}\n\n"
        f"## 리스크\n{g('risk_summary', '(없음)')}\n\n"
        f"## 기술적\n{g('technical_summary', '(없음)')}\n\n"
        f"## 뉴스\n{g('news_summary', '(없음)')}\n"
    )
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": body},
    ]


def create_bear_researcher(llm):
    def node(state):
        try:
            resp = llm.invoke(_build_prompt(state))
            view = resp.content
        except Exception as exc:
            logger.warning("bear_researcher failed: %s", exc)
            view = "(bear view 생성 실패)"
        return {"bear_view": view}
    return node
