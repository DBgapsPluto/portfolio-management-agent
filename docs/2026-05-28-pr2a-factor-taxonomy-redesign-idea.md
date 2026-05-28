# [PR2a 핸드오프] Stage 2 재설계 풀 스펙 — Tier 1·2·3

- **작성일:** 2026-05-28
- **대상:** PR2a(factor model β calibration) 담당자 + Stage 2 후속 구현자
- **목적:** Stage 2의 두 구조적 병목(보수성, coarse 버킷)과 그 확장(실측 calibration, LLM 오버레이)을 **이 문서만으로 구현 가능**하도록 전 tier를 명세.
- **구성:** Tier 1(버킷 재설계+baseline) → Tier 2(실측 calibration) → Tier 3(LLM 오버레이). 각 tier는 독립 구현 가능하며 1→2→3 순서 의존.

> **정직한 한계:** Tier 1·2는 이 문서로 결정적으로 구현 가능. **Tier 3(LLM)은 인터페이스·공식·기본값까지 못 박았으나, 최종 BAND·credibility·프롬프트는 실거래(forward) 튜닝이 필수** — 정적 문서로 100% 고정 불가(LLM 비결정성). §5.6 참조.

---

## 0. 한 줄 요약

| Tier | 무엇 | 결과물 |
|---|---|---|
| **1** | factor→bucket 출력을 5→8버킷(경제 driver)으로 재설계 + 중립 baseline 47%→57% 원칙 재앵커 | 새 `BUCKETS/RISK_BUCKETS/INITIAL_BASELINE/INITIAL_BETA` + 연쇄 파일 |
| **2** | 실측 historical 데이터로 8버킷 β 재calibration + **런타임 wiring**(현재 끊김) | calibrated β가 production에 실제 적용 |
| **3** | factor 출력을 prior-anchor로 두고 LLM directional view를 **동적·bounded** 블렌드 | `LLMBucketView` + overlay 모듈 |

---

## 1. 현재 구조 (출발점)

`skills/research/factor_to_bucket.py`:
- **9 factor**(`FACTORS`): F1_growth, F2_inflation, F3_real_rate, F4_term_premium, F5_credit_cycle, F6_krw_regime, F7_equity_vol_regime, F8_valuation, F9_liquidity_regime.
- **5 bucket**(`BUCKETS`): kr_equity, global_equity, fx_commodity, bond, cash_mmf.
- 모델: `bucket = INITIAL_BASELINE + Σ_f clip(β[f,b]·z[f], ±0.10)` → `project_to_mandate_qp`(L2 projection, 위험합 ≤ `MANDATE_RISK_CAP=0.70`).
- `INITIAL_BASELINE`: kr 0.12/gl 0.20/fx 0.15/bond 0.33/cash 0.20 → **위험 0.47**.
- `RISK_BUCKETS=(kr_equity, global_equity, fx_commodity)`. `PER_FACTOR_BUCKET_CONTRIB_CAP=0.10`.
- 호출: `research_manager.py:138` → `apply_factor_model_with_safety(z)` (β 미전달 → `INITIAL_BETA` 기본값).

`skills/research/factor_calibration.py`: `hybrid_calibration`(`L=-Sharpe+shrinkage·‖β-prior‖²+sign_penalty`), `walk_forward`, `aggregate_median_beta`, `simulate_portfolio_returns`(`HistoricalSample.bucket_returns_next` 사용). **현재 synthetic** — Issue #18로 실측 미완 → production β는 hand-coded.

**확인된 끊김(중요):** 런타임은 `INITIAL_BETA`만 쓴다. `coefficient_table.json`(calibration 산출물)을 **읽는 코드가 없다** → calibration이 production에 반영 안 됨. Tier 2가 이 wiring을 닫아야 함.

---

## 2. 풀고자 하는 문제

### A. 보수성 (수익 경쟁 불리)
2026-05-28 산출 위험 **62%**(cap 70%). baseline 47%+약한 tilt가 한계 → 실효천장 ~62-65%. 채권 23% 중 20%가 단기은행채(near-cash) → 실질현금 ≈35%. 3개월 수익률 컷(§7) 통과 어려움. 원인: baseline 47%가 너무 낮음(지배항) + regime_confidence/risk_score 미반영.

### B. coarse 버킷 (신호 흐려짐 + 쏠림)
- `fx_commodity` 한 칸에 금(실질금리−·안전자산)·원유(성장·인플레+)가 섞임 → **부호 반대 노출이 평균돼 신호 사망**.
- `bond` 한 칸에 듀레이션/신용/현금성 혼재 → near-cash가 듀레이션 둔갑, 실질 방어축 부재.

### C. (Tier 3 동기) macro news 미반영
factor는 backward-looking. 이란 전쟁·외국인 순유출 같은 *개방형 인과*는 고정 factor로 인코딩 불가 → LLM 필요. 단 LLM 단독·고정 1:1은 위험(§5, Gemini 근거 §6).

> 버킷 *내부* 종목 쏠림(AI전력 10%, 단기은행채 20%)은 Stage 3 min-vol + 죽은 cluster cap이 직접 원인 → **본 문서 범위 밖**(§8). taxonomy 분리는 sub-제약 전파로 *완화*만.

---

## 3. Tier 1 — 버킷 8개 재설계 + baseline 재앵커

### 3.1 버킷 정의 (8개)

| 버킷 | 매핑(category / sub_category) | 위험/안전 | driver |
|---|---|---|---|
| `kr_equity` | 국내주식_지수, 국내주식_섹터 | 위험 | KR 성장/밸류 |
| `global_equity` | 해외주식_지수, 해외주식_섹터 | 위험 | 글로벌 성장 |
| `precious_metals` | (FX·원자재) ∩ {gold, silver_precious, broad_commodity} | 위험 | 실질금리(−)·안전자산(+) |
| `cyclical_commodity_fx` | (FX·원자재) ∩ {oil_energy, agricultural, usd_fx} | 위험 | 성장·인플레(+)·경기성 |
| `kr_bond` | 국내채권_종합 | 안전 | KR 듀레이션 |
| `credit` | 국내채권_회사채, 해외채권_회사채 | 안전 | 신용 cycle |
| `global_duration` | 해외채권_종합 | 안전 | 글로벌 듀레이션/안전자산 |
| `cash_mmf` | 금리연계형/초단기채권 | 안전 | 현금성 |

- `RISK_BUCKETS = (kr_equity, global_equity, precious_metals, cyclical_commodity_fx)` — 합 ≤ 0.70(mandate).
- 8개인 이유: universe의 FX·원자재가 7종뿐(≥1,000억 기준 금·은·원유·금현물) → fx 독립 불가, precious vs cyclical **2분할**이 한계.
- investability(≥1,000억): kr_eq~15, gl_eq~20, precious 3, cyclical 1~2, kr_bond 8, credit ~7, global_duration 8, cash 8. → cyclical만 얇음(target 작아 무해).

### 3.2 baseline (원칙 prior, 중립 위험 57%)

```python
INITIAL_BASELINE = {
    "kr_equity": 0.13, "global_equity": 0.25,
    "precious_metals": 0.10, "cyclical_commodity_fx": 0.09,   # 위험 합 0.57
    "kr_bond": 0.09, "credit": 0.08, "global_duration": 0.14, "cash_mmf": 0.12,  # 안전 0.43
}  # Σ=1.0
```
- 원칙: 글로벌>국내, 안전측에 실질 듀레이션(global_duration 0.14) 확보(충격 convexity).
- **⚠️ baseline(절편)은 backtest-fit 금지** — 절편을 Sharpe 최대화하면 표본의 무조건부 배분을 외우는 최악 과적합. baseline은 전략 prior로 손설정, calibration은 **β만** 움직임.

### 3.3 INITIAL_BETA (9 factor × 8 bucket) — 시작 prior

factor 부호: F1 +성장, F2 +인플레, F3 +고실질금리, F4 +가파른커브, F5 **+신용스트레스**, F6 +약한KRW, F7 +고변동, F8 +고평가, F9 +유동성스트레스.

| factor＼bucket | kr_eq | gl_eq | precious | cyclical | kr_bond | credit | gl_dur | cash |
|---|--|--|--|--|--|--|--|--|
| F1_growth | +0.05 | +0.06 | −0.01 | +0.03 | −0.04 | +0.02 | −0.05 | −0.06 |
| F2_inflation | −0.02 | −0.03 | +0.03 | +0.05 | −0.02 | −0.01 | −0.02 | +0.02 |
| F3_real_rate | −0.01 | −0.02 | −0.04 | 0.00 | −0.03 | 0.00 | −0.03 | +0.13 |
| F4_term_premium | +0.02 | +0.03 | 0.00 | 0.00 | +0.03 | +0.01 | +0.03 | −0.12 |
| F5_credit_cycle | −0.05 | −0.06 | +0.02 | 0.00 | +0.01 | −0.06 | +0.04 | +0.10 |
| F6_krw_regime | −0.05 | +0.05 | +0.02 | +0.02 | −0.01 | 0.00 | +0.01 | −0.04 |
| F7_equity_vol | −0.05 | −0.06 | +0.03 | −0.03 | +0.03 | −0.02 | +0.06 | +0.04 |
| F8_valuation | −0.04 | −0.05 | +0.01 | +0.01 | +0.02 | +0.01 | +0.02 | +0.02 |
| F9_liquidity | −0.04 | −0.05 | −0.02 | −0.02 | +0.03 | −0.02 | +0.02 | +0.10 |

- **각 행 합 = 0**(총량 보존, 기존 설계 invariant). 위 표는 합 0으로 맞춰져 있으나, 코드화 후 `assert abs(sum(row))<1e-9`로 검증할 것.
- 핵심 차별: `precious_metals`(F3 −0.04, F7 **+0.03** 방어) vs `cyclical`(F1 +0.03, F7 **−0.03** 경기성) — 부호 반대 → 분리가 신호를 살림. `credit`(F5 −0.06 위험성) vs `global_duration`(F7 +0.06 안전자산) 도 동일.
- `SIGN_RESTRICTION`: 위 표의 강한 부호(|β|≥0.03)를 sign 제약으로 등록(특히 F1 eq +, F3 precious −, F5 credit −, F7 gl_dur +).
- **이 표는 시작 prior** — Tier 2 calibration이 magnitude 조정.

### 3.4 bond_tips_share 처리
현재 `INITIAL_TIPS_BASELINE/BETA`(factor 모델의 bond 내 TIPS 비율) → **새 taxonomy에선 retire**. TIPS(inflation_linked sub_category)는 `kr_bond`/`global_duration` 내부 sub_category 선호로 candidate_selector가 처리(기존 `_RELAXED_MIN_AUM` 메커니즘 재사용). `BucketTarget.bond_tips_share`와 Stage 3 `_select_bond_with_tips_quota`는 제거/단순화(Stage 3 변경 — §8 조율).

### 3.5 연쇄 파일 (Tier 1)
| 파일 | 변경 |
|---|---|
| `skills/research/factor_to_bucket.py` | `BUCKETS`(8), `RISK_BUCKETS`(4), `INITIAL_BASELINE`(§3.2), `INITIAL_BETA`(§3.3), `SIGN_RESTRICTION`. `INITIAL_TIPS_*`·tips 분기 제거. `project_to_mandate_qp`의 risk_indices가 4 위험버킷. |
| `schemas/portfolio.py` | `BucketTarget` 8필드. `risk_asset_weight` property = 4 위험버킷 합. `bond_tips_share` 제거. |
| `agents/managers/research_manager.py` | 8필드 `BucketTarget` 생성(`:157`). |
| `skills/portfolio/candidate_selector.py` | `BUCKET_TO_CATEGORIES` → **(category, sub_category) 필터** 지원(precious/cyclical 분리에 필수). `min_aum_krw` 기본 1조→**1,000억**. |
| `agents/allocator/portfolio_allocator.py` | sector_mapper 8섹터. tips split 분기 제거. |
| tests | 8버킷 invariant(β 행합 0, baseline 합 1, 위험합), 매핑 테스트. |

### 3.6 테스트(Tier 1 수용 기준)
- `sum(INITIAL_BASELINE.values()) == 1.0`, 위험합 == 0.57(±1e-9).
- 모든 factor 행 `sum(β[f,:]) == 0`(±1e-9).
- `apply_factor_model(zeros)` == `INITIAL_BASELINE`.
- `project_to_mandate_qp`: 위험 4버킷 합 ≤ 0.70 보장.
- 각 버킷에 ≥1 investable ETF(≥1,000억; cyclical은 relaxed AUM 허용).

---

## 4. Tier 2 — 실측 calibration + 런타임 wiring

### 4.1 목표
8버킷 β를 **실측 historical**로 walk-forward Sharpe calibration(Issue #18) + **calibrated β를 런타임에 실제 적용**(현재 끊김).

### 4.2 데이터 fetch (`factor_calibration.load_historical_data` — synthetic fallback 제거)
- **Factor 입력(분기, 1991~현재 가능 범위):** FRED(CPI, GDP/nowcast, NFCI, CFNAI, 2y/10y/30y, TIPS breakeven, fed funds, HY OAS) · yfinance(^GSPC, ^KS11, GC=F, SI=F, CL=F, DX-Y.NYB, IEF/TLT, ^IRX) · pykrx(외국인 순매수, KRW REER) → 분기별 9 factor z.
- **버킷 익분기 수익(`bucket_returns_next`, 8개) — 대표 바스켓:**
  | 버킷 | proxy(분기 총수익) |
  |---|---|
  | kr_equity | KOSPI/KOSPI200 TR |
  | global_equity | S&P500(또는 ACWI) TR |
  | precious_metals | 0.6·gold + 0.4·silver |
  | cyclical_commodity_fx | 0.6·WTI + 0.2·agri + 0.2·USD index |
  | kr_bond | KR 10y 국채 TR(수익률→가격) |
  | credit | KR IG 회사채(또는 US IG) TR |
  | global_duration | US 10-30y 국채 TR(TLT류) |
  | cash_mmf | KR CD/콜금리 accrual |
  - **원칙: proxy가 Stage 3 실현과 가깝게.** 기존엔 "bond=종합채"로 calib했으나 실제 near-cash 실현 → β가 반사실에 fit. 새 taxonomy(credit/duration/cash 분리)가 이 mismatch 해소.

### 4.3 calibration 파이프라인
1. `walk_forward(samples, shrinkage_grid=[0.1,0.3,0.5,0.7,1.0], prior=INITIAL_BETA(§3.3))`.
2. shrinkage별 median OOS Sharpe → 최대 선택.
3. `aggregate_median_beta(folds)` → `coefficient_table.json`.
4. `validation_report.md` 생성.
5. **acceptance(D5 유지):** OOS Sharpe > 직전 framework +0.05 AND ≥ 60/40 벤치마크.
6. **런타임 wiring(끊김 닫기):** acceptance PASS 시 — (a) `coefficient_table.json`을 `research_manager`가 로드해 `apply_factor_model_with_safety(z, beta=loaded)`로 주입, 또는 (b) `INITIAL_BETA` 상수를 calibrated 값으로 교체. **반드시 둘 중 하나로 production 반영**(현재는 어느 것도 안 됨).

### 4.4 과적합 통제 (데이터 floor 대응)
8버킷×9factor=72칸을 자유추정 금지:
1. **계층적/부분 풀링**: duration 그룹(kr_bond, global_duration)은 공통 "duration" β + 지역 편차; equity 그룹(kr_eq, gl_eq)도 공통+편차. → 유효 자유도 ↓.
2. sign 제약 + shrinkage(이미 있음), 경제 자명 칸은 pin(precious F1≈0).
3. **OOS 모델선택**: nested walk-forward로 *8버킷이 5버킷 대비 OOS Sharpe 개선 시에만* 8버킷 채택. 미개선 sub-bucket은 병합.
4. 데이터 적은 칸은 prior 지배 수용(자유추정 금지).

### 4.5 cadence
6개월 재calibration(Issue #19 정렬). `AUDIT_DATE`/`COMPONENT_RELIABILITY` 동반 갱신.

### 4.6 테스트(Tier 2 수용 기준)
- synthetic fallback 제거 후 실측 fetch 성공(캐시 포함).
- walk_forward fold ≥ 6, acceptance 자동 판정.
- **런타임이 calibrated β 사용함을 검증하는 통합 테스트**(현재 끊김 회귀 방지).

---

## 5. Tier 3 — LLM 동적-가중 view 오버레이

### 5.1 아키텍처 (weight-space, 비-BL, 비-고정)
```
factor model(8버킷 quant target) ──anchor/prior──┐
                                                  ▼
Stage1 macro_news/report → LLM → directional views(+conf) → 동적 가중 블렌드 → re-project → Stage3
```
- quant 출력이 **닻**(TrustTrade deterministic anchoring). LLM은 **방향성 view**만(simplex 벡터 강제 금지 — LLM 산술 약점 회피, Gemini multimodal 근거 §6).
- 블렌드는 **weight space**(둘 다 가중 출력). Black-Litterman 아님(BL은 기대수익+공분산 필요 → 시스템에 없음).

### 5.2 view 스키마 (신규 `schemas/research.py`)
```python
class LLMBucketView(BaseModel):
    bucket: str            # BUCKETS 중 하나
    delta: float           # 제안 편차(pp, 예 +0.05 = +5pp), 부호 방향
    confidence: float      # 0..1 (자기보고 — 단독 신뢰 금지, §5.4)
    rationale: str         # 근거(철학 점수용 로깅)
    sources: list[str]     # 인용 출처(credibility 채점용)
```
LLM은 *뷰가 있는 버킷만* 출력(나머지 침묵 → delta 0). 출력은 구조화 JSON.

### 5.3 블렌드 공식
```
for b in BUCKETS:
    dev_b = clip(w_LLM * view.confidence_b * view.delta_b, -BAND, +BAND)
    blended_b = quant_b + dev_b
final = project_to_mandate_qp(normalize(blended))   # 합=1, 위험≤0.70 재투영
```
- `BAND` = 버킷당 최대 편차(blast radius cap). **기본 0.05(5pp)** — 검증 불가 레이어라 작게.
- `w_LLM ∈ [0,1]` = 동적 가중(§5.4).

### 5.4 w_LLM = novelty × consensus × credibility (self-confidence 단독 금지)
| 신호 | 정의 | 측정 |
|---|---|---|
| **novelty** | 오늘 뉴스의 이상 salience | 매크로/지정학 뉴스 volume z-score(trailing 대비), clip[0,1]. *과거 재구성 가능 → backtestable proxy.* |
| **consensus** | view 신뢰도 | LLM K회(예 3) 샘플 방향 일치 비율 + 출처 credibility(TrustTrade Selective Consensus). clip[0,1]. |
| **credibility** | 누적 실적 | reflective memory의 과거 view 적중 EWMA. **cold-start init 0.3(보수)**. clip[0,1]. |

`w_LLM = novelty * consensus * credibility`. → 조용한 주 novelty≈0 → 영향 0; 이란 전쟁+일치+실적 → ↑.

### 5.5 reflective memory & test-time adaptation
- 로그(파일/DB): `(date, bucket, delta, confidence, realized_next_period_bucket_return, hit?)`.
- credibility EWMA 갱신: 적중 시 ↑, drawdown 유발 logic ↓(재학습 없이). → TrustTrade Reflective Memory.

### 5.6 backtestability & 정직한 한계
- LLM 레이어는 **walk-forward 불가**(look-ahead: LLM이 사후 사건 앎). → quant 코어(Tier 1-2)만 backtest, LLM은 (a) BAND cap, (b) forward/paper에서 quant-only vs quant+overlay 비교, (c) 전수 로깅, (d) ablation으로 검증.
- **3개월 horizon → credibility 미성숙.** 시작 `BAND=0.05`, credibility init 0.3, 기간 내 제한 적응만.
- **이 tier는 정적 문서로 100% 고정 불가** — BAND·K·EWMA계수·프롬프트는 실거래 튜닝. 문서는 인터페이스/공식/기본값까지.

### 5.7 연쇄 파일 (Tier 3)
| 파일 | 변경 |
|---|---|
| `schemas/research.py` | `LLMBucketView`. |
| `skills/research/llm_view_overlay.py`(신규) | `generate_views(stage1)`, `blend_weight(novelty,consensus,credibility)`, `apply_overlay(quant_target, views)→BucketTarget`. |
| `skills/research/reflective_memory.py`(신규) | view/outcome 로그 + credibility EWMA. |
| `agents/managers/research_manager.py` | quant target 후 overlay 적용(있을 때만). |
| 프롬프트 | quant 8버킷 target + 결정적 지표 제시 + "근거 있을 때만 deviation, 출처 인용" 지시 + JSON 출력. |

### 5.8 테스트(Tier 3 수용 기준)
- overlay OFF == quant 그대로(회귀).
- novelty 0 → w_LLM 0 → quant 동일.
- BAND 초과 deviation 불가(clip 검증).
- re-project 후 위험 ≤0.70, 합=1.
- credibility EWMA 갱신 단위 테스트.

### 5.9 구현 스케치 (프롬프트 + novelty + overlay)

> 모두 *시작 스케치*. 필드명은 실제 스키마에 맞추고, `BAND/alpha/K`·프롬프트는 forward 튜닝.

**(a) LLM 프롬프트 초안**

*system:*
```
너는 거시 전략가다. quant 모델의 8버킷 중립목표(anchor) + 결정적 시장지표 + 최신 뉴스요약을 받는다.
임무: quant가 놓쳤을 forward-looking 정보(지정학·정책·자금흐름)가 있을 때만 특정 버킷을
어느 방향으로 얼마나 조정할지 제안한다.
규칙:
- 뷰 있는 버킷만 출력(근거 없으면 침묵).
- 너는 편차(delta, pp)와 방향만 제안. 최종 비중·정규화·제약은 시스템이 한다(산술 금지).
- 모든 뷰에 rationale + sources. 출처 없으면 confidence를 낮춰라.
- |delta| ≤ 0.08, confidence ∈ [0,1].
- 버킷: kr_equity, global_equity, precious_metals, cyclical_commodity_fx,
        kr_bond, credit, global_duration, cash_mmf.
- 출력은 JSON list만, 그 외 텍스트 금지.
```
*user(템플릿):*
```
[Quant anchor]  {bucket: weight, ...}
[결정적 지표]   regime/conf, VIX, 10y-2y, CPI, HY OAS, PCA1st, 예정 이벤트 ...
[뉴스 요약]     {Stage1 macro_news 구조화 필드 + 상위 headline}

→ LLMBucketView list(JSON) 출력. 스키마: [{"bucket","delta","confidence","rationale","sources"}]
```

**(b) novelty 측정** (이상 뉴스 salience → [0,1], backtestable proxy)
```python
def compute_novelty(news_report, window=60) -> float:
    today = news_report.macro_salience_score              # Stage1 macro_news 구조화 필드
    hist  = news_report.macro_salience_history[-window:]   # trailing 시계열
    if len(hist) < 10:
        return 0.0
    mu, sd = mean(hist), (std(hist) or 1e-9)
    z = (today - mu) / sd
    return clip(z / 3.0, 0.0, 1.0)                         # 3σ 포화
# Stage1 macro_news에 salience_score/history 구조화 필드 추가 필요.
# 없으면 (고중요도 기사 수 × 평균 surprise) 또는 event_count로 대체.
```

**(c) consensus / credibility / overlay** (요지)
```python
def compute_consensus(view_samples) -> dict[str, float]:
    """LLM K회(예 3) 샘플 → 버킷별 방향 일치도 [0,1]."""
    out = {}
    for b in BUCKETS:
        signs = [sign(s[b].delta) for s in view_samples if b in s]
        out[b] = 0.0 if not signs else abs(sum(signs)) / len(signs)
    return out

def update_credibility(cred, bucket, predicted_delta, realized_ret, alpha=0.1):
    """EWMA: 예측 방향·실현수익 동부호 시 ↑. init 0.3(보수)."""
    hit = 1.0 if predicted_delta * realized_ret > 0 else 0.0
    cred[bucket] = (1 - alpha) * cred.get(bucket, 0.3) + alpha * hit
    return cred

def apply_overlay(quant, views, novelty, consensus, credibility, BAND=0.05):
    blended = dict(quant)
    for v in views:
        w   = novelty * consensus.get(v.bucket, 0.0) * credibility.get(v.bucket, 0.3)
        dev = clip(w * v.confidence * v.delta, -BAND, +BAND)   # blast radius cap
        blended[v.bucket] = quant[v.bucket] + dev
    return project_to_mandate_qp(normalize(blended))           # 합=1, 위험≤0.70 재투영
```

---

## 6. regime_confidence / risk_score (전 tier 공통)
- **regime_confidence를 β tilt 스케일러로 쓰지 말 것** — 이산 regime 라벨 확신도이지 factor 신호 강도 아님(범주 오류). "불확실 시 중립 shrink"는 `factor_reliability_audit`(데이터 품질)로. regime_confidence는 regime 라벨 소비처(`factor_scorer.blend_regime_weights`)에만.
- **risk_score 고정 threshold 금지**(calibration 파라미터 증가 + cliff; Gemini의 stat-arb fixed→dynamic threshold 근거 §6). 쓴다면 연속·percentile shrinkage 강도로. **이중계산 주의**(VIX/credit/liquidity = F5/F7/F9 중복) → orthogonal 입증 전엔 추가 입력 금지.

---

## 7. Gemini Deep Research 근거 (`docs/퀀트 트레이딩 알고리즘 및 LLM 활용.docx`)
| 근거 | 적용 |
|---|---|
| 하이브리드 "황금비"(통계 50-60% > LLM 30-40% > 융합) | quant factor가 백본 → Tier 1-2 정교화가 우선, LLM은 융합 레이어(Tier 3). |
| A-C-A: LLM=전략가(거시 방향), 수치는 수학 위임 | β/baseline은 결정적 quant(Tier 1-2), LLM은 directional view(Tier 3.2). |
| multimodal: 수치를 텍스트로 넣으면 산술 약점 → 인코더 분리 | LLM에 simplex 벡터 강제 금지(§5.1-5.2). |
| dynamic thresholding(stat-arb) | risk_score 고정 threshold 금지(§6). |
| TrustTrade(anchoring·selective consensus·reflective memory) | §5.1 닻, §5.4 consensus, §5.5 memory. |
| Man Group(LLM 외삽·과잉반응) / uniform-trust 편향 | LLM bounded(BAND)·credibility 가중(§5.3-5.4), 단독 위임 금지. |
| LLM-driven alpha/factor mining | §3.3 factor/버킷 설계 보조 가능(단 IC/OOS 검증). |

---

## 8. 대회 제약 (DB GAPS, `docs/DB_GAPS_Investment_Tournament_Rules.md`)
- 운용 6/1~8/31(3개월). 평가 = 수익률 컷(상위 30) → 수익 30 + **철학 70**(상관 기반 단일리스크 통제=AI 쏠림 명시 채점).
- 위험자산 ≤70%(위험 4버킷 합), 종목당 ≤20%, 안전 무제한.
- 회전율 하한(셋업 ≥80%, 월 ≥10%) — philosophy.md "턴오버 최소화"와 모순, 별도 점검.
- 자본 10억 → AUM 필터 1조→1,000억 근거(§3.5).

---

## 9. 범위 경계 / 순서 / 조율
**본 문서 범위:** Tier 1(factor→8버킷+baseline), Tier 2(실측 calib+wiring), Tier 3(LLM overlay).
**범위 밖(별도 작업):**
| 항목 | 담당 | 비고 |
|---|---|---|
| 버킷 내부 min-vol 가중 | Stage 3 | "risk_parity"가 실은 min_volatility → 쏠림. |
| cluster cap 부활(AP1) | Stage 3-4 | 죽은 `pass`. 철학 70% 간판 → **다음 우선**. |
| AUM 필터 하향 | Stage 3 candidate_selector | Tier 1 feasibility 전제 → 같이. |

**순서:** Tier 1 → 2 → 3 (의존). Tier 3는 1·2 검증 후.
**조율(내일 미팅):** ① 5→8버킷 reshape vs PR2a 5버킷 calib 충돌 순서/소유권. ② AUM 필터. ③ bucket_returns_next proxy 정의·fetch 범위. ④ baseline 57% risk appetite 합의. ⑤ partial-pooling 범위.

---

## 10. 구현 체크리스트
**Tier 1:** `BUCKETS/RISK_BUCKETS/INITIAL_BASELINE/INITIAL_BETA/SIGN_RESTRICTION` 교체 → tips 제거 → `BucketTarget` 8필드 → `BUCKET_TO_CATEGORIES` sub_category 필터 + min_aum 1,000억 → sector_mapper 8 → 테스트(§3.6).
**Tier 2:** `load_historical_data` 실측 → bucket_returns_next 8 proxy → walk_forward+grid → coefficient_table → acceptance → **런타임 wiring** → 통합테스트(§4.6).
**Tier 3:** `LLMBucketView` → `llm_view_overlay`(generate/blend/apply) → `reflective_memory` → research_manager 통합 → 프롬프트 → 테스트(§5.8). BAND/credibility는 forward 튜닝.

---

## 부록 — 현재 vs 제안
| | 현재 | 제안 |
|---|---|---|
| 버킷 | 5(fx·bond 혼재) | 8(driver 분리) |
| 중립 위험 | 47% | 57%(원칙) |
| β | hand-coded, synthetic calib, **런타임 미반영** | 8버킷 실측 calib + **wiring** |
| 원자재/채권 | 1칸씩 | precious/cyclical, kr_bond/credit/global_duration/cash |
| news | factor 입력만 | Tier 3 LLM bounded overlay |
| regime_conf/risk_score | 미사용 | β tilt 금지 / 고정 threshold 금지 |
