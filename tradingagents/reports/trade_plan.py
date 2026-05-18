"""Trade plan CSV — MTS 입력 포맷.

qty=0 발생 시 (current_prices fetch 실패) CSV 마지막에 명시 경고 라인 추가 +
caller가 활용할 수 있도록 zero_qty_tickers 반환.
"""
import csv
from pathlib import Path


def write_trade_plan(
    weights: dict[str, float],
    capital_krw: int,
    universe_lookup: dict,
    current_prices: dict[str, float],
    out_path: Path,
) -> tuple[Path, list[str]]:
    """Generate MTS-input CSV with: ticker, name, category, weight, amount, qty.

    Returns (out_path, zero_qty_tickers). zero_qty_tickers가 비어있지 않으면
    current_prices fetch 실패한 ticker들 — caller가 state["warnings"]에 기록.
    """
    zero_qty: list[str] = []

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["티커", "ETF명", "자산군", "가중치", "매수금액(KRW)", "수량(주)"])
        for ticker, weight in sorted(weights.items(), key=lambda x: -x[1]):
            meta = universe_lookup.get(ticker, {})
            amount = int(weight * capital_krw)
            price = current_prices.get(ticker, 0)
            qty = int(amount / price) if price > 0 else 0
            if qty == 0 and amount > 0:
                zero_qty.append(ticker)
            w.writerow([
                ticker,
                meta.get("name", ""),
                meta.get("category", ""),
                f"{weight:.4f}",
                amount,
                qty,
            ])

        if zero_qty:
            # MTS는 # 시작 라인을 무시하지만 사람이 보기 명확하도록 빈 줄 + 경고
            f.write("\n")
            f.write(
                f"# WARNING: {len(zero_qty)} ticker(s) have qty=0 "
                f"(current_prices fetch failed or price=0)\n"
            )
            f.write(
                f"# Affected: {', '.join(zero_qty[:10])}"
                + (f" ... and {len(zero_qty)-10} more" if len(zero_qty) > 10 else "")
                + "\n"
            )
            f.write(
                "# Manual fix: re-fetch pykrx snapshot for as_of_date, "
                "or override prices in artifacts/{date}/portfolio.json\n"
            )

    return out_path, zero_qty
