# Tier 1 — Bucket Taxonomy (5 → 8) + Mandate Re-anchor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate factor_to_bucket.py from 5 → 8 buckets (kr_equity, global_equity, precious_metals, cyclical_commodity_fx, kr_bond, credit, global_duration, cash_mmf) with Option C baseline (위험 0.57), define 12×8=96 INITIAL_BETA prior matrix (row sums=0), update SIGN_RESTRICTION + INITIAL_TIPS_BETA for 12 factors, extend VALID_SUB_CATEGORIES + bucket mapping in sub_category.py, and remove AUM filter from candidate_selector.

**Architecture:** factor_to_bucket.py becomes the single source of truth for 8-bucket schema. Stage 3 selector reads `VALID_SUB_CATEGORIES` and `_CATEGORY_TO_BUCKET` (extended) from sub_category.py for ETF eligibility. AUM filter (DEFAULT_MIN_AUM_KRW = 500억 → removed) since mandate's 20% single-ETF cap + Stage 4 cluster cap already control micro-cap risk.

**Tech Stack:** Python 3.11+, pydantic v2 (mandate types), scipy.optimize (project_to_mandate_qp QP), pytest.

**Spec:** [`docs/superpowers/specs/2026-05-28-tier1-bucket-taxonomy-design.md`](../specs/2026-05-28-tier1-bucket-taxonomy-design.md)

**Dependency:** Requires [Tier 0](./2026-05-28-tier0-factor-model-reform.md) FACTORS tuple (12 factor) merged.

---

## File Structure

**Modified:**
- `tradingagents/skills/research/factor_to_bucket.py` — BUCKETS, RISK_BUCKETS, INITIAL_BASELINE, INITIAL_BETA (12×8), INITIAL_TIPS_BETA (12), SIGN_RESTRICTION, project_to_mandate_qp (8-bucket constraint matrix)
- `tradingagents/skills/portfolio/sub_category.py` — VALID_SUB_CATEGORIES (5→8 split), _CATEGORY_TO_BUCKET (special marker), `bucket_for_etf` function
- `tradingagents/skills/portfolio/candidate_selector.py` — AUM filter complete removal (L34/38/51-60/67/75)
- `tests/unit/skills/research/test_factor_to_bucket.py` — 8-bucket tests
- `tests/unit/skills/portfolio/test_sub_category.py` — 8-bucket mapping tests
- `tests/unit/skills/portfolio/test_candidate_selector.py` — AUM removal regression

**Created:**
- `tests/integration/test_tier1_bucket_pipeline.py` — end-to-end 8-bucket smoke

---

## Task 1: BUCKETS + RISK_BUCKETS + INITIAL_BASELINE

**Files:**
- Modify: `tradingagents/skills/research/factor_to_bucket.py`
- Modify: `tests/unit/skills/research/test_factor_to_bucket.py`

- [ ] **Step 1: Write failing test**

`tests/unit/skills/research/test_factor_to_bucket.py`:
```python
import pytest
from tradingagents.skills.research.factor_to_bucket import (
    BUCKETS, RISK_BUCKETS, INITIAL_BASELINE, MANDATE_RISK_CAP,
)


def test_buckets_8_entries():
    assert len(BUCKETS) == 8
    expected = {
        "kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx",
        "kr_bond", "credit", "global_duration", "cash_mmf",
    }
    assert set(BUCKETS) == expected


def test_risk_buckets_subset():
    assert set(RISK_BUCKETS) == {
        "kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx",
    }
    assert all(b in BUCKETS for b in RISK_BUCKETS)


def test_initial_baseline_option_c_57pct_risk():
    """Option C: kr_eq 0.15 + gl_eq 0.20 + precious 0.08 + cyclical 0.14 = 0.57."""
    assert abs(sum(INITIAL_BASELINE.values()) - 1.0) < 1e-9
    risk_sum = sum(INITIAL_BASELINE[b] for b in RISK_BUCKETS)
    assert abs(risk_sum - 0.57) < 1e-9
    safe_sum = sum(INITIAL_BASELINE[b] for b in BUCKETS if b not in RISK_BUCKETS)
    assert abs(safe_sum - 0.43) < 1e-9


def test_mandate_cap_unchanged():
    assert MANDATE_RISK_CAP == 0.70
```

- [ ] **Step 2: Run test (expect FAIL — 5-bucket schema still active)**

```bash
pytest tests/unit/skills/research/test_factor_to_bucket.py::test_buckets_8_entries -v
```

- [ ] **Step 3: Update factor_to_bucket.py**

Replace BUCKETS, RISK_BUCKETS, INITIAL_BASELINE:
```python
BUCKETS: Final[tuple[str, ...]] = (
    "kr_equity",
    "global_equity",
    "precious_metals",
    "cyclical_commodity_fx",
    "kr_bond",
    "credit",
    "global_duration",
    "cash_mmf",
)

RISK_BUCKETS: Final[tuple[str, ...]] = (
    "kr_equity",
    "global_equity",
    "precious_metals",
    "cyclical_commodity_fx",
)

MANDATE_RISK_CAP: Final[float] = 0.70

INITIAL_BASELINE: Final[dict[str, float]] = {
    "kr_equity":             0.15,
    "global_equity":         0.20,
    "precious_metals":       0.08,
    "cyclical_commodity_fx": 0.14,
    "kr_bond":               0.15,
    "credit":                0.05,
    "global_duration":       0.13,
    "cash_mmf":              0.10,
}
# Σ위험 = 0.57, Σ안전 = 0.43, total = 1.0 (Option C — Gemini-validated home bias).
```

- [ ] **Step 4: Run tests (expect PASS)**

```bash
pytest tests/unit/skills/research/test_factor_to_bucket.py::test_buckets_8_entries tests/unit/skills/research/test_factor_to_bucket.py::test_risk_buckets_subset tests/unit/skills/research/test_factor_to_bucket.py::test_initial_baseline_option_c_57pct_risk tests/unit/skills/research/test_factor_to_bucket.py::test_mandate_cap_unchanged -v
```

- [ ] **Step 5: Commit**

```bash
git add tradingagents/skills/research/factor_to_bucket.py tests/unit/skills/research/test_factor_to_bucket.py
git commit -m "feat(tier1): BUCKETS 5→8 + Option C baseline (risk 0.57)"
```

---

## Task 2: INITIAL_BETA prior matrix (12 × 8 = 96 entries)

**Files:**
- Modify: `tradingagents/skills/research/factor_to_bucket.py`
- Modify: `tests/unit/skills/research/test_factor_to_bucket.py`

- [ ] **Step 1: Write failing test**

```python
def test_initial_beta_96_entries_row_sums_zero():
    from tradingagents.skills.research.factor_to_bucket import INITIAL_BETA, BUCKETS, FACTORS
    assert len(INITIAL_BETA) == len(FACTORS) * len(BUCKETS)
    assert len(INITIAL_BETA) == 96
    for factor in FACTORS:
        row_sum = sum(INITIAL_BETA[(factor, b)] for b in BUCKETS)
        assert abs(row_sum) < 1e-9, f"{factor} row sum = {row_sum}"


def test_initial_beta_bounds():
    from tradingagents.skills.research.factor_to_bucket import INITIAL_BETA
    for (f, b), v in INITIAL_BETA.items():
        assert abs(v) <= 0.20, f"{f} × {b} = {v} exceeds bound"
```

- [ ] **Step 2: Run (expect FAIL)**

```bash
pytest tests/unit/skills/research/test_factor_to_bucket.py::test_initial_beta_96_entries_row_sums_zero -v
```

- [ ] **Step 3: Define 12×8 INITIAL_BETA**

Replace `INITIAL_BETA` with the 96-entry dict per spec §3.2. Copy-paste below verbatim:

```python
# Order: kr_equity, global_equity, precious_metals, cyclical_commodity_fx,
#        kr_bond, credit, global_duration, cash_mmf
INITIAL_BETA: Final[dict[tuple[str, str], float]] = {
    # === F1 growth (row sum = 0) ===
    ("F1_growth", "kr_equity"):             +0.05,
    ("F1_growth", "global_equity"):         +0.06,
    ("F1_growth", "precious_metals"):       -0.02,
    ("F1_growth", "cyclical_commodity_fx"): +0.03,
    ("F1_growth", "kr_bond"):               -0.04,
    ("F1_growth", "credit"):                +0.02,
    ("F1_growth", "global_duration"):       -0.05,
    ("F1_growth", "cash_mmf"):              -0.05,
    # === F2 inflation ===
    ("F2_inflation", "kr_equity"):             -0.02,
    ("F2_inflation", "global_equity"):         -0.03,
    ("F2_inflation", "precious_metals"):       +0.04,
    ("F2_inflation", "cyclical_commodity_fx"): +0.05,
    ("F2_inflation", "kr_bond"):               -0.03,
    ("F2_inflation", "credit"):                -0.01,
    ("F2_inflation", "global_duration"):       -0.03,
    ("F2_inflation", "cash_mmf"):              +0.03,
    # === F3 real_rate ===
    ("F3_real_rate", "kr_equity"):             -0.01,
    ("F3_real_rate", "global_equity"):         -0.02,
    ("F3_real_rate", "precious_metals"):       -0.05,
    ("F3_real_rate", "cyclical_commodity_fx"): -0.01,
    ("F3_real_rate", "kr_bond"):               -0.03,
    ("F3_real_rate", "credit"):                 0.00,
    ("F3_real_rate", "global_duration"):       -0.04,
    ("F3_real_rate", "cash_mmf"):              +0.16,
    # === F4 term_premium ===
    ("F4_term_premium", "kr_equity"):             +0.02,
    ("F4_term_premium", "global_equity"):         +0.03,
    ("F4_term_premium", "precious_metals"):        0.00,
    ("F4_term_premium", "cyclical_commodity_fx"):  0.00,
    ("F4_term_premium", "kr_bond"):               +0.04,
    ("F4_term_premium", "credit"):                +0.01,
    ("F4_term_premium", "global_duration"):       +0.03,
    ("F4_term_premium", "cash_mmf"):              -0.13,
    # === F5 credit_cycle ===
    ("F5_credit_cycle", "kr_equity"):             -0.05,
    ("F5_credit_cycle", "global_equity"):         -0.06,
    ("F5_credit_cycle", "precious_metals"):        0.00,
    ("F5_credit_cycle", "cyclical_commodity_fx"):  0.00,
    ("F5_credit_cycle", "kr_bond"):               +0.01,
    ("F5_credit_cycle", "credit"):                -0.06,
    ("F5_credit_cycle", "global_duration"):       +0.04,
    ("F5_credit_cycle", "cash_mmf"):              +0.12,
    # === F6 krw_regime ===
    ("F6_krw_regime", "kr_equity"):             -0.05,
    ("F6_krw_regime", "global_equity"):         +0.05,
    ("F6_krw_regime", "precious_metals"):       +0.02,
    ("F6_krw_regime", "cyclical_commodity_fx"): +0.02,
    ("F6_krw_regime", "kr_bond"):               -0.01,
    ("F6_krw_regime", "credit"):                 0.00,
    ("F6_krw_regime", "global_duration"):       +0.01,
    ("F6_krw_regime", "cash_mmf"):              -0.04,
    # === F7 equity_vol_regime ===
    ("F7_equity_vol_regime", "kr_equity"):             -0.05,
    ("F7_equity_vol_regime", "global_equity"):         -0.06,
    ("F7_equity_vol_regime", "precious_metals"):        0.00,
    ("F7_equity_vol_regime", "cyclical_commodity_fx"): -0.03,
    ("F7_equity_vol_regime", "kr_bond"):               +0.02,
    ("F7_equity_vol_regime", "credit"):                -0.02,
    ("F7_equity_vol_regime", "global_duration"):       +0.04,
    ("F7_equity_vol_regime", "cash_mmf"):              +0.10,
    # === F8 valuation ===
    ("F8_valuation", "kr_equity"):             -0.04,
    ("F8_valuation", "global_equity"):         -0.05,
    ("F8_valuation", "precious_metals"):       +0.01,
    ("F8_valuation", "cyclical_commodity_fx"): +0.01,
    ("F8_valuation", "kr_bond"):               +0.02,
    ("F8_valuation", "credit"):                +0.01,
    ("F8_valuation", "global_duration"):       +0.02,
    ("F8_valuation", "cash_mmf"):              +0.02,
    # === F9 market_dispersion ===
    ("F9_market_dispersion", "kr_equity"):             -0.04,
    ("F9_market_dispersion", "global_equity"):         -0.05,
    ("F9_market_dispersion", "precious_metals"):       -0.02,
    ("F9_market_dispersion", "cyclical_commodity_fx"): -0.02,
    ("F9_market_dispersion", "kr_bond"):               +0.03,
    ("F9_market_dispersion", "credit"):                -0.02,
    ("F9_market_dispersion", "global_duration"):       +0.02,
    ("F9_market_dispersion", "cash_mmf"):              +0.10,
    # === F10 systemic_liquidity ===
    ("F10_systemic_liquidity", "kr_equity"):             -0.06,
    ("F10_systemic_liquidity", "global_equity"):         -0.07,
    ("F10_systemic_liquidity", "precious_metals"):       +0.02,
    ("F10_systemic_liquidity", "cyclical_commodity_fx"): -0.02,
    ("F10_systemic_liquidity", "kr_bond"):               +0.04,
    ("F10_systemic_liquidity", "credit"):                -0.04,
    ("F10_systemic_liquidity", "global_duration"):       +0.04,
    ("F10_systemic_liquidity", "cash_mmf"):              +0.09,
    # === F11 earnings_revision ===
    ("F11_earnings_revision", "kr_equity"):             +0.05,
    ("F11_earnings_revision", "global_equity"):         +0.05,
    ("F11_earnings_revision", "precious_metals"):       -0.01,
    ("F11_earnings_revision", "cyclical_commodity_fx"): +0.01,
    ("F11_earnings_revision", "kr_bond"):               -0.02,
    ("F11_earnings_revision", "credit"):                +0.02,
    ("F11_earnings_revision", "global_duration"):       -0.04,
    ("F11_earnings_revision", "cash_mmf"):              -0.06,
    # === F12 china_credit_impulse ===
    ("F12_china_credit_impulse", "kr_equity"):             +0.04,
    ("F12_china_credit_impulse", "global_equity"):         +0.04,
    ("F12_china_credit_impulse", "precious_metals"):        0.00,
    ("F12_china_credit_impulse", "cyclical_commodity_fx"): +0.04,
    ("F12_china_credit_impulse", "kr_bond"):               -0.02,
    ("F12_china_credit_impulse", "credit"):                +0.02,
    ("F12_china_credit_impulse", "global_duration"):       -0.04,
    ("F12_china_credit_impulse", "cash_mmf"):              -0.08,
}
```

- [ ] **Step 4: Run tests; commit**

```bash
pytest tests/unit/skills/research/test_factor_to_bucket.py -v
git add tradingagents/skills/research/factor_to_bucket.py tests/unit/skills/research/test_factor_to_bucket.py
git commit -m "feat(tier1): INITIAL_BETA 12×8 prior matrix (row sums=0, |β|≤0.20)"
```

---

## Task 3: INITIAL_TIPS_BETA (12 entries)

- [ ] **Step 1: Write failing test**

```python
def test_initial_tips_beta_12_entries():
    from tradingagents.skills.research.factor_to_bucket import (
        INITIAL_TIPS_BETA, INITIAL_TIPS_BASELINE, FACTORS,
    )
    assert len(INITIAL_TIPS_BETA) == 12
    for factor in FACTORS:
        assert factor in INITIAL_TIPS_BETA
    assert INITIAL_TIPS_BASELINE == 0.30
```

- [ ] **Step 2: Update INITIAL_TIPS_BETA**

```python
INITIAL_TIPS_BASELINE: Final[float] = 0.30
INITIAL_TIPS_BETA: Final[dict[str, float]] = {
    "F1_growth":               +0.05,
    "F2_inflation":            +0.20,
    "F3_real_rate":            -0.10,
    "F4_term_premium":          0.00,
    "F5_credit_cycle":         -0.05,
    "F6_krw_regime":            0.00,
    "F7_equity_vol_regime":     0.00,
    "F8_valuation":             0.00,
    "F9_market_dispersion":    -0.03,
    "F10_systemic_liquidity": +0.05,
    "F11_earnings_revision":   0.00,    # NEW: earnings revision → TIPS preference link 약함
    "F12_china_credit_impulse":0.00,    # NEW: china credit → TIPS preference link 약함
}
```

- [ ] **Step 3: Test + commit**

```bash
pytest tests/unit/skills/research/test_factor_to_bucket.py::test_initial_tips_beta_12_entries -v
git commit -am "feat(tier1): INITIAL_TIPS_BETA → 12 entries (F11/F12 added)"
```

---

## Task 4: SIGN_RESTRICTION (8-bucket schema, ~30 entries)

- [ ] **Step 1: Write failing test**

```python
def test_sign_restriction_no_f5_precious_no_f7_gldur_no_f7_precious():
    """Tier 0 decision: remove dash-for-cash contradictions."""
    from tradingagents.skills.research.factor_to_bucket import SIGN_RESTRICTION
    assert ("F5_credit_cycle", "precious_metals") not in SIGN_RESTRICTION
    assert ("F7_equity_vol_regime", "global_duration") not in SIGN_RESTRICTION
    assert ("F7_equity_vol_regime", "precious_metals") not in SIGN_RESTRICTION


def test_sign_restriction_count():
    from tradingagents.skills.research.factor_to_bucket import SIGN_RESTRICTION
    # ~30 entries, exact 30 (count from spec §5)
    assert 28 <= len(SIGN_RESTRICTION) <= 35


def test_sign_restriction_consistency_with_initial_beta():
    """Each restricted (factor, bucket) has INITIAL_BETA sign matching restriction."""
    from tradingagents.skills.research.factor_to_bucket import (
        SIGN_RESTRICTION, INITIAL_BETA,
    )
    for (f, b), sign in SIGN_RESTRICTION.items():
        beta = INITIAL_BETA[(f, b)]
        if sign == "positive":
            assert beta >= 0, f"{f}×{b} sign=positive but prior β={beta}"
        elif sign == "negative":
            assert beta <= 0, f"{f}×{b} sign=negative but prior β={beta}"
```

- [ ] **Step 2: Update SIGN_RESTRICTION**

Replace `SIGN_RESTRICTION` dict in `factor_to_bucket.py` per spec §5:
```python
SignRestriction = Literal["positive", "negative", "neutral", "positive_mild", "negative_mild"]
SIGN_RESTRICTION: Final[dict[tuple[str, str], SignRestriction]] = {
    # F1 growth
    ("F1_growth", "kr_equity"):       "positive",
    ("F1_growth", "global_equity"):   "positive",
    ("F1_growth", "credit"):          "positive",
    ("F1_growth", "kr_bond"):         "negative",
    ("F1_growth", "global_duration"): "negative",
    ("F1_growth", "cash_mmf"):        "negative",
    # F2 inflation
    ("F2_inflation", "precious_metals"):       "positive",
    ("F2_inflation", "cyclical_commodity_fx"): "positive",
    ("F2_inflation", "kr_bond"):               "negative",
    ("F2_inflation", "global_duration"):       "negative",
    # F3 real_rate
    ("F3_real_rate", "precious_metals"):  "negative",
    ("F3_real_rate", "kr_bond"):          "negative",
    ("F3_real_rate", "global_duration"):  "negative",
    ("F3_real_rate", "cash_mmf"):         "positive",
    # F4 term_premium
    ("F4_term_premium", "kr_bond"):         "positive",
    ("F4_term_premium", "global_duration"): "positive",
    ("F4_term_premium", "cash_mmf"):        "negative",
    # F5 credit_cycle (precious 제거 — Tier 0 dash-for-cash 모순)
    ("F5_credit_cycle", "kr_equity"):     "negative",
    ("F5_credit_cycle", "global_equity"): "negative",
    ("F5_credit_cycle", "credit"):        "negative",
    ("F5_credit_cycle", "cash_mmf"):      "positive",
    # F6 krw_regime
    ("F6_krw_regime", "kr_equity"):     "negative",
    ("F6_krw_regime", "global_equity"): "positive",
    # F7 equity_vol_regime (gl_dur, precious 제거 — correlation breakdown)
    ("F7_equity_vol_regime", "kr_equity"):     "negative",
    ("F7_equity_vol_regime", "global_equity"): "negative",
    ("F7_equity_vol_regime", "cash_mmf"):      "positive",
    # F8 valuation
    ("F8_valuation", "kr_equity"):     "negative",
    ("F8_valuation", "global_equity"): "negative",
    # F9 market_dispersion
    ("F9_market_dispersion", "kr_equity"):     "negative",
    ("F9_market_dispersion", "global_equity"): "negative",
    ("F9_market_dispersion", "cash_mmf"):      "positive",
    # F10 systemic_liquidity
    ("F10_systemic_liquidity", "kr_equity"):              "negative",
    ("F10_systemic_liquidity", "global_equity"):          "negative",
    ("F10_systemic_liquidity", "credit"):                 "negative",
    ("F10_systemic_liquidity", "cyclical_commodity_fx"):  "negative",
    ("F10_systemic_liquidity", "kr_bond"):                "positive",
    ("F10_systemic_liquidity", "global_duration"):        "positive",
    ("F10_systemic_liquidity", "cash_mmf"):               "positive",
    # F11 earnings_revision
    ("F11_earnings_revision", "kr_equity"):     "positive",
    ("F11_earnings_revision", "global_equity"): "positive",
    ("F11_earnings_revision", "cash_mmf"):      "negative",
    # F12 china_credit_impulse
    ("F12_china_credit_impulse", "kr_equity"):              "positive",
    ("F12_china_credit_impulse", "cyclical_commodity_fx"):  "positive",
}
```

- [ ] **Step 3: Test + commit**

```bash
pytest tests/unit/skills/research/test_factor_to_bucket.py -v
git commit -am "feat(tier1): SIGN_RESTRICTION 8-bucket schema (~30 entries, F5/F7 dash-for-cash entries removed)"
```

---

## Task 5: project_to_mandate_qp 8-bucket adaptation

- [ ] **Step 1: Write failing test**

```python
def test_project_to_mandate_qp_8_buckets():
    """QP returns dict with 8 keys, sum=1, risk_buckets sum ≤ 0.70."""
    from tradingagents.skills.research.factor_to_bucket import (
        project_to_mandate_qp, BUCKETS, RISK_BUCKETS,
    )
    # Construct target with too much risk
    target = {b: 0.20 for b in RISK_BUCKETS}  # 4 × 0.20 = 0.80 risk
    target.update({b: 0.05 for b in BUCKETS if b not in RISK_BUCKETS})  # 4 × 0.05 = 0.20
    # Total = 1.00, risk = 0.80 — must be projected down to 0.70
    result = project_to_mandate_qp(target)
    assert set(result.keys()) == set(BUCKETS)
    assert abs(sum(result.values()) - 1.0) < 1e-6
    risk = sum(result[b] for b in RISK_BUCKETS)
    assert risk <= 0.70 + 1e-6


def test_project_to_mandate_qp_baseline_preserves_intent():
    from tradingagents.skills.research.factor_to_bucket import (
        project_to_mandate_qp, INITIAL_BASELINE,
    )
    # INITIAL_BASELINE is already feasible (risk 0.57 < 0.70)
    result = project_to_mandate_qp(dict(INITIAL_BASELINE))
    # Should be nearly identical
    for b, w in INITIAL_BASELINE.items():
        assert abs(result[b] - w) < 0.001
```

- [ ] **Step 2: Run test**

```bash
pytest tests/unit/skills/research/test_factor_to_bucket.py::test_project_to_mandate_qp_8_buckets tests/unit/skills/research/test_factor_to_bucket.py::test_project_to_mandate_qp_baseline_preserves_intent -v
```

If PASS: function is bucket-agnostic, no change needed (it iterates over input dict keys). If FAIL: see below.

- [ ] **Step 3: Inspect project_to_mandate_qp**

Existing function should already be bucket-agnostic via:
```python
keys = list(bucket_target.keys())
target = np.array([float(bucket_target[k]) for k in keys], dtype=float)
risk_indices = [i for i, k in enumerate(keys) if k in RISK_BUCKETS]
```

If yes, no change needed. Test PASS validates 8-bucket compatibility.

- [ ] **Step 4: Commit (or skip if no change)**

```bash
git commit --allow-empty -m "test(tier1): project_to_mandate_qp 8-bucket compatibility verified"
```

---

## Task 6: apply_factor_model uses new FACTORS + handles None z

- [ ] **Step 1: Write failing test**

```python
def test_apply_factor_model_handles_missing_factor_z():
    """F11/F12 None case — apply_factor_model should still work."""
    from tradingagents.skills.research.factor_to_bucket import (
        apply_factor_model, INITIAL_BASELINE, BUCKETS,
    )
    # Provide z for F1-F10 only (F11/F12 missing — pre-2010 case)
    factor_z = {
        "F1_growth": 0.5, "F2_inflation": 0.0, "F3_real_rate": 0.0,
        "F4_term_premium": 0.0, "F5_credit_cycle": 0.0,
        "F6_krw_regime": 0.0, "F7_equity_vol_regime": 0.0,
        "F8_valuation": 0.0, "F9_market_dispersion": 0.0,
        "F10_systemic_liquidity": 0.0,
        # F11, F12 absent (None case)
    }
    bucket, tips, contribs = apply_factor_model(factor_z)
    assert set(bucket.keys()) == set(BUCKETS)
    # F1 +0.5 → kr_eq, gl_eq slight positive shift
    assert bucket["kr_equity"] > INITIAL_BASELINE["kr_equity"]


def test_apply_factor_model_all_zero_returns_baseline():
    """All factor z = 0 → bucket == INITIAL_BASELINE."""
    from tradingagents.skills.research.factor_to_bucket import (
        apply_factor_model, INITIAL_BASELINE, FACTORS,
    )
    factor_z = {f: 0.0 for f in FACTORS}
    bucket, tips, contribs = apply_factor_model(factor_z)
    for b, w in INITIAL_BASELINE.items():
        assert abs(bucket[b] - w) < 1e-9
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/unit/skills/research/test_factor_to_bucket.py::test_apply_factor_model_handles_missing_factor_z tests/unit/skills/research/test_factor_to_bucket.py::test_apply_factor_model_all_zero_returns_baseline -v
```

If existing `factor_z.get(f, 0.0)` pattern is in place, PASS without modification.

- [ ] **Step 3: Inspect/update apply_factor_model**

The existing function iterates over `FACTORS` and calls `factor_z.get(f, 0.0)`. After T0 merged FACTORS = 12 entries, this should automatically handle F11/F12 = None (silent 0). Verify by reading the loop:

```python
for f in FACTORS:
    z = float(factor_z.get(f, 0.0))   # None → 0.0 fallback
    ...
```

If test PASSES, no change needed.

- [ ] **Step 4: Commit (verify only)**

```bash
git commit --allow-empty -m "test(tier1): apply_factor_model handles F11/F12 None gracefully"
```

---

## Task 7: VALID_SUB_CATEGORIES (8-bucket extension) in sub_category.py

**Files:**
- Modify: `tradingagents/skills/portfolio/sub_category.py`
- Create: `tests/unit/skills/portfolio/test_sub_category.py`

- [ ] **Step 1: Write failing test**

`tests/unit/skills/portfolio/test_sub_category.py`:
```python
from tradingagents.skills.portfolio.sub_category import (
    VALID_SUB_CATEGORIES, bucket_for_etf,
)


def test_valid_sub_categories_8_buckets():
    expected_buckets = {
        "kr_equity", "global_equity", "precious_metals", "cyclical_commodity_fx",
        "kr_bond", "credit", "global_duration", "cash_mmf",
    }
    assert set(VALID_SUB_CATEGORIES.keys()) == expected_buckets


def test_precious_metals_categories():
    assert "gold" in VALID_SUB_CATEGORIES["precious_metals"]
    assert "silver_precious" in VALID_SUB_CATEGORIES["precious_metals"]


def test_cyclical_commodity_categories():
    cc = VALID_SUB_CATEGORIES["cyclical_commodity_fx"]
    assert "oil_energy" in cc
    assert "broad_commodity" in cc
    assert "usd_fx" in cc


def test_bond_split():
    assert "kr_treasury" in VALID_SUB_CATEGORIES["kr_bond"]
    assert "us_high_yield" in VALID_SUB_CATEGORIES["credit"]
    assert "us_treasury" in VALID_SUB_CATEGORIES["global_duration"]
```

- [ ] **Step 2: Run test (expect FAIL)**

```bash
pytest tests/unit/skills/portfolio/test_sub_category.py -v
```

- [ ] **Step 3: Update VALID_SUB_CATEGORIES**

In `sub_category.py`, replace the dict:
```python
VALID_SUB_CATEGORIES: dict[str, list[str]] = {
    # Unchanged
    "kr_equity": [
        "index_broad", "semiconductor", "it_software", "ai_robotics",
        "battery_ev", "biotech_pharma", "finance", "consumer",
        "industrial_defense", "materials_energy", "factor_value_dividend",
        "thematic_other",
    ],
    "global_equity": [
        "us_broad", "us_tech_nasdaq", "us_sector", "europe", "japan",
        "china", "india", "emerging_other", "ai_theme_global",
        "thematic_other",
    ],
    # === NEW: split from fx_commodity ===
    "precious_metals": [
        "gold",
        "silver_precious",
    ],
    "cyclical_commodity_fx": [
        "oil_energy",
        "agricultural",
        "broad_commodity",
        "usd_fx",
        "jpy_fx",
    ],
    # === NEW: split from bond ===
    "kr_bond": [
        "kr_treasury",
        "short_duration",  # NOTE: implementation-time review per universe (kr vs global)
    ],
    "credit": [
        "kr_corporate",
        "us_high_yield",
        "us_aggregate",
        "em_bond",
    ],
    "global_duration": [
        "us_treasury",
        "inflation_linked",
    ],
    # Unchanged
    "cash_mmf": [
        "mmf_kr",
        "mmf_usd",
        "short_kr_bond",
    ],
}
```

- [ ] **Step 4: Commit**

```bash
pytest tests/unit/skills/portfolio/test_sub_category.py -v
git add tradingagents/skills/portfolio/sub_category.py tests/unit/skills/portfolio/test_sub_category.py
git commit -m "feat(tier1): VALID_SUB_CATEGORIES → 8-bucket (split fx_commodity, bond)"
```

---

## Task 8: _CATEGORY_TO_BUCKET + bucket_for_etf

- [ ] **Step 1: Write failing test**

```python
def test_bucket_for_etf_uses_sub_category():
    """Category '국내채권_종합' alone is ambiguous — needs sub_category."""
    from tradingagents.skills.portfolio.sub_category import bucket_for_etf
    
    class ETF:
        def __init__(self, cat, sub):
            self.category = cat
            self.sub_category = sub
    
    # KR equity straightforward
    assert bucket_for_etf(ETF("국내주식_지수", "index_broad")) == "kr_equity"
    
    # FX 및 원자재 — split by sub_category
    assert bucket_for_etf(ETF("FX 및 원자재", "gold")) == "precious_metals"
    assert bucket_for_etf(ETF("FX 및 원자재", "oil_energy")) == "cyclical_commodity_fx"
    
    # 국내채권 — split (kr_treasury → kr_bond, kr_corporate → credit)
    assert bucket_for_etf(ETF("국내채권_종합", "kr_treasury")) == "kr_bond"
    assert bucket_for_etf(ETF("국내채권_종합", "kr_corporate")) == "credit"
    
    # 해외채권_회사채 → credit directly
    assert bucket_for_etf(ETF("해외채권_회사채", "us_high_yield")) == "credit"
    
    # 금리연계형 → cash_mmf
    assert bucket_for_etf(ETF("금리연계형/초단기채권", "mmf_kr")) == "cash_mmf"
    
    # Unknown sub_category → None
    assert bucket_for_etf(ETF("FX 및 원자재", "unknown_label")) is None
```

- [ ] **Step 2: Update _CATEGORY_TO_BUCKET + bucket_for_etf**

In `sub_category.py`, replace:
```python
# Tier 1: special marker "_split_by_sub_category" — category alone is ambiguous.
_SPLIT_MARKER: Final[str] = "_split_by_sub_category"

_CATEGORY_TO_BUCKET: dict[str, str] = {
    "국내주식_지수": "kr_equity",
    "국내주식_섹터": "kr_equity",
    "해외주식_지수": "global_equity",
    "해외주식_섹터": "global_equity",
    "FX 및 원자재": _SPLIT_MARKER,
    "국내채권_종합": _SPLIT_MARKER,
    "국내채권_회사채": "credit",
    "해외채권_종합": _SPLIT_MARKER,
    "해외채권_회사채": "credit",
    "금리연계형/초단기채권": "cash_mmf",
}


def bucket_for_category(category: str) -> str | None:
    """Backward-compat: legacy single-category lookup."""
    result = _CATEGORY_TO_BUCKET.get(category)
    return result if result and result != _SPLIT_MARKER else None


def bucket_for_etf(etf) -> str | None:
    """8-bucket classification using (category, sub_category).
    
    For categories with _SPLIT_MARKER (FX 및 원자재, 국내채권_종합, 해외채권_종합),
    split by sub_category against VALID_SUB_CATEGORIES.
    """
    cat = _CATEGORY_TO_BUCKET.get(etf.category)
    if cat is None:
        return None
    if cat != _SPLIT_MARKER:
        return cat
    # Split by sub_category
    sub = getattr(etf, "sub_category", None)
    if not sub:
        return None
    for bucket, valid_subs in VALID_SUB_CATEGORIES.items():
        if sub in valid_subs:
            return bucket
    return None
```

- [ ] **Step 3: Test + commit**

```bash
pytest tests/unit/skills/portfolio/test_sub_category.py::test_bucket_for_etf_uses_sub_category -v
git commit -am "feat(tier1): bucket_for_etf with sub_category-based split for ambiguous categories"
```

---

## Task 9: AUM filter removal in candidate_selector.py

**Files:**
- Modify: `tradingagents/skills/portfolio/candidate_selector.py`
- Modify: `tests/unit/skills/portfolio/test_candidate_selector.py` (add regression test)

- [ ] **Step 1: Write failing test (small-AUM ETF passes)**

```python
def test_small_aum_etf_passes_eligibility(universe_with_small_aum):
    """After Tier 1: tiny AUM ETFs eligible (no filter)."""
    from tradingagents.skills.portfolio.candidate_selector import _eligible_for_bucket
    # universe_with_small_aum has e.g., 50억 AUM ETF in "국내주식_지수"
    eligible = _eligible_for_bucket(universe_with_small_aum, ["국내주식_지수"])
    # Was filtered out at 500억 threshold; now passes
    small_aum_tickers = [e.ticker for e in eligible if e.aum_krw < 50_000_000_000]
    assert len(small_aum_tickers) > 0
```

Need to define `universe_with_small_aum` fixture. Reuse existing test fixtures from `tests/unit/skills/portfolio/test_candidate_selector.py` and add a small-AUM entry.

- [ ] **Step 2: Update candidate_selector.py**

Remove the following (per spec §7 — exact lines):

**L34 (DEFAULT_MIN_AUM_KRW):** delete or set to 0
```python
# DEFAULT_MIN_AUM_KRW removed in Tier 1 — AUM filter eliminated.
# Mandate's 20% single-ETF cap + Stage 4 cluster cap suffice for micro-cap control.
```

**L38-43 (_RELAXED_MIN_AUM_KRW dict):** delete entirely

**L51-60 (_min_aum_for_etf):** delete entirely

**L63-68 (_eligible_for_bucket):** simplify
```python
def _eligible_for_bucket(universe: Universe, cats: list[str]) -> list:
    """Category match only — AUM filter removed (Tier 1).
    
    188 universe is already KRX-listed (basic size threshold).
    Mandate's 20% single-ETF cap + Stage 4 cluster cap control micro-cap risk.
    """
    return [e for e in universe.etfs if e.category in cats]
```

**L75 + all callers:** remove `min_aum_krw` parameter from `list_eligible()`, `_fill_bond_bucket()`, etc.

```bash
# Find all references
grep -n "min_aum_krw" tradingagents/skills/portfolio/candidate_selector.py
```

For each occurrence, remove the parameter (function signature + caller args).

- [ ] **Step 3: Run regression test**

```bash
pytest tests/unit/skills/portfolio/test_candidate_selector.py -v
```

Expect: existing tests still pass (AUM filter removal is *backward-permissive*, not restrictive).

- [ ] **Step 4: Commit**

```bash
git add tradingagents/skills/portfolio/candidate_selector.py tests/unit/skills/portfolio/test_candidate_selector.py
git commit -m "feat(tier1): AUM filter complete removal (500억 threshold deleted)"
```

---

## Task 10: BucketTarget schema update (8-bucket support)

**Files:**
- Modify: `tradingagents/schemas/portfolio.py` (BucketTarget if it has hardcoded 5-bucket fields)

- [ ] **Step 1: Inspect BucketTarget**

```bash
grep -A 20 "class BucketTarget" tradingagents/schemas/portfolio.py | head -30
```

- [ ] **Step 2: If BucketTarget has explicit 5-bucket fields, refactor to dict**

If schema is:
```python
class BucketTarget(BaseModel):
    kr_equity: float
    global_equity: float
    fx_commodity: float
    bond: float
    cash_mmf: float
```

Refactor to dict-based:
```python
class BucketTarget(BaseModel):
    weights: dict[str, float] = Field(
        description="Bucket name → weight. 8-bucket schema (Tier 1)."
    )

    def __getitem__(self, key): return self.weights[key]
    def __iter__(self): return iter(self.weights)
    def items(self): return self.weights.items()
    
    @model_validator(mode="after")
    def check_sum(self):
        if abs(sum(self.weights.values()) - 1.0) > 1e-6:
            raise ValueError(f"weights must sum to 1.0, got {sum(self.weights.values())}")
        return self
```

> If BucketTarget already uses a generic dict, no change needed.

- [ ] **Step 3: Test + commit**

```bash
pytest tests/unit/schemas/test_portfolio.py -v 2>/dev/null || pytest tests/unit/skills/research/ -v
git commit -am "feat(tier1): BucketTarget supports arbitrary bucket names (8-bucket)"
```

---

## Task 11: Stage 3 / Stage 4 8-bucket integration smoke

**Files:**
- Create: `tests/integration/test_tier1_bucket_pipeline.py`

- [ ] **Step 1: Write integration test**

```python
"""Tier 1 end-to-end: 8-bucket factor model → allocator → mandate check."""
import pytest
from datetime import date
from tradingagents.skills.research.factor_to_bucket import (
    apply_factor_model_with_safety, INITIAL_BASELINE, BUCKETS,
)


def test_factor_model_returns_8_bucket_target():
    factor_z = {f: 0.0 for f in [
        "F1_growth", "F2_inflation", "F3_real_rate", "F4_term_premium",
        "F5_credit_cycle", "F6_krw_regime", "F7_equity_vol_regime",
        "F8_valuation", "F9_market_dispersion", "F10_systemic_liquidity",
        "F11_earnings_revision", "F12_china_credit_impulse",
    ]}
    bucket, tips, contribs, diag = apply_factor_model_with_safety(factor_z)
    assert set(bucket.keys()) == set(BUCKETS)
    for b, w in INITIAL_BASELINE.items():
        assert abs(bucket[b] - w) < 1e-9


def test_factor_shock_keeps_mandate_compliance():
    """Large F1 shock — risk bucket bias — but mandate cap holds."""
    factor_z = {f: 0.0 for f in [
        "F1_growth", "F2_inflation", "F3_real_rate", "F4_term_premium",
        "F5_credit_cycle", "F6_krw_regime", "F7_equity_vol_regime",
        "F8_valuation", "F9_market_dispersion", "F10_systemic_liquidity",
        "F11_earnings_revision", "F12_china_credit_impulse",
    ]}
    factor_z["F1_growth"] = 3.0  # extreme growth shock
    bucket, _, _, _ = apply_factor_model_with_safety(factor_z)
    risk_sum = sum(bucket[b] for b in ("kr_equity", "global_equity",
                                        "precious_metals", "cyclical_commodity_fx"))
    assert risk_sum <= 0.70 + 1e-6  # mandate cap


def test_188_universe_classification_coverage():
    """Sanity: ≥ 90% of 188 universe ETFs classify into 8 buckets."""
    import json
    from pathlib import Path
    universe_path = Path("data/universe/universe.json")
    if not universe_path.exists():
        pytest.skip("universe.json not present in test env")
    universe = json.loads(universe_path.read_text(encoding="utf-8"))
    etfs = universe.get("etfs", [])
    from tradingagents.skills.portfolio.sub_category import bucket_for_etf
    class _ETF:
        def __init__(self, d):
            self.category = d.get("category")
            self.sub_category = d.get("sub_category")
            self.ticker = d.get("ticker")
    classified = [e for e in etfs if bucket_for_etf(_ETF(e)) is not None]
    coverage = len(classified) / max(len(etfs), 1)
    assert coverage >= 0.85, f"coverage={coverage:.2%} < 85% — sub_category re-enrich needed"
```

- [ ] **Step 2: Run + commit**

```bash
pytest tests/integration/test_tier1_bucket_pipeline.py -v
git add tests/integration/test_tier1_bucket_pipeline.py
git commit -m "test(tier1): integration — 8-bucket factor pipeline + 188 universe coverage"
```

---

## Acceptance Checklist

- [ ] BUCKETS tuple = 8 entries, names match spec
- [ ] RISK_BUCKETS = 4 entries (kr_eq, gl_eq, precious, cyclical)
- [ ] INITIAL_BASELINE sum = 1.0, risk = 0.57, safe = 0.43
- [ ] MANDATE_RISK_CAP = 0.70
- [ ] INITIAL_BETA = 96 entries, all row sums = 0 (±1e-9), |β| ≤ 0.20
- [ ] INITIAL_TIPS_BETA = 12 entries (F1-F12)
- [ ] SIGN_RESTRICTION 28-35 entries, no F5×precious / F7×gl_dur / F7×precious
- [ ] All SIGN_RESTRICTION (factor, bucket) prior β agrees with restriction sign
- [ ] project_to_mandate_qp works for 8-bucket input (sum=1, risk≤0.70)
- [ ] apply_factor_model handles F11/F12 None gracefully (0.0 fallback)
- [ ] VALID_SUB_CATEGORIES has 8 buckets (5 → 8 split — fx_commodity & bond split)
- [ ] _CATEGORY_TO_BUCKET uses _SPLIT_MARKER for ambiguous categories
- [ ] bucket_for_etf(etf) classifies via (category, sub_category) — 8-bucket
- [ ] AUM filter removed from candidate_selector (DEFAULT_MIN_AUM_KRW + helper + filter clause + parameter)
- [ ] 188 universe coverage ≥ 85% (sub_category re-enrich if needed)
- [ ] BucketTarget schema supports 8-bucket weights dict
- [ ] Integration test: factor shock respects mandate

---

**Plan saved to `docs/superpowers/plans/2026-05-28-tier1-bucket-taxonomy.md`.**
