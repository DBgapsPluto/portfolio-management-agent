"""xlsx 14-bucket 분류를 data/universe.json 에 gaps_bucket 으로 병합 (1회).

Usage: .venv/bin/python scripts/enrich_universe_gaps_bucket.py
"""
import json
from pathlib import Path

import pandas as pd

from tradingagents.skills.portfolio.gaps_buckets import CODE_TO_KEY

XLSX = Path("docs/GAPS_ETF_버킷분류_14.xlsx")
UNIVERSE = Path("data/universe.json")


def main() -> None:
    df = pd.read_excel(XLSX, sheet_name="버킷분류")
    code_by_ticker = {
        str(t): str(b) for t, b in zip(df["티커"], df["버킷"])
    }
    u = json.loads(UNIVERSE.read_text())
    missing = []
    for e in u["etfs"]:
        code = code_by_ticker.get(e["ticker"])
        if code is None or code not in CODE_TO_KEY:
            missing.append(e["ticker"])
            continue
        e["gaps_bucket"] = CODE_TO_KEY[code]
    if missing:
        raise SystemExit(f"매핑 실패 {len(missing)}종목: {missing[:10]}")
    UNIVERSE.write_text(json.dumps(u, ensure_ascii=False, indent=2))
    print(f"OK — {len(u['etfs'])}종목 gaps_bucket 병합 완료")


if __name__ == "__main__":
    main()
