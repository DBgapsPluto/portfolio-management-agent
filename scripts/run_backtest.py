"""Backtest the full pipeline across multiple historical regimes.

Runs the E2E pipeline for each as_of date, saves artifacts, and emits a
side-by-side comparison summary (regime classification, bucket target, method,
expected vol/Sharpe, validation status).

Two modes:
- **Default (independent)**: each as_of run 은 previous_portfolio=None →
  rebalance_mode="initial" 으로 검증 (turnover floor 0.80). 5 historical regime
  spot check 에 적합 (regime 별 portfolio 비교).
- **--chained**: 각 as_of run 의 portfolio.json 을 다음 run 의 previous_portfolio
  로 전달 → rebalance_mode="monthly" (turnover floor 0.10). continuous
  rebalance 평가에 적합.

Usage:
    python scripts/run_backtest.py            # independent (default)
    python scripts/run_backtest.py --chained  # continuous rebalance
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import date
from pathlib import Path

# .env auto-load (FRED/ECOS/OPENAI/KRX 키). 다른 backtest 스크립트들과 동일 패턴.
_ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_ROOT / ".env")
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s — %(message)s",
)
logger = logging.getLogger("backtest")


REGIMES = [
    ("2022-12-15", "Hawkish Fed peak (rates 4.5%, CPI 7%+, KR rate hike)"),
    ("2023-04-14", "Post-SVB credit stress (BTFP, regional bank stress)"),
    ("2024-08-14", "Sahm rule first triggered (UR rises, false alarm?)"),  # 08-15 광복절 회피
    ("2025-04-15", "Tariff shock / Trump 25% (KR exports risk, vol spike)"),
    ("2026-05-15", "Current — already run; will skip if artifacts exist"),
]


def _safe_round(val, digits: int = 2):
    """Round but tolerate None / missing fields."""
    if val is None:
        return None
    try:
        return round(float(val), digits)
    except (TypeError, ValueError):
        return None


def run_one(as_of: str, previous_portfolio: dict | None = None) -> dict | None:
    """Run pipeline for one date. Return summary dict or None on failure.

    previous_portfolio: chained 모드 — 이전 run 의 portfolio.json 의 weights dict.
    None 이면 initial rebalance_mode (default spot check 모드).
    """
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    logger.info("=" * 70)
    logger.info(
        "RUNNING as_of=%s (rebalance_mode=%s)",
        as_of, "monthly (chained)" if previous_portfolio else "initial",
    )
    logger.info("=" * 70)

    t0 = time.time()
    try:
        graph = TradingAgentsGraph(preset_name="db_gaps")
    except Exception as e:
        logger.exception("Graph init failed: %s", e)
        return None

    try:
        result = graph.run(
            as_of_date=as_of,
            capital_krw=1_000_000_000,
            previous_portfolio=previous_portfolio,
        )
    except Exception as e:
        logger.exception("Pipeline run failed for %s: %s", as_of, e)
        return None

    elapsed = time.time() - t0

    artifact_path = result.get("final_portfolio_path")
    if not artifact_path or not Path(artifact_path).exists():
        logger.warning("Missing portfolio.json for %s", as_of)
        return None

    portfolio = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
    rd = portfolio.get("research_decision", {})
    bt = portfolio.get("bucket_target", {})
    mc = portfolio.get("method_choice", {})
    vr = portfolio.get("validation_report", {})

    pn = portfolio.get("portfolio_numerics") or {}
    # C5 (2026-05-23): 24-cell field 제거됨. factor model 의 dominant_scenario /
    # factor_scores 만 노출. archive (legacy portfolio.json) 에 24-cell field 가
    # 남아있을 경우 _safe_round / .get 으로 graceful fallback.
    return {
        "as_of": as_of,
        "elapsed_sec": _safe_round(elapsed, 1),
        "dominant_scenario": rd.get("dominant_scenario"),
        "conviction": rd.get("conviction"),
        "factor_scores": {
            k: _safe_round(v, 2) for k, v in (rd.get("factor_scores") or {}).items()
        },
        "bucket_target": {
            k: _safe_round(v, 3) if isinstance(v, (int, float)) else v
            for k, v in bt.items() if k not in ("rationale",)
        },
        "method": mc.get("method"),
        "method_reasoning": (mc.get("reasoning") or "")[:120],
        "expected_volatility_pct": _safe_round(portfolio.get("expected_volatility"), 2),
        "expected_sharpe": _safe_round(portfolio.get("expected_sharpe"), 3),
        "n_assets": pn.get("n_assets"),
        "hhi": _safe_round(pn.get("hhi"), 3),
        "max_cluster_exposure": _safe_round(pn.get("max_cluster_exposure"), 3),
        "validation_passed": vr.get("passed"),
        "rebalance_mode": portfolio.get("rebalance_mode"),
    }


def format_table(rows: list[dict]) -> str:
    """ASCII summary table."""
    if not rows:
        return "(no runs completed)"

    out = []
    out.append("=" * 100)
    out.append(" BACKTEST SUMMARY")
    out.append("=" * 100)

    def _fmt(v, spec):
        return format(v, spec) if v is not None else "—"

    for r in rows:
        out.append("")
        out.append(f"## {r['as_of']}  ({r.get('elapsed_sec', '—')}s)  {r.get('regime_label','')}")
        # C5: factor model — dominant_scenario string + factor z-scores
        out.append(
            f"  Scenario: {r.get('dominant_scenario')!s:<18} "
            f"conviction={r.get('conviction')}"
        )
        factor_scores = r.get("factor_scores") or {}
        if factor_scores:
            top = sorted(factor_scores.items(), key=lambda kv: -abs(kv[1] or 0))[:3]
            out.append(
                "  Factors:  "
                + ", ".join(f"{f}={_fmt(z, '+.2f')}" for f, z in top)
            )
        out.append(f"  Buckets:  {r['bucket_target']}")
        out.append(f"  Method:   {r['method']}  — {r['method_reasoning']}")
        out.append(
            f"  Vol:      {_fmt(r['expected_volatility_pct'], '.1f')}%  "
            f"Sharpe={_fmt(r['expected_sharpe'], '.3f')}  "
            f"n_assets={r['n_assets']}  HHI={_fmt(r['hhi'], '.3f')}  "
            f"max_cluster={_fmt(r['max_cluster_exposure'], '.1%')}"
        )
        out.append(
            f"  Status:   passed={r['validation_passed']}  mode={r['rebalance_mode']}"
        )

    out.append("")
    out.append("=" * 100)
    return "\n".join(out)


def _load_prev_portfolio(as_of: str) -> dict | None:
    """artifacts/<as_of>/portfolio.json 에서 weights 추출. 없으면 None."""
    p = Path(f"artifacts/{as_of}/portfolio.json")
    if not p.exists():
        return None
    try:
        pf = json.loads(p.read_text(encoding="utf-8"))
        weights = pf.get("weights")
        if not isinstance(weights, dict) or not weights:
            return None
        return {"weights": weights}
    except Exception as e:
        logger.warning("Failed to load prev portfolio for %s: %s", as_of, e)
        return None


def main() -> int:
    import argparse

    # Sys.path setup so module imports work without pip install -e .
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    parser = argparse.ArgumentParser(description="DB GAPS pipeline backtest.")
    parser.add_argument(
        "--chained", action="store_true",
        help=(
            "이전 run 의 portfolio.json 을 다음 run 의 previous_portfolio 로 전달 "
            "→ continuous monthly rebalance 평가 모드 (turnover floor 0.10). "
            "기본 (off) 은 independent spot check (turnover floor 0.80)."
        ),
    )
    args = parser.parse_args()

    if args.chained:
        logger.info("CHAINED mode: each as_of uses previous as_of's portfolio.json")

    rows: list[dict] = []
    prev_portfolio: dict | None = None

    for as_of, label in REGIMES:
        existing_summary = Path(f"artifacts/{as_of}/backtest_summary.json")
        if existing_summary.exists():
            logger.info("Loading cached summary for %s", as_of)
            rows.append(json.loads(existing_summary.read_text(encoding="utf-8")))
            # cached run 에서도 chained 모드면 portfolio.json 로드.
            if args.chained:
                prev_portfolio = _load_prev_portfolio(as_of) or prev_portfolio
            continue

        logger.info("Regime label: %s", label)
        summary = run_one(
            as_of,
            previous_portfolio=prev_portfolio if args.chained else None,
        )
        if summary is None:
            logger.error("Skipping %s — failed", as_of)
            continue
        summary["regime_label"] = label
        rows.append(summary)
        out_path = Path(f"artifacts/{as_of}/backtest_summary.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Wrote %s", out_path)

        # Chained 모드: 다음 run 을 위해 prev_portfolio 갱신.
        if args.chained:
            prev_portfolio = _load_prev_portfolio(as_of) or prev_portfolio

    text = format_table(rows)
    print(text)

    combined = Path(
        "artifacts/backtest_summary_chained.json" if args.chained
        else "artifacts/backtest_summary.json"
    )
    combined.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(
        "artifacts/backtest_summary_chained.txt" if args.chained
        else "artifacts/backtest_summary.txt"
    ).write_text(text, encoding="utf-8")
    logger.info("Combined summary → %s", combined)

    return 0


if __name__ == "__main__":
    sys.exit(main())
