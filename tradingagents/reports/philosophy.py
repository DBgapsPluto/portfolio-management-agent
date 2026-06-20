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
    # BL-native step_a (commit 9d458b9) has a different bucket schema
    # ({baseline, view_shift, final, realized, intent_vs_realized, status}) — no
    # scenario_delta/tilt_applied. Branch on method so the old anchor path is intact.
    if sa.get("method") == "bl":
        g = sa.get("global") or {}
        lines = [
            f"BL-native (status {g.get('status', '?')}, "
            f"pinned {g.get('n_pinned', '?')})",
            "| 버킷 | prior | view기여 | 의도 | 실현 | status |",
            "|------|-------|---------|------|------|--------|",
        ]
        for k in GAPS_BUCKET_KEYS:
            d = buckets.get(k)
            if not d:
                continue
            ivr = float(d.get("intent_vs_realized", 0.0) or 0.0)
            # surface repair clawback (의도→실현 gap) only when material
            clawback = f" (실현격차 {ivr * 100:+.1f}%)" if abs(ivr) >= 0.005 else ""
            lines.append(
                f"| {BUCKET_KR_NAME[k]} | {d['baseline'] * 100:.1f}% "
                f"| {d['view_shift'] * 100:+.1f}% | {d['final'] * 100:.1f}% "
                f"| {d['realized'] * 100:.1f}% | {d.get('status', 'bl')}{clawback} |"
            )
        return "\n".join(lines)
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


def format_heterogeneous_selection(attribution) -> str:
    """이종 버킷 테마뷰(sub_category_views) + 결정론 ETF 선정(heterogeneous_selection)을
    한 줄씩 사람이 읽을 수 있게 렌더. "왜 이 이종 버킷이 (예) 반도체를 골랐는가" 역추적용.

    attribution = state['allocation_attribution']. 데이터는 attribution['step_a'] 의
    'sub_category_views'(버킷→{sub_cat: pref})·'heterogeneous_selection'(버킷→trace)
    에서만 읽는다(날조 금지). het 뷰/선정이 전혀 없으면 '해당 없음'.
    """
    sa = attribution.get("step_a") if isinstance(attribution, dict) else None
    sa = sa or {}
    views = sa.get("sub_category_views") or {}
    selection = sa.get("heterogeneous_selection") or {}
    buckets = sorted(set(views) | set(selection))
    if not buckets:
        return "해당 없음"

    def _fmt_view(v: dict) -> str:
        # pref 큰 순(절대값 desc, 동률은 부호 +가 먼저)으로 'sub_cat ±0.8' 나열.
        items = sorted(
            (v or {}).items(), key=lambda kv: (-abs(kv[1]), -kv[1], kv[0])
        )
        return ", ".join(f"{sc} {pref:+.1f}" for sc, pref in items)

    lines: list[str] = []
    for bkey in buckets:
        view_str = _fmt_view(views.get(bkey) or {})
        sel = selection.get(bkey) or {}
        revert = sel.get("revert")
        picks = sel.get("selected") or []
        head = f"- {bkey}: 테마뷰 {view_str or '(없음)'}"
        if revert == "core_aum":
            # 테마 풀이 비어 core-AUM 으로 폴백 — 정직하게 명시(선정 티커는 없음).
            lines.append(f"{head} → 테마풀 공백, core-AUM 폴백")
        elif picks:
            note = " (floor 완화)" if revert == "floor_relaxed" else " (모멘텀 top-K)"
            lines.append(f"{head} → 선정 [{', '.join(picks)}]{note}")
        else:
            lines.append(f"{head} → 선정 (없음)")
    return "\n".join(lines)


def _resolve_weights(state: dict) -> dict[str, float]:
    wv = state.get("weight_vector")
    if wv is not None:
        return dict(wv.weights)
    return dict(state.get("weights") or {})


def _resolve_quadrant(state: dict) -> str:
    """현재 regime quadrant. step_a attribution(앵커·BL 공통 입력) 우선,
    없으면 macro_report.regime.quadrant. 미상이면 빈 문자열."""
    attr = state.get("allocation_attribution") or {}
    sa = attr.get("step_a") if isinstance(attr, dict) else None
    if isinstance(sa, dict):
        q = sa.get("quadrant")
        if q:
            return str(q)
    mr = state.get("macro_report")
    q = getattr(getattr(mr, "regime", None), "quadrant", None)
    return str(q) if q else ""


def _resolve_bucket_weights(state: dict) -> dict[str, float]:
    """실현된 14-버킷 비중 (상관 클러스터 비중합 계산용). 없으면 빈 dict."""
    bt = state.get("bucket_target")
    w = getattr(bt, "weights", None)
    if w:
        return {k: float(v) for k, v in w.items()}
    attr = state.get("allocation_attribution") or {}
    sa = attr.get("step_a") if isinstance(attr, dict) else None
    buckets = (sa or {}).get("buckets") if isinstance(sa, dict) else None
    if isinstance(buckets, dict):
        return {k: float(d.get("realized", d.get("final", 0.0)) or 0.0)
                for k, d in buckets.items()}
    return {}


def _resolve_bl_cov(state: dict):
    """BL 공분산 Σ (pandas.DataFrame) — 리포트 시점에 있으면 상관분석 facts 생성.
    state['bl_cov'] / allocation_attribution['bl_cov'] / ['bl']['cov'] 순으로 탐색.
    없으면 None (상관 fact 는 graceful no-op)."""
    cov = state.get("bl_cov")
    if cov is None:
        attr = state.get("allocation_attribution") or {}
        if isinstance(attr, dict):
            cov = attr.get("bl_cov")
            if cov is None:
                bl = attr.get("bl")
                if isinstance(bl, dict):
                    cov = bl.get("cov") or bl.get("Sigma")
    if cov is None:
        return None
    try:
        import pandas as pd
        if isinstance(cov, pd.DataFrame) and not cov.empty:
            return cov
    except Exception:  # noqa: BLE001
        return None
    return None


def _resolve_bl_correlation(state: dict):
    """PHIL-4: BL 시점에 영속화된 COMPACT 상관행렬(중첩 dict)을 pd.DataFrame 으로 복원.

    Σ 는 리포트 시점엔 사라지므로 allocator 가 build_bl_bucket_weights 에서
    attribution['bl']['__global__']['correlation'] 에 {a:{b:corr}} 형태로 저장한다.
    여기서 읽은 값은 '이미 상관행렬'이므로 correlation_from_cov 를 다시 호출하면 안 된다.
    버킷 순서가 행/열에서 동일하도록 reindex 해 square·symmetric 프레임을 보장한다.
    없으면 None (graceful no-op)."""
    attr = state.get("allocation_attribution") or {}
    if not isinstance(attr, dict):
        return None
    bl = attr.get("bl")
    if not isinstance(bl, dict):
        return None
    glob = bl.get("__global__")
    if not isinstance(glob, dict):
        return None
    corr = glob.get("correlation")
    if not isinstance(corr, dict) or not corr:
        return None
    try:
        import pandas as pd
        # pd.DataFrame(nested_dict) orients COLUMNS by outer keys → reindex both
        # axes to a single consistent bucket order so the frame is square & symmetric.
        order = list(corr.keys())
        df = pd.DataFrame(corr).reindex(index=order, columns=order)
        if df.empty:
            return None
        return df
    except Exception:  # noqa: BLE001
        return None


def _build_philosophy_facts(state: dict) -> str:
    """PHIL-4: '단일 리스크 통제 / AI 쏠림 통제' 판단기준을 충족시키는 결정론 facts.
    (1) prior(baseline) 정당화 — 현 regime 의 QUADRANT_BASELINE 상위 비중,
    (2) 내부 상관분석 — BL Σ→상관행렬 최고 상관쌍 + 그 클러스터 비중합.
    Σ 가 리포트 시점에 없으면 prior fact 만 surface (상관 fact graceful skip)."""
    from tradingagents.skills.portfolio.bl_facts import (
        prior_justification_facts, correlation_from_cov, bl_correlation_facts,
    )
    blocks: list[str] = []
    quadrant = _resolve_quadrant(state)
    if quadrant:
        prior = prior_justification_facts(quadrant)
        if prior:
            blocks.append(prior)
    # 상관행렬 우선순위: (1) BL 시점에 영속화된 상관행렬(이미 상관, recompute 금지),
    # (2) 폴백으로 리포트 시점에 Σ 가 남아 있으면 Σ→상관 계산.
    corr = _resolve_bl_correlation(state)
    if corr is None:
        cov = _resolve_bl_cov(state)
        if cov is not None:
            try:
                corr = correlation_from_cov(cov)
            except Exception as e:  # noqa: BLE001
                logger.warning("philosophy Σ→correlation skipped (%s)", e)
                corr = None
    if corr is not None:
        try:
            corr_block = bl_correlation_facts(
                corr, weights=_resolve_bucket_weights(state)
            )
            if corr_block:
                blocks.append(corr_block)
        except Exception as e:  # noqa: BLE001 — 상관 fact 는 부가정보, 실패해도 리포트 진행
            logger.warning("philosophy correlation facts skipped (%s)", e)
    return "\n\n".join(blocks)


def _resolve_method(state: dict) -> str:
    wv = state.get("weight_vector")
    if wv is not None:
        return wv.method.value
    return str(state.get("method") or "unknown")


def _build_facts_block(state: dict) -> str:
    """B8: deterministic, checkable mandate facts. The philosophy doc is scored at
    70% (투자철학) and the LLM is told to cite numbers only from the inputs; this
    block is the authoritative source for the headline mandate-compliance figures
    (risk %, single/cluster caps, validation) so the doc cannot fabricate them."""
    # Exclude CASH — it is not an ETF, so neither the single-ETF cap nor the
    # holding count counts it (mirrors concentration_check's CASH exemption).
    weights = {t: w for t, w in _resolve_weights(state).items() if t != "CASH"}
    lines: list[str] = [f"- 보유 종목 수: {len(weights)}"]
    if weights:
        top_t, top_w = max(weights.items(), key=lambda kv: kv[1])
        lines.append(
            f"- 최대 단일 비중: {top_t} = {top_w * 100:.1f}% "
            f"(단일 cap 20% 대비 여유 {max(0.0, 0.20 - top_w) * 100:.1f}%p)"
        )
    attr = state.get("allocation_attribution") or {}
    rp = attr.get("realized_risk_pct")
    if isinstance(rp, (int, float)) and not isinstance(rp, bool):
        lines.append(f"- 위험자산 비중: {rp * 100:.1f}% (mandate cap 70%)")
    clusters = state.get("correlation_clusters") or []
    if clusters and weights:
        def _members(c):
            m = getattr(c, "members", None)
            if m is None and isinstance(c, dict):
                m = c.get("members")
            return m or []
        sums = [sum(weights.get(m, 0.0) for m in _members(c)) for c in clusters]
        if sums:
            lines.append(
                f"- 최대 상관클러스터 비중 합: {max(sums) * 100:.1f}% (cluster cap 25%)"
            )
    val = state.get("validation_report")
    if val is not None:
        viol = getattr(val, "violations", []) or []
        hard = sum(1 for v in viol if getattr(v, "severity", None) == "hard")
        lines.append(
            f"- 의무사항 검증: {'통과' if getattr(val, 'passed', False) else '실패'} "
            f"(hard 위반 {hard}건, 총 {len(viol)}건)"
        )
    return "\n".join(lines)


_NUM_RE = re.compile(r"\d+\.?\d*")


def _extract_numbers(text: str) -> set[float]:
    out: set[float] = set()
    for tok in _NUM_RE.findall(text or ""):
        try:
            out.add(round(float(tok), 1))
        except ValueError:
            pass
    return out


def _audit_philosophy_numbers(text: str, state_summary: str) -> list[float]:
    """B8: flag numbers in the philosophy doc that do not appear (within rounding)
    in the inputs — i.e. potential fabrications. Heuristic + LOG-ONLY (never
    rejects): small integers and years are ignored to limit false positives."""
    allowed = _extract_numbers(state_summary)
    unverified: list[float] = []
    for n in _extract_numbers(text):
        if n in allowed:
            continue
        if float(n).is_integer() and (n <= 31 or 1900 <= n <= 2100):
            continue  # days / months / small counts / years — 2-digit %s (e.g. 45) ARE checked
        if any(abs(n - a) <= max(0.1, abs(a) * 0.02) for a in allowed):
            continue  # rounding / reformat tolerance
        unverified.append(n)
    return sorted(unverified)


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
        "### 검증된 의무사항 수치 (Mandate Facts — 비중·cap 관련 수치는 반드시 여기서 인용)\n"
        f"{_build_facts_block(state)}\n\n"
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
        "이종 버킷 테마뷰 + ETF 선정(왜 이 sub_category 를 골랐는가):\n"
        f"{format_heterogeneous_selection(state.get('allocation_attribution'))}\n\n"
        "### 철학 근거 facts (PHIL-4 — 단일 리스크/쏠림 통제 서술 시 반드시 여기서 인용)\n"
        f"{_build_philosophy_facts(state) or '(미산출)'}\n\n"
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
    # B8: surface numbers in the doc that are not present in the inputs (possible
    # fabrication). Log-only — never blocks generation (heuristic, false positives
    # possible), but gives the operator an audit trail for the 70%-scored doc.
    unverified = _audit_philosophy_numbers(text, state_summary)
    if unverified:
        logger.warning(
            "philosophy.md: %d number(s) not found in inputs (possible fabrication, "
            "review): %s", len(unverified),
            ", ".join(f"{u:g}" for u in unverified[:15]),
        )
    return text


def write_philosophy(state: dict, deep_llm, out_path: Path) -> Path:
    text = generate_philosophy(state, deep_llm)
    out_path.write_text(text, encoding="utf-8")
    return out_path
