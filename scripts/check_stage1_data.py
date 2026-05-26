"""Stage 1 데이터 health check — 모든 외부 API 가 정상 동작하는지 확인.

Backtest 진행 전 sanity check. 각 external fetcher 를 실제로 한 번씩 호출해서
(a) 환경변수, (b) 네트워크, (c) API 키 유효성, (d) series 응답 모두 확인.

Usage:
    uv run python scripts/check_stage1_data.py
    uv run python scripts/check_stage1_data.py --as-of 2024-08-14  # 과거 시점

산출: (1) 콘솔 표 (success / fail per fetcher), (2) artifacts/stage1_health.json.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

# .env auto-load (FRED_API_KEY 등). 다른 backtest 스크립트들과 동일 패턴.
_ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_ROOT / ".env")
except ImportError:
    pass  # dotenv 미설치 — 환경변수는 외부에서 export 가정.

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s — %(message)s")
# 노이즈 줄이기 — 우리 결과 출력만.
logging.getLogger("tradingagents").setLevel(logging.ERROR)


# ──────────────────────────────────────────────────────────────────────────
# Probe 정의 — (source, name, callable). callable 은 (value, info) tuple 반환.
# ──────────────────────────────────────────────────────────────────────────

def _check_env() -> dict[str, dict]:
    """Required env vars 점검."""
    out = {}
    for var in ["FRED_API_KEY", "ECOS_API_KEY", "OPENAI_API_KEY"]:
        v = os.environ.get(var)
        out[var] = {
            "set": bool(v),
            "value_preview": (v[:6] + "…" if v else None),
        }
    # KRX (pykrx 일부 endpoint 만 사용)
    for var in ["KRX_ID", "KRX_PW"]:
        v = os.environ.get(var)
        out[var] = {"set": bool(v), "value_preview": None}
    return out


def _check_fred(as_of: date) -> list[dict]:
    """FRED 대표 series 6 개 (cycle / inflation / employment / vol / valuation)."""
    from tradingagents.dataflows.fred import FRED_SERIES, fetch_fred_series

    sample_keys = [
        "us_10y", "us_2y", "us_cpi", "us_cfnai", "us_nfci", "us_5y5y_breakeven",
        "vix_close", "us_tips_10y", "us_ig_oas",
    ]
    start = as_of - timedelta(days=120)
    out = []
    for key in sample_keys:
        try:
            series = fetch_fred_series(
                key, start, as_of, as_of_date=as_of,
            )
            if series is None or (hasattr(series, "empty") and series.empty):
                out.append({"source": "FRED", "name": key, "status": "EMPTY",
                            "value": None, "fred_id": FRED_SERIES.get(key)})
                continue
            last_val = float(series.dropna().iloc[-1])
            last_date = series.dropna().index[-1]
            out.append({
                "source": "FRED", "name": key, "status": "OK",
                "value": round(last_val, 4),
                "last_date": str(last_date)[:10],
                "fred_id": FRED_SERIES.get(key),
            })
        except Exception as e:
            out.append({
                "source": "FRED", "name": key, "status": "ERROR",
                "error": f"{type(e).__name__}: {str(e)[:100]}",
                "fred_id": FRED_SERIES.get(key),
            })
    return out


def _check_ecos(as_of: date) -> list[dict]:
    """ECOS 대표 series 7 개. Series 별 정확한 frequency 사용 (M / D)."""
    from tradingagents.dataflows.ecos import ECOS_STAT_CODES, fetch_ecos_series

    # series → freq 매핑 (Stage 1 코드에서 실제 사용하는 freq 와 일치).
    # 817Y002 (시장금리) 는 daily, 나머지는 monthly.
    SAMPLE_KEYS_BY_FREQ = [
        ("kr_base_rate", "M"),
        ("kr_cpi", "M"),
        ("kr_export", "M"),
        ("kr_cli", "M"),
        ("kr_bsi_mfg", "M"),
        ("kr_treasury_3y", "D"),
        ("kr_corp_aa_3y", "D"),
    ]
    out = []
    for key, freq in SAMPLE_KEYS_BY_FREQ:
        start = as_of - timedelta(days=60 if freq == "D" else 365)
        try:
            series = fetch_ecos_series(
                key, start, as_of, freq=freq, as_of_date=as_of,
            )
            if series is None or (hasattr(series, "empty") and series.empty):
                out.append({
                    "source": "ECOS", "name": key, "status": "EMPTY",
                    "freq": freq, "stat_code": str(ECOS_STAT_CODES.get(key)),
                })
                continue
            last_val = float(series.dropna().iloc[-1])
            last_date = series.dropna().index[-1]
            out.append({
                "source": "ECOS", "name": key, "status": "OK",
                "value": round(last_val, 4),
                "last_date": str(last_date)[:10],
                "freq": freq,
                "stat_code": str(ECOS_STAT_CODES.get(key)),
            })
        except Exception as e:
            out.append({
                "source": "ECOS", "name": key, "status": "ERROR",
                "error": f"{type(e).__name__}: {str(e)[:100]}",
                "freq": freq,
                "stat_code": str(ECOS_STAT_CODES.get(key, "")),
            })
    return out


def _check_yfinance(as_of: date) -> list[dict]:
    """yfinance 대표 ticker 8 개 (VIX/SKEW/MOVE/VVIX + SPY/KOSPI200 + Cu/Au)."""
    from tradingagents.dataflows.equity_indices import (
        EQUITY_INDEX_TICKERS, fetch_equity_index_close,
    )
    from tradingagents.dataflows.commodities import (
        COMMODITY_TICKERS, fetch_commodity_close,
    )

    start = as_of - timedelta(days=120)
    out = []

    eq_samples = ["skew", "vvix", "move", "kospi200", "spy", "usdcnh"]
    for name in eq_samples:
        try:
            series = fetch_equity_index_close(name, start, as_of)
            if series is None or (hasattr(series, "empty") and series.empty):
                out.append({"source": "yfinance/eq", "name": name, "status": "EMPTY",
                            "ticker": EQUITY_INDEX_TICKERS.get(name)})
                continue
            last_val = float(series.dropna().iloc[-1])
            out.append({
                "source": "yfinance/eq", "name": name, "status": "OK",
                "value": round(last_val, 4),
                "last_date": str(series.dropna().index[-1])[:10],
                "ticker": EQUITY_INDEX_TICKERS.get(name),
            })
        except Exception as e:
            out.append({"source": "yfinance/eq", "name": name, "status": "ERROR",
                        "error": f"{type(e).__name__}: {str(e)[:100]}",
                        "ticker": EQUITY_INDEX_TICKERS.get(name)})

    for name in ["copper", "gold"]:
        try:
            series = fetch_commodity_close(name, start, as_of)
            if series is None or (hasattr(series, "empty") and series.empty):
                out.append({"source": "yfinance/cm", "name": name, "status": "EMPTY",
                            "ticker": COMMODITY_TICKERS.get(name)})
                continue
            last_val = float(series.dropna().iloc[-1])
            out.append({
                "source": "yfinance/cm", "name": name, "status": "OK",
                "value": round(last_val, 4),
                "last_date": str(series.dropna().index[-1])[:10],
                "ticker": COMMODITY_TICKERS.get(name),
            })
        except Exception as e:
            out.append({"source": "yfinance/cm", "name": name, "status": "ERROR",
                        "error": f"{type(e).__name__}: {str(e)[:100]}",
                        "ticker": COMMODITY_TICKERS.get(name)})

    return out


def _check_pykrx(as_of: date) -> list[dict]:
    """pykrx: ETF price batch + foreign flow + market index + ETF snapshot."""
    from tradingagents.dataflows.pykrx_data import (
        fetch_etf_ohlcv_batch, fetch_foreign_flow, fetch_market_index,
        fetch_etf_snapshot_by_date,
    )

    out = []
    start = as_of - timedelta(days=30)

    # 1. ETF OHLCV batch (KODEX 200, KODEX 코스닥150 sample)
    try:
        # pykrx 는 fetch_etf_ohlcv_batch — ETF prefix=A 없음 (6자리)
        df = fetch_etf_ohlcv_batch(["069500", "229200"], start, as_of)
        n_rows = len(df) if df is not None else 0
        out.append({
            "source": "pykrx", "name": "etf_ohlcv_batch",
            "status": "OK" if n_rows > 0 else "EMPTY",
            "rows": n_rows,
        })
    except Exception as e:
        out.append({"source": "pykrx", "name": "etf_ohlcv_batch", "status": "ERROR",
                    "error": f"{type(e).__name__}: {str(e)[:100]}"})

    # 2. 외국인 KOSPI 순매수
    try:
        ser = fetch_foreign_flow(start, as_of, market="KOSPI")
        n = len(ser) if ser is not None else 0
        out.append({
            "source": "pykrx", "name": "foreign_flow_KOSPI",
            "status": "OK" if n > 0 else "EMPTY",
            "rows": n,
            "last_value": float(ser.dropna().iloc[-1]) if n > 0 else None,
        })
    except Exception as e:
        out.append({"source": "pykrx", "name": "foreign_flow_KOSPI", "status": "ERROR",
                    "error": f"{type(e).__name__}: {str(e)[:100]}"})

    # 3. KOSPI / KOSDAQ index — cache bypass (health check 는 live API 확인).
    try:
        df_kospi = fetch_market_index("1001", start, as_of, use_cache=False)
        n = len(df_kospi) if df_kospi is not None else 0
        out.append({
            "source": "pykrx", "name": "kospi_index",
            "status": "OK" if n > 0 else "EMPTY",
            "rows": n,
            "last_value": (
                float(df_kospi.dropna().iloc[-1]) if n > 0 else None
            ),
        })
    except Exception as e:
        out.append({"source": "pykrx", "name": "kospi_index", "status": "ERROR",
                    "error": f"{type(e).__name__}: {str(e)[:100]}"})

    # 4. ETF snapshot (Stage 6 trade_plan.csv current_prices 용)
    try:
        snap = fetch_etf_snapshot_by_date(as_of)
        n = len(snap) if snap is not None else 0
        out.append({
            "source": "pykrx", "name": "etf_snapshot",
            "status": "OK" if n > 0 else "EMPTY",
            "rows": n,
        })
    except Exception as e:
        out.append({"source": "pykrx", "name": "etf_snapshot", "status": "ERROR",
                    "error": f"{type(e).__name__}: {str(e)[:100]}"})

    return out


def _check_news_event(as_of: date) -> list[dict]:
    """News + event calendar (Stage 1 macro_news 의 fetcher 만)."""
    out = []
    try:
        from tradingagents.skills.news.event_calendar import (
            fetch_event_calendar_skill,
        )
        events = fetch_event_calendar_skill(as_of, days=90)
        n = len(events) if events else 0
        out.append({
            "source": "events", "name": "cb_calendar",
            "status": "OK" if n > 0 else "EMPTY", "rows": n,
        })
    except Exception as e:
        out.append({"source": "events", "name": "cb_calendar", "status": "ERROR",
                    "error": f"{type(e).__name__}: {str(e)[:100]}"})
    return out


def _check_external_fetchers(as_of: date) -> list[dict]:
    """Stage 2 의 external_fetchers (krw_usd, sp_pe)."""
    from tradingagents.skills.research.external_fetchers import (
        fetch_krw_usd_level, fetch_sp_trailing_pe, reset_cache,
    )

    reset_cache()
    out = []
    try:
        v = fetch_krw_usd_level()
        out.append({
            "source": "external", "name": "krw_usd_level",
            "status": "OK" if v is not None else "EMPTY",
            "value": v,
        })
    except Exception as e:
        out.append({"source": "external", "name": "krw_usd_level", "status": "ERROR",
                    "error": f"{type(e).__name__}: {str(e)[:100]}"})

    try:
        v = fetch_sp_trailing_pe()
        out.append({
            "source": "external", "name": "sp_trailing_pe",
            "status": "OK" if v is not None else "EMPTY",
            "value": v,
        })
    except Exception as e:
        out.append({"source": "external", "name": "sp_trailing_pe", "status": "ERROR",
                    "error": f"{type(e).__name__}: {str(e)[:100]}"})
    return out


# ──────────────────────────────────────────────────────────────────────────
# Report rendering
# ──────────────────────────────────────────────────────────────────────────

def _emoji(status: str) -> str:
    return {"OK": "✓", "EMPTY": "⊘", "ERROR": "✗"}.get(status, "?")


def _print_table(results: list[dict]) -> tuple[int, int, int]:
    n_ok = sum(1 for r in results if r["status"] == "OK")
    n_empty = sum(1 for r in results if r["status"] == "EMPTY")
    n_err = sum(1 for r in results if r["status"] == "ERROR")

    print(
        f"{'src':<13} {'name':<25} {'st':<3} {'value/info':<40} {'note':<30}"
    )
    print("-" * 115)
    for r in sorted(results, key=lambda x: (x["source"], x["name"])):
        src = r["source"]
        name = r["name"]
        st = _emoji(r["status"])
        if r["status"] == "OK":
            if "value" in r:
                info = (
                    f"{r['value']} ({r.get('last_date', '-')})"
                    if r.get("value") is not None else "-"
                )
            elif "rows" in r:
                info = f"{r['rows']} rows"
            else:
                info = "(ok)"
            note = ""
        elif r["status"] == "EMPTY":
            info = "(empty)"
            note = r.get("fred_id") or r.get("stat_code") or r.get("ticker") or ""
        else:
            info = r.get("error", "?")[:38]
            note = r.get("fred_id") or r.get("stat_code") or r.get("ticker") or ""
        print(f"{src:<13} {name:<25} {st:<3} {str(info)[:38]:<40} {str(note)[:30]:<30}")
    print()
    print(f"Summary: {n_ok} OK, {n_empty} EMPTY, {n_err} ERROR (total {len(results)})")
    return n_ok, n_empty, n_err


def _print_env(env: dict) -> None:
    print("\n── Environment ──")
    for var, info in env.items():
        mark = "✓" if info["set"] else "✗"
        preview = f"({info['value_preview']})" if info.get("value_preview") else ""
        print(f"  {mark} {var:<20} {preview}")
    print()


# ──────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stage 1 데이터 health check (backtest 전 sanity)."
    )
    parser.add_argument(
        "--as-of", type=str, default=str(date.today()),
        help="기준일 (YYYY-MM-DD). 기본 오늘.",
    )
    parser.add_argument(
        "--output", type=str, default="artifacts/stage1_health.json",
        help="결과 JSON 산출 경로.",
    )
    args = parser.parse_args()

    as_of = date.fromisoformat(args.as_of)
    print(f"\n===== Stage 1 데이터 Health Check (as_of={as_of}) =====")

    # Sys path 설정 — 다른 entry point 처럼 동작.
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    env = _check_env()
    _print_env(env)

    # 진단 실행 — env var 없으면 그 그룹 skip.
    all_results: list[dict] = []

    if env.get("FRED_API_KEY", {}).get("set"):
        print("── FRED ──")
        fred_results = _check_fred(as_of)
        _print_table(fred_results)
        all_results.extend(fred_results)
    else:
        print("── FRED ── SKIPPED (FRED_API_KEY 없음)\n")

    if env.get("ECOS_API_KEY", {}).get("set"):
        print("── ECOS ──")
        ecos_results = _check_ecos(as_of)
        _print_table(ecos_results)
        all_results.extend(ecos_results)
    else:
        print("── ECOS ── SKIPPED (ECOS_API_KEY 없음)\n")

    print("── yfinance ──")
    yf_results = _check_yfinance(as_of)
    _print_table(yf_results)
    all_results.extend(yf_results)

    print("── pykrx ──")
    pk_results = _check_pykrx(as_of)
    _print_table(pk_results)
    all_results.extend(pk_results)

    print("── External fetchers (Stage 2 fallback) ──")
    ext_results = _check_external_fetchers(as_of)
    _print_table(ext_results)
    all_results.extend(ext_results)

    print("── News / Events ──")
    news_results = _check_news_event(as_of)
    _print_table(news_results)
    all_results.extend(news_results)

    # ── Final summary ──
    n_ok = sum(1 for r in all_results if r["status"] == "OK")
    n_empty = sum(1 for r in all_results if r["status"] == "EMPTY")
    n_err = sum(1 for r in all_results if r["status"] == "ERROR")
    total = len(all_results)
    fail_ratio = (n_empty + n_err) / total if total else 0.0

    print("\n" + "=" * 60)
    print(f"OVERALL: {n_ok}/{total} OK, {n_empty} EMPTY, {n_err} ERROR")
    print(f"Fail ratio: {fail_ratio:.0%}")
    if fail_ratio < 0.1:
        print("Status: ✓ READY FOR BACKTEST")
    elif fail_ratio < 0.3:
        print("Status: ⚠ DEGRADED — sentinel_ratio_gate (#2) 가 일부 발동 가능")
    else:
        print("Status: ✗ NOT READY — backtest 결과 신뢰도 낮음")
    print("=" * 60)

    # JSON 산출
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "as_of": str(as_of),
                "env": env,
                "results": all_results,
                "summary": {
                    "ok": n_ok, "empty": n_empty, "error": n_err,
                    "total": total, "fail_ratio": round(fail_ratio, 3),
                },
            },
            indent=2, ensure_ascii=False, default=str,
        ),
        encoding="utf-8",
    )
    print(f"\nDetails → {out_path}")

    return 0 if fail_ratio < 0.3 else 1


if __name__ == "__main__":
    sys.exit(main())
