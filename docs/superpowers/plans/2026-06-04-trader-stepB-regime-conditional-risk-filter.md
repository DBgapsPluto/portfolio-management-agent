# Step B 레짐 조건부 risk-filter 선정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Step B 종목 선정이 레짐(인플레/USD강세)에 따라 듀레이션·환헤지를 조건부로 선호하도록, 정렬 키에 페널티를 추가한다 (`30년국채(H)` → `미국채10년(UH)` 자동 전환).

**Architecture:** `candidate_selector.py`에 순수 함수 3개(`duration_tier`, `is_hedged`, `regime_selection_prefs`)를 추가하고, `select_representative_candidates`의 core 정렬 키를 `(-AUM, ticker)` → `(dur_pen, hedge_pen, -AUM, ticker)`로 교체(소프트 재정렬, infeasible 없음). `trader_allocator` 노드가 ETF명·quadrant·scenario를 전달한다. 신규 인자는 전부 기본값이라 기존 호출·테스트는 무수정 통과.

**Tech Stack:** Python 3.13, pytest. 신규 의존성·데이터 fetch 없음 (전부 `universe.json`의 `name` 파싱).

**Spec:** `docs/superpowers/specs/2026-06-04-trader-stepB-regime-conditional-risk-filter-design.md`

---

## File Structure

- **Modify** `tradingagents/skills/portfolio/candidate_selector.py` — 순수 함수 3개 추가 + 모듈 상수 4개 + `select_representative_candidates` 시그니처/정렬 키.
- **Modify** `tradingagents/agents/trader/trader_allocator.py` — `name_of` 맵 생성 + 호출에 `name`/`quadrant`/`dominant_scenario` 전달.
- **Test** `tests/unit/skills/portfolio/test_candidate_selector.py` — 순수 함수 단위 + selector 통합 테스트 추가 (기존 테스트 무수정 유지).
- **Test** `tests/unit/agents/trader/test_trader_allocator.py` — 노드가 레짐을 selector로 전달하는지 검증.

---

## Task 1: 순수 함수 3개 (`duration_tier`, `is_hedged`, `regime_selection_prefs`)

**Files:**
- Modify: `tradingagents/skills/portfolio/candidate_selector.py` (상수 + 함수 추가; `import re`는 이미 존재)
- Test: `tests/unit/skills/portfolio/test_candidate_selector.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/skills/portfolio/test_candidate_selector.py` 상단 import에 신규 함수를 추가하고(기존 import 블록 교체):

```python
from tradingagents.skills.portfolio.candidate_selector import (
    _normalize_index, CORE_SUBCATEGORIES, KNOWN_THEMATIC,
    select_representative_candidates,
    duration_tier, is_hedged, regime_selection_prefs,
)
```

파일 끝에 추가:

```python
# === Task 1: 레짐 조건부 risk-filter 순수 함수 ===

def test_duration_tier_from_year():
    assert duration_tier("ACE 미국30년국채액티브(H)") == 3
    assert duration_tier("TIGER 미국채10년선물") == 2
    assert duration_tier("KODEX 국고채3년") == 1


def test_duration_tier_from_tokens():
    assert duration_tier("KODEX CD금리액티브(합성)") == 0
    assert duration_tier("KODEX 머니마켓액티브") == 0
    assert duration_tier("KODEX 종합채권(AA-이상)액티브") == 2
    assert duration_tier("PLUS 미국장기우량회사채") == 3
    assert duration_tier("PLUS 미국단기회사채(AAA~A)") == 1
    assert duration_tier("TIGER 중장기국채") == 2
    assert duration_tier("KODEX 200") == 2   # 마커 없음 → 기본 중기


def test_is_hedged_kr_convention():
    assert is_hedged("ACE 미국30년국채액티브(H)") is True
    assert is_hedged("TIGER 미국30년국채스트립액티브(합성 H)") is True
    assert is_hedged("ACE 미국30년국채엔화노출액티브(H)") is True
    assert is_hedged("ACE 미국30년국채액티브") is False
    assert is_hedged("KODEX 미국S&P500산업재(합성)") is False
    assert is_hedged("ACE KRX금현물") is False


def test_is_hedged_uh_guard():
    # (UH) 환노출 명시 표기는 (H)로 끝나는 글자에 오탐되지 않아야 함
    assert is_hedged("ACE 미국30년국채(UH)") is False


def test_regime_selection_prefs():
    assert regime_selection_prefs("growth_inflation", "neutral") == (True, True)
    assert regime_selection_prefs("recession_inflation", "neutral") == (True, True)
    assert regime_selection_prefs("growth_disinflation", "neutral") == (False, False)
    assert regime_selection_prefs("recession_disinflation", "neutral") == (False, False)
    # 비인플레라도 stress/credit 시나리오면 UH 선호만 켜짐
    assert regime_selection_prefs("growth_disinflation", "kr_stress") == (False, True)
    assert regime_selection_prefs("growth_disinflation", "global_credit") == (False, True)
    assert regime_selection_prefs(None, None) == (False, False)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/skills/portfolio/test_candidate_selector.py -k "duration_tier or is_hedged or regime_selection_prefs" -v`
Expected: FAIL — `ImportError: cannot import name 'duration_tier'`

- [ ] **Step 3: Implement the functions**

`tradingagents/skills/portfolio/candidate_selector.py`에서 `from tradingagents.skills.portfolio.within_bucket import SINGLE_CAP` 아래(`CORE_SUBCATEGORIES` 정의 위)에 추가:

```python
# === 레짐 조건부 risk-filter (Step B, spec 2026-06-04) ===
# 듀레이션 필터 적용 버킷(채권), 헤지 필터 적용 버킷(안전 외화자산).
_DURATION_BUCKETS: set[str] = {"a2_kr_rates", "a3_us_rates"}
_HEDGE_BUCKETS: set[str] = {"a3_us_rates", "a5_gold_infl"}
_INFLATION_QUADRANTS: set[str] = {"growth_inflation", "recession_inflation"}
_UNHEDGED_SCENARIOS: set[str] = {"kr_stress", "global_credit"}


def duration_tier(name: str) -> int:
    """ETF명에서 듀레이션 tier. 0=초단기 … 3=장기 (클수록 인플레 레짐 페널티 큼)."""
    m = re.search(r"(\d+)\s*년", name)
    if m:
        y = int(m.group(1))
        return 3 if y >= 20 else 2 if y >= 7 else 1   # ≥20y 장기 / 7~19y 중기 / 1~6y 단기
    if any(k in name for k in ("CD", "KOFR", "머니마켓", "MMF", "SOFR", "초단기", "통안")):
        return 0
    if "중장기" in name or "중기" in name or "종합" in name:   # 장기 토큰보다 먼저
        return 2
    if any(k in name for k in ("장기", "스트립", "초장기")):
        return 3
    if "단기" in name:
        return 1
    return 2   # 기본 중기


def is_hedged(name: str) -> bool:
    """환헤지 여부. KR 관례: (H)/(합성 H) → 헤지, 무표기·(합성)·(UH) → UH."""
    n = name.strip()
    if n.endswith("(UH)"):       # 환노출 명시 — "H)"로 끝나 오탐되지 않게 먼저 배제
        return False
    return n.endswith("H)")      # (H) / (합성 H) / 엔화노출(H) → 헤지


def regime_selection_prefs(
    quadrant: str | None, scenario: str | None,
) -> tuple[bool, bool]:
    """(prefer_short_duration, prefer_unhedged). 인플레/USD강세 신호 → 단기·UH 선호."""
    prefer_short = quadrant in _INFLATION_QUADRANTS
    prefer_unhedged = prefer_short or scenario in _UNHEDGED_SCENARIOS
    return prefer_short, prefer_unhedged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/skills/portfolio/test_candidate_selector.py -k "duration_tier or is_hedged or regime_selection_prefs" -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/portfolio/candidate_selector.py tests/unit/skills/portfolio/test_candidate_selector.py
git commit -m "feat(stepB): 레짐 risk-filter 순수 함수 (duration_tier/is_hedged/regime_prefs)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `select_representative_candidates` 정렬 키를 레짐-인지로 교체

**Files:**
- Modify: `tradingagents/skills/portfolio/candidate_selector.py` (`select_representative_candidates` 함수 전체)
- Test: `tests/unit/skills/portfolio/test_candidate_selector.py`

- [ ] **Step 1: Write the failing tests**

`tests/unit/skills/portfolio/test_candidate_selector.py` 끝에 추가:

```python
# === Task 2: selector 레짐 조건부 정렬 ===

def _call_regime(rows, bucket_key, *, quadrant, scenario="neutral", w=0.10):
    """rows: (ticker, aum, sub, idx, name). 레짐 인자 포함 호출."""
    eligible = [t for t, *_ in rows]
    aum = {t: a for t, a, _, _, _ in rows}
    sub = {t: s for t, _, s, _, _ in rows}
    idx = {t: i for t, _, _, i, _ in rows}
    name = {t: nm for t, _, _, _, nm in rows}
    return select_representative_candidates(
        bucket_key=bucket_key, eligible=eligible, aum=aum,
        sub_category=sub, underlying_index=idx, name=name,
        quadrant=quadrant, dominant_scenario=scenario,
        bucket_weight=w, capital_krw=1_000_000_000,
    )


# 실 universe 축약: a3_us_rates 30년(H, 최대 AUM) / 30년(UH) / 10년(UH)
_A3_ROWS = [
    ("A453850", 1.82e12, "us_treasury", "미국30년국채", "ACE 미국30년국채액티브(H)"),
    ("A476760", 3.171e11, "us_treasury", "미국30년국채", "ACE 미국30년국채액티브"),
    ("A305080", 2.446e11, "us_treasury", "미국채10년", "TIGER 미국채10년선물"),
]


def test_a3_inflation_picks_short_unhedged():
    # growth_inflation → 단기·UH 선호 → AUM 1등 30년(H) 대신 10년(UH)
    out = _call_regime(_A3_ROWS, "a3_us_rates", quadrant="growth_inflation", w=0.08)
    assert out == ["A305080"]


def test_a3_disinflation_keeps_aum_default():
    # growth_disinflation → 페널티 0 → AUM 1등(30년 H) 유지 (회귀 보장)
    out = _call_regime(_A3_ROWS, "a3_us_rates", quadrant="growth_disinflation", w=0.08)
    assert out == ["A453850"]


def test_a2_inflation_prefers_shorter_kr_bond():
    rows = [
        ("KB30", 900.0, "kr_treasury", "국고채30년", "KODEX 국고채30년액티브"),
        ("KB3",  100.0, "kr_treasury", "국고채3년", "KODEX 국고채3년"),
    ]
    out = _call_regime(rows, "a2_kr_rates", quadrant="growth_inflation", w=0.10)
    assert out == ["KB3"]   # 단기 선호로 AUM 9배 큰 30년을 이김


def test_a5_inflation_prefers_unhedged_gold():
    rows = [
        ("GOLDH", 500.0, "gold", "골드선물", "KODEX 골드선물(H)"),
        ("GOLDP", 300.0, "gold", "금현물", "ACE KRX금현물"),
    ]
    out = _call_regime(rows, "a5_gold_infl", quadrant="growth_inflation", w=0.10)
    assert out == ["GOLDP"]   # AUM 더 작아도 UH(금현물) 우선


def test_b8_oil_only_hedged_is_noop():
    # 유가는 (H)뿐 + b8은 필터 버킷 아님 → AUM 1등 그대로
    rows = [
        ("A261220", 1428.0, "oil_energy", "WTI", "KODEX WTI원유선물(H)"),
        ("AENERGY", 410.0, "materials_energy", "에너지", "TIGER 200 에너지화학"),
    ]
    out = _call_regime(rows, "b8_cyclical_commodity", quadrant="growth_inflation", w=0.10)
    assert out == ["A261220"]


def test_credit_scenario_prefers_unhedged_in_a3():
    # 비인플레(growth_disinflation)지만 global_credit → prefer_unhedged 만 켜짐
    # 듀레이션 페널티 0 이라 30년끼리는 UH가 H를 이김
    rows = [
        ("A453850", 1.82e12, "us_treasury", "미국30년국채", "ACE 미국30년국채액티브(H)"),
        ("A476760", 3.171e11, "us_treasury", "미국30년국채A", "ACE 미국30년국채액티브"),
    ]
    out = _call_regime(rows, "a3_us_rates", quadrant="growth_disinflation",
                       scenario="global_credit", w=0.08)
    assert out == ["A476760"]   # UH 30년
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/unit/skills/portfolio/test_candidate_selector.py -k "a3_inflation or a3_disinflation or a2_inflation or a5_inflation or b8_oil or credit_scenario" -v`
Expected: FAIL — `TypeError: select_representative_candidates() got an unexpected keyword argument 'name'`

- [ ] **Step 3: Replace `select_representative_candidates`**

`tradingagents/skills/portfolio/candidate_selector.py`의 `select_representative_candidates` 함수 전체(현재 `def select_representative_candidates(` 부터 `return selected` 까지)를 아래로 교체:

```python
def select_representative_candidates(
    *,
    bucket_key: str,
    eligible: list[str],
    aum: dict[str, float],
    sub_category: dict[str, str | None],
    underlying_index: dict[str, str],
    bucket_weight: float,
    capital_krw: float,
    name: dict[str, str] | None = None,
    quadrant: str | None = None,
    dominant_scenario: str | None = None,
    trace: dict | None = None,
) -> list[str]:
    """버킷 내 대표 운반체 선정 (결정론).

    core 우선 → 레짐 조건부 정렬(듀레이션·헤지 페널티 → AUM) → index dedup →
    **N = min(n_floor, core distinct)**. 같은-버킷 broad ETF 는 상관성이 높아 adaptive
    다양화 이득이 작으므로 minimal-N 을 의도적 설계로 채택.

    레짐 인자(name/quadrant/dominant_scenario)는 전부 기본값 → 미전달 시 기존 AUM 정렬과
    동일(no-op). 듀레이션은 _DURATION_BUCKETS·인플레 quadrant 에서, 헤지는 _HEDGE_BUCKETS·
    USD강세 신호에서만 페널티가 켜진다 (spec 2026-06-04). 순수 재정렬이라 풀을 비우지 않음.

    capital_krw 는 §6(hysteresis/adaptive-N) 예약 — v1 미사용.
    """
    if not eligible:
        return []
    name = name or {}
    prefer_short, prefer_unhedged = regime_selection_prefs(quadrant, dominant_scenario)

    def _dur_pen(t: str) -> int:
        if bucket_key not in _DURATION_BUCKETS or not prefer_short:
            return 0
        return duration_tier(name.get(t, ""))

    def _hedge_pen(t: str) -> int:
        if bucket_key not in _HEDGE_BUCKETS or not prefer_unhedged:
            return 0
        return 1 if is_hedged(name.get(t, "")) else 0

    def _rank(ts: list[str]) -> list[str]:
        # 레짐 조건부: (듀레이션 페널티, 헤지 페널티, -AUM, ticker). 페널티 미적용 시 AUM 정렬과 동일.
        return sorted(ts, key=lambda t: (_dur_pen(t), _hedge_pen(t), -aum.get(t, 0.0), t))

    def _dedup(ts: list[str], seen_keys: set[str]) -> list[str]:
        out: list[str] = []
        for t in ts:
            key = _normalize_index(underlying_index.get(t)) or t
            if key in seen_keys:
                continue
            seen_keys.add(key)
            out.append(t)
        return out

    core_set = CORE_SUBCATEGORIES.get(bucket_key, set())
    core = [t for t in eligible if sub_category.get(t) in core_set]
    if not core:
        core = list(eligible)

    seen: set[str] = set()
    deduped_core = _dedup(_rank(core), seen)

    n_floor = max(1, math.ceil(bucket_weight / SINGLE_CAP - 1e-9))
    n = min(n_floor, len(deduped_core))
    selected = deduped_core[:n]

    # forced fill — feasibility 한정. thematic 을 sub_category 별 round-robin(AUM 순, 레짐 무관).
    if len(selected) < n_floor:
        core_members = set(core)
        thematic = sorted(
            [t for t in eligible if t not in core_members],
            key=lambda t: (-aum.get(t, 0.0), t),
        )
        groups: dict[str | None, list[str]] = {}
        for t in thematic:
            groups.setdefault(sub_category.get(t), []).append(t)
        order = list(groups)
        while len(selected) < n_floor:
            advanced = False
            for sc in order:
                if len(selected) >= n_floor:
                    break
                q = groups[sc]
                while q:
                    t = q.pop(0)
                    key = _normalize_index(underlying_index.get(t)) or t
                    if key not in seen:
                        seen.add(key)
                        selected.append(t)
                        advanced = True
                        break  # sub_category 당 한 번만 — pass 마다 round-robin(다양성)
            if not advanced:
                break

    if trace is not None:
        trace.update({"bucket": bucket_key, "core_n": len(deduped_core),
                      "n_floor": n_floor, "selected": list(selected)})
    return selected
```

> 변경 핵심: ① 시그니처에 `name`/`quadrant`/`dominant_scenario` 기본값 추가, ② `_rank`가 레짐 페널티 key 사용, ③ forced-fill `thematic`만 AUM-순 명시 정렬(레짐 무관, spec §4). docstring 갱신. 그 외 로직 동일.

- [ ] **Step 4: Run the new tests + the full file (회귀 확인)**

Run: `.venv/bin/python -m pytest tests/unit/skills/portfolio/test_candidate_selector.py -v`
Expected: PASS — 신규 6 + 기존 전부 (기존은 레짐 인자 기본값으로 무변경)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/portfolio/candidate_selector.py tests/unit/skills/portfolio/test_candidate_selector.py
git commit -m "feat(stepB): selector 정렬 키에 듀레이션·헤지 페널티 (소프트 재정렬)

a2/a3 채권 인플레→단기 선호, a3/a5 안전자산 USD강세→UH 선호.
기존 호출은 기본값으로 no-op (회귀 무손실).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `trader_allocator` 노드가 레짐을 selector로 전달

**Files:**
- Modify: `tradingagents/agents/trader/trader_allocator.py:147-185`
- Test: `tests/unit/agents/trader/test_trader_allocator.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/agents/trader/test_trader_allocator.py` 끝에 추가:

```python
def test_node_a3_inflation_selects_short_unhedged(tmp_path):
    """노드가 quadrant·ETF명을 selector로 전달 → a3에서 10년(UH) 선택."""
    etfs = []
    for k in GAPS_BUCKET_KEYS:
        if k == "a3_us_rates":
            continue
        risk = "안전" if k[0] == "a" else "위험"
        for i in (1, 2):
            etfs.append({
                "ticker": f"T_{k}_{i}", "name": f"{k}{i}", "aum_krw": 100.0 * i,
                "underlying_index": f"idx_{k}_{i}", "bucket": risk,
                "category": "c", "gaps_bucket": k,
            })
    etfs += [
        {"ticker": "A453850", "name": "ACE 미국30년국채액티브(H)", "aum_krw": 1.82e12,
         "underlying_index": "미국30년국채", "bucket": "안전", "category": "c",
         "gaps_bucket": "a3_us_rates", "sub_category": "us_treasury"},
        {"ticker": "A305080", "name": "TIGER 미국채10년선물", "aum_krw": 2.446e11,
         "underlying_index": "미국채10년", "bucket": "안전", "category": "c",
         "gaps_bucket": "a3_us_rates", "sub_category": "us_treasury"},
    ]
    p = tmp_path / "u.json"
    p.write_text(json.dumps({"version": "t", "etfs": etfs}, ensure_ascii=False))
    macro = _FakeMacro(_FakeRegime("growth_inflation", 0.7))
    node = create_trader_allocator(_FakeStep(BucketTilt()))
    out = node(_state_14(str(p), macro))
    assert out["candidate_set"].bucket_to_tickers.get("a3_us_rates") == ["A305080"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/agents/trader/test_trader_allocator.py::test_node_a3_inflation_selects_short_unhedged -v`
Expected: FAIL — `assert ['A453850'] == ['A305080']` (노드가 아직 레짐을 전달하지 않아 AUM 1등 30년(H) 선택)

- [ ] **Step 3: Wire the node**

`tradingagents/agents/trader/trader_allocator.py`에서 `idx_of` 맵 정의 줄(현재 `idx_of = {e.ticker: e.underlying_index for e in uni.etfs}`) 바로 아래에 추가:

```python
        name_of = {e.ticker: e.name for e in uni.etfs}
```

그리고 `select_representative_candidates(...)` 호출(현재 `bucket_key=bkey, ... bucket_weight=w, capital_krw=capital,`)을 아래로 교체:

```python
            selections[bkey] = select_representative_candidates(
                bucket_key=bkey, eligible=eligible, aum=aum,
                sub_category=sub_cat, underlying_index=idx_of,
                name=name_of, quadrant=quadrant, dominant_scenario=scenario,
                bucket_weight=w, capital_krw=capital,
            )
```

> `quadrant`·`scenario`는 노드에서 이미 계산됨(Step A 블록). `name_of`만 신규.

- [ ] **Step 4: Run test + 기존 노드 테스트 전체 (회귀)**

Run: `.venv/bin/python -m pytest tests/unit/agents/trader/test_trader_allocator.py -v`
Expected: PASS — 신규 1 + 기존 전부 (기존은 growth_disinflation/macro=None → 레짐 페널티 off → 무변경)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/trader/trader_allocator.py tests/unit/agents/trader/test_trader_allocator.py
git commit -m "feat(stepB): trader 노드가 ETF명·quadrant·scenario를 selector로 전달

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: E2E 검증 (2026-05-29 실데이터)

**Files:** 코드 변경 없음 — 실행 검증만.

- [ ] **Step 1: 통합 테스트 + 전체 스위트 회귀**

Run: `.venv/bin/python -m pytest tests/integration/test_plan_pipeline_mock.py tests/unit/skills/portfolio/test_candidate_selector.py tests/unit/agents/trader/test_trader_allocator.py -v`
Expected: PASS (mock 파이프라인 + selector + 노드 전부)

- [ ] **Step 2: E2E 재실행 (실데이터)**

Run: `.venv/bin/python scripts/run_e2e_test.py --as-of 2026-05-29 --capital 1000000000`
Expected: EXIT 0, validation 통과. (실패 시 출력의 traceback/validation 사유를 그대로 보고하고 중단 — 임의 수정 금지.)

- [ ] **Step 3: 산출물에서 a3 픽 전환 확인**

Run: `grep -E "30년|10년|국채" artifacts/2026-05-29/trade_plan.csv`
Expected: 미국 국채 운반체가 `미국30년국채(H)`(A453850)가 아니라 **`미국채10년`류(UH)** 로 바뀜. (이전 산출물은 A453850 7.51%였음.)

- [ ] **Step 4: 위험자산 70% 캡 유지 확인**

Run: `.venv/bin/python -c "import json; p=json.load(open('artifacts/2026-05-29/portfolio.json')); print(p.get('allocation_attribution',{}).get('realized_risk_pct'))"`
Expected: ≤ 0.70 (risk-repair 유지). 값과 검증 결과를 사용자에게 보고.

- [ ] **Step 5: Commit (산출물은 .gitignore — 코드 변경 없으면 commit 생략, 결과만 보고)**

E2E는 코드 변경이 없으므로 별도 commit 없음. a3 픽 전환·risk≤70%·validation 통과 여부를 사용자에게 요약 보고한다.

---

## Self-Review

**1. Spec coverage:**
- §3.1 `duration_tier` → Task 1 ✅ / §3.2 `is_hedged` (+UH 가드) → Task 1 ✅ / §3.3 `regime_selection_prefs` → Task 1 ✅
- §4 정렬 키 `(dur_pen, hedge_pen, -AUM, ticker)` + 버킷 스코프 → Task 2 ✅ / §4 worked example(a3 flip) → Task 2 `test_a3_inflation_picks_short_unhedged` + Task 3 노드 테스트 ✅
- §4 lexicographic(작은 갭이 헤지 덮음) → `test_a2_inflation_prefers_shorter_kr_bond`(AUM 9배 무시)로 간접 확인 ✅
- §5 시그니처 기본값 + 노드 전달 → Task 2(시그니처)·Task 3(노드) ✅
- §6 에러 처리(name 누락→{}, unknown quadrant→no-op, 유가 no-op) → `regime_selection_prefs(None,None)`·`test_b8_oil_only_hedged_is_noop` ✅
- §7 테스트(단위·통합·E2E·회귀) → Task 1/2/3/4 전부 매핑 ✅
- §8 확장 항목 → v1 제외(계획에 미포함, 의도적) ✅

**2. Placeholder scan:** TBD/TODO 없음. 모든 step에 실제 코드·정확 명령·기대 출력 명시.

**3. Type consistency:** `select_representative_candidates`의 신규 키워드 `name`/`quadrant`/`dominant_scenario`가 Task 2 정의 ↔ Task 3 노드 호출에서 동일. `duration_tier`/`is_hedged`/`regime_selection_prefs` 시그니처가 Task 1 정의 ↔ Task 2 내부 사용에서 일치. 모듈 상수명(`_DURATION_BUCKETS`/`_HEDGE_BUCKETS`/`_INFLATION_QUADRANTS`/`_UNHEDGED_SCENARIOS`) Task 1 정의 ↔ Task 2 사용 일치.
