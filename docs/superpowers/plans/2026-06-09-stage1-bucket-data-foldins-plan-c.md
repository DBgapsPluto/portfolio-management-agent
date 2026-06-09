# Stage1 버킷 데이터 fold-in — Plan C (B7 리츠 + B9 하이일드) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** market_risk 애널리스트에 리츠 거시 드라이버(US REIT 모멘텀·dispersion·모기지 스프레드)와 하이일드 신용 디컴프레션(HY-IG)을 fold-in. KR REIT는 universe 등재로 technical에 자동 반영.

**Architecture:** 신규 애널리스트 노드 0. US REIT/HY ETF는 `equity_indices` 개별 시리즈 캐시. 모기지는 FRED. HY/IG OAS는 **이미 보유**(`fetch_credit_spread`)한 SpreadSnapshot 재사용. KR REIT 가격은 universe.json 등재 → 기존 `fetch_etf_price_batch`가 자동 fetch(critic 권고: 가격은 universe로 흐름). 전부 결정론(LLM 0).

**Tech Stack:** Python 3.12, pydantic v2, pandas, pytest. 데이터: yfinance(VNQ/XLRE/SCHH/HYG/JNK via equity_indices), FRED(MORTGAGE30US, BAMLH0A0HYM2/BAMLC0A0CM 기보유), pykrx(KR REIT via universe). 전부 라이브 검증 완료.

**참고:** spec [§5.5/§5.6](../specs/2026-06-09-stage1-bucket-data-foldins-design.md). Plan A/B 패턴 동일.

> **⚠️ 차단 조건(spec §7.1)**: B9 HY-IG decompression은 backtest에서 `us_hy_oas`·`us_ig_oas`가 둘 다 `BAA10Y`로 fallback(fred.py FRED_FALLBACK_CHAIN)되어 0으로 붕괴한다. snapshot docstring에 "live-only 신호, 2023-06 이전 backtest는 HY=IG=BAA10Y로 decompression≈0" 명시 필수.

---

## File Structure
- `dataflows/equity_indices.py` — vnq/xlre/schh/hyg/jnk
- `dataflows/fred.py` — us_mortgage_30y
- `default_config.py` — publication_lag_days
- `data/universe.json` — KR REIT 329200/476800 등재
- `schemas/risk.py` — `REITDriverSnapshot`, `HYDecompressionSnapshot`
- `schemas/reports.py` — RiskReport Optional 필드
- `skills/risk/reit_driver.py` (new), `hy_decompression.py` (new)
- `skills/registry.py` — `_SKILL_MODULES` 등록
- `agents/analysts/market_risk_analyst.py` — 배선
- tests: `test_reit_driver.py`, `test_hy_decompression.py`, dataflows/universe 보강

---

## Task 1: 인프라 등록 (equity_indices + fred + universe)

**Files:** `equity_indices.py`, `fred.py`, `default_config.py`, `data/universe.json`, `tests/unit/dataflows/test_planc_codes.py` (Create)

- [ ] **Step 1: failing test** — `tests/unit/dataflows/test_planc_codes.py`:
```python
import json
from pathlib import Path
from tradingagents.dataflows.equity_indices import EQUITY_INDEX_TICKERS
from tradingagents.dataflows.fred import FRED_SERIES
from tradingagents.default_config import DEFAULT_CONFIG


def test_planc_equity_tickers():
    for k, v in [("vnq", "VNQ"), ("xlre", "XLRE"), ("schh", "SCHH"),
                 ("hyg", "HYG"), ("jnk", "JNK")]:
        assert EQUITY_INDEX_TICKERS.get(k) == v


def test_mortgage_fred():
    assert FRED_SERIES.get("us_mortgage_30y") == "MORTGAGE30US"
    assert DEFAULT_CONFIG["publication_lag_days"].get("us_mortgage_30y") == 7


def test_kr_reit_in_universe():
    u = json.loads(Path("data/universe.json").read_text(encoding="utf-8"))
    etfs = u.get("etfs", u if isinstance(u, list) else [])
    tickers = {e["ticker"] for e in etfs}
    assert "A329200" in tickers
    assert "A476800" in tickers
```

- [ ] **Step 2:** `.venv/bin/python -m pytest tests/unit/dataflows/test_planc_codes.py -v` → FAIL.

- [ ] **Step 3: equity_indices** — add to `EQUITY_INDEX_TICKERS`:
```python
    "vnq": "VNQ",        # Vanguard US REIT (B7)
    "xlre": "XLRE",      # SPDR Real Estate (B7)
    "schh": "SCHH",      # Schwab US REIT (B7)
    "hyg": "HYG",        # iShares HY corp (B9)
    "jnk": "JNK",        # SPDR HY bond (B9)
```

- [ ] **Step 4: fred** — `FRED_SERIES` += `"us_mortgage_30y": "MORTGAGE30US",  # 30y 모기지 (weekly, B7)`. `default_config.py` `publication_lag_days` += `"us_mortgage_30y": 7,`

- [ ] **Step 5: universe KR REIT** — read `data/universe.json`, copy the exact entry schema (keys: ticker/name/aum_krw/underlying_index/bucket/category/sub_category/listed_since/delisted_at/gaps_bucket), and add two entries to the `etfs` list:
```json
{"ticker": "A329200", "name": "TIGER 리츠부동산인프라", "aum_krw": 0.0, "underlying_index": "FnGuide 리츠부동산인프라 지수", "bucket": "위험", "category": "해외주식_섹터", "sub_category": "thematic_other", "listed_since": "2019-07-19", "delisted_at": null, "gaps_bucket": "b7_reits"},
{"ticker": "A476800", "name": "KODEX 한국부동산리츠인프라", "aum_krw": 0.0, "underlying_index": "FnGuide 한국부동산리츠인프라 지수", "bucket": "위험", "category": "해외주식_섹터", "sub_category": "thematic_other", "listed_since": "2024-05-28", "delisted_at": null, "gaps_bucket": "b7_reits"}
```
(Match the existing JSON indentation/formatting exactly. `aum_krw: 0.0` is a placeholder — these are added for price visibility, not AUM filtering. Verify the file stays valid JSON: `.venv/bin/python -c "import json; json.load(open('data/universe.json'))"`.)

- [ ] **Step 6:** test → PASS. Confirm universe JSON valid.

- [ ] **Step 7: Commit** `feat(stage1): register Plan C series (VNQ/XLRE/SCHH/HYG/JNK, mortgage, KR REIT universe)` (+ trailer).

---

## Task 2: REITDriverSnapshot + compute_reit_driver (B7)

**Files:** `schemas/risk.py`, `skills/risk/reit_driver.py` (new), `skills/registry.py`, `tests/unit/skills/test_reit_driver.py` (new)

- [ ] **Step 1: failing test** — `tests/unit/skills/test_reit_driver.py`:
```python
from datetime import date
import pandas as pd
from tradingagents.skills.risk.reit_driver import compute_reit_driver


def _d(values, start="2025-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"))


def test_reit_driver_basic():
    vnq = _d([100.0] * 64 + [106.0])    # +6% 3m
    xlre = _d([100.0] * 64 + [104.0])
    schh = _d([100.0] * 64 + [105.0])
    mortgage = _d([7.0] * 30)
    dgs10 = _d([4.0] * 30)
    snap = compute_reit_driver(vnq, xlre, schh, mortgage, dgs10, as_of=date(2026, 5, 10))
    assert abs(snap.us_reit_ret_3m_pct - 6.0) < 0.5
    assert abs(snap.mortgage_30y - 7.0) < 1e-6
    assert abs(snap.mortgage_minus_10y_bps - 300.0) < 1e-6  # (7-4)*100


def test_reit_driver_empty_sentinel():
    e = pd.Series([], dtype=float)
    snap = compute_reit_driver(e, e, e, e, e, as_of=date(2026, 5, 10))
    assert snap.staleness_days == 99
```

- [ ] **Step 2:** run → FAIL.

- [ ] **Step 3: schema** — in `tradingagents/schemas/risk.py` add:
```python
class REITDriverSnapshot(StalenessAware):
    """리츠 거시 드라이버 (US REIT 모멘텀·dispersion + 모기지 스프레드).

    KR REIT 가격은 universe 등재로 technical sector_rotation에 반영됨(여기선 US 거시축).
    """
    us_reit_ret_3m_pct: float = Field(description="VNQ 63일 수익률 %")
    us_reit_ret_6m_pct: float = Field(description="VNQ 126일 수익률 %")
    us_reit_dispersion: float = Field(
        default=0.0, description="VNQ/XLRE/SCHH 63일 수익률 cross-sectional std (pp)")
    mortgage_30y: float = Field(default=0.0, description="30y 모기지 금리 %")
    mortgage_minus_10y_bps: float = Field(
        default=0.0, description="(모기지 − 10Y국채) × 100, bps. 부동산 금융비용 스프레드")
    regime: Literal["easing", "neutral", "tightening"] = Field(
        default="neutral", description="mortgage_minus_10y 5y percentile 또는 모기지 추세 기반")
```

- [ ] **Step 4: skill** — create `tradingagents/skills/risk/reit_driver.py`:
```python
from datetime import date

import pandas as pd

from tradingagents.schemas.risk import REITDriverSnapshot
from tradingagents.skills.registry import register_skill


def _ret(s: pd.Series | None, days: int) -> float:
    if s is None or len(s) <= days:
        return 0.0
    return float(s.iloc[-1] / s.iloc[-1 - days] - 1) * 100


def _last(s: pd.Series | None) -> float:
    return float(s.iloc[-1]) if s is not None and not s.empty else 0.0


@register_skill(name="compute_reit_driver", category="risk")
def compute_reit_driver(
    vnq: pd.Series, xlre: pd.Series, schh: pd.Series,
    mortgage: pd.Series, dgs10: pd.Series, as_of: date,
) -> REITDriverSnapshot:
    """US REIT 모멘텀·dispersion + 모기지 스프레드."""
    if vnq is None or vnq.empty:
        return REITDriverSnapshot(
            us_reit_ret_3m_pct=0.0, us_reit_ret_6m_pct=0.0,
            source_date=as_of, staleness_days=99,
        )
    rets_3m = [_ret(s, 63) for s in (vnq, xlre, schh) if s is not None and not s.empty]
    dispersion = float(pd.Series(rets_3m).std(ddof=0)) if len(rets_3m) >= 2 else 0.0
    mort = _last(mortgage)
    ten = _last(dgs10)
    spread_bps = (mort - ten) * 100 if (mort and ten) else 0.0
    return REITDriverSnapshot(
        us_reit_ret_3m_pct=_ret(vnq, 63),
        us_reit_ret_6m_pct=_ret(vnq, 126),
        us_reit_dispersion=dispersion,
        mortgage_30y=mort,
        mortgage_minus_10y_bps=spread_bps,
        regime="neutral",
        source_date=as_of,
    )
```
(regime은 단순 neutral 고정 — percentile 기반은 데이터 충분 시 후속. spec 허용.)

- [ ] **Step 5:** add `"tradingagents.skills.risk.reit_driver"` to `_SKILL_MODULES` in `registry.py`. Run `.venv/bin/python -m pytest tests/unit/skills/test_reit_driver.py -v` → PASS.

- [ ] **Step 6: Commit** `feat(stage1): REIT driver (VNQ/XLRE/SCHH + 모기지) skill (B7)` (+ trailer).

---

## Task 3: HYDecompressionSnapshot + compute_hy_decompression (B9)

**Files:** `schemas/risk.py`, `skills/risk/hy_decompression.py` (new), `skills/registry.py`, `tests/unit/skills/test_hy_decompression.py` (new)

- [ ] **Step 1: failing test** — `tests/unit/skills/test_hy_decompression.py`:
```python
from datetime import date
from tradingagents.skills.risk.hy_decompression import compute_hy_decompression


def test_hy_decompression_basic():
    snap = compute_hy_decompression(hy_oas_bps=450.0, ig_oas_bps=120.0, as_of=date(2026, 5, 10))
    assert abs(snap.hy_minus_ig_bps - 330.0) < 1e-6
    assert snap.regime in ("calm", "widening", "stress")


def test_hy_decompression_collapsed_sentinel():
    # backtest fallback: HY==IG (BAA10Y) → decompression 0 → regime calm, flagged
    snap = compute_hy_decompression(hy_oas_bps=200.0, ig_oas_bps=200.0, as_of=date(2026, 5, 10))
    assert snap.hy_minus_ig_bps == 0.0
    assert snap.collapsed is True
```

- [ ] **Step 2:** run → FAIL.

- [ ] **Step 3: schema** — in `schemas/risk.py` add:
```python
class HYDecompressionSnapshot(StalenessAware):
    """하이일드 − IG OAS 디컴프레션. within-credit risk 신호.

    ⚠️ live-only: backtest에서 us_hy_oas·us_ig_oas가 둘 다 BAA10Y로 fallback되면
    hy_minus_ig=0으로 붕괴(collapsed=True로 표시). 2023-06 이전 historical은 무의미.
    """
    hy_oas_bps: float = Field(description="US HY OAS (bps)")
    ig_oas_bps: float = Field(description="US IG OAS (bps)")
    hy_minus_ig_bps: float = Field(description="HY − IG (bps). 확대 = 신용 차별화/distress")
    collapsed: bool = Field(
        default=False, description="True면 HY==IG (backtest BAA10Y fallback) → 신호 무의미")
    regime: Literal["calm", "widening", "stress"] = Field(
        default="calm", description="hy_minus_ig <300 calm, 300~500 widening, >500 stress")
```

- [ ] **Step 4: skill** — create `tradingagents/skills/risk/hy_decompression.py`:
```python
from datetime import date

from tradingagents.schemas.risk import HYDecompressionSnapshot
from tradingagents.skills.registry import register_skill


def _classify(diff_bps: float) -> str:
    if diff_bps > 500:
        return "stress"
    if diff_bps > 300:
        return "widening"
    return "calm"


@register_skill(name="compute_hy_decompression", category="risk")
def compute_hy_decompression(
    hy_oas_bps: float, ig_oas_bps: float, as_of: date,
) -> HYDecompressionSnapshot:
    """HY − IG OAS 디컴프레션. HY==IG면 backtest fallback 붕괴로 표시."""
    diff = hy_oas_bps - ig_oas_bps
    collapsed = abs(diff) < 1e-9   # HY==IG → BAA10Y fallback (live 신호 아님)
    return HYDecompressionSnapshot(
        hy_oas_bps=hy_oas_bps, ig_oas_bps=ig_oas_bps,
        hy_minus_ig_bps=diff, collapsed=collapsed,
        regime=_classify(diff), source_date=as_of,
    )
```
(입력은 float OAS — market_risk가 이미 가진 SpreadSnapshot.current_bps에서 추출해 전달. 별도 fetch 불필요.)

- [ ] **Step 5:** add `"tradingagents.skills.risk.hy_decompression"` to `_SKILL_MODULES`. Run test → PASS.

- [ ] **Step 6: Commit** `feat(stage1): HY-IG decompression skill (B9, live-only)` (+ trailer).

---

## Task 4: market_risk_analyst 배선 (B7 + B9)

**Files:** `market_risk_analyst.py`, `reports.py`

- [ ] **Step 1: reports.py 필드** — `RiskReport`에 `reit_driver: REITDriverSnapshot | None = None`, `hy_decompression: HYDecompressionSnapshot | None = None` (+ imports from `tradingagents.schemas.risk`).

- [ ] **Step 2: B7 배선** — in `market_risk_analyst.py`, add a try/except block (mirror existing patterns) building reit_driver. Use `fetch_equity_index_close` for VNQ/XLRE/SCHH, `fetch_fred_series_skill` for mortgage + reuse the DGS10 the analyst already fetches (or fetch `us_10y`/`DGS10` via `fetch_fred_series_skill`):
```python
        try:
            from tradingagents.dataflows.equity_indices import fetch_equity_index_close
            vnq = fetch_equity_index_close("vnq", start_5y, as_of)
            xlre = fetch_equity_index_close("xlre", start_5y, as_of)
            schh = fetch_equity_index_close("schh", start_5y, as_of)
            mortgage = fetch_fred_series_skill("us_mortgage_30y", start_5y, as_of, as_of_date=as_of)
            dgs10 = fetch_fred_series_skill("us_10y", start_5y, as_of, as_of_date=as_of)
            reit_driver = compute_reit_driver(vnq, xlre, schh, mortgage, dgs10, as_of=as_of)
        except Exception as e:  # noqa: BLE001
            logger.warning("reit_driver failed → None: %s", e)
            reit_driver = None
```
(Confirm the analyst already fetches `us_10y` somewhere — if so reuse that Series instead of re-fetching; otherwise the above is fine. Use the real lookback var; `start_5y` is used by the KR block — confirm it's in scope here, else use the analyst's standard `start`/lookback.)

- [ ] **Step 3: B9 배선** — the analyst already computes `ig`/`hy` SpreadSnapshots (`fetch_credit_spread("US_IG"/"US_HY", as_of)` → `credit_spread_us_ig`/`credit_spread_us_hy`). After those, add:
```python
        try:
            hy_decompression = compute_hy_decompression(
                hy.current_bps, ig.current_bps, as_of=as_of)
        except Exception as e:  # noqa: BLE001
            logger.warning("hy_decompression failed → None: %s", e)
            hy_decompression = None
```
(Use the REAL variable names the analyst assigns the HY/IG snapshots to — READ the code; they may be `hy`/`ig` or `credit_hy`/`credit_ig`. Extract `.current_bps` from each.)

- [ ] **Step 4: assemble** — define `reit_driver = None` / `hy_decompression = None` defaults before their try blocks so they're always defined; add imports (`compute_reit_driver`, `compute_hy_decompression`); pass `reit_driver=reit_driver, hy_decompression=hy_decompression` into the `RiskReport(...)` constructor.

- [ ] **Step 5: Verify** — `.venv/bin/python -m pytest tests/unit -k "market_risk or reports or reit or hy_decomp" -q` → PASS. Live smoke:
```bash
.venv/bin/python -c "
from datetime import date, timedelta
from tradingagents.dataflows.equity_indices import fetch_equity_index_close
from tradingagents.dataflows.fred import fetch_fred_series
t = date(2026,6,9)
print('vnq', len(fetch_equity_index_close('vnq', t-timedelta(days=200), t)))
print('mortgage', len(fetch_fred_series('us_mortgage_30y', t-timedelta(days=120), t)))
"
```
Expected: non-zero.

- [ ] **Step 6: Commit** `feat(stage1): wire B7 (REIT) + B9 (HY decompression) into market_risk analyst` (+ trailer).

---

## Self-Review (작성자 점검)
- **Spec 커버리지**: §5.5(B7 모기지/REIT dispersion + KR REIT universe)→Task 1·2·4; §5.6(B9 HY-IG decompression)→Task 3·4; §7.1 차단(backtest 붕괴)→HYDecompressionSnapshot `collapsed` 플래그 + docstring. ✅
- **Placeholder 없음**: skill/schema 완전 코드. universe 등재는 실제 JSON 엔트리.
- **Type 일관성**: snapshot 클래스명 ↔ skill 반환 ↔ analyst import 일치. credit_spread는 기존 `fetch_credit_spread`/`SpreadSnapshot.current_bps` 재사용.
- **캐시 안전**: US REIT/HY ETF는 equity_indices 개별 시리즈 캐시.
- **주의(실행자)**: market_risk의 HY/IG snapshot 실제 변수명을 코드로 확인(`.current_bps` 추출). `start_5y` 스코프 확인. KR REIT `aum_krw=0.0`은 placeholder — AUM 필터에 안 걸리는지 확인(걸리면 작은 양수로). B9 collapsed 플래그로 backtest 무의미성 표시.
