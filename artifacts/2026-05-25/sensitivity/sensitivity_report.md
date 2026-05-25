# PR2b Sensitivity Report (2026-05-25)

## Section 1: Era Split (pre/post 2010-01-01)

- pre-2010: N=75, in-sample Sharpe=1.2101117000651322
- post-2010: N=58, in-sample Sharpe=1.2847962127476253
- |β_pre - β_post|_avg = **0.0364** (MODERATE DRIFT)
- |β_pre - β_post|_max = 0.1595

## Section 2: Robustness Penalty {0.10, 0.25, 0.50}

| Penalty coefficient | Best shrinkage |
|---|---|
| 0.10 | 2.0 |
| 0.25 (default) | 2.0 |
| 0.50 | 0.1 |

**Verdict**: SENSITIVE — best shrinkage 가 계수에 의존

## Section 3: Sample Quality Stratified

⚠️ sample_quality has too few unique values for 4 quartiles
   mean confidence = 0.7233
   unique values = 1
   → Quartile 분류 불가 (모든 sample 의 confidence 가 거의 동일 — baseline-fallback dominant).

