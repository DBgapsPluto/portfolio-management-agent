# 리밸런싱 엔진 Plan B — daily 감시 + 조건부 reassess 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** `gaps rebalance daily`가 현재 보유를 재평가해 드리프트·이벤트·regime 프록시를 평가하고, 발화 tier에 따라 결정론 방어 오버레이(daily/event) 또는 조건부 재진단(reassess) target을 만들어 Plan A의 `run_rebalance`로 거래계획을 산출한다.

**Architecture:** Plan A의 엔진(`reprice_holdings`/`build_rebalance_plan`/`validate_rebalance`/`run_rebalance`)은 그대로 재사용. Plan B는 **(1) 트리거 라우터**(드리프트+이벤트+reassess 프록시 → canonical tier), **(2) tier별 target 생성**(daily/event = 결정론 오버레이 on 직전 ETF weights, reassess = macro+risk 재실행 → bucket tilt → **종목 교체 0 비례 스케일**), **(3) daily 오케스트레이션 + CLI**만 추가한다.

**Tech Stack:** Python 3.12+, pytest, 기존 tradingagents 모듈(rebalance.engine/holdings/pricing, skills/mandate/risk_repair, skills/portfolio/gaps_buckets, rebalance/weekly_tilt, dataflows/pykrx_data).

**스펙:** [2026-06-07-rebalancing-engine-design.md](../specs/2026-06-07-rebalancing-engine-design.md) §5(트리거), §6.1(daily 오버레이), §6.2/6.4, §5.4(ladder)

**범위:** daily/event/reassess 경로. monthly는 Plan A 완료. GitHub Actions·알림은 Plan C.

**핵심 설계 결정 (Explore 기반):**
- **reassess ETF 변환 = bucket별 비례 스케일** — 직전 ETF weights를 bucket tilt만큼 bucket 단위로 비례 조정(종목 집합 불변). "종목 교체 최소화"의 극단(교체 0)이라 candidate_selector incumbent-bias가 불필요해짐(스펙 §6.2의 의도 충족, 더 단순).
- daily 오버레이는 직전 ETF weights에 직접 적용(종목 불변): `repair_risk_cap`(emergency_defensive/drift:defensive), 비례 확대(risk_on), 직전 목표 복원(drift:rebalance).
- tier별 target 생성 후 **Plan A `run_rebalance`** 호출(델타·band·재검증·산출물 공유). run_rebalance는 이미 tier-agnostic(floor는 monthly만).

---

## File Structure

| 파일 | 책임 | 신규/수정 |
|---|---|---|
| `tradingagents/rebalance/triggers.py` | 트리거 라우터(드리프트+이벤트+reassess 프록시 → tier) | 신규 |
| `tradingagents/rebalance/overlay.py` | daily/event 결정론 target 오버레이 | 신규 |
| `tradingagents/rebalance/reassess.py` | macro+risk 재진단 → bucket tilt → 비례 스케일 target | 신규 |
| `tradingagents/rebalance/daily_full.py` | daily 오케스트레이션(트리거→target→run_rebalance) | 신규 |
| `tradingagents/rebalance/daily_triggers.py` | `_build_context`에 current_weights·kospi_return_1d 주입 | 수정 |
| `tradingagents/reports/rebalance_rationale.py` | daily/event/reassess 결정론 템플릿(이미 기본 template 존재 — tier 라벨만) | (재사용/소수정) |
| `presets/triggers_default.yaml` | `reassess_triggers` 추가, 레거시 0.18 정리 | 수정 |
| `cli/commands/portfolio.py` | daily 분기 → daily_full.run | 수정 |
| `tests/unit/rebalance/` | 단위 테스트 | 신규 |

---

## Task 1: 트리거 컨텍스트 보강 (current_weights·KOSPI 실측)

[`daily_triggers._build_context`](../../../tradingagents/rebalance/daily_triggers.py)가 실제 보유 비중과 KOSPI 일간수익률을 쓰도록(gap #4). `any_etf_weight`를 인자 `current_weights`로 교체, `kospi_return_1d`를 `fetch_market_index("1001", …)`로 실측.

**Files:** Modify `tradingagents/rebalance/daily_triggers.py`; Test `tests/unit/rebalance/test_trigger_context.py`

- [ ] **Step 1: 테스트**

```python
# tests/unit/rebalance/test_trigger_context.py
import tradingagents.rebalance.daily_triggers as dt


def test_any_etf_weight_from_current_weights(monkeypatch):
    # 외부 fetch 전부 무력화 (값만 확인)
    monkeypatch.setattr(dt, "fetch_volatility_index", lambda k, d: type("S", (), {"current_value": 15.0})())
    monkeypatch.setattr(dt, "fetch_fred_series", lambda *a, **k: __import__("pandas").Series([1.0, 1.0]))
    monkeypatch.setattr(dt, "fetch_etf_snapshot_by_date", lambda d: __import__("pandas").DataFrame())
    monkeypatch.setattr(dt, "fetch_market_index", lambda *a, **k: __import__("pandas").Series([100.0, 102.0]), raising=False)
    ctx = dt._build_context(__import__("datetime").date(2026, 6, 8),
                            current_weights={"A069500": 0.22, "A229200": 0.10})
    assert abs(ctx["any_etf_weight"] - 0.22) < 1e-9          # 실보유 max
    assert abs(ctx["kospi_return_1d"] - 0.02) < 1e-9          # (102-100)/100


def test_falls_back_to_snapshot_when_no_current_weights(monkeypatch):
    import pandas as pd
    monkeypatch.setattr(dt, "fetch_volatility_index", lambda k, d: type("S", (), {"current_value": 15.0})())
    monkeypatch.setattr(dt, "fetch_fred_series", lambda *a, **k: pd.Series([1.0, 1.0]))
    monkeypatch.setattr(dt, "fetch_etf_snapshot_by_date",
                        lambda d: pd.DataFrame({"close": [100.0, 300.0]}))
    monkeypatch.setattr(dt, "fetch_market_index", lambda *a, **k: pd.Series([100.0, 100.0]), raising=False)
    ctx = dt._build_context(__import__("datetime").date(2026, 6, 8), current_weights=None)
    assert abs(ctx["any_etf_weight"] - 0.75) < 1e-9          # 300/400 snapshot fallback
```

- [ ] **Step 2:** `pytest tests/unit/rebalance/test_trigger_context.py -v` → FAIL.

- [ ] **Step 3: 구현** — `_build_context(as_of, current_weights=None)`:
  - 상단에 `from tradingagents.dataflows.pykrx_data import fetch_market_index` 추가(import 위치는 기존 패턴 따라 함수 내부 lazy import도 가능 — 단 테스트가 `dt.fetch_market_index`를 monkeypatch하므로 **모듈 레벨** import).
  - `kospi_return_1d`: `s = fetch_market_index("1001", as_of - timedelta(days=5), as_of)`; `(s.iloc[-1]-s.iloc[-2])/s.iloc[-2]` if `len(s)>=2` else 0.0. 예외 시 0.0.
  - `any_etf_weight`: `current_weights`가 주어지면 `max(current_weights.values(), default=0.0)`; 아니면 기존 snapshot 로직.
  - 시그니처: `def _build_context(as_of: date, current_weights: dict[str, float] | None = None)`. `run()`도 `current_weights`를 받아 전달하도록(`run(as_of, portfolio_path=None, current_weights=None)`).

- [ ] **Step 4:** `pytest tests/unit/rebalance/test_trigger_context.py -v` → PASS. 회귀: `pytest tests/ -k daily_trigger -q`.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/rebalance/daily_triggers.py tests/unit/rebalance/test_trigger_context.py
git commit -m "feat(rebalance): 트리거 컨텍스트에 실보유 비중·KOSPI 일간수익률 주입(gap#4)"
```

---

## Task 2: 트리거 라우터 (드리프트 + 이벤트 + reassess 프록시 → canonical tier)

현재 보유 비중·직전 목표·시장 컨텍스트로 발화 tier를 단일 ladder로 결정(스펙 §5.2/§5.4).

**Files:** Create `tradingagents/rebalance/triggers.py`; Test `tests/unit/rebalance/test_trigger_router.py`

- [ ] **Step 1: 테스트**

```python
# tests/unit/rebalance/test_trigger_router.py
from tradingagents.rebalance.triggers import evaluate_drift, route_tier


def _dials():
    return dict(single_etf_abs_cap=0.19, single_etf_rel_band=0.05, risk_asset_abs_cap=0.68)


def test_drift_single_abs():
    fired = evaluate_drift({"A": 0.20}, {"A": 0.15}, _dials(), is_risk=lambda t: False)
    assert "drift:rebalance" in fired      # 0.20 > 0.19


def test_drift_rel_band():
    fired = evaluate_drift({"A": 0.10, "B": 0.90}, {"A": 0.16, "B": 0.84}, _dials(),
                           is_risk=lambda t: False)
    assert "drift:rebalance" in fired      # |0.10-0.16|=0.06 > 0.05


def test_drift_risk_defensive():
    fired = evaluate_drift({"R": 0.69, "S": 0.31}, {"R": 0.60, "S": 0.40}, _dials(),
                           is_risk=lambda t: t == "R")
    assert "drift:defensive" in fired      # 위험합 0.69 > 0.68


def test_route_priority_emergency_beats_drift():
    # event emergency + drift 동시 → emergency 우선
    tier = route_tier(event_action="emergency_defensive_proposal",
                      drift_fired=["drift:rebalance"], reassess_fired=False)
    assert tier == "event:emergency_defensive"


def test_route_none_when_nothing():
    assert route_tier(event_action=None, drift_fired=[], reassess_fired=False) == "none"


def test_route_reassess_above_drift():
    tier = route_tier(event_action=None, drift_fired=["drift:rebalance"], reassess_fired=True)
    assert tier == "reassess"
```

- [ ] **Step 2:** FAIL.

- [ ] **Step 3: 구현** — `triggers.py`:

```python
"""리밸런싱 트리거 라우터 (스펙 §5). LLM 0."""
from collections.abc import Callable

from tradingagents.skills.mandate.concentration_check import HARD_SINGLE_CAP
from tradingagents.rebalance.engine import risk_total

# canonical ladder (스펙 §5.4) — 높을수록 우선
_LADDER = [
    "event:emergency_defensive", "monthly", "reassess",
    "drift:defensive", "drift:rebalance", "event:risk_on", "alert", "none",
]


def evaluate_drift(current: dict[str, float], target: dict[str, float],
                   dials: dict, is_risk: Callable[[str], bool]) -> list[str]:
    """현재 보유 비중 기준 드리프트 발화 목록."""
    fired: list[str] = []
    single_abs = dials["single_etf_abs_cap"]
    rel_band = dials["single_etf_rel_band"]
    risk_cap = dials["risk_asset_abs_cap"]
    for t, w in current.items():
        if t == "CASH":
            continue
        if w > single_abs or abs(w - target.get(t, 0.0)) > rel_band:
            fired.append("drift:rebalance")
            break
    if risk_total(current, is_risk) > risk_cap:
        fired.append("drift:defensive")
    return fired


_EVENT_TO_TIER = {
    "emergency_defensive_proposal": "event:emergency_defensive",
    "risk_on_proposal": "event:risk_on",
    "rebalance_proposal": "drift:rebalance",
    "alert": "alert",
}


def route_tier(event_action: str | None, drift_fired: list[str],
               reassess_fired: bool) -> str:
    """발화들을 canonical ladder에서 가장 높은 tier 하나로 환원."""
    candidates = set(drift_fired)
    if event_action:
        candidates.add(_EVENT_TO_TIER.get(event_action, "alert"))
    if reassess_fired:
        candidates.add("reassess")
    for tier in _LADDER:
        if tier in candidates:
            return tier
    return "none"
```

- [ ] **Step 4:** PASS + `pytest tests/unit/rebalance/ -q`.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/rebalance/triggers.py tests/unit/rebalance/test_trigger_router.py
git commit -m "feat(rebalance): 트리거 라우터(드리프트+이벤트+reassess, canonical ladder)"
```

---

## Task 3: daily/event 결정론 방어 오버레이

직전 ETF weights에 직접 적용(종목 불변). emergency_defensive=위험 축소, risk_on=위험 확대, drift:defensive=cap 안으로, drift:rebalance=직전 목표 복원(이 경우 target은 직전 목표이므로 오버레이 불필요 — 호출부에서 직전 목표를 target으로 사용).

**Files:** Create `tradingagents/rebalance/overlay.py`; Test `tests/unit/rebalance/test_overlay.py`

- [ ] **Step 1: 테스트**

```python
# tests/unit/rebalance/test_overlay.py
from tradingagents.rebalance.overlay import defensive_overlay, risk_on_overlay


def test_defensive_reduces_risk_to_target():
    w = {"R": 0.65, "S": 0.35}
    out = defensive_overlay(w, is_risk=lambda t: t == "R", defensive_target=0.55)
    assert abs(sum(out.values()) - 1.0) < 1e-9
    assert out["R"] <= 0.55 + 1e-6              # 위험 ≤ target
    assert out["S"] > 0.35                      # 안전 water-fill


def test_risk_on_increases_risk_within_cap():
    w = {"R": 0.50, "S": 0.50}
    out = risk_on_overlay(w, is_risk=lambda t: t == "R", step=0.05, hard_cap=0.70)
    assert abs(sum(out.values()) - 1.0) < 1e-9
    assert 0.50 < out["R"] <= 0.70 + 1e-6
```

- [ ] **Step 2:** FAIL.

- [ ] **Step 3: 구현** — `overlay.py`:

```python
"""daily/event 결정론 방어 오버레이 (스펙 §6.1). 종목 불변, 비중만 조정. LLM 0."""
from collections.abc import Callable

from tradingagents.skills.mandate.risk_repair import repair_risk_cap


def defensive_overlay(weights: dict[str, float], is_risk: Callable[[str], bool],
                      defensive_target: float) -> dict[str, float]:
    """위험자산을 defensive_target 까지 축소 + 안전자산 water-fill. repair_risk_cap 재사용."""
    return repair_risk_cap(weights, is_risk, cap=defensive_target)


def risk_on_overlay(weights: dict[str, float], is_risk: Callable[[str], bool],
                    step: float, hard_cap: float = 0.70) -> dict[str, float]:
    """위험자산을 step 만큼 확대(hard_cap 내). 위험·안전 비례 조정 후 정규화."""
    risk_sum = sum(w for t, w in weights.items() if is_risk(t))
    safe_sum = sum(w for t, w in weights.items() if not is_risk(t))
    if risk_sum <= 0 or safe_sum <= 0:
        return dict(weights)
    new_risk = min(risk_sum + step, hard_cap)
    rf = new_risk / risk_sum
    sf = (1.0 - new_risk) / safe_sum
    out = {t: (w * rf if is_risk(t) else w * sf) for t, w in weights.items()}
    total = sum(out.values())
    return {t: w / total for t, w in out.items()}
```

- [ ] **Step 4:** PASS + suite.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/rebalance/overlay.py tests/unit/rebalance/test_overlay.py
git commit -m "feat(rebalance): daily/event 결정론 방어 오버레이(defensive/risk_on)"
```

---

## Task 4: reassess target (macro+risk 재진단 → bucket tilt → 비례 스케일)

reassess 프록시 발화 시 [`weekly_tilt.run`](../../../tradingagents/rebalance/weekly_tilt.py)로 regime 변화·tilt를 얻고, 변화가 있으면 직전 ETF weights를 **위험/안전 비례 스케일**(종목 교체 0)로 조정. 변화 없으면 None(거래 0).

**Files:** Create `tradingagents/rebalance/reassess.py`; Test `tests/unit/rebalance/test_reassess.py`

- [ ] **Step 1: 테스트** (weekly_tilt.run을 monkeypatch)

```python
# tests/unit/rebalance/test_reassess.py
import tradingagents.rebalance.reassess as ra


def test_no_regime_change_returns_none(monkeypatch):
    monkeypatch.setattr(ra, "weekly_run",
        lambda **k: type("R", (), {"regime_changed": False, "tilt_proposed": {}})())
    out = ra.reassess_target({"R": 0.6, "S": 0.4}, is_risk=lambda t: t == "R",
                             as_of="2026-06-08", previous_path=None)
    assert out is None        # 변화 없음 → 거래 안 함


def test_regime_change_tilts_risk(monkeypatch):
    monkeypatch.setattr(ra, "weekly_run",
        lambda **k: type("R", (), {"regime_changed": True,
                                   "tilt_proposed": {"risk_asset_delta": -0.05}})())
    out = ra.reassess_target({"R": 0.60, "S": 0.40}, is_risk=lambda t: t == "R",
                             as_of="2026-06-08", previous_path=None)
    assert abs(sum(out.values()) - 1.0) < 1e-9
    assert out["R"] < 0.60      # 위험 축소
    assert out["S"] > 0.40
```

- [ ] **Step 2:** FAIL.

- [ ] **Step 3: 구현** — `reassess.py`:

```python
"""조건부 재진단(reassess) target — macro+risk 재실행 → bucket tilt → 비례 스케일 (스펙 §6.2).

종목 교체 0(보유 우선 극대화): 직전 ETF weights 를 위험/안전 그룹 비례로만 조정.
"""
from collections.abc import Callable

from tradingagents.rebalance.weekly_tilt import run as weekly_run


def reassess_target(current: dict[str, float], is_risk: Callable[[str], bool],
                    as_of: str, previous_path: str | None) -> dict[str, float] | None:
    """regime 변화 시 비례 스케일 target, 변화 없으면 None."""
    result = weekly_run(as_of=as_of, previous_path=previous_path)
    if not result.regime_changed:
        return None
    delta = result.tilt_proposed.get("risk_asset_delta", 0.0)
    if delta == 0.0:
        return None
    stock = {t: w for t, w in current.items() if t != "CASH"}
    risk_sum = sum(w for t, w in stock.items() if is_risk(t))
    safe_sum = sum(w for t, w in stock.items() if not is_risk(t))
    if risk_sum <= 0 or safe_sum <= 0:
        return None
    new_risk = max(0.0, min(risk_sum + delta, 0.70))
    rf = new_risk / risk_sum
    sf = (1.0 - new_risk) / safe_sum
    out = {t: (w * rf if is_risk(t) else w * sf) for t, w in stock.items()}
    total = sum(out.values())
    return {t: w / total for t, w in out.items()}
```

- [ ] **Step 4:** PASS + suite.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/rebalance/reassess.py tests/unit/rebalance/test_reassess.py
git commit -m "feat(rebalance): reassess target(macro+risk 재진단→위험 비례 스케일)"
```

---

## Task 5: daily 오케스트레이션 (트리거 → target → run_rebalance)

직전 보유 재평가 → 트리거 평가 → tier별 target 생성 → `run_rebalance`. tier=none이면 모니터링 리포트만.

**Files:** Create `tradingagents/rebalance/daily_full.py`; Test `tests/unit/rebalance/test_daily_full.py`

- [ ] **Step 1: 테스트** (engine·triggers·daily_triggers·prices monkeypatch)

```python
# tests/unit/rebalance/test_daily_full.py
from pathlib import Path
import tradingagents.rebalance.daily_full as df
from tradingagents.dataflows.universe import Universe, ETFEntry


def _uni():
    etfs = [ETFEntry(ticker="A069500", name="x", aum_krw=1e12, underlying_index="x",
                     bucket="위험", category="국내주식_지수"),
            ETFEntry(ticker="A357870", name="y", aum_krw=1e11, underlying_index="y",
                     bucket="안전", category="금리연계형/초단기채권")]
    return Universe(version="t", etfs=etfs)


def test_none_tier_no_trades(tmp_path, monkeypatch):
    # 트리거 미발화 → tier none → 거래 0
    monkeypatch.setattr(df, "_load_prev", lambda p: ({"A069500": 50, "A357870": 50},
                                                     0, {"A069500": 0.5, "A357870": 0.5}))
    monkeypatch.setattr(df, "fetch_current_prices", lambda d: {"A069500": 10000.0, "A357870": 10000.0})
    monkeypatch.setattr(df, "load_universe", lambda p: _uni())
    monkeypatch.setattr(df, "_eval_triggers", lambda **k: ("none", {}, False))
    res = df.run(as_of="2026-06-08", previous_path=str(tmp_path), out_dir=tmp_path)
    assert res.tier == "none"
    assert res.plan == []
```

> NOTE: daily_full은 내부 helper(`_load_prev`, `_eval_triggers`)로 분해해 테스트가 외부 의존(graph 없음 — daily는 graph 미사용)을 격리한다. 실제 구현 시 helper 이름을 테스트와 일치시킬 것.

- [ ] **Step 2:** FAIL.

- [ ] **Step 3: 구현** — `daily_full.py`. 핵심 흐름:
  - `_load_prev(previous_path)` → (prev_qty, prev_cash, prev_target_weights) — `load_prev_holdings` + 직전 portfolio.json weights.
  - `prices = fetch_current_prices(as_of)`; `current = reprice_holdings(prev_qty, prev_cash, prices)`.
  - `_eval_triggers(current, prev_target, ctx_dials, as_of)`: `daily_triggers.run(current_weights=current)` → event_action; `evaluate_drift(...)`; `reassess_triggers` 평가 → `route_tier(...)` → (tier, trigger_ctx, reassess_fired).
  - tier별 target:
    - `none`/`alert` → target=current(거래 0), run_rebalance 건너뛰고 모니터링 RebalanceResult(plan=[]) 반환.
    - `event:emergency_defensive`/`drift:defensive` → `defensive_overlay(prev_target, is_risk, defensive_target)`.
    - `event:risk_on` → `risk_on_overlay(prev_target, is_risk, step)`.
    - `drift:rebalance` → target = prev_target(직전 목표 복원).
    - `reassess` → `reassess_target(current, is_risk, as_of, previous_path)`; None이면 거래 0.
  - target 결정 후 `run_rebalance(as_of, tier, capital, prev_qty, prev_cash, target_weights=target, prices, universe, clusters, previous_weights=prev_target, dials, out_dir, previous_path, deep_llm=None)`.
  - clusters: 직전 portfolio.json의 `correlation_clusters`(dict) → **빈 리스트로 시작**하되, 비어있으면 §6.4 안전장치(비중 변경 tier에서 클러스터 검증 불가 시 경고) — daily는 종목 교체 0이라 클러스터 비중 변화가 작으므로 1차로 빈 리스트 허용 + 경고 로깅. (정밀 재계산은 Plan C 확장.)
  - 반환 `RebalanceResult`(run_rebalance 결과 또는 none-tier 모니터링 result).

> daily는 graph.run을 쓰지 않는다(분석가 미실행). clusters를 Cluster 객체로 못 얻으므로, validate의 correlation은 빈 리스트(vacuous) — 종목 교체 0이라 실제 클러스터 비중 변화가 미미함을 근거로 허용하고 `logger.warning("daily: clusters 미확보 — correlation 검증 생략")`. 이 한계를 RebalanceResult/사유서에 명시.

- [ ] **Step 4:** PASS + suite.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/rebalance/daily_full.py tests/unit/rebalance/test_daily_full.py
git commit -m "feat(rebalance): daily 오케스트레이션(트리거→tier target→run_rebalance)"
```

---

## Task 6: CLI daily 분기 + triggers yaml + 통합 테스트

**Files:** Modify `cli/commands/portfolio.py`, `presets/triggers_default.yaml`; Test `tests/integration/test_daily_rebalance.py`

- [ ] **Step 1: 통합 테스트** — 직전 산출물 fixture → `daily_full.run` monkeypatch(prices/universe/weekly_tilt) → tier에 따라 산출물 생성 또는 none 모니터링. (구현에 맞춰 monkeypatch 조정.)

```python
# tests/integration/test_daily_rebalance.py — 골격
import tradingagents.rebalance.daily_full as df
def test_daily_drift_produces_plan(tmp_path, monkeypatch):
    # prev 보유가 cap 초과(drift) → drift:rebalance → 거래계획 산출
    ...  # _eval_triggers 가 drift:rebalance 반환하도록, target=prev_target 복원
    res = df.run(as_of="2026-06-08", previous_path=str(prev), out_dir=out)
    assert res.tier in ("drift:rebalance", "none")
```

- [ ] **Step 2:** FAIL.

- [ ] **Step 3: 구현**
  - `triggers_default.yaml`에 §5.6 `rebalance.reassess_triggers`(yield_curve_regime_shift: `spread_10y_2y_bps < -50`, vol_regime_shift: `vix_change_5d > 0.30 OR (vix < 18 AND vix_change_5d < -0.30)`) 추가. 레거시 `drift_breach_imminent`(any_etf_weight>0.18)은 `legacy_018_trigger` 결정대로 alert로 강등(action: alert) 또는 제거.
  - `default_config.py` `rebalance` dials에 `single_etf_rel_band: 0.05`, `defensive_target: 0.55`, `reassess_tilt_step: 0.05` 추가(Plan A에서 일부만 등록됨 — 누락분 보강).
  - CLI `rebalance` daily 분기를 `daily_full.run(as_of=target, previous_path=previous_path, out_dir=...)`로 교체, 결과 summary·paths 출력. weekly tier choice는 제거(또는 reassess alias로 안내).

- [ ] **Step 4:** `pytest tests/integration/test_daily_rebalance.py tests/unit/rebalance/ -q` + 회귀 `pytest tests/ -m 'not slow and not eval' -q`.

- [ ] **Step 5: Commit**

```bash
git add cli/commands/portfolio.py presets/triggers_default.yaml tradingagents/default_config.py tests/integration/test_daily_rebalance.py
git commit -m "feat(rebalance): daily CLI + reassess_triggers yaml + dials 보강"
```

---

## 최종 검증
- [ ] `pytest tests/unit/rebalance/ tests/integration/ -q` → 전부 PASS
- [ ] `pytest tests/ -m 'not slow and not eval' -q` → 회귀 없음
- [ ] 수동 스모크(선택): `gaps rebalance daily --date 2026-06-08 --from artifacts/<직전>` → tier 판정 + 발화 시 산출물

## Plan B 자체 검토 노트
- **스펙 커버리지:** §5.2 드리프트=T2 · §5.3 이벤트(기존 yaml)=T1/T6 · §5.4 ladder=T2 · §5.6 reassess_triggers=T6 · §6.1 오버레이=T3 · §6.2 reassess(비례 스케일로 단순화)=T4 · daily 오케스트=T5 · CLI=T6.
- **의도된 단순화/한계:** ① reassess ETF 변환을 비례 스케일(종목 교체 0)로 — candidate_selector incumbent-bias(스펙 §6.2 후보) 불필요해짐. ② daily/reassess는 분석가 미실행이라 correlation_clusters를 Cluster 객체로 못 얻음 → correlation 검증이 vacuous; 종목 교체 0(비중만 소폭 변경)이라 클러스터 비중 변화가 미미함을 근거로 경고 로깅 후 허용. 정밀 클러스터 재계산(find_correlation_clusters on returns)은 후속.
- **구현 중 확인:** daily_triggers `run()` 시그니처 변경(current_weights 추가) 호출부, weekly_tilt.run 반환 구조, fetch_market_index 코드("1001"=KOSPI), default_config dials 키 누락분.
