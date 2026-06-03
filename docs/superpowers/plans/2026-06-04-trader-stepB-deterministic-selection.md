# Trader Step B — Deterministic Representative-Carrier Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** trader Step B(버킷 내 종목 선정)를 LLM에서 **결정론적 대표 운반체 선정**(core sub_category 우선 → AUM → underlying_index dedup → adaptive N)으로 교체한다.

**Architecture:** 신규 `candidate_selector.py`가 순수 함수 `select_representative_candidates`를 제공. trader 노드는 Step A로 정한 `bucket_weights` 각 버킷에 이 함수를 호출해 ticker를 고르고, 기존 AUM water-fill로 종목내 비중을 계산. regime-alpha 팩터·LLM 미사용(적대 리뷰 결과 — alpha는 backtest 게이트/Step A로 연기).

**Tech Stack:** Python 3.12, pytest. `.venv/bin/pytest`, `.venv/bin/python` (plain `python` not on PATH).

**Spec:** [docs/superpowers/specs/2026-06-04-trader-stepB-deterministic-factor-selection-design.md](../specs/2026-06-04-trader-stepB-deterministic-factor-selection-design.md)

---

## File Structure

| 파일 | 책임 |
|---|---|
| `tradingagents/skills/portfolio/candidate_selector.py` | **신규** — `CORE_SUBCATEGORIES`, `KNOWN_THEMATIC`, `_normalize_index`, `select_representative_candidates` |
| `tests/unit/skills/portfolio/test_candidate_selector.py` | **신규** — normalize·coverage·선정 단위 테스트 |
| `tradingagents/agents/trader/trader_allocator.py` | LLM Step B 제거(structured_b/_step_b_prompt/_STEP_B_SYSTEM/StockSelection import/valid_tickers/step_b_llm 파라미터) → 결정론 선정 루프 |
| `tradingagents/graph/trading_graph.py` | `create_trader_allocator(step_a_llm=deep, step_b_llm=deep)` → `step_b_llm` 인자 제거 |
| `tests/unit/agents/trader/test_trader_allocator.py` | step_b `_FakeStep`/`StockSelection` 제거; `create_trader_allocator(...)` 1-arg 갱신; 결정론 선정 통합 테스트 |

> **불변:** `aum_weighted_allocation` + `InfeasibleBucket` fallback(2차 안전망), risk 계산, 출력 dict, Step A 전체. `StockSelection` **스키마 자체는 유지**(tests/unit/schemas/test_research_trade_schemas.py 가 사용) — trader_allocator의 import만 제거.

---

## Task 1: `candidate_selector.py` — `_normalize_index` + 분류 테이블 + coverage 불변식

**Files:**
- Create: `tradingagents/skills/portfolio/candidate_selector.py`
- Test: `tests/unit/skills/portfolio/test_candidate_selector.py`

- [ ] **Step 1: 테스트 작성 (실패 예정)**

`tests/unit/skills/portfolio/test_candidate_selector.py`:
```python
import json, pathlib, collections
import pytest
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.skills.portfolio.gaps_buckets import GAPS_BUCKET_KEYS
from tradingagents.skills.portfolio.candidate_selector import (
    _normalize_index, CORE_SUBCATEGORIES, KNOWN_THEMATIC,
)


def test_normalize_collapses_tr_variants():
    assert _normalize_index("코스피 200") == _normalize_index("코스피 200 TR지수")
    assert _normalize_index("S&P 500") == _normalize_index("S&P 500 Total Return Index")
    assert _normalize_index("NASDAQ 100") == _normalize_index("NASDAQ-100 Total Return Index")


def test_normalize_preserves_subindex():
    # sub-index 는 다른 노출 → 합치면 안 됨
    assert _normalize_index("코스피 200") != _normalize_index("코스피 200 정보기술")


def test_normalize_handles_none_empty():
    assert _normalize_index(None) == ""
    assert _normalize_index("") == ""


def test_core_keys_match_buckets():
    assert set(CORE_SUBCATEGORIES) == set(GAPS_BUCKET_KEYS)
    assert set(KNOWN_THEMATIC) == set(GAPS_BUCKET_KEYS)


def test_coverage_every_universe_subcategory_classified():
    """적대 리뷰 #2: universe 의 모든 (bucket, sub_category) 가 CORE∪KNOWN 에 분류돼야 함.
    미분류 신규 sub_category 가 나타나면 실패 → 사람이 분류 갱신하도록 강제."""
    u = json.loads(pathlib.Path(DEFAULT_CONFIG["universe_path"]).read_text())
    observed = collections.defaultdict(set)
    for e in u["etfs"]:
        observed[e["gaps_bucket"]].add(e.get("sub_category"))
    unmapped = {}
    for bkey, subs in observed.items():
        classified = CORE_SUBCATEGORIES.get(bkey, set()) | KNOWN_THEMATIC.get(bkey, set())
        missing = {s for s in subs if s is not None} - classified
        if missing:
            unmapped[bkey] = missing
    assert not unmapped, f"미분류 sub_category(분류 갱신 필요): {unmapped}"
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/unit/skills/portfolio/test_candidate_selector.py -q`
Expected: FAIL — `ModuleNotFoundError: candidate_selector`

- [ ] **Step 3: `candidate_selector.py` 작성 (데이터 + normalize)**

```python
"""Stage 3 trader Step B — 결정론적 대표 운반체(carrier) 선정.

버킷 비중(Step A)은 이미 결정됨. 여기서는 그 노출을 실현할 ETF 를 고른다:
core(broad) sub_category 우선 → AUM → underlying_index dedup → adaptive N.
regime-alpha/모멘텀/펀더멘털 미사용(적대 리뷰: 미검증 sub-theme 베팅 배제).
"""
from __future__ import annotations

import math
import re

from tradingagents.skills.portfolio.factor_scorer import compute_adaptive_n_max
from tradingagents.skills.portfolio.within_bucket import SINGLE_CAP

# 각 버킷의 '대표(broad) 노출' sub_category (v1 시드, 튜닝 대상).
CORE_SUBCATEGORIES: dict[str, set[str]] = {
    "a1_cash":               {"mmf_kr"},
    "a2_kr_rates":           {"kr_treasury", "kr_corporate"},
    "a3_us_rates":           {"us_treasury"},
    "a4_safe_fx":            {"usd_fx", "jpy_fx"},
    "a5_gold_infl":          {"gold", "inflation_linked"},
    "b1_kr_equity":          {"index_broad"},
    "b2_dm_core":            {"us_broad", "us_tech_nasdaq"},
    "b3_global_tech":        {"us_tech_nasdaq", "ai_theme_global"},
    "b4_china":              {"china"},
    "b5_other_intl":         {"japan", "india", "europe", "emerging_other"},
    "b6_defensive_equity":   {"factor_value_dividend"},
    "b7_reits":              {"thematic_other"},
    "b8_cyclical_commodity": {"oil_energy", "agricultural", "materials_energy"},
    "b9_risk_credit":        {"us_high_yield"},
}

# core 가 아닌(thematic) sub_category — coverage 불변식용 (적대 리뷰 #2).
# universe sync 로 신규 sub_category 가 생기면 coverage 테스트가 실패 → 여기/CORE 에 분류 추가.
KNOWN_THEMATIC: dict[str, set[str]] = {
    "a1_cash":               {"us_treasury", "kr_corporate", "kr_treasury"},
    "a2_kr_rates":           set(),
    "a3_us_rates":           {"us_high_yield", "kr_treasury"},
    "a4_safe_fx":            {"us_treasury"},
    "a5_gold_infl":          {"silver_precious"},
    "b1_kr_equity":          {"thematic_other", "industrial_defense", "consumer",
                              "finance", "materials_energy"},
    "b2_dm_core":            {"thematic_other", "us_sector"},
    "b3_global_tech":        {"semiconductor", "ai_robotics", "battery_ev",
                              "it_software", "thematic_other", "materials_energy"},
    "b4_china":              set(),
    "b5_other_intl":         {"thematic_other"},
    "b6_defensive_equity":   {"thematic_other", "us_sector", "biotech_pharma", "consumer"},
    "b7_reits":              set(),
    "b8_cyclical_commodity": {"thematic_other"},
    "b9_risk_credit":        set(),
}

# dedup 키 정규화: 수익률 계산 변종(TR/Total Return/NTR/ER) + 'index/지수' 제거.
# sub-index 명("정보기술" 등)은 보존 → 다른 노출 분리. (적대 리뷰 #4)
_INDEX_DROP_TOKENS: set[str] = {
    "tr", "tr지수", "total", "return", "net", "ntr",
    "excess", "er", "지수", "index",
}
_SEP = re.compile(r"[\s\-/(),.]+")


def _normalize_index(s: str | None) -> str:
    if not s:
        return ""
    tokens = [t for t in _SEP.split(s.lower()) if t]
    return "".join(t for t in tokens if t not in _INDEX_DROP_TOKENS)
```

- [ ] **Step 4: 통과 확인 (coverage 가 미분류 보고 시 KNOWN_THEMATIC 보정)**

Run: `.venv/bin/pytest tests/unit/skills/portfolio/test_candidate_selector.py -q`
Expected: PASS. (만약 `test_coverage_*` 가 미분류 sub_category 를 보고하면, 보고된 항목을 해당 버킷의 `KNOWN_THEMATIC`(thematic) 또는 `CORE_SUBCATEGORIES`(broad 라면)에 추가 후 재실행.)

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/skills/portfolio/candidate_selector.py tests/unit/skills/portfolio/test_candidate_selector.py
git commit -m "feat(stage3): candidate_selector — CORE/KNOWN_THEMATIC 분류 + _normalize_index (Step B)"
```

---

## Task 2: `select_representative_candidates` — 선정 알고리즘

**Files:**
- Modify: `tradingagents/skills/portfolio/candidate_selector.py`
- Test: `tests/unit/skills/portfolio/test_candidate_selector.py`

- [ ] **Step 1: 테스트 작성 (실패 예정)**

`test_candidate_selector.py` 에 추가:
```python
from tradingagents.skills.portfolio.candidate_selector import select_representative_candidates


def _meta(rows):
    """rows: list of (ticker, aum, sub_category, underlying_index)."""
    aum = {t: a for t, a, _, _ in rows}
    sub = {t: s for t, _, s, _ in rows}
    idx = {t: i for t, _, _, i in rows}
    return [t for t, *_ in rows], aum, sub, idx


def _call(rows, bucket_key, w=0.10, capital=1_000_000_000):
    eligible, aum, sub, idx = _meta(rows)
    return select_representative_candidates(
        bucket_key=bucket_key, eligible=eligible, aum=aum,
        sub_category=sub, underlying_index=idx,
        bucket_weight=w, capital_krw=capital,
    )


def test_deterministic_same_input_same_output():
    rows = [("AB", 100.0, "index_broad", "i1"), ("AC", 200.0, "index_broad", "i2")]
    assert _call(rows, "b1_kr_equity") == _call(rows, "b1_kr_equity")


def test_core_beats_larger_thematic_no_hijack():
    # 거대 thematic(방산, AUM 큼)이 있어도 core(index_broad)가 우선 선정 (w=0.10 → N=1)
    rows = [
        ("ABROAD", 100.0, "index_broad", "kospi200"),
        ("ATHEME", 999.0, "industrial_defense", "defense_idx"),
    ]
    assert _call(rows, "b1_kr_equity", w=0.10) == ["ABROAD"]


def test_dedup_collapses_tr_variant():
    # 같은 KOSPI200(TR/비-TR) 둘 + 정보기술 1 → N=2 면 [최대AUM KOSPI200, 정보기술]
    rows = [
        ("AKOSPI",   300.0, "index_broad", "코스피 200"),
        ("AKOSPITR", 200.0, "index_broad", "코스피 200 TR지수"),
        ("AINFO",    100.0, "index_broad", "코스피 200 정보기술"),
    ]
    out = _call(rows, "b1_kr_equity", w=0.30)  # N_floor=ceil(0.30/0.20)=2
    assert "AKOSPI" in out and "AINFO" in out and "AKOSPITR" not in out


def test_aum_tie_break_by_ticker():
    rows = [("AZ", 100.0, "index_broad", "i1"), ("AA", 100.0, "index_broad", "i2")]
    assert _call(rows, "b1_kr_equity", w=0.10) == ["AA"]   # 동률 → 사전순


def test_n_floor_satisfies_single_cap():
    # w=0.50 → N_floor=ceil(0.50/0.20)=3
    rows = [(f"A{i}", 100.0 - i, "index_broad", f"i{i}") for i in range(5)]
    out = _call(rows, "b1_kr_equity", w=0.50)
    assert len(out) >= 3


def test_optional_diversification_capped_by_core():
    # core 가 2개뿐 → 자본이 커도 thematic 으로 확장하지 않음 (w=0.10, N_floor=1)
    rows = [
        ("AB1", 200.0, "index_broad", "i1"),
        ("AB2", 150.0, "index_broad", "i2"),
        ("AT1", 999.0, "industrial_defense", "d1"),
        ("AT2", 888.0, "consumer", "d2"),
    ]
    out = _call(rows, "b1_kr_equity", w=0.10, capital=10_000_000_000)
    assert all(t in ("AB1", "AB2") for t in out)   # thematic 미진입


def test_forced_fill_uses_thematic_diversity_when_core_short():
    # core 가 1개뿐인데 N_floor=2(w=0.30) → thematic 1개 보충, sub_category 다양
    rows = [
        ("ABROAD", 500.0, "index_broad", "i1"),
        ("AT_DEF1", 400.0, "industrial_defense", "d1"),
        ("AT_DEF2", 390.0, "industrial_defense", "d2"),
        ("AT_FIN1", 300.0, "finance", "f1"),
    ]
    out = _call(rows, "b1_kr_equity", w=0.30)   # N_floor=2
    assert "ABROAD" in out and len(out) == 2
    # 보충 1개는 thematic 중 최대 AUM 테마의 top → AT_DEF1
    assert "AT_DEF1" in out


def test_empty_eligible_returns_empty():
    assert select_representative_candidates(
        bucket_key="b1_kr_equity", eligible=[], aum={}, sub_category={},
        underlying_index={}, bucket_weight=0.1, capital_krw=1e9) == []


def test_core_empty_falls_back_to_eligible():
    # 매칭 core sub_category 없음 → eligible 전체에서 AUM 선정
    rows = [("AT1", 200.0, "thematic_other", "i1"), ("AT2", 100.0, "thematic_other", "i2")]
    assert _call(rows, "b1_kr_equity", w=0.10) == ["AT1"]
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/unit/skills/portfolio/test_candidate_selector.py -q -k "select or core or dedup or tie or n_floor or optional or forced or empty or fallback"`
Expected: FAIL — `ImportError: cannot import name 'select_representative_candidates'`

- [ ] **Step 3: 함수 구현 (`candidate_selector.py` 끝에 추가)**

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
    trace: dict | None = None,
) -> list[str]:
    """버킷 내 대표 운반체 선정 (결정론). core 우선 → AUM → index dedup → adaptive N.

    선택적 다양화는 core(broad) 안에서만(thematic hijack 차단). thematic 은 단일-20%
    feasibility(N_floor)가 core distinct 인덱스로 부족할 때만 sub_category 다양성으로 보충.
    """
    if not eligible:
        return []

    def _rank(ts: list[str]) -> list[str]:
        return sorted(ts, key=lambda t: (-aum.get(t, 0.0), t))

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
    n_div = compute_adaptive_n_max(
        n_positive_alpha=len(deduped_core),
        bucket_weight=bucket_weight, capital_krw=capital_krw,
    )
    n = max(n_floor, min(n_div, len(deduped_core)))
    selected = deduped_core[:n]

    # forced fill — feasibility 한정. thematic 을 sub_category 별 round-robin(AUM 순).
    if len(selected) < n_floor:
        thematic = _rank([t for t in eligible if t not in set(core)])
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
                        break
            if not advanced:
                break

    if trace is not None:
        trace.update({"bucket": bucket_key, "core_n": len(deduped_core),
                      "n_floor": n_floor, "n_div": n_div, "selected": list(selected)})
    return selected
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/pytest tests/unit/skills/portfolio/test_candidate_selector.py -q`
Expected: PASS (전체).

- [ ] **Step 5: 커밋**

```bash
git add tradingagents/skills/portfolio/candidate_selector.py tests/unit/skills/portfolio/test_candidate_selector.py
git commit -m "feat(stage3): select_representative_candidates — core우선·AUM·dedup·adaptive N (Step B)"
```

---

## Task 3: node 배선 교체 (LLM Step B 제거) + graph + trader 테스트

**Files:**
- Modify: `tradingagents/agents/trader/trader_allocator.py`
- Modify: `tradingagents/graph/trading_graph.py:84`
- Test: `tests/unit/agents/trader/test_trader_allocator.py`

- [ ] **Step 1: 테스트 갱신 (실패 예정)**

`tests/unit/agents/trader/test_trader_allocator.py` 에서:
(a) `StockSelection` import 제거. step_b mock 제거. 모든 `create_trader_allocator(_FakeStep(BucketTilt()), _FakeStep(StockSelection(selections={})))` 호출을 **1-arg** `create_trader_allocator(_FakeStep(BucketTilt()))` 로 변경 (해당 테스트들: `test_zero_tilt_bucket_target_equals_baseline`, `test_positive_tilt_increases_bucket_weight`, `test_node_outputs_valid_weight_vector`, `test_node_smoke_thin_pool_does_not_crash`, `test_kr_stress_modifier_shifts_kr_equity_down`).
   - `test_positive_tilt_increases_bucket_weight` 의 `base_node`/`tilt_node` 도 step_b 인자 제거.

(b) 결정론 선정 통합 테스트 추가 (LLM 없이 node 가 선정 생성):
```python
def test_node_deterministic_selection_no_llm(tmp_path):
    up = _universe_14(tmp_path)
    node = create_trader_allocator(_FakeStep(BucketTilt()))
    out1 = node(_state_14(up))
    out2 = node(_state_14(up))
    assert out1["candidate_set"].bucket_to_tickers == out2["candidate_set"].bucket_to_tickers  # 결정론
    wv = out1["weight_vector"]
    assert sum(wv.weights.values()) == pytest.approx(1.0, abs=1e-3)
    assert all(w <= 0.20 + 1e-6 for w in wv.weights.values())
    assert out1["candidate_set"].selection_criteria.startswith("deterministic carrier")
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/unit/agents/trader/test_trader_allocator.py -q`
Expected: FAIL — `create_trader_allocator()` 인자 수 불일치 / `selection_criteria` 불일치.

- [ ] **Step 3: `trader_allocator.py` 수정**

(a) 상단 import에서 `StockSelection` 제거 — `from tradingagents.schemas.portfolio import (BucketTarget, CandidateSet, WeightVector, OptimizationMethod, BucketTilt,)` 로. `bind_structured` 는 유지(structured_a 사용). 그리고 candidate_selector import 추가:
```python
from tradingagents.skills.portfolio.candidate_selector import (
    select_representative_candidates,
)
```

(b) `_STEP_B_SYSTEM` 상수와 `_step_b_prompt` 함수 **제거** (Step B LLM 전용 — 이제 미사용).

(c) `create_trader_allocator` 시그니처/본문 교체:
```python
def create_trader_allocator(step_a_llm):
    structured_a = bind_structured(step_a_llm, BucketTilt, "TraderStepA")

    def node(state):
        uni = _load_universe(state["universe_path"])
        pool = _pool_by_bucket(uni)
        aum = {e.ticker: e.aum_krw for e in uni.etfs}
        risk_flag = {e.ticker: e.bucket for e in uni.etfs}
        sub_cat = {e.ticker: e.sub_category for e in uni.etfs}
        idx_of = {e.ticker: e.underlying_index for e in uni.etfs}
        capital = float(state.get("capital_krw") or 0.0)
```
(즉 `structured_b` 라인 삭제, `valid_tickers` 라인 삭제, `sub_cat`/`idx_of`/`capital` 추가.)

(d) Step A 블록(quadrant~`bucket_weights = _clamp_to_pool_capacity(...)`)은 **그대로**. 그 다음 LLM Step B 블록(`ss = invoke_structured_obj(structured_b, ...)` 부터 `selections[bkey] = picked` 루프까지)을 교체:
```python
        selections: dict[str, list[str]] = {}
        for bkey, w in bucket_weights.items():
            if w <= 0:
                continue
            eligible = [e.ticker for e in pool[bkey]]
            selections[bkey] = select_representative_candidates(
                bucket_key=bkey, eligible=eligible, aum=aum,
                sub_category=sub_cat, underlying_index=idx_of,
                bucket_weight=w, capital_krw=capital,
            )
```
(이후 `try: weights = aum_weighted_allocation(...)` InfeasibleBucket fallback 블록, risk, bucket_target, weight_vector, attribution, return: **그대로 유지**.)

(e) `candidate_set.selection_criteria` 문자열 교체:
```python
            selection_criteria="deterministic carrier: core sub_category + AUM + index-dedup",
```

- [ ] **Step 4: `trading_graph.py:84` 수정**

```python
            create_trader_allocator(step_a_llm=deep),
```
(`step_b_llm=deep` 인자 제거.)

- [ ] **Step 5: 통과 확인 + orphan 정리 확인**

Run: `.venv/bin/pytest tests/unit/agents/trader/test_trader_allocator.py -q`
Expected: PASS.
`grep -n "_step_b_prompt\|_STEP_B_SYSTEM\|structured_b\|valid_tickers" tradingagents/agents/trader/trader_allocator.py` → 결과 없음(전부 제거 확인).

- [ ] **Step 6: 전체 회귀 + 커밋**

Run: `.venv/bin/pytest tests/unit -q`
Expected: PASS (신규 실패 0; 사전존재 무관 실패 시 보고).
```bash
git add tradingagents/agents/trader/trader_allocator.py tradingagents/graph/trading_graph.py tests/unit/agents/trader/test_trader_allocator.py
git commit -m "feat(stage3): trader Step B 결정론 선정 배선 — LLM Step B 제거, select_representative_candidates 연결"
```

---

## Validation (구현 후)

- [ ] **단위/회귀:** `.venv/bin/pytest tests/unit -q` 전체 green.
- [ ] **선정 thesis-불변 (Step B 핵심 효과):** `.venv/bin/python scripts/measure_stepA_input_sensitivity.py --as-of 2026-05-15 --repeat 1` 실행 후, 추가로 thesis 변형 간 **선정 종목(candidate_set)** 이 동일한지 확인 — Step B가 결정론이므로 thesis 4변형에서 selection 100% 동일해야 함. (스크립트가 bucket_target만 보면, 별도로 archived state에 thesis 바꿔 allocator replay 2회 → `weight_vector.weights` ticker 집합 동일 확인.)
- [ ] **E2E spot-check:** `.venv/bin/python scripts/run_e2e_test.py --as-of 2026-05-29` → validation pass; 선정 종목이 각 버킷의 **대표(broad·대형)** ETF인지 육안 확인(예: b1→KOSPI200 broad, b3→broad nasdaq). LLM Step B 제거로 Stage 3 LLM 호출이 1회(Step A)로 줆.

---

## Self-Review 결과 (작성자 점검)

- **Spec 커버리지:** §2.1 normalize/CORE/coverage→Task1, select 알고리즘→Task2, §2.2 node/graph 배선→Task3, §5 검증→Validation. 갭 없음.
- **적대 리뷰 4건:** #1(N=core 상한+forced-fill 다양성)→Task2 `test_optional_diversification_capped_by_core`/`test_forced_fill_uses_thematic_diversity`; #2(coverage)→Task1 `test_coverage_*`; #4(TR normalize)→Task1 `test_normalize_*`+Task2 `test_dedup_*`. #3(hysteresis)는 spec §6 연기 — plan 범위 밖(의도적).
- **Placeholder:** 없음 — 코드/명령/기대출력 구체화. (KNOWN_THEMATIC v1 시드는 coverage 테스트가 실측 검증 — Task1 Step4에 보정 절차 명시.)
- **타입 일관성:** `select_representative_candidates` 시그니처(키워드 인자)가 Task2 정의·Task3 호출 동일; `_normalize_index`/`CORE_SUBCATEGORIES`/`KNOWN_THEMATIC` 이름 Task1·2 일치; `create_trader_allocator(step_a_llm)` 1-arg가 Task3 정의·graph 호출·테스트 동일.
