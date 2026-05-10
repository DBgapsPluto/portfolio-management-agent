"""Monthly operations report (대회 §4.2: ≥A4 2 pages)."""
from pathlib import Path

import pandas as pd


MONTHLY_PROMPT = """\
You are writing the monthly operations report for {month}월 of the Korean investment competition.

Mandatory 3 sections (each ≥500 chars in Korean):
1. **수익률 자체 평가** — 월 수익률이 왜 이렇게 나왔는가? Cite specific events and asset moves.
2. **포트폴리오 변경 사유** — 시장 상황 변화에 따라 비중을 어떻게 조정했는지 logical reasoning.
3. **향후 시장 전망 및 전략** — 다음 월의 매크로 환경 예측 + 선제 대응 전략.

Inputs:
{state_summary}

Performance data:
{pnl_summary}

CRITICAL RULES:
- Korean only, ≥A4 2 pages (~2500 chars total)
- DO NOT copy ETF prospectus or news verbatim
- Self-evaluation must be honest about underperformance

Output full markdown."""


def generate_monthly(state: dict, pnl_csv: Path, month: int, deep_llm) -> str:
    pnl = pd.read_csv(pnl_csv)
    pnl_summary = (
        f"Starting equity: {pnl['equity'].iloc[0]:,.0f} KRW\n"
        f"Ending equity:   {pnl['equity'].iloc[-1]:,.0f} KRW\n"
        f"Return:          {(pnl['equity'].iloc[-1] / pnl['equity'].iloc[0] - 1):+.2%}\n"
        f"Best day:        {pnl['equity'].pct_change().max():+.2%}\n"
        f"Worst day:       {pnl['equity'].pct_change().min():+.2%}\n"
    )
    state_summary = (
        f"Macro: {state.get('macro_summary', '')}\n"
        f"Risk: {state.get('risk_summary', '')}\n"
    )
    response = deep_llm.invoke(MONTHLY_PROMPT.format(
        month=month, state_summary=state_summary, pnl_summary=pnl_summary,
    ))
    return response.content


def write_monthly(state: dict, pnl_csv: Path, month: int, deep_llm, out_path: Path) -> Path:
    text = generate_monthly(state, pnl_csv, month, deep_llm)
    out_path.write_text(text, encoding="utf-8")
    return out_path
