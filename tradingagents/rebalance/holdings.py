"""직전 산출물에서 현재 보유 수량·현금 로딩 (스펙 §7.1).

우선순위: 직전 (rebalancing)_plan.csv 의 '목표수량'(리밸 후 보유) > trade_plan.csv 의 '수량(주)'.
현금은 (rebalancing)_plan.csv 의 '# CASH_RESIDUAL_KRW:' 주석 라인에서.
"""
import csv
import glob
from pathlib import Path


def _read_cash(path: Path) -> int:
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("# CASH_RESIDUAL_KRW:"):
            return int(line.split(":", 1)[1].strip())
    return 0


def load_prev_holdings(prev_dir: Path) -> tuple[dict[str, int], int]:
    """Return (ticker→qty, cash_krw). 빈 dict 가능(파일 없음)."""
    rebal = sorted(glob.glob(str(prev_dir / "*(rebalancing)_plan.csv")))
    if rebal:
        path = Path(rebal[-1])
        qty: dict[str, int] = {}
        with path.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                t = (row.get("티커") or "").strip()
                if not t or t.startswith("#"):
                    continue
                qty[t] = int(float(row.get("목표수량") or 0))
        return {t: q for t, q in qty.items() if q > 0}, _read_cash(path)

    tp = prev_dir / "trade_plan.csv"
    if tp.exists():
        qty = {}
        with tp.open(encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                t = (row.get("티커") or "").strip()
                if not t or t.startswith("#"):
                    continue
                qty[t] = int(float(row.get("수량(주)") or 0))
        return {t: q for t, q in qty.items() if q > 0}, 0

    return {}, 0
