"""리밸런싱 사유서 (스펙 §8.1). monthly=LLM 서술, fallback=결정론 템플릿."""
from pathlib import Path

from tradingagents.rebalance.types import RebalanceResult

_PROMPT = """당신은 자산배분 매니저입니다. 아래 리밸런싱 결과로 사유서를 한국어로 작성하세요.
포함: ① 왜 지금 리밸런싱했는가(트리거) ② 무엇을 바꿨는가(주요 매매) ③ 왜 그렇게(regime/risk 근거) ④ mandate 준수.
트리거: {trigger}
주요 매매: {trades}
turnover: {turnover:.2%}
실현 비중: {realized}
"""


def _template(result: RebalanceResult) -> str:
    lines = [f"# 리밸런싱 사유서 — {result.as_of} ({result.tier})", "",
             f"**트리거:** {result.trigger}", "",
             f"**turnover:** {result.turnover:.2%}", "",
             "## 매매 내역", "", "| 티커 | 구분 | 거래수량 | 금액 |", "|---|---|---|---|"]
    for tl in result.plan:
        lines.append(f"| {tl.ticker} | {tl.action} | {tl.delta_qty} | {tl.delta_amount_krw:,} |")
    return "\n".join(lines) + "\n"


def write_rebalance_rationale(result: RebalanceResult, out_path: Path, deep_llm=None) -> Path:
    if result.tier == "monthly" and deep_llm is not None:
        trades = "; ".join(f"{tl.ticker} {tl.action} {tl.delta_qty}" for tl in result.plan[:10])
        prompt = _PROMPT.format(trigger=result.trigger, trades=trades,
                                turnover=result.turnover, realized=result.realized_weights)
        try:
            md = deep_llm.invoke(prompt).content
        except Exception:
            md = _template(result)
    else:
        md = _template(result)
    out_path.write_text(md, encoding="utf-8")
    return out_path
