# Stage 5 + Stage 6 Audit — 2026-05-26

Plan: [docs/superpowers/plans/2026-05-26-stage5-6-audit.md](superpowers/plans/2026-05-26-stage5-6-audit.md)
Stage 1-4 audit 완료 후 마지막 stage 들. 통합 audit (LOC 적어서 한 plan).

---

## Stage 5+6 특성

- **Stage 5: LLM=0** (4 mandate hard check, deterministic).
- **Stage 6: deep_llm=1** (philosophy.md 작성).
- **이전 attribution chain 의 종착점**:
  - Stage 5 가 attribution 안 받음 → validation_passed=False 시 root cause trace 어려움.
  - Stage 6 의 portfolio.json full_trace 에 allocation/risk_judge attribution 부재.
- mandate_validator logger 0 — Stage 1-4 audit 의 마지막 가시화 누락.

---

## Task 0+1 — Stage 5: mandate_validator observability + named const

### 발견

- **logger 호출 0개** — validation 실패 시 root cause 추적 어려움.
- `mandate_validator_attribution` 부재 → Stage 6 narrative 가 어느 check 어느 ticker 로 fail 했는지 못 봄.
- 4 mandate check 의 magic (0.20/0.25/0.70/0.80/0.10/1e-6/1e-9) 가 함수 안 hardcoded — backtest tuning 시 grep 필요.

### 결정/수정

**Task 0 (observability)**:
- entry log (n_positions, attempts).
- per-check 결과 logger.info (hard/soft counts).
- 최종 verdict logger.info (passed + total violations).
- `mandate_validator_attribution` state output 신규:
  - `input_present` (5 키)
  - `skipped` (weight_vector_missing)
  - `check_counts: {integrity, universe, concentration, correlation, turnover} → {hard, soft}`
  - `rebalance_mode`, `turnover_floor`, `validation_passed`
  - `hard_violations: top-5 {rule, description, suggested_fix}`

**Task 1 (named const)**:
- mandate_validator: TURNOVER_FLOOR_INITIAL=0.80, TURNOVER_FLOOR_MONTHLY=0.10, WEIGHT_SUM_TOLERANCE=1e-3, INITIAL/MONTHLY_DAYS_REMAINING_PROXY.
- concentration_check: HARD_SINGLE_CAP=0.20, HARD_RISK_ASSET_CAP=0.70, FLOAT_TOLERANCE=1e-6.
- correlation_check: DEFAULT_CLUSTER_CAP=0.25, FLOAT_TOLERANCE=1e-6.
- turnover_check: TURNOVER_TOLERANCE=1e-9.

### 회귀: 12 pass.

---

## Task 2+3 — Stage 6: portfolio_manager attribution thread + observability

### 발견

- `_build_full_trace_portfolio` 가 research_decision / method_choice / risk_overlay / portfolio_numerics / validation_report 만 포함. **Stage 3/4/5 의 attribution dict (audit 산출물) 부재** → Stage 6 narrative 가 못 봄.
- magic `4000` chars (philosophy retry threshold) inline.
- warning reason 분류 부재 — operator 가 `PRICE_FETCH_FAILED` vs `PRICE_ZERO` 구분 불가.
- 3 output 산출 시점 logger 부재.

### 결정/수정

**Task 2 (attribution thread)**:
- `_build_full_trace_portfolio` 에 3 key 추가:
  - `allocation_attribution` (Stage 3)
  - `risk_judge_attribution` (Stage 4)
  - `mandate_validator_attribution` (Stage 5 신규)
- 각각 `_serialize_for_json` 처리.
- 결과: **portfolio.json 한 파일만 봐도 Stage 1-5 전체 trace**.

**Task 3 (named const + logger)**:
- PHILOSOPHY_MIN_CHARS=4000, PHILOSOPHY_MAX_RETRIES=1 named const.
- WARN_REASON_{PRICE_FETCH_FAILED, PRICE_ZERO} 분류.
- entry log (as_of, capital, n_positions).
- 각 output 산출 시점 logger.info:
  - portfolio.json (n_positions + attribution_keys 노출)
  - trade_plan.csv (zero_qty count)
  - philosophy.md (size + min threshold)
- 최종 complete log.

### 회귀: 13 pass.

---

## Task 4 — Stage 5+6 통합 sanity

### 신규 test 5개

- `test_mandate_validator_attribution_records_check_counts`: passing path 의 attribution 검증 (5 check 모두 카운트, rebalance_mode='initial', turnover_floor=0.80).
- `test_mandate_validator_attribution_records_hard_violations`: single cap 위반 시 hard_violations list 채움 + validation_passed=False.
- `test_mandate_named_const_present`: 4 check + validator 의 const 존재.
- `test_portfolio_json_includes_stage345_attribution`: portfolio.json 에 3 attribution 모두 포함 + 값 정합성.
- `test_portfolio_manager_named_const_present`: PHILOSOPHY/WARN_REASON const 존재.

### 회귀: 13 pass (test_mandate_validator + test_portfolio_manager_full_trace).

---

## Summary 표 (dimension × area)

| 차원 | mandate_validator | 4 mandate checks | portfolio_manager |
|---|---|---|---|
| **L** | check 결과 routing (변경 없음) | tolerance 정밀화 (1e-9) | warning reason 분류 |
| **H** | 4 named const | 4 check 의 ~9 named const | 4 named const |
| **D** | mandate_validator_attribution dict 신규 | (간접) | 3 attribution → portfolio.json full_trace |
| **O** | entry/per-check/exit logger.info/warning | (변경 없음) | entry/3 output/exit logger.info |

---

## 미해결 / 후속 (이월)

| 항목 | 사유 | 이관 |
|---|---|---|
| mandate threshold 값 변경 | 룰북 sync 필요 | 별도 |
| philosophy.md 6 section schema 변경 | 별도 작업 | followup PR |
| trade_plan.csv 컬럼 추가 | MTS 사양 변경 시 | 별도 |
| previous_portfolio 자동 import | 별도 | 별도 |
| pre-existing fail (technical_analyst) | audit 무관 | 별도 PR |

---

## Commits (Stage 5+6: 4개)

1. 98536d0 — Task 0+1 mandate_validator observability + 4 check named const
2. 9f8d0d6 — Task 2+3 portfolio_manager attribution thread + named const + logger
3. (이번) — Task 4 integration sanity + summary

---

## Stage 1+2+3+4+5+6 audit 누적 통계 (전체)

- **commits**: 6 (Stage 1) + 6 (Stage 2) + 5 (Stage 3) + 5 (Stage 4) + 3 (Stage 5+6) = **25 commits**
- **deferred 핵심 해결**:
  - Stage 1+2 method_picker staleness → Stage 3 Task 0 ✓
  - Stage 1+2+3+4 staleness propagation chain 전체 → Stage 4 Task 0 ✓
- **pre-existing fail**: 2 → 1 (Stage 2 audit 에서 1개 정리)
- **named const**: ~110 총
- **logger 호출**: ~110 총
- **신규 test**: 16 총
- **회귀**: 신규 test 추가 후 전체 통과, 0 new failures (pre-existing 1 제외)

---

## 6 Stage pipeline observability 완성

```
Stage 1 (4 analyst)
  └─ entry/exit log + sentinel inventory + missing-tier summary
     ↓ staleness propagation guard (_safe_get sentinel cut)
Stage 2 (factor model)
  └─ entry/exit log + top contributors + safety_diag in summary
     ↓ named scenario/conviction thresholds
Stage 3 (allocator + method_picker + optimizers + overlay)
  └─ entry/exit log + degraded_inputs strict MIN_VAR + cap_hits / cov_excluded /
     overlay escalation attribution
     ↓ Stage 2 safety_diag thread to Stage 3 attribution
Stage 4 (risk_judge + 3 lens + aggregator + portfolio_metrics)
  └─ entry/exit log + risk_signals degraded skip + 34 named lens consts +
     strength decision logger + missing-data logger
     ↓ risk_judge_attribution with lens_concerns + overlay outcome
Stage 5 (mandate_validator + 4 checks)
  └─ entry/per-check/exit logger + mandate_validator_attribution dict +
     named hard mandate consts
     ↓ 3 attribution dict thread
Stage 6 (portfolio_manager)
  └─ entry + 3 output logger + final attribution-rich portfolio.json
     + classified warnings + named retry thresholds
```

**portfolio.json 한 파일로 6 stage 전체 trace 가능. Stage 6 narrative 가 모든 진단 정보 접근.**
