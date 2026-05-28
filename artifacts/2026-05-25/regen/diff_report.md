# PR2b 2026-05-15 Regen Diff Report

`scripts/run_e2e_test.py --as-of 2026-05-15 --capital 1000000000` 실행 결과를
git HEAD 의 이전 artifacts/2026-05-15/* 와 비교.

**Pipeline runtime**: 203.4s full Stage 1-6 + LLM.
**Validation**: passed=True, hard=0, soft=0.

## Bucket target Δ (calibrated β vs hand-coded prior)

| Bucket | OLD (hand-coded β) | NEW (calibrated β) | Δ |
|---|---|---|---|
| kr_equity | 0.1607 | **0.2631** | **+0.1024** ⬆️ |
| global_equity | 0.0480 | 0.0028 | -0.0452 ⬇️ |
| fx_commodity | 0.0541 | 0.1200 | +0.0659 ⬆️ |
| bond | **0.3729** | 0.2503 | -0.1226 ⬇️ |
| cash_mmf | 0.3644 | 0.3639 | -0.0005 |
| bond_tips_share | 0.3572 | 0.3202 | -0.0370 |

**Key shifts** (둘 다 dominant_scenario=kr_boom + conviction=medium 동일):
- KR equity 대폭 증가 (16% → 26%, +63% relative)
- Bond 감소 (37% → 25%, -33% relative)
- Global equity 거의 제로화 (5% → 0.3%)
- FX commodity 증가 (5% → 12%)
- Cash 변화 없음 (36% 유지)

위험자산 합계: 26.3% → 38.6% (mandate cap 70% 안).

## Method choice (LLM-decided, not directly calibration-driven)

| | OLD | NEW |
|---|---|---|
| method | min_variance | hrp |

Method 변경은 LLM 의 method_picker 결정으로, calibrated β 의 직접 결과가
아닌 LLM 변동성일 가능성 — 단정 불가, follow-up 별도 검증 영역.

## Top weight Δ (large reshuffling)

| Ticker | OLD | NEW | Δ |
|---|---|---|---|
| A229200 | 0.000 | 0.102 | +0.102 (신규) |
| A411060 | 0.029 | 0.093 | +0.065 |
| A385540 | 0.055 | 0.000 | -0.055 |
| A395160 | 0.000 | 0.053 | +0.053 (신규) |
| A091160 | 0.000 | 0.051 | +0.051 (신규) |
| A102110 | 0.046 | 0.000 | -0.046 |

상위 ticker가 일부 교체됨 — bucket reweighting 의 자연스러운 결과.

## global_equity 0% 원인 분석

Live factor z (2026-05-15): F6_krw_regime=-3.00, F7_equity_vol_regime=+3.00,
F3_real_rate=+0.79.

### β × z contribution to global_equity (per-factor cap ±0.10)

| Factor | β NEW | β OLD | z | NEW contribution | OLD contribution |
|---|---|---|---|---|---|
| F6 × -3 | +0.098 | +0.040 | -3.00 | -0.10 (capped) | -0.10 (capped) |
| F7 × +3 | -0.095 | -0.060 | +3.00 | -0.10 (capped) | -0.10 (capped) |
| F3 × 0.79 | -0.073 | -0.030 | +0.79 | -0.058 | -0.024 |
| **Sum** | | | | **-0.258** | **-0.224** |

→ Hand-coded 도 거의 같은 결정 (-0.22 vs -0.26). **차이 0.034 미만**.
→ global_equity 가 0% 가 되는 주 원인은 **calibrated β 가 아니라
   F6/F7 cap 까지 도달한 extreme factor signal**.

이 환경에서는 어떤 β 든 global equity 를 강하게 reduce — calibration 책임
아님.

## Factor signals

- dominant_scenario: kr_boom (양쪽 동일)
- conviction: medium (양쪽 동일)
- top factors:
  - F6_krw_regime = -3.00 (extreme)
  - F7_equity_vol_regime = +3.00 (cap)
  - F3_real_rate = +0.79

## Caveats (Issue #18 에 반영)

본 regen 의 production 적용은 다음 caveat 와 함께:

1. **60-40 대비 not statistically significant** (paired-t p=0.717). Validation
   report Section 1 참조 — Sharpe 만 보면 1위 이지만 통계적으로 60-40 과
   구별 불가.
2. **β era drift** (|β_pre - β_post|_avg = 0.036, MODERATE). 미래 era 에서
   β 가 약간 다를 가능성. quarterly re-calibration cadence 권장.
3. **Robustness penalty sensitive**: shrinkage 선택 계수를 0.25 → 0.50 변경
   시 best shrinkage 2.0 → 0.1 dramatic 변화. 본 결정은 0.25 선택에 의존.
4. **Extreme factor signal effect**: 2026-05-15 의 F6=-3, F7=+3 같은 extreme
   상황에서는 bucket reposition 도 극단 (global_equity 0%) — 일반 상황 (z≈0)
   에서는 baseline 유지될 것.

## Conclusion

Calibrated β 가 production output 을 의미 있게 변화시킴:
- KR equity weight +10pp (16% → 26%)
- Bond weight -12pp (37% → 25%)
- Global equity 거의 제로 (extreme signal 영향)
- Validation passed (mandate compliance OK, hard=0 soft=0)

PR2b 의 historical 검증 (5-strategy 비교 + sensitivity sweep) 의 marginal
evidence 와 본 production output 의 substantive change 의 결합 — Accept
with caveat (grill-me #2 user 결정).
