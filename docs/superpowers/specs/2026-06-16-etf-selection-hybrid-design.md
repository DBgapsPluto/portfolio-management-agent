# 개별 ETF 선택 — 하이브리드(LLM 테마 view + 모멘텀) 설계

**Date:** 2026-06-16 (rev2 — adversarial review 반영)
**Stage:** 3 (Portfolio allocation) — Step B (within-bucket ETF 선택·가중)
**Status:** 설계 검토 중 (rev2: 적대적 검토 11 findings 반영)
**Branch:** `rework/pipeline-methodology`

## 1. 배경 / 문제

BL/배분(Step A)이 *버킷* 비중을 정한 뒤, 그 비중을 버킷 안의 개별 ETF에 배분한다. 현재(`candidate_selector` + `within_bucket`)는 **의도적으로 broad(core) sub_category를 AUM 순으로** 고르고 thematic(반도체·AI·2차전지)을 *배제*한다 (`candidate_selector.py:5`). 가중도 **AUM 비례**.

문제: **AUM은 수익 신호가 아니다.** 이질 버킷(예: `b3_global_tech` = 반도체·AI·2차전지·중국전기차·테슬라 한 버킷)에서 AUM 가중은 *작동 테마(반도체)를 laggard와 크기 비례로 희석*한다. 3개월 대회 수익률 top-30 + IT/반도체 멜트업 환경에서, **개별 ETF 선택이 가장 큰·빠른 수익 레버인데 정반대로 작동 중**이다.

## 2. 목표

> 이질 버킷의 within-bucket ETF 선택을 **하이브리드(LLM 테마 view로 sub_category 좁힘 → 모멘텀 랭크 → mandate cap까지 집중)**로 전환한다. 동질 버킷은 기존 AUM/core 유지. **BL과 별개로, BL보다 먼저** 구현한다.

비범위: BL allocator(별도 spec), daily overlay 수정, 동질 버킷, 14-bucket taxonomy, Step A 버킷 비중.

## 3. 확정 결정사항

| # | 항목 | 결정 |
|---|---|---|
| 1 | 선택 철학 | **하이브리드** — view로 테마 좁힘 → 모멘텀 랭크 |
| 2 | view source | **Step-A 트레이더 LLM 출력 확장** — `BucketTilt`에 `sub_category_views` 추가 (별도 LLM 콜 ❌) |
| 3 | 모멘텀 정의 | **순수 모멘텀** = `mean( z(skip1m_mom_3m), z(skip1m_mom_6m), z(skip1m_mom_12m) )`, **post-cut 풀 cross-section** z. lowvol/quality/size 미사용 |
| 4 | 집중 천장 | **카테고리 cap(해외주식_섹터 10%·국내주식_섹터 15%·해외주식_지수 30% 등, repair_category_caps 강제)이 1차 binding. 군집 25%는 2차 — 신규 cluster_repair(M5)로 graceful 강제** |
| 5 | 가중 방식 | **기존 `aum_weighted_allocation` 재사용** (minimal-N=1이라 fill-from-top과 동일 — M4 불필요). 레버는 100% *선택* |
| 6 | 이질 버킷 | **b2_dm_core · b3_global_tech · b5_other_intl** (b8은 4종목·3개 floor미달로 단일종목 퇴화 → 초기 제외, universe 성장 시 재검토) |
| 7 | 동질 버킷 | a1~a5 · b1 · b4 · b6 · b7 · b8 · b9 → 기존 AUM/core (변경 없음) |
| 8 | 유동성 floor | 이질 버킷 ETF AUM < `min_etf_aum_krw`(dial, **기본 100억** — thematic 과다컷 방지) 컷. 컷·fallback은 **attribution에 기록**(silent revert 방지) |
| 9 | 검증 | **경량 백테스트 sanity** (momentum-pick vs AUM-pick, warm-up 후 유효구간, net-of-cost) — GO/NO-GO. LLM view는 backtest 불가(모멘텀 골격만 검증) |
| 10 | 구현 순서 | ETF 선택 먼저 → BL 나중 |

### 3.1 BL과의 통합 (설계 의도 — 검증된 보장 아님)

theme view LLM과 (나중의) BL view LLM은 **같은 LLM 콜, 다른 granularity**가 되도록 *의도*한다. 별도 콜을 만들지 않고 Step-A LLM 출력을 확장. `sub_category_views`(버킷 내 테마 선호)는 BL이 와도 그대로 유지되고, BL은 버킷-레벨 view만 추가/교체. *(BL 단계에서 실제 호환성 재확인 필요 — 현재는 의도.)*

## 4. 아키텍처 (전 → 후)

```
[후]  Step-A 트레이더 LLM (기존 1콜)
        출력 BucketTilt: tilts(기존) + sub_category_views (이질 버킷만, M3가 비-이질 키 무시)
            sub_category_views = {bucket: {sub_category: pref ∈ [−1,+1]}}
        │
        ▼  (M2: node가 fp→momentum dict 구성 + tilt.sub_category_views를 Step B로 전달)
      Step B, 버킷별:
        이질(b2/b3/b5):  candidate_selector(이질 분기)
            배제(pref<−τ) → 유동성 floor → (선호 있으면 선호만) → 모멘텀 랭크 → minimal-N
            → within_bucket.aum_weighted_allocation (선정 종목, minimal-N=1이면 단일 cap까지)
        동질:  기존 core-by-AUM 경로 (변경 없음)
        │
        ▼
      _repair_all (기존): repair_category_caps + repair_risk_cap   ← 카테고리 10/15% + 위험 70%
      + cluster_repair (M5 신규): 군집 25% graceful 축소           ← state['correlation_clusters'] 소비
      → drop_negligible → _repair_all (2차) → 최종 ETF weights
```

## 5. 컴포넌트

### 수정/신규 (M1–M5)

| # | 파일 | 변경 |
|---|---|---|
| M1 | `schemas/portfolio.py` `BucketTilt` | `sub_category_views: dict[str, dict[str, float]] = Field(default_factory=dict)` 추가. backward-compat(기존 `BucketTilt()`/cached_tilt 불변) |
| M2 | `agents/trader/trader_allocator.py` | (a) `_STEP_A_SYSTEM`/`_step_a_prompt`에 "이질 버킷(b2/b3/b5)만 sub_category 선호 출력" 지시 + 신호 테이블(§6) 주입. (b) **call-site 배선**(아래 §7): `fp`(line 197 기존)에서 `momentum` dict 구성, `select_representative_candidates(...)` 호출(line 215-220)에 `sub_category_views=tilt.sub_category_views.get(bkey)`(bkey∈HET일 때만), `momentum=`, `min_etf_aum_krw=` 추가. attribution 기록(선택 종목·revert 사유) |
| M3 | `skills/portfolio/candidate_selector.py` | `select_representative_candidates`에 이질-버킷 분기(아래 §7). 신규 keyword-only 인자 `sub_category_views=None, momentum=None, min_etf_aum_krw=None` (전부 default → 동질·기존 caller·테스트 불변). 비-이질 sub_category_views 키는 무시 |
| M4 | ~~within_bucket~~ | **불필요** — 이질 버킷 비중 ≤16% → n_floor=1 → 단일 종목. 기존 `aum_weighted_allocation`이 그대로 cap까지 채움. (>20% 버킷 생기면 그때 fill-from-top 추가) |
| M5 | `skills/mandate/cluster_repair.py` (신규) + `_repair_all` 배선 | 군집 25% **graceful 축소** repair (현재 cluster cap은 validator-only — fail 유발). `state['correlation_clusters']` + 최종 weights → 군집합>25% 시 비례 축소 + 비-군집/현금 water-fill. category_repair/risk_repair와 동일 패턴 |

### 유지 (재활용)

`FactorPanel.skip1m_mom_*`(이미 계산), `factor_scorer._zscore/_rank_normalize`(z 프리미티브만 — score_candidates는 mom-only 미지원이라 재사용 안 함), `CORE_SUBCATEGORIES`/`KNOWN_THEMATIC`, `within_bucket`, `repair_category_caps`/`repair_risk_cap`, `correlation_check`(validator), backtest 인프라.

### 신규 상수/dial

```python
HETEROGENEOUS_BUCKETS: set[str] = {"b2_dm_core", "b3_global_tech", "b5_other_intl"}
SUBCAT_PREF_THRESHOLD: float = 0.3   # |pref|>τ 일 때만 배제(−)/선호(+) 작동
# portfolio_dials
min_etf_aum_krw: float = 10_000_000_000   # 100억 — 이질 버킷 유동성 floor
```

## 6. 데이터 / API 사실 (조사 확인)

### 모멘텀 — 이미 계산됨, 안전 접근
```python
# FactorPanel (factor_scorer.py:66-71) — Stage1 technical analyst가 ETF별 계산
skip1m_mom_3m / 6m / 12m : float | None   # Jegadeesh-Titman skip-1m
# allocator 접근 (trader_allocator.py:196-198, 이미 realized_vol 소비 중):
tr = state.get("technical_report"); fp = getattr(tr, "factor_panel", None) or {}
# momentum 구성: 각 ticker p=fp.get(t); raw=[p.skip1m_mom_3m/6m/12m] (None skip);
#   풀 cross-section z-score(_rank_normalize) 후 평균. 전부 None → −inf(최하위, 버킷 비우지 않음)
```
모멘텀 z는 **배제/floor 컷 *이후*의 후보 풀**에서 cross-sectional 계산(고정 cross-section). `score_candidates`는 항상 mom/lowvol/qual/size를 blend하므로 **mom-only로 재사용 불가** — `_zscore/_rank_normalize` 프리미티브만 써서 전용 `momentum_score` 헬퍼 신규 작성.

### sub_category 신호 테이블 (LLM 입력 — §6 스키마 확정)
이질 버킷별, sub_category마다 행:

| 컬럼 | 값 |
|---|---|
| sub_category | 예 `semiconductor` |
| mom_z | `mean(z(skip1m_mom_3m/6m/12m))`를 sub_cat ETF 평균 (None→공란) |
| n_etf | sub_cat 종목 수 |
| top_etf | AUM 최대 ETF명 |
| theme_tag | macro_news `ThemeTag` 매핑(아래) |

**ThemeTag→sub_category 매핑(고정 표):** `ai_semis→{semiconductor, ai_robotics, it_software}`, `ev_battery→{battery_ev}`, `energy→{oil_energy, materials_energy}`, `defense_space→{industrial_defense}`, `biotech_health→{biotech_pharma}`, `crypto_fintech→{finance}`. (그 외 sub_cat은 theme_tag 공란.)
+ Stage-1 macro/risk/technical/news 요약 텍스트(정성 컨텍스트). **b3_global_tech 워크드 예시는 plan에 포함.**

### 선택/가중 인프라
- `candidate_selector.select_representative_candidates` (candidate_selector.py:111, 전부 keyword-only) — 신규 인자 추가 가능, 단일 live caller(trader_allocator.py:215)도 keyword 호출.
- `n_floor = max(1, ceil(bucket_weight/SINGLE_CAP − 1e-9))` (candidate_selector.py:179). `within_bucket._allocate_one_bucket`도 동일 `need = ceil(weight/SINGLE_CAP − _EPS)` (within_bucket.py:24) — 이질 분기는 *동일 상수/epsilon*으로 minimal-N 보장.
- 카테고리 cap: `CATEGORY_CAPS`(concentration_check.py:27-38), `repair_category_caps`(존재). 군집 cap: `correlation_check`(validator-only, repair 부재 → M5).

## 7. 알고리즘 상세

### M2 call-site 배선 (trader_allocator.py:215-220)
```python
# fp 이미 fetch(line 197). momentum dict 구성:
momentum = {t: _momentum_score(fp.get(t)) for t in eligible_all}   # all-None → −inf
...
selected = select_representative_candidates(
    bucket_key=bkey, eligible=..., aum=..., sub_category=..., underlying_index=...,
    bucket_weight=..., capital_krw=..., name=..., quadrant=..., fx_regime=...,
    sub_category_views=(tilt.sub_category_views.get(bkey) if bkey in HETEROGENEOUS_BUCKETS else None),
    momentum=momentum, min_etf_aum_krw=_dials.get("min_etf_aum_krw", 10e9),
)
```

### 이질 버킷 선택 (candidate_selector 이질 분기)
```
입력: sub_category_views(this bucket: sub_cat→pref) or None, momentum, min_etf_aum_krw
1. 배제:  sub_category_views[sc] < −τ 인 sub_cat ETF 제거
2. 유동성: aum[t] < min_etf_aum_krw 인 ETF 제거
3. 선호 좁힘: pref>+τ 인 sub_cat ETF가 ≥1개 있으면 그것만 후보로 (없으면 1·2 후 전체)
4. 랭크:  모멘텀 desc (post-cut 풀 z), tiebreak (−aum, ticker)   ← pref 하드티어 *없음*(모멘텀이 랭크, view는 풀만 좁힘)
5. dedup(_dedup) → minimal-N(=ceil(w/SINGLE_CAP)) 선정
fallback 우선순위(단일 결정론 체인):
   (a) 2의 floor가 *전부* 컷 → floor 무시하고 1·3·4 재실행 (미배분 회피 우선) → attribution.revert="floor_relaxed"
   (b) 1·3 후 풀 공백(전부 배제) → 기존 core-by-AUM → attribution.revert="core_aum"
가중: 기존 within_bucket.aum_weighted_allocation (minimal-N이라 단일 종목 cap까지)
```

### 집중 천장 (정정 — 핵심)
- **1차 binding = 카테고리 cap**: 반도체 집중은 해외주식_섹터 **10%** + 국내주식_섹터 **15%** + 해외주식_지수(필라델피아 단일 ≤20%) 로 *분산되어* 묶임. `repair_category_caps`(기존)가 강제. → 단일 테마 실현 집중 ≈ 카테고리 합산 상한.
- **2차 binding = 군집 25%**: 상관 반도체 군집 합 >25%면 **M5 cluster_repair**가 graceful 축소. (없으면 validator fail.)
- ⚠️ 따라서 **"단일 20%까지 몰빵"은 부정확** — 실현 반도체 집중은 카테고리 cap에 분산되고 군집 25%에서 천장. **그래도 현재 희석 AUM 대비 의미 있는 +집중**(plan §검증에서 정량화).

### repair clawback 분석 (필수 — plan에서 정량화)
fill→`_repair_all`(category+risk)→drop_negligible→`_repair_all`(2차). 카테고리 초과분이 *비례 축소*되어 집중이 일부 되돌아감. **plan Task에서 멜트업 스냅샷으로 concentrate→repair 후 *실현* 반도체 비중을 측정**해 실제 레버 크기를 문서화한다. (cross-bucket b2 nasdaq + b3 반도체 군집 합산 포함.)

## 8. 이질/동질 분류 근거

실측 sub_category 분산(2026-06-16): **이질** = b3(반도체/AI/2차전지/중국전기차), b5(일본/인도/베트남/유럽), b2(S&P vs 나스닥). **동질** = a1~a5·b1(broad 지배)·b4(전부 중국)·b6·b7·b8(4종목·floor미달)·b9.

## 9. 검증 (경량 백테스트 sanity)

`scripts/backtest_etf_selection.py` (신규):
- 이질 버킷에서 최근 구간 월간 재선택, **momentum-pick vs AUM-pick** net-of-cost(편도 10bps) 누적수익·Sharpe·MDD.
- **warm-up:** skip1m_mom_12m은 ~273거래일 필요 → 유효 백테스트 구간 = (가용 이력 − 273d). **최소 N개월(예 ≥24)** 확보돼야 GO/NO-GO 유효. **survivorship:** 신규 thematic ETF는 이력 짧음 → full-history ETF로 제한 또는 월별 coverage 보고.
- **GO:** momentum이 AUM 대비 수익/Sharpe 우위 AND MDD 열위 아님. b8은 단일종목이라 백테스트 제외.

## 10. 엣지 케이스 (단일 결정론)

| Case | Behavior |
|---|---|
| LLM sub_category_views 부재/실패 | 전 sub_cat 중립 → 배제/선호 없이 모멘텀 단독 |
| 비-이질 버킷 sub_category_views 키 | M3가 무시(+로그) — "동질 unchanged" 강제 |
| 모멘텀 전부 None(이력 부족) | 전부 −inf → (−aum,ticker) tiebreak = 사실상 AUM-pick. *별도 "or AUM fallback" 없음* |
| floor가 후보 전부 컷 | floor 무시 재실행(§7 fallback-a) + attribution 기록 |
| 선호/배제로 풀 공백 | core-by-AUM(§7 fallback-b) + attribution 기록 |
| 카테고리/위험 cap | repair_category_caps/risk_repair(기존) |
| 군집 25% cap | **M5 cluster_repair**(신규) graceful 축소 |

## 11. 테스트 전략

**Unit:** BucketTilt.sub_category_views(기본 빈·backward-compat); `_momentum_score`(z-mean·all-None→−inf); candidate_selector 이질 분기(배제·floor·선호좁힘·모멘텀랭크·minimal-N·fallback a/b·비-이질키 무시); cluster_repair(군집>25% 축소·=25% no-op·비-군집 water-fill); 동질 버킷 회귀(불변).
**Integration:** Step B 이질 b3(sub_category_views+모멘텀→반도체 선택→repair 후 실현비중), 동질 b1 불변, mandate 통과.
**적대적 감사 + 경량 백테스트(§9).**

## 12. 범위 / 리스크 (정직)

- **건드림:** BucketTilt(M1), trader_allocator(M2 프롬프트+배선), candidate_selector(M3 이질분기), cluster_repair(M5 신규), backtest 스크립트, 모멘텀 헬퍼.
- **안 건드림:** BL, 오버레이, 동질 버킷, taxonomy, Step A 비중, within_bucket(M4 취소).
- **리스크(정직):**
  1. **모멘텀 고점매수(blow-off):** 순수 모멘텀이 멜트업 꼭대기 종목을 삼. lowvol 가드 제거(의도). → 카테고리 cap(10-15%)이 단일종목 폭주를 *구조적으로* 제한하는 게 유일한 완충. plan에서 reversal/overbought 소프트 가드 *옵션* 검토.
  2. **실현 집중이 기대보다 작음:** 카테고리 cap·repair clawback으로 반도체 집중이 ~카테고리합~군집25% 천장. "20% 몰빵" 아님. plan에서 실측.
  3. **floor silent-revert:** 100억으로 낮췄고 revert를 attribution에 기록 → philosophy에 가시화.
  4. **LLM 테마 view 환각:** 배제(−)가 top-모멘텀 종목을 잘못 컷할 위험 → 배제는 |pref|>τ로 보수적, 모멘텀이 최종 랭크.
- **BL 연결:** sub_category_views = 통합 view 씨앗(§3.1, BL에서 재확인).
