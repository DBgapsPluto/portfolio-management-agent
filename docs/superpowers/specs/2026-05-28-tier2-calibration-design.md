# Tier 2 — β Calibration Framework (Hierarchical + Per-factor Window)

- **작성일:** 2026-05-28
- **대상:** PR2a friend (calibration framework 담당)
- **선행 의존:** [Tier 0](./2026-05-28-tier0-factor-model-reform-design.md), [Tier 1](./2026-05-28-tier1-bucket-taxonomy-design.md) — 12 factor + 8 bucket 구조 확정
- **후속 의존:** Tier 3 (LLM overlay)는 calibrated β output 위에 add
- **외부 참조:** [Gemini Deep Research §6](../../Factor_Model_Gemini_DeepResearch), PR2a calibration framework

---

## 0. TL;DR

12 factor × 8 bucket = 96 β entries (+ TIPS 12 entries = 108 total). Sample/parameter 비율 PR2a 시점 2.96 (5×9=45/133) → **새 환경 1.39 (96/133, 78% 악화)**. Plain ridge로 calibration 불가능 → **3-stage framework**:

1. **Hard zero cells** (~25개, hybrid 직관 + empirical 검증) → free ≈ 71
2. **Hierarchical 5-family prior** → effective param ≈ 40-50
3. **Strong shrinkage** (λ grid [0.5, 1.0, 2.0, 3.0, 5.0, 10.0]) + Effective df ≤ 44 (Gelman N/3) acceptance

**Per-factor window** (PR2a graceful degradation 확장): 각 factor block은 자기 component window에서 fit.

**F11 staggered**: F1-F10/F12 fit 후 F11 column (8 entries) sub-fit (2010+ window, λ_F11 ≥ 2·λ_global).

**Acceptance:** VIF ≤ 5 (spurious pair only), effective df ≤ 44, walk-forward OOS Sharpe > 1.171 (PR2a baseline), sign violation < 5%.

---

## 1. Sample/Parameter 부담

### 1.1. 정량화

| | PR2a (5×9) | Tier 1/2 (8×12) | 증가율 |
|---|---|---|---|
| β entries | 45 | 96 | +113% |
| TIPS entries | 9 | 12 | +33% |
| Total | 54 | 108 | +100% |
| Historical sample (quarterly) | 133 | 133 | 0 |
| **Sample/param** | **2.46** | **1.23** | **−50%** |

Rule of thumb (Harrell 2015 *Regression Modeling Strategies*): 회귀에서 10-20 sample/parameter 권장. 현재 1.23은 **임계 이하**.

### 1.2. 해결 전략

**3-stage compression:**
1. Hard zero cells (~25) → 96 → 71 free entries → 1.87
2. Hierarchical prior (family-level shared μ) → effective free ≈ 40-50 → 2.7-3.3
3. Strong shrinkage λ → effective df 조절 → df ≤ 44 (N/3) 보장

**추가 보호:**
- Per-factor window: 각 factor block은 자기 sample에서 fit (sample maximize)
- F11 staggered: short-window factor를 별도 sub-fit

---

## 2. Per-factor Window Framework

### 2.1. 원칙

각 factor는 자기 *component intersection*에서 fit. PR2a의 `_aggregate()` 기존 None-drop pattern과 호환.

| Factor | Start (Tier 0 §3 검증) | Sample (quarterly) |
|---|---|---|
| F1_growth (gdpnow drop) | 1971+ (INDPRO YoY) | ~212q |
| F2_inflation | 2003+ (TIPS/breakeven) | ~88q |
| F3_real_rate | 2003+ (TIPS) | ~88q |
| F4_term_premium | 1990+ (ACM) | ~140q |
| F5_credit_cycle | 2003+ (KR corp spread) | ~88q |
| F6_krw_regime | 2003+ (foreign_flow) | ~88q |
| F7_equity_vol | 2007+ (VXVCLS) | ~72q |
| F8_valuation | 2003+ (KOSPI fundamental) | ~88q |
| F9_market_dispersion | 1993+ (SPY realized vol) | ~124q |
| F10_systemic_liquidity (SOFR-TED stitched) | 1986+ | ~152q |
| F11_earnings_revision | 2010+ (yfinance) | ~60q (staggered) |
| F12_china_credit_impulse | 1990+ (BIS + 4 lag) | ~140q |

### 2.2. **Joint optimization with NaN-skip** (per-factor window의 자연 확장)

**결정 (이전 B5 ambiguity 해소):** Block fit vs joint hierarchical fit 둘 다 spec 안에 있어 충돌. → **Joint optimization** 채택. Per-factor window는 *factor f의 z-score가 NaN인 sample에서 그 factor의 contribution (β·z + family μ deviation)을 모두 0 처리*. PR2a의 `_aggregate()` graceful degradation의 자연 확장.

```python
def simulate_portfolio_returns_per_factor_aware(
    samples: list[HistoricalSample],
    beta: dict[tuple[str, str], float],
    baseline: dict[str, float] = INITIAL_BASELINE,
) -> np.ndarray:
    """Apply factor model with NaN-skip per factor.
    
    For each sample, for each factor:
      - If factor_z is NaN/None → factor contributes 0 (skip β·z term entirely)
      - Else → β · z contributes per usual
    
    Equivalent to PR2a's _aggregate() pattern: each factor's contribution is 
    independent, missing data just means "no information" for that factor.
    """
    returns = []
    for s in samples:
        bucket = dict(baseline)
        for f in FACTORS:
            z = s.factor_z.get(f)
            if z is None or np.isnan(z):
                continue  # skip this factor's contribution
            for b in BUCKETS:
                contrib = beta.get((f, b), 0.0) * z
                contrib = max(-CAP, min(CAP, contrib))  # ±0.10 cap
                bucket[b] += contrib
        projected = project_to_mandate_qp(bucket)
        ret = sum(projected[b] * s.bucket_returns_next.get(b, 0.0) for b in BUCKETS)
        returns.append(ret)
    return np.array(returns)
```

**Effective sample/parameter:** 각 (factor, bucket) entry는 *그 factor의 valid sample*에서만 update gradient 받음. 즉 F4 (1990+, 140q)는 140 sample 위에서 β_{F4,*} update. F11 (2010+, 60q)은 60 sample 위에서만 β_{F11,*} update (Phase B에서 sub-fit).

이 framework이 §4의 hierarchical group prior와 그대로 결합 (μ_{f, family}도 factor f의 valid sample에서만 gradient 받음).

### 2.3. Sample/param per block

각 factor block (8 entries) 별 sample/param:

| Factor | Sample | param | ratio |
|---|---|---|---|
| F1 | 212q | 8 | 26.5 ✓ |
| F2-F6 (avg 88q) | 88 | 8 | 11.0 ✓ |
| F7 | 72q | 8 | 9.0 ⚠️ marginal |
| F8 | 88q | 8 | 11.0 ✓ |
| F9 | 124q | 8 | 15.5 ✓ |
| F10 (stitched) | 152q | 8 | 19.0 ✓ |
| F11 (staggered) | 60q | 8 | 7.5 ⚠️ (sub-fit with strong shrinkage) |
| F12 | 140q | 8 | 17.5 ✓ |

**대부분 acceptable 범위.** F7/F11만 marginal — hierarchical prior + 강한 shrinkage로 보호.

---

## 3. Hard Zero Cells (~25 cells)

### 3.1. 도출 방법론

**Hybrid 직관 + empirical 검증** (사용자 결정):

**Step 1 — 직관적 zero** (portfolio manager judgment + economic theory):

| Factor | Bucket | Justification | Reference |
|---|---|---|---|
| F1_growth | precious_metals | Growth shocks ≠ gold price (gold은 real rate / systemic driven) | Erb-Harvey 2006 |
| F2_inflation | global_equity | Inflation은 equity의 *2차* 효과 (real EPS via input cost), F8 valuation으로 capture | Fama 1981 |
| F3_real_rate | kr_equity | Real rate은 *US* concept (TIPS), KR equity는 KR rate (F4)로 | Pflueger-Viceira 2011 |
| F3_real_rate | cyclical_commodity_fx | Real rate은 *commodity carry*에 약함 (commodity는 inflation/growth driven) | Erb-Harvey 2006 |
| F4_term_premium | precious_metals | Term premium은 bond duration 신호, gold와 무관 | ACM 2013 |
| F4_term_premium | cyclical_commodity_fx | 동일 | |
| F4_term_premium | credit | Credit은 F5에서 처리 | |
| F5_credit_cycle | precious_metals | Tier 0 sign restriction 제거 (dash-for-cash 양방향) → 0 prior | Brunnermeier-Pedersen 2009 |
| F5_credit_cycle | cyclical_commodity_fx | Credit cycle 직접 영향 약함 | |
| F5_credit_cycle | global_duration | Flight-to-quality가 있지만 F10 systemic이 capture | |
| F6_krw_regime | credit | KRW regime은 KR-specific, US credit과 분리 | Lustig 2011 |
| F6_krw_regime | global_duration | KRW은 US duration에 0 영향 | Rey 2013 |
| F7_equity_vol | cyclical_commodity_fx | Tier 0 sign 약화, F10이 systemic capture | |
| F7_equity_vol | precious_metals | Tier 0 sign 제거 → 0 prior | |
| F7_equity_vol | global_duration | Tier 0 sign 제거 → 0 prior | |
| F8_valuation | precious_metals | Valuation은 equity 개념, gold는 reservoir | Asness 2003 |
| F8_valuation | cyclical_commodity_fx | 동일 | |
| F8_valuation | kr_bond | Cross-asset valuation effect 약함 | |
| F8_valuation | credit | 동일 | |
| F8_valuation | global_duration | 동일 | |
| F8_valuation | cash_mmf | 동일 | |
| F9_market_dispersion | precious_metals | Dispersion은 equity 안 narrow rally 신호 | Solnik-Roulet 2000 |
| F9_market_dispersion | cyclical_commodity_fx | 동일 | |
| F10_systemic_liquidity | precious_metals | Systemic stress 시 gold는 양방향 (margin call vs safe haven) → 0 prior | Brunnermeier-Pedersen 2009 |
| F11_earnings_revision | precious_metals | Earnings revision ≠ commodity price | |
| F11_earnings_revision | cyclical_commodity_fx | 동일 | |
| F12_china_credit_impulse | global_duration | China credit이 US duration에 미치는 영향 약함 | |
| F12_china_credit_impulse | precious_metals | Direct link 약함 | |

**Step 1 결과**: 약 **27 cell**.

**Step 2 — Empirical 검증:**

```python
def validate_hard_zeros(
    samples: list[HistoricalSample],
    candidate_zeros: list[tuple[str, str]],
    threshold: float = 0.15,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """직관적 zero cell을 empirical Pearson ρ로 검증.
    
    ρ = corr(factor_z[f], bucket_return[b]) on training window.
    |ρ| < threshold (0.15) → zero 유지
    |ρ| ≥ threshold → reconsider (sign restriction violation 발생 가능성)
    
    Returns: (confirmed_zeros, contested_zeros)
    """
    confirmed = []
    contested = []
    for (f, b) in candidate_zeros:
        z_series = np.array([s.factor_z.get(f, np.nan) for s in samples])
        r_series = np.array([s.bucket_returns_next.get(b, np.nan) for s in samples])
        mask = ~(np.isnan(z_series) | np.isnan(r_series))
        if mask.sum() < 40:
            confirmed.append((f, b))  # insufficient data — keep zero conservative
            continue
        rho = np.corrcoef(z_series[mask], r_series[mask])[0, 1]
        if abs(rho) < threshold:
            confirmed.append((f, b))
        else:
            contested.append((f, b))
    return confirmed, contested
```

**Step 3 — 최종 결정**: contested zero는 portfolio manager review. 일반적으로:
- |ρ| 0.15-0.25: zero 유지 (noise 가능성)
- |ρ| > 0.25: zero 해제 (genuine signal possible)

**구현 위치:** `tradingagents/skills/research/factor_calibration.py` 안 `HARD_ZERO_CELLS` set으로 정의:

```python
HARD_ZERO_CELLS: Final[frozenset[tuple[str, str]]] = frozenset({
    # Step 1 직관적 zero 27개 (위 표) — Step 2 empirical 검증 통과한 것만 유지
    ("F1_growth", "precious_metals"),
    ("F2_inflation", "global_equity"),
    ("F3_real_rate", "kr_equity"),
    ("F3_real_rate", "cyclical_commodity_fx"),
    ("F4_term_premium", "precious_metals"),
    ("F4_term_premium", "cyclical_commodity_fx"),
    ("F4_term_premium", "credit"),
    ("F5_credit_cycle", "precious_metals"),
    ("F5_credit_cycle", "cyclical_commodity_fx"),
    ("F5_credit_cycle", "global_duration"),
    ("F6_krw_regime", "credit"),
    ("F6_krw_regime", "global_duration"),
    ("F7_equity_vol_regime", "cyclical_commodity_fx"),
    ("F7_equity_vol_regime", "precious_metals"),
    ("F7_equity_vol_regime", "global_duration"),
    ("F8_valuation", "precious_metals"),
    ("F8_valuation", "cyclical_commodity_fx"),
    ("F8_valuation", "kr_bond"),
    ("F8_valuation", "credit"),
    ("F8_valuation", "global_duration"),
    ("F8_valuation", "cash_mmf"),
    ("F9_market_dispersion", "precious_metals"),
    ("F9_market_dispersion", "cyclical_commodity_fx"),
    ("F10_systemic_liquidity", "precious_metals"),
    ("F11_earnings_revision", "precious_metals"),
    ("F11_earnings_revision", "cyclical_commodity_fx"),
    ("F12_china_credit_impulse", "global_duration"),
    ("F12_china_credit_impulse", "precious_metals"),
})
# 총 28개 hard zero cell (empirical 검증 후 5-10개 reconsider 가능)
```

**Free entries:** 96 − 28 = **68 entries** (sample/param 1.96).

---

## 4. Hierarchical 5-Family Group Prior

### 4.1. Bucket family 분류

Gemini deep research §6.1 권고 + correlation 기반:

```python
BUCKET_FAMILIES: Final[dict[str, list[str]]] = {
    "equity":      ["kr_equity", "global_equity"],
    "commodity":   ["precious_metals", "cyclical_commodity_fx"],
    "duration":    ["kr_bond", "global_duration"],
    "credit":      ["credit"],   # single-member (risk-on like, distinct)
    "cash":        ["cash_mmf"], # single-member (haven)
}
```

**근거:**
- Equity family: same "growth premium" 자산, β response 패턴 유사 (Cooper-Mitrache-Priestley 2017)
- Commodity family: real-asset hedge family. precious/cyclical은 driver 다르지만 *equity 대비*는 같은 grouping
- Duration family: same "term premium" play, KR vs global은 currency match만 차이
- Credit: single-member because risk-on like (Bekaert-Hodrick-Zhang 2009) — equity와 duration 사이
- Cash: single-member haven

### 4.2. Hierarchical prior 공식

각 factor f에 대해, family-level mean μ_{f, family}와 within-family deviation:

$$\beta_{f, b} = \mu_{f, \text{family}(b)} + \epsilon_{f,b}, \quad \epsilon \sim N(0, \sigma_{\text{within}}^2)$$

**Calibration objective** (PR2a hybrid_calibration 확장):

```python
def hierarchical_calibration_objective(
    beta: dict[tuple[str, str], float],
    mu: dict[tuple[str, str], float],   # μ_{f, family}
    train_samples: list[HistoricalSample],
    prior: dict[tuple[str, str], float],
    lambda_global: float,
    lambda_family: float,
) -> float:
    """L(β, μ) = -Sharpe(β; train) 
              + λ_global · ||β - prior||²
              + λ_family · Σ_f Σ_{b ∈ family} ||β_{f,b} - μ_{f, family}||²
              + sign_penalty(β)
              + hard_zero_penalty(β)
    """
    sharpe = compute_sharpe(simulate_portfolio_returns(train_samples, beta))
    
    prior_pen = lambda_global * sum(
        (beta[k] - prior[k])**2 for k in beta
    )
    
    family_pen = 0.0
    for (f, b), val in beta.items():
        fam = bucket_family(b)
        family_pen += lambda_family * (val - mu[(f, fam)])**2
    
    sign_pen = compute_sign_penalty(beta)
    
    hard_zero_pen = sum(
        beta[k]**2 * 1000 for k in beta if k in HARD_ZERO_CELLS
    )
    
    return -sharpe + prior_pen + family_pen + sign_pen + hard_zero_pen
```

### 4.3. 구현 (PR2a framework 호환)

```python
def hybrid_calibration_hierarchical(
    train: list[HistoricalSample],
    prior_beta: dict[tuple[str, str], float] | None = None,
    lambda_global: float = 2.0,
    lambda_family: float = 0.5,
    max_iter: int = 100,
) -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], float], float]:
    """Returns (calibrated_beta, calibrated_mu, in_sample_sharpe).
    
    Optimization: scipy.optimize.minimize L-BFGS-B
    Variables: 
      - β: 96 entries (28 hard-zero clamped, 68 free)
      - μ: 12 factor × 5 family = 60 entries
    Total decision dim: 68 + 60 = 128
    """
    prior = prior_beta or INITIAL_BETA
    
    # Decision vector: free β entries + μ entries
    free_beta_keys = sorted(set(prior.keys()) - HARD_ZERO_CELLS)
    mu_keys = sorted([(f, fam) for f in FACTORS for fam in BUCKET_FAMILIES])
    
    x0 = np.concatenate([
        np.array([prior[k] for k in free_beta_keys]),
        np.array([np.mean([prior[(f, b)] for b in BUCKET_FAMILIES[fam]]) 
                  for (f, fam) in mu_keys]),
    ])
    
    bounds = (
        [(-0.20, 0.20)] * len(free_beta_keys) +
        [(-0.15, 0.15)] * len(mu_keys)
    )
    
    def objective(x):
        beta_free = {k: x[i] for i, k in enumerate(free_beta_keys)}
        mu = {k: x[len(free_beta_keys) + i] for i, k in enumerate(mu_keys)}
        beta = {**beta_free, **{k: 0.0 for k in HARD_ZERO_CELLS}}
        return hierarchical_calibration_objective(
            beta, mu, train, prior, lambda_global, lambda_family
        )
    
    result = minimize(objective, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': max_iter})
    
    beta_free = {k: result.x[i] for i, k in enumerate(free_beta_keys)}
    mu = {k: result.x[len(free_beta_keys) + i] for i, k in enumerate(mu_keys)}
    beta = {**beta_free, **{k: 0.0 for k in HARD_ZERO_CELLS}}
    
    final_sharpe = compute_sharpe(simulate_portfolio_returns(train, beta))
    return beta, mu, final_sharpe
```

**Framework 변경 크기 (PR2a friend 추정):**
- `hybrid_calibration` 함수: optimization variable 확장 (β + μ)
- objective function: family penalty 항 추가
- Hard zero handling: 28개 cell clamp
- Helper functions: `bucket_family(b)` lookup

PR2a's `factor_calibration.py:118` 함수의 *medium-size extension*. 단일 L-BFGS-B 호출은 유지.

---

## 5. Shrinkage Grid + Effective df

### 5.1. λ grid 확장

```python
SHRINKAGE_GRID: Final[dict[str, list[float]]] = {
    "lambda_global": [0.5, 1.0, 2.0, 3.0, 5.0, 10.0],
    "lambda_family": [0.1, 0.3, 1.0, 2.0],
}
```

**근거 (Gemini deep research §6.2):**
- PR2a 시점 [0.1, 0.3, 0.5, 0.7, 1.0, 2.0]에서 best = 1.0/2.0
- 96 parameter 환경에서 동일 effective df 유지하려면 λ 상향 필수

### 5.2. Effective df 계산

$$df(\lambda) = \text{tr}(H) = \sum_{j=1}^{p} \frac{d_j^2}{d_j^2 + \lambda}$$

여기서 $H = X(X^\top X + \lambda I)^{-1} X^\top$, $d_j$는 design matrix X의 singular value.

```python
def compute_effective_df(
    design_matrix: np.ndarray,  # (n_samples, n_features)
    lambda_global: float,
) -> float:
    """Effective degrees of freedom for ridge regression.
    
    Reference: Hastie-Tibshirani-Friedman ESL Section 3.4.1.
    
    df → p as λ → 0 (overfit)
    df → 0 as λ → ∞ (no fit)
    """
    _, sing_vals, _ = np.linalg.svd(design_matrix, full_matrices=False)
    return float(np.sum(sing_vals**2 / (sing_vals**2 + lambda_global)))
```

### 5.3. Acceptance criterion

**df ≤ N / 3** (Gelman 2007 표준):
- N = 133 quarter → df ≤ **44**

Cross-validation selection:
1. λ_global, λ_family grid에 대해 walk-forward OOS Sharpe 계산
2. df ≤ 44 constraint 통과한 (λ_global, λ_family) 조합만 후보
3. Top 3 후보의 median OOS Sharpe → 최종 λ 선택

---

## 6. F11 Staggered Protocol

### 6.1. 두 단계 fit

**Phase A (main fit):**
- F1-F10, F12 (11 factor) × 8 bucket = 88 entries
- Hard zero ~24 cells (F11 row의 zero cells 제외)
- Free ≈ 64 entries
- Sample window: 각 factor의 component intersection
- F11 column 8 entries는 **prior로 고정** (INITIAL_BETA의 F11 row 사용)

**Phase B (F11 sub-fit):**
- Phase A β 고정한 상태에서 F11 column 8 entries만 fit
- Sample window: 2010+ (60 quarters)
- Strong shrinkage: `λ_F11 = max(2 × λ_global, 5.0)`
- Hard zero: F11 row의 zero cells (precious, cyclical) 적용
- Free: 6 entries (8 - 2 zero)

### 6.2. 구현

```python
def staggered_calibration(
    train_pre_2010: list[HistoricalSample],  # 1991-2009
    train_2010_plus: list[HistoricalSample], # 2010-2024
    prior: dict[tuple[str, str], float] = INITIAL_BETA,
    lambda_global: float = 2.0,
    lambda_family: float = 0.5,
) -> tuple[dict[tuple[str, str], float], dict[tuple[str, str], float]]:
    """Two-stage staggered calibration for F11.
    
    Phase A: fit F1-F10, F12 (88 entries) on full 1991+ window
    Phase B: fit F11 column (6 free entries) on 2010+ window with strong shrinkage
    """
    # Phase A: F11 column 제외하고 fit
    main_factors = [f for f in FACTORS if f != "F11_earnings_revision"]
    train_main = _filter_samples_by_factors(train_pre_2010 + train_2010_plus, main_factors)
    beta_main, mu_main, _ = hybrid_calibration_hierarchical(
        train_main,
        prior_beta={k: v for k, v in prior.items() if k[0] != "F11_earnings_revision"},
        lambda_global=lambda_global,
        lambda_family=lambda_family,
    )
    
    # Phase B: F11 sub-fit (β_main 고정 + μ_F11 fit)
    f11_keys = [(f, b) for f in ["F11_earnings_revision"] for b in BUCKETS]
    f11_free_keys = [k for k in f11_keys if k not in HARD_ZERO_CELLS]
    lambda_f11 = max(2.0 * lambda_global, 5.0)
    
    beta_f11 = fit_f11_block(
        train_2010_plus,
        beta_main_fixed=beta_main,
        prior_f11={k: prior[k] for k in f11_free_keys},
        lambda_f11=lambda_f11,
    )
    
    # Merge
    calibrated_beta = {**beta_main, **beta_f11, 
                       **{k: 0.0 for k in f11_keys if k in HARD_ZERO_CELLS}}
    return calibrated_beta, mu_main
```

### 6.3. Validation

- F11 OOS Sharpe (2010+ holdout) > 0 (baseline: F11 미사용 시 Sharpe)
- F11 column β: |β_F11| < 0.10 (강한 shrinkage 확인)
- Sign consistency: F11×kr_eq, F11×gl_eq > 0 (Tier 1 SIGN_RESTRICTION 부합)

---

## 7. 8-bucket Historical Return Time Series 구축

### 7.1. 현재 상태

`backtest/historical/bucket_returns.parquet`:
- 5 bucket: kr_equity, global_equity, fx_commodity, bond, cash_mmf
- 1991-Q2 ~ 2024-Q4 quarterly
- 134 rows × 5 columns

### 7.2. 새 8 bucket return proxy — **실측 검증 후 확정**

각 source 가용성 yfinance/pykrx/FRED 실측 검증:

| Bucket | Proxy (검증된 source) | History (실측) |
|---|---|---|
| `kr_equity` | KOSPI 200 TR (KRW) via pykrx `get_index_ohlcv_by_date` (1028) + dividend yield re-investment | 1991+ |
| `global_equity` | **VEU (FTSE All-World ex-US) 2007+, ^GSPC (S&P 500) 1991-2007** (USD→KRW via DEXKOUS) | 1991+ (stitched) |
| `precious_metals` | **GLD (2004+) + SLV (2006+) 50:50** KRW basis. Pre-2004: FRED `GOLDAMGBD228NLBM` (London gold AM) | 1968+ via FRED gold spot |
| `cyclical_commodity_fx` | **DJP (2006+, iPath Bloomberg Commodity) + DXY proxy `DTWEXBGS` weighted 70:30**. Pre-2006: WTI (`CL=F` 2000+) + DXY | 1991+ (mixed proxy) |
| `kr_bond` | **KOSEF 148070.KS (2011+) + ECOS `kr_treasury_10y` duration-based TR (1991-2011)** | 1991+ (stitched) |
| `credit` | **HYG (2007+) + BAA10Y returns proxy (Moody's BAA - 10Y, FRED 1986+, pre-2007)** | 1986+ |
| `global_duration` | **TLT (2002+) + DGS10 yield → duration-based TR (pre-2002)** | 1962+ |
| `cash_mmf` | ECOS `kr_treasury_3y` 단기금리 → 91-day TR proxy. 또는 FRED `DTB3` × DEXKOUS basis | 1991+ |

**MSCI ACWI ex-KR 결정 (이전 A9 ambiguity 해소):**
- "MSCI ACWI ex-KR" 직접 ETF는 *존재하지 않음* (paid MSCI subscription 외).
- 대체 stitching: **VEU (FTSE All-World ex-US) 2007+, ^GSPC 1991-2007**.
- VEU에 KR 1-2% 포함되어 있으나 minor contamination 수용.

**KTB 10Y TR 결정 (A10 해소):**
- pykrx KRX login 필요 (KRX_ID/KRX_PW 환경변수 부재).
- **ECOS 기반 duration approximation 사용**: `kr_treasury_10y` yield 시계열에서:
  - `r_t ≈ -D × (y_t - y_{t-1}) + y_{t-1}/360` (D = 8.5y modified duration)
  - 이는 *zero-coupon equivalent* approximation, *coupon roll-down* 무시. acceptable for backtest.
- 2011+: KOSEF 148070.KS yfinance daily price를 *primary* (TR 정확), ECOS reconstruction은 *fallback*.

### 7.3. 구축 작업

`backtest/historical/bucket_returns.py` (또는 새 module `bucket_returns_8b.py`):

```python
def build_bucket_returns_8b(
    start: date = date(1991, 1, 1),
    end: date = date(2024, 12, 31),
) -> pd.DataFrame:
    """Quarterly returns for 8-bucket schema.
    
    Returns: DataFrame indexed by quarter_end, columns = 8 BUCKETS.
    KRW basis throughout (USD → KRW conversion via DEXKOUS).
    """
    kr_eq = _build_kospi_tr(start, end)             # pykrx 1028 + dividend
    gl_eq = _build_global_equity_stitched(start, end)  # VEU 2007+ / ^GSPC pre-2007
    precious = _build_precious_50_50_krw(start, end)   # GLD+SLV / FRED gold spot pre-2004
    cyclical = _build_cyclical_basket(start, end)      # DJP+DXY weighted / WTI+DXY pre-2006
    kr_bond = _build_kr_bond_tr(start, end)            # KOSEF 2011+ / ECOS duration pre-2011
    credit = _build_credit_proxy(start, end)           # HYG 2007+ / BAA10Y pre-2007
    gl_dur = _build_global_duration_tr(start, end)     # TLT 2002+ / DGS10 duration pre-2002
    cash = _build_kr_cash_tr(start, end)               # ECOS kr_treasury_3y short
    
    df = pd.concat([kr_eq, gl_eq, precious, cyclical, 
                    kr_bond, credit, gl_dur, cash], axis=1)
    df.columns = list(BUCKETS)
    return df.resample("Q").apply(lambda x: (1 + x).prod() - 1)
```

**검증 acceptance:**
- 8 bucket correlation matrix sanity check (예: kr_equity vs global_equity ρ > 0.3, kr_bond vs cash ρ > 0.5)
- 5-bucket → 8-bucket aggregation 비교: 옛 fx_commodity ≈ 0.4 × precious + 0.6 × cyclical (구성 weight 검증)
- Look-ahead bias: as_of_date 검증 (FRED point-in-time pattern 적용)

### 7.3. 구축 작업

`backtest/historical/bucket_returns.py` (또는 별도 `bucket_returns_8b.py`):

```python
def build_bucket_returns_8b(
    start: date = date(1991, 1, 1),
    end: date = date(2024, 12, 31),
) -> pd.DataFrame:
    """Quarterly returns for 8-bucket schema.
    
    Returns: DataFrame indexed by quarter_end, columns = 8 BUCKETS.
    KRW basis throughout (USD → KRW conversion via DEXKOUS).
    """
    kr_eq = _build_kospi_tr(start, end)
    gl_eq = _build_global_equity_krw(start, end)
    precious = _build_precious_krw(start, end)  # GLD+SLV 50:50 KRW
    cyclical = _build_cyclical_commodity_fx(start, end)
    kr_bond = _build_ktb_tr(start, end)
    credit = _build_credit_proxy(start, end)
    gl_dur = _build_global_duration_krw(start, end)
    cash = _build_kr_tbill_tr(start, end)
    
    df = pd.concat([kr_eq, gl_eq, precious, cyclical, 
                    kr_bond, credit, gl_dur, cash], axis=1)
    df.columns = list(BUCKETS)
    return df.resample("Q").apply(lambda x: (1 + x).prod() - 1)
```

**Fallback 사례:**
- precious_metals 1991-2003 (pre-GLD): gold spot (FRED `GOLDAMGBD228NLBM`) + silver spot
- credit 1991-2007 (pre-HYG): BAA10Y returns proxy (Moody's BAA - 10Y)
- global_duration 1991-2002 (pre-TLT): DGS10 yield → price return (duration approximation)

### 7.4. 검증

- 8 bucket sum (correlation matrix 등) sanity check
- 5-bucket과 8-bucket의 *5-bucket aggregation* 비교 (예: precious + cyclical → 옛 fx_commodity)
- Look-ahead bias: as_of_date 검증 (FRED point-in-time 패턴)

---

## 8. Acceptance Criteria

### 8.1. Calibration quality

- [ ] **VIF ≤ 5** for all factor pairs after Tier 0 fix (NFCI/curve 제거 후)
  - Exception: F1-F3 economic correlation 등 *natural* correlation은 별도 표기
- [ ] **Effective df = tr(H) ≤ 44** (Gelman N/3, N=133)
- [ ] **Walk-forward OOS Sharpe > 1.171** (PR2a baseline)
  - Walk-forward: initial train 80q, test 8q, expanding
  - Test windows: 2010-Q1, 2012-Q1, ..., 2022-Q1 (6 folds minimum)
- [ ] **Sign restriction violation rate < 5%** (PR2a 표준)
- [ ] **Hard zero cells β = 0** (clamped, residual < 1e-9)

### 8.2. F11 staggered

- [ ] F11 column fit가 2010+ window에서만 수행
- [ ] F11 column |β| < 0.10 (강한 shrinkage 효과 확인)
- [ ] F11 sign consistency: F11×kr_eq, F11×gl_eq > 0

### 8.3. Framework integration

- [ ] PR2a `hybrid_calibration` extension이 backward-compatible (5-bucket samples로 호출 시 작동)
- [ ] `coefficient_table.json` 또는 INITIAL_BETA 교체 → runtime 적용 검증
- [ ] PR2b validation framework (`backtest/validate_factor_model.py`)가 8-bucket + 12-factor 호환

### 8.4. Robustness

- [ ] λ_global = 5.0 환경에서도 OOS Sharpe positive
- [ ] F11 제외 vs 포함의 OOS Sharpe 비교 (positive contribution 확인)
- [ ] Shrinkage grid 안 best λ 결정 reproducible

---

## 9. 영향받는 파일

| File | 변경 |
|---|---|
| `tradingagents/skills/research/factor_calibration.py` | `hybrid_calibration` → `hybrid_calibration_hierarchical`, `staggered_calibration`, `HARD_ZERO_CELLS` set, `BUCKET_FAMILIES` dict, `compute_effective_df`, validation helpers |
| `tradingagents/skills/research/factor_reliability_empirical.py` | (Tier 0 dependency, 신규) — walk-forward predictive power |
| `scripts/calibrate_factor_model.py` | 8-bucket + 12-factor 호환, hierarchical option, staggered option, shrinkage grid 확장 |
| `scripts/validate_factor_model.py` (PR2b) | 8-bucket + 12-factor sanity tests, VIF check, df check |
| `scripts/sensitivity_sweep.py` (PR2b) | λ_global × λ_family grid, F11 contribution sweep |
| `backtest/historical/bucket_returns.py` | 5-bucket → 8-bucket schema (또는 별도 모듈) |
| `backtest/historical/stage1_builder.py` | Tier 0 신규 component 채움, expanding window 호환 |
| `tradingagents/skills/research/factor_to_bucket.py` | `INITIAL_BETA` 12×8 prior (Tier 1 dependency), runtime이 calibrated β 사용 (PR2a wiring 유지) |
| `tests/unit/skills/research/test_factor_calibration.py` | hierarchical fit, hard zero clamping, staggered F11, VIF/df tests |
| `tests/integration/test_calibration_pipeline.py` | end-to-end calibration → β output → factor model |

---

## 9.5. TIPS β calibration (separate scalar regression)

**결정 (C4 ambiguity 해소):** `INITIAL_TIPS_BETA`는 12 entries (factor × scalar share output). Main β와 별도 simpler regression.

```python
def hybrid_calibration_tips(
    train: list[HistoricalSample],
    prior_tips_beta: dict[str, float] | None = None,
    lambda_global: float = 2.0,
    max_iter: int = 50,
) -> tuple[dict[str, float], float]:
    """TIPS share (within bond bucket) scalar regression.
    
    Target: bucket['bond'] 안의 TIPS share ∈ [0, 1] from
        tips_share(t) = INITIAL_TIPS_BASELINE + Σ_f TIPS_BETA[f] × factor_z[f]
    
    Hierarchical/family X (single output). Hard zero cells:
      - F11_earnings_revision × TIPS = 0 (earnings revision은 TIPS preference에 link 약함)
      - F12_china_credit_impulse × TIPS = 0 (china credit이 TIPS에 link 약함)
    
    Sample/param ratio: 133 / 10 = 13.3 (acceptable).
    """
    HARD_ZERO_TIPS = {"F11_earnings_revision", "F12_china_credit_impulse"}
    free_keys = sorted(set(prior_tips_beta.keys()) - HARD_ZERO_TIPS)
    
    def objective(flat):
        tips_beta = {**{k: flat[i] for i, k in enumerate(free_keys)},
                     **{k: 0.0 for k in HARD_ZERO_TIPS}}
        predicted_shares = []
        realized_shares = []
        for s in train:
            share = INITIAL_TIPS_BASELINE + sum(
                tips_beta.get(f, 0.0) * s.factor_z.get(f, 0.0)
                for f in tips_beta if s.factor_z.get(f) is not None
            )
            share = max(0.0, min(1.0, share))
            predicted_shares.append(share)
            realized_shares.append(s.tips_share_realized)  # bond bucket 안 TIPS realized share
        mse = np.mean((np.array(predicted_shares) - np.array(realized_shares))**2)
        prior_pen = lambda_global * sum((flat[i] - prior_tips_beta[k])**2 
                                         for i, k in enumerate(free_keys))
        return mse + prior_pen
    
    result = minimize(objective, x0=..., method='L-BFGS-B', bounds=[(-0.3, 0.3)] * len(free_keys))
    final_beta = {**{k: result.x[i] for i, k in enumerate(free_keys)},
                  **{k: 0.0 for k in HARD_ZERO_TIPS}}
    return final_beta, result.fun
```

**Notes:**
- `INITIAL_TIPS_BETA` (T1 spec §4)의 12 entries → 10 entries fit (2개 hard zero)
- Sample/param 13.3은 main β의 hierarchical 후 effective 40-50 대비 *훨씬 안정*
- Acceptance: walk-forward MSE < hand-coded prior MSE

## 10. Out of Scope

- **β prior 12×8 numeric matrix**: Tier 1 spec에서 정의 (본 spec은 그 prior를 *calibration의 starting point*로 사용)
- **Bucket-level mandate constraint** (RISK_BUCKETS, MANDATE_RISK_CAP): Tier 1 spec
- **New Stage 1 data fetchers**: Tier 0 spec
- **LLM bucket view overlay**: Tier 3 spec
- **Component weight PCA**: Tier 0 spec out-of-scope (hand-coded 유지)
- **F11 paid IBES**: v2 deferral

---

## 11. 참고문헌

- Gelman et al 2013 *Bayesian Data Analysis* §15 (Hierarchical prior)
- Gemini Deep Research 2026-05-28 §6 (Calibration blueprint)
- Hastie-Tibshirani-Friedman 2009 *Elements of Statistical Learning* §3.4 (Ridge effective df)
- Harrell 2015 *Regression Modeling Strategies* (Sample/param rule of thumb)
- Newey-West 1987 *Econometrica* (HAC standard errors for overlapping observations)
- Pesaran-Timmermann 1995 *JF* (Expanding window normalization — Tier 0 dependency)
- Pinheiro-Bates 2000 *Mixed-Effects Models in S and S-PLUS* (Hierarchical lme)
- Stock-Watson 1996 *J.Business&Economic Statistics* (Staggered availability)
- Yuan-Lin 2006 *JRSSB* "Model Selection and Estimation in Regression with Grouped Variables" (Group Lasso — alternative not chosen)

---

**Next:** Tier 3 spec (LLM overlay framework).
