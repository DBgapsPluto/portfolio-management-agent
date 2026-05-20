# Stage 2 병목 7-issue 일괄 해소 — 설계 (Spec)

- **작성일:** 2026-05-20
- **branch:** `feat/stage2-bottleneck-fixes` (base: `feat/db-gaps-redesign`)
- **목표 완료일:** 2026-05-28 (대회 투자계획서 제출일) 이전, 가급적 2026-05-20 당일
- **PR 단위:** Mega-PR 1개 (commit 5개로 atomic 조직)
- **대상 코드베이스:** `tradingagents/agents/managers/research_manager.py`, `tradingagents/skills/research/*`, `tradingagents/schemas/research.py`, `tradingagents/skills/risk/conditional_stress.py`, `tradingagents/skills/risk/kr_residual_signals.py`

---

## 1. 배경

Stage 2 (Research) 는 24-cell Cartesian product framework로 재설계되어 commit `3ede5cf`에서 도입되었다. 이후 LLM variance 측정 인프라(commit `dce4a63`), calibration 모듈(`e591006`)이 추가되며 quant관점 sanity check 환경이 갖춰졌다. 본 spec는 사용자와의 cold quant-trader review 세션에서 식별된 7개 병목을 단일 PR cycle로 해소한다.

### 1.1 식별된 7 병목 (followup_issues.md Issue #5~#11 등록 예정)

| # | 병목 | Severity | 처방 카테고리 |
|---|---|---|---|
| 5 | β-sharpening 이 24-cell을 1-cell로 짓누름 | High | 알고리즘 변경 (분석 의존) |
| 6 | D2/D3 conditional decontamination 의 baseline σ가 hand-coded | High | 데이터 실측 교체 |
| 7 | `dominant_scenario` legacy mapping 이 B(growth+inflation)를 stagflation 으로 mis-label | **Critical (production bug)** | 1줄 fix + downstream branch |
| 8 | Stage 2의 incremental information value 미측정 — macro_quant reformatter 가능성 | Medium | 분석으로 결정 |
| 9 | 24-dim simplex LLM sampling noise 의 portfolio 흡수 — variance 미측정 | High | 측정 → 처방 |
| 10 | Prompt 의 ~50%가 고정인데 prompt caching 미사용 | Low | 인프라 |
| 11 | Time-series smoothing 없음 — 매주 LLM noise 가 portfolio churn 유발 | High | 알고리즘 추가 |

### 1.2 작업 원칙

- **분석 → 처방 순서 (issue #5, #9, #11)** — variance와 ablation 결과로 β 함수의 모양과 EMA blend 비율(λ)을 정한다. magic number 추가 금지.
- **즉시 fix vs 분석 의존 분리** — Issue #7은 한 줄 production bug, 분석 없이 가장 먼저.
- **Regression test 필수 (memory feedback 정책)** — 단위 test + e2e snapshot 양쪽.
- **5/28 대회 일정 보호** — 각 commit independently revertable, 산출물 재생성(C5)은 diff 검증 후.

---

## 2. PR / Commit 구조

Branch: `feat/stage2-bottleneck-fixes` (현재 작업 branch `feat/db-gaps-redesign`에서 분기).

### C1 `fix(stage2): B→stagflation mis-label 분리, overheating label 도입`

**해결 이슈:** #7

**변경:**
- `tradingagents/schemas/research.py` 의 `dominant_scenario` property 수정:
  - `cycle == "D"` → `"stagflation"`
  - `cycle == "B"` → `"overheating"` (신규 label)
  - 기존 `cycle in ("B", "D") → "stagflation"` 제거
- `tradingagents/agents/allocator/method_picker.py` 의 case 분기에 `overheating` 추가:
  - 기존 stagflation case (risk_parity) 와 분리
  - overheating 처방: 후보 1순위는 mean-variance 또는 BL — 분석 검토 후 결정 (default: HRP, 분산 친화)
- 7-scenario legacy alias 유지 (downstream 호환).

**Test:**
- `tests/unit/skills/test_research_scenario_mapper.py` 에 `dominant_scenario` 매핑 7개 fixture (각 cycle × tail 조합).
- `tests/unit/agents/test_method_picker.py` 에 overheating branch test.

**docs:**
- 같은 commit 에 `docs/followup_issues.md` 의 Issue #5~#11 추가 (현재까지 분석을 기록).

### C2 `chore(stage2): variance + ablation 측정 인프라`

**해결 이슈:** #9, #8 (분석 단계)

**변경:**
- `scripts/measure_llm_variance.py`:
  - `--n` default 20 으로 (기존 5)
  - 진행률 로그 추가 (n/N format)
  - 백그라운드 실행 친화: tqdm 또는 단순 print
- `scripts/measure_stage2_ablation.py` 신설:
  - 입력: `--as-of`, `--mode in {baseline, no_macro, perturb_quadrant}`
  - mode `no_macro`: ESTIMATOR_PROMPT 에서 `=== Macro Quant ===` block 제거
  - mode `perturb_quadrant`: macro_summary 의 regime quadrant 를 다른 값으로 swap (예: growth_inflation → recession_disinflation)
  - 출력: cycle marginal, bucket weight, dominant_scenario, reasoning hash
- `artifacts/2026-05-20/{variance,ablation}/*.json` 결과 저장.
- `docs/followup_issues.md` Issue #5/#8/#9 항목에 측정 결과 1절 추가 (수치 인용).

**Test:**
- 스크립트는 production 코드 아님 — smoke test 만 (`tests/scripts/test_measure_stage2_ablation.py`, 1회 호출 + JSON 구조 검증).

**의도:** 후속 commit (C3) 의 β 함수 변경과 EMA 비율 λ 가 magic number 가 아닌, 측정 데이터에 근거한 결정이 되도록.

### C3 `feat(stage2): β-sharpening 재설계 + temporal smoothing (Cluster B 핵심)`

**해결 이슈:** #5, #11, #8 (반영), #9 (반영)

**변경 — β 함수 재설계 (`tradingagents/skills/research/scenario_mapper.py`):**

분석 결과에 따라 다음 셋 중 하나 채택 (사전 결정 금지):

| 옵션 | 조건 | 동작 |
|---|---|---|
| A. β=1 고정 (sharpening 제거) | variance 가 매우 작거나 backtest 에서 β>1 의 OOS Sharpe 우위 없음 | `_compute_conviction_beta` 가 항상 1.0 반환 |
| B. β backtest 캘리 | 1991-2024 grid search 에서 (β_slope, threshold) 최적 조합 존재 | 새 (slope, threshold) 로 교체, 출처 주석 |
| C. Bayesian shrinkage (역방향) | low conviction 에서 prior 로 shrink 가 OOS 효과 큼 | β 대신 `prior · (1-w) + new · w` (w 는 p_dom 의 함수) |

분석 commit (C2) 산출물 본 다음 결정. spec에는 **선택 기준** 명시:
- variance n=20 에서 bond σ ≤ 3pp, fx σ ≤ 3pp, cycle flip rate ≤ 5% → 옵션 A (sharpening 자체가 불필요).
- backtest grid 에서 (β_slope=0, conviction_threshold=ANY) 가 OOS Sharpe 상위 50% 안 → 옵션 A.
- 그 외 → 옵션 B 또는 C.

**변경 — temporal smoothing (`tradingagents/agents/managers/research_manager.py`):**
- state 에서 `prior_research_decision` 키 읽기 (없으면 None).
- 24-cell 확률 분포에 EMA 적용: `final_probs = λ · new_probs + (1-λ) · prior_probs`.
- λ default 는 ablation 결과로 정한다. 가이드:
  - macro_quant anchoring 강함 → λ 낮게 (예: 0.3, 이전 prior 우세)
  - anchoring 약함 → λ 높게 (예: 0.7, 새 신호 우세)
- prior 가 None 이면 raw new_probs 사용 (cold start).
- Hysteresis (선택): dominant_cycle 변경 시 새 cycle 의 marginal 이 기존보다 +Δ 이상 (예: 0.10) 앞서야 변경. 옵션 토글로 `_HYSTERESIS_DELTA: float = 0.0` (off) default.

**변경 — Stage 2 input pruning (Issue #8 반영):**
- ablation 결과 macro_summary anchoring 90%+ 이면 stage 2 LLM 호출 자체 제거하고 deterministic dispatcher 로 대체 평가 (옵션):
  - cycle marginal = macro_quant.regime quadrant probabilities (이미 stage 1 산출)
  - tail marginal = sigmoid(conditional_stress.aggregate_z)
  - kr marginal = softmax(kr_stress_score, kr_boom_score, 0)
  - axes independence 가정으로 24-cell joint 산출
- 분석 결과 anchoring 60-90% 면 macro_summary 제거 + 나머지 3 summary 만 LLM 에 (Stage 2 의 reformat 비용은 유지하되 prior 안 보여줌).
- anchoring 60% 이하 → 현 prompt 유지.

**Test:**
- `tests/unit/skills/test_research_scenario_mapper.py`:
  - β 함수 변경 후 입력 p_dom ∈ {0.20, 0.35, 0.55, 0.80} 에 대해 β 값 assertion (옵션별).
  - EMA blend: prior=None → raw, prior 존재 → λ blend 검증, 24-cell 분포 sum=1 유지.
  - hysteresis (옵션 on 일 때): Δ 미만이면 dominant 유지, Δ 이상이면 변경.
- `tests/integration/test_stage2_e2e_snapshot.py` (신규):
  - 2026-05-15 fixture 사용, deterministic frozen scenario_probabilities mock.
  - snapshot 1: pre-change ResearchDecision (cycle_marginals, bucket_target).
  - snapshot 2: post-change ResearchDecision.
  - 변경 의도 이외 항목 diff 가 없음을 assertion.

### C4 `perf(stage2): prompt caching + baseline 회귀 실측`

**해결 이슈:** #10, #6

**변경 — prompt caching (`tradingagents/agents/managers/research_manager.py`):**
- ESTIMATOR_PROMPT 를 두 부분으로 분리:
  - system 부분 (고정): Framework 설명 + CYCLE/TAIL/KR_DEFINITIONS + 24-cell list + 추정 절차 + 금지 (~5KB).
  - user 부분 (가변): Stage 1 4 summary + conditional_stress_block + kr_residual_block (~3-5KB).
- Anthropic SDK 의 `cache_control` 마커를 system message 에 적용 (5분 TTL).
- `invoke_with_structured_retry` helper 가 system/user 분리 message format 을 지원하는지 검증, 필요 시 보강.

**변경 — baseline 회귀 (`tradingagents/skills/risk/conditional_stress.py`):**
- `_BASELINE` 의 (mean, σ) 5×4=20 개 entry 를 1970-2024 quarterly data 로 실측.
- Data source: 기존 `playbook_calibration` 모듈이 이미 1970+ data 보유 (commit `e591006`). 같은 data 재사용.
- Quadrant assignment 는 기존 macro_quant `RegimeQuadrant` 정의 따름.
- 각 metric (hy_oas, vix, funding, credit_quality, equity_bond_corr) 의 quadrant-conditional mean/std 계산.
- `scripts/regress_stage2_baselines.py` 신설 — reproducibility:
  - 입력: 1970-2024 quarterly fixture
  - 출력: `_BASELINE` dict 형식의 Python literal 또는 JSON
- 결과를 `conditional_stress.py` 의 `_BASELINE` 으로 commit (회귀 결과 hash 도 주석).

**변경 — KR β 실측 (`tradingagents/skills/risk/kr_residual_signals.py`):**
- `_BETA_KR_CORP_VS_HY`, `_ALPHA_KR_CORP` 를 pandas OLS 로 실측:
  - 회귀식: `kr_corp_spread = α + β · hy_oas + ε`
  - 1990-2024 분기 데이터 (data 보유 여부 확인 필요).
- `_KR_MARGIN_SIGMA_PCT` 도 실측 σ 로 교체.

**Test:**
- `tests/unit/skills/test_conditional_stress.py`: 새 `_BASELINE` 으로 z-score 산출 sanity (2008 Q4 같은 historical event 가 z>+1.0 으로 나오는지).
- `tests/unit/skills/test_kr_residual_signals.py`: 실측 β/α 로 2022 레고랜드 사태가 stress_score > 0 으로 나오는지.
- `tests/unit/agents/test_research_manager.py`: prompt 가 system/user 로 분리되어 LLM 호출 되는지 (mock client 가 받는 messages 구조 검증).

### C5 `data(2026-05-15): 개선된 stage 2 로 산출물 재생성 + 대회 narrative`

**해결 이슈:** 없음 (산출물 갱신)

**변경:**
- `artifacts/2026-05-15/{portfolio.json, philosophy.md, trade_plan.csv}` 를 개선된 stage 2 로 재생성.
- `artifacts/2026-05-15/stage2_diff.md` 신설 — pre/post 비교:
  - dominant_cycle, dominant_scenario 변화
  - bucket_target 각 자산 변화 (pp)
  - method_choice 변화
  - expected_sharpe 변화
- `philosophy.md` narrative 추가 여부 결정 기준:
  - diff 가 작고 명확한 개선 (Sharpe ↑, conviction interpretation 일관성 ↑) → "Stage 2 framework 개선" 1 섹션 추가 (대회 70점 철학 점수 활용).
  - diff 가 크고 portfolio 방향이 뒤집힘 → narrative 보수적, 자세한 내용은 followup_issues.md.
  - 분석 결과(flip rate, anchoring 비율) 자체가 부정적이면 → "한계 인식 + 개선 로드맵" 솔직 narrative.

**Test:** 산출물은 artifact 라 test 없음. 단, 변경 전후 portfolio.json 의 mandate 준수 (위험자산 ≤ 0.70, 단일 ≤ 0.20) 는 기존 validator 가 자동 검증.

---

## 3. 분석 방법론 (C2 산출물 형식)

### 3.1 Variance 측정

**스크립트:** `scripts/measure_llm_variance.py --as-of 2026-05-15 --n 20`

**산출 metric:**

| metric | 의미 | 처방 trigger |
|---|---|---|
| `dominant_cycle_flip_rate` | 20 회 중 dominant cycle 이 다르게 나온 횟수 / 20 | > 5% → smoothing 필수 |
| `cycle_marginal_sigma` (per A/B/C/D) | 20회 marginal 의 표준편차 | B(우세) > 5pp → β 재검토 |
| `bond_weight_sigma` | bucket bond weight σ | > 3pp → smoothing/EMA |
| `fx_weight_sigma` | bucket fx σ | > 3pp → 동일 |
| `effective_cycle_sigma` | post-sharpening cycle marginal σ | β=2.38 산 sharpening이 noise 증폭하는지 |

**산출 형식:** `artifacts/2026-05-20/variance/2026-05-15_n20.json` + `summary.md`.

### 3.2 Ablation 실험

**스크립트:** `scripts/measure_stage2_ablation.py --as-of 2026-05-15 --mode {baseline,no_macro,perturb_quadrant} --n 3`

**Mode:**
- `baseline`: 정상 prompt (3 회).
- `no_macro`: macro_summary block 제거, 나머지 3 summary 만 (3 회).
- `perturb_quadrant`: macro_summary 의 regime.quadrant 를 다른 값으로 swap. 예: 실제 `growth_inflation` → `recession_disinflation` (3 회).

**산출 metric (각 mode 의 평균):**
- cycle marginal distribution
- dominant_cycle
- bucket_target

**해석:**
- `baseline` ≈ `no_macro` (cycle marginal L1 distance < 0.15) → macro_summary 의존 낮음. stage 2 의 informational value 가 있음.
- `baseline` ≠ `perturb_quadrant` (L1 distance > 0.40) → macro_quant anchoring 매우 강함. stage 2 가 단순 reformat.
- 중간 → 부분 anchoring. macro_summary 제거 또는 prior 표기 변경 검토.

### 3.3 결과 → C3 옵션 매핑

| variance 결과 | ablation 결과 | C3 변경 |
|---|---|---|
| bond σ ≤ 3pp, flip ≤ 5% | anchoring 무관 | β=1 고정 (옵션 A), EMA 미적용 |
| bond σ > 3pp, flip ≤ 5% | anchoring 약 | β backtest 캘리 (옵션 B), EMA λ=0.5 |
| bond σ > 3pp, flip > 5% | anchoring 약-중 | 옵션 B + EMA λ=0.4 + hysteresis Δ=0.10 |
| 무관 | anchoring > 90% | stage 2 LLM 호출 제거, deterministic dispatcher 평가 |

---

## 4. Regression test 전략

### 4.1 단위 test (`tests/unit/`)

새/수정:
- `test_research_scenario_mapper.py`:
  - dominant_scenario 7-cycle/tail fixture (7 case)
  - β 함수 (옵션별 1 case)
  - EMA blend (prior=None / present 2 case)
  - hysteresis (off/on 2 case)
- `test_conditional_stress.py`:
  - 새 `_BASELINE` 으로 historical event (2008 Q4) z-score sanity
- `test_kr_residual_signals.py`:
  - 새 β/α 로 2022 레고랜드 stress_score sanity
- `test_method_picker.py`:
  - overheating branch 호출 (1 case)
- `test_research_manager.py`:
  - prompt 가 system/user 분리되어 LLM 호출되는지 (mock client)
  - cache_control 마커 적용 여부

기존 461 test 는 그대로 pass 유지 (회귀 0건).

### 4.2 E2E snapshot (`tests/integration/test_stage2_e2e_snapshot.py`)

새 파일. deterministic LLM mock 으로 stage 2 → stage 6 까지 e2e:
- Fixture: 2026-05-15 raw inputs (이미 보관).
- LLM mock: 24-cell scenario_probabilities 를 frozen JSON 으로 주입 (`tests/fixtures/stage2_frozen_probs.json`).
- 변경 전/후 비교:
  - `ResearchDecision` JSON snapshot
  - `BucketTarget` snapshot
  - downstream `portfolio.json` 의 `weights`, `method_choice` snapshot
- 각 commit 머지 시 snapshot 갱신. 갱신 diff 는 PR 본문에 인용.

### 4.3 LLM mock 패턴

기존 `tests/conftest.py` 의 fixture 패턴 따름. 새 fixture:
```python
@pytest.fixture
def frozen_scenario_probabilities():
    return ScenarioProbabilities24(
        A_N_F=0.05, ..., D_T_stress=0.005, reasoning="frozen"
    )
```
estimator 호출을 monkeypatch 로 위 객체 반환하게 함. mapper 와 downstream 만 검증.

---

## 5. 5/28 일정 매핑 (압축 plan)

```
T+0:00 (5/20 오늘)      C1 commit (즉시 fix + followup 등록) — 30분
T+0:30                   C2 commit 인프라 작성 — 1시간
T+1:30                   variance 백그라운드 launch (~80분 wall) + ablation 백그라운드 launch (~30분)
T+1:30                   동시에 C4 commit 작업 시작:
                          - prompt caching code (30분)
                          - baseline 회귀 script (data 보유 확인 후 1-3시간)
T+3:00                   variance/ablation 결과 회수 → C2 commit 의 followup_issues.md 갱신
T+3:30                   C3 commit 작업: β 옵션 결정, EMA 구현, hysteresis (2-3시간)
T+5:30                   C5 commit: 산출물 재생성 + diff 검증 (1시간)
T+6:30                   Regression test 보강 + 전체 회귀 검증 (1-2시간)
T+8:00                   PR open, self-review
```

총 8 시간 예상. 변동 요인:
- `_BETA_KR_CORP_VS_HY` 회귀용 KR data (1990-2024 분기) 보유 여부 — 부재 시 #6 일부만 (US data 만 회귀) 또는 다음날 보충.
- baseline 회귀의 quadrant assignment 가 기존 macro_quant 와 시계열 호환되는지.

---

## 6. Acceptance criteria (mega-PR 머지 조건)

- [ ] 5 commit 모두 각각 independently revertable (`git revert <hash>` 가 정상 작동).
- [ ] `pytest` 461 + 신규 test 모두 pass.
- [ ] `dominant_scenario` 가 cycle=B 일 때 `"overheating"`, cycle=D 일 때 `"stagflation"` 반환.
- [ ] C2 산출물(`artifacts/2026-05-20/variance/`, `ablation/`) 가 git 에 commit 되어 있음.
- [ ] `followup_issues.md` Issue #5~#11 에 분석 결과 수치 인용.
- [ ] C3 의 β 함수 선택 (A/B/C) 이 분석 결과로 정당화됨 (commit body 에 인용).
- [ ] `_BASELINE` 과 `_BETA_KR_CORP_VS_HY` 가 회귀 결과로 교체됨 (회귀 hash 주석).
- [ ] Prompt 가 system/user 분리, `cache_control` 마커 적용.
- [ ] `artifacts/2026-05-15/stage2_diff.md` 에 pre/post 비교 명시.
- [ ] 변경 후 portfolio 가 mandate (위험자산 ≤ 0.70, 단일 ≤ 0.20) 준수.

---

## 7. 비목표 / Out of scope

- 24-cell schema 자체 변경 (예: 36-cell 확장, axis 추가) — 다음 cycle.
- Stage 1/3/4/5/6 알고리즘 변경 (단, Stage 3 method_picker 의 `overheating` case 만 예외).
- Phase 2 ensemble (3-estimator) — 본 PR 결과로 single estimator 충분성 평가 후.
- LLM client 자체 교체 (deep_llm provider 변경) — 별도.
- Calibration 모듈 (`e591006`) 의 internal 변경 — baseline 회귀에서 *재사용*만, 변경 X.

---

## 8. Risk / Mitigation

| Risk | Mitigation |
|---|---|
| C3 의 β 옵션 결정이 분석 결과로도 모호함 | 옵션 A (β=1 고정) 가 default — over-engineering 회피 |
| Baseline 회귀 data 부족 (KR 부분) | US 부분만 우선 회귀, KR 은 hand-coded 유지 + TODO 주석 |
| variance/ablation script 의 LLM 호출 비용 (~$3 총) | 비용 사전 합의됨. 더 큰 risk 는 latency 가 ~110분 wall — 백그라운드로 회피 |
| 산출물 재생성 후 portfolio 가 5/15 와 크게 달라짐 | C5 의 diff 검증 단계에서 narrative 보수적 선택. 산출물 자체는 commit 으로 안전 |
| Mega-PR 의 review 부담 | commit 단위로 차곡 차곡, 각 commit body 에 변경 의도 명시 |
| 5/28 narrative 결정 보류 (분석 결과 의존) | C5 에서 명시적 결정 기준 (Section 5.5) 미리 합의됨 |

---

## 9. 메모리 / 정책 참조

- regression test 는 코드 변경의 기본값 (memory `feedback_regression_tests.md`).
- 기존 followup_issues.md 의 우선순위 형식 따름 — 표/effort/risk 명시.
- Commit message 는 기존 cadence (`feat/fix/chore/docs/data/perf` prefix + `(stageX)` scope).
