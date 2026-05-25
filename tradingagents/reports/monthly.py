"""Monthly operations report (대회 §4.2: ≥A4 2 pages)."""
from datetime import date
from pathlib import Path

import pandas as pd

from tradingagents.monitor.turnover import TurnoverStatus, compute_turnover


# 대회 초기 자본 (presets/db_gaps.yaml). state에 capital_krw 없을 때 fallback.
_DEFAULT_CAPITAL_KRW = 1_000_000_000

MONTHLY_PROMPT = """\
You are writing the monthly operations report for {month}월 of the Korean investment competition.

Mandatory 3 sections (each ≥500 chars in Korean):
1. **수익률 자체 평가** — 월 수익률이 왜 이렇게 나왔는가? Cite specific events and asset moves.
   회전율(turnover)이 제공된 경우 §3.2 (월별 10% 이상) 충족 여부를 수치와 함께 평가.
2. **포트폴리오 변경 사유** — 시장 상황 변화에 따라 비중을 어떻게 조정했는지 logical reasoning.
3. **향후 시장 전망 및 전략** — 다음 월의 매크로 환경 예측 + 선제 대응 전략.

Inputs:
{state_summary}

Performance data:
{pnl_summary}

Turnover (대회 §3):
{turnover_summary}

CRITICAL RULES:
- Korean only, ≥A4 2 pages (~2500 chars total)
- DO NOT copy ETF prospectus or news verbatim
- Self-evaluation must be honest about underperformance
- 회전율 수치가 제공되면 §1에 반드시 명시하고 §3.2 floor (10%) 충족/미달을 평가

Output full markdown."""


def _format_turnover_summary(
    status: TurnoverStatus | None, month: int,
) -> str:
    """Render TurnoverStatus for the prompt. None → '(not provided)'."""
    if status is None:
        return "(not provided — caller가 transactions_csv를 넘기지 않음)"

    lines: list[str] = []
    month_pct = status.monthly_pcts.get(month)
    if month_pct is not None:
        floor = 0.10
        verdict = "충족" if month_pct >= floor else "미달"
        lines.append(
            f"{month}월 누적 회전율: {month_pct:.2%} "
            f"(룰북 §3.2 floor 10% — {verdict})"
        )
    else:
        lines.append(f"{month}월 누적 회전율: (해당 월 거래 데이터 없음)")

    lines.append(
        f"초기 세팅 회전율 (6/1-6/8): {status.initial_pct:.2%} "
        f"(룰북 §3.1 floor 80%)"
    )

    if status.warnings:
        lines.append("Warnings:")
        for w in status.warnings:
            lines.append(f"  - {w}")

    return "\n".join(lines)


def generate_monthly(
    state: dict,
    pnl_csv: Path,
    month: int,
    deep_llm,
    transactions_csv: Path | None = None,
) -> str:
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

    turnover_status: TurnoverStatus | None = None
    if transactions_csv is not None:
        capital_krw = int(state.get("capital_krw") or _DEFAULT_CAPITAL_KRW)
        as_of_raw = state.get("as_of_date")
        as_of = (
            date.fromisoformat(as_of_raw)
            if isinstance(as_of_raw, str) else date.today()
        )
        turnover_status = compute_turnover(
            Path(transactions_csv), capital_krw, as_of,
        )
    turnover_summary = _format_turnover_summary(turnover_status, month)

    response = deep_llm.invoke(MONTHLY_PROMPT.format(
        month=month,
        state_summary=state_summary,
        pnl_summary=pnl_summary,
        turnover_summary=turnover_summary,
    ))
    return response.content


def write_monthly(
    state: dict,
    pnl_csv: Path,
    month: int,
    deep_llm,
    out_path: Path,
    transactions_csv: Path | None = None,
) -> Path:
    text = generate_monthly(
        state, pnl_csv, month, deep_llm,
        transactions_csv=transactions_csv,
    )
    out_path.write_text(text, encoding="utf-8")
    return out_path
