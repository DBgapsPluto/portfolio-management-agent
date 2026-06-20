# Black-Litterman 버킷 배분 전환 — 설계 (rev0)

> **상태:** 설계 승인 → 적대적 감사 대기.
> **대체:** `origin/feat/bl-allocator` 의 `2026-06-09-bl-allocator-design.md` (옛/삭제 아키텍처 기준). 본 문서가 현행 14-bucket·`trader_allocator` 기준의 정본.
> **선행 sub-project:** ETF-선택 하이브리드(`2026-06-16-etf-selection-hybrid-design.md`, rev3) — *먼저* 출시. 본 BL은 그 위에 버킷 배분층을 교체.
> **브랜치:** `rework/pipeline-methodology`. 테스트: repo `.venv` py3.13, `PYTHONUTF8=1`.

---

## 1. 목적 · 비목적

**목적.** Stage 3 `trader_allocator`의 **Step A(14버킷 비중 결정)** 를, 현행 "quadrant 앵커 baseline + LLM weight-tilt → 밴드 투영(`project_to_band`)" 방식에서 **Black-Litterman**으로 교체한다:

- prior = regime baseline의 reverse-optimization (`Π = δ·Σ·w_baseline`),
- view = LLM의 **버킷 상대순위**(He-Litterman 상대 view) + fx/credit 결정론 view,
- 결합 → `max_quadratic_utility(μ_BL, Σ_p, δ)` → 버킷 비중.

목표 맥락: DB GAPS 대회(2026.6–8, 3개월)에서 **수익 순위 top-30**(30% 배점)을 노리되 **철학 점수**(70% 배점, "AI 쏠림 통제" 포함)를 방어. BL은 *엄밀한 방법론 서사*(철학)와 *공격적 view를 통한 수익 틸트*를 동시에 제공한다.

**비목적.**
- Step B(개별 ETF 선택)·repair·Stage 5/6은 건드리지 않는다. (BL은 Step A 국소 교체.)
- 20년 장기 backtest로 baseline의 Sharpe 우위를 증명하는 것은 **본 출시의 차단요건이 아니다** (§7 게이트1 참조, 비차단 후속).
- 일간 오버레이는 별도 결정(vol cap 제거, mandate-drift only)이며 본 문서 범위 밖. BL 출력은 그 오버레이로 흘러간다.

---

## 2. 핵심 결정 (5)

| # | 결정 | 선택 | 근거 |
|---|---|---|---|
| D1 | backtest STOP 게이트 무게 | **C — 하이브리드** | 싼 게이트2(LLM·proxy 불필요)만 차단 게이트로 유지. 무거운 20년 게이트1은 *목적(3개월 수익순위)과 어긋나는 20년 Sharpe 검증*이라 비차단 후속으로 격하. 과거 BL 실패를 거르는 안전장치는 싸게 보존. |
| D2 | LLM view 형식 | **B — 상대순위 view** | weight-tilt view는 BL을 현행 코드와 동일하게 만들어 무의미(Σ가 일 안 함). 절대 수익 view는 LLM의 약점(레벨추정)+과거 폭주 형태. 상대순위는 LLM 강점(순서)·레벨앵커 회피·He-Litterman 정통·철학 서사 최강. 기존 spec §7(절대 view) 의도적 기각. |
| D3 | Σ(14×14 공분산) 소스 | **A — 최근윈도 proxy + LW수축** | 20년을 미뤘으므로 BL이 필요로 하는 Σ를 최근 ~2–3년 proxy + Ledoit-Wolf 수축으로 공급(월간 롤링). §12.1 proxy 매핑은 *짧은 윈도우*라 장기 가용성 늪 회피. |
| D4 | BL 이동 자유도 | **A — mandate+자가캡만, δ 다이얼** | baseline±band(옛 거버너) 제거. BL은 진짜 리스크모델(Σ)+최적화(δ·분산)라는 내재 거버너를 가짐 — band를 얹으면 둘이 싸워 공격성을 잘라 top-30 도달 난망. 방어성은 prior(=baseline)가 담고(view 약하면 사후≈prior), 집중통제는 ETF층 캡(35% 클러스터/카테고리, 단일≤20%)이 담당. |
| D5 | 도입 방식 | **2 — 병렬모듈+분기** | 신규 BL 모듈 + `trader_allocator` 플래그 분기. 게이트2(BL vs 현행 비교)가 두 경로 공존을 *요구*. 가역적. 통과 후 정리 Phase에서 옛 경로 삭제. |

---

## 3. 아키텍처 & 데이터 흐름 (월간 경로)

```
Stage 1/2 (analysts→research): regime.quadrant(결정론) + 매크로/뉴스 컨텍스트
        ▼
┌─ Stage 3 · Step A : 버킷 비중 (BL) ────────────────────────────┐
│  QUADRANT_BASELINE[quadrant] ─► w_baseline (prior 비중)         │
│  bucket_proxies(최근2~3y) ─► bucket_cov(LW수축,연환산) ─► Σ      │
│            reverse-opt:  Π = δ · Σ · w_baseline                │
│                                                                │
│  [통합 Step-A LLM 1콜]                                          │
│   ├ bucket_ranking (14버킷 tier+conviction) ─► (P,Q,Ω) Idzorek │
│   └ sub_category_views ──────┐  (ETF-선택 필드)                 │
│  fx/credit 결정론 view ───────┼─► (P,Q,Ω) 추가행               │
│                              │                                 │
│                              ▼  μ_BL = BL결합(Π,Σ,τ,P,Q,Ω)     │
│                              max_quadratic_utility(μ_BL,Σ_p,δ; │
│                                박스 w≥0, Σw=1, GROWTH합≤0.70)  │
│                              ▼  bucket_target(14)              │
│                    _clamp_to_pool_capacity (불변 유지)         │
│   ┌──────────────────────────┘                                 │
│   ▼ sub_category_views (BL과 직교 — ETF층 직행)                 │
└────┼───────────────────────────────────────────────────────────┘
     ▼ Step B: candidate_selector(이질분기) → within_bucket (M3/M4, ETF-선택)
     ▼ ETF 비중
  repair: cluster_repair(35%) · single≤20% · repair_risk_cap(RISK_BUCKET_NAMES,≤70%)
     ▼  Stage 5 validator(하드 백스톱) → Stage 6 PM
```

**핵심 불변식 (D4가 안전한 이유).** view=∅ 이면 `μ_BL = Π = δ·Σ·w_baseline`, 그리고
`max_quadratic_utility(Π, Σ, δ) = argmax_w (wᵀΠ − ½δ·wᵀΣw)` 의 무제약 해는
`w* = (1/δ)Σ⁻¹Π = (1/δ)Σ⁻¹·δΣ·w_baseline = w_baseline`. 즉 **band 없이도 view가 약하면
사후 비중이 baseline을 *정확복원*** 하고, view가 강할 때만 멀어진다. (baseline은 모든
quadrant에서 GROWTH합 ≤0.70 — 예: growth_disinflation 0.63 — 이라 그룹제약이 slack →
정확복원 보존.)

**모듈 맵 (D5 병렬+분기).**

| 파일 | 책임 | 신규/수정 |
|---|---|---|
| `tradingagents/backtest/bucket_proxies.py` | §12.1 교정 proxy 맵 + 최근윈도 일별수익 fetch | **신규** |
| `tradingagents/skills/portfolio/bucket_cov.py` | LW 수축 → 연환산 14×14 Σ (PD 보장) | **신규** |
| `tradingagents/skills/portfolio/bl_engine.py` | Π 역산 · 상대view→(P,Q,Ω) · BL결합 · MQU 최적화 | **신규** |
| `tradingagents/schemas/portfolio.py` | `BucketTilt`에 `bucket_ranking` 추가(`sub_category_views`는 ETF-선택이 추가, `tilts`는 정리Phase 제거) | 수정 |
| `tradingagents/agents/trader/trader_allocator.py` | Step-A 프롬프트(상대순위) · 옛/신 분기 플래그 · BL 배선 · vol_haircut 우회 | 수정 |
| `tradingagents/skills/portfolio/scenario_anchor.py` | `QUADRANT_BASELINE` 유지(prior소스); tilt수학(`project_to_band`/`apply_macro_modifiers`/`_risk_tilt_delta`)은 정리Phase 제거 | 수정 |
| `scripts/backtest_bl_gate2.py` | 게이트2: BL(고정view) sanity + 현행 비중 L1 비교 + δ·base_spread 보정 | **신규** |

---

## 4. Σ 인프라 (Phase A)

### 4.1 proxy 맵 (§12.1 교정 — 옵션 A)

각 버킷의 *대표 자산*을 1개 시계열로 대리한다. 짧은 윈도우(최근 2–3년)라 아래 전 티커 가용.

| 버킷 | proxy | 소스 | 통화 |
|---|---|---|---|
| a1_cash | 단기금리 level/12 (분산 floor 처리) | FRED DGS3MO / KR 콜금리 | — |
| a2_kr_rates | KR 국채 (KOSEF 국고채10년 148070, 또는 KR10Y yield→듀레이션 price proxy) | KRX/ECOS | KRW |
| a3_us_rates | US 중기국채 (IEF 7–10Y) | yfinance | USD |
| a4_safe_fx | 안전통화 (DXY, 또는 USDJPY) | yfinance | — |
| a5_gold_infl | 금 (GLD) | yfinance | USD |
| b1_kr_equity | KOSPI200 (^KS200, 또는 EWY) | yfinance | KRW |
| b2_dm_core | 선진 코어 (URTH MSCI World) | yfinance | USD |
| b3_global_tech | 나스닥100 (QQQ) | yfinance | USD |
| b4_china | 중국 (MCHI) | yfinance | USD |
| b5_other_intl | 기타 해외/EM (EEM) | yfinance | USD |
| b6_defensive_equity | 저변동 (SPLV) | yfinance | USD |
| b7_reits | 리츠 (VNQ) | yfinance | USD |
| b8_cyclical_commodity | 원자재 (DBC, 또는 XLE) | yfinance | USD |
| b9_risk_credit | 하이일드 (HYG) | yfinance | USD |

**통화 처리(결정):** proxy 수익을 *native 통화*(글로벌=USD, 국내=KRW)로 계산하고 그 위에서 공분산을 구한다. 글로벌 버킷에 USDKRW를 *주입하지 않는다* — FX는 별도 `a4_safe_fx` view로 다루므로 주입하면 이중계상. (Phase A에서 검증; 이중계상 vs KRW투자자 실현수익의 트레이드오프는 §10 미해결 항목.)

**a1_cash 특례:** 단기금리 수익은 분산≈0 → Σ 특이(singular)·MQU 폭주 위험. 분산에 작은 floor(예: MMF 변동성 ~0.5%/년)를 주고 LW 수축으로 PD 보장. **`fillna(0.0)` 금지** — 0 채움은 σ≈0 위조(원 plan must_fix).

### 4.2 공분산 (`bucket_cov.py`)

최근 윈도(기본 **2년 = 504 거래일**, dial) 일별 native 수익 → Ledoit-Wolf 수축 추정 → **×252 연환산** → 14×14 Σ. PD 보장(수축 + a1 floor). 결측 버킷(가용 데이터 부족)은 에러로 표면화(§6 폴백).

---

## 5. BL 수학 계약 (`bl_engine.py`, lib = PyPortfolioOpt)

> 라이브러리 가용성은 Phase A에서 확인(과거 `bl_views.py` 존재 → pypfopt 의존 추정). 없으면 추가 또는 NumPy 직접 구현(공식이 닫힌형이라 자명).

**(1) Prior 역산.** `Π = δ · Σ · w_baseline`, `w_baseline = QUADRANT_BASELINE[quadrant]`.

**(2) 상대 view 구성 — *결정론적 변환*, LLM은 tier·conviction만.**
- LLM이 14버킷에 **tier** ∈ {strong_OW, OW, neutral, UW, strong_UW} + **conviction** c∈[0,1] 부여.
- 각 비중립 버킷 i → "i가 **동일가중 바스켓**(14버킷 평균) 대비 spread_i 초과수익" 상대 view:
  - `P_i = e_i − (1/N)·1` (zero-sum: `P_i · 1 = 0` ⇒ 정통 상대 view),
  - `Q_i = base_spread · s_i`, `s_i = tier점수 × c` ∈ [−1,+1] (strong_OW=+1, OW=+0.5, neutral=0, UW=−0.5, strong_UW=−1).
  - `base_spread` = 풀컨빅션 연환산 초과수익 상수 = **0.04 (4%/년)** 기본, 게이트2 보정.
- **Ω = Idzorek.** view별 confidence c_i → Ω_ii 역산(고conviction→저Ω→강한 당김). `τ = 0.05` 고정(Idzorek가 τ 민감도 제거).

**(3) fx/credit 결정론 view.** 현 `CREDIT_MODIFIER`/`FX_MODIFIER`의 *의도*를 weight-delta가 아니라 **상대 view**로 재해석해 같은 (P,Q,Ω)에 추가행 투입. 부호=delta 부호, 크기=고정 spread(기본 0.02), confidence=높음(규칙 → 저Ω). 별도 후처리 modifier(`apply_macro_modifiers`) 제거.
  - 예) credit=crisis → "b9_risk_credit UW, a3_us_rates OW" 상대 view; fx=usd_risk_off → "a4_safe_fx OW, b1_kr_equity UW".

**(4) BL 결합.** `μ_BL = [(τΣ)⁻¹ + PᵀΩ⁻¹P]⁻¹ [(τΣ)⁻¹Π + PᵀΩ⁻¹Q]`. 사후공분산 `Σ_p = Σ + [(τΣ)⁻¹ + PᵀΩ⁻¹P]⁻¹` 도 산출해 최적화에 사용(PyPortfolioOpt가 둘 다 반환).

**(5) 최적화.** `max_quadratic_utility(μ_BL, Σ_p, risk_aversion=δ)` + 박스제약:
  - `w_b ≥ 0` (전 버킷),
  - `Σ_b w_b = 1`,
  - `Σ_{b∈GROWTH_KEYS} w_b ≤ 0.70` (선형 그룹제약, **소프트 사전성형** — §5.1 참조).
  → `bucket_target`(14). 이어서 기존 `_clamp_to_pool_capacity`(버킷별 `n_pool×0.20` 용량 clamp + water-fill) 그대로 적용.

**(6) §17 불변식 — 폭주 방지(단위테스트로 잠금).** Π·Q·μ는 전부 **연환산 수익**, Σ는 **연환산**(일별cov×252). 테스트로 `|Π_b| ~ 한자리%대`(≈1e-4 아님) 단언. δ는 **단일 공격성 다이얼**(기본 ~2.5, 게이트2 보정); no-view 시 §3 불변식으로 baseline 정확복원 ⇒ δ는 *view가 있을 때만* 이동폭을 좌우.

### 5.1 위험자산 70% — 이중정의 주의 (감사 오인 방지)

코드에 위험자산 정의가 **둘**이다:
- **트레이더 camp:** `GROWTH_KEYS`(b1–b9, 성장진영). 최적화 그룹제약은 이걸 쓴다 → **소프트 사전성형**.
- **대회 mandate:** `RISK_BUCKET_NAMES`{kr_equity·global_equity·precious_metals·cyclical_commodity_fx}, ETF레벨 `bucket_for_etf`로 측정. **하드 70% 보장은 기존 `repair_risk_cap` + Stage 5 validator가 담당 — BL은 이를 바꾸지 않는다.**

두 정의가 1:1 매핑이 아니므로(예: b6_defensive_equity는 성장camp지만 mandate 위험분류는 다를 수 있음), 최적화 제약은 *근사 사전성형*일 뿐 하드 보장이 아니다. 하드 enforcement는 ETF층의 불변 repair 경로가 책임진다.

---

## 6. 통합 Step-A LLM 계약

한 번의 LLM 콜이 하나의 구조화 객체 출력:

```
BucketTilt (확장):
  bucket_ranking: { <14 bucket_key>: {tier: Literal[...], conviction: float[0,1], rationale: str} }
  sub_category_views: { <bucket>: { <sub_cat>: float } }   # ETF-선택 sub-project가 추가
  tilts: dict[str,float]                                   # 옛 필드 — BL 경로는 무시, 정리Phase 제거
  rationale: str
```

- **스키마 진화 순서:** ① ETF-선택 출시 시 `sub_category_views` 추가(옛 `tilts`/`project_to_band` 위), ② BL Phase C에서 `bucket_ranking` 추가(BL 경로가 읽음), ③ BL Phase D 정리에서 `tilts` 제거.
- bucket_ranking·sub_category_views는 *다른 입도·다른 하류*지만 같은 매크로/테마 추론에서 나오므로 1콜이 정합·토큰효율.
- **설계 의도:** LLM은 *상대 순위 + conviction*(강점)만 내고, 수익숫자(Q)·신뢰(Ω)·비중은 코드가 결정론 변환 → "LLM이 절대수익을 지어낸다"는 §17/과거실패 경로를 구조적 차단.
- 프롬프트는 현 `_step_a_prompt`의 입력(thesis·key_risks·Stage1 요약·feedback)을 재사용하되, 출력 지시를 "tilt 가감" → "각 버킷 tier+conviction 순위"로 교체.

---

## 7. 게이트 & 검증

**게이트2 (유지·차단·LLM불필요).** 고정 view 한 세트(예: "b3 strong_OW, a3 strong_UW")를 BL에 투입해 sanity:
- ⓐ b3↑·a3↓ *방향* 정확,
- ⓑ baseline 대비 L1 ≥ ε_min (기본 **0.05**; BL이 inert 아님),
- ⓒ 폭주 없음(최대 버킷 ≤ sanity 천장 **0.30**, §17 재현 안 됨),
- ⓓ view=∅ 시 baseline 정확복원(L1 < 1e-6).
하나라도 실패 → **STOP**, LLM view(Phase C) 전에 δ·base_spread·Σ 재보정·사용자 보고.

**δ·base_spread 보정.** ETF-선택의 경량 backtest 하네스(`scripts/backtest_etf_selection.py` 류)를 *최근 윈도우*로 재사용, δ·base_spread 스윕 → 최근 수익순위 프록시 최대화하되 집중 건전성 유지하는 값. (단기·수익지향 — 대회 목표 정합.)

**게이트1 (지연·비차단).** 결정론 baseline의 20년 backtest vs 벤치마크(60/40·risk parity·1/N)는 spec에 *후속 검증 태스크*로 남기되 대회 출시를 막지 않는다. (SPLV/HYG 등 proxy의 장기 히스토리 제약은 이 후속에서 다룸.)

---

## 8. 폴백 — BL은 파이프라인을 절대 깨지 않는다 (정직한 로깅)

| 실패 | 처리 |
|---|---|
| Σ 비정상(non-PSD/NaN/짧은윈도) | LW+a1 floor로 대부분 교정; 그래도 불량 → **baseline 폴백**(BL 스킵, `bucket_target=w_baseline`), 로그 |
| BL 최적화 infeasible/solver 실패 | **baseline 폴백**, 로그 |
| LLM view 파싱 실패/빈 ranking | view=∅ → baseline 정확복원(불변식). 에러 아님, 안전 강등 |
| 런타임 폭주 가드 | 최적화 후 최대 버킷 > sanity 천장(예 0.30) → **baseline 폴백** + 로그 (제약 위 최후 방어) |
| mandate 위반 | GROWTH합≤70%는 소프트 제약; 하드(RISK_BUCKET_NAMES,단일≤20%,캡)는 하류 repair + Stage5 백스톱 |

폴백 시에도 `allocation_attribution`에 폴백 사유를 남겨 philosophy 리포트가 정직하게 반영.

---

## 9. 테스트 (사용자 정책: 코드변경마다 적대적 감사 + 테스트 필수)

- `bucket_proxies`: 맵 완전성(14버킷 전부), 최근윈도 fetch, **fillna(0) 금지**(sentinel 오염 차단), a1 floor.
- `bucket_cov`: PD, ×252 연환산, LW 수축이 표본공분산보다 안정.
- `bl_engine`: **no-view→baseline 정확복원**, known-view→방향정확·유계, **§17 스케일 불변식**, 상대view zero-sum P(`P·1=0`), Idzorek Ω가 confidence에 단조감소, fx/credit view 부호 정확.
- `trader_allocator`: 플래그 라우팅(옛/신), 전 폴백 경로, vol_haircut 우회.
- 게이트2 스크립트 = 실행가능 테스트.
- **적대적 감사 워크플로(다중에이전트)** — 코드변경마다(Ultracode 강화).

---

## 10. Phase 구성 (D5 · ETF-선택은 *먼저* 출시)

| Phase | 내용 | 게이트 |
|---|---|---|
| **A — Σ 인프라** | `bucket_proxies`(§4.1 교정맵) + `bucket_cov`(LW·연환산·PD). LLM·BL 없음, 자족 | — |
| **B — BL엔진+게이트2** | `bl_engine`(Π·고정view P/Q/Ω·결합·MQU) + `trader_allocator` 분기플래그(고정view만). 게이트2 sanity + δ·base_spread 보정 | **게이트2(차단)** |
| **C — LLM 상대 view** | `BucketTilt.bucket_ranking` + 프롬프트(상대순위) + LLM view를 fx/credit 결정론 view와 함께 `bl_engine` 배선 | — |
| **D — 정리** | 옛 경로 제거(`project_to_band`/`apply_macro_modifiers`/`_risk_tilt_delta`/`tilts`/`vol_haircut`), BL 기본화·플래그 제거, 풀 라이브 재검증 | — |
| *(지연·비차단)* | 게이트1 20년 backtest = 후속 검증 | — |

**의존성.** ETF-선택 sub-project가 *먼저* 출시(옛 Step A 위). ETF의 M1/M3/M4/M5(`sub_category_views`·candidate_selector·within_bucket·cluster_repair)는 *bucket_target 비중 + sub_category_views*에만 의존하므로 BL이 Step A를 교체해도 **그대로 생존** — BL Phase D가 대체하는 건 ETF M2의 `project_to_band` 배선뿐. 직교.

---

## 11. 미해결 / 위험

- **통화 처리(§4.1):** native-currency 공분산이 KRW투자자 실현수익과 괴리. FX를 a4 view로만 잡는 게 충분한지 Phase A에서 검증.
- **2년 윈도 Σ:** 레짐 전환기 공분산이 덜 robust. LW 수축으로 완화하되, 윈도 길이는 dial로 노출.
- **δ·base_spread 동시보정:** 두 다이얼이 공격성에 곱셈적 → 게이트2에서 *함께* 스윕하지 않으면 식별불가. 보정 절차에서 고정-한쪽-스윕-다른쪽 또는 격자.
- **GROWTH합≤70% 소프트 제약 vs 하드 mandate 괴리(§5.1):** 소프트 제약이 하드와 크게 어긋나면 repair가 BL 의도를 크게 흔들 수 있음 — 게이트2에서 BL출력의 realized risk%(RISK_BUCKET_NAMES 기준)를 함께 측정.
- **PyPortfolioOpt 의존:** 미설치 시 Phase A에서 추가 또는 NumPy 직접 구현 결정.
