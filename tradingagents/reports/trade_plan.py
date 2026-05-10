"""Trade plan CSV — MTS 입력 포맷."""
import csv
from pathlib import Path


def write_trade_plan(
    weights: dict[str, float],
    capital_krw: int,
    universe_lookup: dict,
    current_prices: dict[str, float],
    out_path: Path,
) -> Path:
    """Generate MTS-input CSV with: ticker, name, category, weight, amount, qty."""
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["티커", "ETF명", "자산군", "가중치", "매수금액(KRW)", "수량(주)"])
        for ticker, weight in sorted(weights.items(), key=lambda x: -x[1]):
            meta = universe_lookup.get(ticker, {})
            amount = int(weight * capital_krw)
            price = current_prices.get(ticker, 0)
            qty = int(amount / price) if price > 0 else 0
            w.writerow([
                ticker,
                meta.get("name", ""),
                meta.get("category", ""),
                f"{weight:.4f}",
                amount,
                qty,
            ])
    return out_path
