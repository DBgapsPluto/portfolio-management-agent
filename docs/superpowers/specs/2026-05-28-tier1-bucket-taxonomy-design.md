# Tier 1 — Bucket Taxonomy Redesign (5 → 8) + Mandate Re-anchor

- **작성일:** 2026-05-28
- **대상:** Stage 2/Stage 3 구현자
- **선행 의존:** [Tier 0 spec](./2026-05-28-tier0-factor-model-reform-design.md) — 12 factor 구조 확정
- **후속 의존:** Tier 2 (β calibration), Tier 3 (LLM overlay)
- **외부 참조:** [Gemini Deep Research](../../Factor_Model_Gemini_DeepResearch) §4.1 home bias 정당화

---

## 0. TL;DR

`factor_to_bucket.py`의 5-bucket coarse-grained taxonomy를 **8-bucket 경제 driver 기반**으로 재설계. `INITIAL_BASELINE`을 위험 47% → 57%로 re-anchor (대회 3개월 + 30% 수익 비중 고려). AUM filter 완전 제거. Stage 3 selector의 5-bucket 가정 제거. INITIAL_BETA prior matrix 12×8 = 96 entries 정의 (row sums = 0). INITIAL_TIPS_BETA 12 entries 확장.

---

## 1. 새 8-bucket schema

`tradingagents/skills/research/factor_to_bucket.py`:

```python
BUCKETS: Final[tuple[str, ...]] = (
    "kr_equity",
    "global_equity",
    "precious_metals",         # NEW: gold + silver (real-rate / systemic stress hedge)
    "cyclical_commodity_fx",   # NEW: oil + copper + grain + DXY (inflation + growth)
    "kr_bond",                 # SPLIT from "bond"
    "credit",                  # SPLIT from "bond": HY/IG credit spread plays
    "global_duration",         # SPLIT from "bond": US 20+ Treasury duration
    "cash_mmf",
)

RISK_BUCKETS: Final[tuple[str, ...]] = (
    "kr_equity",
    "global_equity",
    "precious_metals",
    "cyclical_commodity_fx",
)
# 대회 규정 §2.2: 위험자산 sum ≤ 0.70 (MANDATE_RISK_CAP 유지)

MANDATE_RISK_CAP: Final[float] = 0.70
PER_FACTOR_BUCKET_CONTRIB_CAP: Final[float] = 0.10  # unchanged
```

### 1.1. Bucket별 economic driver

| Bucket | Driver | 대표 ETF (KR 도메스틱) |
|---|---|---|
| `kr_equity` | KR growth, KRW regime | KODEX 200, TIGER KOSPI 등 |
| `global_equity` | global growth, USD risk-on | KODEX MSCI World, TIGER S&P 500 |
| `precious_metals` | real rate ↓, USD ↓, systemic stress | KODEX 골드선물, TIGER 골드선물 |
| `cyclical_commodity_fx` | inflation ↑, growth ↑, DXY | KODEX WTI원유선물, TIGER 구리실물, KODEX 미국달러선물 |
| `kr_bond` | KR rate, term premium | KODEX 국고채10년, TIGER 단기채권 |
| `credit` | credit spread, growth | KODEX 미국하이일드, TIGER 단기특수은행채 |
| `global_duration` | US real rate, term premium | TIGER 미국채10년선물, KODEX 미국30년국채 |
| `cash_mmf` | KRW 단기금리, liquidity haven | KODEX 단기채권PLUS, TIGER 머니마켓 |

---

## 2. INITIAL_BASELINE — Option C (위험 0.57)

**원칙 (학술 검증, deferred to Gemini §4.1, §8):**

1. **위험 57% = mandate cap 70%의 80%**: 3개월 대회 + 30% 수익 가중 고려. Conservative하면 수익 점수 손실, 공격적이면 risk-off 시 박살. 중도 risk-on.
2. **위험 안에서 equity 우선**: equity(kr+gl) = 35pp vs commodity(precious+cyclical) = 22pp ≈ 1.6:1. equity가 핵심 risk premium 자산.
3. **Home bias 정당화** (Baxter-Jermann 1997, Heathcote-Perri 2013): kr_eq:gl_eq = 15:20 = 0.75 (KR-원화 펀드).
4. **Precious < cyclical**: precious는 단일 driver (real rate/systemic), cyclical은 broader commodity basket.
5. **안전 안에서 duration > credit**: credit은 risk-on 성격 → 부피 작게. KR duration ≥ global duration (통화 매칭).
6. **Cash 10%**: 3개월 대회 turnover 의무 + 단일 ETF 20% cap 대응 버퍼.

**Baseline 정의:**

```python
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
# Σ위험 = 0.57, Σ안전 = 0.43, total = 1.0
```

---

## 3. INITIAL_BETA prior matrix (12 factor × 8 bucket)

### 3.1. 원칙
- **Row sum = 0** (각 factor가 baseline 합계를 안 바꿈)
- **|β| ≤ 0.20** (PR2a hybrid_calibration bounds 호환)
- **PER_FACTOR_BUCKET_CONTRIB_CAP ±0.10** 유지 (single (factor, bucket) contribution 제한)
- 부호 패턴은 [Tier 0 spec §3](./2026-05-28-tier0-factor-model-reform-design.md) 의 economic intuition + SIGN_RESTRICTION dict에 부합
- Tier 0의 sign restriction 변경 (F5×precious, F7×gl_dur, F7×precious 제거) 반영

### 3.2. 12 × 8 numeric prior (calibration의 prior로 사용, Tier 2 hybrid_calibration의 `||β - prior||²` 항)

| factor \ bucket | kr_eq | gl_eq | precious | cyclical | kr_bond | credit | gl_dur | cash |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| F1_growth | +0.05 | +0.06 | −0.02 | +0.03 | −0.04 | +0.02 | −0.05 | −0.05 |
| F2_inflation | −0.02 | −0.03 | +0.04 | +0.05 | −0.03 | −0.01 | −0.03 | +0.03 |
| F3_real_rate | −0.01 | −0.02 | −0.05 | −0.01 | −0.03 | 0.00 | −0.04 | +0.16 |
| F4_term_premium | +0.02 | +0.03 | 0.00 | 0.00 | +0.04 | +0.01 | +0.03 | −0.13 |
| F5_credit_cycle | −0.05 | −0.06 | 0.00 | 0.00 | +0.01 | −0.06 | +0.04 | +0.12 |
| F6_krw_regime | −0.05 | +0.05 | +0.02 | +0.02 | −0.01 | 0.00 | +0.01 | −0.04 |
| F7_equity_vol | −0.05 | −0.06 | 0.00 | −0.03 | +0.02 | −0.02 | +0.04 | +0.10 |
| F8_valuation | −0.04 | −0.05 | +0.01 | +0.01 | +0.02 | +0.01 | +0.02 | +0.02 |
| F9_market_dispersion | −0.04 | −0.05 | −0.02 | −0.02 | +0.03 | −0.02 | +0.02 | +0.10 |
| F10_systemic_liquidity | −0.06 | −0.07 | +0.02 | −0.02 | +0.04 | −0.04 | +0.04 | +0.09 |
| F11_earnings_revision | +0.05 | +0.05 | −0.01 | +0.01 | −0.02 | +0.02 | −0.04 | −0.06 |
| F12_china_credit_impulse | +0.04 | +0.04 | 0.00 | +0.04 | −0.02 | +0.02 | −0.04 | −0.08 |

**행 합 검증:**
- F1: +0.05+0.06−0.02+0.03−0.04+0.02−0.05−0.05 = **0.00** ✓
- F2: −0.02−0.03+0.04+0.05−0.03−0.01−0.03+0.03 = **0.00** ✓
- F3: −0.01−0.02−0.05−0.01−0.03+0.00−0.04+0.16 = **0.00** ✓
- F4: +0.02+0.03+0.00+0.00+0.04+0.01+0.03−0.13 = **0.00** ✓
- F5: −0.05−0.06+0.00+0.00+0.01−0.06+0.04+0.12 = **0.00** ✓
- F6: −0.05+0.05+0.02+0.02−0.01+0.00+0.01−0.04 = **0.00** ✓
- F7: −0.05−0.06+0.00−0.03+0.02−0.02+0.04+0.10 = **0.00** ✓
- F8: −0.04−0.05+0.01+0.01+0.02+0.01+0.02+0.02 = **0.00** ✓
- F9: −0.04−0.05−0.02−0.02+0.03−0.02+0.02+0.10 = **0.00** ✓
- F10: −0.06−0.07+0.02−0.02+0.04−0.04+0.04+0.09 = **0.00** ✓
- F11: +0.05+0.05−0.01+0.01−0.02+0.02−0.04−0.06 = **0.00** ✓
- F12: +0.04+0.04+0.00+0.04−0.02+0.02−0.04−0.08 = **0.00** ✓

### 3.3. 핵심 해설

- **F1 growth ↑** → kr_eq/gl_eq/credit/cyclical ↑, bond/cash ↓ (절감), precious 약간 ↓
- **F2 inflation ↑** → precious/cyclical (실물) ↑, kr_eq/bond (명목) ↓, cash 약간 ↑
- **F3 real rate ↑** → 모든 자산 negative (precious/bond 가장 큼), cash dominant +0.16
- **F4 term premium ↑** → bond duration (kr_bond/gl_dur) ↑, cash 큰 ↓ (장기 매력)
- **F5 credit cycle ↑ (stress)** → equity/credit ↓, precious 0.00 (sign restriction 제거 — dash-for-cash 가능성), cash +0.12
- **F6 krw weakening ↑** → kr_eq ↓ (외국인 매도), gl_eq ↑ (USD 자산 가치 ↑), precious/cyclical ↑
- **F7 equity vol ↑** → kr_eq/gl_eq ↓, precious/gl_dur 0/약함 (sign restriction 제거 — correlation breakdown 사례), cash ↑
- **F8 expensive ↑** → equity ↓, bond/cash 약간 ↑ (mean reversion expectation)
- **F9 dispersion ↑** → equity ↓ (narrow rally 위험), cash ↑
- **F10 systemic stress ↑** → broad risk-off (모든 위험자산 ↓), kr_bond/gl_dur/cash ↑, credit ↓ (risk-on like)
- **F11 earnings up ↑** → equity ↑ (직접), bond/cash ↓
- **F12 china credit impulse ↑** → kr_eq/gl_eq/cyclical ↑ (KR 수출 우호), bond/cash ↓

---

## 4. INITIAL_TIPS_BETA (12 entries 확장)

`INITIAL_TIPS_BASELINE = 0.30` (bond bucket 안의 TIPS share, unchanged).

```python
INITIAL_TIPS_BETA: Final[dict[str, float]] = {
    "F1_growth":              +0.05,
    "F2_inflation":           +0.20,
    "F3_real_rate":           -0.10,
    "F4_term_premium":         0.00,
    "F5_credit_cycle":        -0.05,
    "F6_krw_regime":           0.00,
    "F7_equity_vol_regime":    0.00,
    "F8_valuation":            0.00,
    "F9_market_dispersion":   -0.03,
    "F10_systemic_liquidity": +0.05,
    "F11_earnings_revision":   0.00,  # NEW: earnings has weak link to TIPS preference
    "F12_china_credit_impulse": 0.00, # NEW: same
}
```

---

## 5. SIGN_RESTRICTION (8-bucket schema)

Tier 0의 sign restriction 제거 결정 반영. 12 × 8 = 96 cell 중 *경제적으로 명백한* sign만 hard restriction (soft prior로 사용).

```python
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
    ("F3_real_rate", "precious_metals"):  "negative",  # 금 기회비용 (Asness 학술)
    ("F3_real_rate", "kr_bond"):          "negative",
    ("F3_real_rate", "global_duration"):  "negative",
    ("F3_real_rate", "cash_mmf"):         "positive",

    # F4 term_premium
    ("F4_term_premium", "kr_bond"):         "positive",
    ("F4_term_premium", "global_duration"): "positive",
    ("F4_term_premium", "cash_mmf"):        "negative",

    # F5 credit_cycle (precious 제거 — Tier 0 §4 dash-for-cash 모순)
    ("F5_credit_cycle", "kr_equity"):     "negative",
    ("F5_credit_cycle", "global_equity"): "negative",
    ("F5_credit_cycle", "credit"):        "negative",
    ("F5_credit_cycle", "cash_mmf"):      "positive",

    # F6 krw_regime
    ("F6_krw_regime", "kr_equity"):     "negative",
    ("F6_krw_regime", "global_equity"): "positive",  # USD 자산 가치 ↑

    # F7 equity_vol_regime (gl_dur, precious 제거 — Tier 0 §4 correlation breakdown)
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

    # F11 earnings_revision (NEW)
    ("F11_earnings_revision", "kr_equity"):     "positive",
    ("F11_earnings_revision", "global_equity"): "positive",
    ("F11_earnings_revision", "cash_mmf"):      "negative",

    # F12 china_credit_impulse (NEW)
    ("F12_china_credit_impulse", "kr_equity"):              "positive",
    ("F12_china_credit_impulse", "cyclical_commodity_fx"):  "positive",
}
```

**총 sign restriction:** 약 30개 cell (12 factor × ~2-4 명백한 bucket).

---

## 6. BUCKET_TO_CATEGORIES (188 ETF → 8 bucket mapping)

**현 시스템 확인 (2026-05-28 실측):**
- `tradingagents/skills/portfolio/sub_category.py:20` 의 `VALID_SUB_CATEGORIES` dict가 *5-bucket schema의 sub_category enum*. 라벨이 universe.json의 `ETFEntry.sub_category` 필드에 저장.
- `sub_category.py:77` 의 `_CATEGORY_TO_BUCKET` 가 9개 category (예: "국내주식_지수") → 5 bucket mapping.

**8-bucket migration 결정 (universe.json sub_category 라벨은 *유지*, mapping만 확장):**

```python
# tradingagents/skills/portfolio/sub_category.py 확장
VALID_SUB_CATEGORIES: dict[str, list[str]] = {
    # === unchanged ===
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
        "kr_treasury",       # 국고채
        "short_duration",    # 단기 (KR 단기채권 위주 — universe-level 확인)
    ],
    "credit": [
        "kr_corporate",      # 국내 회사채
        "us_high_yield",     # US HY
        "us_aggregate",      # US IG aggregate
        "em_bond",           # EM credit
    ],
    "global_duration": [
        "us_treasury",       # US 국채
        "inflation_linked",  # TIPS (US duration + inflation)
    ],
    # === unchanged ===
    "cash_mmf": [
        "mmf_kr",
        "mmf_usd",
        "short_kr_bond",     # 초단기 KR (cash-like, kr_bond와 구분)
    ],
}
```

**주의 — `short_duration` 분류:**
- 기존엔 "bond" 단일 bucket이라 KR 단기 / 글로벌 단기 구분 X.
- 새 schema: `short_duration` 라벨이 KR 위주면 `kr_bond`, 글로벌이면 `global_duration` 또는 `cash_mmf`.
- **구현 시 universe.json 검사**: 각 `short_duration` 라벨 ETF의 실제 underlying (국고채 단기 vs Treasury 단기)을 보고 분류.

**`_CATEGORY_TO_BUCKET` 확장 (universe.json의 9 category → 8 bucket):**

```python
_CATEGORY_TO_BUCKET: dict[str, str] = {
    "국내주식_지수": "kr_equity",
    "국내주식_섹터": "kr_equity",
    "해외주식_지수": "global_equity",
    "해외주식_섹터": "global_equity",
    # NEW: FX 및 원자재 → sub_category로 분기 (precious_metals vs cyclical_commodity_fx)
    "FX 및 원자재": "_split_by_sub_category",  # special marker
    # NEW: 채권 카테고리들 → sub_category로 분기 (kr_bond/credit/global_duration)
    "국내채권_종합": "_split_by_sub_category",
    "국내채권_회사채": "credit",          # 회사채 = credit
    "해외채권_종합": "_split_by_sub_category",
    "해외채권_회사채": "credit",
    "금리연계형/초단기채권": "cash_mmf",
}

def bucket_for_etf(etf: ETFEntry) -> str | None:
    """Category + sub_category 결합으로 8-bucket 분류.
    
    "FX 및 원자재" 같은 broad category는 sub_category로 split (precious vs cyclical).
    """
    cat = _CATEGORY_TO_BUCKET.get(etf.category)
    if cat is None:
        return None
    if cat != "_split_by_sub_category":
        return cat
    # Split by sub_category
    for bucket, valid_subs in VALID_SUB_CATEGORIES.items():
        if etf.sub_category in valid_subs:
            return bucket
    return None  # unclassified
```

**구현 acceptance:**
- [ ] 188 universe 전수 검사: 최소 90% ETF가 8-bucket 중 하나로 분류
- [ ] 분류 안 된 ETF는 `enrich_universe_subcategory.py` 재실행으로 sub_category 재라벨링 (LLM-aided)
- [ ] `short_duration` 라벨 ETF는 underlying 확인 후 `kr_bond` 또는 `cash_mmf` 분류 명확화 (universe.json patch)

---

## 7. AUM filter 제거 — 정확한 location

**현 시스템 (2026-05-28 실측 — `candidate_selector.py`):**

| Line | Code | 변경 |
|---|---|---|
| L34 | `DEFAULT_MIN_AUM_KRW: float = 50_000_000_000` (500억) | **상수 제거 또는 0으로** |
| L38-43 | `_RELAXED_MIN_AUM_KRW: dict[str, float] = {"inflation_linked": 10_000_000_000}` (sparse 완화) | **제거** |
| L51-60 | `def _min_aum_for_etf(etf, default_threshold) -> float:` (helper) | **제거** |
| L63-68 | `def _eligible_for_bucket(universe, cats, min_aum_krw):` — return `[e for e in universe.etfs if e.category in cats and e.aum_krw >= _min_aum_for_etf(e, min_aum_krw)]` | **AUM clause 제거**: `[e for e in universe.etfs if e.category in cats]` |
| L75 | `def list_eligible(bucket_target, as_of, min_aum_krw=DEFAULT_MIN_AUM_KRW):` parameter | **`min_aum_krw` parameter 제거** |
| 모든 호출처 | `min_aum_krw=X` argument | **제거** |

**Migration logic:**

```python
# BEFORE
def _eligible_for_bucket(universe: Universe, cats: list[str], min_aum_krw: float):
    return [
        e for e in universe.etfs
        if e.category in cats and e.aum_krw >= _min_aum_for_etf(e, min_aum_krw)
    ]

# AFTER (Tier 1)
def _eligible_for_bucket(universe: Universe, cats: list[str]):
    """Category match만 — AUM filter 제거 (Tier 1).
    
    근거: 1조 threshold가 10억 capital의 5000배라 너무 strict였음.
    188 universe 자체가 KRX 상장 ETF로 기본 사이즈 필터 통과.
    단일 ETF cap 20% (대회 규정) + Stage 4 risk_judge의 cluster cap이 
    micro-cap 위험 통제.
    """
    return [e for e in universe.etfs if e.category in cats]
```

**관련 영향:**
- L75 `list_eligible()`, L283 `_fill_bond_bucket()` 등 caller도 `min_aum_krw` parameter 제거
- `DEFAULT_MIN_AUM_KRW` 상수 → 완전 제거 또는 단순 deprecated comment

**근거 (Gemini deep research + Stage 3 audit):**
- 1조 threshold (구버전) 또는 500억 (현재)도 188 universe에서 sparse sub-category (inflation_linked, em_bond) 에서 *false positive padding* 발현
- `select_diverse` padding 시 *AUM 통과한 ETF 부족* → 같은 상관성 ETF 재선택 → cluster concentration
- 단일 ETF 20% cap이 micro-cap 위험 자연 제한 (10억 capital × 20% = 2억 한 개 ETF — 일반적인 KRX ETF는 그 정도 거래량 충분)

---

## 8. Stage 3 Connected Changes

### 8.1. `candidate_selector.py`
- `BUCKETS` 5개 가정 제거 (8-bucket 동적 처리)
- `BUCKET_TO_CATEGORIES` 매핑 사용
- AUM filter 제거 (위 §7)

### 8.2. `factor_scorer.py`
- 변경 없음 (factor scorer는 bucket-agnostic)

### 8.3. `method_picker.py`
- 변경 없음 (allocation method는 bucket count에 robust)

### 8.4. `portfolio_allocator.py`
- 8 bucket에 대해 `risk_parity` / `min_volatility` 작동 검증
- Per-bucket cap 결정 logic이 8-bucket sum=1 가정 호환

### 8.5. `overlay_apply.py` (Stage 4)
- `BUCKETS` 참조 확인. Cluster cap (Stage 4)이 새 bucket 구조 호환.

---

## 9. project_to_mandate_qp 변경

`factor_to_bucket.py:project_to_mandate_qp` 함수:

```python
def project_to_mandate_qp(
    bucket_target: dict[str, float],
    risk_cap: float = MANDATE_RISK_CAP,
) -> dict[str, float]:
    """QP-based projection: w* = argmin ||w - bucket_target||²
    
    Subject to:
      - Σ w = 1                                 (probability simplex)
      - 0 ≤ w_b ≤ 1                             (no shorting)
      - Σ_{b ∈ RISK_BUCKETS} w_b ≤ risk_cap     (mandate)
    
    8-bucket version: RISK_BUCKETS = (kr_equity, global_equity, 
    precious_metals, cyclical_commodity_fx). 위험자산 합 ≤ 0.70.
    """
    # 구조 동일, RISK_BUCKETS만 8-bucket 호환
    ...
```

**확인:** PR2a의 SLSQP-based QP solver가 8-bucket으로 확장해도 작동. constraint 행렬 dimension만 변경.

---

## 10. apply_factor_model 변경

`factor_to_bucket.py:apply_factor_model`:

```python
def apply_factor_model(
    factor_z: dict[str, float],
    baseline: dict[str, float] | None = None,
    beta: dict[tuple[str, str], float] | None = None,
    tips_baseline: float | None = None,
    tips_beta: dict[str, float] | None = None,
) -> tuple[dict[str, float], float, dict[str, dict[str, float]]]:
    """factor z → bucket allocation (raw, pre-projection).
    
    Linear additive regression with per-(factor, bucket) contribution cap.
    
    Changes (Tier 1):
    - BUCKETS 5 → 8
    - FACTORS 9 → 12 (Tier 0 dependency)
    - F11 staggered: F11 z=None or confidence=0이면 그 factor 기여 0
    """
    ...
    for f in FACTORS:
        z = float(factor_z.get(f, 0.0))
        if z is None:  # F11 staggered: 2010 이전 sample
            continue
        ...
```

---

## 11. Acceptance Criteria

### 11.1. Code-level
- [ ] `BUCKETS` tuple = 8 entries, 새 이름 정확
- [ ] `INITIAL_BASELINE` sum = 1.0, RISK_BUCKETS sum = 0.57
- [ ] `INITIAL_BETA` 96 entries, 모든 row sum = 0 (±1e-9), |β| ≤ 0.20
- [ ] `INITIAL_TIPS_BETA` 12 entries (F1-F12)
- [ ] `SIGN_RESTRICTION` ~30 entries, Tier 0의 sign 제거 반영
- [ ] `RISK_BUCKETS` = 4 entries, MANDATE_RISK_CAP = 0.70
- [ ] `project_to_mandate_qp` 8-bucket input 처리 OK
- [ ] AUM filter 제거 확인 (candidate_selector.py)

### 11.2. Integration
- [ ] `apply_factor_model_with_safety(factor_z)`가 12-factor input + 8-bucket output 반환
- [ ] Stage 3 candidate_selector가 8-bucket BUCKET_TO_CATEGORIES 사용
- [ ] Stage 4 overlay_apply가 8-bucket 호환
- [ ] F11 staggered: F11 z=None일 때 factor model gracefully degrade

### 11.3. Numerical sanity
- [ ] `apply_factor_model(all-zero z)` → INITIAL_BASELINE 반환 (intercept-only)
- [ ] `apply_factor_model({F1: +2.0, rest: 0})` → equity ↑, bond/cash ↓ (sign 일관)
- [ ] `apply_factor_model({F10: +2.0, rest: 0})` → 모든 RISK_BUCKETS ↓, kr_bond/gl_dur/cash ↑ (broad risk-off)
- [ ] `project_to_mandate_qp(extreme target)`: 위험자산 70%로 clip + 안전자산 잔여 분배

### 11.4. Tests
- [ ] Unit tests: row sum, weight bounds, sign restriction count
- [ ] Integration test: 5-bucket → 8-bucket migration (fixtures regen)
- [ ] Stage 3 selector test: 188 universe → 8 bucket 분류 정확도 (최소 90% ETF 분류됨)

---

## 12. 영향받는 파일

| File | 변경 |
|---|---|
| `tradingagents/skills/research/factor_to_bucket.py` | BUCKETS, RISK_BUCKETS, INITIAL_BASELINE, INITIAL_BETA, INITIAL_TIPS_BETA, SIGN_RESTRICTION, project_to_mandate_qp 모두 8-bucket/12-factor 호환 |
| `tradingagents/skills/portfolio/candidate_selector.py` | BUCKETS 5 가정 제거, BUCKET_TO_CATEGORIES 8-bucket 사용, AUM filter 제거 |
| `tradingagents/skills/portfolio/sub_category.py` | BUCKET_TO_CATEGORIES dict 정의 (또는 candidate_selector로 이동) |
| `tradingagents/agents/allocator/portfolio_allocator.py` | 8-bucket 호환 확인 |
| `tradingagents/skills/portfolio/method_picker.py` | 8-bucket 호환 확인 |
| `tradingagents/skills/portfolio/overlay_apply.py` (Stage 4) | 8-bucket 호환 확인 |
| `tradingagents/agents/managers/research_manager.py` | 12-factor z → 8-bucket output 호환 (interface 변경 0) |
| `backtest/historical/bucket_returns.py` | **8 bucket return proxy 새로 fetch** — Tier 2 의존 |
| `tests/unit/skills/research/test_factor_to_bucket.py` | 8-bucket fixtures, row sum tests |
| `tests/integration/test_factor_model.py` | end-to-end 8-bucket 검증 |

---

## 13. Out of Scope (deferred to other tiers)

- **β calibration**: Tier 2 spec (12×8 prior는 본 spec에서 정의, fit는 T2)
- **Bucket family for hierarchical prior**: Tier 2 spec
- **Hard zero cells (~25)**: Tier 2 spec
- **8-bucket historical return time series 구축**: Tier 2 spec의 calibration data prep
- **LLM bucket view delta** (8 bucket): Tier 3 spec

---

**Next:** Tier 2 spec (calibration framework).
