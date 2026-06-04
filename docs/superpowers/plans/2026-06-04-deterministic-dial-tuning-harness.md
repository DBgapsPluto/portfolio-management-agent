# 결정론 다이얼 튜닝 하네스 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** vol_haircut `floor`×`margin` 다이얼을 과거 4개 날짜에서 sweep해 realized forward Sharpe(63거래일)로 점수화하고 레짐 전반 robust 값을 *추천*하는 하네스 (`scripts/tune_dials.py`). 자동 적용 안 함.

**Architecture:** trader 노드에 `cached_tilt`(LLM skip)·`portfolio_dials`(floor/margin override)를 주입 가능하게 plumbing. 하네스는 `restore_state(date,"allocator")`로 아카이브 복원 → allocator 1회로 LLM tilt 캡처 → grid를 cached_tilt로 재실행(LLM 무호출, ms) → forward 성과 채점.

**Tech Stack:** Python 3.13, pytest, pandas/numpy. 기존 `fetch_returns_matrix`·`backtest/statistics`·`observability/replay` 재사용.

**Spec:** `docs/superpowers/specs/2026-06-04-deterministic-dial-tuning-harness-design.md`

**탐색으로 확정된 사실(구현자 참고):** 4개 날짜(2022-12-15/2023-04-14/2024-08-14/2025-04-15) 전부 `~/.tradingagents/runs/{date}/` 아카이브 존재. `technical_report.json`에 `factor_panel`(realized_vol_60d) 포함. `restore_state(date, "allocator")` + `run_stage(graph, "allocator", state, write_to_archive=False)`로 allocator 단건 재실행 가능. trader 노드 현재: tilt 호출 line 170-174, `apply_vol_haircut` line 184, attribution `step_a` line 265-272.

---

## File Structure

- **Create** `tradingagents/backtest/forward_perf.py` — `score_forward_performance(weights, as_of, horizon)`.
- **Modify** `tradingagents/agents/trader/trader_allocator.py` — cached_tilt + portfolio_dials + tilt-in-attribution.
- **Modify** `tradingagents/agents/utils/agent_states.py` — `cached_tilt`/`portfolio_dials` 옵셔널 필드.
- **Create** `scripts/tune_dials.py` — sweep 하네스.
- **Test** `tests/unit/backtest/test_forward_perf.py`, `tests/unit/agents/trader/test_trader_allocator.py` (추가).

---

## Task 1: `forward_perf.py` — realized forward 성과 점수

**Files:**
- Create: `tradingagents/backtest/forward_perf.py`
- Test: `tests/unit/backtest/test_forward_perf.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/backtest/test_forward_perf.py`:

```python
from datetime import date

import pandas as pd

import tradingagents.backtest.forward_perf as fp


def test_score_ok_basic(monkeypatch):
    idx = pd.date_range("2025-01-02", periods=60, freq="B")
    # A: alternating +0.2%/0% (mean>0, std>0), B: flat
    rm = pd.DataFrame({"A": [0.002, 0.0] * 30, "B": [0.0] * 60}, index=idx)
    monkeypatch.setattr(fp, "fetch_returns_matrix", lambda *a, **k: rm)
    out = fp.score_forward_performance({"A": 0.5, "B": 0.5}, date(2025, 1, 1), 63)
    assert out["status"] == "ok"
    assert out["n_obs"] == 60
    assert out["total_return"] > 0
    assert out["sharpe"] > 0
    assert out["max_drawdown"] <= 0


def test_score_insufficient_obs(monkeypatch):
    idx = pd.date_range("2025-01-02", periods=10, freq="B")
    rm = pd.DataFrame({"A": [0.001] * 10}, index=idx)
    monkeypatch.setattr(fp, "fetch_returns_matrix", lambda *a, **k: rm)
    out = fp.score_forward_performance({"A": 1.0}, date(2025, 1, 1), 63)
    assert out["status"] == "insufficient_data"
    assert out["n_obs"] == 10


def test_score_empty(monkeypatch):
    monkeypatch.setattr(fp, "fetch_returns_matrix", lambda *a, **k: pd.DataFrame())
    out = fp.score_forward_performance({"A": 1.0}, date(2025, 1, 1), 63)
    assert out["status"] == "insufficient_data"


def test_score_truncates_to_horizon(monkeypatch):
    idx = pd.date_range("2025-01-02", periods=200, freq="B")
    rm = pd.DataFrame({"A": [0.001] * 200}, index=idx)
    monkeypatch.setattr(fp, "fetch_returns_matrix", lambda *a, **k: rm)
    out = fp.score_forward_performance({"A": 1.0}, date(2025, 1, 1), 63)
    assert out["n_obs"] == 63   # 앞 63 거래일만
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/backtest/test_forward_perf.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tradingagents.backtest.forward_perf'`
(`tests/unit/backtest/` 디렉토리가 없으면 생성. 형제 test 디렉토리에 `__init__.py`가 없으면 추가하지 말 것.)

- [ ] **Step 3: Implement**

Create `tradingagents/backtest/forward_perf.py`:

```python
"""포트폴리오 realized forward 성과 — 결정론 다이얼 튜닝 채점 (spec 2026-06-04).

[as_of, as_of+H거래일] 구간의 포트폴리오 실현 수익/변동성/MDD/Sharpe.
기존 fetch_returns_matrix + backtest.statistics 재사용. 순수(읽기) 함수.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import pandas as pd

from tradingagents.skills.portfolio.returns_matrix import fetch_returns_matrix
from tradingagents.backtest.statistics import _sharpe, drawdown_analysis

_MIN_OBS: int = 40   # forward 데이터 부족 임계


def score_forward_performance(
    weights: dict[str, float], as_of: date, horizon_trading_days: int = 63,
) -> dict:
    """[as_of, as_of+H거래일] realized 포트 성과. n_obs<40 이면 insufficient_data."""
    tickers = [t for t, w in weights.items() if w > 0]
    if not tickers:
        return {"status": "insufficient_data", "n_obs": 0}

    end = as_of + timedelta(days=math.ceil(horizon_trading_days * 1.6))  # 거래일→캘린더 버퍼
    rm = fetch_returns_matrix(tickers, as_of, end)
    if rm is None or rm.empty:
        return {"status": "insufficient_data", "n_obs": 0}

    rm = rm.iloc[:horizon_trading_days]            # 앞 H 거래일만
    cols = [t for t in rm.columns if t in weights]
    w = pd.Series({t: weights[t] for t in cols})
    port = (rm[cols] * w).sum(axis=1)              # 일별 포트 수익

    n = int(port.shape[0])
    if n < _MIN_OBS:
        return {"status": "insufficient_data", "n_obs": n}

    arr = port.to_numpy()
    return {
        "status": "ok",
        "n_obs": n,
        "sharpe": _sharpe(arr, periods_per_year=252),
        "total_return": float((1.0 + port).prod() - 1.0),
        "ann_vol": float(port.std() * math.sqrt(252)),
        "max_drawdown": drawdown_analysis(arr)["max_drawdown"],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/backtest/test_forward_perf.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/backtest/forward_perf.py tests/unit/backtest/test_forward_perf.py
git commit -m "feat(tuning): forward 성과 점수 함수 (score_forward_performance)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Trader 노드 plumbing — cached_tilt + portfolio_dials + tilt 노출

**Files:**
- Modify: `tradingagents/agents/utils/agent_states.py`
- Modify: `tradingagents/agents/trader/trader_allocator.py`
- Test: `tests/unit/agents/trader/test_trader_allocator.py`

- [ ] **Step 1: Write the failing tests**

In `tests/unit/agents/trader/test_trader_allocator.py`, append:

```python
class _RaisingStep:
    """cached_tilt 있으면 LLM은 호출되면 안 됨 — 호출 시 실패."""
    def with_structured_output(self, schema):
        return self
    def invoke(self, prompt):
        raise AssertionError("cached_tilt 있는데 LLM이 호출됨")


def test_node_uses_cached_tilt_skips_llm(tmp_path):
    up = _universe_14(tmp_path)
    node = create_trader_allocator(_RaisingStep())
    st = _state_14(up)
    st["cached_tilt"] = BucketTilt(tilts={"b3_global_tech": 0.05})
    out = node(st)   # LLM 미호출이라 raise 안 함
    assert out["weight_vector"] is not None
    assert out["allocation_attribution"]["step_a"]["tilt"] == {"b3_global_tech": 0.05}


def test_node_portfolio_dials_override_haircut(tmp_path):
    up = _universe_14(tmp_path)
    panel = {}
    for k in GAPS_BUCKET_KEYS:
        for i in (1, 2):
            v = 0.45 if k == "b8_cyclical_commodity" else 0.12
            panel[f"T_{k}_{i}"] = SimpleNamespace(realized_vol_60d=v)
    tr = SimpleNamespace(factor_panel=panel)

    def run(floor):
        st = _state_14(up)
        st["technical_report"] = tr
        st["portfolio_dials"] = {"vol_haircut_floor": floor, "vol_haircut_margin": 0.2}
        out = create_trader_allocator(_FakeStep(BucketTilt()))(st)
        return out["bucket_target"].weights.get("b8_cyclical_commodity", 0.0)

    # floor 낮을수록 haircut 더 큼 → b8 더 작아짐
    assert run(0.5) < run(0.9)
```
(`SimpleNamespace`·`GAPS_BUCKET_KEYS`·`BucketTilt`는 기존 import에 이미 있음 — Task에서 추가됐던 vol_haircut 테스트 참고. 없으면 추가.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/agents/trader/test_trader_allocator.py -k "cached_tilt or portfolio_dials" -v`
Expected: FAIL — `_RaisingStep`이 호출돼 AssertionError, 그리고 dials override 미반영(`run(0.5)==run(0.9)`).

- [ ] **Step 3: Implement**

(a) `tradingagents/agents/utils/agent_states.py` — `BucketTilt` import + 2 필드. Find the existing `force_method` field (around line 90) and add after it:
```python
    cached_tilt: Annotated[
        Optional["BucketTilt"],
        "Pre-captured Step A tilt (tuning harness). Set → trader skips the LLM call.",
    ]
    portfolio_dials: Annotated[
        Optional[dict],
        "Deterministic dial overrides (tuning), e.g. {vol_haircut_floor, vol_haircut_margin}.",
    ]
```
Add the import near the other schema imports at the top:
```python
from tradingagents.schemas.portfolio import BucketTilt
```
(이미 import 돼 있으면 중복 추가 말 것.)

(b) `tradingagents/agents/trader/trader_allocator.py` — cached_tilt (lines 170-174):
```python
        tilt = state.get("cached_tilt") or invoke_structured_obj(
            structured_a,
            _step_a_prompt(state, quadrant, scenario, confidence, conviction, anchor, eff),
            BucketTilt(), "TraderStepA",
        )
```

(c) Same file — portfolio_dials at the `apply_vol_haircut` call (line 184). Replace:
```python
        bucket_weights = apply_vol_haircut(bucket_weights, bucket_vol)
```
with:
```python
        _dials = state.get("portfolio_dials") or {}
        _hc = {}
        if "vol_haircut_floor" in _dials:
            _hc["floor"] = _dials["vol_haircut_floor"]
        if "vol_haircut_margin" in _dials:
            _hc["margin"] = _dials["vol_haircut_margin"]
        bucket_weights = apply_vol_haircut(bucket_weights, bucket_vol, **_hc)
```

(d) Same file — expose tilt in attribution `step_a` (lines 265-272). Add a `"tilt"` key:
```python
            "step_a": {
                "quadrant": quadrant,
                "scenario": scenario,
                "confidence": confidence,
                "conviction": conviction,
                "tilt_rationale": tilt.rationale,
                "tilt": dict(tilt.tilts),
                "buckets": step_a_buckets,
            },
```

- [ ] **Step 4: Run new tests + full node file (regression)**

Run: `.venv/bin/python -m pytest tests/unit/agents/trader/test_trader_allocator.py -v`
Expected: PASS — 신규 2 + 기존 전부 (cached_tilt/portfolio_dials 미설정 시 기존 동작 불변).

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/utils/agent_states.py tradingagents/agents/trader/trader_allocator.py tests/unit/agents/trader/test_trader_allocator.py
git commit -m "feat(tuning): trader 노드 cached_tilt + portfolio_dials 주입 + tilt 노출

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `scripts/tune_dials.py` — sweep 하네스

**Files:**
- Create: `scripts/tune_dials.py`

- [ ] **Step 1: Implement the harness**

Create `scripts/tune_dials.py`:

```python
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
import statistics
from datetime import date
from pathlib import Path

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.observability.replay import restore_state, run_stage
from tradingagents.schemas.portfolio import BucketTilt
from tradingagents.backtest.forward_perf import score_forward_performance

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("tune_dials")

DATES = ["2022-12-15", "2023-04-14", "2024-08-14", "2025-04-15"]
FLOORS = [0.5, 0.6, 0.7]
MARGINS = [0.1, 0.2, 0.3]
HORIZON = 63
STAGE = "allocator"


def _capture_tilt(graph, d: str) -> BucketTilt:
    state = restore_state(d, STAGE)
    tr = state.get("technical_report")
    fp = getattr(tr, "factor_panel", None) or {}
    assert fp, f"{d}: technical_report.factor_panel 비어있음 — sweep 무의미"
    out = run_stage(graph, STAGE, state)
    tilt_dict = out["allocation_attribution"]["step_a"]["tilt"]
    return BucketTilt(tilts=tilt_dict)


def _score_combo(graph, d: str, tilt: BucketTilt, floor: float, margin: float) -> dict:
    state = restore_state(d, STAGE)
    state["cached_tilt"] = tilt
    state["portfolio_dials"] = {"vol_haircut_floor": floor, "vol_haircut_margin": margin}
    out = run_stage(graph, STAGE, state)
    weights = out["weight_vector"].weights
    return score_forward_performance(weights, date.fromisoformat(d), HORIZON)


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

    rows = []
    for floor, margin in itertools.product(args.floors, args.margins):
        per_date: dict[str, float] = {}
        for d in tilts:
            try:
                perf = _score_combo(graph, d, tilts[d], floor, margin)
                if perf.get("status") == "ok":
                    per_date[d] = round(perf["sharpe"], 3)
                else:
                    logger.warning("%s f=%s m=%s → %s (n=%s)",
                                   d, floor, margin, perf.get("status"), perf.get("n_obs"))
            except Exception as e:  # noqa: BLE001
                logger.warning("score 실패 %s f=%s m=%s: %s", d, floor, margin, e)
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
```

- [ ] **Step 2: Smoke test — 1 날짜·축소 grid (restore_state/run_stage 통합 검증)**

Run: `.venv/bin/python scripts/tune_dials.py --dates 2025-04-15 --floors 0.6 --margins 0.2`
Expected: crash 없이 완료, `=== vol_haircut sweep ===` 표 1행 출력, `artifacts/tuning/vol_haircut_sweep.json` 생성.
- 만약 `Stage 'allocator' not in graph.nodes` 에러면 → `graph.nodes` 의 실제 trader 단계 이름을 확인(`python -c "from tradingagents.graph.trading_graph import TradingAgentsGraph as G; print(sorted(G(preset_name='db_gaps').nodes))"`)하고 `STAGE` 상수를 그 이름으로 교체.
- 만약 `restore_state` 가 universe_path/capital_krw 부재로 노드에서 KeyError → 복원된 state에 `state.setdefault("universe_path","data/universe.json")`, `state.setdefault("capital_krw", 1_000_000_000)` 를 `_capture_tilt`/`_score_combo` 의 `restore_state` 직후에 추가.
- 이 스텝은 통합 디버깅 — 위 2개 외 다른 에러도 origin을 찾아 최소 수정. 절대 점수 로직(score_forward_performance)·노드(Task 2)는 바꾸지 말 것.

- [ ] **Step 3: Commit**

```bash
git add scripts/tune_dials.py
git commit -m "feat(tuning): vol_haircut sweep 하네스 (restore→cached_tilt→forward Sharpe)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

- [ ] **Step 4: Report**

스모크 결과(표 1행 + json 생성 확인)를 보고. 전체 sweep은 Task 4(컨트롤러 실행)에서.

---

## Task 4: 전체 sweep 실행 + 결과 보고 (컨트롤러가 실행)

**Files:** 코드 변경 없음 — 실행.

- [ ] **Step 1: 전체 sweep 실행**

Run: `.venv/bin/python scripts/tune_dials.py`
Expected: 4날짜 × 9조합. `artifacts/tuning/vol_haircut_sweep.json` + stdout robust Sharpe 표.

- [ ] **Step 2: 결과 해석·보고**

- median desc 정렬된 표에서 baseline(floor=0.6, margin=0.2) 대비 더 나은 조합이 있는지.
- robust(median + min) 관점에서 어떤 floor/margin이 레짐 전반 무난한지.
- forward 데이터 부족(insufficient_data)으로 빠진 (날짜,조합)이 있으면 명시.
- **자동 적용 안 함** — 사용자에게 표를 보여주고, 상수 변경 여부는 사용자가 결정.

---

## Self-Review

**1. Spec coverage:**
- §3.1 노드 plumbing(cached_tilt/portfolio_dials/tilt 노출) → Task 2 ✅
- §3.2 `score_forward_performance` → Task 1 ✅
- §3.3 sweep 하네스(restore→capture→sweep→robust median/min→json+stdout, 자동적용X) → Task 3 + Task 4 ✅
- §4 비용(아카이브 존재, LLM 무호출) → Task 3 cached_tilt 경로 ✅
- §5 에러처리(restore 실패 skip, factor_panel assert, insufficient_data 제외) → Task 1·3 ✅
- §6 테스트(단위 score·노드, 스모크) → Task 1/2/3 ✅
- §7 확장 → 제외(의도) ✅

**2. Placeholder scan:** TBD/TODO 없음. Task 3 Step 2는 통합 디버깅 가이드(구체적 fallback 코드 명시) — placeholder 아님.

**3. Type consistency:** `score_forward_performance(weights, as_of, horizon_trading_days)` 정의(Task 1) ↔ 호출 `score_forward_performance(weights, date, HORIZON)`(Task 3) 일치. `cached_tilt`(BucketTilt)·`portfolio_dials`(dict) 노드 사용(Task 2) ↔ 하네스 주입(Task 3) 일치. attribution `step_a["tilt"]`=dict(Task 2d) ↔ 하네스 캡처 `BucketTilt(tilts=tilt_dict)`(Task 3) 일치. `restore_state`/`run_stage` 시그니처 ↔ 하네스 사용 일치.
