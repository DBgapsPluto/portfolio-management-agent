"""Investment philosophy document generator (대회 §4.1: ≥4 워드 페이지).

Stage 6 정리: prompt에 Stage 2 시나리오 + Stage 5 mandate 정보를 섹션별
명시 매핑으로 주입. LLM 호출 수는 유지 (1-2회).
출력 형식: 국내 WM '이달의 투자가이드' 스타일, asterisk 마크다운 금지.
"""
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


PHILOSOPHY_PROMPT = """\
You are writing a Korean asset-allocation strategy report for the DB GAPS investment competition.
Write in the style of a domestic WM monthly guide (e.g. 하나더넥스트 '이달의 투자가이드'):
professional analyst tone, summary bullets, attraction tables (★), and portfolio weight tables.

Use this document structure (fill every section; Korean only):

# DB GAPS 자산배분 전략 리포트
작성일: {as_of_date} | 리서치: DB GAPS Asset Allocation

---

## 투자가이드 요약
- 3~5 bullet points with concrete numbers from inputs (regime, risk assets %, top holdings)

## 자산군별 투자매력도
| 자산군 | 단기(~3M) | Key idea (긍정 vs 부정) |
|--------|----------|-------------------------|
| 국내주식 | ★~★★★ | ... |
| 해외주식 | ★~★★★ | ... |
| FX/원자재 | ★~★★★ | ... |
| 채권 | ★~★★★ | ... |
| MMF | ★~★★★ | ... |

## 제안 포트폴리오 비중
| 자산군 | 목표 비중 | 위험/안전 |
|--------|-----------|-----------|
| (5-bucket rows from inputs) | | |
| 위험자산 합계 | (sum) | 위험 |

## 1. 매크로 환경 진단
(≥600 chars — Stage 1 macro_quant: regime, yield curve, inflation, employment)

## 2. 시장 리스크 평가
(≥600 chars — Stage 1 market_risk: VIX, credit spread, systemic risk)

## 3. 자산군 비중 결정 논리
(≥600 chars — Stage 2 scenario/factor view + 5-bucket target rationale + FX(환) 노출 포지션과 그 의도(원화 약세 수혜 / 위기 시 달러 강세 방어) 설명)

## 4. 단일 리스크 통제 전략
(≥600 chars — Stage 5 concentration check + cluster cap 0.25)

## 5. 시장 충격 시나리오
(≥600 chars — conservative scenarios + Stage 1 conditional stress signals)

## 6. 매매 원칙
(≥600 chars — Stage 5 rebalance_mode + turnover floor)

---
※ 본 자료는 DB GAPS 투자대회 제출용이며, 투자 판단의 최종 책임은 운용자에게 있습니다.

Inputs:
{state_summary}

CRITICAL RULES (대회 §4.1 / §4.2):
- Korean only
- Total ≥4000 chars; sections 1~6 each ≥600 chars
- All numbers MUST come from the inputs above
- DO NOT copy ETF prospectus text or news headlines verbatim
- DO NOT use asterisk characters anywhere in the output (no *, no **, no bold/italic markdown)
- Use hyphen (-) for bullet lists, not asterisks
- Section headers may use ## but never wrap text in asterisks for emphasis
- Attraction table may use ★ characters only

Output the full document."""


RETRY_PROMPT = """\
The document below is only {length} chars. Expand sections 1~6 to ≥600 chars each (total ≥4000).
Keep the same WM report structure (투자가이드 요약, 자산군별 투자매력도 표, 제안 포트폴리오 비중 표, sections 1~6).
Do NOT use asterisk characters anywhere (no *, no **). Use plain text or hyphen bullets only.

Document:

{text}"""


def _strip_markdown_asterisks(text: str) -> str:
    """Remove LLM bold/italic asterisk markup from philosophy output."""
    cleaned = text
    prev = None
    while prev != cleaned:
        prev = cleaned
        cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"\1", cleaned)
    cleaned = re.sub(r"^(\s*)\* +", r"\1- ", cleaned, flags=re.MULTILINE)
    return cleaned.replace("*", "")


def _format_scenario_probs(rd) -> str:
    """Stage 2 risk_tilt 한 줄 요약."""
    if rd is None:
        return "(none)"
    rt = getattr(rd, "risk_tilt", None) or (
        rd.get("risk_tilt") if isinstance(rd, dict) else None
    ) or "neutral"
    return f"risk_tilt={rt}"


def _format_validation(report) -> str:
    if report is None:
        return "(not validated)"
    n_hard = sum(1 for v in report.violations if v.severity == "hard")
    n_soft = sum(1 for v in report.violations if v.severity == "soft")
    return (
        f"passed={report.passed}, hard_violations={n_hard}, soft={n_soft}"
    )


def _bucket_field(bucket, field: str, default: float = 0.0) -> float:
    if bucket is None:
        return default
    if isinstance(bucket, dict):
        return float(bucket.get(field, default) or default)
    return float(getattr(bucket, field, default) or default)


def _format_bucket_target(bucket) -> str:
    if bucket is None:
        return "(none)"
    kr = _bucket_field(bucket, "kr_equity")
    gl = _bucket_field(bucket, "global_equity")
    fx = _bucket_field(bucket, "fx_commodity")
    bond = _bucket_field(bucket, "bond")
    cash = _bucket_field(bucket, "cash_mmf")
    risk = kr + gl + fx
    rationale = ""
    if isinstance(bucket, dict):
        rationale = bucket.get("rationale", "") or ""
    else:
        rationale = getattr(bucket, "rationale", "") or ""
    return (
        f"kr_equity={kr*100:.1f}%, global_equity={gl*100:.1f}%, "
        f"fx_commodity={fx*100:.1f}%, bond={bond*100:.1f}%, "
        f"cash_mmf={cash*100:.1f}%, risk_assets={risk*100:.1f}%\n"
        f"Rationale: {rationale}"
    )


def format_bucket_target_14(bucket_target) -> str:
    """14-bucket 비중을 한글명과 함께 markdown 으로 (0 비중 생략)."""
    from tradingagents.skills.portfolio.gaps_buckets import (
        GAPS_BUCKET_KEYS, BUCKET_KR_NAME,
    )
    weights = getattr(bucket_target, "weights", {}) or {}
    lines = []
    for k in GAPS_BUCKET_KEYS:
        w = weights.get(k, 0.0)
        if w > 1e-6:
            lines.append(f"- {BUCKET_KR_NAME[k]}: {w*100:.1f}%")
    return "\n".join(lines) or "(빈 배분)"


def format_step_a_decomposition(attribution) -> str:
    """Step A 버킷 비중 분해(앵커→시나리오→판단→최종)를 markdown 표로.

    attribution = state['allocation_attribution']; step_a 가 없으면 '(미산출)'.
    """
    from tradingagents.skills.portfolio.gaps_buckets import (
        GAPS_BUCKET_KEYS, BUCKET_KR_NAME,
    )
    sa = attribution.get("step_a") if isinstance(attribution, dict) else None
    buckets = (sa or {}).get("buckets") or {}
    if not buckets:
        return "(미산출)"
    lines = [
        f"Regime {sa.get('quadrant', '?')} / risk_tilt {sa.get('risk_tilt', '?')} "
        f"(conf {float(sa.get('confidence', 0)) * 100:.0f}%, "
        f"fx {sa.get('fx_regime', '?')} / credit {sa.get('credit_regime', '?')})",
        "| 버킷 | 앵커 | 시나리오 | 판단(tilt) | 최종 |",
        "|------|------|----------|-----------|------|",
    ]
    for k in GAPS_BUCKET_KEYS:
        d = buckets.get(k)
        if not d:
            continue
        lines.append(
            f"| {BUCKET_KR_NAME[k]} | {d['baseline'] * 100:.1f}% "
            f"| {d['scenario_delta'] * 100:+.1f}% | {d['tilt_applied'] * 100:+.1f}% "
            f"| {d['final'] * 100:.1f}% |"
        )
    lines.append(f"판단 근거: {sa.get('tilt_rationale') or '(없음)'}")
    return "\n".join(lines)


def _resolve_weights(state: dict) -> dict[str, float]:
    wv = state.get("weight_vector")
    if wv is not None:
        return dict(wv.weights)
    return dict(state.get("weights") or {})


def _resolve_method(state: dict) -> str:
    wv = state.get("weight_vector")
    if wv is not None:
        return wv.method.value
    return str(state.get("method") or "unknown")


def _build_state_summary(state: dict) -> str:
    """philosophy prompt에 들어가는 풍부한 state 요약."""
    wv = state.get("weight_vector")
    rd = state.get("research_decision")
    validation = state.get("validation_report")
    rebalance_mode = state.get("rebalance_mode", "unknown")
    method_choice = state.get("method_choice")
    bucket = state.get("bucket_target")
    weights = _resolve_weights(state)

    method_reasoning = ""
    if method_choice is not None:
        if isinstance(method_choice, dict):
            method_reasoning = method_choice.get("reasoning", "")
        else:
            method_reasoning = getattr(method_choice, "reasoning", "")

    rationale = ""
    if wv is not None:
        rationale = wv.rationale
    else:
        rationale = state.get("rationale", "")

    fx = state.get("fx_exposure") or {}
    fx_str = (
        ", ".join(f"{c} {v*100:.1f}%"
                  for c, v in sorted(fx.items(), key=lambda kv: -kv[1]))
        if fx else "(미산출)"
    )

    return (
        f"as_of_date: {state.get('as_of_date', 'unknown')}\n\n"
        "### Stage 1 — Analyst Summaries\n"
        f"#### Macro\n{state.get('macro_summary', '')}\n\n"
        f"#### Risk\n{state.get('risk_summary', '')}\n\n"
        f"#### Technical\n{state.get('technical_summary', '')}\n\n"
        f"#### News\n{state.get('news_summary', '')}\n\n"
        "### Stage 2 — Research Decision\n"
        f"{state.get('research_debate_summary', '')}\n"
        f"Risk tilt: {_format_scenario_probs(rd)}\n"
        f"버킷 배분(14): {format_bucket_target_14(bucket)}\n\n"
        "### Stage 3 — Method choice\n"
        f"Selected: {_resolve_method(state)}\n"
        f"Reasoning: {method_reasoning}\n"
        "버킷 tilt 분해(Step A — 앵커→시나리오→판단→최종):\n"
        f"{format_step_a_decomposition(state.get('allocation_attribution'))}\n\n"
        "### Stage 5 — Mandate Validation\n"
        f"{_format_validation(validation)}\n"
        f"Rebalance mode: {rebalance_mode}\n\n"
        "### Final Portfolio\n"
        f"Method: {_resolve_method(state)}\n"
        f"Top 5 weights: "
        f"{sorted(weights.items(), key=lambda x: -x[1])[:5]}\n"
        f"Rationale: {rationale}\n\n"
        "### FX(환) 노출 (통화별)\n"
        f"{fx_str}\n"
    )


def generate_philosophy(state: dict, deep_llm) -> str:
    state_summary = _build_state_summary(state)
    as_of_date = state.get("as_of_date", "unknown")
    response = deep_llm.invoke(
        PHILOSOPHY_PROMPT.format(
            state_summary=state_summary,
            as_of_date=as_of_date,
        )
    )
    text = _strip_markdown_asterisks(response.content)
    if len(text) < 4000:
        retry = deep_llm.invoke(
            RETRY_PROMPT.format(length=len(text), text=text)
        )
        text = _strip_markdown_asterisks(retry.content)
    if len(text) < 4000:
        logger.warning(
            "philosophy.md only %d chars after retry — manual review required",
            len(text),
        )
    return text


def write_philosophy(state: dict, deep_llm, out_path: Path) -> Path:
    text = generate_philosophy(state, deep_llm)
    out_path.write_text(text, encoding="utf-8")
    return out_path
