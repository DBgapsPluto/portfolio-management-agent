# Stage1 버킷 데이터 fold-in — Plan A (인프라 + A2 국내금리 + A4 안전통화) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** market_risk 애널리스트에 KR 금리 곡선(5y/30y)·신용(BBB-)·단기자금(CD91) 데이터를, macro_quant 애널리스트에 엔/원 cross(JPY)를 fold-in한다.

**Architecture:** 신규 애널리스트 노드 없음. 기존 ECOS/FRED dict에 series를 등록하고, 기존 skill(`compute_kr_yield_curve`/`compute_kr_corp_spread`/`compute_fx_overlay`)의 시그니처를 후방호환(default 인자)으로 확장하며, 신규 snapshot 필드/클래스를 `default=` sentinel로 추가한다. 애널리스트에서 fetch→compute 배선을 한 줄씩 늘린다.

**Tech Stack:** Python 3.12, pydantic v2, pandas, pytest. 데이터: 한국은행 ECOS(817Y002 일별 시장금리), FRED(DEXJPUS). 전부 라이브 검증 완료(spec §4).

**참고 spec:** [docs/superpowers/specs/2026-06-09-stage1-bucket-data-foldins-design.md](../specs/2026-06-09-stage1-bucket-data-foldins-design.md) §5.1(A2)·§5.7(A4)·§6.

---

## File Structure

**A2 국내금리 → market_risk:**
- Modify `tradingagents/dataflows/ecos.py` — `ECOS_STAT_CODES`에 4 series
- Modify `tradingagents/default_config.py` — `publication_lag_days`에 4 키
- Modify `tradingagents/schemas/risk.py` — `KRYieldCurveSnapshot`·`KRCorpSpreadSnapshot` 필드 추가, `KRShortRateSnapshot` 신규
- Modify `tradingagents/skills/risk/kr_yield_curve.py` — 5y/30y 파라미터
- Modify `tradingagents/skills/risk/kr_corp_spread.py` — BBB- 파라미터
- Create `tradingagents/skills/risk/kr_short_rate.py` — CD91 skill
- Modify `tradingagents/agents/analysts/market_risk_analyst.py` — fetch+compute 배선
- Modify `tests/unit/skills/test_risk_tier3.py` — skill 테스트

**A4 안전통화 → macro_quant:**
- Modify `tradingagents/dataflows/fred.py` — `FRED_SERIES`에 `usd_jpy`
- Modify `tradingagents/default_config.py` — `publication_lag_days`에 `usd_jpy`
- Modify `tradingagents/schemas/macro.py` — `FXSnapshot`에 jpy 필드
- Modify `tradingagents/skills/macro/fx.py` — `usd_jpy` 파라미터
- Modify `tradingagents/agents/analysts/macro_quant_analyst.py` — fetch+compute 배선
- Modify `tests/unit/skills/test_macro_tier3.py` (또는 fx 테스트 파일) — fx 테스트

---

## Task 1: ECOS A2 4 series 등록

**Files:**
- Modify: `tradingagents/dataflows/ecos.py:18-35`
- Modify: `tradingagents/default_config.py:87`
- Test: `tests/unit/dataflows/test_ecos_codes.py` (Create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/dataflows/test_ecos_codes.py
from tradingagents.dataflows.ecos import ECOS_STAT_CODES
from tradingagents.default_config import DEFAULT_CONFIG


def test_a2_series_registered():
    for key, item in [
        ("kr_treasury_5y", "010200001"),
        ("kr_treasury_30y", "010230000"),
        ("kr_corp_bbb_3y", "010320000"),
        ("kr_cd91", "010502000"),
    ]:
        assert key in ECOS_STAT_CODES, f"{key} missing"
        stat, code = ECOS_STAT_CODES[key]
        assert stat == "817Y002"
        assert code == item


def test_a2_publication_lag():
    lag = DEFAULT_CONFIG["publication_lag_days"]
    for key in ("kr_treasury_5y", "kr_treasury_30y", "kr_corp_bbb_3y", "kr_cd91"):
        assert lag.get(key) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/dataflows/test_ecos_codes.py -v`
Expected: FAIL — `kr_treasury_5y missing`

- [ ] **Step 3: Add the series to ECOS_STAT_CODES**

In `tradingagents/dataflows/ecos.py`, after the `kr_corp_aa_3y` line (currently line 34) inside the `ECOS_STAT_CODES` dict, add:

```python
    # A2 fold-in (2026-06-09): 817Y002 일별 시장금리, 라이브 검증 완료.
    "kr_treasury_5y": ("817Y002", "010200001"),     # 국고채(5년)
    "kr_treasury_30y": ("817Y002", "010230000"),    # 국고채(30년)
    "kr_corp_bbb_3y": ("817Y002", "010320000"),     # 회사채(3년, BBB-)
    "kr_cd91": ("817Y002", "010502000"),            # CD 91일
```

- [ ] **Step 4: Add publication lag**

In `tradingagents/default_config.py`, inside the `publication_lag_days` dict (after the `kr_*` entries near line 110), add:

```python
        "kr_treasury_5y": 1, "kr_treasury_30y": 1,
        "kr_corp_bbb_3y": 1, "kr_cd91": 1,
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/dataflows/test_ecos_codes.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add tradingagents/dataflows/ecos.py tradingagents/default_config.py tests/unit/dataflows/test_ecos_codes.py
git commit -m "feat(stage1): register A2 ECOS series (국고채 5y/30y, 회사채 BBB-, CD91)"
```

---

## Task 2: KRYieldCurveSnapshot에 5y/30y term

**Files:**
- Modify: `tradingagents/schemas/risk.py:164-181`
- Modify: `tradingagents/skills/risk/kr_yield_curve.py:37-73`
- Test: `tests/unit/skills/test_risk_tier3.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/skills/test_risk_tier3.py` (the `_daily` helper already exists there):

```python
def test_kr_yc_long_end_terms():
    y3 = _daily([3.0] * 260)
    y10 = _daily([3.7] * 260)
    y5 = _daily([3.3] * 260)
    y30 = _daily([4.0] * 260)
    snap = compute_kr_yield_curve(y3, y10, as_of=date(2026, 5, 10),
                                  treasury_5y=y5, treasury_30y=y30)
    assert abs(snap.treasury_5y - 3.3) < 1e-6
    assert abs(snap.treasury_30y - 4.0) < 1e-6
    assert abs(snap.spread_30y_5y_bps - 70.0) < 1e-6  # (4.0-3.3)*100


def test_kr_yc_long_end_optional():
    # 후방호환: 5y/30y 미제공 시 0.0
    snap = compute_kr_yield_curve(_daily([3.0]), _daily([3.7]), as_of=date(2026, 5, 10))
    assert snap.treasury_5y == 0.0
    assert snap.treasury_30y == 0.0
    assert snap.spread_30y_5y_bps == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/skills/test_risk_tier3.py::test_kr_yc_long_end_terms -v`
Expected: FAIL — `TypeError: compute_kr_yield_curve() got an unexpected keyword argument 'treasury_5y'`

- [ ] **Step 3: Add fields to KRYieldCurveSnapshot**

In `tradingagents/schemas/risk.py`, inside `KRYieldCurveSnapshot` (after the `regime` field, ~line 181), add:

```python
    # A2 fold-in (2026-06-09): long-end terms. default=0.0 후방호환.
    treasury_5y: float = Field(default=0.0, description="국고채 5년 yield (%)")
    treasury_30y: float = Field(default=0.0, description="국고채 30년 yield (%)")
    spread_30y_5y_bps: float = Field(
        default=0.0, description="(30y - 5y) × 100, bps. 장기 term premium")
```

- [ ] **Step 4: Extend compute_kr_yield_curve**

In `tradingagents/skills/risk/kr_yield_curve.py`, change the signature and add long-end computation. Replace the function definition line and the final `return`:

```python
@register_skill(name="compute_kr_yield_curve", category="risk")
def compute_kr_yield_curve(
    treasury_3y: pd.Series, treasury_10y: pd.Series, as_of: date,
    treasury_5y: pd.Series | None = None, treasury_30y: pd.Series | None = None,
) -> KRYieldCurveSnapshot:
    """한국 국고채 yield curve 진단. 미국과 별도 사이클 가능 (BOK vs Fed 정책차)."""
    if treasury_3y is None or treasury_3y.empty or treasury_10y.empty:
        return KRYieldCurveSnapshot(
            treasury_3y=0.0, treasury_10y=0.0, spread_10y_3y_bps=0.0,
            inverted=False, percentile_5y=0.5, regime="flat",
            source_date=as_of, staleness_days=99,
        )
```

Then, just before the final `return KRYieldCurveSnapshot(` (currently line 65), insert:

```python
    def _last(s: pd.Series | None) -> float:
        return float(s.iloc[-1]) if s is not None and not s.empty else 0.0
    y5 = _last(treasury_5y)
    y30 = _last(treasury_30y)
    spread_30y_5y = (y30 - y5) * 100 if (y5 and y30) else 0.0
```

And add the three fields to the final return:

```python
    return KRYieldCurveSnapshot(
        treasury_3y=y3,
        treasury_10y=y10,
        spread_10y_3y_bps=spread_bps,
        inverted=spread_bps < 0,
        percentile_5y=percentile,
        regime=regime,
        treasury_5y=y5,
        treasury_30y=y30,
        spread_30y_5y_bps=spread_30y_5y,
        source_date=as_of,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/skills/test_risk_tier3.py -v`
Expected: PASS (existing KR YC tests + 2 new)

- [ ] **Step 6: Commit**

```bash
git add tradingagents/schemas/risk.py tradingagents/skills/risk/kr_yield_curve.py tests/unit/skills/test_risk_tier3.py
git commit -m "feat(stage1): KR yield curve 5y/30y term premium (A2)"
```

---

## Task 3: KRCorpSpreadSnapshot에 BBB- 등급 스프레드

**Files:**
- Modify: `tradingagents/schemas/risk.py:184-192`
- Modify: `tradingagents/skills/risk/kr_corp_spread.py:17-53`
- Test: `tests/unit/skills/test_risk_tier3.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/skills/test_risk_tier3.py`:

```python
def test_kr_corp_bbb_quality_spread():
    corp_aa = _daily([3.5] * 100)
    treas = _daily([3.0] * 100)
    corp_bbb = _daily([10.3] * 100)  # BBB- 등급, 훨씬 높음
    snap = compute_kr_corp_spread(corp_aa, treas, as_of=date(2026, 5, 10),
                                  corp_bbb_3y=corp_bbb)
    assert abs(snap.corp_bbb_yield_3y - 10.3) < 1e-6
    assert abs(snap.bbb_aa_quality_spread_bps - 680.0) < 1e-6  # (10.3-3.5)*100


def test_kr_corp_bbb_optional():
    snap = compute_kr_corp_spread(_daily([3.5] * 100), _daily([3.0] * 100),
                                  as_of=date(2026, 5, 10))
    assert snap.corp_bbb_yield_3y == 0.0
    assert snap.bbb_aa_quality_spread_bps == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/skills/test_risk_tier3.py::test_kr_corp_bbb_quality_spread -v`
Expected: FAIL — `unexpected keyword argument 'corp_bbb_3y'`

- [ ] **Step 3: Add fields to KRCorpSpreadSnapshot**

In `tradingagents/schemas/risk.py`, inside `KRCorpSpreadSnapshot` (after `regime`, ~line 192), add:

```python
    # A2 fold-in (2026-06-09): BBB- 등급 신용 커브. default=0.0 후방호환.
    corp_bbb_yield_3y: float = Field(default=0.0, description="회사채 BBB- 3y yield (%)")
    bbb_aa_quality_spread_bps: float = Field(
        default=0.0, description="(BBB- - AA-) × 100, bps. 등급 프리미엄(낮은 등급 risk)")
```

- [ ] **Step 4: Extend compute_kr_corp_spread**

In `tradingagents/skills/risk/kr_corp_spread.py`, change the signature (line 18) to add the optional param, and compute the quality spread before the final return:

```python
@register_skill(name="compute_kr_corp_spread", category="risk")
def compute_kr_corp_spread(
    corp_yield_3y: pd.Series, treasury_3y: pd.Series, as_of: date,
    corp_bbb_3y: pd.Series | None = None,
) -> KRCorpSpreadSnapshot:
```

In the empty-input sentinel branch (the early `return` ~line 26), add the two new fields:

```python
        return KRCorpSpreadSnapshot(
            corp_yield_3y=0.0, treasury_3y=0.0, spread_bps=0.0,
            percentile_5y=0.5, regime="calm",
            corp_bbb_yield_3y=0.0, bbb_aa_quality_spread_bps=0.0,
            source_date=as_of, staleness_days=99,
        )
```

Before the final `return KRCorpSpreadSnapshot(` (line 46), insert:

```python
    bbb = float(corp_bbb_3y.iloc[-1]) if corp_bbb_3y is not None and not corp_bbb_3y.empty else 0.0
    quality_spread = (bbb - corp) * 100 if bbb else 0.0
```

And add the two fields to the final return:

```python
    return KRCorpSpreadSnapshot(
        corp_yield_3y=corp,
        treasury_3y=tres,
        spread_bps=spread_bps,
        percentile_5y=percentile,
        regime=_classify_regime(percentile),
        corp_bbb_yield_3y=bbb,
        bbb_aa_quality_spread_bps=quality_spread,
        source_date=as_of,
    )
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/skills/test_risk_tier3.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tradingagents/schemas/risk.py tradingagents/skills/risk/kr_corp_spread.py tests/unit/skills/test_risk_tier3.py
git commit -m "feat(stage1): KR BBB- quality spread (A2)"
```

---

## Task 4: KRShortRateSnapshot + compute_kr_short_rate (CD91)

**Files:**
- Modify: `tradingagents/schemas/risk.py` (신규 클래스)
- Create: `tradingagents/skills/risk/kr_short_rate.py`
- Test: `tests/unit/skills/test_risk_tier3.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/skills/test_risk_tier3.py`:

```python
from tradingagents.skills.risk.kr_short_rate import compute_kr_short_rate


def test_kr_short_rate_calm():
    cd = _daily([2.9] * 30)
    t3 = _daily([3.9] * 30)  # CD < 국고채3y → spread 음수 → calm
    snap = compute_kr_short_rate(cd, t3, as_of=date(2026, 5, 10))
    assert abs(snap.cd91 - 2.9) < 1e-6
    assert abs(snap.cd91_minus_treasury3y_bps - (-100.0)) < 1e-6
    assert snap.regime == "calm"


def test_kr_short_rate_stress():
    cd = _daily([4.5] * 30)
    t3 = _daily([3.9] * 30)  # CD > 국고채3y → funding stress
    snap = compute_kr_short_rate(cd, t3, as_of=date(2026, 5, 10))
    assert snap.cd91_minus_treasury3y_bps > 0
    assert snap.regime == "stress"


def test_kr_short_rate_empty_sentinel():
    snap = compute_kr_short_rate(pd.Series([], dtype=float), pd.Series([], dtype=float),
                                 as_of=date(2026, 5, 10))
    assert snap.staleness_days == 99
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/skills/test_risk_tier3.py::test_kr_short_rate_calm -v`
Expected: FAIL — `ModuleNotFoundError: ... kr_short_rate`

- [ ] **Step 3: Add KRShortRateSnapshot schema**

In `tradingagents/schemas/risk.py`, after `KRCorpSpreadSnapshot` (~line 192), add:

```python
class KRShortRateSnapshot(StalenessAware):
    """CD 91일 금리 vs 국고채 3y. 자금시장 funding stress 진단.

    CD > 국고채3y (양수 spread) = 단기 자금시장 경색 (funding stress).
    """
    cd91: float = Field(description="CD 91일 금리 (%)")
    cd91_minus_treasury3y_bps: float = Field(
        description="(CD91 - 국고채3y) × 100, bps. 양수=자금시장 funding stress")
    regime: Literal["calm", "elevated", "stress"] = Field(
        description="spread < -20bps calm, -20~0 elevated, >0 stress")
```

- [ ] **Step 4: Create the skill**

Create `tradingagents/skills/risk/kr_short_rate.py`:

```python
from datetime import date

import pandas as pd

from tradingagents.schemas.risk import KRShortRateSnapshot
from tradingagents.skills.registry import register_skill


def _classify_regime(spread_bps: float) -> str:
    if spread_bps > 0:
        return "stress"
    if spread_bps > -20:
        return "elevated"
    return "calm"


@register_skill(name="compute_kr_short_rate", category="risk")
def compute_kr_short_rate(
    cd91: pd.Series, treasury_3y: pd.Series, as_of: date,
) -> KRShortRateSnapshot:
    """CD 91일 vs 국고채 3y → 단기 자금시장 funding stress."""
    if cd91 is None or cd91.empty:
        return KRShortRateSnapshot(
            cd91=0.0, cd91_minus_treasury3y_bps=0.0, regime="calm",
            source_date=as_of, staleness_days=99,
        )
    cd = float(cd91.iloc[-1])
    t3 = float(treasury_3y.iloc[-1]) if treasury_3y is not None and not treasury_3y.empty else cd
    spread_bps = (cd - t3) * 100
    return KRShortRateSnapshot(
        cd91=cd,
        cd91_minus_treasury3y_bps=spread_bps,
        regime=_classify_regime(spread_bps),
        source_date=as_of,
    )
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/skills/test_risk_tier3.py -k short_rate -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add tradingagents/schemas/risk.py tradingagents/skills/risk/kr_short_rate.py tests/unit/skills/test_risk_tier3.py
git commit -m "feat(stage1): KR CD91 short-rate funding stress (A2)"
```

---

## Task 5: market_risk_analyst 배선 (A2)

**Files:**
- Modify: `tradingagents/agents/analysts/market_risk_analyst.py:23-38,93-102,408-426`

- [ ] **Step 1: Add imports**

In `tradingagents/agents/analysts/market_risk_analyst.py`, add to the schema import block (line 23-24) `KRShortRateSnapshot`, and add a skill import next to the existing kr skill imports (~line 38):

```python
from tradingagents.skills.risk.kr_short_rate import compute_kr_short_rate
```

- [ ] **Step 2: Add sentinel helper**

After `_sentinel_kr_corp_spread` (~line 102), add:

```python
def _sentinel_kr_short_rate(as_of: date) -> KRShortRateSnapshot:
    return KRShortRateSnapshot(
        cd91=0.0, cd91_minus_treasury3y_bps=0.0, regime="calm",
        source_date=as_of, staleness_days=99,
    )
```

- [ ] **Step 3: Fetch the new ECOS series and pass to skills**

In the KR yield/corp fetch block (currently ~line 408-426), after `kr_10y` is fetched and before `compute_kr_yield_curve`, fetch the long-end + short-rate series, and pass them into the existing compute calls:

```python
            kr_5y = fetch_ecos_series_skill(
                "kr_treasury_5y", start_5y, as_of, freq="D", as_of_date=as_of)
            kr_30y = fetch_ecos_series_skill(
                "kr_treasury_30y", start_5y, as_of, freq="D", as_of_date=as_of)
            kr_yield_curve = compute_kr_yield_curve(
                kr_3y, kr_10y, as_of=as_of, treasury_5y=kr_5y, treasury_30y=kr_30y)
```

Then in the corp-spread block, fetch BBB- and pass it:

```python
            kr_corp_bbb = fetch_ecos_series_skill(
                "kr_corp_bbb_3y", start_5y, as_of, freq="D", as_of_date=as_of)
            kr_corp_spread = compute_kr_corp_spread(
                kr_corp,
                kr_3y if not kr_yield_curve.staleness_days >= 99 else pd.Series(dtype=float),
                as_of=as_of, corp_bbb_3y=kr_corp_bbb)
```

Then add a CD91 fetch + compute (wrap in try/except mirroring the existing pattern), e.g. after the corp block:

```python
            try:
                kr_cd91 = fetch_ecos_series_skill(
                    "kr_cd91", start_5y, as_of, freq="D", as_of_date=as_of)
                kr_short_rate = compute_kr_short_rate(kr_cd91, kr_3y, as_of=as_of)
            except Exception as e:  # noqa: BLE001
                logger.warning("kr_short_rate fetch failed → sentinel: %s", e)
                kr_short_rate = _sentinel_kr_short_rate(as_of)
```

- [ ] **Step 4: Attach kr_short_rate to RiskReport**

Find the `RiskReport(` construction in this file and add `kr_short_rate=kr_short_rate,` to it. **First add the field to the schema:** in `tradingagents/schemas/reports.py`, locate `class RiskReport` and add (with a default so old archives still load):

```python
    kr_short_rate: KRShortRateSnapshot | None = None
```

(import `KRShortRateSnapshot` in reports.py's risk-schema import block.)

- [ ] **Step 5: Run regression + live smoke**

Run: `.venv/bin/python -m pytest tests/unit/ -k "market_risk or risk_tier3" -v`
Expected: PASS (no regressions)

Live smoke (reuses the verified data path):

```bash
.venv/bin/python -c "
from datetime import date
from tradingagents.agents.analysts.market_risk_analyst import create_market_risk_analyst
# (use the project's standard analyst smoke harness if one exists; otherwise
#  assert the ECOS fetch returns non-empty for kr_treasury_5y/kr_cd91)
from tradingagents.skills.macro.ecos_fetcher import fetch_ecos_series_skill
s = fetch_ecos_series_skill('kr_cd91', date(2026,5,1), date(2026,6,9), freq='D', as_of_date=date(2026,6,9))
print('kr_cd91 rows', len(s), 'last', s.iloc[-1] if len(s) else None)
"
```
Expected: `kr_cd91 rows > 0`, last ≈ 2.9

- [ ] **Step 6: Commit**

```bash
git add tradingagents/agents/analysts/market_risk_analyst.py tradingagents/schemas/reports.py
git commit -m "feat(stage1): wire A2 (KR 5y/30y/BBB-/CD91) into market_risk analyst"
```

---

## Task 6: FRED usd_jpy (DEXJPUS) 등록

**Files:**
- Modify: `tradingagents/dataflows/fred.py:48` (FRED_SERIES)
- Modify: `tradingagents/default_config.py:87` (publication_lag_days)
- Test: `tests/unit/dataflows/test_fred_codes.py` (Create)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/dataflows/test_fred_codes.py
from tradingagents.dataflows.fred import FRED_SERIES
from tradingagents.default_config import DEFAULT_CONFIG


def test_usd_jpy_registered():
    assert FRED_SERIES.get("usd_jpy") == "DEXJPUS"
    assert DEFAULT_CONFIG["publication_lag_days"].get("usd_jpy") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/dataflows/test_fred_codes.py -v`
Expected: FAIL — `None != 'DEXJPUS'`

- [ ] **Step 3: Register the series**

In `tradingagents/dataflows/fred.py`, in `FRED_SERIES` right after the `usd_krw` line (line 83), add:

```python
    "usd_jpy": "DEXJPUS",             # JPY per USD (daily). A4 fold-in.
```

In `tradingagents/default_config.py` `publication_lag_days`, near `kr_export` add:

```python
        "usd_jpy": 1,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/dataflows/test_fred_codes.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tradingagents/dataflows/fred.py tradingagents/default_config.py tests/unit/dataflows/test_fred_codes.py
git commit -m "feat(stage1): register usd_jpy (DEXJPUS) FRED series (A4)"
```

---

## Task 7: FXSnapshot에 jpy_krw cross + fx skill 확장

**Files:**
- Modify: `tradingagents/schemas/macro.py:197-215` (FXSnapshot)
- Modify: `tradingagents/skills/macro/fx.py:33-48`
- Test: `tests/unit/skills/test_macro_tier3.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/skills/test_macro_tier3.py` (mirror its existing series helper; if none, define one inline):

```python
from datetime import date
import pandas as pd
from tradingagents.skills.macro.fx import compute_fx_overlay


def _d(values, start="2025-05-10"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"))


def test_fx_jpy_krw_cross():
    usd_krw = _d([1555.96] * 30)
    dxy = _d([100.0] * 30)
    usd_jpy = _d([160.26] * 30)
    snap = compute_fx_overlay(usd_krw, dxy, as_of=date(2026, 6, 9), usd_jpy=usd_jpy)
    assert abs(snap.jpy_krw - (1555.96 / 160.26)) < 1e-4   # ≈ 9.71
    assert snap.jpy_krw_change_1m_pct == 0.0  # 평탄


def test_fx_jpy_optional():
    snap = compute_fx_overlay(_d([1300.0] * 30), _d([100.0] * 30), as_of=date(2026, 6, 9))
    assert snap.jpy_krw == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/skills/test_macro_tier3.py::test_fx_jpy_krw_cross -v`
Expected: FAIL — `unexpected keyword argument 'usd_jpy'`

- [ ] **Step 3: Add fields to FXSnapshot**

In `tradingagents/schemas/macro.py`, inside `FXSnapshot` (after `krw_reer`, ~line 214), add:

```python
    # A4 fold-in (2026-06-09): 엔/원 cross. a4_safe_fx 엔 2종의 1차 driver.
    jpy_krw: float = Field(
        default=0.0, description="KRW per 1 JPY (= usd_krw / usd_jpy). 엔/원 cross")
    jpy_krw_change_1m_pct: float = Field(
        default=0.0, description="JPY/KRW 1개월 % 변화 (+ = 엔 강세 vs 원)")
```

- [ ] **Step 4: Extend compute_fx_overlay**

In `tradingagents/skills/macro/fx.py`, change the signature and compute the cross before the return:

```python
@register_skill(name="compute_fx_overlay", category="macro")
def compute_fx_overlay(
    usd_krw: pd.Series, dxy: pd.Series, as_of: date,
    usd_jpy: pd.Series | None = None,
) -> FXSnapshot:
    """USD/KRW + DXY → KRW 강도 + 글로벌 USD 강도 동시 진단."""
    krw_change = _pct_change_1m(usd_krw)
    dxy_change = _pct_change_1m(dxy)

    jpy_krw = 0.0
    jpy_krw_chg = 0.0
    if usd_jpy is not None and not usd_jpy.empty:
        aligned = pd.concat([usd_krw, usd_jpy], axis=1, join="inner").dropna()
        if not aligned.empty:
            cross = aligned.iloc[:, 0] / aligned.iloc[:, 1]   # usd_krw / usd_jpy = KRW per JPY
            jpy_krw = float(cross.iloc[-1])
            jpy_krw_chg = _pct_change_1m(cross)

    return FXSnapshot(
        usd_krw=float(usd_krw.iloc[-1]),
        dxy=float(dxy.iloc[-1]),
        krw_change_1m_pct=krw_change,
        dxy_change_1m_pct=dxy_change,
        regime=_classify_regime(krw_change, dxy_change),
        jpy_krw=jpy_krw,
        jpy_krw_change_1m_pct=jpy_krw_chg,
        source_date=as_of,
    )
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/unit/skills/test_macro_tier3.py -k fx -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tradingagents/schemas/macro.py tradingagents/skills/macro/fx.py tests/unit/skills/test_macro_tier3.py
git commit -m "feat(stage1): FX jpy_krw cross from DEXJPUS (A4)"
```

---

## Task 8: macro_quant_analyst 배선 (A4)

**Files:**
- Modify: `tradingagents/agents/analysts/macro_quant_analyst.py:311-313,550-552`

- [ ] **Step 1: Fetch usd_jpy and pass to compute_fx_overlay**

In `tradingagents/agents/analysts/macro_quant_analyst.py`, in the FX fetch block (line 550-552), add a `usd_jpy` fetch and pass it:

```python
            krw = fetch_fred_series_skill("usd_krw", start_macro, as_of, as_of_date=as_of)
            dxy = fetch_fred_series_skill("dxy", start_macro, as_of, as_of_date=as_of)
            usd_jpy = fetch_fred_series_skill("usd_jpy", start_macro, as_of, as_of_date=as_of)
            fx = compute_fx_overlay(krw, dxy, as_of=as_of, usd_jpy=usd_jpy)
```

- [ ] **Step 2: Update FX sentinel (optional but consistent)**

The `_sentinel_fx` (line 311-313) needs no change — `jpy_krw` defaults to 0.0. Leave as-is.

- [ ] **Step 3: Run regression + live smoke**

Run: `.venv/bin/python -m pytest tests/unit/ -k "macro_quant or macro_tier3" -v`
Expected: PASS

Live smoke:

```bash
.venv/bin/python -c "
from datetime import date, timedelta
from tradingagents.dataflows.fred import fetch_fred_series
from tradingagents.skills.macro.fx import compute_fx_overlay
t = date(2026,6,9)
krw = fetch_fred_series('usd_krw', t-timedelta(days=60), t)
jpy = fetch_fred_series('usd_jpy', t-timedelta(days=60), t)
dxy = fetch_fred_series('dxy', t-timedelta(days=60), t) if 'dxy' else krw
snap = compute_fx_overlay(krw, dxy, as_of=t, usd_jpy=jpy)
print('jpy_krw', round(snap.jpy_krw, 2))
"
```
Expected: `jpy_krw ≈ 9.7`

- [ ] **Step 4: Commit**

```bash
git add tradingagents/agents/analysts/macro_quant_analyst.py
git commit -m "feat(stage1): wire usd_jpy into macro_quant FX overlay (A4)"
```

---

## Self-Review (작성자 점검 결과)

- **Spec 커버리지**: §5.1(A2 5y/30y/BBB-/CD91) → Task 1–5. §5.7(A4 DEXJPUS/jpy_krw) → Task 6–8. §6(ECOS/FRED dict, publication_lag) → Task 1·6. ✅ 누락 없음.
- **Placeholder**: 모든 step에 실제 코드/명령 포함. analyst 배선(Task 5·8)은 정확한 fetch 키·compute 인자·라인 범위 명시. ✅
- **Type 일관성**: `KRShortRateSnapshot`(Task 4 정의) → Task 5에서 동일명 사용. `compute_fx_overlay(usd_jpy=...)`(Task 7) → Task 8에서 동일 호출. `corp_bbb_3y`/`treasury_5y`/`treasury_30y` 키워드 일관. ✅
- **주의(실행자용)**: analyst 파일 라인 번호는 작성 시점 기준 — 실제 편집 시 인접 코드로 위치를 확인할 것. `RiskReport` 필드 추가(Task 5 Step 4)를 빠뜨리면 배선이 깨지므로 reports.py 수정을 먼저 적용.

---

## Plan B·C 예고 (동일 패턴)

- **Plan B** — B3 반도체(^SOX/SMH→technical, 칩PPI→macro_quant), B5 신흥국(EEM/EMB/VWO→macro_quant), B1 섹터수출(ECOS 403Y002→macro_quant). yfinance는 `fetch_cross_asset_returns(tickers=[...])` 별도 cache_key로 추가(기존 16종 캐시 불변).
- **Plan C** — B7 리츠(모기지/REIT yield/dispersion→market_risk, KR REIT universe 등재), B9 하이일드(HY-IG decompression→market_risk). B9는 backtest fallback(BAA10Y) live-only 가드 명시.
