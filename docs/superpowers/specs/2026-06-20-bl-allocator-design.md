# Black-Litterman 버킷 배분 전환 — 설계 (rev1)

> **상태:** 적대적 감사(5렌즈·35제기·26확정) 반영 완료 → 사용자 검토 대기.
> **rev1 변경:** 다중에이전트 적대적 감사의 4 must-fix(MATH-1 Σ_p→Σ, FALSE-1 천장 false-trip, PARTIAL-1 부분실패, PIT-1 as_of) + 13 should-fix를 전 섹션에 반영. 변경점은 각 절 머리에 `[감사]`로 표기.
> **대체:** `origin/feat/bl-allocator` 의 `2026-06-09-bl-allocator-design.md`. 본 문서가 현 14-bucket·`trader_allocator` 기준 정본.
> **선행 sub-project:** ETF-선택 하이브리드(`2026-06-16-etf-selection-hybrid-design.md`, rev3) — *먼저* 출시(미구현). BL은 그 위에 버킷 배분층 교체.
> **브랜치:** `rework/pipeline-methodology`. 테스트: repo `.venv` py3.13, `PYTHONUTF8=1`.

---

## 1. 목적 · 비목적

**목적.** Stage 3 `trader_allocator`의 **Step A(14버킷 비중 결정)** 를 현행 "quadrant 앵커 + LLM weight-tilt → 밴드 투영(`project_to_band`)"에서 **Black-Litterman**으로 교체:
- prior = regime baseline의 reverse-optimization (`Π = δ·Σ·w_baseline`),
- view = LLM **버킷 상대순위**(He-Litterman 상대 view) + fx/credit 결정론 view,
- 결합 → `max_quadratic_utility(μ_BL, **Σ**, δ)` → 버킷 비중.

**[감사 MAG-2] 역할 분리(정직).** 대회(2026.6–8) **수익 순위 top-30**(30%)의 *주 레버는 ETF-선택층*(반도체 등 집중, 단일≤20%/클러스터35% 캡 내)에 귀속한다. 버킷-BL의 역할은 **리스크-인지 배분 + 엄밀한 방법론 서사(철학 70%) + 방어성**이다 — 4%/년 상대 view의 3개월 *실현* 기여는 상한 가정에서도 ~0.1–0.25%p로 top-30 컷을 단독으로 못 움직인다. BL을 "공격적 수익 틸트"로 과대포지셔닝하지 않는다.

| sub-project | 역할 |
|---|---|
| 버킷-BL (본 문서) | 방법론·방어·철학(70%). view는 *순위* 신호. |
| ETF-선택 (선행) | 집중·수익(30%). 캡 내 종목 알파. |

**비목적.** Step B·repair·Stage 5/6 불변. 20년 Sharpe 증명은 본 출시 비차단(§7). 일간 오버레이(vol cap 제거·mandate-drift only)는 범위 밖이나 BL 출력이 그리로 흐름.

---

## 2. 핵심 결정 (5)

| # | 결정 | 선택 | 근거 |
|---|---|---|---|
| D1 | STOP 게이트 무게 | **C — 하이브리드** | 싼 게이트2(LLM·proxy 불필요)만 차단. 20년 게이트1(목적과 어긋난 20년 Sharpe)은 비차단 후속. |
| D2 | LLM view 형식 | **B — 상대순위** | weight-tilt는 BL을 현행과 동일화(무의미). 절대 view는 LLM 약점+폭주형태. 상대순위=LLM강점·레벨앵커 회피·철학 최강. |
| D3 | Σ 소스 | **A — 최근윈도+LW** | 최근 2년 proxy + Ledoit-Wolf 수축, 월간 롤링. §12.1 매핑을 짧은 윈도로 회피. |
| D4 | BL 이동 자유도 | **A — mandate+캡, δ 다이얼** | baseline±band 제거. 거버너=δ+Σ+mandate. 방어성은 prior가, 집중통제는 ETF층 캡이 담당. **[감사 CAP-3]** band 제거의 실효 집중통제는 *cluster_repair(35%)가 구현된 후* 성립 — §10 선행조건 참조. |
| D5 | 도입 방식 | **2 — 병렬모듈+분기** | 신규 BL 모듈 + 플래그 분기. 게이트2가 두 경로 공존을 요구. 가역. 통과 후 정리. |

---

## 3. 아키텍처 & 데이터 흐름 (월간 경로)

```
Stage 1/2: regime.quadrant(결정론) + 매크로/뉴스 + state['as_of_date']
        ▼
┌─ Stage 3 · Step A : 버킷 비중 (BL) ────────────────────────────┐
│  QUADRANT_BASELINE[quadrant] ─► w_baseline (prior 비중)         │
│  as_of ─► bucket_proxies([as_of−504bd, as_of]) ─► bucket_cov   │
│                                  (LW수축·연환산·inner-join) ─► Σ │
│            reverse-opt:  Π = δ · Σ · w_baseline   (δ-항등)     │
│  [통합 Step-A LLM 1콜]                                          │
│   ├ bucket_ranking (14버킷 tier+conviction) ─► (P,Q,Ω) Idzorek │
│   └ sub_category_views ──────┐  (ETF-선택 필드, BL과 직교)      │
│  fx/credit 결정론 view ───────┼─► (P,Q,Ω) 추가행               │
│                              ▼  μ_BL = BL결합(Π,Σ,τ,P,Q,Ω)     │
│         max_quadratic_utility(μ_BL, **Σ**, δ;                  │
│           w≥0, Σw=1, GROWTH합≤0.70, mandate-RISK합≤0.68)       │
│                              ▼  bucket_target(14, 의도)        │
│         soft-clip(camp별 천장)+water-fill → _clamp_pool        │
│   ┌──────────────────────────┘  (sum=1·제약은 하류가 enforce)  │
│   ▼ sub_category_views (ETF층 직행)                            │
└────┼───────────────────────────────────────────────────────────┘
     ▼ Step B: candidate_selector → within_bucket (ETF-선택 M3/M4)
     ▼ repair: cluster(35%)·single≤20%·repair_risk_cap → renormalize
     ▼  Stage 5 validator(하드 백스톱) → Stage 6 PM
```

**핵심 불변식 (D4 안전성). [감사 MATH-1·INVAR-1]** view=∅ ⇒ `μ_BL = Π = δ·Σ·w_baseline`, 그리고 **최적화 공분산을 prior Σ로 쓸 때** `max_quadratic_utility(Π, Σ, δ)`의 예산제약(Σw=1)+박스+그룹제약 하 해 = `w_baseline` 을 **정확복원**(감사 수치검증 L1=0, 6시드). ⚠️ 사후공분산 Σ_p=(1+τ)Σ를 최적화에 쓰면 해가 `w_baseline/(1+τ)`로 깨져(L1≈0.083) 게이트2 ⓓ가 영구 실패 — **Σ_p는 진단/리스크 리포팅 전용, 최적화는 prior Σ.**

**[감사 CLAMP-1] `_clamp_to_pool_capacity`는 "불변 유지" 아님** — 풀 용량 clamp는 sum=1·GROWTH≤0.70을 *비보존*한다. BL의 sum=1·제약은 clamp가 아니라 하류 `aum_weighted_allocation → repair → 최종 renormalize`(현 trader_allocator.py:235-253)가 보장(옛 경로와 동일). 도식의 'bucket_target(14)'는 pydantic `BucketTarget` 생성이 아니라 MQU 14-벡터 출력.

**모듈 맵 (D5).**

| 파일 | 책임 | 신규/수정 |
|---|---|---|
| `tradingagents/backtest/bucket_proxies.py` | §12.1 교정 proxy 맵 + **as_of 끝점** 윈도 fetch + 버킷별 대체proxy 폴오버 | **신규** |
| `tradingagents/skills/portfolio/bucket_cov.py` | inner-join → numpy.cov → LW수축 → 연환산 Σ(PD); 버킷별 핀; currency_basis dial | **신규** |
| `tradingagents/skills/portfolio/bl_engine.py` | Π 역산(δ-항등) · 상대view→(P,Q,Ω) · BL결합 · MQU(prior Σ) · soft-clip | **신규** |
| `tradingagents/schemas/portfolio.py` | `BucketTilt`에 `bucket_ranking` 추가(`sub_category_views`는 ETF-선택; `tilts`는 정리Phase 제거) | 수정 |
| `tradingagents/agents/trader/trader_allocator.py` | `as_of` 추출·전달 · Step-A 프롬프트(상대순위) · 옛/신 분기 플래그 · vol_haircut 우회 · BL-native attribution | 수정 |
| `tradingagents/skills/portfolio/scenario_anchor.py` | `QUADRANT_BASELINE` 유지(prior); tilt수학은 정리Phase 제거 | 수정 |
| `scripts/backtest_bl_gate2.py` | 게이트2 sanity(ⓐ–ⓔ) + native/KRW Σ 발산 출력 + (자족)δ·base_spread 보정 | **신규** |

---

## 4. Σ 인프라 (Phase A)

### 4.1 proxy 맵 (§12.1 교정 — 옵션 A) · [감사 DATA-1]

| 버킷 | 1차 proxy | 대체 proxy | 소스 |
|---|---|---|---|
| a1_cash | 단기금리 level/12 (분산 floor) | — | FRED DGS3MO 등록 / ECOS CD91 |
| a2_kr_rates | KOSEF 국고채10년 148070 (pykrx) | ECOS kr_treasury_10y | KRX/ECOS |
| a3_us_rates | IEF (7–10Y) | — | yfinance |
| a4_safe_fx | DXY (DTWEXBGS, FRED) | USDJPY | FRED/yfinance |
| a5_gold_infl | GLD | — | yfinance |
| b1_kr_equity | **069500.KS**(KODEX200) 또는 EWY | EWY | pykrx/yfinance |
| b2_dm_core | URTH | ACWI | yfinance |
| b3_global_tech | QQQ | — | yfinance |
| b4_china | MCHI | FXI | yfinance |
| b5_other_intl | EEM | VEA | yfinance |
| b6_defensive_equity | SPLV | — | yfinance |
| b7_reits | VNQ | — | yfinance |
| b8_cyclical_commodity | DBC | XLE | yfinance |
| b9_risk_credit | HYG | — | yfinance |

**[감사 DATA-1] fetcher 배선:** `^KS200`은 yfinance 결측 잦아 1차에서 제외(069500.KS/EWY). 신규 yfinance 배치 namespace(URTH·SPLV·MCHI·DBC·IEF·QQQ·GLD·EEM·VNQ·HYG)는 `cross_asset_returns.py`의 `_raw_yf_batch` + `series_cache.fetch_frame_with_cache` 패턴 재사용(기존 티커셋 불변). DGS3MO·DXY는 `fred.py`에 등록. 작업량은 "신규 ingestion 통째"가 아니라 **기존 배치/캐시 helper 재사용 + ~5 티커 신규 등록**.

**통화 처리(결정) · [감사 FX-5].** 기본 native-통화 공분산(글로벌=USD, 국내=KRW), 글로벌 버킷에 USDKRW 미주입(FX는 a4 view). **단** `bucket_cov`에 `currency_basis ∈ {native, krw_realized}` dial을 두고, krw_realized는 글로벌 일별수익에 USDKRW 일별수익 가산. 게이트2가 두 Σ의 글로벌 비중·위기윈도 방어 차이를 *실측 출력*(글로벌 Δ>5pp 또는 L1>0.10 시 경고). native 채택을 막지 않되 게이트2 증빙 후 진행.

**a1_cash 특례.** 분산≈0 → Σ 특이 위험. 분산에 작은 floor(예 MMF 0.5%/년, illustrative)를 backstop으로 주고 LW 수축이 PD 보장. **`fillna(0.0)` 금지**(σ≈0 위조).

### 4.2 공분산 (`bucket_cov.py`) · [감사 PARTIAL-1·DATA-2·PIT-1]

- **입력 윈도:** `as_of` 끝점 `[as_of−~504거래일, as_of]`. **as_of 이후 데이터 절대 미포함**(look-ahead 차단). `as_of`는 trader_allocator가 `date.fromisoformat(state["as_of_date"])`로 추출·전달(`conditional_logic.py:45-47` 패턴 재사용).
- **공분산 계약(필수):** 전 버킷 수익을 outer-join 후 **공통 거래일 교집합(inner-join, `dropna(how='any')`)에서만** 단일 `numpy.cov` → LW 수축 → **×252 연환산**. **pairwise cov 금지** — pypfopt `sample_cov`/`CovarianceShrinkage`는 내부 `.cov()` pairwise + `fix_nonpositive_semidefinite`로 NaN·non-PSD 가드를 *무력화*하므로, inner-join으로 윈도 일관성 확보 후에만 LW 호출. KR(KST)·US(ET) 휴장 비동기를 0수익으로 위조 금지.
- **부분실패 처리(전체폴백 금지):**
  1. proxy fetch 실패/델리스팅 → §4.1 대체proxy 자동 폴오버.
  2. 폴오버도 실패/미정의 버킷 j, 또는 비-NaN 관측 < 252인 버킷 → **그 버킷만 `w_baseline[j]`로 핀**(고정, view·최적화 제외), 나머지 (14−k) BL을 풀고 핀 합만큼 정규화.
  3. inner-join 후 *전체* 유효관측 < 252 또는 ≥절반 버킷 핀 → 그때만 **전체 baseline 폴백**.
- **cond(Σ) 점검:** krw_realized 등 고공선성 시 LW 수축강도와 함께 `cond(Σ) ≤ 천장(예 200)` 단언.

---

## 5. BL 수학 계약 (`bl_engine.py`, lib = PyPortfolioOpt 또는 NumPy 직접)

**(1) Prior 역산.** `Π = δ · Σ · w_baseline`. **[감사 MATH-2] INVARIANT(δ-항등):** 역산의 δ와 최적화 `risk_aversion=δ`는 **동일 변수**다. 공격성 조절로 δ를 바꾸면 Π를 같은 δ로 *재역산*해야 no-view 정확복원이 보존된다(제약 QP는 스케일 등변 아님). 공격성은 base_spread 우선 조절(§7).

**(2) 상대 view 구성 — 결정론 변환, LLM은 tier·conviction만. [감사 MATH-3·BLOW-1]**
- LLM: 14버킷에 tier ∈ {strong_OW, OW, neutral, UW, strong_UW} + conviction c∈[0, **0.95**](상한 캡, 폭주 완화).
- 부호화 tier점수 s_i = tier점수×c (strong_OW=+1…strong_UW=−1). **평균제거: `s ← s − mean(s)`** → 동일 tier 일색(예 all-OW) 입력은 자동 s=0→Q=0(모순 view 제거, zero-sum 정합).
- **비중립 버킷(s_i≠0)에 대해서만** 상대 view: `P_i = e_i − (1/N)·1`(zero-sum), `Q_i = base_spread · s_i`. 전부 0이면 view=∅ → §3 불변식으로 baseline 복원.
- `base_spread` 기본 0.04(연환산), 게이트2 스윕 산출값으로 대체. `τ = 0.05`.
- **Ω = Idzorek**: c_i → Ω_ii 역산(고conviction→저Ω). (stacked P는 rank≤13이나 prior항 (τΣ)⁻¹로 전체 시스템 full-rank·가역 — 무해.)

**(3) fx/credit 결정론 view.** 현 `CREDIT_MODIFIER`/`FX_MODIFIER` 의도를 상대 view로 재해석해 추가행 투입(부호=delta 부호, 크기 고정 spread 0.02, confidence 높음→저Ω). 후처리 modifier(`apply_macro_modifiers`) 제거. 예) credit=crisis → "b9 UW, a3 OW"; fx=usd_risk_off → "a4 OW, b1 UW".

**(4) BL 결합.** `μ_BL = [(τΣ)⁻¹ + PᵀΩ⁻¹P]⁻¹ [(τΣ)⁻¹Π + PᵀΩ⁻¹Q]`. **[감사 MATH-1]** 사후공분산 Σ_p는 *진단/리스크 리포팅 전용*으로만 산출(또는 미산출) — **최적화 입력 아님**.

**(5) 최적화.** `max_quadratic_utility(μ_BL, **Σ**, risk_aversion=δ)` (prior Σ) + 박스제약:
- `w_b ≥ 0`, `Σ_b w_b = 1`,
- `Σ_{b∈GROWTH_KEYS(b1–b9)} w_b ≤ 0.70` (camp 서사용 소프트 성형),
- **[감사 MANDATE-1·RISK-1] mandate-정렬 제약:** `Σ_{b∈{b1..b8, a5_gold_infl, a4_safe_fx}} w_b ≤ 0.68` — `RISK_BUCKET_NAMES`(precious_metals=a5, cyclical_commodity_fx=a4는 mandate-위험; b9는 mandate-안전)에 근사 정렬해 realized RISK를 사전성형, repair 발동 구조적 축소. (recession quadrant는 0.66으로 보수화해 옛 `_BAND_UP_RECESSION_GROWTH` risk-on 억제 일부 승계.)

이어 **soft-clip + _clamp** (아래 §5.1) 적용 → Step B.

**(6) §17 폭주방지 불변식(테스트 잠금) · [감사 BLOW-1].** Π·Q·μ는 연환산, Σ는 ×252. 테스트는 `|Π_b|~한자리%대` 단언에 더해 **사후 w 단언으로 확장**: 풀컨빅션 단일 view(b3 strong_OW)에서 (i) max bucket ≤ camp별 천장, (ii) baseline 대비 L1 ≤ L1_max(예 0.20), (iii) 방어버킷합 ≥ defensive_floor. Σ vol ±20% grid에서도 유지 또는 §8 폴백 트리거 확인.

### 5.1 천장·집중통제 — soft-clip (binary 천장 폐기) · [감사 FALSE-1·CLAMP-1]

**binary 0.30 천장 + baseline 전체폴백 폐기**(침체기 정당한 a3 OW=0.32~1.00을 폭주 오인해 view 전손하는 false-trip 제거):
- **성장 camp 단일 버킷:** soft-clip 0.30 + 잔여 water-fill(비-clip 버킷에, `_clamp_to_pool_capacity` 패턴 재사용) — baseline 폴백 아님.
- **방어 camp 단일 버킷:** 천장 상향(a1·a3 ≤ 0.50) 또는 버킷레벨 천장 제거하고 집중통제를 ETF층(단일ETF≤20% + 국채 category cap)에 위임(D4/§5.1 위임구조 정합).
- **§8 런타임 폴백은 solver 실패/non-PD Σ 한정** — "max bucket > 천장"은 폴백 사유 아님(soft-clip이 처리).

### 5.2 위험자산 70% 이중정의

- **트레이더 camp** `GROWTH_KEYS`(b1–b9): §5(5) 소프트 그룹제약.
- **대회 mandate** `RISK_BUCKET_NAMES`(ETF레벨 `bucket_for_etf`): 하드 70% 보장은 기존 `repair_risk_cap` + Stage 5 validator. BL은 이를 안 바꿈. §5(5) mandate-정렬 제약(≤0.68)이 둘의 괴리를 사전성형으로 좁힘. (repair는 위험집합 *내부 상대순위 보존*, 훼손은 RISK↔SAFE 재배분.)

---

## 6. 통합 Step-A LLM 계약 · [감사 ATTR-1]

한 LLM 콜이 하나의 구조화 객체:
```
BucketTilt (확장):
  bucket_ranking: { <14 bucket_key>: {tier: Literal[...5...], conviction: float[0,0.95], rationale: str} }
  sub_category_views: { <bucket>: { <sub_cat>: float } }   # ETF-선택이 추가
  tilts: dict[str,float]                                   # 옛 필드 — BL 경로 무시, 정리Phase 제거
  rationale: str
```
- **진화 순서:** ① ETF-선택 출시 시 `sub_category_views`(default_factory, backward-compat) 추가, ② BL Phase C에서 `bucket_ranking` + 프롬프트 교체("tilt 가감"→"tier+conviction 순위") *한 묶음*, ③ Phase D `tilts` 제거. (어느 시점도 한 프롬프트가 tilt와 ranking을 동시 요구하지 않음.)
- bucket_ranking → BL, sub_category_views → ETF층(직교). 같은 추론에서 나오므로 1콜 정합.
- 프롬프트 입력은 현 `_step_a_prompt`(thesis·key_risks·Stage1·feedback) 재사용.

---

## 7. 게이트 & 검증 · [감사 HARNESS-1·MANDATE-1·FX-5·PHIL-4]

**게이트2 (차단·LLM불필요·하네스불필요).** 기본값 δ=2.5, base_spread=0.04로 고정 view 세트를 `bl_engine`에 투입해 sanity(`_clamp` 이전 bucket_target 기준):
- ⓐ b3 strong_OW·a3 strong_UW → 방향 정확,
- ⓑ baseline 대비 L1 ≥ ε_min(0.05; inert 아님),
- ⓒ 폭주 없음(soft-clip 후 max bucket ≤ camp 천장; §17 재현 안 됨),
- ⓓ view=∅ → baseline 정확복원(L1 < 1e-6) — **prior Σ 사용 전제**(MATH-1),
- **ⓔ 방어 OW false-trip 부재:** recession_disinflation + a3 strong_OW 케이스에서 a3가 soft-clip(또는 방어천장)으로 graceful 처리되고 baseline 전체폴백 안 됨,
- **ⓕ realized-RISK 차단:** 고정 view에서 measured risk%(`RISK_BUCKET_NAMES`, trader_allocator.py:267 정의)가 0.70 초과하거나 `repair_risk_cap`이 위험포지션을 ≥5%p 비례축소하면 STOP→base_spread 상한 하향·mandate-제약 강화.
하나라도 실패 → **STOP**, 보고.

**δ·base_spread 보정(비차단 후속·자족). [감사 HARNESS-1·IDENT-1]** 공격성은 *단일 비율* base_spread/δ로 1D 식별(감사 증명) → **δ=2.5 고정, base_spread만 스윕**(2D 격자 불필요). "풀컨빅션 단일 view에서 max bucket을 천장 아래로 유지하는 최대 base_spread"를 채택(0.02~0.05 범위 가능). **하네스는 `scripts/backtest_bl_gate2.py`에 자체 내장**(`returns_matrix.fetch_returns_matrix` + 14 proxy로 최근윈도 수익순위 프록시) — ETF-선택의 미구현 `backtest_etf_selection.py`에 의존하지 않음.

**게이트1 (지연·비차단·경량 재정의). [감사 PHIL-4]** 20년 Sharpe 대신 **최근 2–3년 baseline vs 60/40·1/N의 위험·상관 일관성**(Σ 윈도와 동일 기간)으로 교체(대회 기간 정합, proxy 장기 히스토리 회피).

**철학(70%) 결정론 차단 산출물. [감사 PHIL-4]** prior가 "미검증"으로 비치지 않게, 거짓수치 없이 *검증가능한 결정론 facts*로 평가축(규칙 line 77 "AI쏠림/단일리스크 통제") 직접 충족:
- (a) **prior 정당화 facts:** `philosophy._build_facts_block`에 현 quadrant의 `QUADRANT_BASELINE` 비중 + 레짐→자산군 논리(예 recession_inflation a5 0.17·b8 0.13=인플레헤지) 결정론 주입(LLM이 인용, 날조 금지).
- (b) **내부 상관 분석:** `bucket_cov`의 14×14에서 상관행렬 `Corr=D⁻¹ΣD⁻¹` derive → 철학 "단일 리스크 통제" 섹션에 최고 상관쌍·성장/반도체 클러스터 비중합을 facts로 표면화(`allocation_attribution`에 corr 요약).

---

## 8. 폴백 — BL은 파이프라인을 절대 깨지 않는다 (정직 로깅) · [감사 PARTIAL-1·FALSE-1·ATTR]

| 실패 | 처리 |
|---|---|
| **부분** — 일부 버킷 proxy 실패/일부 컬럼 NaN/단버킷 짧은윈도 | 대체proxy 폴오버(§4.1) → 실패 시 *해당 버킷만* baseline 핀 + (14−k) BL. **전체폴백 아님** |
| 전체 Σ 비정상 — inner-join 유효관측<252 또는 ≥절반 핀 또는 non-PD | **전체 baseline 폴백**(BL 스킵), 로그 |
| BL 최적화 infeasible/solver 실패 | **전체 baseline 폴백**, 로그 |
| LLM view 파싱 실패/빈 ranking | view=∅ → baseline 정확복원(불변식). 에러 아님, 안전 강등 |
| max bucket > camp 천장 | **soft-clip + water-fill**(§5.1) — baseline 폴백 아님 |
| mandate 위반 | GROWTH·mandate-RISK 소프트 제약 사전성형; 하드는 하류 repair + Stage5 |

**[감사 ATTR-1·ATTR-2] BL-native attribution(철학 역추적).** `allocation_attribution.step_a`에 `method='bl'` 분기, 버킷별 분해 `{baseline(prior w_baseline), view_contribution(Π→μ_BL 당김), optimizer_shift(MQU解−prior implied), final(의도), realized(=realized_bucket_weights)}`. `|final−realized|>3%p` 버킷은 사유 태그(`clamp_pool_capacity`/`repair_cap`/`drop_negligible`/`baseline_pinned`/`fallback`). 버킷별 Σ 상태 `{status: bl|proxy_failover|baseline_pinned, reason, n_obs}` 기록. philosophy는 method 키로 분기(anchor 4열 vs BL view-기여 표), bucket_ranking의 tier/conviction/rationale을 '판단 근거'로 렌더. step_a 분해=*의도*(clamp·repair 전), 14-bucket 표=*실현*임을 평가자에게 명시.

---

## 9. 테스트 (코드변경마다 적대적 감사+테스트 필수)

- `bucket_proxies`: 맵 완전성(14), as_of 끝점(**look-ahead 단언**: as_of 이후 거래일 미포함; as_of=T−30 fetch ⊂ as_of=T fetch), 대체proxy 폴오버, `fillna(0) 금지`.
- `bucket_cov`: inner-join Σ NaN-free·PSD·공통윈도, ×252, LW가 표본보다 안정, **부분NaN→그 버킷만 핀·나머지 BL**, min252 핀, KR/US 비동기 fixture(휴장행 0위조 안 함), cond(Σ) 천장, attribution 버킷별 사유.
- `bl_engine`: **임의 δ∈{1,2.5,4,8}에서 no-view→baseline 정확복원(L1<1e-6, prior Σ)**, 역산/최적화 δ 분리 시 ⓓ 실패 음성테스트, known-view 방향정확·**사후 w 유계**(§5(6)), all-same-tier→Q=0, 상대view zero-sum(P·1=0), Idzorek Ω가 conviction 단조감소, fx/credit 부호, **ⓔ 방어 OW false-trip 부재**, mandate-RISK 제약 작동.
- `trader_allocator`: as_of 추출·전달, 플래그 라우팅, vol_haircut 우회, BL-native attribution, 전 폴백.
- 게이트2 스크립트 = 실행 테스트(ⓐ–ⓕ + native/KRW 발산).
- **적대적 감사 워크플로(다중에이전트)** — 코드변경마다.

---

## 10. Phase 구성 (D5 · ETF-선택 선행) · [감사 CAP-3·HARNESS-1]

| Phase | 내용 | 게이트/선행 |
|---|---|---|
| **선행(차단)** | **ETF-선택 sub-project 출시** — M1/M3/M4/M5(`sub_category_views`·candidate_selector·within_bucket·**cluster_repair CLUSTER_CAP=0.35 + correlation_check validator 0.25→0.35 동기화**). 현재 미구현(grep 0, validator 0.25). D4 집중통제의 선행조건. | BL 전 차단 선행 |
| **A — Σ 인프라** | `bucket_proxies`(교정맵·as_of·폴오버) + `bucket_cov`(inner-join·LW·연환산·핀·currency dial). LLM·BL 없음 | — |
| **B — BL엔진+게이트2** | `bl_engine`(Π·δ항등·고정view·결합·MQU prior Σ·soft-clip) + 분기플래그(고정view) + `backtest_bl_gate2.py`(자족 보정) | **게이트2 ⓐ–ⓕ(차단)** |
| **C — LLM 상대 view** | `bucket_ranking` + 프롬프트(상대순위) + LLM view를 fx/credit 결정론 view와 배선 + BL-native attribution + 철학 facts(prior·corr) | — |
| **D — 정리** | 옛 경로 제거(`project_to_band`/`apply_macro_modifiers`/`_risk_tilt_delta`/`tilts`/`vol_haircut`), BL 기본화·플래그 제거, 풀 라이브 재검증 | — |
| *(지연·비차단)* | 게이트1 경량 재정의 backtest | — |

**의존성.** ETF의 M1/M3/M4/M5는 *bucket_target + sub_category_views*에만 의존 → BL이 Step A 교체해도 생존. BL Phase D가 대체하는 건 ETF M2의 `project_to_band` 배선뿐. 직교.

---

## 11. 미해결 / 위험

- **통화 처리(§4.1):** native vs krw_realized — 게이트2 발산 증빙 후 채택(FX-5). 일별 freq corr≈0이라 gap 주로 FX 분산항(~2–3pp).
- **2년 윈도 Σ:** 레짐 전환기 덜 robust → LW 수축 + 윈도 dial.
- **mandate-정렬 제약 근사:** `bucket_for_etf`는 ETF별이라 14버킷↔mandate가 fractional(a4≈0.85 RISK) — 보수적 포함으로 over-constrain은 작음. "FX·원자재" category cap 0.20이 상방 bleed를 ~0.20로 제한.
- **base_spread 수익 한계(MAG-2):** 4%/년의 3개월 실현 ~0.1–0.25%p — 수익 레버는 ETF층. base_spread↑로 짜내는 경로는 §7ⓒ 천장과 구조적 상충.
- **PyPortfolioOpt 의존:** 미설치 시 Phase A에서 추가 또는 NumPy 직접 구현(닫힌형).
- **선행 스택 미출시:** ETF-선택·BL 모두 docs-only. cluster_repair(35%) 미구현 시 D4 집중통제는 기존 25% validator + category cap이 잠정 담당(CAP-3).
