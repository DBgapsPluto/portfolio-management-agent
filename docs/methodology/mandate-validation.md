# Stage 5 — Mandate Validator (deterministic mandate enforcement)

> 파이프라인 6 stage 중 다섯 번째 단계. Stage 4 (Risk Overlay 적용 후의 weight)를 받아 대회 §2.2 / §3.1 등 mandate 룰을 deterministic하게 검증, D4 retry cycle을 발동하거나 통과 시 Stage 6 (Portfolio Manager)로 전달.

> **Stage 5 정리 (Commit A + B)**: Stage 1·2·3·4의 큰 재설계와 달리 *micro-patch만*. 6가지 silent bug / 불명확 항목을 단발적으로 수정. 구조 변경 0, 새 룰 추가 0.

---

## 1. 한 줄 요약

> **6개 deterministic check (integrity / universe / single_cap / risk_asset_cap / correlation_cluster / turnover_floor)를 차례로 실행해 hard violation 1개라도 있으면 retry/fallback 발동, 모두 통과면 Stage 6로 전달. LLM 호출 0회. mandate enforcement의 single source of truth.**

---

## 2. 왜 정리했나 (재설계 X, micro-patch만)

기존 Stage 5는 큰 구조 문제 없었지만 6가지 silent bug / 불명확 항목이 있었다:

| # | 문제 | 영향 |
|---|---|---|
| ① | `correlation_check.severity="soft"` | cluster cap 위반이 D4 retry/fallback 발동 안 함 (사실상 무력화) |
| ② | `concentration_check`이 universe.etfs[].bucket 의존 | universe.json refresh 시 silent drift 가능 |
| ③ | Weight NaN/Inf 사전 검증 부재 | Pydantic이 sum/음수는 잡지만 NaN/Inf 통과 |
| ④ | `turnover_check.days_remaining` 데드 파라미터 | dead code |
| ⑤ | Rebalance mode가 `previous_portfolio` 유무로 implicit 분기 | daily/weekly 확장 불가, archive에 mode 미기록 |
| ⑥ | Stage 4 concentration_lens cluster_caps가 validator 0.25보다 *느슨* (0.30/0.35) | Stage 4의 cluster_caps preset 실효성 0 |

### 정리 원칙

- ✅ **재설계 X** — 구조 그대로 유지 (universe/concentration/correlation/turnover 4 check + integrity pre-check)
- ✅ **LLM 추가 X** — Stage 5는 영원히 deterministic
- ✅ **새 룰 추가 X** — 대회 §에 없는 룰은 자체로 만들지 않음
- ✅ **Validator → Stage 4 역방향 흐름 X** — 책임 경계 명확
- ✅ **Fail-fast 도입 X** — 4개 check 다 돌려서 정보 풍부

---

## 3. 어떤 데이터를 보는가

### 3.1 Input — state에서 읽는 키

| Key | 출처 | 사용처 |
|---|---|---|
| `weight_vector` | Stage 4 (overlay 적용 후) 또는 Stage 3 (overlay empty 시) | 모든 check의 베이스 |
| `universe_path` | config | `load_universe` → universe / category 매핑 |
| `correlation_clusters` | Stage 1 technical | correlation_check |
| `capital_krw` | config | turnover_check (avg_assets) |
| `previous_portfolio` | cross-run | turnover_check (delta) + rebalance mode 결정 |
| `rebalance_mode` (optional) | 운영자 explicit | Stage 5 정리 ⑤에서 신설. FLOOR_BY_MODE 분기 |
| `allocation_attempts` | D4 retry counter | conditional_logic.validation_router 사용 |

→ Stage 5는 외부 fetch 0건. 모든 입력은 in-memory state.

### 3.2 Stage 4 출력은 보지 않음

`risk_overlay` / `portfolio_numerics` 등 Stage 4 산출물은 Stage 5에서 무시. 책임 분리:
- Stage 4 = weight 조정
- Stage 5 = mandate 검증 (조정된 weight 또는 원본 weight)

Stage 4 정보는 Stage 6 리포트에서 활용.

---

## 4. 어떻게 가공하는가 (6 단계)

```
Stage 4 (overlay 적용) 또는 Stage 3 (overlay empty)
                    │
                    ▼
[1] _check_weight_integrity (NaN/Inf/sum/음수)  ← Stage 5 정리 ③
       │
       ├─ hard fail → 다른 check skip, 즉시 retry/fallback
       │
       ▼ pass
[2] validate_universe (188 ETF universe 외 ticker 검사)
[3] validate_concentration (단일 cap 20% + 위험자산 70%)  ← ②
[4] validate_correlation_concentration (cluster ≤ 25%)   ← ① hard 승격
[5] validate_turnover_feasibility (floor by mode)         ← ④⑤
                    │
                    ▼
[6] ValidationReport — passed = not any(hard)
       │
       ├─ passed → Stage 6 finalize
       ├─ fail + attempts<2 → retry_allocator (Stage 3 재호출)
       └─ fail + attempts=2 → fallback_normalizer (emergency)
```

### 4.1 Weight integrity pre-check (Stage 5 정리 ③)

`_check_weight_integrity(wv)`:

```python
# WeightVector.weights dict 검증:
# - 비어있지 않음
# - 모든 값이 numeric (int/float)
# - NaN, Inf 거부
# - 음수 거부
# - sum ≈ 1.0 (tolerance 1e-3)
```

**왜 별도 pre-check?**:
- Pydantic `WeightVector._normalize`가 sum과 음수는 잡지만 **NaN/Inf 통과 가능** (`float("nan")`은 음수 아니고 `float("nan") + 1 = nan`이라 sum 검증도 우회)
- `fallback_normalizer.py:55-58`은 assert로 검증하지만 정상 path 부재
- pre-check가 fail이면 *다른 check 의미 없음* → 즉시 retry/fallback

→ 통상 path에선 통과 (Stage 3 pypfopt 정상 동작 시), 비정상 path 안전망.

### 4.2 universe membership check (`validate_universe`)

```python
universe_tickers = {e.ticker for e in universe.etfs}
for ticker in weights:
    if ticker not in universe_tickers:
        violation: hard
```

→ Stage 3가 universe에서만 후보 선정하므로 정상 path는 항상 통과. 안전망.

### 4.3 concentration check (`validate_concentration`)

대회 §2.2 — 단일 ETF ≤ 20% + 위험자산 ≤ 70%.

**Stage 5 정리 ② — risk_asset 정의 통일**:

기존:
```python
RISK_BUCKETS = {"위험"}
risk_total = Σ(w for t if universe.etfs[t].bucket == "위험")
```

신규:
```python
RISK_BUCKET_NAMES = {"kr_equity", "global_equity", "fx_commodity"}
RISK_CATEGORIES = frozenset(
    cat for bucket in RISK_BUCKET_NAMES
    for cat in BUCKET_TO_CATEGORIES[bucket]   # candidate_selector의 매핑
)
risk_total = Σ(w for t if universe.etfs[t].category in RISK_CATEGORIES)
```

**의도**: universe.json refresh 시 `bucket="위험"` 필드 라벨링 실수해도 영향 없음. **candidate_selector의 BUCKET_TO_CATEGORIES을 single truth source**로 통일.

현재 universe.json 검증: 138개 "위험" 라벨 = (kr_equity 53 + global_equity 78 + fx_commodity 7) 정확히 일치. 따라서 현 동작은 변화 없음, **defensive 개선**.

### 4.4 correlation_check (`validate_correlation_concentration`)

cluster cap (sum of weights in a cluster ≤ 0.25).

**Stage 5 정리 ① — severity hard 승격**:

기존: `severity="soft"` → validator의 `passed = not any(hard)`로 soft 무시 → cluster cap 위반이 D4 retry/fallback **절대 발동 안 함** (사실상 무력화).

신규: `severity="hard"` → mandate-level 강제.

**Stage 4와의 책임 분리** (Commit B 정리 ⑥):
- **Validator (Stage 5)**: baseline cluster_cap=0.25 hard 강제
- **Stage 4 concentration_lens**: *strict-only* cap만 제안 (critical=0.18, high=0.22). validator baseline 0.25 ≤ 인 cap은 no-op.

→ 두 layer 중복 없이 각자 책임:
- Stage 5 = mandate baseline
- Stage 4 = 시장 critical 시 *추가* 압축

### 4.5 turnover_check (`validate_turnover_feasibility`)

대회 §3.1 — turnover floor.

**Stage 5 정리 ④ — `days_remaining` 제거**:
- 시그니처에만 있고 본문 미사용 (dead code)
- 시그니처에서 제거

**공식 (변경 없음)**:
```python
turnover = (buy_amount + sell_amount) / avg_assets
```

이건 "total trade volume" 정의로 buy/sell 양쪽 합산 (2배 카운트). 업계 표준 `(buy+sell)/2/AUM` (two-side average)과 다름.

**왜 유지?**:
- 현재 floor 값 (initial 0.80, monthly 0.10)이 이 정의에 calibrated되어 있음
- 공식 변경 시 floor도 절반으로 조정 필요 → 의도와 같지만 수치 다르게 보임
- 대회 §3.1 룰북 확인 후 마이그레이션 가능 (현재는 self-consistent 유지)

### 4.6 Rebalance mode 명시 분기 (Stage 5 정리 ⑤)

기존:
```python
floor_pct = 0.10 if previous_portfolio else 0.80
days_remaining = 20 if previous_portfolio else 5  # ← 사용 안 됨
```

→ `previous_portfolio` 유무로만 implicit 분기. 2-mode (initial / monthly).

신규:
```python
RebalanceMode = Literal["initial", "monthly"]   # 향후 daily/weekly 확장
FLOOR_BY_MODE: dict[str, tuple[float, int]] = {
    "initial": (0.80, 5),
    "monthly": (0.10, 20),
}

def _resolve_rebalance_mode(state) -> RebalanceMode:
    explicit = state.get("rebalance_mode")
    if explicit in FLOOR_BY_MODE:
        return explicit
    return "monthly" if state.get("previous_portfolio") else "initial"
```

→ explicit `state["rebalance_mode"]` 우선, 없으면 backward-compat. 추가로 `rebalance_mode`가 state output에 기록되어 **archive에 저장**.

daily/weekly는 룰북/운영자 결정 후 `FLOOR_BY_MODE`에 항목 추가.

### 4.7 D4 retry cycle (변경 없음)

`graph/conditional_logic.py:validation_router`:

```python
MAX_ALLOCATION_ATTEMPTS = 2

def validation_router(state):
    if state["validation_passed"]:
        return "finalize"           # → portfolio_manager
    if state["allocation_attempts"] < 2:
        return "retry_allocator"    # → Stage 3 재호출 (band 완화)
    return "fallback"               # → fallback_normalizer
```

`fallback_normalizer` (`conditional_logic.py:create_fallback_normalizer`):
1. Constrained min-variance 재최적화 (`weight_bounds=(0, 0.20)`)
2. 실패 시 `_emergency_cash_portfolio` (등가중 안전자산 5개)

---

## 5. 출력 구조

### 5.1 state 갱신 키

```python
return {
    "validation_report":   ValidationReport(passed, violations),
    "validation_passed":   bool,
    "allocation_feedback": list[Violation]   # hard만 (Stage 3 retry에 주입)
    "rebalance_mode":      RebalanceMode,    # Stage 5 정리 ⑤ — archive
}
```

### 5.2 `ValidationReport` 스키마

```python
class ValidationReport(BaseModel):
    passed:      bool
    violations:  list[Violation]
    suggestions: list[str] = []

    @property
    def has_hard_violations(self) -> bool: ...
    @property
    def hard_violations(self) -> list[Violation]: ...
```

### 5.3 `Violation.rule` Literal (Stage 5 정리에서 2개 추가)

```python
Literal[
    "universe_membership",
    "risk_asset_cap",
    "single_etf_cap",
    "turnover_floor",
    "correlation_concentration",
    "weight_sum",         # ← Stage 5 정리 ③ 신설
    "weight_validity",    # ← Stage 5 정리 ③ 신설
]
```

---

## 6. Downstream 영향 / 호환성

| 다음 단계 | 입력 | 처리 |
|---|---|---|
| `finalize` → Stage 6 portfolio_manager | `weight_vector` (validated) | 정상 path. 리포트 + portfolio.json 생성 |
| `retry_allocator` (D4) | `allocation_feedback` | Stage 3 재호출, attempts++, band ±5%p 완화, per_bucket_n 확장 |
| `fallback` | `weight_vector` | Constrained re-opt → 실패 시 emergency cash |

→ D4 cycle은 Stage 3 → Stage 4 → Stage 5 → (fail) → Stage 3 (band 완화) → Stage 4 → Stage 5 → …

Stage 4는 *retry 시 재실행*되지만 RiskOverlay는 그대로 적용 (이미 검증한 안전한 overlay).

---

## 7. Graceful Degradation

| 실패 | Fallback |
|---|---|
| `weight_vector` 없음 | 즉시 `validation_passed=False`, `weight_validity` hard violation |
| `integrity` hard fail (NaN/Inf) | 다른 check skip, 즉시 retry/fallback |
| `correlation_clusters` empty | correlation_check는 no-op (Stage 1 fail 시 silent) |
| `previous_portfolio` 없음 | `initial` mode 자동 (backward-compat) |
| `rebalance_mode` 비정상 값 | FLOOR_BY_MODE에 없으면 backward-compat (`previous_portfolio` 유무) |
| D4 retry 2회 후도 fail | fallback_normalizer (constrained re-opt) → emergency cash |

→ Stage 5는 *통과/실패* 결정만 하고 weight 자체는 안 건드림 (Stage 3/Stage 4 책임). emergency cash는 마지막 안전망.

---

## 8. 비용 / 복잡도

| 항목 | Before | After |
|---|---|---|
| **LLM 호출** | 0 | **0회** (변경 없음) |
| **외부 fetch** | 0 | 0 |
| **코드 라인** | ~205 LOC | ~310 LOC (integrity + RebalanceMode + 명시 매핑) |
| **테스트** | 기존 + 2 폐기 + 13 신규 | net +11 |
| **silent bug** | 4개 (①③④⑤) | **0개** |

→ Stage 5는 *fast deterministic*. 매 실행 1ms 이내. 비용은 무시 가능.

---

## 9. 검증 결과

| 항목 | 결과 |
|---|---|
| 단위 테스트 | **573 passing** (회귀 0건) |
| Stage 5 신규 unit test | **+13** (integrity 10 + cluster_caps strict-only 3) |
| Stage 5 기존 test 수정 | 2 (turnover signature, correlation severity) |
| Integration | 7 passing (subgraph isolation, phase1 smoke, plan pipeline, 5_28 dry run, risk subgraph, validator cycle) |

### 핵심 invariant 검증
- ① cluster cap 위반 → `severity="hard"` → router가 retry 발동
- ② risk_asset_cap이 BUCKET_TO_CATEGORIES 기준으로 계산
- ③ NaN/Inf/sum/음수/empty 모두 hard violation
- ④ turnover_check 시그니처에 `days_remaining` 제거됨
- ⑤ explicit `rebalance_mode` 우선, backward-compat 보장
- ⑥ Stage 4 concentration_lens preset 모두 validator baseline 0.25 ≤ (strict-only)

---

## 10. Stage 1 / 2 / 3 / 4 / 5 디자인 일관성

| 항목 | Stage 1 | Stage 2 | Stage 3 | Stage 4 | Stage 5 |
|---|---|---|---|---|---|
| LLM 사용 (매일) | quick + subagents | deep 1회 | 0회 | 0회 | **0회** |
| 결정 방식 | LLM + 결정적 mix | 시나리오 확률 → 결정적 매핑 | 결정적 함수 + Stage 3 optimizer | 결정적 룰 + optimizer | **순수 결정적 룰** |
| 외부 fetch | 다수 (FRED/ECOS/yfinance 등) | 0 | 1회 (returns matrix) | 1회 (returns matrix) | **0** |
| Archive | runs/{date}/{report}.json | research_decision.json | candidate/weight/method.json | overlay/weight/summary.json | (validation_report만, archive 기록 X) |
| Mandate 역할 | 입력 검증 | invariant (SCENARIO_BUCKETS) | weight_bounds + sector | overlay → constraint | **enforce + retry/fallback router** |

→ Stage 5는 *가장 결정적*. mandate enforcement의 single source of truth.

---

## 11. Phase 누적 결과

| Phase | 작업 | 효과 | Commit |
|---|---|---|---|
| Baseline | 4 mandate check (universe/concentration/correlation/turnover) + D4 retry | 기본 enforcement | (pre-existing) |
| **Commit A** | ① soft→hard / ② BUCKET_TO_CATEGORIES / ③ NaN/Inf integrity / ④ days_remaining 제거 / ⑤ RebalanceMode Literal | 5가지 silent bug 해소 | `24c6e40` |
| **Commit B** | ⑥ Stage 4 concentration_lens preset 재조정 (validator baseline strict-only) | Stage 4↔5 책임 분리 | `be5409a` |

**총 변화**:
- LLM: 0회 (변경 없음, 영원히 deterministic)
- silent bug: 4개 → 0개
- 새 룰 추가: 0 (대회 §에 없는 것은 X)
- 신규 test: 13 (회귀 0)

---

## 12. 운영 절차

매일 운영에서 Stage 5는 **완전 자동**. 코드 변경 없이:
1. Stage 4가 weight_vector 갱신 (또는 그대로 통과)
2. Stage 5 6 check 순차 실행 (integrity → universe → concentration → correlation → turnover)
3. 통과 → finalize, fail → retry/fallback

### Rebalance mode 명시 운영 시

```python
# 일일 운영자가 state에 rebalance_mode 명시 가능
state["rebalance_mode"] = "monthly"   # FLOOR_BY_MODE에 정의된 값
# 또는 명시 안 하면 previous_portfolio 유무로 자동
```

향후 daily/weekly 도입 시:
```python
# 1. mandate.py: RebalanceMode = Literal["initial","monthly","daily","weekly"]
# 2. mandate_validator.py: FLOOR_BY_MODE에 항목 추가
FLOOR_BY_MODE = {
    "initial": (0.80, 5),
    "monthly": (0.10, 20),
    "weekly":  (?, ?),   # 룰북 / 운영자 결정
    "daily":   (?, ?),   # 룰북 / 운영자 결정
}
```

---

## 13. 파일 매니페스트

| 위치 | 파일 |
|---|---|
| 노드 | `tradingagents/agents/validator/mandate_validator.py` |
| 4 check | `tradingagents/skills/mandate/{universe,concentration,correlation,turnover}_check.py` |
| Fallback | `tradingagents/graph/conditional_logic.py:create_fallback_normalizer` |
| D4 router | `tradingagents/graph/conditional_logic.py:validation_router` |
| 스키마 | `tradingagents/schemas/mandate.py` (Violation, ValidationReport, RebalanceMode) |
| 단위 테스트 | `tests/unit/skills/test_mandate_*.py`, `tests/unit/agents/test_mandate_integrity.py` |
| Integration | `tests/integration/test_validator_cycle.py` (D4 retry 흐름) |

---

## 14. 디자인 의사결정 기록

### 왜 재설계 X (micro-patch만)?

기존 구조 (4 check + D4 retry)가 본질적으로 옳음. 문제는 *세부 룰의 silent bug*뿐 — 구조 변경 비용 vs 개선 효과 trade-off에서 patch가 압도적 우월.

### 왜 correlation severity를 hard로 승격?

기존 `soft`는 validator의 `passed = not any(hard)`로 무시되어 *사실상 dead 룰*. 두 선택지:
- **승격 (선택)**: validator가 mandate-level 강제, Stage 4와 책임 분리
- **유지 + Stage 4가 동적 처리**: Stage 4 Phase 2 의존, 작동 안 하면 silent miss

승격이 더 안전 + Stage 4와 자연 결합.

### 왜 turnover 공식은 그대로 유지?

`(buy+sell)/AUM` (total volume)이 업계 표준 `(buy+sell)/2/AUM` (two-side avg)과 다르지만:
- 현재 floor 80%/10%이 이 정의에 calibrated
- 공식 변경 시 floor 절반 조정 필요 → *의도 동일, 수치 다르게 보임*
- 대회 §3.1 룰북 확인 후 마이그레이션 가능

→ self-consistent within our system. 회귀 위험 0.

### 왜 LLM 추가 안 함?

Stage 5는 *mandate enforcement*. 룰 자체가 deterministic threshold (단일 cap 20%, 위험자산 70% 등) → LLM이 추가 가치 만들 영역 없음. 영원히 결정적 유지.

### 왜 새 룰 추가 안 함?

대회 §에 명시 안 된 룰 (예: max turnover 상한, min holding period)을 자체로 추가하면:
- mandate compliance 측면에서 over-conservative
- 모델 성능 trade-off (대회 평가 영역과 직교)

→ 대회 §에 명시된 것만 강제. 추가 risk control은 Stage 4 lens 영역.

### 왜 Validator → Stage 4 역방향 흐름 없음?

```
[현재] Stage 4 → Stage 5 → (fail) → Stage 3 retry → Stage 4 → Stage 5 → ...
```

만약 Validator가 Stage 4에게 *"이 cluster cap을 더 strict하게"* 같은 신호를 보내려면:
- 책임 모호화
- 무한 루프 위험

→ 책임 경계 명확: Validator는 *통과/실패*만, weight 조정은 Stage 3/Stage 4가 D4 retry로 시도.

### 왜 Fail-fast 도입 안 함?

4 check 다 돌리는 비용 ≈ 1ms. 비용 무시 가능 + *모든 violation을 리포트에 노출*하는 가치 ↑ (Stage 6 리포트 + 향후 개선 정보).

→ integrity pre-check만 fail-fast (다른 check 의미 없으므로). 나머지 4개는 all-run.

### 왜 Stage 4 cluster_caps를 strict-only로?

기존 preset (0.30/0.35) → validator 0.25보다 *느슨* → no-op (실효성 0).

새 preset (0.18/0.22) → validator baseline 위에서 *추가 압축*. 시장 critical 시점에만 발동.

→ 두 layer 책임:
- Stage 5 = 항상 0.25 hard 강제
- Stage 4 = 시장 위험 시 *추가* 0.18까지 압축

---

## 15. 향후 로드맵 (선택적)

### 우선순위 낮음 (룰북 확인 의존)

- **A. turnover 공식 마이그레이션**
  - 대회 §3.1이 two-side average `(buy+sell)/2/AUM`을 요구하면 공식 + floor 절반 조정
  - 현재 self-consistent이라 위험 0

- **B. daily/weekly rebalance mode 추가**
  - 룰북 확인 또는 운영자 결정 후 `FLOOR_BY_MODE`에 항목 추가
  - 기존 코드 변경 0, dict 항목만 추가

### 우선순위 낮음 (Phase 3 운영 후)

- **C. ValidationReport archive**
  - 현재 archive 안 됨 (Stage 5 결과는 in-memory만)
  - Phase 3 패턴으로 `runs/{date}/validation_report.json` 추가 가능
  - 의미: D4 retry 발동 빈도 + 위반 패턴 사후 분석

- **D. Soft 정보 활용 (suggestions 필드)**
  - `ValidationReport.suggestions` 필드는 정의되어 있지만 미사용
  - Stage 6 리포트에서 *경고* 형태로 활용 가능 (turnover 100% → 거래비용 주의 등)

- **E. RebalanceMode daily/weekly 도입 시 daily_triggers 통합**
  - `rebalance/daily_triggers.py`는 이미 존재 (VIX>30 등 트리거)
  - 트리거 발동 시 rebalance_mode="daily" 자동 설정 가능

---

각 향후 항목은 baseline에 대한 **선택적 확장**. 현재 Stage 5는 mandate enforcement에 충분.
