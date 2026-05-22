# Stage 2 Factor Model Implementation Plan (PR1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stage 2 의 24-cell × playbook framework 를 9-factor continuous decomposition + additive bucket regression 으로 hard cutover. 완전 deterministic (Stage 2 내 LLM 0). macro_news 의 NewsReport structured field 를 Option Z 으로 활용.

**Architecture:** Stage 1 (unchanged) → Stage 2 (factor estimators → factor → bucket regression → mandate projection) → BucketTarget. Sub-graph wrapper 제거 (Issue A 자동 해소). Walk-forward Sharpe optim with theory prior shrinkage 로 calibration.

**Tech Stack:** Python 3.12, pydantic v2, pandas (regression + walk-forward), scipy (optimize), pytest, langgraph.

**Spec:** `docs/superpowers/specs/2026-05-22-stage2-factor-model-design.md`

**Execution Protocol:** Mega-PR 의 `docs/superpowers/plans/2026-05-20-stage2-execution-protocol.md` 8 원칙 그대로 적용 — decisions.md 외부화, regression_log.md, job_status.json.

**Memory policies (필독):**
- `feedback_regression_tests.md`: 모든 코드 수정 시 regression test 의무
- `feedback_long_session_protocol.md`: 8 commit 의 multi-session execution 환각 차단 8 원칙

---

## File Structure

### Created (production)
- `tradingagents/skills/research/factor_baselines.py` — long-run (mean, sd) per factor component
- `tradingagents/skills/research/factor_reliability_audit.py` — 2026-05 reliability audit table
- `tradingagents/skills/research/factor_estimators.py` — 9 deterministic factor estimators
- `tradingagents/skills/research/factor_to_bucket.py` — additive regression + mandate projection
- `tradingagents/skills/research/external_fetchers.py` — KRW/USD + S&P P/E temp fetch
- `tradingagents/skills/research/factor_calibration.py` — calibration utilities (used by script)

### Created (scripts + artifacts)
- `scripts/calibrate_factor_model.py` — walk-forward calibration CLI
- `artifacts/2026-05-22/decisions.md` — design decisions (execution protocol)
- `artifacts/2026-05-22/regression_log.md` — per-commit regression results
- `artifacts/2026-05-22/job_status.json` — background job tracker
- `artifacts/2026-05-22/factor_calibration/coefficient_table.json` — final β + baseline
- `artifacts/2026-05-22/factor_calibration/walk_forward_results.csv`
- `artifacts/2026-05-22/factor_calibration/shrinkage_grid.csv`
- `artifacts/2026-05-22/factor_calibration/sample_window_comparison.csv`
- `artifacts/2026-05-22/factor_calibration/validation_report.md`
- `artifacts/2026-05-15/stage2_diff_factor_model.md` — pre/post diff doc

### Created (tests)
- `tests/unit/skills/research/test_factor_baselines.py`
- `tests/unit/skills/research/test_factor_reliability_audit.py`
- `tests/unit/skills/research/test_factor_estimators_individual.py` (9 factor × ~5 case)
- `tests/unit/skills/research/test_factor_estimators_news_components.py`
- `tests/unit/skills/research/test_factor_estimators_news_fallback.py`
- `tests/unit/skills/research/test_factor_indicator_validity.py`
- `tests/unit/skills/research/test_factor_to_bucket.py`
- `tests/unit/skills/research/test_mandate_projection.py`
- `tests/unit/skills/research/test_external_fetchers.py`
- `tests/unit/agents/test_research_manager_factor_model.py`
- `tests/unit/schemas/test_research_decision_factor_schema.py`
- `tests/integration/test_stage2_factor_model_e2e.py`
- `tests/integration/test_stage2_factor_model_backtest.py`

### Modified
- `tradingagents/schemas/research.py` — ResearchDecision schema 변경 (Section 9.1 spec)
- `tradingagents/agents/managers/research_manager.py` — 전면 rewrite (factor pipeline)
- `tradingagents/graph/trading_graph.py` — sub-graph wrapper 제거 (Issue A fix)
- `tradingagents/skills/portfolio/sub_category.py` — `_LEGACY_SCENARIO_TO_AXES` 의 cell key 의존 부분 정리
- `tradingagents/skills/portfolio/method_picker.py` — interface compat 확인 (변경 없을 가능성)
- `tradingagents/agents/allocator/portfolio_allocator.py` — `dominant_cell.key` fallback path 제거, `dominant_scenario` 만 사용
- `tradingagents/observability/replay.py` — STAGE_PREREQUISITES 의 research_debate prereqs 갱신 (sub-graph 제거 반영)
- `tradingagents/agents/utils/agent_states.py` — `prior_research_decision` 유지, sub-graph 관련 정리
- `tests/unit/skills/test_research_scenario_mapper.py` — **DELETE** (24-cell 의존)
- `tests/unit/skills/test_portfolio_method_picker.py` — overheating test 유지 (dominant_scenario 가 string 이므로 호환)
- `tests/integration/test_stage2_e2e_snapshot.py` — **DELETE** (24-cell e2e — 새 e2e test 로 교체)
- `tests/unit/agents/test_research_manager.py` — **DELETE** (24-cell prompt test — 새 test 로 교체)
- `docs/followup_issues.md` — Issue #12-#19 (Stage 1 backlog) 추가
- `artifacts/2026-05-15/{portfolio.json, philosophy.md, trade_plan.csv}` — regen

### Deleted
- `tradingagents/skills/research/scenario_mapper.py`
- `tradingagents/skills/research/scenario_definitions.py`
- `tradingagents/agents/researchers/debate_state.py`
- `tradingagents/agents/researchers/__init__.py` (only file in dir 이면)
- `tradingagents/graph/debate_subgraph.py`
- `tests/unit/skills/test_research_scenario_mapper.py`
- `tests/integration/test_stage2_e2e_snapshot.py`
- `tests/unit/agents/test_research_manager.py`

---

## Branch Setup

### Task 0.1: 새 작업 branch 생성

- [ ] **Step 1: 현재 상태 확인**

```bash
git status --short
git log --oneline -3
git branch --show-current
```

Expected: 현재 branch `feat/stage2-bottleneck-fixes` (Mega-PR + audit/spec 후), 최근 commit 가 `fc345ca docs(stage2): spec update — Option Z`.

- [ ] **Step 2: 새 branch 생성 (base = 현 branch)**

```bash
git checkout -b feat/stage2-factor-model
```

Expected: `Switched to a new branch 'feat/stage2-factor-model'`.

- [ ] **Step 3: regression baseline 확인 (Mega-PR 의 baseline 과 동일)**

```bash
uv run pytest tests/unit/ -q 2>&1 | tail -3
uv run pytest tests/integration/ -q 2>&1 | tail -3
```

Expected:
- Unit: 3 failed (pre-existing) / 619 passed
- Integration: 18 failed (pre-existing) / 19 passed

기록: 본 PR 의 *baseline* — 이 fail set 이 증가하지 않을 것이 merge 조건 (24-cell test 제거 분 제외).

### Task 0.2: Execution safeguards (Mega-PR protocol 적용)

**Files:**
- Create: `artifacts/2026-05-22/decisions.md`
- Create: `artifacts/2026-05-22/regression_log.md`
- Create: `artifacts/2026-05-22/job_status.json`

- [ ] **Step 1: decisions.md 작성**

```bash
mkdir -p artifacts/2026-05-22
```

`artifacts/2026-05-22/decisions.md`:

```markdown
# Stage 2 Factor Model PR1 Decisions

> Brainstorming 의 결정 + 후속 조건부 결정 기록.

| # | 항목 | 결정 | 근거 | 시각 | commit |
|---|---|---|---|---|---|
| D1 | Scope | Stage 2 내부만, Stage 1 gap 별도 PR | brainstorming Q1 | 2026-05-22 | spec |
| D2 | Calibration | Hybrid (theory prior + walk-forward Sharpe optim with shrinkage) | brainstorming Q2 | 2026-05-22 | spec |
| D3 | LLM in Stage 2 | None (deterministic only) — LLM critic 은 future | brainstorming clarification | 2026-05-22 | spec |
| D4 | Migration | Hard cutover (24-cell 완전 제거) | brainstorming Q4 | 2026-05-22 | spec |
| D5 | Acceptance | OOS Sharpe > 현 framework + 0.05 AND ≥ 60/40 | brainstorming Q5 | 2026-05-22 | spec |
| D6 | macro_news 활용 | Option Z — NewsReport structured field deterministic | brainstorming clarification | 2026-05-22 | spec (fc345ca) |
| D7 | Shrinkage λ | _pending_ | calibration grid search 결과 후 | — | — |
| D8 | Sample window | _pending_ | 1991-2024 vs 2010-2024 vs 2020-2024 비교 후 | — | — |
| D9 | yfinance KRW/USD vs Stage 1 fix | external_fetcher (PR1) + Stage 1 PR (Issue #12 backlog) | Gap E workaround | 2026-05-22 | spec |
```

- [ ] **Step 2: regression_log.md baseline 기록**

```bash
uv run pytest tests/unit/ -q 2>&1 | tail -3 > /tmp/baseline_unit.txt
uv run pytest tests/integration/ -q 2>&1 | tail -3 > /tmp/baseline_int.txt
cat /tmp/baseline_unit.txt
cat /tmp/baseline_int.txt
```

`artifacts/2026-05-22/regression_log.md`:

```markdown
# Stage 2 Factor Model PR1 Regression Log

> 각 commit 직후 회귀 결과. baseline 대비 0 *new* regression (pre-existing fail 제외) merge 조건.
> 24-cell 관련 test (`test_research_scenario_mapper.py`, `test_stage2_e2e_snapshot.py`,
> `test_research_manager.py`) 의 *제거* 는 *regression 아님* — factor model test 로 대체.

## Pre-existing failures (factor model 작업과 무관)

### Unit (3)
- tests/unit/agents/test_macro_quant_analyst.py::test_macro_analyst_orchestration
- tests/unit/agents/test_technical_analyst.py::test_technical_analyst_returns_report
- tests/unit/monitor/test_monitor.py::test_turnover_initial_below_floor

### Integration (18)
- tests/integration/test_eval_systemic_score.py (8 cases)
- tests/integration/test_plan_pipeline_mock.py::test_plan_pipeline_produces_artifacts
- 그 외 9 — Stage 1 systemic_score eval (별도 PR cycle)

## Post-C0 baseline (pre-changes)

### Unit
$ uv run pytest tests/unit/ -q 2>&1 | tail -3
<output>

### Integration
$ uv run pytest tests/integration/ -q 2>&1 | tail -3
<output>

## Post-C1
(C1 commit 직후 갱신)

## Post-C2
...

## Post-C3 ... Post-C8
```

Output 의 *raw 마지막 3 줄* 을 `<output>` 자리에 paste.

- [ ] **Step 3: job_status.json 생성**

`artifacts/2026-05-22/job_status.json`:

```json
{
  "comment": "Background process tracker. 결과 인용 전 ls + tail 검증.",
  "jobs": {}
}
```

- [ ] **Step 4: C0 commit (execution safeguards)**

```bash
git add artifacts/2026-05-22/
git commit -m "$(cat <<'EOF'
chore(stage2): factor model PR1 execution safeguards

artifacts/2026-05-22/:
- decisions.md: brainstorming의 D1-D9 결정 외부화
- regression_log.md: pre-existing baseline 명시 + 각 commit 후 갱신
- job_status.json: background process tracker

C1-C8 모든 task가 본 artifacts 참조 의무.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Commit C1: Issue A fix + ResearchDecision schema

> **Why:** 모든 후속 작업이 *AgentState 의 macro_report/risk_report/news_report 직접 접근* 가능해야. Sub-graph wrapper 제거 + schema 새 field (factor_scores) 추가. 이 commit 후에도 *모든 기존 test 작동* (24-cell 코드 그대로 — schema 만 확장).

### Task C1.1: research_manager 의 sub-graph wrapper 폐기

**Files:**
- Modify: `tradingagents/graph/trading_graph.py:92-109`
- Delete: `tradingagents/graph/debate_subgraph.py`
- Delete: `tradingagents/agents/researchers/debate_state.py`

- [ ] **Step 1: 영향 받는 imports 확인**

```bash
grep -rn "from tradingagents.graph.debate_subgraph\|from tradingagents.agents.researchers" --include="*.py" 2>&1 | head -10
grep -rn "InvestDebateState\|build_invest_debate_subgraph" --include="*.py" 2>&1 | head -10
```

Expected: trading_graph.py 와 일부 test 에서 import.

- [ ] **Step 2: trading_graph.py 수정 — research_debate_node 단순화**

`tradingagents/graph/trading_graph.py` 의 `research_debate_node` 정의 (line 92-109 근처) 전체 제거. `research_estimator` (line 81) 를 *직접* archive_wrap.

기존 코드 검색:
```python
def research_debate_node(state):
    sub_input = InvestDebateState(
        messages=[],
        macro_summary=state.get("macro_summary", ""),
        risk_summary=state.get("risk_summary", ""),
        technical_summary=state.get("technical_summary", ""),
        news_summary=state.get("news_summary", ""),
        bucket_target=None,
        research_decision=None,
        research_debate_summary="",
    )
    sub_result = invest_subgraph.invoke(sub_input)
    return {
        "research_debate_summary": sub_result.get("research_debate_summary", ""),
        "bucket_target": sub_result.get("bucket_target"),
        "research_decision": sub_result.get("research_decision"),
    }
```

다음으로 교체:
```python
# Stage 2 research_manager — single-node (sub-graph wrapper 제거, Issue A fix).
# AgentState 직접 접근 → macro_report / risk_report / news_report / prior_research_decision 모두 가용.
research_debate_node = research_estimator  # plain node
```

이전 `build_invest_debate_subgraph` 호출 (line 82 근처) + `invest_subgraph` 변수도 제거.

`InvestDebateState` import 제거.

- [ ] **Step 3: debate_subgraph.py 삭제**

```bash
rm tradingagents/graph/debate_subgraph.py
```

- [ ] **Step 4: debate_state.py + 빈 디렉토리 정리**

```bash
rm tradingagents/agents/researchers/debate_state.py
# __init__.py 가 그것만 import 했다면:
cat tradingagents/agents/researchers/__init__.py
# 결과에 따라:
# - 다른 import 있으면 InvestDebateState 줄만 제거
# - 빈 파일 되면: rm tradingagents/agents/researchers/__init__.py; rmdir tradingagents/agents/researchers
```

- [ ] **Step 5: replay.py 의 prereqs 갱신**

`tradingagents/observability/replay.py` 의 `STAGE_PREREQUISITES["research_debate"]` 에 `news_report` 추가:

```python
"research_debate": [
    "macro_summary", "risk_summary",
    "technical_summary", "news_summary",
    "macro_report", "risk_report", "news_report",  # ← news_report 신규
    "technical_report",                              # ← technical_report 도 (factor F9 의 sector_dispersion/breadth)
    # prior_research_decision 는 Optional — restore 못 해도 OK
],
```

SCHEMA_MAP 에 NewsReport 가 이미 있는지 확인 (Mega-PR C5 에서 추가됨):
```bash
grep -n "NewsReport" tradingagents/observability/replay.py
```

없으면 추가:
```python
from tradingagents.schemas.reports import (
    MacroReport, NewsReport, RiskReport, TechnicalReport,
)
# SCHEMA_MAP 의 dict 에:
"news_report": NewsReport,
```

- [ ] **Step 6: 영향 받는 test 의 import 정리**

```bash
grep -rn "InvestDebateState\|debate_subgraph" tests/ 2>&1
```

발견 시 해당 import 제거 또는 test 자체 정리 (test 의 의미 가 sub-graph 라 의미 잃음 → 삭제).

- [ ] **Step 7: 기존 test 전체 실행 — 회귀 확인**

```bash
uv run pytest tests/unit/ -q 2>&1 | tail -3
```

Expected: 3 failed (pre-existing) / 619 passed (또는 sub-graph 의존 test 가 있어 *추가 fail* — 그건 정상, 해당 test 가 *제거 대상*).

failed 가 sub-graph 의존이면 그 test 의 운명 결정 후:
- 24-cell 의존이면 → C5 에서 삭제 예정 (해당 단계로 미루기, 본 step 에서는 skip).
- 그 외 (예: graph 빌드 test) 면 → 본 step 에서 fix.

- [ ] **Step 8: integration test 회귀**

```bash
uv run pytest tests/integration/ -q 2>&1 | tail -3
```

Expected: 18 failed (pre-existing) / 19 passed.

### Task C1.2: ResearchDecision schema 확장 (factor field 추가, 기존 field 유지)

> 본 task 는 *non-destructive* — 새 field 만 추가. 기존 24-cell field 는 *그대로* 유지하여 C2-C4 에서 *factor pipeline build 중에도* 기존 framework 가 작동.

**Files:**
- Modify: `tradingagents/schemas/research.py`

- [ ] **Step 1: 새 schema field 추가 — failing test 먼저**

`tests/unit/schemas/test_research_decision_factor_schema.py` 신설:

```python
"""ResearchDecision schema 의 factor model field 검증."""
import pytest
from tradingagents.schemas.research import (
    ResearchDecision, ScenarioProbabilities24, CellCoord, ALL_CELLS,
)
from tradingagents.schemas.portfolio import BucketTarget


def _minimal_research_decision_24cell(**override):
    """기존 24-cell schema 기반 ResearchDecision (factor field 없이도 valid)."""
    kwargs = {k: 0.0 for k in ALL_CELLS}
    kwargs["B_N_F"] = 1.0
    probs = ScenarioProbabilities24(**kwargs, reasoning="t")
    base = dict(
        bucket_target=BucketTarget(
            kr_equity=0.1, global_equity=0.2, fx_commodity=0.3,
            bond=0.3, cash_mmf=0.1, rationale="t", bond_tips_share=0.5,
        ),
        scenario_probabilities=probs,
        dominant_cell=CellCoord(cycle="B", tail="N", kr="F"),
        dominant_cell_probability=1.0,
        dominant_cycle="B",
        dominant_cycle_probability=1.0,
        cycle_marginals={"A": 0.0, "B": 1.0, "C": 0.0, "D": 0.0},
        tail_marginals={"N": 1.0, "T": 0.0},
        kr_marginals={"F": 1.0, "boom": 0.0, "stress": 0.0},
        conviction="high",
        conviction_beta=1.0,
        effective_cycle_marginals={"A": 0.0, "B": 1.0, "C": 0.0, "D": 0.0},
    )
    base.update(override)
    return ResearchDecision(**base)


def test_factor_scores_field_accepts_9_factor_dict():
    """factor_scores: dict[str, float] 신규 field — 9 factor."""
    d = _minimal_research_decision_24cell(
        factor_scores={
            "F1_growth": 0.5, "F2_inflation": -0.3, "F3_real_rate": 0.1,
            "F4_term_premium": 0.0, "F5_credit_cycle": -0.2,
            "F6_krw_regime": 0.4, "F7_equity_vol_regime": 0.0,
            "F8_valuation": -0.5, "F9_liquidity_regime": 0.2,
        }
    )
    assert d.factor_scores["F1_growth"] == 0.5
    assert len(d.factor_scores) == 9


def test_factor_contributions_field_accepts_attribution():
    """factor_contributions: dict[str, dict[str, float]] — factor → bucket contribution."""
    d = _minimal_research_decision_24cell(
        factor_contributions={
            "F1_growth": {"kr_equity": 0.01, "global_equity": 0.02,
                          "fx_commodity": 0.0, "bond": -0.02, "cash_mmf": -0.01},
            # ...
        }
    )
    assert d.factor_contributions["F1_growth"]["global_equity"] == 0.02


def test_baseline_bucket_field_accepts_dict():
    """baseline_bucket: dict[str, float] — used baseline (attribution)."""
    d = _minimal_research_decision_24cell(
        baseline_bucket={"kr_equity": 0.12, "global_equity": 0.20,
                         "fx_commodity": 0.15, "bond": 0.33, "cash_mmf": 0.20}
    )
    assert d.baseline_bucket["bond"] == 0.33


def test_factor_field_defaults_empty():
    """factor_scores / factor_contributions / baseline_bucket 가 default 빈 dict — backward-compat."""
    d = _minimal_research_decision_24cell()  # no factor override
    assert d.factor_scores == {}
    assert d.factor_contributions == {}
    assert d.baseline_bucket == {}
```

- [ ] **Step 2: test 실행 — 실패 확인**

```bash
uv run pytest tests/unit/schemas/test_research_decision_factor_schema.py -v 2>&1 | tail -10
```

Expected: FAIL — `factor_scores`, `factor_contributions`, `baseline_bucket` field 미존재.

- [ ] **Step 3: ResearchDecision schema 확장**

`tradingagents/schemas/research.py` 의 `ResearchDecision` class 의 마지막 field (`effective_cycle_marginals`) 다음에 추가:

```python
    # === Factor model fields (Stage 2 factor model, PR 2026-05-22) ===
    # PR1: factor model 와 24-cell 가 *공존*. C5 에서 24-cell field 제거.
    # 본 field 는 *defaults empty* — backward-compat.
    factor_scores: dict[str, float] = Field(
        default_factory=dict,
        description="9 factor (F1-F9) 의 z-score. {factor_name: z}",
    )
    factor_contributions: dict[str, dict[str, float]] = Field(
        default_factory=dict,
        description="Factor → bucket contribution (attribution). "
                    "{factor_name: {bucket_name: pp_contribution}}",
    )
    baseline_bucket: dict[str, float] = Field(
        default_factory=dict,
        description="Calibration 의 baseline bucket weight. attribution 용.",
    )
```

- [ ] **Step 4: test 통과 확인**

```bash
uv run pytest tests/unit/schemas/test_research_decision_factor_schema.py -v 2>&1 | tail -10
```

Expected: 4 PASS.

- [ ] **Step 5: 전체 unit 회귀**

```bash
uv run pytest tests/unit/ -q 2>&1 | tail -3
```

Expected: 3 failed (pre-existing) / 623 passed (+4 new).

### Task C1.3: portfolio_allocator 의 dominant_cell.key fallback 제거

> 본 PR 의 Section 9.4: allocator 가 *항상* `dominant_scenario` (string) 만 사용하도록.

**Files:**
- Modify: `tradingagents/agents/allocator/portfolio_allocator.py:77-85`

- [ ] **Step 1: 현 코드 확인**

```bash
grep -n "dominant_cell\|dominant_scenario" tradingagents/agents/allocator/portfolio_allocator.py
```

- [ ] **Step 2: dominant_cell.key 의존 path 제거**

`tradingagents/agents/allocator/portfolio_allocator.py` 의 line 77-85 근처:

Before:
```python
# 24-cell framework: dominant_cell.key (e.g. "A_N_F") 우선 사용 — log_boost가
# cell-axis 좌표 직접 받아 3축 boost 합성. 없으면 legacy dominant_scenario.
dominant_scenario = None
if research_decision is not None:
    cell = getattr(research_decision, "dominant_cell", None)
    if cell is not None:
        dominant_scenario = cell.key  # "A_N_F" 같은 cell key
    else:
        dominant_scenario = getattr(research_decision, "dominant_scenario", None)
```

After:
```python
# Factor model PR (2026-05-22): dominant_cell 제거. 항상 legacy scenario name string 사용.
# log_boost 가 cell key 받던 path 도 해당 path 제거됨 (sub_category.py).
dominant_scenario = None
if research_decision is not None:
    dominant_scenario = getattr(research_decision, "dominant_scenario", None)
```

- [ ] **Step 3: 회귀**

```bash
uv run pytest tests/unit/agents/ -q 2>&1 | tail -3
```

Expected: 3 failed (pre-existing) / 변동 없음 또는 1-2 fail (test 가 dominant_cell.key 검증 시).

발견되는 fail 이 dominant_cell.key 의존이면 해당 test 도 조정 (cell.key 대신 scenario string).

### Task C1.4: sub_category.py 의 cell key 의존 정리

**Files:**
- Modify: `tradingagents/skills/portfolio/sub_category.py`

- [ ] **Step 1: 현 코드 확인**

```bash
grep -n "cell_key\|_LEGACY_SCENARIO_TO_AXES\|parts\[0\].*parts\[1\]" tradingagents/skills/portfolio/sub_category.py
```

- [ ] **Step 2: `_scenario_to_axes` 의 cell-key path 제거**

`tradingagents/skills/portfolio/sub_category.py:194-204` 근처:

Before:
```python
def _scenario_to_axes(scenario: str) -> tuple[str, str, str] | None:
    """legacy name이나 cell key를 (cycle, tail, kr) tuple로. 못 풀면 None."""
    if scenario in _LEGACY_SCENARIO_TO_AXES:
        return _LEGACY_SCENARIO_TO_AXES[scenario]
    parts = scenario.split("_")
    if len(parts) == 3 and parts[0] in ("A", "B", "C", "D") \
            and parts[1] in ("N", "T") and parts[2] in ("F", "boom", "stress"):
        return (parts[0], parts[1], parts[2])
    return None
```

After:
```python
def _scenario_to_axes(scenario: str) -> tuple[str, str, str] | None:
    """legacy scenario name 을 (cycle, tail, kr) axis tuple 로.
    Factor model PR (2026-05-22): cell key path 제거. dominant_scenario 가 항상 legacy name string.
    """
    return _LEGACY_SCENARIO_TO_AXES.get(scenario)
```

- [ ] **Step 3: 회귀**

```bash
uv run pytest tests/unit/skills/test_portfolio_method_picker.py -v 2>&1 | tail -5
```

Expected: 모두 pass (method_picker test 는 string scenario 만 사용).

### Task C1.5: C1 commit

- [ ] **Step 1: 변경 파일 확인**

```bash
git status --short
```

Expected:
- M `tradingagents/graph/trading_graph.py`
- D `tradingagents/graph/debate_subgraph.py`
- D `tradingagents/agents/researchers/debate_state.py`
- M `tradingagents/observability/replay.py`
- M `tradingagents/schemas/research.py`
- M `tradingagents/agents/allocator/portfolio_allocator.py`
- M `tradingagents/skills/portfolio/sub_category.py`
- A `tests/unit/schemas/test_research_decision_factor_schema.py`

- [ ] **Step 2: regression_log.md 갱신 (Post-C1)**

```bash
uv run pytest tests/unit/ -q 2>&1 | tail -3
uv run pytest tests/integration/ -q 2>&1 | tail -3
```

Output 을 `artifacts/2026-05-22/regression_log.md` 의 `## Post-C1` 자리에 paste.

- [ ] **Step 3: commit**

```bash
git add tradingagents/graph/trading_graph.py \
        tradingagents/observability/replay.py \
        tradingagents/schemas/research.py \
        tradingagents/agents/allocator/portfolio_allocator.py \
        tradingagents/skills/portfolio/sub_category.py \
        tests/unit/schemas/test_research_decision_factor_schema.py \
        artifacts/2026-05-22/regression_log.md
git rm tradingagents/graph/debate_subgraph.py \
       tradingagents/agents/researchers/debate_state.py

git commit -m "$(cat <<'EOF'
feat(stage2): Issue A fix + ResearchDecision schema 확장 (C1)

Sub-graph wrapper 폐기 — Issue A (D2/D3 signal cleaning silent bug) 자동 해소.
AgentState 의 macro_report/risk_report/news_report 가 research_manager 의 state 로 직접 접근.

변경:
- trading_graph.py: research_debate_node wrapper 제거, research_estimator 직접 wire
- debate_subgraph.py: 삭제
- agents/researchers/debate_state.py: 삭제
- replay.py: STAGE_PREREQUISITES["research_debate"] 에 news_report + technical_report 추가
- research.py: ResearchDecision 에 factor_scores/factor_contributions/baseline_bucket 추가
  (defaults empty — 24-cell 와 공존, C5 에서 24-cell field 제거)
- portfolio_allocator.py: dominant_cell.key fallback path 제거 — scenario string only
- sub_category.py: _scenario_to_axes 의 cell-key path 제거

Test:
- test_research_decision_factor_schema.py 신설 (4 test)
- 기존 test 모두 pass (24-cell 코드 그대로 — C5 에서 제거)

Regression (artifacts/2026-05-22/regression_log.md):
- Unit: 3 failed (pre-existing) / 623 passed (+4)
- Integration: 18 failed (pre-existing) / 19 passed (unchanged)
- Δ baseline: 0 new regression

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

> 본 plan 의 *Task C2 ~ C8* 은 별도 문서 section 으로 이어집니다. 본 파일이 너무 길어지지 않게 하기 위해 *Part 2* 로 분리 권장하나, single file 작성 시 *동일 형식 으로 이어 작성*.
>
> **다음 commit 들의 *outline*** (자세한 step 은 본 plan 의 *append* 또는 별도 part):
>
> **C2 (Factor estimators)** ~30시간:
> - Task C2.1: factor_baselines.py 신설 (long-run mean/sd table)
> - Task C2.2: factor_reliability_audit.py 신설 (2026-05 audit table)
> - Task C2.3: external_fetchers.py 신설 (KRW/USD + S&P P/E temp fetch)
> - Task C2.4 ~ C2.12: F1 ~ F9 각 factor estimator (TDD per factor)
> - Task C2.13: factor_estimators.py 의 통합 `compute_all_factors()` + smoke test
> - Task C2.14: News component test + fallback test (Option Z 핵심 검증)
> - Task C2.15: indicator validity test (audit table 강제)
> - Task C2.16: C2 commit
>
> **C3 (Factor → bucket mapping)** ~15시간:
> - Task C3.1: factor_to_bucket.py 신설 — INITIAL_BASELINE + INITIAL_BETA + SIGN_RESTRICTION
> - Task C3.2: additive regression `apply_factor_model()`
> - Task C3.3: bond_tips_share scalar regression
> - Task C3.4: mandate projection
> - Task C3.5: unit test (factor → bucket, mandate enforcement)
> - Task C3.6: C3 commit
>
> **C4 (research_manager wire-up)** ~15시간:
> - Task C4.1: research_manager.py 전면 rewrite (factor pipeline)
> - Task C4.2: EMA infrastructure factor space 재구현
> - Task C4.3: dominant_scenario + conviction 재정의 (deterministic)
> - Task C4.4: summary text 생성
> - Task C4.5: unit test (e2e node)
> - Task C4.6: integration test (mock state → ResearchDecision)
> - Task C4.7: 기존 test 충돌 정리
> - Task C4.8: C4 commit
>
> **C5 (24-cell framework 제거)** ~10시간:
> - Task C5.1: scenario_mapper.py + scenario_definitions.py 삭제
> - Task C5.2: ResearchDecision 의 24-cell field 제거 (factor_scores 만 남김)
> - Task C5.3: ScenarioProbabilities24, CellCoord 등 schema 제거
> - Task C5.4: sub_category.py 의 _LEGACY_SCENARIO_TO_AXES 정리
> - Task C5.5: 24-cell test 파일 삭제 (test_research_scenario_mapper, test_stage2_e2e_snapshot, test_research_manager)
> - Task C5.6: 전체 회귀 — *진짜* 깨끗한 상태 확인
> - Task C5.7: C5 commit
>
> **C6 (Walk-forward calibration)** ~30시간:
> - Task C6.1: scripts/calibrate_factor_model.py 신설
> - Task C6.2: 1991-2024 quarterly historical data 준비 (재사용 + 추가 fetch)
> - Task C6.3: Hybrid calibration loop (shrinkage grid + sample window grid)
> - Task C6.4: Validation report 생성 (acceptance criteria 검증)
> - Task C6.5: artifacts/2026-05-22/factor_calibration/ 저장
> - Task C6.6: INITIAL_BETA 를 calibrated β 로 update
> - Task C6.7: C6 commit
>
> **C7 (2026-05-15 산출물 재생성)** ~6시간:
> - Task C7.1: backup pre-C7 산출물 (/tmp 또는 git diff 비교용)
> - Task C7.2: Stage 2 → 6 sequential replay (replay_stage.py 활용)
> - Task C7.3: artifacts/2026-05-15/ 의 portfolio.json + philosophy.md + trade_plan.csv 갱신
> - Task C7.4: stage2_diff_factor_model.md 작성
> - Task C7.5: D6 (philosophy.md narrative) 결정 + decisions.md 갱신
> - Task C7.6: mandate validation pass 확인
> - Task C7.7: C7 commit
>
> **C8 (Documentation + Stage 1 backlog)** ~3시간:
> - Task C8.1: docs/followup_issues.md 에 Issue #12-#19 추가 (Stage 1 backlog Gap A-H + 임시 fetch migrate)
> - Task C8.2: docs/superpowers/specs/2026-05-22-stage2-pipeline-audit.md status update (A/B/C/H/L/M resolved)
> - Task C8.3: artifacts/2026-05-20/decisions.md (Mega-PR) 의 후속 link 추가
> - Task C8.4: C8 commit

---

---

## Commit C2: Factor Estimators (9 factor + baseline + audit + fetchers)

> **Why:** Stage 2 의 *deterministic compute layer*. 9 factor 각 (struct + news + (필요시) external fetch) → z-score. 본 commit 후에도 *24-cell 와 공존* — research_manager 가 아직 호출 안 함.

### Task C2.1: factor_baselines.py 신설

**Files:** Create `tradingagents/skills/research/factor_baselines.py`

- [ ] **Step 1: 모듈 + LONG_RUN_BASELINE table**

핵심 (mean, sd) per (factor, component). spec section 4.4 참조. 예:
```python
LONG_RUN_BASELINE: Final[dict[tuple[str, str], tuple[float, float]]] = {
    ("F1_growth", "gdpnow"):              (2.0, 2.0),
    ("F1_growth", "cfnai"):               (0.0, 0.5),
    # ... 50+ entries for 9 factors x ~5-7 components each (spec § 4.4)
}

def z_score(value, factor, component) -> float | None:
    base = LONG_RUN_BASELINE.get((factor, component))
    if base is None: return None
    mean, sd = base
    if sd <= 0: return None
    return (value - mean) / sd
```

- [ ] **Step 2: unit test** (`tests/unit/skills/research/test_factor_baselines.py`):
  - All 9 factor names present
  - z_score basic calculation
  - Missing baseline → None
  - sd ≤ 0 → None

- [ ] **Step 3**: `uv run pytest tests/unit/skills/research/test_factor_baselines.py -v` → 4 PASS.

### Task C2.2: factor_reliability_audit.py 신설

**Files:** Create `tradingagents/skills/research/factor_reliability_audit.py`

- [ ] **Step 1: AUDIT_DATE + COMPONENT_RELIABILITY + WEIGHT_CAP_BY_RELIABILITY**

```python
AUDIT_DATE: Final[str] = "2026-05-22"

COMPONENT_RELIABILITY: Final[dict[str, str]] = {
    "gdpnow": "high", "cfnai": "high",
    "sahm": "medium-low",    # post-COVID 왜곡
    "curve": "medium",       # post-COVID de-anchored
    "skew_level": "medium-low",  # post-2018 elevated
    # ... 모든 component (factor_estimators 가 사용)
}

WEIGHT_CAP_BY_RELIABILITY: Final[dict[str, float]] = {
    "high": 0.40, "medium-high": 0.30, "medium": 0.20,
    "medium-low": 0.10, "low": 0.05, "uncertain": 0.0,
}

def get_reliability(component: str) -> str:
    return COMPONENT_RELIABILITY.get(component, "low")  # 보수적

def get_weight_cap(component: str) -> float:
    return WEIGHT_CAP_BY_RELIABILITY[get_reliability(component)]
```

- [ ] **Step 2: indicator validity test** (`tests/unit/skills/research/test_factor_indicator_validity.py`):

```python
def test_audit_date_is_current():
    """6m 초과 시 fail → 재검증 강제."""
    from datetime import date
    audit = date.fromisoformat(AUDIT_DATE)
    days_since = (date.today() - audit).days
    assert days_since <= 180

def test_all_components_have_reliability():
    EXPECTED = {"gdpnow", "cfnai", "nfci", "sahm", "curve",
                "release_surprise", ...}  # full list spec § 4.3
    missing = EXPECTED - set(COMPONENT_RELIABILITY.keys())
    assert not missing

def test_weight_cap_monotone():
    tiers = ["high", "medium-high", "medium", "medium-low", "low"]
    caps = [WEIGHT_CAP_BY_RELIABILITY[t] for t in tiers]
    assert caps == sorted(caps, reverse=True)

def test_low_reliability_capped():
    assert WEIGHT_CAP_BY_RELIABILITY["medium-low"] <= 0.15
```

- [ ] **Step 3**: PASS.

### Task C2.3: external_fetchers.py (KRW/USD + S&P P/E 임시)

**Files:** Create `tradingagents/skills/research/external_fetchers.py` + test.

- [ ] **Step 1: 작성** — yfinance `KRW=X` + `SPY` .info["trailingPE"]. `lru_cache(maxsize=8)`. Exception → None. logger.warning.

- [ ] **Step 2: test (mock yfinance)** — success, empty, exception, missing key. 5 case.

- [ ] **Step 3**: PASS.

### Task C2.4: factor_estimators.py — 공통 schema + `_aggregate`

**Files:** Create `tradingagents/skills/research/factor_estimators.py` (initial)

- [ ] **Step 1: FactorScore/FactorScores dataclass + `_aggregate()` + `_safe_get()` + enum maps (_BIAS_MAP, _RISK_REGIME_MAP)**

핵심 `_aggregate(factor_name, components_raw, weights)`:
1. None component skip.
2. z_score lookup (None 이면 skip).
3. Reliability cap 적용 (`min(weight, get_weight_cap(name))`).
4. Renormalize weights over remaining.
5. Weighted average.
6. Cap to [-3, +3].
7. Return FactorScore with components + audit trail.

- [ ] **Step 2: smoke test** (`tests/unit/skills/research/test_factor_estimators_individual.py` 첫 4 case):
  - All components → expected z
  - None component skipped, renormalize
  - All None → z=0 + interpretation="no data"
  - z=+5 → capped to +3

- [ ] **Step 3**: PASS.

### Task C2.5: F1 growth_surprise estimator

- [ ] **Step 1: failing test** — `_mock_stage1_growth()` helper + 5 case (baseline, strong growth, recession, news_unavailable, news_release_surprise contributes).

- [ ] **Step 2: `compute_growth_surprise(stage1)` 구현**

components:
- macro_report: gdpnow, cfnai, nfci (inverted), sahm_z, slope_2_10y_bps
- news_report.release_surprise: surprise_index_30d, bias_30d (via `_BIAS_MAP`)
- news_report.news_sentiment.avg_sentiment["macro"]
- news_report.global_overnight.risk_regime_overnight (via `_RISK_REGIME_MAP`)

weights (spec § 3.2 F1):
```python
weights = {
    "gdpnow": 0.20, "cfnai": 0.15, "nfci": 0.12,
    "sahm": 0.08, "curve": 0.12,
    "release_surprise": 0.18, "hawkish_bias": 0.05,
    "macro_sent": 0.05, "risk_regime_overnight": 0.05,
}
```

`_aggregate("F1_growth", components_raw, weights)` 호출.

- [ ] **Step 3**: 5 PASS.

### Task C2.6: F2 inflation_surprise

- [ ] **Step 1: failing test** (5 case).
- [ ] **Step 2: 구현**

components: cpi_yoy, cpi_3m, core_pce, five_y_five_y, michigan_1y, real_yield_inv (negated), fed_path_bps, release_hawkish (via `_BIAS_MAP`), macro_sent.
weights (spec § 3.2 F2): 0.18/0.18/0.13/0.13/0.08/0.08/0.08/0.07/0.07.

- [ ] **Step 3**: PASS.

### Task C2.7: F3 real_rate

- [ ] **Step 1: failing test** (4 case).
- [ ] **Step 2: 구현**

components: tips_yield (0.55), fed_voting_balance (0.35), fed_path_implied (0.10).

- [ ] **Step 3**: PASS.

### Task C2.8: F4 term_premium

- [ ] **Step 1: failing test**.
- [ ] **Step 2: 구현**

components: slope_2_10y (0.30), slope_5_30y (0.25), fed_tone_balance (0.30), fed_voting_balance (0.15).

- [ ] **Step 3**: PASS.

### Task C2.9: F5 credit_cycle

- [ ] **Step 1: failing test**.
- [ ] **Step 2: 구현**

components: hy_oas_bps, hy_oas_momentum (z 그대로), credit_quality_bps, funding_bps, corporate_distress (derived: `max(0, count_change) × max(0, -sent)`), dovish_bias (via `_BIAS_MAP` 반전).
weights: 0.30/0.25/0.15/0.10/0.15/0.05.

- [ ] **Step 3**: PASS.

### Task C2.10: F6 krw_regime (external_fetcher 사용)

- [ ] **Step 1: failing test** (yfinance mock).
- [ ] **Step 2: 구현**

components:
- news_report.global_overnight.krw.change_pct (0.20)
- `fetch_krw_usd_level()` (0.20) — external fetch
- kr_us_rate_diff (0.15), foreign_flow_z (0.20), kr_exports_yoy (0.10)
- bok_tone_balance (0.15)

- [ ] **Step 3**: PASS.

### Task C2.11: F7 equity_vol_regime

- [ ] **Step 1: failing test**.
- [ ] **Step 2: 구현**

components: vix_level, vix_z_score, vix_term_ratio, move, realized_vol_60d, skew_change (NOT level), sentiment_dispersion, geopolitical_surge (`max(0, count_change["geopolitical"])`).
weights: 0.22/0.12/0.12/0.18/0.13/0.08/0.08/0.07.

- [ ] **Step 3**: PASS.

### Task C2.12: F8 valuation (external_fetcher)

- [ ] **Step 1: failing test** (yfinance mock).
- [ ] **Step 2: 구현**

components: sp_pe (fetch), earnings_yield (derived 1/PE), erp (EY − tips_yield), kospi_pbr (if available).
weights: 0.20/0.30/0.30/0.20.

Sign caveat: sp_pe baseline (18, 6) → high PE = positive z = "expensive". β calibration 이 negative 로 fit 되도록 (β[F8, equity] < 0).

- [ ] **Step 3**: PASS.

### Task C2.13: F9 liquidity_regime

- [ ] **Step 1: failing test**.
- [ ] **Step 2: 구현**

components:
- vrp: `(vix/100)² − realized_vol²` × 10000 (bps²-like normalization)
- eq_bond_corr, sector_dispersion, breadth
- event_cluster: `release_surprise.high_importance_today` (int → float)
- rising_signal: `1.0 if rising_category is not None else 0.0`

weights: 0.35/0.18/0.18/0.08/0.12/0.09.

- [ ] **Step 3**: PASS.

### Task C2.14: `compute_all_factors()` 통합 + news fallback test

- [ ] **Step 1: 통합 함수**

```python
def compute_all_factors(stage1) -> FactorScores:
    return FactorScores(
        growth_surprise=compute_growth_surprise(stage1),
        inflation_surprise=compute_inflation_surprise(stage1),
        # ... 9 factor 모두
    )
```

- [ ] **Step 2: news fallback test** (`test_factor_estimators_news_fallback.py`):
  - `news_report = None` → quant 만 사용, confidence < 1.0
  - tier-1 (global_overnight) only None
  - 모든 news tier None
  - `compute_all_factors()` → 9-key dict 반환

- [ ] **Step 3: news component test** (`test_factor_estimators_news_components.py`):
  - F1: release_surprise +2 → z 증가
  - F3: fed_voting -1 → z 감소
  - F4: fed_tone +1 → z 증가
  - 등 핵심 news contribution 검증

- [ ] **Step 4**: 전체 PASS.

### Task C2.15: C2 commit

- [ ] **Step 1**: `git status --short` 확인.
- [ ] **Step 2**: regression_log.md `Post-C2` 채움.
- [ ] **Step 3**: commit (`feat(stage2): 9 deterministic factor estimators (C2)`).

---

## Commit C3: Factor → Bucket Mapping

> **Why:** factor z 9-vector → 5-bucket weight. Additive regression + sign restriction + mandate projection.

### Task C3.1: factor_to_bucket.py — INITIAL_BASELINE + INITIAL_BETA + SIGN_RESTRICTION

**Files:** Create `tradingagents/skills/research/factor_to_bucket.py`

- [ ] **Step 1: 상수 정의**

```python
from typing import Final, Literal

BUCKETS: Final[tuple[str, ...]] = (
    "kr_equity", "global_equity", "fx_commodity", "bond", "cash_mmf"
)
FACTORS: Final[tuple[str, ...]] = (
    "F1_growth", "F2_inflation", "F3_real_rate", "F4_term_premium",
    "F5_credit_cycle", "F6_krw_regime", "F7_equity_vol_regime",
    "F8_valuation", "F9_liquidity_regime",
)

INITIAL_BASELINE: Final[dict[str, float]] = {
    "kr_equity":     0.12,
    "global_equity": 0.20,
    "fx_commodity":  0.15,
    "bond":          0.33,
    "cash_mmf":      0.20,
}
# Σ = 1.0, 위험자산 = 0.47 (mandate 0.70 의 67%)

# Each factor row's β sums to 0 across buckets (adjustment preserves total)
# Spec section 5.4 hand-coded prior
INITIAL_BETA: Final[dict[tuple[str, str], float]] = {
    # F1 growth (+z = growth → +equity, -bond)
    ("F1_growth", "kr_equity"):     +0.04,
    ("F1_growth", "global_equity"): +0.06,
    ("F1_growth", "fx_commodity"):  +0.01,
    ("F1_growth", "bond"):          -0.08,
    ("F1_growth", "cash_mmf"):      -0.03,

    # F2 inflation (+z = inflation)
    ("F2_inflation", "kr_equity"):     -0.02,
    ("F2_inflation", "global_equity"): -0.03,
    ("F2_inflation", "fx_commodity"):  +0.07,
    ("F2_inflation", "bond"):          -0.05,
    ("F2_inflation", "cash_mmf"):      +0.03,

    # F3 real_rate (+z = high real rate → -long bond, +cash)
    ("F3_real_rate", "kr_equity"):     -0.02,
    ("F3_real_rate", "global_equity"): -0.03,
    ("F3_real_rate", "fx_commodity"):  -0.01,
    ("F3_real_rate", "bond"):          -0.05,
    ("F3_real_rate", "cash_mmf"):      +0.11,

    # F4 term_premium (+z = steep curve → +long bond, +equity)
    ("F4_term_premium", "kr_equity"):     +0.02,
    ("F4_term_premium", "global_equity"): +0.03,
    ("F4_term_premium", "fx_commodity"):  0.0,
    ("F4_term_premium", "bond"):          +0.02,
    ("F4_term_premium", "cash_mmf"):      -0.07,

    # F5 credit_cycle (+z = credit stress → -equity, -credit bond, +cash)
    ("F5_credit_cycle", "kr_equity"):     -0.05,
    ("F5_credit_cycle", "global_equity"): -0.06,
    ("F5_credit_cycle", "fx_commodity"):  +0.01,  # gold flight
    ("F5_credit_cycle", "bond"):          -0.02,  # mixed (UST↑, HY↓)
    ("F5_credit_cycle", "cash_mmf"):      +0.12,

    # F6 krw_regime (+z = weak KRW → +global, -kr)
    ("F6_krw_regime", "kr_equity"):     -0.05,
    ("F6_krw_regime", "global_equity"): +0.04,
    ("F6_krw_regime", "fx_commodity"):  +0.03,
    ("F6_krw_regime", "bond"):          -0.01,
    ("F6_krw_regime", "cash_mmf"):      -0.01,

    # F7 equity_vol_regime (+z = high vol → -risk, +cash)
    ("F7_equity_vol_regime", "kr_equity"):     -0.04,
    ("F7_equity_vol_regime", "global_equity"): -0.06,
    ("F7_equity_vol_regime", "fx_commodity"):  -0.02,
    ("F7_equity_vol_regime", "bond"):          +0.04,
    ("F7_equity_vol_regime", "cash_mmf"):      +0.08,

    # F8 valuation (+z = expensive (sp_pe 우세) → -equity)
    ("F8_valuation", "kr_equity"):     -0.03,
    ("F8_valuation", "global_equity"): -0.04,
    ("F8_valuation", "fx_commodity"):  +0.01,
    ("F8_valuation", "bond"):          +0.04,
    ("F8_valuation", "cash_mmf"):      +0.02,

    # F9 liquidity_regime (+z = liquidity stress → -risk, +cash)
    ("F9_liquidity_regime", "kr_equity"):     -0.03,
    ("F9_liquidity_regime", "global_equity"): -0.05,
    ("F9_liquidity_regime", "fx_commodity"):  -0.01,
    ("F9_liquidity_regime", "bond"):          +0.04,
    ("F9_liquidity_regime", "cash_mmf"):      +0.05,
}

# Bond TIPS share separate scalar regression (spec § 5.5)
INITIAL_TIPS_BASELINE: Final[float] = 0.30
INITIAL_TIPS_BETA: Final[dict[str, float]] = {
    "F1_growth": +0.05, "F2_inflation": +0.20, "F3_real_rate": -0.10,
    "F4_term_premium": 0.0, "F5_credit_cycle": -0.05,
    "F6_krw_regime": 0.0, "F7_equity_vol_regime": 0.0,
    "F8_valuation": 0.0, "F9_liquidity_regime": -0.03,
}

SignRestriction = Literal["positive", "negative", "neutral",
                            "positive_mild", "negative_mild"]
SIGN_RESTRICTION: Final[dict[tuple[str, str], SignRestriction]] = {
    # spec § 5.3 의 full table (~30 entries)
    ("F1_growth", "kr_equity"): "positive",
    ("F1_growth", "global_equity"): "positive",
    ("F1_growth", "bond"): "negative",
    ("F1_growth", "cash_mmf"): "negative",
    # ... F2-F9
}
```

- [ ] **Step 2: row-sum invariant test**

```python
def test_initial_beta_each_factor_sums_to_zero():
    for f in FACTORS:
        row_sum = sum(INITIAL_BETA.get((f, b), 0) for b in BUCKETS)
        assert abs(row_sum) < 1e-6, f"{f}: row sum {row_sum} != 0"

def test_initial_baseline_sums_to_one():
    assert abs(sum(INITIAL_BASELINE.values()) - 1.0) < 1e-6

def test_initial_baseline_satisfies_mandate():
    risk = INITIAL_BASELINE["kr_equity"] + INITIAL_BASELINE["global_equity"] \
         + INITIAL_BASELINE["fx_commodity"]
    assert risk <= 0.70
```

- [ ] **Step 3**: PASS.

### Task C3.2: apply_factor_model + mandate projection

**Files:** `tradingagents/skills/research/factor_to_bucket.py` 에 함수 추가.

- [ ] **Step 1: failing test**

```python
def test_apply_factor_model_baseline_returns_baseline():
    """모든 factor z = 0 → bucket == baseline."""
    factor_z = {f: 0.0 for f in FACTORS}
    bucket, tips, contributions = apply_factor_model(factor_z)
    for b in BUCKETS:
        assert bucket[b] == pytest.approx(INITIAL_BASELINE[b])

def test_apply_factor_model_growth_lifts_equity():
    """F1 growth = +1.5 → equity ↑, bond ↓."""
    factor_z = {f: 0.0 for f in FACTORS}
    factor_z["F1_growth"] = 1.5
    bucket, _, _ = apply_factor_model(factor_z)
    assert bucket["kr_equity"] > INITIAL_BASELINE["kr_equity"]
    assert bucket["global_equity"] > INITIAL_BASELINE["global_equity"]
    assert bucket["bond"] < INITIAL_BASELINE["bond"]

def test_apply_factor_model_preserves_sum():
    factor_z = {f: 1.0 for f in FACTORS}
    bucket, _, _ = apply_factor_model(factor_z)
    assert abs(sum(bucket.values()) - 1.0) < 1e-6

def test_apply_factor_model_contributions_audit():
    factor_z = {f: 0.0 for f in FACTORS}
    factor_z["F1_growth"] = 1.0
    bucket, tips, contributions = apply_factor_model(factor_z)
    assert contributions["F1_growth"]["kr_equity"] == pytest.approx(0.04)
    assert contributions["F1_growth"]["bond"] == pytest.approx(-0.08)

def test_apply_factor_model_tips_share():
    factor_z = {f: 0.0 for f in FACTORS}
    bucket, tips, _ = apply_factor_model(factor_z)
    assert tips == pytest.approx(INITIAL_TIPS_BASELINE)

    factor_z["F2_inflation"] = 1.0
    _, tips_inflation, _ = apply_factor_model(factor_z)
    assert tips_inflation > tips  # +inflation → TIPS share ↑
```

- [ ] **Step 2: 구현**

```python
def apply_factor_model(
    factor_z: dict[str, float],
    baseline: dict[str, float] | None = None,
    beta: dict[tuple[str, str], float] | None = None,
    tips_baseline: float | None = None,
    tips_beta: dict[str, float] | None = None,
) -> tuple[dict[str, float], float, dict[str, dict[str, float]]]:
    """Factor z → (bucket weights, bond_tips_share, attribution).

    bucket[b] = baseline[b] + Σ_f β[f, b] × z[f]
    bond_tips_share = tips_baseline + Σ_f tips_β[f] × z[f]

    Returns: (bucket dict, tips float, contributions dict for attribution).
    """
    baseline = baseline or INITIAL_BASELINE
    beta = beta or INITIAL_BETA
    tips_baseline = tips_baseline if tips_baseline is not None else INITIAL_TIPS_BASELINE
    tips_beta = tips_beta or INITIAL_TIPS_BETA

    bucket = dict(baseline)
    contributions: dict[str, dict[str, float]] = {}

    for f in FACTORS:
        z = factor_z.get(f, 0.0)
        contributions[f] = {}
        for b in BUCKETS:
            contrib = beta.get((f, b), 0.0) * z
            bucket[b] += contrib
            contributions[f][b] = contrib

    # TIPS share
    tips = tips_baseline + sum(tips_beta.get(f, 0.0) * factor_z.get(f, 0.0) for f in FACTORS)
    tips = max(0.0, min(1.0, tips))

    return bucket, tips, contributions
```

- [ ] **Step 3**: PASS.

### Task C3.3: project_to_mandate

- [ ] **Step 1: failing test**

```python
def test_project_clips_negative():
    weights = {"kr_equity": 0.5, "global_equity": -0.1, "fx_commodity": 0.2,
               "bond": 0.3, "cash_mmf": 0.1}
    out = project_to_mandate(weights)
    assert out["global_equity"] >= 0.0

def test_project_renormalizes_to_one():
    weights = {"kr_equity": 0.3, "global_equity": 0.4, "fx_commodity": 0.2,
               "bond": 0.3, "cash_mmf": 0.2}  # sum 1.4
    out = project_to_mandate(weights)
    assert abs(sum(out.values()) - 1.0) < 1e-6

def test_project_risk_cap_enforced():
    """위험자산 0.85 → 0.70 cap."""
    weights = {"kr_equity": 0.30, "global_equity": 0.30, "fx_commodity": 0.25,
               "bond": 0.10, "cash_mmf": 0.05}  # risk = 0.85
    out = project_to_mandate(weights)
    risk = out["kr_equity"] + out["global_equity"] + out["fx_commodity"]
    assert risk <= 0.70 + 1e-6

def test_project_extreme_factor_z_still_mandate_safe():
    """모든 factor z = +3 (cap), bucket 가 extreme — mandate 강제."""
    factor_z = {f: 3.0 for f in FACTORS}
    bucket, _, _ = apply_factor_model(factor_z)
    bucket = project_to_mandate(bucket)
    risk = bucket["kr_equity"] + bucket["global_equity"] + bucket["fx_commodity"]
    assert risk <= 0.70 + 1e-6
    assert abs(sum(bucket.values()) - 1.0) < 1e-6
```

- [ ] **Step 2: 구현**

```python
def project_to_mandate(
    bucket: dict[str, float],
    risk_cap: float = 0.70,
) -> dict[str, float]:
    """위험자산 ≤ risk_cap + sum=1 enforce."""
    # 1. Clip negatives
    bucket = {b: max(0.0, w) for b, w in bucket.items()}

    # 2. Renormalize to sum=1
    total = sum(bucket.values())
    if total <= 0:
        # Pathological — fallback to baseline
        return dict(INITIAL_BASELINE)
    bucket = {b: w / total for b, w in bucket.items()}

    # 3. 위험자산 cap
    risk_buckets = ("kr_equity", "global_equity", "fx_commodity")
    risk = sum(bucket[b] for b in risk_buckets)
    if risk > risk_cap:
        scale = risk_cap / risk
        for b in risk_buckets:
            bucket[b] *= scale
        # 줄어든 만큼 bond + cash 에 proportionally
        shortfall = 1.0 - sum(bucket.values())
        safe_total = bucket["bond"] + bucket["cash_mmf"]
        if safe_total > 0:
            bucket["bond"] += shortfall * (bucket["bond"] / safe_total)
            bucket["cash_mmf"] += shortfall * (bucket["cash_mmf"] / safe_total)
        else:
            bucket["bond"] += shortfall

    return bucket
```

- [ ] **Step 3**: PASS.

### Task C3.4: C3 commit

- [ ] **Step 1**: 변경 파일 검증 + regression.
- [ ] **Step 2**: regression_log.md Post-C3.
- [ ] **Step 3**: commit (`feat(stage2): factor → bucket additive regression + mandate projection (C3)`).

---

## Commit C4: research_manager Factor Pipeline Wire-up

> **Why:** Stage 2 의 *entry point* 가 factor model 사용. 기존 LLM prompt 제거. EMA infrastructure 를 factor space 에서 재구현. dominant_scenario / conviction 재정의.

### Task C4.1: research_manager.py 전면 rewrite

**Files:** Modify `tradingagents/agents/managers/research_manager.py`

- [ ] **Step 1: failing test 먼저**

`tests/unit/agents/test_research_manager_factor_model.py`:

```python
"""research_manager 의 factor model pipeline e2e."""
from unittest.mock import MagicMock
from tradingagents.agents.managers.research_manager import create_research_manager
from tradingagents.schemas.research import ResearchDecision


def _full_state():
    s = {}
    s["macro_summary"] = "test"
    s["risk_summary"] = "test"
    s["technical_summary"] = "test"
    s["news_summary"] = "test"

    # macro_report (struct, MagicMock for deep attr access)
    s["macro_report"] = MagicMock()
    s["macro_report"].growth.gdp_nowcast = 2.0
    s["macro_report"].growth.cfnai = 0.0
    s["macro_report"].growth.nfci = 0.0
    s["macro_report"].employment.sahm_trigger = False
    s["macro_report"].yield_curve.slope_2_10y_bps = 80
    s["macro_report"].yield_curve.slope_5_30y_bps = 120
    s["macro_report"].cpi.yoy_pct = 2.5
    s["macro_report"].cpi.three_month_annualized_pct = 2.5
    s["macro_report"].cpi.core_pce_yoy = 2.0
    s["macro_report"].inflation_exp.five_y_five_y_pct = 2.3
    s["macro_report"].inflation_exp.michigan_1y_pct = 3.0
    s["macro_report"].real_yields.ten_y_pct = 0.5
    s["macro_report"].fed_path.implied_change_6m_bps = 0
    s["macro_report"].kr_macro.bok_us_rate_diff_bps = -100
    s["macro_report"].kr_macro.exports_yoy_pct = 5.0
    s["macro_report"].foreign_flow.net_flow_z = 0.0

    # risk_report
    s["risk_report"] = MagicMock()
    s["risk_report"].credit_spread_us_hy.current_bps = 400
    s["risk_report"].credit_spread_us_hy.momentum_z = 0.0
    s["risk_report"].credit_quality.quality_spread_bps = 90
    s["risk_report"].funding_stress.spread_bps = 10
    s["risk_report"].vix.current_value = 20.0
    s["risk_report"].vix.z_score = 0.0
    s["risk_report"].vix.term_ratio = 1.0
    s["risk_report"].move.current_value = 90
    s["risk_report"].realized_vol.sixty_d = 0.012
    s["risk_report"].equity_bond_corr.correlation_60d = -0.2
    s["risk_report"].skew.change_1m = 0.0

    # technical_report
    s["technical_report"] = MagicMock()
    s["technical_report"].sector_dispersion = 1.0
    s["technical_report"].breadth = 0.55
    s["technical_report"].kospi_pbr = 1.0

    # news_report
    s["news_report"] = MagicMock()
    s["news_report"].release_surprise.surprise_index_30d = 0.0
    s["news_report"].release_surprise.bias_30d = "balanced"
    s["news_report"].release_surprise.high_importance_today = 1
    s["news_report"].news_sentiment.avg_sentiment = {"macro": 0.0, "corporate": 0.0}
    s["news_report"].news_sentiment.count_change_vs_7d = {"corporate": 0, "geopolitical": 0}
    s["news_report"].news_sentiment.sentiment_dispersion = 0.3
    s["news_report"].news_sentiment.rising_category = None
    s["news_report"].global_overnight.risk_regime_overnight = "mixed"
    s["news_report"].global_overnight.krw.change_pct = 0.0
    s["news_report"].cb_speakers.fed_voting_balance = 0.0
    s["news_report"].cb_speakers.fed_tone_balance = 0.0
    s["news_report"].cb_speakers.bok_tone_balance = 0.0

    return s


def test_research_manager_returns_research_decision():
    node = create_research_manager(deep_llm=None)  # LLM 미사용
    state = _full_state()
    result = node(state)
    assert "research_decision" in result
    assert "bucket_target" in result
    assert "research_debate_summary" in result
    assert isinstance(result["research_decision"], ResearchDecision)


def test_research_decision_has_factor_scores():
    node = create_research_manager(deep_llm=None)
    state = _full_state()
    result = node(state)
    rd = result["research_decision"]
    assert len(rd.factor_scores) == 9
    assert "F1_growth" in rd.factor_scores

def test_bucket_target_mandate_safe():
    node = create_research_manager(deep_llm=None)
    state = _full_state()
    result = node(state)
    bt = result["bucket_target"]
    risk = bt.kr_equity + bt.global_equity + bt.fx_commodity
    assert risk <= 0.70 + 1e-6
    assert abs(bt.kr_equity + bt.global_equity + bt.fx_commodity + bt.bond + bt.cash_mmf - 1.0) < 1e-6
```

- [ ] **Step 2: research_manager.py rewrite**

```python
"""Research Manager (Stage 2) — Factor model (PR 2026-05-22).

Pipeline:
  Stage 1 (4 analyst struct + 4 summary) → AgentState
    → compute_all_factors(state) → FactorScores (9 z-vector)
    → apply_prior_smoothing (EMA in factor space, λ=1 default no-op)
    → apply_factor_model(z, β) → bucket weights + attribution
    → project_to_mandate → BucketTarget
    → derive_dominant_scenario + derive_conviction (deterministic legacy compat)
    → ResearchDecision

Stage 2 추가 LLM 호출 0. macro_news_analyst 의 NewsReport structured field 활용 (Option Z).
"""
from typing import Optional

from tradingagents.schemas.portfolio import BucketTarget
from tradingagents.schemas.research import ResearchDecision
from tradingagents.skills.research.factor_estimators import (
    compute_all_factors, FactorScores,
)
from tradingagents.skills.research.factor_to_bucket import (
    apply_factor_model, project_to_mandate, INITIAL_BASELINE,
)


# Temporal smoothing (factor space). EMA infrastructure 유지 — default no-op.
_EMA_LAMBDA: float = 1.0      # 1.0 → identity. variance 측정 후 < 1.0 활성화 가능.


def _blend_factors_with_prior(
    new: FactorScores,
    prior_decision: ResearchDecision | None,
    lam: float,
) -> FactorScores:
    """EMA on factor z-vector. λ=1 → identity. prior None → identity."""
    if prior_decision is None or lam >= 1.0 - 1e-9:
        return new
    from dataclasses import replace
    prior_z = prior_decision.factor_scores
    if not prior_z:  # prior decision (legacy 24-cell) has no factor_scores
        return new

    blended = FactorScores(
        growth_surprise=replace(new.growth_surprise,
            z_score=lam * new.growth_surprise.z_score + (1 - lam) * prior_z.get("F1_growth", 0)),
        inflation_surprise=replace(new.inflation_surprise,
            z_score=lam * new.inflation_surprise.z_score + (1 - lam) * prior_z.get("F2_inflation", 0)),
        # ... 9 factor 모두 (간략 표현)
        real_rate=new.real_rate,  # PLACEHOLDER — 실제로는 9 factor 모두 blend
        term_premium=new.term_premium,
        credit_cycle=new.credit_cycle,
        krw_regime=new.krw_regime,
        equity_vol_regime=new.equity_vol_regime,
        valuation=new.valuation,
        liquidity_regime=new.liquidity_regime,
    )
    return blended


def derive_dominant_scenario(factor_scores: FactorScores) -> str:
    """Legacy compat — deterministic mapping factor z → scenario name."""
    f1 = factor_scores.growth_surprise.z_score
    f2 = factor_scores.inflation_surprise.z_score
    f5 = factor_scores.credit_cycle.z_score
    f6 = factor_scores.krw_regime.z_score
    f7 = factor_scores.equity_vol_regime.z_score

    # Priority overrides
    if f7 > 1.5 and f5 > 1.0:
        return "global_credit"
    if f6 > 1.0:    # KRW weak + 기타 KR stress
        # boom vs stress — krw_regime 의 sign 만으로는 모호. F5/F7 으로 distinguish.
        if f5 > 0.5 or f7 > 0.5:
            return "kr_stress"
        return "kr_boom"
    if f6 < -1.0:
        # KRW strong + KR boom indicators (foreign flow, exports)
        return "kr_boom"

    # Cycle quadrant
    if f1 > 0.5 and f2 > 0.5:
        return "overheating"   # growth + inflation
    if f1 > 0.5 and f2 < -0.5:
        return "goldilocks"    # growth + disinflation
    if f1 < -0.5 and f2 > 0.5:
        return "stagflation"   # recession + inflation
    if f1 < -0.5 and f2 < -0.5:
        return "broad_recession"
    return "goldilocks"  # default (mild conditions)


def derive_conviction(factor_scores: FactorScores) -> str:
    """Legacy compat — total magnitude + sign agreement 기반."""
    z_dict = factor_scores.to_dict()
    total_mag = sum(abs(z) for z in z_dict.values())

    # Sign agreement metric: 주요 4 factor (F1, F2, F5, F7) 의 sign alignment
    signs = [z_dict["F1_growth"], -z_dict["F5_credit_cycle"], -z_dict["F7_equity_vol_regime"]]
    # 양수면 risk-on, 음수면 risk-off
    avg_sign = sum(1 if s > 0 else -1 if s < 0 else 0 for s in signs)
    alignment = abs(avg_sign) / len(signs)  # 0-1

    if total_mag > 4.0 and alignment > 0.6:
        return "high"
    if total_mag > 2.0 and alignment > 0.3:
        return "medium"
    return "low"


def create_research_manager(deep_llm):
    """Note: deep_llm 파라미터 유지 (interface compat), 본 함수 내에서 사용 안 함."""
    def node(state):
        # 1. Compute 9 factors (deterministic)
        factor_scores = compute_all_factors(state)

        # 2. EMA blend (λ=1.0 default no-op)
        prior_decision: Optional[ResearchDecision] = state.get("prior_research_decision")
        factor_scores = _blend_factors_with_prior(factor_scores, prior_decision, _EMA_LAMBDA)

        # 3. Factor → bucket
        bucket, tips_share, contributions = apply_factor_model(factor_scores.to_dict())

        # 4. Mandate projection
        bucket = project_to_mandate(bucket)

        # 5. Legacy compat fields
        dominant_scenario = derive_dominant_scenario(factor_scores)
        conviction = derive_conviction(factor_scores)

        # 6. Build BucketTarget
        rationale = (
            f"Factor model: dominant_scenario={dominant_scenario}, conviction={conviction}. "
            f"Top contributors: " +
            ", ".join(f"{f}={factor_scores.to_dict()[f]:+.2f}"
                       for f in sorted(factor_scores.to_dict(),
                                       key=lambda k: -abs(factor_scores.to_dict()[k]))[:3])
        )[:500]

        target = BucketTarget(
            kr_equity=bucket["kr_equity"],
            global_equity=bucket["global_equity"],
            fx_commodity=bucket["fx_commodity"],
            bond=bucket["bond"],
            cash_mmf=bucket["cash_mmf"],
            bond_tips_share=tips_share,
            rationale=rationale,
        )

        # 7. ResearchDecision — *factor field 만* (24-cell field 는 C5 에서 제거)
        # PR1 의 C2-C4 는 *공존 phase* — 24-cell field 는 default empty.
        decision = ResearchDecision(
            bucket_target=target,
            # Legacy 24-cell — minimal placeholder (C5 에서 제거)
            scenario_probabilities=_legacy_empty_probs(),
            dominant_cell=_legacy_dominant_cell(dominant_scenario),
            dominant_cell_probability=0.0,
            dominant_cycle=_scenario_to_cycle(dominant_scenario),
            dominant_cycle_probability=0.0,
            cycle_marginals={"A": 0, "B": 0, "C": 0, "D": 0},
            tail_marginals={"N": 1.0, "T": 0.0},
            kr_marginals={"F": 1.0, "boom": 0.0, "stress": 0.0},
            conviction=conviction,
            conviction_beta=1.0,
            effective_cycle_marginals={"A": 0, "B": 0, "C": 0, "D": 0},
            # New factor model fields
            factor_scores=factor_scores.to_dict(),
            factor_contributions=contributions,
            baseline_bucket=dict(INITIAL_BASELINE),
        )

        # 8. Summary text
        summary = (
            f"## Research Decision (Factor Model)\n"
            f"Dominant scenario: {dominant_scenario} ({conviction})\n\n"
            f"Factor z-scores:\n" +
            "\n".join(f"  {f}: {z:+.2f}" for f, z in factor_scores.to_dict().items()) +
            f"\n\n## Bucket Target\n"
            f"국내주식: {target.kr_equity*100:.1f}%, "
            f"해외주식: {target.global_equity*100:.1f}%, "
            f"FX/원자재: {target.fx_commodity*100:.1f}%, "
            f"채권: {target.bond*100:.1f}% (TIPS {tips_share*100:.0f}%), "
            f"MMF: {target.cash_mmf*100:.1f}%\n"
            f"위험자산 합: {(target.kr_equity + target.global_equity + target.fx_commodity)*100:.1f}%"
        )

        return {
            "bucket_target": target,
            "research_decision": decision,
            "research_debate_summary": summary,
        }

    return node


# Legacy helpers (C5 에서 ResearchDecision schema 의 24-cell field 와 함께 제거)
def _legacy_empty_probs():
    from tradingagents.schemas.research import ScenarioProbabilities24, ALL_CELLS
    kwargs = {k: 0.0 for k in ALL_CELLS}
    kwargs["A_N_F"] = 1.0
    return ScenarioProbabilities24(**kwargs, reasoning="factor model (legacy compat)")

def _legacy_dominant_cell(scenario):
    from tradingagents.schemas.research import CellCoord
    return CellCoord(cycle="A", tail="N", kr="F")  # placeholder

def _scenario_to_cycle(scenario):
    return {"goldilocks": "A", "overheating": "B",
            "broad_recession": "C", "stagflation": "D"}.get(scenario, "A")
```

- [ ] **Step 3**: 3 test PASS.

### Task C4.2-4.5: 추가 test + 회귀

- [ ] **C4.2**: integration test (`tests/integration/test_stage2_factor_model_e2e.py`) — replay_stage 으로 2026-05-15 fixture 실행, bucket_target 검증.
- [ ] **C4.3**: 기존 test 충돌 정리 — 24-cell prompt test (`test_research_manager.py`) 가 *깨질 가능성* → 해당 test 삭제 (C5 에서 어차피 제거).
- [ ] **C4.4**: 전체 회귀 — 24-cell 제거 분 제외 0 new regression.
- [ ] **C4.5**: C4 commit (`feat(stage2): research_manager factor model pipeline wire-up (C4)`).

---

## Commit C5: 24-cell Framework 완전 제거

> **Why:** Hard cutover 완료. Dead code 제거 + schema cleanup. 본 commit 후 codebase 에 24-cell 흔적 0.

### Task C5.1-C5.7

- [ ] **C5.1**: `git rm tradingagents/skills/research/scenario_mapper.py tradingagents/skills/research/scenario_definitions.py`.
- [ ] **C5.2**: `tradingagents/schemas/research.py` 에서 `ScenarioProbabilities24`, `CellCoord`, `ALL_CELLS`, `TRANSIENT_CELLS`, `cell_key`, `parse_cell_key`, `CycleQuadrant`, `TailState`, `KRDirection`, `ScenarioProbabilities` alias 제거.
- [ ] **C5.3**: `ResearchDecision` 의 24-cell field 제거 — `scenario_probabilities`, `dominant_cell`, `dominant_cell_probability`, `dominant_cycle`, `dominant_cycle_probability`, `cycle_marginals`, `tail_marginals`, `kr_marginals`, `conviction_beta`, `effective_cycle_marginals`. **유지**: `conviction`, `dominant_scenario` (legacy compat — derived). **추가 유지**: factor field.
- [ ] **C5.4**: `research_manager.py` 의 `_legacy_empty_probs`, `_legacy_dominant_cell`, `_scenario_to_cycle` 제거. `ResearchDecision` 생성 시 24-cell field 안 채움.
- [ ] **C5.5**: `tradingagents/skills/portfolio/sub_category.py` 의 `_LEGACY_SCENARIO_TO_AXES` *유지* (downstream method_picker 의 scenario string mapping 용). Cell key 의존 부분만 정리 (이미 C1.4 에서).
- [ ] **C5.6**: 24-cell 의존 test 삭제:
  - `git rm tests/unit/skills/test_research_scenario_mapper.py`
  - `git rm tests/integration/test_stage2_e2e_snapshot.py`
  - `git rm tests/unit/agents/test_research_manager.py`
- [ ] **C5.7**: 전체 회귀 — `uv run pytest tests/ -q | tail -10`. 24-cell test 제거 만큼 test count 감소 (예: -25 ~ -30). pre-existing 3 unit fail / 18 integration fail *외* 새 fail 없음.
- [ ] **C5.8**: C5 commit (`refactor(stage2): 24-cell framework 완전 제거 (C5)`).

---

## Commit C6: Walk-forward Calibration

> **Why:** Hand-coded INITIAL_BETA 를 *backtest informed* 로 update. Spec § 6.

### Task C6.1: calibrate_factor_model.py CLI

**Files:** Create `scripts/calibrate_factor_model.py`, `tradingagents/skills/research/factor_calibration.py`

- [ ] **Step 1: factor_calibration.py 의 helper**

```python
def simulate_portfolio_returns(historical_data, beta_table) -> np.ndarray:
    """historical (factor_z, bucket_returns) → portfolio returns."""
    returns = []
    for t in range(len(historical_data)):
        factor_z = historical_data[t]["factor_z"]  # 9-vector
        bucket, _, _ = apply_factor_model(factor_z, beta=beta_table)
        bucket = project_to_mandate(bucket)
        ret = sum(bucket[b] * historical_data[t]["bucket_returns_next"][b]
                  for b in BUCKETS)
        returns.append(ret)
    return np.array(returns)

def hybrid_calibration(train, theory_prior, shrinkage=0.5):
    """scipy.optimize 으로 Sharpe maximization with prior shrinkage + sign constraint."""
    # ... (spec § 6.1)
```

- [ ] **Step 2: CLI script `scripts/calibrate_factor_model.py`**

```python
"""Walk-forward Sharpe maximization for factor model β.

Usage:
    python scripts/calibrate_factor_model.py --sample full --shrinkage-grid
"""
import argparse, json
from pathlib import Path
# ...

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", choices=["full", "post_gm", "post_covid"],
                        default="full")
    parser.add_argument("--shrinkage-grid", action="store_true")
    parser.add_argument("--out-dir", default="artifacts/2026-05-22/factor_calibration")
    args = parser.parse_args()

    # 1. Load historical (1991-2024 quarterly factor_z + bucket returns)
    historical = load_historical_data(args.sample)

    # 2. Walk-forward calibration
    results = []
    for shrinkage in ([0.1, 0.3, 0.5, 0.7, 1.0] if args.shrinkage_grid else [0.5]):
        fold_results = walk_forward(historical, shrinkage=shrinkage)
        results.append({"shrinkage": shrinkage, "folds": fold_results,
                        "oos_sharpe_median": np.median([f["oos_sharpe"] for f in fold_results])})

    # 3. Save artifacts
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    # final β = best shrinkage 의 median across folds
    best = max(results, key=lambda r: r["oos_sharpe_median"])
    final_beta = aggregate_median_beta(best["folds"])
    (out / "coefficient_table.json").write_text(json.dumps(final_beta, indent=2))
    # walk_forward_results.csv, shrinkage_grid.csv, validation_report.md
    ...
```

- [ ] **Step 3: Historical data preparation**

`tradingagents/skills/research/factor_calibration.py` 의 `load_historical_data(sample)`:
- 1991-2024 quarterly FRED + ECOS + yfinance fetch.
- 각 quarter t 에 대해: factor_z (9-vector) computed via *historical Stage 1 mock* + bucket returns (KOSPI, S&P, IEF, DJP, ^IRX).
- KRW base conversion.
- Cache to local file (1회 fetch 후 재사용).

`historical_data[t]` = `{"date": ..., "factor_z": {"F1_growth": ..., ...}, "bucket_returns_next": {"kr_equity": ..., ...}}`

### Task C6.2-C6.5

- [ ] **C6.2**: shrinkage grid + sample window grid 실행 — background.
- [ ] **C6.3**: validation_report.md 작성 — acceptance criteria (OOS Sharpe > current +0.05, ≥ 60/40) check.
- [ ] **C6.4**: 결과로 INITIAL_BETA update (factor_to_bucket.py). 또는 별도 `CALIBRATED_BETA` constant 추가 + default 로 사용.
- [ ] **C6.5**: 2026-05-15 fixture 로 sanity (factor model 출력이 reasonable).
- [ ] **C6.6**: C6 commit (`chore(stage2): walk-forward calibration + β update (C6)`).

---

## Commit C7: 2026-05-15 산출물 재생성

### Task C7.1-C7.7

- [ ] **C7.1**: backup pre-C7 산출물 (`cp artifacts/2026-05-15/*.{json,md,csv} /tmp/`).
- [ ] **C7.2**: Stage 2-6 sequential replay:
  ```bash
  set -a && source .env && set +a
  uv run python scripts/replay_stage.py --as-of 2026-05-15 --stage research_debate --write-archive
  uv run python scripts/replay_stage.py --as-of 2026-05-15 --stage allocator --write-archive
  uv run python scripts/replay_stage.py --as-of 2026-05-15 --stage risk_debate --write-archive
  uv run python scripts/replay_stage.py --as-of 2026-05-15 --stage validator --write-archive
  uv run python scripts/replay_stage.py --as-of 2026-05-15 --stage portfolio_manager --artifacts-dir artifacts --write-archive
  ```
- [ ] **C7.3**: artifacts/2026-05-15/2026-05-15/{...} → artifacts/2026-05-15/{...} move.
- [ ] **C7.4**: stage2_diff_factor_model.md 작성 — pre/post 비교 (factor_scores, bucket_target, method_choice, weights). Mega-PR 의 stage2_diff.md 와 유사 format.
- [ ] **C7.5**: D6 결정 (philosophy.md narrative) — diff magnitude 보고 결정. decisions.md update.
- [ ] **C7.6**: validation_report.passed=True 확인 + mandate.
- [ ] **C7.7**: C7 commit (`data(2026-05-15): factor model 으로 산출물 재생성 + diff (C7)`).

---

## Commit C8: Documentation + Stage 1 Backlog

### Task C8.1: docs/followup_issues.md 에 Stage 1 backlog 추가

`docs/followup_issues.md` 의 `## 우선순위 제안` 표 직전에 Issue #12-#19 추가:

```markdown
## Issue #12 — Stage 1 macro_quant 에 KR FX skill 추가 (factor model F6 Gap E+F)

### Problem
factor model 의 F6 krw_regime 가 KRW/USD level + REER 필요. 현재 Stage 2 의 `external_fetchers.py` 가 yfinance 임시 fetch. Stage 1 fetch + cache 가 더 적절.

### Proposed approach
- macro_quant 의 sub_skill: kr_fx (KRW/USD level via yfinance KRW=X, REER via BIS monthly)
- MacroReport schema 에 `kr_fx: KRFXSnapshot` 필드 추가
- factor_estimators.py 의 F6 가 `stage1.macro_report.kr_fx.*` 으로 source 변경 (external_fetcher 제거)

### Effort
~4-6시간

---

## Issue #13 — Stage 1 macro_quant 에 LEI + ISM sub-components 추가 (F1 Gap A+B)
...

## Issue #14 — Stage 1 macro_quant 에 r-star (HLW) + ACM/Kim-Wright term premium 추가 (F3+F4 Gap C+D)
...

## Issue #15 — Stage 1 market_risk 에 valuation skill 추가 (F8 Gap G)
forward P/E, ERP. external_fetcher.fetch_sp_trailing_pe 의 대체.

## Issue #16 — Stage 1 market_risk 에 cross-currency basis 추가 (F9 Gap H)

## Issue #17 — external_fetchers.py 의 임시 fetch 를 Stage 1 으로 migrate (cleanup)
Issue #12, #15 완료 후 external_fetchers.py 자체 삭제. factor_estimators.py update.

## Issue #18 — factor model β 재calibration (6m 주기)
historical 갱신 + walk-forward 재실행.

## Issue #19 — factor reliability audit 6m 재검증 (AUDIT_DATE update)
factor_reliability_audit.py 의 component reliability + weight cap 검토.
```

### Task C8.2: Audit doc status update

`docs/superpowers/specs/2026-05-22-stage2-pipeline-audit.md` 의 각 Issue 의 status update:
- Issue A (signal cleaning bug): **RESOLVED** (C1 sub-graph 폐기).
- Issue B (EMA prior latent): **RESOLVED** (C1 — AgentState 직접 접근).
- Issue C (state isolation redesign): **RESOLVED** (C1).
- Issue D (anchoring): **REPLACED** — factor model 으로 architecture 변경. anchoring 측정 불필요.
- Issue E (legacy mapping 정보 손실): **PARTIAL** — factor → bucket 의 contribution attribution 으로 보완. method_picker 는 여전히 dominant_scenario 사용.
- Issue F (calibration 혼재): **RESOLVED** — hand-coded → walk-forward calibration.
- Issue G (LLM fragility): **RESOLVED** — Stage 2 deterministic.
- Issue H (cross-effect downstream): **REPLACED** — factor 가 직접 bucket 결정.
- Issue I (정보 압축): **RESOLVED** — factor → bucket 의 attribution 명시.
- Issue J (reasoning 1500자): **OBSOLETE** — LLM 호출 없음.
- Issue K (message channel): **RESOLVED** — sub-graph 제거.
- Issue L (silent exception): **RESOLVED** — `_safe_get` 의 None handling.
- Issue M (cell key vs dominant_scenario inconsistency): **RESOLVED** — cell 제거.

### Task C8.3: decisions.md 갱신

`artifacts/2026-05-22/decisions.md` 의 pending decision (D7, D8) 채움 (C6 calibration 결과 반영).

### Task C8.4: C8 commit

`docs(stage2): Stage 1 backlog (Issue #12-#19) + audit status update (C8)`.

---

## Final Validation Gate

- [ ] **모든 commit 완료 후**:
  - `uv run pytest tests/ -q` — 3 unit pre-existing fail / 18 integration pre-existing fail 외 *0 new fail*.
  - `artifacts/2026-05-22/regression_log.md` 의 모든 Post-Cx 채움.
  - `artifacts/2026-05-22/decisions.md` 의 pending 모두 채움.
  - `artifacts/2026-05-15/portfolio.json` mandate.passed = True.
  - `artifacts/2026-05-15/stage2_diff_factor_model.md` 작성.
  - `docs/followup_issues.md` 의 Issue #12-#19 등록.
  - Walk-forward OOS Sharpe > 현 framework + 0.05 AND ≥ 60/40 (`artifacts/2026-05-22/factor_calibration/validation_report.md`).

- [ ] **Finishing branch (사용자 결정)**:
  - Option 2 (push + PR) 권장 — Mega-PR 와 동일 protocol.

---

## 참조

- Spec: `docs/superpowers/specs/2026-05-22-stage2-factor-model-design.md`
- Audit: `docs/superpowers/specs/2026-05-22-stage2-pipeline-audit.md`
- Mega-PR execution protocol: `docs/superpowers/plans/2026-05-20-stage2-execution-protocol.md`
- Memory: `feedback_regression_tests.md`, `feedback_long_session_protocol.md`
- Mega-PR design (predecessor): `docs/superpowers/specs/2026-05-20-stage2-bottleneck-fix-design.md`
