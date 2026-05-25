# Stage 4 Fixes — Design Spec

> 2026-05-25 · 브랜치 `feat/stage4-fixes` · 한 PR로 묶음

## 0. 배경

Stage 4 (Risk Overlay) 실측 분석 (2026-05-25) 에서 확인한 결과:

- `~/.tradingagents/runs/` archive 2건 (5/15, 5/25) 모두 **weight 변경 0**.
  - 5/15: severity gate 미통과 (medium 1개) → empty overlay.
  - 5/25: severity gate 통과 (critical 1 → strength 0.7) 했으나 primary + half-strength 둘 다 infeasible → 1차 결과 그대로 fallback.
- 코드 분석으로 구조적 결함 3개 발견:
  - `cluster_caps` 가 EF constraint 로 wire 안 됨 ([overlay_apply.py:176-179](../../../tradingagents/agents/allocator/overlay_apply.py#L176-L179)).
  - `macro_conditional_lens` 의 recession 분기에서 `>0.65` (high) 가 `>0.55` (medium) 뒤에 와서 **unreachable** ([macro_conditional_lens.py:52-56](../../../tradingagents/agents/risk_lens/macro_conditional_lens.py#L52-L56)).
  - HRP method 가 overlay 발동 시 MIN_VARIANCE 로 swap (별도 fix 대상 아님 — 현 PR 범위 밖).
- 영향력 측정 인프라 부재: anchor 채점이 Stage 3 까지만 평가, Stage 4 효과를 누적 관찰할 telemetry 없음.

→ **현재 spec 은 이 중 측정 가능한 권고 4개 (2·3·4·5) 만 다룬다**. Phase E backtest 모드 (권고 1) 는 별도 브랜치 / 별도 spec.

## 1. 목표

이 PR 머지 후:

1. **(권고 4)** `macro_conditional_lens` 의 recession 분기 `high` 가 실제 도달 가능.
2. **(권고 3)** `concentration_lens` 가 제안한 `cluster_caps` 가 2 차 optimizer 의 EF constraint 로 강제됨.
3. **(권고 2)** `apply_risk_overlay` 가 단순 `primary → half → fallback` 이 아니라 **drop_level escalation** 으로 점진 완화. 각 단계 결과가 archive + 누적 stats 에 기록됨.
4. **(권고 5)** `anchor_eval(_live).py` 가 `--with-stage4` 플래그로 Stage 4 적용 후 weight 도 8 축 채점, Stage 3 only 와 나란히 비교.
5. 562 unit + 4 integration test 회귀 0 건.

## 2. Non-goals

- Phase E historical backtest 모드 (별도 PR).
- Lens threshold calibration (60 일 운영 데이터 확보 후).
- HRP-with-constraints 구현 (overlay 발동 시 MV swap 유지).
- BL views 자동 생성.
- Anchor JSON schema 변경 (Stage 4 입력 default 로 흡수).

## 3. 권고 4 — `macro_conditional_lens` recession 분기 fix

### 3.1 현 코드 ([macro_conditional_lens.py:52-56](../../../tradingagents/agents/risk_lens/macro_conditional_lens.py#L52-L56))

```python
if regime_quadrant in ("recession_disinflation", "recession_inflation"):
    if risk_weight > 0.55:
        return "medium"
    if risk_weight > 0.65:   # unreachable
        return "high"
```

### 3.2 수정

```python
if regime_quadrant in ("recession_disinflation", "recession_inflation"):
    if risk_weight > 0.65:
        return "high"
    if risk_weight > 0.55:
        return "medium"
```

### 3.3 검증

- 신규 unit test 2개:
  - `risk_weight=0.70`, `regime=recession_disinflation` → `level=high`.
  - `risk_weight=0.60`, `regime=recession_inflation` → `level=medium`.
- 기존 `test_risk_lenses.py` 회귀 통과.

## 4. 권고 3 — `cluster_caps` wire

### 4.1 데이터 흐름

`technical_report.correlation_clusters: list[Cluster]` 에서 각 `Cluster.cluster_id` 와 `Cluster.members: list[str]` 가 이미 정의됨 ([schemas/technical.py:36-40](../../../tradingagents/schemas/technical.py#L36-L40)).

현재 `apply_risk_overlay` signature 는 `clusters` 를 받지 않음. `risk_judge` 노드가 state 의 `technical_report.correlation_clusters` 를 pass.

### 4.2 EF constraint 변환

`_solve_with_overlay` 에서 EF 생성 후, overlay 의 cluster_caps 를 group constraint 로 추가:

```python
asset_idx = {t: i for i, t in enumerate(ef.tickers)}
for cluster in clusters:
    if cluster.cluster_id not in overlay.cluster_caps:
        continue
    cap = overlay.cluster_caps[cluster.cluster_id]
    indices = [asset_idx[t] for t in cluster.members if t in asset_idx]
    if len(indices) >= 2:
        ef.add_constraint(
            lambda w, idxs=indices, c=cap: sum(w[i] for i in idxs) <= c
        )
```

### 4.3 우선순위

`cluster_caps` 는 가장 indirect 한 신호 (cluster id 매칭 + 멤버 합산 proxy) → infeasibility escalation 에서 **가장 먼저 drop** (Sec 5 참조).

### 4.4 검증

- 신규 unit test 3개:
  - 합성 5 종목 × 2 cluster, cluster_caps={c1: 0.30} → 결과 weight 의 c1 합 ≤ 0.30 검증.
  - cluster_caps 명시됐으나 cluster.members 가 universe 에 없음 → constraint 추가 X, 정상 풀이.
  - cluster_caps 가 strict 해서 bucket equality 와 충돌 → drop_level=1 로 escalation (Sec 5 와 통합 test).

## 5. 권고 2 — Telemetry + Auto-relax (drop_level escalation)

### 5.1 새 구조

`_solve_with_overlay(method, returns, candidates, bucket_target, overlay, clusters, drop_level: int = 0) -> WeightVector`

`drop_level` 별 동작 (**각 level 은 이전 level 의 완화를 누적 포함**):

| drop_level | 누적 적용 |
|---|---|
| 0 | full (cluster_caps + ceilings + bucket equality + multiplier) |
| 1 | level 0 에서 cluster_caps 제거 |
| 2 | level 1 + weight_ceilings 제거 |
| 3 | level 2 + bucket equality → `±5%p` band (Stage 3 D4 retry 패턴) |
| 4 | level 3 + multiplier=1.0 (= 1차 결과 동일) |

### 5.2 `apply_risk_overlay` 루프 재작성

```python
OUTCOMES = ["primary_success", "relax_cluster", "relax_ceiling",
            "relax_band", "fallback_to_1st"]

def apply_risk_overlay(...) -> tuple[WeightVector, str]:
    if overlay.is_empty():
        return weight_vector_1, "primary_success"

    last_err = None
    for level in range(5):
        try:
            wv = _solve_with_overlay(..., drop_level=level)
            return wv, OUTCOMES[level]
        except Exception as e:
            last_err = e
            logger.warning("overlay drop_level=%d failed: %s", level, e)

    # drop_level=4 마저 실패: 1차 결과 + rationale 로그
    return weight_vector_1.model_copy(update={...}), "fallback_to_1st"
```

→ 기존 `half_strength` 함수는 제거. 단계적 escalation 이 더 informative.

### 5.3 Telemetry

#### Per-run archive
`RiskOverlay` schema 에 신규 필드:

```python
overlay_apply_outcome: Literal[
    "primary_success", "relax_cluster", "relax_ceiling",
    "relax_band", "fallback_to_1st"
] = "primary_success"
```

`risk_judge` 노드가 `apply_risk_overlay` 의 두 번째 return 을 받아 `RiskOverlay.overlay_apply_outcome` 에 설정 후 archive.

#### 누적 stats
신규 모듈 `tradingagents/observability/overlay_stats.py`:

```python
STATS_PATH = Path.home() / ".tradingagents/stats/overlay_outcomes.jsonl"

def record_overlay_outcome(
    date: str, outcome: str, lens_levels: dict[str, str],
    strength: float, multiplier: float,
) -> None:
    """append-only one-line per run."""
    ...
```

매 run 의 `risk_judge` 노드 끝에서 호출. 형식:

```json
{"date": "2026-05-25", "outcome": "relax_band", "lens_levels":
 {"tail_risk": "low", "concentration": "critical", "macro_conditional": "medium"},
 "strength_applied": 0.7, "multiplier_final": 0.944}
```

#### CLI
신규 `scripts/overlay_telemetry.py`:

```bash
python scripts/overlay_telemetry.py [--last N]
# 출력 예시:
#   Last 30 runs:
#     primary_success     12 (40%)
#     relax_cluster        5 (17%)
#     relax_ceiling        3 (10%)
#     relax_band           7 (23%)
#     fallback_to_1st      3 (10%)
#   Mean strength_applied: 0.42
#   Lens severity distribution:
#     tail_risk:        none=18 low=8 medium=3 high=1 critical=0
#     concentration:    none=10 low=8 medium=7 high=3 critical=2
#     macro_conditional: none=22 low=0 medium=5 high=3 critical=0
```

### 5.4 검증

- 신규 unit test 5개:
  - 각 drop_level 이 infeasibility → 다음 level escalate (5 단계 케이스).
  - `overlay_apply_outcome` 정확히 기록.
  - Stats jsonl append 동작 (tmp_path fixture).
  - 빈 overlay → `primary_success` outcome.
  - drop_level=4 도 실패 (인공 조건) → `fallback_to_1st` + 1차 weight 반환.

## 6. 권고 5 — Anchor 채점에 Stage 4 추가

### 6.1 CLI 인터페이스

```bash
# 기존 (변경 없음)
python scripts/anchor_eval.py --anchor 2024-08_yen_carry
python scripts/anchor_eval_live.py --anchor 2024-08_yen_carry

# 신규 플래그
python scripts/anchor_eval.py --anchor 2024-08_yen_carry --with-stage4
python scripts/anchor_eval_live.py --anchor 2024-08_yen_carry --with-stage4
```

### 6.2 출력 포맷 (`--with-stage4` 시)

```
2024-08_yen_carry
  Stage 3 only:    8/8  (method=min_variance)
  Stage 3 + 4:     8/8  (method=min_variance, outcome=primary_success, mult=0.80)
  Δ axes:           (none flipped)
  Δ weights:        kr_equity -3.0%p, bond +2.0%p, cash_mmf +1.0%p
```

`Δ axes` 는 8 축 중 변화한 축 (예: `risk_asset_max: pass → fail`). `Δ weights` 는 bucket 합 기준 변화량 ≥ 0.5%p 만 표시.

### 6.3 Synthetic anchor 입력 default

Stage 4 가 보는 입력 중 anchor JSON 에 없는 것:

| 입력 | 출처 (anchor synthetic) | Default if absent |
|---|---|---|
| `vix_term.regime` | `stage1.market_risk_extras.vix_term_regime` | `"contango"` |
| `funding_stress.regime` | `stage1.market_risk_extras.funding_regime` | `"calm"` |
| `correlation_clusters` | `stage1.technical_extras.correlation_clusters` | `[]` |
| `research_decision.conviction` | `stage2.conviction` | `"medium"` |

→ Anchor JSON schema 는 **breaking change 없음**. 신규 `stage1.market_risk_extras` / `stage1.technical_extras` / `stage2.conviction` 은 Pydantic `Optional` (default `None`) 필드로만 추가 — 기존 7 anchor 파일은 수정 없이 default 적용. 신규 anchor 작성 시 명시 가능.

LIVE harness 는 Stage 1 real 실행 → 모든 필드 자동 확보.

### 6.4 검증

- 신규 unit test 4개:
  - default 입력으로 Stage 4 호출 → outcome 정상.
  - `--with-stage4` 가 8 축 점수 dict 두 개 반환 (`stage3_only` + `stage3_plus_4`).
  - `Δ weights` 계산 정확성 (bucket 단위 합산).
  - cluster_caps 가 active 한 anchor (e.g. synthetic high-concentration) → cluster_caps 적용 후 weight 차이 확인.
- 7 anchor smoke (manual): `python scripts/anchor_eval.py --all --with-stage4` 실행, 표 형태 출력 확인.

## 7. 파일 매니페스트

### 변경 (existing)

| 파일 | 변경 요지 |
|---|---|
| `tradingagents/agents/risk_lens/macro_conditional_lens.py` | recession 분기 순서 뒤집기 (1줄). |
| `tradingagents/agents/allocator/overlay_apply.py` | `_solve_with_overlay(drop_level)` 도입, `apply_risk_overlay` 가 `(wv, outcome)` tuple 반환, cluster_caps EF constraint 추가, `_half_strength` 제거. |
| `tradingagents/agents/managers/risk_judge.py` | `apply_risk_overlay` 의 outcome 받아 `RiskOverlay.overlay_apply_outcome` 설정, `record_overlay_outcome` 호출, `correlation_clusters` pass. |
| `tradingagents/schemas/risk_overlay.py` | `RiskOverlay.overlay_apply_outcome` 필드 추가 (default `"primary_success"`). |
| `tradingagents/observability/anchor_evaluator.py` | `evaluate_anchor(..., with_stage4: bool = False)` 추가, return 타입에 `stage3_plus_4` optional key. |
| `tradingagents/observability/anchor_live.py` | 동일 시그니처 확장. |
| `scripts/anchor_eval.py` | `--with-stage4` 플래그, 표 출력 확장. |
| `scripts/anchor_eval_live.py` | 동상. |

### 신규

| 파일 | 역할 |
|---|---|
| `tradingagents/observability/overlay_stats.py` | `record_overlay_outcome` + `summarize_outcomes` helper. |
| `scripts/overlay_telemetry.py` | 누적 stats CLI. |
| `tests/unit/agents/test_overlay_drop_levels.py` | drop_level escalation 5 케이스. |
| `tests/unit/agents/test_overlay_cluster_caps.py` | cluster_caps EF constraint 검증. |
| `tests/unit/observability/test_overlay_stats.py` | jsonl append + summarize. |
| `tests/unit/observability/test_anchor_stage4.py` | --with-stage4 채점 dict 정합성. |

### 수정 (test)

| 파일 | 변경 요지 |
|---|---|
| `tests/unit/agents/test_risk_lenses.py` | macro_conditional high 분기 발동 test 2개 추가. |
| `tests/unit/agents/test_overlay_apply.py` | `_half_strength` 제거에 따른 케이스 정리 + `(wv, outcome)` tuple 반환 검증. |
| `tests/unit/skills/test_risk_severity_aggregator.py` | 영향 없음, 회귀만 확인. |

## 8. 마이그레이션 / 호환성

- `apply_risk_overlay` return 타입 변경 (`WeightVector` → `tuple[WeightVector, str]`). 호출자는 `risk_judge` 하나 → 동시 수정.
- `RiskOverlay.overlay_apply_outcome` 신규 필드 default 가 `"primary_success"` → 기존 archive JSON 도 deserialize 가능.
- `_half_strength` 제거. 외부 호출 없음 (검색 확인 완료: 호출자 0).
- Anchor JSON 신규 optional field (`stage1.market_risk_extras` 등). 기존 7 anchor 파일은 수정 없이 default 적용.

## 9. 리스크 및 완화

| 리스크 | 완화 |
|---|---|
| drop_level escalation 이 너무 자주 fallback 까지 가서 *체감* 영향 여전히 0 | Telemetry CLI 로 매주 비율 점검. 30% 이상 fallback 이면 Phase 3 calibration trigger. |
| cluster_caps 가 모든 case 에서 1 단계 drop 발생 → cluster 신호 가치 0 | Test 로 단순 case (2 cluster, low overlap) 에서 cluster_caps 적용 성공 검증. |
| Anchor 7 개 모두 `--with-stage4` 가 pass count 동일 → Stage 4 영향력 anchor 로 검증 불가 | Phase E backtest 가 본 검증. Anchor 는 보조 신호. |
| Stats jsonl 파일이 무한 증가 | Phase 3 에서 rotation 추가 (현재 PR 범위 밖). 1년 = ~250 run = ~50KB 로 사실상 무시. |

## 10. Out of scope (재확인)

- Phase E backtest 모드.
- Lens threshold calibration.
- HRP-with-constraints.
- BL views 자동 생성.
- Anchor JSON schema breaking change.

---

## 11. 변경 후 디자인 일관성

| 항목 | Stage 1 | Stage 2 | Stage 3 | Stage 4 (이 PR 후) |
|---|---|---|---|---|
| LLM 사용 (매일) | quick + subagents | deep 1회 | 0 회 | 0 회 |
| Mandate | 입력 검증 | invariant | weight_bounds + sector | overlay → constraint, **drop_level escalation** |
| Infeasibility 처리 | — | — | D4 retry (per_bucket_n + ±5%p band) | **drop_level escalation (Stage 3 패턴 차용)** |
| Telemetry | runs/{date}/*.json | runs/{date}/research_decision.json | runs/{date}/*.json + allocation_attribution | runs/{date}/risk_overlay.json + **stats/overlay_outcomes.jsonl** |
| Anchor 채점 | — | — | 8 축 (synthetic + LIVE) | **--with-stage4 비교** |

→ 이 PR 후 Stage 4 가 Stage 3 의 D4 retry 패턴 / archive 패턴과 일관. 사용자가 처음 분석에서 지적한 "infeasibility 자주 발동되면 Stage 4 무의미" 문제에 정량 가시성 확보.
