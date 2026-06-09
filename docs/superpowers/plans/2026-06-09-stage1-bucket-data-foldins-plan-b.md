# Stage1 버킷 데이터 fold-in — Plan B (B3 반도체 + B5 신흥국 + B1 섹터수출) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** technical 애널리스트에 미·글로벌 반도체 모멘텀(^SOX/SMH)을, macro_quant에 칩 PPI·신흥국(EEM/EMB)·KR 섹터 수출물량을 fold-in.

**Architecture:** 신규 애널리스트 노드 0. 신규 yfinance 심볼은 `equity_indices.EQUITY_INDEX_TICKERS`에 등록해 개별 시리즈 캐시로 fetch(cross_asset 캐시 busting 회피 — critic 권고). 신규 snapshot은 기존 노드에 Optional 필드로 추가. 전부 결정론(LLM 0).

**Tech Stack:** Python 3.12, pydantic v2, pandas, pytest. 데이터: yfinance(^SOX·SMH·EEM·EMB·VWO via equity_indices), FRED(PCU334413334413), ECOS(403Y002). 전부 라이브 검증 완료(spec §4).

**참고:** spec [§5.2/§5.3/§5.4](../specs/2026-06-09-stage1-bucket-data-foldins-design.md). Plan A에서 확립된 패턴(`fetch_*_skill → compute_X → snapshot → sentinel`, `default=` 후방호환, TDD)을 그대로 따른다.

---

## File Structure

- `tradingagents/dataflows/equity_indices.py` — `EQUITY_INDEX_TICKERS`에 sox/smh/eem/emb/vwo
- `tradingagents/dataflows/fred.py` — `us_chip_ppi`
- `tradingagents/dataflows/ecos.py` — 403Y002 섹터 수출물량 5종
- `tradingagents/default_config.py` — publication_lag_days
- `tradingagents/schemas/technical.py` — `SemiMomentumSnapshot`
- `tradingagents/schemas/macro.py` — `ChipCycleSnapshot`, `EmergingMarketSnapshot`, `KRSectorExportSnapshot`
- `tradingagents/schemas/reports.py` — TechnicalReport/MacroReport Optional 필드
- `tradingagents/skills/technical/semi_momentum.py` (new)
- `tradingagents/skills/macro/chip_cycle.py` (new), `emerging_market.py` (new), `kr_sector_export.py` (new)
- analyst 배선: `technical_analyst.py`, `macro_quant_analyst.py`
- tests: `tests/unit/skills/test_semi_momentum.py`, `test_chip_cycle.py`, `test_emerging_market.py`, `test_kr_sector_export.py`, `tests/unit/dataflows/` 보강

---

## Task 1: 인프라 등록 (equity_indices + fred + ecos)

**Files:** `equity_indices.py`, `fred.py`, `ecos.py`, `default_config.py`, `tests/unit/dataflows/test_planb_codes.py` (Create)

- [ ] **Step 1: failing test** — `tests/unit/dataflows/test_planb_codes.py`:
```python
from tradingagents.dataflows.equity_indices import EQUITY_INDEX_TICKERS
from tradingagents.dataflows.fred import FRED_SERIES
from tradingagents.dataflows.ecos import ECOS_STAT_CODES
from tradingagents.default_config import DEFAULT_CONFIG


def test_equity_index_tickers():
    assert EQUITY_INDEX_TICKERS.get("sox") == "^SOX"
    assert EQUITY_INDEX_TICKERS.get("smh") == "SMH"
    assert EQUITY_INDEX_TICKERS.get("eem") == "EEM"
    assert EQUITY_INDEX_TICKERS.get("emb") == "EMB"
    assert EQUITY_INDEX_TICKERS.get("vwo") == "VWO"


def test_chip_ppi_fred():
    assert FRED_SERIES.get("us_chip_ppi") == "PCU334413334413"
    assert DEFAULT_CONFIG["publication_lag_days"].get("us_chip_ppi") == 30


def test_kr_sector_export_ecos():
    for key, item in [
        ("kr_export_semi", "30911AA"), ("kr_export_battery", "31013AA"),
        ("kr_export_display", "30921AA"), ("kr_export_chem", "305AA"),
        ("kr_export_steel", "3071AA"),
    ]:
        assert key in ECOS_STAT_CODES
        stat, code = ECOS_STAT_CODES[key]
        assert stat == "403Y002"
        assert code == item
```

- [ ] **Step 2:** `.venv/bin/python -m pytest tests/unit/dataflows/test_planb_codes.py -v` → FAIL.

- [ ] **Step 3: equity_indices** — in `tradingagents/dataflows/equity_indices.py`, add to `EQUITY_INDEX_TICKERS` dict:
```python
    "sox": "^SOX",       # PHLX Semiconductor Index (B3)
    "smh": "SMH",        # VanEck Semiconductor ETF (B3, 글로벌)
    "eem": "EEM",        # iShares MSCI EM (B5)
    "emb": "EMB",        # iShares EM USD Bond (B5)
    "vwo": "VWO",        # Vanguard FTSE EM (B5 보조)
```

- [ ] **Step 4: fred** — in `tradingagents/dataflows/fred.py` `FRED_SERIES`, add:
```python
    "us_chip_ppi": "PCU334413334413",   # 반도체·관련소자 PPI (월간, B3)
```
In `default_config.py` `publication_lag_days`, add: `"us_chip_ppi": 30,`

- [ ] **Step 5: ecos** — in `tradingagents/dataflows/ecos.py` `ECOS_STAT_CODES`, add:
```python
    # B1 fold-in (2026-06-09): 403Y002 섹터별 수출물량지수 (월간), 라이브 검증 완료.
    "kr_export_semi": ("403Y002", "30911AA"),      # 반도체
    "kr_export_battery": ("403Y002", "31013AA"),   # 전지
    "kr_export_display": ("403Y002", "30921AA"),   # 디스플레이
    "kr_export_chem": ("403Y002", "305AA"),        # 화학
    "kr_export_steel": ("403Y002", "3071AA"),      # 철강
```
In `default_config.py` `publication_lag_days`, add each: `"kr_export_semi": 30,` …(전부 30, 월간).

- [ ] **Step 6:** `.venv/bin/python -m pytest tests/unit/dataflows/test_planb_codes.py -v` → PASS.

- [ ] **Step 7: Commit**
```bash
git add tradingagents/dataflows/equity_indices.py tradingagents/dataflows/fred.py tradingagents/dataflows/ecos.py tradingagents/default_config.py tests/unit/dataflows/test_planb_codes.py
git commit -m "feat(stage1): register Plan B series (^SOX/SMH/EEM/EMB/VWO, chip PPI, 섹터수출)"
```
(commit trailer: blank line then `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`)

---

## Task 2: SemiMomentumSnapshot + compute_semi_momentum (B3 technical)

**Files:** `schemas/technical.py`, `skills/technical/semi_momentum.py` (new), `tests/unit/skills/test_semi_momentum.py` (new)

- [ ] **Step 1: failing test** — `tests/unit/skills/test_semi_momentum.py`:
```python
from datetime import date
import pandas as pd
from tradingagents.skills.technical.semi_momentum import compute_semi_momentum


def _d(values, start="2025-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"))


def test_semi_momentum_basic():
    # SOX +10% over 63d, SMH +5%, SPY +2%
    sox = _d([100.0] * 64 + [110.0])
    smh = _d([100.0] * 64 + [105.0])
    spy = _d([100.0] * 64 + [102.0])
    snap = compute_semi_momentum(sox, smh, spy, as_of=date(2026, 5, 10))
    assert abs(snap.sox_ret_3m_pct - 10.0) < 0.5
    assert abs(snap.smh_vs_spy_rel_3m - 3.0) < 0.5   # 5 - 2
    assert abs(snap.sox_minus_smh_div_3m - 5.0) < 0.5  # 10 - 5


def test_semi_momentum_empty_sentinel():
    snap = compute_semi_momentum(pd.Series([], dtype=float), pd.Series([], dtype=float),
                                 pd.Series([], dtype=float), as_of=date(2026, 5, 10))
    assert snap.staleness_days == 99
```

- [ ] **Step 2:** run → FAIL (ModuleNotFound).

- [ ] **Step 3: schema** — in `tradingagents/schemas/technical.py` (it already imports `StalenessAware`, `Field`; confirm) add:
```python
class SemiMomentumSnapshot(StalenessAware):
    """미·글로벌 반도체 모멘텀 (^SOX 미국, SMH 글로벌). 성장테마 상대강도."""
    sox_ret_3m_pct: float = Field(description="^SOX 63일 수익률 %")
    sox_ret_6m_pct: float = Field(description="^SOX 126일 수익률 %")
    smh_ret_3m_pct: float = Field(description="SMH 63일 수익률 %")
    smh_vs_spy_rel_3m: float = Field(description="SMH 3m − SPY 3m (성장테마 상대강도)")
    sox_minus_smh_div_3m: float = Field(description="^SOX 3m − SMH 3m (미국 vs 글로벌 반도체 디버전스)")
```

- [ ] **Step 4: skill** — create `tradingagents/skills/technical/semi_momentum.py`:
```python
from datetime import date

import pandas as pd

from tradingagents.schemas.technical import SemiMomentumSnapshot
from tradingagents.skills.registry import register_skill


def _ret(s: pd.Series | None, days: int) -> float:
    if s is None or len(s) <= days:
        return 0.0
    return float(s.iloc[-1] / s.iloc[-1 - days] - 1) * 100


@register_skill(name="compute_semi_momentum", category="technical")
def compute_semi_momentum(
    sox: pd.Series, smh: pd.Series, spy: pd.Series, as_of: date,
) -> SemiMomentumSnapshot:
    """^SOX/SMH 모멘텀 + SPY 대비 상대강도 + 미·글로벌 디버전스."""
    if sox is None or sox.empty:
        return SemiMomentumSnapshot(
            sox_ret_3m_pct=0.0, sox_ret_6m_pct=0.0, smh_ret_3m_pct=0.0,
            smh_vs_spy_rel_3m=0.0, sox_minus_smh_div_3m=0.0,
            source_date=as_of, staleness_days=99,
        )
    sox_3m = _ret(sox, 63)
    smh_3m = _ret(smh, 63)
    spy_3m = _ret(spy, 63)
    return SemiMomentumSnapshot(
        sox_ret_3m_pct=sox_3m,
        sox_ret_6m_pct=_ret(sox, 126),
        smh_ret_3m_pct=smh_3m,
        smh_vs_spy_rel_3m=smh_3m - spy_3m,
        sox_minus_smh_div_3m=sox_3m - smh_3m,
        source_date=as_of,
    )
```

- [ ] **Step 5:** `.venv/bin/python -m pytest tests/unit/skills/test_semi_momentum.py -v` → PASS.

- [ ] **Step 6: Commit** `feat(stage1): SOX/SMH semiconductor momentum skill (B3)` (+ trailer).

---

## Task 3: ChipCycleSnapshot + compute_chip_cycle (B3 macro)

**Files:** `schemas/macro.py`, `skills/macro/chip_cycle.py` (new), `tests/unit/skills/test_chip_cycle.py` (new)

- [ ] **Step 1: failing test** — `tests/unit/skills/test_chip_cycle.py`:
```python
from datetime import date
import pandas as pd
from tradingagents.skills.macro.chip_cycle import compute_chip_cycle


def _m(values, start="2024-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="MS"))


def test_chip_cycle_yoy():
    # 13 months, last=110 vs 12-ago=100 → +10% YoY
    vals = [100.0] * 12 + [110.0]
    snap = compute_chip_cycle(_m(vals), as_of=date(2026, 5, 10))
    assert abs(snap.chip_ppi_yoy_pct - 10.0) < 1e-6
    assert snap.chip_ppi == 110.0


def test_chip_cycle_empty_sentinel():
    snap = compute_chip_cycle(pd.Series([], dtype=float), as_of=date(2026, 5, 10))
    assert snap.staleness_days == 99
```

- [ ] **Step 2:** run → FAIL.

- [ ] **Step 3: schema** — in `tradingagents/schemas/macro.py` add:
```python
class ChipCycleSnapshot(StalenessAware):
    """반도체 제조 PPI (FRED PCU334413334413, 월간). 칩 가격 사이클."""
    chip_ppi: float = Field(description="반도체 PPI level")
    chip_ppi_yoy_pct: float = Field(description="12개월 전 대비 % (칩 가격 인플/디플)")
    momentum_3mo_pct: float = Field(default=0.0, description="3개월 변화율 %")
    accelerating: bool = Field(default=False, description="3mo > 0 and YoY > 0")
```

- [ ] **Step 4: skill** — create `tradingagents/skills/macro/chip_cycle.py`:
```python
from datetime import date

import pandas as pd

from tradingagents.schemas.macro import ChipCycleSnapshot
from tradingagents.skills.registry import register_skill


@register_skill(name="compute_chip_cycle", category="macro")
def compute_chip_cycle(chip_ppi: pd.Series, as_of: date) -> ChipCycleSnapshot:
    """칩 PPI YoY + 3개월 모멘텀."""
    if chip_ppi is None or chip_ppi.empty:
        return ChipCycleSnapshot(
            chip_ppi=0.0, chip_ppi_yoy_pct=0.0,
            source_date=as_of, staleness_days=99,
        )
    level = float(chip_ppi.iloc[-1])
    yoy = float(chip_ppi.iloc[-1] / chip_ppi.iloc[-13] - 1) * 100 if len(chip_ppi) >= 13 else 0.0
    mom_3 = float(chip_ppi.iloc[-1] / chip_ppi.iloc[-4] - 1) * 100 if len(chip_ppi) >= 4 else 0.0
    return ChipCycleSnapshot(
        chip_ppi=level,
        chip_ppi_yoy_pct=yoy,
        momentum_3mo_pct=mom_3,
        accelerating=(mom_3 > 0 and yoy > 0),
    )
```

- [ ] **Step 5:** test → PASS.
- [ ] **Step 6: Commit** `feat(stage1): chip PPI cycle skill (B3)` (+ trailer).

---

## Task 4: EmergingMarketSnapshot + compute_emerging_market (B5 macro)

**Files:** `schemas/macro.py`, `skills/macro/emerging_market.py` (new), `tests/unit/skills/test_emerging_market.py` (new)

- [ ] **Step 1: failing test** — `tests/unit/skills/test_emerging_market.py`:
```python
from datetime import date
import pandas as pd
from tradingagents.skills.macro.emerging_market import compute_emerging_market


def _d(values, start="2025-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="D"))


def test_em_basic():
    eem = _d([100.0] * 64 + [108.0])   # +8% 3m
    emb = _d([100.0] * 64 + [102.0])
    dxy = _d([100.0] * 64 + [98.0])    # DXY -2% (달러 약세 → EM 우호)
    snap = compute_emerging_market(eem, emb, dxy, as_of=date(2026, 5, 10))
    assert abs(snap.em_equity_ret_3m_pct - 8.0) < 0.5
    assert snap.regime == "risk_on"   # EM 강세 + 달러 약세


def test_em_empty_sentinel():
    snap = compute_emerging_market(pd.Series([], dtype=float), pd.Series([], dtype=float),
                                   pd.Series([], dtype=float), as_of=date(2026, 5, 10))
    assert snap.staleness_days == 99
```

- [ ] **Step 2:** run → FAIL.

- [ ] **Step 3: schema** — in `schemas/macro.py` add:
```python
class EmergingMarketSnapshot(StalenessAware):
    """신흥국 광역 (EEM 주식, EMB 달러채) + 달러 대비 상대강도."""
    em_equity_ret_3m_pct: float = Field(description="EEM 63일 수익률 %")
    em_equity_ret_6m_pct: float = Field(description="EEM 126일 수익률 %")
    em_debt_ret_3m_pct: float = Field(description="EMB 63일 수익률 % (캐리 proxy)")
    em_vs_dxy_rel: float = Field(description="EEM 3m − DXY 3m (달러 약세 시 EM 우호)")
    regime: Literal["risk_on", "neutral", "risk_off"] = Field(
        description="em_vs_dxy_rel > +3 risk_on, < -3 risk_off, else neutral")
```

- [ ] **Step 4: skill** — create `tradingagents/skills/macro/emerging_market.py`:
```python
from datetime import date

import pandas as pd

from tradingagents.schemas.macro import EmergingMarketSnapshot
from tradingagents.skills.registry import register_skill


def _ret(s: pd.Series | None, days: int) -> float:
    if s is None or len(s) <= days:
        return 0.0
    return float(s.iloc[-1] / s.iloc[-1 - days] - 1) * 100


def _classify(rel: float) -> str:
    if rel > 3:
        return "risk_on"
    if rel < -3:
        return "risk_off"
    return "neutral"


@register_skill(name="compute_emerging_market", category="macro")
def compute_emerging_market(
    eem: pd.Series, emb: pd.Series, dxy: pd.Series, as_of: date,
) -> EmergingMarketSnapshot:
    """EEM/EMB 모멘텀 + DXY 대비 상대강도."""
    if eem is None or eem.empty:
        return EmergingMarketSnapshot(
            em_equity_ret_3m_pct=0.0, em_equity_ret_6m_pct=0.0,
            em_debt_ret_3m_pct=0.0, em_vs_dxy_rel=0.0, regime="neutral",
            source_date=as_of, staleness_days=99,
        )
    eem_3m = _ret(eem, 63)
    dxy_3m = _ret(dxy, 63)
    rel = eem_3m - dxy_3m
    return EmergingMarketSnapshot(
        em_equity_ret_3m_pct=eem_3m,
        em_equity_ret_6m_pct=_ret(eem, 126),
        em_debt_ret_3m_pct=_ret(emb, 63),
        em_vs_dxy_rel=rel,
        regime=_classify(rel),
    )
```

- [ ] **Step 5:** test → PASS.
- [ ] **Step 6: Commit** `feat(stage1): emerging market (EEM/EMB/DXY) skill (B5)` (+ trailer).

---

## Task 5: KRSectorExportSnapshot + compute_kr_sector_export (B1 macro)

**Files:** `schemas/macro.py`, `skills/macro/kr_sector_export.py` (new), `tests/unit/skills/test_kr_sector_export.py` (new)

- [ ] **Step 1: failing test** — `tests/unit/skills/test_kr_sector_export.py`:
```python
from datetime import date
import pandas as pd
from tradingagents.skills.macro.kr_sector_export import compute_kr_sector_export


def _m(values, start="2024-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="MS"))


def test_sector_export_yoy():
    series = {
        "semi": _m([100.0] * 12 + [120.0]),     # +20% YoY (leader)
        "battery": _m([100.0] * 12 + [95.0]),   # -5%
        "display": _m([100.0] * 12 + [110.0]),
        "chem": _m([100.0] * 12 + [105.0]),
        "steel": _m([100.0] * 12 + [102.0]),
    }
    snap = compute_kr_sector_export(series, as_of=date(2026, 5, 10))
    assert abs(snap.semi_yoy_pct - 20.0) < 1e-6
    assert snap.leader_sector == "semi"


def test_sector_export_empty_sentinel():
    snap = compute_kr_sector_export({}, as_of=date(2026, 5, 10))
    assert snap.staleness_days == 99
```

- [ ] **Step 2:** run → FAIL.

- [ ] **Step 3: schema** — in `schemas/macro.py` add:
```python
class KRSectorExportSnapshot(StalenessAware):
    """KR 섹터별 수출물량 YoY (ECOS 403Y002). 섹터 펀더멘털 모멘텀."""
    semi_yoy_pct: float = Field(default=0.0, description="반도체 수출물량 YoY %")
    battery_yoy_pct: float = Field(default=0.0, description="전지 YoY %")
    display_yoy_pct: float = Field(default=0.0, description="디스플레이 YoY %")
    chem_yoy_pct: float = Field(default=0.0, description="화학 YoY %")
    steel_yoy_pct: float = Field(default=0.0, description="철강 YoY %")
    leader_sector: str = Field(default="", description="YoY 최고 섹터")
    laggard_sector: str = Field(default="", description="YoY 최저 섹터")
```

- [ ] **Step 4: skill** — create `tradingagents/skills/macro/kr_sector_export.py`:
```python
from datetime import date

import pandas as pd

from tradingagents.schemas.macro import KRSectorExportSnapshot
from tradingagents.skills.registry import register_skill

_SECTORS = ["semi", "battery", "display", "chem", "steel"]


def _yoy(s: pd.Series | None) -> float:
    if s is None or len(s) < 13:
        return 0.0
    return float(s.iloc[-1] / s.iloc[-13] - 1) * 100


@register_skill(name="compute_kr_sector_export", category="macro")
def compute_kr_sector_export(
    series: dict[str, pd.Series], as_of: date,
) -> KRSectorExportSnapshot:
    """섹터별 수출물량 YoY + leader/laggard. series 키: semi/battery/display/chem/steel."""
    if not series or all(s is None or s.empty for s in series.values()):
        return KRSectorExportSnapshot(source_date=as_of, staleness_days=99)
    yoy = {k: _yoy(series.get(k)) for k in _SECTORS}
    leader = max(yoy, key=yoy.get)
    laggard = min(yoy, key=yoy.get)
    return KRSectorExportSnapshot(
        semi_yoy_pct=yoy["semi"], battery_yoy_pct=yoy["battery"],
        display_yoy_pct=yoy["display"], chem_yoy_pct=yoy["chem"],
        steel_yoy_pct=yoy["steel"], leader_sector=leader, laggard_sector=laggard,
    )
```

- [ ] **Step 5:** test → PASS.
- [ ] **Step 6: Commit** `feat(stage1): KR sector export volume skill (B1)` (+ trailer).

---

## Task 6: 애널리스트 배선 (technical: B3 / macro_quant: B3·B5·B1)

**Files:** `technical_analyst.py`, `macro_quant_analyst.py`, `reports.py`

- [ ] **Step 1: reports.py 필드 추가** — `TechnicalReport`에 `semi_momentum: SemiMomentumSnapshot | None = None` (+ import). `MacroReport`에 `chip_cycle: ChipCycleSnapshot | None = None`, `emerging_market: EmergingMarketSnapshot | None = None`, `kr_sector_export: KRSectorExportSnapshot | None = None` (+ imports).

- [ ] **Step 2: technical 배선** — in `technical_analyst.py`, where benchmarks `bench_spy`/`bench_kospi` are fetched via `fetch_equity_index_close(...)` (~line 235), add SOX/SMH fetch + compute, mirroring the existing try/except:
```python
        try:
            sox = fetch_equity_index_close("sox", start, as_of)
            smh = fetch_equity_index_close("smh", start, as_of)
            semi_momentum = compute_semi_momentum(sox, smh, bench_spy, as_of=as_of)
        except Exception as e:  # noqa: BLE001
            logger.warning("semi_momentum fetch failed → None: %s", e)
            semi_momentum = None
```
Add `compute_semi_momentum` import; pass `semi_momentum=semi_momentum` to the `TechnicalReport(...)` constructor. (Use the actual benchmark var name found for SPY; if `bench_spy` can be `None`, `compute_semi_momentum` still handles it via `_ret` guards.)

- [ ] **Step 3: macro_quant 배선** — in `macro_quant_analyst.py`, add three `_build_*` helpers near the existing `_build_commodity_momentum` (use `fetch_fred_series_skill`/`fetch_equity_index_close`/`fetch_ecos_series_skill` and the in-scope `as_of`):
```python
def _build_chip_cycle(as_of: date) -> ChipCycleSnapshot | None:
    from tradingagents.skills.macro.fred_fetcher import fetch_fred_series_skill
    try:
        start = as_of - timedelta(days=365 * 3)
        ppi = fetch_fred_series_skill("us_chip_ppi", start, as_of, as_of_date=as_of)
        return compute_chip_cycle(ppi, as_of=as_of)
    except Exception as e:  # noqa: BLE001
        logger.warning("chip_cycle failed: %s", e)
        return None


def _build_emerging_market(as_of: date) -> EmergingMarketSnapshot | None:
    from tradingagents.dataflows.equity_indices import fetch_equity_index_close
    from tradingagents.skills.macro.fred_fetcher import fetch_fred_series_skill
    try:
        start = as_of - timedelta(days=300)
        eem = fetch_equity_index_close("eem", start, as_of)
        emb = fetch_equity_index_close("emb", start, as_of)
        dxy = fetch_fred_series_skill("dxy", start, as_of, as_of_date=as_of)
        return compute_emerging_market(eem, emb, dxy, as_of=as_of)
    except Exception as e:  # noqa: BLE001
        logger.warning("emerging_market failed: %s", e)
        return None


def _build_kr_sector_export(as_of: date) -> KRSectorExportSnapshot | None:
    from tradingagents.skills.macro.ecos_fetcher import fetch_ecos_series_skill
    try:
        start = as_of - timedelta(days=365 * 2)
        series = {
            "semi": fetch_ecos_series_skill("kr_export_semi", start, as_of, freq="M", as_of_date=as_of),
            "battery": fetch_ecos_series_skill("kr_export_battery", start, as_of, freq="M", as_of_date=as_of),
            "display": fetch_ecos_series_skill("kr_export_display", start, as_of, freq="M", as_of_date=as_of),
            "chem": fetch_ecos_series_skill("kr_export_chem", start, as_of, freq="M", as_of_date=as_of),
            "steel": fetch_ecos_series_skill("kr_export_steel", start, as_of, freq="M", as_of_date=as_of),
        }
        return compute_kr_sector_export(series, as_of=as_of)
    except Exception as e:  # noqa: BLE001
        logger.warning("kr_sector_export failed: %s", e)
        return None
```
Add the imports (`compute_chip_cycle`, `compute_emerging_market`, `compute_kr_sector_export`, and the 3 snapshot types). Call the 3 helpers near where `commodity_momentum` is built and pass `chip_cycle=...`, `emerging_market=...`, `kr_sector_export=...` into the `MacroReport(...)` constructor.

- [ ] **Step 4: Verify** — `.venv/bin/python -m pytest tests/unit -k "technical or macro_quant or reports or semi or chip or emerging or sector_export" -q` → PASS. Live smoke:
```bash
.venv/bin/python -c "
from datetime import date, timedelta
from tradingagents.dataflows.equity_indices import fetch_equity_index_close
from tradingagents.dataflows.fred import fetch_fred_series
from tradingagents.skills.macro.ecos_fetcher import fetch_ecos_series_skill
t = date(2026,6,9)
print('sox', len(fetch_equity_index_close('sox', t-timedelta(days=200), t)))
print('eem', len(fetch_equity_index_close('eem', t-timedelta(days=200), t)))
print('chip_ppi', len(fetch_fred_series('us_chip_ppi', t-timedelta(days=900), t)))
print('export_semi', len(fetch_ecos_series_skill('kr_export_semi', t-timedelta(days=730), t, freq='M', as_of_date=t)))
"
```
Expected: all non-zero.

- [ ] **Step 5: Commit** `feat(stage1): wire B3/B5/B1 into technical + macro_quant analysts` (+ trailer).

---

## Self-Review (작성자 점검)
- **Spec 커버리지**: §5.2(B3 SOX/SMH+칩PPI)→Task 2·3·6; §5.3(B5 EEM/EMB)→Task 4·6; §5.4(B1 수출물량)→Task 5·6; §6 인프라→Task 1. ✅
- **Placeholder 없음**: 모든 skill/schema 완전 코드. analyst 배선은 `_build_*` 패턴(macro_quant 기존 `_build_commodity_momentum`과 동일) + 실제 fetch 키.
- **Type 일관성**: snapshot 클래스명 ↔ skill 반환 ↔ analyst import 일치. `fetch_equity_index_close`/`fetch_ecos_series_skill`/`fetch_fred_series_skill` 실제 시그니처 사용.
- **캐시 안전**: 신규 yf 심볼은 equity_indices 개별 시리즈 캐시(cross_asset 캐시키 변경 회피).
- **주의(실행자)**: technical_analyst의 SPY 벤치 변수명을 실제 코드로 확인. macro_quant `_build_*` 호출 위치와 `MacroReport(...)` 인자 추가를 함께 적용(누락 시 필드 미반영). 월간 ECOS staleness는 publication_lag 30으로 흡수.
