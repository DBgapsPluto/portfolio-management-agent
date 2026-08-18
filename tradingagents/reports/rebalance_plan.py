"""리밸런싱 산출물 — (rebalancing)_plan.csv + (rebalancing).json (스펙 §8)."""
import csv
import glob
import json
import logging
from dataclasses import asdict
from pathlib import Path

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.monitor.notify import send_rebalance_alert
from tradingagents.rebalance.types import RebalanceResult
from tradingagents.skills.mandate.turnover_check import compute_trade_turnover

logger = logging.getLogger(__name__)


def write_rebalance_plan(result: RebalanceResult, universe_lookup: dict, out_path: Path) -> Path:
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["티커", "ETF명", "자산군", "현재수량", "목표수량",
                    "매매구분", "거래수량", "거래금액(KRW)"])
        for tl in result.plan:
            meta = universe_lookup.get(tl.ticker, {})
            w.writerow([tl.ticker, meta.get("name", ""), meta.get("category", ""),
                        tl.current_qty, tl.target_qty, tl.action,
                        tl.delta_qty, tl.delta_amount_krw])
        f.write(f"# CASH_RESIDUAL_KRW: {result.cash_residual_krw}\n")
        f.write(f"# CASH_WEIGHT: {result.realized_weights.get('CASH', 0.0):.6f}\n")
    return out_path


def write_rebalance_json(result: RebalanceResult, out_path: Path, previous_path: str) -> Path:
    validation = result.validation
    payload = {
        "as_of_date": result.as_of,
        "tier": result.tier,
        "trigger": result.trigger,
        "current_weights": result.current_weights,
        "target_weights": result.target_weights,
        "realized_weights": result.realized_weights,
        "plan": [asdict(tl) for tl in result.plan],
        "turnover": result.turnover,
        # F3/C2: 월누적(MTD) 집계용 체결 명목 + 평가액 (MF-7). 이 필드가 없는
        # 과거 아티팩트는 compute_turnover_month_to_date 에서 자연 제외된다.
        "buy_krw": result.buy_krw,
        "sell_krw": result.sell_krw,
        "begin_value": result.begin_value,
        "end_value": result.end_value,
        "cash_residual_krw": result.cash_residual_krw,
        "skipped_no_trade": result.skipped_no_trade,
        # F3: 월누적(MTD) 배선 결과 (MF-7). run_rebalance 가 이 함수 최초 호출 이후
        # compute_turnover_month_to_date 로 채우고 다시 기록한다 — 배선 이전/실패 시
        # 기본값(0.0/False)만 남는다.
        "turnover_month_to_date": result.turnover_month_to_date,
        "projected_shortfall": result.projected_shortfall,
        "validation": (validation.model_dump() if hasattr(validation, "model_dump")
                       else validation),
        "previous_portfolio_path": previous_path,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8")
    return out_path


def compute_turnover_month_to_date(
    as_of: str, floor_pct: float, artifacts_dir: str | None = None,
) -> dict:
    """당월(연-월) 누적 회전율 (F3/C2, MF-7).

    글롭 규약: artifacts_dir/<YYYY-MM>-*/*(rebalancing).json — 일자별 디렉터리
    (YYYY-MM-DD, engine.py의 out_dir) 하위 (rebalancing).json 을 연-월 접두사로
    묶는다(engine.py 의 json_path 명명 규약 확인).

    buy_krw/sell_krw/begin_value/end_value 필드 영속화(C1-persist) 이전 아티팩트는
    이 필드들이 없어 집계에서 자연 제외된다 — MTD는 그 시점 이후부터 완전하며
    이전 달로 소급되지 않는다.
    """
    base = artifacts_dir or DEFAULT_CONFIG.get("artifacts_dir", "./artifacts")
    year_month = as_of[:7]
    pattern = str(Path(base) / f"{year_month}-*" / "*(rebalancing).json")

    buy_sum = 0.0
    sell_sum = 0.0
    begin_values: list[float] = []
    end_values: list[float] = []
    for path in sorted(glob.glob(pattern)):
        try:
            d = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("turnover MTD: %s 읽기 실패 — 집계 제외 (%s)", path, e)
            continue
        if "buy_krw" not in d or "begin_value" not in d or "end_value" not in d:
            continue   # 필드 영속화 이전 아티팩트 — 소급 불가, 자연 제외 (MF-7)
        buy_sum += d["buy_krw"]
        sell_sum += d.get("sell_krw", 0.0)
        begin_values.append(d["begin_value"])
        end_values.append(d["end_value"])

    if not begin_values:
        logger.warning("turnover MTD(%s): 관측 아티팩트 없음 — shortfall 가정", year_month)
        return {"turnover_month_to_date": 0.0, "projected_shortfall": True, "n_observed": 0}

    avg_begin = sum(begin_values) / len(begin_values)
    avg_end = sum(end_values) / len(end_values)
    mtd = compute_trade_turnover(buy_krw=buy_sum, sell_krw=sell_sum,
                                 begin_value=avg_begin, end_value=avg_end)
    projected_shortfall = mtd < floor_pct
    if projected_shortfall:
        logger.warning("turnover MTD(%s) %.4f < floor %.4f — 월간 미충족 예상",
                       year_month, mtd, floor_pct)
        send_rebalance_alert(
            tier="monthly", action="turnover_mtd_shortfall",
            summary=f"MTD turnover {mtd:.2%} < floor {floor_pct:.2%} (n={len(begin_values)})",
            top_trades=[],
        )
    return {"turnover_month_to_date": mtd, "projected_shortfall": projected_shortfall,
            "n_observed": len(begin_values)}
