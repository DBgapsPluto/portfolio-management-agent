# Stage 2 Pipeline Audit (2026-05-22)

> **목적:** Stage 2 Mega-PR (feat/stage2-bottleneck-fixes, commits fc65717 → 47b5590) merge 후, Stage 2 전체 파이프라인의 *남은 구조적 문제* 를 audit. Issue #5-#11 의 후속.
>
> **본 문서의 위치:** Mega-PR 의 Issue #5-#11 (`docs/superpowers/specs/2026-05-20-stage2-bottleneck-fix-design.md`) 가 단일 PR cycle 에서 해결한 문제들 *이외*에, 파이프라인 read-through 에서 발견된 *새 문제*들. 본 문서는 별도 PR cycle 의 spec/plan 입력.
>
> **Scope:** Stage 2 (`research_debate` 노드 + sub-graph + scenario_mapper + 24-cell schema) 의 read-only audit. 코드 변경 없음.

---

## Executive Summary

Mega-PR 이 7개 식별된 issue (#5-#11) 를 해소했지만, Stage 2 전체 파이프라인 read-through 결과 **13개 추가 issue (A-M)** 발견. 분류:

| 분류 | 개수 | 항목 |
|---|---|---|
| **Critical (production behavior wrong)** | 1 | A (D2/D3 signal cleaning silent bug) |
| **High (design intent unfulfilled)** | 4 | F (calibration 혼재), H (cross-effect downstream 미활용), D (anchoring 재측정 필요 — A 의존), I (정보 압축 미측정) |
| **Medium (correctness 의문 또는 maintainability)** | 4 | E (legacy mapping 정보 손실), G (LLM fragility), M (cell key/dominant_scenario inconsistency), C (state isolation redesign) |
| **Low (latent or cosmetic)** | 4 | B (EMA prior latent bug), J (reasoning 1500자 제한), K (message channel 미사용), L (silent exception) |

**가장 중요한 발견**: Issue **A** — `conditional_stress.py` + `kr_residual_signals.py` 모듈 (Stage 0 signal cleaning, Issue #6 의 데이터 정확도 작업의 *전제*) 이 production 에서 *한 번도 호출되지 않음*. State isolation (sub-graph wrap) 으로 `macro_report` / `risk_report` 가 sub-graph 로 안 넘어감 → `_build_signal_blocks()` 항상 빈 결과. spec 문서에는 작동하는 것으로 기술돼 있으나 실제로는 LLM 이 raw text summary 에서 D2/D3 결정.

**Mega-PR 의 모든 측정 결과 (C2 variance + ablation) 는 사실 "Stage 0 signal cleaning 이 빈 상태" 에서의 측정** — Issue A 수정 후 anchoring/variance 재측정 필수.

---

# Issue A: D2/D3 Stage 0 signal cleaning silent bug

## Severity: **CRITICAL** (production behavior diverges from documented design)

**Status (2026-05-22, PR `feat/stage2-factor-model`)**: RESOLVED — C1 commit `c0df101` 에서
sub-graph wrapper 폐기. research_manager 가 AgentState 직접 접근 (Option 2 채택 — factor
model 으로 architecture 가 redesign 되면서 sub-graph 자체 불필요).

## Problem (현상)

`tradingagents/agents/managers/research_manager.py:192-231` 의 `_build_signal_blocks(state)` 함수:

```python
def _build_signal_blocks(state) -> tuple[str, str]:
    macro_report = state.get("macro_report")
    risk_report = state.get("risk_report")
    if macro_report is None or risk_report is None:
        return ("", "")  # ← 항상 이 path 가 trigger
    # 이하 conditional_stress + kr_residual_signals 호출 (unreachable)
```

**왜 항상 None 인가**: Stage 2 가 sub-graph (`InvestDebateState`) wrapper 안에서 실행. `trading_graph.py:93-103` 의 `research_debate_node` 가 parent state 에서 sub_input 구성 시 `macro_report` / `risk_report` 를 *복사하지 않음*:

```python
sub_input = InvestDebateState(
    messages=[],
    macro_summary=state.get("macro_summary", ""),
    risk_summary=state.get("risk_summary", ""),
    technical_summary=state.get("technical_summary", ""),
    news_summary=state.get("news_summary", ""),
    bucket_target=None,
    research_decision=None,
    research_debate_summary="",
    # macro_report ❌ 누락
    # risk_report ❌ 누락
    # technical_report ❌ 누락
    # prior_research_decision ❌ 누락
)
```

`InvestDebateState` schema (`debate_state.py:14-32`) 도 위 4개 키가 정의 안 됨. → sub-graph 의 estimator 노드가 받는 state 에는 `macro_report` / `risk_report` 가 존재하지 않음.

## Why this matters

### 1. Documented design 이 작동 안 함

`docs/superpowers/specs/2026-05-09-db-gaps-agent-redesign-design.md` 의 Stage 2 design 은 "D2 / D3 cycle-decontamination — conditional stress surprise + KR residual signals" 를 핵심으로 명시.

`tradingagents/skills/risk/conditional_stress.py` 의 docstring:
> 해결: 각 D1 regime quadrant가 normally produce하는 baseline stress level을 두고, 실측 값과의 *surprise*만 D2 신호로 사용. surprise > +1σ가 진짜 systemic tail의 독립 신호.

`tradingagents/skills/risk/kr_residual_signals.py` 의 docstring:
> 해결: KR 신호에서 *global cycle로 설명되는 분*을 빼고 KR-specific residual만 D3로.

**현실**: 두 모듈이 한 번도 호출되지 않음. LLM prompt 의 `[축 직교성 가이드 — D2, D3 신호 cycle-decontamination (Stage 0)]` 블록이 매번 빈 string. → LLM 이 D2/D3 결정을 *raw text summary* 에서만 추정.

### 2. Mega-PR Issue #6 의 작업 전제가 무너짐

Issue #6 (D7 deferred) 의 목표 = `_BASELINE` 5×4 hand-coded → 1970-2024 quarterly regression 으로 교체.

전제: baseline 이 z-score 산출에 *사용되어야* fix 의 가치가 있음. 그러나 z-score 자체가 LLM 에 도달 안 함 → **`_BASELINE` 의 정확도 자체가 무관**. Issue #6 의 Phase A/B/C 계획 전부 의문.

### 3. Mega-PR 의 모든 측정이 "빈 stage 0 block" 상태에서 이뤄짐

- C2 variance n=20 (`artifacts/2026-05-20/variance/n20_run.json`): 0% flip, σ 0.3pp.
- C2 ablation baseline n=3: B=0.79, overheating × 3.
- Anchoring 측정 (L1=0.995, ratio 0.73): "macro_summary 의존 매우 큼".

이 모든 측정이 **stage 0 signal cleaning block 이 빈 상태** 에서의 측정. Issue A 수정 후:
- variance 가 달라질 수 있음 (D2/D3 신호가 prompt 에 들어가면 LLM 의 cell distribution 이 변화).
- Anchoring 결과도 변할 수 있음 (다른 input 이 늘어나면 macro_summary 의 상대 weight ↓).

→ **C3/C4/C5 의 모든 결정 (β=1, EMA λ=1, hysteresis off, prompt split, D5 keep prompt) 의 데이터 근거가 부분적으로 invalid**. Issue A 수정 후 재측정 필수.

### 4. "직교성" 보장 안 됨 (24-cell framework 의 핵심 가정)

24-cell framework 의 설계 의도:
- D1 (cycle) ⊥ D2 (tail): D2 신호는 D1 baseline 대비 surprise (conditional_stress) 여야 D1 신호 이중 가산 회피.
- D1 ⊥ D3 (KR): D3 신호는 global cycle 영향 제거한 residual (kr_residual_signals) 여야 D1 reflagging 회피.

**현실**: LLM 이 raw text summary 만 보고 D2/D3 추정 → "HY OAS 700bp" (절대값) 같은 cycle proxy 를 D2 로 직접 사용. 직교성 깨짐.

## Best fix

**Option 1: Pre-process at parent level (Recommended)**

`research_debate_node` 가 sub-graph 호출 *전에* `_build_signal_blocks()` 호출. 결과 *문자열* 만 sub_input 에 전달.

```python
# trading_graph.py 수정
def research_debate_node(state):
    # Parent level 에서 signal cleaning (macro_report, risk_report 사용)
    from tradingagents.agents.managers.research_manager import _build_signal_blocks
    conditional_stress_block, kr_residual_block = _build_signal_blocks(state)

    # InvestDebateState 에 string 만 전달
    sub_input = InvestDebateState(
        messages=[],
        macro_summary=state.get("macro_summary", ""),
        risk_summary=state.get("risk_summary", ""),
        technical_summary=state.get("technical_summary", ""),
        news_summary=state.get("news_summary", ""),
        conditional_stress_block=conditional_stress_block,  # ← 신규
        kr_residual_block=kr_residual_block,                # ← 신규
        prior_research_decision=state.get("prior_research_decision"),  # ← Bug B 동시 fix
        bucket_target=None, research_decision=None,
        research_debate_summary="",
    )
    sub_result = invest_subgraph.invoke(sub_input)
    return {...}

# debate_state.py 수정 — 신규 필드
class InvestDebateState(MessagesState):
    # ... 기존 필드 ...
    conditional_stress_block: Annotated[str, "Stage 0 D2 cycle-decontaminated surprise block"]
    kr_residual_block: Annotated[str, "Stage 0 D3 KR residual signal block"]
    prior_research_decision: Annotated[Optional[ResearchDecision], "Previous decision for EMA prior"]

# research_manager.py 수정 — _build_signal_blocks 의존 제거
def create_research_manager(deep_llm):
    def node(state):
        # state.get() 으로 직접 가져옴 — parent 가 넘긴 string 사용
        conditional_stress_block = state.get("conditional_stress_block", "")
        kr_residual_block = state.get("kr_residual_block", "")
        # ... 나머지 동일 ...
```

**왜 이게 best**:
1. **State isolation 명목 유지**: sub-graph 는 여전히 raw `MacroReport` / `RiskReport` 객체 안 봄. string 만 받음.
2. **Bug A + B 동시 fix**: prior_research_decision 도 같이 전달.
3. **Production 코드 변화 최소**: `_build_signal_blocks` 함수는 그대로, 호출 위치만 parent 로 이동. unit test 영향 적음.
4. **Test affordance**: parent level 에서 호출하므로 mock 객체로 macro_report/risk_report 주입 쉬움.

**Trade-offs**:
- 책임이 일부 parent (graph wiring) 로 이동 — Stage 2 "내부 logic" 의 일부가 외부에 노출.
- 그러나 *string 만* 외부에 있고 *추출 logic* 은 여전히 `research_manager.py` 안에 있어 응집성 유지.

**Option 2: Sub-graph 폐기**

`research_debate_node` 를 single node 로 변환, AgentState 전체 전달.

- Pro: 가장 단순. 모든 latent state-passing bug 해소.
- Con: Stage 2 의 *형식상 isolation* 폐기 — Bull/Bear 토론 재도입 시 reverting 필요. 그러나 spec 이 단일 estimator 로 확정됐다면 의미 없음.

**Option 3: InvestDebateState 에 모든 필드 추가**

`macro_report`, `risk_report`, `technical_report`, `prior_research_decision` 등 sub-graph 가 받는 state 를 parent 와 거의 동일하게.

- Pro: 코드 변화 최소.
- Con: sub-graph 가 raw 객체 (MacroReport, RiskReport) 노출 → isolation 의 의미 거의 없어짐. Option 1 보다 더 obscure.

**최종 추천**: **Option 1**. State isolation 의 명목 (raw 객체 격리) 은 지키되, 의도된 input (string blocks) 은 명시적으로 전달.

## Effort

- 코드 변경: ~50 LOC (3 files).
- Test: 기존 `_build_signal_blocks` 호출 위치만 바뀌므로 unit test 거의 그대로. parent 의 새 wiring 에 대한 1-2 integration test.
- Regression: production 의 prompt 가 실제로 변화 → C2 variance/ablation 재측정 필수 (Issue D 의존).
- **~2-3시간 (fix) + ~3-4시간 (재측정, Issue D 와 동시).**

## Dependencies

- **선행 없음** — 본 issue 가 거의 모든 다른 issue 의 *전제*.
- **본 issue 의 해결 후 재측정 필요**: D (anchoring), Mega-PR 의 C3 결정 (β/EMA/hysteresis) 재평가.

---

# Issue B: EMA prior latent bug

## Severity: **LOW** (현재 default no-op, latent)

**Status (2026-05-22, PR `feat/stage2-factor-model`)**: RESOLVED — C1 commit `c0df101` 에서
sub-graph 제거로 prior_research_decision 의 state passing 가 정상화. 추가로 factor model 의
`_blend_factors_with_prior` 가 factor-level EMA 를 직접 다룸 (C4 commit `1aeee32`).

## Problem

C3 (`commit 87fb76d`) 에서 추가한 EMA 인프라:

```python
# research_manager.py
prior_decision: ResearchDecision | None = state.get("prior_research_decision")
smoothed_probs = _blend_with_prior(probs, prior_decision, _EMA_LAMBDA)
```

`state.get("prior_research_decision")` 가 sub-graph 에서 항상 None (InvestDebateState 에 해당 필드 없음). 따라서:
- `_EMA_LAMBDA = 1.0` (default) → identity path 가 trigger. 정상.
- 미래에 `_EMA_LAMBDA < 1.0` 으로 활성화 → prior 가 None 이라 *여전히 identity* (no-op). EMA 작동 안 함.

## Why this matters

현재 default 로는 영향 없음. 그러나:
1. **Issue #11 의 처방이 fire 안 되는 상태**. 미래 cycle transition 시점 variance 측정 후 λ=0.4 활성화하려 해도 작동 안 함 — 활성화 시 *추가* 버그 발견 필요.
2. **Test 가 false positive**: `tests/unit/agents/test_research_manager.py::test_blend_with_lambda_zero_returns_prior_probs` 는 *함수 자체* 의 logic 만 검증. End-to-end (graph 통한 state passing) 는 검증 안 됨.

## Best fix

Issue A 의 Option 1 fix 와 *동일한 변경* 으로 동시 해결. `research_debate_node` 가 `state.get("prior_research_decision")` 을 sub_input 에 명시적으로 전달.

Test 보강:
```python
# tests/integration/test_stage2_e2e_snapshot.py 확장
def test_c3_ema_through_graph_with_prior_works():
    """EMA 가 graph wiring 을 통해서도 작동하는지 e2e 검증."""
    # langgraph invoke 로 research_debate 호출, prior 전달, λ<1.0 임시 설정,
    # 출력의 cycle marginal 이 prior 쪽으로 끌렸는지 assertion.
```

## Effort

- Issue A 의 일부 → 추가 effort 없음.
- Integration test 1개 추가: ~30분.

## Dependencies

- Issue A 와 같이 fix.

---

# Issue C: State isolation 의 redesign 필요 (meta-issue)

## Severity: **MEDIUM** (architectural decision)

**Status (2026-05-22, PR `feat/stage2-factor-model`)**: RESOLVED — C1 commit `c0df101`.
Option 2 (sub-graph 폐기) 채택. factor model 으로 architecture 가 단일 estimator 보다 더
deterministic 한 형태로 redesign — sub-graph isolation 의 가치 자체 사라짐.

## Problem

Sub-graph wrapper 의 원래 의도 (`debate_state.py:14-19`):
> Bull/Bear 토론 폐기. 단일 estimator 노드만 운영하지만, D2 isolation (parent state에 raw 산출물이 안 새도록) 원칙은 유지한다.

현 상태:
- Bull/Bear 토론은 *폐기됨* (Phase 1, `debate_subgraph.py:3`).
- Single estimator 노드만 sub-graph 내부에 있음.
- Sub-graph 의 *유일한 부수효과* 는 입력 state 를 InvestDebateState 로 *축소* 하는 것.
- 이 축소가 Issue A + B 의 원인.

즉 **sub-graph 가 이제 부정적 가치만 가짐** (가치 추가 없이 bug 만 도입).

## Why this matters

설계 의도 (isolation) vs 실제 효과 (silent bug) 가 정반대. 두 가지 결정이 필요:

1. Isolation 원칙을 *유지할 가치가 있는가*?
2. 유지한다면 *어떻게 부수효과 (bug) 없이 유지할 것인가*?

## Best fix

Issue A 의 fix option 들이 이 결정과 직결:

**Option 1 (Pre-process at parent)**: 명목 isolation 유지 + string 전달.
**Option 2 (Sub-graph 폐기)**: Isolation 원칙 폐기.

**추천**: Option 1.

근거:
- Option 2 는 더 단순하나, *미래의 ensemble estimator* (예: 3-estimator + median voting, Issue G 참조) 도입 시 sub-graph 재도입 필요.
- Option 1 의 추가 cost (필드 3개) 는 미미. Option 2 의 단순화 cost 는 *미래 reversibility*.

→ Issue A 의 Option 1 채택 시 본 issue 도 자동 해결.

## Effort

- Issue A 와 동일 — 별도 작업 없음.

## Dependencies

- Issue A 와 일체.

---

# Issue D: macro_quant anchoring 재측정 필요

## Severity: **HIGH** (Mega-PR 의 모든 측정 결과의 generalizability)

**Status (2026-05-22, PR `feat/stage2-factor-model`)**: REPLACED — factor model 으로 Stage 2
architecture 가 LLM 호출 없는 deterministic factor pipeline 으로 redesign. anchoring 측정 자체가
LLM 의존성 분석이었으므로 의미 사라짐 (LLM 호출 0). 새 architecture 의 factor reliability 는
`factor_reliability_audit.py` + `test_factor_indicator_validity.py` 가 검증 (Issue #19).

## Problem

C2 ablation 측정 결과 (`artifacts/2026-05-20/ablation/summary.md`):
- L1(baseline, no_macro) = 0.995
- L1(baseline, perturb_quadrant) = 0.727
- Anchoring ratio = 0.73 (< 2.0 → "pure reformat 아님")

이 측정의 *전제*:
1. baseline = 정상 prompt (Issue A 영향: stage 0 block 이 사실 빈 상태)
2. 2026-05-15 fixture 한 시점 (cycle B-dominant calm 시기)

## Why this matters

### Issue A 수정 후 변화 가능성

Issue A 가 fix 되면 stage 0 block (conditional_stress + kr_residual) 이 prompt 에 *실제로* 들어감. 새 input source 추가 → macro_summary 의 relative weight 변화 가능:
- Baseline 의 distribution 가 변할 수 있음 (다른 신호 추가).
- L1(baseline, no_macro) 가 줄어들 수 있음 (다른 신호가 cycle 추정에 기여).
- L1(baseline, perturb) 도 변할 수 있음.

→ "macro 의존 매우 큼" 결론이 변할 가능성.

### Single fixture 의존성

2026-05-15 는 high-conviction B-cycle (cycle marginal 0.84, 거의 unanimous). LLM 이 의문 없는 시점:
- Variance 측정에서도 0% flip — *flip 할 여지가 없는 시점*.
- Anchoring 측정에서도 macro_quant 의 quadrant 가 *너무 명확* → 다른 신호가 challenge 어려움.

다른 시점:
- **Cycle transition (예: B → C 전환기)**: macro_quant 가 0.55 정도로 불확실. Stage 2 의 LLM judgment 가 중요해질 가능성. Anchoring 낮을 수 있음.
- **Crisis (예: 2020 Q2)**: macro 신호 vs news/market 신호 큰 괴리. Stage 2 의 integration 이 실제 가치 있을 시점.
- **Calm (예: 2017)**: macro 신호 weak (no clear regime). 다른 신호 의존 ↑.

본 PR 의 *모든 결정* (D1-D7) 이 2026-05-15 한 시점에서 도출. Generalization 안 됨.

## Best fix

**Phase 1: Issue A fix 후 같은 fixture (2026-05-15) 재측정**

- 새 prompt (stage 0 block 포함) 로 variance + ablation 재실행.
- 비용: ~$0.5 (variance n=20) + ~$2 (ablation 3 mode × n=3) = ~$2.5.
- Wall: ~10분.
- 비교: pre-fix vs post-fix 의 L1/anchoring/variance 변화.

**Phase 2: 다른 3 시점 측정**

추천 fixture:
- **2024-Q2** (calm goldilocks A cycle): macro 신호 약함, 다른 신호 의존 검증.
- **2022-Q4** (inflation peak, B → C 전환 시작): macro 의 quadrant 가 흔들리는 시점.
- **2020-Q2** (COVID crisis): macro vs market vs news 괴리 큰 시점.

각 fixture 의 archived state 가 있어야 함 (`~/.tradingagents/runs/{date}/`). 없으면 full Stage 1 재실행 필요 (~$0.5/fixture × 3 = $1.5).

총 비용: ~$10. Wall: ~1시간.

**Phase 3: 결과 기반 D1-D5 재평가**

- 모든 fixture 에서 σ ≈ 0 / anchoring 0.7+ → 현 결정 유지.
- Transition / crisis 에서 σ > 3pp 또는 anchoring < 0.4 → D2 (EMA), D5 (input pruning) 재결정.

## Effort

- Phase 1: ~30분 (재실행 + 결과 분석).
- Phase 2: ~2-3시간 (fixture 준비 + 실행 + 분석).
- Phase 3: ~1시간.
- **총 ~4시간**.

## Dependencies

- **선행: Issue A fix**.
- **후속: Mega-PR 의 D1/D2/D5 결정 재평가**.

---

# Issue E: dominant_scenario legacy mapping 의 정보 손실

## Severity: **HIGH** (24-cell framework 의 design intent 미실현)

**Status (2026-05-22, PR `feat/stage2-factor-model`)**: PARTIAL — factor model 으로 24-cell
discrete bucket 자체 사라짐 → 정보 압축의 일부는 자동 해소 (factor → bucket additive
regression 으로 9 factor 의 풍부함 5 bucket 에 보존). `factor_contributions` attribution
이 각 bucket weight 의 factor-level 분해를 제공. 다만 method_picker 는 여전히
dominant_scenario string (factor 의 derive_dominant_scenario) 으로 method 결정 — 24-cell
시절과 동일한 압축 형태 유지. Stage 1 backlog Issue #18 (real β calibration) 후 method_picker
도 factor-aware 로 재설계 가능.

## Problem

`schemas/research.py:184-216` 의 `dominant_scenario` property:

```python
@property
def dominant_scenario(self) -> str:
    if self.tail_marginals.get("T", 0.0) >= 0.30:
        return "global_credit"
    if self.kr_marginals.get("stress", 0.0) >= 0.30:
        return "kr_stress"
    if self.kr_marginals.get("boom", 0.0) >= 0.30:
        return "kr_boom"
    cycle = self.dominant_cycle
    if cycle == "A": return "goldilocks"
    if cycle == "B": return "overheating"
    if cycle == "C": return "broad_recession"
    return "stagflation"  # cycle == "D"
```

→ 24-cell 의 rich 분포 (24 cell × prob + tail/kr marginals) 를 **단일 string** (8개 legacy name) 으로 압축.

**Downstream caller**:
- `method_picker._SCENARIO_METHOD[scenario]` → string 매칭으로 OptimizationMethod 결정
- `macro_conditional_lens._severity_per_scenario(dominant_scenario, ...)` → string 매칭으로 concern level
- `candidate_selector` → log_boost(scenario) 의 fallback (dominant_cell.key 우선)

## Why this matters

### 정보 손실 사례

**예: B_N_F 0.58 + B_N_stress 0.12 + C_N_F 0.08** (2026-05-15 분포):
- dominant_cycle = B
- tail_marginal(T) = ~0.07 (< 0.30)
- kr_marginal(stress) = ~0.13 (< 0.30)
- → dominant_scenario = "overheating"

method_picker 가 "overheating" → HRP 선택.
- 그러나 *B + KR-stress 동시* (B_N_stress 0.12 + KR 의 stress marginal 0.13) 신호가 있는데 무시됨.
- **B + KR stress 의 적절한 처방은 pure overheating 과 다를 수 있음**: 예 fx_commodity 비중을 높이되 KR 비중 더 축소.

### Threshold 0.30 의 magic number

`tail >= 0.30 → global_credit`, `kr_stress >= 0.30 → kr_stress` — 모두 hand-coded 임계. backtest 캘리브레이션 근거 없음.

예: tail = 0.29 vs 0.31 → 결과 (global_credit vs cycle-based label) 완전히 달라짐. Tipping point 의 정당성 부재.

### 24-cell 디자인의 ROI 의문

24-cell framework 의 *유일한* downstream 활용은:
1. `bucket_target` (cell prob 의 *선형결합* → 5 bucket)
2. `candidate_selector` 의 log_boost (dominant_cell.key 으로 3축 boost 합성)

method_picker, risk_lens 는 *legacy string* 만 봄. 즉 24-cell 의 풍부함이 *반쪽만* 활용됨.

## Best fix

**Approach: Downstream caller 가 24-cell 정보 직접 활용**

각 downstream caller 를 수정:

### method_picker 수정

```python
def pick_optimization_method(..., research_decision=None, ...):
    if research_decision is None:
        # fallback path
        return ...

    # 24-cell aware decision
    cell_marg = research_decision.cycle_marginals
    tail_marg = research_decision.tail_marginals
    kr_marg = research_decision.kr_marginals

    # Multi-signal: cycle + tail + kr 조합
    if tail_marg["T"] >= 0.25 and kr_marg["stress"] >= 0.15:
        # 두 위험 동시 → 가장 defensive
        return MethodChoice(MIN_VARIANCE, reasoning="tail + KR stress 동시")
    if tail_marg["T"] >= 0.25:
        return MethodChoice(MIN_VARIANCE, reasoning="tail 우세")
    if kr_marg["stress"] >= 0.25:
        return MethodChoice(MIN_VARIANCE, reasoning="KR stress 우세")
    # cycle 단독
    cycle = research_decision.dominant_cycle
    cycle_prob = cell_marg[cycle]
    if cycle == "B" and kr_marg["stress"] >= 0.12:
        # B + 약한 KR stress → HRP 보다 균형 → RISK_PARITY
        return MethodChoice(RISK_PARITY, reasoning="B + 약한 KR stress")
    # 그 외 standard cycle mapping
    ...
```

### macro_conditional_lens 수정

비슷하게, 24-cell marginal 직접 활용.

### dominant_scenario 의 위치

legacy 호환을 위해 유지 (외부 caller 가 있을 수 있음, 또는 logging/narrative 에서 사용).

## Trade-offs

**Pros**:
- 24-cell 디자인의 실질 가치 회복.
- Multi-signal 조합 (B + KR stress 같은) 의 적절한 처방 가능.

**Cons**:
- 새 코드의 *각 분기마다* threshold 결정 필요 — 새 magic number 도입 위험.
- Backtest 캘리브레이션 없이 hand-coded threshold 를 늘리면 Issue F (calibration 혼재) 가 악화.

**Mitigation**: 새 threshold 추가 시 *항상* artifacts/{date}/decisions.md 에 근거 기록. backtest 또는 ablation 측정 후에만 추가.

## Effort

- 코드: 각 caller 별 ~50-100 LOC. method_picker, macro_conditional_lens 두 곳.
- Test: 새 분기마다 unit test (~10개 신규).
- Calibration: 각 threshold 의 정당화 — ~5-10시간 (Issue F 와 일부 겹침).
- **총 ~15-20시간**.

## Dependencies

- 선행 없음 (independent fix).
- Issue F (calibration) 와 동시 진행 시 효율적.

---

# Issue F: backtest informed vs hand judgment 혼재 (calibration)

## Severity: **HIGH** (false precision)

**Status (2026-05-22, PR `feat/stage2-factor-model`)**: RESOLVED — C6 commit `736971f` 에서
walk-forward calibration infrastructure 구축 (`factor_calibration.py` + `scripts/
calibrate_factor_model.py`). hand-coded `_EQUITY_TOTAL` / `_BOND_TOTAL` / `_KR_SHARE` 등
24-cell playbook 자체가 C5 commit `3353c64` 에서 제거. 대신 9 factor → 5 bucket 의 β
matrix (INITIAL_BETA + walk-forward calibrated) 가 sole source of truth. 다만 *real
historical data* 의 calibration 은 Stage 1 backlog Issue #18 (real fetch + production
β calibration) 후 PR2 에서 수행.

## Problem

`scenario_definitions.py` 의 playbook 파라미터 출처가 mixed:

| 파라미터 | 출처 | 신뢰도 |
|---|---|---|
| `_EQUITY_TOTAL[("A", "N")]` = 0.65 | backtest n=42 | 높음 |
| `_EQUITY_TOTAL[("A", "T")]` = 0.40 | backtest n=16 (1998 LTCM), Sharpe 1.74 | 중간 |
| `_EQUITY_TOTAL[("B", "N")]` = 0.30 | hand (backtest recency-biased) | **낮음** |
| `_EQUITY_TOTAL[("C", "T")]` = 0.10 | backtest n=2 (2008 Q4 lesson) | sample 부족 |
| `_EQUITY_TOTAL[("D", "N")]` = 0.15 | hand (backtest n=2 noise) | **낮음** |
| `_KR_SHARE["F"]` = (0.30, 0.70) | backtest 0/100 corner 무시 + soft nudge | **혼합** |
| `_KR_SHARE["boom"]` = (0.65, 0.35) | hand compromise | **낮음** |
| `_FX_COMMODITY["disinflation", "N"]` = 0.05 | hand (fx 빼는 corner 회피) | **낮음** |
| `_BOND_TOTAL[("A", "N")]` = 0.30 | backtest n=42, 0.35 | 높음 |
| `_BOND_TOTAL[("C", "T")]` = 0.55 | backtest n=2, 0.75 → 2008 Q4 lesson 으로 완화 | **부분 backtest** |
| `_BOND_TIPS_SHARE["disinflation"]` = 0.15 | backtest TIPS-heavy + hand 완화 | **혼합** |

## Why this matters

### False precision

코드는 "_EQUITY_TOTAL[(D,N)] = 0.15" 같이 정확한 숫자를 제시 — 마치 통계적 의미가 있는 것처럼 보임. 실제로는 n=2 의 backtest 잡음 + hand judgment 의 mix. portfolio 가 이 숫자에 *민감* 한 cell (B/D cycle 또는 transient) 일수록 결과의 통계적 의미 손실.

### Cell 별 신뢰도가 천차만별

같은 framework 안에 신뢰도 높은 cell (A-N, A-T) 과 신뢰도 낮은 cell (B-N, D-N) 이 공존. 사용자/reviewer 가 "이 숫자가 어디서 왔는지" 추적 어려움.

### Recency bias

`_EQUITY_TOTAL[("B", "N")] = 0.30` 의 주석: "overheating; backtest recency-biased (2022) ignored". 2022 의 B cycle 이 *유일한* 최근 sample 이라 backtest 결과를 무시하고 hand judgment 채택. 그러나 hand judgment 의 0.30 도 결국 *intuition*.

### Mega-PR Issue #6 의 한계

Issue #6 의 목표는 `_BASELINE` (conditional_stress 의 baseline 데이터) 의 1970-2024 회귀였으나, 본 issue (playbook 자체의 calibration) 는 별개. 둘 다 hand-coded 문제이지만 다른 layer.

## Best fix

**Phase 1: Cell 별 신뢰도 명시화 (가장 시급)**

`scenario_definitions.py` 에 각 파라미터의 *source* + *confidence* 메타데이터 추가:

```python
@dataclass
class PlaybookParam:
    value: float
    source: Literal["backtest", "hand", "backtest_adjusted"]
    sample_size: int  # 0 if hand
    confidence: Literal["high", "medium", "low"]
    note: str = ""

_EQUITY_TOTAL: dict[tuple[CycleQuadrant, TailState], PlaybookParam] = {
    ("A", "N"): PlaybookParam(0.65, "backtest", 42, "high",
                              "goldilocks classic, 1991-2024 quarterly"),
    ("B", "N"): PlaybookParam(0.30, "hand", 0, "low",
                              "backtest recency-biased (2022 only)"),
    # ...
}
```

`make_playbook()` 가 `.value` 만 사용 (현재 코드와 backward-compat).

**Pro**: 즉시 가치 있음 — 사용자가 *어느 cell 이 의문스러운지* 명확히 인식. 코드 변경 최소.

**Phase 2: Backtest infrastructure 구축**

기존 `tradingagents/backtest/` 모듈 (`classify.py`, `optimize.py`) 가 이미 일부 작업. 부족한 부분:
- B cycle (growth+inflation) 의 historical sample 확장 (1970s OPEC 시기, 2000-2008 일부, 2021H2 — 가능한 모든 시점 식별)
- D cycle 의 sample 확장 (1973-80, 2022-23 narrow)
- KR axis 의 historical proxy (KOSPI vs MSCI World, 1990+)
- Tail event 의 일관된 정의 (현재 hand 정의)

**Phase 3: Bayesian shrinkage**

Sample 부족한 cell 의 backtest 결과 → *prior 와 결합*. Prior = 인접 cell 의 평균 또는 macro consensus.

`α / (α + n)` shrinkage: n=2 cell 은 α=5 prior 가 70% weight, n=42 cell 은 prior 가 10% weight.

이미 `playbook_calibration.json` (commit e591006) 에서 이 접근. 그러나 *cell 별 playbook (5 bucket weights)* 에는 아직 적용 안 됨 — 본 issue 의 scope.

## Trade-offs

**Pros**:
- False precision 제거.
- Cell 별 reliability 명확화.
- Phase 2-3 까지 가면 calibration 의 통계적 정당성 확보.

**Cons**:
- Phase 2-3 큰 작업 (~20-40시간).
- backtest infrastructure 확장에 historical data 의존.
- Cycle 정의 자체의 historical assignment 도 의문 (어느 분기가 B cycle? 같은 boundary case).

## Effort

- Phase 1 (메타데이터): ~3-4시간.
- Phase 2 (backtest 확장): ~10-20시간 (data 부족 여부에 따라).
- Phase 3 (shrinkage): ~5-10시간.
- **총 ~20-35시간** — 별도 PR cycle.

## Dependencies

- 선행 없음 (Phase 1 은 독립).
- Phase 2 가 D7 (Mega-PR 의 deferred Issue #6) 의 backtest infrastructure 와 일부 겹침.

---

# Issue G: 단일 deep LLM 호출의 fragility

## Severity: **MEDIUM** (이미 mitigated, 추가 개선 여지)

**Status (2026-05-22, PR `feat/stage2-factor-model`)**: RESOLVED — C4 commit `1aeee32` 에서
Stage 2 의 LLM 호출 완전 제거. factor pipeline (compute_all_factors →
_blend_factors_with_prior → apply_factor_model_with_safety → derive_dominant_scenario /
conviction) 으로 deterministic. sum-to-1 validator fragility / single-LLM noise / retry
fail-hard 모두 N/A.

## Problem

`research_manager.create_research_manager().node()` 가 단일 deep LLM 호출 (`invoke_with_structured_retry` max_retries=1). 즉 *최대 2 attempts* 로 ScenarioProbabilities24 산출.

알려진 fragility:
1. **24-dim sum-to-1**: LLM 이 합 정확히 1.0 맞추기 어려움. C5 에서 tol 0.005 → 0.02 완화하긴 했으나, edge case (sum < 0.95 또는 > 1.05) 여전히 reject.
2. **단일 sample 의 noise**: variance n=20 측정에서 (현재 fixture) σ 작지만, 다른 fixture 에서 클 가능성.
3. **Retry 1회 후 hard fail**: 2회 attempt 모두 실패 시 *전체 pipeline 중단*.

C2 ablation 의 LLM validation 실패율:
- baseline: 0% (3/3)
- variance n=20: 0% (20/20)
- no_macro: 33% (1/3 fail)
- perturb_quadrant: 67% (6/9 fail)

→ perturbed input 일수록 LLM 의 sum-to-1 정확도 ↓.

## Why this matters

1. **Production reliability**: 정상 input 에서는 0% fail rate 이지만, *edge case* (unusual macro 상황) 에서 fail rate 증가 가능. 매주 호출 중 한 번이라도 fail 하면 *그 주의 portfolio 결정 못 함*.
2. **Single-point-of-failure**: 단일 LLM 의 sampling stochasticity 가 전체 결과 결정. ensemble 의 *분산 효과* 없음.
3. **No fallback**: LLM 실패 시 hardcoded fallback (예: prior_research_decision 사용) 없음.

## Best fix

**Option 1: Auto-normalize sum (작은 fix)**

`ScenarioProbabilities24._sum_to_one` validator 가 합 [0.85, 1.15] 범위면 *자동 normalize*, 그 외만 reject:

```python
@model_validator(mode="before")
@classmethod
def _normalize_sum(cls, data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    cell_values = {k: data.get(k, 0) for k in ALL_CELLS if k in data}
    total = sum(cell_values.values())
    if not (0.85 <= total <= 1.15):
        # 너무 멀면 reject (LLM 출력 망가짐)
        raise ValueError(f"Cell probabilities sum {total} outside [0.85, 1.15]")
    # 자동 normalize
    if abs(total - 1.0) > 1e-9:
        for k, v in cell_values.items():
            data[k] = v / total
    return data
```

**Pros**: 즉시 가치, retry 률 ↓. Issue B 의 sum-to-1 follow-up.
**Cons**: 큰 sum 오차 (예: 0.7) 는 LLM 출력이 망가진 것 — 자동 normalize 가 위험할 수 있음.

**Option 2: Retry 횟수 증가 + exponential backoff**

`invoke_with_structured_retry` 의 max_retries 를 1 → 3, retry 시 temperature 변경.

**Pros**: 단순.
**Cons**: latency / cost 증가, 근본 해결 아님.

**Option 3: Ensemble (3-estimator + median voting)**

3 개의 LLM 호출 (각각 다른 temperature 또는 seed 또는 model) → cell 별 median 으로 합성.

```python
def estimator_ensemble(messages, n=3):
    samples = []
    for i in range(n):
        try:
            sample = invoke_with_structured_retry(...)
            samples.append(sample.as_dict())
        except Exception:
            continue
    if len(samples) < 2:
        raise ValueError(f"Ensemble failed: {len(samples)} valid samples")
    # Median per cell
    median = {k: statistics.median(s[k] for s in samples) for k in ALL_CELLS}
    # Renormalize (median 합 != 1)
    total = sum(median.values())
    median = {k: v/total for k, v in median.items()}
    reasoning = "Ensemble median of {n} samples"
    return ScenarioProbabilities24(**median, reasoning=reasoning)
```

**Pros**: noise 감소, single-failure 회피.
**Cons**: cost 3x, latency 3x, *median* 이 24-cell 분포로 의미 있는지 통계적 검증 필요.

**Option 4: Hybrid — deterministic fallback**

LLM 실패 시:
```python
def fallback_scenario_probs(macro_report) -> ScenarioProbabilities24:
    """LLM 실패 시 macro_quant 의 regime 만으로 24-cell 산출."""
    quadrant = macro_report.regime.quadrant  # "growth_inflation" 등
    cycle = {"growth_disinflation": "A", "growth_inflation": "B",
             "recession_disinflation": "C", "recession_inflation": "D"}[quadrant]
    # cycle 에 80%, tail=N 95%, kr=F 80% (default prior)
    kwargs = {k: 0.0 for k in ALL_CELLS}
    kwargs[f"{cycle}_N_F"] = 0.80
    # 나머지 분배
    ...
    return ScenarioProbabilities24(**kwargs, reasoning="LLM fallback")
```

**Pros**: hard fail 없음, 항상 portfolio 산출 가능.
**Cons**: fallback 결과의 신뢰도 낮음. Issue D (anchoring) 의 *극단* — Stage 2 의 가치 거의 없는 path.

**최종 추천**: **Option 1 + Option 4 동시 채택**.

- Option 1 (auto-normalize) 으로 70% 의 LLM noise 흡수.
- Option 4 (deterministic fallback) 로 *마지막 safety net*. fallback fire 시 warning log.

Option 3 (ensemble) 은 cost 3x 부담 — 별도 PR cycle 에서 evaluation 후 결정.

## Trade-offs

- Option 1: 무리 없는 개선.
- Option 4: fallback fire 빈도 모니터링 필요. 자주 fire 면 LLM 자체 문제 → 별도 fix.

## Effort

- Option 1: ~1시간 + test 2-3개.
- Option 4: ~2시간 + test 2-3개 + integration 검증.
- **총 ~4시간**.

## Dependencies

- Independent.

---

# Issue H: Sharpening 제거 후에도 24-cell cross-effect 활용 미흡

## Severity: **HIGH** (design intent unfulfilled)

**Status (2026-05-22, PR `feat/stage2-factor-model`)**: REPLACED — 24-cell framework 자체
폐기 (C5 commit `3353c64`). factor model 의 9 factor 가 *직접* bucket weight 결정
(additive regression + QP projection) — winner-take-all 의 정보 손실 path 자체 사라짐.
method_picker 의 cycle-aware 결정은 Issue E (PARTIAL) 의 후속.

## Problem

C3 에서 β=1 고정 → `effective_cycle_marginals == cycle_marginals`. 24-cell 의 cross-effect (B_N_F + B_N_stress + C_N_F 등 다양한 cell 의 weighted contribution) 가 `bucket_target` 에 *수학적으로* 반영됨.

그러나 **downstream 은 여전히 dominant_scenario string 만 사용**:
- `method_picker._SCENARIO_METHOD["overheating"]` → HRP
- `macro_conditional_lens._severity_per_scenario("overheating", ...)` → concern level

즉:
- B_N_F 0.58 + B_N_stress 0.12 → method = HRP (B-overheating 처방)
- B_N_F 0.58 + C_N_F 0.20 → method = HRP (마찬가지)
- B_N_F 0.40 + C_N_F 0.30 → method = HRP (cycle B 가 marginal 최대 — but 박빙)

세 경우의 method 가 동일 — 24-cell 의 *세부 distribution* 무시.

## Why this matters

이는 Issue E (legacy mapping 정보 손실) 의 *구체적 사례*. 별도 항목으로 분리한 이유:

**24-cell 디자인의 *원래 의도***:
- `dominant_cycle` 박빙 시 (예 B 0.40 vs C 0.35) 단순 winner-take-all 보다 *mixed strategy* 가 적절.
- `bucket_target` 은 이미 mixed (선형결합). 그러나 `method_picker` 는 winner-take-all.

**구체적 harm**:
- 2026-05-15 의 B 84% dominance → method_picker 의 결정이 *very robust* (다른 cell weight 작음).
- Transition 시점 (예: B 50% / C 40%): method_picker 가 여전히 B 처방 (HRP). 그러나 *50/50 가까운 박빙* 은 hybrid (RISK_PARITY) 또는 conservative (MIN_VARIANCE) 가 적절할 수 있음.
- Conviction "medium" (0.35-0.55) 일 때 method 가 HRP → RISK_PARITY 로 downgrade 되긴 함 (`method_picker.py:82-83`). 그러나 *어떤 alternative cycle* 인지 무시 — A-near vs C-near 에 따라 alternative 가 다름.

## Best fix

**Option 1: method_picker 에 cycle marginal 직접 활용 (Issue E 의 specific)**

```python
def pick_optimization_method(..., research_decision=None, ...):
    cycle_marg = research_decision.cycle_marginals
    dom_cycle = research_decision.dominant_cycle
    dom_prob = cycle_marg[dom_cycle]

    # Entropy 또는 박빙 detection
    second_cycle = max((c for c in cycle_marg if c != dom_cycle),
                       key=lambda c: cycle_marg[c])
    second_prob = cycle_marg[second_cycle]
    margin = dom_prob - second_prob

    if margin < 0.15:
        # 박빙 — conservative
        return MethodChoice(MIN_VARIANCE, reasoning=f"박빙: {dom_cycle}={dom_prob:.0%} vs {second_cycle}={second_prob:.0%}")
    if margin < 0.30:
        # medium conviction — RISK_PARITY (balanced)
        ...
    # 그 외 standard mapping
```

**Option 2: Effective method = weighted average of per-cell method**

각 cell 의 *적절한 method* 정의 → cell prob 으로 weighted vote:

```python
_CELL_METHOD_AFFINITY: dict[str, dict[OptimizationMethod, float]] = {
    "A_N_F": {HRP: 1.0},
    "A_T_F": {MIN_VARIANCE: 0.8, HRP: 0.2},
    "B_N_F": {HRP: 0.7, RISK_PARITY: 0.3},
    "B_N_stress": {MIN_VARIANCE: 0.5, RISK_PARITY: 0.5},  # B+KR stress
    "C_N_F": {MIN_VARIANCE: 0.6, RISK_PARITY: 0.4},
    "C_T_F": {MIN_VARIANCE: 1.0},
    "D_N_F": {RISK_PARITY: 0.7, MIN_VARIANCE: 0.3},
    # ...
}

# method 점수 합산
method_scores = defaultdict(float)
for cell_key in ALL_CELLS:
    p = research_decision.scenario_probabilities.as_dict()[cell_key]
    for method, affinity in _CELL_METHOD_AFFINITY.get(cell_key, {}).items():
        method_scores[method] += p * affinity
chosen = max(method_scores, key=method_scores.get)
```

**Pros**: 24-cell 의 풍부함 fully 활용.
**Cons**: 새 hand-coded table (`_CELL_METHOD_AFFINITY`) — Issue F 의 calibration 문제 재발. 24 × 3-4 method = ~80 affinity 값.

**최종 추천**: **Option 1** (entropy-based, threshold 적음) → Issue F calibration 작업 후 Option 2 평가.

## Effort

- Option 1: ~3-4시간 + test 5-10개.
- Option 2: ~10-15시간 + calibration ~10시간 = ~25시간.
- Recommended (Option 1): ~4시간.

## Dependencies

- Issue E 와 동시 진행 (같은 caller 수정).
- Issue F (calibration) 의 method affinity table 작업과 별개.

---

# Issue I: Stage 2 → Stage 3 hand-off 의 정보 압축 미측정

## Severity: **MEDIUM** (correctness vs efficiency trade-off 불명)

**Status (2026-05-22, PR `feat/stage2-factor-model`)**: RESOLVED — factor model 의
`factor_contributions` attribution 이 각 bucket weight 의 9 factor-level 분해를 명시.
philosophy.md narrative 가 factor z + top contributor 로 재작성 (C7 commit `8d5a6b6`).
information content 압축의 정도가 *측정 가능* + *audit 가능*.

## Problem

Stage 2 출력의 information content:
- 24 cell × float (24 numbers) = ~24 floats of info
- 4 marginals (cycle 4 + tail 2 + kr 3) = 9 floats
- dominant_cell coord + prob = ~2 metadata
- conviction (3-level) + beta + effective marginals = ~6 metadata
- reasoning (≤1500 chars) = ~250 token of qualitative

→ 총 *~40 numbers + 1500 chars* 정보.

Stage 3 method_picker 가 *사용* 하는 정보:
- dominant_scenario (1 of 8 strings) = 3 bits
- conviction (1 of 3) = ~1.6 bits
- → **~5 bits**

candidate_selector:
- dominant_cell.key (1 of 24) = ~4.6 bits 또는 dominant_scenario fallback
- bucket_target weights (5 floats) = ~24 bits effective

risk_judge:
- 전체 research_decision (full object) 받음. 그러나 *어느 필드를 보는지* 코드 분석 필요.

→ Stage 2 의 input 정보 (24-dim simplex 의 모든 mass) → method_picker 에 ~5 bits 만 전달. 거의 *winner-take-all 압축*.

## Why this matters

1. **Stage 2 의 ROI 의문**: $0.15 + 10s 의 LLM 호출이 ~40 numbers 생성하지만 *그 중 ~5 bits 만 downstream method 결정에 영향*. 나머지는 (bucket_target 의 weight + candidate_selector 의 boost 에) 부분 활용 또는 무시.
2. **압축의 정당성 미검증**: 5 bits 압축이 *정보 손실 없이 충분* 한가? 또는 *과도한 압축* 인가? 측정 안 됨.
3. **Issue H 의 일반화**: 24-cell cross-effect 가 method 결정에 *전혀* 반영 안 됨 — 정보 압축의 극단.

## Best fix

**Measurement first (분석 → 처방)**:

24-cell 정보의 *각 분기* 가 final portfolio (weights) 에 미치는 *민감도* 측정:

```python
# 단일 cell 만 +Δ 했을 때 final weights 의 L1 change 측정
def cell_sensitivity(cell_key, delta=0.05):
    base_probs = ScenarioProbabilities24(...)  # 2026-05-15 fixture
    perturbed = base_probs.model_copy(update={cell_key: getattr(base_probs, cell_key) + delta})
    # renormalize, run full Stage 2-3 pipeline, compare weights
    return l1(base_weights, perturbed_weights)

# 24 cell × sensitivity → ranking
```

높은 sensitivity → 그 cell 의 정보가 *손실되면 portfolio 변화 큼*.
낮은 sensitivity → 압축해도 무관 (예: B_T_stress 같이 transient).

**측정 결과 기반 결정**:
- Sensitivity 가 dominant cell 에 집중 → 현 압축 (dominant_scenario) 정당화.
- Sensitivity 가 분산 → Issue E/H 의 cross-effect 활용 필수.

## Effort

- Measurement: ~5시간 (perturbation × 24 cell, pipeline 재실행).
- 결과 분석 + 결정: ~3시간.
- 결정에 따른 코드 수정: Issue E/H 와 통합.
- **측정만 ~8시간**.

## Dependencies

- Issue A fix 후 (정확한 baseline 위해).
- Issue E/H 의 *결정 근거* 로 사용.

---

# Issue J: ScenarioProbabilities24 의 reasoning 1500자 제한

## Severity: **LOW** (현재 LLM 출력 형식 결과)

**Status (2026-05-22, PR `feat/stage2-factor-model`)**: OBSOLETE — Stage 2 LLM 호출 0 →
reasoning field 자체 사라짐. ResearchDecision 의 `reasoning` 가 factor 의 deterministic
narrative 로 대체 (factor z + top contributors 의 정형 출력).

## Problem

`ScenarioProbabilities24.reasoning: str = Field(max_length=1500, description=...)`.

LLM 이 *24 cell* 의 distribution 근거를 1500자에 담아야 함. 실제 출력 (2026-05-15 sample):

```
"D1: Macro Quant strongly points to B growth+inflation: regime=growth_inflation 0.84, CPI 3.9%
with 3m ann 7.3% accelerating, GDPNow +4.0, CFNAI near expansion, Sahm false. ...
D2: mostly N. Tail block calm/neutral: ...
D3: mostly F, but KR stress residual is meaningful. ...
Top cells: B_N_F dominant baseline; B_N_stress second from KR-specific spread/tier weakness;
B_N_boom third from strong exports/CLI under non-tail backdrop."
```

→ axis 별 marginal + top 3 cell 근거만. 나머지 21 cell 의 *왜 그 값인가* 는 표현 안 됨.

## Why this matters

1. **Audit 어려움**: 특정 cell (예: D_N_stress 0.02) 의 근거가 reasoning 에 없음. "왜 D_N_stress 가 0.02 가 아니라 0.05 면 안 되나?" 의문 답 불가.
2. **21 cell 의 prob 가 *그럴듯하게 떨어뜨림***: LLM 이 axis marginal 만 신경 쓰고 *cell prob 은 그 marginal 의 product 정도* 로 채우는 경향. 즉 *cell-level resolution 의 의미가 약함*.

## Best fix

**Option 1: Reasoning 길이 ↑ (단순)**

`max_length=1500` → `max_length=3500`. cell 별 추가 근거 가능.

**Pros**: 즉시. **Cons**: 비용 (token), narrative noise.

**Option 2: Structured reasoning 분리**

reasoning 을 4 field 로 분리:
- `cycle_rationale: str ≤ 500` (D1 marginal 근거)
- `tail_rationale: str ≤ 300` (D2)
- `kr_rationale: str ≤ 300` (D3)
- `cell_overlay_rationale: str ≤ 500` (top/transient cell 의 특이 근거)

**Pros**: 명시적 structure, LLM 에게 *각 axis 정당화 의무화*.
**Cons**: schema 변경 (downstream caller 영향).

**Option 3: 측정 driven*

Issue I 의 sensitivity 측정 결과:
- Cell 별 sensitivity 높은 cell *만* reasoning 의무화.
- 나머지 cell 은 schema 단순화 (예: 4 cycle × {N,T} = 8 의 lower-resolution distribution).

→ Issue I 의 결과 의존.

**최종 추천**: **단기 Option 1 (1500 → 2500)** + **중기 Option 3 (Issue I 후 평가)**.

## Effort

- Option 1: ~30분.
- Option 2: ~2시간 + downstream 영향 검증.
- Option 3: Issue I 결과 의존, ~10시간 cumulative.

## Dependencies

- Option 3 ← Issue I.

---

# Issue K: Sub-graph 의 message channel 미사용

## Severity: **LOW (cosmetic)**

**Status (2026-05-22, PR `feat/stage2-factor-model`)**: RESOLVED — C1 commit `c0df101` 에서
sub-graph 자체 제거. InvestDebateState 의 messages 필드 N/A.

## Problem

`InvestDebateState(MessagesState)` 는 langgraph 의 `messages: list[BaseMessage]` accumulator 를 상속. 그러나:

```python
sub_input = InvestDebateState(
    messages=[],
    ...
)
```

`messages=[]` 로 초기화하고 *어디서도 messages 가 채워지지 않음*. Estimator 노드도 LLM 호출 결과를 messages 에 append 안 함.

## Why this matters

1. **Bull/Bear 토론 폐기의 잔재**: 원래 messages 는 turn-by-turn debate 의 channel. single estimator 로 전환 후 의미 없음.
2. **Schema 의 misrepresentation**: `MessagesState` 상속이 *현재 의도와 안 맞음*. reviewer 가 "토론 구조가 있는 줄" 오해.
3. **Sub-graph 폐기 또는 redesign 시 정리 필요**.

## Best fix

Issue A 의 Option 1 fix 와 동시:
- `InvestDebateState(MessagesState)` → `InvestDebateState(TypedDict)` 또는 직접 정의.
- `messages` 필드 제거.

또는 Issue A 의 Option 2 (sub-graph 폐기) 채택 시 자동 해결.

## Effort

- ~30분 (schema 변경 + import 정리).

## Dependencies

- Issue A 의 fix 결정 후 같이.

---

# Issue L: `_build_signal_blocks` 의 silent exception 처리

## Severity: **LOW** (current state 에서 trigger 안 됨)

**Status (2026-05-22, PR `feat/stage2-factor-model`)**: RESOLVED — `_build_signal_blocks`
및 conditional_stress / kr_residual_signals 의존 path 가 factor model 으로 대체되며 사라짐.
factor 의 각 estimator (e.g., `_compute_growth_surprise`) 의 None handling 은 `_safe_get`
helper 으로 명시적 — silent exception swallowing 없음.

## Problem

```python
def _build_signal_blocks(state) -> tuple[str, str]:
    macro_report = state.get("macro_report")
    risk_report = state.get("risk_report")
    if macro_report is None or risk_report is None:
        return ("", "")
    try:
        # ... regime quadrant 추출 + stress/kr 계산 ...
        return (stress.to_prompt_block(), kr.to_prompt_block())
    except Exception:        # ← 모든 예외 silent
        return ("", "")
```

모든 exception 을 catch → 빈 string 반환. logging 도 없음.

## Why this matters

1. **현재 상태**: macro_report/risk_report 항상 None (Issue A) → early return → try block 도달 안 함 → exception 자체 안 발생.
2. **Issue A fix 후**: try block 이 도달. 실제 exception 발생 가능 (예: regime 객체의 schema 변경, quadrant 가 잘못된 값). exception silent 처리 → debug 어려움. Stage 0 block 이 빈 채로 LLM 호출 — silent degradation.

## Best fix

```python
def _build_signal_blocks(state) -> tuple[str, str]:
    macro_report = state.get("macro_report")
    risk_report = state.get("risk_report")
    if macro_report is None or risk_report is None:
        logger.warning("research_manager: macro/risk report missing, skip signal cleaning")
        return ("", "")
    try:
        # ... 계산 ...
        return (stress.to_prompt_block(), kr.to_prompt_block())
    except Exception as e:
        logger.exception(
            "research_manager: signal cleaning failed (regime=%s) — falling back to empty blocks",
            getattr(getattr(macro_report, "regime", None), "quadrant", "?"),
        )
        return ("", "")
```

또는 더 엄격하게 — exception 시 *raise* (silent degradation 회피):
```python
    try:
        return (stress.to_prompt_block(), kr.to_prompt_block())
    except Exception:
        # Stage 0 block 부재는 진짜 design 위반 — 빠르게 fail
        raise
```

**추천**: 점진적 — 첫 fix 에서는 logging 추가 (debug 가능), 운영 안정 후 strict raise 로 전환.

## Effort

- ~30분.

## Dependencies

- Issue A 의 fix 후 (그 전엔 trigger 안 됨).

---

# Issue M: cell key vs dominant_scenario 의 inconsistency

## Severity: **MEDIUM** (correctness 의문, edge case)

**Status (2026-05-22, PR `feat/stage2-factor-model`)**: RESOLVED — C5 commit `3353c64` 에서
24-cell framework 자체 제거. `dominant_cell` 필드 사라지고 `dominant_scenario` 가 factor 의
`derive_dominant_scenario` 가 단일 source 로 설정 (factor model 의 `_legacy_*` helper 폐기).
edge case (cell key vs scenario inconsistency) 의 가능성 자체 사라짐.

## Problem

`dominant_cell.key` 와 `dominant_scenario` 의 결정 logic 이 *독립적*:

```python
# dominant_cell: max(24 cell probabilities)
dominant_key = max(raw_prob_dict, key=lambda k: raw_prob_dict[k])

# dominant_scenario: tail/kr override → cycle fallback
def dominant_scenario(self) -> str:
    if self.tail_marginals.get("T", 0.0) >= 0.30:
        return "global_credit"
    if self.kr_marginals.get("stress", 0.0) >= 0.30:
        return "kr_stress"
    if self.kr_marginals.get("boom", 0.0) >= 0.30:
        return "kr_boom"
    # cycle-based
    cycle = self.dominant_cycle  # = max(cycle_marginal)
    ...
```

**Edge case**:
- B_N_F = 0.40, C_T_F = 0.25, C_T_stress = 0.20, ... 같은 분포
- dominant_cell = B_N_F (max cell)
- tail_marginal(T) = 0.25 + 0.20 + ... = potentially 0.30+
- → dominant_scenario = "global_credit"

→ allocator 가 *dominant_cell ("B_N_F", overheating 시그널)* 와 *dominant_scenario ("global_credit", defensive 시그널)* 를 동시에 받음. 두 신호가 *반대 방향*.

`portfolio_allocator.py:79-85` 의 fallback chain:
```python
if cell is not None:
    dominant_scenario = cell.key  # "B_N_F" 사용
else:
    dominant_scenario = getattr(research_decision, "dominant_scenario", None)  # fallback
```

→ allocator 는 항상 `cell.key` 사용 (B_N_F). 그러나 method_picker 는 `dominant_scenario` (global_credit) 사용 → method = MIN_VARIANCE.

**Result**: allocator 의 candidate_selector 는 *B-overheating boost*, method_picker 는 *defensive MIN_VARIANCE*. 일관성 깨짐.

## Why this matters

- Production 에서 *동시에* 두 신호 다른 case 가 *얼마나 자주* 발생? 측정 안 됨.
- 2026-05-15 case 는 명확한 B-dominant 라 두 신호 일치. 다른 시점 (tail / kr 가 cycle 과 별개로 우세한 경우) 에서 inconsistency 발생.

## Best fix

**Option 1: dominant_scenario 의 logic 명확화 — cycle priority + override 명시**

현재 logic 의 *모호성* 제거:
```python
@property
def dominant_scenario(self) -> str:
    """우선순위:
    1. tail_marginal(T) ≥ 0.30 AND dominant_cycle != C → global_credit
       (C-T 는 cycle-recession + tail = broad_recession 보다 global_credit 이 적절)
    2. kr_stress ≥ 0.30 → kr_stress
    3. kr_boom ≥ 0.30 → kr_boom
    4. cycle-based mapping
    """
    # ...
```

**Option 2: dominant_cell 과 dominant_scenario 의 일관성 강제**

`map_probs_to_bucket()` 후처리에서:
- dominant_cell 의 cycle/tail/kr 좌표가 dominant_scenario 의 mapping 과 일치 검증.
- 불일치 시 둘 중 *어느 쪽이 우선* 인지 명시 (예: dominant_cell 우선, dominant_scenario 가 그것의 함수).

```python
def dominant_scenario(self) -> str:
    c, t, kr = self.dominant_cell.cycle, self.dominant_cell.tail, self.dominant_cell.kr
    if t == "T":
        return "global_credit"
    if kr == "stress":
        return "kr_stress"
    if kr == "boom":
        return "kr_boom"
    # cycle-based
    return {"A": "goldilocks", "B": "overheating",
            "C": "broad_recession", "D": "stagflation"}[c]
```

→ dominant_cell 의 좌표로부터 *유도*. 두 값이 항상 consistent.

**Trade-off**: Option 2 는 *cell-prob 의 노이즈* 에 dominant_scenario 도 노출됨. tail_marginal 0.30 같은 *aggregate threshold* 의 의도 (개별 cell prob 의 노이즈 평균화) 가 사라짐.

**Option 3: downstream 의 multi-signal 활용 (Issue E/H 와 통합)**

dominant_scenario 자체 폐기. method_picker, risk_lens 등이 24-cell marginal 직접 사용.

## 최종 추천

- **단기 (current PR cycle 후속)**: Option 1 (logic 명확화 + 우선순위 정의).
- **중기 (Issue E/H 와 통합)**: Option 3 (legacy 폐기).

## Effort

- Option 1: ~2시간 + test 추가.
- Option 3: Issue E/H 와 통합 ~15-20시간.

## Dependencies

- Issue E (legacy mapping) 와 같이 결정.

---

# 수정 우선순위 + 의존 그래프

## 우선순위 (5/28 대회 ↔ 후속 작업 분리)

### Tier 1 (즉시 — 다음 PR cycle, 5/28 전)

| # | Issue | 이유 |
|---|---|---|
| 1 | **A** (signal cleaning silent bug) | CRITICAL. 모든 다른 measurement 의 전제. 본 fix 없이 Issue D 재측정 불가. |
| 2 | **B** (EMA prior latent bug) | A 와 같은 fix 로 동시 해결. cost 0 추가. |
| 3 | **C** (state isolation redesign) | A 의 fix option 결정과 일체. 추가 작업 없음. |
| 4 | **L** (silent exception) | A 의 fix 후 trigger 가능. 작은 logging fix. |
| 5 | **K** (message channel) | A 의 schema 변경 시 동시 정리. cosmetic. |

→ **Single PR cycle (~3-4시간)** 으로 5개 issue 모두 해결.

### Tier 2 (재측정 + 결정 재평가, 5/28 전 가능)

| # | Issue | 이유 |
|---|---|---|
| 6 | **D** (anchoring 재측정) | Tier 1 fix 후 필수. Mega-PR D1-D5 결정 generalize 검증. |
| 7 | **I** (정보 압축 측정) | D 측정 과정에서 같이 데이터 수집 가능. |
| 8 | **G** (LLM fragility) | sum-to-1 auto-normalize + fallback. ~4시간. |
| 9 | **M** (cell/scenario inconsistency) | logic 명확화. ~2시간. |

→ **Single PR cycle (~8-10시간)**.

### Tier 3 (구조 개선, 5/28 후)

| # | Issue | 이유 |
|---|---|---|
| 10 | **E** + **H** (downstream 24-cell 활용) | Architecture 개선. ~15-20시간. |
| 11 | **F** (calibration) | Phase 1 메타데이터 (~4시간), Phase 2-3 backtest 확장 (~20-30시간). |
| 12 | **J** (reasoning 길이/structure) | Phase 1 (1500 → 2500) ~30분, Phase 3 (Issue I 후) cumulative. |
| 13 | Mega-PR Issue #6 (D7 deferred) | F 의 Phase 2 와 같이 진행. |

→ **여러 PR cycle (~50-80시간)**.

## 의존 그래프

```
                A (signal cleaning fix)
                |
                ├── B (EMA prior fix, A 와 동시)
                ├── C (isolation redesign, A 와 일체)
                ├── L (silent exception, A 후)
                ├── K (message channel, A 후)
                │
                ▼
                D (anchoring 재측정)
                |
                ├── I (정보 압축 측정, D 와 동시)
                │
                ▼
                E + H (downstream 24-cell 활용)
                |
                ├── F (calibration, 독립 진행 가능)
                ├── M (legacy logic 명확화, E 와 동시)
                ├── J (reasoning, I 결과 의존)
                │
                ▼
                Mega-PR D1-D5 재평가 (필요 시)
```

## 5/28 대회 전 권장 작업

**Minimum viable**:
- Tier 1 (A/B/C/L/K) — ~4시간.
- Tier 2 의 D (재측정만) — ~4시간.

**합산 ~8시간** 으로 Mega-PR 의 silent bug 해소 + 결정 재검증.

**Stretch goal**:
- Tier 2 의 G (LLM robustness) — ~4시간.

**5/28 후로**:
- E/H/F/M/I/J — 구조 개선 작업.

---

# 참고

- Mega-PR (해소한 Issue #5-#11): `docs/superpowers/specs/2026-05-20-stage2-bottleneck-fix-design.md`
- Mega-PR 의 decisions: `artifacts/2026-05-20/decisions.md`
- Mega-PR 의 측정 결과: `artifacts/2026-05-20/{variance,ablation}/`
- 본 audit 후속 PR 의 spec/plan 위치: `docs/superpowers/specs/2026-05-22-stage2-pipeline-fix-design.md` (작성 예정), `docs/superpowers/plans/2026-05-22-stage2-pipeline-fix.md` (작성 예정)

---

## Resolution Summary (PR `feat/stage2-factor-model`, 2026-05-22)

| Issue | Title | Status | Commit |
|---|---|---|---|
| A | Signal cleaning silent bug | RESOLVED | c0df101 (C1) |
| B | EMA prior latent | RESOLVED | c0df101 (C1) |
| C | State isolation redesign | RESOLVED | c0df101 (C1) |
| D | Anchoring measurement | REPLACED | architecture 변경 |
| E | Legacy mapping 정보 손실 | PARTIAL | factor_contributions 추가 |
| F | Calibration 혼재 | RESOLVED | 736971f (C6) |
| G | LLM fragility | RESOLVED | 1aeee32 (C4) |
| H | Cross-effect downstream | REPLACED | factor model 직접 |
| I | 정보 압축 | RESOLVED | factor_contributions |
| J | reasoning 1500자 | OBSOLETE | LLM 호출 없음 |
| K | Message channel | RESOLVED | c0df101 |
| L | Silent exception | RESOLVED | _safe_get None handling |
| M | Cell key inconsistency | RESOLVED | 3353c64 (C5) |

13 issue 모두 처리. **PARTIAL (E) + REPLACED (D, H) + OBSOLETE (J)** 는 architecture 변경
의 결과 — 별도 후속 작업 불요.
