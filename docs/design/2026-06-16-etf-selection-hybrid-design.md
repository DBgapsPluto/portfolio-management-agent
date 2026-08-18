# 개별 ETF 선택 — 하이브리드(LLM 테마 view + 위험조정 모멘텀) 설계

**Date:** 2026-06-16 (rev3 — self-imposed cap 발견 + A2/C2/D2 확정)
**Stage:** 3 (Portfolio allocation) — Step B (within-bucket ETF 선택·가중)
**Status:** 설계 확정 (rev3)
**Branch:** `rework/pipeline-methodology`

## 1. 배경 / 문제

Step A가 *버킷* 비중을 정한 뒤, 그 비중을 버킷 내 ETF에 배분한다. 현재(`candidate_selector`+`within_bucket`)는 **의도적으로 broad(core)를 AUM 순으로** 고르고 thematic(반도체·AI)을 배제(candidate_selector.py:5), 가중도 AUM. **AUM은 수익 신호가 아니다** → 이질 버킷(b3 = 반도체/AI/2차전지/중국전기차 한 버킷)에서 작동 테마를 laggard와 크기 비례로 희석. 3개월 top-30 수익 + 멜트업 환경에서 *개별 ETF 선택이 최대·최속 수익 레버인데 정반대*다.

## 2. 목표

> 이질 버킷의 within-bucket ETF 선택을 **하이브리드(LLM 테마 view로 sub_category 좁힘 → 위험조정 모멘텀 랭크 → top-K 분산 집중)**로 전환. 동질 버킷은 기존 AUM/core 유지. **BL과 별개로, BL보다 먼저** 구현. 집중은 *의도적·방어가능*하게(철학점수 보호).

비범위: BL allocator, daily overlay, 동질 버킷, 14-bucket taxonomy, Step A 비중.

## 3. mandate 현실 (rev3 핵심 — 반드시 인지)

**대회 §2.2 하드 규칙(컷오프):** 단일 ETF ≤20% · 위험자산 ≤70% · 회전율(80%/10%). **그게 전부.**

**self-imposed(대회 규칙 ❌ — 우리가 건 것):**
- 카테고리 cap(해외주식_섹터 10%·국내주식_섹터 15%·해외주식_지수 30%·…). *concentration_check.py:25 주석이 "대회 §2.2"라 했으나 오기 — 규칙에 없음.*
- 군집 cap(현재 25%). *대회 규칙엔 cluster cap 없음.*

**철학점수(70%) 평가항목:** 대회 규칙 line 77 — *"내부 상관관계 분석해 '단일 리스크(예: AI 쏠림)'를 통제했는가 집중 평가."* → **AI 집중은 하드 cap이 아니라 *철학점수로 심사*된다.** 따라서 집중은 *금지가 아니라*, *의도적·통제된 집중이면 방어 가능, 무통제 몰빵이면 감점.*

## 4. 확정 결정사항

| # | 항목 | 결정 |
|---|---|---|
| 1 | 선택 철학 | **하이브리드** — view로 테마 좁힘 → 위험조정 모멘텀 랭크 → top-K 분산 |
| 2 | view source | **Step-A 트레이더 LLM 출력 확장** — `BucketTilt.sub_category_views` (별도 콜 ❌, BL view 씨앗) |
| 3 | 신호 (**D2**) | **위험조정 모멘텀** = `z_mean(skip1m_mom_3/6/12m) − W_VOL·z(realized_vol_60d)`, post-cut 풀 cross-section. blow-off 종목 demote |
| 4 | 집중 천장 (**A2**) | **카테고리 cap 유지**(10/15%, repair_category_caps) + **군집 cap 25%→35% 완화**(self-imposed, cluster_repair M5로 graceful). 의도적 집중 + 철학 서사로 방어 |
| 5 | 선택·가중 (**C2**) | **top-K(기본 3) 위험조정모멘텀 선정 + 모멘텀 가중**(단일종목 위험 ↓, 테마내 분산 = 철학 유리). M4 부활(가중 의미 생김) |
| 6 | 이질 버킷 | **b2_dm_core · b3_global_tech · b5_other_intl** (b8 제외) |
| 7 | 동질 버킷 | a1~a5·b1·b4·b6·b7·b8·b9 → 기존 AUM/core (불변) |
| 8 | 유동성 floor | ETF AUM < `min_etf_aum_krw`(기본 100억) 컷, 컷·revert는 attribution 기록 |
| 9 | 검증 | 경량 백테스트 sanity (위험조정모멘텀 top-K vs AUM, warm-up 후 유효구간, net-of-cost) |
| 10 | 철학 방어 | 집중은 philosophy.md에 *의도적 AI 수퍼사이클 집중 + 통제(top-K 분산·위험조정·35% 군집상한)* 서사로 명시 → 70% 평가항목 직접 충족 |

## 5. 아키텍처 (전 → 후)

```
[후]  Step-A 트레이더 LLM (기존 1콜)
        BucketTilt: tilts + sub_category_views (이질 버킷만, M3가 비-이질 키 무시)
        │  (M2: node가 fp→risk_adj_momentum dict 구성 + tilt.sub_category_views 전달)
        ▼
      Step B, 버킷별:
        이질(b2/b3/b5): candidate_selector(이질 분기)
            배제(pref<−τ) → 유동성 floor → (선호 있으면 선호만) → 위험조정모멘텀 랭크
            → top-K(기본3, ≥n_floor) 선정
          within_bucket.momentum_weighted_allocation(M4): 위험조정모멘텀 비례 가중 + 20% cap
        동질: 기존 core-by-AUM (불변)
        │
        ▼
      _repair_all(기존): repair_category_caps(10/15%) + repair_risk_cap(70%)
      + cluster_repair(M5 신규): 군집 35% graceful 축소 (state['correlation_clusters'])
      → drop_negligible → _repair_all(2차) → 최종 ETF weights
```

## 6. 컴포넌트 (M1–M5)

| # | 파일 | 변경 |
|---|---|---|
| M1 | `schemas/portfolio.py` `BucketTilt` | `sub_category_views: dict[str, dict[str, float]] = Field(default_factory=dict)`. backward-compat |
| M2 | `agents/trader/trader_allocator.py` | (a) 프롬프트에 "이질 버킷(b2/b3/b5)만 sub_category 선호 출력" + 신호 테이블(§7). (b) call-site(line 215-220): `fp`(line 197)에서 `risk_adj_momentum` dict 구성, `sub_category_views=tilt.sub_category_views.get(bkey)`(bkey∈HET), `momentum=`, `min_etf_aum_krw=`, `top_k=` 추가. attribution(선택·revert·테마) 기록 |
| M3 | `skills/portfolio/candidate_selector.py` | 이질 분기(§7): keyword-only `sub_category_views=None, momentum=None, min_etf_aum_krw=None, top_k=None` (default → 동질·기존 caller·테스트 불변). 비-이질 키 무시 |
| M4 | `skills/portfolio/within_bucket.py` | `momentum_weighted_allocation(bucket_weights, selections, score, cap)` 신규 — score(위험조정모멘텀)를 **비-음수 가중으로 변환 후**(score는 z라 음수 가능 → 직접 비례 ❌; **softmax(score/T)** 또는 desc-rank 가중) 배분 + 20% cap water-fill(`_redistribute_single_cap` 재사용). 이질 버킷만; 동질은 `aum_weighted_allocation`. (T=온도 dial, 기본 1.0 — 작을수록 1등 집중) |
| M5 | `skills/mandate/cluster_repair.py`(신규)+`_repair_all` 배선 | 군집 `CLUSTER_CAP=0.35` graceful 축소. `state['correlation_clusters']`+weights → 군집합>35% 시 군집 내 비례 축소 + 비-군집/현금 water-fill. category/risk_repair 패턴. **correlation_check(validator) 임계도 0.35로 동기화** |

### 신규 상수/dial
```python
HETEROGENEOUS_BUCKETS = {"b2_dm_core", "b3_global_tech", "b5_other_intl"}
SUBCAT_PREF_THRESHOLD = 0.3        # |pref|>τ 일 때만 배제/선호
W_VOL = 0.4                        # 위험조정 모멘텀의 vol 페널티 가중 (dial, backtest 튜닝)
# portfolio_dials
min_etf_aum_krw = 10_000_000_000   # 100억
top_k_heterogeneous = 3            # 이질 버킷 선정 종목 수
# mandate
CLUSTER_CAP = 0.35                 # self-imposed (대회 규칙 아님). 25%→35% 완화 (A2)
```

## 7. 알고리즘 상세

### 위험조정 모멘텀 (M2 헬퍼)
```python
# 각 ticker p=fp.get(t). raw_mom=[p.skip1m_mom_3m/6m/12m] (None skip).
# post-cut 풀에서: mom_z = mean( _rank_normalize(skip1m_mom_{3,6,12}m) )
#                vol_z = _rank_normalize(realized_vol_60d)
# score = mom_z − W_VOL·vol_z      (전부 None → −inf, 버킷 비우지 않음)
# score_candidates는 mom/lowvol/qual/size blend라 재사용 ❌ — _zscore/_rank_normalize 프리미티브만 사용
```

### 이질 버킷 선택 (candidate_selector 이질 분기)
```
1. 배제: sub_category_views[sc] < −τ ETF 제거
2. 유동성: aum[t] < min_etf_aum_krw ETF 제거
3. 선호 좁힘: pref>+τ sub_cat ETF ≥1개면 그것만 (없으면 1·2 후 전체)
4. 랭크: 위험조정모멘텀 desc, tiebreak(−aum, t)
5. dedup → top max(n_floor, min(top_k, |pool|)) 선정
fallback(단일 체인): (a) floor가 전부 컷 → floor 무시 재실행, attribution.revert="floor_relaxed";
                     (b) 배제로 풀 공백 → core-by-AUM, attribution.revert="core_aum"
가중: within_bucket.momentum_weighted_allocation(score) + 20% cap
```

### 집중 천장 (정정 — §3 반영)
- **카테고리 cap(self-imposed, 유지)**: 반도체가 해외섹터 ≤10% + 국내섹터 ≤15% + 필라델피아(해외지수, ≤20% 단일)로 분산. `repair_category_caps` 강제.
- **군집 cap 35%(self-imposed, A2 완화)**: 상관 반도체 군집합 >35%면 **M5 cluster_repair** graceful 축소. → 실현 반도체 ≈ 카테고리합~군집35% 천장. **현재 희석 대비 의미 있는 +집중(~수%→~30%대), 단 "70% 몰빵" 아님.**
- **repair clawback 정량화(plan Task):** 멜트업 스냅샷으로 concentrate→repair 후 *실현* 반도체 비중 측정(cross-bucket b2+b3 군집 합산 포함) → 진짜 레버 크기 문서화.

## 8. 이질/동질 분류 (실측)

이질 = b3(반도체/AI/2차전지/중국전기차)·b5(일본/인도/베트남/유럽)·b2(S&P vs 나스닥). 동질 = a1~a5·b1(broad 지배)·b4(전부 중국)·b6·b7·b8(4종목·floor미달)·b9.

## 9. 검증 (경량 백테스트 sanity)

`scripts/backtest_etf_selection.py`: 이질 버킷에서 월간 재선택 **위험조정모멘텀 top-K vs AUM-top** net-of-cost(10bps) 누적수익·Sharpe·MDD. warm-up=~273거래일(skip1m_mom_12m) → 유효구간=(이력−273d), 최소 ≥24개월. survivorship: full-history ETF 제한 또는 월별 coverage 보고. b8 제외. **GO:** 위험조정모멘텀이 AUM 대비 수익/Sharpe 우위 AND MDD 열위 아님.

## 10. 엣지 케이스

| Case | Behavior |
|---|---|
| sub_category_views 부재/실패 | 전 sub_cat 중립 → 위험조정모멘텀 단독 |
| 비-이질 버킷 키 | M3 무시(+로그) |
| 모멘텀/vol 전부 None | score=−inf → (−aum,t) tiebreak = 사실상 AUM-pick |
| floor가 후보 전부 컷 | floor 무시 재실행(§7 a) + attribution |
| 선호/배제로 공백 | core-by-AUM(§7 b) + attribution |
| 카테고리/위험 cap | repair_category_caps/risk_repair(기존) |
| 군집 35% cap | M5 cluster_repair(신규) |
| top_k > pool | min(top_k, |pool|), ≥n_floor |

## 11. 테스트

**Unit:** BucketTilt.sub_category_views(backward-compat); risk_adj_momentum 헬퍼(z·vol페널티·all-None→−inf); candidate_selector 이질분기(배제·floor·선호·랭크·top-K·fallback a/b·비-이질키무시); momentum_weighted_allocation(비례·cap·minimal-N); cluster_repair(>35%축소·=35% no-op·water-fill); 동질 회귀(불변).
**Integration:** Step B 이질 b3(view+모멘텀→반도체 top-K→repair 후 실현비중·군집≤35%), 동질 b1 불변, mandate 통과.
**적대적 감사 + 경량 백테스트(§9).**

## 12. 범위 / 리스크 (정직)

- **건드림:** BucketTilt(M1)·trader_allocator(M2)·candidate_selector(M3)·within_bucket(M4 부활)·cluster_repair(M5 신규)·backtest·모멘텀 헬퍼. **correlation_check/concentration_check의 self-imposed cap 주석 정정(§3).**
- **안 건드림:** BL·오버레이·동질 버킷·taxonomy·Step A·카테고리 cap(유지).
- **리스크(정직):**
  1. **모멘텀 고점매수:** D2(위험조정)가 가장 변동성 큰 blow-off를 demote해 *부분* 완화. + C2(top-K 분산)로 단일종목 위험 ↓. + 카테고리 cap이 구조적 완충. 그래도 멜트업 반전 시 손실.
  2. **실현 집중이 기대보다 작음:** 카테고리 cap·repair로 반도체 ~30%대 천장(군집35%). "70% 몰빵" 아님 — plan에서 실측.
  3. **철학점수 trade-off:** 35% 군집 완화는 AI 쏠림 방향. **#10 의도적-통제 서사(분산·위험조정·35%상한)로 방어** — 무통제 몰빵(A4)이 아니므로 방어 가능하나, *완전 분산(A1)보다는 철학점수 양보*임을 인지.
  4. floor silent-revert: 100억+attribution 기록으로 가시화.
  5. LLM 테마 view 환각: 배제는 |pref|>τ 보수적, 모멘텀이 최종 랭크.
- **BL 연결:** sub_category_views = 통합 view 씨앗(§2, BL에서 재확인).
