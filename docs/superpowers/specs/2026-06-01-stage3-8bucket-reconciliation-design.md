# Stage 3 — 8-Bucket Reconciliation (Stage 2 통합 복구)

- **작성일:** 2026-06-01
- **대상:** Stage 3 (portfolio allocation) 구현자
- **선행 의존:** [Tier 0](./2026-05-28-tier0-factor-model-reform-design.md) (12 factor), [Tier 1](./2026-05-28-tier1-bucket-taxonomy-design.md) (8 bucket), [Tier 2](./2026-05-28-tier2-calibration-design.md) (calibrated β) — **이미 main 머지 완료**
- **관련 작업:** Stage 3 Phase 1~4d (NCO/BL/method_picker — `docs/stage3-implementation-summary.md`)

---

## 0. TL;DR

Tier 0/1/2 reform (PR #12)이 Stage 2 factor model을 **5-bucket → 8-bucket** 으로 교체하며 main에 머지됐으나, Stage 3 portfolio allocation은 **부분적으로만 마이그레이션**되어 현재 **import 자체가 불가능한 깨진 상태**다. 본 spec은 Stage 3를 8-bucket schema에 완전히 정합시킨다.

**3대 결정 (사용자 확정):**
1. **범위:** Stage 3 할당 전체 8-bucket 복구 (Stage 4 overlay는 범위 외).
2. **cash_spillover:** 8-bucket 동적 재작성, **RISK_BUCKETS 4개만** cash로 spill (안전자산 제외).
3. **SCENARIO_BUCKET_RULEBOOK:** Tier 1 `INITIAL_BETA` 부호 패턴 기반으로 9×5 → 9×8 파생.

**검증:** `pytest` collection ERROR 11 → 0, 모든 allocator/portfolio 테스트 green, 8-bucket BucketTarget로 allocator E2E 완주.

---

## 1. 현재 깨진 상태 (ground-truth 확정)

### 1.1. 🔴 P0 — import 불가

`tradingagents/skills/portfolio/candidate_selector.py:55-57`에 Tier 1 머지가 남긴 **고아 docstring 조각**:

```python
# line 51:  DEFAULT_BOOST_SCALE: float = 1.0
# ...
# line 55:      Uses bucket_for_etf() which respects sub_category for ambiguous categories
# line 56:      (FX 및 원자재 → precious_metals vs cyclical_commodity_fx;
# line 57:       국내채권_종합/해외채권_종합 → kr_bond / credit / global_duration).
# line 59:  def _eligible_for_bucket(universe: Universe, cats: list[str]):
```

→ `IndentationError: unexpected indent` → `portfolio_allocator.py`가 `candidate_selector`를 import 하므로 **연쇄적으로 11개 테스트 모듈 collection ERROR**.

### 1.2. 🔴 P0 — 라이브 할당 경로 crash

`BucketTarget`은 Tier 1에서 `weights: dict[str, float]` 단일 필드로 재설계됨 (`schemas/portfolio.py:14-72`). legacy attribute(`bucket_target.kr_equity`)와 legacy kwargs 생성(`BucketTarget(kr_equity=...)`)은 **모두 실패**(AttributeError / ValidationError). `__getitem__`/`get`/`items`/`keys`/`values` dict-like accessor만 존재.

그런데 다음이 여전히 legacy 5-bucket을 사용:

| 위치 | 문제 | 실패 유형 |
|---|---|---|
| `cash_spillover.py:118-121` | `bucket_target.kr_equity + .fx_commodity + .bond` 합산 | AttributeError |
| `cash_spillover.py:127,142,164` | `bucket_names=('kr_equity','global_equity','fx_commodity','bond','cash_mmf')` | KeyError/누락 |
| `cash_spillover.py:188-194` | `BucketTarget(kr_equity=..., fx_commodity=..., bond=...)` kwargs 생성 | ValidationError |
| `portfolio_allocator.py:235-240` | attribution `bucket_target_stage2` 스냅샷 5-bucket attr | AttributeError |
| `portfolio_allocator.py:261-265` | attribution `bucket_target` 스냅샷 5-bucket attr | AttributeError |
| `portfolio_allocator.py:1121-1126` | `_nco_per_bucket` target_map 5-bucket attr | AttributeError |
| `portfolio_allocator.py:1136` | `_nco_per_bucket` TIPS split이 `bucket == "bond"` (8-bucket엔 없음) | silent skip |

`cash_spillover.adjust_bucket_targets`는 `portfolio_allocator.py:245`에서 무조건 호출되므로, 8-bucket BucketTarget이 들어오면 **즉시 crash**.

### 1.3. 🟡 P1 — 5-bucket 로직이 조용히 틀린 결과

| 위치 | 문제 |
|---|---|
| `candidate_selector.py:32-41` | `BUCKET_TO_CATEGORIES` 5키. line 85, 233에서 `BUCKET_TO_CATEGORIES[bucket_name]` → split bucket KeyError. `_eligible_for_bucket`이 `bucket_for_etf()` 미사용 |
| `bl_views.py:15-34` | `SCENARIO_BUCKET_RULEBOOK` 9×5. `generate_bl_views`가 8-bucket 후보 중 precious_metals/cyclical_commodity_fx/kr_bond/credit/global_duration를 line 111(`if bucket not in bucket_returns: continue`)에서 **조용히 skip** → BL view 누락 |

### 1.4. 🟡 P1 — 테스트/픽스처 5-bucket

| 위치 | 문제 |
|---|---|
| `tests/integration/_allocator_state_helpers.py:19-25` | `BUCKET_CATEGORIES` 5키 (10개 phase 테스트가 사용) |
| `tests/integration/_allocator_state_helpers.py:90-107` | `make_bucket_target()` 5-positional-arg + 5-bucket kwargs |
| `tests/integration/test_allocator_phase1.py:106` | `BUCKET_CATEGORIES['fx_commodity']` 하드코딩 |
| `tests/integration/test_allocator_phase3a.py:102` | 5-bucket 튜플 순회 |
| `tests/unit/skills/test_portfolio_bl_views.py:23-26` | `test_rulebook_has_all_5_buckets` (정확히 5개 강제) |
| `tests/unit/skills/test_portfolio_cash_spillover.py:217-221` | 5-bucket 순회 |

### 1.5. ✅ 이미 8-bucket (변경 불필요)

`factor_to_bucket.py` (BUCKETS/FACTORS/INITIAL_BETA/INITIAL_BASELINE), `factor_calibration.py` (HARD_ZERO_CELLS/BUCKET_FAMILIES), `schemas/portfolio.py` (BucketTarget), `sub_category.py` (`bucket_for_etf`, `VALID_SUB_CATEGORIES`, `_CATEGORY_TO_BUCKET`, `_SPLIT_TARGETS`), `portfolio_allocator.py`의 `_build_ticker_to_bucket_map`(L440-464)·`_hrp_per_bucket`(L953-969) (global_duration TIPS split 이미 적용), `bucket_returns_8b.py`, `anchor_evaluator.py`.

---

## 2. 8-bucket schema 기준 (Tier 1 §1)

```python
BUCKETS = (
    "kr_equity", "global_equity",
    "precious_metals", "cyclical_commodity_fx",   # ← fx_commodity 분할
    "kr_bond", "credit", "global_duration",        # ← bond 분할
    "cash_mmf",
)
RISK_BUCKETS = ("kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx")
```

매핑: 옛 `fx_commodity` = `precious_metals` + `cyclical_commodity_fx`; 옛 `bond` = `kr_bond` + `credit` + `global_duration`. TIPS(inflation_linked sub_category)는 Tier 1 §6 기준 `global_duration` 소속.

---

## 3. 컴포넌트별 설계

### 3.1. `candidate_selector.py` — bucket_for_etf 기반 eligibility

**문제:** syntax error + `BUCKET_TO_CATEGORIES` 5키가 split bucket을 처리 못 함.

**설계:** `sub_category.bucket_for_etf(etf) -> str | None` (이미 8-bucket 권위 분류기)로 eligibility 일원화. `BUCKET_TO_CATEGORIES` dict 제거.

```python
def _eligible_for_bucket(universe: Universe, bucket_name: str) -> list:
    """ETFs that classify into the given 8-bucket via bucket_for_etf().

    Replaces the legacy category-list match. bucket_for_etf() handles
    sub_category disambiguation for split buckets (precious_metals vs
    cyclical_commodity_fx; kr_bond / credit / global_duration).
    """
    return [e for e in universe.etfs if bucket_for_etf(e) == bucket_name]
```

- 고아 docstring 조각(L55-57) 제거 → `_eligible_for_bucket` docstring으로 정상화.
- 호출처 2곳 갱신:
  - `list_eligible_tickers` L85-86: `cats = BUCKET_TO_CATEGORIES[bucket_name]` 제거 → `_eligible_for_bucket(universe, bucket_name)`.
  - `select_etf_candidates` L233-234: 동일.
- `bucket_name == "bond_tips_share"` skip 가드는 유지 (BucketTarget 순회 시 weights 키만 처리하므로 실제로 불필요하나 방어적으로 보존; weights에는 bond_tips_share 키가 없음 → 자연히 통과).

**TIPS quota 경로 (audit 발견 — `_nco`와 동일 누락):** `select_etf_candidates` L245의 `if bucket_name == "bond" and bucket_target.bond_tips_share > 0.0:` → `if bucket_name == "global_duration" and ...`. 이 분기는 `_select_bond_with_tips_quota`(L346)를 호출해 `inflation_linked` sub_category quota를 적용한다. 8-bucket엔 `"bond"` 키가 없어 **현재 TIPS quota가 영영 발동 안 함**. L215 주석은 이미 "TIPS quota applies to global_duration"이라 명시하나 코드만 legacy. `_select_bond_with_tips_quota` 내부 로직(`inflation_linked` vs 나머지 split)은 변경 불필요 — global_duration 풀의 US TIPS 를 정상 분리.

**`BUCKET_TO_CATEGORIES` 외부 importer 처리 (audit 발견):** 단순 제거 시 3개 importer가 깨짐 →
  - `portfolio_allocator.py:21`: **미사용 import** → import 라인에서 제거.
  - `observability/stage3_ablation.py:28,178`: import + `for bucket in BUCKET_TO_CATEGORIES.keys()` 순회 → 동적 `cs.bucket_to_tickers.keys()` (또는 `factor_to_bucket.BUCKETS`) 8-bucket 순회로 교체.
  - `scripts/stage3_ablation.py:40`: import 갱신 (동일 패턴).

**`inflation_linked` 이중 등록 (audit 검토 — 정상):** `VALID_SUB_CATEGORIES`에서 `inflation_linked`가 kr_bond(L62)·global_duration(L73) 양쪽에 있으나, `_SPLIT_TARGETS`가 category로 구분(국내채권_종합→kr_bond, 해외채권_종합→global_duration)하므로 KR 물가채는 `kr_bond`, US TIPS는 `global_duration`으로 정확히 분류됨. `bond_tips_share`는 global_duration 풀의 US-TIPS 비율에 적용. **sub_category.py 변경 불필요.**

**경계/의존:** 입력 = `Universe` + 8-bucket `BucketTarget`. 출력 = `dict[bucket_name, list[ticker]]` (8키). `bucket_for_etf`가 None 반환하는 미분류 ETF는 어떤 bucket에도 안 들어감 (기존 category-miss 동작과 동일).

### 3.2. `cash_spillover.py` — 8-bucket 동적 + RISK_BUCKETS만 spill

**핵심 원칙 (사용자 확정):** conviction 공식 `(mean_alpha/threshold) × (ENB/√N)` 은 **alpha를 추구하는 위험자산에만 유효**하다. 안전자산(kr_bond/credit/global_duration)은 alpha가 아니라 risk ballast로 보유하므로 alpha-conviction으로 평가해 cash로 흘리면 Stage 2의 의도적 duration/credit 배분을 잠식한다. → **spill 대상 = RISK_BUCKETS 4개**.

**상수 변경:**

```python
# RISK_BUCKETS — spillover 평가 대상 (Tier 1 정의와 일치)
SPILLOVER_RISK_BUCKETS: tuple[str, ...] = (
    "kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx",
)

# 옛 fx_commodity:0.15 → 분할된 두 자식이 계승
SPILLOVER_THRESHOLD_BY_BUCKET: dict[str, float] = {
    "precious_metals": 0.15,
    "cyclical_commodity_fx": 0.15,
}
SPILLOVER_THRESHOLD_DEFAULT: float = 0.3   # unchanged
CASH_CAP_FOR_SPILLOVER_TARGET: float = 0.40  # unchanged
```

**`adjust_bucket_targets` 재작성 (구조 보존, 5-bucket 하드코딩만 제거):**

```python
def adjust_bucket_targets(bucket_target, bucket_chosen, alpha_scores_by_bucket, returns):
    weights = dict(bucket_target.weights)              # 8-bucket dict, 동적
    total_in = sum(weights.values())
    assert abs(total_in - 1.0) < SPILLOVER_NUMERICAL_TOLERANCE

    # conviction은 RISK_BUCKETS 중 weight>0 인 것만 (안전자산은 평가/ spill 안 함)
    risk_buckets = [b for b in SPILLOVER_RISK_BUCKETS if weights.get(b, 0.0) > 0.0]
    convictions = {
        b: compute_bucket_conviction(
            bucket=b, chosen=bucket_chosen.get(b, []),
            alpha_scores=alpha_scores_by_bucket.get(b, {}), returns=returns,
        )
        for b in risk_buckets
    }

    adjusted = dict(weights)
    # Step 1 — RISK_BUCKET → cash 비례 spillover
    spillover_amounts = {}
    for b in risk_buckets:
        amt = adjusted[b] * convictions[b].spillover_ratio
        spillover_amounts[b] = amt
        adjusted[b] -= amt
    cash_new = adjusted["cash_mmf"] + sum(spillover_amounts.values())

    # Step 2 — effective_cap = max(0.40, macro cash)
    effective_cap = max(CASH_CAP_FOR_SPILLOVER_TARGET, weights["cash_mmf"])
    if cash_new <= effective_cap:
        adjusted["cash_mmf"], overflow, cash_cap_triggered = cash_new, 0.0, False
    else:
        adjusted["cash_mmf"], overflow, cash_cap_triggered = effective_cap, cash_new - effective_cap, True

    # Step 3 — overflow → high-conviction RISK_BUCKET (conviction 가중)
    cash_overflow_to_buckets = {}
    if overflow > 0:
        high_conv = {b: convictions[b].conviction for b in risk_buckets
                     if convictions[b].conviction >= convictions[b].threshold}
        if high_conv:
            tw = sum(high_conv.values())
            for b, c in high_conv.items():
                add = overflow * (c / tw)
                adjusted[b] += add
                cash_overflow_to_buckets[b] = add
        else:
            adjusted["cash_mmf"] += overflow
            logger.warning("all risk buckets low-conviction; cash exceeds cap")

    # invariant
    if abs(sum(adjusted.values()) - 1.0) > SPILLOVER_NUMERICAL_TOLERANCE:
        raise RuntimeError("spillover sum invariant broken")

    adjusted_bt = BucketTarget(
        weights=adjusted,
        bond_tips_share=bucket_target.bond_tips_share,
        rationale=(f"{bucket_target.rationale or ''} | spillover "
                   f"{sum(spillover_amounts.values()):.3f} → cash")[:300],
    )
    return SpilloverResult(
        adjusted_bucket_target=adjusted_bt, convictions=convictions,
        cash_overflow_to_buckets=cash_overflow_to_buckets,
        total_spillover_to_cash=sum(spillover_amounts.values()),
        cash_cap_triggered=cash_cap_triggered,
        thresholds={b: _threshold_for(b) for b in risk_buckets},
    )
```

**동작 변화 (의도됨):** 기존엔 `bond`도 spill 대상이었으나, 신규엔 안전자산(kr_bond/credit/global_duration)은 spill 제외 → 거시 판단대로 유지. 안전자산이 conviction에서 빠지므로 `SpilloverResult.convictions`/`thresholds`는 **weight>0 인 RISK_BUCKET만** 포함(≤4 키, partial dict). 소비자(`attribution["cash_spillover"]` model_dump, 로깅)는 partial dict 무관. `cash_mmf`는 8-bucket BucketTarget 불변식상 항상 존재 → 직접 접근 유지 (불가능 케이스 방어 안 함).

**경계/의존:** 출력 `adjusted_bucket_target`은 항상 8키 weights sum=1.0 보존, `bond_tips_share` 보존.

### 3.3. `bl_views.py` — SCENARIO_BUCKET_RULEBOOK 9×8

`fx_commodity` → `precious_metals` + `cyclical_commodity_fx`, `bond` → `kr_bond` + `credit` + `global_duration` 분해. kr_equity/global_equity/cash_mmf는 원본 유지. cash_mmf = 0.025 (KOFR floor), |값| ≤ 0.30 유지 (test 강제).

**파생 원칙:** Tier 1 `INITIAL_BETA` 부호 패턴 + Tier 1 §1.1 economic driver:
- `precious_metals`: real rate↓·USD↓·systemic stress hedge (gold-like, 방어적).
- `cyclical_commodity_fx`: inflation↑·growth↑·DXY (oil/copper, 경기순응).
- `kr_bond`: KR rate·term premium.
- `credit`: credit spread·growth (**risk-on 성격** — stress 시 음수).
- `global_duration`: US real rate·term premium (risk-off 강한 안전판).

```python
SCENARIO_BUCKET_RULEBOOK: dict[str, dict[str, float]] = {
    "goldilocks":       {"kr_equity": 0.10, "global_equity": 0.12,
                         "precious_metals": 0.02, "cyclical_commodity_fx": 0.03,
                         "kr_bond": 0.02, "credit": 0.05, "global_duration": 0.03,
                         "cash_mmf": 0.025},
    "overheating":      {"kr_equity": 0.06, "global_equity": 0.08,
                         "precious_metals": 0.06, "cyclical_commodity_fx": 0.12,
                         "kr_bond": 0.01, "credit": 0.03, "global_duration": -0.01,
                         "cash_mmf": 0.025},
    "late_cycle":       {"kr_equity": 0.02, "global_equity": 0.04,
                         "precious_metals": 0.07, "cyclical_commodity_fx": 0.06,
                         "kr_bond": 0.06, "credit": 0.00, "global_duration": 0.07,
                         "cash_mmf": 0.025},
    "stagflation":      {"kr_equity": -0.05, "global_equity": -0.03,
                         "precious_metals": 0.13, "cyclical_commodity_fx": 0.10,
                         "kr_bond": 0.00, "credit": -0.03, "global_duration": 0.00,
                         "cash_mmf": 0.025},
    "broad_recession":  {"kr_equity": -0.08, "global_equity": -0.05,
                         "precious_metals": 0.04, "cyclical_commodity_fx": -0.06,
                         "kr_bond": 0.07, "credit": -0.04, "global_duration": 0.10,
                         "cash_mmf": 0.025},
    "kr_stress":        {"kr_equity": -0.10, "global_equity": 0.05,
                         "precious_metals": 0.06, "cyclical_commodity_fx": 0.04,
                         "kr_bond": 0.03, "credit": 0.01, "global_duration": 0.07,
                         "cash_mmf": 0.025},
    "global_credit":    {"kr_equity": -0.05, "global_equity": -0.08,
                         "precious_metals": 0.02, "cyclical_commodity_fx": -0.05,
                         "kr_bond": 0.05, "credit": -0.08, "global_duration": 0.10,
                         "cash_mmf": 0.025},
    "ai_concentration": {"kr_equity": 0.05, "global_equity": 0.10,
                         "precious_metals": 0.02, "cyclical_commodity_fx": 0.02,
                         "kr_bond": 0.03, "credit": 0.04, "global_duration": 0.02,
                         "cash_mmf": 0.025},
    "kr_boom":          {"kr_equity": 0.13, "global_equity": 0.08,
                         "precious_metals": 0.01, "cyclical_commodity_fx": 0.04,
                         "kr_bond": 0.00, "credit": 0.04, "global_duration": 0.01,
                         "cash_mmf": 0.025},
}
```

**핵심 — 8-bucket 분해가 드러내는 신호:** recession/credit 시나리오(broad_recession, global_credit)에서 `global_duration`은 강한 안전판(+0.10)이지만 `credit`은 폭락(-0.04 ~ -0.08). 5-bucket의 단일 `bond`는 이 둘을 뭉개고 있었다. 부호는 `INITIAL_BETA`의 F10(systemic, broad_recession ↔) row(precious +, kr_bond +, credit −, gl_dur +, cyclical −) 및 F2(inflation, stagflation ↔) row(precious +, cyclical +, duration −, credit −)와 일치 검증함.

**부호 판단 메모 (adversarial audit 반영):**
- **성장 시나리오의 채권 중립화** — `goldilocks` kr_bond 0.02 (disinflation 금리인하 채널로 약하게 +), `kr_boom` kr_bond 0.00 (강한 KR 성장 → BOK 긴축 압력, F12 kr_bond − 반영 중립화). 순수 F1_growth row는 kr_bond −0.04 이나, goldilocks 는 disinflation 동반이라 약한 + 유지.
- **late_cycle credit 중립화** — 0.03 → 0.00. late cycle 은 spread 확대 국면(F5_credit_cycle credit −0.06)이라 risk-on 자산인 credit 을 + 로 두지 않음.
- **stagflation global_duration 중립 (의도적 — audit 권고 +0.05 와 다름)** — 0.00 유지. stagflation 은 **deflationary recession 이 아니다**. 인플레가 명목 duration(global_duration ETF 가 보유)을 직접 훼손(2022년 TLT −30% 사례)하므로 broad_recession(+0.10) 같은 안전판이 **아니다**. real-rate 하락(우호)과 inflation premium(불리)이 상쇄 → 중립 0.00 이 가장 방어 가능. (TIPS 는 bond_tips_share 로 global_duration 내 별도 처리되어 stagflation 수혜를 일부 포착.)

`generate_bl_views`(L64-134) 함수 본체는 **변경 없음** — 이미 candidates 키를 동적 순회하고 rulebook에 있는 bucket만 view 생성한다. rulebook이 8키가 되면 자동으로 8-bucket view 생성. `SCENARIO_BL_TILT`(L51-61)도 bucket 차원이 없어 변경 없음.

### 3.4. `portfolio_allocator.py` — attribution + _nco 동적화

**attribution 스냅샷 (L234-241, L260-266):** 5-bucket attr 열거 → `dict(bucket_target.weights)` 동적.

```python
# L234-241
attribution["config"]["bucket_target_stage2"] = {
    **dict(bucket_target.weights),
    "bond_tips_share": bucket_target.bond_tips_share,
}
# L260-266
attribution["config"]["bucket_target"] = dict(bucket_target.weights)
```

**`_nco_per_bucket` (L1121-1155):** target_map 동적화 + TIPS split을 `global_duration` 기준으로 (기존 HRP 경로 L953-969 / ticker-map 경로 L440-464와 동일 패턴 정렬).

```python
# L1121-1126
target_map = dict(bucket_target.weights)   # 8-bucket, 동적
split_bond = bucket_target.bond_tips_share > 0.0
# ...
# L1136: TIPS split 키 변경
if bucket == "global_duration" and split_bond:   # was: bucket == "bond"
    tips_tickers = [t for t in tickers if sub_category_lookup.get(t) == "inflation_linked"]
    tips_target = target * bucket_target.bond_tips_share
    nominal_target = target * (1.0 - bucket_target.bond_tips_share)
    # ... (이하 sub_buckets append 로직 동일)
```

**의존:** `_build_ticker_to_bucket_map`·`_hrp_per_bucket`는 이미 8-bucket이므로 변경 없음. NCO 경로만 HRP 경로와 동작 일치.

### 3.5. 테스트 / 픽스처 8-bucket

- `_allocator_state_helpers.py`:
  - `BUCKET_CATEGORIES`: 8-bucket으로 확장 (각 bucket → 합성 universe용 category/sub_category). `bucket_for_etf`가 분류 가능하도록 sub_category 라벨 부여.
  - `make_bucket_target()`: 8-bucket weights dict 생성 + sum=1.0 검증. `BucketTarget(weights={...}, rationale=..., bond_tips_share=...)`.
- `test_allocator_phase1.py:106`: `BUCKET_CATEGORIES['fx_commodity']` → 8-bucket 키.
- `test_allocator_phase3a.py:102`: 5-bucket 순회 → 8-bucket 순회.
- `test_portfolio_bl_views.py:23-26`: `test_rulebook_has_all_5_buckets` → `test_rulebook_has_all_8_buckets` (expected_buckets = 8키).
- `test_portfolio_cash_spillover.py:217-221`: RISK_BUCKETS(4개) 기준으로 갱신 + 안전자산 spill 안 됨 검증 추가.

---

## 4. 데이터 흐름 (수정 후)

```
Stage 2 research_manager
  → BucketTarget(weights={8-bucket}, bond_tips_share, rationale)   [state["bucket_target"]]
       │
Stage 3 portfolio_allocator
  ├─ candidate_selector: bucket_for_etf() → bucket_to_tickers (8키)
  ├─ cash_spillover: RISK_BUCKETS 4개 conviction → cash spill → adjusted BucketTarget (8키)
  ├─ method_picker: scenario → method (bucket-agnostic, 변경 없음)
  ├─ bl_views: SCENARIO_BUCKET_RULEBOOK[scenario] (8키) → 8-bucket BL views
  └─ NCO/HRP per-bucket: target_map = weights (8키), global_duration TIPS split
       → WeightVector (ticker → weight, sum=1.0)
```

---

## 5. 에러 처리 / 불변식

- **BucketTarget sum=1.0**: cash_spillover 입력·출력 모두 `SPILLOVER_NUMERICAL_TOLERANCE`(1e-9) 검증. 깨지면 RuntimeError.
- **미분류 ETF**: `bucket_for_etf` None → 해당 ETF는 어떤 bucket에도 미포함 (기존 동작 유지, crash 없음).
- **빈 bucket**: weight>0 이지만 candidate 0개 → 기존 NCO/HRP fallback(equal weight / shortfall 기록) 그대로.
- **unknown scenario**: `generate_bl_views`가 rulebook에 없는 scenario면 빈 view + `fallback_reason` 기록 (기존 동작 유지).

---

## 6. 테스트 전략

1. **import/collection**: `pytest --collect-only` → 11 ERROR 제거.
2. **candidate_selector**: 8-bucket BucketTarget → 각 bucket의 eligible ticker가 `bucket_for_etf` 결과와 일치. split bucket(precious vs cyclical) 분리 검증.
3. **cash_spillover**: RISK_BUCKETS 4개만 spill, 안전자산 weight 불변, sum=1.0, low/high-conviction overflow 재분배.
4. **bl_views**: `SCENARIO_BUCKET_RULEBOOK` 9 scenario × 8 bucket, `generate_bl_views`가 8-bucket 후보 전부에 view 생성 (skip 0).
5. **allocator E2E**: 8-bucket mock state → allocator 완주, attribution 8키 스냅샷, NCO global_duration TIPS split 동작.
6. **regression**: 기존 phase 테스트(1~4d) green 복구.

---

## 7. Acceptance Criteria

### 7.1. 복구
- [ ] `candidate_selector.py` import OK, syntax error 제거
- [ ] `pytest tests/unit/skills/test_portfolio_*.py tests/integration/test_allocator_*.py --collect-only` → 0 errors
- [ ] 8-bucket BucketTarget로 `allocate_portfolio` E2E 완주 (crash 없음)

### 7.2. 정합성
- [ ] `candidate_selector`가 `bucket_for_etf()` 사용, `BUCKET_TO_CATEGORIES` 제거
- [ ] `candidate_selector` TIPS quota 경로(L245)가 `global_duration` 기준 → `_select_bond_with_tips_quota` 실제 발동
- [ ] `BUCKET_TO_CATEGORIES` 외부 importer 3곳(portfolio_allocator import, observability/scripts stage3_ablation) 갱신, import 에러 0
- [ ] `cash_spillover`가 RISK_BUCKETS 4개만 spill, 안전자산 불변, `BucketTarget(weights=...)` 생성
- [ ] `SCENARIO_BUCKET_RULEBOOK` 9×8, 모든 값 |·| ≤ 0.30, cash_mmf = 0.025
- [ ] `generate_bl_views`가 8-bucket 후보 전부에 view 생성 (silent skip 0)
- [ ] `_nco_per_bucket` TIPS split이 `global_duration` 기준 (HRP 경로와 일치)
- [ ] attribution 스냅샷이 8키 동적

### 7.3. 테스트
- [ ] `_allocator_state_helpers` 8-bucket, 10개 phase 테스트 green
- [ ] `test_rulebook_has_all_8_buckets` 신규
- [ ] cash_spillover 테스트가 RISK_BUCKETS-only 동작 검증
- [ ] 전체 portfolio/allocator 테스트 suite green

---

## 8. Out of Scope

- **Stage 4 overlay_apply.py** (Tier 1 §8.5 cluster cap 8-bucket 호환) — 별도 작업.
- **bucket_returns.py 5-bucket → 8-bucket** — allocator는 실제 ticker returns(returns DataFrame) 사용, bucket_returns는 backtest/calibration 전용. `bucket_returns_8b.py`는 이미 존재. backtest 전환은 별도.
- **SCENARIO_BUCKET_RULEBOOK 값 backtest 튜닝** — 본 spec은 economic-intuition prior. 실측 calibration은 후속.
- **cash_spillover에 credit 포함 여부** — 현재 RISK_BUCKETS 4개. credit(risk-on 성격) 확장은 backtest 후 재검토.
- **Tier 3 LLM overlay** — 이미 구현됨 (feature-flag OFF).

---

## 9. 영향받는 파일

| File | 변경 |
|---|---|
| `tradingagents/skills/portfolio/candidate_selector.py` | syntax error 제거, `bucket_for_etf()` eligibility, `BUCKET_TO_CATEGORIES` 제거, TIPS quota 경로 `bond`→`global_duration`(L245) |
| `tradingagents/skills/portfolio/cash_spillover.py` | 8-bucket 동적, RISK_BUCKETS spill, `BucketTarget(weights=)` 생성, threshold 키 이관, docstring 갱신 |
| `tradingagents/skills/portfolio/bl_views.py` | `SCENARIO_BUCKET_RULEBOOK` 9×8 |
| `tradingagents/agents/allocator/portfolio_allocator.py` | attribution 스냅샷 동적, `_nco_per_bucket` 동적 + TIPS `global_duration`, `BUCKET_TO_CATEGORIES` import 제거 |
| `tradingagents/observability/stage3_ablation.py` | `BUCKET_TO_CATEGORIES.keys()` 순회 → 동적 8-bucket |
| `scripts/stage3_ablation.py` | `BUCKET_TO_CATEGORIES` import 제거/갱신 |
| `tests/integration/_allocator_state_helpers.py` | `BUCKET_CATEGORIES`·`make_bucket_target` 8-bucket |
| `tests/integration/test_allocator_phase1.py` | 8-bucket 키 |
| `tests/integration/test_allocator_phase3a.py` | 8-bucket 순회 |
| `tests/unit/skills/test_portfolio_bl_views.py` | `test_rulebook_has_all_8_buckets` |
| `tests/unit/skills/test_portfolio_cash_spillover.py` | RISK_BUCKETS-only 검증 |

**참고:** `tradingagents/skills/portfolio/sub_category.py`는 변경 없음 (`inflation_linked` 이중 등록은 `_SPLIT_TARGETS` category 구분으로 정상 동작).

---

**Next:** writing-plans skill로 구현 plan 작성.
