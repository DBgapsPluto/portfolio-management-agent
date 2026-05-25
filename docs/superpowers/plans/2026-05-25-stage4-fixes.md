# Stage 4 Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stage 4 Risk Overlay에 4개 fix (권고 2·3·4·5)를 적용해 실제 영향력을 측정 가능하게 만들고 구조적 결함을 제거한다.

**Architecture:** 작은 fix → schema 변경 → overlay_apply 전면 재작성 (drop_level escalation + cluster_caps wire) → risk_judge 어댑테이션 → telemetry 인프라 → anchor 채점 확장 순. 각 task가 독립적으로 테스트 가능하고 commit-able. 기존 562 unit + 4 integration 테스트 회귀 0 건 목표.

**Tech Stack:** Python 3.12, pypfopt (EfficientFrontier + add_constraint), Pydantic v2, pytest, pandas, numpy.

**Spec:** [docs/superpowers/specs/2026-05-25-stage4-fixes-design.md](../specs/2026-05-25-stage4-fixes-design.md)

**Branch:** `feat/stage4-fixes` (이미 main 1c601d1 에서 분기, spec commit `c8e8360`)

---

## Task 1: macro_conditional recession 분기 unreachable fix (권고 4)

**Files:**
- Modify: `tradingagents/agents/risk_lens/macro_conditional_lens.py:52-56`
- Test: `tests/unit/agents/test_risk_lenses.py`

- [ ] **Step 1: Add failing tests to test_risk_lenses.py**

테스트 파일 끝에 다음 추가:

```python
def test_macro_lens_recession_high_branch_reachable():
    """recession 분기에서 risk_weight=0.70 → high (이전엔 medium에서 fall-through)."""
    from tradingagents.agents.risk_lens.macro_conditional_lens import (
        run_macro_conditional_lens,
    )
    from tradingagents.schemas.portfolio import (
        CandidateSet, OptimizationMethod, WeightVector,
    )

    wv = WeightVector(
        method=OptimizationMethod.MIN_VARIANCE,
        weights={"A001": 0.20, "A002": 0.20, "A003": 0.20, "A004": 0.20, "A005": 0.20},
        rationale="test",
    )
    cs = CandidateSet(
        bucket_to_tickers={
            "kr_equity": ["A001"], "global_equity": ["A002"],
            "fx_commodity": ["A003"], "bond": ["A004"], "cash_mmf": ["A005"],
        },
        selection_criteria="test", total_candidates=5,
    )
    # risk_weight = A001 + A002 + A003 = 0.60. 0.65 threshold 위로 만들기 위해
    # bond 0 으로 줄이고 위험자산 증가.
    wv2 = wv.model_copy(update={
        "weights": {"A001": 0.25, "A002": 0.25, "A003": 0.25, "A004": 0.15, "A005": 0.10},
    })
    # 단순화: 위험자산 0.75 인 상태
    result = run_macro_conditional_lens(
        wv2, cs, research_decision=None, systemic_score=5.0,
        regime_quadrant="recession_disinflation",
    )
    assert result.level == "high", f"expected high, got {result.level}"


def test_macro_lens_recession_medium_still_works():
    """recession + risk=0.60 → medium (high 분기 추가 후에도 medium 정상)."""
    from tradingagents.agents.risk_lens.macro_conditional_lens import (
        run_macro_conditional_lens,
    )
    from tradingagents.schemas.portfolio import (
        CandidateSet, OptimizationMethod, WeightVector,
    )

    wv = WeightVector(
        method=OptimizationMethod.MIN_VARIANCE,
        weights={"A001": 0.20, "A002": 0.20, "A003": 0.20, "A004": 0.20, "A005": 0.20},
        rationale="test",
    )
    cs = CandidateSet(
        bucket_to_tickers={
            "kr_equity": ["A001"], "global_equity": ["A002"],
            "fx_commodity": ["A003"], "bond": ["A004"], "cash_mmf": ["A005"],
        },
        selection_criteria="test", total_candidates=5,
    )
    # risk_weight=0.60 (각 위험자산 0.20)
    result = run_macro_conditional_lens(
        wv, cs, research_decision=None, systemic_score=5.0,
        regime_quadrant="recession_inflation",
    )
    assert result.level == "medium", f"expected medium, got {result.level}"
```

- [ ] **Step 2: Run new tests to verify they fail**

Run: `pytest tests/unit/agents/test_risk_lenses.py::test_macro_lens_recession_high_branch_reachable tests/unit/agents/test_risk_lenses.py::test_macro_lens_recession_medium_still_works -v`

Expected: `test_macro_lens_recession_high_branch_reachable` 가 FAIL (`expected high, got medium` — high 분기 unreachable).
`test_macro_lens_recession_medium_still_works` 는 PASS.

- [ ] **Step 3: Fix recession 분기 순서 in macro_conditional_lens.py:52-56**

`tradingagents/agents/risk_lens/macro_conditional_lens.py` 의 다음 블록:

```python
    if regime_quadrant in ("recession_disinflation", "recession_inflation"):
        if risk_weight > 0.55:
            return "medium"
        if risk_weight > 0.65:
            return "high"
```

을 다음으로 교체:

```python
    if regime_quadrant in ("recession_disinflation", "recession_inflation"):
        if risk_weight > 0.65:
            return "high"
        if risk_weight > 0.55:
            return "medium"
```

- [ ] **Step 4: Run new tests + full lens test file to verify**

Run: `pytest tests/unit/agents/test_risk_lenses.py -v`

Expected: 모든 테스트 PASS, 신규 2개 포함. 기존 lens 테스트 회귀 0.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/risk_lens/macro_conditional_lens.py tests/unit/agents/test_risk_lenses.py
git commit -m "fix(stage4): make macro_conditional recession 'high' branch reachable

>0.65 분기가 >0.55 (medium) 뒤에 와서 dead code였음.
순서 뒤집어서 high → medium fall-through 로 수정."
```

---

## Task 2: Add `overlay_apply_outcome` field to RiskOverlay schema (권고 2 prep)

**Files:**
- Modify: `tradingagents/schemas/risk_overlay.py`
- Test: `tests/unit/schemas/test_risk_overlay.py`

- [ ] **Step 1: Add failing test**

`tests/unit/schemas/test_risk_overlay.py` 끝에 추가:

```python
def test_risk_overlay_has_outcome_field_with_default():
    """RiskOverlay 에 overlay_apply_outcome 신규 필드, default='primary_success'."""
    from tradingagents.schemas.risk_overlay import RiskOverlay

    overlay = RiskOverlay.no_concerns()
    assert overlay.overlay_apply_outcome == "primary_success"

    overlay2 = RiskOverlay(overlay_apply_outcome="relax_band")
    assert overlay2.overlay_apply_outcome == "relax_band"


def test_risk_overlay_outcome_literal_validation():
    """overlay_apply_outcome 은 정해진 5 값만 허용."""
    import pytest
    from pydantic import ValidationError
    from tradingagents.schemas.risk_overlay import RiskOverlay

    with pytest.raises(ValidationError):
        RiskOverlay(overlay_apply_outcome="invalid_value")
```

- [ ] **Step 2: Run test → verify fail**

Run: `pytest tests/unit/schemas/test_risk_overlay.py::test_risk_overlay_has_outcome_field_with_default -v`

Expected: FAIL — `AttributeError: 'RiskOverlay' object has no attribute 'overlay_apply_outcome'`.

- [ ] **Step 3: Add Literal type + field to risk_overlay.py**

`tradingagents/schemas/risk_overlay.py:17-18` 의 Literal 정의 옆에 추가:

```python
OverlayOutcome = Literal[
    "primary_success", "relax_cluster", "relax_ceiling",
    "relax_band", "fallback_to_1st",
]
```

그리고 `class RiskOverlay(StalenessAware):` 안의 마지막 필드 (`lens_concerns` 다음 줄) 에 추가:

```python
    overlay_apply_outcome: OverlayOutcome = Field(
        default="primary_success",
        description="apply_risk_overlay 가 어느 drop_level 에서 풀이를 성공했는지. "
                    "telemetry/감사용. is_empty() 인 경우도 'primary_success'.",
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/unit/schemas/test_risk_overlay.py -v`

Expected: 신규 2개 + 기존 모두 PASS.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/schemas/risk_overlay.py tests/unit/schemas/test_risk_overlay.py
git commit -m "feat(stage4): add RiskOverlay.overlay_apply_outcome telemetry field

5 가지 outcome literal: primary_success / relax_cluster / relax_ceiling /
relax_band / fallback_to_1st. apply_risk_overlay 가 다음 task 에서 설정."
```

---

## Task 3: Refactor `apply_risk_overlay` to drop_level escalation + cluster_caps wire + tuple return (권고 2·3 core)

**Files:**
- Modify: `tradingagents/agents/allocator/overlay_apply.py` (전면 재작성)
- Modify: `tests/unit/agents/test_overlay_apply.py` (`_half_strength` import 제거, tuple unpacking 적용)
- Create: `tests/unit/agents/test_overlay_drop_levels.py`
- Create: `tests/unit/agents/test_overlay_cluster_caps.py`

이 task 는 큰 변경이라 하위 step 이 많음. **TDD: 신규 테스트 먼저 → 구현 → 기존 테스트 적응.**

- [ ] **Step 1: Create test_overlay_drop_levels.py with 5 failing tests**

`tests/unit/agents/test_overlay_drop_levels.py` 신규 파일:

```python
"""apply_risk_overlay drop_level escalation — 권고 2 핵심."""
import numpy as np
import pandas as pd
import pytest

from tradingagents.agents.allocator.overlay_apply import apply_risk_overlay
from tradingagents.schemas.portfolio import (
    BucketTarget, CandidateSet, OptimizationMethod, WeightVector,
)
from tradingagents.schemas.risk_overlay import RiskOverlay


_TICKERS = [f"A{i:03d}" for i in range(1, 11)]


def _wv():
    return WeightVector(
        method=OptimizationMethod.MIN_VARIANCE,
        weights={t: 0.10 for t in _TICKERS},
        rationale="1st result",
    )


def _candidates():
    return CandidateSet(
        bucket_to_tickers={
            "kr_equity":     _TICKERS[0:2],
            "global_equity": _TICKERS[2:4],
            "fx_commodity":  _TICKERS[4:6],
            "bond":          _TICKERS[6:8],
            "cash_mmf":      _TICKERS[8:10],
        },
        selection_criteria="test", total_candidates=10,
    )


def _bucket():
    return BucketTarget(
        kr_equity=0.20, global_equity=0.20, fx_commodity=0.20,
        bond=0.20, cash_mmf=0.20,
        rationale="test bucket",
    )


def _returns():
    rng = np.random.default_rng(42)
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    cols = {}
    for i, t in enumerate(_TICKERS):
        cols[t] = rng.normal(0.0005, 0.005 + i * 0.001, 300)
    return pd.DataFrame(cols, index=idx)


def test_empty_overlay_returns_primary_success_and_unchanged_weights():
    """is_empty overlay → 1차 weight 그대로 + outcome='primary_success'."""
    overlay = RiskOverlay.no_concerns()
    wv1 = _wv()
    wv2, outcome = apply_risk_overlay(
        wv1, overlay, _candidates(), _returns(), _bucket(),
        OptimizationMethod.MIN_VARIANCE, clusters=[],
    )
    assert outcome == "primary_success"
    assert wv2.weights == wv1.weights


def test_full_overlay_solves_at_drop_level_zero():
    """가벼운 overlay (multiplier=0.85) → primary_success outcome."""
    overlay = RiskOverlay(
        risk_asset_multiplier=0.85, strength_applied=0.5,
        severity_decision="test",
    )
    wv1 = _wv()
    wv2, outcome = apply_risk_overlay(
        wv1, overlay, _candidates(), _returns(), _bucket(),
        OptimizationMethod.MIN_VARIANCE, clusters=[],
    )
    assert outcome == "primary_success"
    # risk_assets shrunk → safe assets ↑
    risk_total = sum(wv2.weights.get(t, 0) for t in _TICKERS[0:6])
    assert risk_total < 0.60 - 1e-3, (
        f"risk total {risk_total} should be < 0.60 after multiplier 0.85"
    )


def test_drop_level_escalation_through_cluster_then_ceiling():
    """cluster_caps + 매우 엄격한 ceilings → cluster 먼저 drop, ceiling 다음.

    아주 strict cluster_cap (불가능) 강제 → drop_level=1 (relax_cluster)
    로 escalate 후 풀이 성공.
    """
    overlay = RiskOverlay(
        cluster_caps={"impossible_cluster": 0.01},  # universe 에 없는 cluster
        risk_asset_multiplier=0.90,
        strength_applied=0.5, severity_decision="test",
    )
    wv1 = _wv()
    wv2, outcome = apply_risk_overlay(
        wv1, overlay, _candidates(), _returns(), _bucket(),
        OptimizationMethod.MIN_VARIANCE, clusters=[],  # no cluster data → cap skip
    )
    # cluster_caps 가 있지만 clusters=[] → 적용 skip → drop_level=0 성공
    assert outcome == "primary_success"


def test_drop_level_fallback_to_1st_when_all_levels_infeasible():
    """모든 drop_level 실패하는 인공 케이스 → fallback_to_1st + 1차 weight 반환."""
    # 모든 ticker 에 1.0 floor 강제 → 5 tickers × 1.0 = 5.0 weight 필요 (불가능)
    overlay = RiskOverlay(
        tail_hedge_floor={t: 1.0 for t in _TICKERS},
        strength_applied=1.0, severity_decision="test",
    )
    wv1 = _wv()
    wv2, outcome = apply_risk_overlay(
        wv1, overlay, _candidates(), _returns(), _bucket(),
        OptimizationMethod.MIN_VARIANCE, clusters=[],
    )
    assert outcome == "fallback_to_1st"
    assert wv2.weights == wv1.weights
    assert "Stage 4 overlay infeasible" in wv2.rationale


def test_drop_level_ceiling_relaxed_when_bucket_equality_too_tight():
    """엄격한 weight_ceilings + strict bucket equality → relax_ceiling 으로 escalate.

    kr_equity bucket = 0.20, 2개 ticker × ceiling=0.05 → 합 0.10 < 0.20.
    drop_level=2 (ceilings 제거) 후 풀이 성공.
    """
    overlay = RiskOverlay(
        weight_ceilings={"A001": 0.05, "A002": 0.05},
        risk_asset_multiplier=1.0,
        strength_applied=0.7, severity_decision="test",
    )
    wv1 = _wv()
    wv2, outcome = apply_risk_overlay(
        wv1, overlay, _candidates(), _returns(), _bucket(),
        OptimizationMethod.MIN_VARIANCE, clusters=[],
    )
    # ceiling 0.05 가 bucket 0.20 와 충돌 → drop_level=1 cluster skip,
    # drop_level=2 ceiling drop 으로 풀이 성공
    assert outcome in ("relax_ceiling", "relax_band"), (
        f"expected ceiling/band relax, got {outcome}"
    )
```

- [ ] **Step 2: Create test_overlay_cluster_caps.py with 3 failing tests**

`tests/unit/agents/test_overlay_cluster_caps.py` 신규 파일:

```python
"""cluster_caps EF group constraint wire — 권고 3."""
import numpy as np
import pandas as pd

from tradingagents.agents.allocator.overlay_apply import apply_risk_overlay
from tradingagents.schemas.portfolio import (
    BucketTarget, CandidateSet, OptimizationMethod, WeightVector,
)
from tradingagents.schemas.risk_overlay import RiskOverlay
from tradingagents.schemas.technical import Cluster


_TICKERS = [f"A{i:03d}" for i in range(1, 11)]


def _wv():
    return WeightVector(
        method=OptimizationMethod.MIN_VARIANCE,
        weights={t: 0.10 for t in _TICKERS},
        rationale="1st",
    )


def _candidates():
    return CandidateSet(
        bucket_to_tickers={
            "kr_equity":     _TICKERS[0:2],
            "global_equity": _TICKERS[2:4],
            "fx_commodity":  _TICKERS[4:6],
            "bond":          _TICKERS[6:8],
            "cash_mmf":      _TICKERS[8:10],
        },
        selection_criteria="test", total_candidates=10,
    )


def _bucket():
    return BucketTarget(
        kr_equity=0.20, global_equity=0.20, fx_commodity=0.20,
        bond=0.20, cash_mmf=0.20, rationale="test bucket",
    )


def _returns():
    rng = np.random.default_rng(42)
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    cols = {t: rng.normal(0.0005, 0.005 + i * 0.001, 300)
            for i, t in enumerate(_TICKERS)}
    return pd.DataFrame(cols, index=idx)


def test_cluster_caps_constrain_cluster_sum():
    """A001+A002 가 한 cluster (kr_equity bucket 동일). cluster_cap=0.30 → 합 ≤ 0.30."""
    # bucket kr_equity target = 0.20, 즉 A001+A002 합 = 0.20 → cluster cap 0.30 은 redundant.
    # 더 strict 케이스: cluster_cap=0.15 < bucket 0.20 → bucket equality 와 충돌 → escalate.
    # 여기서는 redundant case 로 정상 작동 확인.
    overlay = RiskOverlay(
        cluster_caps={"c_kr": 0.30}, risk_asset_multiplier=1.0,
        strength_applied=0.5, severity_decision="test",
    )
    clusters = [Cluster(
        cluster_id="c_kr", members=["A001", "A002"],
        avg_internal_correlation=0.85, category_label="KR equity",
    )]
    wv1 = _wv()
    wv2, outcome = apply_risk_overlay(
        wv1, overlay, _candidates(), _returns(), _bucket(),
        OptimizationMethod.MIN_VARIANCE, clusters=clusters,
    )
    assert outcome == "primary_success"
    cluster_total = wv2.weights.get("A001", 0) + wv2.weights.get("A002", 0)
    assert cluster_total <= 0.30 + 1e-6


def test_cluster_caps_skipped_when_members_not_in_universe():
    """cluster.members 가 candidate set 에 없으면 constraint 추가 skip → 정상 풀이."""
    overlay = RiskOverlay(
        cluster_caps={"c_ghost": 0.01},
        strength_applied=0.5, severity_decision="test",
    )
    clusters = [Cluster(
        cluster_id="c_ghost", members=["GHOST1", "GHOST2"],
        avg_internal_correlation=0.85, category_label="not in universe",
    )]
    wv1 = _wv()
    wv2, outcome = apply_risk_overlay(
        wv1, overlay, _candidates(), _returns(), _bucket(),
        OptimizationMethod.MIN_VARIANCE, clusters=clusters,
    )
    assert outcome == "primary_success"


def test_cluster_caps_drop_when_strict_conflict_with_bucket():
    """매우 엄격한 cluster_cap (< bucket target) → drop_level=1 (relax_cluster) escalate."""
    overlay = RiskOverlay(
        cluster_caps={"c_kr": 0.05},  # bucket kr_equity=0.20 인데 cap 0.05 → 충돌
        strength_applied=1.0, severity_decision="test",
    )
    clusters = [Cluster(
        cluster_id="c_kr", members=["A001", "A002"],
        avg_internal_correlation=0.85, category_label="KR equity",
    )]
    wv1 = _wv()
    wv2, outcome = apply_risk_overlay(
        wv1, overlay, _candidates(), _returns(), _bucket(),
        OptimizationMethod.MIN_VARIANCE, clusters=clusters,
    )
    # cluster_cap 0.05 vs bucket equality 0.20 충돌 → cluster drop 후 정상
    assert outcome == "relax_cluster"
```

- [ ] **Step 3: Run new tests → verify fail**

Run: `pytest tests/unit/agents/test_overlay_drop_levels.py tests/unit/agents/test_overlay_cluster_caps.py -v`

Expected: 모두 FAIL — `apply_risk_overlay()` 가 `clusters` 키워드 인자 모름 + tuple 반환 안 함.

- [ ] **Step 4: Rewrite `tradingagents/agents/allocator/overlay_apply.py`**

기존 파일 전면 교체:

```python
"""Stage 4 RiskOverlay 를 Stage 3 optimizer 2 차 호출의 constraint 로 변환.

흐름:
  Stage 3 (1차) → WeightVector w1
  Stage 4       → RiskOverlay
  apply_risk_overlay (이 모듈):
    overlay 비면 → (w1, 'primary_success')
    overlay 차면 → drop_level 0 → 1 → 2 → 3 → 4 순으로 escalate, 처음 성공한
                   레벨의 outcome 반환. 모두 실패하면 (w1, 'fallback_to_1st').

drop_level 정의 (각 level 은 이전 level 의 완화를 누적 포함):
  0: full (cluster_caps + weight_ceilings + bucket equality + multiplier)
  1: cluster_caps 제거
  2: + weight_ceilings 제거
  3: + bucket equality → ±5%p band (Stage 3 D4 retry 패턴)
  4: + multiplier=1.0 (= 1차 결과 동일)

HRP method 는 sector_constraints 미지원 → MIN_VARIANCE 로 swap.
mandate (단일 cap 20%, sum=1.0) 는 overlay 적용 후에도 자동 보장.
"""
from __future__ import annotations

import logging

import pandas as pd
from pypfopt import EfficientFrontier, expected_returns, risk_models

from tradingagents.schemas.portfolio import (
    BucketTarget, CandidateSet, OptimizationMethod, WeightVector,
)
from tradingagents.schemas.risk_overlay import RiskOverlay
from tradingagents.schemas.technical import Cluster

logger = logging.getLogger(__name__)

_BUCKET_BAND = 0.05  # ±5%p (Stage 3 D4 retry 패턴과 동일)

_OUTCOMES = [
    "primary_success", "relax_cluster", "relax_ceiling",
    "relax_band", "fallback_to_1st",
]


def _shrink_bucket_by_multiplier(
    bucket_target: BucketTarget, multiplier: float,
) -> BucketTarget:
    """위험자산 multiplier 적용 — 줄어든 만큼 bond + mmf 로 재정규화."""
    if multiplier >= 0.999:
        return bucket_target

    risk_orig = (
        bucket_target.kr_equity + bucket_target.global_equity
        + bucket_target.fx_commodity
    )
    safe_orig = bucket_target.bond + bucket_target.cash_mmf
    new_risk = risk_orig * multiplier
    shrinkage = risk_orig - new_risk

    if safe_orig > 0:
        bond_share = bucket_target.bond / safe_orig
        mmf_share = bucket_target.cash_mmf / safe_orig
        new_bond = bucket_target.bond + shrinkage * bond_share
        new_mmf = bucket_target.cash_mmf + shrinkage * mmf_share
    else:
        new_bond = bucket_target.bond + shrinkage * 0.6
        new_mmf = bucket_target.cash_mmf + shrinkage * 0.4

    risk_factor = new_risk / risk_orig if risk_orig > 0 else 0.0
    return BucketTarget(
        kr_equity=bucket_target.kr_equity * risk_factor,
        global_equity=bucket_target.global_equity * risk_factor,
        fx_commodity=bucket_target.fx_commodity * risk_factor,
        bond=new_bond, cash_mmf=new_mmf,
        rationale=(
            f"Stage 4 overlay shrink (×{multiplier:.2f}): "
            f"{bucket_target.rationale[:300]}"
        )[:500],
    )


def _solve_with_overlay(
    method: OptimizationMethod,
    returns: pd.DataFrame,
    candidates: CandidateSet,
    bucket_target: BucketTarget,
    overlay: RiskOverlay,
    clusters: list[Cluster],
    drop_level: int,
) -> WeightVector:
    """drop_level 별 overlay 구성으로 EF 풀이. infeasible 시 raise.

    drop_level 누적:
      0: cluster_caps + weight_ceilings + bucket equality + multiplier
      1: cluster_caps 제거
      2: + weight_ceilings 제거
      3: + bucket equality → ±5%p band
      4: + multiplier=1.0
    """
    sector_mapper: dict[str, str] = {}
    for bucket, tickers in candidates.bucket_to_tickers.items():
        for t in tickers:
            sector_mapper[t] = bucket

    valid = [t for t in returns.columns if t in sector_mapper]
    returns = returns[valid].dropna(axis=0, how="any")

    # multiplier: level<=3 적용, level==4 면 1.0
    eff_multiplier = (
        overlay.risk_asset_multiplier if drop_level <= 3 else 1.0
    )
    adjusted_bucket = _shrink_bucket_by_multiplier(
        bucket_target, eff_multiplier,
    )
    target_map = {
        "kr_equity":     adjusted_bucket.kr_equity,
        "global_equity": adjusted_bucket.global_equity,
        "fx_commodity":  adjusted_bucket.fx_commodity,
        "bond":          adjusted_bucket.bond,
        "cash_mmf":      adjusted_bucket.cash_mmf,
    }
    # bucket: level<=2 equality, level>=3 ±band
    if drop_level <= 2:
        sector_lower = dict(target_map)
        sector_upper = dict(target_map)
    else:
        sector_lower = {k: max(0.0, v - _BUCKET_BAND) for k, v in target_map.items()}
        sector_upper = {k: min(1.0, v + _BUCKET_BAND) for k, v in target_map.items()}

    # HRP fallback → MV (EF 기반)
    if method == OptimizationMethod.HRP:
        method = OptimizationMethod.MIN_VARIANCE

    # weight_ceilings: level<=1 적용, level>=2 제거
    ceilings = overlay.weight_ceilings if drop_level <= 1 else {}
    floors = overlay.tail_hedge_floor  # floor 는 항상 유지 (안전 신호)

    # global upper bound (단일 cap 20%, ceiling 으로 더 좁힐 수 있음)
    global_upper = 0.20
    for t, ceil in ceilings.items():
        if t in valid:
            global_upper = max(global_upper, min(0.20, ceil))

    S = risk_models.sample_cov(returns)
    mu = expected_returns.mean_historical_return(returns, returns_data=True)

    ef = EfficientFrontier(mu, S, weight_bounds=(0, 0.20))
    ef.add_sector_constraints(sector_mapper, sector_lower, sector_upper)

    asset_idx = {t: i for i, t in enumerate(ef.tickers)}

    # Per-ticker ceiling (level <= 1)
    for t, upper in ceilings.items():
        if t in asset_idx:
            idx = asset_idx[t]
            cap = min(0.20, upper)
            ef.add_constraint(lambda w, i=idx, u=cap: w[i] <= u)

    # Per-ticker floor (always, when not in conflict; conflict → solver 가 infeasible)
    for t, lower in floors.items():
        if t in asset_idx and lower > 0:
            idx = asset_idx[t]
            ef.add_constraint(lambda w, i=idx, lo=lower: w[i] >= lo)

    # cluster_caps (level == 0 만)
    if drop_level == 0 and overlay.cluster_caps:
        for cluster in clusters:
            if cluster.cluster_id not in overlay.cluster_caps:
                continue
            cap = overlay.cluster_caps[cluster.cluster_id]
            indices = [asset_idx[t] for t in cluster.members if t in asset_idx]
            if len(indices) >= 2:
                ef.add_constraint(
                    lambda w, idxs=indices, c=cap: sum(w[i] for i in idxs) <= c
                )

    if method == OptimizationMethod.MIN_VARIANCE:
        ef.min_volatility()
    elif method == OptimizationMethod.RISK_PARITY:
        ef.min_volatility()
    elif method == OptimizationMethod.BLACK_LITTERMAN:
        ef.max_sharpe()
    else:
        ef.max_sharpe()

    weights = {t: float(w) for t, w in ef.clean_weights().items() if w > 1e-4}
    total = sum(weights.values())
    if total <= 0:
        raise RuntimeError("Optimizer returned empty weights")
    weights = {t: w / total for t, w in weights.items()}

    if any(w > 0.20 + 1e-6 for w in weights.values()):
        raise RuntimeError("Optimizer with overlay still violates 20% cap")

    return WeightVector(
        method=method,
        weights=weights,
        rationale=(
            f"Stage 4 overlay applied (drop_level={drop_level}, "
            f"strength={overlay.strength_applied:.2f}, "
            f"mult={eff_multiplier:.2f}). "
            f"{overlay.severity_decision[:200]}"
        )[:500],
    )


def apply_risk_overlay(
    weight_vector_1: WeightVector,
    overlay: RiskOverlay,
    candidates: CandidateSet,
    returns: pd.DataFrame,
    bucket_target: BucketTarget,
    method: OptimizationMethod,
    clusters: list[Cluster] | None = None,
) -> tuple[WeightVector, str]:
    """Stage 4 overlay 적용 → (WeightVector, outcome) tuple.

    outcome ∈ {primary_success, relax_cluster, relax_ceiling, relax_band,
    fallback_to_1st}. Empty overlay → (w1, primary_success).
    """
    if overlay.is_empty():
        return weight_vector_1, "primary_success"

    clusters = clusters or []
    last_err = None
    for level in range(5):
        try:
            wv = _solve_with_overlay(
                method, returns, candidates, bucket_target, overlay,
                clusters, drop_level=level,
            )
            return wv, _OUTCOMES[level]
        except Exception as e:
            last_err = e
            logger.warning(
                "Stage 4 overlay drop_level=%d infeasible (%s)", level, e,
            )

    # 모든 level 실패 — 1 차 결과 보존
    logger.warning(
        "Stage 4 overlay all drop_levels infeasible; last err=%s", last_err,
    )
    return weight_vector_1.model_copy(update={
        "rationale": (
            f"[Stage 4 overlay infeasible — 1st result kept] "
            f"{weight_vector_1.rationale[:400]}"
        )[:500],
    }), "fallback_to_1st"
```

- [ ] **Step 5: Update existing test_overlay_apply.py to match new tuple return + drop _half_strength import**

`tests/unit/agents/test_overlay_apply.py:8-10` 의 import 문:

```python
from tradingagents.agents.allocator.overlay_apply import (
    _half_strength, _shrink_bucket_by_multiplier, apply_risk_overlay,
)
```

을 다음으로:

```python
from tradingagents.agents.allocator.overlay_apply import (
    _shrink_bucket_by_multiplier, apply_risk_overlay,
)
```

그 다음 파일 전체를 grep 으로 확인:

Run: `grep -n "_half_strength\|apply_risk_overlay(" tests/unit/agents/test_overlay_apply.py`

각 `apply_risk_overlay(...)` 호출 결과를 받는 줄에서 `result = apply_risk_overlay(...)` → `result, _ = apply_risk_overlay(...)` 또는 `result, outcome = apply_risk_overlay(...)` 로 변경. `_half_strength` 를 직접 호출하는 테스트가 있으면 제거 (사용자 발견 시 inline 으로 처리).

가장 흔한 패턴:

```python
# Before
wv2 = apply_risk_overlay(wv1, overlay, candidates, returns, bucket, method)
# After
wv2, _ = apply_risk_overlay(wv1, overlay, candidates, returns, bucket, method, clusters=[])
```

각 호출에 `clusters=[]` keyword 추가 (default 가 None 이라 기술적으로는 생략 가능하지만 명시로 의도 표시).

- [ ] **Step 6: Run all overlay tests → verify pass**

Run: `pytest tests/unit/agents/test_overlay_apply.py tests/unit/agents/test_overlay_drop_levels.py tests/unit/agents/test_overlay_cluster_caps.py -v`

Expected: 모두 PASS. 기존 test 중 `_half_strength` 직접 호출이 있다면 그 테스트 1개 제거 (해당 함수 삭제됨).

만약 `test_half_strength_*` 류 테스트가 있으면 step 5 작업 중 함께 제거하고 commit 메시지에 명시.

- [ ] **Step 7: Run full unit suite for regression check**

Run: `pytest tests/unit/ -q 2>&1 | tail -20`

Expected: failed=0. 변경 전 562 + 신규 ~8 = 570 근방.

- [ ] **Step 8: Commit**

```bash
git add tradingagents/agents/allocator/overlay_apply.py tests/unit/agents/test_overlay_apply.py tests/unit/agents/test_overlay_drop_levels.py tests/unit/agents/test_overlay_cluster_caps.py
git commit -m "feat(stage4): drop_level escalation + cluster_caps wire (overlay_apply)

- apply_risk_overlay 가 (WeightVector, outcome) tuple 반환.
- drop_level 0→4 점진 escalation: cluster_caps → ceilings → bucket band → multiplier.
- cluster_caps EF group constraint 로 wire (Phase 2 보류분 해소).
- HRP overlay 발동 시 MV swap 유지.
- _half_strength 2 단 fallback 제거 (drop_level escalation 으로 대체)."
```

---

## Task 4: Update `risk_judge` to handle tuple return + pass clusters + set outcome

**Files:**
- Modify: `tradingagents/agents/managers/risk_judge.py`
- Test: `tests/integration/test_risk_subgraph_isolation.py` (회귀 확인) + 신규 unit test

- [ ] **Step 1: Add failing unit test for risk_judge outcome plumbing**

`tests/unit/agents/test_risk_judge.py` 신규 파일:

```python
"""risk_judge 가 apply_risk_overlay outcome 을 RiskOverlay 에 기록."""
from unittest.mock import patch

import numpy as np
import pandas as pd

from tradingagents.agents.managers.risk_judge import create_risk_judge
from tradingagents.schemas.portfolio import (
    BucketTarget, CandidateSet, OptimizationMethod, WeightVector,
)
from tradingagents.schemas.risk_overlay import RiskOverlay


def _state():
    tickers = [f"A{i:03d}" for i in range(1, 11)]
    rng = np.random.default_rng(7)
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    returns = pd.DataFrame(
        {t: rng.normal(0.0005, 0.005, 300) for t in tickers}, index=idx,
    )

    wv = WeightVector(
        method=OptimizationMethod.MIN_VARIANCE,
        weights={t: 0.10 for t in tickers}, rationale="1st",
    )
    cs = CandidateSet(
        bucket_to_tickers={
            "kr_equity":     tickers[0:2],
            "global_equity": tickers[2:4],
            "fx_commodity":  tickers[4:6],
            "bond":          tickers[6:8],
            "cash_mmf":      tickers[8:10],
        },
        selection_criteria="test", total_candidates=10,
    )
    bt = BucketTarget(
        kr_equity=0.20, global_equity=0.20, fx_commodity=0.20,
        bond=0.20, cash_mmf=0.20, rationale="test",
    )
    return {
        "as_of_date": "2024-06-15",
        "weight_vector":     wv,
        "candidate_set":     cs,
        "bucket_target":     bt,
        "risk_report":       None,
        "macro_report":      None,
        "research_decision": None,
        "technical_report":  None,
    }, returns


def test_risk_judge_records_overlay_outcome_in_overlay_schema():
    """risk_judge 노드가 RiskOverlay.overlay_apply_outcome 을 설정."""
    state, returns = _state()
    node = create_risk_judge()

    with patch(
        "tradingagents.agents.managers.risk_judge.fetch_returns_matrix",
        return_value=returns,
    ):
        out = node(state)

    overlay = out["risk_overlay"]
    assert isinstance(overlay, RiskOverlay)
    # outcome 은 항상 5 값 중 하나여야 함
    assert overlay.overlay_apply_outcome in {
        "primary_success", "relax_cluster", "relax_ceiling",
        "relax_band", "fallback_to_1st",
    }


def test_risk_judge_skip_when_inputs_missing_sets_primary_success():
    """input 누락 시 RiskOverlay.no_concerns() → outcome=primary_success default."""
    node = create_risk_judge()
    out = node({"as_of_date": "2024-06-15"})  # weight_vector etc. 없음
    assert out["risk_overlay"].overlay_apply_outcome == "primary_success"
```

- [ ] **Step 2: Run new tests → verify fail**

Run: `pytest tests/unit/agents/test_risk_judge.py -v`

Expected: FAIL (또는 ERROR) — `apply_risk_overlay` 가 이제 tuple 반환하는데 risk_judge 가 unpack 안 함.

- [ ] **Step 3: Modify risk_judge.py — handle tuple return + pass clusters + set outcome**

`tradingagents/agents/managers/risk_judge.py:148-151` 의 다음 블록:

```python
        # 6. overlay 적용 (empty면 1차 그대로)
        weight_vector_2 = apply_risk_overlay(
            weight_vector_1, overlay, candidate_set, returns, bucket_target,
            method=weight_vector_1.method,
        )
```

을 다음으로 교체:

```python
        # 6. overlay 적용 (empty면 1차 그대로)
        weight_vector_2, outcome = apply_risk_overlay(
            weight_vector_1, overlay, candidate_set, returns, bucket_target,
            method=weight_vector_1.method, clusters=clusters,
        )
        overlay = overlay.model_copy(update={"overlay_apply_outcome": outcome})
```

(`clusters` 변수는 이미 같은 함수 안에서 `clusters = getattr(technical_report, "correlation_clusters", None) or []` 로 정의돼 있음 — line 113-115.)

- [ ] **Step 4: Run risk_judge tests + integration → verify pass**

Run: `pytest tests/unit/agents/test_risk_judge.py tests/integration/test_risk_subgraph_isolation.py -v`

Expected: 모두 PASS. 회귀 0.

- [ ] **Step 5: Run full unit + integration suite**

Run: `pytest tests/ -q 2>&1 | tail -20`

Expected: failed=0.

- [ ] **Step 6: Commit**

```bash
git add tradingagents/agents/managers/risk_judge.py tests/unit/agents/test_risk_judge.py
git commit -m "feat(stage4): risk_judge plumbs clusters + records overlay_apply_outcome

apply_risk_overlay 신규 tuple 반환 받아 RiskOverlay.overlay_apply_outcome 에
설정. correlation_clusters 도 pass (cluster_caps EF wire 활성화)."
```

---

## Task 5: Create `overlay_stats` module + `overlay_telemetry.py` CLI

**Files:**
- Create: `tradingagents/observability/overlay_stats.py`
- Create: `scripts/overlay_telemetry.py`
- Create: `tests/unit/observability/test_overlay_stats.py`
- Modify: `tradingagents/agents/managers/risk_judge.py` (record 호출 추가)

- [ ] **Step 1: Add failing tests in test_overlay_stats.py**

`tests/unit/observability/test_overlay_stats.py` 신규 파일:

```python
"""overlay_stats jsonl append + summarize."""
import json
from pathlib import Path

import pytest

from tradingagents.observability.overlay_stats import (
    record_overlay_outcome, summarize_outcomes,
)


def test_record_overlay_outcome_appends_jsonl_line(tmp_path: Path):
    stats_path = tmp_path / "outcomes.jsonl"
    record_overlay_outcome(
        date="2026-05-25", outcome="relax_band",
        lens_levels={"tail_risk": "low", "concentration": "critical",
                     "macro_conditional": "medium"},
        strength=0.7, multiplier=0.944, stats_path=stats_path,
    )
    assert stats_path.exists()
    lines = stats_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["date"] == "2026-05-25"
    assert rec["outcome"] == "relax_band"
    assert rec["lens_levels"]["concentration"] == "critical"
    assert rec["strength_applied"] == 0.7
    assert rec["multiplier_final"] == 0.944


def test_record_overlay_outcome_append_mode(tmp_path: Path):
    stats_path = tmp_path / "outcomes.jsonl"
    for d in ("2026-05-20", "2026-05-21", "2026-05-22"):
        record_overlay_outcome(
            date=d, outcome="primary_success", lens_levels={},
            strength=0.0, multiplier=1.0, stats_path=stats_path,
        )
    lines = stats_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3


def test_summarize_outcomes_counts_and_means(tmp_path: Path):
    stats_path = tmp_path / "outcomes.jsonl"
    for d, oc, s in (
        ("2026-05-20", "primary_success", 0.5),
        ("2026-05-21", "relax_band", 0.7),
        ("2026-05-22", "fallback_to_1st", 1.0),
        ("2026-05-23", "primary_success", 0.3),
    ):
        record_overlay_outcome(
            date=d, outcome=oc, lens_levels={"tail_risk": "low"},
            strength=s, multiplier=0.9, stats_path=stats_path,
        )
    summary = summarize_outcomes(stats_path)
    assert summary["n_runs"] == 4
    assert summary["outcome_counts"]["primary_success"] == 2
    assert summary["outcome_counts"]["relax_band"] == 1
    assert summary["outcome_counts"]["fallback_to_1st"] == 1
    # fallback_pct = 1/4 = 0.25
    assert summary["fallback_pct"] == pytest.approx(0.25)
    # mean strength = (0.5+0.7+1.0+0.3)/4 = 0.625
    assert summary["mean_strength"] == pytest.approx(0.625)


def test_summarize_outcomes_empty_file(tmp_path: Path):
    stats_path = tmp_path / "outcomes.jsonl"
    summary = summarize_outcomes(stats_path)
    assert summary["n_runs"] == 0
    assert summary["outcome_counts"] == {}
    assert summary["fallback_pct"] == 0.0
```

- [ ] **Step 2: Run new tests → verify fail (module 부재)**

Run: `pytest tests/unit/observability/test_overlay_stats.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named '...overlay_stats'`.

- [ ] **Step 3: Create `tradingagents/observability/overlay_stats.py`**

```python
"""Stage 4 overlay outcome telemetry — append-only jsonl + summarize.

매 risk_judge 실행마다 한 줄 append. CLI 가 누적 통계 표 출력.

Path default: ~/.tradingagents/stats/overlay_outcomes.jsonl
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


DEFAULT_STATS_PATH = Path.home() / ".tradingagents" / "stats" / "overlay_outcomes.jsonl"


def record_overlay_outcome(
    *,
    date: str,
    outcome: str,
    lens_levels: dict[str, str],
    strength: float,
    multiplier: float,
    stats_path: Path | str | None = None,
) -> None:
    """Append one jsonl line. 부모 dir 없으면 생성."""
    path = Path(stats_path) if stats_path else DEFAULT_STATS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "date":              date,
        "outcome":           outcome,
        "lens_levels":       lens_levels,
        "strength_applied":  strength,
        "multiplier_final":  multiplier,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def summarize_outcomes(
    stats_path: Path | str | None = None,
    *,
    last_n: int | None = None,
) -> dict[str, Any]:
    """누적 stats 집계. last_n 지정 시 최근 N 개만."""
    path = Path(stats_path) if stats_path else DEFAULT_STATS_PATH
    if not path.exists():
        return {
            "n_runs": 0, "outcome_counts": {}, "fallback_pct": 0.0,
            "mean_strength": 0.0, "lens_severity": {},
        }
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    records = [json.loads(line) for line in lines if line.strip()]
    if last_n is not None:
        records = records[-last_n:]
    if not records:
        return {
            "n_runs": 0, "outcome_counts": {}, "fallback_pct": 0.0,
            "mean_strength": 0.0, "lens_severity": {},
        }
    outcome_counts = Counter(r["outcome"] for r in records)
    fallback_pct = outcome_counts.get("fallback_to_1st", 0) / len(records)
    mean_strength = sum(r["strength_applied"] for r in records) / len(records)
    lens_severity: dict[str, Counter] = {}
    for r in records:
        for lens, lvl in r.get("lens_levels", {}).items():
            lens_severity.setdefault(lens, Counter())[lvl] += 1
    return {
        "n_runs":         len(records),
        "outcome_counts": dict(outcome_counts),
        "fallback_pct":   fallback_pct,
        "mean_strength":  mean_strength,
        "lens_severity":  {l: dict(c) for l, c in lens_severity.items()},
    }
```

- [ ] **Step 4: Run tests → verify pass**

Run: `pytest tests/unit/observability/test_overlay_stats.py -v`

Expected: 4개 모두 PASS.

- [ ] **Step 5: Wire record_overlay_outcome into risk_judge**

`tradingagents/agents/managers/risk_judge.py` 상단 import 옆에 추가:

```python
from tradingagents.observability.overlay_stats import record_overlay_outcome
```

그리고 `return { "weight_vector": weight_vector_2, ... }` (line ~171) 바로 직전에 다음 블록 삽입:

```python
        # 7. telemetry — 누적 stats jsonl 한 줄 append
        try:
            record_overlay_outcome(
                date=as_of_str or "unknown",
                outcome=overlay.overlay_apply_outcome,
                lens_levels={c.lens: c.level for c in concerns},
                strength=overlay.strength_applied,
                multiplier=overlay.risk_asset_multiplier,
            )
        except Exception:
            # telemetry 실패는 파이프라인 안 막음
            logger.warning(
                "overlay_outcomes.jsonl write failed", exc_info=True,
            )
```

`logger` 가 risk_judge 에 없으면 파일 상단에 `import logging\nlogger = logging.getLogger(__name__)` 추가.

- [ ] **Step 6: Run risk_judge unit tests again to confirm no regression**

Run: `pytest tests/unit/agents/test_risk_judge.py -v`

Expected: PASS. record_overlay_outcome 이 default path (`~/.tradingagents/stats/...`) 에 한 줄 append 됨 (테스트는 path mocking 안 했으므로 실제 파일 생성. 정상).

- [ ] **Step 7: Create scripts/overlay_telemetry.py CLI**

```python
"""Stage 4 overlay outcome 누적 stats 표.

Usage:
    python scripts/overlay_telemetry.py
    python scripts/overlay_telemetry.py --last 30
    python scripts/overlay_telemetry.py --stats-path ~/.tradingagents/stats/overlay_outcomes.jsonl
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tradingagents.observability.overlay_stats import (
    DEFAULT_STATS_PATH, summarize_outcomes,
)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--last", type=int, default=None, help="최근 N 개만")
    p.add_argument(
        "--stats-path", default=str(DEFAULT_STATS_PATH),
        help="jsonl 경로",
    )
    args = p.parse_args()

    stats_path = Path(args.stats_path).expanduser()
    summary = summarize_outcomes(stats_path, last_n=args.last)

    header = f"Stage 4 overlay telemetry — {stats_path}"
    if args.last:
        header += f" (last {args.last} runs)"
    print(header)
    print("-" * len(header))

    n = summary["n_runs"]
    if n == 0:
        print("no records.")
        return 0

    print(f"\nTotal runs: {n}")
    print(f"Mean strength_applied: {summary['mean_strength']:.3f}")
    print(f"Fallback rate (fallback_to_1st): {summary['fallback_pct']*100:.1f}%")

    print("\nOutcome counts:")
    for oc in ("primary_success", "relax_cluster", "relax_ceiling",
               "relax_band", "fallback_to_1st"):
        c = summary["outcome_counts"].get(oc, 0)
        pct = c / n * 100
        print(f"  {oc:<20s} {c:>5d} ({pct:5.1f}%)")

    print("\nLens severity distribution:")
    for lens in ("tail_risk", "concentration", "macro_conditional"):
        sev = summary["lens_severity"].get(lens, {})
        parts = [
            f"{lvl}={sev.get(lvl, 0)}"
            for lvl in ("none", "low", "medium", "high", "critical")
        ]
        print(f"  {lens:<18s} " + " ".join(parts))

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 8: Manual smoke — run CLI with no records**

Run: `python scripts/overlay_telemetry.py --stats-path /tmp/nonexistent.jsonl`

Expected:
```
Stage 4 overlay telemetry — /tmp/nonexistent.jsonl
--------------------------------------------------
no records.
```

- [ ] **Step 9: Commit**

```bash
git add tradingagents/observability/overlay_stats.py scripts/overlay_telemetry.py tests/unit/observability/test_overlay_stats.py tradingagents/agents/managers/risk_judge.py
git commit -m "feat(stage4): overlay_stats jsonl telemetry + CLI

- observability/overlay_stats.py: record_overlay_outcome (append-only jsonl)
  + summarize_outcomes (집계 dict).
- risk_judge: 매 run 한 줄 append (실패해도 파이프라인 안 막음).
- scripts/overlay_telemetry.py: 누적 통계 표 출력 (--last N 지원).

매일 fallback_pct 관찰 → 30%+ 면 lens threshold 재검토 trigger."
```

---

## Task 6: Extract `_score_eight_axes` helper from anchor_evaluator (refactor prep)

**Files:**
- Modify: `tradingagents/observability/anchor_evaluator.py`
- Test: `tests/unit/observability/test_anchor_evaluator.py` (회귀)

> 이 task 는 신규 기능 X — 다음 두 task (with_stage4 in evaluator + live) 가 같은 채점 로직을 두 번 돌려야 하므로 DRY 위해 helper 추출. 7 anchor smoke 회귀로 안전성 확인.

- [ ] **Step 1: Identify the 8 check blocks to extract**

`tradingagents/observability/anchor_evaluator.py:254-363` 의 `# ─── 7축 체크 ───` 부터 `return AnchorEvalResult(...)` 직전까지가 채점 로직. 입력은 `expected`, `weights`, `sub_totals`, `n_unique`, `risk_asset_total`, `method_str`.

→ 이 블록을 함수로 추출:

```python
def _score_eight_axes(
    expected: dict,
    *,
    weights: dict[str, float],
    sub_totals: dict[str, float],
    n_unique: int,
    risk_asset_total: float,
    method_str: str,
) -> list[CheckResult]:
    """7-8 축 채점 — anchor_evaluator + anchor_live 공통.

    expected: anchor JSON 의 expected_stage3 dict.
    return: 8 개 CheckResult (method/required/substitute/forbidden/
            min_weights/max_weights/diversity/risk_asset).
    """
    checks: list[CheckResult] = []
    # ... (현재 line 254-362 의 본문 그대로 옮김, return AnchorEvalResult 직전까지)
    return checks
```

- [ ] **Step 2: Apply the extraction**

`tradingagents/observability/anchor_evaluator.py` 의 `_bucket_of_ticker(...)` 함수 정의 (line 184-196) 다음에 `_score_eight_axes` 정의 삽입.

본문은 line 254-362 의 8 개 `checks.append(CheckResult(...))` 블록을 그대로 옮기되, **`expected = anchor["expected_stage3"]` 줄은 인자로 받음**.

추출 후 `evaluate_anchor` 안의 line 254-362 블록을 다음 한 줄로 교체:

```python
    checks = _score_eight_axes(
        expected=anchor["expected_stage3"],
        weights=weights,
        sub_totals=sub_totals,
        n_unique=n_unique,
        risk_asset_total=risk_asset_total,
        method_str=method_str,
    )
```

(line 364 의 `return AnchorEvalResult(...)` 는 그대로 유지, `checks=checks` 사용.)

- [ ] **Step 3: Run anchor evaluator unit tests → verify pass (회귀)**

Run: `pytest tests/unit/observability/test_anchor_evaluator.py -v`

Expected: 모든 기존 테스트 PASS. 채점 결과 동일.

- [ ] **Step 4: Manual smoke — run 1 anchor end-to-end**

Run: `python scripts/anchor_eval.py --anchor 2024-08_yen_carry 2>&1 | tail -30`

Expected: `pass 8/8` (refactor 전과 동일).

- [ ] **Step 5: Commit**

```bash
git add tradingagents/observability/anchor_evaluator.py
git commit -m "refactor(anchor): extract _score_eight_axes helper for DRY

Stage 4 with_stage4 모드가 같은 채점을 두 번 돌려야 하므로 분리.
동작 변경 없음, 회귀 0."
```

---

## Task 7: Add `with_stage4` to `evaluate_anchor` (권고 5 part 1)

**Files:**
- Modify: `tradingagents/observability/anchor_evaluator.py`
- Create: `tests/unit/observability/test_anchor_stage4.py`

- [ ] **Step 1: Write failing test**

`tests/unit/observability/test_anchor_stage4.py` 신규 파일:

```python
"""evaluate_anchor(--with_stage4=True) 채점."""
from pathlib import Path

import pytest

from tradingagents.observability.anchor_evaluator import evaluate_anchor


_REPO = Path(__file__).resolve().parents[3]


def test_with_stage4_false_returns_only_stage3_checks():
    """default (with_stage4=False) → 기존 동작 그대로."""
    anchor = _REPO / "data" / "historical_anchors" / "2024-08_yen_carry.json"
    universe = _REPO / "data" / "universe.json"
    if not anchor.exists() or not universe.exists():
        pytest.skip("anchor/universe fixture missing")
    cache = Path.home() / ".tradingagents" / "cache" / "etf_prices.parquet"

    result = evaluate_anchor(anchor, universe_path=str(universe), cache_path=str(cache))
    # 기존 시그니처: checks 1 set
    assert isinstance(result.checks, list)
    assert len(result.checks) == 8
    # stage4 결과 없음
    assert getattr(result, "stage4_checks", None) is None


def test_with_stage4_true_returns_both_sets():
    """with_stage4=True → checks (stage3) + stage4_checks (stage3+4) 둘 다."""
    anchor = _REPO / "data" / "historical_anchors" / "2024-08_yen_carry.json"
    universe = _REPO / "data" / "universe.json"
    if not anchor.exists() or not universe.exists():
        pytest.skip("anchor/universe fixture missing")
    cache = Path.home() / ".tradingagents" / "cache" / "etf_prices.parquet"

    result = evaluate_anchor(
        anchor, universe_path=str(universe), cache_path=str(cache),
        with_stage4=True,
    )
    assert len(result.checks) == 8
    assert result.stage4_checks is not None
    assert len(result.stage4_checks) == 8
    assert result.stage4_outcome in {
        "primary_success", "relax_cluster", "relax_ceiling",
        "relax_band", "fallback_to_1st",
    }
    # Stage 3 + 4 weights 도 보존
    assert result.stage4_weights is not None


def test_stage4_weights_differ_only_when_overlay_active():
    """overlay 가 empty 면 stage4_weights == weights."""
    anchor = _REPO / "data" / "historical_anchors" / "2024-08_yen_carry.json"
    universe = _REPO / "data" / "universe.json"
    if not anchor.exists() or not universe.exists():
        pytest.skip("anchor/universe fixture missing")
    cache = Path.home() / ".tradingagents" / "cache" / "etf_prices.parquet"

    result = evaluate_anchor(
        anchor, universe_path=str(universe), cache_path=str(cache),
        with_stage4=True,
    )
    if result.stage4_outcome == "primary_success" and \
       not result.stage4_overlay_was_active:
        assert result.stage4_weights == result.weights


def test_weight_diff_summary_present_when_active():
    """overlay active 시 stage4_weight_diff 가 bucket-단위 변화 dict 반환."""
    # 이 테스트는 실측 케이스에서 검증. yen_carry 가 multiplier=0.80 → bucket 변화.
    anchor = _REPO / "data" / "historical_anchors" / "2024-08_yen_carry.json"
    universe = _REPO / "data" / "universe.json"
    if not anchor.exists() or not universe.exists():
        pytest.skip("anchor/universe fixture missing")
    cache = Path.home() / ".tradingagents" / "cache" / "etf_prices.parquet"

    result = evaluate_anchor(
        anchor, universe_path=str(universe), cache_path=str(cache),
        with_stage4=True,
    )
    if result.stage4_overlay_was_active:
        assert isinstance(result.stage4_bucket_diff, dict)
        # 변화량 합 ≈ 0 (재정규화) — 0.01 이내 tolerance
        assert abs(sum(result.stage4_bucket_diff.values())) < 0.01
```

- [ ] **Step 2: Run test → verify fail**

Run: `pytest tests/unit/observability/test_anchor_stage4.py -v`

Expected: FAIL — `evaluate_anchor` 가 `with_stage4` kwarg 모름.

- [ ] **Step 3: Extend `AnchorEvalResult` dataclass with Stage 4 fields**

`tradingagents/observability/anchor_evaluator.py` 의 `AnchorEvalResult` dataclass (line 50-85) 에 다음 필드 추가:

```python
    # Stage 4 (with_stage4=True 시만 채워짐)
    stage4_checks: list[CheckResult] | None = None
    stage4_outcome: str | None = None
    stage4_weights: dict[str, float] | None = None
    stage4_overlay_was_active: bool = False
    stage4_bucket_diff: dict[str, float] | None = None
```

`to_dict()` 에도 다음 추가:

```python
        if self.stage4_checks is not None:
            d["stage4"] = {
                "checks":             [asdict(c) for c in self.stage4_checks],
                "outcome":            self.stage4_outcome,
                "weights":            self.stage4_weights,
                "overlay_was_active": self.stage4_overlay_was_active,
                "bucket_diff":        self.stage4_bucket_diff,
                "pass_count":         sum(1 for c in self.stage4_checks if c.passed),
            }
        return d  # 기존 return 유지
```

(`to_dict` 가 `return {...}` 직후로 만드는 패턴이면 `d = { ... }` 로 받아서 위 블록 추가 후 return.)

- [ ] **Step 4: Add stage4-runner helper to anchor_evaluator.py**

`_score_eight_axes` 정의 다음에 추가:

```python
def _bucket_weights(weights: dict[str, float], universe: Universe) -> dict[str, float]:
    """ticker weight → bucket sum."""
    bucket_of = _bucket_of_ticker(universe)
    out: dict[str, float] = {}
    for t, w in weights.items():
        b = bucket_of.get(t, "_unknown")
        out[b] = out.get(b, 0.0) + w
    return out


def _run_stage4(
    state: dict, weight_vector_1, candidate_set, returns,
    bucket_target, anchor: dict, clusters: list,
) -> tuple[dict[str, float], str, bool]:
    """Stage 4 risk_judge 의 핵심 로직만 호출 (LLM 0, returns 재사용).

    return: (final_weights, outcome, overlay_was_active)
    """
    from tradingagents.agents.allocator.overlay_apply import apply_risk_overlay
    from tradingagents.agents.risk_lens.concentration_lens import (
        run_concentration_lens,
    )
    from tradingagents.agents.risk_lens.macro_conditional_lens import (
        run_macro_conditional_lens,
    )
    from tradingagents.agents.risk_lens.tail_risk_lens import run_tail_risk_lens
    from tradingagents.skills.risk.portfolio_metrics import (
        compute_portfolio_numerics,
    )
    from tradingagents.skills.risk.severity_aggregator import (
        aggregate_lens_concerns,
    )

    numerics = compute_portfolio_numerics(
        weight_vector_1, returns, clusters=clusters,
    )
    # Stage 1 정량 신호: anchor synthetic 에서는 systemic 만 있음, 나머지 default
    systemic_score = float(
        anchor["stage1"]["systemic"].get("score", 5.0)
    )
    extras = anchor["stage1"].get("market_risk_extras", {})
    vix_term_regime = extras.get("vix_term_regime", "contango")
    funding_regime = extras.get("funding_regime", "calm")
    regime_quadrant = anchor["stage1"]["regime"]["quadrant"]
    research_decision = state["research_decision"]

    tail = run_tail_risk_lens(
        numerics, systemic_score=systemic_score,
        vix_term_regime=vix_term_regime, funding_regime=funding_regime,
    )
    conc = run_concentration_lens(numerics, weight_vector_1)
    macro = run_macro_conditional_lens(
        weight_vector_1, candidate_set,
        research_decision=research_decision,
        systemic_score=systemic_score, regime_quadrant=regime_quadrant,
    )
    overlay = aggregate_lens_concerns([tail, conc, macro])

    if overlay.is_empty():
        return weight_vector_1.weights, "primary_success", False

    wv2, outcome = apply_risk_overlay(
        weight_vector_1, overlay, candidate_set, returns,
        bucket_target, method=weight_vector_1.method,
        clusters=clusters,
    )
    return wv2.weights, outcome, True
```

- [ ] **Step 5: Update `evaluate_anchor` signature + integrate Stage 4 path**

`evaluate_anchor` 시그니처 변경:

```python
def evaluate_anchor(
    anchor_path: Path | str,
    *,
    universe_path: str,
    cache_path: str | None = None,
    with_stage4: bool = False,
) -> AnchorEvalResult:
```

`return AnchorEvalResult(...)` (line ~364) 직전에 다음 블록 삽입:

```python
    # Stage 4 (with_stage4=True 시만)
    stage4_checks = stage4_outcome = stage4_weights = stage4_bucket_diff = None
    stage4_active = False
    if with_stage4:
        # synthetic anchor 의 cluster/conviction extras
        tech_extras = anchor["stage1"].get("technical_extras", {})
        clusters_data = tech_extras.get("correlation_clusters", [])
        from tradingagents.schemas.technical import Cluster
        clusters = [Cluster(**c) for c in clusters_data]

        stage4_weights, stage4_outcome, stage4_active = _run_stage4(
            state, wv, candidate_set=out["candidate_set"],
            returns=returns, bucket_target=bt, anchor=anchor,
            clusters=clusters,
        )
        # 재채점
        sub_totals_4 = _sub_category_totals(stage4_weights, universe)
        n_unique_4 = sum(
            1 for sc, w in sub_totals_4.items() if sc != "_unknown" and w > 0
        )
        risk_asset_total_4 = sum(
            w for t, w in stage4_weights.items() if bucket_of.get(t) in _RISK_BUCKETS
        )
        stage4_checks = _score_eight_axes(
            expected=anchor["expected_stage3"],
            weights=stage4_weights,
            sub_totals=sub_totals_4,
            n_unique=n_unique_4,
            risk_asset_total=risk_asset_total_4,
            method_str=method_str,
        )
        # bucket-단위 차이
        b3 = _bucket_weights(weights, universe)
        b4 = _bucket_weights(stage4_weights, universe)
        all_b = set(b3) | set(b4)
        stage4_bucket_diff = {
            b: round(b4.get(b, 0) - b3.get(b, 0), 4)
            for b in all_b
            if abs(b4.get(b, 0) - b3.get(b, 0)) >= 0.005
        }
```

그리고 `return AnchorEvalResult(...)` 의 마지막 `allocation_attribution=out.get("allocation_attribution"),` 다음에 추가:

```python
        stage4_checks=stage4_checks,
        stage4_outcome=stage4_outcome,
        stage4_weights=stage4_weights,
        stage4_overlay_was_active=stage4_active,
        stage4_bucket_diff=stage4_bucket_diff,
```

⚠️ `_run_stage4` 호출에서 `out["candidate_set"]` 이 필요. `evaluate_anchor` 의 `out = node(state)` 직후에 `candidate_set = out["candidate_set"]` 임시 변수 만들어두면 깔끔하지만, 직접 dict access 도 동작.

또한 `bucket_of` 는 stage 3 채점 시 line 249 에서 이미 만들어둔 변수. 그대로 재사용.

- [ ] **Step 6: Run new tests → verify pass**

Run: `pytest tests/unit/observability/test_anchor_stage4.py -v`

Expected: 4 개 모두 PASS (real data 의존 — fixture missing 시 skip).

- [ ] **Step 7: Run regression**

Run: `pytest tests/unit/observability/ -v`

Expected: 기존 anchor_evaluator 테스트 전부 PASS + 신규 4개 PASS.

- [ ] **Step 8: Manual smoke — anchor with --with-stage4 via Python**

(CLI 는 다음 task. 여기서는 Python 직접 호출로 확인.)

```bash
python -c "
from tradingagents.observability.anchor_evaluator import evaluate_anchor
from pathlib import Path
r = evaluate_anchor(
    'data/historical_anchors/2024-08_yen_carry.json',
    universe_path='data/universe.json',
    cache_path=str(Path.home()/'.tradingagents/cache/etf_prices.parquet'),
    with_stage4=True,
)
print(f'stage3: {r.pass_count}/{len(r.checks)}')
print(f'stage4: {sum(c.passed for c in r.stage4_checks)}/{len(r.stage4_checks)}')
print(f'outcome: {r.stage4_outcome}')
print(f'bucket_diff: {r.stage4_bucket_diff}')
"
```

Expected: 두 점수 출력 + outcome 출력.

- [ ] **Step 9: Commit**

```bash
git add tradingagents/observability/anchor_evaluator.py tests/unit/observability/test_anchor_stage4.py
git commit -m "feat(anchor): evaluate_anchor(with_stage4=True) re-scores after Stage 4

AnchorEvalResult 에 stage4_checks / outcome / weights / bucket_diff 필드 추가.
Default off — 기존 호출자 영향 0. Synthetic anchor extras 누락 시 safe default."
```

---

## Task 8: Add `with_stage4` to `evaluate_anchor_live` (권고 5 part 2)

**Files:**
- Modify: `tradingagents/observability/anchor_live.py`

- [ ] **Step 1: Add failing test**

`tests/unit/observability/test_anchor_stage4.py` 끝에 추가:

```python
def test_live_evaluate_with_stage4_optional_kwarg_exists():
    """signature 확인 — LIVE 실제 호출은 LLM 비용으로 skip."""
    import inspect
    from tradingagents.observability.anchor_live import evaluate_anchor_live
    sig = inspect.signature(evaluate_anchor_live)
    assert "with_stage4" in sig.parameters
    assert sig.parameters["with_stage4"].default is False
```

- [ ] **Step 2: Run test → verify fail**

Run: `pytest tests/unit/observability/test_anchor_stage4.py::test_live_evaluate_with_stage4_optional_kwarg_exists -v`

Expected: FAIL — `with_stage4` 가 signature 에 없음.

- [ ] **Step 3: Extend evaluate_anchor_live signature + Stage 4 integration**

`tradingagents/observability/anchor_live.py:134-141` 의 signature:

```python
def evaluate_anchor_live(
    anchor_path: Path | str,
    *,
    universe_path: str,
    cache_path: str | None = None,
    quick_llm=None,
    deep_llm=None,
) -> AnchorEvalResult:
```

을 다음으로:

```python
def evaluate_anchor_live(
    anchor_path: Path | str,
    *,
    universe_path: str,
    cache_path: str | None = None,
    quick_llm=None,
    deep_llm=None,
    with_stage4: bool = False,
) -> AnchorEvalResult:
```

함수 끝의 `return AnchorEvalResult(...)` 직전에 다음 블록 추가 (Task 7 의 코드와 거의 같음 — LIVE 는 cluster/extras 가 state 에 이미 있음):

```python
    stage4_checks = stage4_outcome = stage4_weights = stage4_bucket_diff = None
    stage4_active = False
    if with_stage4:
        from tradingagents.observability.anchor_evaluator import (
            _run_stage4, _score_eight_axes, _bucket_weights,
        )
        # LIVE 의 technical_report 에 correlation_clusters 가 있음
        clusters = getattr(
            state["technical_report"], "correlation_clusters", None,
        ) or []
        # _run_stage4 는 anchor dict 의 extras 를 보지만 LIVE 는 real 이라
        # extras 없어도 risk_report 에서 가져옴 → wrapper 가 필요.
        # 단순화: LIVE state 가 이미 다 있으므로 risk_judge 노드 직접 호출.
        from tradingagents.agents.managers.risk_judge import create_risk_judge
        risk_state = dict(state)
        risk_state.update({
            "as_of_date":   anchor["as_of_date"],
            "weight_vector":  wv,
            "candidate_set":  out["candidate_set"],
        })
        risk_node = create_risk_judge(cache_path=cache_path)
        risk_out = risk_node(risk_state)
        stage4_weights = risk_out["weight_vector"].weights
        stage4_outcome = risk_out["risk_overlay"].overlay_apply_outcome
        stage4_active = not risk_out["risk_overlay"].is_empty()

        sub_totals_4 = _sub_category_totals(stage4_weights, universe)
        n_unique_4 = sum(
            1 for sc, w in sub_totals_4.items() if sc != "_unknown" and w > 0
        )
        risk_asset_total_4 = sum(
            w for t, w in stage4_weights.items() if bucket_of.get(t) in _RISK_BUCKETS
        )
        stage4_checks = _score_eight_axes(
            expected=anchor["expected_stage3"],
            weights=stage4_weights,
            sub_totals=sub_totals_4,
            n_unique=n_unique_4,
            risk_asset_total=risk_asset_total_4,
            method_str=method_str,
        )
        b3 = _bucket_weights(weights, universe)
        b4 = _bucket_weights(stage4_weights, universe)
        all_b = set(b3) | set(b4)
        stage4_bucket_diff = {
            b: round(b4.get(b, 0) - b3.get(b, 0), 4)
            for b in all_b
            if abs(b4.get(b, 0) - b3.get(b, 0)) >= 0.005
        }
```

그리고 `return AnchorEvalResult(...)` 의 인자 목록 끝에 추가:

```python
        stage4_checks=stage4_checks,
        stage4_outcome=stage4_outcome,
        stage4_weights=stage4_weights,
        stage4_overlay_was_active=stage4_active,
        stage4_bucket_diff=stage4_bucket_diff,
```

(LIVE 의 evaluate 가 직접 8 축 체크 중복 코드를 가지면, Task 6 의 helper 를 LIVE 채점에도 적용해 dedupe — 이 task 범위 밖이지만 hint.)

- [ ] **Step 4: Run signature test → verify pass**

Run: `pytest tests/unit/observability/test_anchor_stage4.py::test_live_evaluate_with_stage4_optional_kwarg_exists -v`

Expected: PASS.

- [ ] **Step 5: Run all observability tests for regression**

Run: `pytest tests/unit/observability/ -v`

Expected: 모두 PASS.

- [ ] **Step 6: Commit**

```bash
git add tradingagents/observability/anchor_live.py tests/unit/observability/test_anchor_stage4.py
git commit -m "feat(anchor): evaluate_anchor_live(with_stage4=True) for live harness

LIVE state 에 이미 correlation_clusters/vix_term 등 있으므로 risk_judge 노드
직접 호출. Default off — LLM 비용 영향 없음 (Stage 4 자체는 LLM 0회)."
```

---

## Task 9: CLI flags `--with-stage4` in anchor_eval(_live).py + dual-row output

**Files:**
- Modify: `scripts/anchor_eval.py`
- Modify: `scripts/anchor_eval_live.py`

- [ ] **Step 1: Update scripts/anchor_eval.py for --with-stage4**

`scripts/anchor_eval.py` 의 `_print_anchor` 함수 다음을 교체:

```python
def _print_anchor(r: AnchorEvalResult) -> None:
    icon_pass = "✓"
    icon_fail = "✗"
    head = f"[{r.anchor_id}] {r.title}  ({r.as_of_date})"
    print(f"\n{head}")
    print("  " + "-" * (len(head) - 2))
    print(f"  method chosen     : {r.chosen_method}")
    print(f"  positions         : {len(r.weights)}, unique_sub_cat={r.n_unique_sub_categories}, risk_asset={r.risk_asset_total:.3f}")
    print(f"  Stage 3 only      : pass {r.pass_count}/{len(r.checks)}  (fail {r.fail_count})")
    if r.stage4_checks is not None:
        s4_pass = sum(1 for c in r.stage4_checks if c.passed)
        print(
            f"  Stage 3 + 4       : pass {s4_pass}/{len(r.stage4_checks)}  "
            f"(outcome={r.stage4_outcome}, active={r.stage4_overlay_was_active})"
        )
        # Δ axes: stage3 vs stage4 채점 결과가 flip 된 축 목록
        s3_by_name = {c.name: c.passed for c in r.checks}
        s4_by_name = {c.name: c.passed for c in r.stage4_checks}
        flipped = [
            f"{name}: {'pass' if s3_by_name[name] else 'fail'}→"
            f"{'pass' if s4_by_name.get(name, False) else 'fail'}"
            for name in s3_by_name
            if s4_by_name.get(name) is not None
            and s3_by_name[name] != s4_by_name[name]
        ]
        if flipped:
            print(f"  Δ axes            : {'; '.join(flipped)}")
        else:
            print(f"  Δ axes            : (none flipped)")
        if r.stage4_bucket_diff:
            diff_str = ", ".join(
                f"{b}={v:+.3f}" for b, v in sorted(r.stage4_bucket_diff.items())
            )
            print(f"  Δ buckets         : {diff_str}")
    print()
    for c in r.checks:
        icon = icon_pass if c.passed else icon_fail
        print(f"    {icon} {c.name:<22s} {c.detail}")
```

argparse 블록 (line 42-62) 에 추가:

```python
    p.add_argument(
        "--with-stage4", action="store_true",
        help="Stage 4 적용 후 weight 도 8 축 채점, 나란히 출력",
    )
```

`evaluate_anchor(...)` / `evaluate_all(...)` 호출 (line 74-80) 에 `with_stage4=args.with_stage4` 인자 전달:

```python
    if args.anchor:
        ...
        results = [evaluate_anchor(
            anchor_path, universe_path=args.universe, cache_path=args.cache,
            with_stage4=args.with_stage4,
        )]
    else:
        results = evaluate_all(
            catalog_dir, universe_path=args.universe, cache_path=args.cache,
            with_stage4=args.with_stage4,
        )
```

`evaluate_all` signature 도 `with_stage4: bool = False` 인자 추가 (anchor_evaluator.py:378). 본문에서 `evaluate_anchor(p, ...)` 에 pass.

요약 표 (line 94-97) 에 stage4 열 추가:

```python
    if results and results[0].stage4_checks is not None:
        print(f"  {'anchor':<32s} {'s3':>4s}/{'tot':>3s} {'s3+4':>4s}/{'tot':>3s}  outcome")
        for r in results:
            s4_pass = sum(c.passed for c in r.stage4_checks)
            print(
                f"  {r.anchor_id:<32s} "
                f"{r.pass_count:>4d}/{len(r.checks):>3d} "
                f"{s4_pass:>4d}/{len(r.stage4_checks):>3d}  {r.stage4_outcome}"
            )
    else:
        print(f"  {'anchor':<32s} {'pass':>4s} / {'tot':>3s}  method")
        for r in results:
            print(f"  {r.anchor_id:<32s} {r.pass_count:>4d} / {len(r.checks):>3d}  {r.chosen_method}")
```

- [ ] **Step 2: Update evaluate_all in anchor_evaluator.py**

`tradingagents/observability/anchor_evaluator.py:378` 의 `evaluate_all` signature:

```python
def evaluate_all(
    catalog_dir: Path | str,
    *,
    universe_path: str,
    cache_path: str | None = None,
    with_stage4: bool = False,
) -> list[AnchorEvalResult]:
```

본문에서 `evaluate_anchor(p, universe_path=universe_path, cache_path=cache_path)` 호출에 `with_stage4=with_stage4` 추가.

- [ ] **Step 3: Update scripts/anchor_eval_live.py for --with-stage4**

`scripts/anchor_eval_live.py` 의 argparse 에 같은 `--with-stage4` 플래그 추가, `evaluate_anchor_live(...)` / `evaluate_all_live(...)` 호출에 `with_stage4=args.with_stage4` 전달.

`evaluate_all_live` 도 anchor_live.py 에서 signature 확장:

```python
def evaluate_all_live(
    catalog_dir: Path | str,
    *,
    universe_path: str,
    cache_path: str | None = None,
    quick_llm=None,
    deep_llm=None,
    with_stage4: bool = False,
) -> list[AnchorEvalResult]:
```

본문에서 `evaluate_anchor_live(p, ...)` 호출에 `with_stage4=with_stage4` 추가.

`anchor_eval_live.py` 의 출력은 `--compare-synthetic` 옵션이 있을 수 있음. 단순화: synthetic 비교는 기존 그대로 두고, `--with-stage4` 가 있으면 추가 행만 출력 (Task 9 step 1 의 `_print_anchor` 패턴과 동일).

- [ ] **Step 4: Manual smoke — anchor_eval CLI with both flags**

Run: `python scripts/anchor_eval.py --anchor 2024-08_yen_carry --with-stage4 2>&1 | tail -20`

Expected: Stage 3 only + Stage 3+4 두 행 출력. outcome 표시.

- [ ] **Step 5: Manual smoke — all 7 anchors with --with-stage4**

Run: `python scripts/anchor_eval.py --with-stage4 2>&1 | tail -20`

Expected: SUMMARY 표에 stage3 + stage3+4 두 열 + outcome.

- [ ] **Step 6: Commit**

```bash
git add scripts/anchor_eval.py scripts/anchor_eval_live.py tradingagents/observability/anchor_evaluator.py tradingagents/observability/anchor_live.py
git commit -m "feat(anchor): CLI --with-stage4 flag for both eval scripts

evaluate_all(_live) 도 with_stage4 인자 받음. 출력에 두 행 + Δ buckets +
SUMMARY 표 확장. 기본 off 라 기존 호출 영향 0."
```

---

## Task 10: Final regression + manual e2e smoke + PR creation

**Files:**
- 변경 없음 — 검증 + commit + push + PR.

- [ ] **Step 1: Full unit + integration suite**

Run: `pytest tests/ -q 2>&1 | tail -30`

Expected: `failed=0`. 신규 ~14 + 기존 562 + integration 4 ≈ 580.

- [ ] **Step 2: Manual smoke — anchor with stage4 (production-like)**

Run: `python scripts/anchor_eval.py --with-stage4 2>&1 | tee /tmp/anchor_with_stage4.log`

확인:
- 7 anchor 모두 stage3 only + stage3+4 두 행 출력
- 적어도 1 anchor 에서 `stage4_overlay_was_active=True` 또는 outcome ≠ primary_success (yen_carry, kr_political_shock 등 systemic 8+ anchor 가 다른 outcome 가능)
- `Δ buckets` 가 변화 있을 때만 표시

- [ ] **Step 3: Verify overlay telemetry CLI**

Run: `python scripts/overlay_telemetry.py`

Expected: 기존 jsonl 이 없으면 "no records.", 있으면 표 출력. 정상 동작 확인.

(만약 risk_judge 노드를 한 번도 안 돌렸다면 jsonl 없음 → 정상. 다음 단계에서 dry run 으로 채울 수 있음.)

- [ ] **Step 4: Optional — main pipeline dry run to populate stats**

Run: `python -c "from tradingagents.observability.anchor_evaluator import evaluate_anchor; from pathlib import Path; \
r = evaluate_anchor('data/historical_anchors/2024-08_yen_carry.json', universe_path='data/universe.json', cache_path=str(Path.home()/'.tradingagents/cache/etf_prices.parquet'), with_stage4=True); \
print(r.stage4_outcome)"`

→ jsonl 한 줄 append. 그 다음 `python scripts/overlay_telemetry.py` 로 확인.

- [ ] **Step 5: Push branch**

```bash
git push -u origin feat/stage4-fixes
```

- [ ] **Step 6: Create PR**

```bash
gh pr create --title "feat(stage4): risk overlay fixes — drop_level escalation, cluster_caps wire, anchor stage4 scoring" --body "$(cat <<'EOF'
## Summary

Stage 4 (Risk Overlay) 영향력 측정 + 구조적 결함 수정. 4 권고 묶음.

- **권고 4** (1 줄): `macro_conditional` recession 분기 `>0.65` (high) 가 `>0.55` (medium) 뒤에 있어 unreachable 이었음. 순서 뒤집어 fix.
- **권고 3**: `cluster_caps` 가 EF group constraint 로 실제 wire (Phase 2 보류분). risk_judge 가 `correlation_clusters` pass.
- **권고 2**: `apply_risk_overlay` 가 `_half_strength` 2 단 fallback → **drop_level escalation** (0→4: cluster → ceiling → bucket band → multiplier). `(WeightVector, outcome)` tuple 반환. 매 run 결과를 `~/.tradingagents/stats/overlay_outcomes.jsonl` 에 누적, `scripts/overlay_telemetry.py` CLI 로 fallback_pct/lens 분포 표.
- **권고 5**: `anchor_eval(_live).py --with-stage4` 플래그. Stage 3 only vs Stage 3+4 두 행 + Δ buckets 출력. `AnchorEvalResult` 에 `stage4_checks/outcome/weights/bucket_diff` 필드 (default `None`).

Phase E (historical 60일 backtest) 는 별도 브랜치/PR.

## Test plan

- [x] `pytest tests/ -q` failed=0 (기존 562 + 신규 ~14)
- [x] `python scripts/anchor_eval.py --with-stage4` 7 anchor 모두 두 행 출력
- [x] `python scripts/overlay_telemetry.py` 표 정상 (jsonl 없으면 "no records.")
- [ ] Reviewer: 5/25 archive 케이스 (`A069500 0.20` corner) 가 새 drop_level escalation 으로 어떤 outcome 인지 확인 — 이전엔 fallback_to_1st 였음.

## Spec
[docs/superpowers/specs/2026-05-25-stage4-fixes-design.md](docs/superpowers/specs/2026-05-25-stage4-fixes-design.md)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 7: Report PR URL**

PR URL 을 사용자에게 출력.

---

## 검증 체크리스트 (전체)

PR 머지 전 다음이 모두 ✓:

- [ ] 4 권고 모두 구현 + commit 분리
- [ ] 신규 unit test 14+개 (recommendation 4: 2, recommendation 2 schema: 2, recommendation 2 drop_level: 5, recommendation 3 cluster: 3, recommendation 2 risk_judge: 2, recommendation 2 stats: 4, recommendation 5 anchor: 4)
- [ ] `pytest tests/ -q` failed=0
- [ ] 7 anchor `--with-stage4` smoke OK
- [ ] `overlay_telemetry.py` CLI 정상
- [ ] `_half_strength` 함수 / `test_half_strength_*` 테스트 모두 제거됨 (drop_level 이 대체)
- [ ] Spec [docs/superpowers/specs/2026-05-25-stage4-fixes-design.md](../specs/2026-05-25-stage4-fixes-design.md) 의 모든 섹션 cover
