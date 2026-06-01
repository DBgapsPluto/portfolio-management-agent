# Stage 3 8-Bucket Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stage 3 portfolio allocation 코드를 Stage 2 의 8-bucket schema 에 정합시켜 현재 깨진 import + 라이브 crash 를 복구한다.

**Architecture:** `BucketTarget` 은 이미 `weights: dict[str,float]`(8키) 단일 필드. Stage 3 의 잔존 5-bucket 하드코딩(attribute 접근, kwargs 생성, `BUCKET_TO_CATEGORIES`, `SCENARIO_BUCKET_RULEBOOK` 9×5, `bucket=="bond"`)을 동적 8-bucket 으로 교체. eligibility 는 `sub_category.bucket_for_etf()` 로 일원화. cash_spillover 는 RISK_BUCKETS 4개만 spill.

**Tech Stack:** Python 3.13, pytest, pydantic, pandas, numpy. 인터프리터: `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13` (이하 `$PY`).

**작업 디렉터리:** `/Users/kimjaewon/Pluto/TradingAgents/.claude/worktrees/stage3-8bucket-reconciliation` (worktree, branch `worktree-stage3-8bucket-reconciliation`). 모든 명령은 이 디렉터리에서 실행.

**Spec:** `docs/superpowers/specs/2026-06-01-stage3-8bucket-reconciliation-design.md`

**8-bucket reference:**
```
BUCKETS = (kr_equity, global_equity, precious_metals, cyclical_commodity_fx,
           kr_bond, credit, global_duration, cash_mmf)
RISK_BUCKETS = (kr_equity, global_equity, precious_metals, cyclical_commodity_fx)
```

---

## File Structure

| File | 책임 | Task |
|---|---|---|
| `tradingagents/skills/portfolio/candidate_selector.py` | bucket→ETF eligibility (bucket_for_etf), TIPS quota | 1 |
| `tradingagents/agents/allocator/portfolio_allocator.py` | import 정리(T1), attribution/_nco 동적(T5) | 1, 5 |
| `tradingagents/observability/stage3_ablation.py` | BUCKET_TO_CATEGORIES.keys() 순회 제거 | 1 |
| `scripts/stage3_ablation.py` | BUCKET_TO_CATEGORIES import 제거 | 1 |
| `tradingagents/skills/portfolio/bl_views.py` | SCENARIO_BUCKET_RULEBOOK 9×8 | 2 |
| `tradingagents/skills/portfolio/cash_spillover.py` | 8-bucket 동적, RISK_BUCKETS spill | 3 |
| `tests/integration/_allocator_state_helpers.py` | 8-bucket 합성 universe + make_bucket_target | 4 |
| `tests/unit/skills/test_portfolio_bl_views.py` | 8-bucket rulebook 테스트 | 2 |
| `tests/unit/skills/test_portfolio_cash_spillover.py` | RISK_BUCKETS-only 테스트 | 3 |
| `tests/integration/test_allocator_phase1.py`, `test_allocator_phase3a.py` | 8-bucket 키/순회 | 4 |

**변경 없음:** `sub_category.py`(inflation_linked 이중등록은 `_SPLIT_TARGETS` category 구분으로 정상), `factor_to_bucket.py`, `schemas/portfolio.py`, `method_picker.py`, `_build_ticker_to_bucket_map`/`_hrp_per_bucket`(이미 global_duration).

---

## Task 1: candidate_selector 8-bucket eligibility + import 복구

현재 main 은 `candidate_selector.py:55` 의 고아 docstring 으로 import 자체가 불가(11 collection ERROR). 이 task 가 import 를 복구하고 eligibility 를 `bucket_for_etf()` 로 일원화한다. `BUCKET_TO_CATEGORIES` 제거에 따른 외부 importer 3곳도 동시 처리.

**Files:**
- Modify: `tradingagents/skills/portfolio/candidate_selector.py`
- Modify: `tradingagents/agents/allocator/portfolio_allocator.py:21` (import)
- Modify: `tradingagents/observability/stage3_ablation.py:28,178`
- Modify: `scripts/stage3_ablation.py:40`

- [ ] **Step 1: import 가능 여부 확인 (현재 실패 재현)**

Run:
```bash
$PY -c "import tradingagents.skills.portfolio.candidate_selector" 2>&1 | tail -3
```
Expected: `IndentationError: unexpected indent` (line 55).

- [ ] **Step 2: 고아 docstring 조각 제거 + `_eligible_for_bucket` 를 bucket_for_etf 기반으로 교체**

`candidate_selector.py` 의 현재 L55-64:
```python
    Uses bucket_for_etf() which respects sub_category for ambiguous categories
    (FX 및 원자재 → precious_metals vs cyclical_commodity_fx;
     국내채권_종합/해외채권_종합 → kr_bond / credit / global_duration).

def _eligible_for_bucket(universe: Universe, cats: list[str]):
    """Single eligibility filter (Stage 3 D2/D3 — used by both list_* and select_*)."""
    return [
        e for e in universe.etfs
        if e.category in cats
    ]
```
→ 다음으로 교체 (고아 텍스트 L55-57 제거 + 시그니처/본문 변경):
```python
def _eligible_for_bucket(universe: Universe, bucket_name: str):
    """ETFs that classify into `bucket_name` via bucket_for_etf().

    8-bucket eligibility (Stage 3 D2/D3 — used by both list_* and select_*).
    bucket_for_etf() handles sub_category disambiguation for split buckets
    (FX 및 원자재 → precious_metals vs cyclical_commodity_fx; 국내채권_종합/
    해외채권_종합 → kr_bond / credit / global_duration).
    """
    return [e for e in universe.etfs if bucket_for_etf(e) == bucket_name]
```

- [ ] **Step 3: `BUCKET_TO_CATEGORIES` dict 제거**

`candidate_selector.py` 현재 L28-41 의 주석 + dict 전체:
```python
# Map 8-bucket names to universe .category values.
# Buckets that require sub_category disambiguation (precious_metals,
# cyclical_commodity_fx, kr_bond, credit, global_duration) are filtered via
# bucket_for_etf() rather than a simple category string match.
BUCKET_TO_CATEGORIES = {
    "kr_equity": ["국내주식_지수", "국내주식_섹터"],
    "global_equity": ["해외주식_지수", "해외주식_섹터"],
    "fx_commodity": ["FX 및 원자재"],
    "bond": [
        "국내채권_종합", "국내채권_회사채",
        "해외채권_종합", "해외채권_회사채",
    ],
    "cash_mmf": ["금리연계형/초단기채권"],
}
```
→ 완전히 삭제 (eligibility 는 이제 bucket_for_etf 사용). 위 블록을 제거.

- [ ] **Step 4: 호출처 2곳 갱신 (L85, L233)**

`list_eligible_tickers` 의 L85-86:
```python
        cats = BUCKET_TO_CATEGORIES[bucket_name]
        out[bucket_name] = [e.ticker for e in _eligible_for_bucket(universe, cats)]
```
→
```python
        out[bucket_name] = [e.ticker for e in _eligible_for_bucket(universe, bucket_name)]
```

`select_etf_candidates` 의 L233-234:
```python
        cats = BUCKET_TO_CATEGORIES[bucket_name]
        eligible = _eligible_for_bucket(universe, cats)
```
→
```python
        eligible = _eligible_for_bucket(universe, bucket_name)
```

- [ ] **Step 5: TIPS quota 경로 `bond` → `global_duration` (L245)**

`select_etf_candidates` 의 L245:
```python
        if bucket_name == "bond" and bucket_target.bond_tips_share > 0.0:
```
→
```python
        if bucket_name == "global_duration" and bucket_target.bond_tips_share > 0.0:
```
(이 분기가 `_select_bond_with_tips_quota` 를 호출. 8-bucket 엔 `"bond"` 키가 없어 현재 영영 미발동. 내부 로직은 변경 불필요 — `inflation_linked` sub_category split 정상.)

- [ ] **Step 6: portfolio_allocator.py import 정리 (L21)**

현재:
```python
from tradingagents.skills.portfolio.candidate_selector import (
    BUCKET_TO_CATEGORIES, list_eligible_tickers,
```
→ `BUCKET_TO_CATEGORIES` 제거 (portfolio_allocator 에서 미사용):
```python
from tradingagents.skills.portfolio.candidate_selector import (
    list_eligible_tickers,
```
(나머지 import 항목은 그대로 — 실제 import 라인 전체를 확인해 `BUCKET_TO_CATEGORIES,` 토큰만 제거.)

- [ ] **Step 7: observability/stage3_ablation.py 갱신 (L28 import, L178 순회)**

L28 import 에서 `BUCKET_TO_CATEGORIES,` 토큰 제거. L178:
```python
        for bucket in BUCKET_TO_CATEGORIES.keys():
```
→ baseline candidate set 의 실제 bucket 키를 동적 순회:
```python
        for bucket in base_cs.bucket_to_tickers.keys():
```
(`base_cs` 는 같은 함수 내 baseline CandidateSet — L171 `base_cs` 가 정의되어 있는지 확인. 없으면 `factor_to_bucket.BUCKETS` 를 import 해 순회.)

- [ ] **Step 8: scripts/stage3_ablation.py import 정리 (L40)**

L40 import 에서 `BUCKET_TO_CATEGORIES,` 토큰 제거. 파일 내 사용처가 있으면(`grep -n BUCKET_TO_CATEGORIES scripts/stage3_ablation.py`) `factor_to_bucket.BUCKETS` 또는 동적 키로 교체.

- [ ] **Step 9: import + collection 복구 확인**

Run:
```bash
$PY -c "import tradingagents.agents.allocator.portfolio_allocator; import tradingagents.observability.stage3_ablation; print('OK')"
$PY -m pytest tests/unit/skills/test_portfolio_*.py tests/integration/test_allocator_*.py --collect-only -q 2>&1 | tail -3
```
Expected: `OK`, collection errors **0** (이전 11 → 0). 개별 테스트 실패는 이후 task 에서 해결.

- [ ] **Step 10: Commit**

```bash
git add tradingagents/skills/portfolio/candidate_selector.py tradingagents/agents/allocator/portfolio_allocator.py tradingagents/observability/stage3_ablation.py scripts/stage3_ablation.py
git commit -m "fix(stage3): candidate_selector 8-bucket eligibility + import 복구

- 고아 docstring(syntax error) 제거 → import 복구
- _eligible_for_bucket: bucket_for_etf() 기반 8-bucket
- TIPS quota 경로 bond → global_duration (L245)
- BUCKET_TO_CATEGORIES 제거 + 외부 importer 3곳 정리

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: bl_views SCENARIO_BUCKET_RULEBOOK 9×8

**Files:**
- Modify: `tradingagents/skills/portfolio/bl_views.py:15-34`
- Modify: `tests/unit/skills/test_portfolio_bl_views.py`

- [ ] **Step 1: 테스트를 8-bucket 으로 갱신 (실패 유도)**

`test_portfolio_bl_views.py` 의 다음 4개 테스트를 교체.

`test_rulebook_has_all_5_buckets` (L23-26) →
```python
def test_rulebook_has_all_8_buckets():
    expected_buckets = {
        "kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx",
        "kr_bond", "credit", "global_duration", "cash_mmf",
    }
    for scenario, bucket_returns in SCENARIO_BUCKET_RULEBOOK.items():
        assert set(bucket_returns.keys()) == expected_buckets, scenario
```

`test_generate_bl_views_known_scenario_basic` (L36-56) → `"bond"` → `"global_duration"`, 기대값 goldilocks global_duration=0.03:
```python
def test_generate_bl_views_known_scenario_basic():
    candidates = {
        "kr_equity":       ["A069500", "A102110"],
        "global_equity":   ["A360750"],
        "global_duration": ["A148070"],
        "cash_mmf":        ["A130730"],
    }
    views, confs, _ = generate_bl_views(
        scenario="goldilocks",
        regime_confidence=0.8,
        candidates=candidates,
    )
    assert views["A069500"] == 0.10
    assert views["A102110"] == 0.10
    assert views["A360750"] == 0.12
    assert views["A148070"] == 0.03
    assert views["A130730"] == 0.025
    assert len(views) == 5
    assert len(confs) == 5
    # goldilocks view_conf_multi=1.3: 0.8*1.3=1.04 → clipped to 1.0
    assert all(c == BL_VIEW_CONF_MAX_AFTER_MULTI for c in confs)
```

`test_generate_bl_views_records_breakdown` (L59-74) → `"bond"` → `"global_duration"`, late_cycle global_duration=0.07:
```python
def test_generate_bl_views_records_breakdown():
    candidates = {"kr_equity": ["A069500"], "global_duration": ["A148070", "A114260"]}
    breakdown: dict = {}
    views, confs, _ = generate_bl_views(
        scenario="late_cycle",
        regime_confidence=0.75,
        candidates=candidates,
        breakdown_out=breakdown,
    )
    assert breakdown["scenario"] == "late_cycle"
    assert breakdown["regime_confidence_raw"] == 0.75
    assert breakdown["confidence_used"] == 0.75
    assert breakdown["n_views_per_bucket"] == {"kr_equity": 1, "global_duration": 2}
    assert breakdown["rulebook_returns_used"] == {
        "kr_equity": 0.02, "global_duration": 0.07,
    }
```

`test_generate_bl_views_bucket_agnostic` (L123-139) → `"bond"` → `"global_duration"`:
```python
def test_generate_bl_views_bucket_agnostic():
    candidates = {
        "kr_equity":       ["A069500"],
        "alt_realestate":  ["AXYZ"],
        "global_duration": ["A148070"],
    }
    breakdown: dict = {}
    views, confs, _ = generate_bl_views(
        scenario="goldilocks",
        regime_confidence=0.8,
        candidates=candidates,
        breakdown_out=breakdown,
    )
    assert "A069500" in views
    assert "A148070" in views
    assert "AXYZ" not in views
    assert "alt_realestate" not in breakdown["n_views_per_bucket"]
```

- [ ] **Step 2: 테스트 실패 확인**

Run:
```bash
$PY -m pytest tests/unit/skills/test_portfolio_bl_views.py::test_rulebook_has_all_8_buckets tests/unit/skills/test_portfolio_bl_views.py::test_generate_bl_views_known_scenario_basic -v
```
Expected: FAIL (rulebook 은 아직 5-bucket, `global_duration` 키 없음).

- [ ] **Step 3: SCENARIO_BUCKET_RULEBOOK 9×8 로 교체**

`bl_views.py` 의 L12-34 (주석 + dict)를 교체:
```python
# 9 scenario × 8 bucket → annualized expected return (decimal).
# scenario keys MUST equal method_picker._SCENARIO_METHOD keys (test enforced).
# cash_mmf ≈ KOFR floor (2.5%). Returns capped at |0.30| (test enforced).
# fx_commodity → precious_metals + cyclical_commodity_fx;
# bond → kr_bond + credit + global_duration (Tier 1 INITIAL_BETA 부호 파생).
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

- [ ] **Step 4: bl_views 테스트 green 확인**

Run:
```bash
$PY -m pytest tests/unit/skills/test_portfolio_bl_views.py -v 2>&1 | tail -20
```
Expected: 모두 PASS (test_rulebook_covers_all_scenarios, test_rulebook_returns_finite_decimals, test_rulebook_has_all_8_buckets, generate_bl_views 계열 전부).

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/portfolio/bl_views.py tests/unit/skills/test_portfolio_bl_views.py
git commit -m "feat(stage3): SCENARIO_BUCKET_RULEBOOK 9x8 (INITIAL_BETA 부호 파생)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: cash_spillover 8-bucket 동적 (RISK_BUCKETS-only)

**Files:**
- Modify: `tradingagents/skills/portfolio/cash_spillover.py`
- Modify: `tests/unit/skills/test_portfolio_cash_spillover.py`

- [ ] **Step 1: 상수 교체 (L26-31)**

현재:
```python
SPILLOVER_THRESHOLD_DEFAULT: float = 0.3
SPILLOVER_THRESHOLD_BY_BUCKET: dict[str, float] = {
    "fx_commodity": 0.15,
}
CASH_CAP_FOR_SPILLOVER_TARGET: float = 0.40
SPILLOVER_NUMERICAL_TOLERANCE: float = 1e-9
```
→
```python
SPILLOVER_THRESHOLD_DEFAULT: float = 0.3
# 옛 fx_commodity:0.15 → 분할된 두 자식이 계승
SPILLOVER_THRESHOLD_BY_BUCKET: dict[str, float] = {
    "precious_metals": 0.15,
    "cyclical_commodity_fx": 0.15,
}
# conviction(alpha 기반)은 위험자산에만 유효 → 안전자산(kr_bond/credit/global_duration)은
# spill 대상 제외 (Tier 1 RISK_BUCKETS 와 일치).
SPILLOVER_RISK_BUCKETS: tuple[str, ...] = (
    "kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx",
)
CASH_CAP_FOR_SPILLOVER_TARGET: float = 0.40
SPILLOVER_NUMERICAL_TOLERANCE: float = 1e-9
```

- [ ] **Step 2: `adjust_bucket_targets` 전체 교체 (L105-207)**

현재 함수(L105-207)를 다음으로 교체:
```python
def adjust_bucket_targets(
    bucket_target: BucketTarget,
    bucket_chosen: dict[str, list[str]],
    alpha_scores_by_bucket: dict[str, dict[str, float]],
    returns: pd.DataFrame,
) -> SpilloverResult:
    """RISK_BUCKET conviction 계산 → 3-step redistribution (8-bucket).

    Step 1: RISK_BUCKET → cash_mmf 비례 spillover (현금 자체는 대상 아님)
    Step 2: effective_cap = max(0.40, macro cash) — macro 보존
    Step 3: overflow → high-conviction RISK_BUCKET conviction 가중 비례

    안전자산(kr_bond/credit/global_duration)은 alpha-conviction 평가/spill 안 함
    (Stage 2 거시 판단대로 보존). convictions/thresholds 는 weight>0 인
    RISK_BUCKET 만 포함(≤4 키, partial dict).
    """
    weights = dict(bucket_target.weights)
    total_in = sum(weights.values())
    assert abs(total_in - 1.0) < SPILLOVER_NUMERICAL_TOLERANCE, (
        f"bucket_target sum {total_in} != 1.0"
    )

    risk_buckets = [b for b in SPILLOVER_RISK_BUCKETS if weights.get(b, 0.0) > 0.0]

    # 1. RISK_BUCKET conviction
    convictions: dict[str, ConvictionResult] = {}
    for b in risk_buckets:
        convictions[b] = compute_bucket_conviction(
            bucket=b,
            chosen=bucket_chosen.get(b, []),
            alpha_scores=alpha_scores_by_bucket.get(b, {}),
            returns=returns,
        )

    adjusted = dict(weights)

    # 2. Step 1 — RISK_BUCKET → cash 비례 spillover
    spillover_amounts: dict[str, float] = {}
    for b in risk_buckets:
        amt = adjusted[b] * convictions[b].spillover_ratio
        spillover_amounts[b] = amt
        adjusted[b] -= amt
    cash_new = adjusted["cash_mmf"] + sum(spillover_amounts.values())

    # 3. Step 2 — effective_cap = max(0.40, macro cash)
    effective_cap = max(CASH_CAP_FOR_SPILLOVER_TARGET, weights["cash_mmf"])
    if cash_new <= effective_cap:
        adjusted["cash_mmf"] = cash_new
        overflow = 0.0
        cash_cap_triggered = False
    else:
        adjusted["cash_mmf"] = effective_cap
        overflow = cash_new - effective_cap
        cash_cap_triggered = True

    # 4. Step 3 — overflow → high-conviction RISK_BUCKET
    cash_overflow_to_buckets: dict[str, float] = {}
    if overflow > 0:
        high_conv = {
            b: convictions[b].conviction
            for b in risk_buckets
            if convictions[b].conviction >= convictions[b].threshold
        }
        if high_conv:
            total_weight = sum(high_conv.values())
            for b, c in high_conv.items():
                add = overflow * (c / total_weight)
                adjusted[b] += add
                cash_overflow_to_buckets[b] = add
        else:
            adjusted["cash_mmf"] += overflow
            logger.warning(
                "all risk buckets low-conviction; cash_mmf %.3f exceeds cap %.2f",
                adjusted["cash_mmf"], effective_cap,
            )

    # 5. 합 invariant
    total_out = sum(adjusted.values())
    if abs(total_out - 1.0) > SPILLOVER_NUMERICAL_TOLERANCE:
        raise RuntimeError(
            f"spillover sum invariant broken: total_out={total_out}"
        )

    # 6. 새 BucketTarget (weights dict, bond_tips_share 보존)
    adjusted_bt = BucketTarget(
        weights=adjusted,
        bond_tips_share=bucket_target.bond_tips_share,
        rationale=(
            f"{bucket_target.rationale or ''} | spillover "
            f"{sum(spillover_amounts.values()):.3f} → cash"
        )[:300],
    )

    return SpilloverResult(
        adjusted_bucket_target=adjusted_bt,
        convictions=convictions,
        cash_overflow_to_buckets=cash_overflow_to_buckets,
        total_spillover_to_cash=sum(spillover_amounts.values()),
        cash_cap_triggered=cash_cap_triggered,
        thresholds={b: _threshold_for(b) for b in risk_buckets},
    )
```

- [ ] **Step 3: 테스트 파일 8-bucket 재작성**

`test_portfolio_cash_spillover.py` 에서 5-bucket 의존을 교체. 변경 대상:
1. `test_conviction_fx_commodity_uses_specific_threshold` → `precious_metals` 사용.
2. `_make_full_universe_returns`, `_baseline_bucket_target`, `_full_universe_chosen` → 8-bucket.
3. spillover 테스트들 → RISK_BUCKETS-only 의미로 재작성 + 안전자산 불변 검증 추가.

`test_conviction_fx_commodity_uses_specific_threshold` (L66-73) →
```python
def test_conviction_precious_uses_specific_threshold():
    """precious_metals 는 threshold 0.15 사용."""
    tickers = ["A411060", "A261220"]
    returns = _make_returns(tickers, seed=4)
    alpha_scores = {t: 0.1 for t in tickers}
    result = compute_bucket_conviction("precious_metals", tickers, alpha_scores, returns)
    assert result.threshold == SPILLOVER_THRESHOLD_BY_BUCKET["precious_metals"]
    assert result.threshold == 0.15
```
`test_conviction_single_chosen` (L76-86) 의 `compute_bucket_conviction("fx_commodity", ...)` → `"precious_metals"` 로 변경 (threshold 0.15 동일).

`_make_full_universe_returns` / `_baseline_bucket_target` / `_full_universe_chosen` (L89-115) →
```python
def _make_full_universe_returns():
    tickers = (
        [f"K{i:05d}" for i in range(4)]    # kr_equity
        + [f"G{i:05d}" for i in range(4)]  # global_equity
        + [f"P{i:05d}" for i in range(2)]  # precious_metals
        + [f"Y{i:05d}" for i in range(2)]  # cyclical_commodity_fx
        + [f"B{i:05d}" for i in range(2)]  # kr_bond
        + [f"R{i:05d}" for i in range(2)]  # credit
        + [f"D{i:05d}" for i in range(2)]  # global_duration
        + [f"C{i:05d}" for i in range(2)]  # cash_mmf
    )
    return _make_returns(tickers, seed=42)


def _baseline_bucket_target() -> BucketTarget:
    return BucketTarget(
        weights={
            "kr_equity": 0.20, "global_equity": 0.20,
            "precious_metals": 0.08, "cyclical_commodity_fx": 0.07,
            "kr_bond": 0.12, "credit": 0.05, "global_duration": 0.13,
            "cash_mmf": 0.15,
        },
        bond_tips_share=0.30,
        rationale="test",
    )


def _full_universe_chosen():
    return {
        "kr_equity":             [f"K{i:05d}" for i in range(4)],
        "global_equity":         [f"G{i:05d}" for i in range(4)],
        "precious_metals":       [f"P{i:05d}" for i in range(2)],
        "cyclical_commodity_fx": [f"Y{i:05d}" for i in range(2)],
        "kr_bond":               [f"B{i:05d}" for i in range(2)],
        "credit":                [f"R{i:05d}" for i in range(2)],
        "global_duration":       [f"D{i:05d}" for i in range(2)],
        "cash_mmf":              [f"C{i:05d}" for i in range(2)],
    }
```
(weights 합 = 0.20+0.20+0.08+0.07+0.12+0.05+0.13+0.15 = 1.00.)

`test_spillover_no_spillover_when_full_conviction` (L118-140) → 8-bucket alpha + weights accessor:
```python
def test_spillover_no_spillover_when_full_conviction():
    """RISK_BUCKET conviction >= 1 → spillover 0, adjusted == original."""
    returns = _make_full_universe_returns()
    bt = _baseline_bucket_target()
    chosen = _full_universe_chosen()
    alphas = {
        "kr_equity":             {t: 0.6 for t in chosen["kr_equity"]},
        "global_equity":         {t: 0.6 for t in chosen["global_equity"]},
        "precious_metals":       {t: 0.3 for t in chosen["precious_metals"]},   # 2× 0.15
        "cyclical_commodity_fx": {t: 0.3 for t in chosen["cyclical_commodity_fx"]},
    }
    result = adjust_bucket_targets(bt, chosen, alphas, returns)
    assert result.total_spillover_to_cash == pytest.approx(0.0, abs=1e-9)
    assert result.cash_cap_triggered is False
    adj = result.adjusted_bucket_target
    assert adj["kr_equity"] == pytest.approx(bt["kr_equity"], abs=1e-9)
    assert adj["global_duration"] == pytest.approx(bt["global_duration"], abs=1e-9)
```

`test_spillover_fx_negative_only_goes_to_cash` (L143-163) → precious_metals 사용:
```python
def test_spillover_precious_zero_alpha_goes_to_cash():
    """precious_metals alpha=0 → 100% cash spillover. 나머지 RISK_BUCKET high conv."""
    returns = _make_full_universe_returns()
    bt = _baseline_bucket_target()
    chosen = _full_universe_chosen()
    alphas = {
        "kr_equity":             {t: 0.6 for t in chosen["kr_equity"]},
        "global_equity":         {t: 0.6 for t in chosen["global_equity"]},
        "precious_metals":       {t: 0.0 for t in chosen["precious_metals"]},
        "cyclical_commodity_fx": {t: 0.3 for t in chosen["cyclical_commodity_fx"]},
    }
    result = adjust_bucket_targets(bt, chosen, alphas, returns)
    adj = result.adjusted_bucket_target
    assert adj["precious_metals"] == pytest.approx(0.0, abs=1e-9)
    # precious(0.08) 전체가 cash 로. cash 0.15 + 0.08 = 0.23 (cap 0.40 이하)
    assert adj["cash_mmf"] == pytest.approx(0.23, abs=1e-9)
    assert result.total_spillover_to_cash == pytest.approx(0.08, abs=1e-9)
    assert result.cash_cap_triggered is False
```

`test_spillover_cash_cap_overflow_redistributes` (L166-184) → 8-bucket, RISK_BUCKET 만 spill:
```python
def test_spillover_cash_cap_overflow_redistributes():
    """RISK_BUCKET 다수 spill → cash > 40% → overflow → high-conv RISK_BUCKET."""
    returns = _make_full_universe_returns()
    bt = _baseline_bucket_target()
    chosen = _full_universe_chosen()
    alphas = {
        "kr_equity":             {t: 0.6 for t in chosen["kr_equity"]},       # high conv (keeps)
        "global_equity":         {t: 0.0 for t in chosen["global_equity"]},   # full spillover
        "precious_metals":       {t: 0.0 for t in chosen["precious_metals"]}, # full spillover
        "cyclical_commodity_fx": {t: 0.0 for t in chosen["cyclical_commodity_fx"]},
    }
    result = adjust_bucket_targets(bt, chosen, alphas, returns)
    adj = result.adjusted_bucket_target
    # cash_new = 0.15 + 0.20(gl_eq) + 0.08(precious) + 0.07(cyclical) = 0.50 → cap 0.40 → overflow 0.10
    # overflow 0.10 → high_conv (kr_equity only)
    assert result.cash_cap_triggered is True
    assert adj["cash_mmf"] == pytest.approx(0.40, abs=1e-9)
    assert adj["kr_equity"] == pytest.approx(0.20 + 0.10, abs=1e-9)
```

`test_spillover_all_low_conviction_warning` (L187-200) → RISK_BUCKET 만 alpha=0:
```python
def test_spillover_all_low_conviction_warning(caplog):
    """모든 RISK_BUCKET alpha=0 → cash > 40% + warning."""
    returns = _make_full_universe_returns()
    bt = _baseline_bucket_target()
    chosen = _full_universe_chosen()
    alphas = {b: {t: 0.0 for t in chosen[b]}
              for b in ("kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx")}
    with caplog.at_level(logging.WARNING):
        result = adjust_bucket_targets(bt, chosen, alphas, returns)
    assert result.adjusted_bucket_target["cash_mmf"] > 0.40
    assert any("low-conviction" in r.message.lower() for r in caplog.records)
```

`test_spillover_invariants` (L203-222) → 8-bucket weights accessor:
```python
def test_spillover_invariants():
    """합 1 보존 + bond_tips_share 보존 + 모든 weight ≥ 0."""
    returns = _make_full_universe_returns()
    bt = _baseline_bucket_target()
    chosen = _full_universe_chosen()
    alphas = {
        "kr_equity":             {t: 0.40 for t in chosen["kr_equity"]},
        "global_equity":         {t: 0.60 for t in chosen["global_equity"]},
        "precious_metals":       {t: 0.10 for t in chosen["precious_metals"]},
        "cyclical_commodity_fx": {t: 0.10 for t in chosen["cyclical_commodity_fx"]},
    }
    result = adjust_bucket_targets(bt, chosen, alphas, returns)
    adj = result.adjusted_bucket_target
    assert abs(sum(adj.weights.values()) - 1.0) < 1e-9
    assert adj.bond_tips_share == bt.bond_tips_share
    for b in adj.weights:
        assert adj.weights[b] >= 0.0
```

`test_conviction_empty_chosen` (L55-63) 의 `compute_bucket_conviction("fx_commodity", ...)` → `"cyclical_commodity_fx"` 로 변경.

- [ ] **Step 4: 안전자산 불변 신규 테스트 추가**

`test_portfolio_cash_spillover.py` 끝에 추가:
```python
def test_spillover_safe_buckets_never_spill():
    """안전자산(kr_bond/credit/global_duration)은 alpha=0 이어도 spill 안 함."""
    returns = _make_full_universe_returns()
    bt = _baseline_bucket_target()
    chosen = _full_universe_chosen()
    # RISK_BUCKET 은 high conv, 안전자산은 alpha 정보 없음(전달 안 함)
    alphas = {
        "kr_equity":             {t: 0.6 for t in chosen["kr_equity"]},
        "global_equity":         {t: 0.6 for t in chosen["global_equity"]},
        "precious_metals":       {t: 0.3 for t in chosen["precious_metals"]},
        "cyclical_commodity_fx": {t: 0.3 for t in chosen["cyclical_commodity_fx"]},
    }
    result = adjust_bucket_targets(bt, chosen, alphas, returns)
    adj = result.adjusted_bucket_target
    # 안전자산 weight 불변
    assert adj["kr_bond"] == pytest.approx(bt["kr_bond"], abs=1e-9)
    assert adj["credit"] == pytest.approx(bt["credit"], abs=1e-9)
    assert adj["global_duration"] == pytest.approx(bt["global_duration"], abs=1e-9)
    # convictions/thresholds 는 RISK_BUCKET 만 (4 키)
    assert set(result.convictions.keys()) == {
        "kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx",
    }
```

- [ ] **Step 5: cash_spillover 테스트 green 확인**

Run:
```bash
$PY -m pytest tests/unit/skills/test_portfolio_cash_spillover.py -v 2>&1 | tail -25
```
Expected: 모두 PASS.

- [ ] **Step 6: docstring 갱신 (L1-11, L105 함수 docstring)**

모듈 docstring 의 "Phase 1 도입..." 블록에서 spill 대상이 RISK_BUCKET 임을 반영. L7 "각 bucket weight" → "각 RISK_BUCKET weight". (함수 docstring 은 Step 2 에서 이미 교체됨.)

- [ ] **Step 7: Commit**

```bash
git add tradingagents/skills/portfolio/cash_spillover.py tests/unit/skills/test_portfolio_cash_spillover.py
git commit -m "feat(stage3): cash_spillover 8-bucket 동적 (RISK_BUCKETS-only spill)

- weights dict 동적 순회, BucketTarget(weights=) 생성
- spill 대상 = RISK_BUCKETS 4개 (안전자산 ballast 보존)
- threshold fx_commodity → precious_metals/cyclical_commodity_fx

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: test helper 8-bucket 합성 universe

`_allocator_state_helpers.py` 의 5-bucket `BUCKET_CATEGORIES`/`make_synthetic_universe`/`make_bucket_target` 를 8-bucket 으로 교체. 통합 phase 테스트 전체가 이를 사용하므로 allocator(Task 5) 검증의 전제.

**Files:**
- Modify: `tests/integration/_allocator_state_helpers.py`
- Modify: `tests/integration/test_allocator_phase1.py:106`
- Modify: `tests/integration/test_allocator_phase3a.py:102`

- [ ] **Step 1: BUCKET_CATEGORIES + make_synthetic_universe 8-bucket 교체**

`_allocator_state_helpers.py` L19-46 교체:
```python
# bucket → (universe category, risk_label, sub_category) for synthetic ETFs.
# category+sub_category must classify via sub_category.bucket_for_etf().
BUCKET_CATEGORIES: dict[str, tuple[str, str, str | None]] = {
    "kr_equity":             ("국내주식_지수",         "위험", "index_broad"),
    "global_equity":         ("해외주식_지수",         "위험", "us_broad"),
    "precious_metals":       ("FX 및 원자재",          "위험", "gold"),
    "cyclical_commodity_fx": ("FX 및 원자재",          "위험", "oil_energy"),
    "kr_bond":               ("국내채권_종합",         "안전", "kr_treasury"),
    "credit":                ("해외채권_회사채",       "안전", "us_high_yield"),
    "global_duration":       ("해외채권_종합",         "안전", "us_treasury"),
    "cash_mmf":              ("금리연계형/초단기채권", "안전", "mmf_kr"),
}


def make_synthetic_universe(
    n_per_bucket: int = 4,
    base_aum: float = 50_000_000_000,
) -> Universe:
    """8 bucket × n_per_bucket ETFs (bucket_for_etf 분류 가능).

    global_duration 은 짝/홀 인덱스로 us_treasury / inflation_linked 를 번갈아
    부여해 TIPS quota split(bond_tips_share>0) 경로를 테스트 가능하게 한다.
    """
    etfs: list[ETFEntry] = []
    for b_idx, (bucket_name, (category, risk, sub_cat)) in enumerate(BUCKET_CATEGORIES.items()):
        for i in range(n_per_bucket):
            sc = sub_cat
            if bucket_name == "global_duration":
                sc = "inflation_linked" if i % 2 == 1 else "us_treasury"
            etfs.append(ETFEntry(
                ticker=f"A_{b_idx}{i:02d}",
                name=f"{bucket_name}_{i}",
                aum_krw=base_aum * (i + 1),
                underlying_index=f"idx_{b_idx}_{i}",
                bucket=risk,
                category=category,
                sub_category=sc,
            ))
    return Universe(version="test", etfs=etfs)
```
(주의 1: `precious_metals`/`cyclical_commodity_fx` 는 같은 category "FX 및 원자재" 이나 sub_category(gold vs oil_energy)로 `bucket_for_etf` 가 구분. 주의 2: ticker 는 bucket 인덱스 `b_idx`(0-7)로 prefix → kr_equity/kr_bond, global_equity/global_duration 같은 동일 2글자 bucket 도 **ticker 충돌 없음**.)

- [ ] **Step 2: make_bucket_target 8-bucket weights dict 교체**

L90-107 교체:
```python
def make_bucket_target(
    *,
    kr_equity: float = 0.15,
    global_equity: float = 0.20,
    precious_metals: float = 0.08,
    cyclical_commodity_fx: float = 0.14,
    kr_bond: float = 0.15,
    credit: float = 0.05,
    global_duration: float = 0.13,
    cash_mmf: float = 0.10,
    bond_tips_share: float = 0.0,
    rationale: str = "test",
) -> BucketTarget:
    """합 검증된 8-bucket BucketTarget (default = INITIAL_BASELINE)."""
    weights = {
        "kr_equity": kr_equity, "global_equity": global_equity,
        "precious_metals": precious_metals, "cyclical_commodity_fx": cyclical_commodity_fx,
        "kr_bond": kr_bond, "credit": credit, "global_duration": global_duration,
        "cash_mmf": cash_mmf,
    }
    total = sum(weights.values())
    assert abs(total - 1.0) < 1e-9, f"bucket weights sum {total} != 1.0"
    return BucketTarget(weights=weights, bond_tips_share=bond_tips_share, rationale=rationale)
```

- [ ] **Step 3: make_bucket_target legacy 호출처 grep + 갱신**

Run:
```bash
grep -rn "make_bucket_target(" tests/ | grep -E "fx_commodity|bond=" 
```
나온 각 호출처에서 `fx_commodity=X` → `precious_metals=`/`cyclical_commodity_fx=` 분할, `bond=Y` → `kr_bond=`/`credit=`/`global_duration=` 분할로 교체 (합 1.0 유지). 인자 없이 `make_bucket_target()` 호출은 그대로 OK (default 8-bucket).

- [ ] **Step 4: test_allocator_phase1.py:106 갱신**

Run: `grep -n "fx_commodity\|BUCKET_CATEGORIES\[" tests/integration/test_allocator_phase1.py`
해당 줄(L106 `BUCKET_CATEGORIES['fx_commodity']`)을 `BUCKET_CATEGORIES['precious_metals']` 또는 테스트 의도에 맞는 8-bucket 키로 교체. 테스트가 단일 bucket 의 category 를 참조하는 것이므로 존재하는 8-bucket 키로 변경.

- [ ] **Step 5: test_allocator_phase3a.py:102 갱신**

Run: `grep -n "fx_commodity\|'bond'\|\"bond\"" tests/integration/test_allocator_phase3a.py`
5-bucket 튜플 순회를:
```python
for bucket_name in ("kr_equity", "global_equity", "precious_metals",
                    "cyclical_commodity_fx", "kr_bond", "credit",
                    "global_duration", "cash_mmf"):
```
로 교체.

- [ ] **Step 6: helper import + 합성 universe 분류 검증**

Run:
```bash
$PY -c "
from tests.integration._allocator_state_helpers import make_synthetic_universe, make_bucket_target
from tradingagents.skills.portfolio.sub_category import bucket_for_etf
u = make_synthetic_universe(n_per_bucket=4)
got = sorted({bucket_for_etf(e) for e in u.etfs})
print('buckets:', got)
bt = make_bucket_target()
print('bt weights:', sorted(bt.weights.keys()), 'sum=', round(sum(bt.weights.values()),6))
"
```
Expected: `buckets` 가 8개 전부 포함 (None 없음), `bt` sum=1.0.

- [ ] **Step 7: Commit**

```bash
git add tests/integration/_allocator_state_helpers.py tests/integration/test_allocator_phase1.py tests/integration/test_allocator_phase3a.py
git commit -m "test(stage3): _allocator_state_helpers 8-bucket 합성 universe

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: portfolio_allocator attribution + _nco 동적

**Files:**
- Modify: `tradingagents/agents/allocator/portfolio_allocator.py`

- [ ] **Step 1: attribution 스냅샷 동적화 (L234-241, L260-266)**

L234-241 의 `bucket_target_stage2`:
```python
        attribution["config"]["bucket_target_stage2"] = {
            "kr_equity":      bucket_target.kr_equity,
            "global_equity":  bucket_target.global_equity,
            "fx_commodity":   bucket_target.fx_commodity,
            "bond":           bucket_target.bond,
            "cash_mmf":       bucket_target.cash_mmf,
            "bond_tips_share": bucket_target.bond_tips_share,
        }
```
→
```python
        attribution["config"]["bucket_target_stage2"] = {
            **dict(bucket_target.weights),
            "bond_tips_share": bucket_target.bond_tips_share,
        }
```

L260-266 의 `bucket_target`:
```python
        attribution["config"]["bucket_target"] = {
            "kr_equity":     bucket_target.kr_equity,
            "global_equity": bucket_target.global_equity,
            "fx_commodity":  bucket_target.fx_commodity,
            "bond":          bucket_target.bond,
            "cash_mmf":      bucket_target.cash_mmf,
        }
```
→
```python
        attribution["config"]["bucket_target"] = dict(bucket_target.weights)
```

- [ ] **Step 2: `_nco_per_bucket` target_map + TIPS split 동적화 (L1121-1136)**

L1121-1127:
```python
    target_map = {
        "kr_equity": bucket_target.kr_equity,
        "global_equity": bucket_target.global_equity,
        "fx_commodity": bucket_target.fx_commodity,
        "bond": bucket_target.bond,
        "cash_mmf": bucket_target.cash_mmf,
    }
```
→
```python
    target_map = dict(bucket_target.weights)
```

L1136:
```python
        if bucket == "bond" and split_bond:
```
→
```python
        if bucket == "global_duration" and split_bond:
```
(이하 sub-pool split 로직 L1137-1157 은 변경 없음 — `bond_tips`/`bond_nominal` sub_label 은 HRP 경로와 동일.)

- [ ] **Step 3: import 가능 + 단위 호출 확인**

Run:
```bash
$PY -c "import tradingagents.agents.allocator.portfolio_allocator as m; print('import OK')"
```
Expected: `import OK`.

- [ ] **Step 4: allocator 통합 테스트 green 확인**

Run:
```bash
$PY -m pytest tests/integration/test_allocator_phase1.py tests/integration/test_allocator_phase3a.py -v 2>&1 | tail -20
```
Expected: 모두 PASS (helper 8-bucket + allocator 동적화 적용).

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/allocator/portfolio_allocator.py
git commit -m "fix(stage3): allocator attribution + _nco_per_bucket 8-bucket 동적

- attribution 스냅샷 dict(bucket_target.weights)
- _nco target_map 동적 + TIPS split bond → global_duration

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: 전체 suite green + E2E 검증

**Files:** (코드 변경 없음 — 잔존 실패 수정만)

- [ ] **Step 1: 전체 portfolio + allocator suite 실행**

Run:
```bash
$PY -m pytest tests/unit/skills/test_portfolio_*.py tests/integration/test_allocator_*.py -q 2>&1 | tail -30
```
Expected: 0 errors, 0 failures. 실패가 남으면 잔존 5-bucket 하드코딩이므로 해당 파일을 grep:
```bash
grep -rn "fx_commodity\|\"bond\"\|'bond'\|\.kr_equity\|\.fx_commodity\|\.bond\b" tests/integration/test_allocator_*.py tests/unit/skills/test_portfolio_*.py
```
나온 항목을 8-bucket 으로 교체 후 재실행.

- [ ] **Step 2: E2E — 8-bucket BucketTarget 로 allocator 완주 (crash 없음)**

Run:
```bash
$PY -c "
from datetime import date
from tests.integration._allocator_state_helpers import (
    make_synthetic_universe, make_synthetic_returns, make_factor_panel,
    make_bucket_target, make_research_decision, make_macro_report,
    make_risk_report, make_technical_report,
)
u = make_synthetic_universe(n_per_bucket=4)
tickers = [e.ticker for e in u.etfs]
returns = make_synthetic_returns(tickers)
fp = make_factor_panel(tickers)
bt = make_bucket_target(bond_tips_share=0.3)
print('risk_asset_weight:', round(bt.risk_asset_weight, 4))
print('weights keys:', len(bt.weights))
assert abs(sum(bt.weights.values()) - 1.0) < 1e-9
print('E2E setup OK — 8-bucket BucketTarget valid')
"
```
Expected: `risk_asset_weight` 출력, `E2E setup OK`. (full allocator node E2E 는 기존 phase 통합 테스트가 커버.)

- [ ] **Step 3: 전체 회귀 — 다른 영역 깨지지 않았는지**

Run:
```bash
$PY -m pytest tests/unit -q 2>&1 | tail -15
```
Expected: pre-existing 실패 외 신규 실패 0. (pre-existing 실패는 stage 별 audit memo 의 known fail.)

- [ ] **Step 4: spec self-review 체크리스트 대조**

`docs/superpowers/specs/2026-06-01-stage3-8bucket-reconciliation-design.md` §7 acceptance criteria 각 항목을 실제로 확인 (체크박스):
- candidate_selector bucket_for_etf, BUCKET_TO_CATEGORIES 제거, TIPS quota global_duration
- BUCKET_TO_CATEGORIES importer 3곳
- cash_spillover RISK_BUCKETS-only
- SCENARIO_BUCKET_RULEBOOK 9×8
- generate_bl_views silent skip 0
- _nco TIPS global_duration
- attribution 8키 동적

- [ ] **Step 5: Commit (잔존 수정이 있었던 경우만)**

```bash
git add -A
git commit -m "test(stage3): 8-bucket 잔존 5-bucket 참조 정리 + 전체 suite green

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review (plan 작성자 체크 완료)

**Spec coverage:** §3.1(T1), §3.2(T3), §3.3(T2), §3.4(T1 TIPS+T5 nco/attr), §3.5(T2/T3/T4 tests) 모두 task 매핑됨. §3.1 의 BUCKET_TO_CATEGORIES importer 3곳 → T1 Step 6-8. candidate_selector TIPS quota → T1 Step 5.

**Placeholder scan:** 모든 코드 step 에 실제 코드 포함. grep 기반 step(T4 Step3, T6 Step1)은 변환 규칙을 명시.

**Type consistency:** `BucketTarget(weights=dict, bond_tips_share=, rationale=)` 생성 시그니처가 cash_spillover(T3)·helper(T4) 일관. `adj["key"]`/`adj.weights[key]` accessor 일관. `SPILLOVER_RISK_BUCKETS` 4-tuple 이 cash_spillover 전반 일관. rulebook 8키가 T2 test 기대값과 일치(goldilocks global_duration=0.03, late_cycle=0.07).
