"""결정론 다이얼(vol_haircut) 튜닝 sweep — robust forward Sharpe (spec 2026-06-04).

각 과거 날짜: runs/{date} 복원 → allocator 1회로 LLM tilt 캡처 → floor×margin grid를
cached_tilt로 재실행(LLM 무호출) → 63거래일 forward Sharpe. robust = 날짜 median(+min).
리포트만(artifacts/tuning/vol_haircut_sweep.json) — 자동 적용 안 함.
"""
from __future__ import annotations

import argparse
import itertools
import json
import logging
import math
import signal
import statistics
from datetime import date, timedelta
from pathlib import Path

# .env auto-load (FRED/ECOS/OPENAI/KRX 키). run_backtest.py 와 동일 패턴.
_ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_ROOT / ".env")
except ImportError:
    pass

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.observability.replay import restore_state, run_stage
from tradingagents.schemas.portfolio import BucketTilt
from tradingagents.backtest.forward_perf import score_forward_performance
from tradingagents.skills.portfolio.returns_matrix import fetch_returns_matrix

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("tune_dials")

DATES = ["2022-12-15", "2023-04-14", "2024-08-14", "2025-04-15"]
FLOORS = [0.5, 0.6, 0.7]
MARGINS = [0.1, 0.2, 0.3]
HORIZON = 63
STAGE = "allocator"
UNIVERSE_PATH = "data/universe.json"
CAPITAL_KRW = 1_000_000_000


def _capture_tilt(graph, d: str) -> BucketTilt:
    state, _ = restore_state(d, STAGE, UNIVERSE_PATH, CAPITAL_KRW)
    tr = state.get("technical_report")
    fp = getattr(tr, "factor_panel", None) or {}
    assert fp, f"{d}: technical_report.factor_panel 비어있음 — sweep 무의미"
    out = run_stage(graph, STAGE, state)
    tilt_dict = out["allocation_attribution"]["step_a"]["tilt"]
    return BucketTilt(tilts=tilt_dict)


class _FetchTimeout(BaseException):
    """SIGALRM 하드 타임아웃 — BaseException 상속(pykrx 내부 except Exception 이 못 삼키게)."""


def _fetch_forward(union, d_date, end, attempts: int = 3, timeout: int = 40):
    """날짜당 forward 수익 행렬 1회 fetch + SIGALRM 하드 타임아웃 + 재시도.

    pykrx/KRX 가 timeout 없이 무한 hang → SIGALRM 으로 blocking syscall 강제 중단
    (메인 스레드 전용, Unix). 모두 실패면 None(그 날짜 제외)."""
    def _handler(signum, frame):
        raise _FetchTimeout()

    for i in range(attempts):
        old = signal.signal(signal.SIGALRM, _handler)
        signal.alarm(timeout)
        try:
            rm = fetch_returns_matrix(union, d_date, end)
            if rm is not None and not rm.empty:
                return rm
            logger.warning("forward fetch 빈 결과 (try %d/%d)", i + 1, attempts)
        except _FetchTimeout:
            logger.warning("forward fetch TIMEOUT %ds (try %d/%d)", timeout, i + 1, attempts)
        except Exception as e:  # noqa: BLE001
            logger.warning("forward fetch 실패 (try %d/%d): %s", i + 1, attempts, e)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)
    return None


def _combo_weights(graph, d: str, tilt: BucketTilt, floor: float, margin: float) -> dict:
    """결정론(네트워크 X): cached_tilt + dial override 로 allocator 재실행 → 최종 weights."""
    state, _ = restore_state(d, STAGE, UNIVERSE_PATH, CAPITAL_KRW)
    state["cached_tilt"] = tilt
    state["portfolio_dials"] = {"vol_haircut_floor": floor, "vol_haircut_margin": margin}
    out = run_stage(graph, STAGE, state)
    return out["weight_vector"].weights


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", nargs="*", default=DATES)
    ap.add_argument("--floors", nargs="*", type=float, default=FLOORS)
    ap.add_argument("--margins", nargs="*", type=float, default=MARGINS)
    args = ap.parse_args()

    graph = TradingAgentsGraph(preset_name="db_gaps")

    tilts: dict[str, BucketTilt] = {}
    for d in args.dates:
        try:
            tilts[d] = _capture_tilt(graph, d)
            logger.info("tilt captured: %s", d)
        except Exception as e:  # noqa: BLE001
            logger.warning("skip %s (restore/tilt 실패): %s", d, e)

    grid = list(itertools.product(args.floors, args.margins))
    score: dict[tuple, dict[str, float]] = {g: {} for g in grid}

    # 날짜-외부 루프: 조합 weights 결정론 계산(네트워크 X) → 합집합 1회 forward fetch → 메모리 채점.
    # (조합마다 재fetch 하면 pykrx/KRX stall 노출이 36회 → 4회로 축소.)
    for d in tilts:
        d_date = date.fromisoformat(d)
        combo_w: dict[tuple, dict] = {}
        for floor, margin in grid:
            try:
                combo_w[(floor, margin)] = _combo_weights(graph, d, tilts[d], floor, margin)
            except Exception as e:  # noqa: BLE001
                logger.warning("weights 실패 %s f=%s m=%s: %s", d, floor, margin, e)
        union = sorted({t for w in combo_w.values() for t, x in w.items() if x > 0})
        end = d_date + timedelta(days=math.ceil(HORIZON * 1.6))
        logger.info("date %s: %d combos, fetching %d tickers forward (1 fetch)...",
                    d, len(combo_w), len(union))
        rm = _fetch_forward(union, d_date, end)
        logger.info("date %s: forward matrix %s", d, None if rm is None else rm.shape)
        if rm is None:
            logger.warning("date %s: forward fetch 전부 실패 → 이 날짜 제외", d)
            continue
        for (floor, margin), w in combo_w.items():
            perf = score_forward_performance(w, d_date, HORIZON, returns_matrix=rm)
            if perf.get("status") == "ok":
                score[(floor, margin)][d] = round(perf["sharpe"], 3)
            else:
                logger.warning("%s f=%s m=%s → %s (n=%s)",
                               d, floor, margin, perf.get("status"), perf.get("n_obs"))

    rows = []
    for floor, margin in grid:
        per_date = score[(floor, margin)]
        sh = list(per_date.values())
        rows.append({
            "floor": floor, "margin": margin, "per_date": per_date,
            "median": round(statistics.median(sh), 3) if sh else None,
            "min": round(min(sh), 3) if sh else None,
            "mean": round(statistics.mean(sh), 3) if sh else None,
        })

    rows.sort(key=lambda r: (r["median"] is not None, r["median"] if r["median"] is not None else -9),
              reverse=True)

    out_dir = Path("artifacts/tuning")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "vol_haircut_sweep.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== vol_haircut sweep — robust forward Sharpe (63 거래일) ===")
    print(f"{'floor':>6} {'margin':>7} {'median':>8} {'min':>8} {'mean':>8}   per-date(Sharpe)")
    for r in rows:
        base = "  <= baseline" if (r["floor"] == 0.6 and r["margin"] == 0.2) else ""
        print(f"{r['floor']:>6} {r['margin']:>7} {str(r['median']):>8} {str(r['min']):>8} "
              f"{str(r['mean']):>8}   {r['per_date']}{base}")


if __name__ == "__main__":
    main()
