# Stage 3 Phase 2b — ENB Greedy Forward Selection + Adaptive N Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stage 3 종목 선정 알고리즘을 cluster-aware top-N 에서 ENB greedy forward selection 으로 교체. 종목 수 자동 결정 (adaptive n_max), 한계효용 stop, Phase 2a impl_score 가 처음 실질 영향. Phase 1 followup state mocking helpers 로 4 skip tests enable.

**Architecture:** `select_cluster_aware` 를 `select_by_enb_greedy` 로 replace, `compute_adaptive_n_max` 신규. candidate_selector 가 sigma + capital_krw 인자 받음. allocator 가 sigma 한 번 계산해서 candidate + optimize 양쪽 전달. State mocking helpers 가 외부 의존 없이 풀 파이프라인 통합 테스트 가능하게 함.

**Tech Stack:** Python 3.13, numpy, pandas, pypfopt (risk_models.sample_cov), pydantic, pytest.

**Spec:** [docs/superpowers/specs/2026-05-30-stage3-phase2b-enb-greedy-design.md](../specs/2026-05-30-stage3-phase2b-enb-greedy-design.md)

---

## File Structure

| 파일 | 변경 | 책임 |
|---|---|---|
| `tradingagents/skills/portfolio/factor_scorer.py` | Modify | `select_cluster_aware`/`_corr_groups` 삭제, `compute_adaptive_n_max`/`_enb_equal_weight`/`select_by_enb_greedy` 신규 + constants |
| `tradingagents/skills/portfolio/candidate_selector.py` | Modify | `select_etf_candidates` 시그니처 확장 (sigma + capital_krw 추가, per_bucket_n 제거) |
| `tradingagents/agents/allocator/portfolio_allocator.py` | Modify | sigma 사전 계산 + capital_krw 추출, per_bucket_n 로직 폐기, select_etf_candidates 호출 update, attribution config 업데이트 |
| `tests/integration/_allocator_state_helpers.py` | Create | State mock builder (universe, returns, factor_panel, regime, etc.) |
| `tests/unit/skills/test_portfolio_factor_scorer.py` | Modify | ENB greedy 단위 테스트 다수, 기존 cluster-aware 테스트 제거 |
| `tests/unit/skills/test_portfolio_candidate.py` | Modify | 시그니처 변경 반영 + adaptive N 회귀 |
| `tests/integration/test_allocator_phase1.py` | Modify | 4 skip tests enable |
| `tests/integration/test_allocator_phase2b.py` | Create | adaptive N + ENB greedy 통합 검증 |

---

### Task 1: Constants + `compute_adaptive_n_max`

**Files:**
- Modify: `tradingagents/skills/portfolio/factor_scorer.py`
- Modify: `tests/unit/skills/test_portfolio_factor_scorer.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/skills/test_portfolio_factor_scorer.py` 끝에 append:
```python
def test_compute_adaptive_n_max_alpha_cap():
    """양수 alpha 후보 수가 가장 작으면 그 값이 n_max."""
    from tradingagents.skills.portfolio.factor_scorer import compute_adaptive_n_max
    n = compute_adaptive_n_max(
        n_positive_alpha=3,
        bucket_weight=0.30,
        capital_krw=1_000_000_000_000,  # 1T (충분히 큰)
    )
    assert n == 3


def test_compute_adaptive_n_max_weight_cap():
    """작은 bucket weight → weight cap (weight/0.025)."""
    from tradingagents.skills.portfolio.factor_scorer import compute_adaptive_n_max
    n = compute_adaptive_n_max(
        n_positive_alpha=100,  # 충분히 많은 양수
        bucket_weight=0.05,    # 5% bucket → cap = 5%/2.5% = 2
        capital_krw=1_000_000_000_000,
    )
    assert n == 2


def test_compute_adaptive_n_max_capital_cap():
    """1B 자본 + 10% bucket → 100M / 50M = 2."""
    from tradingagents.skills.portfolio.factor_scorer import compute_adaptive_n_max
    n = compute_adaptive_n_max(
        n_positive_alpha=10,
        bucket_weight=0.10,
        capital_krw=1_000_000_000,
    )
    # weight_cap = 0.10/0.025 = 4
    # capital_cap = 0.10 × 1B / 50M = 2
    # min(10, 4, 2, 8) = 2
    assert n == 2


def test_compute_adaptive_n_max_abs_max():
    """모든 cap 큼 → ABS_MAX_PER_BUCKET 8."""
    from tradingagents.skills.portfolio.factor_scorer import compute_adaptive_n_max
    n = compute_adaptive_n_max(
        n_positive_alpha=20,
        bucket_weight=0.50,        # weight_cap = 20
        capital_krw=100_000_000_000,  # 100B → capital_cap = 1000
    )
    assert n == 8


def test_compute_adaptive_n_max_zero_bucket_weight():
    """bucket_weight = 0 → n_max = 0."""
    from tradingagents.skills.portfolio.factor_scorer import compute_adaptive_n_max
    n = compute_adaptive_n_max(
        n_positive_alpha=10,
        bucket_weight=0.0,
        capital_krw=1_000_000_000,
    )
    assert n == 0


def test_compute_adaptive_n_max_zero_positive_alpha():
    """positive_alpha = 0 → n_max = 0 (음수만)."""
    from tradingagents.skills.portfolio.factor_scorer import compute_adaptive_n_max
    n = compute_adaptive_n_max(
        n_positive_alpha=0,
        bucket_weight=0.30,
        capital_krw=1_000_000_000,
    )
    assert n == 0
```

- [ ] **Step 2: Run failing**

```bash
cd /Users/kimjaewon/Pluto/TradingAgents/.claude/worktrees/<worktree>
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_factor_scorer.py -v -k adaptive_n_max 2>&1 | tail -10
```
Expected: 6 FAIL (ImportError or NameError)

- [ ] **Step 3: Add constants + implementation**

`tradingagents/skills/portfolio/factor_scorer.py` 의 module-level constants 섹션 (대략 line 30 근처, `TIMING_DELTA` 같은 기존 constants 옆) 에 추가:

```python
# Phase 2b (2026-05-30). ENB greedy + adaptive n_max constants.
ENB_DELTA_THRESHOLD: float = 0.15
ABS_MAX_PER_BUCKET: int = 8
MIN_POSITION_KRW: float = 50_000_000
MIN_BUCKET_POSITION_RATIO: float = 0.025
N_MIN_HARD_FLOOR: int = 1
ALPHA_IMPL_BLEND_DEFAULT: float = 0.85
```

함수 추가 (파일 끝 또는 `select_cluster_aware` 위에):
```python
def compute_adaptive_n_max(
    *,
    n_positive_alpha: int,
    bucket_weight: float,
    capital_krw: float,
) -> int:
    """Adaptive n_max — 4 cap 의 min.

    n_max = min(
        n_positive_alpha,
        max(1, int(bucket_weight / MIN_BUCKET_POSITION_RATIO)),
        max(1, int(bucket_weight * capital_krw / MIN_POSITION_KRW)),
        ABS_MAX_PER_BUCKET,
    )
    bucket_weight = 0 시 즉시 0.
    """
    if bucket_weight <= 0:
        return 0
    if n_positive_alpha <= 0:
        return 0
    weight_cap = max(1, int(bucket_weight / MIN_BUCKET_POSITION_RATIO))
    capital_cap = max(1, int(bucket_weight * capital_krw / MIN_POSITION_KRW))
    return min(n_positive_alpha, weight_cap, capital_cap, ABS_MAX_PER_BUCKET)
```

- [ ] **Step 4: Run tests pass**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_factor_scorer.py -v -k adaptive_n_max 2>&1 | tail -10
```
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/portfolio/factor_scorer.py tests/unit/skills/test_portfolio_factor_scorer.py
git commit -m "feat(stage3): compute_adaptive_n_max + ENB greedy constants

Phase 2b Task 1. min(positive_alpha, weight/0.025, capital×weight/50M, 8) cap.
ENB_DELTA_THRESHOLD=0.15, ABS_MAX_PER_BUCKET=8, MIN_POSITION_KRW=50M,
MIN_BUCKET_POSITION_RATIO=0.025, ALPHA_IMPL_BLEND_DEFAULT=0.85. 6 tests."
```

---

### Task 2: `_enb_equal_weight` helper

**Files:**
- Modify: `tradingagents/skills/portfolio/factor_scorer.py`
- Modify: `tests/unit/skills/test_portfolio_factor_scorer.py`

- [ ] **Step 1: Write failing test**

`tests/unit/skills/test_portfolio_factor_scorer.py` 끝에 append:
```python
def test_enb_equal_weight_single_ticker():
    """1 종목 → ENB = 1.0."""
    import pandas as pd
    import numpy as np
    from tradingagents.skills.portfolio.factor_scorer import _enb_equal_weight

    sigma = pd.DataFrame(
        np.eye(3) * 0.04,
        index=["A", "B", "C"], columns=["A", "B", "C"],
    )
    assert _enb_equal_weight(["A"], sigma) == 1.0


def test_enb_equal_weight_empty():
    """0 종목 → 0.0."""
    import pandas as pd
    import numpy as np
    from tradingagents.skills.portfolio.factor_scorer import _enb_equal_weight

    sigma = pd.DataFrame(np.eye(2) * 0.04, index=["A", "B"], columns=["A", "B"])
    assert _enb_equal_weight([], sigma) == 0.0


def test_enb_equal_weight_uncorrelated_pair_close_to_two():
    """2 종목 uncorrelated → ENB ≈ 2."""
    import pandas as pd
    import numpy as np
    from tradingagents.skills.portfolio.factor_scorer import _enb_equal_weight

    sigma = pd.DataFrame(
        np.eye(2) * 0.04,
        index=["A", "B"], columns=["A", "B"],
    )
    enb = _enb_equal_weight(["A", "B"], sigma)
    assert 1.95 < enb < 2.05
```

- [ ] **Step 2: Run failing**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_factor_scorer.py -v -k enb_equal_weight 2>&1 | tail -10
```
Expected: 3 FAIL (NameError)

- [ ] **Step 3: Implement helper**

`tradingagents/skills/portfolio/factor_scorer.py` 의 import 블록 상단에 추가:
```python
from tradingagents.skills.portfolio.diversification import compute_enb
```

함수 (`compute_adaptive_n_max` 직후):
```python
def _enb_equal_weight(selected: list[str], sigma: pd.DataFrame) -> float:
    """Equal-weight ENB for selected tickers."""
    n = len(selected)
    if n == 0:
        return 0.0
    if n == 1:
        return 1.0
    sub_sigma = sigma.loc[selected, selected]
    equal_w = {t: 1.0 / n for t in selected}
    return compute_enb(equal_w, sub_sigma, method="minimum_torsion")
```

- [ ] **Step 4: Run tests pass**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_factor_scorer.py -v -k enb_equal_weight 2>&1 | tail -10
```
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/portfolio/factor_scorer.py tests/unit/skills/test_portfolio_factor_scorer.py
git commit -m "feat(stage3): _enb_equal_weight helper

Phase 2b Task 2. compute_enb(equal weight, minimum_torsion) wrapper. n=0→0, n=1→1.
3 tests (single, empty, uncorrelated)."
```

---

### Task 3: `select_by_enb_greedy` 핵심 함수

**Files:**
- Modify: `tradingagents/skills/portfolio/factor_scorer.py`
- Modify: `tests/unit/skills/test_portfolio_factor_scorer.py`

- [ ] **Step 1: Write failing tests (큰 묶음)**

`tests/unit/skills/test_portfolio_factor_scorer.py` 끝에 append:
```python
def _make_diag_sigma(tickers, vol=0.04):
    """Diagonal cov = uncorrelated."""
    import pandas as pd
    import numpy as np
    n = len(tickers)
    return pd.DataFrame(np.eye(n) * vol, index=tickers, columns=tickers)


def _make_dup_sigma(tickers, vol=0.04, rho=0.999):
    """All-pairs high correlation."""
    import pandas as pd
    import numpy as np
    n = len(tickers)
    corr = np.full((n, n), rho)
    np.fill_diagonal(corr, 1.0)
    return pd.DataFrame(corr * vol, index=tickers, columns=tickers)


def test_select_by_enb_greedy_seed_from_top_composite():
    """Seed = (alpha_impl_blend × z(alpha) + (1 - blend) × z(impl)) 1등."""
    from tradingagents.skills.portfolio.factor_scorer import select_by_enb_greedy
    eligible = ["A", "B", "C"]
    alpha = {"A": 0.1, "B": 0.5, "C": 0.3}  # B 가 alpha 1등
    impl = {"A": 0.0, "B": 0.0, "C": 0.0}    # impl tie
    sigma = _make_diag_sigma(eligible)
    chosen = select_by_enb_greedy(
        eligible=eligible, alpha_scores=alpha, impl_scores=impl,
        sigma=sigma, n_max=1,
    )
    assert chosen == ["B"]


def test_select_by_enb_greedy_alpha_floor_only_positive():
    """음수 alpha 자동 제외."""
    from tradingagents.skills.portfolio.factor_scorer import select_by_enb_greedy
    eligible = ["A", "B", "C", "D"]
    alpha = {"A": 0.5, "B": -0.1, "C": -0.2, "D": -0.3}
    impl = {t: 0.0 for t in eligible}
    sigma = _make_diag_sigma(eligible)
    chosen = select_by_enb_greedy(
        eligible=eligible, alpha_scores=alpha, impl_scores=impl,
        sigma=sigma, n_max=4,
    )
    assert chosen == ["A"]


def test_select_by_enb_greedy_handles_no_positive_alpha():
    """모든 alpha ≤ 0 → 빈 list."""
    from tradingagents.skills.portfolio.factor_scorer import select_by_enb_greedy
    eligible = ["A", "B"]
    alpha = {"A": -0.1, "B": -0.2}
    impl = {"A": 0.0, "B": 0.0}
    sigma = _make_diag_sigma(eligible)
    chosen = select_by_enb_greedy(
        eligible=eligible, alpha_scores=alpha, impl_scores=impl,
        sigma=sigma, n_max=3,
    )
    assert chosen == []


def test_select_by_enb_greedy_n_max_zero_returns_empty():
    """n_max = 0 → 빈 list."""
    from tradingagents.skills.portfolio.factor_scorer import select_by_enb_greedy
    eligible = ["A", "B"]
    alpha = {"A": 0.5, "B": 0.3}
    impl = {"A": 0.0, "B": 0.0}
    sigma = _make_diag_sigma(eligible)
    chosen = select_by_enb_greedy(
        eligible=eligible, alpha_scores=alpha, impl_scores=impl,
        sigma=sigma, n_max=0,
    )
    assert chosen == []


def test_select_by_enb_greedy_stops_at_n_max():
    """n_max=2 도달 시 중단 (uncorrelated 라 delta 큼)."""
    from tradingagents.skills.portfolio.factor_scorer import select_by_enb_greedy
    eligible = ["A", "B", "C", "D"]
    alpha = {t: 0.5 for t in eligible}  # 모두 동등 alpha
    impl = {t: 0.0 for t in eligible}
    sigma = _make_diag_sigma(eligible)
    chosen = select_by_enb_greedy(
        eligible=eligible, alpha_scores=alpha, impl_scores=impl,
        sigma=sigma, n_max=2,
    )
    assert len(chosen) == 2


def test_select_by_enb_greedy_duplicates_picked_once():
    """corr ≈ 1 인 3 ETF → seed 1개만 (ΔENB ≈ 0)."""
    from tradingagents.skills.portfolio.factor_scorer import select_by_enb_greedy
    eligible = ["A", "B", "C"]
    alpha = {t: 0.5 for t in eligible}
    impl = {t: 0.0 for t in eligible}
    sigma = _make_dup_sigma(eligible)  # 모두 corr ≈ 1
    chosen = select_by_enb_greedy(
        eligible=eligible, alpha_scores=alpha, impl_scores=impl,
        sigma=sigma, n_max=3,
    )
    # 첫 1개만 (ΔENB ≈ 0 < 0.15)
    assert len(chosen) == 1


def test_select_by_enb_greedy_attribution_progression_recorded():
    """selection_trace 의 모든 키 채움."""
    from tradingagents.skills.portfolio.factor_scorer import select_by_enb_greedy
    eligible = ["A", "B", "C", "D"]
    alpha = {"A": 0.5, "B": 0.3, "C": -0.1, "D": 0.4}
    impl = {t: 0.0 for t in eligible}
    sigma = _make_diag_sigma(eligible)
    trace: dict = {}
    select_by_enb_greedy(
        eligible=eligible, alpha_scores=alpha, impl_scores=impl,
        sigma=sigma, n_max=3, selection_trace=trace,
    )
    assert "stop_reason" in trace
    assert "enb_progression" in trace
    assert "rejected" in trace
    assert "alpha_impl_blend_used" in trace
    # 음수 alpha 인 C 가 rejected 에 alpha_negative 로 기록
    rejected_alpha_neg = [r for r in trace["rejected"] if r.get("reason") == "alpha_negative"]
    assert any(r["ticker"] == "C" for r in rejected_alpha_neg)


def test_select_by_enb_greedy_alpha_impl_blend_weighting():
    """alpha 동등 → impl 큰 쪽 우선 (blend < 1)."""
    from tradingagents.skills.portfolio.factor_scorer import select_by_enb_greedy
    eligible = ["A", "B"]
    alpha = {"A": 0.5, "B": 0.5}  # tie
    impl = {"A": 0.1, "B": 0.9}    # B 가 impl 1등
    sigma = _make_diag_sigma(eligible)
    chosen = select_by_enb_greedy(
        eligible=eligible, alpha_scores=alpha, impl_scores=impl,
        sigma=sigma, n_max=1,
    )
    assert chosen == ["B"]


def test_select_by_enb_greedy_stops_at_delta_threshold():
    """corr ≈ 1 의 후보들 → delta 미달 stop."""
    from tradingagents.skills.portfolio.factor_scorer import select_by_enb_greedy
    eligible = ["A", "B", "C"]
    alpha = {t: 0.5 for t in eligible}
    impl = {t: 0.0 for t in eligible}
    sigma = _make_dup_sigma(eligible)
    trace: dict = {}
    chosen = select_by_enb_greedy(
        eligible=eligible, alpha_scores=alpha, impl_scores=impl,
        sigma=sigma, n_max=3, selection_trace=trace,
    )
    assert len(chosen) == 1
    assert trace["stop_reason"] == "delta_below_threshold"
```

- [ ] **Step 2: Run failing**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_factor_scorer.py -v -k select_by_enb_greedy 2>&1 | tail -15
```
Expected: 9 FAIL (NameError: select_by_enb_greedy)

- [ ] **Step 3: Implement `select_by_enb_greedy`**

`tradingagents/skills/portfolio/factor_scorer.py` 에 추가 (`_enb_equal_weight` 직후):
```python
def select_by_enb_greedy(
    *,
    eligible: list[str],
    alpha_scores: dict[str, float],
    impl_scores: dict[str, float],
    sigma: pd.DataFrame,
    n_max: int,
    n_min: int = N_MIN_HARD_FLOOR,
    enb_delta_threshold: float = ENB_DELTA_THRESHOLD,
    alpha_impl_blend: float = ALPHA_IMPL_BLEND_DEFAULT,
    selection_trace: dict | None = None,
) -> list[str]:
    """Forward greedy ENB-incremental selection.

    1. Pool = {t in eligible | alpha_scores[t] > 0}  (alpha floor)
    2. Composite = blend × z(alpha) + (1 - blend) × z(impl)
    3. Seed = composite top-1
    4. While pool and len < n_max:
         j* = argmax (ENB(selected ∪ {j}) - ENB(selected))
         if ΔENB < threshold and len ≥ n_min: stop
         selected.append(j*)
    """
    # 음수 alpha 추적 (trace 용)
    rejected_alpha_negative = [
        {"ticker": t, "reason": "alpha_negative"}
        for t in eligible if alpha_scores.get(t, 0.0) <= 0
    ]

    pool = [t for t in eligible if alpha_scores.get(t, 0.0) > 0]
    if not pool:
        if selection_trace is not None:
            selection_trace["stop_reason"] = "no_positive_alpha"
            selection_trace["enb_progression"] = []
            selection_trace["rejected"] = rejected_alpha_negative
            selection_trace["alpha_impl_blend_used"] = alpha_impl_blend
        return []

    if n_max <= 0:
        if selection_trace is not None:
            selection_trace["stop_reason"] = "capacity_zero"
            selection_trace["enb_progression"] = []
            selection_trace["rejected"] = rejected_alpha_negative
            selection_trace["alpha_impl_blend_used"] = alpha_impl_blend
        return []

    # Composite score
    z_alpha = _rank_normalize({t: alpha_scores[t] for t in pool})
    z_impl = _rank_normalize({t: impl_scores.get(t, 0.0) for t in pool})
    composite = {
        t: alpha_impl_blend * z_alpha[t] + (1 - alpha_impl_blend) * z_impl[t]
        for t in pool
    }
    pool.sort(key=lambda t: composite[t], reverse=True)

    # Seed
    seed = pool.pop(0)
    selected = [seed]
    progression: list[dict] = [{"step": 0, "ticker": seed, "enb": 1.0}]
    rejected_deltas: list[dict] = []
    stop_reason = "pool_exhausted"

    # Greedy forward
    while pool and len(selected) < n_max:
        prev_enb = _enb_equal_weight(selected, sigma)
        best_t = None
        best_delta = -float("inf")
        for j in pool:
            candidate_set = selected + [j]
            try:
                new_enb = _enb_equal_weight(candidate_set, sigma)
            except Exception as e:  # noqa: BLE001
                logger.warning("enb compute failed for %s: %s", j, e)
                continue
            delta = new_enb - prev_enb
            if delta > best_delta:
                best_delta = delta
                best_t = j

        if best_t is None:
            stop_reason = "numerical_failure"
            break

        if best_delta < enb_delta_threshold and len(selected) >= n_min:
            stop_reason = "delta_below_threshold"
            rejected_deltas.extend(
                {"ticker": t, "reason": "delta_too_small", "delta": float(best_delta)}
                for t in pool
            )
            break

        selected.append(best_t)
        pool.remove(best_t)
        progression.append({
            "step": len(selected) - 1,
            "ticker": best_t,
            "enb": float(prev_enb + best_delta),
            "delta": float(best_delta),
        })

    if len(selected) >= n_max and stop_reason == "pool_exhausted":
        stop_reason = "n_max_reached"

    if selection_trace is not None:
        selection_trace["stop_reason"] = stop_reason
        selection_trace["enb_progression"] = progression
        selection_trace["rejected"] = rejected_alpha_negative + rejected_deltas
        selection_trace["alpha_impl_blend_used"] = alpha_impl_blend

    return selected
```

- [ ] **Step 4: Run tests pass**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_factor_scorer.py -v -k select_by_enb_greedy 2>&1 | tail -15
```
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/portfolio/factor_scorer.py tests/unit/skills/test_portfolio_factor_scorer.py
git commit -m "feat(stage3): select_by_enb_greedy 신규

Phase 2b Task 3. Forward greedy ENB-incremental selection.
- Alpha floor (Phase 1 정신)
- Composite seed (0.85α + 0.15 impl)
- Stop: delta < 0.15 (한계효용) or n_max reached or pool exhausted
- selection_trace: stop_reason, enb_progression, rejected, alpha_impl_blend_used
9 unit tests."
```

---

### Task 4: `select_cluster_aware` + `_corr_groups` 삭제

**Files:**
- Modify: `tradingagents/skills/portfolio/factor_scorer.py`
- Modify: `tests/unit/skills/test_portfolio_factor_scorer.py`

- [ ] **Step 1: Confirm callers**

```bash
cd /Users/kimjaewon/Pluto/TradingAgents/.claude/worktrees/<worktree>
grep -rn "select_cluster_aware\|_corr_groups" tradingagents/ tests/ 2>&1 | grep -v __pycache__ | head -20
```
호출처: `candidate_selector.py` (Task 5 에서 교체), `test_portfolio_factor_scorer.py` (이 task 에서 제거).

- [ ] **Step 2: 기존 cluster-aware 테스트 제거**

`tests/unit/skills/test_portfolio_factor_scorer.py` 에서 다음 패턴의 테스트 모두 제거 (전체 함수 body 삭제):
- `test_*cluster_aware*` — 모든 cluster-aware 관련 (3-5개)
- `test_*select_cluster_aware*`

grep 으로 정확히 찾고 함수 단위로 삭제. 단 `test_select_by_enb_greedy_*` 와 `test_compute_adaptive_n_max_*` 는 유지.

- [ ] **Step 3: Delete `select_cluster_aware` + `_corr_groups`**

`tradingagents/skills/portfolio/factor_scorer.py` 에서:
- `def _corr_groups(...)` 함수 전체 삭제 (대략 line 430-460)
- `def select_cluster_aware(...)` 함수 전체 삭제 (대략 line 491-650)

`select_diverse` 는 유지 (bond TIPS path 에서 사용).

- [ ] **Step 4: py_compile + tests pass**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m py_compile tradingagents/skills/portfolio/factor_scorer.py && echo OK
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_factor_scorer.py -q 2>&1 | tail -5
```
Expected: compile OK + factor_scorer 단위 테스트 모두 PASS (이전 cluster-aware 테스트 제거됨).

만약 candidate_selector.py 가 select_cluster_aware import 한 채로 두면 ImportError 발생 → Task 5 에서 정리 (이 task 는 factor_scorer 만 정리). 단위 테스트 run 시 candidate_selector 가 collect 안 되면 OK; collect 단계에서 fail 하면 일단 `# select_cluster_aware import 제거 — Task 5 에서 처리` 같은 placeholder 주석 + 호출 라인 임시 None 처리.

실제로는 Task 5 와 함께 묶어서 진행하면 깔끔.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/portfolio/factor_scorer.py tests/unit/skills/test_portfolio_factor_scorer.py
git commit -m "refactor(stage3): select_cluster_aware + _corr_groups 삭제

Phase 2b Task 4. ENB greedy 로 교체됨. clean break — backward compat 없음.
호출처 update 는 Task 5 (candidate_selector). bond TIPS path 의 select_diverse 는 유지.
기존 cluster-aware 단위 테스트 제거."
```

---

### Task 5: `candidate_selector` 시그니처 확장 (sigma + capital_krw, per_bucket_n 제거)

**Files:**
- Modify: `tradingagents/skills/portfolio/candidate_selector.py`
- Modify: `tests/unit/skills/test_portfolio_candidate.py`

- [ ] **Step 1: Write failing test for adaptive N attribution**

`tests/unit/skills/test_portfolio_candidate.py` 끝에 append:
```python
def test_select_etf_candidates_attribution_records_selection_trace(monkeypatch):
    """attribution['buckets'][b]['selection_trace'] 가 채워짐."""
    from datetime import date
    import math
    import numpy as np
    import pandas as pd

    from tradingagents.dataflows.universe import ETFEntry, Universe
    from tradingagents.schemas.portfolio import BucketTarget
    from tradingagents.skills.portfolio.candidate_selector import select_etf_candidates
    from tradingagents.skills.portfolio.factor_scorer import FactorPanel

    etfs = [
        ETFEntry(
            ticker=f"K{i:02d}", name=f"K{i}", aum_krw=10_000_000_000_000,
            underlying_index=f"X{i}", bucket="위험", category="국내주식_지수",
        )
        for i in range(4)
    ]
    universe = Universe(version="test", etfs=etfs)
    bt = BucketTarget(
        kr_equity=0.5, global_equity=0.0, fx_commodity=0.0,
        bond=0.0, cash_mmf=0.5, bond_tips_share=0.0, rationale="test",
    )
    rng = np.random.default_rng(7)
    returns = pd.DataFrame(
        rng.normal(0, 0.01, size=(252, 4)),
        columns=[e.ticker for e in etfs],
    )
    sigma = returns.cov()
    factor_panel = {
        e.ticker: FactorPanel(
            skip1m_mom_3m=0.05, skip1m_mom_6m=0.05, skip1m_mom_12m=0.05,
            realized_vol_60d=0.1, sharpe_60d=0.5,
            log_aum=math.log(e.aum_krw),
        )
        for e in etfs
    }
    # metrics fetch mock — 빈 DataFrame
    monkeypatch.setattr(
        "tradingagents.skills.portfolio.candidate_selector.fetch_etf_metrics_window",
        lambda tickers, start, end, cache_path=None: pd.DataFrame(),
    )
    attribution: dict = {}
    select_etf_candidates(
        universe, bt, as_of=date(2026, 5, 28),
        returns=returns, factor_panel=factor_panel,
        sigma=sigma, capital_krw=1_000_000_000,
        attribution=attribution,
    )
    bucket_attr = attribution["buckets"]["kr_equity"]
    assert "selection_trace" in bucket_attr
    trace = bucket_attr["selection_trace"]
    assert "stop_reason" in trace
    assert "enb_progression" in trace


def test_select_etf_candidates_adaptive_n_caps_small_capital(monkeypatch):
    """1B capital × 0.10 bucket = 100M → n_max=2 (capital cap)."""
    from datetime import date
    import math
    import numpy as np
    import pandas as pd

    from tradingagents.dataflows.universe import ETFEntry, Universe
    from tradingagents.schemas.portfolio import BucketTarget
    from tradingagents.skills.portfolio.candidate_selector import select_etf_candidates
    from tradingagents.skills.portfolio.factor_scorer import FactorPanel

    # 10 ETF (충분히 많은) — 모두 uncorrelated
    etfs = [
        ETFEntry(
            ticker=f"K{i:02d}", name=f"K{i}", aum_krw=10_000_000_000_000,
            underlying_index=f"X{i}", bucket="위험", category="국내주식_지수",
        )
        for i in range(10)
    ]
    universe = Universe(version="test", etfs=etfs)
    bt = BucketTarget(
        kr_equity=0.10, global_equity=0.0, fx_commodity=0.0,
        bond=0.0, cash_mmf=0.90, bond_tips_share=0.0, rationale="test",
    )
    rng = np.random.default_rng(11)
    returns = pd.DataFrame(
        rng.normal(0, 0.01, size=(252, 10)),
        columns=[e.ticker for e in etfs],
    )
    sigma = returns.cov()
    factor_panel = {
        e.ticker: FactorPanel(
            skip1m_mom_3m=0.05, skip1m_mom_6m=0.05, skip1m_mom_12m=0.05,
            realized_vol_60d=0.1, sharpe_60d=0.5,
            log_aum=math.log(e.aum_krw),
        )
        for e in etfs
    }
    monkeypatch.setattr(
        "tradingagents.skills.portfolio.candidate_selector.fetch_etf_metrics_window",
        lambda tickers, start, end, cache_path=None: pd.DataFrame(),
    )
    candidates = select_etf_candidates(
        universe, bt, as_of=date(2026, 5, 28),
        returns=returns, factor_panel=factor_panel,
        sigma=sigma, capital_krw=1_000_000_000,
    )
    # 1B × 0.10 / 50M = 2 → n_max=2 (uncorrelated 이므로 delta 한계 도달 전 n_max 도달)
    assert len(candidates.bucket_to_tickers["kr_equity"]) == 2
```

- [ ] **Step 2: Run failing**

Expected: 2 FAIL — signature mismatch (sigma 인자 미정의 + per_bucket_n 제거 안 됨).

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_candidate.py -v -k "adaptive\|selection_trace" 2>&1 | tail -10
```

- [ ] **Step 3: Modify `candidate_selector.py` 시그니처**

`tradingagents/skills/portfolio/candidate_selector.py` 의 import 블록 상단에 추가:
```python
from tradingagents.skills.portfolio.factor_scorer import (
    compute_adaptive_n_max, select_by_enb_greedy,
)
```

기존 `from tradingagents.skills.portfolio.factor_scorer import (... select_cluster_aware ...)` 에서 `select_cluster_aware` 제거.

`select_etf_candidates` 시그니처에서:
- `per_bucket_n: int = 5` 제거
- `sigma: pd.DataFrame,` 추가 (필수)
- `capital_krw: float,` 추가 (필수)

본문에서 `select_cluster_aware(...)` 호출 부분 (대략 line 285 근처) 을 다음으로 교체:

```python
            # Phase 2b — adaptive n_max + ENB greedy
            bucket_eligible_tickers = [e.ticker for e in eligible_in_bucket]
            n_positive_alpha = sum(1 for t in bucket_eligible_tickers if alpha_scores.get(t, 0.0) > 0)
            n_max = compute_adaptive_n_max(
                n_positive_alpha=n_positive_alpha,
                bucket_weight=bucket_weight,
                capital_krw=capital_krw,
            )
            sigma_sub = sigma.reindex(
                index=bucket_eligible_tickers, columns=bucket_eligible_tickers,
            ).dropna(how="all").dropna(axis=1, how="all")
            # 일부 ticker 가 sigma 에 없으면 그 ticker 만 제외
            valid_eligible = [t for t in bucket_eligible_tickers if t in sigma_sub.index]
            selection_trace: dict = {}
            chosen = select_by_enb_greedy(
                eligible=valid_eligible,
                alpha_scores=alpha_scores,
                impl_scores=impl_scores,
                sigma=sigma_sub,
                n_max=n_max,
                selection_trace=selection_trace,
            )
            if bucket_attr is not None:
                bucket_attr["selection_trace"] = selection_trace
                bucket_attr["n_max_computed"] = n_max
```

기존 `chosen[:per_bucket_n]` 같은 slicing 라인 제거.

기존 attribution 의 `per_bucket_n` 참조 (대략 line 204) 제거 — 기존 `attribution["config"]["per_bucket_n"]` 같은 키 set 부분이 candidate_selector 에 있으면 제거.

`selection_criteria` 문자열 update:
```python
selection_criteria=(
    f"AUM filter removed, mode={mode_label}, capital={capital_krw/1e9:.1f}B KRW, "
    f"strategy=enb_greedy"
)[:300],
```

- [ ] **Step 4: 기존 test fixture update (per_bucket_n 사용처)**

`tests/unit/skills/test_portfolio_candidate.py` 안의 기존 테스트들이 `per_bucket_n=` 또는 sigma 없이 호출하면 FAIL. 모두 update:
- `per_bucket_n=N` 인자 제거
- `sigma=returns.cov()` 와 `capital_krw=1_000_000_000` 추가

기존 회귀 테스트의 chosen 길이 검증 (`assert len(chosen) == N`) 가 있으면 adaptive 결과로 update 또는 assertion 완화.

각 기존 test 의 callsite 보고 fix.

- [ ] **Step 5: Run candidate tests**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_candidate.py -v 2>&1 | tail -25
```
Expected: 모든 candidate 테스트 통과 (signature 일관, adaptive N 동작).

- [ ] **Step 6: Commit**

```bash
git add tradingagents/skills/portfolio/candidate_selector.py tests/unit/skills/test_portfolio_candidate.py
git commit -m "refactor(stage3): candidate_selector signature + ENB greedy 호출

Phase 2b Task 5. per_bucket_n 제거, sigma + capital_krw 추가. select_cluster_aware
호출을 select_by_enb_greedy 로 교체. attribution.buckets[b].selection_trace 추가.
2 new tests + 기존 회귀 update."
```

---

### Task 6: `portfolio_allocator` 호출부 + sigma 계산 + per_bucket_n 폐기

**Files:**
- Modify: `tradingagents/agents/allocator/portfolio_allocator.py`

- [ ] **Step 1: Inspect 변경 지점**

```bash
grep -nE "per_bucket_n|select_etf_candidates|sample_cov" tradingagents/agents/allocator/portfolio_allocator.py 2>&1 | head -20
```

- [ ] **Step 2: 변경 적용**

`tradingagents/agents/allocator/portfolio_allocator.py` 의 `node` 함수에서:

(a) `per_bucket_n` 결정 블록 (대략 line 108-114) **전체 삭제**:
```python
        # Phase 2b — per_bucket_n 결정 로직 폐기 (adaptive n_max 가 candidate_selector 안에서 자동)
        # 기존:
        # per_bucket_n = 4
        # if research_decision conviction == "low": per_bucket_n = 5
        # if attempts > 0: per_bucket_n = max(per_bucket_n + 2, 6)
```

(b) returns 검증 직후 (대략 line 130 근처, `if returns is None or returns.empty: raise ...` 이후) **sigma 사전 계산** 추가:
```python
        # Phase 2b — sigma 사전 계산 (candidate_selector + optimize 모두 사용)
        import numpy as np
        sigma = returns.dropna(axis=0, how="any").cov()
        capital_krw = float(state.get("capital_krw") or state.get("capital") or 1_000_000_000)
```

(c) `select_etf_candidates(...)` 호출 (대략 line 211) **인자 수정**:
- `per_bucket_n=per_bucket_n` 제거
- `sigma=sigma, capital_krw=capital_krw` 추가

```python
        candidates = select_etf_candidates(
            universe, bucket_target, as_of,
            returns=returns,
            factor_panel=factor_panel,
            sigma=sigma,
            capital_krw=capital_krw,
            # 기존 인자들 그대로 유지 (clusters, factor_scores 등)
            ...
        )
```

(d) attribution["config"] 변경:
```python
        # 제거: attribution["config"]["per_bucket_n"] = per_bucket_n
        attribution["config"]["selection_strategy"] = "enb_greedy"
        attribution["config"]["capital_krw"] = capital_krw
```

(e) `per_bucket_n` 변수가 다른 곳 (예: logger.info, attribution config 초기화) 참조하면 그것도 제거.

- [ ] **Step 3: Syntax + portfolio tests pass**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m py_compile tradingagents/agents/allocator/portfolio_allocator.py && echo OK
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/unit/skills/test_portfolio_*.py tests/unit/agents/test_portfolio_allocator.py -q 2>&1 | tail -5
```
Expected: OK + all pass.

- [ ] **Step 4: Integration tests 회귀**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/integration/test_plan_pipeline_mock.py tests/integration/test_5_28_dry_run.py -v 2>&1 | tail -10
```
Expected: 2 passed (Phase 1 의 spillover passthrough 패턴이 이미 적용됨, sigma 인자만 추가).

만약 fail 하면 mock fixture 의 select_etf_candidates 호출이 `sigma`, `capital_krw` 인자 받지 않아서일 수 있음. mock 의 lambda signature 만 update (`lambda *a, **kw: ...`).

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/allocator/portfolio_allocator.py
git commit -m "refactor(stage3): allocator sigma 사전 계산 + capital_krw + per_bucket_n 폐기

Phase 2b Task 6. select_etf_candidates 호출에 sigma + capital_krw 전달.
per_bucket_n 결정 로직 (conviction, attempts) 폐기 — adaptive_n_max 자동.
attribution.config.selection_strategy='enb_greedy' + capital_krw 기록."
```

---

### Task 7: State mocking helpers (Phase 1 followup)

**Files:**
- Create: `tests/integration/_allocator_state_helpers.py`

- [ ] **Step 1: Write helper module**

`tests/integration/_allocator_state_helpers.py` 생성:
```python
"""Allocator state mocking helpers (Phase 2b followup).

allocator node 가 read 하는 state dict 합성. 외부 의존성 없이
풀 파이프라인 통합 테스트 enable.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from tradingagents.dataflows.universe import ETFEntry, Universe
from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.skills.portfolio.factor_scorer import FactorPanel


BUCKET_CATEGORIES: dict[str, tuple[str, str, str | None]] = {
    "kr_equity":     ("국내주식_지수",         "위험", None),
    "global_equity": ("해외주식_지수",         "위험", None),
    "fx_commodity":  ("FX 및 원자재",          "위험", "gold"),
    "bond":          ("국내채권_종합",         "안전", "nominal"),
    "cash_mmf":      ("금리연계형/초단기채권", "안전", None),
}


def make_synthetic_universe(
    n_per_bucket: int = 4,
    base_aum: float = 50_000_000_000,
) -> Universe:
    """5 bucket × n_per_bucket ETFs."""
    etfs: list[ETFEntry] = []
    for bucket_name, (category, risk, sub_cat) in BUCKET_CATEGORIES.items():
        prefix = bucket_name[:2].upper()
        for i in range(n_per_bucket):
            etfs.append(ETFEntry(
                ticker=f"A_{prefix}{i:02d}",
                name=f"{bucket_name}_{i}",
                aum_krw=base_aum * (i + 1),
                underlying_index=f"{prefix}_idx_{i}",  # unique
                bucket=risk,
                category=category,
                sub_category=sub_cat,
            ))
    return Universe(version="test", etfs=etfs)


def make_synthetic_returns(
    tickers: list[str],
    n_days: int = 252,
    vol: float = 0.02,
    seed: int = 42,
) -> pd.DataFrame:
    """일별 returns DataFrame (모두 uncorrelated)."""
    rng = np.random.default_rng(seed)
    data = rng.normal(0.0, vol, size=(n_days, len(tickers)))
    return pd.DataFrame(data, columns=tickers)


def make_factor_panel(
    tickers: list[str],
    aum_by_ticker: dict[str, float] | None = None,
    alpha_overrides: dict[str, float] | None = None,
) -> dict[str, FactorPanel]:
    """FactorPanel dict. alpha 는 skip1m mom 으로 표현."""
    aum_by_ticker = aum_by_ticker or {}
    alpha_overrides = alpha_overrides or {}
    panels: dict[str, FactorPanel] = {}
    for t in tickers:
        aum = aum_by_ticker.get(t, 50_000_000_000)
        # alpha_override 가 있으면 skip1m mom 들을 그 값으로
        alpha = alpha_overrides.get(t, 0.05)
        panels[t] = FactorPanel(
            skip1m_mom_3m=alpha,
            skip1m_mom_6m=alpha,
            skip1m_mom_12m=alpha,
            realized_vol_60d=0.10,
            sharpe_60d=0.5,
            log_aum=math.log(aum),
        )
    return panels


def make_bucket_target(
    *,
    kr_equity: float = 0.20,
    global_equity: float = 0.20,
    fx_commodity: float = 0.15,
    bond: float = 0.30,
    cash_mmf: float = 0.15,
    bond_tips_share: float = 0.0,
    rationale: str = "test",
) -> BucketTarget:
    """합 검증된 BucketTarget."""
    total = kr_equity + global_equity + fx_commodity + bond + cash_mmf
    assert abs(total - 1.0) < 1e-9, f"bucket weights sum {total} != 1.0"
    return BucketTarget(
        kr_equity=kr_equity, global_equity=global_equity,
        fx_commodity=fx_commodity, bond=bond, cash_mmf=cash_mmf,
        bond_tips_share=bond_tips_share, rationale=rationale,
    )
```

(나머지 schema (research_decision, macro_report, risk_report, technical_report) 의 builder 는 각 schema 의 필수 필드 검토 후 추가. spec 의 Section 4 참고. 실 schema 시그니처 확인:

```bash
grep -nE "^class ResearchDecision|^class MacroReport|^class Regime|^class RiskReport|^class SystemicScore|^class TechnicalReport" tradingagents/schemas/*.py
```

발견된 schemas 의 필수 필드에 맞춰 builder 작성. 길이 절약 위해 spec 의 Section 4 API 시그니처 그대로 따라가되, 실제 필수 필드는 grep 후 채움.)

```python
# Pseudo — 실제 schema 필드 grep 후 적용
def make_research_decision(
    *,
    conviction: str = "medium",
    dominant_scenario: str | None = "goldilocks",
    factor_scores: dict[str, float] | None = None,
):
    """ResearchDecision mock — 실제 schema 필수 필드 채움."""
    from tradingagents.schemas.research import ResearchDecision
    return ResearchDecision(
        # ... 실제 필드들 ...
        conviction=conviction,
        dominant_scenario=dominant_scenario,
        factor_scores=factor_scores or {},
    )


def make_macro_report(
    *,
    regime_quadrant: str = "growth_disinflation",
    regime_confidence: float = 0.7,
    staleness_days: int = 1,
):
    """MacroReport + Regime — schema 필드 채움."""
    from tradingagents.schemas.macro import MacroReport, Regime
    regime = Regime(
        quadrant=regime_quadrant,
        confidence=regime_confidence,
        staleness_days=staleness_days,
        # ... 실 필드 ...
    )
    return MacroReport(regime=regime, ...)


def make_risk_report(
    *,
    systemic_score: float = 5.0,
    systemic_regime: str = "neutral",
    staleness_days: int = 1,
):
    """RiskReport + SystemicScore."""
    from tradingagents.schemas.risk import RiskReport, SystemicScore
    score = SystemicScore(
        score=systemic_score,
        regime=systemic_regime,
        staleness_days=staleness_days,
        # ... 실 필드 ...
    )
    return RiskReport(systemic_score=score, ...)


def make_technical_report(
    factor_panel: dict[str, FactorPanel],
    *,
    correlation_clusters: list | None = None,
):
    """TechnicalReport with factor_panel."""
    from tradingagents.schemas.technical import TechnicalReport
    return TechnicalReport(
        factor_panel=factor_panel,
        correlation_clusters=correlation_clusters or [],
        risk_adjusted={},
        trend_quantification={},
        extended_indicators={},
        individual_etf_states={},
    )


def make_allocator_state(
    *,
    as_of: date,
    universe_path: str,
    bucket_target: BucketTarget,
    technical_report,
    macro_report,
    risk_report,
    research_decision,
    capital_krw: float = 1_000_000_000,
    allocation_feedback: list | None = None,
    allocation_attempts: int = 0,
) -> dict:
    """allocator node 가 read 하는 state dict."""
    return {
        "as_of_date": as_of.isoformat(),
        "universe_path": universe_path,
        "bucket_target": bucket_target,
        "technical_report": technical_report,
        "macro_report": macro_report,
        "risk_report": risk_report,
        "research_decision": research_decision,
        "capital_krw": capital_krw,
        "allocation_feedback": allocation_feedback or [],
        "allocation_attempts": allocation_attempts,
    }
```

- [ ] **Step 2: Smoke test**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -c "
import sys
sys.path.insert(0, '.')
from datetime import date
from tests.integration._allocator_state_helpers import (
    make_synthetic_universe, make_synthetic_returns, make_factor_panel,
    make_bucket_target, make_macro_report, make_risk_report,
    make_research_decision, make_technical_report, make_allocator_state,
)
u = make_synthetic_universe()
print('universe:', len(u.etfs), 'ETFs')
tickers = [e.ticker for e in u.etfs]
r = make_synthetic_returns(tickers, n_days=100)
print('returns shape:', r.shape)
fp = make_factor_panel(tickers)
print('factor_panel:', len(fp))
bt = make_bucket_target()
print('bucket_target:', bt.rationale)
"
```
Expected: 모든 builder 동작.

만약 schema 의 필수 필드 누락으로 fail 하면 schema 정의 grep 으로 확인 + 채움.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/_allocator_state_helpers.py
git commit -m "test(stage3): allocator state mocking helpers (Phase 1 followup)

Phase 2b Task 7. universe / returns / factor_panel / bucket_target / regime /
research_decision / state dict builder. Phase 1 의 4 skip integration tests
enable 의 prerequisite."
```

---

### Task 8: `test_allocator_phase1.py` 4 skip tests Enable

**Files:**
- Modify: `tests/integration/test_allocator_phase1.py`

- [ ] **Step 1: 4 skip 데코레이터 제거 + 실제 구현**

`tests/integration/test_allocator_phase1.py` 의 4 skip tests 를 update.

**test 1**: `test_allocator_with_normal_universe`
```python
def test_allocator_with_normal_universe(tmp_path, monkeypatch):
    """5 bucket 양수 alpha 충분 → spillover ≈ 0, ENB > 2.0."""
    from datetime import date
    from tests.integration._allocator_state_helpers import (
        make_synthetic_universe, make_synthetic_returns, make_factor_panel,
        make_bucket_target, make_macro_report, make_risk_report,
        make_research_decision, make_technical_report, make_allocator_state,
    )
    from tradingagents.agents.allocator.portfolio_allocator import create_portfolio_allocator
    import pandas as pd

    universe = make_synthetic_universe(n_per_bucket=4)
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(universe.model_dump_json())

    tickers = [e.ticker for e in universe.etfs]
    returns = make_synthetic_returns(tickers, n_days=252, seed=7)
    factor_panel = make_factor_panel(tickers)  # default alpha 0.05 (양수)

    # KRX metrics fetch mock — fallback
    monkeypatch.setattr(
        "tradingagents.skills.portfolio.candidate_selector.fetch_etf_metrics_window",
        lambda tickers, start, end, cache_path=None: pd.DataFrame(),
    )
    # returns matrix fetch mock
    monkeypatch.setattr(
        "tradingagents.agents.allocator.portfolio_allocator.fetch_returns_matrix",
        lambda eligible, start, end, cache_path=None: returns[eligible],
    )

    state = make_allocator_state(
        as_of=date(2026, 5, 28),
        universe_path=str(universe_path),
        bucket_target=make_bucket_target(),
        technical_report=make_technical_report(factor_panel),
        macro_report=make_macro_report(),
        risk_report=make_risk_report(),
        research_decision=make_research_decision(),
    )

    node_func = create_portfolio_allocator()
    result = node_func(state)

    spillover = result["allocation_attribution"]["cash_spillover"]
    assert spillover["total_spillover_to_cash"] < 0.10
    assert result["allocation_attribution"]["enb"] > 1.5
```

**test 2**: `test_allocator_with_fx_negative_only`
```python
def test_allocator_with_fx_negative_only(tmp_path, monkeypatch):
    """fx_commodity alpha 음수 → bucket weight 감소, cash 증가."""
    from datetime import date
    from tests.integration._allocator_state_helpers import (
        make_synthetic_universe, make_synthetic_returns, make_factor_panel,
        make_bucket_target, make_macro_report, make_risk_report,
        make_research_decision, make_technical_report, make_allocator_state,
        BUCKET_CATEGORIES,
    )
    from tradingagents.agents.allocator.portfolio_allocator import create_portfolio_allocator
    import pandas as pd

    universe = make_synthetic_universe(n_per_bucket=4)
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(universe.model_dump_json())

    tickers = [e.ticker for e in universe.etfs]
    fx_cat = BUCKET_CATEGORIES["fx_commodity"][0]
    fx_tickers = [e.ticker for e in universe.etfs if e.category == fx_cat]
    returns = make_synthetic_returns(tickers, n_days=252, seed=11)
    factor_panel = make_factor_panel(
        tickers,
        alpha_overrides={t: -0.05 for t in fx_tickers},  # fx alpha 음수
    )

    monkeypatch.setattr(
        "tradingagents.skills.portfolio.candidate_selector.fetch_etf_metrics_window",
        lambda tickers, start, end, cache_path=None: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "tradingagents.agents.allocator.portfolio_allocator.fetch_returns_matrix",
        lambda eligible, start, end, cache_path=None: returns[eligible],
    )

    state = make_allocator_state(
        as_of=date(2026, 5, 28),
        universe_path=str(universe_path),
        bucket_target=make_bucket_target(),
        technical_report=make_technical_report(factor_panel),
        macro_report=make_macro_report(),
        risk_report=make_risk_report(),
        research_decision=make_research_decision(),
    )

    node_func = create_portfolio_allocator()
    result = node_func(state)

    config = result["allocation_attribution"]["config"]
    bt_stage2 = config["bucket_target_stage2"]
    bt_post = config["bucket_target_post_spillover"]
    assert bt_post["fx_commodity"] < bt_stage2["fx_commodity"]
    assert bt_post["cash_mmf"] > bt_stage2["cash_mmf"]
```

**test 3**: `test_allocator_with_global_low_conviction`
```python
def test_allocator_with_global_low_conviction(tmp_path, monkeypatch):
    """global alpha 낮음 → 부분 spillover."""
    from datetime import date
    from tests.integration._allocator_state_helpers import (
        make_synthetic_universe, make_synthetic_returns, make_factor_panel,
        make_bucket_target, make_macro_report, make_risk_report,
        make_research_decision, make_technical_report, make_allocator_state,
        BUCKET_CATEGORIES,
    )
    from tradingagents.agents.allocator.portfolio_allocator import create_portfolio_allocator
    import pandas as pd

    universe = make_synthetic_universe(n_per_bucket=4)
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(universe.model_dump_json())

    tickers = [e.ticker for e in universe.etfs]
    global_cat = BUCKET_CATEGORIES["global_equity"][0]
    global_tickers = [e.ticker for e in universe.etfs if e.category == global_cat]
    returns = make_synthetic_returns(tickers, n_days=252, seed=13)
    factor_panel = make_factor_panel(
        tickers,
        alpha_overrides={t: 0.005 for t in global_tickers},  # 낮은 양수
    )

    monkeypatch.setattr(
        "tradingagents.skills.portfolio.candidate_selector.fetch_etf_metrics_window",
        lambda tickers, start, end, cache_path=None: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "tradingagents.agents.allocator.portfolio_allocator.fetch_returns_matrix",
        lambda eligible, start, end, cache_path=None: returns[eligible],
    )

    state = make_allocator_state(
        as_of=date(2026, 5, 28),
        universe_path=str(universe_path),
        bucket_target=make_bucket_target(),
        technical_report=make_technical_report(factor_panel),
        macro_report=make_macro_report(),
        risk_report=make_risk_report(),
        research_decision=make_research_decision(),
    )

    node_func = create_portfolio_allocator()
    result = node_func(state)

    # global 의 conviction 이 낮아 일부 spillover 일어남 (full 또는 부분)
    spillover = result["allocation_attribution"]["cash_spillover"]
    convictions = spillover["convictions"]
    assert convictions["global_equity"]["conviction"] < 0.6
```

**test 4**: `test_allocator_cash_overflow_redistribution`
```python
def test_allocator_cash_overflow_redistribution(tmp_path, monkeypatch):
    """global+fx+bond 음수 → cash > 40% → overflow → kr_equity 로."""
    from datetime import date
    from tests.integration._allocator_state_helpers import (
        make_synthetic_universe, make_synthetic_returns, make_factor_panel,
        make_bucket_target, make_macro_report, make_risk_report,
        make_research_decision, make_technical_report, make_allocator_state,
        BUCKET_CATEGORIES,
    )
    from tradingagents.agents.allocator.portfolio_allocator import create_portfolio_allocator
    import pandas as pd

    universe = make_synthetic_universe(n_per_bucket=4)
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(universe.model_dump_json())

    tickers = [e.ticker for e in universe.etfs]
    # global, fx, bond ticker 들 모두 alpha 음수
    neg_categories = [
        BUCKET_CATEGORIES["global_equity"][0],
        BUCKET_CATEGORIES["fx_commodity"][0],
        BUCKET_CATEGORIES["bond"][0],
    ]
    neg_tickers = [e.ticker for e in universe.etfs if e.category in neg_categories]
    returns = make_synthetic_returns(tickers, n_days=252, seed=17)
    factor_panel = make_factor_panel(
        tickers,
        alpha_overrides={t: -0.05 for t in neg_tickers},
    )

    monkeypatch.setattr(
        "tradingagents.skills.portfolio.candidate_selector.fetch_etf_metrics_window",
        lambda tickers, start, end, cache_path=None: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "tradingagents.agents.allocator.portfolio_allocator.fetch_returns_matrix",
        lambda eligible, start, end, cache_path=None: returns[eligible],
    )

    state = make_allocator_state(
        as_of=date(2026, 5, 28),
        universe_path=str(universe_path),
        bucket_target=make_bucket_target(cash_mmf=0.15),  # cash 작게 → overflow 유도
        technical_report=make_technical_report(factor_panel),
        macro_report=make_macro_report(),
        risk_report=make_risk_report(),
        research_decision=make_research_decision(),
    )

    node_func = create_portfolio_allocator()
    result = node_func(state)

    spillover = result["allocation_attribution"]["cash_spillover"]
    assert spillover["cash_cap_triggered"] is True
    # overflow 가 kr_equity 또는 cash_mmf 로 분배됨
    assert spillover["adjusted_bucket_target"]["cash_mmf"] <= 0.40 + 1e-6
```

각 test 의 `@pytest.mark.skip(...)` 데코레이터 제거.

- [ ] **Step 2: Run tests**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/integration/test_allocator_phase1.py -v 2>&1 | tail -15
```
Expected: 모두 PASS (4 skip 사라지고 실제 실행).

만약 schema 빌더 부족으로 fail 하면 `_allocator_state_helpers.py` 의 schema builder 보강 (Task 7 의 retro fix).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_allocator_phase1.py
git commit -m "test(stage3): Phase 1 의 4 skip integration tests enable

Phase 2b Task 8. state_helpers 활용해 실제 동작 검증:
- normal universe (spillover ≈ 0)
- fx negative only (bucket weight 감소)
- global low conviction (부분 spillover)
- cash overflow redistribution (cap_triggered)
Phase 1 followup 완료."
```

---

### Task 9: `test_allocator_phase2b.py` 신규 통합 테스트

**Files:**
- Create: `tests/integration/test_allocator_phase2b.py`

- [ ] **Step 1: Write integration tests**

`tests/integration/test_allocator_phase2b.py` 생성:
```python
"""Phase 2b integration — adaptive N + ENB greedy 통합 검증."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from tests.integration._allocator_state_helpers import (
    BUCKET_CATEGORIES, make_allocator_state, make_bucket_target,
    make_factor_panel, make_macro_report, make_research_decision,
    make_risk_report, make_synthetic_returns, make_synthetic_universe,
    make_technical_report,
)
from tradingagents.agents.allocator.portfolio_allocator import (
    create_portfolio_allocator,
)


def _setup_state(tmp_path, monkeypatch, *, capital_krw: float = 1_000_000_000,
                 n_per_bucket: int = 6, bt=None):
    universe = make_synthetic_universe(n_per_bucket=n_per_bucket)
    universe_path = tmp_path / "universe.json"
    universe_path.write_text(universe.model_dump_json())
    tickers = [e.ticker for e in universe.etfs]
    returns = make_synthetic_returns(tickers, n_days=252, seed=5)
    factor_panel = make_factor_panel(tickers)
    monkeypatch.setattr(
        "tradingagents.skills.portfolio.candidate_selector.fetch_etf_metrics_window",
        lambda tickers, start, end, cache_path=None: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "tradingagents.agents.allocator.portfolio_allocator.fetch_returns_matrix",
        lambda eligible, start, end, cache_path=None: returns[eligible],
    )
    state = make_allocator_state(
        as_of=date(2026, 5, 28),
        universe_path=str(universe_path),
        bucket_target=bt or make_bucket_target(),
        technical_report=make_technical_report(factor_panel),
        macro_report=make_macro_report(),
        risk_report=make_risk_report(),
        research_decision=make_research_decision(),
        capital_krw=capital_krw,
    )
    return state


def test_adaptive_n_max_small_bucket_uses_capacity_cap(tmp_path, monkeypatch):
    """1B × kr_equity 0.10 = 100M → n_max = 2."""
    bt = make_bucket_target(
        kr_equity=0.10, global_equity=0.20, fx_commodity=0.10,
        bond=0.30, cash_mmf=0.30,
    )
    state = _setup_state(tmp_path, monkeypatch, bt=bt, n_per_bucket=10)
    result = create_portfolio_allocator()(state)
    bucket_attr = result["allocation_attribution"]["buckets"]["kr_equity"]
    trace = bucket_attr["selection_trace"]
    assert trace["n_max_components"]["capital_cap"] == 2
    # n_max_chosen 이 모든 cap 의 min 일 수 있음
    n_chosen = len(bucket_attr["chosen"])
    assert n_chosen <= 2


def test_adaptive_n_max_large_bucket_uses_abs_max(tmp_path, monkeypatch):
    """대형 자본 + 큰 bucket → abs_max 8 도달."""
    bt = make_bucket_target(
        kr_equity=0.50, global_equity=0.20, fx_commodity=0.0,
        bond=0.0, cash_mmf=0.30,
    )
    state = _setup_state(
        tmp_path, monkeypatch, bt=bt, n_per_bucket=15,
        capital_krw=10_000_000_000_000,  # 10T → capital_cap 매우 큼
    )
    result = create_portfolio_allocator()(state)
    bucket_attr = result["allocation_attribution"]["buckets"]["kr_equity"]
    trace = bucket_attr["selection_trace"]
    # abs_max 가 작은 cap 이 됨
    assert trace["n_max_components"]["abs_max"] == 8


def test_enb_greedy_attribution_has_progression(tmp_path, monkeypatch):
    """selection_trace 의 progression / stop_reason 채워짐."""
    state = _setup_state(tmp_path, monkeypatch)
    result = create_portfolio_allocator()(state)
    for bucket_name in ("kr_equity", "global_equity", "bond"):
        bucket_attr = result["allocation_attribution"]["buckets"][bucket_name]
        trace = bucket_attr["selection_trace"]
        assert "enb_progression" in trace
        assert "stop_reason" in trace
        assert trace["stop_reason"] in {
            "n_max_reached", "delta_below_threshold",
            "pool_exhausted", "no_positive_alpha", "capacity_zero",
        }


def test_attribution_selection_strategy_enb_greedy(tmp_path, monkeypatch):
    """attribution.config.selection_strategy = 'enb_greedy'."""
    state = _setup_state(tmp_path, monkeypatch)
    result = create_portfolio_allocator()(state)
    config = result["allocation_attribution"]["config"]
    assert config.get("selection_strategy") == "enb_greedy"
    assert "capital_krw" in config
```

- [ ] **Step 2: Run tests**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest tests/integration/test_allocator_phase2b.py -v 2>&1 | tail -10
```
Expected: 4 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_allocator_phase2b.py
git commit -m "test(stage3): Phase 2b integration 테스트

Phase 2b Task 9. 4 integration tests: small bucket capital cap, large bucket
abs_max, attribution progression, selection_strategy 키 확인."
```

---

### Task 10: Regression + Acceptance 검증

**Files:**
- (산출물 갱신): `artifacts/<as_of>/portfolio.json`

- [ ] **Step 1: E2E 실행**

```bash
cd /Users/kimjaewon/Pluto/TradingAgents/.claude/worktrees/<worktree>
cp /Users/kimjaewon/Pluto/TradingAgents/.env . 2>/dev/null || echo ".env not in main"

/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/run_e2e_test.py --as-of 2026-05-15 --capital 1000000000 2>&1 | tail -40
```

가능한 결과:
- **성공**: artifacts/2026-05-15/portfolio.json 갱신. attribution.buckets.*.selection_trace 채워짐.
- **부분 성공**: 일부 단계 실패해도 attribution 일부 채워짐. Phase 2b 특화 키 확인.
- **실패**: state 또는 환경 의존성. 보고 후 결정.

- [ ] **Step 2: Acceptance 검증 (직접 attribution 확인)**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -c "
import json
with open('artifacts/2026-05-15/portfolio.json') as f:
    p = json.load(f)
attr = p['allocation_attribution']
config = attr.get('config', {})
print('selection_strategy:', config.get('selection_strategy'))
print('capital_krw:', config.get('capital_krw'))
print()
buckets = attr.get('buckets', {})
for bname, ba in buckets.items():
    trace = ba.get('selection_trace', {})
    chosen = ba.get('chosen', [])
    print(f'{bname}: chosen={len(chosen)}, stop={trace.get(\"stop_reason\")}, n_max={trace.get(\"n_max_components\", {}).get(\"n_max_chosen\")}')
print()
# n_total 비교 (Phase 1 baseline 의 weights 와 비교)
weights = p.get('weights', {})
print('n_total:', len(weights))
print('ENB:', attr.get('enb'))
"
```

Expected:
- selection_strategy = 'enb_greedy'
- 5 bucket 의 selection_trace 모두 채워짐
- n_total ≤ 20 (Phase 1 baseline 대비 감소 또는 동등)

- [ ] **Step 3: regression_compare 실행**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/regression_compare.py \
    --baseline artifacts/baseline/ \
    --new artifacts/ \
    --out artifacts/phase2b_regression.json 2>&1 | tail -40
```

Acceptance (Phase 1, 2a generic) 결과 확인. Phase 2b 추가:
- (d), (e), (f), (g) 가 acceptance 추가 항목이지만 regression_compare.py 가 이를 직접 체크하지 않음 — 위 Step 2 의 manual 검증으로 대체.

- [ ] **Step 4: Full regression**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m pytest \
    tests/unit/dataflows/ \
    tests/unit/skills/test_portfolio_*.py \
    tests/unit/agents/test_portfolio_allocator.py \
    tests/integration/test_allocator_phase1.py \
    tests/integration/test_allocator_phase2a.py \
    tests/integration/test_allocator_phase2b.py \
    tests/integration/test_plan_pipeline_mock.py \
    tests/integration/test_5_28_dry_run.py \
    -q 2>&1 | tail -10
```
Expected: all pass.

- [ ] **Step 5: Commit 산출물 + regression**

```bash
git add artifacts/2025-04-15/ artifacts/2026-05-15/ artifacts/phase2b_regression.json 2>&1
git commit -m "$(cat <<'EOF'
chore(stage3): Phase 2b 적용 후 산출물 갱신 + 회귀 결과

baseline → phase2b:
  Phase 1, 2a generic acceptance: 회귀 결과 첨부
  Phase 2b specific:
    - attribution.config.selection_strategy = 'enb_greedy'
    - attribution.buckets.*.selection_trace 채워짐
    - n_total 감소 또는 동등 (adaptive N 효과)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)" 2>&1 || echo "nothing to commit"
```

---

## Self-Review

플랜 완성 후 spec 대비 누락 확인:

1. **Spec 신규/변경 모듈**:
   - `factor_scorer.py` (select_cluster_aware 삭제 + ENB greedy 신규) — Task 1, 2, 3, 4 ✓
   - `candidate_selector.py` (시그니처 확장) — Task 5 ✓
   - `portfolio_allocator.py` (sigma + capital_krw) — Task 6 ✓
   - `_allocator_state_helpers.py` (신규) — Task 7 ✓
   - `test_allocator_phase1.py` (4 skip enable) — Task 8 ✓
   - `test_allocator_phase2b.py` (신규) — Task 9 ✓

2. **Spec acceptance criteria (a)-(g)** — Task 10 manual + regression_compare ✓

3. **Phase 1 followup** (state mocking + 4 skip enable) — Task 7, 8 ✓

4. **Backward compat** (`select_diverse` 유지, attribution 신규 키만 추가) — 명시 ✓

5. **Bond TIPS 미해결** — spec 의 Out of Scope 명시. plan 에 task 없음 (의도된 design 결정).

## Execution Notes

- 모든 task TDD 흐름 (실패 → 구현 → 통과 → 커밋)
- Task 4 와 Task 5 는 묶어서 (factor_scorer 의 select_cluster_aware 제거 + candidate_selector 의 호출처 교체) 같이 진행 권장 — 둘 사이에 import 의존성
- Task 7 의 schema builder 작성 시 실제 schema 필드 grep 으로 확인 후 채움 (필수 필드 누락 위험)
- Task 8 의 4 tests 중 일부가 fail 시 schema builder 보강 (retro fix)
- Task 10 의 e2e 는 환경 의존 — 실패 시 partial DONE_WITH_CONCERNS 보고
- 모든 commit message `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` trailer 권장
