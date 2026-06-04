# Step A 변동성 haircut Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Step A에서 고변동 버킷(유가 선물 등)을 현재 실현변동성에 비례해 결정론적으로 축소하고 저변동 버킷에 재배분한다 (유가 ~9%→~5-6%). 앵커/LLM tilt 구조는 보존(한쪽 haircut만).

**Architecture:** 순수 모듈 `vol_haircut.py`(`bucket_volatility` + `apply_vol_haircut`)를 신설하고, trader 노드가 Stage 1의 `technical_report.factor_panel[t].realized_vol_60d`를 읽어 `project_to_band` 직후·`_clamp_to_pool_capacity` 직전에 적용한다. technical_report 없으면 no-op.

**Tech Stack:** Python 3.13, pytest. 신규 데이터 fetch 없음 (factor_panel은 Stage 1 기계산).

**Spec:** `docs/superpowers/specs/2026-06-04-stepA-volatility-haircut-design.md`

---

## File Structure

- **Create** `tradingagents/skills/portfolio/vol_haircut.py` — `bucket_volatility(pool, vol_of, aum)` + `apply_vol_haircut(bucket_weights, bucket_vol)`.
- **Modify** `tradingagents/agents/trader/trader_allocator.py` — import + Step A wiring + attribution.
- **Test** `tests/unit/skills/portfolio/test_vol_haircut.py` (신규), `tests/unit/agents/trader/test_trader_allocator.py` (추가).

---

## Task 1: `vol_haircut.py` 순수 함수

**Files:**
- Create: `tradingagents/skills/portfolio/vol_haircut.py`
- Test: `tests/unit/skills/portfolio/test_vol_haircut.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/skills/portfolio/test_vol_haircut.py`:

```python
from tradingagents.skills.portfolio.vol_haircut import (
    bucket_volatility, apply_vol_haircut,
)


def test_bucket_volatility_aum_weighted():
    pool = {"b8": ["OIL", "GAS"], "a1": ["CASH"]}
    vol_of = {"OIL": 0.40, "GAS": 0.30, "CASH": 0.01}
    aum = {"OIL": 300.0, "GAS": 100.0, "CASH": 50.0}
    out = bucket_volatility(pool, vol_of, aum)
    assert abs(out["b8"] - 0.375) < 1e-9   # (0.40*300+0.30*100)/400
    assert abs(out["a1"] - 0.01) < 1e-9


def test_bucket_volatility_skips_none_and_zero():
    pool = {"b": ["X", "Y", "Z"]}
    vol_of = {"X": 0.20, "Y": None, "Z": 0.0}
    aum = {"X": 100.0, "Y": 100.0, "Z": 100.0}
    out = bucket_volatility(pool, vol_of, aum)
    assert abs(out["b"] - 0.20) < 1e-9     # only X counts


def test_bucket_volatility_omits_bucket_with_no_vol():
    out = bucket_volatility({"b": ["X"]}, {"X": None}, {"X": 100.0})
    assert "b" not in out


def test_haircut_trims_high_vol_bucket():
    bw = {"b8": 0.5, "a1": 0.5}
    bv = {"b8": 0.40, "a1": 0.10}      # ref=0.25, thr=0.30; b8 factor=max(0.6,0.75)=0.75
    out = apply_vol_haircut(bw, bv)
    assert abs(out["b8"] - 0.375) < 1e-9   # 0.5*0.75
    assert abs(out["a1"] - 0.625) < 1e-9   # freed 0.125 → a1
    assert abs(sum(out.values()) - 1.0) < 1e-9


def test_haircut_floor_caps_trim():
    bw = {"hi": 0.1, "lo": 0.9}
    bv = {"hi": 1.0, "lo": 0.10}       # ref=0.19, thr=0.228; factor=max(0.6,0.228)=0.6
    out = apply_vol_haircut(bw, bv)
    assert abs(out["hi"] - 0.06) < 1e-9    # 0.1*0.6 (floored)
    assert abs(sum(out.values()) - 1.0) < 1e-9


def test_haircut_noop_when_uniform_vol():
    bw = {"a": 0.5, "b": 0.5}
    out = apply_vol_haircut(bw, {"a": 0.20, "b": 0.20})
    assert out == bw


def test_haircut_noop_when_no_vol_data():
    bw = {"a": 0.5, "b": 0.5}
    assert apply_vol_haircut(bw, {}) == bw
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/skills/portfolio/test_vol_haircut.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tradingagents.skills.portfolio.vol_haircut'`

- [ ] **Step 3: Implement the module**

Create `tradingagents/skills/portfolio/vol_haircut.py`:

```python
"""Step A 변동성 haircut — 고변동 버킷 축소 → 저변동 재배분 (spec 2026-06-04).

리스크 일관성 오버레이(방향 베팅 아님). realized_vol_60d 기반, 결정론·순수.
technical_report(factor_panel) 부재 시 호출부가 빈 bucket_vol 전달 → no-op.
"""
from __future__ import annotations

_VOL_HAIRCUT_FLOOR: float = 0.6      # 최대 40% haircut
_VOL_HAIRCUT_MARGIN: float = 0.2     # ref 대비 20% 초과 시에만 haircut
_MIN_VOL_REDISTRIB: float = 0.03     # 재배분 가중 vol floor (cash 과집중 방지)


def bucket_volatility(
    pool: dict[str, list[str]],
    vol_of: dict[str, float | None],
    aum: dict[str, float],
) -> dict[str, float]:
    """버킷별 vol = 풀 ETF realized_vol_60d 의 AUM-가중 평균. None/0 skip.

    유효 vol 종목 0개 버킷은 결과에서 생략(haircut 대상 아님).
    """
    out: dict[str, float] = {}
    for b, tickers in pool.items():
        num = den = 0.0
        for t in tickers:
            v = vol_of.get(t)
            if v is None or v <= 0:
                continue
            a = max(aum.get(t, 0.0), 0.0)
            num += a * v
            den += a
        if den > 0:
            out[b] = num / den
    return out


def apply_vol_haircut(
    bucket_weights: dict[str, float],
    bucket_vol: dict[str, float],
    floor: float = _VOL_HAIRCUT_FLOOR,
    margin: float = _VOL_HAIRCUT_MARGIN,
) -> dict[str, float]:
    """한쪽 역변동성 haircut + 저변동 재배분. 합 보존.

    ref = bucket_weights 가중 평균 vol(포트폴리오 평균 vol). vol>ref·(1+margin) 버킷만
    factor=max(floor, thr/vol) 축소(thr=ref·(1+margin), 임계 연속). freed → 저변동(vol<ref)
    버킷에 (현재비중 / max(vol, MIN)) 비례 배분. vol 데이터 없으면 무변경.
    """
    present = {b: bucket_vol[b] for b in bucket_weights if b in bucket_vol}
    wsum = sum(bucket_weights[b] for b in present)
    if not present or wsum <= 0:
        return dict(bucket_weights)

    ref = sum(bucket_weights[b] * present[b] for b in present) / wsum
    thr = ref * (1.0 + margin)

    out = dict(bucket_weights)
    freed = 0.0
    for b in present:
        if present[b] > thr:
            factor = max(floor, thr / present[b])
            new = out[b] * factor
            freed += out[b] - new
            out[b] = new
    if freed <= 1e-12:
        return out

    recips = {b: out[b] / max(present[b], _MIN_VOL_REDISTRIB)
              for b in present if present[b] < ref and out[b] > 0}
    base = sum(recips.values())
    if base <= 1e-12:
        recips = {b: out[b] for b in present if present[b] <= thr and out[b] > 0}
        base = sum(recips.values())
    if base <= 1e-12:
        return out
    for b, wgt in recips.items():
        out[b] += freed * wgt / base
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/skills/portfolio/test_vol_haircut.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/portfolio/vol_haircut.py tests/unit/skills/portfolio/test_vol_haircut.py
git commit -m "feat(stepA): 변동성 haircut 순수 함수 (bucket_volatility/apply_vol_haircut)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: trader 노드에 변동성 haircut 배선

**Files:**
- Modify: `tradingagents/agents/trader/trader_allocator.py`
- Test: `tests/unit/agents/trader/test_trader_allocator.py`

- [ ] **Step 1: Write the failing test**

In `tests/unit/agents/trader/test_trader_allocator.py`, add `from types import SimpleNamespace` near the top imports (if not present). Then append:

```python
def test_node_vol_haircut_reduces_high_vol_bucket(tmp_path):
    """technical_report에 b8 고vol 주입 → b8 비중이 haircut 없을 때보다 감소."""
    up = _universe_14(tmp_path)
    panel = {}
    for k in GAPS_BUCKET_KEYS:
        for i in (1, 2):
            v = 0.45 if k == "b8_cyclical_commodity" else 0.12
            panel[f"T_{k}_{i}"] = SimpleNamespace(realized_vol_60d=v)
    tr = SimpleNamespace(factor_panel=panel)

    base = create_trader_allocator(_FakeStep(BucketTilt()))(_state_14(up))
    st = _state_14(up)
    st["technical_report"] = tr
    hc = create_trader_allocator(_FakeStep(BucketTilt()))(st)

    b8_base = base["bucket_target"].weights.get("b8_cyclical_commodity", 0.0)
    b8_hc = hc["bucket_target"].weights.get("b8_cyclical_commodity", 0.0)
    assert b8_hc < b8_base, f"haircut이 b8을 줄여야 함: base={b8_base}, hc={b8_hc}"


def test_node_vol_haircut_noop_without_technical_report(tmp_path):
    """technical_report 없으면 무변경(회귀 보장)."""
    up = _universe_14(tmp_path)
    out1 = create_trader_allocator(_FakeStep(BucketTilt()))(_state_14(up))
    out2 = create_trader_allocator(_FakeStep(BucketTilt()))(_state_14(up))
    assert out1["bucket_target"].weights == out2["bucket_target"].weights
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/agents/trader/test_trader_allocator.py::test_node_vol_haircut_reduces_high_vol_bucket -v`
Expected: FAIL — `assert b8_hc < b8_base` (둘이 같음; 노드가 아직 haircut 미적용)

- [ ] **Step 3: Wire the node**

In `tradingagents/agents/trader/trader_allocator.py`:

(a) Add the import after the existing `from tradingagents.skills.portfolio.scenario_anchor import (...)` block:
```python
from tradingagents.skills.portfolio.vol_haircut import (
    bucket_volatility, apply_vol_haircut,
)
```

(b) Find the two consecutive lines:
```python
        bucket_weights = project_to_band(anchor, tilt.tilts, eff_lo, eff_hi)
        bucket_weights = _clamp_to_pool_capacity(bucket_weights, pool)
```
and insert the haircut BETWEEN them, so it reads:
```python
        bucket_weights = project_to_band(anchor, tilt.tilts, eff_lo, eff_hi)
        # 변동성 haircut: 고변동 버킷 축소 → 저변동 재배분 (technical_report 없으면 no-op)
        tr = state.get("technical_report")
        fp = getattr(tr, "factor_panel", None) or {}
        vol_of = {t: getattr(fp.get(t), "realized_vol_60d", None) for t in aum}
        pool_tickers = {b: [e.ticker for e in pool.get(b, [])] for b in bucket_weights}
        bucket_vol = bucket_volatility(pool_tickers, vol_of, aum)
        bucket_weights = apply_vol_haircut(bucket_weights, bucket_vol)
        bucket_weights = _clamp_to_pool_capacity(bucket_weights, pool)
```

(c) In the `attribution` dict (currently `attribution = {"bucket_weights": ..., "realized_risk_pct": ..., "n_holdings": ...}`), add a `vol_haircut` key:
```python
        attribution = {
            "bucket_weights": bucket_weights,
            "realized_risk_pct": risk_pct,
            "n_holdings": len(weight_vector.weights),
            "vol_haircut": {"bucket_vol": bucket_vol},
        }
```

- [ ] **Step 4: Run the new tests + full node test file (regression)**

Run: `.venv/bin/python -m pytest tests/unit/agents/trader/test_trader_allocator.py -v`
Expected: PASS — new 2 + all existing (existing have no technical_report → no-op → unchanged).

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/trader/trader_allocator.py tests/unit/agents/trader/test_trader_allocator.py
git commit -m "feat(stepA): trader 노드에 변동성 haircut 적용 (project_to_band 직후)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: E2E 검증 (2026-05-29 실데이터)

**Files:** 코드 변경 없음 — 실행 검증만.

- [ ] **Step 1: 관련 스위트 회귀**

Run: `.venv/bin/python -m pytest tests/unit/skills/portfolio/test_vol_haircut.py tests/unit/agents/trader/test_trader_allocator.py tests/integration/test_plan_pipeline_mock.py -q`
Expected: PASS.

- [ ] **Step 2: E2E 재실행**

Run: `.venv/bin/python scripts/run_e2e_test.py --as-of 2026-05-29 --capital 1000000000`
Expected: EXIT 0, validation 통과. (실패 시 traceback/사유 그대로 보고하고 중단.)

- [ ] **Step 3: 유가(b8) 비중 감소 확인**

Run: `.venv/bin/python -c "import json; p=json.load(open('artifacts/2026-05-29/portfolio.json')); bt=p['bucket_target']['weights']; print('b8_cyclical_commodity=', round(bt.get('b8_cyclical_commodity',0),4)); print('vol_haircut=', p['allocation_attribution'].get('vol_haircut'))"`
Expected: b8 비중이 이전(~0.098)보다 감소(~0.05-0.07), `vol_haircut.bucket_vol`에 버킷별 vol 기록.

- [ ] **Step 4: trade_plan.csv 유가 비중 확인**

Run: `grep -E "WTI|원유|에너지" artifacts/2026-05-29/trade_plan.csv`
Expected: WTI원유선물 비중이 이전 ~8.9%보다 감소.

- [ ] **Step 5: validation·risk 확인 + 결과 보고 (코드 변경 없으니 commit 생략)**

Run: `.venv/bin/python -c "import json; p=json.load(open('artifacts/2026-05-29/portfolio.json')); print('passed=', p['validation_report']['passed'], 'risk=', p['allocation_attribution']['realized_risk_pct'])"`
Expected: passed=True, risk ≤ 0.70. 유가 비중 감소폭 + vol_haircut 값을 사용자에게 요약 보고.

---

## Self-Review

**1. Spec coverage:**
- §3 `bucket_volatility`(AUM-가중·None skip·빈버킷 생략) → Task 1 ✅ / §3 `apply_vol_haircut`(ref 비중-가중·thr·FLOOR·재배분·MIN floor) → Task 1 ✅
- §4 wiring(project_to_band 직후, technical_report 읽기, attribution) → Task 2 ✅
- §5 에러처리(report 없음 no-op, 일부 결측, 균일 vol, vol≈0) → `test_haircut_noop_when_no_vol_data`·`test_haircut_noop_when_uniform_vol`·`test_node_vol_haircut_noop_without_technical_report`·`bucket_volatility` skip 테스트 ✅
- §6 테스트(단위·통합·E2E) → Task 1/2/3 ✅
- §7 확장 → v1 제외(의도) ✅

**2. Placeholder scan:** TBD/TODO 없음. 모든 step에 실제 코드·명령·기대 출력.

**3. Type consistency:** `bucket_volatility(pool, vol_of, aum)`·`apply_vol_haircut(bucket_weights, bucket_vol)` 정의(Task 1) ↔ 노드 호출(Task 2) 시그니처 일치. `vol_of`/`pool_tickers`/`bucket_vol` 노드 구성 ↔ 함수 파라미터 타입(dict[str,list[str]] / dict[str,float|None] / dict[str,float]) 일치. `attribution["vol_haircut"]["bucket_vol"]` 키(Task 2) ↔ E2E 검증(Task 3) 일치.
