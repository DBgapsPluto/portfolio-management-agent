# 개별 ETF 선택 — 하이브리드(LLM 테마 view + 모멘텀) 설계

**Date:** 2026-06-16
**Stage:** 3 (Portfolio allocation) — Step B (within-bucket ETF 선택·가중)
**Status:** 설계 승인됨 (구현 대기)
**Branch:** `rework/pipeline-methodology`

## 1. 배경 / 문제

BL/배분(Step A)이 *버킷* 비중을 정한 뒤, 그 비중을 버킷 안의 개별 ETF에 배분한다. 현재 이 단계(`candidate_selector` + `within_bucket`)는:

- **의도적으로 broad(core) sub_category를 AUM 순으로** 고르고 thematic(반도체·AI·2차전지)을 *배제*한다 (`candidate_selector.py:5` "regime-alpha/모멘텀/펀더멘털 미사용").
- 가중도 **AUM 비례** (`within_bucket.aum_weighted_allocation`).

문제: **AUM은 수익 신호가 아니다.** 이질 버킷(예: `b3_global_tech`은 반도체·AI·2차전지·중국전기차·테슬라가 한 버킷)에서 AUM 가중은 *작동 테마(반도체)를 laggard와 크기 비례로 희석*한다. 3개월 대회 수익률 top-30 목표 + 현재 IT/반도체 멜트업 환경에서, **개별 ETF 선택이 가장 큰(그리고 가장 빠른) 수익 레버인데 정반대로 작동 중**이다.

실측(2026-06-16): `b3_global_tech` 후보 — TIGER미국테크TOP10, KODEX반도체, 필라델피아반도체, AI반도체, 2차전지, 중국전기차, 테슬라밸류체인. 수익률이 정반대로 갈리는 그랩백.

## 2. 목표

> 이질 버킷의 within-bucket ETF 선택을 **하이브리드(LLM 테마 view로 sub_category 좁힘 → 모멘텀 가중 → mandate cap까지 집중)**로 전환한다. 동질 버킷은 기존 AUM/core 유지. **BL과 별개로, BL보다 먼저** 구현한다.

비범위: BL allocator(별도 spec), daily overlay 수정(별도 결정), 동질 버킷, 14-bucket taxonomy, Step A 버킷 비중.

## 3. 확정 결정사항

| # | 항목 | 결정 |
|---|---|---|
| 1 | 선택 철학 | **하이브리드** — view로 테마 좁힘 → 모멘텀 가중 |
| 2 | view source | **Step-A 트레이더 LLM 출력 확장** (별도 LLM 콜 ❌) — `BucketTilt`에 `sub_category_views` 추가 |
| 3 | 모멘텀 정의 | **순수 모멘텀** skip-1m 3/6/12m (`FactorPanel.skip1m_mom_*`). lowvol 포함 컴포짓 미사용(winner 깎음) |
| 4 | 집중 강도 | **mandate cap까지 풀로** (단일 20% / 군집 25%가 하드 천장, repair 강제) |
| 5 | 가중 방식 | **fill-from-top** (모멘텀 상위부터 cap까지 채움) |
| 6 | 이질 버킷 | **b2_dm_core · b3_global_tech · b5_other_intl · b8_cyclical_commodity** |
| 7 | 동질 버킷 | a1~a5 · b1_kr_equity · b4_china · b6 · b7 · b9 → 기존 AUM/core (변경 없음) |
| 8 | 유동성 floor | 이질 버킷에서 ETF AUM < `min_etf_aum_krw`(dial, 기본 500억) 컷 |
| 9 | 검증 | **경량 백테스트 sanity** (momentum-pick vs AUM-pick, ~2년, net-of-cost) — GO/NO-GO |
| 10 | 구현 순서 | ETF 선택 먼저 → BL 나중 |

### 3.1 핵심 — BL과의 통합 (sub_category_views = 통합 view의 씨앗)

theme view LLM과 (나중의) BL view LLM은 **같은 LLM 콜, 다른 granularity**다. 따라서 별도 콜을 만들지 않고 **Step-A 트레이더 LLM 출력을 확장**한다. LLM 콜이 진화한다:

```
지금(ETF):  BucketTilt(버킷 tilt)      + sub_category_views   ← 한 콜
나중(BL):   BucketView(버킷 BL view)   + sub_category_views   ← 같은 한 콜 (BL spec에서 교체)
```

`sub_category_views`(버킷 내 테마 선호)는 BL이 와도 *그대로 유지*된다. BL은 버킷-레벨만 교체. → LLM 콜 1개로 유지, 재작업 0.

## 4. 아키텍처 (전 → 후)

```
[전]  Step A LLM(BucketTilt: 버킷 tilt) → 버킷 비중
      Step B: candidate_selector(core sub_cat → AUM → dedup, minimal-N)
              within_bucket.aum_weighted_allocation → ETF weights

[후]  Step A LLM(BucketTilt: 버킷 tilt + sub_category_views[이질 버킷])
        │  sub_category_views = {bucket: {sub_category: pref ∈ [−1,+1]}}
        ▼
      Step B:
        이질 버킷(b2/b3/b5/b8):
          candidate_selector(확장):
             후보풀 = sub_category_views 배제(pref<−τ) 컷 → 유동성 floor → 선호(pref>+τ) 우선
             랭크   = 모멘텀(skip-1m 3/6/12m z)
             선정   = minimal-N (ceil(버킷비중/0.20)) 최상위
          within_bucket(확장): fill-from-top by 모멘텀 + 20% cap
        동질 버킷: 기존 그대로
        │
        ▼
      repair(기존): 카테고리·위험·군집 25% cap 강제 → 최종 ETF weights
```

## 5. 컴포넌트

### 수정 (M1–M4)

| # | 파일 | 변경 |
|---|---|---|
| M1 | `schemas/portfolio.py` `BucketTilt` | `sub_category_views: dict[str, dict[str, float]] = {}` 추가 (bucket→sub_cat→pref [−1,+1]). 기본 빈 dict → backward-compat |
| M2 | `agents/trader/trader_allocator.py` | `_STEP_A_SYSTEM`/`_step_a_prompt`에 "이질 버킷 sub_category 선호 출력" 지시 + 신호 테이블(아래 §6) 주입. node가 `sub_category_views`를 Step B(candidate_selector)로 전달. attribution 기록 |
| M3 | `skills/portfolio/candidate_selector.py` | `select_representative_candidates`에 이질-버킷 분기: `sub_category_views`·`momentum`·`min_etf_aum_krw` 인자 → 배제 컷 + 유동성 floor + 모멘텀 랭크. 동질 버킷은 기존 경로 |
| M4 | `skills/portfolio/within_bucket.py` | `fill_from_top_allocation(bucket_weights, selections, momentum, cap)` 신규 (모멘텀 상위부터 cap 채움). 이질 버킷에만 적용; 동질은 `aum_weighted_allocation` 유지 |

### 유지 (재활용)

`FactorPanel`(모멘텀 이미 계산, §6) · `CORE_SUBCATEGORIES`/`KNOWN_THEMATIC`(이질/동질 + sub_cat 매핑) · `within_bucket` cap water-fill · repair(category/risk/cluster) · `factor_scorer.score_candidates`(z-score 헬퍼 재활용 가능).

### 신규 상수/dial

```python
# candidate_selector.py (또는 config)
HETEROGENEOUS_BUCKETS: set[str] = {
    "b2_dm_core", "b3_global_tech", "b5_other_intl", "b8_cyclical_commodity",
}
SUBCAT_PREF_THRESHOLD: float = 0.3   # |pref|>τ 일 때만 선호/배제 작동, 그 외 중립
# portfolio_dials
min_etf_aum_krw: float = 50_000_000_000   # 500억 — 이질 버킷 유동성 floor
```

## 6. 데이터 / API 사실 (조사 확인)

### 모멘텀 — 이미 계산됨, 연결만
```python
# FactorPanel (factor_scorer.py:60-71) — Stage1 technical analyst가 ETF별 계산
skip1m_mom_3m / skip1m_mom_6m / skip1m_mom_12m : float | None   # Jegadeesh-Titman skip-1m
realized_vol_60d, sharpe_60d, log_aum
# allocator 접근: state["technical_report"].factor_panel[ticker]
#   (trader_allocator.py:197 이미 realized_vol_60d 소비 중 → mom_* 추가 소비만 하면 됨)
```
모멘텀 score = `skip1m_mom_{3,6,12}m`의 z-score 평균(풀 내 cross-sectional). `factor_scorer`의 z-score/blend 헬퍼 재활용 가능(단 본 설계는 mom-only — lowvol/quality/size 미사용).

### sub_category 신호 테이블 (theme view LLM 입력)
이질 버킷별로 — sub_category마다 `(평균 모멘텀, 종목수, 대표 ETF명)` + macro_news `ThemeTag`(ai_semis·ev_battery 등) + Stage-1 요약 텍스트. *BL의 미구현 N2 집계에 의존하지 않는다 — factor_panel + universe sub_category로 자체 경량 집계.*

### 선택/가중 인프라
- `candidate_selector.select_representative_candidates(...)` (candidate_selector.py:111) — core-by-AUM. 이질 분기 추가.
- `within_bucket.aum_weighted_allocation` / `_allocate_one_bucket` (within_bucket.py:53,18) — AUM 비례 + 20% cap. minimal-N이라 12% 버킷 → 1종목 12%.
- `n_floor = ceil(bucket_weight/0.20)` (candidate_selector.py:179) — 이미 최소 종목수.

## 7. 알고리즘 상세

### 이질 버킷 선택 (candidate_selector 확장)
```
입력: bucket_key, eligible[], aum, sub_category, momentum(ticker→score),
      sub_category_views(this bucket: sub_cat→pref), min_etf_aum_krw
1. 배제: sub_category_views[sc] < −τ 인 sub_cat 의 ETF 제거
2. 유동성 floor: aum[t] < min_etf_aum_krw 인 ETF 제거
3. 선호 우선 + 모멘텀 랭크:
     key = (−1 if sub_category_views.get(sc,0) > +τ else 0,   # 선호 sub_cat 먼저
            −momentum.get(t, −inf),                            # 그 안에서 모멘텀
            −aum.get(t,0), t)                                  # tiebreak
4. index dedup(기존 _dedup) 후 minimal-N(=ceil(w/0.20)) 선정
5. 후보 공백(전부 배제/floor 컷) → 기존 core-by-AUM 으로 fallback
```

### 이질 버킷 가중 (within_bucket.fill_from_top_allocation)
```
selected = 모멘텀 desc 정렬
budget = bucket_weight
for t in selected:  w[t] = min(SINGLE_CAP, budget);  budget −= w[t]
# 잔여 budget > 0 (전부 cap) → InfeasibleBucket (n_floor 보장상 발생 안 함)
```
→ 최고 모멘텀 ETF에 cap까지 집중. 예: b3 12% → 반도체 12% (1종목).

### 집중 천장
단일 20% + **군집 25%**는 repair(기존)가 하드 강제. 반도체 군집이 포트 전체 25% 초과 시 repair가 깎음 = "cap full"의 상한.

## 8. 이질/동질 분류 근거

실측 sub_category 분산(2026-06-16):
- **이질**: b3(semiconductor/ai_robotics/battery_ev/china-ev), b5(japan/india/vietnam/europe), b2(us_broad vs us_tech_nasdaq), b8(oil/agri/materials).
- **동질**: a1~a5(현금·채권·금 대체재), b1(index_broad 지배 — 삼성그룹/조선 thematic은 소수), b4(전부 china), b6(dividend/value), b7(thematic_other only), b9(us_high_yield only).
- b1은 borderline(broad 지배) → 초기 동질, 추후 재검토.

## 9. 검증 (경량 백테스트 sanity — GO/NO-GO)

`scripts/backtest_etf_selection.py` (신규):
- 각 이질 버킷에서, 최근 ~2년 월간 재선택으로 **momentum-top ETF vs AUM-top ETF**의 net-of-cost(편도 10bps) 월수익 시계열 비교.
- 산출: 누적수익·Sharpe·MDD. **momentum이 AUM 대비 우위(수익/Sharpe) AND MDD 열위 아님** → GO. 아니면 설계 재고(예: 모멘텀 horizon 조정).
- LLM theme view는 백테스트 불가(LLM) → backtest는 *모멘텀 골격*만 검증(LLM view는 live 적용). 이는 의도된 한계로 문서화.

## 10. 엣지 케이스

| Case | Behavior |
|---|---|
| LLM `sub_category_views` 부재/실패 | 전 sub_cat 중립 → 모멘텀 단독 선택(배제/선호 없이) |
| 모멘텀 데이터 없음(신규 ETF, factor_panel None) | 해당 ETF 모멘텀 −inf 취급(후순위) 또는 AUM fallback |
| 선호풀 공백(전부 배제 or floor 컷) | 기존 core-by-AUM fallback (버킷 비우지 않음) |
| 유동성 floor가 후보 전부 컷 | floor 무시하고 모멘텀 랭크(거래성보다 미배분 회피 우선) |
| 동질 버킷 | 기존 경로 그대로 (분기 안 탐) |
| mandate cap | repair가 하드 강제 (단일/군집/카테고리) |

## 11. 테스트 전략

**Unit:**
- `BucketTilt.sub_category_views` 스키마(기본 빈 dict, backward-compat).
- candidate_selector 이질 분기: 배제 컷·유동성 floor·모멘텀 랭크·minimal-N·fallback 4종.
- `within_bucket.fill_from_top_allocation`: cap 채움·잔여·minimal-N.
- 동질 버킷 회귀(기존 core-by-AUM 불변).

**Integration:** Step B 전체(이질 b3에 sub_category_views + 모멘텀 → 반도체 집중, 동질 b1 불변), mandate 통과.

**적대적 감사:** 변경 후 적대적 워크플로 검증(코드변경 정책). + 경량 백테스트(§9).

## 12. 범위 / BL과의 관계 (재확인)

- **건드림:** BucketTilt 스키마, trader_allocator Step-A 프롬프트+Step-B 배선, candidate_selector(이질 분기), within_bucket(fill-from-top), 신규 backtest 스크립트.
- **안 건드림:** BL(별도 spec), 오버레이, 동질 버킷 로직, 14-bucket taxonomy, Step A 버킷 비중 산출.
- **BL 연결:** `sub_category_views`는 BL이 흡수할 통합 LLM view의 씨앗(§3.1). BL spec에서 버킷-레벨 view만 추가/교체.
