# Stage 3 Audit — 2026-05-26

Plan: [docs/superpowers/plans/2026-05-26-stage3-audit.md](superpowers/plans/2026-05-26-stage3-audit.md)
Stage 1+2 deferred 흡수: method_picker / portfolio_allocator 의 regime/systemic_score staleness 검사 (Task 0).

---

## Stage 3 특성

- **LLM 호출 0회** (method_picker = 결정적, optimizer = pypfopt 수학)
- **이미 일부 logger 존재** (cov 표본, perf, overlay infeasible)
- **2 큰 코드 경로**: HRP per-bucket (직접 구현) vs EfficientFrontier (pypfopt)
- attribution dict 구조 가장 풍부

---

## Task 0 — Stage 1+2 staleness 검사 + strict MIN_VARIANCE

### 발견 (Stage 1+2 deferred)

- `portfolio_allocator.py:50-51` 의 `regime = state["macro_report"].regime` 와 `risk_score = state["risk_report"].systemic_score` 에 staleness 검사 0.
- Stage 1 의 macro_quant / market_risk 가 fetch 실패 시 sentinel(staleness=99) 객체로 만든 합성 regime / score 가 그대로 method_picker → optimizer 선택에 영향.
- 예: BSI / FCI / CFNAI 등 핵심 입력 다수 sentinel → macro_quant 가 "growth_disinflation, conf=0.5" 같은 placeholder regime 산출 → Stage 3 이걸 받아서 HRP 선택 → 실제로는 fetch 실패 상황인데 공격적 portfolio.

### 결정/수정

- allocator entry: `regime.staleness_days`, `risk_score.staleness_days` 검사. 둘 다 ≥99 면:
  - `attribution["config"]["degraded_inputs"] = True`
  - `logger.warning(...)`
- method_picker 시그니처 확장: `degraded_inputs`, `regime_staleness`, `systemic_staleness` 인자.
- **신규 rule 0** (rule_index=0, priority highest): `degraded_inputs=True` → `MIN_VARIANCE` 강제 (fail-safe).
- 정상 stale (1~7d) 통과 — 둘 다 완전 실패 (≥99) 시에만 발동.
- `SYSTEMIC_EXTREME_THRESHOLD = 8.0`, `LOW_CONVICTION_HRP_DOWNGRADE = True` named const.
- 각 rule fire 시 `logger.info` (rule 0 은 `logger.warning`).

### 회귀: 88 pass + 1 pre-existing fail.

---

## Task 1+2 — allocator + method_picker observability

### 발견

- portfolio_allocator: entry log 0 — per_bucket_n / attempts / conviction / scenario / eligible 수 추적 불가.
- Stage 2 의 `safety_diagnostics` + `factor_contributions` 가 ResearchDecision 에 채워지지만 Stage 3 attribution 에 thread 안 됨. Stage 6 narrative blind.
- `_optimize_with_bucket_constraints` 의 cov fallback: logger 만 있고 attribution 미기록 → "왜 이 ticker 가 빠졌지?" 즉답 불가.
- EF post-clip redistribute (cap clip) silent.
- Magic numbers 산재: `0.20` (single cap), `0.05` (retry band), `60` (cov obs), `365*3` (lookback), `0.85` (corr threshold).
- method_picker: 각 rule fire trace 없음 (inputs_trace dict 만), scenario downgrade silent.

### 결정/수정

- `logger.info` entry/exit (per_bucket_n, conviction, scenario, n candidates, final method, max_w, vol, sharpe, attempts).
- `attribution["research_safety"]` ← `research_decision.safety_diagnostics` 복사. intervention 시 `logger.warning`.
- `attribution["research_inputs"]["top_factor_contributors"]` ← top-3 `|β·z|` (factor, bucket, contribution_pp).
- `attribution["research_inputs"]["factor_scores"]` ← 9 factor z-dict.
- `attribution["cov_excluded_tickers"]`, `cov_final_obs` 기록.
- `_optimize_with_bucket_constraints` 시그니처에 `attribution` 인자 추가.
- `attribution["cap_clipped_tickers"]` 기록.
- 6 magic → named const:
  - `SINGLE_ASSET_CAP = 0.20`
  - `MIN_COV_OBS = 60`
  - `RETRY_BAND_WIDTH = 0.05`
  - `HRP_WATER_FILL_MAX_ITERS = 20`
  - `PRICE_LOOKBACK_DAYS_ALLOC = 365 * 3`
  - `CORRELATION_THRESHOLD_ALLOC = 0.85`
- method_picker 각 rule fire 시 logger.info (rule 0 은 warning).
- scenario downgrade 시 `inputs["downgraded_from_hrp"] = True` + logger 명시.

### 회귀: 97 pass.

---

## Task 3 — HRP per-bucket cap-saturation 가시화

### 발견

- `_hrp_per_bucket` 의 "all assets at cap" shortfall path: logger 없고 attribution 미기록. bucket target 미충족이 silent.
- Final normalization (sum≠1.0) intervene 발동 silent.
- magic `0.20`, `20` (max iter), `10` (cap loop) 산재.
- post-condition assertion 메시지에 violator (ticker, weight) list 없음.

### 결정/수정

- `_hrp_per_bucket` 시그니처에 `attribution` 인자 추가.
- Bucket cap-all 시 `logger.warning("HRP: bucket %s 의 모든 자산이 cap 도달")` + `attribution["hrp_bucket_shortfalls"]` list 에 `{bucket, pool_target, actual, shortfall, n_assets_capped}` 기록.
- Final normalization 발동 시 `logger.info` + `attribution["hrp_final_norm_intervened"]`.
- Magic 모두 `SINGLE_ASSET_CAP`, `HRP_WATER_FILL_MAX_ITERS` 사용.
- Post-condition assert 에 violator list 노출.

### 회귀: 83 pass.

---

## Task 4 — overlay_apply 5-level escalation 가시화

### 발견

- `apply_risk_overlay` 의 5 drop_level escalation: 각 level "무엇이 풀렸나" 코멘트로만 있고 named 안 됨. 결과 (final_level / dropped_constraints / all_failed) attribution 미기록.
- Magic `0.20` single-cap 산재.

### 결정/수정

- `OVERLAY_DROP_LEVELS: dict[int, str]` named dict (5 level → label).
- `SINGLE_ASSET_CAP_OVERLAY = 0.20` const.
- `apply_risk_overlay` 시그니처에 `attribution` 인자 추가. 다음 키 기록:
  - `final_level: int` (성공 level, 또는 -1 if overlay empty, None if all-fail)
  - `final_level_label: str`
  - `infeasible_levels: list[int]`
  - `infeasible_errors: list[str]`
  - `all_failed: bool`
  - `dropped_constraints: list[str]` (성공 level 까지 누적)
- 각 level 시도/성공/실패 logger 에 named label.

### 회귀: 5 overlay tests pass.

---

## Task 5 — Stage 3 통합 sanity

### 신규 unit test (method_picker)

- `test_degraded_inputs_forces_min_variance`: rule 0 fail-safe 발동 검증.
- `test_normal_staleness_does_not_trigger_strict_mode`: 1-7d stale 통과 검증.
- `test_low_conviction_downgrade_attribution`: HRP→RISK_PARITY downgrade 시 `inputs["downgraded_from_hrp"] = True` 검증.
- `test_named_const_present`: SYSTEMIC_EXTREME_THRESHOLD / LOW_CONVICTION_HRP_DOWNGRADE const 존재.

### 회귀

- unit: pre-existing technical fail 제외 → audit 직전 882 → 신규 4 test = **886 pass**, 0 new fail.

---

## Summary 표 (dimension × area)

| 차원 | allocator | method_picker | optimizers/HRP | overlay_apply |
|---|---|---|---|---|
| **L** | Stage 1+2 staleness 검사 (deferred 해결) | rule 0 strict mode | HRP cap-all shortfall logger | 5-level escalation 가시화 |
| **H** | 6 named const | SYSTEMIC_EXTREME_THRESHOLD, LOW_CONVICTION_HRP_DOWNGRADE | SINGLE_ASSET_CAP / HRP_WATER_FILL_MAX_ITERS 재사용 | OVERLAY_DROP_LEVELS dict, SINGLE_ASSET_CAP_OVERLAY |
| **D** | safety_diag + factor_contributions thread | inputs_trace 확장 (staleness, downgrade) | hrp_bucket_shortfalls + cov_excluded + cap_clipped | overlay attribution (final_level, dropped_constraints) |
| **O** | entry/exit log + Stage 2 intervention warning | per-rule logger.info/warning | shortfall warning + norm intervene info | per-level info/warning + named label |

---

## 미해결 / 후속 (이월)

| 항목 | 사유 | 이관 |
|---|---|---|
| Stage 2 deferred: scenario hysteresis | brainstorm 필요 (deadband 폭 결정) | followup PR |
| Stage 2 deferred: derive_conviction 9-factor weighted alignment | backtest 효과 검증 필요 | followup PR |
| Stage 1 deferred: classify_regime LLM prompt sentinel hint | LLM prompt 재설계 사이클 | 별도 작업 |
| Stage 1 deferred: 매직 임계값 (ADX 등) tuning | backtest 필요 | 대회 5/28 후 |
| pre-existing fail: test_technical_analyst_returns_report | 본 audit 무관 | 별도 PR (5분) |
| BlackLitterman views 자동 생성 | views 생성 logic 부재 | 별도 작업 |
| Single-cap 0.20 → 0.15 변경 | mandate 변경 | 별도 |
| TIPS baseline 0.30 tuning | backtest 필요 | 별도 |

---

## Commits (Stage 3: 5개)

1. 2895bcd — Task 0 staleness check + strict MIN_VARIANCE
2. 394cd65 — Task 1+2 allocator observability + Stage 2 diag thread + named const
3. b487e98 — Task 3 HRP cap-saturation visibility
4. 834436b — Task 4 overlay 5-level visibility
5. (이번) — Task 5 integration sanity + summary

---

## Stage 1+2+3 audit 누적 통계

- **commits**: 6 (Stage 1) + 6 (Stage 2) + 5 (Stage 3) = **17 commits**
- **deferred 해결**: Stage 1 #2 (method_picker staleness) ✓, Stage 2 #3 (동일) ✓
- **pre-existing fail**: 2 → 1 (Stage 2 audit 에서 1개 정리)
- **새 const 분리**: Stage 1 (~24) + Stage 2 (9) + Stage 3 (~14) = ~47개
- **새 logger 호출**: Stage 1 (~45) + Stage 2 (~10) + Stage 3 (~20) = ~75개
- **새 integration test**: 4 (Stage 2) + 4 (Stage 3 method_picker) = 8개
