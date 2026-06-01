# Stage 3 Portfolio Allocation — Implementation Summary

**작성일**: 2026-05-30
**범위**: Phase 1 → Phase 4d (10 phases, 2026-05-28 ~ 2026-05-30)
**최종 main commit**: `8699446` (Phase 4d merge)
**누적 test 수**: 신규 ~100 tests, 통합 후 151 PASS

---

## 0. Stage 3 의 목적

Stage 3 는 Stage 2 의 산출물 (regime / scenario / candidates) 을 받아 **portfolio weights** 를 결정한다. 핵심 책임:

1. **종목 선정** — universe 에서 bucket 별로 ETF 선택 (candidate_selector)
2. **Optimization** — 선택된 종목에 weight 부여 (allocator)
3. **사후 검증** — ENB 분산도, cap 준수, attribution trace
4. **Validator/Retry** — 인증 안 통과 시 method downgrade

Stage 3 가 다루는 결정 변수:
- 어떤 ETF 들을 portfolio 에 포함할지 (selection)
- 각 ticker 의 비중 (weights ∈ [0, cap])
- bucket 간 배분 (sector constraints)
- 어떤 optimizer method 를 쓸지 (method_picker)

---

## 1. Phase 별 단계별 설명

### Phase 1 — Cash Spillover + ENB + AUM Filter 제거 (2026-05-28, `c0be9b2`)

**Why**: 기존 구조의 3가지 문제 해결:
- cash 가 spillover 없이 buffer 만 차지
- ENB (Effective Number of Bets) 미측정 → 다양화 정도 불명
- AUM 최소 필터 (500억) 가 small ETF 배제 → universe 축소 위험

**핵심 변경**:
1. `cash_spillover.py` 신규: cash bucket 의 잉여를 다른 bucket 에 conviction 기반 재분배
2. `diversification.py`: `compute_enb(weights, sigma, method="minimum_torsion")` 으로 portfolio 의 진짜 베팅 수 측정
3. `select_etf_candidates` 의 AUM 최소 필터 제거 (선정 단계에서 제외 안 함)

**Adapter / 입력 흐름**:
```
Stage 2 → candidates_per_bucket (no AUM filter)
  → allocator weights
  → ENB 사후 측정 (warning if ENB < 3.0)
  → cash_spillover (conviction × residual)
```

**User-modified deviations** (구현 시):
- `spillover_ratio = 1 - conviction` (원래 안 `1 - conviction/threshold`)
- `minimum_torsion_decomposition` 의 분모를 eigenvalues 사용 (원래 안 `diag(Σ)`)

**Tests**: 4 통합 + Phase 1 의 4 skip tests (Phase 2b 에서 활성)

---

### Phase 2a — ETF Metrics + impl_score 4-요소 (2026-05-29, `1993d6c`)

**Why**: `log_aum` 단독 score 로는 ETF 의 "실행 품질" 표현 부족. premium/discount, tracking error, 거래량 등 동시 고려 필요.

**핵심 변경**:
1. `etf_metrics.py` 신규: KRX OpenAPI 에서 ETF 일별 detail (NAV, market_price, volume, AUM) fetch + 메트릭 계산
   - `premium_discount = market_price / NAV - 1`
   - `tracking_error` (12개월 window)
   - `volume_per_aum` (30일 median)
2. `compute_impl_score` 4-요소 weighted composite:
   ```
   impl_score(t) = +0.33 × z(log_aum)
                  + 0.17 × z(volume_per_aum)
                  + (-0.28) × z(|premium_discount|)
                  + (-0.22) × z(tracking_error)
   ```
3. `select_etf_candidates` 에 impl_scores dict 전달

**KRX endpoint 404 issue**:
- `etf/etf_bydd_trd` endpoint 가 운영상 404 → graceful fallback (log_aum 단독)
- 정상 동작 시 4-요소, 실패 시 1-요소 — 둘 다 backward-compat

**Tests**: unit 4 + integration 4

---

### Phase 2b — ENB Greedy + Adaptive n_max (2026-05-30, `9bd46c9`)

**Why**: 기존 cluster-aware top-N 가 강제 N 선정 → 의미 없는 종목까지 포함. ENB greedy 가 "다음 종목이 분산 가치 ΔENB ≥ threshold" 인 것만 추가.

**핵심 변경**:
1. `select_cluster_aware` + `_corr_groups` **삭제** (clean break)
2. `compute_adaptive_n_max(n_positive_alpha, bucket_weight, capital_krw)` — 4 cap min
   - `n_positive_alpha`
   - `bucket_weight / 0.025` (MIN_BUCKET_POSITION_RATIO)
   - `bucket_weight × capital_krw / 50M` (MIN_POSITION_KRW)
   - `ABS_MAX_PER_BUCKET = 8`
3. `select_by_enb_greedy(eligible, alpha, impl_scores, sigma, n_max, ...)`:
   - Composite seed: `0.85α + 0.15 impl` (ALPHA_IMPL_BLEND_DEFAULT)
   - Stop: `ΔENB < 0.15` (ENB_DELTA_THRESHOLD) or n_max or pool 고갈
4. `select_etf_candidates` 시그니처: `sigma` + `capital_krw` 추가, `per_bucket_n` 제거
5. `portfolio_allocator`: `sigma = returns.dropna(axis=0).cov()` 사전 계산
6. `_allocator_state_helpers.py` 신규 — Phase 1 의 4 skip tests 활성

**Results (2026-05-15 e2e)**:
- selection_strategy = 'enb_greedy'
- n_total: 18 → 9 (**50% 감소**, 의미 있는 종목만)
- ENB: 4.25

**Tests**: 5 unit + Phase 1 의 4 skip 활성

---

### Phase 3a — NCO Bucket-Internal Optimizer (2026-05-30, `be9c976`)

**Why**: HRP/MV/RP 의 cluster 인식 약함. Lopez de Prado 2019 NCO (Nested Clustered Optimization) 가 bucket 내 cluster + inter-cluster 균형 → 더 robust.

**핵심 변경**:
1. `nco.py` 신규 5 함수:
   - `_opt_port(cov, mu=None)` — closed-form CVO (min-var when mu=None, max-sharpe when mu given)
   - `_hierarchical_cluster(corr, max_num_clusters)` — single-linkage + silhouette best k
   - `_intra_cluster_weights(cov, labels, mu=None)` — n_assets × n_clusters DataFrame
   - `_inter_cluster_weights(reduced_cov, reduced_mu)` — wraps _opt_port
   - `compute_nco_weights(returns, mu, max_num_clusters, breakdown_out)` — full algorithm
2. `OptimizationMethod.NCO = "nco"` Pydantic enum 추가
3. `_nco_per_bucket` helper (HRP-per-bucket 패턴) + allocator NCO 분기
4. `state["force_method"]` A/B 메커니즘 — `MethodChoice(rule_fired="state_override", rule_index=-1)`
5. `scripts/run_e2e_test.py --force-method` (6 method choice)

**NCO 알고리즘 outline**:
```
1. Hierarchical clustering on √((1-corr)/2) distance (single-linkage)
2. Best k via silhouette score
3. Intra-cluster CVO (each cluster 내 weights)
4. Reduced Σ̂ = intra.T @ Σ @ intra (cluster level cov)
5. Inter-cluster CVO on reduced Σ̂
6. Final weights = intra @ inter
```

**Tests**: 20 unit + 7 integration = 27 신규 PASS

---

### Phase 3b — Black-Litterman Views Adapter (2026-05-30, `688dd20`)

**Why**: BLACK_LITTERMAN enum 만 존재하고 dead code 상태. method_picker 도 BL 을 절대 선택 안 함. Stage 2 의 scenario + regime_confidence 에서 BL views (P, Q, confidence) 자동 생성하는 adapter 필요.

**핵심 변경**:
1. `bl_views.py` 신규:
   - `SCENARIO_BUCKET_RULEBOOK`: 9 scenario × 5 bucket → 연환산 expected return
   - `BL_VIEW_MIN_CONFIDENCE = 0.10` (Idzorek-Walters Ω 안정성 floor)
   - `generate_bl_views(...)` — bucket-agnostic, unknown scenario → graceful fallback
2. `method_picker`:
   - `BL_TRIGGER_CONFIDENCE = 0.7` 상수
   - rule 2 (scenario_mapping) 보다 먼저 BL trigger rule
   - 기존 rule 2~6 의 rule_index +1 shift
3. `portfolio_allocator` BL 분기 활성화:
   - `_optimize_with_bucket_constraints` 시그니처에 `scenario`, `regime_confidence` 추가
   - `method_params['_bl_trigger']=True` 면 `generate_bl_views` 호출
   - `attribution.bl_views_breakdown` / `bl_views_fallback` 기록

**SCENARIO_BUCKET_RULEBOOK 일부 (cell = annualized expected return)**:
| scenario | kr_equity | global_equity | fx_commodity | bond | cash_mmf |
|---|---|---|---|---|---|
| goldilocks | 0.10 | 0.12 | 0.02 | 0.04 | 0.025 |
| broad_recession | -0.08 | -0.05 | -0.02 | 0.08 | 0.025 |
| late_cycle | 0.02 | 0.04 | 0.08 | 0.06 | 0.025 |
| kr_boom | 0.13 | 0.08 | 0.02 | 0.03 | 0.025 |

**E2E (2026-05-15)**: regime_confidence=0.91 → BL **자동 트리거**. method=black_litterman, scenario=late_cycle, n_views=13, ENB=4.46.

**Tests**: 12 unit + 4 picker + 7 integration = 23 신규 PASS

---

### Phase 3c — NCO Backbone Cutover (2026-05-30, `0807562`)

**Why**: NCO 가 Phase 3a 에서 force_method 로 검증 완료. method_picker 의 모든 HRP 출력을 NCO 로 격상 → production backbone.

**핵심 변경** (6 line-level):
1. `_SCENARIO_METHOD` 4 cell: `overheating`, `goldilocks`, `ai_concentration`, `kr_boom` 모두 HRP → NCO
2. rule 7 default HRP → NCO
3. `LOW_CONVICTION_HRP_DOWNGRADE` 상수 + scenario_mapping rule 의 downgrade 블록 **제거**
4. `inputs_trace["downgraded_from_hrp"]` key 사라짐

**보존** (force_method='hrp' A/B 용):
- `OptimizationMethod.HRP` enum
- `_hrp_per_bucket` 함수
- allocator HRP 분기 코드
- MV/RP cells (defensive scenarios — global_credit, broad_recession, kr_stress, stagflation, late_cycle, regime_growth_inflation)

**method_picker rule precedence (Phase 3c 후)**:
```
rule 0 degraded_inputs       → MV  (defensive)
rule 1 systemic_extreme      → MV  (defensive)
rule 2 bl_high_confidence    → BL  (Phase 3b)
rule 3 scenario_mapping      → MV / RP / NCO
rule 4 regime_recession      → MV
rule 5 systemic_risk_off     → MV
rule 6 regime_growth_inflation → RP
rule 7 default               → NCO (이전 HRP)
```

**E2E (2026-05-15)**: regime_conf=0.91 → BL trigger 우선이라 method=black_litterman 그대로 (회귀 무손실). NCO backbone 효과는 unit/integration test 로 검증.

**Tests**: 7 신규 unit + 3 integration = 10 신규 PASS

---

### Phase 4a — Ledoit-Wolf Linear Shrinkage Cov (2026-05-30, `7ff5f9e`)

**Why**: 모든 method 가 condition 하는 covariance 의 추정량을 sample_cov 에서 Ledoit-Wolf shrinkage 로 격상. small-sample noise 가 weight concentration 으로 propagate 차단.

**핵심 변경**:
1. `cov_estimator.py` 신규:
   - `compute_robust_cov(returns, *, breakdown_out=None) -> pd.DataFrame`
   - pypfopt `CovarianceShrinkage(returns).ledoit_wolf()` wrap
   - δ shrinkage intensity 노출 (constant returns → fallback)
2. 8 호출지 sample_cov → compute_robust_cov:
   - `portfolio_allocator.py:537` + attribution.cov_breakdown
   - `overlay_apply.py:79`
   - `optimizers.py:39/56/88` (min_vol, risk_parity, BL)
   - `conditional_logic.py:48`
   - `nco.py:142` (n=2 shortcut), `:153` (general path + breakdown)
3. `nco.py:154` `returns.corr()` **unchanged** (clustering distance 용 raw)

**attribution 구조**:
```json
{
  "cov_breakdown": {
    "estimator": "ledoit_wolf",
    "shrinkage_intensity": 0.0776,
    "n_obs": 218,
    "n_assets": 13
  }
}
```

**E2E (2026-05-15, --force-method nco)**:
- δ=0.0776 (top-level)
- Per-pool: kr_equity δ=0.0812, global_equity δ=0.0700

**관찰**: δ 작음 — sample size T=218 에서 sample cov 도 stable. 큰 효과는 small universe 또는 nonlinear (Phase 4d) 에서.

**Tests**: 6 unit + 3 integration = 9 신규 PASS

---

### Phase 4b — BL Tilt Dial (regime별 τ + view_conf multi) (2026-05-30, `e70e790`)

**Why**: Phase 3b 의 BL_TRIGGER_CONFIDENCE 고정값 + view_confidences=regime_confidence 단순 사용. scenario 별로 BL 강도 differentiated 필요 (goldilocks 는 view 우세, recession 은 prior 우세).

**핵심 변경**:
1. `bl_views.py` 의 매트릭스 추가:
   - `SCENARIO_BL_TILT`: 9 scenario × (tau, view_conf_multi)
   - 상수 4종 (clip bounds, defaults)
2. `generate_bl_views` 시그니처 확장: return tuple [2] → [3] (tilt_params 추가)
3. allocator BL 분기:
   - `BlackLittermanModel(tau=tilt_params["tau"])` 전달
   - `view_confidences` 는 post-multiplier 적용 + [0.05, 1.0] clipped
   - force_method 외부 주입 경로는 tilt 비적용 (기존 동작 보존)

**SCENARIO_BL_TILT 매트릭스**:
| scenario | tau | view_conf_multi |
|---|---|---|
| goldilocks | 0.10 | 1.3 |
| kr_boom | 0.10 | 1.3 |
| overheating | 0.07 | 1.0 |
| ai_concentration | 0.07 | 1.0 |
| late_cycle | 0.05 | 0.8 |
| stagflation | 0.05 | 0.7 |
| broad_recession | 0.025 | 0.5 |
| kr_stress | 0.025 | 0.5 |
| global_credit | 0.025 | 0.5 |

**E2E (2026-05-15)**: scenario=late_cycle, tilt={tau=0.05, multi=0.8, applied=True}, confidence_used=0.9.

**Tests**: 8 unit + 12 기존 갱신 + 4 integration = 12 신규 PASS

---

### Phase 4c — ENB CRITICAL Threshold + EW Fallback (2026-05-30, `47c222c`)

**Why**: ENB 사후 측정이 warning 만 — weights 가 집중되어 있어도 그대로 통과. 더 강한 CRITICAL threshold + EW fallback safety net.

**핵심 변경**:
1. `portfolio_allocator.py` 상수 2종:
   - `ENB_CRITICAL_THRESHOLD = 2.0`
   - `ENB_FALLBACK_MIN_TICKERS = 5` (1/n ≤ cap 보장)
2. `_apply_single_cap_redistribution(weights, cap, max_iter=10)` helper:
   - Iterative cap clip + non-capped 비례 분배
   - 빈 dict 안전 처리
3. post-optimization ENB check 4-way 분기:
   - `enb_action="none"`: ENB ≥ WARNING (정상)
   - `"warning_only"`: WARNING > ENB ≥ CRITICAL
   - `"warning_only_n_too_small"`: ENB < CRITICAL, n < 5 (fallback 무력화)
   - `"equal_weight_fallback"`: ENB < CRITICAL, n ≥ 5 (EW + cap clip 적용)

**attribution**:
```json
{
  "enb": 1.8,
  "enb_action": "equal_weight_fallback",
  "enb_post_fallback": 4.5
}
```

**E2E (2026-05-15)**: enb=3.306, enb_action="none" (정상, fallback 미발동, 회귀 무손실).

**Tests**: 5 unit + 4 integration = 9 신규 PASS

---

### Phase 4d — QIS Nonlinear Shrinkage (2026-05-30, `8699446`)

**Why**: Phase 4a 의 linear LW 는 단일 δ 로 모든 eigenvalue 균일 축소. 큰 / 작은 eigenvalue 는 noise 특성이 달라 per-eigenvalue 차등 shrinkage 가 더 정확. Ledoit-Wolf 2020 QIS 가 closed-form per-eigenvalue.

**핵심 변경**:
1. `cov_estimator.py`:
   - `_qis_cov(Y, k=1)` NumPy 구현 (Ledoit-Wolf 2020 Algorithm 1):
     - Eigendecomposition + Hilbert transform + spectral density estimate
     - Eq 4.5: `d_i^* = λ_i / [(1-c-πcλH)² + (πcλf)²]`
   - `compute_robust_cov(returns, *, method='qis', breakdown_out=None)` 시그니처 확장
   - method='qis' (default) | 'ledoit_wolf' | unknown → fallback
2. 8 호출지 자동 QIS (signature 변경 없이 default 효과)
3. attribution.cov_breakdown.estimator = "qis" default

**shrinkage_intensity 의미 변경**:
- linear: δ ∈ [0, 1] (단일 강도)
- QIS: mean(1 - d/λ) — lower bound 없음 (관측 -1.18 까지). 음수 = 작은 λ 가 sample 보다 커지는 정상 동작.

**E2E (2026-05-15, default BL)**:
- estimator='qis', intensity=-0.280
- NCO pool bond_nominal: intensity=-0.066
- weight sum=1.0, n_total=10

**Known issues**:
- regression (d) fx_commodity drift: QIS ≠ LW → 다른 weights (fx 0.120 → 0.201). baseline refresh 필요.
- NCO 2 unit test tolerance 확장: 작은 N=4 에서 QIS ≠ LW 차이.

**Tests**: 6 unit + 2 기존 갱신 + 2 integration = 10 신규 PASS

---

## 2. 누적 통계

| Phase | merge SHA | 신규 tests | 통합 PASS | 핵심 변경 |
|---|---|---|---|---|
| 1 | c0be9b2 | ~10 | ~80 | cash_spillover + ENB + no AUM filter |
| 2a | 1993d6c | ~10 | ~90 | impl_score 4-요소 |
| 2b | 9bd46c9 | ~10 | ~95 | ENB greedy + adaptive n_max |
| 3a | be9c976 | 27 | ~125 | NCO bucket-internal |
| 3b | 688dd20 | 23 | ~145 | BL views adapter |
| 3c | 0807562 | 10 | 113 | NCO backbone cutover |
| 4a | 7ff5f9e | 9 | 122 | LW linear shrinkage cov |
| 4b | e70e790 | 12 | 134 | BL tilt dial |
| 4c | 47c222c | 9 | 143 | ENB CRITICAL + EW fallback |
| 4d | 8699446 | 10 | 151 | QIS nonlinear shrinkage |

**Total**: ~100 신규 tests across 10 phases.

---

## 3. 최종 architecture (Stage 3 entire data flow)

```
┌─────────────────────────────────────────────────────────────┐
│  Stage 2 outputs                                            │
│    regime_quadrant / regime_confidence                       │
│    dominant_scenario (9 scenario)                            │
│    factor_panel                                              │
└──────────────────┬──────────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  Phase 2a: ETF metrics fetch                                 │
│    KRX OpenAPI → ETFDailyMetrics (NAV, P/D, volume, AUM)    │
│  Phase 2a: impl_score 4-요소 composite                       │
│    + 0.33 z(log_aum) + 0.17 z(vol/AUM)                       │
│    - 0.28 z(|P/D|) - 0.22 z(TE)                              │
└──────────────────┬──────────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  Phase 2b: ENB greedy selection                              │
│    composite seed = 0.85α + 0.15 impl                        │
│    forward greedy add until ΔENB < 0.15 or n_max             │
│    n_max = min(n_α⁺, bucket/MIN_RATIO, capital/MIN_KRW, 8)  │
│  → candidates_per_bucket                                     │
└──────────────────┬──────────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  Phase 3b: method_picker (8 rule chain)                      │
│    0. degraded_inputs → MV                                   │
│    1. systemic_extreme → MV                                  │
│    2. bl_high_confidence (Phase 3b)                          │
│       conf ≥ 0.7 + scenario in RULEBOOK → BL                 │
│    3. scenario_mapping (Phase 3c)                            │
│       NCO 4 cells / MV 3 cells / RP 2 cells                  │
│    4-6. regime / systemic fallback                           │
│    7. default → NCO (Phase 3c, 이전 HRP)                     │
│  + state["force_method"] override (Phase 3a A/B)             │
└──────────────────┬──────────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  Phase 4d: compute_robust_cov (default qis)                  │
│    QIS per-eigenvalue nonlinear shrinkage                    │
│    (or method='ledoit_wolf' for Phase 4a linear)             │
│  → sigma_df 정확도 향상                                       │
└──────────────────┬──────────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  portfolio_allocator (method 분기)                           │
│    NCO: bucket-internal hierarchical → intra+inter CVO      │
│    BL  (Phase 4b): tau + view_conf_multi (scenario tilt)    │
│    HRP: hierarchical risk parity                            │
│    MV / RP: pypfopt EfficientFrontier                        │
│  → wv: WeightVector                                          │
└──────────────────┬──────────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  Phase 4c: ENB post-optimization check                       │
│    ENB ≥ 3.0 (WARNING): none                                 │
│    2.0 ≤ ENB < 3.0: warning_only                             │
│    ENB < 2.0 + n ≥ 5: EW fallback (cap clip + redistribute)  │
│    ENB < 2.0 + n < 5: warning_only_n_too_small               │
└──────────────────┬──────────────────────────────────────────┘
                   ▼
┌─────────────────────────────────────────────────────────────┐
│  Phase 1: cash_spillover                                     │
│    cash bucket 잉여 → conviction × residual 비례 분배        │
└──────────────────┬──────────────────────────────────────────┘
                   ▼
                 Final weights → Validator
```

---

## 4. 핵심 상수 reference

### method_picker.py
```
BL_TRIGGER_CONFIDENCE: 0.7   (Phase 3b)
SYSTEMIC_EXTREME_THRESHOLD: 9 (이전)
ENB_DELTA_THRESHOLD: 0.15 (Phase 2b factor_scorer)
```

### portfolio_allocator.py
```
ENB_WARNING_THRESHOLD: 3.0   (기존)
ENB_CRITICAL_THRESHOLD: 2.0  (Phase 4c)
ENB_FALLBACK_MIN_TICKERS: 5  (Phase 4c)
SINGLE_ASSET_CAP: 0.20       (기존)
MIN_COV_OBS: 50              (기존)
```

### bl_views.py
```
BL_VIEW_MIN_CONFIDENCE: 0.10  (Phase 3b)
BL_VIEW_CONF_MIN_AFTER_MULTI: 0.05  (Phase 4b)
BL_VIEW_CONF_MAX_AFTER_MULTI: 1.0   (Phase 4b)
BL_TAU_DEFAULT: 0.05                (Phase 4b)
BL_VIEW_CONF_MULTI_DEFAULT: 1.0     (Phase 4b)
```

### factor_scorer.py (Phase 2b)
```
ENB_DELTA_THRESHOLD: 0.15
ABS_MAX_PER_BUCKET: 8
MIN_POSITION_KRW: 50_000_000
MIN_BUCKET_POSITION_RATIO: 0.025
N_MIN_HARD_FLOOR: 1
ALPHA_IMPL_BLEND_DEFAULT: 0.85
```

### nco.py (Phase 3a)
```
NCO_MAX_NUM_CLUSTERS_RATIO: 0.5
NCO_MIN_NUM_CLUSTERS: 2
NCO_LINKAGE_METHOD: "single"
NCO_MIN_VAR_REGULARIZATION: 1e-8
```

---

## 5. attribution 구조 (final, 모든 phase 통합)

```json
{
  "allocation_attribution": {
    "method_picker": {
      "method": "black_litterman",
      "rule_fired": "bl_high_confidence",
      "rule_index": 2,
      "inputs": {...}
    },
    "cov_breakdown": {
      "estimator": "qis",
      "shrinkage_intensity": -0.280,
      "n_obs": 218,
      "n_assets": 13
    },
    "bl_views_breakdown": {
      "scenario": "late_cycle",
      "regime_confidence_raw": 0.91,
      "confidence_used": 0.91,
      "n_views_per_bucket": {"kr_equity": 3, "global_equity": 3, "bond": 6},
      "rulebook_returns_used": {...},
      "tilt_params": {
        "tau": 0.05,
        "view_conf_multi": 0.8,
        "view_conf_multi_applied": true
      }
    },
    "optimization": {
      "nco_breakdown_per_pool": {
        "kr_equity": {
          "n_clusters": 2,
          "silhouette": 0.31,
          "cov_breakdown": {...}
        }
      }
    },
    "enb": 4.46,
    "enb_action": "none",
    "config": {
      "selection_strategy": "enb_greedy",
      "capital_krw": 1000000000
    }
  }
}
```

---

## 6. 잔존 항목

### Stage 3 audit deferred (이전)
- **TIPS baseline 0.30 tuning** — backtest 후 검토
- **Single-cap 0.20 mandate change** — const 값 변경 가능 (named 분리됨)

### Phase 4 followup
- **expense_ratio 5번째 impl_score 요소** — data source 부재 (KRX endpoint 추가 또는 universe.json 정적 필드 필요)
- **regression baseline refresh** — Phase 4d 도입 후 1회 (QIS 결과 반영)
- **5-regime backtest** — QIS + BL tilt dial + NCO backbone 의 실제 alpha 효과 검증
- **Per-eigenvalue intensity list 노출** — 현재 mean 만 (선택적)
- **HRP enum 자체 제거** — Phase 3d 후보 (force_method='hrp' A/B 종료 후)

### Pre-existing fail
- `tests/unit/agents/test_technical_analyst.py::test_technical_analyst_returns_report` — rank_momentum 빈 dict

### Stage 1+2 deferred (Stage 3 무관)
- Stage 1: classify_regime LLM prompt, ADX threshold tuning
- Stage 2: scenario hysteresis, derive_conviction 9-factor

---

## 7. 메모리 reference

각 phase 의 followup 메모:
- [stage3_phase1_followup](../.claude/projects/-Users-kimjaewon-Pluto-TradingAgents/memory/stage3_phase1_followup.md)
- [stage3_phase2a_followup](../.claude/projects/-Users-kimjaewon-Pluto-TradingAgents/memory/stage3_phase2a_followup.md)
- [stage3_phase2b_followup](../.claude/projects/-Users-kimjaewon-Pluto-TradingAgents/memory/stage3_phase2b_followup.md)
- [stage3_phase3a_followup](../.claude/projects/-Users-kimjaewon-Pluto-TradingAgents/memory/stage3_phase3a_followup.md)
- [stage3_phase3b_followup](../.claude/projects/-Users-kimjaewon-Pluto-TradingAgents/memory/stage3_phase3b_followup.md)
- [stage3_phase3c_followup](../.claude/projects/-Users-kimjaewon-Pluto-TradingAgents/memory/stage3_phase3c_followup.md)
- [stage3_phase4a_followup](../.claude/projects/-Users-kimjaewon-Pluto-TradingAgents/memory/stage3_phase4a_followup.md)
- [stage3_phase4b_followup](../.claude/projects/-Users-kimjaewon-Pluto-TradingAgents/memory/stage3_phase4b_followup.md)
- [stage3_phase4c_followup](../.claude/projects/-Users-kimjaewon-Pluto-TradingAgents/memory/stage3_phase4c_followup.md)
- [stage3_phase4d_followup](../.claude/projects/-Users-kimjaewon-Pluto-TradingAgents/memory/stage3_phase4d_followup.md)
- [stage3_audit_deferred](../.claude/projects/-Users-kimjaewon-Pluto-TradingAgents/memory/stage3_audit_deferred.md)

각 phase 의 spec / plan:
- `docs/superpowers/specs/2026-05-30-stage3-phase{4a,4b,4c,4d}-*-design.md`
- `docs/superpowers/plans/2026-05-30-stage3-phase{4a,4b,4c,4d}-*.md`

Phase 1~3 의 spec/plan 은 `docs/superpowers/specs/2026-05-{28,29,30}-stage3-phase*` 경로.
