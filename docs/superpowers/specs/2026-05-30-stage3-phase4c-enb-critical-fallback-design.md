# Stage 3 Phase 4c — ENB CRITICAL Threshold + EW Fallback Design

**Date:** 2026-05-30
**Stage:** 3 (Portfolio allocation)
**Phase:** 4c (ENB threshold 차단 + EW fallback)
**Status:** Approved for implementation

## Goal

`ENB_WARNING_THRESHOLD=3.0` 만 있던 기존 ENB 사후 측정에 더 강한 `ENB_CRITICAL_THRESHOLD=2.0` 추가. ENB < CRITICAL 시 (집중도 위험) 선택된 ticker 들에 equal-weight (cap clip) 강제 fallback. attribution 에 `enb_action` + `enb_post_fallback` 노출.

## Rationale

현재 ENB 사후 측정은 warning log 만 — weights 가 집중되어 있어도 그대로 통과. critical threshold + EW fallback 으로 최소 분산 보장. Phase 1 의 ENB decomposition (cash_spillover) 과 별개의 portfolio-level safety net.

## Scope

### In-scope

1. `tradingagents/agents/allocator/portfolio_allocator.py`:
   - 상수 2종 신규: `ENB_CRITICAL_THRESHOLD=2.0`, `ENB_FALLBACK_MIN_TICKERS=5`
   - post-optimization ENB check 분기 확장 (4-way action)
   - `_apply_single_cap_redistribution(weights, cap)` helper 신규
   - attribution 키 2종 추가: `enb_action`, `enb_post_fallback`

### Out-of-scope

- expense_ratio 5번째 impl_score 요소 (data source 부재 — 후속 phase)
- ENB threshold 차단 의 method downgrade 변형 (단순 EW fallback 채택)
- ENB CRITICAL threshold tuning (backtest 후 검토)
- backtest 검증

## Architecture

```
                BEFORE                              AFTER (Phase 4c)
─────────────────────────────────────────────────────────────────────
post-optimization (line 343):
  enb_value = compute_enb(...)
  attribution["enb"] = enb_value
  if enb < WARNING (3.0):
    logger.warning(...)
                                     ↓
  enb_value = compute_enb(...)
  attribution["enb"] = enb_value
  enb_action = "none"

  if 0 < enb_value < CRITICAL (2.0):
    if n >= ENB_FALLBACK_MIN_TICKERS (5):
      weights = EW with cap clip + redistribute
      enb_post = compute_enb(weights, ...)
      attribution["enb_post_fallback"] = enb_post
      enb_action = "equal_weight_fallback"
    else:
      enb_action = "warning_only_n_too_small"

  elif 0 < enb_value < WARNING:
    enb_action = "warning_only"

  attribution["enb_action"] = enb_action
```

## Components

### `tradingagents/agents/allocator/portfolio_allocator.py`

**(a) 상수 신규 (line 56 근처)**:

```python
ENB_WARNING_THRESHOLD: float = 3.0   # 기존
ENB_CRITICAL_THRESHOLD: float = 2.0  # NEW (Phase 4c)
ENB_FALLBACK_MIN_TICKERS: int = 5    # NEW — 1/n ≤ cap (0.20) 보장
```

**(b) post-optimization ENB check 확장 (line 343 근처)**:

```python
# Phase 1 ENB 사후 측정 + Phase 4c critical threshold + EW fallback
try:
    enb_value = compute_enb(wv.weights, sigma_df, method="minimum_torsion")
except Exception as e:
    logger.warning("ENB 계산 실패: %s", e)
    enb_value = 0.0
attribution["enb"] = float(enb_value)

enb_action = "none"
if 0 < enb_value < ENB_CRITICAL_THRESHOLD:
    n_selected = len(wv.weights)
    if n_selected >= ENB_FALLBACK_MIN_TICKERS:
        ew_weights = {t: 1.0 / n_selected for t in wv.weights}
        ew_weights = _apply_single_cap_redistribution(
            ew_weights, SINGLE_ASSET_CAP,
        )
        wv = WeightVector(weights=ew_weights)
        try:
            enb_post = compute_enb(wv.weights, sigma_df, method="minimum_torsion")
        except Exception:
            enb_post = 0.0
        attribution["enb_post_fallback"] = float(enb_post)
        enb_action = "equal_weight_fallback"
        logger.warning(
            "ENB %.2f < %.2f (CRITICAL) — EW fallback (n=%d, ENB→%.2f)",
            enb_value, ENB_CRITICAL_THRESHOLD, n_selected, enb_post,
        )
    else:
        enb_action = "warning_only_n_too_small"
        logger.warning(
            "ENB %.2f < %.2f (CRITICAL) but n=%d < %d — fallback skipped, warning only",
            enb_value, ENB_CRITICAL_THRESHOLD, n_selected, ENB_FALLBACK_MIN_TICKERS,
        )
elif 0 < enb_value < ENB_WARNING_THRESHOLD:
    enb_action = "warning_only"
    logger.warning(
        "ENB %.2f < %.2f — possible insufficient diversification",
        enb_value, ENB_WARNING_THRESHOLD,
    )

attribution["enb_action"] = enb_action
```

**(c) `_apply_single_cap_redistribution` helper 신규**:

```python
def _apply_single_cap_redistribution(
    weights: dict[str, float],
    cap: float,
    max_iter: int = 10,
) -> dict[str, float]:
    """
    Cap-clip + 잔여를 non-capped 자산에 비례 분배 (iterative).

    Used by ENB CRITICAL EW fallback path. Starting from {t: 1/n},
    이미 cap 이하면 no-op. cap 초과 자산 있으면 clip + redistribute
    한 후 다시 검사 — max_iter 반복.

    Returns:
        weights: sum ≈ 1.0, max(w) ≤ cap (가능한 경우).
        빈 dict 입력 시 빈 dict 반환.
    """
    weights = dict(weights)
    if not weights:
        return weights
    for _ in range(max_iter):
        excess = {t: max(0.0, w - cap) for t, w in weights.items()}
        total_excess = sum(excess.values())
        if total_excess < 1e-9:
            break
        weights = {t: min(w, cap) for t, w in weights.items()}
        non_capped = [t for t, w in weights.items() if w < cap - 1e-9]
        if not non_capped:
            break
        share = total_excess / len(non_capped)
        for t in non_capped:
            weights[t] += share
    total = sum(weights.values())
    if total > 0:
        weights = {t: w / total for t, w in weights.items()}
    return weights
```

### Attribution 구조

```json
{
  "allocation_attribution": {
    "enb": 1.8,
    "enb_action": "equal_weight_fallback",
    "enb_post_fallback": 4.5
  }
}
```

`enb_action` 값 4종:
- `"none"`: ENB ≥ WARNING (정상)
- `"warning_only"`: WARNING > ENB ≥ CRITICAL
- `"warning_only_n_too_small"`: CRITICAL > ENB, n < 5 (fallback 무력화)
- `"equal_weight_fallback"`: CRITICAL > ENB, n ≥ 5 (EW 적용)

`enb_post_fallback`: `enb_action="equal_weight_fallback"` 인 경우에만 존재.

## Edge Cases

| Case | enb_action | weights 변화 |
|---|---|---|
| ENB = 4.5 | `"none"` | unchanged |
| ENB = 2.5 | `"warning_only"` | unchanged |
| ENB = 1.5, n=10 | `"equal_weight_fallback"` | 1/10 each (no cap clip) |
| ENB = 1.5, n=4 | `"warning_only_n_too_small"` | unchanged (1/4=0.25 > cap 0.20) |
| ENB = 1.5, n=5 | `"equal_weight_fallback"` | 1/5 = 0.20 (=cap) |
| ENB = 0 (계산 실패) | `"none"` | unchanged |
| EW 후 sum ≠ 1.0 | renormalize | sum = 1.0 |
| EW 후 ENB 측정 실패 | `enb_post_fallback = 0.0` | weights 유지 |
| force_method='bl'/'nco' 외부 주입 | 동일 적용 | EW fallback 가능 |

## Numerical Safety

- `_apply_single_cap_redistribution` max_iter=10 으로 무한루프 방지
- `total > 0` 체크로 0-division 방지
- ENB 측정 실패 → `enb_value = 0.0` (기존 패턴 유지)

## Backward Compat

- `ENB_WARNING_THRESHOLD=3.0` 동작 그대로 — `enb_action="warning_only"` attribute 만 추가
- `attribution["enb"]` 기존 키 그대로
- 새 키 2종 추가 (`enb_action`, `enb_post_fallback`)
- EW fallback 발동 시 weights 가 EW 로 강제 변경 — **회귀 baseline 갱신 권장**
- 단, 기존 e2e 의 ENB 값 (~3-5) 은 CRITICAL=2.0 보다 크므로 fallback 발동 안 함 → 회귀 무손실 기대

## Testing Strategy

### Unit tests — `tests/unit/agents/test_portfolio_allocator.py` (MODIFY, 5 tests 추가)

1. `test_apply_single_cap_redistribution_basic` — n=10, 1/n=0.10 → no cap clip
2. `test_apply_single_cap_redistribution_cap_clipped_all` — n=3, 1/3=0.333 → 모두 cap → renormalize
3. `test_apply_single_cap_redistribution_partial_cap` — 일부 cap 초과 → clip + non-capped 재분배
4. `test_apply_single_cap_redistribution_iterative` — 첫 분배 후 또 cap 초과 → iter 반복 검증
5. `test_apply_single_cap_redistribution_empty` — `{}` 입력 → `{}` 반환

### Integration tests — `tests/integration/test_allocator_phase4c.py` (NEW, 4 tests)

1. `test_allocator_enb_none_action_default` — 정상 ENB → `enb_action="none"`, no enb_post_fallback
2. `test_allocator_enb_warning_only_action` — WARNING > ENB ≥ CRITICAL → `enb_action="warning_only"`, weights unchanged
3. `test_allocator_enb_critical_ew_fallback` — ENB < CRITICAL, n≥5 → `enb_action="equal_weight_fallback"`, `enb_post_fallback` 기록, weights EW + cap clip
4. `test_allocator_enb_critical_n_too_small_no_fallback` — ENB < CRITICAL, n<5 → `enb_action="warning_only_n_too_small"`, weights unchanged

NOTE: 통합 테스트에서 ENB 값 제어를 위해 `monkeypatch` 로 `compute_enb` patch.

### Regression — Phase 1/2a/2b/3a/3b/3c/4a/4b

기존 250+ tests PASS 기대. e2e 의 ENB (~3-5) > CRITICAL=2.0 → fallback 발동 안 함. 만약 mock helper 의 sigma 가 작은 universe + 한 cluster 집중일 때 ENB < 2.0 일 가능성 있음 — fallback 발동 시 assertion 갱신.

### Acceptance criteria

| # | Criterion | Verification |
|---|---|---|
| (a) | `ENB_CRITICAL_THRESHOLD=2.0` 상수 | grep |
| (b) | `_apply_single_cap_redistribution` helper | unit 1-5 |
| (c) | `enb_action="none"` (정상) | integration 1 |
| (d) | `enb_action="warning_only"` | integration 2 |
| (e) | `enb_action="equal_weight_fallback"` + post 측정 | integration 3 |
| (f) | `enb_action="warning_only_n_too_small"` 변동 없음 | integration 4 |
| (g) | 기존 250+ tests PASS | full regression |

총 9 신규 test (5 unit + 4 integration).

## Related Memory

- [[stage3_phase1_followup]] — Phase 1 ENB decomposition (cash_spillover, 별개)
- [[stage3_phase2b_followup]] — Phase 2b ENB greedy selection (ENB 입력의 소스)
- [[stage3_phase4a_followup]] — cov shrinkage (sigma_df 정확도)
- [[stage3_phase4b_followup]] — BL tilt dial (Phase 4c 와 별개 method 분기)
