# Stage 2 Factor-based Model — Design (PR1)

- **작성일:** 2026-05-22
- **선행:** Stage 2 Mega-PR (commits fc65717 → 47b5590) merged. Audit (`docs/superpowers/specs/2026-05-22-stage2-pipeline-audit.md`).
- **Scope:** Stage 2 *내부 algorithm 전면 교체*. 24-cell × playbook → Continuous factor model + additive bucket regression.
- **Migration:** Hard cutover (현 framework 완전 제거).
- **LLM 사용:** Stage 2 내 *완전 deterministic*. LLM critic 은 *future expansion* — 본 PR scope 외.

---

## 0. 결정 요약 (brainstorming session 의 result)

| Decision | Choice | 출처 |
|---|---|---|
| Scope | Stage 2 *내부* algorithm 만 교체. Stage 1 *변경 없음*. 필요 input 부재 시 *문서화 후 후속 PR*. | User Q1 |
| Calibration | Hybrid (theory prior + walk-forward Sharpe maximization with shrinkage) | User Q2 |
| LLM role in Stage 2 | **None** — 완전 deterministic. LLM critic 은 future expansion. | User clarification |
| Migration | Hard cutover (24-cell × playbook 완전 제거) | User Q4 |
| Acceptance criterion | Walk-forward OOS Sharpe > 현 framework + 0.05 AND OOS Sharpe ≥ 60/40 | User Q5 |
| Regression test policy | 모든 코드 수정 시 *의무*. Factor 추가 시 backtest contribution + sign restriction 검증 의무. | User 추가 요구 |
| 지표 reliability 검증 | 각 factor 의 *theoretical validity + 2026-05 현재 reliability* cold audit 적용. | User 추가 요구 |

---

## 1. 배경 + 동기

Stage 2 Mega-PR (C0-C5) 후 audit (`2026-05-22-stage2-pipeline-audit.md`) 가 13 개 structural issue 식별. 그 중:

- **Issue A (critical)**: `_build_signal_blocks()` 가 production 에서 한 번도 호출 안 됨 — sub-graph state isolation 으로 `macro_report` / `risk_report` 가 sub-graph 로 안 넘어감. → Stage 0 D2/D3 signal cleaning 무력화.
- **D1/D2/D3 의 non-orthogonality**: 4-cycle × 2-tail × 3-kr = 24-cell 의 axis 가 *statistical / semantic / completeness* 어느 의미로도 orthogonal 아님. Cross-correlation 강함 (예: P(T|B) ≈ 0).
- **Hand-coded playbook**: 24 × 5 = 120 weight 의 *hand judgment + sparse backtest* mix. False precision.
- **Expected-playbook decision rule**: $E[w] = \sum P(\text{cell}) \cdot \text{playbook}(\text{cell})$ 가 *risk-neutral certainty-equivalent* — risk aversion 무시.
- **누락 dimension**: phase, liquidity, valuation, concentration, currency regime — 24-cell 에 없음.

본 PR 의 의도: 위 structural issue 의 *대부분* 을 *factor-based continuous decomposition* 으로 해소.

## 2. Architecture overview

### 2.1 신 pipeline

```
[Stage 1 (unchanged)]
  AgentState:
    ├── macro_report (struct)
    ├── risk_report (struct)
    ├── technical_report (struct)
    ├── news_report (struct)
    ├── macro_summary, risk_summary, ... (text — Stage 2 미사용)
    └── prior_research_decision (optional)
              │
              ▼
[Stage 2 — Factor model (deterministic, NEW)]
  Sub-graph wrapper 제거 — research_debate 가 single node.

  research_manager.node(state: AgentState):
    │
    ├── 2a. compute_factors(state) → FactorScores (9-dim z-vector)
    │       ↳ deterministic estimators, struct field 직접 접근
    │       ↳ Issue A 해소 (signal cleaning 이 *실제로* 작동)
    │
    ├── 2b. (PR1: skip) LLM critic 자리 — *future expansion*
    │
    ├── 2c. factor_to_bucket(factors, β) → raw bucket weights
    │       ↳ bucket[b] = baseline[b] + Σ_f β[f, b] × z[f]
    │       ↳ β = walk-forward calibrated
    │
    ├── 2d. apply_prior_smoothing(weights, prior_decision) → smoothed weights
    │       ↳ EMA with λ default 1.0 (no-op) — infrastructure 유지
    │
    └── 2e. project_to_mandate(weights) → final BucketTarget
            ↳ 위험자산 ≤ 0.70, 단일 ≤ 0.20 enforce
              │
              ▼
[Output: BucketTarget (same schema) + ResearchDecision (modified schema)]
```

### 2.2 변경 summary

| Aspect | 현재 | 신 |
|---|---|---|
| Sub-graph | yes (`InvestDebateState`) | **제거** (single node) |
| Inference | LLM (24-cell prob) | **Deterministic factor estimator** |
| Decomposition | 24-cell joint | **9 continuous factor (approximately orthogonal)** |
| Mapping | 24 × hand-coded playbook | **Additive regression β (calibrated)** |
| Calibration | hand-coded | **Theory prior + walk-forward Sharpe optim** |
| LLM in Stage 2 | yes (1 deep call) | **No** (future expansion 만) |
| Reproducibility | partial (LLM noise) | **Full** (deterministic) |

### 2.3 Downstream 호환

- `BucketTarget` schema *동일* (5 bucket weight + bond_tips_share + rationale). Downstream 영향 없음.
- `ResearchDecision` schema *변경*:
  - 제거: `scenario_probabilities: ScenarioProbabilities24`, `dominant_cell: CellCoord`, `dominant_cell_probability`, `cycle_marginals`, `tail_marginals`, `kr_marginals`, `effective_cycle_marginals`, `conviction_beta`.
  - 신설: `factor_scores: dict[str, float]` (9 factor z-scores), `factor_contributions: dict[str, dict[str, float]]` (factor → bucket contribution for attribution).
  - 유지 (재정의): `dominant_scenario` (legacy compat — *deterministic* function of factors), `conviction` (uncertainty measure).
- Downstream caller (`portfolio_allocator`, `method_picker`, `risk_judge`, `macro_conditional_lens`) 의 *현재 사용 field*:
  - `dominant_scenario` (string): legacy compat 유지 — 가장 dominant factor 기반 deterministic mapping (cell.key 형식 X, scenario name 만).
  - `conviction` (high/medium/low): 재정의 — factor sign agreement + magnitude 기반.

→ Downstream code *수정 없음* (interface preserved).

### 2.4 제거되는 코드

- `tradingagents/skills/research/scenario_mapper.py` (전체)
- `tradingagents/skills/research/scenario_definitions.py` (전체)
- `tradingagents/schemas/research.py` 의 `ScenarioProbabilities24`, `CellCoord`, `ALL_CELLS`, `TRANSIENT_CELLS`, `cell_key`, `parse_cell_key`, `CycleQuadrant`, `TailState`, `KRDirection`
- `tradingagents/agents/managers/research_manager.py` 의 prompt 관련 (`_SYSTEM_PROMPT`, `_USER_TEMPLATE`, `_build_messages`, `ESTIMATOR_PROMPT`)
- `tradingagents/agents/researchers/debate_state.py` (전체) + `tradingagents/graph/debate_subgraph.py` (전체)
- `tradingagents/skills/portfolio/sub_category.py` 의 `_LEGACY_SCENARIO_TO_AXES` (cell key 의존 부분만)

LOC impact: 제거 ~700, 추가 ~1300.

## 3. Stage 1 input contract + gap

### 3.1 Issue A fix (sub-graph wrapper 제거)

**현재 silent bug** (audit Issue A): `research_debate_node` 가 `InvestDebateState` 로 state 축소 시 `macro_report`/`risk_report`/`prior_research_decision` 누락 → `_build_signal_blocks()` 가 항상 빈 결과.

**Fix**: sub-graph wrapper *완전 폐기*. `research_manager` 가 *single node* — `AgentState` 직접 접근.

`tradingagents/graph/trading_graph.py` 의 `research_debate_node` wrapper 제거:
```python
# Before
def research_debate_node(state):
    sub_input = InvestDebateState(
        messages=[],
        macro_summary=state.get("macro_summary", ""),
        ...  # macro_report 등 누락
    )
    sub_result = invest_subgraph.invoke(sub_input)
    return {...}

# After
research_debate_node = create_research_manager(deep)  # single node
```

`debate_state.py` + `debate_subgraph.py` 파일 자체 삭제.

### 3.2 Per-factor Stage 1 input table

각 factor 의 *Stage 1 source field* + *availability*. 2026-05 *현재 reliability* 포함.

#### F1 — growth_surprise

| Component | Stage 1 source | Available | 2026 reliability | Weight in F1 |
|---|---|---|---|---|
| GDPNow | `macro_report.growth.gdp_nowcast` | ✓ | high | 0.25 |
| CFNAI | `macro_report.growth.cfnai` | ✓ | high | 0.20 |
| NFCI (inverted) | `macro_report.growth.nfci` | ✓ | high | 0.15 |
| Sahm trigger | `macro_report.employment.sahm_trigger` | ✓ | **medium-low** (post-COVID 왜곡, Sahm 자체 false-positive 인정) | **0.10 cap** |
| Yield curve 2-10y | `macro_report.yield_curve.slope_2_10y_bps` | ✓ | **medium** (post-COVID de-anchored) | **0.15 cap** |
| LEI 6m change | not in Stage 1 (Gap A) | ✗ | high | 0 (post-Stage-1-PR) |
| ISM PMI sub-components | not in Stage 1 (Gap B) | ✗ | high | 0 (post-Stage-1-PR) |

PR1 component weight sum = 0.85 (LEI/ISM 추가 후 1.0 으로 rebalance).

#### F2 — inflation_surprise

| Component | Stage 1 source | Available | 2026 reliability | Weight |
|---|---|---|---|---|
| CPI YoY | `macro_report.cpi.yoy_pct` | ✓ | high | 0.20 |
| CPI 3m annualized | `macro_report.cpi.three_month_annualized_pct` | ✓ | high | 0.20 |
| Core PCE YoY | `macro_report.cpi.core_pce_yoy` (검증) | partial | high | 0.15 |
| 5y5y forward | `macro_report.inflation_exp.five_y_five_y_pct` | ✓ | high | 0.15 |
| Michigan 1y | `macro_report.inflation_exp.michigan_1y_pct` | ✓ | **medium** (behavioral noise ↑) | 0.10 cap |
| Real yields 10y (inverted) | `macro_report.real_yields.ten_y_pct` | ✓ | high | 0.10 |
| Fed path 6m bps | `macro_report.fed_path.implied_change_6m_bps` | ✓ | high | 0.10 |

#### F3 — real_rate

| Component | Stage 1 source | Available | 2026 reliability | Weight |
|---|---|---|---|---|
| 10y TIPS yield | `macro_report.real_yields.ten_y_pct` | ✓ | high | 0.85 |
| r-star (HLW) | not in Stage 1 (Gap C) | ✗ | **medium** (post-COVID modeling uncertainty) | 0 (long-run mean 1.0% fallback) |

PR1 effective weight: TIPS yield 만 사용.

#### F4 — term_premium

| Component | Stage 1 source | Available | 2026 reliability | Weight |
|---|---|---|---|---|
| 2-10y slope | `macro_report.yield_curve.slope_2_10y_bps` | ✓ | **medium** (F1 와 같은 de-anchor 이슈) | 0.40 |
| 5-30y slope | `macro_report.yield_curve.slope_5_30y_bps` (검증) | partial | high | 0.30 |
| ACM term premium | not in Stage 1 (Gap D) | ✗ | **uncertain** (NY Fed 2024 methodology review) | 0 (fallback to slope only) |
| Kim-Wright term premium | not in Stage 1 | ✗ | high (still published) | 0 (post-Stage-1-PR) |

PR1 effective: slope only. F4 의 *signal quality* 가 다른 factor 보다 낮음 — *weight bound at calibration*.

#### F5 — credit_cycle

| Component | Stage 1 source | Available | 2026 reliability | Weight |
|---|---|---|---|---|
| US HY OAS current | `risk_report.credit_spread_us_hy.current_bps` | ✓ | high (real-time) | 0.40 |
| HY OAS 4w momentum z | `risk_report.credit_spread_us_hy.momentum_z` | ✓ | high | 0.30 |
| Cycle-conditional baseline | `_BASELINE[quadrant]` (hand-coded — Issue #6 D7 deferred) | ✓ | medium | (baseline 으로 z 산출) |
| Credit quality spread | `risk_report.credit_quality.quality_spread_bps` | ✓ | high | 0.20 |
| Funding stress | `risk_report.funding_stress.spread_bps` | ✓ | high | 0.10 |

PR1: 모두 available. Quadrant 는 `macro_report.regime.quadrant`.

#### F6 — KRW regime (★ critical gap)

| Component | Stage 1 source | Available | 2026 reliability | Weight |
|---|---|---|---|---|
| KRW/USD level | not in Stage 1 (Gap E — *critical*) | ✗ | high | (PR1: yfinance fetch 임시 workaround) |
| KRW REER | not in Stage 1 (Gap F) | ✗ | high | 0 (long-run mean fallback) |
| KR-US rate diff | `macro_report.kr_macro.bok_us_rate_diff_bps` (검증) | partial | high | 0.30 |
| Foreign flow z | `macro_report.foreign_flow.net_flow_z` | ✓ | high | 0.30 |
| KR exports YoY z | `macro_report.kr_macro.exports_yoy_z` (검증) | partial | high | 0.20 |

**Gap E (KRW/USD)** 가 *블로커*. Workaround:
- PR1: `tradingagents/skills/external/krw_fetcher.py` 신설 — yfinance `KRW=X` 직접 fetch + cache. Stage 2 안에서 호출. Stage 1 변경 0.
- 후속 Stage 1 PR 으로 macro_quant 안의 정식 KR FX skill 로 이동.

#### F7 — equity_vol_regime

| Component | Stage 1 source | Available | 2026 reliability | Weight |
|---|---|---|---|---|
| VIX level | `risk_report.vix.current_value` | ✓ | high | 0.25 |
| VIX z-score | `risk_report.vix.z_score` | ✓ | high | 0.15 |
| VIX term ratio | `risk_report.vix.term_ratio` | ✓ | high | 0.15 |
| MOVE | `risk_report.move.current_value` (검증) | partial | high | 0.20 |
| SKEW level | `risk_report.skew.current_value` (검증) | partial | **medium-low** (post-2018 structurally elevated) | 0 (SKEW change 만 사용) |
| SKEW 1m change | derived | partial | medium | 0.10 |
| Realized vol 60d | `risk_report.realized_vol.sixty_d` (검증) | partial | high | 0.15 |

#### F8 — valuation (★ 2026 uncertainty)

| Component | Stage 1 source | Available | 2026 reliability | Weight |
|---|---|---|---|---|
| S&P forward P/E | not in Stage 1 (Gap G — *critical*) | ✗ | **medium** (AI environment noise ↑) | (PR1: yfinance trailing P/E proxy) |
| S&P earnings yield | derived (1/PE) | ✗ | medium | 0.30 |
| ERP (EY − real rate) | derived | ✗ | **medium-high** (cleaner than raw P/E) | 0.50 |
| KOSPI PBR | pykrx | ✗ | high | 0.20 |

PR1: trailing P/E via yfinance. *2026 reliability medium* → F8 의 *overall weight in bucket regression* 을 cap (calibration step 에서).

#### F9 — liquidity_regime

| Component | Stage 1 source | Available | 2026 reliability | Weight |
|---|---|---|---|---|
| VRP (VIX² − realized²) | derived from F7 components | ✓ (derived) | high | 0.40 |
| Equity-bond corr 60d | `risk_report.equity_bond_corr.correlation_60d` | ✓ | high | 0.20 |
| Sector dispersion | `technical_report.sector_dispersion` (검증) | partial | high | 0.20 |
| Breadth (A/D) | `technical_report.breadth` (검증) | partial | **medium** (narrow AI rally distortion) | 0.10 cap |
| Cross-currency basis | not in Stage 1 (Gap H) | ✗ | high | 0 (post-Stage-1-PR) |

### 3.3 Gap 종합 + workaround

| Gap | Factor | PR1 workaround | Stage 1 PR (후속) |
|---|---|---|---|
| A: LEI | F1 | weight 0 (subset components) | macro_quant 에 LEI fetch 추가 |
| B: ISM sub | F1 | weight 0 | macro_quant 에 ISM detail |
| C: r-star | F3 | long-run mean (1.0%) | macro_quant 에 HLW model |
| D: ACM/KW | F4 | slope-only | macro_quant 에 term premium fetch |
| **E: KRW/USD** | F6 | **yfinance fetch in Stage 2 (임시)** | macro_quant 에 KR FX skill |
| F: KRW REER | F6 | long-run mean | macro_quant 에 BIS REER |
| **G: Forward P/E** | F8 | **yfinance trailing P/E (임시)** | market_risk 에 valuation skill |
| H: Cross-currency basis | F9 | weight 0 | market_risk 에 cross-currency |

**임시 fetch 위치**: `tradingagents/skills/research/external_fetchers.py` (신설) — KRW/USD + 트레일링 P/E.

### 3.4 Stage 1 backlog 문서

본 PR merge 시 `docs/followup_issues.md` 에 *Issue #12-#19* 등록:
- #12 macro_quant 에 KR FX skill 추가 (Gap E + F)
- #13 macro_quant 에 LEI + ISM sub 추가 (Gap A + B)
- #14 macro_quant 에 r-star + term premium 추가 (Gap C + D)
- #15 market_risk 에 valuation skill 추가 (Gap G)
- #16 market_risk 에 cross-currency basis 추가 (Gap H)
- #17 `external_fetchers.py` 의 임시 fetch 를 Stage 1 으로 migrate (cleanup)

## 4. Factor estimators (Stage 2a)

### 4.1 9-factor 구조

각 factor 는 *continuous z-score* 산출 — long-run (1970-2024 quarterly) mean + sd 기준 normalization.

```python
@dataclass
class FactorScore:
    raw_value: float          # 가중 평균 z (pre-cap)
    z_score: float            # final z (capped, signed)
    components: dict[str, float]  # component 별 z (audit trail)
    confidence: float         # data quality / staleness (0-1)
    interpretation: str       # human-readable narrative

@dataclass
class FactorScores:
    growth_surprise: FactorScore        # F1
    inflation_surprise: FactorScore     # F2
    real_rate: FactorScore              # F3
    term_premium: FactorScore           # F4
    credit_cycle: FactorScore           # F5
    krw_regime: FactorScore             # F6
    equity_vol_regime: FactorScore      # F7
    valuation: FactorScore              # F8
    liquidity_regime: FactorScore       # F9
```

### 4.2 Factor estimator 의 일반 형태

```python
def compute_factor_f(stage1_inputs, components_weights: dict[str, float]) -> FactorScore:
    """Generic factor computation:
       1. 각 component 의 raw value 추출.
       2. Long-run baseline 으로 z-score 산출.
       3. 가중 평균 (component weights).
       4. Sign convention 적용.
       5. Cap to [-3, +3] for stability.
    """
    components_z = {}
    for name, weight in components_weights.items():
        if weight == 0:
            continue
        raw = extract_component(stage1_inputs, name)
        if raw is None:  # data unavailable
            continue
        baseline_mean, baseline_sd = LONG_RUN_BASELINE[f][name]
        z = (raw - baseline_mean) / baseline_sd
        components_z[name] = z

    # 가중 평균 (정규화)
    total_weight = sum(components_weights[n] for n in components_z)
    if total_weight == 0:
        return FactorScore(0, 0, {}, confidence=0, interpretation="no data")

    weighted_z = sum(components_z[n] * components_weights[n] for n in components_z) / total_weight
    capped_z = max(-3.0, min(3.0, weighted_z))

    return FactorScore(
        raw_value=weighted_z,
        z_score=capped_z,
        components=components_z,
        confidence=total_weight,  # 1.0 if all components available
        interpretation=narrative_string(components_z, factor_name=f),
    )
```

### 4.3 F1-F9 의 *concrete formula*

#### F1 — growth_surprise

```python
def compute_growth_surprise(stage1) -> FactorScore:
    # Component z-scores
    z_gdpnow = z(stage1.macro_report.growth.gdp_nowcast, mean=2.0, sd=2.0)
    z_cfnai = z(stage1.macro_report.growth.cfnai, mean=0.0, sd=0.5)
    z_nfci = -z(stage1.macro_report.growth.nfci, mean=0.0, sd=0.5)  # tight = recession
    z_sahm = -1.0 if stage1.macro_report.employment.sahm_trigger else +0.5
    z_curve = z(stage1.macro_report.yield_curve.slope_2_10y_bps, mean=80, sd=80)

    # Weighted aggregation (Sahm + curve weight cap per 2026 reliability)
    weights = {
        "gdpnow": 0.25, "cfnai": 0.20, "nfci": 0.15,
        "sahm": 0.10, "curve": 0.15,  # capped at low weight
        # "lei": 0.10, "ism_sub": 0.05  # post-Stage-1-PR
    }
    return aggregate_z(components, weights)

# Sign convention: +z = growth, -z = recession
```

#### F2 — inflation_surprise

```python
def compute_inflation_surprise(stage1) -> FactorScore:
    z_cpi_yoy = z(stage1.macro_report.cpi.yoy_pct, mean=2.5, sd=2.0)
    z_cpi_3m = z(stage1.macro_report.cpi.three_month_annualized_pct, mean=2.5, sd=3.0)
    z_core = z(stage1.macro_report.cpi.core_pce_yoy, mean=2.0, sd=1.5)
    z_5y5y = z(stage1.macro_report.inflation_exp.five_y_five_y_pct, mean=2.3, sd=0.5)
    z_mich = z(stage1.macro_report.inflation_exp.michigan_1y_pct, mean=3.0, sd=1.5)
    z_real = -z(stage1.macro_report.real_yields.ten_y_pct, mean=0.5, sd=1.0)
    z_fed = z(stage1.macro_report.fed_path.implied_change_6m_bps, mean=0, sd=50)

    weights = {"cpi_yoy": 0.20, "cpi_3m": 0.20, "core": 0.15,
               "5y5y": 0.15, "mich": 0.10, "real": 0.10, "fed": 0.10}
    return aggregate_z(components, weights)

# +z = inflation, -z = disinflation
```

(F3-F9 의 자세한 formula 는 별도 implementation plan 에 — spec 의 patten 동일.)

### 4.4 Long-run baseline

`tradingagents/skills/research/factor_baselines.py` 신설:

```python
# Long-run (1970-2024 quarterly, FRED + ECOS data) baseline.
# 각 component 의 (mean, sd) 산출 — backtest 단계에서 정확화.
# PR1 초기: macro consensus 기반 hand-coded, calibration step 에서 실측 sd 로 교체.

LONG_RUN_BASELINE = {
    "F1_growth": {
        "gdpnow":    (2.0, 2.0),    # historical US RGDP yoy ≈ 2%, sd 2%
        "cfnai":     (0.0, 0.5),    # by construction
        "nfci":      (0.0, 0.5),    # by construction
        "curve":     (80, 80),       # 2-10y slope bps
    },
    "F2_inflation": {
        "cpi_yoy":   (2.5, 2.0),
        "cpi_3m":    (2.5, 3.0),    # more volatile
        "core":      (2.0, 1.5),
        "5y5y":      (2.3, 0.5),
        "mich":      (3.0, 1.5),
        "real_inv":  (0.5, 1.0),
        "fed":       (0, 50),
    },
    # ... F3-F9 ...
}

# PR1 의 baseline 은 hand-coded. Calibration step 에서:
#   - 1970-2024 quarterly data 로 each component 의 실측 (mean, sd) 계산.
#   - hand-coded vs 실측 diff > 30% 시 alert (모델 가정 검토).
```

### 4.5 Indicator validity *test* (regression test 정책의 일부)

각 factor 의 *theoretical + 2026 reliability* 가 본 design 의 *core assumption*. 매 modification 시 *재검증* 의무:

`tests/unit/skills/test_factor_indicator_validity.py` 신설:

```python
def test_factor_components_meet_reliability_requirements():
    """각 component 의 2026 reliability 가 documented threshold 충족.
    Component 또는 weight 변경 시 *명시적 update* 의무.
    """
    AUDIT_DATE = "2026-05-22"
    for factor_name, audit in FACTOR_RELIABILITY_AUDIT.items():
        for component, expected_reliability in audit.items():
            actual = COMPONENT_RELIABILITY[component]
            assert actual == expected_reliability, (
                f"{factor_name}.{component} reliability changed from "
                f"'{expected_reliability}' (audit {AUDIT_DATE}) to '{actual}'. "
                f"Re-audit + update FACTOR_RELIABILITY_AUDIT + design doc."
            )

def test_factor_component_weights_cap_low_reliability():
    """Low/medium-low reliability component 의 weight 가 cap 이하.
    Audit 의 weight cap 강제.
    """
    for factor_name, weights in COMPONENT_WEIGHTS.items():
        for component, weight in weights.items():
            reliability = COMPONENT_RELIABILITY[component]
            cap = WEIGHT_CAP_BY_RELIABILITY[reliability]
            assert weight <= cap, (
                f"{factor_name}.{component} weight {weight} > cap {cap} "
                f"for reliability '{reliability}'"
            )
```

→ **Factor component 또는 weight 변경 시 test 자동 fail → 명시적 audit update 의무화**.

## 5. Factor → Bucket Mapping (Stage 2c)

### 5.1 Linear additive model

```python
bucket[b](t) = baseline[b] + Σ_f β[f, b] × z_f(t) + Σ_(f,g) γ[f, g, b] × z_f(t) × z_g(t)
              ^^^^^^^^^^^   ^^^^^^^^^^^^^^^^^^^^^^^^   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
              baseline        main effect                sparse interaction (PR1: 0개로 시작)

with constraints:
  Σ_b baseline[b] = 1.0          (probability simplex)
  Σ_b β[f, b] = 0 ∀ f             (adjustment vector preserves sum)
  Σ_b γ[f, g, b] = 0 ∀ (f, g)
  baseline[b] ≥ 0
  sign(β[f, b]) = THEORY_PRIOR_SIGN[f][b]  (constraint at calibration)
```

### 5.2 Parameter count

| Parameter group | Count | Free (after constraint) |
|---|---|---|
| baseline (5 bucket) | 5 | 4 |
| β main (9 × 5) | 45 | 36 |
| γ sparse interaction (PR1: 0) | 0 | 0 |
| **PR1 total** | **50** | **40** |

Sample (1991-2024 quarterly) = 135. Sample / param = 3.4. *Acceptable with shrinkage* (Bayesian regularization).

### 5.3 Sign restriction (theory prior)

```python
# Direction 만 prior (magnitude 는 calibration).
SIGN_RESTRICTION = {
    # F1 growth: +equity / -bond
    ("F1_growth", "kr_equity"):     "positive",
    ("F1_growth", "global_equity"): "positive",
    ("F1_growth", "fx_commodity"):  "neutral",   # +growth doesn't strongly help fx
    ("F1_growth", "bond"):          "negative",
    ("F1_growth", "cash_mmf"):      "negative",

    # F2 inflation: +commodity/TIPS, -nominal bond, mild -equity
    ("F2_inflation", "kr_equity"):     "negative_mild",
    ("F2_inflation", "global_equity"): "negative_mild",
    ("F2_inflation", "fx_commodity"):  "positive",
    ("F2_inflation", "bond"):          "negative",  # nominal bond hurt
    ("F2_inflation", "cash_mmf"):      "positive_mild",

    # ... F3-F9 모두 ...
}
```

### 5.4 Initial baseline + β (hand-coded prior, calibration 전)

```python
INITIAL_BASELINE = {
    "kr_equity":     0.12,
    "global_equity": 0.20,
    "fx_commodity":  0.15,
    "bond":          0.33,
    "cash_mmf":      0.20,
}
# 위험자산 = 0.47 (mandate 0.70 의 67%)

INITIAL_BETA = {
    # (factor, bucket): coefficient
    # Each row (factor) sums to 0 across buckets.

    # F1 growth (+z = growth → +equity, -bond)
    ("F1_growth", "kr_equity"):     +0.04,
    ("F1_growth", "global_equity"): +0.06,
    ("F1_growth", "fx_commodity"):  +0.01,
    ("F1_growth", "bond"):          -0.08,
    ("F1_growth", "cash_mmf"):      -0.03,

    # F2 inflation
    ("F2_inflation", "kr_equity"):     -0.02,
    ("F2_inflation", "global_equity"): -0.03,
    ("F2_inflation", "fx_commodity"):  +0.07,
    ("F2_inflation", "bond"):          -0.05,
    ("F2_inflation", "cash_mmf"):      +0.03,

    # ... 9 factor × 5 bucket = 45 coefficient hand-coded ...
}
```

### 5.5 Bond TIPS share

별도 scalar regression:

```python
bond_tips_share(t) = baseline_tips + Σ_f β_tips[f] × z_f(t)

# F2 inflation 의 영향 가장 큼: +z → tips share ↑.
INITIAL_TIPS_BETA = {
    "F1_growth":           +0.05,    # mild
    "F2_inflation":        +0.20,    # dominant
    "F3_real_rate":        -0.10,    # high real rate → 나nominal preferred
    "F4_term_premium":     0.0,
    "F5_credit_cycle":     -0.05,    # credit risk → nominal Treasury 선호
    "F6_krw_regime":       0.0,
    "F7_equity_vol":       0.0,
    "F8_valuation":        0.0,
    "F9_liquidity":        -0.03,    # liquidity 부족 → nominal preferred
}
INITIAL_TIPS_BASELINE = 0.30
```

## 6. Calibration (Stage 2 의 *training step*)

### 6.1 Walk-forward Sharpe maximization with theory shrinkage

```python
def calibrate(historical_data, theory_prior, shrinkage=0.5):
    """Hybrid: theory prior + walk-forward Sharpe maximization."""

    fold_results = []
    for fold_start in range(20*4, len(historical_data) - 4, 4):
        # Train: [0, fold_start) — expanding window
        # Test:  [fold_start, fold_start + 4) — next year (4 quarter)
        train = historical_data[:fold_start]
        test = historical_data[fold_start:fold_start + 4]

        def objective(beta_flat):
            beta = unflatten(beta_flat)
            returns = simulate_portfolio_returns(train, beta)
            sharpe = mean(returns) / std(returns) * np.sqrt(4)

            # Shrinkage to theory prior
            shrinkage_penalty = shrinkage * sum(
                (beta[k] - theory_prior[k]) ** 2 for k in beta
            )

            # Sign constraint (hard)
            sign_violations = 0
            for k, expected_sign in SIGN_RESTRICTION.items():
                if expected_sign == "positive" and beta[k] < 0:
                    sign_violations += abs(beta[k]) * 100
                elif expected_sign == "negative" and beta[k] > 0:
                    sign_violations += abs(beta[k]) * 100

            return -sharpe + shrinkage_penalty + sign_violations

        from scipy.optimize import minimize
        result = minimize(
            objective,
            x0=flatten(theory_prior),
            method="L-BFGS-B",
            bounds=THEORY_BOUNDS,  # magnitude bounds per factor
            options={"maxiter": 1000},
        )

        # OOS evaluation
        test_returns = simulate_portfolio_returns(test, unflatten(result.x))
        test_sharpe = mean(test_returns) / std(test_returns) * np.sqrt(4)

        fold_results.append({
            "fold_start": fold_start,
            "in_sample_sharpe": -result.fun + shrinkage_penalty,
            "oos_sharpe": test_sharpe,
            "beta": unflatten(result.x),
        })

    # Aggregate (median across folds — robust to outlier folds)
    final_beta = aggregate_median([f["beta"] for f in fold_results])
    return final_beta, fold_results
```

### 6.2 Shrinkage 강도 선택

`shrinkage ∈ {0.1, 0.3, 0.5, 0.7, 1.0}` 의 grid search:
- 각 값 별 walk-forward OOS Sharpe.
- *Highest OOS Sharpe* 의 shrinkage 선택.
- *2026-05-15* 시점의 모델 출력의 *interpretability* 도 고려 (low shrinkage = data fit, high = theory prior).

### 6.3 Sample window 선택

3 후보 비교:
- **Full**: 1991-2024 (135 quarter) — most data.
- **Post-Great-Moderation**: 2010-2024 (60 quarter) — *현재 regime* 비교적 stable.
- **Post-COVID**: 2020-2024 (20 quarter) — 가장 *current-like*, 그러나 sample 부족.

각 sample window 별 calibration → OOS Sharpe. 결과 보고.

*Cold prediction*: Post-Great-Moderation (2010-2024) 가 *best balance* — sample 충분 + post-COVID *과대 가중 X*.

### 6.4 Calibration 산출물

`artifacts/2026-05-22/factor_calibration/`:
- `coefficient_table.json`: final β + baseline + tips_beta.
- `walk_forward_results.csv`: per-fold (β, in_sample_sharpe, oos_sharpe).
- `shrinkage_grid.csv`: shrinkage 별 결과.
- `sample_window_comparison.csv`: 3 window 별 결과.
- `validation_report.md`: pass/fail summary + decision.

## 7. EMA prior smoothing (Stage 2d — infrastructure 유지)

현 Mega-PR 의 EMA infrastructure 유지하나 *factor space 에서* 작동:

```python
def apply_prior_smoothing(factor_scores, prior_decision, lam=1.0):
    """Factor z 의 EMA blend. λ=1.0 default → identity.
    Future: variance 측정 후 λ < 1.0 활성화 (regime transition 시점).
    """
    if prior_decision is None or lam >= 1.0 - 1e-9:
        return factor_scores

    prior_factors = prior_decision.factor_scores
    smoothed = {}
    for f in FACTORS:
        new_z = factor_scores[f].z_score
        prior_z = prior_factors[f].z_score
        blended_z = lam * new_z + (1 - lam) * prior_z
        smoothed[f] = FactorScore(z_score=blended_z, ...)
    return smoothed
```

PR1: λ=1.0 (no-op). 미래 cycle transition 시점 측정 후 활성화.

## 8. Mandate projection (Stage 2e)

```python
def project_to_mandate(bucket_weights):
    """위험자산 ≤ 0.70, 단일 ≤ 0.20 enforce."""
    # Step 1: clip negative weights (sign-restricted factor 의 extreme z 방어)
    for b in BUCKETS:
        bucket_weights[b] = max(0.0, bucket_weights[b])

    # Step 2: renormalize to sum=1
    total = sum(bucket_weights.values())
    bucket_weights = {b: w / total for b, w in bucket_weights.items()}

    # Step 3: 위험자산 cap 적용
    risk_assets = bucket_weights["kr_equity"] + bucket_weights["global_equity"] + \
                  bucket_weights["fx_commodity"]
    if risk_assets > 0.70:
        scale = 0.70 / risk_assets
        for b in ("kr_equity", "global_equity", "fx_commodity"):
            bucket_weights[b] *= scale
        # 줄어든 분량을 bond + cash 에 proportionally 분배
        shortfall = 1.0 - sum(bucket_weights.values())
        bond_cash_total = bucket_weights["bond"] + bucket_weights["cash_mmf"]
        if bond_cash_total > 0:
            bucket_weights["bond"] += shortfall * (bucket_weights["bond"] / bond_cash_total)
            bucket_weights["cash_mmf"] += shortfall * (bucket_weights["cash_mmf"] / bond_cash_total)
        else:
            bucket_weights["bond"] += shortfall

    # Step 4: 단일 ETF cap (≤0.20) 은 *Stage 3 의 portfolio_allocator + Stage 5 validator* 에서 enforce.
    # Stage 2 의 출력은 *bucket level 5-vector* — 각 bucket 안의 ETF cap 은 본 단계 scope 외.
    # bucket weight 가 0.45 (예: bond) 같이 0.20 초과해도 OK — bucket 은 *category*, ETF 아님.

    return bucket_weights
```

## 9. Downstream interface 변경

### 9.1 `ResearchDecision` schema

```python
class ResearchDecision(BaseModel):
    # 유지 (interface compat)
    bucket_target: BucketTarget                 # 5 bucket weight + bond_tips_share

    # 신설 (factor model output)
    factor_scores: dict[str, float]              # 9 factor z-scores
    factor_contributions: dict[str, dict[str, float]]  # factor → bucket contribution (attribution)
    baseline_bucket: dict[str, float]            # used baseline (for attribution)

    # 유지 + 재정의
    conviction: Literal["high", "medium", "low"]  # factor sign agreement + magnitude 기반
    dominant_scenario: str                       # legacy compat — factor → scenario name mapping

    # 제거
    # - scenario_probabilities (24-cell)
    # - dominant_cell, dominant_cell_probability
    # - dominant_cycle, dominant_cycle_probability
    # - cycle_marginals, tail_marginals, kr_marginals
    # - effective_cycle_marginals
    # - conviction_beta
```

### 9.2 `dominant_scenario` 재정의 (legacy compat)

```python
def derive_dominant_scenario(factor_scores: FactorScores) -> str:
    """Legacy 8 scenario name 으로의 deterministic mapping.

    Priority:
    1. F7 equity_vol_regime z > +1.5 + F5 credit_cycle z > +1.0 → "global_credit"
    2. F6 krw_regime의 stress > +1.0 → "kr_stress"
    3. F6 krw_regime의 boom > +1.0 → "kr_boom"
    4. F1 + F2 quadrant:
        F1 > 0.5 + F2 > 0.5 → "overheating"
        F1 > 0.5 + F2 < -0.5 → "goldilocks"
        F1 < -0.5 + F2 > 0.5 → "stagflation"
        F1 < -0.5 + F2 < -0.5 → "broad_recession"
        그 외 → "goldilocks" default
    """
    ...
```

### 9.3 `conviction` 재정의

```python
def derive_conviction(factor_scores: FactorScores) -> str:
    """Factor 들의 *sign agreement* + *magnitude* 기반.

    - High: 주요 factor 들의 sign 이 *일치* + magnitude 합이 크다.
    - Medium: mixed signal.
    - Low: 박빙 또는 sign 충돌.
    """
    # Sum of absolute z (magnitude)
    total_magnitude = sum(abs(s.z_score) for s in factor_scores.values())

    # Sign agreement metric (each factor 의 sign 의 *aligned-ness*)
    # 자세한 알고리즘: PCA 또는 단순 dot-product
    sign_alignment = compute_sign_alignment(factor_scores)

    if total_magnitude > 4.0 and sign_alignment > 0.6:
        return "high"
    if total_magnitude > 2.0 and sign_alignment > 0.3:
        return "medium"
    return "low"
```

### 9.4 Downstream caller 영향

| Caller | 사용 field | 영향 |
|---|---|---|
| `portfolio_allocator` | `dominant_cell.key` (priority) or `dominant_scenario` (fallback) | dominant_cell 제거 → fallback path 만 — *코드 수정 필요* |
| `method_picker` | `dominant_scenario`, `conviction` | interface 유지 — *코드 변경 없음* |
| `risk_judge` | research_decision (전체) | factor_scores 추가 사용 가능 — 선택 |
| `macro_conditional_lens` | `dominant_scenario`, `conviction` | interface 유지 — *코드 변경 없음* |
| `portfolio_manager` | research_decision (LLM 에 전달) | 새 schema 로 narrative 생성 — prompt 변경 |

**portfolio_allocator 의 dominant_cell 의존 제거**:
```python
# Before
if cell is not None:
    dominant_scenario = cell.key   # "B_N_F"
else:
    dominant_scenario = research_decision.dominant_scenario

# After
dominant_scenario = research_decision.dominant_scenario  # always string
```

candidate_selector 의 `log_boost(scenario, sub_category)` 가 cell key 받던 path 제거 — legacy scenario name 만.

## 10. Validation + Regression test policy

### 10.1 본 PR 의 acceptance criteria

| Test | Threshold | Action if fail |
|---|---|---|
| Walk-forward OOS Sharpe (full sample) | > 현 framework + 0.05 | 폐기 또는 design 재검토 |
| Walk-forward OOS Sharpe | ≥ 60/40 KR-tilted benchmark | 폐기 또는 design 재검토 |
| Sign restriction violation | 0 | calibration constraint 강화 |
| Mandate violation in backtest | 0 | projection 알고리즘 fix |
| Sub-period stability (Coefficient CV) | < 0.7 | factor 또는 model 재검토 |
| Bootstrap CI excludes 0 (significant) | ≥ 15 / 45 coefficients | 부족 → model 의 statistical power 부족 인정 |

### 10.2 Regression test 정책

`tests/` 안의 *의무 test*:

#### Unit tests

- `tests/unit/skills/research/test_factor_estimators.py`: 9 factor 각각의 *deterministic computation* 검증. Mock Stage 1 input → expected z-score.
- `tests/unit/skills/research/test_factor_indicator_validity.py`: §4.5 의 reliability audit 강제 (component / weight 변경 시 test fail).
- `tests/unit/skills/research/test_factor_to_bucket.py`: additive regression formula 검증. Mock factor scores → expected bucket weights.
- `tests/unit/skills/research/test_mandate_projection.py`: mandate enforcement 검증 (extreme z 입력 시 항상 위험자산 ≤ 0.70).
- `tests/unit/agents/test_research_manager_factor_model.py`: end-to-end node 호출 (mock state → ResearchDecision).
- `tests/unit/schemas/test_research_decision_schema.py`: 신 schema validation.

#### Integration tests

- `tests/integration/test_stage2_factor_model_e2e.py`: 2026-05-15 fixture 로 e2e 호출 (replay 사용). 모든 stage (Stage 2 → 3 → 4 → 5 → 6) 가 작동 + mandate 통과.
- `tests/integration/test_stage2_factor_model_backtest.py`: walk-forward backtest 의 *최소 runnable* 버전 (5-year sample 만 — fast).

#### Calibration tests

- `tests/calibration/test_walk_forward.py` (신규 디렉토리): full walk-forward backtest. Slow (~5-10분). CI optional.

#### Regression tests *원칙*

```
1. 모든 코드 modification (factor 추가/삭제, weight 변경, formula 변경, β table 변경) 시 
   *해당 영역* 의 unit test 추가/갱신 의무.
   
2. Factor 의 *component 또는 weight* 변경 시:
   - test_factor_indicator_validity.py 의 audit table 명시적 update.
   - 이게 *코드 변경의 일부* (test 가 audit update 강제).
   
3. β table 변경 (recalibration 포함) 시:
   - calibration artifacts (artifacts/<date>/factor_calibration/) 갱신.
   - walk_forward_results.csv 의 OOS Sharpe report.
   - 본 PR 의 acceptance criteria 통과 검증.

4. Schema 변경 (ResearchDecision field 추가/제거) 시:
   - schema test 갱신.
   - downstream caller 의 test 도 갱신 (interface 영향 검증).

5. Stage 1 의 *입력 field* 변경 (Gap E/G 의 임시 fetch → 정식 Stage 1 migration 시) 시:
   - factor estimator 의 *input source* 변경 — unit test 의 input mock 갱신.
   - integration test 로 e2e 검증.

6. *어떤 PR* 도 regression test 부재 시 *block* (CI failure).
```

### 10.3 Indicator validity의 *재검증* 의무

본 design 의 *2026-05 reliability audit* 은 *시점 의존*. 시간 흐름에 따라:
- 매 6개월: factor reliability audit 재실행 권장.
- Post-COVID labor market 변화, AI 환경 변화, regime change 시 즉시.
- audit 변경 시 *code (weights) + test (audit table) + spec doc* 동시 update.

`tests/unit/skills/research/test_factor_indicator_validity.py` 의 audit table 이 *single source of truth* — 코드 + spec doc 가 이를 reference.

## 11. Test strategy summary

### 11.1 신규 test 수

| 영역 | 신규 test 수 (대략) |
|---|---|
| Factor estimators (9 factor × ~5 case) | 45 |
| Factor → bucket | 10 |
| Mandate projection | 8 |
| Research manager e2e | 5 |
| Schema | 5 |
| Indicator validity | 10 |
| Integration | 5 |
| Calibration | 3 |
| **Total** | **~91** |

### 11.2 Regression target

본 PR merge 후:
- Pre-existing 3 unit fail + 18 integration fail 의 *증가 없음* (Mega-PR 의 baseline 유지).
- 24-cell scenario_mapper tests (Mega-PR 에서 추가된 9 + 2 = 11 test) *제거됨* (해당 영역 코드 제거 동반) — *기존 functionality 의 손실 아님* (factor model 이 동등 또는 우월 기능).

## 12. Migration plan

### 12.1 PR1 의 commit 구조

```
C1: Issue A fix (sub-graph wrapper 제거) + ResearchDecision schema 변경
    ↳ debate_state.py, debate_subgraph.py 제거
    ↳ trading_graph.py 의 wrapper 제거
    ↳ ResearchDecision schema 변경 (factor_scores 추가, scenario_probs 제거)
    ↳ downstream caller minimal change (dominant_cell.key 의존 제거)
    
C2: Factor estimator 9개 구현
    ↳ tradingagents/skills/research/factor_estimators.py 신설
    ↳ factor_baselines.py 신설 (long-run mean/sd)
    ↳ external_fetchers.py 신설 (KRW/USD, P/E 임시 fetch)
    ↳ unit test 추가

C3: Factor → bucket mapping
    ↳ factor_to_bucket.py 신설
    ↳ INITIAL_BETA + INITIAL_BASELINE hand-coded
    ↳ mandate projection
    ↳ unit test

C4: research_manager 의 factor model wire-up
    ↳ ESTIMATOR_PROMPT 및 LLM 호출 제거
    ↳ Stage 2a → 2c → 2d → 2e pipeline
    ↳ EMA infrastructure 유지 (factor space)
    ↳ dominant_scenario / conviction 재정의
    ↳ e2e unit + integration test

C5: 24-cell framework 제거
    ↳ scenario_mapper.py, scenario_definitions.py 제거
    ↳ ScenarioProbabilities24 등 schema 제거
    ↳ sub_category.py 의 cell key 의존 제거
    ↳ 기존 test 의 24-cell 의존 test 제거 (factor model test 로 대체)

C6: Walk-forward calibration
    ↳ scripts/calibrate_factor_model.py 신설
    ↳ 1991-2024 quarterly historical 준비 (재사용 가능 부분 활용)
    ↳ Hybrid calibration with shrinkage grid + sample window grid
    ↳ calibration artifacts 저장
    ↳ acceptance criteria 검증
    
C7: 2026-05-15 산출물 재생성
    ↳ artifacts/2026-05-15/{portfolio.json, philosophy.md, trade_plan.csv} regen
    ↳ stage2_diff_factor_model.md 작성 (pre/post 비교)
    ↳ philosophy.md 의 narrative 가 factor 기반 (대회 향)

C8: 문서 + Stage 1 backlog 등록
    ↳ docs/followup_issues.md 에 Issue #12-#19 (Stage 1 backlog) 등록
    ↳ docs/superpowers/specs/.../audit.md 의 status update
```

### 12.2 Mega-PR execution protocol 적용

본 PR 이 8 commit (~120-150시간) — Mega-PR 의 execution protocol (`2026-05-20-stage2-execution-protocol.md`) 동일 적용:
- decisions.md 외부화 (factor weight, shrinkage 등 결정 인쇄)
- job_status.json (calibration backtest 가 background)
- regression_log.md (각 commit 직후 결과)
- spec 인용 line 번호 (factor / β coefficient 의 source)

## 13. Non-goals (의식적 제외)

- LLM critic (PR1 외 future expansion)
- Bucket grouping 재정의 (fx_commodity 분할 등) — mandate 호환 별도 결정
- Stage 1 신호 추가 (Gap A-H) — 별도 Stage 1 PR
- Stage 3 (ETF selection) 변경 — 별도 작업 중
- Stage 4 (risk overlay) 변경
- Mandate 자체 변경
- Phase 2 (multi-estimator ensemble Q/M/H)

## 14. Risks + mitigations

| Risk | Mitigation |
|---|---|
| Walk-forward OOS Sharpe 가 60/40 미달 | acceptance criterion 명시 — 미달 시 polite rollback. 본 PR 의 빌드 시간 sunk. |
| Calibration 의 *over-fit* | shrinkage + walk-forward + sign restriction. CV < 0.7 검증. |
| 임시 yfinance fetch 의 rate limit / 실패 | retry + 5-min cache. 실패 시 *factor F6/F8 의 confidence ↓* 명시 (LLM fallback 가능). |
| 2026-05 reliability audit 의 *miscalibration* | indicator_validity test 가 변경 강제. 6m 주기 재검증. |
| Downstream caller 의 cell.key 의존 path 의 누락 | C1 의 grep audit + downstream test 확장. |
| `dominant_scenario` 재정의가 *기존 downstream 의도와 불일치* | C5 후 e2e test 로 method_picker 등 의 분기 변경 점검. |
| Calibration 시간 (walk-forward 가 ~3-5분 × multiple grid) | calibration script 가 background. CI 분리. |
| Mega-PR 의 EMA/hysteresis 가 factor space 에서 *재설계 시* hidden bug | infrastructure 유지 + λ=1.0 default (no-op). 명시적 test. |

## 15. Acceptance + Sign-off

본 PR merge 의 조건:
- [ ] 모든 unit test pass (신규 ~91 + 기존 유지 부분).
- [ ] Integration test pass.
- [ ] Walk-forward OOS Sharpe > 현 framework + 0.05.
- [ ] Walk-forward OOS Sharpe ≥ 60/40 KR-tilted.
- [ ] Sign restriction violation = 0.
- [ ] Mandate violation = 0 in full backtest.
- [ ] Sub-period stability CV < 0.7.
- [ ] 2026-05-15 산출물 mandate 통과.
- [ ] Stage 1 backlog (Issue #12-#19) followup_issues.md 등록.
- [ ] `docs/followup_issues.md` 의 Issue #6 (D7 deferred) 상태 update — factor model 의 *_BASELINE 의존 이전* 명시.
- [ ] `docs/superpowers/specs/2026-05-22-stage2-pipeline-audit.md` 의 Issue A/B/C/H/L/M 상태 *resolved* update.
- [ ] philosophy.md 의 narrative 가 factor-based (대회 5/28 대비).

---

## 16. 참조

- Stage 2 Mega-PR (predecessor): `docs/superpowers/specs/2026-05-20-stage2-bottleneck-fix-design.md`
- Audit (motivation): `docs/superpowers/specs/2026-05-22-stage2-pipeline-audit.md`
- Mega-PR execution protocol: `docs/superpowers/plans/2026-05-20-stage2-execution-protocol.md`
- Followup issues: `docs/followup_issues.md`
- DB GAPS agent redesign (parent system): `docs/superpowers/specs/2026-05-09-db-gaps-agent-redesign-design.md`
- Memory policies: `feedback_regression_tests.md` (regression test 의무), `feedback_long_session_protocol.md` (long-session 8 원칙)
