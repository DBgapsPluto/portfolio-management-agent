# Confidence-Scaled BL Prior Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** BL prior를 regime argmax 하드선택에서 confidence 보간(`prior_w = (1−c)·W_NEUTRAL + c·QUADRANT_BASELINE[quadrant]`)으로 교체 — regime 오분류 시 graceful.

**Architecture:** 신규 순수 skill `compute_regime_confidence`(신호 일치도 c, Laplace 평활)가 매크로 스냅샷에서 c를 산출 → `RegimeClassification.signal_confidence`(Optional, code fold-in)에 저장 → `build_bl_bucket_weights`가 c로 prior를 중립(W_NEUTRAL, 위험 0.50 재정규화)과 regime baseline 사이 보간. BL 엔진·LLM confidence 불변.

**Tech Stack:** Python 3.13, pydantic v2, numpy/pandas, pytest. spec: `docs/superpowers/specs/2026-06-23-confidence-scaled-prior-design.md` (rev1, 1549786).

**테스트 실행(항상):** `PYTHONUTF8=1 PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest <path> -q -p no:cacheprovider`

**정책:** 코드 변경마다 테스트 통과 + 적대적 감사 필수(사용자). MATH-1(no-view→prior_w 정확복원)·회귀 0(default 1.0) 보존. 브랜치 `rework/pipeline-methodology`.

---

## File Structure

| 파일 | 책임 | 변경 |
|---|---|---|
| `tradingagents/skills/macro/regime_confidence.py` (신규) | 신호 일치도 c (순수) | Task 1 |
| `tradingagents/schemas/macro.py` | RegimeClassification | Task 2: `signal_confidence` 필드 |
| `tradingagents/agents/analysts/macro_quant_analyst.py` | regime fold-in | Task 3: 양 분기 주입 |
| `tradingagents/agents/trader/trader_allocator.py` | W_NEUTRAL + 보간 + node 배선 | Task 4 |
| `scripts/backtest_bl_calibration.py` | c 검증 | Task 5 |

빌드 순서: Task 1(leaf) → 2 → 3 → 4(통합) → 5(검증).

---

### Task 1: `compute_regime_confidence` skill (신호 일치도)

**Files:**
- Create: `tradingagents/skills/macro/regime_confidence.py`
- Test: `tests/unit/skills/macro/test_regime_confidence.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/unit/skills/macro/test_regime_confidence.py`

```python
from types import SimpleNamespace as NS
import pytest
from tradingagents.skills.macro import regime_confidence as rc


def test_laplace_agreement_n1():
    assert rc._agreement([1], +1) == pytest.approx(2/3)      # n=1 일치
    assert rc._agreement([-1], +1) == pytest.approx(1/3)     # n=1 불일치
    assert rc._agreement([], +1) == 0.0                       # n=0 → 0


def test_laplace_agreement_smoothing_decays():
    assert rc._agreement([1]*10, +1) == pytest.approx(11/12)  # n=10 → 0.917


def test_fresh_gate_stale_and_none_abstain():
    assert rc._fresh(None) is False
    assert rc._fresh(NS(staleness_days=99)) is False
    assert rc._fresh(NS(staleness_days=0)) is True


def test_growth_votes_sign_rules():
    snaps = {
        "us_leading": NS(recession_signal=False, cfnai_ma3=0.5, staleness_days=0),
        "yield_curve": NS(spread_10y_2y_bps=-30.0, staleness_days=0),   # 역전 → −1
        "gdp_nowcast": NS(nowcast_pct=3.5, staleness_days=0),           # >2.0 → +1
        "risk_appetite": NS(signal="neutral", staleness_days=0),        # neutral → 기권
    }
    votes = rc._growth_votes(snaps)
    assert sorted(votes) == [-1, 1, 1]   # cfnai+1, yc−1, gdp+1; risk_appetite 기권


def test_compute_confidence_all_agree_high():
    # growth_inflation 분면: 성장+ · 인플레+ 전 신호 일치
    snaps = {
        "us_leading": NS(recession_signal=False, cfnai_ma3=0.5, staleness_days=0),
        "gdp_nowcast": NS(nowcast_pct=3.5, staleness_days=0),
        "inflation": NS(momentum_3mo=4.0, core_pce_yoy=3.0, staleness_days=0),  # >3, >2 → +1,+1
    }
    c = rc.compute_regime_confidence(snaps, "growth_inflation")
    assert c > 0.5


def test_compute_confidence_cross_check_lowers_c():
    # LLM이 growth_inflation 찍었으나 인플레 신호 전부 반대(disinflation)
    snaps = {
        "us_leading": NS(recession_signal=False, cfnai_ma3=0.5, staleness_days=0),
        "gdp_nowcast": NS(nowcast_pct=3.5, staleness_days=0),
        "inflation": NS(momentum_3mo=1.0, core_pce_yoy=1.5, staleness_days=0),  # <3,<2 → −1,−1
    }
    c = rc.compute_regime_confidence(snaps, "growth_inflation")
    assert c < 0.5      # 인플레 일치도 낮아 c 하락


def test_compute_confidence_none_snapshot_no_crash():
    snaps = {"commodity_momentum": None, "chip_cycle": None,
             "gdp_nowcast": NS(nowcast_pct=3.0, staleness_days=0)}
    c = rc.compute_regime_confidence(snaps, "growth_inflation")
    assert 0.0 <= c <= 1.0   # None 기권, 예외 없음


def test_compute_confidence_output_bounded_and_bad_quadrant():
    assert rc.compute_regime_confidence({}, "growth_inflation") == 0.0   # 전 신호 없음 → c=0
    assert rc.compute_regime_confidence({}, "nonsense") == 0.0           # 미지 분면 → 0
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/unit/skills/macro/test_regime_confidence.py -q` · Expected: FAIL (module not found)

- [ ] **Step 3: 구현** — `tradingagents/skills/macro/regime_confidence.py`

```python
"""결정론 regime confidence — 신호 일치도 (LLM 자가보고 아님). spec 2026-06-23 §4.

c = growth_agreement × inflation_agreement (Laplace 평활).
각 신호는 부호(+1 확장/인플레 · −1 침체/디스인플레) 투표. stale(sentinel)·None·neutral 기권.
"""
from __future__ import annotations

STALENESS_ABSTAIN = 99   # sentinel 상수 (fetch 성공=0, 실패=99). [감사] real-stale 아닌 fetch-fail 게이트.

# quadrant → (growth_dir, inflation_dir)
_QUADRANT_DIR: dict[str, tuple[int, int]] = {
    "growth_inflation":       (+1, +1),
    "growth_disinflation":    (+1, -1),
    "recession_inflation":    (-1, +1),
    "recession_disinflation": (-1, -1),
}


def _sign(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


def _fresh(snap) -> bool:
    """fetch-fail(sentinel 99)·None 기권 게이트."""
    return snap is not None and getattr(snap, "staleness_days", STALENESS_ABSTAIN) < STALENESS_ABSTAIN


def _growth_votes(s: dict) -> list[int]:
    """성장신호 부호(+1 확장/−1 침체). neutral(0) 제외."""
    v: list[int] = []
    us = s.get("us_leading")
    if _fresh(us):
        v.append(-1 if us.recession_signal else _sign(us.cfnai_ma3))
    krl = s.get("kr_leading")
    if _fresh(krl):
        v.append(1 if krl.phase in ("expansion", "peak") else -1)
    kre = s.get("kr_export")
    if _fresh(kre):
        v.append(_sign(kre.yoy_pct))
    krb = s.get("kr_bsi")
    if _fresh(krb):
        v.append(-1 if krb.contraction_signal else _sign(krb.mfg_bsi - 100.0))
    emp = s.get("employment")
    if _fresh(emp):
        v.append(-1 if emp.sahm_rule_triggered else _sign(-emp.rate_change_3mo))
    ra = s.get("risk_appetite")
    if _fresh(ra):
        v.append({"risk_on": 1, "risk_off": -1}.get(ra.signal, 0))
    yc = s.get("yield_curve")
    if _fresh(yc):
        v.append(-1 if yc.spread_10y_2y_bps < 0 else 1)
    cn = s.get("china_leading")
    if _fresh(cn):
        v.append({"expansion": 1, "contraction": -1}.get(cn.realtime_signal, 0))
    gd = s.get("gdp_nowcast")
    if _fresh(gd):
        v.append(_sign(gd.nowcast_pct - 2.0))   # 잠재성장 상수
    return [x for x in v if x != 0]


def _inflation_votes(s: dict) -> list[int]:
    """인플레신호 부호(+1 인플레/−1 디스인플레). 레벨 우선."""
    v: list[int] = []
    infl = s.get("inflation")
    if _fresh(infl):
        v.append(_sign(infl.momentum_3mo - 3.0))            # 레짐경계 3% (레벨투표)
        if infl.core_pce_yoy is not None:
            v.append(_sign(infl.core_pce_yoy - 2.0))         # Fed 타겟
    ie = s.get("inflation_exp")
    if _fresh(ie):
        v.append({"upside": 1, "downside": -1}.get(ie.unanchored_direction, 0))
    cm = s.get("commodity_momentum")
    if _fresh(cm):
        v.append(_sign(cm.wti_3m_pct))                       # copper는 성장축만 (cross-axis 중복 회피)
    cc = s.get("chip_cycle")
    if _fresh(cc):
        v.append(1 if cc.accelerating else _sign(cc.chip_ppi_yoy_pct))
    return [x for x in v if x != 0]


def _agreement(votes: list[int], direction: int) -> float:
    """Laplace 평활: n=0→0, n≥1→(k+1)/(n+2)."""
    n = len(votes)
    if n == 0:
        return 0.0
    k = sum(1 for x in votes if x == direction)
    return (k + 1) / (n + 2)


def compute_regime_confidence(snapshots: dict, quadrant: str) -> float:
    """신호 일치도 c ∈ [0,1]. snapshots = {name: snapshot|None}."""
    g_dir, i_dir = _QUADRANT_DIR.get(quadrant, (0, 0))
    if g_dir == 0:
        return 0.0
    c = _agreement(_growth_votes(snapshots), g_dir) * _agreement(_inflation_votes(snapshots), i_dir)
    return max(0.0, min(1.0, c))
```

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/unit/skills/macro/test_regime_confidence.py -q` · Expected: 8 PASS

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/skills/macro/regime_confidence.py tests/unit/skills/macro/test_regime_confidence.py
git commit -m "feat(macro): compute_regime_confidence — 신호 일치도 c (Laplace, fetch-fail 기권)"
```

- [ ] **Step 6: 적대적 감사** — 부호규칙이 spec §4 표와 일치하는지, Laplace n=0/n=1 정확, None/stale/neutral 기권, c∈[0,1], cross-check(타축 반대→c↓) 확인.

---

### Task 2: `RegimeClassification.signal_confidence` 필드

**Files:**
- Modify: `tradingagents/schemas/macro.py` (`RegimeClassification`, line 94-99)
- Test: `tests/unit/schemas/test_regime_signal_confidence.py` (신규)

- [ ] **Step 1: 실패 테스트 작성**

```python
from datetime import date
from tradingagents.schemas.macro import RegimeClassification


def test_signal_confidence_optional_default_none():
    r = RegimeClassification(quadrant="growth_inflation", confidence=0.8,
                             drivers=["x"], reasoning="y", source_date=date(2026, 5, 10))
    assert r.signal_confidence is None          # LLM이 안 채워도 OK (structured-output 비강요)


def test_signal_confidence_accepts_and_bounds():
    r = RegimeClassification(quadrant="growth_inflation", confidence=0.8, drivers=["x"],
                             reasoning="y", source_date=date(2026, 5, 10), signal_confidence=0.42)
    assert r.signal_confidence == 0.42
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        r.model_copy(update={"signal_confidence": 1.5})   # le=1 위반
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/unit/schemas/test_regime_signal_confidence.py -q` · Expected: FAIL

- [ ] **Step 3: 구현** — `macro.py` `RegimeClassification`에 필드 추가:

```python
class RegimeClassification(StalenessAware):
    """Subagent output — schema-locked."""
    quadrant: RegimeQuadrant
    confidence: float = Field(ge=0, le=1)
    drivers: list[str] = Field(min_length=1, max_length=5)
    reasoning: str = Field(max_length=300)
    # 결정론 신호-일치도 c (LLM-independent, analyst가 사후 model_copy로 주입). default None →
    # with_structured_output이 LLM에 강요하지 않음. spec 2026-06-23 §3.
    signal_confidence: float | None = Field(default=None, ge=0, le=1)
```

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/unit/schemas/test_regime_signal_confidence.py -q` · Expected: PASS. 회귀: `pytest tests/unit -k regime -q` · Expected: PASS (기존 RegimeClassification 생성처 무변경 — default None)

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/schemas/macro.py tests/unit/schemas/test_regime_signal_confidence.py
git commit -m "feat(schema): RegimeClassification.signal_confidence (Optional, code-injected)"
```

- [ ] **Step 6: 적대적 감사** — Optional+default None이라 LLM structured-output·기존 생성처(degraded·테스트) 무영향 확인. prompts/macro-analysis.md는 미변경(LLM이 모르게).

---

### Task 3: `macro_quant_analyst` fold-in (양 분기)

**Files:**
- Modify: `tradingagents/agents/analysts/macro_quant_analyst.py` (degraded 분기 756-769, 정상 분기 직후 ~823)
- Test: `tests/unit/agents/test_macro_regime_confidence_foldin.py` (신규)

- [ ] **Step 1: 실패 테스트 작성** — fold-in 헬퍼를 단위 테스트(전체 analyst는 무겁다)

```python
from datetime import date
from types import SimpleNamespace as NS
from tradingagents.agents.analysts import macro_quant_analyst as mqa
from tradingagents.schemas.macro import RegimeClassification


def test_foldin_overwrites_llm_value():
    # LLM이 채운 signal_confidence를 결정론 fold-in이 덮어쓴다
    regime = RegimeClassification(quadrant="growth_inflation", confidence=0.9, drivers=["x"],
                                  reasoning="y", source_date=date(2026, 5, 10),
                                  signal_confidence=0.99)   # LLM 오염값
    snaps = {"gdp_nowcast": NS(nowcast_pct=3.0, staleness_days=0),
             "inflation": NS(momentum_3mo=4.0, core_pce_yoy=3.0, staleness_days=0)}
    out = mqa._fold_in_signal_confidence(regime, snaps)
    assert out.signal_confidence != 0.99           # 덮어써짐
    assert out.signal_confidence > 0.0             # 결정론 산출


def test_regime_snaps_builds_dict():
    # _build_regime_snaps가 로컬 스냅샷들을 skill 키로 매핑
    keys = mqa._REGIME_SNAP_KEYS
    assert "gdp_nowcast" in keys and "inflation" in keys and "commodity_momentum" in keys
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/unit/agents/test_macro_regime_confidence_foldin.py -q` · Expected: FAIL

- [ ] **Step 3: 구현** — `macro_quant_analyst.py`:

(a) import 추가 (상단, 다른 skill import 옆):
```python
from tradingagents.skills.macro.regime_confidence import compute_regime_confidence
```

(b) 모듈 레벨 헬퍼 추가 (`SENTINEL_RATIO_SKIP_LLM` 상수 근처):
```python
# regime_confidence skill에 넘길 스냅샷 키 매핑 (로컬 변수명 → skill 신호 키).
_REGIME_SNAP_KEYS = (
    "us_leading", "kr_leading", "kr_export", "kr_bsi", "employment",
    "risk_appetite", "yield_curve", "china_leading", "gdp_nowcast",
    "inflation", "inflation_exp", "commodity_momentum", "chip_cycle",
)


def _fold_in_signal_confidence(regime, snaps: dict):
    """결정론 c를 RegimeClassification에 주입(LLM값 덮어씀). D7 model_copy 패턴."""
    c = compute_regime_confidence(snaps, regime.quadrant)
    return regime.model_copy(update={"signal_confidence": c})
```

(c) 정상 분기: `classify_regime(...)` 호출(771-823) 결과 `regime` 할당 *직후*(narrative_prompt 빌드 전, ~824)에 삽입:
```python
        # 결정론 신호-일치도 c 주입 (LLM 자가보고 confidence와 별개). spec 2026-06-23.
        _regime_snaps = {
            "us_leading": us_leading, "kr_leading": kr_leading, "kr_export": kr_export,
            "kr_bsi": kr_bsi, "employment": emp, "risk_appetite": risk_appetite,
            "yield_curve": yc, "china_leading": china_leading, "gdp_nowcast": gdp_nowcast,
            "inflation": infl, "inflation_exp": inflation_exp,
            "commodity_momentum": commodity_momentum_snapshot, "chip_cycle": chip_cycle_snap,
        }
        regime = _fold_in_signal_confidence(regime, _regime_snaps)
```
(주의: 이 블록은 `if sentinel_ratio >= ...: ... else: regime = classify_regime(...)` 의 *else 끝*, 즉 if/else 양쪽이 합류한 *뒤*에 두지 말 것 — degraded는 (d)에서 0.0 강제. 정상 분기 else 블록 *내부* 마지막에 둔다.)

(d) degraded 분기: `RegimeClassification(...)` 생성(756-769) *직후*에 0.0 무조건 설정:
```python
            regime = regime.model_copy(update={"signal_confidence": 0.0})
            # sentinel≥50%는 §4 신호가 stale함을 보장 못하고 quadrant가 placeholder라,
            # spurious c 대신 0.0 강제 → BL prior 강제 중립. spec 2026-06-23 §3/§5.
```

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/unit/agents/test_macro_regime_confidence_foldin.py -q` · Expected: PASS. 회귀: `pytest tests/unit/agents -k macro -q -p no:cacheprovider` · Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/agents/analysts/macro_quant_analyst.py tests/unit/agents/test_macro_regime_confidence_foldin.py
git commit -m "feat(macro): fold deterministic signal_confidence into regime (both branches, degraded=0)"
```

- [ ] **Step 6: 적대적 감사** — 정상 분기 fold-in이 LLM값 덮어씀·snaps dict가 실제 로컬과 일치(commodity_momentum_snapshot/chip_cycle_snap None 가능)·degraded는 0.0 강제·스냅샷 변수가 그 시점 scope에 생존 확인.

---

### Task 4: `W_NEUTRAL` + prior 보간 + node 배선

**Files:**
- Modify: `tradingagents/agents/trader/trader_allocator.py` (`build_bl_bucket_weights` ~313-334, node ~424-435)
- Test: `tests/unit/agents/trader/test_confidence_scaled_prior.py` (신규)

- [ ] **Step 1: 실패 테스트 작성**

```python
import pandas as pd
import pytest
from tradingagents.agents.trader import trader_allocator as ta
from tradingagents.skills.portfolio.scenario_anchor import QUADRANT_BASELINE
from tradingagents.skills.portfolio.gaps_buckets import GROWTH_KEYS

_RISK = {"a5_gold_infl"} | set(GROWTH_KEYS)


def test_w_neutral_risk_sum_half_and_sums_to_one():
    risk = sum(ta.W_NEUTRAL[b] for b in ta.W_NEUTRAL if b in _RISK)
    assert risk == pytest.approx(0.50, abs=1e-9)         # 위험 0.50 재정규화
    assert sum(ta.W_NEUTRAL.values()) == pytest.approx(1.0, abs=1e-9)
    assert all(w >= 0 for w in ta.W_NEUTRAL.values())


def test_interpolate_prior_endpoints():
    base = QUADRANT_BASELINE["growth_disinflation"]
    p0 = ta._interpolate_prior("growth_disinflation", 0.0)
    p1 = ta._interpolate_prior("growth_disinflation", 1.0)
    assert all(p0[b] == pytest.approx(ta.W_NEUTRAL[b]) for b in p0)   # c=0 → 중립
    assert all(p1[b] == pytest.approx(base[b]) for b in p1)           # c=1 → baseline
    assert sum(p0.values()) == pytest.approx(1.0) and sum(p1.values()) == pytest.approx(1.0)


def test_risk_monotonic_recession_does_not_overshoot():
    # 침체 baseline 위험<0.50 인데 c↓ 시 0.50 으로 수렴(0.60 으로 과상승 안 함)
    def risk_of(p): return sum(p[b] for b in p if b in _RISK)
    base_risk = risk_of(QUADRANT_BASELINE["recession_disinflation"])
    r_c0 = risk_of(ta._interpolate_prior("recession_disinflation", 0.0))
    r_c1 = risk_of(ta._interpolate_prior("recession_disinflation", 1.0))
    assert r_c1 == pytest.approx(base_risk, abs=1e-9)
    assert r_c0 == pytest.approx(0.50, abs=1e-9)          # 중립으로, 0.60 아님
    assert base_risk <= r_c0 <= 0.50 + 1e-9               # 0.40→0.50 (의도적), 과상승 없음
```

- [ ] **Step 2: 실패 확인** — Run: `pytest tests/unit/agents/trader/test_confidence_scaled_prior.py -q` · Expected: FAIL

- [ ] **Step 3: 구현** — `trader_allocator.py`:

(a) 모듈 레벨 상수·헬퍼 추가 (`QUADRANT_BASELINE` import 아래, `build_bl_bucket_weights` 위):
```python
def _rescale_risk_to(weights: dict, target_risk: float, risk_keys: set) -> dict:
    """위험-proxy 합을 target_risk로 재정규화(위험·방어 각 비례 스케일). 합=1 유지."""
    risk_sum = sum(w for b, w in weights.items() if b in risk_keys)
    def_sum = 1.0 - risk_sum
    out = {}
    for b, w in weights.items():
        if b in risk_keys:
            out[b] = w * (target_risk / risk_sum) if risk_sum > 1e-12 else w
        else:
            out[b] = w * ((1.0 - target_risk) / def_sum) if def_sum > 1e-12 else w
    return out


# 위험-proxy = {a5_gold_infl} ∪ GROWTH_KEYS (mandate RISK_PROXY와 동일). [감사 F1] 위험 0.50 중립.
_RISK_PROXY_KEYS = {"a5_gold_infl"} | set(GROWTH_KEYS)
_RAW_NEUTRAL = {
    b: sum(QUADRANT_BASELINE[q][b] for q in QUADRANT_BASELINE) / len(QUADRANT_BASELINE)
    for b in next(iter(QUADRANT_BASELINE.values()))
}
W_NEUTRAL = _rescale_risk_to(_RAW_NEUTRAL, target_risk=0.50, risk_keys=_RISK_PROXY_KEYS)


def _interpolate_prior(quadrant: str, c: float) -> dict:
    """prior_w = (1−c)·W_NEUTRAL + c·QUADRANT_BASELINE[quadrant]. convex → 합=1."""
    c = max(0.0, min(1.0, float(c)))
    base_q = QUADRANT_BASELINE[quadrant]
    return {b: (1.0 - c) * W_NEUTRAL[b] + c * base_q[b] for b in base_q}
```
(`GROWTH_KEYS`는 이미 import됨 — Task BL-B6에서 추가. 없으면 `from tradingagents.skills.portfolio.gaps_buckets import GROWTH_KEYS` 추가.)

(b) `build_bl_bucket_weights` 시그니처에 `signal_confidence` 추가 + base 보간. 현재 `base = pd.Series(QUADRANT_BASELINE[quadrant])`(~318)를 교체:
```python
def build_bl_bucket_weights(as_of, quadrant, ranking, *, fx_regime="neutral",
                            credit_regime="neutral", delta=2.5, base_spread=0.04,
                            turnover_cap=0.50, signal_confidence=1.0, window_days=730):
    ...
    base = pd.Series(_interpolate_prior(quadrant, signal_confidence))   # [감사] regime baseline → 보간 prior
    ...
```
(나머지 함수 본문 — Sigma fetch, extra_views, bl_allocate(Sigma, base, ...) — 불변. `base`가 prior_w가 되어 자동 상속.)

(c) node에서 c 추출·전달. BL 분기의 `build_bl_bucket_weights(...)` 호출(~428-433)에 추가:
```python
            _sig_conf = getattr(getattr(state.get("macro_report"), "regime", None),
                                "signal_confidence", 1.0)
            bucket_weights, bl_meta = build_bl_bucket_weights(
                as_of_bl, quadrant, ranking, fx_regime=fx_regime, credit_regime=credit_regime,
                delta=float(_dials.get("bl_delta", 2.5)),
                base_spread=float(_dials.get("bl_base_spread", 0.04)),
                turnover_cap=float(_dials.get("bl_turnover_cap", 0.50)),
                signal_confidence=(1.0 if _sig_conf is None else float(_sig_conf)),
            )
```
(`_sig_conf is None → 1.0` fallback: signal_confidence 미설정 시 현 거동(prior=baseline) 유지 → 회귀 0.)

- [ ] **Step 4: 통과 확인** — Run: `pytest tests/unit/agents/trader/test_confidence_scaled_prior.py -q` · Expected: PASS. 회귀: `pytest tests/unit/agents/trader tests/unit/skills/portfolio -q -p no:cacheprovider` · Expected: PASS (기존 BL 테스트는 signal_confidence 미전달 → default 1.0 → prior=baseline → green). MATH-1: `pytest tests/unit/skills/portfolio/test_bl_combine.py -q` 불변.

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/agents/trader/trader_allocator.py tests/unit/agents/trader/test_confidence_scaled_prior.py
git commit -m "feat(bl): confidence-scaled prior interpolation (W_NEUTRAL@0.50, c from regime) — graceful regime"
```

- [ ] **Step 6: 적대적 감사** — W_NEUTRAL 위험 0.50·합1, 보간 endpoints·위험 단조성(침체 과상승 없음), default 1.0 회귀 0, MATH-1(no-view→prior_w 복원) 불변, node None-guard 확인.

---

### Task 5: c 검증 (unit/property + 라이브 스모크)

**Files:**
- Create: `tests/integration/test_confidence_scaled_prior_e2e.py`
- (선택) Modify: `scripts/backtest_bl_calibration.py` (regime-PATH A/B)

- [ ] **Step 1: end-to-end property 테스트 작성** — node를 use_bl=True로 구동, macro_report에 다른 signal_confidence를 주입해 prior가 중립↔baseline로 이동하는지 검증 (Task BL-B6의 `test_trader_allocator_bl_branch.py` 픽스처·monkeypatch 패턴 재사용)

```python
# 핵심 assert: macro_report.regime.signal_confidence=0.0 → bucket_target ≈ W_NEUTRAL(위험~0.50);
#             =1.0 → bucket_target ≈ QUADRANT_BASELINE[quadrant](위험 baseline값);
#             둘의 L1 차이 > 0 (c가 실제로 prior를 움직임).
def test_node_prior_moves_with_signal_confidence(monkeypatch, <fixtures>):
    # fetch_bucket_proxy_returns monkeypatch(합성 14버킷), bl_fixed_ranking={} (no-view),
    # macro_report.regime.signal_confidence 를 0.0 / 1.0 로 두 번 실행 후 bucket_target 비교.
    ...  # no-view라 prior_w가 그대로 복원(MATH-1) → c=0 위험≈0.50, c=1 위험≈baseline
```
> 구현자 메모: no-view(`bl_fixed_ranking={}`)이면 MATH-1로 bucket_target ≈ prior_w. 따라서 c=0 → 위험≈0.50, c=1 → 위험≈baseline. 두 run의 위험% 차이로 "c가 prior를 움직임"을 직접 검증. fixture는 `test_trader_allocator_bl_branch.py` 재사용.

- [ ] **Step 2: 실행** — Run: `pytest tests/integration/test_confidence_scaled_prior_e2e.py -q -p no:cacheprovider` · Expected: PASS

- [ ] **Step 3: 라이브 스모크** — 데모 run(전체 파이프라인) 1회: `macro_report.regime.signal_confidence` 산출값 + BL prior가 baseline 대비 중립으로 당겨진 정도를 출력·확인(코드변경 아님, 검증).

- [ ] **Step 4: (선택) regime-PATH A/B backtest** — `scripts/backtest_bl_calibration.py`에 `--regime-path` 모드 추가: 매월말 `tradingagents/backtest/classify.py::assign_cycle`로 PIT quadrant 산출 → `regime-swap(c=1) vs confidence-scaled(compute_regime_confidence)` 누적수익·MDD 비교(2020-03·2022 전환 윈도우 슬라이스). graceful 버전이 전환구간서 나은지 실증. *데이터/하네스 가용 시.*

- [ ] **Step 5: 커밋**

```bash
git add tests/integration/test_confidence_scaled_prior_e2e.py
git commit -m "test(bl): confidence-scaled prior e2e — c moves prior neutral↔baseline (MATH-1 preserved)"
```

- [ ] **Step 6: 적대적 감사** — c가 실제로 prior를 움직이나, no-view 복원이 보간 prior로 성립하나, 라이브 산출 c가 데이터와 부합하나 확인.

---

## Self-Review (작성자 체크)

- **Spec 커버리지:** §4 skill(T1)·§3 schema/fold-in(T2/T3)·§5 W_NEUTRAL+보간+node(T4)·§6 검증(T5). degraded c=0(T3d)·None 기권(T1)·Laplace(T1)·CPI 레벨투표(T1)·위험 0.50(T4)·default 1.0 회귀(T4)·MATH-1(T4)·정직 param(skill 구조 그대로) — 전 항목 매핑. ✅
- **타입 일관성:** `compute_regime_confidence(snapshots:dict, quadrant:str)→float`(T1) → T3에서 동일 호출. `_interpolate_prior(quadrant,c)→dict`·`W_NEUTRAL:dict`(T4). `signal_confidence: float|None`(T2) → T3 fold-in·T4 node 추출 일치(None→1.0 fallback). `_REGIME_SNAP_KEYS`(T3) 키가 skill의 `s.get(...)` 키와 일치(us_leading·kr_leading·…·commodity_momentum·chip_cycle). ✅
- **placeholder:** T5 Step1·Step4는 기존 픽스처/하네스 의존이라 "구현자 메모"로 명시(완전 assert 조건 + 패턴 지정). 그 외 완전 코드. ✅
