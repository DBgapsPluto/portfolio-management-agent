# Factor Model Calibration — Validation Report

**Date**: 2026-05-23
**Sample window**: full (n=135 quarters)
**Selected shrinkage**: 1.00
**Data source**: synthetic (infrastructure validation only)

## Sharpe ratios (annualized)

| Strategy | Sharpe | Δ vs initial |
|---|---|---|
| INITIAL_BETA (hand-coded) | 1.702 | baseline |
| Calibrated β | 2.364 | +0.662 |
| 60/40 KR-tilted | 1.071 | +1.293 vs final |

## Acceptance criteria (plan §0 D5)

- [x] OOS Sharpe > INITIAL +0.05: Δ +0.662 (need > +0.05)
- [x] OOS Sharpe ≥ 60/40: Δ +1.293 (need ≥ 0)

**Overall**: PASS

## Shrinkage grid

| shrinkage | median_oos_sharpe | n_folds |
|---|---|---|
| 0.10 | 2.230 | 6 |
| 0.30 | 2.235 | 6 |
| 0.50 | 2.367 | 6 |
| 0.70 | 2.347 | 6 |
| 1.00 | 2.399 | 6 |


## Notes

- 본 calibration 은 *synthetic data fallback* 으로 실행됨 (실측 FRED + yfinance + pykrx fetch
  가 가능해질 때 production calibration 필요).
- 결정된 β 가 INITIAL_BETA 와 *유사* 면 hand-coded prior 의 합리성 부분 검증됨.
- Δ vs 60/40 가 positive 가 *true OOS superiority* 의 *necessary not sufficient* 조건.
- C7 단계 에서 실 운영 fixture 로 sanity 검증.

## Next steps

- INITIAL_BETA 를 calibrated β 로 교체 권장 (단, synthetic 결과 이므로 real fetch 후 재실행 필수)
- Real historical data fetch (Stage 1 backlog Issue #18)
- 6m 주기 재calibration
