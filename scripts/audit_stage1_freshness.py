"""Audit Stage 1 freshness — 4명 분석가 출력에서 실데이터 vs sentinel/empty 구분.

목적:
    "Stage 1이 진짜로 API를 때려서 라이브 데이터를 가져오는지, 아니면 API 오류로
    조용히 sentinel/empty fallback 으로 떨어지고 있는지"를 엄밀히 검증한다.

판정 규칙:
    - StalenessAware 스냅샷:
        staleness_days == 99   → 🚨 SENTINEL (fallback)
        staleness_days in 0..7 → ✅ LIVE
        staleness_days  > 7    → ⚠️ STALE (캐시거나 publication lag)
    - GlobalOvernightSnapshot.fetched_count < 9 → ⚠️ PARTIAL
    - NewsReport.{global_overnight, save_brief, news_sentiment, cb_speakers, release_surprise}
        가 None        → ❌ MISSING
    - NewsSentimentSnapshot.counts 합계 0 → ❌ NO_NEWS
    - SpeakerToneAggregate.{fed,bok,other}_speakers_7d 모두 0 → ❌ NO_SPEAKERS
    - ReleaseSurpriseSnapshot.today_releases + last_5d_releases 모두 빈 list → ❌ NO_RELEASES
    - DivergenceScore: us_kr_rate_gap_bps == 0 AND us_kr_inflation_gap == 0 AND score == 0
        → 🚨 SENTINEL (`macro_quant_analyst.py:208` 의 staleness=99 미설정 fallback)
    - TechnicalReport.factor_panel 비어있음 → ❌ NO_PANEL

종료 코드:
    0 — 모든 데이터 라이브
    1 — sentinel/missing 존재 (조용한 fallback 발생)
    2 — 분석가 실행 자체 실패

사용:
    python scripts/audit_stage1_freshness.py --as-of 2026-05-15 \
        [--analyst macro_quant|market_risk|technical|macro_news|all]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

# Make `tradingagents` importable when running this script directly without
# `pip install -e .` (i.e. fresh clone). Project root is one level above scripts/.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Shim: the project imports `pandas_ta` but PyPI no longer ships pandas-ta for
# Python 3.11. `pandas_ta_classic` is the maintained drop-in fork with the same
# public API. Alias before any tradingagents.skills.technical import resolves.
if "pandas_ta" not in sys.modules:
    try:
        import pandas_ta_classic as _ta_classic  # type: ignore
        sys.modules["pandas_ta"] = _ta_classic
    except ImportError:
        pass  # tradingagents.skills.technical will fail with original error

# Stub: `tradingagents.agents.__init__` eagerly imports the risk_judge, which
# pulls in pypfopt → cvxpy. cvxpy >= 1.7 requires numpy >= 2, but the rest of
# the project pins numpy < 2 for pandas binary compat. We don't use pypfopt in
# Stage 1, so stub it out so the import chain resolves.
if "pypfopt" not in sys.modules:
    import types as _types
    _stub = _types.ModuleType("pypfopt")
    # Names imported by tradingagents.agents.allocator.overlay_apply
    for _name in (
        "EfficientFrontier", "HRPOpt", "expected_returns", "risk_models",
        "EfficientCVaR", "CovarianceShrinkage", "objective_functions",
    ):
        setattr(_stub, _name, type(_name, (), {}))
    sys.modules["pypfopt"] = _stub
    for _sub in (
        "pypfopt.efficient_frontier", "pypfopt.hierarchical_portfolio",
        "pypfopt.expected_returns", "pypfopt.risk_models",
        "pypfopt.objective_functions",
    ):
        sys.modules[_sub] = _types.ModuleType(_sub)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("audit_stage1")

# --- Constants used by classifier ---
SENTINEL_STALENESS = 99
STALE_THRESHOLD = 7

OK = "[OK]   LIVE      "
PARTIAL = "[WARN] PARTIAL   "
STALE = "[WARN] STALE     "
SENTINEL = "[BAD]  SENTINEL  "
MISSING = "[BAD]  MISSING   "
NO_DATA = "[BAD]  NO_DATA   "


@dataclass
class Finding:
    """단일 (분석가, 필드) 점검 결과."""
    analyst: str
    field_name: str
    verdict: str           # OK / PARTIAL / STALE / SENTINEL / MISSING / NO_DATA
    detail: str = ""

    @property
    def is_real(self) -> bool:
        return self.verdict == OK


@dataclass
class AuditReport:
    findings: list[Finding] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    timings_sec: dict[str, float] = field(default_factory=dict)

    def add(self, *args, **kwargs) -> None:
        self.findings.append(Finding(*args, **kwargs))

    def by_analyst(self, name: str) -> list[Finding]:
        return [f for f in self.findings if f.analyst == name]

    def counts(self) -> dict[str, int]:
        c: dict[str, int] = {}
        for f in self.findings:
            c[f.verdict] = c.get(f.verdict, 0) + 1
        return c


# =========================================================================
# Classifier helpers — each snapshot family gets one
# =========================================================================


def _stale_verdict(staleness_days: int | None) -> str:
    if staleness_days is None:
        return MISSING
    if staleness_days == SENTINEL_STALENESS:
        return SENTINEL
    if staleness_days > STALE_THRESHOLD:
        return STALE
    return OK


def _check_stalenessaware(snap, label: str) -> tuple[str, str]:
    """Return (verdict, detail) for any StalenessAware snapshot."""
    if snap is None:
        return MISSING, f"{label}: snapshot is None"
    sd = getattr(snap, "staleness_days", None)
    src = getattr(snap, "source_date", None)
    return _stale_verdict(sd), f"staleness_days={sd}, source_date={src}"


# =========================================================================
# Per-analyst auditors
# =========================================================================


def audit_macro(report, out: AuditReport) -> None:
    """MacroReport — 모든 StalenessAware 서브필드를 점검."""
    A = "macro_quant"
    # Fields that are always present (non-Optional) StalenessAware subfields:
    targets = [
        "yield_curve", "inflation", "employment", "kr_divergence", "regime",
        "kr_export", "kr_leading", "kr_business_survey",
        "us_leading", "gdp_nowcast",
        "financial_conditions", "inflation_expectations", "fed_path",
        "fx", "risk_appetite", "china_leading", "foreign_flow",
        "policy_uncertainty", "tail_risk",
    ]
    for name in targets:
        snap = getattr(report, name, None)
        verdict, detail = _check_stalenessaware(snap, name)
        # DivergenceScore: Bug-A fix 후로는 staleness_days=99 가 정상적으로 박혀
        # 일반 _check_stalenessaware 가 처리. 이전 silent fallback heuristic 은
        # legacy data 대응을 위해 보존 (재실행 시 cache hit으로 staleness=0+0/0/0
        # 일 가능성).
        if name == "kr_divergence" and snap is not None and verdict == OK:
            if (
                snap.score == 0
                and snap.us_kr_rate_gap_bps == 0
                and snap.us_kr_inflation_gap == 0
            ):
                verdict = SENTINEL
                detail = (
                    "score=0, us_kr_rate_gap_bps=0, us_kr_inflation_gap=0 — "
                    "silent fallback heuristic (Bug-A 이전 cache hit 가능성)"
                )
        out.add(A, name, verdict, detail)

    # Calendar events (not StalenessAware): just count
    ev = getattr(report, "upcoming_events", []) or []
    verdict = OK if len(ev) > 0 else NO_DATA
    out.add(
        A, "upcoming_events", verdict,
        f"central-bank calendar count={len(ev)}",
    )


def audit_risk(report, out: AuditReport) -> None:
    """RiskReport — 모든 StalenessAware + correlation_concentration sentinel."""
    A = "market_risk"
    targets = [
        "vix", "vkospi", "credit_spread_us_ig", "credit_spread_us_hy",
        "fear_greed", "breadth_kr", "breadth_us",
        "correlation_concentration", "systemic_score",
        "vix_term", "skew", "vxn",
        "real_yields", "funding_stress", "credit_quality",
        "kr_yield_curve", "kr_corp_spread", "kr_margin_debt", "kr_market_tier",
        "equity_bond_corr",
    ]
    for name in targets:
        snap = getattr(report, name, None)
        verdict, detail = _check_stalenessaware(snap, name)
        # PCA(correlation_concentration)는 synthetic fallback도 staleness=99 박음 (이미 OK)
        # fear_greed sentinel: staleness=99 + current_value=50 + label='neutral'
        if name == "fear_greed" and verdict == OK and snap is not None:
            if snap.current_value == 50 and snap.label == "neutral":
                # 잠재적 sentinel지만 staleness=99 가 아니므로 그냥 알림
                detail += " (note: value=50/neutral — scrape OK or sentinel?)"
        out.add(A, name, verdict, detail)


def audit_technical(report, out: AuditReport) -> None:
    """TechnicalReport — factor_panel 사이즈, extended_indicators, 클러스터."""
    A = "technical"
    panel = getattr(report, "factor_panel", {}) or {}
    n_panel = len(panel)
    if n_panel == 0:
        out.add(A, "factor_panel", NO_DATA, "factor_panel is empty (pykrx fetch 실패 추정)")
    elif n_panel < 50:
        out.add(A, "factor_panel", PARTIAL, f"factor_panel count={n_panel} (정상은 188 근접)")
    else:
        out.add(A, "factor_panel", OK, f"factor_panel count={n_panel}")

    ext = getattr(report, "extended_indicators", {}) or {}
    if not ext:
        out.add(A, "extended_indicators", NO_DATA, "extended_indicators empty")
    else:
        out.add(A, "extended_indicators", OK, f"count={len(ext)}")

    trend_q = getattr(report, "trend_quantification", {}) or {}
    if not trend_q:
        out.add(A, "trend_quantification", NO_DATA, "trend_quantification empty")
    else:
        out.add(A, "trend_quantification", OK, f"count={len(trend_q)}")

    risk_adj = getattr(report, "risk_adjusted", {}) or {}
    if not risk_adj:
        out.add(A, "risk_adjusted", NO_DATA, "risk_adjusted empty")
    else:
        out.add(A, "risk_adjusted", OK, f"count={len(risk_adj)}")

    # asset_class_momentum / clusters는 fetch 의존 — 비어있다면 가격 fetch 실패
    acm = getattr(report, "asset_class_momentum", {}) or {}
    total_ranked = sum(len(v) for v in acm.values())
    if total_ranked == 0:
        out.add(A, "asset_class_momentum", NO_DATA, "no momentum rankings")
    else:
        out.add(
            A, "asset_class_momentum", OK,
            f"categories={len(acm)}, total ranks={total_ranked}",
        )

    clusters = getattr(report, "correlation_clusters", []) or []
    if not clusters:
        out.add(A, "correlation_clusters", PARTIAL, "no clusters (단일 자산만일 수 있음)")
    else:
        out.add(A, "correlation_clusters", OK, f"clusters count={len(clusters)}")

    breadth = getattr(report, "universe_breadth", None)
    if breadth is None:
        out.add(A, "universe_breadth", MISSING, "snapshot is None")
    else:
        out.add(A, "universe_breadth", OK, "snapshot present")

    sector = getattr(report, "sector_rotation", None)
    if sector is None:
        out.add(A, "sector_rotation", MISSING, "snapshot is None")
    else:
        out.add(A, "sector_rotation", OK, "snapshot present")


def audit_news(report, out: AuditReport) -> None:
    """NewsReport — Tier 1~5 snapshot 존재 + 내부 카운트."""
    A = "macro_news"

    # upcoming_events (calendar) — fetch_event_calendar_skill
    ev = getattr(report, "upcoming_events", []) or []
    if not ev:
        out.add(A, "upcoming_events", NO_DATA, "event calendar fetch 0건")
    else:
        out.add(A, "upcoming_events", OK, f"count={len(ev)}")

    # ranked_news — news_fetcher RSS
    rn = getattr(report, "ranked_news", []) or []
    if not rn:
        out.add(A, "ranked_news", NO_DATA, "RSS news fetch 0건")
    else:
        out.add(A, "ranked_news", OK, f"count={len(rn)}")

    # Tier-1 global_overnight
    overnight = getattr(report, "global_overnight", None)
    if overnight is None:
        out.add(A, "global_overnight (Tier-1)", MISSING, "yfinance 9종 전체 실패")
    else:
        n = overnight.fetched_count
        verdict = OK if n == 9 else (PARTIAL if n > 0 else NO_DATA)
        out.add(
            A, "global_overnight (Tier-1)", verdict,
            f"fetched={n}/9 regime={overnight.risk_regime_overnight}",
        )

    # Tier-2 release_surprise
    rs = getattr(report, "release_surprise", None)
    if rs is None:
        out.add(A, "release_surprise (Tier-2)", MISSING, "snapshot is None")
    else:
        n_today = len(rs.today_releases)
        n_5d = len(rs.last_5d_releases)
        if n_today == 0 and n_5d == 0:
            out.add(
                A, "release_surprise (Tier-2)", NO_DATA,
                "today=0 + last_5d=0 — SAVE에서도 발표 추출 못함",
            )
        else:
            out.add(
                A, "release_surprise (Tier-2)", OK,
                f"today={n_today}, last_5d={n_5d}, bias={rs.bias_30d}",
            )

    # Tier-3 news_sentiment
    ns = getattr(report, "news_sentiment", None)
    if ns is None:
        out.add(A, "news_sentiment (Tier-3)", MISSING, "snapshot is None")
    else:
        total = sum(ns.counts.values()) if ns.counts else 0
        if total == 0:
            out.add(A, "news_sentiment (Tier-3)", NO_DATA, "카테고리별 count 모두 0")
        else:
            out.add(
                A, "news_sentiment (Tier-3)", OK,
                f"items={total}, dominant={ns.dominant_category}, "
                f"rising={ns.rising_category}",
            )

    # Tier-4 cb_speakers
    cb = getattr(report, "cb_speakers", None)
    if cb is None:
        out.add(A, "cb_speakers (Tier-4)", MISSING, "snapshot is None")
    else:
        n = len(cb.fed_speakers_7d) + len(cb.bok_speakers_7d) + len(cb.other_speakers_7d)
        if n == 0:
            out.add(
                A, "cb_speakers (Tier-4)", NO_DATA,
                "Fed/BOK/other 모두 0 — speaker 매칭 실패 또는 LLM tone 실패",
            )
        else:
            out.add(
                A, "cb_speakers (Tier-4)", OK,
                f"fed={len(cb.fed_speakers_7d)}, bok={len(cb.bok_speakers_7d)}, "
                f"other={len(cb.other_speakers_7d)}",
            )

    # Tier-5 save_brief
    sb = getattr(report, "save_brief", None)
    if sb is None:
        out.add(
            A, "save_brief (Tier-5)", MISSING,
            "data/SAVE/YYYY-MM-DD.* 파일 없음 또는 파싱 실패",
        )
    else:
        out.add(
            A, "save_brief (Tier-5)", OK,
            f"file={sb.source_file}, pages={sb.pages_parsed}/{sb.pages_total}, "
            f"releases={len(sb.economic_releases)}, "
            f"news_cards={len(sb.news_cards)}, "
            f"schedule={len(sb.weekly_schedule)}",
        )


# =========================================================================
# Runner
# =========================================================================


def _build_state(as_of: str, universe_path: str, capital: int = 1_000_000_000) -> dict:
    """Stage 1 분석가들이 요구하는 최소 상태."""
    from tradingagents.agents.utils.agent_states import _create_empty_state
    return _create_empty_state(
        as_of_date=as_of,
        universe_path=universe_path,
        capital_krw=capital,
        preset_name="db_gaps",
    )


def _make_llms(config: dict):
    from tradingagents.llm_clients import create_llm_client
    deep = create_llm_client(
        provider=config["llm_provider"], model=config["deep_think_llm"],
    ).get_llm()
    quick = create_llm_client(
        provider=config["llm_provider"], model=config["quick_think_llm"],
    ).get_llm()
    return quick, deep


def _run_node(name: str, factory_fn, state, out: AuditReport, *factory_args) -> Any:
    """factory_fn(quick, deep, ...) → node 함수를 만들어 실행하고 결과 반환."""
    logger.info("Running analyst: %s", name)
    t0 = time.time()
    try:
        node = factory_fn(*factory_args)
        delta = node(state)
        out.timings_sec[name] = time.time() - t0
        return delta
    except Exception as e:
        out.timings_sec[name] = time.time() - t0
        msg = f"{name} raised: {type(e).__name__}: {e}"
        out.errors.append(msg)
        logger.exception("Analyst %s failed: %s", name, e)
        return None


def run_audit(as_of: str, analyst_filter: str = "all") -> AuditReport:
    from tradingagents.agents.analysts.macro_news_analyst import (
        create_macro_news_analyst,
    )
    from tradingagents.agents.analysts.macro_quant_analyst import (
        create_macro_quant_analyst,
    )
    from tradingagents.agents.analysts.market_risk_analyst import (
        create_market_risk_analyst,
    )
    from tradingagents.agents.analysts.technical_analyst import (
        create_technical_analyst,
    )
    from tradingagents.default_config import DEFAULT_CONFIG

    out = AuditReport()

    quick, deep = _make_llms(DEFAULT_CONFIG)
    state = _build_state(as_of, universe_path=DEFAULT_CONFIG["universe_path"])
    cache_path = DEFAULT_CONFIG.get("etf_price_cache_path")

    run = {
        "macro_quant": (
            create_macro_quant_analyst,
            (quick, deep),
            "macro_report",
            audit_macro,
        ),
        "market_risk": (
            create_market_risk_analyst,
            (quick, deep),
            "risk_report",
            audit_risk,
        ),
        "technical": (
            create_technical_analyst,
            (quick, deep, cache_path),
            "technical_report",
            audit_technical,
        ),
        "macro_news": (
            create_macro_news_analyst,
            (quick, deep),
            "news_report",
            audit_news,
        ),
    }
    if analyst_filter != "all":
        run = {analyst_filter: run[analyst_filter]}

    for name, (factory, args, report_key, auditor) in run.items():
        delta = _run_node(name, factory, state, out, *args)
        if delta is None:
            continue
        report = delta.get(report_key)
        if report is None:
            out.errors.append(f"{name}: missing report key {report_key} in delta")
            continue
        auditor(report, out)

    return out


# =========================================================================
# Output formatting
# =========================================================================


def print_report(out: AuditReport) -> None:
    print()
    print("=" * 88)
    print(" STAGE 1 FRESHNESS AUDIT")
    print("=" * 88)

    # Timings
    print("\n--- Timings ---")
    for name, t in out.timings_sec.items():
        print(f"  {name:14s}  {t:6.1f} s")

    # Errors
    if out.errors:
        print("\n--- Execution errors ---")
        for e in out.errors:
            print(f"  ERR  {e}")

    # Findings grouped by analyst
    for analyst in ("macro_quant", "market_risk", "technical", "macro_news"):
        fs = out.by_analyst(analyst)
        if not fs:
            continue
        print(f"\n--- {analyst} ({len(fs)} fields) ---")
        for f in fs:
            print(f"  {f.verdict} {f.field_name:32s}  {f.detail}")

    # Summary
    counts = out.counts()
    print("\n--- Summary ---")
    total = sum(counts.values())
    for k in (OK, PARTIAL, STALE, SENTINEL, MISSING, NO_DATA):
        n = counts.get(k, 0)
        if n:
            pct = n / total * 100 if total else 0
            print(f"  {k} {n:3d}  ({pct:4.1f}%)")
    print(f"  Total fields checked: {total}")
    bad = counts.get(SENTINEL, 0) + counts.get(MISSING, 0) + counts.get(NO_DATA, 0)
    if out.errors and not out.findings:
        print("\n  >> ANALYST CRASHED before report could be built — see errors above.")
    elif out.errors and out.findings:
        print(f"\n  >> {bad} bad fields + {len(out.errors)} analyst execution errors.")
    elif bad:
        print(f"\n  >> {bad} fields are sentinel / missing / no-data.")
    else:
        print("\n  >> All fields are live data.")
    print("=" * 88)


def dump_json(out: AuditReport, path: Path) -> None:
    payload = {
        "timings_sec": out.timings_sec,
        "errors": out.errors,
        "findings": [
            {
                "analyst": f.analyst, "field": f.field_name,
                "verdict": f.verdict.strip(), "detail": f.detail,
            }
            for f in out.findings
        ],
        "summary": out.counts(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("JSON report → %s", path)


# =========================================================================
# Main
# =========================================================================


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", default="2026-05-15", help="YYYY-MM-DD")
    parser.add_argument(
        "--analyst", default="all",
        choices=("all", "macro_quant", "market_risk", "technical", "macro_news"),
    )
    parser.add_argument(
        "--json-out", default=None,
        help="Optional path to dump JSON report.",
    )
    args = parser.parse_args()

    try:
        date.fromisoformat(args.as_of)
    except ValueError:
        logger.error("Invalid --as-of: %s", args.as_of)
        return 2

    try:
        out = run_audit(args.as_of, args.analyst)
    except Exception as e:
        logger.exception("Audit failed at top level: %s", e)
        traceback.print_exc()
        return 2

    print_report(out)
    if args.json_out:
        dump_json(out, Path(args.json_out))

    counts = out.counts()
    bad = counts.get(SENTINEL, 0) + counts.get(MISSING, 0) + counts.get(NO_DATA, 0)
    # 분석가 실행 자체가 실패한 경우(에러는 있는데 finding이 없을 수도)는 빨간불.
    if out.errors and not out.findings:
        return 2
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
