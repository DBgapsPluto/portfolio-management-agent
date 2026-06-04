"""Investment philosophy document generator (대회 §4.1: ≥4 워드 페이지).

Stage 6 정리: prompt에 Stage 2 시나리오 + Stage 4 lens / numerics + Stage 5
mandate 정보를 섹션별 명시 매핑으로 주입. LLM 호출 수는 유지 (1-2회).
출력 형식: 국내 WM '이달의 투자가이드' 스타일, asterisk 마크다운 금지.
"""
import logging
import re
from pathlib import Path

from tradingagents.reports.execution_trace import (
    _aggregate_wm_5bucket,
    render_execution_trace,
    render_failure_philosophy_stub,
    render_pipeline_narrative,
)
from tradingagents.skills.research.factor_to_bucket import BUCKETS

logger = logging.getLogger(__name__)


PHILOSOPHY_PROMPT = """\
You are writing a Korean asset-allocation strategy report for the DB GAPS investment competition.
Write in the style of a domestic WM monthly guide (e.g. 하나더넥스트 '이달의 투자가이드'):
professional analyst tone, summary bullets, attraction tables (★), and portfolio weight tables.

The document title and ## 의사결정 경로 section are inserted by the system — do NOT output them.
Start directly with ## 투자가이드 요약.

Use this document structure (fill every section; Korean only):

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
Use the dual-column table from inputs (목표=feasible contract, 제출=final allocator weights).
Do not invent percentages; if columns differ, explain pipeline path (Stage 3 sync/HRP, Stage 4 clip, Stage 5 fallback).
| 자산군 | 목표(feasible) | 제출(final) | 위험/안전 |
|--------|----------------|-------------|-----------|
| (rows from WM dual table in inputs) | | | |
| 위험자산 합계 | (feasible risk sum) | (final risk sum) | 위험 |

## 1. 매크로 환경 진단
(≥600 chars — Stage 1 macro_quant: regime, yield curve, inflation, employment)

## 2. 시장 리스크 평가
(≥600 chars — Stage 1 market_risk + Stage 4 portfolio_numerics: VIX, credit spread, CVaR, HHI)

## 3. 자산군 비중 결정 논리
(≥600 chars — Stage 2 scenario/factor view + 5-bucket target rationale)

## 4. 단일 리스크 통제 전략
(≥600 chars — Stage 4 concentration lens + Stage 5 cluster cap 0.25)

## 5. 시장 충격 시나리오
(≥600 chars — conservative scenarios + Stage 4 tail_risk lens)

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
- Narrative must align with ## 의사결정 경로 (already in inputs); do not claim 70% mandate if final risk differs without explaining validator/fallback

Output the full document body (no title line)."""


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
    """ResearchDecision factor scores → 정렬된 한 줄 요약."""
    if rd is None:
        return "(none)"
    factor_scores = getattr(rd, "factor_scores", None) or {}
    if isinstance(rd, dict):
        factor_scores = rd.get("factor_scores") or {}
    dominant = getattr(rd, "dominant_scenario", None) or (
        rd.get("dominant_scenario") if isinstance(rd, dict) else None
    ) or "?"
    if not factor_scores:
        return f"dominant={dominant} (no factor scores)"
    sorted_z = sorted(factor_scores.items(), key=lambda kv: -abs(kv[1]))[:5]
    z_str = ", ".join(f"{name} {z:+.2f}" for name, z in sorted_z)
    return f"dominant={dominant}; top factors: {z_str}"


def _format_overlay(overlay) -> str:
    """RiskOverlay → 짧은 요약."""
    if overlay is None:
        return "(none — Stage 4 not run or empty)"
    if overlay.is_empty():
        return f"(empty — {overlay.severity_decision})"
    lens_summary = "; ".join(
        f"{lc.lens}={lc.level}" for lc in overlay.lens_concerns
    ) if overlay.lens_concerns else "(no lens concerns)"
    return (
        f"strength={overlay.strength_applied:.2f}, "
        f"multiplier={overlay.risk_asset_multiplier:.2f}, "
        f"ceilings={len(overlay.weight_ceilings)}, "
        f"floors={len(overlay.tail_hedge_floor)} | {lens_summary}"
    )


def _format_numerics(n) -> str:
    if n is None:
        return "(not computed)"
    return (
        f"HHI={n.hhi:.3f}, top1={n.top1_weight*100:.1f}%, "
        f"top3_sum={n.top3_weight_sum*100:.1f}%, "
        f"max_cluster={n.max_cluster_exposure*100:.1f}%, "
        f"CVaR_95={n.cvar_95_1d*100:.2f}%, vol_60d={n.realized_vol_60d*100:.2f}%"
    )


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


def _feasible_8bucket(state: dict) -> dict[str, float]:
    rd = state.get("research_decision")
    ac = getattr(rd, "allocation_contract", None) if rd is not None else None
    if ac is not None:
        return {b: float(ac.feasible_weights.get(b, 0.0)) for b in BUCKETS}
    bucket = state.get("bucket_target")
    if bucket is None:
        return {}
    if hasattr(bucket, "weights"):
        return dict(bucket.weights)
    return dict(bucket.get("weights") or {})


def _final_8bucket(state: dict) -> dict[str, float]:
    attr = state.get("allocation_attribution") or {}
    align = attr.get("implementation_alignment") or {}
    realized = align.get("realized_bucket_weights")
    if realized:
        return dict(realized)
    wv = state.get("weight_vector")
    if wv is None:
        return {}
    from tradingagents.skills.portfolio.contract_stage3 import realized_bucket_weights

    cs = state.get("candidate_set")
    b2t = getattr(cs, "bucket_to_tickers", None) if cs is not None else None
    if b2t:
        return realized_bucket_weights(dict(wv.weights), b2t)
    return {}


def format_wm_dual_portfolio_table(state: dict) -> str:
    """WM 5-bucket: 목표(feasible) vs 제출(final)."""
    feas = _aggregate_wm_5bucket(_feasible_8bucket(state))
    final = _aggregate_wm_5bucket(_final_8bucket(state))
    if not feas and not final:
        return "(no bucket weights)"
    rows = [
        "| 자산군 | 목표(feasible) | 제출(final) |",
        "|--------|----------------|-------------|",
    ]
    labels = {
        "kr_equity": "국내주식",
        "global_equity": "해외주식",
        "fx_commodity": "FX/원자재",
        "bond": "채권",
        "cash_mmf": "MMF",
    }
    risk_keys = ("kr_equity", "global_equity", "fx_commodity")
    for key, label in labels.items():
        rows.append(
            f"| {label} | {feas.get(key, 0) * 100:.1f}% | {final.get(key, 0) * 100:.1f}% |"
        )
    rows.append(
        f"| 위험자산 합계 | "
        f"{sum(feas.get(k, 0) for k in risk_keys) * 100:.1f}% | "
        f"{sum(final.get(k, 0) for k in risk_keys) * 100:.1f}% |"
    )
    return "\n".join(rows)


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
    overlay = state.get("risk_overlay")
    numerics = state.get("portfolio_numerics")
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

    return (
        f"as_of_date: {state.get('as_of_date', 'unknown')}\n\n"
        "### Stage 1 — Analyst Summaries\n"
        f"#### Macro\n{state.get('macro_summary', '')}\n\n"
        f"#### Risk\n{state.get('risk_summary', '')}\n\n"
        f"#### Technical\n{state.get('technical_summary', '')}\n\n"
        f"#### News\n{state.get('news_summary', '')}\n\n"
        "### Stage 2 — Research Decision\n"
        f"{state.get('research_debate_summary', '')}\n"
        f"Scenario / factors: {_format_scenario_probs(rd)}\n"
        f"5-bucket target (executed): {_format_bucket_target(bucket)}\n"
        f"WM dual portfolio table:\n{format_wm_dual_portfolio_table(state)}\n\n"
        "### Stage 3 — Method choice\n"
        f"Selected: {_resolve_method(state)}\n"
        f"Reasoning: {method_reasoning}\n\n"
        "### Stage 4 — Risk Overlay\n"
        f"Overlay: {_format_overlay(overlay)}\n"
        f"Portfolio numerics: {_format_numerics(numerics)}\n\n"
        "### Stage 5 — Mandate Validation\n"
        f"{_format_validation(validation)}\n"
        f"Rebalance mode: {rebalance_mode}\n\n"
        "### Final Portfolio\n"
        f"Method: {_resolve_method(state)}\n"
        f"Top 5 weights: "
        f"{sorted(weights.items(), key=lambda x: -x[1])[:5]}\n"
        f"Rationale: {rationale}\n"
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
    as_of_date = state.get("as_of_date", "unknown")
    header = (
        f"# DB GAPS 자산배분 전략 리포트\n"
        f"작성일: {as_of_date} | 리서치: DB GAPS Asset Allocation\n\n"
    )
    path = render_pipeline_narrative(state)
    body = generate_philosophy(state, deep_llm)
    trace = render_execution_trace(state)
    text = f"{header}{path}\n\n{body.rstrip()}\n\n{trace}\n"
    out_path.write_text(text, encoding="utf-8")
    return out_path


def write_failure_philosophy(state: dict, error_message: str, out_path: Path) -> Path:
    """Deterministic philosophy.md when contract/sync aborts (Philo fail)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = render_failure_philosophy_stub(state, error_message)
    out_path.write_text(text, encoding="utf-8")
    return out_path


def write_failure_philosophy_for_state(
    state: dict,
    error_message: str,
    *,
    artifacts_dir: str | None = None,
) -> str | None:
    """Best-effort failure doc under artifacts/{as_of}/philosophy.md."""
    as_of = state.get("as_of_date", "unknown")
    base = artifacts_dir
    if base is None:
        cfg = state.get("config")
        if isinstance(cfg, dict):
            base = cfg.get("artifacts_dir")
    if not base:
        return None
    out_path = Path(base) / str(as_of) / "philosophy.md"
    write_failure_philosophy(state, error_message, out_path)
    return str(out_path)
